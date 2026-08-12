"""The synchronous facade over the async core.

One background thread owns one event loop for the client's lifetime. Not
``asyncio.run()`` per call: that would tear down connection pools between requests, break
streaming iterators, and kill supervised local servers.

Cancellation is the delicate part (open question 3, settled here). A ``KeyboardInterrupt``
raised in the *calling* thread cannot interrupt the loop thread directly, so the facade
cancels the future, which cancels the loop-side task, which unwinds httpx2's stream context
manager and closes the connection — then re-raises in the caller.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import queue
import threading
from collections.abc import Callable, Coroutine, Iterator, Mapping, Sequence
from concurrent.futures import Future
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, TypeVar

from ..benchmark import (
    BENCHMARK_OUTPUT_TOKENS,
    BENCHMARK_PROMPT_TOKENS,
    BenchmarkSample,
    Measurement,
    MeasurementStore,
)
from ..capabilities.budget import ContextBudget
from ..capabilities.estimate import TokenEstimator
from ..capabilities.ledger import SpendLedger, SpendTotals
from ..capabilities.pricing_table import PricingTable
from ..capabilities.probes import EmbeddingProbeReport, ProbeReport
from ..catalog.model import Catalog
from ..compare import TargetComparison
from ..context_request import ContextRequest
from ..credentials import ResolverChain
from ..errors import ConfigError
from ..events.observers import Observer
from ..local.acquire import AcquisitionReport, ProgressSink
from ..local.hardware import HardwareProfile
from ..local.services import PULL_TIMEOUT_S, PullReport
from ..local.store import ModelStore, RemovalReport, ResolvedModel, StoreEntry
from ..local.tuning import Posture
from ..local.variants import VariantPrefs
from ..manifest import RunManifest
from ..registry import ProviderRegistry
from ..routing.policy import Route
from ..session import Session
from ..types.capabilities import DiscoveredModel, Feature, Health, ModelCapabilities
from ..types.events import StreamEnded, StreamEvent
from ..types.operations import (
    BatchPolicy,
    EmbeddingResult,
    EmbeddingSpace,
    InferenceOperation,
    RerankDocument,
    RerankResult,
)
from ..types.requests import (
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
from ..types.results import Diagnostic, Generation
from ..verification import Verification
from .async_client import AsyncClient, MessagesInput
from .models import CatalogView
from .providers import ProviderSettings
from .tools import DEFAULT_MAX_ROUNDS

__all__ = ["Client", "SyncStream"]

_T = TypeVar("_T")

_SHUTDOWN_TIMEOUT_S = 5.0
_STREAM_QUEUE_SIZE = 256
"""Bounds memory when a consumer iterates more slowly than the provider streams."""


class _LoopThread:
    """A daemon thread running one event loop for the lifetime of a client."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="anyinfer-loop", daemon=True)
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.call_soon(self._ready.set)
        self.loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, _T]) -> Future[_T]:
        """Schedule a coroutine on the loop from any thread."""
        try:
            return asyncio.run_coroutine_threadsafe(coro, self.loop)
        except RuntimeError:
            # The loop is stopped (client closed mid-call from another thread). The
            # coroutine will never run; close it now or its garbage collection raises
            # a "never awaited" warning in whatever thread happens to trigger it.
            coro.close()
            raise

    def run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        """Run a coroutine to completion, propagating cancellation on interrupt."""
        future = self.submit(coro)
        try:
            return future.result()
        except (KeyboardInterrupt, SystemExit):
            future.cancel()
            raise

    def shutdown(self) -> None:
        """Cancel outstanding work, stop the loop, and join the thread."""
        if not self._thread.is_alive():
            return

        async def _cancel_all() -> None:
            current = asyncio.current_task()
            tasks = [t for t in asyncio.all_tasks() if t is not current]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        # Shutdown is best-effort throughout: a stuck task must not prevent the loop
        # from stopping, or close() would hang the calling thread.
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(_cancel_all(), self.loop).result(
                timeout=_SHUTDOWN_TIMEOUT_S
            )
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=_SHUTDOWN_TIMEOUT_S)
        # Only safe once the loop has actually stopped and its thread has exited;
        # closing a running loop raises, and leaving it open leaks its selector.
        if not self._thread.is_alive():
            with contextlib.suppress(Exception):
                self.loop.close()


class _Sentinel:
    """Marks the end of a stream queue."""


