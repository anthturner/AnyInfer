"""Input-only accounting-v1 observations over actual public Python values and helpers."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import asdict
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from pathlib import Path
from typing import Any

import anyinfer as ai
from anyinfer.capabilities import (
    SpendLedger,
    SpendStore,
    build_context_budget,
    compute_cost,
    estimate_request,
    with_cost,
)
from anyinfer.capabilities.estimate import TokenEstimate
from anyinfer.capabilities.gating import check_context_fit
from anyinfer.capabilities.pricing import compute_operation_cost
from anyinfer.errors import ContextLengthError
from anyinfer.events.telemetry import RequestStarted
from anyinfer.routing.limits import RateLimiter
from anyinfer.types.capabilities import (
    ModelCapabilities,
    Pricing,
    RateLimitHeaders,
    Sourced,
    TokenCalibration,
)
from anyinfer.types.requests import (
    GenerationRequest,
    RateLimits,
    ResolvedTarget,
    Sampling,
    SchemaSpec,
)
from anyinfer.types.results import Usage

_FIXTURE = Path(__file__).parent / "fixtures" / "accounting-v1" / "inputs.json"
_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999)
_REPOSITORY = Path(__file__).resolve().parents[1]
_REVISION = re.compile(r"[0-9a-f]{40}")


def _money(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _usage(data: dict[str, Any]) -> Usage:
    fields = {
        key: value for key, value in data.items() if key not in {"cost_usd", "server_tool_uses"}
    }
    return Usage(
        **fields,
        cost_usd=_money(data.get("cost_usd")),
        server_tool_uses=dict(data.get("server_tool_uses", {})),
    )


def _pricing(data: dict[str, Any]) -> Pricing:
    return Pricing(
        input_per_1m=Decimal(data["input_per_1m"]),
        output_per_1m=Decimal(data["output_per_1m"]),
        cache_read_per_1m=_money(data.get("cache_read_per_1m")),
        cache_write_per_1m=_money(data.get("cache_write_per_1m")),
        currency=data.get("currency", "USD"),
        per_search_unit=_money(data.get("per_search_unit")),
        per_server_tool_use={
            key: Decimal(value) for key, value in data.get("per_server_tool_use", {}).items()
        },
    )


def _capabilities(data: dict[str, Any] | None, provenance: str | None) -> ModelCapabilities | None:
    if data is None or provenance is None:
        return None
    return ModelCapabilities(pricing=Sourced(_pricing(data), provenance))


def _usage_value(value: Usage) -> dict[str, Any]:
    return {
        "input_tokens": value.input_tokens,
        "output_tokens": value.output_tokens,
        "total_tokens": value.total_tokens,
        "cache_read_tokens": value.cache_read_tokens,
        "cache_write_tokens": value.cache_write_tokens,
        "reasoning_tokens": value.reasoning_tokens,
        "search_units": value.search_units,
        "cost_usd": None if value.cost_usd is None else str(value.cost_usd),
        "server_tool_uses": dict(value.server_tool_uses),
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


def _request(
    messages: list[str],
    max_output_tokens: int | None = None,
    schema: dict[str, Any] | None = None,
) -> GenerationRequest:
    return GenerationRequest(
        messages=tuple(ai.user(text) for text in messages),
        sampling=Sampling(max_output_tokens=max_output_tokens),
        schema=None if schema is None else SchemaSpec(schema),
    )


def _estimate_value(value: Any) -> dict[str, Any]:
    return {
        "messages": asdict(value.messages),
        "tools": asdict(value.tools),
        "schema": asdict(value.schema),
        "envelope": asdict(value.envelope),
        "unpriced_parts": value.unpriced_parts,
        "tokens": value.tokens,
        "floor": value.floor,
    }


def _budget_value(value: Any) -> dict[str, Any]:
    estimate = value.estimate
    cost = value.estimated_cost
    return {
        "estimate": _estimate_value(estimate),
        "reserve": value.output_reserve_tokens,
        "headroom": value.headroom_tokens,
        "allowance": value.input_allowance_tokens,
        "remaining": value.remaining_tokens,
        "fits": value.fits,
        "estimated_cost": None
        if cost is None
        else {
            "low": str(cost.low),
            "high": str(cost.high),
            "currency": cost.currency,
        },
    }


class _LiteralEstimator:
    """Fixture-owned implementation of the public estimator protocol, not a calculator."""

    def __init__(self, result: dict[str, int], calls: list[str]) -> None:
        self._result = result
        self._calls = calls

    def estimate(self, text: str) -> TokenEstimate:
        self._calls.append(text)
        return TokenEstimate(self._result["tokens"], self._result["floor"])


def _observe_limiter(data: dict[str, Any]) -> dict[str, Any]:
    now = float(data["clock"])
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    async def observe() -> dict[str, Any]:
        limiter = RateLimiter(
            RateLimits(**data["limits"]),
            dialect=RateLimitHeaders(**data.get("dialect", {})),
            clock=lambda: now,
            sleep=sleep,
        )
        outcomes: list[dict[str, Any]] = []
        for action in data["actions"]:
            operation = action if isinstance(action, str) else action.get("op")
            if operation == "slot":
                async with limiter.slot():
                    outcomes.append({"op": "slot"})
            elif operation == "observe":
                limiter.observe(action["headers"])
                outcomes.append({"op": "observe"})
            elif operation == "observed_wait":
                outcomes.append({"op": "observed_wait", "value": limiter.observed_wait_s()})
            else:
                raise ValueError(f"unsupported limiter action {action!r}")
        return {"sleeps": sleeps, "clock": now, "actions": outcomes}

    return asyncio.run(observe())


def _observe(case: dict[str, Any]) -> dict[str, Any]:
    kind = case["kind"]
    with localcontext(_CONTEXT):
        if kind == "usage":
            return {"normalized": _usage_value(_usage(case["input"]).normalized())}
        if kind == "usage_merge":
            return {"merged": _usage_value(_usage(case["left"]).merge(_usage(case["right"])))}
        if kind == "usage_sum":
            return {"sum": _usage_value(Usage.sum([_usage(part) for part in case["parts"]]))}
        if kind in {"generation_cost", "with_cost", "operation_cost"}:
            usage = _usage(case["usage"])
            capabilities = _capabilities(case["pricing"], case["provenance"])
            if kind == "generation_cost":
                cost = compute_cost(usage, capabilities)
                return {"cost": None if cost is None else str(cost)}
            if kind == "with_cost":
                return {"usage": _usage_value(with_cost(usage, capabilities))}
            cost = compute_operation_cost(usage, capabilities, case["operation"])
            return {"cost": None if cost is None else str(cost)}
        if kind == "budget":
            pricing = case["pricing"]
            capabilities = ModelCapabilities(
                context_window=(
                    None
                    if case.get("context_window") is None
                    else Sourced(case["context_window"], case["window_provenance"])
                ),
                pricing=None
                if pricing is None
                else Sourced(_pricing(pricing), case["pricing_provenance"]),
                max_output_tokens=(
                    None
                    if case.get("model_max_output_tokens") is None
                    else Sourced(case["model_max_output_tokens"], case["window_provenance"])
                ),
            )
            budget = build_context_budget(
                _request(case["messages"], case["max_output_tokens"], case.get("schema")),
                capabilities,
                output_reserve_tokens=case.get("output_reserve_tokens"),
            )
            return _budget_value(budget)
        if kind == "estimate":
            calls: list[str] = []
            estimator = None
            if (literal := case.get("literal_estimator")) is not None:
                estimator = _LiteralEstimator(literal, calls)
            calibration = None
            if (calibration_input := case.get("calibration")) is not None:
                calibration = TokenCalibration(**calibration_input)
            estimate = estimate_request(
                _request(case["messages"], schema=case.get("schema")),
                estimator=estimator,
                calibration=calibration,
            )
            return {"estimate": _estimate_value(estimate), "calls": calls}
        if kind == "budget_gate":
            capabilities = ModelCapabilities(
                context_window=(
                    None
                    if case.get("context_window") is None
                    else Sourced(case["context_window"], case["window_provenance"])
                ),
            )
            try:
                budget = check_context_fit(
                    _request(case["messages"], case.get("max_output_tokens")),
                    capabilities,
                    estimator=(
                        None
                        if case.get("literal_estimator") is None
                        else _LiteralEstimator(case["literal_estimator"], [])
                    ),
                    output_reserve_tokens=case.get("output_reserve_tokens"),
                    provider=case.get("provider"),
                    model=case.get("model"),
                )
            except ContextLengthError as error:
                return {
                    "outcome": "context_length",
                    "error": {
                        "type": type(error).__name__,
                        "provider": error.provider,
                        "phase": error.phase,
                        "retryable": error.retryable,
                    },
                }
            return {"outcome": "accepted", "budget": _budget_value(budget)}
        if kind == "policy":
            policy = ai.SpendPolicy(
                _money(case["max_total_usd"]), _money(case["max_request_usd"]), case["on_unknown"]
            )
            return {
                "active": policy.active,
                "max_total_usd": None
                if policy.max_total_usd is None
                else str(policy.max_total_usd),
                "max_request_usd": None
                if policy.max_request_usd is None
                else str(policy.max_request_usd),
                "on_unknown": policy.on_unknown,
            }
        if kind == "ledger":
            ledger = SpendLedger(case["currency"])
            actions: list[dict[str, Any]] = []
            for action in case["actions"]:
                op = action["op"]
                if op == "reserve":
                    accepted, spent, reserved = ledger.reserve(
                        action["request_id"],
                        Decimal(action["estimate"]),
                        _money(action["ceiling"]),
                    )
                    actions.append(
                        {
                            "op": op,
                            "accepted": accepted,
                            "spent": str(spent),
                            "reserved": str(reserved),
                        }
                    )
                elif op == "record":
                    ledger.on_event(
                        RequestStarted(
                            action["request_id"], (action["target"],), action["metadata"]
                        )
                    )
                    provider, model = action["target"].split(":", 1)
                    ledger.record(
                        ResolvedTarget(provider, model),
                        _usage(action["usage"]),
                        request_id=action["request_id"],
                    )
                    actions.append(
                        {
                            "op": op,
                            "totals": _totals(ledger.totals()),
                            "by_target": {
                                key: _totals(value) for key, value in ledger.by_target().items()
                            },
                            "by_label": {
                                key: _totals(value)
                                for key, value in ledger.by_label("tenant").items()
                            },
                        }
                    )
                elif op == "release":
                    ledger.release(action["request_id"])
                    actions.append({"op": op, "reserved": str(ledger.reserved())})
                elif op == "reset":
                    ledger.reset()
                    actions.append(
                        {
                            "op": op,
                            "totals": _totals(ledger.totals()),
                            "reserved": str(ledger.reserved()),
                        }
                    )
                else:
                    raise ValueError(f"unsupported ledger action {op!r}")
            return {"actions": actions}
        if kind == "store":
            with tempfile.TemporaryDirectory() as directory:
                store = SpendStore(Path(directory) / "spend.json")
                for index in range(case["buckets"]):
                    ledger = SpendLedger(case["currency"])
                    ledger.record(
                        ResolvedTarget("fixture", "model"), Usage(cost_usd=Decimal(case["cost"]))
                    )
                    store.accumulate(ledger, bucket=f"b{index}")
                return {
                    "buckets": list(store.load()),
                    "bytes": store.path.read_bytes().decode("utf-8"),
                }
        if kind == "store_seed":
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "spend.json"
                if case.get("seed_bytes_base64") is not None:
                    path.write_bytes(base64.b64decode(case["seed_bytes_base64"], validate=True))
                store = SpendStore(path)
                before = {key: _totals(value) for key, value in store.load().items()}
                ledger = SpendLedger(case["currency"])
                ledger.record(
                    ResolvedTarget("fixture", "model"), Usage(cost_usd=Decimal(case["cost"]))
                )
                store.accumulate(ledger, bucket=case.get("bucket", "total"))
                return {
                    "before": before,
                    "buckets": {key: _totals(value) for key, value in store.load().items()},
                    "bytes": path.read_bytes().decode("utf-8"),
                }
        if kind == "limiter":
            return _observe_limiter(case)
        if kind == "limiter_actions":
            return _observe_limiter(case)
        if kind.startswith("native_only_"):
            return {"domain": "native-only", "value": case["value"]}
        raise ValueError(f"unsupported accounting case kind {kind!r}")


def _execution_metadata(corpus: bytes) -> dict[str, Any]:
    """Bind an observation to its exact corpus and current development checkout."""
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if revision.returncode != 0:
        raise RuntimeError("git rev-parse HEAD failed; execution provenance cannot be established")
    source_revision = revision.stdout.strip()
    if _REVISION.fullmatch(source_revision) is None:
        raise RuntimeError("git rev-parse HEAD returned an invalid source revision")

    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        raise RuntimeError("git status failed; source dirtiness cannot be established")

    return {
        "runtime": "python",
        "source_revision": source_revision,
        "source_dirty": bool(status.stdout),
        "corpus_sha256": hashlib.sha256(corpus).hexdigest(),
    }


def _error_observation(case: dict[str, Any], error: Exception) -> dict[str, Any]:
    """Project an actual public error without interpreting diagnostic prose."""
    observation: dict[str, Any] = {
        "id": case["id"],
        "kind": case["kind"],
        "status": "error",
        "error_type": type(error).__name__,
        "error_flags": {
            "is_value_error": isinstance(error, ValueError),
            "is_arithmetic_error": isinstance(error, ArithmeticError),
        },
    }
    for error_type, cause in (
        (InvalidOperation, "invalid_operation"),
        (Overflow, "overflow"),
        (DivisionByZero, "division_by_zero"),
    ):
        if isinstance(error, error_type):
            observation["decimal_cause"] = cause
            break
    return observation


def observe(inputs: Path) -> dict[str, Any]:
    corpus = inputs.read_bytes()
    source = json.loads(corpus)
    observations: list[dict[str, Any]] = []
    for case in source["cases"]:
        try:
            observations.append(
                {"id": case["id"], "kind": case["kind"], "status": "ok", "value": _observe(case)}
            )
        except Exception as error:  # Actual structured type, never message matching.
            observations.append(_error_observation(case, error))
    return {
        **_execution_metadata(corpus),
        "profile": "accounting-v1",
        "observations": observations,
    }


def test_accounting_input_profile_uses_actual_public_helpers() -> None:
    """A thin smoke check keeps the fixture executable without creating expected verdicts."""
    result = observe(_FIXTURE)
    assert result["profile"] == "accounting-v1"
    assert [item["id"] for item in result["observations"]] == [
        item["id"] for item in json.loads(_FIXTURE.read_bytes())["cases"]
    ]
    assert any(
        item["kind"] == "generation_cost" and item["status"] == "ok"
        for item in result["observations"]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observe", nargs=2, metavar=("INPUT", "OUTPUT"))
    arguments = parser.parse_args()
    if arguments.observe is None:
        parser.error("--observe INPUT OUTPUT is required")
    source, output = (Path(value) for value in arguments.observe)
    output.write_text(
        json.dumps(observe(source), ensure_ascii=True, separators=(",", ":")), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
