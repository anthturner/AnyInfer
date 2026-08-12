"""Routing and dispatch for the embedding and reranking operations.

Generation's `_route_events` machinery is deeply specialized — schema repair, cache marks,
content-filter redirect, arena fan-out — none of which embeddings or reranking need. This
module reuses the same lower-level primitives generation is built on (`Route`, `Retry`,
`HealthCache`, `resolve_target`, `backoff_delay`, the telemetry event types) rather than
threading two new operations through machinery built for a third.

Embedding routing carries one safety rule generation does not need: cross-target fallback is
refused unless both targets are asserted compatible, because a wrong-but-plausible vector is
a worse failure than an ordinary provider error. Reranking gets ordinary fallback.
"""

from __future__ import annotations

import asyncio
import functools
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, TypeVar

from ..errors import AllTargetsFailedError, ConfigError, ProviderError
from ..events.telemetry import (
    AttemptStarted,
    FallbackTriggered,
    RequestCompleted,
    RequestFailed,
    RequestStarted,
    RetryScheduled,
    TargetResolved,
)
from ..providers.base import (
    EmbeddingWireRequest,
    EmbeddingWireResult,
    EmbedsText,
    ReranksText,
    RerankWireDocument,
    RerankWireRequest,
    RerankWireResult,
)
from ..routing.health import HealthCache
from ..routing.policy import Route, backoff_delay
from ..types.operations import (
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingSpace,
    EmbeddingVector,
    RankedItem,
    RerankRequest,
    RerankResult,
)
from ..types.requests import ResolvedTarget, Target
from ..types.results import AttemptRecord, Timing, Usage

if TYPE_CHECKING:
    from ..catalog.model import Catalog
    from ..events.telemetry import TelemetryEvent
    from ..registry import ProviderRegistry
    from .providers import AdapterPool

    EmitFn = Callable[[TelemetryEvent], None]

__all__ = ["dispatch_embed", "dispatch_rerank"]

_WireResultT = TypeVar("_WireResultT")


def _resolve(
    target: Target,
    *,
    registry: ProviderRegistry,
    catalog: Catalog | None,
    configured_providers: Sequence[str],
) -> ResolvedTarget:
    from ..catalog.resolve import resolve_target

    return resolve_target(
        target,
        registry=registry,
        catalog=catalog,
        configured_providers=configured_providers,
    )


async def _attempt_with_retry(
    *,
    resolved: ResolvedTarget,
    route: Route,
    request_id: str,
    emit: EmitFn,
    call: Callable[[], Awaitable[tuple[_WireResultT, Timing]]],
) -> tuple[_WireResultT, Timing, list[AttemptRecord]]:
    """Run one target's retry loop. Returns the wire result, its timing, and attempt log.

    Raises the last `ProviderError` once the target's retry budget is spent. The retry
    policy guarantees at least one attempt (``max_attempts >= 1`` is not itself enforced
    here — a policy with zero attempts is a caller error the loop below turns into an
    immediate `ConfigError` rather than ever silently returning nothing).
    """
    attempts: list[AttemptRecord] = []
    attempt_number = 0
    while attempt_number < route.retry.max_attempts:
        attempt_number += 1
        emit(AttemptStarted(request_id=request_id, target=resolved, attempt_number=attempt_number))
        started = time.monotonic()
        try:
            wire_result, timing = await call()
        except ProviderError as exc:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            timing = Timing(started_at=started, total_ms=elapsed_ms)
            error_info = exc.snapshot()
            attempts.append(
                AttemptRecord(target=resolved, outcome="failed", error=error_info, timing=timing)
            )
            if attempt_number >= route.retry.max_attempts or not route.retry.should_retry(exc):
                raise
            delay = backoff_delay(attempt_number, route.retry, retry_after_s=exc.retry_after_s)
            emit(
                RetryScheduled(
                    request_id=request_id,
                    target=resolved,
                    attempt_number=attempt_number,
                    delay_s=delay,
                    error=error_info,
                )
            )
            attempts[-1] = AttemptRecord(
                target=resolved, outcome="retried", error=error_info, timing=timing
            )
            await asyncio.sleep(delay)
            continue
        else:
            attempts.append(AttemptRecord(target=resolved, outcome="ok", timing=timing))
            return wire_result, timing, attempts
    raise ConfigError(
        "retry policy allows zero attempts",
        hint="Retry.max_attempts must be at least 1",
    )


