"""Token estimation, context budgets, and pre-dispatch gating (D25, L6)."""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.capabilities.budget import (
    DEFAULT_OUTPUT_RESERVE_TOKENS,
    MAXIMUM_HEADROOM_TOKENS,
    MINIMUM_HEADROOM_TOKENS,
    build_context_budget,
    headroom_for,
)
from anyinfer.capabilities.estimate import (
    PER_MESSAGE_OVERHEAD_TOKENS,
    HeuristicTokenEstimator,
    TokenEstimate,
    estimate_request,
)
from anyinfer.capabilities.gating import check_context_fit, context_gate_error
from anyinfer.errors import ContextLengthError
from anyinfer.registry import ProviderDescriptor, ProviderRegistry
from anyinfer.routing.policy import never_retry_client_errors
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.types.capabilities import ModelCapabilities, Sourced, TokenCalibration
from anyinfer.types.messages import Message, Text, ToolCall, ToolResult, user
from anyinfer.types.requests import GenerationRequest, Sampling, SchemaSpec, ToolSpec
from support import make_client, make_multi_client


def _request(text: str, **kwargs: object) -> GenerationRequest:
    return GenerationRequest(messages=(user(text),), **kwargs)  # type: ignore[arg-type]


# ---- the estimator -------------------------------------------------------------------


def test_heuristic_estimator_math() -> None:
    estimate = HeuristicTokenEstimator().estimate("x" * 30)
    assert estimate.tokens == 10  # ceil(30 / 3)
    assert estimate.floor == 3  # 30 // 8


def test_heuristic_estimator_counts_utf8_bytes_not_characters() -> None:
    estimate = HeuristicTokenEstimator().estimate("é" * 3)  # 6 UTF-8 bytes
    assert estimate.tokens == 2


def test_heuristic_estimator_floor_never_exceeds_tokens() -> None:
    estimate = HeuristicTokenEstimator().estimate("x")
    assert estimate.floor <= estimate.tokens
    assert HeuristicTokenEstimator().estimate("") == TokenEstimate(0, 0)


def test_heuristic_estimator_multiplier_inflates_estimate_but_not_floor() -> None:
    plain = HeuristicTokenEstimator().estimate("x" * 300)
    calibrated = HeuristicTokenEstimator(multiplier=1.5).estimate("x" * 300)
    assert calibrated.tokens == 150  # ceil(100 * 1.5)
    assert calibrated.floor == plain.floor, "envelope calibration must not raise the floor"


@pytest.mark.parametrize("multiplier", [0.0, -1.0, float("inf"), float("nan")])
def test_heuristic_estimator_rejects_bad_multiplier(multiplier: float) -> None:
    with pytest.raises(ValueError):
        HeuristicTokenEstimator(multiplier=multiplier)


def test_exact_estimator_plugs_in_through_the_protocol() -> None:
    class Exact:
        def estimate(self, text: str) -> TokenEstimate:
            count = len(text.split())
            return TokenEstimate(count, count)

    estimate = estimate_request(_request("one two three"), estimator=Exact())
    assert estimate.messages.floor == 3
    assert estimate.messages.tokens == 3 + PER_MESSAGE_OVERHEAD_TOKENS


# ---- request estimation --------------------------------------------------------------


def test_estimate_request_charges_per_message_overhead_to_tokens_only() -> None:
    empty = GenerationRequest(messages=(Message(role="user", content=(Text(""),)),))
    estimate = estimate_request(empty)
    assert estimate.messages.tokens == PER_MESSAGE_OVERHEAD_TOKENS
    assert estimate.messages.floor == 0


def test_estimate_request_counts_tools_and_schema() -> None:
    bare = estimate_request(_request("hi"))
    assert bare.tools == TokenEstimate(0, 0)
    assert bare.schema == TokenEstimate(0, 0)

    loaded = estimate_request(
        _request(
            "hi",
            tools=(ToolSpec("lookup", "Find a record.", {"type": "object"}),),
            schema=SchemaSpec(json_schema={"type": "object", "properties": {}}),
        )
    )
    assert loaded.tools.tokens > 0
    assert loaded.schema.tokens > 0
    assert loaded.tokens == loaded.messages.tokens + loaded.tools.tokens + loaded.schema.tokens


