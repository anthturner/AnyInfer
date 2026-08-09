"""The async core: routing, assembly, validation, repair, and telemetry.

This is the real implementation; `Client` is a synchronous facade over it. The routed loop
in `AsyncClient.stream()` is the single place retries, fallback, health gating, timing, and
schema repair happen—never in an adapter.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Any

from ..capabilities.assemble import CapabilityStore
from ..capabilities.budget import ContextBudget, build_context_budget
from ..capabilities.estimate import HeuristicTokenEstimator, TokenEstimator
from ..capabilities.gating import check_context_fit
from ..capabilities.pricing import with_cost
from ..capabilities.pricing_table import PricingTable
from ..catalog.model import Catalog, TargetEntry
from ..catalog.resolve import load_default_catalog, resolve_target
from ..credentials import ResolverChain
from ..errors import (
    AllTargetsFailedError,
    ConfigError,
    ProviderError,
    ProviderUnavailableError,
    SchemaViolationError,
    StreamProtocolError,
    ToolLoopError,
    TransportError,
)
from ..events.observers import EventDispatcher, Observer
from ..events.telemetry import (
    AttemptCompleted,
    AttemptStarted,
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
from ..local.acquire import AcquisitionReport, ProgressSink
from ..local.hardware import HardwareProfile
from ..local.store import ModelStore, RemovalReport, ResolvedModel, StoreEntry
from ..local.tuning import Posture
from ..local.variants import VariantPrefs
from ..providers.base import AdapterFinal, ProviderAdapter
from ..registry import ProviderDescriptor, ProviderRegistry, default_registry
from ..routing.attempts import AttemptBuffer
from ..routing.health import HealthCache
from ..routing.policy import Route, backoff_delay
from ..schema.repair import build_repair_messages
from ..schema.validate import extract_json, validate
from ..types.capabilities import DiscoveredModel, Health, ModelCapabilities, Sourced
from ..types.events import (
    AttemptFailed,
    StreamEnded,
    StreamEvent,
    TimingMark,
    UsageUpdate,
    is_content_event,
)
from ..types.messages import Message, user
from ..types.requests import (
    GenerationRequest,
    ReasoningEffort,
    Repair,
    ResolvedTarget,
    Sampling,
    SchemaSpec,
    SupportsJSONSchema,
    Target,
    ToolChoice,
    ToolSpec,
)
from ..types.results import (
    AttemptRecord,
    Diagnostic,
    Generation,
    Mechanism,
    Outcome,
    Timing,
)
from .models import (
    CatalogView,
    acquire_catalog_model,
    build_catalog_view,
    locate_catalog_model,
)
from .providers import AdapterPool, ProviderSettings
from .tools import (
    DEFAULT_MAX_ROUNDS,
    Tool,
    ToolRegistry,
    build_tool_turn,
)
from .wire import build_wire_request, dropped_parameters

__all__ = ["AsyncClient", "AsyncStream", "MessagesInput"]

MessagesInput = str | Message | Sequence[Message]
"""What callers may pass as ``messages``: a bare prompt, one message, or a sequence."""


def _coerce_messages(value: MessagesInput) -> tuple[Message, ...]:
    """Normalize the accepted message spellings into a tuple."""
    if isinstance(value, str):
        return (user(value),)
    if isinstance(value, Message):
        return (value,)
    return tuple(value)


class _ContentPolicyRedirect(Exception):  # noqa: N818 — control flow, not a failure
    """Internal control flow: a content-filter refusal redirects to its own chain.

    Never escapes the router — `AsyncClient._routed_stream` catches it and re-dispatches
    to ``chain``.
    """

    def __init__(self, chain: Sequence[Target]) -> None:
        super().__init__("content-policy redirect")
        self.chain = list(chain)


class AsyncClient:
    """The asynchronous inference client.

    Args:
        providers: Per-provider settings. The order given is the preference order used when
            resolving catalog aliases.
        registry: Provider registry; defaults to the process-wide one.
        catalog: Alias catalog; defaults to the bundled catalog. Pass ``None`` explicitly via
            ``use_default_catalog=False`` to disable alias resolution.
        route: Default route applied when a call names no target.
        observers: Telemetry observers, registered payload-free.
        resolver: Credential resolver chain.
        retain_raw: Keep the provider's raw payload on results. Off by default because raw
            payloads carry response text that payload-free telemetry deliberately omits.
        repair: Default repair budget for schema violations.
        use_default_catalog: Load the bundled catalog when ``catalog`` is not supplied.
        estimator: Token counting strategy for budgets and the pre-dispatch gate.
            Defaults to the dependency-free byte heuristic.
        context_gate: Fail a target before dispatch when the request provably cannot
            fit its known context window. Only trusted-provenance windows gate,
            and only on the estimate's floor, so a heuristic never refuses a request
            that might have fit.
        pricing_table: Model pricing supplying the ``catalog`` layer of capability
            assembly. Defaults to the table bundled with this release; pass the
            result of `fetch_pricing()` for newer numbers.
        capability_overrides: Deliberate corrections keyed by ``"provider:model"``.
            Every supplied field is applied at ``override`` provenance — the strongest
            layer, outranking discovery and probes — so a wrong upstream number can
            always be fixed locally.
        model_dir: Where acquired model weights are stored. Defaults to the per-OS data
            directory, overridable with ``ANYINFER_MODEL_DIR``.
    """

    def __init__(
        self,
        providers: Sequence[ProviderSettings] | None = None,
        *,
        registry: ProviderRegistry | None = None,
        catalog: Catalog | None = None,
        route: Route | None = None,
        observers: Sequence[Observer] | None = None,
        resolver: ResolverChain | None = None,
        retain_raw: bool = False,
        repair: Repair | None = None,
        use_default_catalog: bool = True,
        estimator: TokenEstimator | None = None,
        context_gate: bool = True,
        pricing_table: PricingTable | None = None,
        capability_overrides: Mapping[str, ModelCapabilities] | None = None,
        model_dir: Path | None = None,
    ) -> None:
        self._registry = registry or default_registry
        self._events = EventDispatcher(list(observers or []))
        self._pool = AdapterPool(
            list(providers or []),
            registry=self._registry,
            resolver=resolver,
            # Lifecycle telemetry from adapters (server start/stop, download progress)
            # flows through the same dispatcher as request-path events.
            events=self._emit,
        )
        if catalog is None and use_default_catalog:
            catalog = load_default_catalog()
        self._catalog = catalog
        self._default_route = route
        self._health = HealthCache()
        self._capabilities = CapabilityStore(
            pricing=pricing_table,
            overrides=_parse_overrides(capability_overrides, self._registry),
        )
        self._retain_raw = retain_raw
        self._default_repair = repair
        self._estimator: TokenEstimator = estimator or HeuristicTokenEstimator()
        self._context_gate = context_gate
        self._store = ModelStore(model_dir)
        self._closed = False

    # ---- lifecycle -------------------------------------------------------------------

    async def __aenter__(self) -> AsyncClient:
        """Enter an async context managing this client's adapters."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the client on context exit."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close every adapter this client built."""
        if self._closed:
            return
        self._closed = True
        await self._pool.aclose()

    # ---- observation -----------------------------------------------------------------

    def subscribe(self, observer: Observer, *, payloads: bool = False) -> None:
        """Register a telemetry observer.

        Args:
            observer: The sink.
            payloads: Opt in to prompt and response text. Off by default, so no
                observer sees payload text it did not explicitly ask for.
        """
        self._events.subscribe(observer, payloads=payloads)

    def unsubscribe(self, observer: Observer) -> None:
        """Remove a telemetry observer."""
        self._events.unsubscribe(observer)

    @property
    def catalog(self) -> Catalog | None:
        """The alias catalog in force, if any."""
        return self._catalog

    # ---- discovery -------------------------------------------------------------------

    async def models(self, provider_id: str) -> Sequence[DiscoveredModel]:
        """List a provider's models, recording what they report about capabilities."""
        adapter = await self._pool.get(provider_id)
        models = await adapter.list_models()
        canonical = self._registry.resolve_alias(provider_id)
        self._capabilities.record_discovery(canonical, models)
        return models

    async def health(self, provider_id: str) -> Health:
        """Probe a provider's readiness."""
        adapter = await self._pool.get(provider_id)
        return await adapter.health()

    async def diagnostics(self, provider_id: str) -> Sequence[Diagnostic]:
        """Ask a provider what it has noticed about its own runtime.

        Answers the question a health probe cannot: not "can I reach it" but "is it in
        good shape" — a model that spilled out of VRAM, a runtime that fell back to the
        CPU, a supervised server nearing its memory ceiling. Requests to such a provider
        succeed; they are simply much slower than the caller expects, with nothing in the
        result to explain why.

        Providers that declare ``reports_diagnostics`` answer; the rest return nothing,
        as does one that fails to answer — this is advisory data and never raises.

        Args:
            provider_id: The configured provider to ask.

        Returns:
            What the provider reported, most likely empty.
        """
        adapter = await self._pool.get(provider_id)
        descriptor = self._pool.descriptor_for(provider_id)
        reported = await _collect_diagnostics(adapter, descriptor)
        for diagnostic in reported:
            self._emit(ProviderDiagnostic(None, diagnostic))
        return reported

    def resolve(self, target: Target) -> ResolvedTarget:
        """Resolve a target string without issuing a request."""
        return resolve_target(
            target,
            registry=self._registry,
            catalog=self._catalog,
            configured_providers=self._pool.configured_ids,
        )

    # ---- local models ----------------------------------------------------------------

    @property
    def model_store(self) -> ModelStore:
        """The store acquired model weights live in."""
        return self._store

    async def local_catalog(
        self,
        provider_id: str | None = None,
        *,
        hardware: HardwareProfile | None = None,
        best_at: str | None = None,
        posture: Posture = "balanced",
    ) -> CatalogView:
        """Browse the local model catalog, annotated with how each entry fits.

        Performs no network I/O: the catalog is bundled data and hardware detection is
        local and cached.

        Args:
            provider_id: Restrict to models one configured engine can serve. Its locality
                also decides whether this machine is the right one to probe.
            hardware: Specs to judge against, overriding detection. This is how an
                application answers for a remote host after asking the user.
            best_at: One category from the catalog's closed vocabulary.
            posture: How much of the machine to budget.

        Returns:
            The view. ``hardware_source == "unavailable"`` means the engine runs somewhere
            AnyInfer cannot probe, and the application should collect the host's specs and
            call again.

        Raises:
            ConfigError: If ``best_at`` names a category no catalog entry uses.
        """
        probeable = True
        if provider_id is not None:
            probeable = self._pool.locality_for(provider_id) == "local"
        return build_catalog_view(
            self._catalog,
            provider_id=provider_id,
            hardware=hardware,
            best_at=best_at,
            posture=posture,
            probeable=probeable,
        )

    async def acquire_model(
        self,
        model_id: str,
        *,
        engine: str | None = None,
        variant_id: str | None = None,
        hardware: HardwareProfile | None = None,
        progress: ProgressSink | None = None,
        prefs: VariantPrefs | None = None,
        dry_run: bool = False,
        token: str | None = None,
    ) -> AcquisitionReport:
        """Download a catalog model's weights into this client's model store.

        The quantization is *chosen*, not assumed: the highest curated rung whose weights
        and KV cache fit this machine's budget. Pass ``variant_id`` to override that.

        ``dry_run=True`` resolves everything and reports the exact byte count without
        writing anything — what an application needs to confirm a large download with a
        user before starting it.

        Args:
            model_id: A catalog model id.
            engine: ``"llama.cpp"`` or ``"vllm"``; defaults to whatever the model offers.
            variant_id: Acquire this exact variant, skipping selection.
            hardware: Specs to select against, overriding detection.
            progress: Aggregate progress sink. See `AcquisitionProgress` for the
                threading contract it must honor.
            prefs: Selection preferences, including the low-quality opt-in.
            dry_run: Plan and report without writing.
            token: A credential for the source, when it needs one. Defaults to
                ``HF_TOKEN``.

        Returns:
            The report, naming the registered entry and what it cost.

        Raises:
            ConfigError: If there is no catalog, the model is unknown, or nothing fits.
            LocalRuntimeError: On a transfer failure, digest mismatch, or full disk.
        """
        return await acquire_catalog_model(
            self._catalog,
            self._store,
            model_id,
            engine=engine,
            variant_id=variant_id,
            hardware=hardware,
            progress=progress,
            prefs=prefs,
            dry_run=dry_run,
            token=token,
        )

    async def installed_models(self) -> Sequence[StoreEntry]:
        """Every model acquired into this client's store."""
        return self._store.list_installed()

    async def locate_model(
        self,
        model_id: str,
        *,
        variant_id: str | None = None,
        engine: str | None = None,
        verify: bool = False,
    ) -> ResolvedModel | None:
        """Find an acquired model on disk, with advisory launch arguments.

        No network I/O. Verification is shallow by default — size and modification time
        against the index — because re-hashing forty gigabytes on every lookup would be
        absurd; ``verify=True`` forces the full check.
        """
        return locate_catalog_model(
            self._catalog,
            self._store,
            model_id,
            variant_id=variant_id,
            engine=engine,
            verify=verify,
        )

    async def remove_model(self, entry_id: str) -> RemovalReport:
        """Delete an acquired model's files and unregister it.

        A model adopted from somebody else's cache is only unregistered; its files belong
        to whatever put them there.
        """
        return self._store.remove(entry_id)

    # ---- generation ------------------------------------------------------------------

    async def generate(
        self,
        messages: MessagesInput,
        *,
        target: Target | None = None,
        route: Route | Target | Sequence[Target] | None = None,
        schema: SchemaSpec | SupportsJSONSchema | Mapping[str, Any] | None = None,
        tools: Sequence[ToolSpec] = (),
        tool_choice: ToolChoice = "auto",
        sampling: Sampling | None = None,
        reasoning: ReasoningEffort | None = None,
        timeout_s: float | None = None,
        repair: Repair | None = None,
        provider_options: Mapping[str, Mapping[str, Any]] | None = None,
        metadata: Mapping[str, str] | None = None,
        max_response_bytes: int | None = None,
    ) -> Generation:
        """Generate a single result, draining the event stream internally.

        Returns:
            The assembled `Generation`.

        Raises:
            anyinfer.errors.AllTargetsFailedError: Every target failed.
            anyinfer.errors.SchemaViolationError: The response never satisfied the schema.
        """
        request = self._build_request(
            messages,
            schema=schema,
            tools=tools,
            tool_choice=tool_choice,
            sampling=sampling,
            reasoning=reasoning,
            timeout_s=timeout_s,
            repair=repair,
            provider_options=provider_options,
            metadata=metadata,
            max_response_bytes=max_response_bytes,
        )
        resolved_route = self._resolve_route(target, route)
        async for event in self._routed_stream(request, resolved_route, stream=False):
            if isinstance(event, StreamEnded):
                return event.result
        raise AllTargetsFailedError(hint="the router produced no result and no error")

    def stream(
        self,
        messages: MessagesInput,
        *,
        target: Target | None = None,
        route: Route | Target | Sequence[Target] | None = None,
        schema: SchemaSpec | SupportsJSONSchema | Mapping[str, Any] | None = None,
        tools: Sequence[ToolSpec] = (),
        tool_choice: ToolChoice = "auto",
        sampling: Sampling | None = None,
        reasoning: ReasoningEffort | None = None,
        timeout_s: float | None = None,
        repair: Repair | None = None,
        provider_options: Mapping[str, Mapping[str, Any]] | None = None,
        metadata: Mapping[str, str] | None = None,
        max_response_bytes: int | None = None,
    ) -> AsyncStream:
        """Start a streaming generation.

        Returns:
            An `AsyncStream`: an async iterator of
            `StreamEvent`, usable as an async context manager,
            exposing the final result as `AsyncStream.result`.
        """
        request = self._build_request(
            messages,
            schema=schema,
            tools=tools,
            tool_choice=tool_choice,
            sampling=sampling,
            reasoning=reasoning,
            timeout_s=timeout_s,
            repair=repair,
            provider_options=provider_options,
            metadata=metadata,
            max_response_bytes=max_response_bytes,
        )
        resolved_route = self._resolve_route(target, route)
        return AsyncStream(self._routed_stream(request, resolved_route, stream=True))

    async def run_tools(
        self,
        messages: MessagesInput,
        *,
        tools: Sequence[Tool | Any],
        target: Target | None = None,
        route: Route | Target | Sequence[Target] | None = None,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        **kwargs: Any,
    ) -> Generation:
        """Generate, dispatching any tools the model calls, until it answers.

        Tools run sequentially, and a tool that raises becomes an error-flagged result the
        model can react to rather than an exception the caller must handle.

        Args:
            messages: The starting conversation.
            tools: Callables or `tool()`-decorated tools.
            target: A single target, as for `generate()`.
            route: A route, as for `generate()`.
            max_rounds: Maximum tool rounds before giving up.
            **kwargs: Forwarded to `generate()`.

        Returns:
            The final `Generation`, once the model stops
            calling tools.

        Raises:
            anyinfer.errors.ToolLoopError: If the model calls an unknown tool, or the round
                budget is exhausted.
        """
        registry = ToolRegistry(list(tools))
        conversation: list[Message] = list(_coerce_messages(messages))

        for _ in range(max_rounds):
            result = await self.generate(
                conversation,
                target=target,
                route=route,
                tools=registry.specs,
                **kwargs,
            )
            if result.finish_reason != "tool_calls" or not result.tool_calls:
                return result

            outputs = [await registry.dispatch(call) for call in result.tool_calls]
            conversation.extend(build_tool_turn(result.tool_calls, outputs))

        raise ToolLoopError(
            f"the tool loop ran {max_rounds} rounds without a final answer",
            hint="raise max_rounds, or simplify the tools so the model converges",
        )

    def _build_request(
        self,
        messages: MessagesInput,
        *,
        schema: SchemaSpec | SupportsJSONSchema | Mapping[str, Any] | None,
        tools: Sequence[ToolSpec],
        tool_choice: ToolChoice,
        sampling: Sampling | None,
        reasoning: ReasoningEffort | None,
        timeout_s: float | None,
        repair: Repair | None,
        provider_options: Mapping[str, Mapping[str, Any]] | None,
        metadata: Mapping[str, str] | None,
        max_response_bytes: int | None,
    ) -> GenerationRequest:
        spec = SchemaSpec.coerce(schema) if schema is not None else None
        request = GenerationRequest(
            messages=_coerce_messages(messages),
            schema=spec,
            tools=tuple(tools),
            tool_choice=tool_choice,
            sampling=sampling or Sampling(),
            reasoning=reasoning,
            timeout_s=timeout_s,
            repair=repair or self._default_repair,
            provider_options=dict(provider_options or {}),
            metadata=dict(metadata or {}),
        )
        if max_response_bytes is not None:
            # None means "use the dataclass default cap", so it cannot be passed through.
            request = replace(request, max_response_bytes=max_response_bytes)
        return request

    def budget(
        self,
        messages: MessagesInput,
        *,
        target: Target,
        schema: SchemaSpec | SupportsJSONSchema | Mapping[str, Any] | None = None,
        tools: Sequence[ToolSpec] = (),
        sampling: Sampling | None = None,
        output_reserve_tokens: int | None = None,
    ) -> ContextBudget:
        """Compute the context budget for a request without sending it.

        This is the preflight calculator: apps assembling large prompts read
        `remaining_tokens` to decide how
        much more material fits, instead of hand-rolling window arithmetic per provider.
        Pure computation — no request is issued, no network is touched; capabilities come
        from the catalog plus whatever discovery or probes have already been recorded.

        Args:
            messages: The conversation as assembled so far.
            target: The target to budget against.
            schema: Structured-output schema the real request will carry, if any.
            tools: Tools the real request will offer, if any.
            sampling: Sampling controls; ``max_output_tokens`` shapes the output reserve.
            output_reserve_tokens: Overrides the derived output reserve.

        Returns:
            The computed `ContextBudget`. When the
            target's context window is unknown, the budget's verdict is ``None`` — never
            a guess.
        """
        request = self._build_request(
            messages,
            schema=schema,
            tools=tools,
            tool_choice="auto",
            sampling=sampling,
            reasoning=None,
            timeout_s=None,
            repair=None,
            provider_options=None,
            metadata=None,
            max_response_bytes=None,
        )
        resolved = self.resolve(target)
        descriptor = self._pool.descriptor_for(resolved.provider_id)
        capabilities = self._capabilities_for(descriptor, resolved)
        return build_context_budget(
            request,
            capabilities,
            estimator=self._estimator,
            calibration=descriptor.token_calibration,
            output_reserve_tokens=output_reserve_tokens,
        )

    def _capabilities_for(
        self, descriptor: ProviderDescriptor, resolved: ResolvedTarget
    ) -> ModelCapabilities:
        """Assemble capabilities, layering in catalog alias facts when one was used.

        A catalog alias entry may pin a context window or output ceiling for its target;
        those enter the assembly at ``catalog`` provenance, so live discovery and probes
        still win.
        """
        capabilities = self._capabilities.capabilities_for(
            descriptor,
            resolved.model,
            locality=self._pool.locality_for(resolved.provider_id),
        )
        if resolved.via_alias and self._catalog is not None and (
            self._catalog.has_alias(resolved.via_alias)
        ):
            entry = self._catalog.alias(resolved.via_alias).targets.get(resolved.provider_id)
            if entry is not None:
                capabilities = _overlay_catalog_windows(capabilities, entry)
        return capabilities

    def _resolve_route(
        self,
        target: Target | None,
        route: Route | Target | Sequence[Target] | None,
    ) -> Route:
        """Pick the route in force: explicit route, explicit target, then the default.

        ``route`` accepts the flexible spellings `Route.coerce()` understands — a
        `Route`, one target string, or a sequence of targets forming a fallback chain.
        """
        if route is not None:
            return Route.coerce(route)
        if target is not None:
            return Route(targets=(target,))
        if self._default_route is not None:
            return self._default_route
        raise _missing_target_error(self._pool.configured_ids)

    # ---- the routed loop -------------------------------------------------------------

    async def _routed_stream(
        self,
        request: GenerationRequest,
        route: Route,
        *,
        stream: bool,
    ) -> AsyncIterator[StreamEvent]:
        """Run the route and yield its events."""
        request_id = uuid.uuid4().hex
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

        def unvisited_content_chain() -> list[Target]:
            return [
                t for t in route.content_policy_targets if str(self.resolve(t)) not in visited
            ]

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

            adapter = await self._pool.get(resolved.provider_id)
            descriptor = self._pool.descriptor_for(resolved.provider_id)
            capabilities = self._capabilities_for(descriptor, resolved)
            redirected_now = False

            for attempt_number in range(1, route.retry.max_attempts + 1):
                self._emit(AttemptStarted(request_id, resolved, attempt_number))
                buffer = AttemptBuffer(target=resolved)
                emitted_content = False

                try:
                    async for event in self._run_attempt(
                        request=request,
                        resolved=resolved,
                        adapter=adapter,
                        descriptor=descriptor,
                        capabilities=capabilities,
                        buffer=buffer,
                        request_id=request_id,
                        stream=stream,
                        attempts=attempts,
                        content_chain=(
                            unvisited_content_chain
                            if route.content_policy_targets and not content_redirected
                            else None
                        ),
                    ):
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
                        FallbackTriggered(
                            request_id, from_target=resolved, to_target=pending[0]
                        )
                    )
                    break
                except ProviderError as error:
                    last_error = error
                    retryable = route.retry.should_retry(error)
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

        failure = AllTargetsFailedError(
            _failure_detail(attempts, last_error),
            attempts=tuple(attempts),
            hint=_failure_hint(attempts),
        )
        self._emit(RequestFailed(request_id, failure.snapshot()))
        raise failure

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
        content_chain: Callable[[], list[Target]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Run one attempt against one target, including the schema repair loop.

        Repair re-runs *this* target rather than the route: a schema violation says
        something about the model, not the endpoint's availability.

        ``content_chain``, when supplied, is consulted after a ``content_filter``
        finish: a non-empty chain raises `_ContentPolicyRedirect` instead of
        completing, and the router re-dispatches to that chain.
        """
        if self._context_gate:
            # A ContextLengthError raised here follows the exact path a provider-reported
            # overflow would: the default retry predicate declines it, and the route
            # redirects to context_window_targets — minus the round trip (L6).
            check_context_fit(
                request,
                capabilities,
                estimator=self._estimator,
                calibration=descriptor.token_calibration,
                provider=resolved.provider_id,
                model=resolved.model,
            )
            self._emit(
                UsageEstimated(
                    request_id, resolved, "input_tokens", "pre-dispatch context-gate estimate"
                )
            )

        current = request
        repair_budget, repair_clamp_reason = _repair_budget(request, descriptor)
        if repair_clamp_reason is not None:
            self._emit(
                ParameterDropped(
                    request_id, resolved, "repair.max_attempts", repair_clamp_reason
                )
            )
        repair_attempts = 0
        yielded_content = False

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
            )
            if repair_attempts == 0:
                for parameter, reason in dropped_parameters(current, descriptor):
                    self._emit(ParameterDropped(request_id, resolved, parameter, reason))

            saw_usage_event = False
            try:
                async with asyncio.timeout(current.effective_timeout_s):
                    async for event in adapter.generate(wire):
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
                    f"attempt against {resolved} timed out after "
                    f"{current.effective_timeout_s:g}s",
                    provider=resolved.provider_id,
                    phase="stream" if stream else "generate",
                    hint="raise timeout_s, or choose a faster model",
                ) from None

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
                if self._retain_raw:
                    active_buffer.raw = final.raw

            if (
                content_chain is not None
                and active_buffer.finish_reason == "content_filter"
                and not (stream and yielded_content)
            ):
                # A refusal with a configured content-policy chain redirects instead of
                # completing — but never after the consumer has already seen streamed
                # text from this attempt, where a silent restart would contradict it.
                chain = content_chain()
                if chain:
                    attempts.append(
                        AttemptRecord(
                            resolved, "redirected", timing=active_buffer.build_timing()
                        )
                    )
                    raise _ContentPolicyRedirect(chain)

            structured, errors = self._validate(current, active_buffer)

            if errors and repair_attempts < repair_budget:
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
                raise SchemaViolationError(
                    f"response did not match the required schema: {errors[0]}",
                    raw_text=active_buffer.text,
                    errors=errors,
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
            )
            self._emit(
                AttemptCompleted(
                    request_id, resolved, result.usage, timing, result.finish_reason
                )
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
            repair_attempts=repair_attempts,
            attempts=attempts,
            warnings=tuple(buffer.warnings),
            raw=buffer.raw,
        )

    def _emit(self, event: TelemetryEvent) -> None:
        """Dispatch a telemetry event when anyone is listening."""
        if self._events.has_observers:
            self._events.emit(event)


async def _collect_diagnostics(
    adapter: ProviderAdapter, descriptor: ProviderDescriptor
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


def _structured_candidate(
    request: GenerationRequest, buffer: AttemptBuffer
) -> Any | None:
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


def _overlay_catalog_windows(
    capabilities: ModelCapabilities, entry: TargetEntry
) -> ModelCapabilities:
    """Layer a catalog alias entry's window facts in at ``catalog`` provenance.

    Field-targeted rather than a full overlay so an entry that pins only a window can
    never disturb features or pricing.
    """
    if entry.context_window:
        candidate = Sourced(entry.context_window, "catalog")
        if candidate.outranks(capabilities.context_window):
            capabilities = replace(capabilities, context_window=candidate)
    if entry.max_output_tokens:
        candidate = Sourced(entry.max_output_tokens, "catalog")
        if candidate.outranks(capabilities.max_output_tokens):
            capabilities = replace(capabilities, max_output_tokens=candidate)
    return capabilities


def _parse_overrides(
    overrides: Mapping[str, ModelCapabilities] | None,
    registry: ProviderRegistry,
) -> dict[str, dict[str, ModelCapabilities]]:
    """Group ``"provider:model"``-keyed overrides by canonical provider id.

    Raises:
        ConfigError: On a key without a model part, or an unknown provider.
    """
    parsed: dict[str, dict[str, ModelCapabilities]] = {}
    for target, caps in (overrides or {}).items():
        provider, sep, model = target.partition(":")
        if not sep or not model:
            raise ConfigError(
                f"capability override key {target!r} is not of the form 'provider:model'",
                hint="overrides are per concrete model; aliases cannot be overridden",
            )
        parsed.setdefault(registry.resolve_alias(provider), {})[model] = caps
    return parsed


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


class AsyncStream:
    """An async iterator over stream events, with the final result attached.

    Supports the three consumption shapes the design targets: iterate deltas, watch for the
    first-token mark and then read the result, or ignore events and read the result.
    """

    def __init__(self, source: AsyncIterator[StreamEvent]) -> None:
        self._source = source
        self._result: Generation | None = None
        self._closed = False

    def __aiter__(self) -> AsyncStream:
        """Iterate stream events."""
        return self

    async def __anext__(self) -> StreamEvent:
        """Yield the next event, capturing the result when the stream ends."""
        event = await self._source.__anext__()
        if isinstance(event, StreamEnded):
            self._result = event.result
        return event

    async def __aenter__(self) -> AsyncStream:
        """Enter a context that guarantees the stream is closed."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the underlying generator, cancelling any in-flight request."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the stream early, releasing the provider connection."""
        if self._closed:
            return
        self._closed = True
        aclose = getattr(self._source, "aclose", None)
        if aclose is not None:
            await aclose()

    @property
    def result(self) -> Generation:
        """The final result.

        Raises:
            RuntimeError: If the stream has not been fully consumed yet.
        """
        if self._result is None:
            raise RuntimeError(
                "stream result is not available until the stream has been consumed; "
                "iterate the stream to completion first"
            )
        return self._result

    async def collect(self) -> Generation:
        """Drain the stream and return the final result."""
        async for _ in self:
            pass
        return self.result
