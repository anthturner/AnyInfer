"""Native timeout observations for the portable core driver recipes.

These recipes deliberately exercise the production ``asyncio.timeout`` boundary.  The
fixture adapter supplies only an offline endpoint; it does not emulate timeout policy.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, cast

from anyinfer._client import generation
from anyinfer._client.async_client import AsyncClient
from anyinfer.errors import AllTargetsFailedError
from anyinfer.routing.policy import Retry, Route
from anyinfer.types.messages import user
from anyinfer.types.requests import Repair
from anyinfer.types.results import ErrorInfo

from .adapter import FixtureProvider, GateController, HarnessError, VirtualClock
from .values import MissingEvidenceError

__all__ = ["observe_timeout_recipe"]

_RECIPE_IDS = frozenset(
    {
        "driver/timeout-effective-default-explicit",
        "driver/timeout-reset-per-entry",
        "driver/timeout-cleanup-disposal",
    }
)
_WATCHDOG_S = 5.0


class _TimeoutSpy:
    """Observe native timeout contexts while delegating their complete behaviour."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._original: Callable[[float | None], Any] | None = None

    @contextmanager
    def installed(self) -> Iterator[None]:
        original = generation.asyncio.timeout
        self._original = original

        def factory(delay: float | None) -> Any:
            native = original(delay)
            record: dict[str, Any] = {
                "context_ordinal": len(self.records),
                "configured_timeout_s": delay,
                "entered": False,
                "exited": False,
                "expired": False,
            }
            self.records.append(record)

            class ObservedTimeout:
                async def __aenter__(self) -> Any:
                    value = await native.__aenter__()
                    record["entered"] = True
                    self_events = spy.events
                    self_events.append(
                        {
                            "event_ordinal": len(self_events),
                            "context_ordinal": record["context_ordinal"],
                            "kind": "enter",
                        }
                    )
                    return value

                async def __aexit__(
                    self,
                    exc_type: type[BaseException] | None,
                    exc: BaseException | None,
                    traceback: Any,
                ) -> bool | None:
                    try:
                        outcome = cast(bool | None, await native.__aexit__(exc_type, exc, traceback))
                        return outcome
                    finally:
                        record["exited"] = True
                        record["expired"] = bool(native.expired())
                        self_events = spy.events
                        self_events.append(
                            {
                                "event_ordinal": len(self_events),
                                "context_ordinal": record["context_ordinal"],
                                "kind": "exit",
                            }
                        )

            return ObservedTimeout()

        spy = self
        generation.asyncio.timeout = factory
        try:
            yield
        finally:
            generation.asyncio.timeout = original
            self._original = None


async def _watch(awaitable: Awaitable[Any], label: str) -> Any:
    """Fail a wedged test harness without giving it an SDK outcome."""
    try:
        return await asyncio.wait_for(awaitable, _WATCHDOG_S)
    except TimeoutError as exc:
        raise HarnessError(f"timeout proof harness stuck while {label}") from exc