def test_estimate_request_envelope_is_zero_without_a_calibration() -> None:
    estimate = estimate_request(_request("hi"))
    assert estimate.envelope == TokenEstimate(0, 0)
    assert estimate_request(_request("hi"), calibration=TokenCalibration()).envelope.tokens == 0


def test_estimate_request_envelope_charges_multiplier_and_overhead() -> None:
    plain = estimate_request(_request("x" * 300))
    calibrated = estimate_request(
        _request("x" * 300), calibration=TokenCalibration(multiplier=2.0, overhead_tokens=50)
    )

    content = plain.messages.tokens
    assert calibrated.messages == plain.messages, "the components sent stay as sent"
    assert calibrated.envelope.tokens == content + 50
    assert calibrated.tokens == plain.tokens + content + 50


def test_estimate_request_envelope_never_raises_the_floor() -> None:
    plain = estimate_request(_request("x" * 3_000))
    calibrated = estimate_request(
        _request("x" * 3_000), calibration=TokenCalibration(multiplier=3.0, overhead_tokens=900)
    )
    assert calibrated.floor == plain.floor
    assert calibrated.envelope.floor == 0


@pytest.mark.parametrize(
    ("multiplier", "overhead"),
    [(0.0, 0), (-1.0, 0), (float("inf"), 0), (float("nan"), 0), (1.0, -1)],
)
def test_token_calibration_rejects_nonsense(multiplier: float, overhead: int) -> None:
    with pytest.raises(ValueError):
        TokenCalibration(multiplier=multiplier, overhead_tokens=overhead)


def test_estimate_request_counts_tool_calls_and_results() -> None:
    conversation = GenerationRequest(
        messages=(
            user("look this up"),
            Message(
                role="assistant",
                content=(ToolCall(id="c1", name="lookup", arguments={"query": "x" * 120}),),
            ),
            Message(role="tool", content=(ToolResult(call_id="c1", content="y" * 120),)),
        )
    )
    plain = estimate_request(GenerationRequest(messages=(user("look this up"),)))
    assert estimate_request(conversation).messages.tokens > plain.messages.tokens + 80


# ---- the budget calculator -----------------------------------------------------------


def test_budget_allowance_math() -> None:
    budget = build_context_budget(
        _request("x" * 300), ModelCapabilities(context_window=Sourced(16_384, "catalog"))
    )
    assert budget.headroom_tokens == 820  # ceil(16384 * 0.05)
    assert budget.output_reserve_tokens == DEFAULT_OUTPUT_RESERVE_TOKENS
    assert budget.input_allowance_tokens == 16_384 - 4_096 - 820
    assert budget.remaining_tokens == budget.input_allowance_tokens - budget.estimate.tokens
    assert budget.fits is True


def test_headroom_clamps() -> None:
    assert headroom_for(1_000) == MINIMUM_HEADROOM_TOKENS
    assert headroom_for(1_000_000) == MAXIMUM_HEADROOM_TOKENS
    assert headroom_for(16_384) == 820


def test_budget_reserve_follows_the_request_max_output_tokens() -> None:
    budget = build_context_budget(
        _request("hi", sampling=Sampling(max_output_tokens=512)),
        ModelCapabilities(context_window=Sourced(8_192, "catalog")),
    )
    assert budget.output_reserve_tokens == 512


def test_budget_reserve_is_capped_by_the_model_max_output() -> None:
    budget = build_context_budget(
        _request("hi"),
        ModelCapabilities(
            context_window=Sourced(8_192, "catalog"),
            max_output_tokens=Sourced(1_024, "catalog"),
        ),
    )
    assert budget.output_reserve_tokens == 1_024


