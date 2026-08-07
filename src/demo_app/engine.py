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

from anyinfer import Client, ContextBudget, ProviderSettings, Route
from anyinfer.events.telemetry import TelemetryEvent
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

__all__ = ["Engine", "GenerationSpec", "TelemetryRelay"]


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


class TelemetryRelay(QObject):
    """An `Observer` that re-emits events as Qt signals.

    AnyInfer calls observers from whichever thread is running the request; Qt's queued
    connections are what make it safe for the inspector widget to render them.
    """

    # Not named `event`: QObject.event() is a virtual method, and shadowing it with a
    # signal breaks Qt's event delivery for this object.
    telemetry = Signal(object)

    def on_event(self, telemetry_event: TelemetryEvent) -> None:
        """Receive one telemetry event from the core."""
        self.telemetry.emit(telemetry_event)


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


class _GenerateJob(QRunnable):
    """Runs one generation on a pool thread, emitting events as they stream in."""

    def __init__(self, client: Client, spec: GenerationSpec, signals: _Signals) -> None:
        super().__init__()
        self._client = client
        self._spec = spec
        self._signals = signals
        self._cancelled = False
        self._terminal_emitted = False

    def cancel(self) -> None:
        """Ask the job to stop at the next event boundary."""
        self._cancelled = True

    def run(self) -> None:
        """Execute the request, translating stream events into Qt signals.

        Exactly one terminal signal always fires — ``finished``, ``failed``, or
        ``cancelled`` — so the engine's busy state can never be left dangling.
        """
        try:
            with self._client.stream(
                list(self._spec.messages),
                route=self._spec.route,
                schema=self._spec.schema,
                sampling=self._spec.sampling,
                repair=self._spec.repair,
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
    busy_changed = Signal(bool)

    def __init__(self, config: DemoConfig) -> None:
        super().__init__()
        self._pool = QThreadPool(self)
        # Requests are serialized: the demo shows one conversation at a time, and a second
        # concurrent stream would interleave deltas into the same transcript.
        self._pool.setMaxThreadCount(1)
        self._registry = ProviderRegistry()
        self._fake_backend = DemoFakeBackend()
        register_demo_provider(self._registry)
        self._relay = TelemetryRelay()
        self._relay.telemetry.connect(self.telemetry)
        self._config = config
        self._client: Client | None = None
        self._active: _GenerateJob | None = None
        self._busy = False

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
        """Whether a request is in flight."""
        return self._busy

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
        self._pool.clear()
        self._pool.waitForDone(2_000)
        if self._client is not None:
            self._client.close()
            self._client = None

    # ---- work ------------------------------------------------------------------------

    def generate(self, spec: GenerationSpec) -> None:
        """Start a generation on the pool. Ignored while another is running."""
        if self._busy:
            return
        # Rewind the fakes so the flaky model's scripted failure is reproducible on every
        # run rather than only the first.
        self._fake_backend.set_json_mode(spec.schema is not None)
        signals = _Signals()
        signals.text_delta.connect(self.text_delta)
        signals.reasoning_delta.connect(self.reasoning_delta)
        signals.first_token.connect(self.first_token)
        signals.attempt_failed.connect(self.attempt_failed)
        signals.usage_update.connect(self.usage_update)
        signals.finished.connect(self._on_finished)
        signals.failed.connect(self._on_failed)
        signals.cancelled.connect(self._on_cancelled)

        job = _GenerateJob(self.client(), spec, signals)
        self._active = job
        self._set_busy(True)
        self._pool.start(job)

    def cancel(self) -> None:
        """Cancel the in-flight generation, if any."""
        if self._active is not None:
            self._active.cancel()

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

    def _on_finished(self, result: Generation) -> None:
        self._active = None
        self._set_busy(False)
        self.finished.emit(result)

    def _on_failed(self, message: str, error: object) -> None:
        self._active = None
        self._set_busy(False)
        self.failed.emit(message, error)

    def _on_cancelled(self) -> None:
        self._active = None
        self._set_busy(False)
        self.cancelled.emit()

    def _set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)
