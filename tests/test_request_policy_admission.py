"""Public admission, context, and spend-policy controls over builtin HTTP traffic."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.capabilities import SpendLedger
from anyinfer.credentials import EnvResolver, ResolverChain
from anyinfer.errors import SpendLimitError
from anyinfer.registry import ProviderRegistry
from anyinfer.types.capabilities import ModelCapabilities, Pricing, Sourced


def _response() -> httpx2.Response:
    return httpx2.Response(
        200,
        headers={"content-type": "application/json"},
        json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def _client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
    *,
    capabilities: ModelCapabilities | None = None,
    spend: ai.SpendPolicy | None = None,
    ledger: SpendLedger | None = None,
    context_gate: bool = True,
) -> ai.AsyncClient:
    """Build a configured public OpenAI-compatible client with offline traffic."""
    monkeypatch.setenv("ANYINFER_POLICY_TEST_KEY", "policy-fixture-token")
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    builtin = registry.get("openai-compat")
    if capabilities is not None:
        builtin = replace(builtin, static_capabilities={"m": capabilities})
    registry.register(builtin, replace=True)
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://policy.invalid/v1",
                api_key="env://ANYINFER_POLICY_TEST_KEY",
                transport=httpx2.MockTransport(handler),
            )
        ],
        registry=registry,
        resolver=ResolverChain([EnvResolver()]),
        use_default_catalog=False,
        spend=spend,
        ledger=ledger,
        context_gate=context_gate,
    )


@pytest.mark.asyncio
async def test_unknown_cost_refusal_is_a_direct_public_admission_error_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown/refuse is a direct pre-dispatch admission refusal, not a route attempt."""
    calls = 0

    def handle(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return _response()

    client = _client(
        monkeypatch,
        handle,
        spend=ai.SpendPolicy(max_request_usd=Decimal("0"), on_unknown="refuse"),
    )
    try:
        with pytest.raises(SpendLimitError) as raised:
            await client.generate("unknown", target="openai-compat:m")
    finally:
        await client.aclose()

    assert calls == 0
    error = raised.value
    assert error.phase == "generate"
    assert error.retryable is False
    assert error.provider is None
    assert error.limit_usd is None
    assert error.spent_usd == Decimal("0")
    assert error.estimated_usd is None


@pytest.mark.asyncio
async def test_policy_auto_ledger_and_unknown_allow_preserve_public_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inactive supplied policy still installs its ledger; unknown/allow reserves nothing."""
    calls = 0

    def handle(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        assert request.headers["authorization"] == "Bearer policy-fixture-token"
        return _response()

    client = _client(monkeypatch, handle, spend=ai.SpendPolicy())
    try:
        result = await client.generate("ordinary", target="openai-compat:m")
        totals = client.spend()
    finally:
        await client.aclose()

    assert result.text == "ok"
    assert calls == 1
    assert totals.requests == 1
    assert totals.unknown_requests == 1


@pytest.mark.asyncio
async def test_trusted_context_window_refuses_before_http_but_disabled_gate_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a trusted whole window gates; the public opt-out leaves dispatch intact."""
    calls = 0
    capabilities = ModelCapabilities(context_window=Sourced(128, "catalog"))

    def handle(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return _response()

    prompt = "word " * 400
    gated = _client(monkeypatch, handle, capabilities=capabilities)
    try:
        with pytest.raises(ai.AllTargetsFailedError) as raised:
            await gated.generate(prompt, target="openai-compat:m")
    finally:
        await gated.aclose()

    assert calls == 0
    error = raised.value.attempts[0].error
    assert error is not None
    assert error.type_name == "ContextLengthError"
    assert error.retryable is False
    assert error.phase == "generate"

    ungated = _client(monkeypatch, handle, capabilities=capabilities, context_gate=False)
    try:
        assert (await ungated.generate(prompt, target="openai-compat:m")).text == "ok"
    finally:
        await ungated.aclose()

    assert calls == 1


@pytest.mark.asyncio
async def test_equal_per_request_ceiling_dispatches_and_commits_winning_ledger_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Equality passes admission and completion, not preflight, owns the ledger charge."""
    calls = 0
    capabilities = ModelCapabilities(
        pricing=Sourced(Pricing(Decimal("0"), Decimal("0")), "catalog")
    )
    ledger = SpendLedger()

    def handle(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return _response()

    client = _client(
        monkeypatch,
        handle,
        capabilities=capabilities,
        spend=ai.SpendPolicy(max_request_usd=Decimal("0")),
        ledger=ledger,
    )
    try:
        result = await client.generate("equal", target="openai-compat:m")
    finally:
        await client.aclose()

    assert result.text == "ok"
    assert calls == 1
    assert ledger.totals().requests == 1
    assert ledger.totals().cost == Decimal("0")
