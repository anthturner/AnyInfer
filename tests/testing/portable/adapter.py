"""In-process adapter used by the portable core-generation driver tests.

The fixture adapter deliberately replays only adapter-level observations.  Routing,
schema validation, repairs, and timeout policy stay in :class:`AsyncClient`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from anyinfer._client.providers import ProviderSettings
from anyinfer.errors import (
    AuthError,
    ContextLengthError,
    ModelNotFoundError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
    StreamProtocolError,
    TransportError,
    UnsupportedInputError,
)
from anyinfer.providers.base import AdapterEvent, AdapterFinal, ProviderConfig, WireRequest
from anyinfer.registry import ProviderDescriptor, ProviderRegistry
from anyinfer.types.capabilities import (
    DiscoveredModel,
    Feature,
    Health,
    ModelCapabilities,
    Sourced,
)
from anyinfer.types.events import TextDelta, UsageUpdate
from anyinfer.types.results import Usage

__all__ = ["FixtureProvider", "GateController", "HarnessError", "ScriptError", "VirtualClock"]


class HarnessError(RuntimeError):
    """A fixture harness fault, deliberately distinct from a provider failure."""


class ScriptError(HarnessError):
    """The fixture adapter script was malformed or did not have another entry."""


class VirtualClock:
    """A monotonic clock for core backoff and health tests, not native timeouts."""

    def __init__(self, start_ms: int = 0) -> None:
        self._seconds = start_ms / 1_000
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self._seconds

    async def sleep(self, delay: float) -> None:
        if delay:
            self.sleeps.append(delay)
            self._seconds += delay
        await asyncio.sleep(0)


class GateController:
    """Coordinate literal ``await_release`` script actions with a test driver."""

    def __init__(self, *, watchdog_s: float = 30.0) -> None:
        self._ready: dict[str, asyncio.Event] = {}
        self._released: dict[str, asyncio.Event] = {}
        self._watchdog_s = watchdog_s

    def _event(self, events: dict[str, asyncio.Event], gate_id: str) -> asyncio.Event:
        return events.setdefault(gate_id, asyncio.Event())

    async def wait_ready(self, gate_id: str) -> None:
        try:
            await asyncio.wait_for(self._event(self._ready, gate_id).wait(), self._watchdog_s)
        except TimeoutError as exc:
            raise HarnessError(f"gate {gate_id!r} was not reached by the adapter") from exc

    def release(self, gate_id: str) -> None:
        self._event(self._released, gate_id).set()

    async def await_release(self, gate_id: str) -> None:
        self._event(self._ready, gate_id).set()
        try:
            await asyncio.wait_for(self._event(self._released, gate_id).wait(), self._watchdog_s)
        except TimeoutError as exc:
            raise HarnessError(f"gate {gate_id!r} was not released by the driver") from exc


_FailureCategory = Literal[
    "auth",
    "rate_limit",
    "transport",
    "provider_unavailable",
    "model_not_found",
    "context_length",
    "stream_protocol",
    "unsupported_input",
]

_FAILURE_TYPES: Mapping[_FailureCategory, type[ProviderError]] = {
    "auth": AuthError,
    "rate_limit": RateLimitError,
    "transport": TransportError,
    "provider_unavailable": ProviderUnavailableError,
    "model_not_found": ModelNotFoundError,
    "context_length": ContextLengthError,
    "stream_protocol": StreamProtocolError,
    "unsupported_input": UnsupportedInputError,
}

_USAGE_FIELDS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
    }
)


def _usage(value: object) -> Usage | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) - _USAGE_FIELDS:
        raise ScriptError("script usage must contain only portable token fields")
    if any(not isinstance(item, int) and item is not None for item in value.values()):
        raise ScriptError("script usage values must be integers or null")
    return Usage(**dict(value))


def _failure(value: object, provider_id: str) -> ProviderError:
    if not isinstance(value, Mapping):
        raise ScriptError("script failure must be an object")
    category = value.get("category")
    if category not in _FAILURE_TYPES:
        raise ScriptError("script failure has an unknown category")
    retryable = value.get("retryable")
    if retryable is not None and not isinstance(retryable, bool):
        raise ScriptError("script failure retryable must be a boolean")
    phase = value.get("phase")
    if phase is not None and phase not in {"configure", "discover", "generate", "stream", "validate", "cleanup"}:
        raise ScriptError("script failure has an unknown phase")
    kwargs: dict[str, Any] = {"provider": provider_id}
    for field in ("retryable", "retry_after_s", "http_status"):
        if field in value:
            kwargs[field] = value[field]
    if phase is not None:
        kwargs["phase"] = phase
    failure_type = _FAILURE_TYPES[cast(_FailureCategory, category)]
    return failure_type(f"fixture scripted {category} failure", **kwargs)


@dataclass(frozen=True, slots=True)
class CleanupRecord:
    """One cleanup-failure action reached by an adapter entry."""

    entry_ordinal: int


class _FixtureAdapter:
    def __init__(
        self,
        config: ProviderConfig,
        *,
        models: Mapping[str, ModelCapabilities],
        script: Sequence[Mapping[str, Any]],
        gates: GateController,
    ) -> None:
        self._provider_id = config.provider_id
        self._models = models
        self._script = tuple(script)
        self._gates = gates
        self._next_entry = 0
        self._closed = False
        self.requests: list[WireRequest] = []
        self.entry_ordinals: list[int] = []
        self.cleanup_records: list[CleanupRecord] = []

    async def list_models(self) -> Sequence[DiscoveredModel]:
        return tuple(DiscoveredModel(model_id, capabilities) for model_id, capabilities in self._models.items())

    async def health(self) -> Health:
        return Health(True)

    async def aclose(self) -> None:
        self._closed = True

    def generate(self, wire: WireRequest) -> AsyncIterator[AdapterEvent]:
        """Record the real wire request before returning its native async iterator."""
        ordinal = self._next_entry
        self._next_entry += 1
        self.requests.append(wire)
        self.entry_ordinals.append(ordinal)
        if ordinal >= len(self._script):
            raise ScriptError("fixture adapter script exhausted")
        return self._replay(self._script[ordinal], ordinal)

    async def _replay(self, entry: Mapping[str, Any], ordinal: int) -> AsyncIterator[AdapterEvent]:
        events = entry.get("events")
        failure = entry.get("fail")
        cleanup_failure = entry.get("fail_in_cleanup")
        if failure is not None and cleanup_failure is not None:
            raise ScriptError("script entry cannot have both fail and fail_in_cleanup")
        if events is None:
            if failure is None:
                raise ScriptError("script entry needs events or fail")
            raise _failure(failure, self._provider_id)
        if not isinstance(events, list):
            raise ScriptError("script events must be a list")
        final_seen = False
        try:
            for action in events:
                if not isinstance(action, Mapping) or len(action) != 1:
                    raise ScriptError("script action must be a one-field object")
                name, value = next(iter(action.items()))
                if name == "text":
                    if not isinstance(value, str):
                        raise ScriptError("text action needs a string")
                    yield TextDelta(value)
                elif name == "usage":
                    yield UsageUpdate(_usage(value) or Usage())
                elif name == "await_release":
                    if not isinstance(value, str) or not value:
                        raise ScriptError("await_release needs a nonempty gate id")
                    await self._gates.await_release(value)
                elif name == "final":
                    if final_seen or not isinstance(value, Mapping):
                        raise ScriptError("script entry has an invalid final action")
                    finish_reason = value.get("finish_reason", "stop")
                    if finish_reason not in {"stop", "length", "tool_calls", "content_filter", "other"}:
                        raise ScriptError("script final has an unknown finish reason")
                    final_seen = True
                    yield AdapterFinal(finish_reason=finish_reason, usage=_usage(value.get("usage")))
                else:
                    raise ScriptError(f"unknown script action {name!r}")
            if failure is not None:
                raise _failure(failure, self._provider_id)
            if cleanup_failure is not None and not final_seen:
                raise ScriptError("fail_in_cleanup requires a final action")
        finally:
            if cleanup_failure is not None and final_seen:
                self.cleanup_records.append(CleanupRecord(ordinal))
                raise _failure(cleanup_failure, self._provider_id)


class FixtureProvider:
    """Register one isolated fixture adapter with a fresh registry and settings object."""

    def __init__(self, adapter_config: Mapping[str, Any], *, gates: GateController | None = None) -> None:
        self._config = dict(adapter_config)
        self.gates = gates or GateController()
        models = self._model_capabilities(self._config.get("models"))
        script = self._config.get("script")
        if not isinstance(script, list) or not all(isinstance(item, Mapping) for item in script):
            raise ScriptError("adapter config script must be a list of objects")
        ceiling = self._config.get("max_repair_attempts")
        if ceiling is not None and (not isinstance(ceiling, int) or isinstance(ceiling, bool)):
            raise ScriptError("max_repair_attempts must be an integer or null")
        self.registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
        self.adapter: _FixtureAdapter | None = None

        def factory(config: ProviderConfig) -> _FixtureAdapter:
            adapter = _FixtureAdapter(config, models=models, script=script, gates=self.gates)
            self.adapter = adapter
            return adapter

        descriptor = ProviderDescriptor(
            id="fixture",
            display_name="Portable fixture",
            factory=factory,
            static_capabilities=models,
            default_capabilities=ModelCapabilities(
                features=Sourced(Feature.STREAMING | Feature.SYSTEM_PROMPT, "catalog")
            ),
            max_repair_attempts=ceiling,
        )
        self.registry.register(descriptor, replace=True)
        self.settings = ProviderSettings(provider_id="fixture", options=self._config)

    @staticmethod
    def _model_capabilities(value: object) -> Mapping[str, ModelCapabilities]:
        if not isinstance(value, Mapping) or not value:
            raise ScriptError("adapter config must declare models")
        models: dict[str, ModelCapabilities] = {}
        expected = {"grammar": False, "json_schema": False, "json_mode": False}
        for model_id, model in value.items():
            if not isinstance(model_id, str) or not isinstance(model, Mapping):
                raise ScriptError("adapter model declarations must be objects keyed by id")
            if model.get("capabilities") != expected:
                raise ScriptError("fixture model capabilities must be the portable false flags")
            models[model_id] = ModelCapabilities(
                features=Sourced(Feature.STREAMING | Feature.SYSTEM_PROMPT, "catalog")
            )
        return models
