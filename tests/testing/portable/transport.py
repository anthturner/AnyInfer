"""Native HTTP observation runner for the private portable transport corpus."""

from __future__ import annotations

import base64
import contextlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from typing import Any, Literal, cast

import httpx2

from anyinfer._client.async_client import AsyncClient
from anyinfer._client.providers import ProviderSettings
from anyinfer.providers.base import AdapterEvent, AdapterFinal, ProviderConfig, WireRequest
from anyinfer.registry import ProviderRegistry
from anyinfer.schema._capture import capture_enabled
from anyinfer.types.events import StreamEvent, TextDelta, UsageUpdate
from anyinfer.types.requests import Repair, Sampling

from .adapter import HarnessError, VirtualClock
from .comparison import compare_fixture
from .projection import _error, project_run
from .records import NativeRun
from .runner import (
    _core_operation,
    _execute_core_operation,
    _messages,
    _route,
    _sampling,
    _Telemetry,
)
from .values import MissingEvidenceError, control_number_equal, json_value, type_aware_equal

__all__ = ["TransportRun", "compare_transport_fixture", "run_transport_fixture"]


@dataclass(frozen=True, slots=True)
class TransportRun:
    """Facts from one native OpenAI-compatible transport execution."""

    case_id: str
    requests: tuple[WireRequest, ...] = ()
    http_requests: tuple[dict[str, Any], ...] = ()
    delivered_chunks: tuple[tuple[bytes, ...], ...] = ()
    adapter_events: tuple[AdapterEvent, ...] = ()
    core: NativeRun | None = None
    error: BaseException | None = None
    error_stage: Literal["construction", "operation", "harness"] | None = None


class _ByteFactsStream(httpx2.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...], delivered: list[bytes]) -> None:
        self._chunks = chunks
        self._delivered = delivered

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self._delivered.append(chunk)
            yield chunk

    async def aclose(self) -> None:
        return None


class _ResponseScript:
    def __init__(self, responses: Sequence[object]) -> None:
        self._responses = tuple(self._decode(item) for item in responses)
        self.requests: list[dict[str, Any]] = []
        self.delivered: list[list[bytes]] = []
        self.fault: HarnessError | None = None
        self.semantic_headers = {"content-type", "authorization"}

    @staticmethod
    def _decode(item: object) -> tuple[int, dict[str, str], tuple[bytes, ...]]:
        if not isinstance(item, Mapping):
            raise HarnessError("transport response must be an object")
        status, headers, chunks = item.get("status"), item.get("headers"), item.get("byte_chunks")
        if not isinstance(status, int) or isinstance(status, bool):
            raise HarnessError("transport response status must be an integer")
        if not isinstance(headers, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in headers.items()
        ):
            raise HarnessError("transport response headers must be string mappings")
        if not isinstance(chunks, Sequence) or isinstance(chunks, str | bytes):
            raise HarnessError("transport response byte_chunks must be an array")
        decoded: list[bytes] = []
        for chunk in chunks:
            if (
                not isinstance(chunk, Mapping)
                or set(chunk) != {"bytes"}
                or not isinstance(chunk["bytes"], str)
            ):
                raise HarnessError("transport byte chunk must contain only base64 bytes")
            try:
                decoded.append(base64.b64decode(chunk["bytes"], validate=True))
            except ValueError as error:
                raise HarnessError("transport byte chunk is not valid base64") from error
        return status, {key.lower(): value for key, value in headers.items()}, tuple(decoded)

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if len(self.requests) >= len(self._responses):
            self.fault = HarnessError("transport script has no remaining response")
            raise self.fault
        status, headers, chunks = self._responses[len(self.requests)]
        try:
            body = json.loads(request.content)
        except ValueError as error:
            raise HarnessError("native transport request body is not JSON") from error
        if not isinstance(body, Mapping):
            raise HarnessError("native transport request body is not an object")
        semantic_headers = {
            key.lower(): value
            for key, value in request.headers.items()
            if key.lower() in self.semantic_headers
        }
        self.requests.append(
            {
                "method": request.method,
                "path": request.url.path,
                "headers": semantic_headers,
                "body": dict(body),
                "stream": body.get("stream") is True,
            }
        )
        delivered: list[bytes] = []
        self.delivered.append(delivered)
        stream = _ByteFactsStream(chunks, delivered)
        response = httpx2.Response(status, headers=headers, stream=stream, request=request)
        return response

    def verify_consumed(self) -> None:
        if self.fault is not None:
            raise self.fault
        if len(self.requests) != len(self._responses):
            raise HarnessError("transport script has unused responses")