def _same_space_target(candidate: ResolvedTarget, primary: ResolvedTarget) -> bool:
    """Whether two resolved targets are provably the same embedding space before dispatch.

    Before a response exists, the only equivalence AnyInfer can prove is the identical
    provider and model — a caller-asserted compatibility id lives on `EmbeddingSpace`,
    which is built from the response. Trusted per-target compatibility ids from
    config/catalog are future work; until then anything else is a guess, and a guessed
    equivalence is exactly what the embedding-space safety rule exists to refuse.
    """
    return candidate.provider_id == primary.provider_id and candidate.model == primary.model


async def dispatch_embed(
    request: EmbeddingRequest,
    route: Route,
    *,
    pool: AdapterPool,
    registry: ProviderRegistry,
    catalog: Catalog | None,
    configured_providers: Sequence[str],
    health: HealthCache,
    emit: EmitFn,
    retain_raw: bool,
) -> EmbeddingResult:
    """Route and dispatch one embedding request, honoring the embedding-space safety rule.

    Raises:
        anyinfer.errors.AllTargetsFailedError: Every target in the route failed.
        anyinfer.errors.ConfigError: The expected embedding space was declared and the
            resolved target's space does not match it, or a fallback target cannot be
            proven to share the route's primary target's embedding space and
            ``allow_incompatible_fallback`` was not set.
    """
    request_id = uuid.uuid4().hex
    emit(RequestStarted(request_id=request_id, targets=route.targets))
    all_attempts: list[AttemptRecord] = []
    warnings: list[str] = []
    primary: ResolvedTarget | None = None
    last_error: ProviderError | None = None

    for position, target in enumerate(route.targets):
        resolved = _resolve(
            target, registry=registry, catalog=catalog, configured_providers=configured_providers
        )
        emit(TargetResolved(request_id=request_id, target=resolved))
        if primary is None:
            primary = resolved

        if route.health_gate and health.recently_failed(resolved, route.health_ttl_s):
            all_attempts.append(AttemptRecord(target=resolved, outcome="skipped_unhealthy"))
            continue

        if not _same_space_target(resolved, primary) and not request.allow_incompatible_fallback:
            raise ConfigError(
                f"embedding fallback to {resolved} refused: it cannot be proven to share "
                f"an embedding space with the route's primary target {primary}",
                provider=resolved.provider_id,
                hint=(
                    "vectors from a different embedding space fail silently when compared; "
                    "keep embedding routes on one provider:model, or set "
                    "allow_incompatible_fallback=True to accept incomparable vectors"
                ),
            )

        adapter = await pool.get(resolved.provider_id)
        if not isinstance(adapter, EmbedsText):
            raise ConfigError(
                f"provider {resolved.provider_id!r} does not support embedding",
                provider=resolved.provider_id,
                hint="choose a target whose provider declares the 'embedding' operation",
            )

        embed_call = functools.partial(_call_embed, adapter, resolved, request)
        try:
            wire_result, timing, attempts = await _attempt_with_retry(
                resolved=resolved,
                route=route,
                request_id=request_id,
                emit=emit,
                call=embed_call,
            )
        except ProviderError as exc:
            health.mark_failed(resolved, exc.detail)
            all_attempts.extend(_pending_attempts(resolved, exc))
            last_error = exc
            if position + 1 < len(route.targets):
                emit(
                    FallbackTriggered(
                        request_id=request_id,
                        from_target=resolved,
                        to_target=route.targets[position + 1],
                        error=exc.snapshot(),
                    )
                )
            continue

        health.mark_healthy(resolved)
        all_attempts.extend(attempts)

        space = _build_space(resolved, request, wire_result)
        if request.expected_space is not None and not space.compatible_with(
            request.expected_space
        ):
            raise ConfigError(
                f"embedding response from {resolved} does not match the expected "
                "embedding space",
                provider=resolved.provider_id,
                hint=(
                    "the resolved target produced a different vector space than "
                    "expected_space asserted; verify the target or drop expected_space"
                ),
            )
        if primary is not None and not _same_space_target(resolved, primary):
            warnings.append(
                f"embedding fallback served by {resolved} could not be proven compatible "
                f"with the route's primary target {primary}; these vectors are not safely "
                "comparable with vectors from that target"
            )

        vectors = tuple(EmbeddingVector(values=v) for v in wire_result.vectors)
        if len(vectors) != len(request.inputs):
            raise ConfigError(
                f"provider {resolved.provider_id!r} returned {len(vectors)} vectors for "
                f"{len(request.inputs)} inputs",
                provider=resolved.provider_id,
                hint="this is a provider-side contract violation; report it upstream",
            )

        usage = wire_result.usage or Usage()
        emit(RequestCompleted(request_id=request_id, target=resolved, usage=usage, timing=timing))
        return EmbeddingResult(
            vectors=vectors,
            target=resolved,
            space=space,
            usage=usage,
            timing=timing,
            attempts=tuple(all_attempts),
            warnings=tuple(warnings),
            raw=wire_result.raw if retain_raw else None,
        )

    error_info = last_error.snapshot() if last_error is not None else None
    if error_info is not None:
        emit(RequestFailed(request_id=request_id, error=error_info))
    raise AllTargetsFailedError(attempts=tuple(all_attempts))


