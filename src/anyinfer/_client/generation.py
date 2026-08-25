"""Generation execution — the request path from a resolved route to a finished attempt.

Split out of `async_client.py`, which had grown to hold nearly all orchestration in one
class. These eleven methods are the part that runs a generation: route iteration and event
projection (`_routed_stream`, `_route_events`), the single-attempt body (`_run_attempt`),
and the request-shaping steps each attempt goes through — context compaction, pacing,
schema validation, prompt assembly, and cache planning.

**Why a mixin rather than free functions.** These methods share ten pieces of client state
and call seventeen sibling methods across the class. Rewriting that into functions taking
an explicit client would touch every line of eight hundred without changing behaviour, and
buy an indirection the class does not otherwise use. The mixin keeps the bodies untouched
and byte-identical, so the split is navigability only: one file per concern, with
`AsyncClient` composing them. Nothing here is meaningful on its own -- it is `AsyncClient`,
in a second file.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ..capabilities.budget import build_context_budget
from ..capabilities.cache import CachePlan, plan_cache
from ..capabilities.estimate import TokenEstimator
from ..capabilities.gating import check_context_fit
from ..capabilities.ledger import SpendLedger
from ..capabilities.pricing import (
    TRUSTED_PROVENANCE,
    with_cost,
)
from ..capabilities.tokenizers import estimator_for
from ..context.select import select as select_context
from ..context_request import ContextSummary
from ..errors import (
    AllTargetsFailedError,
    AuthError,
    ConfigError,
    ContextLengthError,
    ProviderError,
    ProviderUnavailableError,
    SchemaViolationError,
    StreamProtocolError,
    TransportError,
)
from ..events.observers import EventDispatcher
from ..events.telemetry import (
    AttemptCompleted,
    AttemptStarted,
    CachePlanned,
    FallbackTriggered,
    FirstToken,
    ParameterDropped,
    ProviderDiagnostic,
    RepairAttempted,
    RequestCompleted,
    RequestFailed,
    RequestStarted,
    RetryScheduled,
    TargetResolved,
    TelemetryEvent,
    UsageEstimated,
)
from ..manifest import ManifestBuilder
from ..providers.base import (
    AdapterFinal,
    ProviderAdapter,
    ProviderLifecycle,
    aclosing_if_supported,
)
from ..registry import ProviderDescriptor
from ..routing.attempts import AttemptBuffer
from ..routing.health import HealthCache
from ..routing.limits import AttemptPacing, RateLimiter
from ..routing.policy import Route, backoff_delay
from ..schema.partial import partial_object
from ..schema.repair import build_repair_messages
from ..schema.validate import extract_json, validate
from ..session import Session
from ..types.capabilities import (
    ModelCapabilities,
    TokenCalibration,
)
from ..types.events import (
    AttemptFailed,
    StreamEnded,
    StreamEvent,
    TimingMark,
    UsageUpdate,
    is_content_event,
)
from ..types.messages import (
    Text,
    system,
    user,
)
from ..types.requests import (
    CachePolicy,
    GenerationRequest,
    HistoryPolicy,
    ResolvedTarget,
    Target,
)
from ..types.results import (
    AttemptRecord,
    Diagnostic,
    Generation,
    Mechanism,
    Outcome,
    Timing,
)
from .providers import AdapterPool
from .wire import build_wire_request, dropped_parameters


def _as_generator(adapter: ProviderLifecycle, resolved: ResolvedTarget) -> ProviderAdapter:
    """Narrow a pooled adapter to the generation protocol, or say which one it is not.

    Raises:
        ConfigError: If the provider's adapter cannot generate. A descriptor claiming an
            operation its adapter lacks is an authoring bug, so this names the provider
            rather than surfacing an `AttributeError` from inside the router.
    """
    if not isinstance(adapter, ProviderAdapter):
        raise ConfigError(
            f"provider {resolved.provider_id!r} does not support generation",
            provider=resolved.provider_id,
            hint="choose a target whose provider declares the 'generation' operation",
        )
    return adapter


def _last_user_text(request: GenerationRequest) -> str:
    """The last user message's visible text, used only as a context-ranking query."""
    for message in reversed(request.messages):
        if message.role == "user":
            return "".join(part.text for part in message.content if isinstance(part, Text))
    return ""

class _ContentPolicyRedirect(Exception):  # noqa: N818 — control flow, not a failure
    """Internal control flow: a content-filter refusal redirects to its own chain.

    Never escapes the router — `AsyncClient._routed_stream` catches it and re-dispatches
    to ``chain``.
    """

    def __init__(self, chain: Sequence[Target]) -> None:
        super().__init__("content-policy redirect")
        self.chain = list(chain)

def _prompt_text(request: GenerationRequest) -> str:
    """Flatten a request's messages for payload-opted-in observers."""
    return "\n\n".join(m.text for m in request.messages if m.text)

