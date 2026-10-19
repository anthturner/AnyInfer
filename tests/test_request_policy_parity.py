"""Public request-policy-v1 observations over the frozen literal corpus.

This observer deliberately has no expected-result table.  It turns only the frozen input
records into public SDK calls, then serializes the public results, telemetry, and transport
captures needed by the frozen output grammar.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import hashlib
import json
import re
import subprocess
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest
from jsonschema import Draft202012Validator

import anyinfer as ai
from anyinfer.capabilities import SpendLedger
from anyinfer.capabilities.estimate import HeuristicTokenEstimator, TokenEstimate
from anyinfer.credentials import LiteralResolver, ResolverChain
from anyinfer.events import telemetry as events
from anyinfer.providers.base import AdapterFinal, WireRequest
from anyinfer.registry import ProviderDescriptor, ProviderRegistry
from anyinfer.types.capabilities import Feature, ModelCapabilities, Pricing, Sourced
from anyinfer.types.messages import Message, Text, ToolCall, ToolResult
from anyinfer.types.results import Usage

_ROOT = Path(__file__).parent / "fixtures" / "request-policy-v1"
_INPUTS = _ROOT / "inputs.json"
_OUTPUT_SCHEMA = _ROOT / "observations.schema.json"
_REPOSITORY = Path(__file__).resolve().parents[1]
_REVISION = re.compile(r"[0-9a-f]{40}")
_FROZEN_INPUT_SHA256 = "92e0fc9f6e128db05719446a91b891e9ee9cacc989d97f392496a8f08e649316"
_OPERATION_INDEX: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "request_policy_operation_index", default=None
)


class _FixedEstimator:
    def __init__(self, source: dict[str, int] | None) -> None:
        self._source = source
        self._default = HeuristicTokenEstimator()
        self.calls: list[str] = []

    def estimate(self, text: str) -> TokenEstimate:
        self.calls.append(text)
        if self._source is None:
            return self._default.estimate(text)
        return TokenEstimate(self._source["tokens"], self._source["floor"])


class _Collector:
    def __init__(self, snapshot: Callable[[Any, int | None], None]) -> None:
        self.items: list[Any] = []
        self._snapshot = snapshot
        self.request_operations: dict[str, int] = {}
        self.attempts: dict[tuple[str, str], int] = {}
        self.operation_started: dict[int, asyncio.Event] = {}

    async def wait_for_operation(self, operation_index: int) -> None:
        event = self.operation_started.setdefault(operation_index, asyncio.Event())
        await asyncio.wait_for(event.wait(), timeout=1)

    def on_event(self, event: Any) -> None:
        operation_index = _OPERATION_INDEX.get()
        request_id = getattr(event, "request_id", None)
        if isinstance(event, events.RequestStarted):
            if operation_index is None:
                raise RuntimeError("RequestStarted escaped its public operation context")
            self.request_operations[event.request_id] = operation_index
            self.operation_started.setdefault(operation_index, asyncio.Event()).set()
        elif request_id is not None and request_id not in self.request_operations:
            raise RuntimeError("telemetry arrived before RequestStarted correlation")
        if isinstance(event, events.AttemptStarted):
            self.attempts[(event.request_id, str(event.target))] = event.attempt_number
        self.items.append(event)
        self._snapshot(event, operation_index)


class _BodyGate(httpx2.AsyncByteStream):
    """A literal body gate whose only controls come from the frozen script."""

    def __init__(self, payload: bytes, name: str, resource: Callable[[str], None]) -> None:
        self._payload = payload
        self.name = name
        self._resource = resource
        self.started = asyncio.Event()
        self.second_read_started = asyncio.Event()
        self.cancel_observed = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.started.set()
        self._resource("body_ready")
        yield self._payload
        self.second_read_started.set()
        self._resource("pending_observed")
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancel_observed.set()
            await self.release.wait()
            raise

    async def aclose(self) -> None:
        self.closed = True
        self._resource("body_closed")


async def _bounded_stream_cleanup(
    active_stream: Any | None,
    pending_read: asyncio.Task[Any] | None,
    close_task: asyncio.Task[None] | None,
    *,
    primary_failure: BaseException | None,
    timeout_s: float = 1,
) -> None:
    """Join stream shutdown without allowing a cleanup failure to replace work failure."""
    cleanup_failure: BaseException | None = None
    for task in (pending_read, close_task):
        if task is None:
            continue
        if not task.done():
            task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout_s)
        except (asyncio.CancelledError, StopAsyncIteration):
            pass
        except BaseException as error:
            if cleanup_failure is None:
                cleanup_failure = error
    if active_stream is not None:
        try:
            await asyncio.wait_for(active_stream.aclose(), timeout=timeout_s)
        except BaseException as error:
            if cleanup_failure is None:
                cleanup_failure = error
    if cleanup_failure is not None and primary_failure is None:
        raise cleanup_failure


class _RecordingAdapter:
    def __init__(
        self,
        scripts: list[dict[str, Any]],
        wires: list[dict[str, Any]],
        operation_index: Callable[[], int],
        instance: str,
        descriptor: str,
        entered: Callable[[], None],
        closed: Callable[[str, str], None],
    ) -> None:
        self._scripts = scripts
        self._wires = wires
        self._operation_index = operation_index
        self._instance = instance
        self._descriptor = descriptor
        self._entered = entered
        self._closed_callback = closed
        self.closed = False

    async def list_models(self) -> tuple[()]:
        return ()

    async def health(self) -> Any:
        return ai.Health(True)

    def generate(self, request: WireRequest) -> AsyncIterator[Any]:
        if not self._scripts:
            raise RuntimeError("recording script underflow")
        script = self._scripts.pop(0)
        self._entered()
        self._wires.append(
            {
                "operation_index": self._operation_index(),
                "script_id": script["id"],
                "instance": self._instance,
                "target": f"{self._instance}:{request.model}",
                "descriptor": self._descriptor,
                "request": request,
            }
        )

        async def run() -> AsyncIterator[Any]:
            for event in script["events"]:
                if event["type"] == "text_delta":
                    yield ai.TextDelta(event["text"])
                elif event["type"] == "tool_call_delta":
                    yield ai.ToolCallDelta(
                        event["index"],
                        event["call_id"],
                        event["name"],
                        event["arguments_fragment"],
                    )
                else:
                    value = event["usage"]
                    yield AdapterFinal(
                        event["finish_reason"],
                        Usage(
                            input_tokens=value["input_tokens"],
                            output_tokens=value["output_tokens"],
                        ),
                    )

        return run()

    async def aclose(self) -> None:
        self.closed = True
        self._closed_callback(self._instance, self._descriptor)


def _messages(source: list[dict[str, Any]]) -> tuple[Message, ...]:
    values: list[Message] = []
    for message in source:
        if "content" in message:
            values.append(Message(message["role"], (Text(message["content"] or ""),)))
            continue
        parts = []
        for part in message["parts"]:
            if part["type"] == "text":
                parts.append(Text(part["text"]))
            elif part["type"] == "tool_call":
                parts.append(ToolCall(part["id"], part["name"], part["arguments"]))
            else:
                parts.append(ToolResult(part["call_id"], part["content"], part["is_error"]))
        values.append(Message(message["role"], tuple(parts)))
    return tuple(values)


def _usage(value: Usage) -> dict[str, Any]:
    return {
        "input_tokens": value.input_tokens,
        "output_tokens": value.output_tokens,
        "total_tokens": value.total_tokens,
        "cache_read_tokens": value.cache_read_tokens,
        "cache_write_tokens": value.cache_write_tokens,
        "reasoning_tokens": value.reasoning_tokens,
        "cost_usd": None if value.cost_usd is None else str(value.cost_usd),
        "search_units": value.search_units,
        "server_tool_uses": dict(getattr(value, "server_tool_uses", {})),
    }


def _manifest_usage(value: Usage) -> dict[str, Any]:
    """Project the public manifest facet, which intentionally omits tool-use counts."""
    return {
        "input_tokens": value.input_tokens,
        "output_tokens": value.output_tokens,
        "total_tokens": value.total_tokens,
        "cache_read_tokens": value.cache_read_tokens,
        "cache_write_tokens": value.cache_write_tokens,
        "reasoning_tokens": value.reasoning_tokens,
        "cost_usd": None if value.cost_usd is None else str(value.cost_usd),
        "search_units": value.search_units,
    }


def _totals(value: Any) -> dict[str, Any]:
    return {
        "cost": str(value.cost),
        "currency": value.currency,
        "requests": value.requests,
        "unknown_requests": value.unknown_requests,
        "input_tokens": value.input_tokens,
        "output_tokens": value.output_tokens,
        "cache_read_tokens": value.cache_read_tokens,
    }


def _error(value: Any) -> dict[str, Any]:
    return {
        "runtime_type": getattr(value, "type_name", type(value).__name__),
        "provider": getattr(value, "provider", None),
        "phase": getattr(value, "phase", None),
        "retryable": bool(getattr(value, "retryable", False)),
        "http_status": getattr(value, "http_status", None),
        "retry_after_s": getattr(value, "retry_after_s", None),
        "limit_usd": None if getattr(value, "limit_usd", None) is None else str(value.limit_usd),
        "spent_usd": None if getattr(value, "spent_usd", None) is None else str(value.spent_usd),
        "estimated_usd": None
        if getattr(value, "estimated_usd", None) is None
        else str(value.estimated_usd),
    }


def _attempt_error(value: Any) -> dict[str, Any]:
    return {
        key: _error(value)[key]
        for key in ("runtime_type", "provider", "phase", "retryable", "http_status")
    }


def _result(value: Any) -> dict[str, Any]:
    manifest = value.manifest
    payload = None
    if manifest is not None and manifest.payloads is not None:
        payload = {
            "tool_arguments": list(manifest.payloads.tool_arguments),
            "repair_texts": list(manifest.payloads.repair_texts),
        }
    return {
        "target": str(value.target),
        "text": value.text,
        "structured": value.structured,
        "finish_reason": value.finish_reason,
        "usage": _usage(value.usage),
        "repair_attempts": value.repair_attempts,
        "warnings": list(value.warnings),
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": dict(call.arguments)}
            for call in value.tool_calls
        ],
        "manifest": None
        if manifest is None
        else {
            "format": manifest.format,
            "complete": manifest.complete,
            "request_id_relation": "same_operation",
            "usage": _manifest_usage(manifest.usage) if manifest.usage else None,
            "payload": payload,
        },
    }


def _wire(value: dict[str, Any]) -> dict[str, Any]:
    request: WireRequest = value["request"]
    return {
        key: value[key]
        for key in (
            "operation_index",
            "script_id",
            "instance",
            "target",
            "descriptor",
        )
    } | {
        "messages": [
            {"role": str(message.role), "content": message.text or None}
            for message in request.messages
        ],
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
            }
            for tool in request.tools
        ],
        "tool_choice": request.tool_choice,
        "cache_marks": list(request.cache_marks),
    }


def _telemetry(collector: _Collector) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in collector.items:
        request_id = getattr(event, "request_id", None)
        index = None if request_id is None else collector.request_operations.get(request_id)
        if request_id is not None and index is None:
            raise RuntimeError("telemetry has no public operation correlation")
        if isinstance(event, events.RequestStarted):
            rows.append(
                {
                    "type": "RequestStarted",
                    "operation_index": index,
                    "targets": [str(t) for t in event.targets],
                }
            )
        elif isinstance(event, events.TargetResolved):
            rows.append(
                {"type": "TargetResolved", "operation_index": index, "target": str(event.target)}
            )
        elif isinstance(event, events.AttemptStarted):
            rows.append(
                {
                    "type": "AttemptStarted",
                    "operation_index": index,
                    "attempt": event.attempt_number,
                    "target": str(event.target),
                }
            )
        elif isinstance(event, events.AttemptCompleted):
            attempt = collector.attempts.get((event.request_id, str(event.target)))
            if attempt is None:
                raise RuntimeError("AttemptCompleted lacks preceding AttemptStarted")
            rows.append(
                {
                    "type": "AttemptCompleted",
                    "operation_index": index,
                    "outcome": "ok",
                }
            )
        elif isinstance(event, events.RequestCompleted):
            rows.append(
                {
                    "type": "RequestCompleted",
                    "operation_index": index,
                    "target": str(event.target),
                    "usage": _usage(event.usage),
                    "repair_attempts": event.repair_attempts,
                }
            )
        elif isinstance(event, events.RequestFailed):
            rows.append(
                {
                    "type": "RequestFailed",
                    "operation_index": index,
                    "error": _attempt_error(event.error),
                }
            )
        elif isinstance(event, events.RetryScheduled):
            rows.append(
                {
                    "type": "RetryScheduled",
                    "operation_index": index,
                    "attempt": event.attempt_number,
                    "error": _attempt_error(event.error),
                }
            )
        elif isinstance(event, events.FallbackTriggered):
            if event.error is None:
                raise RuntimeError("unrepresentable no-error fallback in frozen profile")
            rows.append(
                {
                    "type": "FallbackTriggered",
                    "operation_index": index,
                    "source": str(event.from_target),
                    "destination": str(event.to_target),
                    "error": _attempt_error(event.error),
                }
            )
        elif isinstance(event, events.RepairAttempted):
            if event.mechanism is None:
                raise RuntimeError("repair telemetry has no public mechanism")
            rows.append(
                {
                    "type": "RepairAttempted",
                    "operation_index": index,
                    "count": event.attempt_number,
                    "mechanism": event.mechanism,
                }
            )
        elif isinstance(event, events.CachePlanned):
            rows.append(
                {
                    "type": "CachePlanned",
                    "operation_index": index,
                    "mechanism": event.mechanism,
                    "count": event.mark_count,
                    "estimated_tokens": event.estimated_cacheable_tokens,
                }
            )
        elif isinstance(event, events.ParameterDropped):
            rows.append(
                {
                    "type": "ParameterDropped",
                    "operation_index": index,
                    "parameter": event.parameter,
                    "reason": event.reason,
                }
            )
        elif isinstance(event, events.ProviderDiagnostic):
            rows.append(
                {
                    "type": "ProviderDiagnostic",
                    "operation_index": index,
                    "target": str(event.target) if event.target else None,
                    "code": event.diagnostic.code,
                    "severity": event.diagnostic.severity,
                }
            )
        elif isinstance(event, events.UsageEstimated):
            rows.append(
                {
                    "type": "UsageEstimated",
                    "operation_index": index,
                    "field": event.field_name,
                    "method": event.method,
                }
            )
        elif isinstance(event, events.RateLimitObserved):
            rows.append(
                {
                    "type": "RateLimitObserved",
                    "operation_index": None,
                    "provider": event.provider_id,
                    "remaining": event.requests_remaining,
                    "reset": None if event.resets_in_s is None else str(event.resets_in_s),
                }
            )
    return rows


def _metadata(raw: bytes) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=_REPOSITORY, capture_output=True, text=True, check=False
    )
    revision = result.stdout.strip()
    if result.returncode or _REVISION.fullmatch(revision) is None:
        raise RuntimeError("cannot establish git revision")
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=_REPOSITORY,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode:
        raise RuntimeError("cannot establish git dirtiness")
    return {
        "profile": "request-policy-v1",
        "runtime": "python",
        "source_revision": revision,
        "source_dirty": bool(status.stdout),
        "corpus_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _strict_corpus(raw: bytes) -> dict[str, Any]:
    """Reject non-frozen syntax before any public client is constructed."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raise RuntimeError("frozen corpus must not contain a UTF-8 BOM")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError(f"duplicate JSON key in frozen corpus: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise RuntimeError(f"nonfinite JSON number in frozen corpus: {value}")

    digest = hashlib.sha256(raw).hexdigest()
    if digest != _FROZEN_INPUT_SHA256:
        raise RuntimeError("corpus SHA256 does not match the frozen request-policy input")
    source = json.loads(
        raw,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_nonfinite,
    )
    schema_raw = _OUTPUT_SCHEMA.parent / "schema.json"
    schema = json.loads(schema_raw.read_bytes(), object_pairs_hook=reject_duplicates)
    errors = list(Draft202012Validator(schema).iter_errors(source))
    if errors:
        raise RuntimeError(f"frozen corpus fails input schema: {errors[0].message}")
    return source


