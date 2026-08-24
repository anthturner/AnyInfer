"""The OpenAI-compatible preset registry: descriptors, quirks, and conformance."""

from __future__ import annotations

import json

import httpx2
import pytest

import anyinfer as ai
from anyinfer.providers.presets import (
    COMPAT_PRESETS,
    CompatPreset,
    PresetCompatAdapter,
    PresetEmbeddingAdapter,
    preset_descriptors,
)
from anyinfer.registry import ProviderRegistry
from anyinfer.testing.conformance import (
    Capabilities,
    ConformanceHarness,
    run_conformance,
)
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

PRESETS_BY_ID = {p.id: p for p in COMPAT_PRESETS}


# ---- descriptor integrity ------------------------------------------------------------


def test_every_preset_registers_and_resolves() -> None:
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    for preset in COMPAT_PRESETS:
        descriptor = registry.get(preset.id)
        assert descriptor.display_name == preset.display_name
        for alias in preset.aliases:
            assert registry.resolve_alias(alias) == preset.id


def test_preset_ids_and_aliases_are_globally_unique() -> None:
    """The registry rejects collisions; loading all built-ins proves there are none."""
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    assert len(registry.known_ids()) >= 9 + len(COMPAT_PRESETS)


def test_hosted_presets_declare_an_api_key_field() -> None:
    for descriptor in preset_descriptors():
        preset = PRESETS_BY_ID[descriptor.id]
        keys = {f.key for f in descriptor.setup.fields}
        if preset.locality == "hosted":
            assert "api_key" in keys, f"{preset.id} must describe its credential"
        assert "base_url" in keys, f"{preset.id} must allow an endpoint override"


def test_a_keyless_local_engine_can_still_be_given_a_key() -> None:
    """Started with ``--api-key``, or put behind a proxy, and it needs one after all.

    The original gap: a local preset declared no credential field at all, so a vLLM
    server launched with authentication was unconfigurable from any UI driven by the
    setup spec — the field existed on `ProviderSettings` and nowhere a user could reach.
    """
    for descriptor in preset_descriptors():
        preset = PRESETS_BY_ID[descriptor.id]
        if preset.locality != "local" or not preset.accepts_api_key:
            continue
        key_field = next(f for f in descriptor.setup.fields if f.key == "api_key")
        assert not key_field.required, f"{preset.id} must still work keyless"
        assert key_field.advanced, f"{preset.id} must not ask for a key it rarely needs"


def test_a_preset_whose_key_would_not_authenticate_offers_no_key_field() -> None:
    """Lemonade wants ``?api_key=``; Docker Model Runner ignores the header outright.

    Taking a credential, sending it in a header neither of them reads, and then failing
    to authenticate is worse than not offering the field.
    """
    for descriptor in preset_descriptors():
        if PRESETS_BY_ID[descriptor.id].accepts_api_key:
            continue
        keys = {f.key for f in descriptor.setup.fields}
        assert "api_key" not in keys, f"{descriptor.id} cannot use a bearer credential"


def test_a_preset_with_a_default_endpoint_does_not_ask_for_one() -> None:
    """The split a consuming app relies on: hosted asks for a key, local asks nothing."""
    for descriptor in preset_descriptors():
        preset = PRESETS_BY_ID[descriptor.id]
        essential = {f.key for f in descriptor.setup.essential_fields}
        if preset.requires_base_url:
            assert "base_url" in essential, f"{preset.id} must prompt for its endpoint"
        else:
            assert "base_url" not in essential, f"{preset.id} already knows its endpoint"
        if preset.locality == "local" and not preset.requires_api_key:
            # Nothing at all to fill in, except for the two engines whose address cannot
            # be guessed: KServe is a cluster service host, and Foundry Local picks its
            # port at service start.
            assert essential <= {"base_url"}, f"{preset.id} should need no setup at all"
            assert bool(essential) == preset.requires_base_url


def test_presets_without_a_default_base_url_require_one() -> None:
    for preset in COMPAT_PRESETS:
        if preset.base_url is None:
            assert preset.requires_base_url, f"{preset.id} has no URL and requires none"
            assert preset.base_url_hint, f"{preset.id} needs a base_url hint"