class _RecordingAdapter:
    """Thin per-run recorder around the actual registered adapter."""

    def __init__(self, delegate: Any, requests: list[WireRequest]) -> None:
        self._delegate = delegate
        self._requests = requests

    async def list_models(self) -> Any:
        return await self._delegate.list_models()

    async def health(self) -> Any:
        return await self._delegate.health()

    async def aclose(self) -> None:
        await self._delegate.aclose()

    async def generate(self, wire: WireRequest) -> AsyncIterator[AdapterEvent]:
        self._requests.append(wire)
        async with contextlib.aclosing(self._delegate.generate(wire)) as events:
            async for event in events:
                yield event


def _script(fixture: Mapping[str, Any]) -> _ResponseScript:
    responses = fixture.get("responses")
    if not isinstance(responses, Sequence) or isinstance(responses, str | bytes):
        raise HarnessError("transport fixture responses must be an array")
    return _ResponseScript(responses)


def _settings(config: object, script: _ResponseScript) -> ProviderSettings:
    if not isinstance(config, Mapping):
        raise HarnessError("transport input.adapter_config must be an object")
    provider_id = config.get("provider_id")
    base_url = config.get("base_url")
    api_key = config.get("api_key")
    headers = config.get("headers")
    timeout_s = config.get("timeout_s")
    if (
        provider_id != "openai-compat"
        or base_url != "https://fixture.invalid/v1"
        or api_key != "fixture-token"
        or not isinstance(headers, Mapping)
        or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in headers.items()
        )
        or not isinstance(timeout_s, int | float)
        or isinstance(timeout_s, bool)
    ):
        raise HarnessError("transport adapter_config is invalid")
    script.semantic_headers.update(key.lower() for key in headers)
    return ProviderSettings(
        provider_id=provider_id,
        base_url=base_url,
        api_key=api_key,
        headers=cast(dict[str, str], dict(headers)),
        timeout_s=timeout_s,
        transport=httpx2.MockTransport(script.handler),
    )


def _registry(requests: list[WireRequest]) -> ProviderRegistry:
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    descriptor = registry.get("openai-compat")
    factory = descriptor.factory

    def recording_factory(config: ProviderConfig) -> _RecordingAdapter:
        return _RecordingAdapter(factory(config), requests)

    registry.register(dataclass_replace(descriptor, factory=recording_factory), replace=True)
    return registry


def _wire(value: object) -> WireRequest:
    if not isinstance(value, Mapping):
        raise HarnessError("transport input.wire must be an object")
    messages = _messages(value.get("messages"))
    sampling = _sampling(value.get("sampling")) or Sampling()
    fields = {
        "model": value.get("model"),
        "mechanism": value.get("mechanism"),
        "stream": value.get("stream"),
        "timeout_s": value.get("timeout_s"),
        "max_response_bytes": value.get("max_response_bytes"),
    }
    if not isinstance(fields["model"], str) or not isinstance(fields["stream"], bool):
        raise HarnessError("transport wire model and stream are required")
    if fields["mechanism"] not in {None, "prompt"}:
        raise HarnessError("transport wire mechanism must be null or prompt")
    if not isinstance(fields["timeout_s"], int | float) or isinstance(fields["timeout_s"], bool):
        raise HarnessError("transport wire timeout_s must be numeric")
    if not isinstance(fields["max_response_bytes"], int) or isinstance(
        fields["max_response_bytes"], bool
    ):
        raise HarnessError("transport wire max_response_bytes must be an integer")
    return WireRequest(
        model=fields["model"],
        messages=messages,
        sampling=sampling,
        mechanism=fields["mechanism"],
        stream=fields["stream"],
        timeout_s=fields["timeout_s"],
        max_response_bytes=fields["max_response_bytes"],
    )


