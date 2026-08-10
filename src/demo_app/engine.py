"""The bridge between AnyInfer's async core and Qt's event loop.

Qt owns the main thread; AnyInfer's `Client` owns a background loop thread
(the async-core/sync-facade design). Neither can block the other, so this module keeps
them apart:

- Generations, discovery, and health probes run on a `QThreadPool` worker, never on the
  GUI thread.
- Results cross back as Qt signals, which Qt marshals to the GUI thread for us.
- Nothing here touches a widget, and nothing in the widget layer touches AnyInfer
  directly — widgets call `Engine` methods and listen to `Engine` signals. The one
  synchronous call is `Engine.budget()`, a pure in-process calculation cheap enough for
  the GUI thread when debounced.

That separation is the part worth copying into a real application. The alternative — calling
``client.generate()`` from a button handler — freezes the UI for the length of the request.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from anyinfer import (
    BenchmarkSample,
    CachePolicy,
    Client,
    ContextBudget,
    HistoryPolicy,
    Measurement,
    ProviderSettings,
    Route,
    Session,
)
from anyinfer.events.telemetry import TelemetryEvent
from anyinfer.local.acquire import AcquisitionProgress
from anyinfer.local.tuning import Posture
from anyinfer.registry import ProviderRegistry
from anyinfer.types.events import (
    AttemptFailed,
    ReasoningDelta,
    StreamEnded,
    TextDelta,
    TimingMark,
    UsageUpdate,
)
from anyinfer.types.messages import Message
from anyinfer.types.requests import Repair, Sampling
from anyinfer.types.results import Generation

from .config import DemoConfig
from .fake_provider import DemoFakeBackend, register_demo_provider

__all__ = ["Engine", "GenerationSpec", "RuntimeInstallProgress", "TelemetryRelay"]


@dataclass(frozen=True, slots=True)
class GenerationSpec:
    """Everything the UI collected for one request.

    A frozen value rather than a pile of keyword arguments, so it can be handed to a worker
    thread with no risk of the UI mutating it mid-flight.
    """

    messages: tuple[Message, ...]
    route: Route
    sampling: Sampling
    schema: Mapping[str, Any] | None = None
    repair: Repair | None = None
    reasoning: str | None = None
    """Normalized reasoning effort, or ``None`` to send no reasoning field at all."""
    use_session: bool = False
    """Whether to thread this turn through the engine's provider-side session handle."""
    history: HistoryPolicy | None = None
    """Opt-in conversation compaction; ``None`` sends the full transcript untouched."""
    cache: CachePolicy | None = None
    """Opt-in prompt-cache placement; ``None`` caches exactly nothing."""


@dataclass(frozen=True, slots=True)
class RuntimeInstallProgress:
    """One llama.cpp runtime archive's download progress."""

    artifact_id: str
    downloaded_bytes: int
    total_bytes: int | None = None


class TelemetryRelay(QObject):
    """An `Observer` that re-emits events as Qt signals.

    AnyInfer calls observers from whichever thread is running the request; Qt's queued
    connections are what make it safe for the inspector widget to render them.
    """

    # Not named `event`: QObject.event() is a virtual method, and shadowing it with a
    # signal breaks Qt's event delivery for this object.
    telemetry = Signal(object)
    acquisition_progress = Signal(object)

    def on_event(self, telemetry_event: TelemetryEvent) -> None:
        """Receive one telemetry event from the core."""
        self.telemetry.emit(telemetry_event)

    def on_progress(self, progress: AcquisitionProgress) -> None:
        """Receive one acquisition progress snapshot.

        A separate channel from `on_event`, because acquisition progress is not
        telemetry: it is reported through the sink the caller passed to
        ``acquire_model()`` rather than to registered observers, and it describes a
        download rather than a request. Crossing it into the telemetry stream would put
        thousands of throttled byte counts into an inspector built to show request trees.
        """
        self.acquisition_progress.emit(progress)


class _Signals(QObject):
    """Signals for one unit of background work.

    A fresh `QObject` per job, because `QRunnable` is not a ``QObject`` and
    therefore cannot carry signals itself.
    """

    text_delta = Signal(str)
    reasoning_delta = Signal(str)
    first_token = Signal(float)
    attempt_failed = Signal(object)
    usage_update = Signal(object)
    finished = Signal(object)
    failed = Signal(str, object)
    cancelled = Signal()
    call_failed = Signal(str, str, object)  # (provider_id, message, error)
    models_listed = Signal(str, object)
    health_checked = Signal(str, object)
    task_done = Signal(str, object)  # (key, result)
    task_failed = Signal(str, str, object)  # (key, message, error)


