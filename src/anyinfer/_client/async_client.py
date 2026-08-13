"""The async core: routing, assembly, validation, repair, and telemetry.

This is the real implementation; `Client` is a synchronous facade over it. The routed loop
in `AsyncClient.stream()` is the single place retries, fallback, health gating, timing, and
schema repair happen—never in an adapter.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import math
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from .._usage import merge_usage
from ..arena import ArenaResult, Candidate, candidate_envelope, select_candidates
from ..benchmark import (
    BENCHMARK_OUTPUT_TOKENS,
    BENCHMARK_PROMPT_TOKENS,
    BenchmarkSample,
    Measurement,
    MeasurementStore,
    benchmark_prompt,
    identity_for,
    measurement_from,
)
from ..capabilities.assemble import CapabilityStore
from ..capabilities.budget import ContextBudget, build_context_budget
from ..capabilities.cache import CachePlan, plan_cache
from ..capabilities.estimate import HeuristicTokenEstimator, TokenEstimator
from ..capabilities.gating import check_context_fit
from ..capabilities.ledger import SpendLedger, SpendTotals
from ..capabilities.pricing import (
    TRUSTED_PROVENANCE,
    CostEstimate,
    compute_operation_cost,
    with_cost,
)
from ..capabilities.pricing_table import PricingTable
from ..capabilities.probes import (
    DEFAULT_PROBE_FEATURES,
    PROBE_MAX_OUTPUT_TOKENS,
    PROBE_SCHEMA,
    PROBE_TOOL,
    PROBEABLE_FEATURES,
    EmbeddingProbeReport,
    FeatureProbe,
    ProbeOutcome,
    ProbeReport,
    mechanism_for,
    probe_prompt,
    probed_features,
)
from ..catalog.model import Catalog, TargetEntry
from ..catalog.resolve import load_default_catalog, resolve_target
from ..compare import EmbeddingTargetComparison, TargetComparison
from ..context.select import select as select_context
from ..context_request import ContextRequest, ContextSummary
from ..credentials import ResolverChain
from ..errors import (
    AllTargetsFailedError,
    AnyInferError,
    ConfigError,
    ContextLengthError,
    ProviderError,
    ProviderUnavailableError,
    SchemaViolationError,
    SpendLimitError,
    StreamProtocolError,
    ToolLoopError,
    TransportError,
    UnsupportedInputError,
)
from ..events.observers import EventDispatcher, Observer
from ..events.telemetry import (
    ArenaCompleted,
    AttemptCompleted,
    AttemptStarted,
    CachePlanned,
    DownloadProgress,
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
from ..local.hardware import HardwareProfile, probe_signature
from ..local.metrics import ResourceSample, SystemSampler
from ..local.services import PULL_TIMEOUT_S, PullReport, PullRequest
from ..local.store import ModelStore, RemovalReport, ResolvedModel, StoreEntry
from ..local.tuning import Posture
from ..local.variants import VariantPrefs
from ..manifest import DroppedParameter, ManifestBuilder, RunManifest
from ..providers.base import (
    AdapterFinal,
    GeneratesText,
    ProviderAdapter,
    ProviderLifecycle,
    aclosing_if_supported,
)
from ..registry import ProviderDescriptor, ProviderRegistry, default_registry
from ..routing.attempts import AttemptBuffer
from ..routing.health import HealthCache
from ..routing.limits import AttemptPacing, RateLimiter
from ..routing.policy import Retry, Route, backoff_delay
from ..schema.mechanism import MechanismRung, choose_mechanism
from ..schema.partial import partial_object
from ..schema.repair import build_repair_messages
from ..schema.validate import extract_json, validate
from ..session import Session
from ..types.capabilities import (
    DiscoveredModel,
    Feature,
    Health,
    ModelCapabilities,
    Sourced,
    TokenCalibration,
)
from ..types.events import (
    AttemptFailed,
    StreamEnded,
    StreamEvent,
    TextDelta,
    TimingMark,
    ToolCallDelta,
    UsageUpdate,
    is_content_event,
)
from ..types.messages import (
    AudioPart,
    DocumentPart,
    ImagePart,
    Message,
    Text,
    system,
    user,
)
from ..types.operations import (
    DEFAULT_MAX_EMBEDDING_RESPONSE_BYTES,
    DEFAULT_MAX_RERANK_RESPONSE_BYTES,
    BatchPolicy,
    EmbeddingCapabilities,
    EmbeddingInputIntent,
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingSpace,
    InferenceOperation,
    RerankDocument,
    RerankRequest,
    RerankResult,
)
from ..types.requests import (
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_MAX_INPUT_PART_BYTES,
    ArenaPolicy,
    CachePolicy,
    GenerationRequest,
    HistoryPolicy,
    ReasoningEffort,
    Repair,
    ResolvedTarget,
    Sampling,
    SchemaSpec,
    SpendPolicy,
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
    Usage,
)
from ..verification import (
    VERIFY_MAX_OUTPUT_TOKENS,
    VERIFY_PROMPT,
    VERIFY_REASONING_OUTPUT_TOKENS,
    VERIFY_SCHEMA,
    Verification,
    excerpt,
    judge_reply,
)
from .models import (
    CatalogView,
    acquire_catalog_model,
    build_catalog_view,
    locate_catalog_model,
)
from .operations import dispatch_embed, dispatch_rerank
from .providers import AdapterPool, ProviderSettings
from .tools import (
    DEFAULT_MAX_ROUNDS,
    Tool,
    ToolMemo,
    ToolRegistry,
    build_tool_turn,
)
from .wire import build_wire_request, dropped_parameters

__all__ = ["AsyncClient", "AsyncStream", "MessagesInput"]

MessagesInput = str | Message | Sequence[Message]
"""What callers may pass as ``messages``: a bare prompt, one message, or a sequence."""

_spend_prechecked: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "anyinfer_spend_prechecked", default=False
)


def _coerce_messages(value: MessagesInput) -> tuple[Message, ...]:
    """Normalize the accepted message spellings into a tuple."""
    if isinstance(value, str):
        return (user(value),)
    if isinstance(value, Message):
        return (value,)
    return tuple(value)


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
        history: Conversation-compaction policy applied when a request outgrows its
            target's window. ``None`` — the default; never compacts. This is the
            client's half of the overflow answer; ``Route.context_window_targets`` is
            the other half, and the policy's ``mode`` decides which is tried first.
        spend: Ceiling on what this client may spend, checked before dispatch.
            ``None`` — the default; never refuses anything. Not an organization
            quota: it governs this client object in this process and nothing else.
        ledger: Spend rollup to record into. One is created automatically when
            ``spend`` is set; supply your own to share a total between clients or to
            read it without a policy in force.
        cache: Prompt-cache placement applied to every request that does not carry its
            own. ``None`` — the default; never engages a provider's cache, because
            caching changes what a provider bills and how long it keeps a copy of the
            prompt. A request's own ``cache`` overrides this.
            Every frontend built on this client inherits it.
        pricing_table: Model pricing supplying the ``catalog`` layer of capability
            assembly. Defaults to the table bundled with this release; pass the
            result of `fetch_pricing()` for newer numbers.
        manifests: Assemble a `RunManifest` for every call, reachable as
            `Generation.manifest`. On by default: it allocates one small object per
            in-flight request, writes nothing, sends nothing, and is content-free — the
            invited/uninvited line in this library has always been about spend and side
            effects, and a manifest has neither. Switch it off to skip the allocation
            entirely.
        manifest_payloads: Capture prompt, response, schema, and tool-call text into the
            manifest's ``payloads`` facet, redacted. Off by default and independent of
            observer payload opt-in, so a manifest cannot start carrying prompt text
            because some unrelated telemetry sink asked for it.
        capability_overrides: Deliberate corrections keyed by ``"provider:model"``.
            Every supplied field is applied at ``override`` provenance — the strongest
            layer, outranking discovery and probes, so a wrong upstream number can
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
        operation_routes: Mapping[str, Route] | None = None,
        observers: Sequence[Observer] | None = None,
        resolver: ResolverChain | None = None,
        retain_raw: bool = False,
        repair: Repair | None = None,
        use_default_catalog: bool = True,
        estimator: TokenEstimator | None = None,
        context_gate: bool = True,
        history: HistoryPolicy | None = None,
        cache: CachePolicy | None = None,
        arena: ArenaPolicy | None = None,
        arenas: Mapping[str, ArenaPolicy] | None = None,
        spend: SpendPolicy | None = None,
        ledger: SpendLedger | None = None,
        pricing_table: PricingTable | None = None,
        manifests: bool = True,
        manifest_payloads: bool = False,
        capability_overrides: Mapping[str, ModelCapabilities] | None = None,
        model_dir: Path | None = None,
    ) -> None:
        self._registry = registry or default_registry
        self._events = EventDispatcher(list(observers or []))
        if catalog is None and use_default_catalog:
            catalog = load_default_catalog()
        self._catalog = catalog
        self._pool = AdapterPool(
            list(providers or []),
            registry=self._registry,
            catalog=self._catalog,
            resolver=resolver,
            # Lifecycle telemetry from adapters (server start/stop, download progress)
            # flows through the same dispatcher as request-path events.
            events=self._emit,
        )
        self._default_route = route
        self._operation_routes: dict[str, Route] = dict(operation_routes or {})
        self._health = HealthCache()
        self._capabilities = CapabilityStore(
            pricing=pricing_table,
            overrides=_parse_overrides(capability_overrides, self._registry),
        )
        self._retain_raw = retain_raw
        self._default_repair = repair
        self._estimator: TokenEstimator = estimator or HeuristicTokenEstimator()
        self._context_gate = context_gate
        self._history = history
        self._cache = cache
        self._arena = arena
        self._arenas = dict(arenas or {})
        self._spend_policy = spend
        # A policy needs a running total to enforce a cumulative ceiling, so one is
        # created on demand; a caller who supplied their own keeps theirs.
        self._ledger = ledger or (SpendLedger() if spend is not None else None)
        if self._ledger is not None:
            self._events.subscribe(self._ledger)
        # Last cacheable-prefix signature per target, for the implicit-mode guard.
        # Bounded by the number of targets a client talks to, and content-free.
        self._cache_prefixes: dict[str, str] = {}
        self._manifests = manifests
        self._manifest_payloads = manifest_payloads
        # Builders in flight, keyed by request id, so `_emit` can route an event to the
        # run it belongs to without every emit site having to carry the handle.
        self._builders: dict[str, ManifestBuilder] = {}
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

    async def models(
        self, provider_id: str, *, operation: InferenceOperation | None = None
    ) -> Sequence[DiscoveredModel]:
        """List a provider's models, recording what they report about capabilities.

        Args:
            provider_id: The configured provider to list.
            operation: Keep only models *known* to serve this operation — via a
                discovered operation tag, or the descriptor's static embedding/rerank
                capability tables. A model whose operations are unknown is included only
                for ``"generation"`` on a generation-capable provider (the pre-filter
                behaviour); for embedding and rerank, unknown support is never guessed
                into the listing. ``None`` lists everything.
        """
        adapter = await self._pool.get(provider_id)
        models = await adapter.list_models()
        canonical = self._registry.resolve_alias(provider_id)
        self._capabilities.record_discovery(canonical, models)
        if operation is None:
            return models
        descriptor = self._pool.descriptor_for(provider_id)
        static_ids: frozenset[str] = frozenset()
        if operation == "embedding":
            static_ids = frozenset(descriptor.static_embedding_capabilities)
        elif operation == "rerank":
            static_ids = frozenset(descriptor.static_rerank_capabilities)

        def _serves(model: DiscoveredModel) -> bool:
            tagged = model.capabilities.operations if model.capabilities is not None else None
            if tagged is not None:
                return operation in tagged.value
            if model.id in static_ids:
                return True
            return operation == "generation" and "generation" in descriptor.operations

        return tuple(m for m in models if _serves(m))

    def operations_for(self, target: Target) -> frozenset[InferenceOperation]:
        """Which inference operations the resolved target is *known* to serve.

        Model-level facts win: a discovered operation tag, else membership in the
        descriptor's static embedding/rerank capability tables. A model with no
        model-level facts on a generation-capable provider reports ``{"generation"}`` —
        the assumption every listing made before operations existed — and never has
        embedding or rerank support guessed in.

        Args:
            target: A target string or catalog alias; resolved without dispatching.

        Raises:
            anyinfer.errors.ConfigError: If the target cannot be resolved at all.
        """
        resolved = self.resolve(target)
        capabilities = self._operation_capabilities(resolved)
        if capabilities is not None and capabilities.operations is not None:
            return capabilities.operations.value
        descriptor = self._pool.descriptor_for(resolved.provider_id)
        known: set[InferenceOperation] = set()
        if resolved.model in descriptor.static_embedding_capabilities:
            known.add("embedding")
        if resolved.model in descriptor.static_rerank_capabilities:
            known.add("rerank")
        if not known and "generation" in descriptor.operations:
            known.add("generation")
        return frozenset(known)

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

    def session(self, target: Target) -> Session:
        """Open a handle that lets a provider keep what it already knows.

        Every request is independent by default, which is right for one-shot work and
        wrong for a conversation. Providers that can carry state between turns each save
        something different — Copilot keeps the conversation server-side, llama.cpp keeps
        the model and its KV cache resident, Ollama keeps the model loaded, and a session
        is how a caller says "these requests belong together" without having to know which.

        A session never changes an answer; it is a performance and cost optimization.
        Opening one against a provider that cannot keep state is therefore allowed and
        merely inert: every request behaves exactly as it would have, and
        `Session.supported` and
        `Session.reuse` say so.

        ```python
        with client.session("copilot:auto") as chat:
            await client.generate("Summarize this report.", session=chat)
            await client.generate("Now list the risks.", session=chat)
        ```

        Args:
            target: The target this session's state belongs to. State is not portable, so
                a turn routed anywhere else runs without it.

        Returns:
            The `Session` handle.

        Raises:
            anyinfer.errors.ConfigError: If the target cannot be resolved.
        """
        resolved = self.resolve(target)
        descriptor = self._pool.descriptor_for(resolved.provider_id)
        return Session(resolved, supported=descriptor.supports_sessions)

    async def verify(
        self,
        target: Target,
        *,
        timeout_s: float = 60.0,
        operation: InferenceOperation = "generation",
    ) -> Verification:
        """Prove a target works by asking it something, end to end.

        `health()` answers "can I reach this endpoint", which is not the question behind a
        *Test connection* button: a credential can be valid for a model listing and not for
        inference, a model id can be a typo, a deployment can exist with no capacity, and a
        provider can answer fluently while never holding a schema. Only a real request
        distinguishes those, so this spends one — deliberately tiny, capped at
        `VERIFY_MAX_OUTPUT_TOKENS`
        output tokens, or
        `VERIFY_REASONING_OUTPUT_TOKENS`
        when the target is known to be a reasoning model and would otherwise spend the
        whole budget thinking before it said anything.

        Never raises for a provider problem: "this target is broken" is the answer to the
        question, not a failure to answer it. A malformed *target*, on the other hand, is
        the caller's mistake and still raises.

        Args:
            target: The target to verify. A catalog alias resolves as usual.
            timeout_s: Wall clock for the probe.
            operation: Which operation to prove. ``"embedding"`` embeds one tiny probe
                text and judges the vector; ``"rerank"`` ranks two probe documents.
                Both spend one deliberately small real request, exactly like the
                generation probe.

        Returns:
            The `Verification`, whose ``reached``
            and ``ok`` distinguish "unreachable" from "reachable but could not hold the
            shape".

        Raises:
            anyinfer.errors.ConfigError: If the target cannot be resolved at all.
        """
        resolved = self.resolve(target)
        started = time.monotonic()
        if operation != "generation":
            return await self._verify_operation(target, resolved, operation, timeout_s, started)
        try:
            # No retries and no fallback: a probe reports what this target did, and a
            # chain that quietly answered from somewhere else would report a working
            # connection the operator does not have.
            result = await self.generate(
                VERIFY_PROMPT,
                route=Route(targets=(target,), retry=Retry(max_attempts=1)),
                schema=VERIFY_SCHEMA,
                sampling=Sampling(
                    max_output_tokens=self._probe_output_budget(resolved), temperature=0.0
                ),
                timeout_s=timeout_s,
            )
        except SchemaViolationError as error:
            # It answered — just not in the shape asked for. That is a real and
            # separately-actionable state, so it is reported as reached-but-not-ok
            # rather than as a failure to connect.
            return Verification(
                target=resolved,
                ok=False,
                reached=True,
                latency_ms=(time.monotonic() - started) * 1000.0,
                detail=f"the provider answered, but not in the requested shape: {error.detail}",
                reply=excerpt(error.raw_text or ""),
                diagnostics=await self._safe_diagnostics(resolved.provider_id),
            )
        except (AllTargetsFailedError, ProviderError) as error:
            return Verification(
                target=resolved,
                ok=False,
                latency_ms=(time.monotonic() - started) * 1000.0,
                detail=_verification_detail(error),
                diagnostics=await self._safe_diagnostics(resolved.provider_id),
            )

        ok, detail, reply = judge_reply(result.structured, result.text)
        return Verification(
            # `result.target`, not the pre-request resolution: a provider that picks the
            # model itself has now picked one, and which one is the useful answer.
            target=result.target,
            ok=ok,
            reached=True,
            latency_ms=(time.monotonic() - started) * 1000.0,
            detail=detail,
            reply=reply,
            mechanism=result.structured_mechanism,
            usage=result.usage,
            diagnostics=await self._safe_diagnostics(result.target.provider_id),
        )

    async def _verify_operation(
        self,
        target: Target,
        resolved: ResolvedTarget,
        operation: InferenceOperation,
        timeout_s: float,
        started: float,
    ) -> Verification:
        """Verify an embedding or rerank target with one deliberately tiny real call.

        Same contract as the generation probe: no retries, no fallback, and a provider
        problem is the answer rather than an exception. A target whose provider does not
        declare the operation reports not-reached with the refusal's own hint.
        """
        try:
            if operation == "embedding":
                embedded = await self.embed(
                    ["anyinfer verification probe"],
                    route=Route(targets=(target,), retry=Retry(max_attempts=1)),
                    input_type="document",
                    timeout_s=timeout_s,
                    manifest=False,
                )
                dimensions = len(embedded.vectors[0])
                return Verification(
                    target=embedded.target,
                    ok=True,
                    reached=True,
                    latency_ms=(time.monotonic() - started) * 1000.0,
                    detail=f"embedded one probe text into {dimensions} dimensions",
                    usage=embedded.usage,
                    diagnostics=await self._safe_diagnostics(embedded.target.provider_id),
                )
            ranked = await self.rerank(
                "which document mentions verification",
                ["this one mentions verification", "an unrelated sentence about weather"],
                route=Route(targets=(target,), retry=Retry(max_attempts=1)),
                top_n=1,
                timeout_s=timeout_s,
                manifest=False,
            )
            ok = len(ranked.items) >= 1
            return Verification(
                target=ranked.target,
                ok=ok,
                reached=True,
                latency_ms=(time.monotonic() - started) * 1000.0,
                detail=(
                    "ranked two probe documents"
                    if ok
                    else "the provider returned no ranked items for two documents"
                ),
                usage=ranked.usage,
                diagnostics=await self._safe_diagnostics(ranked.target.provider_id),
            )
        except ConfigError as error:
            # A local refusal — the provider does not declare the operation, or the
            # request could never be sent. Nothing was spent; nothing was reached.
            return Verification(
                target=resolved,
                ok=False,
                reached=False,
                latency_ms=(time.monotonic() - started) * 1000.0,
                detail=error.detail,
                diagnostics=await self._safe_diagnostics(resolved.provider_id),
            )
        except (AllTargetsFailedError, ProviderError) as error:
            return Verification(
                target=resolved,
                ok=False,
                latency_ms=(time.monotonic() - started) * 1000.0,
                detail=_verification_detail(error),
                diagnostics=await self._safe_diagnostics(resolved.provider_id),
            )

    async def probe_embedding(
        self,
        target: Target,
        *,
        timeout_s: float = 30.0,
        record: bool = True,
    ) -> EmbeddingProbeReport:
        """Measure an embedding target with one tiny real call.

        Embedding capability tables only carry what a provider documents; a self-hosted
        or preset endpoint often documents nothing. This spends one deliberately small
        request and measures what came back — the vector length, and whether it was
        unit-normalized — recording both at ``probed`` provenance so later calls (and
        `capabilities_for` consumers) see measured facts instead of blanks.

        **This costs money and time**, exactly like `probe()`: opt-in, one round trip.

        Args:
            target: The embedding target to measure.
            timeout_s: Wall clock for the probe call.
            record: Store the findings at ``probed`` provenance.

        Returns:
            The `EmbeddingProbeReport` with the measured facts.

        Raises:
            anyinfer.errors.ConfigError: If the target cannot be resolved, or its
                provider does not declare the embedding operation.
            anyinfer.errors.AllTargetsFailedError: If the probe call itself failed.
        """
        result = await self.embed(
            ["anyinfer embedding probe"],
            route=Route(targets=(target,), retry=Retry(max_attempts=1)),
            input_type="document",
            timeout_s=timeout_s,
            manifest=False,
        )
        vector = result.vectors[0]
        norm = math.sqrt(sum(v * v for v in vector.values))
        normalized = abs(norm - 1.0) <= 1e-3
        capabilities = EmbeddingCapabilities(
            dimensions=len(vector), normalized=normalized
        )
        if record:
            self._capabilities.record_embedding_probe(
                result.target.provider_id, result.target.model, capabilities
            )
        return EmbeddingProbeReport(
            target=result.target,
            dimensions=len(vector),
            normalized=normalized,
            capabilities=capabilities,
            usage=result.usage,
        )

    async def probe(
        self,
        target: Target,
        *,
        features: Sequence[Feature] | None = None,
        timeout_s: float = 30.0,
        record: bool = True,
    ) -> ProbeReport:
        """Measure what a target actually supports, one tiny request per feature.

        The capability layer's third tier, and the only one that is a *measurement*. The
        catalog says what a model should support and discovery says what a provider
        claims; for the compatibility surface — every preset endpoint, every self-hosted
        OpenAI-compatible server — both are educated guesses, and a server that accepts
        ``response_format`` while ignoring it is indistinguishable from one that honors it
        until a schema silently stops being enforced.

        **This costs money and time**: one round trip per feature, four by default. It is
        opt-in for that reason, and normally run once when an application first configures
        an endpoint rather than on every start.

        A probe that settles nothing records nothing. A provider that accepts the request
        and answers something unexpected is `inconclusive`, because a weak model and an
        ignored parameter look identical in one reply.

        Args:
            target: The target to measure.
            features: Which features to test; defaults to
                `DEFAULT_PROBE_FEATURES`.
            timeout_s: Wall clock for each individual probe.
            record: Store the findings at ``probed`` provenance, so later requests choose
                mechanisms from measurement rather than assumption. Pass ``False`` to look
                without committing.

        Returns:
            The `ProbeReport`: per-feature outcomes,
            what was recorded, and what it cost.

        Raises:
            anyinfer.errors.ConfigError: If the target cannot be resolved, or a feature was
                named that no probe can settle.
        """
        resolved = self.resolve(target)
        selected = tuple(features) if features is not None else DEFAULT_PROBE_FEATURES
        unknown = [f for f in selected if f not in PROBEABLE_FEATURES]
        if unknown:
            names = ", ".join(str(f.name) for f in unknown)
            raise ConfigError(
                f"no probe can settle {names}",
                hint=(
                    f"probeable features are {', '.join(str(f.name) for f in PROBEABLE_FEATURES)}"
                ),
            )

        adapter = await self._pool.get(resolved.provider_id)
        if not isinstance(adapter, GeneratesText):
            raise ConfigError(
                f"provider {resolved.provider_id!r} does not support generation",
                provider=resolved.provider_id,
                hint="feature probes only apply to targets that generate text",
            )
        descriptor = self._pool.descriptor_for(resolved.provider_id)
        results: list[FeatureProbe] = []
        usage = Usage()
        for feature in selected:
            probe, spent = await self._probe_feature(
                adapter, descriptor, resolved, feature, timeout_s
            )
            results.append(probe)
            usage = usage.merge(spent)

        known = self._capabilities_for(descriptor, resolved).features
        merged = probed_features(known, tuple(results))
        capabilities = ModelCapabilities(features=merged) if merged is not None else None
        if record and capabilities is not None:
            self._capabilities.record_probe(descriptor.id, resolved.model, capabilities)
        return ProbeReport(
            target=resolved,
            probes=tuple(results),
            capabilities=capabilities,
            requests=len(results),
            usage=usage.normalized(),
        )

    async def _probe_feature(
        self,
        adapter: ProviderAdapter,
        descriptor: ProviderDescriptor,
        resolved: ResolvedTarget,
        feature: Feature,
        timeout_s: float,
    ) -> tuple[FeatureProbe, Usage]:
        """Run one probe against the adapter directly, bypassing the router.

        Deliberately not routed: a probe asks what *this* target does, so a retry or a
        fallback answering from somewhere else would record a measurement of the wrong
        model. It also has to force a mechanism the capability ladder would not choose —
        that is the entire point, which it does by handing the wire builder a synthetic
        capability set claiming exactly the feature under test.
        """
        wanted = Feature.STREAMING if feature is Feature.STREAMING else feature
        request = GenerationRequest(
            messages=(user(probe_prompt(feature)),),
            schema=SchemaSpec.coerce(PROBE_SCHEMA) if mechanism_for(feature) else None,
            tools=(PROBE_TOOL,) if feature is Feature.TOOLS else (),
            tool_choice="required" if feature is Feature.TOOLS else "auto",
            sampling=Sampling(max_output_tokens=PROBE_MAX_OUTPUT_TOKENS, temperature=0.0),
            timeout_s=timeout_s,
        )
        wire = build_wire_request(
            request,
            resolved,
            descriptor,
            capabilities=ModelCapabilities(features=Sourced(wanted, "probed")),
            stream=feature is Feature.STREAMING,
        )

        text_parts: list[str] = []
        content_events = 0
        tool_called = False
        usage = Usage()
        try:
            async with asyncio.timeout(timeout_s):
                async for event in adapter.generate(wire):
                    if isinstance(event, AdapterFinal):
                        if event.usage is not None:
                            usage = usage.merge(event.usage)
                        continue
                    if isinstance(event, UsageUpdate):
                        usage = usage.merge(event.usage)
                        continue
                    if is_content_event(event):
                        content_events += 1
                    if isinstance(event, TextDelta):
                        text_parts.append(event.text)
                    elif isinstance(event, ToolCallDelta):
                        tool_called = True
        except (ProviderError, TimeoutError) as error:
            # A rejection is the most informative answer a probe can get: the provider
            # said, in its own words, that it will not do this.
            detail = error.detail if isinstance(error, ProviderError) else "the probe timed out"
            outcome: ProbeOutcome = (
                "unsupported" if isinstance(error, ProviderError) else "inconclusive"
            )
            return FeatureProbe(feature, outcome, detail), usage

        return _judge_probe(feature, "".join(text_parts), content_events, tool_called), usage

    async def benchmark(
        self,
        target: Target,
        *,
        prompt_tokens: int = BENCHMARK_PROMPT_TOKENS,
        output_tokens: int = BENCHMARK_OUTPUT_TOKENS,
        timeout_s: float = 120.0,
        store: MeasurementStore | None = None,
        progress: Callable[[BenchmarkSample], None] | None = None,
    ) -> Measurement:
        """Measure what a target actually does, with one deterministic request.

        Capabilities describe a model; none of them says how fast it is *here*. For local
        inference that is the number that decides everything — the same weights on the same
        GPU differ by an order of magnitude depending on what else is resident and how many
        layers ended up offloaded, and it is the number an application needs to pick a
        default model or explain a slow session.

        Prefill and decode are reported separately, because a machine can be fast at one
        and slow at the other, and prefill throughput is reported *only* when the provider
        timed its own prefill phase. Deriving it from time-to-first-token would fold
        queueing and network latency into a figure labelled compute.

        **This costs one real request** of roughly ``prompt_tokens`` in and
        ``output_tokens`` out. Nothing is written anywhere unless ``store`` is passed.

        Args:
            target: The target to measure.
            prompt_tokens: Approximate prompt size. Large enough that prefill is a real
                phase rather than rounding error.
            output_tokens: Output cap. Decode throughput needs enough tokens to average
                over.
            timeout_s: Wall clock for the request.
            store: An application-owned store to record the result in. Omitted, the
                measurement is returned and forgotten.
            progress: Optional sink for live token-rate and local host-utilization samples.
                Token counts are estimated until the terminal provider usage arrives.

        Returns:
            The `Measurement`, whose rates are
            ``None`` where nothing could be measured rather than zero.

        Raises:
            anyinfer.errors.ConfigError: If the target cannot be resolved.
            anyinfer.errors.AllTargetsFailedError: If the request itself failed — an
                unmeasurable target is a failure, unlike an unverifiable one.
        """
        resolved = self.resolve(target)
        started = time.monotonic()
        estimated_bytes = 0
        decoding = False
        stop_sampling = asyncio.Event()
        sampler = (
            SystemSampler()
            if self._pool.locality_for(resolved.provider_id) == "local"
            else None
        )

        def publish(sample: BenchmarkSample) -> None:
            if progress is None:
                return
            try:
                progress(sample)
            except Exception:  # noqa: BLE001 — an observer must not break the measurement
                return

        async def sample_live() -> None:
            previous_tokens = 0
            previous_at = started
            while not stop_sampling.is_set():
                resources = (
                    await asyncio.to_thread(sampler.sample)
                    if sampler is not None
                    else ResourceSample()
                )
                now = time.monotonic()
                tokens = estimated_bytes // 4
                interval = now - previous_at
                if not decoding:
                    # No output during load/prefill is a measured zero, and preserving it
                    # makes the warm-up interval visible instead of starting the chart at
                    # the first decoded token.
                    rate = 0.0
                elif interval > 0 and tokens >= previous_tokens:
                    rate = (tokens - previous_tokens) / interval
                else:
                    rate = None
                publish(
                    BenchmarkSample(
                        elapsed_ms=(now - started) * 1000.0,
                        phase="decode" if decoding else "warmup",
                        estimated_output_tokens=tokens,
                        output_tokens_per_s=rate,
                        resources=resources,
                    )
                )
                previous_tokens, previous_at = tokens, now
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_sampling.wait(), timeout=0.25)

        sample_task = asyncio.create_task(sample_live()) if progress is not None else None
        try:
            async with self.stream(
                benchmark_prompt(prompt_tokens),
                route=Route(targets=(target,), retry=Retry(max_attempts=1)),
                sampling=Sampling(max_output_tokens=output_tokens, temperature=0.0),
                timeout_s=timeout_s,
            ) as stream:
                async for event in stream:
                    if isinstance(event, TextDelta):
                        decoding = True
                        estimated_bytes += len(event.text.encode("utf-8"))
            result = stream.result
        finally:
            stop_sampling.set()
            if sample_task is not None:
                await sample_task
        measurement = measurement_from(
            identity_for(
                result.target,
                endpoint=self._pool.base_url_for(resolved.provider_id),
                host=self._host_signature(resolved.provider_id),
            ),
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            ttft_ms=result.timing.first_token_ms,
            total_ms=result.timing.total_ms,
            decode_tokens_per_s=result.timing.output_tokens_per_s,
            prefill_ms=result.timing.phases.get("prefill_ms"),
            model_load_ms=result.timing.phases.get("model_load_ms"),
            measured_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        if store is not None:
            store.record(measurement)
        final_resources = (
            await asyncio.to_thread(sampler.sample)
            if sampler is not None
            else ResourceSample()
        )
        publish(
            BenchmarkSample(
                elapsed_ms=measurement.total_ms,
                phase="complete",
                estimated_output_tokens=measurement.output_tokens or estimated_bytes // 4,
                output_tokens_per_s=measurement.decode_tokens_per_s,
                resources=final_resources,
            )
        )
        return measurement

    def _host_signature(self, provider_id: str) -> str | None:
        """A machine signature for locally-executed targets, and nothing for the rest.

        A hosted provider's throughput has nothing to do with this computer, so recording
        this machine's specs beside it would invite a comparison that means nothing. Local
        detection is cached, and never triggered from here for a target it cannot describe.
        """
        if self._pool.locality_for(provider_id) != "local":
            return None
        try:
            return probe_signature()
        except Exception:  # noqa: BLE001 — an identity detail, never a reason to fail
            return None

    def _probe_output_budget(self, resolved: ResolvedTarget) -> int:
        """How many output tokens the probe may spend on this target.

        A thinking model produces its reasoning first and its answer second, so the
        ordinary 64-token ceiling truncates it mid-thought and the probe reports "the
        provider answered with empty text" — a connection failure the operator does not
        have.

        The reasoning flag decides this **whatever its provenance**, which is deliberately
        weaker than the rule the request path applies to sending a reasoning *parameter*.
        The two differ because their consequences differ. Sending a parameter a model does
        not have is a silently-ignored request field, so that decision waits for a
        trustworthy signal. This decision only moves a *ceiling*: a model that answers in
        six tokens spends six either way, and the larger cap costs more only for a model
        that was going to be truncated — that is, one that would have failed the probe
        regardless. Gating it on trusted provenance sounded careful and was not: every
        real Ollama model reports its features at ``default``, so the gate would never
        have fired for the thinking models it was written for.
        """
        try:
            descriptor = self._pool.descriptor_for(resolved.provider_id)
        except ConfigError:
            return VERIFY_MAX_OUTPUT_TOKENS
        capabilities = self._capabilities_for(descriptor, resolved)
        if Feature.REASONING in capabilities.features.value:
            return VERIFY_REASONING_OUTPUT_TOKENS
        return VERIFY_MAX_OUTPUT_TOKENS

    async def _safe_diagnostics(self, provider_id: str) -> tuple[Diagnostic, ...]:
        """Diagnostics for a verification report, tolerating an unconfigured provider."""
        try:
            return tuple(await self.diagnostics(provider_id))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a probe must report, not raise
            return ()

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

    async def pull_model(
        self,
        provider_id: str,
        model: str,
        *,
        progress: Callable[[TelemetryEvent], None] | None = None,
        timeout_s: float = PULL_TIMEOUT_S,
    ) -> PullReport:
        """Tell an engine that keeps its own store to make a model available.

        Distinct from `acquire_model()`, which fetches weights *this* library places and
        indexes. Some local engines — Ollama — already have a store, a registry, and a
        downloader; for those the useful operation is not "download these bytes" but "make
        yourself ready", and the bytes land in the engine's store under the engine's own
        name. Nothing is written to this client's model store and
        `locate_model()` will not find it, because it is not ours to find.

        Progress arrives as `DownloadProgress`
        events on the client's observers, and additionally on ``progress`` when one is
        given.

        Args:
            provider_id: The configured provider to pull on.
            model: The model name in that engine's namespace, e.g. ``"qwen3:8b"``.
            progress: An extra sink for progress events, for a caller that wants them
                without registering an observer.
            timeout_s: Wall clock for the whole transfer. Generous by default: a timeout
                that fires mid-download turns a slow link into a failure the user cannot
                act on.

        Returns:
            The `PullReport`, which distinguishes a
            transfer from a model that was already present.

        Raises:
            anyinfer.errors.ConfigError: If the provider is unknown, or cannot pull.
            anyinfer.errors.ModelNotFoundError: If the engine's registry has no such model.
            anyinfer.errors.LocalRuntimeError: If the engine is unreachable or the pull
                fails.
        """
        descriptor = self._pool.descriptor_for(provider_id)
        if descriptor.model_puller is None:
            raise ConfigError(
                f"{descriptor.id} does not manage its own model store",
                provider=descriptor.id,
                hint=(
                    "use client.acquire_model() for engines whose weights this library "
                    "downloads and places"
                ),
            )
        base_url = self._pool.base_url_for(provider_id)
        if not base_url:
            raise ConfigError(
                f"{descriptor.id} has no endpoint to pull from",
                provider=descriptor.id,
                hint="configure a base_url for this provider",
            )

        def sink(event: DownloadProgress) -> None:
            self._emit(event)
            if progress is not None:
                progress(event)

        report: PullReport = await descriptor.model_puller(
            PullRequest(
                model=model,
                base_url=base_url,
                timeout_s=timeout_s,
                transport=self._pool.transport_for(provider_id),
                progress=sink,
            )
        )
        # What the engine can serve just changed, so any cached listing is now stale.
        self._capabilities.invalidate(descriptor.id)
        return report

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
        against the index, because re-hashing forty gigabytes on every lookup would be
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
        history: HistoryPolicy | None = None,
        cache: CachePolicy | None = None,
        arena: ArenaPolicy | None = None,
        context: ContextRequest | None = None,
        provider_options: Mapping[str, Mapping[str, Any]] | None = None,
        metadata: Mapping[str, str] | None = None,
        max_response_bytes: int | None = None,
        max_input_part_bytes: int | None = None,
        max_input_bytes: int | None = None,
        session: Session | None = None,
        manifest: bool | None = None,
    ) -> Generation:
        """Generate a single result, draining the event stream internally.

        ``manifest`` overrides the client's manifest setting for this one call; ``None``
        inherits it.

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
            history=history,
            cache=cache,
            arena=arena,
            context=context,
            provider_options=provider_options,
            metadata=metadata,
            max_response_bytes=max_response_bytes,
            max_input_part_bytes=max_input_part_bytes,
            max_input_bytes=max_input_bytes,
        )
        arena_policy = self._effective_arena(arena, target, route)
        if arena_policy is not None:
            return await self._run_arena(request, arena_policy, manifest=manifest)
        resolved_route = self._resolve_route(target, route, session)
        return await self._generate_request(
            request, resolved_route, session=session, manifest=manifest
        )

    async def embed(
        self,
        inputs: str | Sequence[str],
        *,
        target: Target | None = None,
        route: Route | Target | Sequence[Target] | None = None,
        input_type: Literal["query", "document", "classification", "clustering"] | None = None,
        dimensions: int | None = None,
        expected_space: EmbeddingSpace | None = None,
        allow_incompatible_fallback: bool = False,
        batch: BatchPolicy | None = None,
        timeout_s: float | None = None,
        provider_options: Mapping[str, Mapping[str, Any]] | None = None,
        metadata: Mapping[str, str] | None = None,
        max_response_bytes: int | None = None,
        retain_raw: bool | None = None,
        manifest: bool | None = None,
    ) -> EmbeddingResult:
        """Embed one or more texts into vectors.

        Args:
            inputs: A single text, or an ordered sequence of texts to embed. Duplicates
                are preserved exactly.
            target: A single target, as for `generate()`.
            route: A fallback chain, as for `generate()`. Embedding fallback is
                safe-by-default: a fallback target is dispatched only when it is the
                identical ``provider:model`` as the route's primary target; anything else
                is refused before any request is sent, unless
                ``allow_incompatible_fallback`` is set.
            input_type: What the embedded text will be used for, when the target model
                distinguishes it.
            dimensions: Requested output dimensionality, for models supporting native
                dimensionality reduction.
            expected_space: An `anyinfer.EmbeddingSpace` the result must match; a
                successful-but-incompatible response is rejected rather than returned.
            allow_incompatible_fallback: Explicit opt-in permitting fallback to a target
                that cannot be proven to share the primary target's embedding space. Off
                by default because wrong-space vectors fail silently when compared; a
                result served this way always carries a warning naming both targets.
            batch: Core-owned batching policy. A request larger than the target's
                verified batch limit is split into ordered chunks and re-assembled in
                input order; an unknown limit is never guessed — see `anyinfer.BatchPolicy`.
            timeout_s: Per-attempt wall-clock budget.
            provider_options: Escape hatch, namespaced by provider id.
            metadata: Caller-supplied labels carried through telemetry.
            max_response_bytes: Hard cap on one provider response body.
            retain_raw: Keep the provider's raw response payload on the result. Defaults
                to the client's ``retain_raw`` setting.
            manifest: Overrides the client's manifest setting for this one call;
                ``None`` inherits it.

        Returns:
            The assembled `EmbeddingResult`.

        Raises:
            anyinfer.errors.AllTargetsFailedError: Every target failed.
            anyinfer.errors.ConfigError: The resolved target does not support embedding,
                its response fails the embedding-space safety check, or an incompatible
                fallback was refused before dispatch.
        """
        texts = (inputs,) if isinstance(inputs, str) else tuple(inputs)
        request = EmbeddingRequest(
            inputs=texts,
            input_type=input_type,
            dimensions=dimensions,
            expected_space=expected_space,
            allow_incompatible_fallback=allow_incompatible_fallback,
            timeout_s=timeout_s,
            max_response_bytes=max_response_bytes
            if max_response_bytes is not None
            else DEFAULT_MAX_EMBEDDING_RESPONSE_BYTES,
            metadata=metadata or {},
            provider_options=provider_options or {},
            batch=batch if batch is not None else BatchPolicy(),
        )
        resolved_route = self._resolve_operation_route(target, route, "embedding")
        request_id = uuid.uuid4().hex
        self._check_operation_spend(
            operation="embedding", route=resolved_route, texts=texts, request_id=request_id
        )
        try:
            return await dispatch_embed(
                request,
                resolved_route,
                pool=self._pool,
                registry=self._registry,
                catalog=self._catalog,
                configured_providers=self._pool.configured_ids,
                health=self._health,
                emit=self._emit,
                retain_raw=retain_raw if retain_raw is not None else self._retain_raw,
                manifest=self._manifests if manifest is None else manifest,
                anyinfer_version=_version(),
                capabilities_for=self._operation_capabilities,
                embedding_capabilities_for=self._embedding_capabilities_of,
                request_id=request_id,
            )
        except BaseException:
            if self._ledger is not None:
                self._ledger.release(request_id)
            raise

    async def rerank(
        self,
        query: str,
        documents: Sequence[str | RerankDocument],
        *,
        target: Target | None = None,
        route: Route | Target | Sequence[Target] | None = None,
        top_n: int | None = None,
        batch: BatchPolicy | None = None,
        timeout_s: float | None = None,
        provider_options: Mapping[str, Mapping[str, Any]] | None = None,
        metadata: Mapping[str, str] | None = None,
        max_response_bytes: int | None = None,
        return_documents: bool = False,
        retain_raw: bool | None = None,
        manifest: bool | None = None,
    ) -> RerankResult:
        """Rank documents by relevance to a query.

        Args:
            query: The query text every document is scored against.
            documents: Document texts, or `anyinfer.RerankDocument` values carrying
                caller-owned ids. Plain strings are assigned ids ``"0"``, ``"1"``, ...
                in order.
            target: A single target, as for `generate()`.
            route: A fallback chain, as for `generate()`.
            top_n: Return only the top N ranked items.
            batch: Core-owned batching policy. A rerank request larger than the target's
                verified document limit is refused rather than split, unless
                ``BatchPolicy.rerank_cross_batch`` explicitly accepts chunk-local
                rankings — scores from separate calls are not globally comparable.
            timeout_s: Per-attempt wall-clock budget.
            provider_options: Escape hatch, namespaced by provider id.
            metadata: Caller-supplied labels carried through telemetry.
            max_response_bytes: Hard cap on one provider response body.
            return_documents: Echo document text back on each ranked item.
            retain_raw: Keep the provider's raw response payload on the result. Defaults
                to the client's ``retain_raw`` setting.
            manifest: Overrides the client's manifest setting for this one call;
                ``None`` inherits it.

        Returns:
            The assembled `RerankResult`.

        Raises:
            anyinfer.errors.AllTargetsFailedError: Every target failed.
            anyinfer.errors.ConfigError: The resolved target does not support reranking,
                or its response names a document index outside the request.
        """
        docs = tuple(
            doc if isinstance(doc, RerankDocument) else RerankDocument(id=str(i), text=doc)
            for i, doc in enumerate(documents)
        )
        request = RerankRequest(
            query=query,
            documents=docs,
            top_n=top_n,
            timeout_s=timeout_s,
            max_response_bytes=max_response_bytes
            if max_response_bytes is not None
            else DEFAULT_MAX_RERANK_RESPONSE_BYTES,
            metadata=metadata or {},
            provider_options=provider_options or {},
            batch=batch if batch is not None else BatchPolicy(),
            return_documents=return_documents,
        )
        resolved_route = self._resolve_operation_route(target, route, "rerank")
        request_id = uuid.uuid4().hex
        self._check_operation_spend(
            operation="rerank", route=resolved_route, texts=None, request_id=request_id
        )
        try:
            return await dispatch_rerank(
                request,
                resolved_route,
                pool=self._pool,
                registry=self._registry,
                catalog=self._catalog,
                configured_providers=self._pool.configured_ids,
                health=self._health,
                emit=self._emit,
                retain_raw=retain_raw if retain_raw is not None else self._retain_raw,
                manifest=self._manifests if manifest is None else manifest,
                anyinfer_version=_version(),
                capabilities_for=self._operation_capabilities,
                request_id=request_id,
            )
        except BaseException:
            if self._ledger is not None:
                self._ledger.release(request_id)
            raise

    async def _generate_request(
        self,
        request: GenerationRequest,
        route: Route,
        *,
        session: Session | None = None,
        manifest: bool | None = None,
    ) -> Generation:
        """Run one ordinary route; arena branches reuse this exact path."""
        request_id, builder = self._new_run(request, route, manifest)
        # Closed explicitly: returning out of `async for` abandons the generator, and its
        # cleanup, which is what unregisters the run — would then wait for a collection.
        async with contextlib.aclosing(
            self._routed_stream(
                request,
                route,
                stream=False,
                session=session,
                request_id=request_id,
                builder=builder,
            )
        ) as events:
            async for event in events:
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
        history: HistoryPolicy | None = None,
        cache: CachePolicy | None = None,
        arena: ArenaPolicy | None = None,
        context: ContextRequest | None = None,
        provider_options: Mapping[str, Mapping[str, Any]] | None = None,
        metadata: Mapping[str, str] | None = None,
        max_response_bytes: int | None = None,
        max_input_part_bytes: int | None = None,
        max_input_bytes: int | None = None,
        session: Session | None = None,
        manifest: bool | None = None,
    ) -> AsyncStream:
        """Start a streaming generation.

        ``manifest`` overrides the client's manifest setting for this one call; ``None``
        inherits it.

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
            history=history,
            cache=cache,
            arena=arena,
            context=context,
            provider_options=provider_options,
            metadata=metadata,
            max_response_bytes=max_response_bytes,
            max_input_part_bytes=max_input_part_bytes,
            max_input_bytes=max_input_bytes,
        )
        arena_policy = self._effective_arena(arena, target, route)
        if arena_policy is not None:
            return AsyncStream(self._arena_stream(request, arena_policy), builder=None)
        resolved_route = self._resolve_route(target, route, session)
        request_id, builder = self._new_run(request, resolved_route, manifest)
        return AsyncStream(
            self._routed_stream(
                request,
                resolved_route,
                stream=True,
                session=session,
                request_id=request_id,
                builder=builder,
            ),
            builder=builder,
        )

    def _effective_arena(
        self,
        arena: ArenaPolicy | None,
        target: Target | None,
        route: Route | Target | Sequence[Target] | None,
    ) -> ArenaPolicy | None:
        """Resolve request, named, then client-default arena policy without routing."""
        if arena is not None:
            return arena
        if route is None and isinstance(target, str) and target in self._arenas:
            return self._arenas[target]
        if target is None and route is None:
            return self._arena
        return None

    async def _arena_stream(
        self, request: GenerationRequest, policy: ArenaPolicy
    ) -> AsyncGenerator[StreamEvent, None]:
        """Buffer arena branches, then expose only the selected answer as one stream."""
        result = await self._run_arena(request, policy)
        if result.text:
            yield TextDelta(result.text)
        yield StreamEnded(result)

    async def _run_arena(
        self,
        request: GenerationRequest,
        policy: ArenaPolicy,
        *,
        manifest: bool | None = None,
        spend_multiplier: int = 1,
    ) -> Generation:
        """Fan out fixed independent routes, then select after every branch completes."""
        arena_id = uuid.uuid4().hex
        self._reserve_arena_spend(arena_id, request, policy, candidate_multiplier=spend_multiplier)
        semaphore = asyncio.Semaphore(policy.concurrency)
        branch_request = replace(request, arena=None)

        async def candidate(target: str) -> tuple[Candidate, tuple[AttemptRecord, ...]]:
            started = time.monotonic()
            try:
                resolved = self.resolve(target)
            except (AnyInferError, ValueError) as exc:
                error = exc if isinstance(exc, AnyInferError) else ConfigError(str(exc))
                return (
                    Candidate(
                        ResolvedTarget("unresolved", target),
                        error=error.snapshot(),
                        elapsed_ms=(time.monotonic() - started) * 1000.0,
                    ),
                    (),
                )
            try:
                async with semaphore:
                    token = _spend_prechecked.set(True)
                    try:
                        generation = await self._generate_request(
                            branch_request,
                            Route(targets=(target,)),
                            manifest=manifest,
                        )
                    finally:
                        _spend_prechecked.reset(token)
                return (
                    Candidate(
                        resolved,
                        generation=generation,
                        valid=(generation.structured is not None)
                        if request.schema is not None
                        else None,
                        elapsed_ms=(time.monotonic() - started) * 1000.0,
                    ),
                    generation.attempts,
                )
            except AnyInferError as exc:
                attempts = exc.attempts if isinstance(exc, AllTargetsFailedError) else ()
                return (
                    Candidate(
                        resolved,
                        error=exc.snapshot(),
                        valid=False if request.schema is not None else None,
                        elapsed_ms=(time.monotonic() - started) * 1000.0,
                    ),
                    attempts,
                )

        try:
            rows = await asyncio.gather(*(candidate(target) for target in policy.targets))
            candidates = tuple(row[0] for row in rows)
            successful = tuple(item for item in candidates if item.generation is not None)
            if len(successful) < policy.min_candidates:
                attempts = tuple(attempt for row in rows for attempt in row[1])
                raise AllTargetsFailedError(
                    f"arena produced {len(successful)} candidates; "
                    f"{policy.min_candidates} required",
                    attempts=attempts,
                    hint="fix a failed target or lower arena min_candidates",
                )

            winner, strategy, agreement, degradation = select_candidates(
                candidates, policy, has_schema=request.schema is not None
            )
            calls = len(policy.targets)
            judge_generation: Generation | None = None
            if policy.strategy in ("judge", "synthesize"):
                judge_generation, judged_winner, judge_reason = await self._arena_verdict(
                    request, policy, candidates
                )
                calls += 1
                if policy.strategy == "judge" and judged_winner is not None:
                    winner = judged_winner
                    strategy = "judge"
                    degradation = None
                elif policy.strategy == "synthesize" and judge_generation is not None:
                    strategy = "synthesize"
                    degradation = None
                else:
                    degradation = judge_reason or "the arena verdict could not be applied"

            if winner is None or winner.generation is None:
                raise AllTargetsFailedError("arena had no selectable candidate")
            if degradation:
                self._emit(
                    ParameterDropped(
                        arena_id,
                        winner.target,
                        "arena.strategy",
                        degradation,
                    )
                )

            complete = len(successful) == len(candidates)
            usages = [item.generation.usage for item in successful if item.generation is not None]
            if judge_generation is not None:
                usages.append(judge_generation.usage)
            aggregate = merge_usage(usages) if complete else Usage()
            arena_result = ArenaResult(
                candidates=candidates,
                winner=winner,
                strategy=strategy,
                agreement=agreement,
                synthesized=(judge_generation if policy.strategy == "synthesize" else None),
                calls=calls,
                usage=aggregate,
                usage_complete=complete,
            )
            promoted = (
                judge_generation
                if policy.strategy == "synthesize" and judge_generation is not None
                else winner.generation
            )
            if promoted is None:
                raise RuntimeError("arena selected a candidate without a generation")
            self._emit(
                ArenaCompleted(
                    arena_id,
                    len(candidates),
                    arena_result.strategy,
                    arena_result.agreement,
                    arena_result.calls,
                    arena_result.memoized_tool_calls,
                    arena_result.synthesized is not None,
                )
            )
            return replace(promoted, arena=arena_result)
        finally:
            if self._ledger is not None:
                self._ledger.release(arena_id)

    async def _arena_verdict(
        self,
        request: GenerationRequest,
        policy: ArenaPolicy,
        candidates: tuple[Candidate, ...],
    ) -> tuple[Generation | None, Candidate | None, str | None]:
        """Run the one bounded judge or synthesis call and interpret its result."""
        default = (
            "Choose the strongest candidate. Return its one-based index and a brief reason."
            if policy.strategy == "judge"
            else "Synthesize one accurate answer from the candidates."
        )
        envelope = candidate_envelope(candidates, reveal_targets=policy.reveal_targets)
        prompt = f"{policy.instructions or default}\n\n{envelope}"
        schema: Mapping[str, Any] | SchemaSpec | None
        if policy.strategy == "judge":
            schema = {
                "type": "object",
                "properties": {
                    "pick": {"type": "integer", "minimum": 1},
                    "why": {"type": "string"},
                },
                "required": ["pick", "why"],
                "additionalProperties": False,
            }
        else:
            schema = request.schema
        judge_request = replace(
            request,
            messages=(user(prompt),),
            schema=SchemaSpec.coerce(schema) if schema is not None else None,
            tools=(),
            tool_choice="none",
            arena=None,
        )
        token = _spend_prechecked.set(True)
        try:
            generation = await self._generate_request(
                judge_request, Route(targets=(str(policy.judge_target),))
            )
        except AnyInferError as exc:
            return None, None, f"arena {policy.strategy} call failed: {exc.detail}"
        finally:
            _spend_prechecked.reset(token)
        if policy.strategy == "synthesize":
            return generation, None, None
        structured = generation.structured
        pick = structured.get("pick") if isinstance(structured, Mapping) else None
        if isinstance(pick, int) and 1 <= pick <= len(candidates):
            selected = candidates[pick - 1]
            if selected.generation is not None:
                return generation, selected, None
        return generation, None, "arena judge returned an unusable candidate index"

    def _reserve_arena_spend(
        self,
        arena_id: str,
        request: GenerationRequest,
        policy: ArenaPolicy,
        *,
        candidate_multiplier: int,
    ) -> None:
        """Reserve the summed high estimate before any arena branch dispatches."""
        spend = self._spend_policy
        if spend is None or not spend.active:
            return
        total = Decimal(0)
        unknown: list[str] = []
        weighted = [(target, candidate_multiplier) for target in policy.targets]
        if policy.judge_target is not None:
            weighted.append((policy.judge_target, 1))
        for target, multiplier in weighted:
            try:
                resolved = self.resolve(target)
                descriptor = self._pool.descriptor_for(resolved.provider_id)
                capabilities = self._capabilities_for(descriptor, resolved)
                estimate = self._estimate_request_cost(request, capabilities)
            except (AnyInferError, ValueError):
                estimate = None
            if estimate is None:
                unknown.append(str(target))
            else:
                total += estimate * multiplier
        spent = self._ledger.totals().cost if self._ledger is not None else Decimal(0)
        if unknown and spend.on_unknown == "refuse":
            raise SpendLimitError(
                f"the summed cost of this {len(policy.targets)}-candidate arena cannot "
                f"be estimated because pricing is unknown for {', '.join(unknown)}",
                limit_usd=spend.max_request_usd or spend.max_total_usd,
                spent_usd=spent,
                hint="supply trusted pricing or set spend on_unknown='allow'",
            )
        if spend.max_request_usd is not None and total > spend.max_request_usd:
            raise SpendLimitError(
                f"the summed estimate {total} for {len(policy.targets)} arena candidates "
                f"exceeds the per-request ceiling {spend.max_request_usd}",
                limit_usd=spend.max_request_usd,
                spent_usd=spent,
                estimated_usd=total,
            )
        if spend.max_total_usd is not None:
            ledger = self._ledger
            if ledger is None:
                raise RuntimeError("a cumulative spend policy requires a spend ledger")
            accepted, spent, reserved = ledger.reserve(arena_id, total, spend.max_total_usd)
            if not accepted:
                raise SpendLimitError(
                    f"this client has spent {spent}, reserved {reserved}, and this "
                    f"{len(policy.targets)}-candidate arena could cost {total}, above "
                    f"the total ceiling {spend.max_total_usd}",
                    limit_usd=spend.max_total_usd,
                    spent_usd=spent,
                    estimated_usd=total,
                )

    def _new_run(
        self, request: GenerationRequest, route: Route, manifest: bool | None
    ) -> tuple[str, ManifestBuilder | None]:
        """Mint a correlation id and, unless manifests are off, the builder to go with it.

        The builder is created *here* rather than inside the routed generator so a
        streaming caller holds it before the first event is produced, which is what makes
        a cancelled stream still able to answer for itself.
        """
        request_id = uuid.uuid4().hex
        enabled = self._manifests if manifest is None else manifest
        if not enabled:
            return request_id, None
        builder = ManifestBuilder(
            request,
            [str(t) for t in route.targets],
            request_id=request_id,
            anyinfer_version=_version(),
            payloads=self._manifest_payloads,
            estimator=self._estimator,
        )
        self._builders[request_id] = builder
        return request_id, builder

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
        arena_arg = kwargs.pop("arena", None)
        policy = self._effective_arena(arena_arg, target, route)
        if policy is not None:
            return await self._run_tools_arena(
                messages,
                tools=tools,
                policy=policy,
                max_rounds=max_rounds,
                kwargs=kwargs,
            )
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

    async def _run_tools_arena(
        self,
        messages: MessagesInput,
        *,
        tools: Sequence[Tool | Any],
        policy: ArenaPolicy,
        max_rounds: int,
        kwargs: Mapping[str, Any],
    ) -> Generation:
        """Run one isolated tool conversation per arena candidate."""
        template_registry = ToolRegistry(list(tools))
        base_request = self._build_request(
            messages,
            schema=kwargs.get("schema"),
            tools=template_registry.specs,
            tool_choice=kwargs.get("tool_choice", "auto"),
            sampling=kwargs.get("sampling"),
            reasoning=kwargs.get("reasoning"),
            timeout_s=kwargs.get("timeout_s"),
            repair=kwargs.get("repair"),
            history=kwargs.get("history"),
            cache=kwargs.get("cache"),
            provider_options=kwargs.get("provider_options"),
            metadata=kwargs.get("metadata"),
            max_response_bytes=kwargs.get("max_response_bytes"),
            arena=policy,
        )
        arena_id = uuid.uuid4().hex
        self._reserve_arena_spend(arena_id, base_request, policy, candidate_multiplier=max_rounds)
        memo = ToolMemo()
        semaphore = asyncio.Semaphore(policy.concurrency)

        async def branch(target: str) -> Candidate:
            started = time.monotonic()
            try:
                resolved = self.resolve(target)
            except (AnyInferError, ValueError) as exc:
                error = exc if isinstance(exc, AnyInferError) else ConfigError(str(exc))
                return Candidate(
                    ResolvedTarget("unresolved", target),
                    error=error.snapshot(),
                    rounds=0,
                    elapsed_ms=(time.monotonic() - started) * 1000.0,
                )
            registry = ToolRegistry(list(tools), memo=memo, memo_mode=policy.memoize_tools)
            conversation = list(_coerce_messages(messages))
            rounds = 0
            try:
                async with semaphore:
                    token = _spend_prechecked.set(True)
                    try:
                        for rounds in range(1, max_rounds + 1):
                            result = await self.generate(
                                conversation,
                                target=target,
                                tools=registry.specs,
                                arena=None,
                                **dict(kwargs),
                            )
                            if result.finish_reason != "tool_calls" or not result.tool_calls:
                                return Candidate(
                                    resolved,
                                    generation=result,
                                    valid=(result.structured is not None)
                                    if base_request.schema is not None
                                    else None,
                                    elapsed_ms=(time.monotonic() - started) * 1000.0,
                                    rounds=rounds,
                                    tool_calls=registry.dispatched,
                                )
                            outputs = [await registry.dispatch(call) for call in result.tool_calls]
                            conversation.extend(build_tool_turn(result.tool_calls, outputs))
                    finally:
                        _spend_prechecked.reset(token)
                raise ToolLoopError(
                    f"the tool loop ran {max_rounds} rounds without a final answer"
                )
            except AnyInferError as exc:
                return Candidate(
                    resolved,
                    error=exc.snapshot(),
                    valid=False if base_request.schema is not None else None,
                    elapsed_ms=(time.monotonic() - started) * 1000.0,
                    rounds=rounds,
                    tool_calls=registry.dispatched,
                )

        try:
            candidates = tuple(
                await asyncio.gather(*(branch(target) for target in policy.targets))
            )
            successful = tuple(item for item in candidates if item.generation is not None)
            if len(successful) < policy.min_candidates:
                raise AllTargetsFailedError(
                    f"arena produced {len(successful)} completed tool loops; "
                    f"{policy.min_candidates} required"
                )
            winner, strategy, agreement, degradation = select_candidates(
                candidates, policy, has_schema=base_request.schema is not None
            )
            calls = sum(item.rounds or 0 for item in candidates)
            verdict: Generation | None = None
            if policy.strategy in ("judge", "synthesize"):
                verdict, selected, reason = await self._arena_verdict(
                    base_request, policy, candidates
                )
                calls += 1
                if policy.strategy == "judge" and selected is not None:
                    winner, strategy, degradation = selected, "judge", None
                elif policy.strategy == "synthesize" and verdict is not None:
                    strategy, degradation = "synthesize", None
                else:
                    degradation = reason or "the arena verdict could not be applied"
            if winner is None or winner.generation is None:
                raise AllTargetsFailedError("arena had no selectable completed tool loop")
            if degradation:
                self._emit(
                    ParameterDropped(arena_id, winner.target, "arena.strategy", degradation)
                )
            complete = len(successful) == len(candidates)
            usages = [item.generation.usage for item in successful if item.generation is not None]
            if verdict is not None:
                usages.append(verdict.usage)
            arena_result = ArenaResult(
                candidates=candidates,
                winner=winner,
                strategy=strategy,
                agreement=agreement,
                synthesized=verdict if policy.strategy == "synthesize" else None,
                calls=calls,
                memoized_tool_calls=memo.hits,
                usage=merge_usage(usages) if complete else Usage(),
                usage_complete=complete,
            )
            promoted = (
                verdict
                if policy.strategy == "synthesize" and verdict is not None
                else winner.generation
            )
            if promoted is None:
                raise RuntimeError("arena selected a candidate without a generation")
            self._emit(
                ArenaCompleted(
                    arena_id,
                    len(candidates),
                    strategy,
                    agreement,
                    calls,
                    memo.hits,
                    verdict is not None and policy.strategy == "synthesize",
                )
            )
            return replace(promoted, arena=arena_result)
        finally:
            if self._ledger is not None:
                self._ledger.release(arena_id)

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
        history: HistoryPolicy | None,
        cache: CachePolicy | None,
        provider_options: Mapping[str, Mapping[str, Any]] | None,
        metadata: Mapping[str, str] | None,
        max_response_bytes: int | None,
        max_input_part_bytes: int | None = None,
        max_input_bytes: int | None = None,
        arena: ArenaPolicy | None = None,
        context: ContextRequest | None = None,
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
            history=history,
            cache=cache,
            arena=arena,
            context=context,
            provider_options=dict(provider_options or {}),
            metadata=dict(metadata or {}),
            max_input_part_bytes=(
                DEFAULT_MAX_INPUT_PART_BYTES
                if max_input_part_bytes is None
                else max_input_part_bytes
            ),
            max_input_bytes=(
                DEFAULT_MAX_INPUT_BYTES if max_input_bytes is None else max_input_bytes
            ),
        )
        if max_response_bytes is not None:
            # None means "use the dataclass default cap", so it cannot be passed through.
            request = replace(request, max_response_bytes=max_response_bytes)
        return request

    def spend(self) -> SpendTotals:
        """What this client has spent so far.

        Returns zeros; never ``None``, when no ledger is attached, so a caller reading
        this never has to branch on whether accounting was switched on. Check
        `SpendTotals.unknown_requests` before treating the figure as complete: requests
        against a target with no trusted pricing are counted there rather than being
        silently priced at zero.
        """
        return self._ledger.totals() if self._ledger is not None else SpendTotals()

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
            history=None,
            cache=None,
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

    async def compare(
        self,
        messages: MessagesInput | GenerationRequest,
        *,
        targets: Sequence[Target],
        schema: SchemaSpec | SupportsJSONSchema | Mapping[str, Any] | None = None,
        tools: Sequence[ToolSpec] = (),
        tool_choice: ToolChoice = "auto",
        sampling: Sampling | None = None,
        reasoning: ReasoningEffort | None = None,
        timeout_s: float | None = None,
        repair: Repair | None = None,
        history: HistoryPolicy | None = None,
        cache: CachePolicy | None = None,
        arena: ArenaPolicy | None = None,
        context: ContextRequest | None = None,
        provider_options: Mapping[str, Mapping[str, Any]] | None = None,
        metadata: Mapping[str, str] | None = None,
        max_response_bytes: int | None = None,
        refresh: bool = False,
    ) -> tuple[TargetComparison, ...]:
        """Compare how one request would behave across targets without generating.

        Results preserve caller order and are never ranked or consumed by routing. With
        ``refresh=False`` (the default), no adapter is constructed and no network is
        touched. ``refresh=True`` may list models to refresh discovered capabilities.
        """
        request = (
            messages
            if isinstance(messages, GenerationRequest)
            else self._build_request(
                messages,
                schema=schema,
                tools=tools,
                tool_choice=tool_choice,
                sampling=sampling,
                reasoning=reasoning,
                timeout_s=timeout_s,
                repair=repair,
                history=history,
                cache=cache,
                arena=arena,
                context=context,
                provider_options=provider_options,
                metadata=metadata,
                max_response_bytes=max_response_bytes,
            )
        )

        resolved_items: list[tuple[str, ResolvedTarget | None, str]] = []
        refresh_ids: list[str] = []
        for requested in targets:
            spelling = str(requested)
            try:
                resolved = self.resolve(requested)
                reason = self._pool.configuration_reason(resolved.provider_id) or ""
            except (ConfigError, ValueError) as exc:
                resolved_items.append((spelling, None, str(exc)))
                continue
            resolved_items.append((spelling, resolved, reason))
            if refresh and not reason and resolved.provider_id not in refresh_ids:
                refresh_ids.append(resolved.provider_id)

        refresh_errors: dict[str, str] = {}
        for provider_id in refresh_ids:
            try:
                await self.models(provider_id)
            except Exception as exc:  # noqa: BLE001 — failure is comparison data
                refresh_errors[provider_id] = str(exc)

        results: list[TargetComparison] = []
        policy = request.cache if request.cache is not None else self._cache
        for requested, item_resolved, reason in resolved_items:
            if item_resolved is None or reason:
                results.append(
                    TargetComparison(
                        requested=requested,
                        resolved=item_resolved,
                        resolvable=False,
                        reason=reason or "target could not be resolved",
                    )
                )
                continue
            resolved = item_resolved
            if resolved.provider_id in refresh_errors:
                results.append(
                    TargetComparison(
                        requested=requested,
                        resolved=resolved,
                        resolvable=False,
                        reason=(
                            "capability refresh failed: " + refresh_errors[resolved.provider_id]
                        ),
                    )
                )
                continue
            listed = self._capabilities.discovered_has_model(resolved.provider_id, resolved.model)
            if listed is False:
                results.append(
                    TargetComparison(
                        requested=requested,
                        resolved=resolved,
                        resolvable=False,
                        reason=(
                            f"model {resolved.model!r} was absent from the provider's "
                            "completed model listing"
                        ),
                    )
                )
                continue

            descriptor = self._pool.descriptor_for(resolved.provider_id)
            capabilities = self._capabilities_for(descriptor, resolved)
            target_request = request
            if request.context is not None:
                try:
                    target_request, _ = self._apply_context_request(
                        request,
                        capabilities=capabilities,
                        calibration=descriptor.token_calibration,
                        builder=None,
                        emit=False,
                    )
                except ConfigError as exc:
                    results.append(
                        TargetComparison(
                            requested=requested,
                            resolved=resolved,
                            resolvable=True,
                            reason=str(exc),
                        )
                    )
                    continue
            budget = build_context_budget(
                target_request,
                capabilities,
                estimator=self._estimator,
                calibration=descriptor.token_calibration,
            )
            trusted_window = (
                budget.context_window is not None
                and budget.context_window.provenance in TRUSTED_PROVENANCE
            )
            fits = budget.fits if trusted_window else None
            mechanism = None
            rungs: tuple[MechanismRung, ...] = ()
            if target_request.schema is not None:
                decision = choose_mechanism(capabilities, with_trail=True)
                mechanism, rungs = decision
            drops = tuple(
                DroppedParameter(str(resolved), parameter, why)
                for parameter, why in dropped_parameters(target_request, descriptor, capabilities)
            )
            cache_plan = (
                plan_cache(target_request, policy, capabilities, descriptor, self._estimator)
                if policy is not None and policy.active
                else None
            )
            provenance = {
                name: sourced.provenance
                for name, sourced in (
                    ("context_window", capabilities.context_window),
                    ("max_output_tokens", capabilities.max_output_tokens),
                    ("features", capabilities.features),
                    ("pricing", capabilities.pricing),
                    ("default_temperature", capabilities.default_temperature),
                    ("default_top_p", capabilities.default_top_p),
                )
                if sourced is not None
            }
            results.append(
                TargetComparison(
                    requested=requested,
                    resolved=resolved,
                    fits=fits,
                    budget=budget,
                    structured_mechanism=mechanism,
                    mechanism_rungs=rungs,
                    dropped=drops,
                    cache=cache_plan,
                    cost=budget.estimated_cost,
                    capability_provenance=provenance,
                )
            )
        return tuple(results)

    async def compare_embedding(
        self,
        inputs: str | Sequence[str],
        *,
        targets: Sequence[Target],
        input_type: EmbeddingInputIntent | None = None,
        refresh: bool = False,
    ) -> tuple[EmbeddingTargetComparison, ...]:
        """Compare how one embedding request would behave across targets, without dispatching.

        Results preserve caller order and are never ranked. With ``refresh=False`` (the
        default), no adapter is constructed and no network is touched; ``refresh=True``
        may list models to refresh discovered capabilities, exactly as `compare()`.
        """
        texts = (inputs,) if isinstance(inputs, str) else tuple(inputs)

        resolved_items: list[tuple[str, ResolvedTarget | None, str]] = []
        refresh_ids: list[str] = []
        for requested in targets:
            spelling = str(requested)
            try:
                resolved = self.resolve(requested)
                reason = self._pool.configuration_reason(resolved.provider_id) or ""
            except (ConfigError, ValueError) as exc:
                resolved_items.append((spelling, None, str(exc)))
                continue
            resolved_items.append((spelling, resolved, reason))
            if refresh and not reason and resolved.provider_id not in refresh_ids:
                refresh_ids.append(resolved.provider_id)

        refresh_errors: dict[str, str] = {}
        for provider_id in refresh_ids:
            try:
                await self.models(provider_id)
            except Exception as exc:  # noqa: BLE001 — failure is comparison data
                refresh_errors[provider_id] = str(exc)

        results: list[EmbeddingTargetComparison] = []
        for requested, item_resolved, reason in resolved_items:
            if item_resolved is None or reason:
                results.append(
                    EmbeddingTargetComparison(
                        requested=requested,
                        resolved=item_resolved,
                        resolvable=False,
                        reason=reason or "target could not be resolved",
                    )
                )
                continue
            resolved = item_resolved
            if resolved.provider_id in refresh_errors:
                results.append(
                    EmbeddingTargetComparison(
                        requested=requested,
                        resolved=resolved,
                        resolvable=False,
                        reason=(
                            "capability refresh failed: " + refresh_errors[resolved.provider_id]
                        ),
                    )
                )
                continue

            descriptor = self._pool.descriptor_for(resolved.provider_id)
            if "embedding" not in descriptor.operations:
                results.append(
                    EmbeddingTargetComparison(
                        requested=requested,
                        resolved=resolved,
                        resolvable=False,
                        reason=(
                            f"{resolved.provider_id!r} does not declare the embedding operation"
                        ),
                    )
                )
                continue

            model_capabilities = self._capabilities_for(descriptor, resolved)
            embedding_capabilities = (
                self._embedding_capabilities_of(resolved) or EmbeddingCapabilities()
            )

            fits: bool | None = None
            if embedding_capabilities.max_batch_inputs is not None:
                fits = len(texts) <= embedding_capabilities.max_batch_inputs
            if embedding_capabilities.max_input_tokens is not None:
                token_fits = all(
                    self._estimator.estimate(t).tokens <= embedding_capabilities.max_input_tokens
                    for t in texts
                )
                fits = token_fits if fits is None else (fits and token_fits)

            cost: CostEstimate | None = None
            floor_tokens = sum(self._estimator.estimate(t).floor for t in texts)
            planning_tokens = sum(self._estimator.estimate(t).tokens for t in texts)
            low_cost = compute_operation_cost(
                Usage(input_tokens=floor_tokens), model_capabilities, "embedding"
            )
            high_cost = compute_operation_cost(
                Usage(input_tokens=planning_tokens), model_capabilities, "embedding"
            )
            if low_cost is not None and high_cost is not None:
                currency = (
                    model_capabilities.pricing.value.currency
                    if model_capabilities.pricing is not None
                    else "USD"
                )
                cost = CostEstimate(low=low_cost, high=high_cost, currency=currency)

            notes: list[str] = []
            if (
                input_type is not None
                and embedding_capabilities.input_intents
                and input_type not in embedding_capabilities.input_intents
            ):
                notes.append(
                    f"{input_type!r} is not among the intents this model documents: "
                    f"{embedding_capabilities.input_intents}"
                )

            provenance = {
                name: sourced.provenance
                for name, sourced in (("pricing", model_capabilities.pricing),)
                if sourced is not None
            }

            results.append(
                EmbeddingTargetComparison(
                    requested=requested,
                    resolved=resolved,
                    fits=fits,
                    dimensions=embedding_capabilities.dimensions,
                    dimension_choices=embedding_capabilities.dimension_choices,
                    max_batch_inputs=embedding_capabilities.max_batch_inputs,
                    max_input_tokens=embedding_capabilities.max_input_tokens,
                    input_intents=embedding_capabilities.input_intents,
                    normalized=embedding_capabilities.normalized,
                    cost=cost,
                    capability_provenance=provenance,
                    notes=tuple(notes),
                )
            )
        return tuple(results)

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
        if (
            resolved.via_alias
            and self._catalog is not None
            and (self._catalog.has_alias(resolved.via_alias))
        ):
            entry = self._catalog.alias(resolved.via_alias).targets.get(resolved.provider_id)
            if entry is not None:
                capabilities = _overlay_catalog_windows(capabilities, entry)
        return capabilities

    def _resolve_route(
        self,
        target: Target | None,
        route: Route | Target | Sequence[Target] | None,
        session: Session | None = None,
    ) -> Route:
        """Pick the route in force: explicit route, explicit target, session, then default.

        ``route`` accepts the flexible spellings `Route.coerce()` understands — a
        `Route`, one target string, or a sequence of targets forming a fallback chain.

        An open session names a target of its own, and a caller who has one rarely wants to
        repeat it on every turn, so it stands in when nothing more specific was given. It
        never *overrides* anything: a session is about reuse, not routing.
        """
        if route is not None:
            return Route.coerce(route)
        if target is not None:
            return Route(targets=(target,))
        if session is not None:
            return Route(targets=(str(session.target),))
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

            adapter = await self._pool.get(resolved.provider_id)
            if not isinstance(adapter, GeneratesText):
                raise ConfigError(
                    f"provider {resolved.provider_id!r} does not support generation",
                    provider=resolved.provider_id,
                    hint="choose a target whose provider declares the 'generation' operation",
                )
            descriptor = self._pool.descriptor_for(resolved.provider_id)
            capabilities = self._capabilities_for(descriptor, resolved)
            if builder is not None:
                builder.note_capabilities(resolved, capabilities)
            try:
                target_request, context_summary = self._apply_context_request(
                    active,
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
        budget = build_context_budget(
            request, capabilities, estimator=self._estimator, calibration=calibration
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
            estimator=self._estimator,
            keep_recent=policy.keep_recent,
            keep_system=policy.keep_system,
        )
        if not compaction.changed:
            return None
        # A compaction event carries no request id, so the builder is handed over
        # explicitly rather than found by correlation.
        self._emit(compaction.event(), builder=builder)
        return request.with_messages(compaction.messages)

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
        capabilities: ModelCapabilities,
        calibration: TokenCalibration,
        builder: ManifestBuilder | None,
        emit: bool = True,
    ) -> tuple[GenerationRequest, ContextSummary | None]:
        """Reduce caller-approved documents for one resolved target before its gate."""
        policy = request.context
        if policy is None:
            return request, None
        max_tokens = policy.max_tokens
        if max_tokens is None:
            budget = build_context_budget(
                request,
                capabilities,
                estimator=self._estimator,
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
            estimator=self._estimator,
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
        self._check_spend(request, resolved, capabilities, request_id=request_id)

        if self._context_gate:
            # A ContextLengthError raised here follows the exact path a provider-reported
            # overflow would: the default retry predicate declines it, and the route
            # redirects to context_window_targets — minus the round trip.
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
            self._estimator,
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

    def _check_multimodal(
        self,
        request: GenerationRequest,
        resolved: ResolvedTarget,
        capabilities: ModelCapabilities,
    ) -> None:
        """Refuse only a trusted absence; unknown multimodal support stays unknown."""
        required: set[Feature] = set()
        for message in request.messages:
            for part in message.content:
                if isinstance(part, ImagePart):
                    required.add(Feature.VISION)
                elif isinstance(part, DocumentPart):
                    required.add(Feature.DOCUMENT)
                elif isinstance(part, AudioPart):
                    required.add(Feature.AUDIO_IN)
        if not required or capabilities.features.provenance not in TRUSTED_PROVENANCE:
            return
        missing = [feature for feature in required if feature not in capabilities.features.value]
        if missing:
            labels = ", ".join((feature.name or str(feature)).lower() for feature in missing)
            raise UnsupportedInputError(
                f"{resolved} does not support attached {labels} input",
                provider=resolved.provider_id,
                hint="choose a model whose capabilities include the required input modality",
            )

    def _operation_capabilities(self, resolved: ResolvedTarget) -> ModelCapabilities | None:
        """Assembled capabilities for one embed/rerank target, or ``None`` when unknown."""
        try:
            descriptor = self._pool.descriptor_for(resolved.provider_id)
            return self._capabilities_for(descriptor, resolved)
        except (AnyInferError, ValueError):
            return None

    def _resolve_operation_route(
        self,
        target: Target | None,
        route: Route | Target | Sequence[Target] | None,
        operation: InferenceOperation,
    ) -> Route:
        """The route one embed/rerank call uses.

        An explicit target or route always wins. With neither, the operation's own
        configured default applies before the generation ``default_route`` — so an
        embedding route is never selected for generation (different lookup entirely)
        and a generation default only serves an embed/rerank call if its targets
        actually declare the operation, which dispatch enforces.
        """
        if route is None and target is None:
            configured = self._operation_routes.get(operation)
            if configured is not None:
                return configured
        return self._resolve_route(target, route, None)

    def _embedding_capabilities_of(self, resolved: ResolvedTarget) -> Any:
        """Static embedding capabilities layered under anything a probe measured."""
        try:
            descriptor = self._pool.descriptor_for(resolved.provider_id)
        except (AnyInferError, ValueError):
            return None
        static = descriptor.static_embedding_capabilities.get(resolved.model)
        probed = self._capabilities.embedding_probed_for(
            resolved.provider_id, resolved.model
        )
        if static is not None and probed is not None:
            return static.overlay(probed)
        return probed if probed is not None else static

    def _check_operation_spend(
        self,
        *,
        operation: InferenceOperation,
        route: Route,
        texts: Sequence[str] | None,
        request_id: str,
    ) -> None:
        """Refuse an embed/rerank call that would cross this client's spending ceiling.

        Embedding costs are estimated from the caller's texts at the first target's
        trusted input rate. Rerank costs are never estimated — search-unit billing has no
        verified request-shape formula, and a guessed estimate would enforce nothing
        while appearing to — so ``on_unknown`` governs rerank calls.

        Raises:
            SpendLimitError: When a ceiling would be crossed, or when the cost cannot be
                known and the policy says not to spend blind.
        """
        policy = self._spend_policy
        if policy is None or not policy.active:
            return
        spent = self._ledger.totals().cost if self._ledger is not None else Decimal(0)

        estimate: Decimal | None = None
        if operation == "embedding" and texts is not None and route.targets:
            try:
                resolved = self.resolve(route.targets[0])
                capabilities = self._operation_capabilities(resolved)
            except (AnyInferError, ValueError):
                capabilities = None
            if capabilities is not None:
                tokens = sum(self._estimator.estimate(t).tokens for t in texts)
                estimate = compute_operation_cost(
                    Usage(input_tokens=tokens), capabilities, "embedding"
                )

        if estimate is None:
            if policy.on_unknown == "refuse":
                raise SpendLimitError(
                    f"the cost of this {operation} request cannot be estimated",
                    limit_usd=policy.max_request_usd or policy.max_total_usd,
                    spent_usd=spent,
                    hint=(
                        "this target has no trusted pricing (rerank costs are never "
                        "estimated); set on_unknown='allow' to send it anyway, or supply "
                        "pricing as a capability override"
                    ),
                )
            return

        if policy.max_request_usd is not None and estimate > policy.max_request_usd:
            raise SpendLimitError(
                f"this {operation} request could cost {estimate}, above the per-request "
                f"ceiling of {policy.max_request_usd}",
                limit_usd=policy.max_request_usd,
                spent_usd=spent,
                estimated_usd=estimate,
            )

        if policy.max_total_usd is not None:
            ledger = self._ledger
            if ledger is None:
                raise RuntimeError("a cumulative spend policy requires a spend ledger")
            accepted, spent, reserved = ledger.reserve(request_id, estimate, policy.max_total_usd)
            if not accepted:
                raise SpendLimitError(
                    f"this client has spent {spent}, reserved {reserved}, and this "
                    f"{operation} request could cost {estimate}, above the total "
                    f"ceiling {policy.max_total_usd}",
                    limit_usd=policy.max_total_usd,
                    spent_usd=spent,
                    estimated_usd=estimate,
                )

    def _check_spend(
        self,
        request: GenerationRequest,
        resolved: ResolvedTarget,
        capabilities: ModelCapabilities | None,
        *,
        request_id: str,
    ) -> None:
        """Refuse a request that would cross this client's spending ceiling.

        Runs before dispatch, so a refusal costs nothing. The estimate is the *high* end of
        the preflight range and is reported in the error, so a caller can see the arithmetic
        rather than being told only that they were declined.

        Raises:
            SpendLimitError: When a ceiling would be crossed, or when the cost cannot be
                known and the policy says not to spend blind.
        """
        if _spend_prechecked.get():
            return
        policy = self._spend_policy
        if policy is None or not policy.active:
            return

        spent = self._ledger.totals().cost if self._ledger is not None else Decimal(0)
        estimate = self._estimate_request_cost(request, capabilities)

        if estimate is None:
            if policy.on_unknown == "refuse":
                raise SpendLimitError(
                    f"the cost of a request to {resolved} cannot be estimated",
                    limit_usd=policy.max_request_usd or policy.max_total_usd,
                    spent_usd=spent,
                    hint=(
                        "this target has no trusted pricing; set on_unknown='allow' to "
                        "send it anyway, or supply pricing as a capability override"
                    ),
                )
            return

        if policy.max_request_usd is not None and estimate > policy.max_request_usd:
            raise SpendLimitError(
                f"a request to {resolved} could cost {estimate}, above the per-request "
                f"ceiling of {policy.max_request_usd}",
                limit_usd=policy.max_request_usd,
                spent_usd=spent,
                estimated_usd=estimate,
                hint="shorten the prompt, cap max_output_tokens, or raise max_request_usd",
            )

        if policy.max_total_usd is not None:
            ledger = self._ledger
            if ledger is None:
                raise RuntimeError("a cumulative spend policy requires a spend ledger")
            accepted, spent, reserved = ledger.reserve(
                request_id, estimate, policy.max_total_usd
            )
            if not accepted:
                raise SpendLimitError(
                    f"this client has spent {spent}, reserved {reserved}, and the next "
                    f"request could cost {estimate}, above the ceiling of "
                    f"{policy.max_total_usd}",
                    limit_usd=policy.max_total_usd,
                    spent_usd=spent,
                    estimated_usd=estimate,
                    hint="raise max_total_usd, or reset the ledger to start a new budget",
                )

    def _estimate_request_cost(
        self, request: GenerationRequest, capabilities: ModelCapabilities | None
    ) -> Decimal | None:
        """The high end of a request's preflight cost range, or ``None`` when unknowable."""
        if capabilities is None or capabilities.pricing is None:
            return None
        budget = build_context_budget(
            request,
            capabilities,
            estimator=self._estimator,
            calibration=TokenCalibration(),
        )
        estimated = budget.estimated_cost
        return estimated.high if estimated is not None else None

    def _check_prefix_stability(
        self,
        request: GenerationRequest,
        plan: CachePlan,
        resolved: ResolvedTarget,
        builder: ManifestBuilder | None = None,
    ) -> None:
        """Warn when a caller's own prompt is defeating the cache they asked for.

        An implicit-caching provider only helps if the prefix is identical between turns.
        A timestamp in the system block, or tools serialized in a different order each
        time, silently produces a hit rate of zero, and the only evidence is a
        ``cache_read_tokens`` that never rises, which nobody is watching. Comparing the
        prefix signature across requests to the same target turns that into a diagnostic.

        Advisory only: nothing is rewritten, and the request proceeds either way.
        """
        signature = plan.prefix_signature(request)
        key = str(resolved)
        previous = self._cache_prefixes.get(key)
        self._cache_prefixes[key] = signature
        if previous is not None and previous != signature:
            self._emit(
                ProviderDiagnostic(
                    resolved,
                    Diagnostic(
                        code="cache.prefix-unstable",
                        severity="info",
                        message=(
                            "the cacheable prefix changed since the last request to this "
                            "target, so the provider's prompt cache will not be hit"
                        ),
                    ),
                ),
                builder=builder,
            )

    def _emit(self, event: TelemetryEvent, *, builder: ManifestBuilder | None = None) -> None:
        """Dispatch a telemetry event to observers and to the run's manifest builder.

        The builder is normally found by correlation — every request-path event carries a
        ``request_id``, and passed explicitly only for the handful of events that carry
        none, where correlation would have to guess between concurrent runs.
        """
        if self._builders:
            sink = builder
            if sink is None:
                request_id = getattr(event, "request_id", None)
                if isinstance(request_id, str) and request_id:
                    sink = self._builders.get(request_id)
            if sink is not None:
                sink.observe(event)
        if self._events.has_observers:
            self._events.emit(event)