_END = _Sentinel()


class SyncStream:
    """A blocking iterator over stream events, fed from the background loop.

    Use it as a context manager so an early exit cancels the underlying request instead of
    leaving it running:

    ```python
    with client.stream(messages, target="ollama:qwen3:8b") as stream:
        for event in stream:
            ...
        final = stream.result
    ```
    """

    def __init__(self, loop: _LoopThread, factory: Any) -> None:
        self._loop = loop
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=_STREAM_QUEUE_SIZE)
        self._result: Generation | None = None
        self._closed = False
        # Built here rather than inside the pump so the caller's thread holds the stream
        # object, and therefore its manifest — before the first event exists. Nothing in
        # `AsyncClient.stream()` awaits, and an async generator binds no loop until it is
        # first iterated, so constructing it off the loop thread is safe.
        self._async_stream = factory()
        self._future = loop.submit(self._pump(self._async_stream))

    async def _pump(self, stream: Any) -> None:
        """Drain the async stream into the thread-safe queue."""
        try:
            async for event in stream:
                await asyncio.to_thread(self._queue.put, event)
            await asyncio.to_thread(self._queue.put, _END)
        except asyncio.CancelledError:
            await asyncio.to_thread(self._queue.put, _END)
            raise
        except BaseException as exc:  # noqa: BLE001 — re-raised in the consumer thread
            await asyncio.to_thread(self._queue.put, exc)
        finally:
            await stream.aclose()

    def __iter__(self) -> Iterator[StreamEvent]:
        """Iterate events as they arrive."""
        return self

    def __next__(self) -> StreamEvent:
        """Block for the next event, re-raising loop-side exceptions here."""
        if self._closed:
            raise StopIteration
        item = self._queue.get()
        if isinstance(item, _Sentinel):
            self._closed = True
            raise StopIteration
        if isinstance(item, BaseException):
            self._closed = True
            raise item
        if isinstance(item, StreamEnded):
            self._result = item.result
        event: StreamEvent = item
        return event

    def __enter__(self) -> SyncStream:
        """Enter a context that cancels the request on exit."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the stream, cancelling it if it was not fully consumed."""
        self.close()

    def close(self) -> None:
        """Cancel the underlying request and drain any buffered events."""
        if self._closed:
            return
        self._closed = True
        self._future.cancel()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    @property
    def result(self) -> Generation:
        """The final result.

        Raises:
            RuntimeError: If the stream has not been consumed to completion.
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

        The blocking mirror of `AsyncStream.manifest`, and readable at any point — including
        after `close()` cancelled the request, which is when it is most useful. ``None``
        when the client was built with manifests switched off.
        """
        manifest: RunManifest | None = self._async_stream.manifest
        return manifest

    def collect(self) -> Generation:
        """Drain the stream and return the final result."""
        for _ in self:
            pass
        return self.result