class _GenerateJob(QRunnable):
    """Runs one generation on a pool thread, emitting events as they stream in."""

    def __init__(
        self,
        client: Client,
        spec: GenerationSpec,
        signals: _Signals,
        session: Session | None = None,
    ) -> None:
        super().__init__()
        self._client = client
        self._spec = spec
        self._signals = signals
        self._session = session
        self._cancelled = False
        self._terminal_emitted = False

    def cancel(self) -> None:
        """Ask the job to stop at the next event boundary."""
        self._cancelled = True

    def run(self) -> None:
        """Execute the request, translating stream events into Qt signals.

        Exactly one terminal signal always fires — ``finished``, ``failed``, or
        ``cancelled``, so the engine's busy state can never be left dangling.
        """
        try:
            with self._client.stream(
                list(self._spec.messages),
                route=self._spec.route,
                schema=self._spec.schema,
                sampling=self._spec.sampling,
                repair=self._spec.repair,
                reasoning=self._spec.reasoning,  # type: ignore[arg-type]
                session=self._session,
                history=self._spec.history,
                cache=self._spec.cache,
            ) as stream:
                for event in stream:
                    if self._cancelled:
                        # Leaving the `with` block cancels the in-flight request rather
                        # than letting it run to completion unobserved.
                        return
                    self._dispatch(event)
        except Exception as error:  # noqa: BLE001 — a demo must not die on a worker thread
            # Emitted as (message, error) rather than a flattened string: an
            # AnyInferError's structured hint is the actionable part, and the UI shows it.
            self._terminal_emitted = True
            self._signals.failed.emit(str(error), error)
        finally:
            if not self._terminal_emitted:
                self._signals.cancelled.emit()

    def _dispatch(self, event: object) -> None:
        if isinstance(event, TextDelta):
            self._signals.text_delta.emit(event.text)
        elif isinstance(event, ReasoningDelta):
            self._signals.reasoning_delta.emit(event.text)
        elif isinstance(event, TimingMark) and event.name == "first_token":
            self._signals.first_token.emit(event.at_ms)
        elif isinstance(event, AttemptFailed):
            self._signals.attempt_failed.emit(event.record)
        elif isinstance(event, UsageUpdate):
            self._signals.usage_update.emit(event.usage)
        elif isinstance(event, StreamEnded):
            self._terminal_emitted = True
            self._signals.finished.emit(event.result)


class _CallJob(QRunnable):
    """Runs one non-streaming client call (``models``/``health``) off the GUI thread.

    ``emit`` is the *bound* signal instance to fire on success; annotating it as ``Any`` is
    deliberate, since PySide6's bound signals have no public static type. Failures go out
    through ``call_failed``, a channel of their own — a background discovery error must
    never masquerade as a failed generation.
    """

    def __init__(self, fn: Any, provider_id: str, emit: Any, signals: _Signals) -> None:
        super().__init__()
        self._fn = fn
        self._provider_id = provider_id
        self._emit = emit
        self._signals = signals

    def run(self) -> None:
        """Call the client and emit the outcome."""
        try:
            self._emit(self._provider_id, self._fn(self._provider_id))
        except Exception as error:  # noqa: BLE001 — surfaced in the UI, not raised
            self._signals.call_failed.emit(self._provider_id, str(error), error)


class _TaskJob(QRunnable):
    """Runs one arbitrary client call off the GUI thread, tagged by a caller-chosen key.

    `_CallJob` covers the ``fn(provider_id)`` shape that discovery and health share.
    Everything else the library exposes — acquiring a model, probing a target, installing
    a runtime — has its own signature and its own return type, so this job carries a
    prepared zero-argument callable instead and lets the *key* say which request an answer
    belongs to. Without that key a panel with two probes in flight cannot tell which one
    just came back.
    """

    def __init__(self, key: str, fn: Any, signals: _Signals) -> None:
        super().__init__()
        self._key = key
        self._fn = fn
        self._signals = signals

    def run(self) -> None:
        """Call it, and report either outcome on a channel of its own."""
        try:
            result = self._fn()
        except Exception as error:  # noqa: BLE001 — surfaced in the UI, not raised
            self._signals.task_failed.emit(self._key, str(error), error)
            return
        self._signals.task_done.emit(self._key, result)


