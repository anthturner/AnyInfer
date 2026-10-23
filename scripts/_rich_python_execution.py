"""Execute literal rich-generation inputs through AnyInfer's public clients."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from enum import Enum
from typing import Any

import httpx2
from _rich_observation_python import canonical_data, serialization_evidence
from _rich_python_adapters import ScriptedAdapter, ScriptLedger

import anyinfer as ai
from anyinfer.events import event_to_dict
from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced
from anyinfer.types.events import (
    AttemptFailed,
    CitationDelta,
    ReasoningDelta,
    ServerToolDelta,
    StreamEnded,
    TextDelta,
    TimingMark,
    ToolCallDelta,
    UsageUpdate,
)

_FEATURES = {
    "streaming": Feature.STREAMING,
    "json_schema": Feature.JSON_SCHEMA,
    "grammar": Feature.GRAMMAR,
    "json_mode": Feature.JSON_MODE,
    "tools": Feature.TOOLS,
    "reasoning": Feature.REASONING,
    "system_prompt": Feature.SYSTEM_PROMPT,
    "cache_usage": Feature.CACHE_USAGE,
    "cache_placement": Feature.CACHE_PLACEMENT,
    "image": Feature.VISION,
    "document": Feature.DOCUMENT,
    "audio": Feature.AUDIO_IN,
    "logprobs": Feature.LOGPROBS,
    "video": Feature.VIDEO_IN,
    "citations": Feature.CITATIONS,
    "web_search": Feature.WEB_SEARCH,
    "code_execution": Feature.CODE_EXECUTION,
    "server_tools": Feature.WEB_SEARCH | Feature.CODE_EXECUTION,
}
_MISSING = object()


class ObservedMockTransport(httpx2.AsyncBaseTransport):
    """Wrap the fixture mock at its real async transport lifecycle boundary."""

    def __init__(self, handler: Any, ledger: ScriptLedger, provider_id: str) -> None:
        self._transport = httpx2.MockTransport(handler)
        self._ledger = ledger
        self._provider_id = provider_id
        self._closed = False

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._transport.aclose()
        self._ledger.cleanup.append(f"server:{self._provider_id}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if dataclasses.is_dataclass(value):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _features(descriptor: dict[str, Any]) -> Feature:
    result = Feature(0)
    for name in descriptor.get("features", ()):
        result |= _FEATURES[name]
    return result


def _registry(case: dict[str, Any], ledger: ScriptLedger) -> tuple[Any, list[Any]]:
    registry = ai.ProviderRegistry(load_builtins=False, load_entry_points=False)
    settings = []
    for item in case["descriptors"]:
        provider_id = item["id"]
        adapter = ScriptedAdapter(provider_id, ledger)
        capabilities = ModelCapabilities(
            features=Sourced(_features(item), item.get("features_provenance", "default"))
        )
        provider_scripts = [
            script for script in case["scripts"] if script["provider"] == provider_id
        ]
        http_scripts = [script for script in provider_scripts if script["transport"] == "http"]
        adapter_scripts = [
            script for script in provider_scripts if script["transport"] == "adapter"
        ]
        wire_support = set(item.get("wire_support", ()))
        use_builtin = not adapter_scripts and (
            bool(http_scripts)
            or "openai" in wire_support
            or (not provider_scripts and ai.default_registry.has(provider_id))
        )
        if use_builtin:

            def handle(actual_request: Any, *, _provider_id: str = provider_id) -> Any:
                body = json.loads(actual_request.content or b"{}")
                ledger.http_bodies.append(body)
                ledger.http_providers.append(_provider_id)
                selected = ledger.consume_http(_provider_id)
                if not selected["actions"]:
                    raise RuntimeError(f"HTTP script {selected['id']} has no response action")
                response = selected["actions"][0]
                status = response["status"]
                headers = response.get("headers", {})
                content = response["body"].encode("utf-8")
                return httpx2.Response(
                    status, headers=headers, content=content, request=actual_request
                )

            transport = ObservedMockTransport(handle, ledger, provider_id)
            # A literal `openai` wire-support descriptor denotes generic Chat
            # Completions even when the fixture registers the id `openai`.
            template_id = "openai-compat" if "openai" in wire_support else provider_id
            template = ai.default_registry.get(template_id)
            descriptor = replace(
                template,
                id=provider_id,
                aliases=(),
                static_capabilities={item["model"]: capabilities},
            )
            registry.register(descriptor)
            settings.append(
                ai.ProviderSettings(
                    provider_id=provider_id,
                    base_url="https://fixture.invalid/v1",
                    api_key="fixture-key",
                    transport=transport,
                )
            )
        else:
            registry.register(
                ai.ProviderDescriptor(
                    id=provider_id,
                    display_name=provider_id,
                    factory=lambda _config, instance=adapter: instance,
                    static_capabilities={item["model"]: capabilities},
                    supports_sessions="sessions" in item.get("wire_support", ()),
                    server_tools=frozenset(
                        tool["kind"] for tool in case["request"].get("server_tools", ())
                    )
                    if "server_tools" in item.get("wire_support", ())
                    else frozenset(),
                )
            )
            settings.append(ai.ProviderSettings(provider_id=provider_id))
    return registry, settings


class TelemetryRecorder:
    """Collect the actual default observer stream without opting into payloads."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def on_event(self, event: Any) -> None:
        self.events.append(event)