def test_local_presets_default_to_loopback() -> None:
    """A local engine's default must be loopback, but it may have no default at all.

    KServe is addressed by a cluster service host and Foundry Local picks its port at
    service start, so neither has a loopback address to guess. Those declare
    ``requires_base_url`` instead, which the setup UI already knows how to prompt for;
    what must never happen is a local preset silently pointing off-box.
    """
    for preset in COMPAT_PRESETS:
        if preset.locality != "local":
            continue
        if preset.base_url is None:
            assert preset.requires_base_url, f"{preset.id} has neither a URL nor a prompt"
            continue
        assert "127.0.0.1" in preset.base_url or "localhost" in preset.base_url


# ---- quirk behaviors -----------------------------------------------------------------


def _adapter(preset_id: str, handler, **config_kwargs) -> PresetCompatAdapter:
    from anyinfer.providers.base import ProviderConfig

    preset = PRESETS_BY_ID[preset_id]
    return PresetCompatAdapter(
        ProviderConfig(
            provider_id=preset_id,
            base_url=preset.base_url or "https://fake.invalid/v1",
            transport=httpx2.MockTransport(handler),
            **config_kwargs,
        ),
        preset=preset,
    )


async def test_tabbyapi_authenticates_with_x_api_key() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"object": "list", "data": []})

    adapter = _adapter("tabbyapi", handler, api_key="tabby-secret-key")
    try:
        await adapter.list_models()
    finally:
        await adapter.aclose()

    assert seen[0].headers["x-api-key"] == "tabby-secret-key"
    assert "authorization" not in seen[0].headers


async def test_moonshot_renames_the_output_token_parameter() -> None:
    from anyinfer.providers.base import WireRequest
    from anyinfer.types.requests import Sampling

    seen: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                ]
            },
        )

    adapter = _adapter("moonshot", handler, api_key="k")
    try:
        request = WireRequest(
            model="kimi-k2",
            messages=(ai.user("hi"),),
            sampling=Sampling(max_output_tokens=64),
            stream=False,
        )
        async for _ in adapter.generate(request):
            pass
    finally:
        await adapter.aclose()

    assert seen[0]["max_completion_tokens"] == 64
    assert "max_tokens" not in seen[0]


async def test_missing_listing_reports_no_models_and_optimistic_health() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("no request should be issued")

    adapter = _adapter("z-ai", handler, api_key="k")
    try:
        assert await adapter.list_models() == []
        health = await adapter.health()
    finally:
        await adapter.aclose()

    assert health.ok is True
    assert "probe" in health.detail


async def test_errors_are_attributed_to_the_preset_id() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"error": {"message": "bad key"}})

    client = ai.AsyncClient(
        [ai.ProviderSettings.of("groq", api_key="bad", transport=httpx2.MockTransport(handler))]
    )
    async with client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate("hi", target="groq:llama-3.3-70b-versatile")

    error = excinfo.value.attempts[-1].error
    assert error is not None
    assert error.provider == "groq", "attribution must name the preset, not openai-compat"


def test_reasoning_translators_produce_the_documented_wire_fields() -> None:
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)

    assert registry.get("parasail").reasoning_translator("minimal") == {
        "reasoning_effort": "low"
    }, "three-level providers clamp minimal onto their lowest documented level"
    assert registry.get("parasail").reasoning_translator("high") == {"reasoning_effort": "high"}
    assert registry.get("mistral").reasoning_translator("minimal") == {
        "reasoning_effort": "minimal"
    }
    assert registry.get("cerebras").reasoning_translator("minimal") == {
        "reasoning_effort": "low"
    }, "providers without a minimal level clamp it to low"
    assert registry.get("vercel-ai-gateway").reasoning_translator("high") == {
        "reasoning": {"effort": "high"}
    }
    assert registry.get("moonshot").reasoning_translator("high") == {}, (
        "presets without a documented control send nothing"
    )
    assert registry.get("mistral").reasoning_translator(None) == {}