def _missing_target_error(configured: Sequence[str]) -> ConfigError:
    """Build the error for a request that named no target and had no default route."""
    known = ", ".join(configured) or "(none configured)"
    return ConfigError(
        "no target specified for this request",
        hint=(
            "pass target='provider:model' or a catalog alias, or set a default route on "
            f"the client. Configured providers: {known}"
        ),
    )

def _failure_detail(attempts: Sequence[AttemptRecord], last: ProviderError | None) -> str:
    tried = len([a for a in attempts if a.outcome != "skipped_unhealthy"])
    skipped = len([a for a in attempts if a.outcome == "skipped_unhealthy"])
    parts = [f"all routing targets failed after {tried} attempt(s)"]
    if skipped:
        parts.append(f"{skipped} target(s) skipped as unhealthy")
    if last is not None:
        parts.append(f"last error: {last.detail}")
    return "; ".join(parts)

def _failure_hint(attempts: Sequence[AttemptRecord]) -> str:
    if attempts and all(a.outcome == "skipped_unhealthy" for a in attempts):
        return "every target was health-gated; set Route(health_gate=False) to force an attempt"
    return "inspect error.attempts for the per-target trail"

async def _collect_diagnostics(
    adapter: ProviderLifecycle, descriptor: ProviderDescriptor
) -> Sequence[Diagnostic]:
    """Ask a provider what it noticed about itself, tolerating anything it does.

    Advisory data must never turn a successful generation into a failed one, so every
    failure mode here — a provider that declares the capability but does not implement
    it, one that raises, one that returns nonsense — resolves to "nothing to report".
    Cancellation is the one exception: it is the caller leaving, not a provider fault.
    """
    if not descriptor.reports_diagnostics:
        return ()
    collect = getattr(adapter, "diagnostics", None)
    if not callable(collect):
        return ()
    try:
        reported = await collect()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — a diagnostic must never fail the request it annotates
        return ()
    if not isinstance(reported, Sequence):
        return ()
    return tuple(item for item in reported if isinstance(item, Diagnostic))

def _repair_budget(
    request: GenerationRequest, descriptor: ProviderDescriptor
) -> tuple[int, str | None]:
    """Resolve how many repair round trips this target may actually be asked for.

    Returns:
        The budget in force, and an explanation when the provider's ceiling reduced the
        caller's request — ``None`` when the caller got exactly what they asked for.
    """
    requested = request.repair.max_attempts if request.repair else 0
    ceiling = descriptor.max_repair_attempts
    if ceiling is None or requested <= ceiling:
        return requested, None
    return ceiling, (
        f"{descriptor.id} allows at most {ceiling} schema-repair round trip(s); "
        f"{requested} requested"
    )

def _structured_candidate(request: GenerationRequest, buffer: AttemptBuffer) -> Any | None:
    """Recover a structured answer that arrived as a forced tool call.

    Providers with no response-format field (Anthropic, Bedrock) emulate a schema by
    declaring it as a single forced tool, so a well-behaved model answers with a *tool
    call* rather than text. Reading only the text would then report an empty response
    for a request the provider satisfied perfectly.

    Only a call matching the schema's name counts, and only when the caller offered no
    tools of their own — otherwise a genuine tool call in a schema-carrying request
    would be mistaken for the answer.

    Returns:
        The tool call's arguments, or ``None`` to fall back to parsing the text.
    """
    if request.tools or request.schema is None:
        return None
    for call in buffer.build_tool_calls():
        if call.name == request.schema.name:
            return dict(call.arguments)
    return None