def telemetry_projection(events: list[Any]) -> list[dict[str, Any]]:
    records = []
    for item in events:
        name = type(item).__name__
        common = {"event": name, "request_id": getattr(item, "request_id", "")}
        if name == "TargetResolved":
            stable = {**common, "target": _target(item.target)}
        elif name == "RequestStarted":
            stable = {
                **common,
                "targets": list(item.targets),
                "metadata": [
                    {"key": key, "value": value} for key, value in sorted(item.metadata.items())
                ],
                "operation": item.operation,
                "prompt_text": item.prompt_text,
            }
        elif name == "AttemptStarted":
            stable = {
                **common,
                "target": _target(item.target),
                "attempt_number": item.attempt_number,
            }
        elif name == "AttemptCompleted":
            stable = {
                **common,
                "target": _target(item.target),
                "usage": _usage(item.usage),
                "timing": _timing(item.timing),
                "finish_reason": item.finish_reason,
            }
        elif name == "RequestCompleted":
            stable = {
                **common,
                "target": _target(item.target),
                "usage": _usage(item.usage),
                "timing": _timing(item.timing),
                "repair_attempts": item.repair_attempts,
                "response_text": item.response_text,
            }
        elif name == "RepairAttempted":
            stable = {
                **common,
                "target": _target(item.target),
                "attempt_number": item.attempt_number,
                "mechanism": item.mechanism,
                "errors": list(item.errors),
                "raw_text": item.raw_text,
            }
        elif name == "FallbackTriggered":
            stable = {
                **common,
                "from_target": _target(item.from_target),
                "to_target": item.to_target,
                "error": _error_projection(item.error),
            }
        elif name == "ParameterDropped":
            stable = {
                **common,
                "target": _target(item.target),
                "parameter": item.parameter,
                "reason": item.reason,
            }
        elif name == "RequestFailed":
            stable = {**common, "error": _error_projection(item.error)}
        elif name == "FirstToken":
            stable = {
                **common,
                "target": _target(item.target),
                "at_ms_present": item.at_ms is not None,
            }
        elif name == "UsageEstimated":
            stable = {
                **common,
                "target": _target(item.target),
                "field_name": item.field_name,
                "method": item.method,
            }
        elif name == "RetryScheduled":
            stable = {
                **common,
                "target": _target(item.target),
                "attempt_number": item.attempt_number,
                "delay_s": item.delay_s,
                "error": _error_projection(item.error),
            }
        else:
            raise TypeError(f"telemetry event not represented by frozen schema: {name}")
        # The serialized evidence is from the actual typed event's complete field set,
        # after the SDK's normal payload stripping has already run.
        serialized = event_to_dict(item)
        records.append(
            {
                "stable": stable,
                "serialized": serialization_evidence(
                    serialized, scope="telemetry", event_type=name
                ),
            }
        )
    return records


def manifest_projection(result: Any) -> dict[str, Any] | None:
    manifest = getattr(result, "manifest", None)
    if manifest is None:
        return None
    # Use the product's own serializer so field-path and marker evidence reflects the
    # default manifest representation, not a parallel dataclass walk.
    value = json.loads(manifest.to_json(indent=None))
    request = value["request"]
    shape = {
        "message_count": request["message_count"],
        "role_counts": [
            {"role": role, "count": count} for role, count in request["role_counts"].items()
        ],
        "schema_present": request["schema_present"],
        "schema_name": request["schema_name"],
        "tool_names": request["tool_names"],
        "tool_choice": request["tool_choice"],
        "metadata_keys": request["metadata_keys"],
    }
    return {
        "operation": value["operation"],
        "target": _target(result.target),
        "request": shape,
        "payloads": "present" if value.get("payloads") is not None else "null",
        "serialized": serialization_evidence(value, scope="manifest"),
    }