async def dispatch_rerank(
    request: RerankRequest,
    route: Route,
    *,
    pool: AdapterPool,
    registry: ProviderRegistry,
    catalog: Catalog | None,
    configured_providers: Sequence[str],
    health: HealthCache,
    emit: EmitFn,
    retain_raw: bool,
) -> RerankResult:
    """Route and dispatch one rerank request.

    Raises:
        anyinfer.errors.AllTargetsFailedError: Every target in the route failed.
        anyinfer.errors.ConfigError: A provider returned a malformed ranking (out-of-range
            or duplicate document indexes).
    """
    request_id = uuid.uuid4().hex
    emit(RequestStarted(request_id=request_id, targets=route.targets))
    all_attempts: list[AttemptRecord] = []
    last_error: ProviderError | None = None

    for position, target in enumerate(route.targets):
        resolved = _resolve(
            target, registry=registry, catalog=catalog, configured_providers=configured_providers
        )
        emit(TargetResolved(request_id=request_id, target=resolved))

        if route.health_gate and health.recently_failed(resolved, route.health_ttl_s):
            all_attempts.append(AttemptRecord(target=resolved, outcome="skipped_unhealthy"))
            continue

        adapter = await pool.get(resolved.provider_id)
        if not isinstance(adapter, ReranksText):
            raise ConfigError(
                f"provider {resolved.provider_id!r} does not support reranking",
                provider=resolved.provider_id,
                hint="choose a target whose provider declares the 'rerank' operation",
            )

        rerank_call = functools.partial(_call_rerank, adapter, resolved, request)
        try:
            wire_result, timing, attempts = await _attempt_with_retry(
                resolved=resolved,
                route=route,
                request_id=request_id,
                emit=emit,
                call=rerank_call,
            )
        except ProviderError as exc:
            health.mark_failed(resolved, exc.detail)
            all_attempts.extend(_pending_attempts(resolved, exc))
            last_error = exc
            if position + 1 < len(route.targets):
                emit(
                    FallbackTriggered(
                        request_id=request_id,
                        from_target=resolved,
                        to_target=route.targets[position + 1],
                        error=exc.snapshot(),
                    )
                )
            continue

        health.mark_healthy(resolved)
        all_attempts.extend(attempts)

        items = _validate_ranked_items(resolved, request, wire_result)
        usage = wire_result.usage or Usage()
        emit(RequestCompleted(request_id=request_id, target=resolved, usage=usage, timing=timing))
        return RerankResult(
            items=items,
            target=resolved,
            usage=usage,
            timing=timing,
            attempts=tuple(all_attempts),
            raw=wire_result.raw if retain_raw else None,
        )

    error_info = last_error.snapshot() if last_error is not None else None
    if error_info is not None:
        emit(RequestFailed(request_id=request_id, error=error_info))
    raise AllTargetsFailedError(attempts=tuple(all_attempts))