async def test_reka_authenticates_with_x_api_key() -> None:
    """Reka's HTTP reference documents x-api-key on chat, not a bearer token."""
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"object": "list", "data": []})

    adapter = _adapter("reka", handler, api_key="reka-secret-key")
    try:
        await adapter.list_models()
    finally:
        await adapter.aclose()

    assert seen[0].headers["x-api-key"] == "reka-secret-key"
    assert "authorization" not in seen[0].headers


def test_local_presets_use_their_documented_default_ports() -> None:
    """Ports differ per engine and a wrong one fails only at runtime, so pin them.

    Several of these deliberately avoid the value a reader would guess: TGI and
    OpenLLM serve on 3000, Aphrodite on 2242 rather than vLLM's 8000, and Triton's
    OpenAI frontend on 9000 while 8000 stays its own KServe endpoint.
    """
    documented = {
        "vllm": 8000,
        "sglang": 30000,
        "koboldcpp": 5001,
        "jan": 1337,
        "gpt4all": 4891,
        "localai": 8080,
        "llamafile": 8080,
        "tgi": 3000,
        "openllm": 3000,
        "aphrodite": 2242,
        "mlc-llm": 8000,
        "triton": 9000,
    }
    for preset_id, port in documented.items():
        preset = PRESETS_BY_ID[preset_id]
        assert preset.default_port == port, f"{preset_id} default port"
        assert f":{port}" in (preset.base_url or ""), f"{preset_id} base URL port"


def test_presets_requiring_a_base_url_have_no_misleading_default() -> None:
    """Account/region-scoped endpoints must not ship a URL that would resolve."""
    for preset_id in ("snowflake-cortex", "databricks", "oci-genai"):
        preset = PRESETS_BY_ID[preset_id]
        assert preset.requires_base_url is True
        assert preset.base_url is None
        assert preset.base_url_hint


def test_endpoints_corrected_by_re_verification_stay_corrected() -> None:
    """Pin the facts a 2026-08-07 re-verification pass found recorded wrongly.

    Each of these shipped with a plausible but wrong value, and every one fails only
    against the live service — a wrong host 404s, a disabled listing silently reports
    no models. They are cheap to assert and expensive to rediscover.
    """
    stepfun = PRESETS_BY_ID["stepfun"]
    assert stepfun.base_url == "https://api.stepfun.com/v1", (
        "the documented host is api.stepfun.com; .ai and the /step_plan/v1 "
        "subscription path were both wrong here"
    )
    assert stepfun.key_env == "STEP_API_KEY", "official examples spell it STEP_API_KEY"

    # Listings these providers do document — disabling them silently loses discovery.
    for preset_id in ("helicone", "geniex", "qianfan", "stepfun"):
        assert PRESETS_BY_ID[preset_id].models_listing is True, preset_id

    watsonx = PRESETS_BY_ID["watsonx"]
    assert watsonx.key_env == "WATSONX_API_KEY", (
        "IBM's own example passes the Cloud API key through, so the preset must not "
        "imply an IAM token exchange is mandatory"
    )
    assert watsonx.output_tokens_field == "max_tokens", (
        "max_completion_tokens was never observed in IBM's own examples"
    )


def test_requesty_spells_its_lowest_effort_min_not_minimal() -> None:
    """Requesty documents `min`; `minimal` is a near-homograph it does not accept."""
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    assert registry.get("requesty").reasoning_translator("minimal") == {"reasoning_effort": "min"}
    assert registry.get("requesty").reasoning_translator("high") == {"reasoning_effort": "high"}


async def test_perplexity_declares_tools_as_ignored() -> None:
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    descriptor = registry.get("perplexity")
    assert "tools" in descriptor.ignored_parameters
    from anyinfer.types.capabilities import Feature

    assert not descriptor.default_capabilities.features.value & Feature.TOOLS


# ---- conformance ---------------------------------------------------------------------

PROBE_ANSWER = json.dumps({"answer": "ok"})