def test_budget_explicit_overrides_and_validation() -> None:
    caps = ModelCapabilities(context_window=Sourced(8_192, "catalog"))
    budget = build_context_budget(
        _request("hi"), caps, output_reserve_tokens=100, headroom_tokens=0
    )
    assert budget.input_allowance_tokens == 8_092
    with pytest.raises(ValueError):
        build_context_budget(_request("hi"), caps, output_reserve_tokens=-1)
    with pytest.raises(ValueError):
        build_context_budget(_request("hi"), caps, headroom_tokens=-1)


def test_budget_with_unknown_window_is_unknown_not_guessed() -> None:
    for caps in (None, ModelCapabilities()):
        budget = build_context_budget(_request("x" * 100_000), caps)
        assert budget.input_allowance_tokens is None
        assert budget.remaining_tokens is None
        assert budget.fits is None


# ---- the gate ------------------------------------------------------------------------


def test_gate_only_trusted_provenance_gates() -> None:
    oversized = _request("x" * 10_000)
    placeholder = build_context_budget(
        oversized, ModelCapabilities(context_window=Sourced(64, "default"))
    )
    assert context_gate_error(placeholder) is None

    known = build_context_budget(
        oversized, ModelCapabilities(context_window=Sourced(64, "catalog"))
    )
    error = context_gate_error(known, provider="p", model="m")
    assert isinstance(error, ContextLengthError)
    assert error.provider == "p"
    assert "m" in error.detail
    assert never_retry_client_errors(error) is False, "gate errors must never be retried"


def test_gate_acts_on_the_floor_not_the_planning_estimate() -> None:
    # 600 bytes: planning estimate 200 tokens, floor 75 — over the allowance but under
    # the window, so the request may proceed and the provider gets the final say.
    budget = build_context_budget(
        _request("x" * 600),
        ModelCapabilities(context_window=Sourced(150, "catalog")),
        output_reserve_tokens=0,
        headroom_tokens=0,
    )
    assert budget.fits is False
    assert context_gate_error(budget) is None


def test_check_context_fit_returns_the_budget_or_raises() -> None:
    caps = ModelCapabilities(context_window=Sourced(16_384, "catalog"))
    budget = check_context_fit(_request("hi"), caps)
    assert budget.fits is True
    with pytest.raises(ContextLengthError):
        check_context_fit(_request("x" * 10_000), ModelCapabilities(context_window=Sourced(64, "probed")))


# ---- client integration --------------------------------------------------------------


def _capacity_registry() -> ProviderRegistry:
    """Two openai-compat registrations whose static catalogs differ only in window size."""
    from anyinfer.providers.openai_compat import OpenAICompatAdapter

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    for provider_id, window in (("tiny", 64), ("big", 200_000)):
        registry.register(
            ProviderDescriptor(
                id=provider_id,
                display_name=f"Fake {provider_id}",
                factory=OpenAICompatAdapter,
                requires_base_url=True,
                static_capabilities={
                    "m": ModelCapabilities(context_window=Sourced(window, "catalog"))
                },
            )
        )
    return registry


OVERSIZED_PROMPT = "word " * 400  # 2000 bytes: floor 250 tokens, far over a 64-token window


async def test_gate_fails_fast_without_a_round_trip() -> None:
    server = FakeOpenAIServer(FakeResponse(text="never reached"))
    async with make_multi_client(
        [("tiny", server)], registry=_capacity_registry()
    ) as client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate(OVERSIZED_PROMPT, target="tiny:m")

    assert server.call_count == 0, "a gated request must never reach the provider"
    trail = excinfo.value.attempts
    assert [a.error.type_name for a in trail if a.error] == ["ContextLengthError"]


async def test_gate_redirects_to_context_window_targets() -> None:
    tiny_server = FakeOpenAIServer(FakeResponse(text="never reached"))
    big_server = FakeOpenAIServer(FakeResponse(text="from the larger model"))
    async with make_multi_client(
        [("tiny", tiny_server), ("big", big_server)], registry=_capacity_registry()
    ) as client:
        result = await client.generate(
            OVERSIZED_PROMPT,
            route=ai.Route(targets=("tiny:m",), context_window_targets=("big:m",)),
        )

    assert result.text == "from the larger model"
    assert tiny_server.call_count == 0
    assert big_server.call_count == 1


