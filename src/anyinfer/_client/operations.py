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
from typing import TYPE_CHECKING, Any, TypeVar, cast

from ..capabilities.pricing import with_operation_cost
from ..errors import AllTargetsFailedError, ConfigError, ProviderError
from ..events.telemetry import (
    AttemptCompleted,
    AttemptStarted,
    FallbackTriggered,
    RequestCompleted,
    RequestFailed,
    RequestStarted,
    RetryScheduled,
    TargetResolved,
)
from ..manifest import build_operation_manifest
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
    DEFAULT_MAX_DOCUMENTS,
    DEFAULT_MAX_EMBEDDING_INPUTS,
    BatchFailure,
    BatchPolicy,
    EmbeddingCapabilities,
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingSpace,
    EmbeddingVector,
    RankedItem,
    RerankDocument,
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
_BatchOutcomeT = TypeVar("_BatchOutcomeT")


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
            # Both wire-result types carry `usage`; the retry loop is generic over them,
            # so the attribute is read dynamically. Embed/rerank attempts always finish
            # with the normalized "stop" — there is no other way for one to end well.
            usage = getattr(wire_result, "usage", None) or Usage()
            emit(
                AttemptCompleted(
                    request_id=request_id,
                    target=resolved,
                    usage=usage,
                    timing=timing,
                    finish_reason="stop",
                )
            )
            return wire_result, timing, attempts
    raise ConfigError(
        "retry policy allows zero attempts",
        hint="Retry.max_attempts must be at least 1",
    )


def _effective_batch_limit(policy: BatchPolicy, declared: int | None) -> int | None:
    """The per-call item limit that applies: caller override, else verified capability.

    ``None`` means no limit is known — and an unknown limit is never guessed
    (DESIGN.md §28): the request goes out as one call if it is under the sanity
    ceiling, and is refused locally otherwise.
    """
    if policy.max_items_override is not None:
        return policy.max_items_override
    return declared


def _plan_chunks(
    *,
    item_count: int,
    limit: int | None,
    default_ceiling: int,
    provider_id: str,
    unit: str,
) -> list[slice] | None:
    """Decide how a request is dispatched against the resolved limit.

    Returns ``None`` for a single unsplit call, or the ordered chunk slices when the
    request exceeds a known limit — permission to actually split is the caller's check,
    since embedding and reranking gate it differently.

    Raises:
        anyinfer.errors.ConfigError: The limit is unknown and the request exceeds the
            sanity ceiling; splitting it would require inventing a provider maximum.
    """
    if limit is None:
        if item_count > default_ceiling:
            raise ConfigError(
                f"{unit} count {item_count} exceeds the sanity ceiling of "
                f"{default_ceiling} and provider {provider_id!r} declares no verified "
                "batch limit",
                provider=provider_id,
                hint=(
                    "AnyInfer never guesses a provider maximum; set "
                    "BatchPolicy.max_items_override to a limit you have verified, or use "
                    "a target whose descriptor declares one"
                ),
            )
        return None
    if item_count <= limit:
        return None
    return [slice(start, min(start + limit, item_count)) for start in range(0, item_count, limit)]


