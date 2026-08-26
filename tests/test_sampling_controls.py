"""Seed, penalties, and log-probabilities: the normalized surface and each dialect's spelling.

Three of these four are sampling knobs every major dialect ships and AnyInfer previously
made callers spell per provider through ``provider_options`` — which is exactly the
per-engine branch in a consuming app that this library exists to remove. The fourth,
log-probabilities, is an *output* the normalized result had nowhere to put, so the sidecar
refused the request outright rather than bill for data it could not return.

What makes these worth their own module is the failure mode. A seed that reaches no wire
field, or a penalty spelled under a name the provider does not read, produces a perfectly
successful response that silently ignored the caller — so every test here asserts on the
bytes that left, not merely on the absence of an exception.
"""

from __future__ import annotations

import math

import httpx2
import pytest

import anyinfer as ai
from anyinfer._client.wire import build_wire_request, dropped_parameters
from anyinfer.providers.base import WireRequest
from anyinfer.registry import default_registry
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced
from anyinfer.types.requests import MAX_TOP_LOGPROBS, GenerationRequest, Sampling
from anyinfer.types.results import TokenLogprob
from support import make_client

# ---- the normalized types --------------------------------------------------------------


def test_unset_sampling_stays_byte_for_byte_what_it_was() -> None:
    """The additions are additive: a default `Sampling` must still mean "ask for nothing"."""
    assert Sampling() == Sampling(seed=None, presence_penalty=None, frequency_penalty=None)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"seed": -1}, "seed"),
        ({"presence_penalty": math.nan}, "presence_penalty"),
        ({"frequency_penalty": math.inf}, "frequency_penalty"),
    ],
)
def test_sampling_refuses_values_no_provider_could_act_on(
    kwargs: dict[str, float], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        Sampling(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("count", [-1, MAX_TOP_LOGPROBS + 1])
def test_logprobs_count_is_bounded_at_construction(count: int) -> None:
    """Refused here rather than as a provider 400 after the prompt was assembled."""
    with pytest.raises(ValueError, match="logprobs"):
        GenerationRequest(messages=(ai.user("hi"),), logprobs=count)


def test_logprobs_zero_is_a_real_request_and_not_an_absence() -> None:
    """`0` asks for the chosen token's own probability; `None` asks for nothing."""
    assert GenerationRequest(messages=(ai.user("hi"),), logprobs=0).logprobs == 0
    assert GenerationRequest(messages=(ai.user("hi"),)).logprobs is None


def test_token_logprob_exposes_the_probability_without_forcing_the_conversion() -> None:
    assert TokenLogprob(token="x", logprob=0.0).probability == pytest.approx(1.0)
    assert TokenLogprob(token="x", logprob=math.log(0.25)).probability == pytest.approx(0.25)


# ---- each dialect's spelling -------------------------------------------------------------

_SAMPLING = Sampling(seed=1234, presence_penalty=0.5, frequency_penalty=-0.25)


def _wire(**overrides: object) -> WireRequest:
    defaults: dict[str, object] = {"model": "m", "messages": (ai.user("hi"),)}
    defaults.update(overrides)
    return WireRequest(**defaults)  # type: ignore[arg-type]


def _adapter(provider_id: str) -> object:
    from anyinfer.providers.base import ProviderConfig

    descriptor = default_registry.get(provider_id)
    return descriptor.factory(
        ProviderConfig(
            provider_id=provider_id,
            base_url="https://fake.invalid/v1",
            # A mock transport, though nothing here makes a call: a real client builds a
            # real SSL context, which opens trust-store CA files nothing closes.
            transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json={})),
        )
    )


@pytest.mark.parametrize(
    ("provider_id", "expected"),
    [
        # The OpenAI-compat dialect, which the 86 presets and llama.cpp all inherit.
        ("openai-compat", {"seed": 1234, "presence_penalty": 0.5, "frequency_penalty": -0.25}),
        # Cohere v2 keeps the OpenAI spelling for these three even though it renames top_p.
        ("cohere", {"seed": 1234, "presence_penalty": 0.5, "frequency_penalty": -0.25}),
    ],
)
def test_flat_dialects_spell_the_new_knobs_at_the_top_level(
    provider_id: str, expected: dict[str, object]
) -> None:
    payload = _adapter(provider_id).build_payload(_wire(sampling=_SAMPLING))  # type: ignore[attr-defined]
    for key, value in expected.items():
        assert payload[key] == value, f"{provider_id} must send {key}"


def test_gemini_spells_them_camel_case_inside_generation_config() -> None:
    payload = _adapter("gemini").build_payload(_wire(sampling=_SAMPLING))  # type: ignore[attr-defined]
    config = payload["generationConfig"]
    assert config["seed"] == 1234
    assert config["presencePenalty"] == 0.5
    assert config["frequencyPenalty"] == -0.25


def test_ollama_spells_them_inside_its_options_block() -> None:
    payload = _adapter("ollama").build_payload(_wire(sampling=_SAMPLING))  # type: ignore[attr-defined]
    options = payload["options"]
    assert options["seed"] == 1234
    assert options["presence_penalty"] == 0.5
    assert options["frequency_penalty"] == -0.25


@pytest.mark.parametrize("provider_id", ["openai-compat", "cohere", "gemini", "ollama"])
def test_an_unset_knob_is_omitted_entirely_rather_than_defaulted(provider_id: str) -> None:
    """AnyInfer never invents a seed; the wire body must not carry one uninvited."""
    payload = _adapter(provider_id).build_payload(_wire())  # type: ignore[attr-defined]
    flat = repr(payload)
    for name in ("seed", "presence_penalty", "presencePenalty", "frequency", "logprobs"):
        assert name not in flat, f"{provider_id} invented {name}"


