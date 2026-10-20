"""Public retrieval-v1 observer over the frozen literal input corpus.

The module deliberately records SDK facts; it contains no result, route, chunk, or cost
oracle.  The companion checker qualifies the generated envelope independently.
"""

from __future__ import annotations

# ruff: noqa: E402
import argparse
import asyncio
import contextvars
import hashlib
import json
import math
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _csharp_observation import ObservationError, read_json_bytes, source_identity
from _csharp_retrieval_inputs import validate_inputs

import anyinfer as ai
from anyinfer.capabilities import SpendLedger
from anyinfer.capabilities.estimate import TokenEstimate
from anyinfer.errors import (
    AnyInferError,
    ContextLengthError,
    ProviderError,
    ProviderUnavailableError,
)
from anyinfer.providers.base import (
    EmbeddingWireRequest,
    EmbeddingWireResult,
    EmbedsText,
    ReranksText,
    RerankWireRequest,
    RerankWireResult,
    WireRankedItem,
)
from anyinfer.redaction import registry as redaction_registry
from anyinfer.registry import ProviderDescriptor, ProviderRegistry
from anyinfer.types.capabilities import ModelCapabilities, Pricing, Sourced
from anyinfer.types.operations import EmbeddingCapabilities, RerankCapabilities, RerankDocument
from anyinfer.types.results import Usage

FIXTURE = ROOT / "tests" / "fixtures" / "retrieval-v1"
INPUT_SCHEMA = FIXTURE / "schema.json"
INPUTS = FIXTURE / "inputs.json"
PROFILE = "retrieval-v1"
FROZEN_INPUT_SHA256 = "cbf8640aa19920044e652d2a095563c480b8a5e7b18c16a2e471f89eb24a4750"
_OPERATION: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "retrieval_profile_operation", default=None
)
_REVISION = re.compile(r"[0-9a-f]{40}")


class _FixedEstimator:
    def __init__(self, value: Mapping[str, int] | None) -> None:
        self._value = value
        self.calls: list[str] = []

    def estimate(self, text: str) -> TokenEstimate:
        self.calls.append(text)
        if self._value is None:
            return ai.HeuristicTokenEstimator().estimate(text)
        return TokenEstimate(self._value["tokens"], self._value["floor"])


class _Collector:
    """Captures real typed events and rejects uncorrelated request relations."""

    def __init__(self, order: Callable[[], int]) -> None:
        self.order = order
        self.events: list[tuple[int, int | None, Any]] = []
        self.requests: dict[str, int] = {}
        self.faults: list[str] = []

    def on_event(self, event: Any) -> None:
        operation = _OPERATION.get()
        request_id = getattr(event, "request_id", None)
        try:
            if isinstance(event, ai.RequestStarted):
                if operation is None:
                    raise RuntimeError("RequestStarted escaped public operation context")
                self.requests[event.request_id] = operation
            elif request_id is not None and request_id not in self.requests:
                raise RuntimeError("telemetry arrived before RequestStarted")
            self.events.append((self.order(), operation, event))
        except Exception as exc:
            # SDK observer failures are isolated; retain this local fact for validation.
            self.faults.append(f"{type(exc).__name__}: {exc}")


@dataclass
class _Barrier:
    readiness: asyncio.Event
    release: asyncio.Event
    cleanup: asyncio.Event


async def _await_owned(task: asyncio.Task[Any]) -> asyncio.CancelledError | None:
    """Join observer-owned work despite repeated cancellation of this observer."""
    current = asyncio.current_task()
    assert current is not None
    cancel_count = current.cancelling()
    interrupted: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as caught:
            if current.cancelling() > cancel_count:
                interrupted = interrupted or caught
                cancel_count = current.cancelling()
        except BaseException:
            # The caller inspects task.result() after the task has settled.
            pass
    return interrupted


async def _finish_held(
    task: asyncio.Task[Any], ready: asyncio.Task[bool], barrier: _Barrier, entered: bool
) -> None:
    if not ready.done():
        ready.cancel()
    await asyncio.wait({task, ready}, return_when=asyncio.ALL_COMPLETED)
    if entered:
        await barrier.cleanup.wait()


def _task_failure(task: asyncio.Task[Any]) -> BaseException | None:
    try:
        task.result()
    except BaseException as caught:
        return caught
    return None