async def run_transport_fixture(fixture: Mapping[str, Any]) -> TransportRun:
    """Execute a transport fixture against an actual OpenAI-compatible adapter."""
    case_id = fixture.get("id")
    if not isinstance(case_id, str):
        raise ValueError("transport fixture id must be a string")
    try:
        input_data = fixture.get("input")
        if not isinstance(input_data, Mapping):
            raise HarnessError("transport fixture input must be an object")
        script = _script(fixture)
        requests: list[WireRequest] = []
        registry = _registry(requests)
        settings = _settings(input_data.get("adapter_config"), script)
        kind = fixture.get("kind")
        if kind == "adapter":
            return await _run_adapter(case_id, input_data, script, registry, settings, requests)
        if kind == "core_http":
            return await _run_core(case_id, input_data, script, registry, settings, requests)
        raise HarnessError("transport fixture kind must be adapter or core_http")
    except Exception as error:
        return TransportRun(
            case_id=case_id,
            error=error,
            error_stage="harness" if isinstance(error, HarnessError) else "construction",
        )


def _facts(
    case_id: str, script: _ResponseScript, requests: list[WireRequest], **kwargs: Any
) -> TransportRun:
    delivered = tuple(tuple(row) for row in script.delivered)
    return TransportRun(
        case_id=case_id,
        requests=tuple(requests),
        http_requests=tuple(script.requests),
        delivered_chunks=delivered,
        **kwargs,
    )


async def _run_adapter(
    case_id: str,
    input_data: Mapping[str, Any],
    script: _ResponseScript,
    registry: ProviderRegistry,
    settings: ProviderSettings,
    requests: list[WireRequest],
) -> TransportRun:
    wire = _wire(input_data.get("wire"))
    adapter = registry.get("openai-compat").factory(
        ProviderConfig(
            provider_id=settings.provider_id,
            base_url=settings.base_url,
            api_key=settings.api_key,
            headers=settings.headers,
            timeout_s=settings.timeout_s,
            transport=settings.transport,
        )
    )
    events: list[AdapterEvent] = []
    error: BaseException | None = None
    try:
        try:
            async with contextlib.aclosing(cast(Any, adapter).generate(wire)) as iterator:
                async for event in iterator:
                    events.append(event)
        except Exception as caught:
            error = caught
        try:
            script.verify_consumed()
        except HarnessError as script_fault:
            error = script_fault
    finally:
        await adapter.aclose()
    return _facts(
        case_id,
        script,
        requests,
        adapter_events=tuple(events),
        error=error,
        error_stage="harness"
        if isinstance(error, HarnessError)
        else "operation"
        if error
        else None,
    )