class Engine(QObject):
    """Owns the AnyInfer client and runs every call off the GUI thread.

    The client is rebuilt whenever configuration changes, because
    `ProviderSettings` is frozen and adapters are cached for a client's
    lifetime — swapping an API key means a new client, not a mutated one.
    """

    text_delta = Signal(str)
    reasoning_delta = Signal(str)
    first_token = Signal(float)
    attempt_failed = Signal(object)
    usage_update = Signal(object)
    finished = Signal(object)
    failed = Signal(str, object)
    cancelled = Signal()
    telemetry = Signal(object)
    models_listed = Signal(str, object)
    health_checked = Signal(str, object)
    discovery_failed = Signal(str, str, object)  # (provider_id, message, error)
    task_done = Signal(str, object)  # (key, result)
    task_failed = Signal(str, str, object)  # (key, message, error)
    acquisition_progress = Signal(object)
    runtime_install_progress = Signal(object)
    benchmark_progress = Signal(str, int, object)  # (task key, one-based run, sample)
    busy_changed = Signal(bool)

    # Keyed twins of the generation signals, for callers running several conversations
    # at once: the key is whatever the caller passed to `generate()` (the tabbed window
    # passes the conversation id). The unkeyed signals above still fire for every
    # generation — a caller that shows one conversation at a time never needs the keys.
    gen_text_delta = Signal(str, str)  # (key, text)
    gen_reasoning_delta = Signal(str, str)
    gen_first_token = Signal(str, float)
    gen_attempt_failed = Signal(str, object)
    gen_usage_update = Signal(str, object)
    gen_finished = Signal(str, object)
    gen_failed = Signal(str, str, object)  # (key, message, error)
    gen_cancelled = Signal(str)
    gen_busy_changed = Signal(str, bool)

    def __init__(self, config: DemoConfig) -> None:
        super().__init__()
        self._pool = QThreadPool(self)
        # A few generations may run at once — one per conversation tab, because each
        # tab owns its own transcript; the keys keep their event streams apart. The cap
        # stays small: this is a demo, not a load generator.
        self._pool.setMaxThreadCount(4)
        # Local-model work gets a pool of its own. Downloading a few gigabytes of weights
        # takes minutes, and on the request pool it would sit in front of every discovery
        # probe and every chat turn until it finished — a model manager that freezes the
        # conversation is worse than no model manager.
        self._task_pool = QThreadPool(self)
        self._task_pool.setMaxThreadCount(2)
        self._registry = ProviderRegistry()
        self._fake_backend = DemoFakeBackend()
        register_demo_provider(self._registry)
        self._relay = TelemetryRelay()
        self._relay.telemetry.connect(self.telemetry)
        self._relay.acquisition_progress.connect(self.acquisition_progress)
        self._config = config
        self._client: Client | None = None
        self._active: dict[str, _GenerateJob] = {}
        self._session: Session | None = None
        self._session_target = ""

    # ---- lifecycle -------------------------------------------------------------------

    @property
    def registry(self) -> ProviderRegistry:
        """The demo's own registry, including the offline provider."""
        return self._registry

    @property
    def config(self) -> DemoConfig:
        """The configuration the current client was built from."""
        return self._config

    @property
    def busy(self) -> bool:
        """Whether any generation is in flight."""
        return bool(self._active)

    def busy_for(self, key: str) -> bool:
        """Whether the generation started under ``key`` is still in flight."""
        return key in self._active

    def apply_config(self, config: DemoConfig) -> None:
        """Adopt new configuration, discarding the client built from the old one."""
        self._config = config
        self.close()

    def update_preferences(self, config: DemoConfig) -> None:
        """Adopt configuration fields the client never reads — theme, saved route, budgets.

        Unlike `apply_config()` this must not close the client: preference changes are
        legal mid-stream, and tearing the client down would kill an in-flight generation.
        """
        self._config = config

    def client(self) -> Client:
        """The current client, built on first use after a configuration change."""
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self) -> Client:
        settings: list[ProviderSettings] = []
        for provider in self._config.enabled_providers():
            transport = None
            if provider.provider_id == "demo-fake":
                transport = self._fake_backend.transport()
            settings.append(
                ProviderSettings(
                    provider_id=provider.provider_id,
                    # The alias is what makes two instances of one engine distinct
                    # adapters, addressable as `alias:model`.
                    alias=provider.alias,
                    base_url=provider.base_url or None,
                    api_key=provider.api_key or None,
                    api_version=provider.api_version or None,
                    options={**provider.options, **provider.extra_values()},
                    transport=transport,
                )
            )
        return Client(settings, registry=self._registry, observers=[self._relay])

    def budget(self, messages: Sequence[Message], target: str) -> ContextBudget:
        """Preflight the context budget for a prospective request.

        The one engine call made synchronously on the GUI thread: `budget()` is a pure
        in-process calculation with no network round-trip, and the caller debounces it.
        """
        return self.client().budget(list(messages), target=target)

    def close(self) -> None:
        """Close the client, releasing adapters and the background loop thread.

        The active generation (if any) is cancelled and queued discovery jobs are
        dropped, then a running job is given a moment to wind down *before* the client
        goes away — a job that outlives its client would die uselessly (and noisily)
        instead.
        """
        self.cancel()
        if self._session is not None:
            # The handle refers to state on the client that is about to go away; closing
            # it here stops a later turn resuming into a client that no longer exists.
            self._session.close()
            self._session = None
        self._session_target = ""
        self._pool.clear()
        self._task_pool.clear()
        self._pool.waitForDone(2_000)
        # Bounded like the request pool, and for the same reason: a download that has
        # already started cannot be interrupted, and blocking the close on it would hang
        # the window for as long as the remaining gigabytes take.
        self._task_pool.waitForDone(2_000)
        if self._client is not None:
            self._client.close()
            self._client = None

    # ---- work ------------------------------------------------------------------------

    def generate(self, spec: GenerationSpec, key: str = "") -> None:
        """Start a generation on the pool, identified by ``key``.

        A second call under the *same* key is ignored while that generation runs — one
        stream per conversation, but different keys run concurrently. ``key`` may stay
        empty for callers with a single conversation; the empty string is a key like any
        other.
        """
        if key in self._active:
            return
        # Rewind the fakes so the flaky model's scripted failure is reproducible on every
        # run rather than only the first. The answer *shape* is decided per request by
        # the fake transport, so concurrent generations cannot reshape each other.
        self._fake_backend.set_json_mode(spec.schema is not None)
        was_busy = self.busy
        signals = _Signals()
        signals.text_delta.connect(self.text_delta)
        signals.text_delta.connect(lambda text, k=key: self.gen_text_delta.emit(k, text))
        signals.reasoning_delta.connect(self.reasoning_delta)
        signals.reasoning_delta.connect(lambda text, k=key: self.gen_reasoning_delta.emit(k, text))
        signals.first_token.connect(self.first_token)
        signals.first_token.connect(lambda ms, k=key: self.gen_first_token.emit(k, ms))
        signals.attempt_failed.connect(self.attempt_failed)
        signals.attempt_failed.connect(
            lambda record, k=key: self.gen_attempt_failed.emit(k, record)
        )
        signals.usage_update.connect(self.usage_update)
        signals.usage_update.connect(lambda usage, k=key: self.gen_usage_update.emit(k, usage))
        signals.finished.connect(lambda result, k=key: self._on_finished(k, result))
        signals.failed.connect(lambda message, error, k=key: self._on_failed(k, message, error))
        signals.cancelled.connect(lambda k=key: self._on_cancelled(k))

        job = _GenerateJob(self.client(), spec, signals, self._session_for(spec))
        self._active[key] = job
        self.gen_busy_changed.emit(key, True)
        if not was_busy:
            self.busy_changed.emit(True)
        self._pool.start(job)

    def _session_for(self, spec: GenerationSpec) -> Session | None:
        """The session handle this turn should thread through, if any.

        Opened once per target and kept, because that is the whole point: a handle
        recreated per request carries no state forward and would report ``fresh`` every
        time. Switching targets opens a new one — a provider's session is its own, and
        handing Ollama's handle to Copilot would be meaningless.
        """
        if not spec.use_session:
            return None
        target = str(spec.route.targets[0]) if spec.route.targets else ""
        if not target:
            return None
        # Compared as the string the user picked rather than through
        # `Session.applies_to()`: that takes a resolved
        # target, and resolving one here purely to decide whether to reuse a handle would
        # spend a lookup to answer a question the bar's own selection already answers.
        if self._session is not None and self._session_target != target:
            self._session.close()
            self._session = None
        if self._session is None or self._session.closed:
            self._session = self.client().session(target)
            self._session_target = target
        return self._session

    @property
    def session_reuse(self) -> str:
        """How the last session-threaded turn was served, or an empty string.

        ``resumed`` means the provider kept the conversation; ``fresh`` means it started
        one; ``unsupported`` means the provider has no session concept and the transcript
        was re-sent. Reported rather than hidden, since the three cost very different
        amounts.
        """
        return self._session.reuse if self._session is not None else ""

    def cancel(self, key: str | None = None) -> None:
        """Cancel one keyed generation, or all active generations if no key is given."""
        if key is None:
            for job in self._active.values():
                job.cancel()
            return
        active = self._active.get(key)
        if active is not None:
            active.cancel()

    def list_models(self, provider_id: str) -> None:
        """Discover a provider's models in the background.

        A failure is reported through `discovery_failed` and leaves the generation
        state (busy, the active job) untouched.
        """
        signals = _Signals()
        signals.models_listed.connect(self.models_listed)
        signals.call_failed.connect(self.discovery_failed)
        self._pool.start(
            _CallJob(self.client().models, provider_id, signals.models_listed.emit, signals)
        )

    def check_health(self, provider_id: str) -> None:
        """Probe a provider's readiness in the background.

        A failure is reported through `discovery_failed` and leaves the generation
        state (busy, the active job) untouched.
        """
        signals = _Signals()
        signals.health_checked.connect(self.health_checked)
        signals.call_failed.connect(self.discovery_failed)
        self._pool.start(
            _CallJob(self.client().health, provider_id, signals.health_checked.emit, signals)
        )

    # ---- library surfaces beyond generation ------------------------------------------

    def run_task(self, key: str, fn: Any) -> None:
        """Run one prepared client call on the local-work pool, reporting it under ``key``.

        The single entry point every non-generation surface goes through: catalog browsing,
        acquisition, removal, probes, benchmarks, runtime installs. Each is one library
        call, so the demo's job is to get it off the GUI thread and label the answer — not
        to wrap it in logic of its own.
        """
        signals = _Signals()
        signals.task_done.connect(self.task_done)
        signals.task_failed.connect(self.task_failed)
        self._task_pool.start(_TaskJob(key, fn, signals))

    def local_catalog(
        self, key: str, provider_id: str | None, *, posture: Posture = "balanced"
    ) -> None:
        """Browse the local catalog, annotated with how each entry fits this machine."""
        client = self.client()
        self.run_task(key, lambda: client.local_catalog(provider_id, posture=posture))

    def installed_models(self, key: str) -> None:
        """List every model acquired into this client's store."""
        client = self.client()
        self.run_task(key, client.installed_models)

    def acquire_model(
        self, key: str, model_id: str, *, engine: str | None = None, dry_run: bool = False
    ) -> None:
        """Download a catalog model's weights, reporting progress as it goes.

        ``dry_run`` resolves and plans the acquisition, which files, how many bytes, what
        is already on disk — without fetching anything, so a UI can show the cost of a
        download before committing to it.
        """
        client = self.client()
        self.run_task(
            key,
            lambda: client.acquire_model(
                model_id, engine=engine, dry_run=dry_run, progress=self._relay.on_progress
            ),
        )

    def remove_model(self, key: str, entry_id: str) -> None:
        """Delete an acquired model from the store."""
        client = self.client()
        self.run_task(key, lambda: client.remove_model(entry_id))

    def install_runtime(self, key: str, kind: str | None, *, force: bool = False) -> None:
        """Install one llama.cpp runtime and relay its archive download progress."""
        from anyinfer.local.hardware import detect
        from anyinfer.local.runtimes import install_runtime

        hardware = detect()

        def progress(artifact_id: str, downloaded: int, total: int | None) -> None:
            self.runtime_install_progress.emit(
                RuntimeInstallProgress(artifact_id, downloaded, total)
            )

        self.run_task(
            key,
            lambda: install_runtime(
                kind,  # type: ignore[arg-type]
                hardware=hardware,
                progress=progress,
                force=force,
            ),
        )

    def pull_model(self, key: str, provider_id: str, model: str) -> None:
        """Tell an engine that keeps its own store to make a model available."""
        client = self.client()
        self.run_task(key, lambda: client.pull_model(provider_id, model))

    def resolve(self, key: str, target: str) -> None:
        """Resolve a target to its provider, model, and capabilities without a request."""
        client = self.client()
        self.run_task(key, lambda: client.resolve(target))

    def probe(self, key: str, target: str) -> None:
        """Measure what a target actually supports, one request per feature."""
        client = self.client()
        self.run_task(key, lambda: client.probe(target))

    def verify(self, key: str, target: str) -> None:
        """Prove a target works end to end by asking it something."""
        client = self.client()
        self.run_task(key, lambda: client.verify(target))

    def benchmark(self, key: str, target: str) -> None:
        """Measure a target's latency and throughput with one deterministic request."""
        client = self.client()
        self.run_task(
            key,
            lambda: client.benchmark(
                target,
                progress=lambda sample: self._emit_benchmark_sample(key, 1, sample),
            ),
        )

    def benchmark_pair(self, key: str, target: str) -> None:
        """Run two back-to-back benchmarks, so warm-up cost becomes observable.

        The library does not (yet) report whether a local engine had the model in memory
        when a benchmark ran, and this demo must not guess. What it *can* do is control
        the protocol: the second run is warm by construction — it starts the moment the
        first finishes, while the first inherits whatever state the engine was in. Equal
        numbers mean the engine was already warm; a large first-run TTFT is the load cost
        it absorbed. The pair is one task so nothing else can run between them.
        """
        client = self.client()

        def run() -> tuple[Measurement, Measurement]:
            first = client.benchmark(
                target,
                progress=lambda sample: self._emit_benchmark_sample(key, 1, sample),
            )
            second = client.benchmark(
                target,
                progress=lambda sample: self._emit_benchmark_sample(key, 2, sample),
            )
            return first, second

        self.run_task(key, run)

    def _emit_benchmark_sample(self, key: str, run: int, sample: BenchmarkSample) -> None:
        """Relay a live benchmark point from the client's loop thread into Qt."""
        self.benchmark_progress.emit(key, run, sample)

    def diagnostics(self, key: str, provider_id: str) -> None:
        """Ask a provider what it has noticed about its own runtime."""
        client = self.client()
        self.run_task(key, lambda: client.diagnostics(provider_id))

    def run_tools(
        self, key: str, prompt: str, target: str, tools: Sequence[Any], *, max_rounds: int = 4
    ) -> None:
        """Generate with a tool loop, dispatching calls until the model answers.

        The loop itself is `run_tools()`: it issues the request,
        matches each returned call to a tool, runs it, feeds the result back, and repeats
        until there is an answer or the round budget is spent. An application writing that
        loop by hand is the mistake this demonstrates the absence of.
        """
        client = self.client()
        # The fake backend scripts its tool call on the *first* request of a run, so the
        # scripted servers are rewound here for the same reason a generation rewinds them:
        # the demonstration has to be repeatable, not once per process.
        self._fake_backend.set_json_mode(False)
        self.run_task(
            key,
            lambda: client.run_tools(prompt, tools=tools, target=target, max_rounds=max_rounds),
        )

    def _on_finished(self, key: str, result: Generation) -> None:
        self._settle(key)
        self.finished.emit(result)
        self.gen_finished.emit(key, result)

    def _on_failed(self, key: str, message: str, error: object) -> None:
        self._settle(key)
        self.failed.emit(message, error)
        self.gen_failed.emit(key, message, error)

    def _on_cancelled(self, key: str) -> None:
        self._settle(key)
        self.cancelled.emit()
        self.gen_cancelled.emit(key)

    def _settle(self, key: str) -> None:
        """Retire one job and report the busy transitions it caused."""
        self._active.pop(key, None)
        self.gen_busy_changed.emit(key, False)
        if not self._active:
            self.busy_changed.emit(False)