def _context_facts(
    records: list[dict[str, Any]], events: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not records:
        raise MissingEvidenceError("native asyncio.timeout created no observable contexts")
    facts: list[dict[str, Any]] = []
    for ordinal, record in enumerate(records):
        if not record["entered"] or not record["exited"]:
            raise MissingEvidenceError("native timeout context did not enter and exit")
        configured = record["configured_timeout_s"]
        if not isinstance(configured, int | float) or isinstance(configured, bool):
            raise MissingEvidenceError("native timeout context did not expose a numeric duration")
        facts.append(
            {
                "ordinal": ordinal,
                "configured_timeout_s": configured,
                "entered": True,
                "exited": True,
                "expired": bool(record["expired"]),
            }
        )
    expected_events = len(records) * 2
    if len(events) != expected_events:
        raise MissingEvidenceError("native timeout context lacks an ordered entry/exit observation")
    event_facts: list[dict[str, Any]] = []
    for event_ordinal, event in enumerate(events):
        if event != {
            "event_ordinal": event_ordinal,
            "context_ordinal": event_ordinal // 2,
            "kind": "enter" if event_ordinal % 2 == 0 else "exit",
        }:
            raise AssertionError("native timeout contexts overlapped or disposed out of entry order")
        event_facts.append(dict(event))
    return facts, event_facts


def _timeout_error_fact(error: BaseException | None) -> dict[str, Any]:
    """Extract the actual routed terminal category without copying diagnostic detail."""
    if not isinstance(error, AllTargetsFailedError):
        raise AssertionError(f"native timeout did not reach routing terminal mapping: {error!r}")
    attempts = error.attempts
    if not attempts:
        raise AssertionError("native timeout terminal error carried no attempt trail")
    last = attempts[-1]
    snapshot = last.error
    category = _snapshot_category(snapshot)
    if category != "transport":
        raise AssertionError(f"native timeout mapped to {category!r}, not transport")
    return {
        "terminal_type": type(error).__name__,
        "attempt_category": category,
        "attempt_error_type": snapshot.type_name if snapshot is not None else None,
        "attempt_count": len(attempts),
    }


def _snapshot_category(snapshot: ErrorInfo | None) -> str:
    """Map the structured, redacted attempt snapshot without reading its detail."""
    if snapshot is None:
        raise MissingEvidenceError("native timeout terminal attempt has no error snapshot")
    categories = {"TransportError": "transport"}
    try:
        return categories[snapshot.type_name]
    except KeyError as exc:
        raise AssertionError(f"native timeout mapped to {snapshot.type_name!r}, not TransportError") from exc


async def _client(provider: FixtureProvider, clock: VirtualClock) -> AsyncClient:
    return AsyncClient(
        [provider.settings], registry=provider.registry, use_default_catalog=False, _clock=clock, _sleep=clock.sleep
    )


async def _effective_default_explicit() -> dict[str, Any]:
    """Observe the default wire budget, explicit budget, and a real explicit expiry."""
    spy = _TimeoutSpy()
    default_provider = FixtureProvider(_adapter([_final("ok")]))
    explicit_provider = FixtureProvider(_adapter([_final("ok")]))
    timeout_provider = FixtureProvider(_adapter([{"events": [{"await_release": "expire"}]}]))
    default_clock, explicit_clock, timeout_clock = VirtualClock(), VirtualClock(), VirtualClock()

    with spy.installed():
        async with await _client(default_provider, default_clock) as client:
            await client.generate((user("default"),), route=_route(), max_response_bytes=777)
        async with await _client(explicit_provider, explicit_clock) as client:
            await client.generate(
                (user("explicit"),), route=_route(), timeout_s=0.05, max_response_bytes=333
            )
        async with await _client(timeout_provider, timeout_clock) as client:
            task = asyncio.create_task(
                client.generate((user("expires"),), route=_route(), timeout_s=0.05)
            )
            await _watch(timeout_provider.gates.wait_ready("expire"), "waiting for timeout readiness")
            try:
                await _watch(task, "waiting for native timeout terminal mapping")
            except Exception as error:
                terminal = _timeout_error_fact(error)
            else:
                raise AssertionError("suspended adapter completed without native timeout")

    contexts, context_events = _context_facts(spy.records, spy.events)
    wires = [
        *cast(list[Any], default_provider.adapter.requests if default_provider.adapter else ()),
        *cast(list[Any], explicit_provider.adapter.requests if explicit_provider.adapter else ()),
        *cast(list[Any], timeout_provider.adapter.requests if timeout_provider.adapter else ()),
    ]
    if len(wires) != 3:
        raise MissingEvidenceError("timeout recipe did not observe every entered wire request")
    observed = [(wire.timeout_s, wire.max_response_bytes) for wire in wires]
    if observed != [(120.0, 777), (0.05, 333), (0.05, 1048576)]:
        raise AssertionError(f"unexpected actual timeout/byte wire settings: {observed!r}")
    if [fact["configured_timeout_s"] for fact in contexts] != [120.0, 0.05, 0.05]:
        raise AssertionError("native contexts did not receive the effective request timeout")
    if contexts[-1]["expired"] is not True:
        raise AssertionError("suspended real adapter entry did not expire its native context")
    return {
        "contexts": contexts,
        "context_events": context_events,
        "wire_timeout_and_bytes": [[a, b] for a, b in observed],
        "terminal": terminal,
    }


async def _reset_per_entry() -> dict[str, Any]:
    """Observe original/correction/restarted entries getting separate full budgets."""
    provider = FixtureProvider(
        _adapter(
            [
                _final('{"name": "wrong"}'),
                {"fail": {"category": "transport", "retryable": True, "phase": "stream"}},
                _final('{"name": "wrong"}'),
                _final('{"age": 7}'),
            ]
        )
    )
    spy, clock = _TimeoutSpy(), VirtualClock()
    schema = {"type": "object", "properties": {"age": {"type": "integer"}}, "required": ["age"]}
    with spy.installed():
        async with await _client(provider, clock) as client:
            result = await client.generate(
                (user("repair"),), route=_route(retry=2), schema=schema, repair=Repair(max_attempts=1), timeout_s=7.25
            )
    contexts, context_events = _context_facts(spy.records, spy.events)
    if result.structured != {"age": 7}:
        raise AssertionError("native correction/restart recipe did not reach its winning result")
    if len(contexts) != 4 or any(fact["configured_timeout_s"] != 7.25 for fact in contexts):
        raise AssertionError("each actual adapter entry did not receive a fresh full timeout")
    if len({id(record) for record in spy.records}) != 4:
        raise AssertionError("timeout contexts were not distinct native creations")
    wires = provider.adapter.requests if provider.adapter else ()
    if len(wires) != 4 or any(wire.timeout_s != 7.25 for wire in wires):
        raise MissingEvidenceError("restart recipe lacks entered wire timeout evidence")
    return {
        "contexts": contexts,
        "context_events": context_events,
        "entry_count": len(wires),
        "wire_timeouts": [wire.timeout_s for wire in wires],
        "winning_repair_attempts": result.repair_attempts,
    }


async def _cleanup_disposal() -> dict[str, Any]:
    """Suspend the real adapter-generator cleanup inside its entry timeout."""
    gates = GateController()
    provider = FixtureProvider(_adapter([_final("cleanup")]), gates=gates)
    spy, clock = _TimeoutSpy(), VirtualClock()
    with spy.installed():
        async with await _client(provider, clock) as client:
            adapter = cast(Any, await client._pool.get("fixture"))
            original = adapter.generate

            async def cleanup_suspended(wire: Any) -> AsyncIterator[Any]:
                events = original(wire)
                try:
                    async for event in events:
                        yield event
                finally:
                    await gates.await_release("cleanup")

            adapter.generate = cleanup_suspended
            task = asyncio.create_task(client.generate((user("cleanup"),), route=_route(), timeout_s=0.05))
            await _watch(gates.wait_ready("cleanup"), "waiting for adapter cleanup readiness")
            try:
                await _watch(task, "waiting for cleanup timeout terminal mapping")
            except Exception as error:
                terminal = _timeout_error_fact(error)
            else:
                raise AssertionError("suspended adapter cleanup completed without native timeout")
    contexts, context_events = _context_facts(spy.records, spy.events)
    if len(contexts) != 1 or not contexts[0]["expired"]:
        raise AssertionError("cleanup did not expire within its one native entry context")
    if provider.adapter is None or not provider.adapter._closed:
        raise AssertionError("client disposal did not close the underlying fixture adapter")
    return {
        "contexts": contexts,
        "context_events": context_events,
        "cleanup_ready": True,
        "adapter_closed": True,
        "terminal": terminal,
    }


def _adapter(script: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "max_repair_attempts": None,
        "models": {"alpha": {"capabilities": {"grammar": False, "json_schema": False, "json_mode": False}}},
        "health_preset": [],
        "script": script,
    }


def _final(text: str) -> dict[str, Any]:
    return {"events": [{"text": text}, {"final": {"finish_reason": "stop", "usage": None}}]}


def _route(*, retry: int = 1) -> Route:
    return Route(targets=("fixture:alpha",), retry=Retry(max_attempts=retry))


async def observe_timeout_recipe(recipe_ref: str) -> dict[str, Any]:
    """Run one native timeout proof and return its actual ordinary-JSON facts."""
    if recipe_ref not in _RECIPE_IDS:
        raise HarnessError(f"unknown timeout proof recipe {recipe_ref!r}")
    recipes: Mapping[str, Callable[[], Awaitable[dict[str, Any]]]] = {
        "driver/timeout-effective-default-explicit": _effective_default_explicit,
        "driver/timeout-reset-per-entry": _reset_per_entry,
        "driver/timeout-cleanup-disposal": _cleanup_disposal,
    }
    return await recipes[recipe_ref]()