async def _run_core(
    case_id: str,
    input_data: Mapping[str, Any],
    script: _ResponseScript,
    registry: ProviderRegistry,
    settings: ProviderSettings,
    requests: list[WireRequest],
) -> TransportRun:
    operation = input_data.get("operation")
    if not isinstance(operation, Mapping):
        fault = HarnessError("transport input.operation must be an object")
        native = NativeRun(case_id=case_id, error=fault, error_stage="harness")
        return _facts(case_id, script, requests, core=native, error=fault, error_stage="harness")
    request = operation.get("request")
    if not isinstance(request, Mapping):
        fault = HarnessError("transport operation request must be an object")
        native = NativeRun(case_id=case_id, error=fault, error_stage="harness")
        return _facts(case_id, script, requests, core=native, error=fault, error_stage="harness")
    input_schema = request.get("schema")

    def failed(
        error: BaseException,
        *,
        stage: Literal["construction", "harness"],
        origin: Literal["messages", "route", "sampling", "repair"] | None = None,
        messages: tuple[Any, ...] | None = None,
    ) -> TransportRun:
        native = NativeRun(
            case_id=case_id,
            error=error,
            error_stage=stage,
            construction_origin=origin,
            input_messages=messages,
            input_schema=input_schema,
        )
        return _facts(case_id, script, requests, core=native, error=error, error_stage=stage)

    try:
        messages = _messages(request.get("messages"))
    except ValueError as caught:
        return failed(caught, stage="construction", origin="messages")
    except Exception as caught:
        return failed(caught, stage="harness")
    try:
        route = _route(operation.get("route"))
    except ValueError as caught:
        return failed(caught, stage="construction", origin="route", messages=messages)
    except Exception as caught:
        return failed(caught, stage="harness", messages=messages)
    try:
        sampling = _sampling(request.get("sampling"))
    except ValueError as caught:
        return failed(caught, stage="construction", origin="sampling", messages=messages)
    except Exception as caught:
        return failed(caught, stage="harness", messages=messages)
    repair_data = request.get("repair")
    try:
        if repair_data is not None and not isinstance(repair_data, Mapping):
            raise HarnessError("transport core repair must be an object or null")
        repair = Repair(**dict(repair_data)) if repair_data is not None else None
    except ValueError as caught:
        return failed(caught, stage="construction", origin="repair", messages=messages)
    except Exception as caught:
        return failed(caught, stage="harness", messages=messages)
    core_operation = _core_operation(
        request,
        messages=messages,
        route=route,
        sampling=sampling,
        repair=repair,
    )
    consume = core_operation.consume
    if consume not in {"buffered", "stream"}:
        fault = HarnessError("transport core consume must be buffered or stream")
        return failed(fault, stage="harness", messages=messages)
    events: list[StreamEvent] = []
    result = None
    error: BaseException | None = None
    stage: Literal["operation", "harness"] | None = None
    observer = _Telemetry()
    clock = VirtualClock(0)
    with capture_enabled() as operations:
        async with AsyncClient(
            [settings],
            registry=registry,
            use_default_catalog=False,
            observers=[observer],
            _clock=clock,
            _sleep=clock.sleep,
        ) as client:
            try:
                result = await _execute_core_operation(client, core_operation, events)
            except Exception as caught:
                error = caught
                stage = "harness" if isinstance(caught, HarnessError) else "operation"
            try:
                script.verify_consumed()
            except HarnessError as script_fault:
                error, stage = script_fault, "harness"
    native = NativeRun(
        case_id=case_id,
        events=tuple(events),
        result=result,
        error=error,
        error_stage=stage,
        operations=tuple(operations),
        requests=tuple(requests),
        input_messages=messages,
        input_schema=core_operation.schema,
        consumption_mode=consume,
        telemetry=tuple(observer.events),
        clock_advances_ms=tuple(delay * 1000 for delay in clock.sleeps),
    )
    return _facts(case_id, script, requests, core=native, error=error, error_stage=stage)


def _adapter_event(event: AdapterEvent) -> dict[str, Any]:
    if isinstance(event, TextDelta):
        return {"text_delta": {"text": event.text}}
    if isinstance(event, UsageUpdate):
        usage = event.usage
        return {
            "usage": {
                name: getattr(usage, name)
                for name in (
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                    "reasoning_tokens",
                )
            }
        }
    if isinstance(event, AdapterFinal):
        final_usage = event.usage
        return {
            "final": {
                "finish_reason": event.finish_reason,
                "usage": None
                if final_usage is None
                else {
                    name: getattr(final_usage, name)
                    for name in (
                        "input_tokens",
                        "output_tokens",
                        "total_tokens",
                        "cache_read_tokens",
                        "cache_write_tokens",
                        "reasoning_tokens",
                    )
                },
            }
        }
    raise MissingEvidenceError(f"unprojectable adapter event {type(event).__name__}")


def _error_projection(error: BaseException | None, stage: str | None) -> dict[str, Any] | None:
    if error is None:
        return None
    try:
        return _error(error, stage=stage)
    except MissingEvidenceError:
        return {"native_type": type(error).__name__}


def _wire_limits(run: TransportRun) -> list[dict[str, int | float]]:
    return [
        {"timeout_s": wire.timeout_s, "max_response_bytes": wire.max_response_bytes}
        for wire in run.requests
    ]


def _adapter_outcome(run: TransportRun) -> dict[str, Any]:
    if run.error is not None:
        error = _error_projection(run.error, run.error_stage)
        if error is None or "native_type" in error:
            raise MissingEvidenceError("adapter error has no portable projection")
        return {"error": error}
    return {"events": [_adapter_event(event) for event in run.adapter_events]}


def _observation(run: TransportRun) -> dict[str, Any]:
    observed: dict[str, Any] = {
        "status": "observed",
        "http_requests": list(run.http_requests),
        "wire_limits": _wire_limits(run),
    }
    if run.core is not None:
        observed["core"] = project_run(run.core)
    else:
        observed["adapter_outcome"] = _adapter_outcome(run)
    return cast(dict[str, Any], json_value(observed))