class Client:
    """The synchronous inference client.

    A thin facade: every method schedules work on one background event loop that owns the
    real `AsyncClient`. Safe to call from multiple
    threads, and concurrent requests still overlap on the loop.

    Args are identical to `AsyncClient`.
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
        self._loop = _LoopThread()
        self._async = self._loop.run(
            _construct(
                providers=providers,
                registry=registry,
                catalog=catalog,
                route=route,
                observers=observers,
                resolver=resolver,
                retain_raw=retain_raw,
                repair=repair,
                use_default_catalog=use_default_catalog,
                estimator=estimator,
                context_gate=context_gate,
                history=history,
                cache=cache,
                arena=arena,
                arenas=arenas,
                spend=spend,
                ledger=ledger,
                pricing_table=pricing_table,
                manifests=manifests,
                manifest_payloads=manifest_payloads,
                capability_overrides=capability_overrides,
                model_dir=model_dir,
            )
        )
        self._closed = False
        atexit.register(self.close)

    # ---- lifecycle -------------------------------------------------------------------

    def __enter__(self) -> Client:
        """Enter a context that closes the client on exit."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the client on context exit."""
        self.close()

    def close(self) -> None:
        """Close adapters, stop the background loop, and join its thread."""
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            self._loop.run(self._async.aclose())
        self._loop.shutdown()
        with contextlib.suppress(Exception):
            atexit.unregister(self.close)

    def _ensure_open(self) -> None:
        """Fail a call on a closed client with the reason, not a loop internals error."""
        if self._closed:
            raise ConfigError(
                "this client is closed",
                hint="close() is final — build a new Client instead of reusing this one",
            )

    # ---- observation -----------------------------------------------------------------

    def subscribe(self, observer: Observer, *, payloads: bool = False) -> None:
        """Register a telemetry observer."""
        self._async.subscribe(observer, payloads=payloads)

    def unsubscribe(self, observer: Observer) -> None:
        """Remove a telemetry observer."""
        self._async.unsubscribe(observer)

    # ---- discovery -------------------------------------------------------------------

    def models(
        self, provider_id: str, *, operation: InferenceOperation | None = None
    ) -> Sequence[DiscoveredModel]:
        """List a provider's models. See `AsyncClient.models`."""
        self._ensure_open()
        return self._loop.run(self._async.models(provider_id, operation=operation))

    def health(self, provider_id: str) -> Health:
        """Probe a provider's readiness."""
        self._ensure_open()
        return self._loop.run(self._async.health(provider_id))

    def diagnostics(self, provider_id: str) -> Sequence[Diagnostic]:
        """Ask a provider what it has noticed about its own runtime.

        See `AsyncClient.diagnostics`.
        """
        self._ensure_open()
        return self._loop.run(self._async.diagnostics(provider_id))

    def resolve(self, target: Target) -> ResolvedTarget:
        """Resolve a target string without issuing a request."""
        self._ensure_open()
        return self._async.resolve(target)

    def pull_model(
        self,
        provider_id: str,
        model: str,
        *,
        progress: Any | None = None,
        timeout_s: float = PULL_TIMEOUT_S,
    ) -> PullReport:
        """Tell an engine that keeps its own store to make a model available.

        See `AsyncClient.pull_model`.
        """
        self._ensure_open()
        return self._loop.run(
            self._async.pull_model(provider_id, model, progress=progress, timeout_s=timeout_s)
        )

    def session(self, target: Target) -> Session:
        """Open a handle that lets a provider keep what it already knows.

        See `AsyncClient.session`.
        """
        self._ensure_open()
        return self._async.session(target)

    def benchmark(
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

        See `AsyncClient.benchmark`.
        """
        self._ensure_open()
        return self._loop.run(
            self._async.benchmark(
                target,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                timeout_s=timeout_s,
                store=store,
                progress=progress,
            )
        )

    def probe(
        self,
        target: Target,
        *,
        features: Sequence[Feature] | None = None,
        timeout_s: float = 30.0,
        record: bool = True,
    ) -> ProbeReport:
        """Measure what a target actually supports, one request per feature.

        See `AsyncClient.probe`.
        """
        self._ensure_open()
        return self._loop.run(
            self._async.probe(target, features=features, timeout_s=timeout_s, record=record)
        )

    def verify(
        self,
        target: Target,
        *,
        timeout_s: float = 60.0,
        operation: InferenceOperation = "generation",
    ) -> Verification:
        """Prove a target works by asking it something, end to end.

        See `AsyncClient.verify`.
        """
        self._ensure_open()
        return self._loop.run(
            self._async.verify(target, timeout_s=timeout_s, operation=operation)
        )

    def probe_embedding(
        self,
        target: Target,
        *,
        timeout_s: float = 30.0,
        record: bool = True,
    ) -> EmbeddingProbeReport:
        """Measure an embedding target with one real call. See `AsyncClient.probe_embedding`."""
        self._ensure_open()
        return self._loop.run(
            self._async.probe_embedding(target, timeout_s=timeout_s, record=record)
        )

    # ---- local models ----------------------------------------------------------------

    @property
    def model_store(self) -> ModelStore:
        """The store acquired model weights live in."""
        return self._async.model_store

    def local_catalog(
        self,
        provider_id: str | None = None,
        *,
        hardware: HardwareProfile | None = None,
        best_at: str | None = None,
        posture: Posture = "balanced",
    ) -> CatalogView:
        """Browse the local model catalog, annotated with how each entry fits.

        See `AsyncClient.local_catalog`.
        """
        self._ensure_open()
        return self._loop.run(
            self._async.local_catalog(
                provider_id, hardware=hardware, best_at=best_at, posture=posture
            )
        )

    def acquire_model(
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
        """Download a catalog model's weights. See `AsyncClient.acquire_model`.

        The progress sink is invoked from the background loop thread, so it must not block
        and must not call back into this client.
        """
        self._ensure_open()
        return self._loop.run(
            self._async.acquire_model(
                model_id,
                engine=engine,
                variant_id=variant_id,
                hardware=hardware,
                progress=progress,
                prefs=prefs,
                dry_run=dry_run,
                token=token,
            )
        )

    def installed_models(self) -> Sequence[StoreEntry]:
        """Every model acquired into this client's store."""
        self._ensure_open()
        return self._loop.run(self._async.installed_models())

    def locate_model(
        self,
        model_id: str,
        *,
        variant_id: str | None = None,
        engine: str | None = None,
        verify: bool = False,
    ) -> ResolvedModel | None:
        """Find an acquired model on disk. See `AsyncClient.locate_model`."""
        self._ensure_open()
        return self._loop.run(
            self._async.locate_model(model_id, variant_id=variant_id, engine=engine, verify=verify)
        )

    def remove_model(self, entry_id: str) -> RemovalReport:
        """Delete an acquired model. See `AsyncClient.remove_model`."""
        self._ensure_open()
        return self._loop.run(self._async.remove_model(entry_id))

    def spend(self) -> SpendTotals:
        """What this client has spent so far. See `AsyncClient.spend`."""
        totals: SpendTotals = self._async.spend()
        return totals

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

        Pure computation — runs directly on the calling thread. See
        `AsyncClient.budget()`.
        """
        self._ensure_open()
        return self._async.budget(
            messages,
            target=target,
            schema=schema,
            tools=tools,
            sampling=sampling,
            output_reserve_tokens=output_reserve_tokens,
        )

    def compare(
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
        """Compare request portability without generating. See `AsyncClient.compare`."""
        self._ensure_open()
        return self._loop.run(
            self._async.compare(
                messages,
                targets=targets,
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
                refresh=refresh,
            )
        )

    # ---- generation ------------------------------------------------------------------

    def generate(
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
        """Generate a single result. See `AsyncClient.generate()`."""
        self._ensure_open()
        return self._loop.run(
            self._async.generate(
                messages,
                target=target,
                route=route,
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
                session=session,
                manifest=manifest,
            )
        )

    def embed(
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
        """Embed one or more texts into vectors. See `AsyncClient.embed()`."""
        self._ensure_open()
        return self._loop.run(
            self._async.embed(
                inputs,
                target=target,
                route=route,
                input_type=input_type,
                dimensions=dimensions,
                expected_space=expected_space,
                allow_incompatible_fallback=allow_incompatible_fallback,
                batch=batch,
                timeout_s=timeout_s,
                provider_options=provider_options,
                metadata=metadata,
                max_response_bytes=max_response_bytes,
                retain_raw=retain_raw,
                manifest=manifest,
            )
        )

    def rerank(
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
        """Rank documents by relevance to a query. See `AsyncClient.rerank()`."""
        self._ensure_open()
        return self._loop.run(
            self._async.rerank(
                query,
                documents,
                target=target,
                route=route,
                top_n=top_n,
                batch=batch,
                timeout_s=timeout_s,
                provider_options=provider_options,
                metadata=metadata,
                max_response_bytes=max_response_bytes,
                return_documents=return_documents,
                retain_raw=retain_raw,
                manifest=manifest,
            )
        )

    def run_tools(
        self,
        messages: MessagesInput,
        *,
        tools: Sequence[Any],
        target: Target | None = None,
        route: Route | Target | Sequence[Target] | None = None,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        **kwargs: Any,
    ) -> Generation:
        """Generate, dispatching tools until the model answers.

        See `AsyncClient.run_tools()`.
        """
        self._ensure_open()
        return self._loop.run(
            self._async.run_tools(
                messages,
                tools=tools,
                target=target,
                route=route,
                max_rounds=max_rounds,
                **kwargs,
            )
        )

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
    ) -> SyncStream:
        """Start a streaming generation, returning a blocking iterator.

        See `AsyncClient.stream()`. Use the result as a context manager so that leaving
        the block early cancels the in-flight request.
        """
        self._ensure_open()

        def factory() -> Any:
            return self._async.stream(
                messages,
                target=target,
                route=route,
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
                session=session,
                manifest=manifest,
            )

        return SyncStream(self._loop, factory)


async def _construct(**kwargs: Any) -> AsyncClient:
    """Build the async client *on* the loop thread, so its state has correct affinity."""
    return AsyncClient(**kwargs)