def _redact_payload(value: Any) -> Any:
    """Use the public redactor recursively without changing JSON shapes."""
    if isinstance(value, str):
        return ai.redact(value)
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_payload(item) for item in value]
    if isinstance(value, dict):
        return {_redact_payload(key): _redact_payload(item) for key, item in value.items()}
    return value


async def _observe_case(case: dict[str, Any]) -> dict[str, Any]:
    """Execute one frozen stimulus using public clients and public transport seams."""
    procedure = case["procedure"]
    for secret in case.get("client", {}).get("registered_secrets", []):
        ai.register_secret(secret)
    all_scripts = list(case["scripts"])
    scripts = [script for script in all_scripts if script["transport"] == "http"]
    http: list[dict[str, Any]] = []
    wires: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []
    body_gates: dict[str, _BodyGate] = {}
    gate_ready = {
        script["gate"]["name"]: asyncio.Event() for script in all_scripts if "gate" in script
    }
    estimator = _FixedEstimator(case.get("estimator"))
    ledger = SpendLedger()
    checkpoint_values: dict[str, dict[str, Any]] = {}
    armed_checkpoints: set[str] = set()

    def estimator_inputs() -> list[str]:
        return [] if estimator is None else list(estimator.calls)

    def capture_checkpoint(name: str) -> None:
        if name not in case["procedure"].get("checkpoints", []) or name in checkpoint_values:
            return
        checkpoint_values[name] = {
            "name": name,
            "reserved": str(ledger.reserved()),
            "totals": _totals(ledger.totals()),
            "estimator_inputs": estimator_inputs(),
        }

    def arm_checkpoint(name: str) -> None:
        if name in procedure.get("checkpoints", []) and name not in checkpoint_values:
            armed_checkpoints.add(name)

    def capture_armed_checkpoints() -> None:
        """Snapshot admission state only at an actual provider-adapter entry."""
        for name in procedure.get("checkpoints", []):
            if name in armed_checkpoints:
                capture_checkpoint(name)

    estimates_by_request: dict[str, int] = {}

    def capture_event(event: Any, operation_index: int | None) -> None:
        if isinstance(event, events.UsageEstimated):
            count = estimates_by_request.get(event.request_id, 0) + 1
            estimates_by_request[event.request_id] = count
            if count == 1:
                arm_checkpoint("after_initial_reserve")
            elif procedure["name"] == "retry_replacement":
                arm_checkpoint("after_retry_replacement")
        elif isinstance(event, events.FallbackTriggered):
            arm_checkpoint("after_fallback_handoff")
        elif isinstance(event, events.RepairAttempted):
            arm_checkpoint("after_repair")

    collector = _Collector(capture_event)
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    builtin = registry.get("openai-compat")
    adapters: list[Any] = []
    instances = {
        item["id"]: item
        for item in case.get("instances", case.get("config", {}).get("providers", []))
    }

    def handler(instance: str) -> httpx2.MockTransport:
        def send(request: httpx2.Request) -> httpx2.Response:
            operation_index = _OPERATION_INDEX.get()
            if operation_index is None:
                raise RuntimeError("transport escaped its public operation context")
            if not scripts:
                raise RuntimeError("HTTP script underflow")
            script = scripts.pop(0)
            if script["transport"] != "http" or script["instance"] != instance:
                raise RuntimeError("literal script order mismatch")
            capture_armed_checkpoints()
            body = script["body"]
            if body["kind"] == "json":
                payload = json.dumps(body["value"]).encode()
            else:
                payload = "".join(body["chunks"]).encode()
            http.append(
                {
                    "operation_index": operation_index,
                    "script_id": script["id"],
                    "instance": instance,
                    "method": request.method,
                    "path": request.url.path,
                    "query": request.url.query.decode(),
                    "headers": {
                        key.lower(): value
                        for key, value in request.headers.items()
                        if key.lower() != "authorization"
                    },
                    "request_json": json.loads(request.content),
                    "status": script["status"],
                }
            )
            resources.append(
                {
                    "type": "handler_entry",
                    "operation_index": operation_index,
                    "script_id": script["id"],
                    "instance": instance,
                }
            )
            gate = script.get("gate")
            if gate is not None:

                def resource(kind: str) -> None:
                    resources.append(
                        {
                            "type": kind,
                            "operation_index": operation_index,
                            "script_id": script["id"],
                            "instance": instance,
                        }
                    )

                stream = _BodyGate(payload, gate["name"], resource)
                body_gates[gate["name"]] = stream
                gate_ready[gate["name"]].set()
                return httpx2.Response(
                    script["status"],
                    headers={header["name"]: header["value"] for header in script["headers"]},
                    stream=stream,
                )
            return httpx2.Response(
                script["status"],
                headers={header["name"]: header["value"] for header in script["headers"]},
                content=payload,
            )

        return httpx2.MockTransport(send)

    recording_scripts = [script for script in all_scripts if script["transport"] == "recording"]
    recording_descriptor = case.get("descriptor", {"id": "recording", "adapter": "recording"})
    recording_instance_ids: set[str] = set()
    if recording_scripts:

        def recording_operation_index() -> int:
            value = _OPERATION_INDEX.get()
            if value is None:
                raise RuntimeError("recording adapter escaped its public operation context")
            return value

        def recording_factory(config: Any) -> Any:
            if config.provider_id not in recording_instance_ids:
                raise RuntimeError("recording factory lacks a public configured instance mapping")

            def closed(instance: str, _adapter_descriptor: str) -> None:
                resources.append(
                    {
                        "type": "adapter_closed",
                        "operation_index": None,
                        "script_id": None,
                        "instance": instance,
                    }
                )

            adapter = _RecordingAdapter(
                recording_scripts,
                wires,
                recording_operation_index,
                config.provider_id,
                recording_descriptor["id"],
                capture_armed_checkpoints,
                closed,
            )
            adapters.append(adapter)
            return adapter

    descriptor_default = builtin.default_capabilities
    descriptor_static: dict[str, ModelCapabilities] = {}
    caps: dict[str, ModelCapabilities] = {}

    def capability_for(target: str) -> tuple[str, ModelCapabilities]:
        _, _, model = target.partition(":")
        return model, descriptor_static.get(model, ModelCapabilities())

    for item in case.get("capabilities", []):
        model, current = capability_for(item["target"])
        window = item.get("context_window")
        value = None if window is None else Sourced(window, item["provenance"])
        feature_value = Feature(0)
        for feature_name in item.get("features", []):
            feature_value |= Feature[feature_name]
        if item["provenance"] == "default":
            descriptor_default = replace(
                descriptor_default,
                context_window=value,
                features=Sourced(feature_value, item["provenance"])
                if "features" in item
                else descriptor_default.features,
            )
        else:
            descriptor_static[model] = replace(
                current,
                context_window=value,
                features=Sourced(feature_value, item["provenance"])
                if "features" in item
                else current.features,
            )
    for item in case.get("pricing", []):
        model, current = capability_for(item["target"])
        descriptor_static[model] = replace(
            current,
            pricing=Sourced(
                Pricing(Decimal(item["input_per_1m"]), Decimal(item["output_per_1m"])),
                item["provenance"],
            ),
        )

    def factory(config: Any) -> Any:
        if config.transport is None:
            raise RuntimeError("public provider pool did not supply configured transport")
        adapter = builtin.factory(config)
        adapters.append(adapter)
        return adapter

    registry.register(
        replace(
            builtin,
            factory=factory,
            default_capabilities=descriptor_default,
            static_capabilities=descriptor_static,
        ),
        replace=True,
    )
    if recording_scripts:
        registry.register(
            ProviderDescriptor(
                recording_descriptor["id"],
                recording_descriptor["id"],
                recording_factory,
                aliases=(recording_descriptor["adapter"],),
                static_capabilities=descriptor_static,
                cache_mechanism=recording_descriptor.get("cache_mechanism"),
                cache_max_marks=recording_descriptor.get("cache_max_marks", 0),
                cache_min_tokens=recording_descriptor.get("cache_min_tokens", 0),
            ),
            replace=True,
        )
    parsed_config = None
    if "config" in case:
        parsed_config = ai.loads_config(json.dumps(case["config"]), registry=registry)

    def providers_for_client() -> list[Any]:
        """Give each public client its own raw transport for pool governance."""
        if parsed_config is not None:
            providers = [
                replace(provider, transport=handler(provider.alias or provider.provider_id))
                for provider in parsed_config.providers
            ]
        else:
            providers = [
                ai.ProviderSettings.of(
                    instance["adapter"],
                    base_url=instance.get("base_url", "https://policy.invalid/v1"),
                    api_key=instance["api_key"],
                    alias=instance["id"],
                    limits=ai.RateLimits(**instance["limits"]) if "limits" in instance else None,
                    transport=handler(instance["id"]),
                )
                for instance in instances.values()
            ]
        recording_instance_ids.update(
            provider.instance_id
            for provider in providers
            if provider.provider_id == recording_descriptor["adapter"]
        )
        return providers

    policy = case.get("spend_policy")

    def make_client(*, manifest_payloads: bool = False) -> Any:
        return ai.AsyncClient(
            providers_for_client(),
            registry=registry,
            resolver=ResolverChain([LiteralResolver()]),
            observers=[collector],
            use_default_catalog=False,
            estimator=estimator,
            ledger=ledger,
            spend=None
            if policy is None
            else ai.SpendPolicy(
                Decimal(policy["max_total_usd"]) if policy["max_total_usd"] is not None else None,
                Decimal(policy["max_request_usd"])
                if policy["max_request_usd"] is not None
                else None,
                policy["on_unknown"],
            ),
            context_gate=case.get("client", {}).get("context_gate", True),
            cache=None if parsed_config is None else parsed_config.cache,
            capability_overrides=caps,
            manifest_payloads=manifest_payloads,
        )

    capture_modes = procedure.get("capture_modes", [])
    client = make_client(manifest_payloads=bool(capture_modes and capture_modes[0] == "explicit"))
    clients = [client]
    request = case.get("request", case.get("action"))
    messages = _messages(request["messages"])
    kwargs: dict[str, Any] = {
        "schema": request.get("schema"),
        "repair": None if "repair" not in request else ai.Repair(**request["repair"]),
        "tools": tuple(ai.ToolSpec(**tool) for tool in request.get("tools", [])),
        "tool_choice": request.get("tool_choice", "auto"),
        "cache": None if "cache" not in request else ai.CachePolicy(**request["cache"]),
    }
    if "max_output_tokens" in request:
        kwargs["sampling"] = ai.Sampling(max_output_tokens=request["max_output_tokens"])
    if "target" in request:
        kwargs["target"] = request["target"]
    else:
        route = request["route"]
        kwargs["route"] = ai.Route(
            route["targets"],
            ai.Retry(**route["retry"]),
            health_gate=route["health_gate"],
            context_window_targets=route.get("context_window_targets"),
        )
    operations: list[dict[str, Any]] = []
    stream_events: list[dict[str, Any]] = []
    pending_tasks: list[asyncio.Task[Any]] = []

    def request_id_relation(operation_index: int) -> str:
        request_ids = [
            request_id
            for request_id, value in collector.request_operations.items()
            if value == operation_index
        ]
        if not request_ids:
            return "none_observed"
        if len(request_ids) == 1:
            return "all_present_same"
        raise RuntimeError("public operation produced multiple request identities")

    def terminal_event(operation_index: int, *, required: bool = False) -> str:
        """Read the terminal state from captured public telemetry, never from outcome text."""
        terminals = [
            event
            for event in collector.items
            if isinstance(event, events.RequestCompleted | events.RequestFailed)
            and collector.request_operations.get(event.request_id) == operation_index
        ]
        if not terminals:
            if required:
                raise RuntimeError("public operation has no captured terminal telemetry")
            return "none"
        if len(terminals) != 1:
            raise RuntimeError("public operation has multiple terminal telemetry events")
        return "completed" if isinstance(terminals[0], events.RequestCompleted) else "failed"

    def failure_attempts(error: Exception) -> list[dict[str, Any]]:
        if not isinstance(error, ai.AllTargetsFailedError):
            return []
        return [
            {
                "target": str(item.target),
                "outcome": item.outcome,
                "error": None if item.error is None else _attempt_error(item.error),
            }
            for item in error.attempts
        ]

    def project_stream_event(event: Any, operation_index: int) -> None:
        """Retain the admitted public stream facts shared by all stream consumers."""
        if isinstance(event, ai.ToolCallDelta):
            stream_events.append(
                {
                    "type": "tool_call_delta",
                    "operation_index": operation_index,
                    "index": event.index,
                    "id": event.call_id,
                    "name": event.name,
                    "arguments": event.arguments_fragment,
                }
            )
        elif isinstance(event, ai.TimingMark) and event.name in {"first_token", "last_token"}:
            stream_events.append(
                {
                    "type": "timing_mark",
                    "operation_index": operation_index,
                    "name": event.name,
                }
            )

    async def run_one(
        operation_index: int,
        operation_messages: tuple[Message, ...],
        *,
        stream: bool = False,
        override_cache: dict[str, Any] | None = None,
    ) -> None:
        operation_kwargs = dict(kwargs)
        context_token = _OPERATION_INDEX.set(operation_index)
        if override_cache is not None:
            operation_kwargs["cache"] = ai.CachePolicy(**override_cache)
        try:
            capture_checkpoint("before_dispatch")
            if stream:
                active_stream = client.stream(operation_messages, **operation_kwargs)
                async for event in active_stream:
                    project_stream_event(event, operation_index)
                result = active_stream.result
            else:
                result = await client.generate(operation_messages, **operation_kwargs)
            operations.append(
                {
                    "index": operation_index,
                    "entry_point": "stream" if stream else "generate",
                    "outcome": "ok",
                    "result": _result(result),
                    "error": None,
                    "attempts": [
                        {
                            "target": str(item.target),
                            "outcome": item.outcome,
                            "error": None if item.error is None else _attempt_error(item.error),
                        }
                        for item in result.attempts
                    ],
                    "relations": {
                        "request_id_relation": request_id_relation(operation_index),
                        "send_count": sum(
                            item["operation_index"] == operation_index for item in http + wires
                        ),
                        "terminal_event": terminal_event(operation_index, required=True),
                        "cleanup": "released",
                        "cancel_requested": False,
                        "cancelled_before_terminal": False,
                    },
                }
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            operations.append(
                {
                    "index": operation_index,
                    "entry_point": "stream" if stream else "generate",
                    "outcome": "error",
                    "result": None,
                    "error": _error(error),
                    "attempts": failure_attempts(error),
                    "relations": {
                        "request_id_relation": request_id_relation(operation_index),
                        "send_count": sum(
                            item["operation_index"] == operation_index for item in http + wires
                        ),
                        "terminal_event": terminal_event(
                            operation_index,
                            required=isinstance(error, ai.AllTargetsFailedError),
                        ),
                        "cleanup": "released",
                        "cancel_requested": False,
                        "cancelled_before_terminal": False,
                    },
                }
            )
        finally:
            _OPERATION_INDEX.reset(context_token)

    call_messages = [_messages(call["messages"]) for call in request.get("calls", [])]
    if not call_messages:
        repeat = len(procedure.get("capture_modes", [])) or (
            len(all_scripts)
            if procedure["name"]
            in {
                "concurrent_reservation_recovery",
                "stream_early_close",
                "governor_body_gate",
                "config_consumer",
            }
            else 1
        )
        call_messages = [messages] * repeat
    primary_failed = False
    try:
        gated_names = [script["gate"]["name"] for script in all_scripts if "gate" in script]
        if procedure["name"] == "stream_early_close":
            gate_name = gated_names[0]
            stream_script = next(
                script for script in all_scripts if script.get("gate", {}).get("name") == gate_name
            )
            frames = "".join(stream_script["body"]["chunks"])
            payloads = [
                json.loads(line.removeprefix("data: "))
                for line in frames.splitlines()
                if line.startswith("data: ")
            ]
            expected_text = payloads[0]["choices"][0]["delta"]["content"]
            gate: _BodyGate | None = None
            active_stream: Any | None = None
            pending_read: asyncio.Task[Any] | None = None
            close_task: asyncio.Task[None] | None = None
            stream_context_token = _OPERATION_INDEX.set(0)
            stream_primary_failure: BaseException | None = None
            try:
                capture_checkpoint("before_dispatch")
                active_stream = client.stream(call_messages[0], **kwargs)
                iterator = active_stream.__aiter__()
                while True:
                    event = await asyncio.wait_for(anext(iterator), timeout=1)
                    project_stream_event(event, 0)
                    if isinstance(event, ai.TextDelta):
                        if event.text != expected_text:
                            raise RuntimeError("literal SSE first content mismatch")
                        break
                await asyncio.wait_for(gate_ready[gate_name].wait(), timeout=1)
                gate = body_gates[gate_name]
                pending_read = asyncio.create_task(anext(iterator))
                pending_tasks.append(pending_read)
                await asyncio.wait_for(gate.second_read_started.wait(), timeout=1)
                capture_checkpoint("while_stream_open")
                pending_read.cancel()
                resources.append(
                    {
                        "type": "cancel_requested",
                        "operation_index": 0,
                        "script_id": stream_script["id"],
                        "instance": stream_script["instance"],
                    }
                )
                await asyncio.wait_for(gate.cancel_observed.wait(), timeout=1)
                gate.release.set()
                resources.append(
                    {
                        "type": "body_released",
                        "operation_index": 0,
                        "script_id": stream_script["id"],
                        "instance": stream_script["instance"],
                    }
                )
                try:
                    await asyncio.wait_for(pending_read, timeout=1)
                except asyncio.CancelledError:
                    pass
                else:
                    raise RuntimeError("held public stream read did not retain cancellation")
                close_task = asyncio.create_task(active_stream.aclose())
                pending_tasks.append(close_task)
                await asyncio.wait_for(close_task, timeout=1)
                resources.append(
                    {
                        "type": "stream_closed",
                        "operation_index": 0,
                        "script_id": stream_script["id"],
                        "instance": stream_script["instance"],
                    }
                )
                operations.append(
                    {
                        "index": 0,
                        "entry_point": "stream",
                        "outcome": "cancelled",
                        "result": None,
                        "error": None,
                        "attempts": [],
                        "relations": {
                            "request_id_relation": request_id_relation(0),
                            "send_count": sum(item["operation_index"] == 0 for item in http),
                            "terminal_event": "none",
                            "cleanup": "released",
                            "cancel_requested": True,
                            "cancelled_before_terminal": True,
                        },
                    }
                )
                capture_checkpoint("after_close")
            except BaseException as error:
                stream_primary_failure = error
                raise
            finally:
                if gate is not None:
                    gate.release.set()
                try:
                    await _bounded_stream_cleanup(
                        active_stream,
                        pending_read,
                        close_task,
                        primary_failure=stream_primary_failure,
                    )
                finally:
                    _OPERATION_INDEX.reset(stream_context_token)
            for index, call in enumerate(call_messages[1:], start=1):
                await run_one(index, call)
        elif procedure["name"] == "concurrent_reservation_recovery" or (
            procedure["name"] == "governor_body_gate" and "queue" in gated_names
        ):
            first = asyncio.create_task(
                run_one(0, call_messages[0], stream=bool(request.get("stream")))
            )
            pending_tasks.append(first)
            gate_name = gated_names[0]
            await asyncio.wait_for(gate_ready[gate_name].wait(), timeout=1)
            gate = body_gates[gate_name]
            await asyncio.wait_for(gate.started.wait(), timeout=1)
            capture_checkpoint("while_stream_open")
            queued = asyncio.create_task(run_one(1, call_messages[0]))
            pending_tasks.append(queued)
            await collector.wait_for_operation(1)
            if gate_name == "queue":
                resources.append(
                    {
                        "type": "pending_observed",
                        "operation_index": 1,
                        "script_id": None,
                        "instance": None,
                    }
                )
            if procedure["name"] == "governor_body_gate":
                queued.cancel()
                resources.append(
                    {
                        "type": "cancel_requested",
                        "operation_index": 1,
                        "script_id": None,
                        "instance": None,
                    }
                )
                with suppress(asyncio.CancelledError):
                    await asyncio.wait_for(queued, timeout=1)
                operations.append(
                    {
                        "index": 1,
                        "entry_point": "generate",
                        "outcome": "cancelled",
                        "result": None,
                        "error": None,
                        "attempts": [],
                        "relations": {
                            "request_id_relation": request_id_relation(1),
                            "send_count": sum(item["operation_index"] == 1 for item in http),
                            "terminal_event": "none",
                            "cleanup": "released",
                            "cancel_requested": True,
                            "cancelled_before_terminal": True,
                        },
                    }
                )
                capture_checkpoint("after_cancel")
            else:
                await asyncio.wait_for(queued, timeout=1)
                first.cancel()
                resources.append(
                    {
                        "type": "cancel_requested",
                        "operation_index": 0,
                        "script_id": None,
                        "instance": None,
                    }
                )
                await asyncio.wait_for(gate.cancel_observed.wait(), timeout=1)
                gate.release.set()
                gate_script = next(
                    script
                    for script in all_scripts
                    if script.get("gate", {}).get("name") == gate_name
                )
                resources.append(
                    {
                        "type": "body_released",
                        "operation_index": 0,
                        "script_id": gate_script["id"],
                        "instance": gate_script["instance"],
                    }
                )
                try:
                    await asyncio.wait_for(first, timeout=1)
                except asyncio.CancelledError:
                    pass
                else:
                    raise RuntimeError("held public generation did not retain cancellation")
                operations.append(
                    {
                        "index": 0,
                        "entry_point": "generate",
                        "outcome": "cancelled",
                        "result": None,
                        "error": None,
                        "attempts": [],
                        "relations": {
                            "request_id_relation": request_id_relation(0),
                            "send_count": sum(item["operation_index"] == 0 for item in http),
                            "terminal_event": "none",
                            "cleanup": "released",
                            "cancel_requested": True,
                            "cancelled_before_terminal": True,
                        },
                    }
                )
            if procedure["name"] == "governor_body_gate":
                gate.release.set()
                gate_script = next(
                    script
                    for script in all_scripts
                    if script.get("gate", {}).get("name") == gate_name
                )
                resources.append(
                    {
                        "type": "body_released",
                        "operation_index": 0,
                        "script_id": gate_script["id"],
                        "instance": gate_script["instance"],
                    }
                )
                await asyncio.wait_for(first, timeout=1)
            if procedure["name"] == "concurrent_reservation_recovery":
                capture_checkpoint("after_cancel")
            await run_one(2, call_messages[0], override_cache=request.get("caller_cache"))
        elif procedure["name"] == "tool_stream":
            if capture_modes:
                for index, (mode, call) in enumerate(
                    zip(capture_modes, call_messages, strict=True)
                ):
                    if index:
                        client = make_client(manifest_payloads=mode == "explicit")
                        clients.append(client)
                    await run_one(index, call, stream=True)
            else:
                for index, call in enumerate(call_messages):
                    await run_one(index, call, stream=True)
        elif gated_names:
            first = asyncio.create_task(
                run_one(0, call_messages[0], stream=bool(request.get("stream")))
            )
            pending_tasks.append(first)
            gate_name = gated_names[0]
            await asyncio.wait_for(gate_ready[gate_name].wait(), timeout=1)
            gate = body_gates[gate_name]
            await asyncio.wait_for(gate.started.wait(), timeout=1)
            capture_checkpoint("while_stream_open")
            concurrent_second = procedure["name"] in {"governor_body_gate", "config_consumer"}
            second: asyncio.Task[None] | None = None
            if concurrent_second:
                second = asyncio.create_task(
                    run_one(1, call_messages[1], override_cache=request.get("caller_cache"))
                )
                pending_tasks.append(second)
                await collector.wait_for_operation(1)
                if any(item["operation_index"] == 1 for item in http + wires):
                    raise RuntimeError(
                        "second public operation sent before the held body released"
                    )
            gate.release.set()
            script = next(
                item for item in all_scripts if item.get("gate", {}).get("name") == gate_name
            )
            resources.append(
                {
                    "type": "body_released",
                    "operation_index": 0,
                    "script_id": script["id"],
                    "instance": script["instance"],
                }
            )
            await asyncio.wait_for(first, timeout=1)
            if second is not None:
                await asyncio.wait_for(second, timeout=1)
            remaining = call_messages[2:] if concurrent_second else call_messages[1:]
            start = 2 if concurrent_second else 1
            for index, call in enumerate(remaining, start=start):
                await run_one(index, call, override_cache=request.get("caller_cache"))
        else:
            for index, call in enumerate(call_messages):
                await run_one(
                    index,
                    call,
                    stream=bool(request.get("stream")) and index == 0,
                    override_cache=request.get("caller_cache") if index else None,
                )
    except BaseException:
        primary_failed = True
        raise
    finally:
        for gate in body_gates.values():
            gate.release.set()
        cleanup_failure: BaseException | None = None
        for task in pending_tasks:
            if not task.done():
                task.cancel()
        for task in pending_tasks:
            try:
                await asyncio.wait_for(task, timeout=1)
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            except BaseException as error:
                if cleanup_failure is None:
                    cleanup_failure = error
        for active_client in reversed(clients):
            try:
                await asyncio.wait_for(active_client.aclose(), timeout=1)
                resources.append(
                    {
                        "type": "client_closed",
                        "operation_index": None,
                        "script_id": None,
                        "instance": None,
                    }
                )
            except BaseException as error:
                if cleanup_failure is None:
                    cleanup_failure = error
        try:
            capture_checkpoint("after_close")
            capture_checkpoint("after_terminal_cleanup")
        except BaseException as error:
            if cleanup_failure is None:
                cleanup_failure = error
        if cleanup_failure is not None and not primary_failed:
            raise cleanup_failure
    if scripts or recording_scripts:
        raise RuntimeError(
            "unconsumed literal scripts: "
            f"{[script['id'] for script in scripts + recording_scripts]}"
        )
    required_checkpoints = procedure.get("checkpoints", [])
    missing_checkpoints = [name for name in required_checkpoints if name not in checkpoint_values]
    if missing_checkpoints:
        raise RuntimeError(f"missing public checkpoint(s): {', '.join(missing_checkpoints)}")
    checkpoints = [checkpoint_values[name] for name in required_checkpoints]
    return _redact_payload(
        {
            "id": case["id"],
            "kind": case["kind"],
            "status": "ok",
            "value": {
                "operations": sorted(operations, key=lambda operation: operation["index"]),
                "ledger": {"totals": _totals(ledger.totals()), "reserved": str(ledger.reserved())}
                if case.get("spend_policy")
                else None,
                "checkpoints": checkpoints,
                "telemetry": _telemetry(collector),
                "http": http,
                "adapter_wires": [_wire(wire) for wire in wires],
                "stream_events": stream_events,
                "resources": resources,
                "configuration": None
                if parsed_config is None
                else {
                    "provider_ids": [
                        provider.alias or provider.provider_id
                        for provider in parsed_config.providers
                    ],
                    "default_route": []
                    if parsed_config.route is None
                    else [str(target) for target in parsed_config.route.targets],
                    "cache_mode": None
                    if parsed_config.cache is None
                    else parsed_config.cache.mode,
                },
            },
        }
    )


async def observe_async(inputs: Path) -> dict[str, Any]:
    raw = inputs.read_bytes()
    metadata = _metadata(raw)
    source = _strict_corpus(raw)
    observations = []
    for case in source["cases"]:
        observations.append(await _observe_case(case))
    return {**metadata, "observations": observations}


def observe(inputs: Path) -> dict[str, Any]:
    return asyncio.run(observe_async(inputs))


def test_request_policy_observer_uses_frozen_public_corpus() -> None:
    result = observe(_INPUTS)
    schema = json.loads(_OUTPUT_SCHEMA.read_bytes())
    assert not list(Draft202012Validator(schema).iter_errors(result))
    assert len(result["observations"]) == 29


@pytest.fixture(scope="module")
def observed_policy() -> dict[str, Any]:
    """Run the frozen public corpus once for capture-origin regressions."""
    return observe(_INPUTS)


def _observed_case(observed: dict[str, Any], identifier: str) -> dict[str, Any]:
    return next(item for item in observed["observations"] if item["id"] == identifier)


def test_observer_correlates_real_attempts_and_captures_checkpoints_at_barriers(
    observed_policy: dict[str, Any],
) -> None:
    """A retry's public telemetry and ledger boundaries stay operation-correlated."""
    value = _observed_case(observed_policy, "admission-tight-retry-replacement")["value"]
    checkpoints = {item["name"]: item for item in value["checkpoints"]}
    assert [item["name"] for item in value["checkpoints"]] == [
        "before_dispatch",
        "after_initial_reserve",
        "after_retry_replacement",
        "after_terminal_cleanup",
    ]
    assert checkpoints["before_dispatch"]["estimator_inputs"] == []
    assert checkpoints["before_dispatch"]["reserved"] == "0"
    assert checkpoints["after_initial_reserve"]["estimator_inputs"]
    assert len(checkpoints["after_retry_replacement"]["estimator_inputs"]) > len(
        checkpoints["after_initial_reserve"]["estimator_inputs"]
    )

    telemetry = value["telemetry"]
    assert [item["attempt"] for item in telemetry if item["type"] == "AttemptStarted"] == [1, 2]
    completed = [item for item in telemetry if item["type"] == "AttemptCompleted"]
    assert completed == [{"type": "AttemptCompleted", "operation_index": 0, "outcome": "ok"}]
    assert all(item["operation_index"] == 0 for item in telemetry)

    failed = _observed_case(observed_policy, "governor-non-success-header-release")["value"]
    failed_operation = failed["operations"][0]
    assert failed_operation["relations"]["terminal_event"] == "failed"
    assert failed_operation["attempts"]

    refused = _observed_case(observed_policy, "admission-unknown-zero-refuse")["value"]
    refused_operation = refused["operations"][0]
    assert refused_operation["relations"]["terminal_event"] == "none"
    assert refused_operation["attempts"] == []


def test_observer_forwards_literal_zero_output_limit_only_for_sending_context_cases(
    observed_policy: dict[str, Any],
) -> None:
    """Public configured builtins retain an explicit zero through to their wire request."""
    refusal = _observed_case(observed_policy, "context-trusted-preflight-refusal")["value"]
    assert refusal["http"] == []

    for identifier in (
        "context-default-over-floor-allows",
        "context-trusted-equality-allows",
        "context-unknown-allows",
        "context-opt-out-dispatches",
    ):
        http = _observed_case(observed_policy, identifier)["value"]["http"]
        assert len(http) == 1
        assert http[0]["request_json"]["max_tokens"] == 0


def test_observer_uses_three_real_operations_for_cancel_then_recovery(
    observed_policy: dict[str, Any],
) -> None:
    """The refused or cancelled middle public operation has no transport send."""
    for identifier, middle_outcome in (
        ("admission-concurrent-total-cancel-recover", "error"),
        ("governor-cancel-then-reuse", "cancelled"),
    ):
        value = _observed_case(observed_policy, identifier)["value"]
        operations = value["operations"]
        assert [item["index"] for item in operations] == [0, 1, 2]
        assert operations[1]["outcome"] == middle_outcome
        assert operations[1]["relations"]["send_count"] == 0
        assert operations[1]["relations"]["request_id_relation"] == "all_present_same"
        assert operations[2]["outcome"] == "ok"
        assert operations[2]["relations"]["send_count"] == 1
        body_release = next(item for item in value["resources"] if item["type"] == "body_released")
        held_entry = next(
            item
            for item in value["resources"]
            if item["type"] == "handler_entry" and item["operation_index"] == 0
        )
        assert body_release["instance"] == held_entry["instance"]


def test_observer_redacts_registered_secret_without_changing_capture_shape(
    observed_policy: dict[str, Any],
) -> None:
    """Raw HTTP and returned tool arguments use the public redactor's output."""
    observation = _observed_case(observed_policy, "tool-default-explicit-capture-secret-redaction")
    encoded = json.dumps(observation, ensure_ascii=True)
    assert "SYNTHETIC-POLICY-SECRET" not in encoded
    assert encoded.count("[redacted]") >= 4
    assert [item["script_id"] for item in observation["value"]["http"]] == [
        "default",
        "explicit",
    ]
    assert [
        item["result"]["tool_calls"][0]["arguments"]["secret"]
        for item in observation["value"]["operations"]
    ] == ["[redacted]", "[redacted]"]
    assert [
        item["result"]["manifest"]["payload"] for item in observation["value"]["operations"]
    ] == [None, {"tool_arguments": ['{"secret": "[redacted]"}'], "repair_texts": []}]


def test_observer_releases_the_held_body_before_the_recovery_send(
    observed_policy: dict[str, Any],
) -> None:
    """Ordinary body gates use two public calls and release before the second send."""
    for identifier, first_outcome in (
        ("governor-body-cleanup-before-later-send", "ok"),
        ("governor-non-success-header-release", "error"),
    ):
        value = _observed_case(observed_policy, identifier)["value"]
        assert [(item["index"], item["outcome"]) for item in value["operations"]] == [
            (0, first_outcome),
            (1, "ok"),
        ]
        resources = value["resources"]
        first_closed = next(
            index
            for index, item in enumerate(resources)
            if item["type"] == "body_closed" and item["operation_index"] == 0
        )
        recovery_entered = next(
            index
            for index, item in enumerate(resources)
            if item["type"] == "handler_entry" and item["operation_index"] == 1
        )
        assert first_closed < recovery_entered


def test_observer_reserves_the_third_operation_for_the_literal_queue_gate(
    observed_policy: dict[str, Any],
) -> None:
    """Only the queue-owned procedure creates unsent cancellation plus recovery."""
    operations = _observed_case(observed_policy, "governor-cancel-then-reuse")["value"][
        "operations"
    ]
    assert [
        (item["index"], item["outcome"], item["relations"]["send_count"]) for item in operations
    ] == [
        (0, "ok", 1),
        (1, "cancelled", 0),
        (2, "ok", 1),
    ]
    resources = _observed_case(observed_policy, "governor-cancel-then-reuse")["value"]["resources"]
    pending = next(
        index
        for index, item in enumerate(resources)
        if item["type"] == "pending_observed" and item["operation_index"] == 1
    )
    cancelled = next(
        index
        for index, item in enumerate(resources)
        if item["type"] == "cancel_requested" and item["operation_index"] == 1
    )
    released = next(
        index for index, item in enumerate(resources) if item["type"] == "body_released"
    )
    assert pending < cancelled < released


def test_observer_releases_cancelled_held_bodies_before_close_and_recovery(
    observed_policy: dict[str, Any],
) -> None:
    """A held public body observes cancellation but cannot close or free its permit early."""
    for identifier, recovery_index in (
        ("admission-concurrent-total-cancel-recover", 2),
        ("admission-early-stream-close-release", 1),
    ):
        resources = _observed_case(observed_policy, identifier)["value"]["resources"]
        cancel = next(
            index
            for index, item in enumerate(resources)
            if item["type"] == "cancel_requested" and item["operation_index"] == 0
        )
        release = next(
            index
            for index, item in enumerate(resources)
            if item["type"] == "body_released" and item["operation_index"] == 0
        )
        closed = next(
            index
            for index, item in enumerate(resources)
            if item["type"] == "body_closed" and item["operation_index"] == 0
        )
        recovery = next(
            index
            for index, item in enumerate(resources)
            if item["type"] == "handler_entry" and item["operation_index"] == recovery_index
        )
        assert cancel < release < closed < recovery


def test_observer_retains_early_stream_first_token_before_cancellation(
    observed_policy: dict[str, Any],
) -> None:
    """The manual early-close consumer projects admitted timing before it cancels the read."""
    value = _observed_case(observed_policy, "admission-early-stream-close-release")["value"]
    assert {
        "type": "timing_mark",
        "operation_index": 0,
        "name": "first_token",
    } in value["stream_events"]


def test_observer_applies_literal_recording_cache_setup(
    observed_policy: dict[str, Any],
) -> None:
    """Descriptor mechanism and model features produce public cache evidence."""
    explicit = _observed_case(observed_policy, "cache-explicit-marks")["value"]
    assert explicit["adapter_wires"][0]["instance"] == "cache"
    assert explicit["adapter_wires"][0]["cache_marks"]
    assert [item["type"] for item in explicit["telemetry"] if item["type"] == "CachePlanned"] == [
        "CachePlanned"
    ]

    refusal = _observed_case(observed_policy, "cache-explicit-refusal")["value"]
    assert refusal["adapter_wires"][0]["cache_marks"] == []
    assert [
        (item["type"], item["operation_index"])
        for item in refusal["telemetry"]
        if item["type"] in {"ParameterDropped", "CachePlanned"}
    ] == [("ParameterDropped", 0)]

    implicit = _observed_case(observed_policy, "cache-implicit-degradation-prefix-change")["value"]
    assert [item["cache_marks"] for item in implicit["adapter_wires"]] == [[], [], []]
    cache_events = [
        (item["type"], item["operation_index"])
        for item in implicit["telemetry"]
        if item["type"] in {"ParameterDropped", "CachePlanned", "ProviderDiagnostic"}
    ]
    assert cache_events == [
        ("ParameterDropped", 0),
        ("CachePlanned", 0),
        ("ParameterDropped", 1),
        ("CachePlanned", 1),
        ("ProviderDiagnostic", None),
        ("ParameterDropped", 2),
        ("CachePlanned", 2),
    ]

    config = _observed_case(observed_policy, "config-auto-cache-caller-off")["value"]
    assert [item["cache_marks"] for item in config["adapter_wires"]] == [[], []]
    assert [
        (item["type"], item["operation_index"])
        for item in config["telemetry"]
        if item["type"] in {"ParameterDropped", "CachePlanned"}
    ] == [("ParameterDropped", 0)]


def test_blocked_stream_close_does_not_replace_an_active_failure() -> None:
    """The bounded close seam preserves work failure even when cleanup never completes."""

    class BlockingStream:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def aclose(self) -> None:
            self.started.set()
            await self.release.wait()

    async def run() -> None:
        stream = BlockingStream()
        primary = RuntimeError("primary operation failure")
        await _bounded_stream_cleanup(
            stream,
            None,
            None,
            primary_failure=primary,
            timeout_s=0.01,
        )
        assert stream.started.is_set()
        raise primary

    with pytest.raises(RuntimeError, match="primary operation failure"):
        asyncio.run(run())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observe", nargs=2, metavar=("INPUT", "OUTPUT"))
    args = parser.parse_args()
    if args.observe is None:
        parser.error("--observe INPUT OUTPUT is required")
    source, output = (Path(value) for value in args.observe)
    output.write_text(
        json.dumps(observe(source), ensure_ascii=True, separators=(",", ":")), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