def _http_equal(wanted: Any, actual: Any) -> bool:
    if type_aware_equal(wanted, actual):
        return True
    if not isinstance(wanted, list) or not isinstance(actual, list) or len(wanted) != len(actual):
        return False
    for left, right in zip(wanted, actual, strict=True):
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            return False
        if set(left) != set(right) or any(
            not type_aware_equal(left.get(field), right.get(field))
            for field in ("method", "path", "headers", "stream")
        ):
            return False
        left_body, right_body = left.get("body"), right.get("body")
        if not isinstance(left_body, Mapping) or not isinstance(right_body, Mapping):
            return False
        if set(left_body) != set(right_body):
            return False
        for key, value in left_body.items():
            candidate = right_body[key]
            if key in {"temperature", "top_p", "presence_penalty", "frequency_penalty"}:
                if not control_number_equal(value, candidate):
                    return False
            elif not type_aware_equal(value, candidate):
                return False
    return True


def _limits_equal(wanted: Any, actual: Any) -> bool:
    if not isinstance(wanted, list) or not isinstance(actual, list) or len(wanted) != len(actual):
        return False
    for left, right in zip(wanted, actual, strict=True):
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            return False
        if set(left) != {"timeout_s", "max_response_bytes"} or set(right) != set(left):
            return False
        if not control_number_equal(left["timeout_s"], right["timeout_s"]):
            return False
        if not type_aware_equal(left["max_response_bytes"], right["max_response_bytes"]):
            return False
    return True


def compare_transport_fixture(fixture: Mapping[str, Any], run: TransportRun) -> dict[str, Any]:
    """Return a fail-closed development comparison for one transport observation."""
    result: dict[str, Any] = {
        "id": fixture.get("id"),
        "verdict": "error",
        "detail": None,
        "observations": None,
    }
    try:
        observed = _observation(run)
        result["observations"] = observed
    except MissingEvidenceError as error:
        result["detail"] = str(error)
        return result
    expected = fixture.get("expected")
    if not isinstance(expected, Mapping):
        result["detail"] = "transport fixture expected value is missing"
        return result
    if expected.get("status") == "to_be_observed":
        result.update(
            verdict=None,
            detail="pending native observation",
            evidence={
                "delivered_byte_chunks": [
                    [base64.b64encode(chunk).decode("ascii") for chunk in response]
                    for response in run.delivered_chunks
                ]
            },
        )
        return result
    if run.error is not None and run.error_stage == "harness":
        result["detail"] = f"transport harness fault: {type(run.error).__name__}"
        return result
    differences: list[str] = []
    if not _http_equal(expected.get("http_requests"), observed.get("http_requests")):
        differences.append("http_requests")
    if not _limits_equal(expected.get("wire_limits"), observed.get("wire_limits")):
        differences.append("wire_limits")
    if run.core is not None:
        wanted_core = expected.get("core")
        operation = fixture.get("input")
        request = (
            operation.get("operation", {}).get("request")
            if isinstance(operation, Mapping)
            else None
        )
        if not isinstance(wanted_core, Mapping) or not isinstance(request, Mapping):
            differences.append("core")
        else:
            nested = compare_fixture(
                {"id": fixture.get("id"), "request": request, "expected": wanted_core}, run.core
            )
            if nested["verdict"] == "error":
                result.update(
                    verdict="error",
                    detail=f"core comparison unavailable: {nested['detail']}",
                    evidence={
                        "delivered_byte_chunks": [
                            [base64.b64encode(chunk).decode("ascii") for chunk in response]
                            for response in run.delivered_chunks
                        ]
                    },
                )
                return result
            if nested["verdict"] != "pass":
                detail = nested["detail"]
                differences.append(f"core: {detail or 'observation differs'}")
    elif not type_aware_equal(expected.get("adapter_outcome"), observed.get("adapter_outcome")):
        differences.append("adapter_outcome")
    if differences:
        result.update(verdict="fail", detail="; ".join(differences))
    else:
        result["verdict"] = "pass"
    result["evidence"] = {
        "delivered_byte_chunks": [
            [base64.b64encode(chunk).decode("ascii") for chunk in response]
            for response in run.delivered_chunks
        ]
    }
    return result