def _event(event: Any, attempt_number: int = 1) -> dict[str, Any]:
    if isinstance(event, (TextDelta, ReasoningDelta)):
        return {"type": type(event).__name__, "text": event.text}
    if isinstance(event, ToolCallDelta):
        return {
            "type": "ToolCallDelta",
            "index": event.index,
            "call_id": event.call_id,
            "name": event.name,
            "arguments_fragment": event.arguments_fragment,
        }
    if isinstance(event, CitationDelta):
        item = event.citation
        return {
            "type": "CitationDelta",
            "citation": {
                "start_index": item.start_index,
                "end_index": item.end_index,
                "quoted_text": item.quoted_text,
                "document_index": item.document_index,
                "title": item.title,
                "uri": item.uri,
            },
        }
    if isinstance(event, ServerToolDelta):
        return {
            "type": "ServerToolDelta",
            "kind": event.kind,
            "status": event.status,
            "sources": [{"url": source.url, "title": source.title} for source in event.sources],
            "output": event.output,
            "detail": event.detail,
        }
    if isinstance(event, UsageUpdate):
        return {"type": "UsageUpdate", "usage": _jsonable(event.usage)}
    if isinstance(event, TimingMark):
        return {"type": "TimingMark", "name": event.name}
    if isinstance(event, AttemptFailed):
        record = event.record
        return {
            "type": "AttemptFailed",
            "record": {
                "target": _target(record.target),
                "attempt_number": attempt_number,
                "outcome": record.outcome,
                "error": _error_projection(record.error),
                "timing": _timing(record.timing),
            },
        }
    if isinstance(event, StreamEnded):
        return {"type": "StreamEnded", "result": _result(event.result)}
    raise TypeError(f"unhandled public stream event {type(event).__name__}")


def _target(value: Any) -> dict[str, Any]:
    if value is None:
        return {"provider_id": "", "model": "", "via_alias": None}
    return {"provider_id": value.provider_id, "model": value.model, "via_alias": value.via_alias}


def _usage(value: Any) -> dict[str, Any]:
    if value is None:
        value = ai.Usage()
    result = {
        name: _jsonable(getattr(value, name))
        for name in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
            "cost_usd",
            "search_units",
        )
    }
    result["server_tool_uses"] = [
        {"kind": kind, "uses": count} for kind, count in sorted(value.server_tool_uses.items())
    ]
    return result


def _timing(value: Any) -> dict[str, Any]:
    return {
        "first_token_present": value is not None and value.first_token_ms is not None,
        "total_present": value is not None and value.total_ms is not None,
        "phase_order": list(value.phases) if value is not None else [],
    }


def _error_projection(error: Any) -> dict[str, Any] | None:
    if error is None:
        return None
    if isinstance(error, asyncio.CancelledError):
        detail = None
    elif hasattr(error, "detail"):
        detail = error.detail
    else:
        detail = str(error)
    return {
        "type_name": getattr(error, "type_name", type(error).__name__),
        "provider": getattr(error, "provider", None),
        "phase": getattr(error, "phase", None),
        "retryable": bool(getattr(error, "retryable", False)),
        "retry_after_s": getattr(error, "retry_after_s", None),
        "http_status": getattr(error, "http_status", None),
        "detail": detail,
        "hint": getattr(error, "hint", None),
    }


def _result(value: Any) -> dict[str, Any]:
    return {
        "text": value.text,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": canonical_data(call.arguments)}
            for call in value.tool_calls
        ],
        "target": _target(value.target),
        "finish_reason": value.finish_reason,
        "usage": _usage(value.usage),
        "logprobs": _jsonable(value.logprobs),
        "citations": _jsonable(value.citations),
        "server_tool_uses": _jsonable(value.server_tool_uses),
        "raw": value.raw,
        "timing": _timing(value.timing),
        "attempts": [
            {
                "target": _target(item.target),
                "attempt_number": index,
                "outcome": item.outcome,
                "error": _error_projection(item.error),
                "timing": _timing(item.timing),
            }
            for index, item in enumerate(value.attempts, 1)
        ],
        "warnings": list(value.warnings),
    }