def test_the_compat_dialect_needs_both_logprob_fields_to_turn_the_feature_on() -> None:
    """`top_logprobs` alone returns nothing upstream, so the boolean always rides along."""
    chosen_only = _adapter("openai-compat").build_payload(_wire(logprobs=0))  # type: ignore[attr-defined]
    assert chosen_only["logprobs"] is True
    assert "top_logprobs" not in chosen_only

    with_alternatives = _adapter("openai-compat").build_payload(_wire(logprobs=3))  # type: ignore[attr-defined]
    assert with_alternatives["logprobs"] is True
    assert with_alternatives["top_logprobs"] == 3


def test_the_responses_dialect_takes_only_the_count() -> None:
    payload = _adapter("openai").build_payload(_wire(logprobs=3))  # type: ignore[attr-defined]
    assert payload["top_logprobs"] == 3
    assert "logprobs" not in payload


def test_gemini_omits_a_zero_count_it_would_reject() -> None:
    config = _adapter("gemini").build_payload(_wire(logprobs=0))["generationConfig"]  # type: ignore[attr-defined]
    assert config["responseLogprobs"] is True
    assert "logprobs" not in config


# ---- what happens when a target cannot honor them ---------------------------------------


@pytest.mark.parametrize(
    ("provider_id", "parameter"),
    [
        ("anthropic", "seed"),
        ("anthropic", "logprobs"),
        ("bedrock", "frequency_penalty"),
        ("openai", "seed"),
        ("ollama", "logprobs"),
        ("cohere", "logprobs"),
    ],
)
def test_a_target_that_cannot_honor_a_knob_says_so(provider_id: str, parameter: str) -> None:
    """The silently-ignored parameter is the failure mode this library exists to remove."""
    request = GenerationRequest(
        messages=(ai.user("hi"),),
        sampling=Sampling(seed=1, presence_penalty=0.1, frequency_penalty=0.1),
        logprobs=2,
    )
    dropped = dict(dropped_parameters(request, default_registry.get(provider_id)))
    assert parameter in dropped, f"{provider_id} silently ignores {parameter}"
    assert dropped[parameter], "a drop must carry a reason a person can act on"


def test_nothing_is_reported_dropped_when_nothing_was_asked_for() -> None:
    """A caller who set no knobs must not be told about knobs they never used."""
    request = GenerationRequest(messages=(ai.user("hi"),))
    for provider_id in ("anthropic", "bedrock", "openai", "ollama", "cohere"):
        dropped = dict(dropped_parameters(request, default_registry.get(provider_id)))
        assert not {"seed", "presence_penalty", "frequency_penalty", "logprobs"} & set(dropped)


def test_a_model_trustedly_without_logprobs_is_not_asked_for_them() -> None:
    """A `default`-provenance guess is not enough to withhold; a catalog fact is."""
    request = GenerationRequest(messages=(ai.user("hi"),), logprobs=2)
    descriptor = default_registry.get("openai-compat")
    target = ai.ResolvedTarget(provider_id="openai-compat", model="m")

    guessed = ModelCapabilities(features=Sourced(Feature.STREAMING, "default"))
    assert build_wire_request(request, target, descriptor, capabilities=guessed).logprobs == 2

    known = ModelCapabilities(features=Sourced(Feature.STREAMING, "catalog"))
    assert build_wire_request(request, target, descriptor, capabilities=known).logprobs is None
    assert "logprobs" in dict(dropped_parameters(request, descriptor, known))

    supported = ModelCapabilities(features=Sourced(Feature.STREAMING | Feature.LOGPROBS, "catalog"))
    assert build_wire_request(request, target, descriptor, capabilities=supported).logprobs == 2


# ---- end to end, through the client ------------------------------------------------------


@pytest.mark.parametrize("stream", [False, True])
async def test_log_probabilities_reach_the_result(stream: bool) -> None:
    """Buffered and streamed dialects put them in different places; the result is one shape."""
    server = FakeOpenAIServer(
        FakeResponse(
            text="Hi",
            logprobs=(("Hi", -0.125),),
            top_logprobs=(("Hello", -2.5),),
        )
    )
    client = make_client(server)
    try:
        target = "openai-compat:fake-model-small"
        if stream:
            handle = client.stream("hi", target=target, logprobs=1)
            async for _ in handle:
                pass
            result = handle.result
        else:
            result = await client.generate("hi", target=target, logprobs=1)
    finally:
        await client.aclose()

    assert server.requests[0]["logprobs"] is True
    assert server.requests[0]["top_logprobs"] == 1
    assert [t.token for t in result.logprobs] == ["Hi"]
    assert result.logprobs[0].logprob == pytest.approx(-0.125)
    assert result.logprobs[0].bytes == tuple(b"Hi")
    assert [t.token for t in result.logprobs[0].top] == ["Hello"]


async def test_a_result_carries_no_log_probabilities_when_none_were_asked_for() -> None:
    """The fake answers with them only on request, so this proves the field was sent."""
    server = FakeOpenAIServer(FakeResponse(text="Hi", logprobs=(("Hi", -0.125),)))
    client = make_client(server)
    try:
        result = await client.generate("hi", target="openai-compat:fake-model-small")
    finally:
        await client.aclose()

    assert "logprobs" not in server.requests[0]
    assert result.logprobs == ()


async def test_a_seed_reaches_the_wire_through_the_client() -> None:
    server = FakeOpenAIServer(FakeResponse(text="Hi"))
    client = make_client(server)
    try:
        await client.generate(
            "hi",
            target="openai-compat:fake-model-small",
            sampling=Sampling(seed=99, presence_penalty=0.4),
        )
    finally:
        await client.aclose()

    assert server.requests[0]["seed"] == 99
    assert server.requests[0]["presence_penalty"] == pytest.approx(0.4)