def _server_for(scenario: str) -> FakeOpenAIServer:
    if scenario == "tools":
        return FakeOpenAIServer(
            FakeResponse(
                text="",
                tool_calls=(("call_0", "lookup", '{"key": "alpha"}'),),
                finish_reason="tool_calls",
            )
        )
    if scenario == "structured":
        return FakeOpenAIServer(FakeResponse(text=PROBE_ANSWER))
    if scenario == "repair":
        return FakeOpenAIServer(
            [FakeResponse(text='{"wrong": true}'), FakeResponse(text=PROBE_ANSWER)]
        )
    if scenario == "auth_error":
        return FakeOpenAIServer(FakeResponse(status=401, error_message="invalid key"))
    if scenario == "rate_limited":
        return FakeOpenAIServer(
            [
                FakeResponse(status=429, error_message="slow down", headers={"retry-after": "0"}),
                FakeResponse(text="recovered"),
            ]
        )
    if scenario == "oversized":
        return FakeOpenAIServer(FakeResponse(text="x" * 20_000))
    if scenario == "odd_finish":
        return FakeOpenAIServer(FakeResponse(text="hello", finish_reason="model_decided"))
    return FakeOpenAIServer(FakeResponse(text="Hello from the preset fake."))


def _harness(preset: CompatPreset, model: str) -> ConformanceHarness:
    async def build_client(scenario: str) -> ai.AsyncClient:
        return ai.AsyncClient(
            [
                ai.ProviderSettings.of(
                    preset.id,
                    api_key="test-key" if preset.requires_api_key else None,
                    base_url=preset.base_url or "https://fake.invalid/v1",
                    transport=_server_for(scenario).transport(),
                )
            ],
            route=ai.Route(
                targets=(f"{preset.id}:{model}",),
                retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
            ),
        )

    return ConformanceHarness(
        provider_id=preset.id,
        model=model,
        build_client=build_client,
        supports=Capabilities(
            reasoning=False,  # the shared fake has no reasoning channel
            list_models=preset.models_listing,
            tools="tools" not in preset.ignored_parameters,
            cancellation=True,
        ),
    )


@pytest.mark.parametrize("preset_id", sorted(PRESETS_BY_ID), ids=str)
async def test_preset_conformance(preset_id: str) -> None:
    """Run the full conformance suite against every preset, not a sampled few.

    Sampling by "quirk axis" was the old approach, and it assumed the axes were known
    and orthogonal. They are neither: a preset combines an auth spelling, a token-field
    rename, a listing flag and a reasoning translator, and it is the *combination* that
    reaches the wire. Since the harness is provider-agnostic and each run is a handful
    of in-memory requests, covering all of them costs little and removes the judgment
    call about which ones deserve coverage.
    """
    preset = PRESETS_BY_ID[preset_id]
    results = await run_conformance(_harness(preset, "fake-model-small"))
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, f"{preset_id} failures: {[(f.name, f.detail) for f in failures]}"


# ---- the 2026-08-07 batch: routers, regional clouds, and local engines ----------------


@pytest.mark.parametrize(
    ("preset_id", "expected_base"),
    [
        ("requesty", "https://router.requesty.ai/v1"),
        ("martian", "https://api.withmartian.com/v1"),
        ("helicone", "https://ai-gateway.helicone.ai"),
        ("chutes", "https://llm.chutes.ai/v1"),
        ("avian", "https://api.avian.io/v1"),
        ("volcengine", "https://ark.ap-southeast.bytepluses.com/api/v3"),
        ("qianfan", "https://qianfan.baidubce.com/v2"),
        ("hunyuan", "https://api.hunyuan.cloud.tencent.com/v1"),
        ("spark", "https://spark-api-open.xf-yun.com/v1"),
        ("stepfun", "https://api.stepfun.com/v1"),
    ],
)
def test_new_hosted_presets_carry_their_verified_endpoint(
    preset_id: str, expected_base: str
) -> None:
    """Endpoints come from each provider's own docs; a wrong one fails only at runtime."""
    assert PRESETS_BY_ID[preset_id].base_url == expected_base


@pytest.mark.parametrize(
    ("preset_id", "port"),
    [("xinference", 9997), ("ramalama", 8080), ("geniex", 18181)],
)
def test_new_local_presets_pin_their_documented_port(preset_id: str, port: int) -> None:
    preset = PRESETS_BY_ID[preset_id]
    assert preset.locality == "local"
    assert preset.requires_api_key is False
    assert preset.default_port == port
    assert preset.base_url is not None and str(port) in preset.base_url