def _judge_probe(
    feature: Feature, text: str, content_events: int, tool_called: bool
) -> FeatureProbe:
    """Read what came back from a probe the provider accepted.

    Acceptance alone proves nothing — the failure this whole layer exists to catch is a
    server that takes ``response_format`` and ignores it, so each feature is judged on
    whether the *answer* shows the mechanism worked. Anything short of that is
    inconclusive rather than a verdict, because one reply cannot separate a weak model
    from an ignored parameter.
    """
    if feature is Feature.TOOLS:
        if tool_called:
            return FeatureProbe(feature, "supported", "the model called the offered tool")
        return FeatureProbe(
            feature,
            "inconclusive",
            "the request was accepted but answered with text instead of a tool call",
        )

    if feature is Feature.STREAMING:
        if content_events > 1:
            return FeatureProbe(
                feature, "supported", f"the answer arrived in {content_events} deltas"
            )
        return FeatureProbe(
            feature,
            "inconclusive",
            "the answer arrived in one delta, which a buffered provider and a fast one "
            "both produce",
        )

    parsed, error = extract_json(text)
    if error is not None:
        return FeatureProbe(feature, "inconclusive", f"the request was accepted but {error}")
    if feature is Feature.JSON_MODE:
        # JSON mode promises well-formed JSON and nothing about its shape, so parsing is
        # the whole test. Holding it to the schema would fail a provider doing its job.
        return FeatureProbe(feature, "supported", "the answer was well-formed JSON")
    if validate(parsed, PROBE_SCHEMA):
        return FeatureProbe(
            feature,
            "inconclusive",
            "the request was accepted and answered with JSON that ignored the schema",
        )
    return FeatureProbe(feature, "supported", "the answer matched the requested schema")