class GenerationExecutionMixin:
    """The generation request path. Mixed into `AsyncClient`; not usable alone."""

    if TYPE_CHECKING:
        # Declared, never defined. `AsyncClient` supplies every one of these; the block is
        # type-checking-only, so nothing here exists at runtime to shadow the real
        # implementation, and mypy --strict still sees what the mixin depends on. Adding a
        # dependency on new client state means adding it here, which keeps the coupling
        # this split has to live with visible rather than implicit.
        _builders: dict[str, ManifestBuilder]
        _cache: CachePolicy | None
        _context_gate: bool
        _estimator: TokenEstimator
        _events: EventDispatcher
        _health: HealthCache
        _history: HistoryPolicy | None
        _ledger: SpendLedger | None
        _pool: AdapterPool
        _retain_raw: bool

        def resolve(self, target: Target) -> ResolvedTarget: ...

        def _new_run(
            self, request: GenerationRequest, route: Route, manifest: bool | None
        ) -> tuple[str, ManifestBuilder | None]: ...

        def _capabilities_for(
            self, descriptor: ProviderDescriptor, resolved: ResolvedTarget
        ) -> ModelCapabilities: ...

        def _check_multimodal(
            self,
            request: GenerationRequest,
            resolved: ResolvedTarget,
            capabilities: ModelCapabilities,
        ) -> None: ...

        def _check_server_tools(
            self,
            request: GenerationRequest,
            resolved: ResolvedTarget,
            capabilities: ModelCapabilities,
        ) -> None: ...

        def _check_spend(
            self,
            request: GenerationRequest,
            resolved: ResolvedTarget,
            capabilities: ModelCapabilities | None,
            *,
            request_id: str,
        ) -> None: ...

        def _check_prefix_stability(
            self,
            request: GenerationRequest,
            plan: CachePlan,
            resolved: ResolvedTarget,
            builder: ManifestBuilder | None = None,
        ) -> None: ...

        def _emit(
            self, event: TelemetryEvent, *, builder: ManifestBuilder | None = None
        ) -> None: ...

    async def _routed_stream(
        self,
        request: GenerationRequest,
        route: Route,
        *,
        stream: bool,
        session: Session | None = None,
        request_id: str | None = None,
        builder: ManifestBuilder | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Run the route and yield its events."""
        if request_id is None:
            request_id, builder = self._new_run(request, route, None)
        try:
            # `aclosing` rather than a bare `async for`: closing *this* generator early
            # (a consumer breaking out of a stream) throws GeneratorExit at the current
            # `yield`, which does not itself close `_route_events`'s generator — leaving
            # it, and everything it wraps down to the provider connection, to finalize
            # during GC instead of closing deterministically.
            async with contextlib.aclosing(
                self._route_events(
                    request,
                    route,
                    stream=stream,
                    session=session,
                    request_id=request_id,
                    builder=builder,
                )
            ) as events:
                async for event in events:
                    yield event
        finally:
            # The builder outlives this generator only through the handle a streaming
            # caller already holds; the registry must not, or an abandoned stream would
            # leak one entry per call.
            self._builders.pop(request_id, None)
            if self._ledger is not None:
                self._ledger.release(request_id)

    async def _route_events(
        self,
        request: GenerationRequest,
        route: Route,
        *,
        stream: bool,
        session: Session | None,
        request_id: str,
        builder: ManifestBuilder | None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Run the route proper, once the run is registered."""
        if session is not None:
            session._ensure_usable()
        attempts: list[AttemptRecord] = []
        self._emit(
            RequestStarted(
                request_id=request_id,
                targets=route.targets,
                metadata=request.metadata,
                prompt_text=_prompt_text(request) if self._events.wants_payloads else None,
            )
        )

        if not route.targets:
            error = _missing_target_error(self._pool.configured_ids)
            self._emit(RequestFailed(request_id, error.snapshot()))
            raise error

        last_error: ProviderError | None = None
        pending: list[Target] = list(route.targets)
        visited: set[str] = set()
        content_redirected = False
        active = request
        compacted = False

        def unvisited_content_chain() -> list[Target]:
            return [t for t in route.content_policy_targets if str(self.resolve(t)) not in visited]

        while pending:
            target = pending.pop(0)
            resolved = self.resolve(target)
            if str(resolved) in visited:
                continue
            visited.add(str(resolved))
            self._emit(TargetResolved(request_id, resolved))

            if route.health_gate and self._health.recently_failed(resolved, route.health_ttl_s):
                attempts.append(AttemptRecord(resolved, "skipped_unhealthy"))
                continue

            adapter = _as_generator(await self._pool.get(resolved.provider_id), resolved)
            descriptor = self._pool.descriptor_for(resolved.provider_id)
            capabilities = self._capabilities_for(descriptor, resolved)
            if builder is not None:
                builder.note_capabilities(resolved, capabilities)
            try:
                target_request, context_summary = self._apply_context_request(
                    active,
                    resolved=resolved,
                    capabilities=capabilities,
                    calibration=descriptor.token_calibration,
                    builder=builder,
                )
            except ConfigError as error:
                self._emit(RequestFailed(request_id, error.snapshot()))
                raise
            redirected_now = False

            for attempt_number in range(1, route.retry.max_attempts + 1):
                self._emit(AttemptStarted(request_id, resolved, attempt_number))
                buffer = AttemptBuffer(target=resolved)
                emitted_content = False

                try:
                    # See the matching comment in `_routed_stream`: `aclosing` ensures an
                    # early close of *this* generator also closes `_run_attempt`'s, rather
                    # than orphaning it.
                    async with contextlib.aclosing(
                        self._run_attempt(
                            request=target_request,
                            resolved=resolved,
                            adapter=adapter,
                            descriptor=descriptor,
                            capabilities=capabilities,
                            buffer=buffer,
                            request_id=request_id,
                            stream=stream,
                            attempts=attempts,
                            session=session,
                            builder=builder,
                            context_summary=context_summary,
                            content_chain=(
                                unvisited_content_chain
                                if route.content_policy_targets and not content_redirected
                                else None
                            ),
                        )
                    ) as attempt_events:
                        async for event in attempt_events:
                            if is_content_event(event):
                                emitted_content = True
                            yield event
                    self._health.mark_healthy(resolved)
                    return
                except _ContentPolicyRedirect as redirect:
                    # The target answered, but with a content-filter refusal, and the
                    # route names a differently-governed chain for exactly that case.
                    # The refusal is discarded and the route redirects (Route docs).
                    self._health.mark_healthy(resolved)
                    content_redirected = True
                    redirected_now = True
                    pending = list(redirect.chain)
                    self._emit(
                        FallbackTriggered(request_id, from_target=resolved, to_target=pending[0])
                    )
                    break
                except ProviderError as error:
                    last_error = error
                    retryable = route.retry.should_retry(error)
                    if not retryable and isinstance(error, AuthError):
                        # An auth failure is deterministic — unless the credential rotated
                        # underneath a long-running process, in which case the same request
                        # succeeds with a freshly resolved one. The pool re-resolves and
                        # answers whether anything actually moved, so a genuinely wrong key
                        # still fails on the first attempt rather than being sent twice.
                        retryable = await self._pool.refresh_credential(resolved.provider_id)
                        if retryable:
                            adapter = _as_generator(
                                await self._pool.get(resolved.provider_id), resolved
                            )
                    budget_left = attempt_number < route.retry.max_attempts

                    if isinstance(error, StreamProtocolError) and emitted_content:
                        # The consumer has already seen text from this attempt. Silently
                        # retrying or falling back would duplicate or contradict it, so the
                        # failure surfaces instead.
                        record = AttemptRecord(
                            resolved, "failed", error.snapshot(), buffer.build_timing()
                        )
                        attempts.append(record)
                        yield AttemptFailed(record)
                        self._emit(RequestFailed(request_id, error.snapshot()))
                        raise

                    outcome: Outcome = "retried" if (retryable and budget_left) else "failed"
                    record = AttemptRecord(
                        resolved, outcome, error.snapshot(), buffer.build_timing()
                    )
                    attempts.append(record)
                    yield AttemptFailed(record)

                    if retryable and budget_left:
                        delay = backoff_delay(
                            attempt_number, route.retry, retry_after_s=error.retry_after_s
                        )
                        self._emit(
                            RetryScheduled(
                                request_id, resolved, attempt_number, delay, error.snapshot()
                            )
                        )
                        if delay > 0:
                            await asyncio.sleep(delay)
                        continue

                    if isinstance(error, TransportError | ProviderUnavailableError):
                        self._health.mark_failed(resolved, error.detail)
                    break

            if redirected_now:
                continue

            if last_error is not None:
                # A failure class with its own chain (context overflow) redirects the
                # remaining route: trying more same-sized models after a context
                # overflow just reproduces the overflow.
                specialized = route.specialized_chain_for(last_error)
                if specialized:
                    pending = [t for t in specialized if str(self.resolve(t)) not in visited]

            if pending and last_error is not None:
                self._emit(
                    FallbackTriggered(
                        request_id,
                        from_target=resolved,
                        to_target=pending[0],
                        error=last_error.snapshot(),
                    )
                )

            if not pending and not compacted and isinstance(last_error, ContextLengthError):
                # Every target, including the overflow chain — is exhausted and the
                # request still does not fit anywhere. Only now is losing history the
                # better answer than failing, which is what `last_resort` means. One
                # pass only: a second would be compacting an already-compacted request.
                policy = self._history_policy(active)
                if policy is not None and policy.mode == "last_resort":
                    retry = await self._compact_for_route(active, route, policy, builder)
                    if retry is not None:
                        compacted = True
                        active = retry
                        pending = list(route.targets)
                        visited.clear()
                        last_error = None

        failure = AllTargetsFailedError(
            _failure_detail(attempts, last_error),
            attempts=tuple(attempts),
            hint=_failure_hint(attempts),
        )
        self._emit(RequestFailed(request_id, failure.snapshot()))
        raise failure

    async def _compact_for_route(
        self,
        request: GenerationRequest,
        route: Route,
        policy: HistoryPolicy,
        builder: ManifestBuilder | None = None,
    ) -> GenerationRequest | None:
        """Shrink a conversation to fit the route's first target, for a retry pass.

        The first target is the one the retry will actually try first, so it is the
        window worth fitting. A route whose later targets are smaller may still overflow
        on those, and will simply fail there as it would have anyway.
        """
        resolved = self.resolve(route.targets[0])
        await self._pool.get(resolved.provider_id)
        descriptor = self._pool.descriptor_for(resolved.provider_id)
        return self._compact_to_fit(
            request,
            resolved=resolved,
            capabilities=self._capabilities_for(descriptor, resolved),
            calibration=descriptor.token_calibration,
            policy=policy,
            builder=builder,
        )

    def _history_policy(self, request: GenerationRequest) -> HistoryPolicy | None:
        """The compaction policy in force, request override beating the client default."""
        policy = request.history if request.history is not None else self._history
        return policy if policy is not None and policy.active else None

    def _compact_to_fit(
        self,
        request: GenerationRequest,
        *,
        resolved: ResolvedTarget,
        capabilities: ModelCapabilities,
        calibration: TokenCalibration | None,
        policy: HistoryPolicy,
        builder: ManifestBuilder | None = None,
    ) -> GenerationRequest | None:
        """Shrink a request's conversation to fit one target, or return ``None``.

        ``None`` means "nothing to do, or nothing that can be done": the request already
        fits, the window is unknown (unknown stays unknown — the client will not invent one
        to justify discarding a conversation), or compaction found nothing it was allowed
        to drop.

        Only the *messages* are compacted, so the budget compaction is held to is the
        allowance minus what tools, schema, and transport envelope already claim. The
        envelope component is treated as fixed even though it shrinks with the content,
        which compacts marginally harder than strictly necessary — the safe direction.
        """
        estimator = self._estimator_for(resolved)
        budget = build_context_budget(
            request, capabilities, estimator=estimator, calibration=calibration
        )
        allowance = budget.input_allowance_tokens
        if allowance is None or budget.fits is not False:
            return None

        overhead = budget.estimate.tokens - budget.estimate.messages.tokens
        target_tokens = allowance - overhead
        if target_tokens < 1:
            # The tools and schema alone exceed the window; dropping the conversation
            # would not save the request, and would lose it for nothing.
            return None

        from ..context.history import compact_history

        compaction = compact_history(
            request.messages,
            max_tokens=target_tokens,
            estimator=estimator,
            keep_recent=policy.keep_recent,
            keep_system=policy.keep_system,
        )
        if not compaction.changed:
            return None
        # A compaction event carries no request id, so the builder is handed over
        # explicitly rather than found by correlation.
        self._emit(compaction.event(), builder=builder)
        return request.with_messages(compaction.messages)

    def _estimator_for(self, resolved: ResolvedTarget) -> TokenEstimator:
        """The estimator to count this target's tokens with.

        A tokenizer is a *model's* fact, but `TokenEstimator.estimate`
        sees only text — so an estimator that knows how to specialize is asked to, once
        per target, and one that does not is returned unchanged. The shipped byte
        heuristic is in the second group, which is why it needed no change.
        """
        return estimator_for(self._estimator, resolved.provider_id, resolved.model)

    def _client_side_pacing(
        self, limiter: RateLimiter | None, descriptor: ProviderDescriptor
    ) -> AbstractAsyncContextManager[None]:
        """Pace a provider whose transport the core did not build.

        An adapter that talks through a vendor SDK has no transport of ours to wrap, so its
        concurrency bound is applied here instead — around the call rather than under it.
        Every other provider is already governed at the transport, and taking the permit
        twice would halve its configured concurrency, so this yields nothing for them.
        """
        if limiter is None or not descriptor.governs_own_transport:
            return contextlib.nullcontext()
        return limiter.slot()

    def _apply_context_request(
        self,
        request: GenerationRequest,
        *,
        resolved: ResolvedTarget,
        capabilities: ModelCapabilities,
        calibration: TokenCalibration,
        builder: ManifestBuilder | None,
        emit: bool = True,
    ) -> tuple[GenerationRequest, ContextSummary | None]:
        """Reduce caller-approved documents for one resolved target before its gate."""
        policy = request.context
        if policy is None:
            return request, None
        estimator = self._estimator_for(resolved)
        max_tokens = policy.max_tokens
        if max_tokens is None:
            budget = build_context_budget(
                request,
                capabilities,
                estimator=estimator,
                calibration=calibration,
            )
            if (
                budget.context_window is not None
                and budget.context_window.provenance in TRUSTED_PROVENANCE
            ):
                max_tokens = budget.remaining_tokens
        if max_tokens is None or max_tokens < 1:
            raise ConfigError(
                "the resolved target has no known remaining context budget for documents",
                hint="set ContextRequest(max_tokens=...) explicitly, or choose a target "
                "with a trusted context window",
            )
        query = policy.query if policy.query is not None else _last_user_text(request)
        reduction = select_context(
            policy.documents,
            query,
            max_tokens=max_tokens,
            strategy=policy.strategy,
            max_documents=policy.max_request_documents,
            max_bytes=policy.max_request_bytes,
            estimator=estimator,
            tuning=policy.tuning,
        )
        if emit:
            self._emit(reduction.event(), builder=builder)
        envelope = system(reduction.text) if policy.placement == "system" else user(reduction.text)
        messages = list(request.messages)
        if policy.placement == "system":
            messages.insert(0, envelope)
        else:
            index = 0
            while index < len(messages) and messages[index].role == "system":
                index += 1
            messages.insert(index, envelope)
        return (
            replace(request, messages=tuple(messages), context=None),
            ContextSummary.from_reduction(reduction),
        )

    async def _run_attempt(
        self,
        *,
        request: GenerationRequest,
        resolved: ResolvedTarget,
        adapter: ProviderAdapter,
        descriptor: ProviderDescriptor,
        capabilities: ModelCapabilities,
        buffer: AttemptBuffer,
        request_id: str,
        stream: bool,
        attempts: list[AttemptRecord],
        session: Session | None = None,
        builder: ManifestBuilder | None = None,
        context_summary: ContextSummary | None = None,
        content_chain: Callable[[], list[Target]] | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Run one attempt against one target, including the schema repair loop.

        Repair re-runs *this* target rather than the route: a schema violation says
        something about the model, not the endpoint's availability.

        ``content_chain``, when supplied, is consulted after a ``content_filter``
        finish: a non-empty chain raises `_ContentPolicyRedirect` instead of
        completing, and the router re-dispatches to that chain.
        """
        policy = self._history_policy(request)
        if policy is not None and policy.mode == "proactive":
            # Shrink to fit *this* target before the gate can refuse it. The tradeoff is
            # stated on HistoryPolicy: a larger-window target further down the route will
            # never be reached, because there is no longer an overflow to redirect.
            fitted = self._compact_to_fit(
                request,
                resolved=resolved,
                capabilities=capabilities,
                calibration=descriptor.token_calibration,
                policy=policy,
                builder=builder,
            )
            if fitted is not None:
                request = fitted

        # Money is checked in the same place as size, and for the same reason: a refusal
        # that costs a round trip is a refusal that already spent something.
        self._check_multimodal(request, resolved, capabilities)
        self._check_server_tools(request, resolved, capabilities)
        self._check_spend(request, resolved, capabilities, request_id=request_id)

        if self._context_gate:
            # A ContextLengthError raised here follows the exact path a provider-reported
            # overflow would: the default retry predicate declines it, and the route
            # redirects to context_window_targets — minus the round trip.
            check_context_fit(
                request,
                capabilities,
                estimator=self._estimator_for(resolved),
                calibration=descriptor.token_calibration,
                provider=resolved.provider_id,
                model=resolved.model,
            )
            self._emit(
                UsageEstimated(
                    request_id, resolved, "input_tokens", "pre-dispatch context-gate estimate"
                )
            )

        session_applies = session is not None and session.applies_to(resolved)
        current = request
        repair_budget, repair_clamp_reason = _repair_budget(request, descriptor)
        if repair_clamp_reason is not None:
            self._emit(
                ParameterDropped(request_id, resolved, "repair.max_attempts", repair_clamp_reason)
            )
        repair_attempts = 0
        yielded_content = False

        cache_plan = self._plan_cache(
            current, resolved, descriptor, capabilities, request_id, builder
        )
        buffer.cache_mechanism = cache_plan.mechanism

        while True:
            active_buffer = buffer if repair_attempts == 0 else AttemptBuffer(target=resolved)
            yield TimingMark("attempt_start", 0.0)
            first_token_seen = False
            final: AdapterFinal | None = None

            wire = build_wire_request(
                current,
                resolved,
                descriptor,
                capabilities=capabilities,
                stream=stream,
                # A session's state is only offered to the target it belongs to: after a
                # fallback, one provider's handle means nothing to another.
                session_state=session.state if session_applies and session else None,
                cache_marks=tuple(mark.segment for mark in cache_plan.marks),
            )
            limiter = self._pool.limiter_for(resolved.provider_id)
            if repair_attempts == 0:
                for parameter, reason in dropped_parameters(current, descriptor, capabilities):
                    self._emit(ParameterDropped(request_id, resolved, parameter, reason))
                if limiter is not None and limiter.unsupported_headers_reason:
                    self._emit(
                        ParameterDropped(
                            request_id,
                            resolved,
                            "limits.respect_headers",
                            limiter.unsupported_headers_reason,
                        )
                    )

            saw_usage_event = False
            pacing = AttemptPacing(request_id, resolved)
            try:
                # An early close here must also close the adapter's generator, or the
                # provider connection it holds is left to finalize during GC instead of
                # closing deterministically (see the matching comment in `_routed_stream`).
                # `aclosing_if_supported` rather than `contextlib.aclosing`: `adapter` is
                # `ProviderAdapter`-typed, and `GeneratesText.generate()` does not promise
                # `.aclose()` (see that Protocol's docstring).
                async with (
                    self._client_side_pacing(limiter, descriptor),
                    asyncio.timeout(current.effective_timeout_s),
                    aclosing_if_supported(adapter.generate(wire)) as adapter_events,
                ):
                    async for event in adapter_events:
                        # Pacing is over once anything comes back, and the marker must not
                        # outlive it: this is an async generator, so a marker still set at a
                        # yield would follow the consumer into whatever it does next.
                        pacing.detach()
                        if isinstance(event, AdapterFinal):
                            final = event
                            continue
                        if is_content_event(event) and not first_token_seen:
                            first_token_seen = True
                            at_ms = active_buffer.mark_first_token(time.monotonic())
                            self._emit(FirstToken(request_id, resolved, at_ms))
                            yield TimingMark("first_token", at_ms)
                        if isinstance(event, UsageUpdate):
                            saw_usage_event = True
                            active_buffer.usage = active_buffer.usage.merge(event.usage)
                        else:
                            active_buffer.absorb(event)
                        if is_content_event(event):
                            yielded_content = True
                        yield event
            except TimeoutError:
                # asyncio.timeout raises the builtin TimeoutError, which would bypass
                # the router's ProviderError handling — no attempt record, no retry,
                # no failure telemetry. Surface it as the typed, retryable transport
                # failure it is instead.
                raise TransportError(
                    f"attempt against {resolved} timed out after {current.effective_timeout_s:g}s",
                    provider=resolved.provider_id,
                    phase="stream" if stream else "generate",
                    hint="raise timeout_s, or choose a faster model",
                ) from None
            finally:
                # A failed attempt queued just as long as a successful one, and its record
                # should say so — otherwise a paced fan-out reads as a slow provider.
                pacing.detach()
                if pacing.waited:
                    active_buffer.phases["queued_ms"] = pacing.waited_ms

            if final is not None and session is not None:
                session._record(final.session_state, applied=session_applies)
            if final is not None:
                active_buffer.finish_reason = final.finish_reason
                if final.usage is not None:
                    active_buffer.usage = active_buffer.usage.merge(final.usage)
                    if not saw_usage_event:
                        # Some dialects report usage only on their terminal object
                        # (Ollama's `done` message). Consumers watching the stream must
                        # still see it, so the core normalizes the difference away.
                        yield UsageUpdate(final.usage)
                active_buffer.phases.update(final.phases)
                active_buffer.logprobs = final.logprobs
                active_buffer.server_tool_uses = final.server_tool_uses
                if final.server_tool_uses:
                    # Onto usage as well as the result: cost is computed from usage alone,
                    # and a search is a billed line item like any token.
                    active_buffer.usage = replace(
                        active_buffer.usage,
                        server_tool_uses={
                            use.kind: use.uses for use in final.server_tool_uses
                        },
                    )
                if self._retain_raw:
                    active_buffer.raw = final.raw

            if (
                content_chain is not None
                and active_buffer.finish_reason == "content_filter"
                and not (stream and yielded_content)
            ):
                # A refusal with a configured content-policy chain redirects instead of
                # completing, but never after the consumer has already seen streamed
                # text from this attempt, where a silent restart would contradict it.
                chain = content_chain()
                if chain:
                    attempts.append(
                        AttemptRecord(resolved, "redirected", timing=active_buffer.build_timing())
                    )
                    raise _ContentPolicyRedirect(chain)

            structured, errors = self._validate(current, active_buffer)

            if errors and repair_attempts < repair_budget:
                if builder is not None:
                    builder.note_repair_text(active_buffer.text)
                self._emit(
                    RepairAttempted(
                        request_id,
                        resolved,
                        repair_attempts + 1,
                        wire.mechanism,
                        errors,
                        active_buffer.text if self._events.wants_payloads else None,
                    )
                )
                current = request.with_messages(
                    build_repair_messages(request.messages, active_buffer.text, errors)
                )
                repair_attempts += 1
                continue

            if errors:
                schema = request.schema
                if schema is None:
                    raise RuntimeError("schema validation failed for a request without a schema")
                partial, missing = partial_object(active_buffer.text, schema.json_schema)
                raise SchemaViolationError(
                    f"response did not match the required schema: {errors[0]}",
                    raw_text=active_buffer.text,
                    errors=errors,
                    partial=partial,
                    missing_required=missing,
                    provider=resolved.provider_id,
                    hint=(
                        "set repair=Repair(max_attempts=1) to let the model correct itself, "
                        "or relax the schema"
                    ),
                )

            # Cost is computed centrally so every provider reports it identically, and
            # stays None when pricing is unknown rather than becoming a misleading zero.
            active_buffer.usage = with_cost(active_buffer.usage, capabilities)

            for diagnostic in await _collect_diagnostics(adapter, descriptor):
                active_buffer.warnings.append(diagnostic.message)
                self._emit(ProviderDiagnostic(resolved, diagnostic, request_id))

            timing = active_buffer.build_timing()
            record = AttemptRecord(resolved, "ok", timing=timing)
            attempts.append(record)
            result = self._assemble(
                current,
                active_buffer,
                resolved,
                structured,
                wire.mechanism,
                repair_attempts,
                tuple(attempts),
                timing,
                context_summary,
            )
            self._emit(
                AttemptCompleted(request_id, resolved, result.usage, timing, result.finish_reason)
            )
            self._emit(
                RequestCompleted(
                    request_id,
                    resolved,
                    result.usage,
                    timing,
                    repair_attempts,
                    result.text if self._events.wants_payloads else None,
                )
            )
            if builder is not None:
                # Assembled last, so the record carries the completion events above as
                # well as the result they describe.
                builder.note_result(result)
                result = replace(result, manifest=builder.build())
            yield StreamEnded(result)
            return

    def _validate(
        self, request: GenerationRequest, buffer: AttemptBuffer
    ) -> tuple[Any, tuple[str, ...]]:
        """Extract and validate structured output, if the request asked for any."""
        if request.schema is None:
            return None, ()

        candidate = _structured_candidate(request, buffer)
        if candidate is None:
            parsed, parse_error = extract_json(buffer.text)
            if parse_error is not None:
                return None, (parse_error,)
            candidate = parsed

        errors = validate(candidate, request.schema.json_schema)
        return (candidate, ()) if not errors else (None, errors)

    def _assemble(
        self,
        request: GenerationRequest,
        buffer: AttemptBuffer,
        resolved: ResolvedTarget,
        structured: Any,
        mechanism: Mechanism | None,
        repair_attempts: int,
        attempts: tuple[AttemptRecord, ...],
        timing: Timing,
        context_summary: ContextSummary | None = None,
    ) -> Generation:
        """Build the final `Generation` from an attempt's buffers."""
        tool_calls = buffer.build_tool_calls()
        finish_reason = buffer.finish_reason
        if tool_calls and finish_reason == "stop":
            # Some dialects report "stop" alongside tool calls; the tool-call path is what
            # the caller must actually branch on.
            finish_reason = "tool_calls"
        return Generation(
            text=buffer.text,
            structured=structured,
            tool_calls=tool_calls,
            target=resolved,
            finish_reason=finish_reason,
            usage=buffer.usage.normalized(),
            timing=timing,
            structured_mechanism=mechanism if request.schema is not None else None,
            cache_mechanism=buffer.cache_mechanism,
            repair_attempts=repair_attempts,
            attempts=attempts,
            warnings=tuple(buffer.warnings),
            raw=buffer.raw,
            context_reduction=context_summary,
            logprobs=buffer.logprobs,
            citations=tuple(buffer.citations),
            server_tool_uses=buffer.server_tool_uses,
        )

    def _plan_cache(
        self,
        request: GenerationRequest,
        resolved: ResolvedTarget,
        descriptor: ProviderDescriptor,
        capabilities: ModelCapabilities | None,
        request_id: str,
        builder: ManifestBuilder | None = None,
    ) -> CachePlan:
        """Decide how to engage this target's prompt cache, and say so out loud.

        A policy that cannot be honored produces a `ParameterDropped` rather than silence:
        a caller who asked for caching and got none has a cost expectation that is now
        wrong, and finding out from a bill is not acceptable.
        """
        policy = request.cache if request.cache is not None else self._cache
        if builder is not None:
            builder.note_cache_policy(policy.mode if policy is not None else None)
        if policy is None or not policy.active:
            return CachePlan()

        plan = plan_cache(
            request,
            policy,
            capabilities or ModelCapabilities(),
            descriptor,
            self._estimator_for(resolved),
        )

        if plan.mechanism == "implicit":
            self._check_prefix_stability(request, plan, resolved, builder)

        if not plan.active:
            self._emit(
                ParameterDropped(
                    request_id,
                    resolved,
                    "cache.mode",
                    plan.reasons[0] if plan.reasons else "no cacheable segment",
                )
            )
            return plan

        if policy.mode == "explicit" and plan.mechanism != "explicit":
            # The caller asked for marks specifically. Getting prefix caching instead is a
            # weaker guarantee, and the difference is theirs to know about.
            self._emit(
                ParameterDropped(
                    request_id,
                    resolved,
                    "cache.mode",
                    f"the target offers {plan.mechanism} caching, not explicit marks",
                )
            )

        self._emit(
            CachePlanned(
                request_id,
                resolved,
                plan.mechanism or "",
                len(plan.marks),
                plan.estimated_cacheable_tokens,
            )
        )
        return plan