def test_watsonx_demands_a_base_url_because_it_is_regional() -> None:
    preset = PRESETS_BY_ID["watsonx"]
    assert preset.base_url is None
    assert preset.requires_base_url
    assert "ml.cloud.ibm.com" in preset.base_url_hint
    # Not max_completion_tokens: that spelling appears in no IBM-published example.
    assert preset.output_tokens_field == "max_tokens"


def test_the_rebranded_engines_keep_their_old_names_reachable() -> None:
    """A rename should not strand anyone who knows the project by its former name."""
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    assert registry.resolve_alias("nexa") == "geniex"
    assert registry.resolve_alias("doubao") == "volcengine"
    assert registry.resolve_alias("ernie") == "qianfan"


def test_semantic_hazards_are_documented_where_a_reader_will_look() -> None:
    """Two presets deviate in behavior, not just spelling; the note must say so."""
    assert "after" in PRESETS_BY_ID["hunyuan"].note.lower()
    assert "inverting the vendor/model order" in PRESETS_BY_ID["helicone"].note

    # Qianfan's usual failure is mixing v2 keys with the deprecated v1 flow.
    assert "v1" in PRESETS_BY_ID["qianfan"].note

    # Spark's HTTP path takes a different credential than its WebSocket one.
    assert "APIPassword" in PRESETS_BY_ID["spark"].note


def test_regional_presets_declare_no_model_listing() -> None:
    """Only where GET /models is genuinely undocumented may discovery be disabled.

    Qianfan, StepFun and GenieX were originally listed here too; re-verification found
    all three do document a listing, so they moved to the enabled set rather than
    having this assertion relaxed.
    """
    for preset_id in ("volcengine", "hunyuan", "spark"):
        assert PRESETS_BY_ID[preset_id].models_listing is False, preset_id


# ---- embeddings (T5: verified-only opt-in) --------------------------------------------


def _embedding_adapter(preset_id: str, handler, **config_kwargs) -> PresetEmbeddingAdapter:
    from anyinfer.providers.base import ProviderConfig

    preset = PRESETS_BY_ID[preset_id]
    assert preset.embeddings, f"{preset_id} has not been verified for embeddings"
    return PresetEmbeddingAdapter(
        ProviderConfig(
            provider_id=preset_id,
            base_url=preset.base_url or "https://fake.invalid/v1",
            transport=httpx2.MockTransport(handler),
            **config_kwargs,
        ),
        preset=preset,
    )


def test_only_the_verified_four_presets_declare_embeddings() -> None:
    """Unverified presets stay generation-only — the correct default (plan BH.I.2)."""
    embedding_ids = {p.id for p in COMPAT_PRESETS if p.embeddings}
    assert embedding_ids == {"together", "fireworks", "mistral", "deepinfra"}


def test_embedding_presets_declare_the_operation_and_adapter() -> None:
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    for preset_id in ("together", "fireworks", "mistral", "deepinfra"):
        descriptor = registry.get(preset_id)
        assert descriptor.operations == frozenset({"generation", "embedding"})
    for preset_id in ("groq", "cerebras"):
        descriptor = registry.get(preset_id)
        assert descriptor.operations == frozenset({"generation"})


async def test_a_verified_preset_embeds_through_the_shared_dialect() -> None:
    seen: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [0.1, 0.2]}],
                "model": "togethercomputer/m2-bert-80M-8k-retrieval",
            },
        )

    adapter = _embedding_adapter("together", handler, api_key="k")
    try:
        from anyinfer.providers.base import EmbeddingWireRequest

        result = await adapter.embed(
            EmbeddingWireRequest(
                model="togethercomputer/m2-bert-80M-8k-retrieval", inputs=("hi",)
            )
        )
    finally:
        await adapter.aclose()

    assert seen[0]["model"] == "togethercomputer/m2-bert-80M-8k-retrieval"
    assert result.vectors[0] == pytest.approx((0.1, 0.2))


def test_an_unverified_preset_has_no_embed_method() -> None:
    """A PresetCompatAdapter has no embed() at all — the structural opt-in guard."""
    assert not hasattr(PresetCompatAdapter, "embed")
    assert hasattr(PresetEmbeddingAdapter, "embed")
