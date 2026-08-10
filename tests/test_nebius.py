"""The Nebius adapter: the verbose model listing and what it discovers."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx2

import anyinfer as ai
from anyinfer.providers.base import ProviderConfig, WireRequest
from anyinfer.providers.nebius import NebiusAdapter
from anyinfer.testing.conformance import Capabilities, ConformanceHarness, run_conformance
from anyinfer.testing.fakes import sse_lines

VERBOSE_LISTING = {
    "data": [
        {
            "id": "deepseek-ai/DeepSeek-V3",
            "object": "model",
            "context_length": 163840,
            "quantization": "fp8",
            "supported_features": ["streaming", "tools", "structured_output"],
            # Per *single* token, as decimal strings.
            "pricing": {"prompt": "0.0000005", "completion": "0.0000015"},
        },
        {
            "id": "deepseek-ai/DeepSeek-V3-fast",
            "object": "model",
            "context_length": 163840,
            "supported_features": ["streaming", "tools", "reasoning"],
            "pricing": {"prompt": "0.000002", "completion": "0.000006"},
        },
    ]
}


def _adapter(handler: Any) -> NebiusAdapter:
    return NebiusAdapter(
        ProviderConfig(
            provider_id="nebius",
            api_key="nebius-key",
            base_url="https://api.tokenfactory.nebius.com/v1",
            transport=httpx2.MockTransport(handler),
        )
    )


async def test_the_listing_is_requested_verbosely() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=VERBOSE_LISTING)

    adapter = _adapter(handler)
    try:
        await adapter.list_models()
    finally:
        await adapter.aclose()

    assert seen[0].url.params["verbose"] == "true"


async def test_per_token_prices_scale_to_per_million() -> None:
    """Listing prices are per single token; capabilities are per million."""
    adapter = _adapter(lambda r: httpx2.Response(200, json=VERBOSE_LISTING))
    try:
        models = await adapter.list_models()
    finally:
        await adapter.aclose()

    caps = models[0].capabilities
    assert caps is not None and caps.pricing is not None
    assert caps.pricing.value.input_per_1m == Decimal("0.5")
    assert caps.pricing.value.output_per_1m == Decimal("1.5")
    assert caps.pricing.provenance == "discovered"


async def test_the_fast_flavor_is_priced_separately() -> None:
    """`-fast` is a distinct id with its own rate, not a modifier on the base model."""
    adapter = _adapter(lambda r: httpx2.Response(200, json=VERBOSE_LISTING))
    try:
        models = await adapter.list_models()
    finally:
        await adapter.aclose()

    by_id = {m.id: m for m in models}
    base = by_id["deepseek-ai/DeepSeek-V3"].capabilities
    fast = by_id["deepseek-ai/DeepSeek-V3-fast"].capabilities
    assert base is not None and fast is not None
    assert base.pricing is not None and fast.pricing is not None
    assert fast.pricing.value.input_per_1m > base.pricing.value.input_per_1m


async def test_context_and_quantization_are_discovered() -> None:
    adapter = _adapter(lambda r: httpx2.Response(200, json=VERBOSE_LISTING))
    try:
        models = await adapter.list_models()
    finally:
        await adapter.aclose()

    caps = models[0].capabilities
    assert caps is not None
    assert caps.context_window is not None
    assert caps.context_window.value == 163840
    assert caps.context_window.provenance == "discovered"
    assert caps.local is not None and caps.local.quantization == "fp8"


async def test_features_follow_the_listing() -> None:
    """An enumeration that omits a feature is meaningful, so absence means unsupported."""
    adapter = _adapter(lambda r: httpx2.Response(200, json=VERBOSE_LISTING))
    try:
        models = await adapter.list_models()
    finally:
        await adapter.aclose()

    base = models[0].capabilities
    fast = models[1].capabilities
    assert base is not None and fast is not None
    assert base.features.value & ai.Feature.JSON_SCHEMA
    assert not base.features.value & ai.Feature.REASONING
    assert fast.features.value & ai.Feature.REASONING


async def test_an_unpriced_entry_stays_unpriced() -> None:
    """Cost stays honestly unknown rather than becoming a misleading zero."""
    listing = {"data": [{"id": "some/model", "context_length": 8192}]}
    adapter = _adapter(lambda r: httpx2.Response(200, json=listing))
    try:
        models = await adapter.list_models()
    finally:
        await adapter.aclose()

    caps = models[0].capabilities
    assert caps is not None
    assert caps.pricing is None


async def test_a_deployment_without_the_verbose_form_degrades() -> None:
    """Ids alone beat failing outright when the query parameter is not supported."""
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        verbose = request.url.params.get("verbose")
        calls.append(str(verbose))
        if verbose == "true":
            return httpx2.Response(400, json={"error": {"message": "unknown parameter"}})
        return httpx2.Response(200, json={"data": [{"id": "plain/model"}]})

    adapter = _adapter(handler)
    try:
        models = await adapter.list_models()
    finally:
        await adapter.aclose()

    assert [m.id for m in models] == ["plain/model"]
    assert calls == ["true", "None"], "the verbose attempt comes first"


async def test_a_real_error_still_raises() -> None:
    """Degrading on 400 must not swallow an auth failure."""
    adapter = _adapter(lambda r: httpx2.Response(401, json={"error": {"message": "bad key"}}))
    try:
        raised = False
        try:
            await adapter.list_models()
        except ai.AuthError:
            raised = True
    finally:
        await adapter.aclose()

    assert raised, "401 is a real failure, not a missing feature"


async def test_generation_uses_the_shared_dialect() -> None:
    body = {
        "choices": [
            {"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}
        ]
    }
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "nebius",
                api_key="k",
                transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json=body)),
            )
        ]
    )
    async with client:
        result = await client.generate("hi", target="nebius:deepseek-ai/DeepSeek-V3")

    assert result.text == "hello"


async def test_streamed_reasoning_is_separate_from_answer_text() -> None:
    chunks = [
        {
            "choices": [
                {
                    "delta": {"reasoning_content": "Checking..."},
                    "finish_reason": None,
                }
            ]
        },
        {"choices": [{"delta": {"content": "42"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    response = httpx2.Response(
        200,
        content=sse_lines(chunks),
        headers={"content-type": "text/event-stream"},
    )
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "nebius",
                api_key="k",
                transport=httpx2.MockTransport(lambda request: response),
            )
        ]
    )
    async with client:
        stream = client.stream("hi", target="nebius:deepseek-ai/DeepSeek-V3")
        events = [event async for event in stream]

    reasoning = [event.text for event in events if isinstance(event, ai.ReasoningDelta)]
    assert reasoning == ["Checking..."]
    assert stream.result.text == "42"


async def test_buffered_reasoning_alias_is_surfaced_once() -> None:
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "42",
                    "reasoning": "Checking...",
                },
                "finish_reason": "stop",
            }
        ]
    }
    adapter = _adapter(lambda request: httpx2.Response(200, json=body))
    try:
        events = [
            event
            async for event in adapter.generate(
                WireRequest(
                    model="deepseek-ai/DeepSeek-V3",
                    messages=(ai.user("hi"),),
                    stream=False,
                )
            )
        ]
    finally:
        await adapter.aclose()

    reasoning = [event.text for event in events if isinstance(event, ai.ReasoningDelta)]
    assert reasoning == ["Checking..."]


def test_reasoning_effort_passes_through() -> None:
    translate = ai.default_registry.get("nebius").reasoning_translator
    assert translate("high") == {"reasoning_effort": "high"}
    assert translate("minimal") == {"reasoning_effort": "minimal"}
    assert translate(None) == {}


# --- conformance -------------------------------------------------------------------
#
# Nebius shares the compat generation path, so the interesting axis for the matrix is
# `list_models`: the fake below answers the verbose form, which is the adapter's only
# real delta from the preset tier.


def _nebius_server(scenario: str) -> Any:
    from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

    inner: FakeOpenAIServer
    if scenario == "tools":
        inner = FakeOpenAIServer(
            FakeResponse(
                text="",
                tool_calls=(("call_0", "lookup", '{"key": "alpha"}'),),
                finish_reason="tool_calls",
            )
        )
    elif scenario == "structured":
        inner = FakeOpenAIServer(FakeResponse(text=json.dumps({"answer": "42"})))
    elif scenario == "repair":
        inner = FakeOpenAIServer(
            [
                FakeResponse(text='{"wrong": true}'),
                FakeResponse(text=json.dumps({"answer": "42"})),
            ]
        )
    elif scenario == "auth_error":
        inner = FakeOpenAIServer(FakeResponse(status=401, error_message="invalid key"))
    elif scenario == "rate_limited":
        inner = FakeOpenAIServer(
            [
                FakeResponse(status=429, error_message="slow down", headers={"retry-after": "0"}),
                FakeResponse(text="recovered"),
            ]
        )
    elif scenario == "oversized":
        inner = FakeOpenAIServer(FakeResponse(text="x" * 100_000))
    elif scenario == "odd_finish":
        inner = FakeOpenAIServer(FakeResponse(text="done", finish_reason="wat"))
    else:
        inner = FakeOpenAIServer(FakeResponse(text="Hello from Nebius."))

    compat = inner.transport()

    def handler(request: httpx2.Request) -> Any:
        # The verbose listing is the adapter's only delta; everything else is the
        # shared compat dialect.
        if request.url.path.endswith("/models"):
            return httpx2.Response(200, json=VERBOSE_LISTING)
        return compat.handler(request)

    return handler


async def _build_nebius_client(scenario: str) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "nebius",
                api_key="test-key",
                transport=httpx2.MockTransport(_nebius_server(scenario)),
            )
        ],
        route=ai.Route(
            targets=("nebius:deepseek-ai/DeepSeek-V3",),
            retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
        ),
    )


HARNESS = ConformanceHarness(
    provider_id="nebius",
    model="deepseek-ai/DeepSeek-V3",
    build_client=_build_nebius_client,
    # The shared fake has no reasoning channel; the translator test above covers it.
    supports=Capabilities(reasoning=False),
)


async def test_nebius_conformance() -> None:
    results = await run_conformance(HARNESS)
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, f"conformance failures: {[(f.name, f.detail) for f in failures]}"