def _verification_detail(error: Exception) -> str:
    """Explain a failed probe in the terms an operator can act on.

    The router wraps a provider failure in `AllTargetsFailedError`, whose message is about
    routing — accurate, and unhelpful when the route was one target long. The underlying
    error's own detail and hint are what actually name the missing credential or the
    mistyped model, so those are what surface here.
    """
    if isinstance(error, AllTargetsFailedError):
        for attempt in reversed(error.attempts):
            if attempt.error is not None:
                return attempt.error.detail
        return error.detail
    detail = error.detail if isinstance(error, ProviderError) else str(error)
    hint = getattr(error, "hint", None)
    return f"{detail} ({hint})" if hint else detail


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


def _version() -> str:
    """This distribution's version, imported late to keep the package import acyclic."""
    from .. import __version__

    return __version__


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

    def __init__(
        self,
        source: AsyncIterator[StreamEvent],
        *,
        builder: ManifestBuilder | None = None,
    ) -> None:
        self._source = source
        self._result: Generation | None = None
        self._closed = False
        self._builder = builder

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

    @property
    def manifest(self) -> RunManifest | None:
        """What this call has done so far, as a `RunManifest`.

        Available at any point, which is the whole reason the handle lives on the stream
        rather than only on the result: a stream that was cancelled or that failed
        part-way has no `Generation` to carry a manifest, and that is precisely the call
        whose story a caller needs. Such a record has ``complete=False``.

        ``None`` when the client was built with manifests switched off.
        """
        return self._builder.build() if self._builder is not None else None

    async def collect(self) -> Generation:
        """Drain the stream and return the final result."""
        async for _ in self:
            pass
        return self.result
