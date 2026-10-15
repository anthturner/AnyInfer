"""Execute portable fixture inputs through the native AsyncClient without judging them."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Literal

from anyinfer._client.async_client import AsyncClient
from anyinfer.events.telemetry import ParameterDropped, RepairAttempted
from anyinfer.routing.policy import Retry, Route
from anyinfer.schema._capture import capture_enabled
from anyinfer.types.events import StreamEvent
from anyinfer.types.messages import ImagePart, Message, Text, assistant, system, user
from anyinfer.types.requests import Repair, Sampling

from .adapter import FixtureProvider, HarnessError, ScriptError, VirtualClock
from .records import NativeRun


class _Telemetry:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def on_event(self, event: Any) -> None:
        if isinstance(event, RepairAttempted | ParameterDropped):
            self.events.append(event)


def _messages(value: object) -> tuple[Message, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise HarnessError("fixture request.messages must be an array")
    result: list[Message] = []
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            raise HarnessError("fixture message must have a role")
        role = item["role"]
        if "parts" in item:
            parts = item["parts"]
            if not isinstance(parts, Sequence):
                raise HarnessError("fixture message.parts must be an array")
            content: list[Any] = []
            for part in parts:
                if not isinstance(part, Mapping):
                    raise HarnessError("fixture part must be an object")
                if part.get("kind") == "text" and isinstance(part.get("text"), str):
                    content.append(Text(part["text"]))
                elif part.get("kind") == "image_url" and isinstance(part.get("url"), str):
                    content.append(ImagePart(url=part["url"], media_type=part.get("media_type", "image/png")))
                else:
                    raise HarnessError("unsupported fixture input part")
            result.append(Message(role=role, content=tuple(content)))
            continue
        text = item.get("text")
        if isinstance(text, list):
            if not all(isinstance(part, str) for part in text):
                raise HarnessError("fixture message.text parts must be text")
            result.append(Message(role=role, content=tuple(Text(part) for part in text)))
            continue
        joined = text
        if not isinstance(joined, str):
            raise HarnessError("fixture message.text must be text")
        if role == "system":
            result.append(system(joined))
        elif role == "user":
            result.append(user(joined))
        elif role == "assistant":
            result.append(assistant(joined))
        elif role == "tool":
            result.append(Message(role="tool", content=(Text(joined),)))
        else:
            raise HarnessError("unknown fixture message role")
    return tuple(result)


def _sampling(value: object) -> Sampling | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise HarnessError("fixture sampling must be an object")
    return Sampling(**dict(value))


def _route(value: object) -> Route:
    if not isinstance(value, Mapping):
        raise HarnessError("fixture route must be an object")
    retry = value.get("retry", {})
    if not isinstance(retry, Mapping):
        raise HarnessError("fixture retry must be an object")
    targets = value.get("targets")
    if not isinstance(targets, Sequence) or isinstance(targets, str | bytes):
        raise HarnessError("fixture route.targets must be an array")
    if not all(isinstance(target, str) for target in targets):
        raise HarnessError("fixture route.targets must contain strings")
    return Route(
        targets=tuple(targets),
        retry=Retry(**dict(retry)),
        health_gate=value.get("health_gate", True),
        health_ttl_s=value.get("health_ttl_s", 30.0),
    )


async def run_fixture(fixture: Mapping[str, Any], *, with_mirror: bool = True) -> NativeRun:
    """Observe one fixture input through a fresh native client.

    This reads no expected field: records contain only facts from the request path.
    """
    case_id = fixture.get("id")
    if not isinstance(case_id, str):
        raise ValueError("fixture id must be a string")
    if with_mirror and case_id == "streaming/buffered-equals-streamed":
        primary = await run_fixture(fixture, with_mirror=False)
        mirrored = dict(fixture)
        request = dict(fixture["request"])
        request["consume"] = "buffered"
        mirrored["request"] = request
        return replace(primary, mirror=await run_fixture(mirrored, with_mirror=False))
    try:
        request = fixture["request"]
        adapter = fixture["adapter"]
        if not isinstance(request, Mapping) or not isinstance(adapter, Mapping):
            raise HarnessError("fixture request and adapter are required objects")
        clock_data = fixture.get("clock", {})
        clock = VirtualClock(int(clock_data.get("start_ms", 0)) if isinstance(clock_data, Mapping) else 0)
        provider = FixtureProvider(adapter)
        observer = _Telemetry()
    except Exception as construction_error:
        return NativeRun(case_id=case_id, error=construction_error, error_stage="harness")

    try:
        messages = _messages(request.get("messages"))
    except ValueError as error:
        return NativeRun(case_id=case_id, error=error, error_stage="construction", construction_origin="messages", input_schema=request.get("schema"))
    except Exception as construction_error:
        return NativeRun(case_id=case_id, error=construction_error, error_stage="harness")

    try:
        route = _route(fixture.get("route"))
    except ValueError as error:
        return NativeRun(case_id=case_id, error=error, error_stage="construction", construction_origin="route", input_messages=messages, input_schema=request.get("schema"))
    except Exception as construction_error:
        return NativeRun(case_id=case_id, error=construction_error, error_stage="harness", input_messages=messages, input_schema=request.get("schema"))

    try:
        sampling = _sampling(request.get("sampling"))
    except ValueError as error:
        return NativeRun(case_id=case_id, error=error, error_stage="construction", construction_origin="sampling", input_messages=messages, input_schema=request.get("schema"))
    except Exception as construction_error:
        return NativeRun(case_id=case_id, error=construction_error, error_stage="harness", input_messages=messages, input_schema=request.get("schema"))

    try:
        repair_data = request.get("repair")
        if repair_data is not None and not isinstance(repair_data, Mapping):
            raise HarnessError("fixture repair must be an object or null")
        repair = Repair(**dict(repair_data)) if repair_data is not None else None
        consume = request.get("consume", "buffered")
    except ValueError as error:
        return NativeRun(case_id=case_id, error=error, error_stage="construction", construction_origin="repair", input_messages=messages, input_schema=request.get("schema"))
    except Exception as construction_error:
        return NativeRun(case_id=case_id, error=construction_error, error_stage="harness", input_messages=messages, input_schema=request.get("schema"))
    events: list[StreamEvent] = []
    consumption_mode: Literal["buffered", "stream"] | None = None
    result = None
    operation_error: BaseException | None = None
    stage: Literal["construction", "operation", "harness"] | None = None
    with capture_enabled() as operations:
      async with AsyncClient([provider.settings], registry=provider.registry, use_default_catalog=False, observers=[observer], _clock=clock, _sleep=clock.sleep) as client:
        presets = adapter.get("health_preset", [])
        if isinstance(presets, list):
            for preset in presets:
                if isinstance(preset, Mapping):
                    clock._seconds = int(preset["failed_at_ms"]) / 1000
                    client._health.mark_failed(client.resolve(str(preset["target"])))
            clock_data = fixture.get("clock", {})
            if isinstance(clock_data, Mapping):
                clock._seconds = int(clock_data.get("start_ms", 0)) / 1000
        try:
            if consume == "buffered":
                consumption_mode = "buffered"
                result = await client.generate(messages, route=route, schema=request.get("schema"), sampling=sampling, repair=repair, timeout_s=request.get("timeout_s"), max_response_bytes=request.get("max_response_bytes"))
            else:
                consumption_mode = "stream"
                stream = client.stream(messages, route=route, schema=request.get("schema"), sampling=sampling, repair=repair, timeout_s=request.get("timeout_s"), max_response_bytes=request.get("max_response_bytes"))
                if consume == "close_without_advance":
                    await stream.aclose()
                elif isinstance(consume, str) and consume.startswith("stream_cancel_after_events:"):
                    gate_ids = [
                        next(iter(action.values()))
                        for entry in adapter.get("script", [])
                        if isinstance(entry, Mapping)
                        for action in entry.get("events", [])
                        if isinstance(action, Mapping) and set(action) == {"await_release"}
                    ]

                    async def drain() -> None:
                        async with stream:
                            async for event in stream:
                                events.append(event)

                    task = asyncio.create_task(drain())
                    try:
                        if len(gate_ids) != 1:
                            raise HarnessError("cancellation requires exactly one fixture gate")
                        await provider.gates.wait_ready(str(gate_ids[0]))
                        threshold = int(consume.rsplit(":", 1)[1])
                        if threshold < 1:
                            raise HarnessError("cancellation event threshold must be positive")
                        if len(events) != threshold:
                            raise HarnessError("cancellation gate did not establish the requested public-event threshold")
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError as cancelled:
                            operation_error, stage = cancelled, "operation"
                    finally:
                        if not task.done():
                            task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                else:
                    async with stream:
                        async for event in stream:
                            events.append(event)
                    result = stream.result
                    if consume == "close_twice_after_end":
                        await stream.aclose()
                        await stream.aclose()
        except asyncio.CancelledError:
            raise
        except Exception as caught:
            operation_error, stage = caught, "harness" if isinstance(caught, HarnessError | ScriptError) else "operation"
    native = NativeRun(case_id=case_id, events=tuple(events), result=result, error=operation_error, error_stage=stage, telemetry=tuple(observer.events), operations=tuple(operations), requests=tuple(provider.adapter.requests if provider.adapter else ()), clock_advances_ms=tuple(delay * 1000 for delay in clock.sleeps), cleanup_records=tuple(provider.adapter.cleanup_records if provider.adapter else ()), input_messages=messages, input_schema=request.get("schema"), consumption_mode=consumption_mode)
    return native