def _part_projection(value: Any) -> dict[str, Any]:
    kind = type(value).__name__
    if kind == "Text":
        return {"type": "text", "text": value.text}
    if kind == "ToolCall":
        return {
            "type": "tool_call",
            "id": value.id,
            "name": value.name,
            "arguments": canonical_data(value.arguments),
        }
    if kind == "ToolResult":
        return {
            "type": "tool_result",
            "call_id": value.call_id,
            "content": value.content,
            "is_error": value.is_error,
        }
    data = getattr(value, "data", None)
    evidence = (
        None if data is None else {"length": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    )
    if kind == "ImagePart":
        return {
            "type": "image",
            "data": evidence,
            "url": value.url,
            "media_type": value.media_type,
            "detail": value.detail,
        }
    if kind == "DocumentPart":
        return {
            "type": "document",
            "data": evidence,
            "url": value.url,
            "media_type": value.media_type,
            "filename": value.filename,
        }
    if kind == "AudioPart":
        return {"type": "audio", "data": evidence, "media_type": value.media_type}
    if kind == "VideoPart":
        return {
            "type": "video",
            "data": evidence,
            "url": value.url,
            "media_type": value.media_type,
            "start_offset_s": value.start_offset_s,
            "end_offset_s": value.end_offset_s,
            "fps": value.fps,
        }
    raise TypeError(f"unhandled adapter content part {kind}")


def _wire_request(value: Any) -> dict[str, Any]:
    return {
        "model": value.model,
        "messages": [
            {"role": message.role, "content": [_part_projection(part) for part in message.content]}
            for message in value.messages
        ],
        "sampling": _jsonable(value.sampling),
        "reasoning_wire": canonical_data(value.reasoning_wire),
        "mechanism": value.mechanism,
        "wire_schema": None if value.wire_schema is None else canonical_data(value.wire_schema),
        "schema_name": value.schema_name,
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": canonical_data(tool.parameters),
                "annotations": _jsonable(tool.annotations),
            }
            for tool in value.tools
        ],
        "tool_choice": value.tool_choice,
        "stream": value.stream,
        "timeout_s": value.timeout_s,
        "max_response_bytes": value.max_response_bytes,
        "cache_marks": list(value.cache_marks),
        "server_tools": [
            {"kind": tool.kind, "max_uses": tool.max_uses} for tool in value.server_tools
        ],
        "cite_documents": value.cite_documents,
        "logprobs": value.logprobs,
        "extra_options": canonical_data(value.extra_options),
        "session_state": _session_state(value),
    }


def _session_state(value: Any) -> dict[str, Any]:
    """Preserve absent, explicit null, and non-null session-state values."""
    state = getattr(value, "session_state", _MISSING)
    if state is _MISSING:
        return {"state": "absent"}
    if state is None:
        return {"state": "null"}
    return {"state": "value", "value": canonical_data(state)}


def _http_body(value: Any) -> Any:
    """Project actual HTTP JSON while replacing inline media bytes by digest evidence."""
    if isinstance(value, dict):
        projected = {}
        for key, item in value.items():
            if key in {"data", "file_data"} and isinstance(item, str):
                encoded = (
                    item.split(",", 1)[1]
                    if item.startswith("data:") and ";base64," in item
                    else item
                )
                try:
                    decoded = base64.b64decode(encoded, validate=True)
                except (ValueError, base64.binascii.Error):
                    projected[key] = _http_body(item)
                else:
                    projected[key] = {
                        "byte_evidence": {
                            "length": len(decoded),
                            "sha256": hashlib.sha256(decoded).hexdigest(),
                        }
                    }
            else:
                projected[key] = _http_body(item)
        return projected
    if isinstance(value, list):
        return [_http_body(item) for item in value]
    if isinstance(value, str) and value.startswith("data:") and ";base64," in value:
        _header, encoded = value.split(",", 1)
        decoded = base64.b64decode(encoded, validate=True)
        return {
            "byte_evidence": {
                "length": len(decoded),
                "sha256": hashlib.sha256(decoded).hexdigest(),
            }
        }
    return value