def _pending_attempts(resolved: ResolvedTarget, exc: ProviderError) -> list[AttemptRecord]:
    """The final failed-attempt record for a target whose retry budget is spent."""
    return [AttemptRecord(target=resolved, outcome="failed", error=exc.snapshot())]


async def _call_embed(
    adapter: EmbedsText, resolved: ResolvedTarget, request: EmbeddingRequest
) -> tuple[EmbeddingWireResult, Timing]:
    wire_request = EmbeddingWireRequest(
        model=resolved.model,
        inputs=request.inputs,
        input_type=request.input_type,
        dimensions=request.dimensions,
        timeout_s=request.effective_timeout_s,
        max_response_bytes=request.max_response_bytes,
        extra_options=request.provider_options.get(resolved.provider_id, {}),
    )
    started = time.monotonic()
    result = await adapter.embed(wire_request)
    total_ms = (time.monotonic() - started) * 1000.0
    return result, Timing(started_at=started, total_ms=total_ms)


async def _call_rerank(
    adapter: ReranksText, resolved: ResolvedTarget, request: RerankRequest
) -> tuple[RerankWireResult, Timing]:
    wire_request = RerankWireRequest(
        model=resolved.model,
        query=request.query,
        documents=tuple(
            RerankWireDocument(index=i, text=doc.text) for i, doc in enumerate(request.documents)
        ),
        top_n=request.top_n,
        timeout_s=request.effective_timeout_s,
        max_response_bytes=request.max_response_bytes,
        extra_options=request.provider_options.get(resolved.provider_id, {}),
    )
    started = time.monotonic()
    result = await adapter.rerank(wire_request)
    total_ms = (time.monotonic() - started) * 1000.0
    return result, Timing(started_at=started, total_ms=total_ms)


def _build_space(
    resolved: ResolvedTarget, request: EmbeddingRequest, wire_result: EmbeddingWireResult
) -> EmbeddingSpace:
    dimensions = wire_result.dimensions
    if dimensions is None and wire_result.vectors:
        dimensions = len(wire_result.vectors[0])
    return EmbeddingSpace(
        provider_id=resolved.provider_id,
        model=wire_result.model or resolved.model,
        dimensions=dimensions,
        normalized=wire_result.normalized,
    )


def _validate_ranked_items(
    resolved: ResolvedTarget, request: RerankRequest, wire_result: RerankWireResult
) -> tuple[RankedItem, ...]:
    """Turn wire-reported indexes into `RankedItem`s, trusting nothing malformed.

    Raises:
        anyinfer.errors.ConfigError: The provider returned an out-of-range or duplicate
            document index. AnyInfer never guesses which document a malformed result meant.
    """
    doc_count = len(request.documents)
    seen: set[int] = set()
    items: list[RankedItem] = []
    for wire_item in wire_result.items:
        if not (0 <= wire_item.index < doc_count):
            raise ConfigError(
                f"provider {resolved.provider_id!r} returned an out-of-range document "
                f"index {wire_item.index} for a request with {doc_count} documents",
                provider=resolved.provider_id,
                hint="this is a provider-side contract violation; report it upstream",
            )
        if wire_item.index in seen:
            raise ConfigError(
                f"provider {resolved.provider_id!r} returned document index "
                f"{wire_item.index} more than once in one rerank result",
                provider=resolved.provider_id,
                hint="this is a provider-side contract violation; report it upstream",
            )
        seen.add(wire_item.index)
        document = request.documents[wire_item.index]
        items.append(
            RankedItem(
                index=wire_item.index,
                document_id=document.id,
                score=wire_item.score,
                text=document.text if request.return_documents else None,
            )
        )
    return tuple(items)