class _RecordingState:
    """Shared state for literal retrieval-only adapters (never a generation adapter)."""

    def __init__(
        self,
        *,
        instance: str,
        descriptor: str,
        scripts: list[dict[str, Any]],
        wires: list[dict[str, Any]],
        resources: list[dict[str, Any]],
        barriers: dict[str, _Barrier],
        order: Callable[[], int],
    ) -> None:
        self.instance = instance
        self.descriptor = descriptor
        self.scripts = scripts
        self.wires = wires
        self.resources = resources
        self.barriers = barriers
        self.order = order
        self.closed = False

    async def list_models(self) -> tuple[()]:
        return ()

    async def health(self) -> ai.Health:
        return ai.Health(True)

    def _wire(
        self,
        script: dict[str, Any],
        step: dict[str, Any],
        kind: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        wire = {
            "selector_id": script["id"],
            "step_ordinal": step["ordinal"],
            "instance": self.instance,
            "target": _target(self.instance, request["model"]),
            "kind": kind,
            "entered_order": self.order(),
            "terminal_order": None,
            "request": request,
            "outcome": None,
            "response": None,
            "failure": None,
        }
        self.wires.append(wire)
        self.resources.append(
            _resource("call_entered", self.order(), script, self.instance, step["ordinal"])
        )
        return wire

    async def _terminal(
        self,
        script: dict[str, Any],
        step: dict[str, Any],
        wire: dict[str, Any],
        result: EmbeddingWireResult | RerankWireResult | None,
    ) -> EmbeddingWireResult | RerankWireResult:
        if step["action"] == "barrier":
            gate = step["gate"]
            barrier = self.barriers[gate["readiness"]]
            barrier.readiness.set()
            self.resources.append(
                _resource("barrier_reached", self.order(), script, self.instance, step["ordinal"])
            )
            try:
                await barrier.release.wait()
            except asyncio.CancelledError:
                wire.update(
                    terminal_order=self.order(), outcome="cancelled", response=None, failure=None
                )
                raise
            finally:
                barrier.cleanup.set()
                self.resources.append(
                    _resource(
                        "provider_cleanup_entered",
                        self.order(),
                        script,
                        self.instance,
                        step["ordinal"],
                    )
                )
            step = step["continuation"]
        wire["terminal_order"] = self.order()
        if step["action"] == "provider_failure":
            error = _provider_error(step["failure"])
            wire.update(outcome="provider_failure", failure=_error(error), response=None)
            raise error
        if result is None:
            raise RuntimeError("literal response did not construct a public wire DTO")
        wire.update(outcome="response", response=_wire_response(result), failure=None)
        return result


class _Embeds(_RecordingState):
    async def embed(self, request: EmbeddingWireRequest) -> EmbeddingWireResult:
        script, step = self._step("embedding", request.model, {"inputs": list(request.inputs)})
        source = _response_after_barrier(step)
        result = (
            None
            if source is None
            else EmbeddingWireResult(
                tuple(tuple(vector) for vector in source["vectors"]),
                source["model"],
                source["dimensions"],
                source["normalized"],
                _usage_from(source["usage"]),
                source["phases"],
                source["raw"],
            )
        )
        return await self._terminal(
            script,
            step,
            self._wire(script, step, "embedding", _embedding_wire_request(request)),
            result,
        )


class _Reranks(_RecordingState):
    async def rerank(self, request: RerankWireRequest) -> RerankWireResult:
        documents = [{"index": item.index, "text": item.text} for item in request.documents]
        script, step = self._step("rerank", request.model, {"documents": documents})
        source = _response_after_barrier(step)
        result = (
            None
            if source is None
            else RerankWireResult(
                tuple(WireRankedItem(item["index"], item["score"]) for item in source["items"]),
                source["model"],
                _usage_from(source["usage"]),
                source["raw"],
            )
        )
        return await self._terminal(
            script, step, self._wire(script, step, "rerank", _rerank_wire_request(request)), result
        )


class _Neither(_RecordingState):
    pass


class _Both(_Embeds, _Reranks):
    pass


def _adapter_type(protocols: tuple[str, ...]) -> type[_RecordingState]:
    declared = frozenset(protocols)
    if declared == {"embedding"}:
        return _Embeds
    if declared == {"rerank"}:
        return _Reranks
    if declared == {"embedding", "rerank"}:
        return _Both
    if not declared:
        return _Neither
    raise RuntimeError("invalid literal runtime protocol set")


def _step(
    self: _RecordingState, operation: str, model: str, slice_value: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    matches = [
        script
        for script in self.scripts
        if script["operation"] == operation
        and script["instance"] == self.instance
        and script["model"] == model
        and script["slice"] == slice_value
        and script["steps"]
    ]
    if len(matches) != 1:
        raise RuntimeError(f"no unique literal selector for {operation}:{self.instance}:{model}")
    script = matches[0]
    step = script["steps"].pop(0)
    return script, step


async def _aclose(self: _RecordingState) -> None:
    if not self.closed:
        self.closed = True
        self.resources.append(
            _resource("adapter_close_started", self.order(), None, self.instance)
        )
        self.resources.append(
            _resource("adapter_close_completed", self.order(), None, self.instance)
        )


_RecordingState._step = _step  # type: ignore[attr-defined]
_RecordingState.aclose = _aclose  # type: ignore[attr-defined]


def _provider_error(source: Mapping[str, Any]) -> ProviderError:
    kinds: Mapping[str, type[ProviderError]] = {
        "provider": ProviderError,
        "provider_unavailable": ProviderUnavailableError,
        "context_length": ContextLengthError,
    }
    error_type = kinds.get(source["kind"])
    if error_type is None:
        raise RuntimeError("unknown literal provider failure kind")
    return error_type(
        source["detail"],
        provider=source["provider"],
        phase=source["phase"],
        retryable=source["retryable"],
        http_status=source["http_status"],
        retry_after_s=source["retry_after_s"],
        hint=source["hint"],
    )


def _response_after_barrier(step: Mapping[str, Any]) -> Mapping[str, Any] | None:
    terminal = step["continuation"] if step["action"] == "barrier" else step
    return terminal.get("response") if terminal["action"].endswith("_response") else None


def _wire_response(result: EmbeddingWireResult | RerankWireResult) -> dict[str, Any]:
    if isinstance(result, EmbeddingWireResult):
        return {
            "vectors": [list(vector) for vector in result.vectors],
            "model": result.model,
            "dimensions": result.dimensions,
            "normalized": result.normalized,
            "usage": None if result.usage is None else _usage(result.usage),
            "phases": dict(result.phases),
            "raw": result.raw,
        }
    return {
        "items": [{"index": item.index, "score": item.score} for item in result.items],
        "model": result.model,
        "usage": None if result.usage is None else _usage(result.usage),
        "raw": result.raw,
    }


def _usage_from(source: Mapping[str, Any] | None) -> Usage | None:
    if source is None:
        return None
    values = dict(source)
    if values["cost_usd"] is not None:
        values["cost_usd"] = Decimal(values["cost_usd"])
    return Usage(**values)


def _target(instance: str, model: str) -> dict[str, Any]:
    return {"provider_id": instance, "model": model, "via_alias": None}


def _public_target(value: Any) -> dict[str, Any]:
    return {
        "provider_id": value.provider_id,
        "model": value.model,
        "via_alias": value.via_alias,
    }


def _space(value: Any) -> dict[str, Any]:
    return {
        "provider_id": value.provider_id,
        "model": value.model,
        "model_revision": value.model_revision,
        "dimensions": value.dimensions,
        "input_intent_aware": value.input_intent_aware,
        "normalized": value.normalized,
        "compatibility_id": value.compatibility_id,
    }


def _only_barrier(barriers: Mapping[str, _Barrier]) -> _Barrier:
    """Return the one literal cancellation barrier, rejecting ambiguous fixtures."""
    if len(barriers) != 1:
        raise RuntimeError("caller-cancellation case did not reach exactly one barrier")
    return next(iter(barriers.values()))


def _barrier_script(
    scripts: list[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    matches = [
        (script, step)
        for script in scripts
        for step in script["steps"]
        if step["action"] == "barrier"
    ]
    if len(matches) != 1:
        raise RuntimeError("caller-cancellation case did not declare exactly one barrier")
    return matches[0]


def _ledger_snapshot(label: str, ledger: SpendLedger) -> dict[str, Any]:
    totals = ledger.totals()
    return {
        "label": label,
        "reserved": str(ledger.reserved()),
        "totals": {
            "cost": str(totals.cost),
            "currency": totals.currency,
            "requests": totals.requests,
            "unknown_requests": totals.unknown_requests,
            "input_tokens": totals.input_tokens,
            "output_tokens": totals.output_tokens,
            "cache_read_tokens": totals.cache_read_tokens,
        },
    }


def _resource(
    kind: str,
    order: int,
    script: Mapping[str, Any] | None,
    instance: str | None,
    step_ordinal: int | None = None,
) -> dict[str, Any]:
    return {
        "type": kind,
        "order": order,
        "selector_id": None if script is None else script["id"],
        "step_ordinal": step_ordinal,
        "instance": instance,
    }


def _embedding_wire_request(request: EmbeddingWireRequest) -> dict[str, Any]:
    return {
        "model": request.model,
        "inputs": list(request.inputs),
        "input_type": request.input_type,
        "dimensions": request.dimensions,
        "timeout_s": request.timeout_s,
        "max_response_bytes": request.max_response_bytes,
        "extra_options": dict(request.extra_options),
    }


def _rerank_wire_request(request: RerankWireRequest) -> dict[str, Any]:
    return {
        "model": request.model,
        "query": request.query,
        "documents": [{"index": item.index, "text": item.text} for item in request.documents],
        "top_n": request.top_n,
        "timeout_s": request.timeout_s,
        "max_response_bytes": request.max_response_bytes,
        "extra_options": dict(request.extra_options),
    }


def _pricing(source: Mapping[str, Any] | None) -> Pricing | None:
    if source is None:
        return None
    decimal_fields = {
        "input_per_1m",
        "output_per_1m",
        "cache_read_per_1m",
        "cache_write_per_1m",
        "per_search_unit",
    }
    values = {
        key: Decimal(value) if key in decimal_fields and value is not None else value
        for key, value in source.items()
        if key not in {"source", "per_server_tool_use"}
    }
    values["per_server_tool_use"] = {
        name: Decimal(rate) for name, rate in source["per_server_tool_use"].items()
    }
    return Pricing(**values)


def _capabilities(
    descriptor: Mapping[str, Any],
) -> tuple[ModelCapabilities, EmbeddingCapabilities | None, RerankCapabilities | None]:
    source = descriptor["capabilities"]
    pricing = _pricing(source["pricing"])
    capabilities = ModelCapabilities(
        # Descriptors only declare defaults.  A literal override is layered through
        # AsyncClient.capability_overrides below, not mislabeled as descriptor evidence.
        pricing=Sourced(pricing, "default") if pricing is not None else None
    )
    embedding_source = source["embedding"]
    if embedding_source is None:
        embedding = None
    else:
        embedding_values = dict(embedding_source)
        for field in ("dimension_choices", "input_intents"):
            if field in embedding_values:
                embedding_values[field] = tuple(embedding_values[field])
        embedding = EmbeddingCapabilities(**embedding_values)
    rerank = None if source["rerank"] is None else RerankCapabilities(**source["rerank"])
    return capabilities, embedding, rerank


def _capability_overrides(case: Mapping[str, Any]) -> dict[str, ModelCapabilities]:
    overrides: dict[str, ModelCapabilities] = {}
    for descriptor in case["descriptors"]:
        pricing_source = descriptor["capabilities"]["pricing"]
        if pricing_source is not None and pricing_source["source"] == "override":
            pricing = _pricing(pricing_source)
            if pricing is not None:
                overrides[f"{descriptor['instance']}:{descriptor['model']}"] = ModelCapabilities(
                    pricing=Sourced(pricing, "override")
                )
    return overrides


async def _observe_case(case: dict[str, Any], operation_index: int) -> dict[str, Any]:
    scripts = [json.loads(json.dumps(script)) for script in case["scripts"]]
    wires: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []
    factories: list[dict[str, Any]] = []
    barriers: dict[str, _Barrier] = {
        step["gate"]["readiness"]: _Barrier(asyncio.Event(), asyncio.Event(), asyncio.Event())
        for script in scripts
        for step in script["steps"]
        if step["action"] == "barrier"
    }
    order = 0

    def next_order() -> int:
        nonlocal order
        order += 1
        return order

    collector = _Collector(next_order)

    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    adapters: list[_RecordingState] = []
    for source in case["descriptors"]:
        capabilities, embedding, rerank = _capabilities(source)

        def factory(config: Any, source: Mapping[str, Any] = source) -> _RecordingState:
            factories.append(
                {
                    "type": "factory_entered",
                    "order": next_order(),
                    "instance": config.provider_id,
                    "model": source["model"],
                    "declared_operations": list(source["operations"]),
                }
            )
            adapter = _adapter_type(tuple(source["runtime_protocols"]))(
                instance=config.provider_id,
                descriptor=source["id"],
                scripts=scripts,
                wires=wires,
                resources=resources,
                barriers=barriers,
                order=next_order,
            )
            adapters.append(adapter)
            factories.append(
                {
                    "type": "factory_returned",
                    "order": next_order(),
                    "instance": config.provider_id,
                    "model": source["model"],
                    "declared_operations": list(source["operations"]),
                    "runtime_protocols": [
                        name
                        for name, protocol in (
                            ("embedding", EmbedsText),
                            ("rerank", ReranksText),
                        )
                        if isinstance(adapter, protocol)
                    ],
                }
            )
            return adapter

        registry.register(
            ProviderDescriptor(
                id=source["id"],
                display_name=source["id"],
                factory=factory,
                operations=frozenset(source["operations"]),
                static_capabilities={source["model"]: capabilities},
                static_embedding_capabilities={}
                if embedding is None
                else {source["model"]: embedding},
                static_rerank_capabilities={} if rerank is None else {source["model"]: rerank},
            )
        )

    settings = [
        ai.ProviderSettings.of(item["id"], alias=item["instance"]) for item in case["descriptors"]
    ]
    ledger = SpendLedger() if case["ledger"] else None
    estimator = _FixedEstimator(case["client"]["estimator"])
    for secret in case["client"]["registered_secrets"]:
        # Credential-shaped literals are registered before any evidence is projected.
        ai.register_secret(secret)
    spend_source = case["spend_policy"]
    spend = (
        None
        if spend_source is None
        else ai.SpendPolicy(
            **{
                key: Decimal(value) if key.startswith("max_") and value is not None else value
                for key, value in spend_source.items()
            }
        )
    )
    default_route = _route(case["client"]["default_route"])
    operation_routes = (
        {case["kind"]: _route(case["client"]["operation_route"])}
        if case["client"]["operation_route"] is not None
        else {}
    )
    provider_settings: tuple[ai.ProviderSettings, ...] | list[ai.ProviderSettings] = settings
    if case["client"]["source"] == "from_config":
        config = ai.AnyInferConfig(
            providers=tuple(settings), route=default_route, operation_routes=operation_routes
        )
        provider_settings = config.providers
        default_route = config.route
        operation_routes = dict(config.operation_routes)
    client = ai.AsyncClient(
        provider_settings,
        registry=registry,
        observers=[collector],
        use_default_catalog=False,
        estimator=estimator,
        ledger=ledger,
        spend=spend,
        retain_raw=False,
        manifests=True,
        capability_overrides=_capability_overrides(case),
        route=default_route,
        operation_routes=operation_routes,
    )
    request = case["request"]
    token = _OPERATION.set(operation_index)
    result: Any | None = None
    error: BaseException | None = None
    escaped: BaseException | None = None
    ledger_snapshots: list[dict[str, Any]] | None = [] if ledger is not None else None

    def checkpoint(label: str) -> None:
        if ledger is not None and ledger_snapshots is not None:
            ledger_snapshots.append(_ledger_snapshot(label, ledger))

    checkpoint("before_call")
    try:
        if case["kind"] == "embedding":
            inputs: str | list[str] = request.get("input", request.get("inputs"))
            expected_space = request["expected_space"]
            call = client.embed(
                inputs,
                target=case["client"]["per_call_target"],
                route=_route(case["client"]["per_call_route"]),
                input_type=request["input_type"],
                dimensions=request["dimensions"],
                expected_space=(
                    None if expected_space is None else ai.EmbeddingSpace(**expected_space)
                ),
                allow_incompatible_fallback=request["allow_incompatible_fallback"],
                batch=ai.BatchPolicy(**request["batch"]),
                timeout_s=request["timeout_s"],
                metadata=request["metadata"],
                provider_options=request["provider_options"],
                max_response_bytes=request.get("max_response_bytes"),
                retain_raw=request["retain_raw"],
            )
        else:
            documents = [
                RerankDocument(item["id"], item["text"], item["metadata"])
                for item in request["documents"]
            ]
            call = client.rerank(
                request["query"],
                documents,
                target=case["client"]["per_call_target"],
                route=_route(case["client"]["per_call_route"]),
                top_n=request["top_n"],
                batch=ai.BatchPolicy(**request["batch"]),
                timeout_s=request["timeout_s"],
                metadata=request["metadata"],
                provider_options=request["provider_options"],
                max_response_bytes=request.get("max_response_bytes"),
                return_documents=request["return_documents"],
                retain_raw=request["retain_raw"],
            )
        if case["procedure"]["name"] == "caller_cancel_while_provider_held":
            task = asyncio.create_task(call)
            barrier = _only_barrier(barriers)
            barrier_script, barrier_step = _barrier_script(scripts)
            ready = asyncio.create_task(barrier.readiness.wait())
            branch_fault: BaseException | None = None
            requested_cancel = False
            try:
                done, _ = await asyncio.wait({task, ready}, return_when=asyncio.FIRST_COMPLETED)
                if task not in done:
                    checkpoint("while_provider_held")
                    resources.append(
                        _resource(
                            "caller_cancel_requested",
                            next_order(),
                            barrier_script,
                            barrier_script["instance"],
                            barrier_step["ordinal"],
                        )
                    )
                    requested_cancel = task.cancel()
            except BaseException as caught:
                branch_fault = caught
            finally:
                entered = barrier.readiness.is_set()
                barrier.release.set()
                resources.append(
                    _resource(
                        "barrier_released",
                        next_order(),
                        barrier_script,
                        barrier_script["instance"],
                        barrier_step["ordinal"],
                    )
                )
                finalizer = asyncio.create_task(_finish_held(task, ready, barrier, entered))
                interrupted = await _await_owned(finalizer)
                finish_fault = _task_failure(finalizer)
                ready_fault = _task_failure(ready)
                task_fault = _task_failure(task)
                join_fault = finish_fault or (
                    ready_fault if not isinstance(ready_fault, asyncio.CancelledError) else None
                )
                if task_fault is not branch_fault and not (
                    requested_cancel and isinstance(task_fault, asyncio.CancelledError)
                ):
                    join_fault = join_fault or task_fault
                primary = interrupted or branch_fault
                if primary is not None:
                    if (
                        interrupted is not None
                        and branch_fault is not None
                        and join_fault is not None
                    ):
                        branch_fault.__cause__ = join_fault
                    secondary = (
                        (branch_fault or join_fault) if interrupted is not None else join_fault
                    )
                    if secondary is not None and secondary is not primary:
                        raise primary from secondary
                    raise primary
                if join_fault is not None:
                    raise join_fault
                if task_fault is not None:
                    if requested_cancel and isinstance(task_fault, asyncio.CancelledError):
                        error = task_fault
                    else:
                        raise task_fault
                else:
                    result = task.result()
        else:
            result = await call
    except BaseException as caught:
        if isinstance(caught, AnyInferError):
            error = caught
        else:
            escaped = caught
    finally:
        if case["procedure"]["name"] == "caller_cancel_while_provider_held":
            final_script, final_step = _barrier_script(case["scripts"])
            resources.append(
                _resource(
                    "operation_finally",
                    next_order(),
                    final_script,
                    final_script["instance"],
                    final_step["ordinal"],
                )
            )
        _OPERATION.reset(token)
        checkpoint("after_operation")
        resources.append(_resource("normal_client_close_started", next_order(), None, None))
        closed = False
        close_task = asyncio.create_task(client.aclose())
        while not close_task.done():
            try:
                await asyncio.shield(close_task)
            except asyncio.CancelledError as caught:
                # External cancellation must not interrupt observer-owned joining.
                if escaped is None:
                    escaped = caught
            except BaseException as caught:
                if error is None and escaped is None:
                    escaped = caught
        try:
            close_task.result()
            closed = True
        except BaseException as caught:
            if error is None and escaped is None:
                escaped = caught
        if closed:
            resources.append(_resource("normal_client_close_completed", next_order(), None, None))
        checkpoint("after_client_close")
    if collector.faults:
        raise RuntimeError("telemetry correlation failure")
    if any(script["steps"] for script in scripts):
        raise RuntimeError("unconsumed literal retrieval scripts")
    if escaped is not None:
        raise escaped
    return _value(case, result, error, factories, wires, collector, resources, ledger_snapshots)


def _route(source: Mapping[str, Any] | None) -> ai.Route | None:
    if source is None:
        return None
    retry = source["retry"]
    return ai.Route(
        tuple(source["targets"]),
        retry=ai.Retry(
            max_attempts=retry["max_attempts"],
            backoff_base_s=retry["backoff_base_s"],
            backoff_max_s=retry["backoff_max_s"],
        ),
        health_gate=source["health_gate"],
    )


def _value(
    case: Mapping[str, Any],
    result: Any | None,
    error: BaseException | None,
    factories: list[dict[str, Any]],
    wires: list[dict[str, Any]],
    collector: _Collector,
    resources: list[dict[str, Any]],
    ledger: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    if result is not None:
        operation = {
            "kind": case["kind"],
            "outcome": "ok",
            "result": _result(result),
            "error": None,
            "attempts": [_attempt(value) for value in result.attempts],
            "request_relation": "operation",
            "cancellation_relation": "none",
        }
    elif isinstance(error, asyncio.CancelledError):
        operation = {
            "kind": case["kind"],
            "outcome": "cancelled",
            "result": None,
            "error": None,
            "attempts": [],
            "request_relation": "operation",
            "cancellation_relation": "caller_cancelled",
        }
    else:
        operation = {
            "kind": case["kind"],
            "outcome": "error",
            "result": None,
            "error": _error(error),
            "attempts": _attempts_from(error),
            "request_relation": "operation",
            "cancellation_relation": "none",
        }
    value = {
        "operation": operation,
        "factories": factories,
        "wires": wires,
        "telemetry": _telemetry(collector),
        "ledger": ledger,
        "manifest": None if result is None else _manifest(result.manifest, collector),
        "resources": resources,
        "batch_failures": _batch_failures(error),
    }
    return _redact_evidence(value)


def _batch_failures(error: BaseException | None) -> list[dict[str, Any]] | None:
    if type(error).__name__ != "AllTargetsFailedError":
        return None
    return [
        {
            "batch_index": failure.batch_index,
            "item_count": failure.item_count,
            "succeeded": failure.succeeded,
            "error": failure.error,
        }
        for failure in error.batch_failures
    ]


def _telemetry(collector: _Collector) -> list[dict[str, Any]]:
    """Project the closed public retrieval event family in the order observed."""
    values: list[dict[str, Any]] = []
    for order, _, event in collector.events:
        name = type(event).__name__
        value: dict[str, Any] = {
            "type": name,
            "order": order,
            "request_relation": "operation",
        }
        if name == "RequestStarted":
            value.update(
                targets=list(event.targets),
                metadata=dict(event.metadata),
                operation=event.operation,
            )
        elif name == "TargetResolved":
            value["target"] = _public_target(event.target)
        elif name == "AttemptStarted":
            value.update(
                target=_public_target(event.target),
                attempt=event.attempt_number,
            )
        elif name == "AttemptCompleted":
            value.update(
                target=_public_target(event.target),
                usage=_usage(event.usage),
                timing=_timing(event.timing),
                finish_reason=event.finish_reason,
            )
        elif name == "RetryScheduled":
            value.update(
                target=_public_target(event.target),
                attempt=event.attempt_number,
                delay_s=event.delay_s,
                error=_snapshot(event.error),
            )
        elif name == "FallbackTriggered":
            value.update(
                from_target=_public_target(event.from_target),
                to_target=event.to_target,
                error=None if event.error is None else _snapshot(event.error),
            )
        elif name == "RequestCompleted":
            value.update(
                target=_public_target(event.target),
                usage=_usage(event.usage),
                timing=_timing(event.timing),
                repair_attempts=event.repair_attempts,
            )
        elif name == "RequestFailed":
            value["error"] = _snapshot(event.error)
        else:
            continue
        values.append(value)
    return values


def _manifest(value: Any, collector: _Collector) -> dict[str, Any] | None:
    if value is None:
        return None
    if value.request_id not in collector.requests:
        raise RuntimeError("manifest request id was not observed by telemetry")
    return {
        "request_relation": "operation",
        "format": value.format,
        "complete": value.complete,
        "operation": value.operation,
        "route": {
            "requested": list(value.route.requested),
            "resolved": value.route.resolved,
            "considered": [
                {"target": item.target, "outcome": item.outcome, "reason": item.reason}
                for item in value.route.considered
            ],
        },
        "attempts": [
            {
                "target": item.target,
                "attempt_number": item.attempt_number,
                "outcome": item.outcome,
                "error": None if item.error is None else _snapshot(item.error),
                "first_token_ms": item.first_token_ms,
                "total_ms": item.total_ms,
                "queued_ms": item.queued_ms,
                "retry_reason": item.retry_reason,
                "retry_delay_s": item.retry_delay_s,
                "paced_s": dict(item.paced_s),
            }
            for item in value.attempts
        ],
        "usage": {
            "input_tokens": value.usage.input_tokens,
            "output_tokens": value.usage.output_tokens,
            "total_tokens": value.usage.total_tokens,
            "cache_read_tokens": value.usage.cache_read_tokens,
            "cache_write_tokens": value.usage.cache_write_tokens,
            "reasoning_tokens": value.usage.reasoning_tokens,
            "cost_usd": value.usage.cost_usd,
            "estimated_fields": dict(value.usage.estimated_fields),
            "search_units": value.usage.search_units,
        },
        "timing": {
            "first_token_ms": value.timing.first_token_ms,
            "total_ms": value.timing.total_ms,
            "output_tokens_per_s": value.timing.output_tokens_per_s,
            "phases": dict(value.timing.phases),
        },
        "notes": list(value.notes),
        "embedding_space": None
        if value.embedding_space is None
        else _space(value.embedding_space),
        "payloads": None,
    }


def _attempt(value: Any) -> dict[str, Any]:
    return {
        "target": None if value.target is None else _public_target(value.target),
        "outcome": value.outcome,
        "error": None if value.error is None else _snapshot(value.error),
        "timing": None if value.timing is None else _timing(value.timing),
    }


def _attempts_from(error: BaseException | None) -> list[dict[str, Any]]:
    return [_attempt(value) for value in getattr(error, "attempts", ())]


def _snapshot(value: Any) -> dict[str, Any]:
    return {
        "runtime_type": value.type_name,
        "provider": value.provider,
        "phase": value.phase,
        "retryable": value.retryable,
        "http_status": value.http_status,
        "detail": value.detail,
    }


def _error(error: BaseException | None) -> dict[str, Any]:
    if error is None:
        raise RuntimeError("missing terminal error")
    value = {
        "runtime_type": type(error).__name__,
        "message": error.args[0] if error.args else "",
        "provider": getattr(error, "provider", None),
        "phase": getattr(error, "phase", None),
        "retryable": getattr(error, "retryable", False),
        "http_status": getattr(error, "http_status", None),
        "retry_after_s": getattr(error, "retry_after_s", None),
        "detail": getattr(error, "detail", None),
        "hint": getattr(error, "hint", None),
    }
    if type(error).__name__ == "SpendLimitError":
        value.update(
            limit_usd=_money(getattr(error, "limit_usd", None)),
            spent_usd=_money(getattr(error, "spent_usd", None)),
            estimated_usd=_money(getattr(error, "estimated_usd", None)),
        )
    return value


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _timing(value: Any) -> dict[str, Any]:
    return {
        "started_at": value.started_at,
        "first_token_ms": value.first_token_ms,
        "total_ms": value.total_ms,
        "output_tokens_per_s": value.output_tokens_per_s,
        "phases": dict(value.phases),
    }


def _result(result: Any) -> dict[str, Any]:
    usage = _usage(result.usage)
    common = {
        "target": _public_target(result.target),
        "usage": usage,
        "timing": _timing(result.timing),
        "warnings": list(result.warnings),
        "raw": _redact_raw(result.raw),
    }
    if hasattr(result, "vectors"):
        return common | {
            "vectors": [list(value.values) for value in result.vectors],
            "space": {
                "provider_id": result.space.provider_id,
                "model": result.space.model,
                "model_revision": result.space.model_revision,
                "dimensions": result.space.dimensions,
                "input_intent_aware": result.space.input_intent_aware,
                "normalized": result.space.normalized,
                "compatibility_id": result.space.compatibility_id,
            },
        }
    return common | {
        "items": [
            {
                "index": item.index,
                "document_id": item.document_id,
                "score": item.score,
                "text": item.text,
            }
            for item in result.items
        ]
    }


def _redact_raw(value: Any) -> Any:
    """Redact evidence recursively without changing JSON value kinds or collection order."""
    # Reuse the public process registry while preserving non-string raw values
    # mechanically.
    if isinstance(value, str):
        return redaction_registry.redact(value)
    if isinstance(value, list):
        return [_redact_raw(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_raw(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _redact_raw(item) for key, item in value.items()}
    return value


def _redact_evidence(value: Any) -> Any:
    """Apply the public redactor to every evidence string, including mapping keys."""
    if isinstance(value, str):
        return redaction_registry.redact(value)
    if isinstance(value, list):
        return [_redact_evidence(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_evidence(item) for item in value]
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            rendered = redaction_registry.redact(str(key))
            if rendered in output:
                raise ObservationError("redaction collapsed distinct evidence keys")
            output[rendered] = _redact_evidence(item)
        return output
    return value


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
        "server_tool_uses": dict(value.server_tool_uses),
    }


async def _observe(source: Mapping[str, Any]) -> dict[str, Any]:
    schema = read_json_bytes(INPUT_SCHEMA)
    if not isinstance(schema, dict):
        raise ObservationError("retrieval schema must be an object")
    validate_inputs(source, schema)
    records = []
    for index, case in enumerate(source["cases"]):
        records.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "status": "ok",
                "value": await _observe_case(case, index),
            }
        )
    revision, dirty = source_identity()
    envelope = {
        "profile": PROFILE,
        "runtime": "python",
        "source_revision": revision,
        "source_dirty": dirty,
        "corpus_sha256": FROZEN_INPUT_SHA256,
        "observations": records,
    }
    _validate_output(envelope, source)
    return envelope


def _validate_output(envelope: Mapping[str, Any], source: Mapping[str, Any]) -> None:
    """Apply the frozen Draft 2020-12 output contract before the caller writes bytes."""
    _assert_finite(envelope)
    schema = read_json_bytes(FIXTURE / "observations.schema.json")
    if not isinstance(schema, dict):
        raise ObservationError("retrieval observation schema must be an object")
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(envelope), key=str)
    if errors:
        raise ObservationError("retrieval observation violates frozen output schema")
    rendered = json.dumps(envelope, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    for case in source["cases"]:
        for secret in case["client"]["registered_secrets"]:
            if secret in rendered:
                raise ObservationError("retrieval observation contains a registered secret")


def _assert_finite(value: Any) -> None:
    """Reject generated non-finite evidence without coercing JSON scalar kinds."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ObservationError("retrieval observation contains a non-finite number")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_finite(key)
            _assert_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_finite(item)


def observe(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_INPUT_SHA256:
        raise ObservationError("input bytes do not match frozen retrieval-v1 corpus")
    source = read_json_bytes(path)
    if not isinstance(source, dict):
        raise ObservationError("retrieval input must be an object")
    return asyncio.run(_observe(source))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observe", nargs=2, metavar=("INPUT", "OUTPUT"))
    args = parser.parse_args()
    if args.observe is None:
        parser.error("--observe INPUT OUTPUT is required")
    input_path, output_path = (Path(value) for value in args.observe)
    output_path.write_text(
        json.dumps(observe(input_path), ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


# Focused producer controls.  They exercise observer mechanics, never corpus outcomes.
def test_retrieval_parity_config_object_preserves_public_routes() -> None:
    provider = ai.ProviderSettings.of("observer-test", alias="observer-instance")
    route = ai.Route(("observer-instance:model",))
    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id="observer-test",
            display_name="observer-test",
            factory=lambda _: _Neither(
                instance="observer-instance",
                descriptor="observer-test",
                scripts=[],
                wires=[],
                resources=[],
                barriers={},
                order=lambda: 1,
            ),
            operations=frozenset(),
        )
    )
    config = ai.AnyInferConfig(
        providers=(provider,), route=route, operation_routes={"embedding": route}
    )
    client = ai.AsyncClient(
        config.providers,
        route=config.route,
        operation_routes=config.operation_routes,
        registry=registry,
        use_default_catalog=False,
    )
    assert config.providers == (provider,)
    assert config.route == route
    assert config.operation_routes["embedding"] == route
    assert client is not None
    asyncio.run(client.aclose())


def test_retrieval_parity_redacts_nested_raw_without_coercion() -> None:
    secret = "observer-fixture-secret"
    ai.register_secret(secret)
    raw = {"number": 7, "enabled": False, "nested": [secret, None]}
    assert _redact_raw(raw) == {
        "number": 7,
        "enabled": False,
        "nested": ["[redacted]", None],
    }


def test_retrieval_parity_error_info_is_the_six_public_fields() -> None:
    snapshot = _provider_error(
        {
            "kind": "provider",
            "detail": "failure",
            "provider": "observer",
            "phase": "generate",
            "retryable": True,
            "http_status": 503,
            "retry_after_s": 1.5,
            "hint": "retry",
        }
    ).snapshot()
    assert _snapshot(snapshot) == {
        "runtime_type": "ProviderError",
        "provider": "observer",
        "phase": "generate",
        "retryable": True,
        "http_status": 503,
        "detail": "failure",
    }


if __name__ == "__main__":
    main()