async def test_gate_can_be_disabled() -> None:
    server = FakeOpenAIServer(FakeResponse(text="provider decided"))
    async with make_multi_client(
        [("tiny", server)], registry=_capacity_registry(), context_gate=False
    ) as client:
        result = await client.generate(OVERSIZED_PROMPT, target="tiny:m")

    assert result.text == "provider decided"
    assert server.call_count == 1


async def test_unknown_window_never_gates() -> None:
    server = FakeOpenAIServer(FakeResponse(text="dispatched"))
    async with make_client(server) as client:
        result = await client.generate(OVERSIZED_PROMPT, target="openai-compat:m")
    assert result.text == "dispatched"


async def test_client_budget_is_a_pure_preflight() -> None:
    server = FakeOpenAIServer()
    async with make_multi_client(
        [("big", server)], registry=_capacity_registry()
    ) as client:
        budget = client.budget("plan around me", target="big:m")

    assert budget.context_window == Sourced(200_000, "catalog")
    assert budget.input_allowance_tokens == 200_000 - 4_096 - 8_192
    assert budget.fits is True
    assert server.call_count == 0


def _calibrated_registry(calibration: TokenCalibration) -> ProviderRegistry:
    """One openai-compat registration that declares a transport envelope."""
    from anyinfer.providers.openai_compat import OpenAICompatAdapter

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id="enveloped",
            display_name="Fake enveloped",
            factory=OpenAICompatAdapter,
            requires_base_url=True,
            token_calibration=calibration,
            static_capabilities={
                "m": ModelCapabilities(context_window=Sourced(100_000, "catalog"))
            },
        )
    )
    return registry


async def test_client_budget_applies_the_descriptor_calibration() -> None:
    server = FakeOpenAIServer()
    prompt = "word " * 200
    async with make_multi_client(
        [("enveloped", server)],
        registry=_calibrated_registry(TokenCalibration(multiplier=2.4, overhead_tokens=1_200)),
    ) as calibrated_client:
        calibrated = calibrated_client.budget(prompt, target="enveloped:m")
    async with make_multi_client(
        [("enveloped", server)], registry=_calibrated_registry(TokenCalibration())
    ) as plain_client:
        plain = plain_client.budget(prompt, target="enveloped:m")

    assert calibrated.estimate.envelope.tokens > 1_200
    assert calibrated.remaining_tokens < plain.remaining_tokens, (
        "a provider that bills for its own harness must budget for it"
    )
    assert server.call_count == 0


async def test_calibration_never_gates_a_request_the_floor_permits() -> None:
    # A large multiplier pushes the planning estimate over a small window, but the gate
    # reads the floor, which no calibration moves — so the provider still gets its say.
    from anyinfer.providers.openai_compat import OpenAICompatAdapter

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id="enveloped",
            display_name="Fake enveloped",
            factory=OpenAICompatAdapter,
            requires_base_url=True,
            token_calibration=TokenCalibration(multiplier=8.0, overhead_tokens=4_000),
            static_capabilities={
                "m": ModelCapabilities(context_window=Sourced(2_000, "catalog"))
            },
        )
    )
    server = FakeOpenAIServer(FakeResponse(text="dispatched"))
    async with make_multi_client([("enveloped", server)], registry=registry) as client:
        budget = client.budget("word " * 100, target="enveloped:m")
        assert budget.fits is False, "the planning figure is over the allowance"
        result = await client.generate("word " * 100, target="enveloped:m")

    assert result.text == "dispatched"
    assert server.call_count == 1


def test_sync_client_budget() -> None:
    server = FakeOpenAIServer()
    client = ai.Client(
        [
            ai.ProviderSettings.of(
                "big", base_url="https://fake.invalid/v1", transport=server.transport()
            )
        ],
        registry=_capacity_registry(),
    )
    try:
        budget = client.budget("hello", target="big:m")
        assert budget.fits is True
    finally:
        client.close()