async def _run_bounded(
    thunks: Sequence[Callable[[], Awaitable[_BatchOutcomeT]]],
    *,
    max_concurrency: int,
) -> list[_BatchOutcomeT | BaseException]:
    """Run chunk dispatches with bounded concurrency, collecting every outcome.

    Results come back in submission order regardless of completion order, which is what
    makes downstream order preservation trivial. Exceptions are collected rather than
    raised so the caller can report every chunk's outcome (all-or-error, ER-style),
    not just the first failure's.
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _bounded(thunk: Callable[[], Awaitable[_BatchOutcomeT]]) -> _BatchOutcomeT:
        async with semaphore:
            return await thunk()

    return await asyncio.gather(*(_bounded(t) for t in thunks), return_exceptions=True)


def _batch_failure_report(
    resolved: ResolvedTarget,
    outcomes: Sequence[object],
    chunk_sizes: Sequence[int],
    all_attempts: list[AttemptRecord],
    *,
    emit: EmitFn,
    request_id: str,
    health: HealthCache,
) -> AllTargetsFailedError:
    """Build the all-or-error failure for a split request with at least one failed chunk.

    Successful chunks are recorded too — their spend already happened and hiding it
    would understate what the failure cost.
    """
    batch_failures: list[BatchFailure] = []
    first_error: ProviderError | None = None
    for index, outcome in enumerate(outcomes):
        if isinstance(outcome, ProviderError):
            first_error = first_error or outcome
            all_attempts.extend(_pending_attempts(resolved, outcome))
            batch_failures.append(
                BatchFailure(
                    batch_index=index,
                    item_count=chunk_sizes[index],
                    succeeded=False,
                    error=outcome.detail,
                )
            )
        else:
            success = cast("tuple[object, Timing, list[AttemptRecord]]", outcome)
            all_attempts.extend(success[2])
            batch_failures.append(
                BatchFailure(batch_index=index, item_count=chunk_sizes[index], succeeded=True)
            )
    if first_error is None:  # pragma: no cover — caller guarantees a failed chunk
        raise RuntimeError("batch failure report built with no failed chunk")
    health.mark_failed(resolved, first_error.detail)
    emit(RequestFailed(request_id=request_id, error=first_error.snapshot()))
    failed = sum(1 for b in batch_failures if not b.succeeded)
    return AllTargetsFailedError(
        f"{failed} of {len(batch_failures)} internal batches failed for {resolved}",
        attempts=tuple(all_attempts),
        batch_failures=tuple(batch_failures),
        hint=(
            "batched requests are all-or-error; batch_failures records every chunk's "
            "outcome, including the spend of the ones that succeeded"
        ),
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
    manifest: bool = False,
    anyinfer_version: str = "",
    capabilities_for: Callable[[ResolvedTarget], Any] | None = None,
    embedding_capabilities_for: Callable[[ResolvedTarget], EmbeddingCapabilities | None]
    | None = None,
    request_id: str | None = None,
) -> EmbeddingResult:
    """Route and dispatch one embedding request, honoring the embedding-space safety rule.

    Raises:
        anyinfer.errors.AllTargetsFailedError: Every target in the route failed.
        anyinfer.errors.ConfigError: The expected embedding space was declared and the
            resolved target's space does not match it, or a fallback target cannot be
            proven to share the route's primary target's embedding space and
            ``allow_incompatible_fallback`` was not set.
    """
    request_id = request_id or uuid.uuid4().hex
    emit(RequestStarted(request_id=request_id, targets=route.targets, operation="embedding"))
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
        # Declared operations are the authoritative gate: a structurally-present method
        # on an adapter that never declared the operation is not an offer to serve it.
        if (
            "embedding" not in registry.get(resolved.provider_id).operations
            or not isinstance(adapter, EmbedsText)
        ):
            raise ConfigError(
                f"provider {resolved.provider_id!r} does not support embedding",
                provider=resolved.provider_id,
                hint="choose a target whose provider declares the 'embedding' operation",
            )

        declared = (
            embedding_capabilities_for(resolved)
            if embedding_capabilities_for is not None
            else registry.get(resolved.provider_id).static_embedding_capabilities.get(
                resolved.model, None
            )
        )
        limit = _effective_batch_limit(
            request.batch, declared.max_batch_inputs if declared is not None else None
        )
        if request.input_type is not None and declared is not None:
            # `input_intents` is declared-empty when the model verifiably has no intent
            # concept (the field's documented semantics) — the caller's intent silently
            # doing nothing is exactly the degradation that must be recorded, not hidden.
            if declared.input_intents == ():
                warnings.append(
                    f"{resolved} does not distinguish embedding input intents; "
                    f"input_type={request.input_type!r} has no effect on this target"
                )
            elif request.input_type not in declared.input_intents:
                warnings.append(
                    f"{resolved} does not support input_type={request.input_type!r} "
                    f"(supported: {', '.join(declared.input_intents)}); the provider's "
                    "own handling applies"
                )
        chunks = _plan_chunks(
            item_count=len(request.inputs),
            limit=limit,
            default_ceiling=DEFAULT_MAX_EMBEDDING_INPUTS,
            provider_id=resolved.provider_id,
            unit="embedding input",
        )
        if chunks is not None and not request.batch.allow_split:
            raise ConfigError(
                f"embedding input count {len(request.inputs)} exceeds the resolved batch "
                f"limit of {limit} and BatchPolicy.allow_split is False",
                provider=resolved.provider_id,
                hint="reduce the request, raise the verified limit override, or allow splitting",
            )

        if chunks is None:
            embed_call = functools.partial(_call_embed, adapter, resolved, request, request.inputs)
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
            wire_results = [wire_result]
            total_timing = timing
        else:
            chunk_inputs = [request.inputs[s] for s in chunks]
            batch_started = time.monotonic()
            outcomes = await _run_bounded(
                [
                    functools.partial(
                        _attempt_with_retry,
                        resolved=resolved,
                        route=route,
                        request_id=request_id,
                        emit=emit,
                        call=functools.partial(_call_embed, adapter, resolved, request, inputs),
                    )
                    for inputs in chunk_inputs
                ],
                max_concurrency=request.batch.max_concurrency,
            )
            for outcome in outcomes:
                if isinstance(outcome, BaseException) and not isinstance(outcome, ProviderError):
                    raise outcome
            if any(isinstance(outcome, ProviderError) for outcome in outcomes):
                # All-or-error: a partially embedded batch is never a result (ER.4.4).
                # No cross-target fallback either — re-running the succeeded chunks on
                # another target would double their spend invisibly.
                raise _batch_failure_report(
                    resolved,
                    outcomes,
                    [len(inputs) for inputs in chunk_inputs],
                    all_attempts,
                    emit=emit,
                    request_id=request_id,
                    health=health,
                )
            health.mark_healthy(resolved)
            wire_results = []
            for chunk_index, outcome in enumerate(outcomes):
                if isinstance(outcome, BaseException):  # pragma: no cover — excluded above
                    raise outcome
                chunk_wire, _chunk_timing, chunk_attempts = outcome
                all_attempts.extend(chunk_attempts)
                if len(chunk_wire.vectors) != len(chunk_inputs[chunk_index]):
                    raise ConfigError(
                        f"provider {resolved.provider_id!r} returned "
                        f"{len(chunk_wire.vectors)} vectors for a batch of "
                        f"{len(chunk_inputs[chunk_index])} inputs",
                        provider=resolved.provider_id,
                        hint="this is a provider-side contract violation; report it upstream",
                    )
                wire_results.append(chunk_wire)
            total_timing = Timing(
                started_at=batch_started,
                total_ms=(time.monotonic() - batch_started) * 1000.0,
            )

        space = _build_space(resolved, request, wire_results[0])
        for later in wire_results[1:]:
            later_space = _build_space(resolved, request, later)
            if later_space != space:
                raise ConfigError(
                    f"provider {resolved.provider_id!r} reported inconsistent embedding "
                    "spaces across the internal batches of one request",
                    provider=resolved.provider_id,
                    hint="this is a provider-side contract violation; report it upstream",
                )
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

        vectors = tuple(
            EmbeddingVector(values=v) for wire in wire_results for v in wire.vectors
        )
        if len(vectors) != len(request.inputs):
            raise ConfigError(
                f"provider {resolved.provider_id!r} returned {len(vectors)} vectors for "
                f"{len(request.inputs)} inputs",
                provider=resolved.provider_id,
                hint="this is a provider-side contract violation; report it upstream",
            )
        if vectors and any(len(v) != len(vectors[0]) for v in vectors):
            # A ragged response is not "variable dimensions"; it is a malformed result —
            # every vector in one space has one length, and guessing which length was
            # meant would corrupt whatever index these vectors land in.
            raise ConfigError(
                f"provider {resolved.provider_id!r} returned vectors of inconsistent "
                "dimensions in one response",
                provider=resolved.provider_id,
                hint="this is a provider-side contract violation; report it upstream",
            )

        usage = Usage.sum([wire.usage or Usage() for wire in wire_results])
        if capabilities_for is not None:
            usage = with_operation_cost(usage, capabilities_for(resolved), "embedding")
        emit(
            RequestCompleted(
                request_id=request_id, target=resolved, usage=usage, timing=total_timing
            )
        )
        raw: object | None = None
        if retain_raw:
            raw = wire_results[0].raw if len(wire_results) == 1 else tuple(
                wire.raw for wire in wire_results
            )
        return EmbeddingResult(
            vectors=vectors,
            target=resolved,
            space=space,
            usage=usage,
            timing=total_timing,
            attempts=tuple(all_attempts),
            warnings=tuple(warnings),
            raw=raw,
            manifest=build_operation_manifest(
                operation="embedding",
                request_id=request_id,
                requested_targets=route.targets,
                resolved=resolved,
                attempts=all_attempts,
                usage=usage,
                timing=total_timing,
                warnings=warnings,
                embedding_space=space,
                anyinfer_version=anyinfer_version,
            )
            if manifest
            else None,
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
    manifest: bool = False,
    anyinfer_version: str = "",
    capabilities_for: Callable[[ResolvedTarget], Any] | None = None,
    request_id: str | None = None,
) -> RerankResult:
    """Route and dispatch one rerank request.

    Raises:
        anyinfer.errors.AllTargetsFailedError: Every target in the route failed.
        anyinfer.errors.ConfigError: A provider returned a malformed ranking (out-of-range
            or duplicate document indexes).
    """
    request_id = request_id or uuid.uuid4().hex
    emit(RequestStarted(request_id=request_id, targets=route.targets, operation="rerank"))
    all_attempts: list[AttemptRecord] = []
    warnings: list[str] = []
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
        if (
            "rerank" not in registry.get(resolved.provider_id).operations
            or not isinstance(adapter, ReranksText)
        ):
            raise ConfigError(
                f"provider {resolved.provider_id!r} does not support reranking",
                provider=resolved.provider_id,
                hint="choose a target whose provider declares the 'rerank' operation",
            )

        declared = (
            registry.get(resolved.provider_id)
            .static_rerank_capabilities.get(resolved.model, None)
        )
        limit = _effective_batch_limit(
            request.batch, declared.max_documents if declared is not None else None
        )
        chunks = _plan_chunks(
            item_count=len(request.documents),
            limit=limit,
            default_ceiling=DEFAULT_MAX_DOCUMENTS,
            provider_id=resolved.provider_id,
            unit="rerank document",
        )
        if chunks is not None:
            if not request.batch.allow_split:
                raise ConfigError(
                    f"rerank document count {len(request.documents)} exceeds the resolved "
                    f"batch limit of {limit} and BatchPolicy.allow_split is False",
                    provider=resolved.provider_id,
                    hint=(
                        "reduce the request, raise the verified limit override, or allow "
                        "splitting"
                    ),
                )
            if not request.batch.rerank_cross_batch:
                raise ConfigError(
                    f"rerank document count {len(request.documents)} exceeds the resolved "
                    f"batch limit of {limit}, and scores from separate rerank calls are "
                    "not globally comparable",
                    provider=resolved.provider_id,
                    hint=(
                        "reduce the documents, or set BatchPolicy.rerank_cross_batch=True "
                        "to accept a concatenation of chunk-local rankings — the result "
                        "will say so in a warning"
                    ),
                )

        if chunks is None:
            rerank_call = functools.partial(
                _call_rerank, adapter, resolved, request, tuple(enumerate(request.documents))
            )
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
            if capabilities_for is not None:
                usage = with_operation_cost(usage, capabilities_for(resolved), "rerank")
            emit(
                RequestCompleted(
                    request_id=request_id, target=resolved, usage=usage, timing=timing
                )
            )
            return RerankResult(
                items=items,
                target=resolved,
                usage=usage,
                timing=timing,
                attempts=tuple(all_attempts),
                warnings=tuple(warnings),
                raw=wire_result.raw if retain_raw else None,
                manifest=build_operation_manifest(
                    operation="rerank",
                    request_id=request_id,
                    requested_targets=route.targets,
                    resolved=resolved,
                    attempts=all_attempts,
                    usage=usage,
                    timing=timing,
                    warnings=warnings,
                    anyinfer_version=anyinfer_version,
                )
                if manifest
                else None,
            )

        chunk_pairs = [
            tuple((index, request.documents[index]) for index in range(s.start, s.stop))
            for s in chunks
        ]
        batch_started = time.monotonic()
        outcomes = await _run_bounded(
            [
                functools.partial(
                    _attempt_with_retry,
                    resolved=resolved,
                    route=route,
                    request_id=request_id,
                    emit=emit,
                    call=functools.partial(_call_rerank, adapter, resolved, request, pairs),
                )
                for pairs in chunk_pairs
            ],
            max_concurrency=request.batch.max_concurrency,
        )
        for outcome in outcomes:
            if isinstance(outcome, BaseException) and not isinstance(outcome, ProviderError):
                raise outcome
        if any(isinstance(outcome, ProviderError) for outcome in outcomes):
            # All-or-error, same rule as embedding batches (ER.4.4/ER.10.5).
            raise _batch_failure_report(
                resolved,
                outcomes,
                [len(pairs) for pairs in chunk_pairs],
                all_attempts,
                emit=emit,
                request_id=request_id,
                health=health,
            )
        health.mark_healthy(resolved)

        seen: set[int] = set()
        ranked: list[RankedItem] = []
        usages: list[Usage] = []
        raws: list[object] = []
        for chunk_index, outcome in enumerate(outcomes):
            if isinstance(outcome, BaseException):  # pragma: no cover — excluded above
                raise outcome
            chunk_wire, _chunk_timing, chunk_attempts = outcome
            all_attempts.extend(chunk_attempts)
            allowed = {index for index, _ in chunk_pairs[chunk_index]}
            ranked.extend(
                _validate_ranked_items(
                    resolved, request, chunk_wire, allowed_indexes=allowed, seen=seen
                )
            )
            usages.append(chunk_wire.usage or Usage())
            raws.append(chunk_wire.raw)
        cross_batch_warning = (
            f"rerank request was split into {len(chunk_pairs)} batches of at most "
            f"{limit} documents for {resolved}; scores are comparable only within each "
            "batch — this result concatenates chunk-local rankings and is not a "
            "provider-certified global ordering"
        )
        if request.top_n is not None:
            cross_batch_warning += (
                f"; top_n={request.top_n} was applied within each batch, not globally"
            )
        warnings.append(cross_batch_warning)
        usage = Usage.sum(usages)
        if capabilities_for is not None:
            usage = with_operation_cost(usage, capabilities_for(resolved), "rerank")
        total_timing = Timing(
            started_at=batch_started,
            total_ms=(time.monotonic() - batch_started) * 1000.0,
        )
        emit(
            RequestCompleted(
                request_id=request_id, target=resolved, usage=usage, timing=total_timing
            )
        )
        return RerankResult(
            items=tuple(ranked),
            target=resolved,
            usage=usage,
            timing=total_timing,
            attempts=tuple(all_attempts),
            warnings=tuple(warnings),
            raw=tuple(raws) if retain_raw else None,
            manifest=build_operation_manifest(
                operation="rerank",
                request_id=request_id,
                requested_targets=route.targets,
                resolved=resolved,
                attempts=all_attempts,
                usage=usage,
                timing=total_timing,
                warnings=warnings,
                anyinfer_version=anyinfer_version,
            )
            if manifest
            else None,
        )

    error_info = last_error.snapshot() if last_error is not None else None
    if error_info is not None:
        emit(RequestFailed(request_id=request_id, error=error_info))
    raise AllTargetsFailedError(attempts=tuple(all_attempts))


def _pending_attempts(resolved: ResolvedTarget, exc: ProviderError) -> list[AttemptRecord]:
    """The final failed-attempt record for a target whose retry budget is spent."""
    return [AttemptRecord(target=resolved, outcome="failed", error=exc.snapshot())]


async def _call_embed(
    adapter: EmbedsText,
    resolved: ResolvedTarget,
    request: EmbeddingRequest,
    inputs: tuple[str, ...],
) -> tuple[EmbeddingWireResult, Timing]:
    wire_request = EmbeddingWireRequest(
        model=resolved.model,
        inputs=inputs,
        input_type=request.input_type,
        dimensions=request.dimensions,
        timeout_s=request.effective_timeout_s,
        max_response_bytes=request.max_response_bytes,
        extra_options=request.provider_options.get(resolved.provider_id, {}),
    )
    started = time.monotonic()
    result = await adapter.embed(wire_request)
    total_ms = (time.monotonic() - started) * 1000.0
    return result, Timing(started_at=started, total_ms=total_ms, phases=dict(result.phases))


async def _call_rerank(
    adapter: ReranksText,
    resolved: ResolvedTarget,
    request: RerankRequest,
    documents: tuple[tuple[int, RerankDocument], ...],
) -> tuple[RerankWireResult, Timing]:
    wire_request = RerankWireRequest(
        model=resolved.model,
        query=request.query,
        documents=tuple(
            RerankWireDocument(index=index, text=doc.text) for index, doc in documents
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
    resolved: ResolvedTarget,
    request: RerankRequest,
    wire_result: RerankWireResult,
    *,
    allowed_indexes: set[int] | None = None,
    seen: set[int] | None = None,
) -> tuple[RankedItem, ...]:
    """Turn wire-reported indexes into `RankedItem`s, trusting nothing malformed.

    For a split request, ``allowed_indexes`` restricts one chunk's result to the
    documents that chunk was actually asked to rank, and ``seen`` is shared across
    chunks so a duplicate cannot hide by arriving in two different batches.

    Raises:
        anyinfer.errors.ConfigError: The provider returned an out-of-range, out-of-batch,
            or duplicate document index. AnyInfer never guesses which document a
            malformed result meant.
    """
    doc_count = len(request.documents)
    seen = set() if seen is None else seen
    items: list[RankedItem] = []
    for wire_item in wire_result.items:
        if not (0 <= wire_item.index < doc_count):
            raise ConfigError(
                f"provider {resolved.provider_id!r} returned an out-of-range document "
                f"index {wire_item.index} for a request with {doc_count} documents",
                provider=resolved.provider_id,
                hint="this is a provider-side contract violation; report it upstream",
            )
        if allowed_indexes is not None and wire_item.index not in allowed_indexes:
            raise ConfigError(
                f"provider {resolved.provider_id!r} returned document index "
                f"{wire_item.index}, which is outside the internal batch it was asked "
                "to rank",
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
