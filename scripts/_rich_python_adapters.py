"""Controlled adapter scripts for the rich Python observation driver."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import anyinfer as ai
from anyinfer.providers.base import AdapterFinal, WireRequest


@dataclass
class ScriptLedger:
    """Consumes each literal adapter script once and records real wire requests."""

    scripts: dict[str, dict[str, Any]]
    procedure_ids: tuple[str, ...]
    consumed_ids: list[str] = field(default_factory=list)
    wire_requests: list[Any] = field(default_factory=list)
    wire_providers: list[str] = field(default_factory=list)
    http_bodies: list[dict[str, Any]] = field(default_factory=list)
    http_providers: list[str] = field(default_factory=list)
    cleanup: list[str] = field(default_factory=list)
    barriers: list[str] = field(default_factory=list)
    _ready_events: dict[str, asyncio.Event] = field(default_factory=dict)
    _release_events: dict[str, asyncio.Event] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._pending = deque(self.procedure_ids)

    @classmethod
    def from_case(cls, case: dict[str, Any]) -> ScriptLedger:
        scripts = {script["id"]: script for script in case["scripts"]}
        return cls(scripts, tuple(case["procedure"]["script_ids"]))

    def consume(self, provider: str, model: str, request: Any) -> dict[str, Any]:
        if not self._pending:
            raise RuntimeError(f"unexpected adapter invocation for {provider}:{model}")
        identifier = self._pending.popleft()
        script = self.scripts[identifier]
        if script["provider"] != provider or script["model"] != model:
            raise RuntimeError(f"script {identifier} does not match {provider}:{model}")
        self.consumed_ids.append(identifier)
        self.wire_requests.append(request)
        self.wire_providers.append(provider)
        return script

    def consume_http(self, provider: str) -> dict[str, Any]:
        if not self._pending:
            raise RuntimeError(f"unexpected HTTP invocation for {provider}")
        identifier = self._pending.popleft()
        script = self.scripts[identifier]
        if script["provider"] != provider or script["transport"] != "http":
            raise RuntimeError(f"script {identifier} does not match HTTP provider {provider}")
        self.consumed_ids.append(identifier)
        return script

    def assert_consumed(self) -> None:
        if self._pending:
            raise RuntimeError(f"unconsumed scripts: {', '.join(self._pending)}")

    async def barrier(self, readiness: str, release: str) -> None:
        self.barriers.append(readiness)
        self._ready_events.setdefault(readiness, asyncio.Event()).set()
        await self._release_events.setdefault(release, asyncio.Event()).wait()

    async def wait_ready(self, readiness: str) -> None:
        await self._ready_events.setdefault(readiness, asyncio.Event()).wait()

    def release_barrier(self, identifier: str) -> None:
        self._release_events.setdefault(identifier, asyncio.Event()).set()


class ScriptedAdapter:
    """Public-protocol adapter that emits exactly the next literal action list."""

    def __init__(self, provider: str, ledger: ScriptLedger) -> None:
        self.provider = provider
        self.ledger = ledger

    async def list_models(self) -> tuple[Any, ...]:
        return ()

    async def health(self) -> Any:
        return ai.Health(ok=True)

    def generate(self, request: WireRequest) -> AsyncIterator[Any]:
        script = self.ledger.consume(self.provider, request.model, request)

        async def events() -> AsyncIterator[Any]:
            barrier_cleanup: str | None = None
            try:
                for action in script["actions"]:
                    kind = action["action"]
                    if kind == "text_delta":
                        yield ai.TextDelta(action["text"])
                    elif kind == "reasoning_delta":
                        yield ai.ReasoningDelta(action["text"])
                    elif kind == "tool_call_delta":
                        yield ai.ToolCallDelta(
                            action["index"],
                            action.get("call_id"),
                            action.get("name"),
                            action["arguments_fragment"],
                        )
                    elif kind == "citation_delta":
                        yield ai.CitationDelta(ai.Citation(**action["citation"]))
                    elif kind == "server_tool_delta":
                        yield ai.ServerToolDelta(
                            kind=action["kind"],
                            status=action["status"],
                            sources=tuple(
                                ai.ServerToolSource(**item) for item in action.get("sources", ())
                            ),
                            output=action.get("output", ""),
                            detail=action.get("detail", ""),
                        )
                    elif kind == "adapter_final":
                        yield AdapterFinal(
                            finish_reason=action["finish_reason"],
                            usage=ai.Usage(**action["usage"]) if action.get("usage") else None,
                            phases=action.get("phases", {}),
                            raw=action.get("raw"),
                            logprobs=tuple(
                                ai.TokenLogprob(**item) for item in action.get("logprobs", ())
                            ),
                            server_tool_uses=tuple(
                                ai.ServerToolUse(**item)
                                for item in action.get("server_tool_uses", ())
                            ),
                        )
                    elif kind == "provider_failure":
                        failure = action["failure"]
                        raise ai.ProviderError(
                            failure["detail"],
                            provider=self.provider,
                            retryable=failure["retryable"],
                        )
                    elif kind == "barrier":
                        barrier_cleanup = action.get("finally_cleanup")
                        await self.ledger.barrier(action["readiness"], action["release"])
                        for next_action in action.get("next_actions", ()):
                            yield await self._emit_action(next_action)
                    elif kind == "usage_update":
                        yield ai.UsageUpdate(ai.Usage(**action["usage"]))
                    elif kind in {"http_response", "sse_frame"}:
                        raise RuntimeError("HTTP scripts require the observer transport executor")
                    else:
                        raise ValueError(f"unknown scripted action {kind!r}")
            finally:
                if barrier_cleanup:
                    self.ledger.cleanup.append(f"barrier:{barrier_cleanup}")

        return events()

    async def _emit_action(self, action: dict[str, Any]) -> Any:
        """Emit a barrier's continuation action through the same normalized types."""
        kind = action["action"]
        if kind == "adapter_final":
            return AdapterFinal(
                finish_reason=action["finish_reason"],
                usage=ai.Usage(**action["usage"]) if action.get("usage") else None,
                phases=action.get("phases", {}),
                raw=action.get("raw"),
                logprobs=tuple(ai.TokenLogprob(**item) for item in action.get("logprobs", ())),
                server_tool_uses=tuple(
                    ai.ServerToolUse(**item) for item in action.get("server_tool_uses", ())
                ),
            )
        if kind == "text_delta":
            return ai.TextDelta(action["text"])
        if kind == "reasoning_delta":
            return ai.ReasoningDelta(action["text"])
        if kind == "tool_call_delta":
            return ai.ToolCallDelta(
                action["index"],
                action.get("call_id"),
                action.get("name"),
                action["arguments_fragment"],
            )
        if kind == "citation_delta":
            return ai.CitationDelta(ai.Citation(**action["citation"]))
        if kind == "server_tool_delta":
            return ai.ServerToolDelta(
                kind=action["kind"],
                status=action["status"],
                sources=tuple(ai.ServerToolSource(**item) for item in action.get("sources", ())),
                output=action.get("output", ""),
                detail=action.get("detail", ""),
            )
        if kind == "usage_update":
            return ai.UsageUpdate(ai.Usage(**action["usage"]))
        raise ValueError(f"unsupported barrier continuation action {kind!r}")

    async def aclose(self) -> None:
        self.ledger.cleanup.append(self.provider)