async def execute_async(
    case: dict[str, Any], request: ai.GenerationRequest, ledger: ScriptLedger
) -> tuple[list[dict[str, Any]], Any, BaseException | None, list[dict[str, str]], list[Any]]:
    registry, providers = _registry(case, ledger)
    raw_case_request = case["request"]
    raw_route = raw_case_request.get("route")
    route = None
    if raw_route:
        route = ai.Route(
            tuple(raw_route["targets"]),
            retry=ai.Retry(**raw_route["retry"]) if raw_route.get("retry") else ai.Retry(),
            health_gate=raw_route.get("health_gate", True),
        )
    client_options = case["client"]
    telemetry = TelemetryRecorder()
    client = ai.AsyncClient(
        providers,
        registry=registry,
        route=route,
        observers=(telemetry,),
        retain_raw=raw_case_request["retain_raw"],
        manifests=raw_case_request["manifest"],
        manifest_payloads=False,
        use_default_catalog=client_options.get("use_default_catalog", True),
        context_gate=client_options.get("context_gate", True),
    )
    events: list[dict[str, Any]] = []
    result = None
    error = None
    cleanup: list[dict[str, str]] = []
    kwargs = {
        "target": raw_case_request.get("target"),
        "route": route,
        "schema": request.schema,
        "tools": request.tools,
        "tool_choice": request.tool_choice,
        "sampling": request.sampling,
        "reasoning": request.reasoning,
        "timeout_s": request.timeout_s,
        "repair": request.repair,
        "logprobs": request.logprobs,
        "cite_documents": request.cite_documents,
        "server_tools": request.server_tools,
        "provider_options": request.provider_options,
        "metadata": request.metadata,
        "max_response_bytes": request.max_response_bytes,
        "max_input_part_bytes": request.max_input_part_bytes,
        "max_input_bytes": request.max_input_bytes,
    }
    kwargs = {key: value for key, value in kwargs.items() if value is not None}
    try:
        procedure = case["procedure"]["name"]
        if procedure == "async_generate":
            result = await client.generate(request.messages, **kwargs)
        elif procedure in {"async_stream", "async_stream_close", "async_stream_cancel"}:
            stream = client.stream(request.messages, **kwargs)
            if procedure == "async_stream":
                async with stream:
                    async for event in stream:
                        if isinstance(event, StreamEnded):
                            result = event.result
                        attempt_number = max(
                            1,
                            sum(
                                1
                                for item in events
                                if item.get("type") == "TimingMark"
                                and item.get("name") == "attempt_start"
                            ),
                        )
                        events.append(_event(event, attempt_number))
            else:
                script = ledger.scripts[case["procedure"]["script_ids"][0]]
                barrier = next(
                    action for action in script["actions"] if action["action"] == "barrier"
                )

                async def advance_to_barrier() -> None:
                    while not ledger._ready_events.get(
                        barrier["readiness"], asyncio.Event()
                    ).is_set():
                        event = await stream.__anext__()
                        if isinstance(event, StreamEnded):
                            nonlocal result
                            result = event.result
                        attempt_number = max(
                            1,
                            sum(
                                1
                                for item in events
                                if item.get("type") == "TimingMark"
                                and item.get("name") == "attempt_start"
                            ),
                        )
                        events.append(_event(event, attempt_number))

                pending = asyncio.create_task(advance_to_barrier())
                await ledger.wait_ready(barrier["readiness"])
                if procedure == "async_stream_cancel":
                    pending.cancel()
                    try:
                        await pending
                    except asyncio.CancelledError as exc:
                        error = exc
                else:
                    # The early-close control uses the public stream's aclose path.
                    # Stop the pending read first so Python can close its async generator.
                    pending.cancel()
                    try:
                        await pending
                    except asyncio.CancelledError:
                        ledger.cleanup.append("reader_cancelled:stream")
                    await stream.aclose()
                ledger.release_barrier(barrier["release"])
                await stream.aclose()
        elif procedure == "sync_generate":
            sync = ai.Client(
                providers,
                registry=registry,
                route=route,
                observers=(telemetry,),
                retain_raw=raw_case_request["retain_raw"],
                manifests=raw_case_request["manifest"],
                manifest_payloads=False,
                use_default_catalog=client_options.get("use_default_catalog", True),
                context_gate=client_options.get("context_gate", True),
            )
            try:
                result = sync.generate(request.messages, **kwargs)
            finally:
                sync.close()
                cleanup.append({"kind": "client_close", "id": "client"})
        else:
            raise ValueError(f"not an async procedure: {procedure}")
    except asyncio.CancelledError as exc:
        error = exc
    except Exception as exc:  # noqa: BLE001 - capture the actual public call outcome
        error = exc
    finally:
        if case["procedure"]["name"] != "sync_generate":
            await client.aclose()
            cleanup.append({"kind": "client_close", "id": "client"})
    ledger.assert_consumed()
    observed_cleanup = []
    for item in ledger.cleanup:
        if item.startswith("barrier:"):
            observed_cleanup.append(
                {"kind": "barrier_finally", "id": item.removeprefix("barrier:")}
            )
        elif item.startswith("server:"):
            observed_cleanup.append({"kind": "server_close", "id": item.removeprefix("server:")})
        elif item.startswith("reader_cancelled:"):
            observed_cleanup.append({"kind": "reader_cancelled", "id": "stream"})
        else:
            observed_cleanup.append({"kind": "adapter_close", "id": item})
    return (
        events,
        result,
        error,
        observed_cleanup + cleanup,
        telemetry.events,
    )
