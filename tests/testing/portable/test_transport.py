"""Focused native HTTP transport-runner coverage with controlled scripts."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from collections.abc import AsyncIterator
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

from anyinfer.providers import openai_compat
from anyinfer.providers.base import AdapterEvent, WireRequest
from anyinfer.types.events import TextDelta
from anyinfer.types.messages import user

from .adapter import HarnessError
from .reference import _validator_module
from .transport import _RecordingAdapter, compare_transport_fixture, run_transport_fixture


def _chunk(value: bytes) -> dict[str, str]:
    return {"bytes": base64.b64encode(value).decode("ascii")}


def _response(text: str = "hello", *, status: int = 200) -> dict[str, object]:
    payload = {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }
    return {
        "status": status,
        "headers": {"content-type": "application/json"},
        "byte_chunks": [_chunk(json.dumps(payload).encode())],
    }


def _config(*, header: str = "yes", timeout_s: float = 23.0) -> dict[str, Any]:
    return {
        "provider_id": "openai-compat",
        "base_url": "https://fixture.invalid/v1",
        "api_key": "fixture-token",
        "headers": {"client-tag": header},
        "timeout_s": timeout_s,
    }


def _fixture(*, stream: bool = False, responses: list[object] | None = None) -> dict[str, Any]:
    return {
        "fixture_version": "0",
        "id": "transport/openai-chat/controlled",
        "family": "transport/openai-chat",
        "profile": "core-generation",
        "description": "controlled native OpenAI-compatible transport",
        "kind": "adapter",
        "input": {
            "adapter_config": _config(),
            "wire": {
                "model": "fixture-model",
                "messages": [{"role": "user", "text": "hello"}],
                "sampling": {"temperature": 0.25},
                "mechanism": None,
                "stream": stream,
                "timeout_s": 17.0,
                "max_response_bytes": 4096,
            },
        },
        "responses": responses if responses is not None else [_response()],
        "expected": {"status": "to_be_observed"},
    }


def _validate(tmp_path: Path, fixture: dict[str, Any], *, name: str = "controlled") -> list[str]:
    path = tmp_path / "transport" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixture), encoding="utf-8")
    return cast(
        list[str],
        _validator_module().validate(
            tmp_path, specification_root=Path("specification"), fixture_paths=[path]
        ),
    )


def _expected_adapter(*, stream: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "fixture-model",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.25,
    }
    if stream:
        body.update(stream=True, stream_options={"include_usage": True})
    usage = {
        "input_tokens": 2,
        "output_tokens": 1,
        "total_tokens": 3,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "reasoning_tokens": None,
    }
    events: list[dict[str, Any]] = [{"text_delta": {"text": "hello"}}]
    if not stream:
        events.append({"usage": usage})
    events.append({"final": {"finish_reason": "stop", "usage": usage}})
    return {
        "status": "observed",
        "http_requests": [
            {
                "method": "POST",
                "path": "/v1/chat/completions",
                "headers": {
                    "content-type": "application/json",
                    "authorization": "Bearer fixture-token",
                    "client-tag": "yes",
                },
                "body": body,
                "stream": stream,
            }
        ],
        "wire_limits": [{"timeout_s": 17.0, "max_response_bytes": 4096}],
        "adapter_outcome": {"events": events},
    }


def _expected_core() -> dict[str, Any]:
    expected = _expected_adapter()
    expected.pop("adapter_outcome")
    expected["core"] = {
        "status": "observed",
        "calls": [
            {
                "model": "fixture-model",
                "role": "original",
                "mechanism": None,
                "timeout_s": 17.0,
                "max_response_bytes": 4096,
                "messages": [{"role": "user", "text": "hello"}],
            }
        ],
        "clock_advances_ms": [],
        "telemetry": {"repair_attempted": [], "parameter_dropped": []},
        "events": [],
        "outcome": {
            "result": {
                "text": "hello",
                "structured": None,
                "target": {"provider_id": "openai-compat", "model": "fixture-model"},
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": 2,
                    "output_tokens": 1,
                    "total_tokens": 3,
                    "cache_read_tokens": None,
                    "cache_write_tokens": None,
                    "reasoning_tokens": None,
                },
                "timing": {"first_token_ms": "non_null", "total_ms": "present"},
                "structured_mechanism": None,
                "repair_attempts": 0,
                "attempts": [{"target": "openai-compat:fixture-model", "outcome": "ok"}],
                "warnings": [],
            }
        },
        "accounting": None,
    }
    return expected


def _as_core(fixture: dict[str, Any]) -> dict[str, Any]:
    fixture["id"] = "transport/openai-chat/core-controlled"
    fixture["kind"] = "core_http"
    fixture["input"] = {
        "adapter_config": _config(),
        "operation": {
            "request": {
                "messages": [{"role": "user", "text": "hello"}],
                "sampling": {"temperature": 0.25},
                "consume": "buffered",
                "timeout_s": 17.0,
                "max_response_bytes": 4096,
                "schema": None,
                "repair": {"max_attempts": 0},
            },
            "route": {
                "targets": ["openai-compat:fixture-model"],
                "retry": {"max_attempts": 1},
            },
        },
    }
    return fixture


async def test_transport_direct_observes_real_http_request_config_and_native_wire(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    fixture["expected"] = _expected_adapter()
    assert _validate(tmp_path, fixture) == []
    run = await run_transport_fixture(fixture)
    assert run.error is None and len(run.requests) == 1
    assert run.requests[0].timeout_s == 17.0 and run.requests[0].max_response_bytes == 4096
    request = run.http_requests[0]
    assert request["method"] == "POST" and request["path"] == "/v1/chat/completions"
    assert request["headers"] == {
        "content-type": "application/json",
        "authorization": "Bearer fixture-token",
        "client-tag": "yes",
    }
    assert request["body"]["temperature"] == 0.25 and "top_p" not in request["body"]
    comparison = compare_transport_fixture(fixture, run)
    assert comparison["verdict"] == "pass", comparison["detail"]


async def test_transport_configured_semantic_header_and_timeout_reach_actual_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_timeouts: list[float | None] = []
    compat_module = cast(Any, openai_compat)
    original = compat_module.build_client

    def recording_build_client(*args: Any, **kwargs: Any) -> Any:
        observed_timeouts.append(kwargs["timeout_s"])
        return original(*args, **kwargs)

    monkeypatch.setattr(compat_module, "build_client", recording_build_client)
    fixture = _fixture()
    fixture["input"]["adapter_config"] = _config(header="observed", timeout_s=41.5)
    assert _validate(tmp_path, fixture) == []
    run = await run_transport_fixture(fixture)
    assert run.error is None and run.http_requests[0]["headers"]["client-tag"] == "observed"
    assert observed_timeouts == [41.5]
    assert run.requests[0].timeout_s == 17.0


async def test_transport_stream_preserves_literal_split_sse_byte_facts(tmp_path: Path) -> None:
    payload = (
        b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
        + b'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}\n\n'
        + b"data: [DONE]\n\n"
    )
    fixture = _fixture(
        stream=True,
        responses=[
            {
                "status": 200,
                "headers": {"content-type": "text/event-stream"},
                "byte_chunks": [
                    _chunk(payload[:19]),
                    _chunk(payload[19:71]),
                    _chunk(payload[71:]),
                ],
            }
        ],
    )
    assert _validate(tmp_path, fixture) == []
    run = await run_transport_fixture(fixture)
    assert (
        run.error is None
        and len(run.delivered_chunks[0]) == 3
        and b"".join(run.delivered_chunks[0]) == payload
    )
    assert [type(event).__name__ for event in run.adapter_events] == [
        "TextDelta",
        "TextDelta",
        "AdapterFinal",
    ]
    assert compare_transport_fixture(fixture, run)["verdict"] is None


async def test_transport_protocol_and_cap_faults_are_native_operation_errors(
    tmp_path: Path,
) -> None:
    malformed = _fixture(
        responses=[
            {
                "status": 200,
                "headers": {"content-type": "application/json"},
                "byte_chunks": [_chunk(b"not json")],
            }
        ]
    )
    assert _validate(tmp_path, malformed) == []
    malformed_run = await run_transport_fixture(malformed)
    capped = _fixture()
    capped["input"]["wire"]["max_response_bytes"] = 1
    assert _validate(tmp_path, capped, name="capped") == []
    capped_run = await run_transport_fixture(capped)
    assert malformed_run.error is not None and malformed_run.error_stage == "operation"
    assert capped_run.error is not None and capped_run.error_stage == "operation"


async def test_transport_observed_adapter_mismatch_fails(tmp_path: Path) -> None:
    fixture = _fixture()
    fixture["expected"] = _expected_adapter()
    fixture["expected"]["http_requests"] = []
    assert _validate(tmp_path, fixture) == []
    run = await run_transport_fixture(fixture)
    assert compare_transport_fixture(fixture, run)["verdict"] == "fail"


async def test_transport_core_keeps_native_capture_and_pending_observation(tmp_path: Path) -> None:
    fixture = _as_core(_fixture())
    fixture["expected"] = _expected_core()
    assert _validate(tmp_path, fixture) == []
    run = await run_transport_fixture(fixture)
    assert (
        run.core is not None
        and run.core.requests == run.requests
        and len(run.core.operations) == 1
    )
    comparison = compare_transport_fixture(fixture, run)
    assert comparison["verdict"] == "pass", comparison["observations"]["core"]["outcome"]
    bad = deepcopy(fixture)
    bad["input"]["operation"]["request"]["consume"] = "close_without_advance"
    problems = _validate(tmp_path, bad, name="bad-consume")
    assert any("close_without_advance" in problem for problem in problems)
    refused = await run_transport_fixture(bad)
    assert isinstance(refused.error, HarnessError) and refused.error_stage == "harness"


@pytest.mark.parametrize(
    "responses", [[], [_response(), _response()]], ids=["exhausted", "surplus"]
)
async def test_transport_script_exhaustion_and_surplus_are_harness_faults(
    tmp_path: Path, responses: list[object]
) -> None:
    fixture = _fixture(responses=responses)
    assert _validate(tmp_path, fixture) == []
    run = await run_transport_fixture(fixture)
    assert isinstance(run.error, HarnessError) and run.error_stage == "harness"


@pytest.mark.parametrize("kind", ["adapter", "core_http"])
async def test_transport_native_error_does_not_hide_surplus_script_fault(
    tmp_path: Path, kind: str
) -> None:
    fixture = _fixture(responses=[_response(status=503), _response()])
    if kind == "core_http":
        fixture = _as_core(fixture)
    assert _validate(tmp_path, fixture) == []
    run = await run_transport_fixture(fixture)
    assert isinstance(run.error, HarnessError) and run.error_stage == "harness"


async def test_transport_core_retry_uses_virtual_backoff_and_orders_native_facts(
    tmp_path: Path,
) -> None:
    fixture = _as_core(_fixture(responses=[_response(status=503), _response("retry")]))
    fixture["input"]["operation"]["route"]["retry"] = {
        "max_attempts": 2,
        "backoff_base_s": 0.25,
        "backoff_max_s": 0.25,
    }
    assert _validate(tmp_path, fixture, name="retry") == []

    run = await run_transport_fixture(fixture)

    assert run.core is not None and run.error is None
    assert run.core.clock_advances_ms == (250.0,)
    assert len(run.http_requests) == 2
    assert [entry.entry_ordinal for entry in run.core.operations[0].entries] == [0, 1]
    assert [wire.model for wire in run.requests] == ["fixture-model", "fixture-model"]


async def test_transport_core_sampling_construction_preserves_typed_facts(tmp_path: Path) -> None:
    fixture = _as_core(_fixture())
    assert _validate(tmp_path, fixture, name="sampling-baseline") == []
    invalid = deepcopy(fixture)
    request = invalid["input"]["operation"]["request"]
    request["sampling"] = {"seed": -1}

    run = await run_transport_fixture(invalid)

    assert run.core is not None
    assert run.core.error_stage == "construction"
    assert run.core.construction_origin == "sampling"
    assert run.core.input_schema is None
    assert run.core.input_messages is not None
    assert run.http_requests == () and run.requests == () and run.core.operations == ()


async def test_transport_core_repair_retains_schema_telemetry_and_default_consume(
    tmp_path: Path,
) -> None:
    fixture = _as_core(
        _fixture(
            responses=[
                _response('{"age": 6}'),
                _response('{"age": 7}'),
            ]
        )
    )
    request = fixture["input"]["operation"]["request"]
    request.pop("consume")
    request["schema"] = {
        "type": "object",
        "required": ["age"],
        "properties": {"age": {"type": "integer", "minimum": 7}},
    }
    request["repair"] = {"max_attempts": 1}
    assert _validate(tmp_path, fixture, name="repair") == []

    run = await run_transport_fixture(fixture)

    assert run.core is not None and run.error is None
    assert run.core.input_schema == request["schema"]
    assert run.core.consumption_mode == "buffered"
    assert len(run.requests) == 2 and len(run.core.operations[0].entries) == 2
    assert [type(event).__name__ for event in run.core.telemetry] == ["RepairAttempted"]


class _DelegatingProbe:
    def __init__(self) -> None:
        self.wire: object | None = None
        self.iterator_closed = False
        self.adapter_closed = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def list_models(self) -> list[object]:
        return []

    async def health(self) -> object:
        return object()

    async def aclose(self) -> None:
        self.adapter_closed = True

    async def generate(self, wire: WireRequest) -> AsyncIterator[AdapterEvent]:
        self.wire = wire
        try:
            self.entered.set()
            yield TextDelta("native")
            await self.release.wait()
        finally:
            self.iterator_closed = True


def _wire_request() -> WireRequest:
    return WireRequest(model="fixture-model", messages=(user("hello"),))


async def test_transport_recorder_forwards_identity_and_closes_delegated_iterator() -> None:
    delegate = _DelegatingProbe()
    requests: list[WireRequest] = []
    recorder = _RecordingAdapter(delegate, requests)
    wire = _wire_request()
    iterator = cast(Any, recorder.generate(wire))
    event = await anext(iterator)
    await iterator.aclose()
    await recorder.aclose()
    assert isinstance(event, TextDelta) and event.text == "native"
    assert (
        delegate.wire is wire
        and requests == [wire]
        and delegate.iterator_closed
        and delegate.adapter_closed
    )


async def test_transport_recorder_does_not_suppress_cancellation_or_fatal_delegate_errors() -> (
    None
):
    delegate = _DelegatingProbe()
    recorder = _RecordingAdapter(delegate, [])
    wire = _wire_request()

    async def consume_until_cancelled() -> None:
        async with contextlib.aclosing(cast(Any, recorder.generate(wire))) as events:
            async for _ in events:
                await delegate.release.wait()

    task = asyncio.create_task(consume_until_cancelled())
    await delegate.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert delegate.iterator_closed

    class FatalDelegate(_DelegatingProbe):
        async def generate(self, wire: WireRequest) -> AsyncIterator[AdapterEvent]:
            if wire.model == "unreachable":
                yield TextDelta("unreachable")
                return
            raise SystemExit("fatal delegate failure")

    with pytest.raises(SystemExit, match="fatal delegate failure"):
        await anext(_RecordingAdapter(FatalDelegate(), []).generate(wire))
