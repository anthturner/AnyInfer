"""Exact token counting, and what exactness is actually for.

An estimate carries two numbers with opposite biases. The planning figure should err high
so a caller deciding "does more context fit?" errs small; the **floor** should err low
because the pre-dispatch gate *refuses* on it. The byte heuristic's floor divides by 8 and
so under-counts by roughly half — meaning the gate lets through requests that will
overflow. That gap, not the planning figure, is what installing a tokenizer buys, and it
is what most of these tests measure.
"""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.capabilities.estimate import HeuristicTokenEstimator, TokenEstimate
from anyinfer.capabilities.tokenizers import (
    DEFAULT_ENCODING,
    TargetAwareTokenEstimator,
    TiktokenEstimator,
    estimator_for,
)

pytest.importorskip("tiktoken", reason="the exact estimator lives behind the tokenizers extra")

PROSE = "The quick brown fox jumps over the lazy dog, repeatedly and with some enthusiasm."


def test_a_known_model_counts_exactly_and_says_so() -> None:
    """`floor == tokens` is the signal the gate reads to act with full force."""
    estimate = TiktokenEstimator().for_model("openai", "gpt-4o").estimate(PROSE)
    assert estimate.tokens == estimate.floor
    assert estimate.tokens > 0


CODE = "def f(x):\n    return [y for y in x if y > 0]\n" * 4


@pytest.mark.parametrize("text", [PROSE, CODE, PROSE * 20])
def test_an_exact_floor_is_meaningfully_tighter_than_the_heuristic_it_replaces(
    text: str,
) -> None:
    """The reason to install this at all, measured rather than asserted in the abstract.

    The gap is widest on code, which tokenizers pack aggressively and a bytes-per-token
    constant cannot: measured here, the byte floor lands at 31%-71% of the true count
    depending on the text. The gate refuses on that floor, so every point of that gap is a
    request it lets through and the provider then rejects.
    """
    exact = TiktokenEstimator().for_model("openai", "gpt-4o").estimate(text)
    heuristic = HeuristicTokenEstimator().estimate(text)
    assert heuristic.floor < exact.floor * 0.8


def test_an_unpublished_tokenizer_is_a_guess_and_is_reported_as_one() -> None:
    """Anthropic, Gemini, and Cohere publish no tokenizer; a substituted one may over-count."""
    substituted = TiktokenEstimator().for_model("anthropic", "claude-opus-5").estimate(PROSE)
    assert substituted.floor < substituted.tokens, "a substituted count must not claim exactness"
    assert substituted.floor > HeuristicTokenEstimator().estimate(PROSE).floor, (
        "but it must still beat counting bytes, or there was no point installing it"
    )


def test_a_pinned_encoding_is_the_callers_assertion_and_is_trusted() -> None:
    """For an open-weight family behind a compat endpoint, the model id says nothing."""
    estimate = TiktokenEstimator("cl100k_base").estimate(PROSE)
    assert estimate.tokens == estimate.floor


def test_a_pinned_estimator_ignores_per_model_specialization() -> None:
    pinned = TiktokenEstimator("cl100k_base")
    assert pinned.for_model("openai", "gpt-4o") is pinned


def test_empty_text_costs_nothing() -> None:
    assert TiktokenEstimator().estimate("") == TokenEstimate(0, 0)


def test_special_token_text_is_counted_rather_than_raising() -> None:
    """A user pasting `<|endoftext|>` must not crash a budget calculation."""
    estimate = TiktokenEstimator().for_model("openai", "gpt-4o").estimate("<|endoftext|> hello")
    assert estimate.tokens > 1


def test_the_default_encoding_is_the_newer_one() -> None:
    """An unknown model is likelier newer than older, and the newer encoding packs tighter.

    Guessing the tighter encoding under-counts, which keeps a floor a floor.
    """
    assert DEFAULT_ENCODING == "o200k_base"


# ---- the specialization seam -------------------------------------------------------------


def test_a_target_aware_estimator_is_specialized_and_a_plain_one_is_not() -> None:
    plain = HeuristicTokenEstimator()
    assert estimator_for(plain, "openai", "gpt-4o") is plain

    aware = TiktokenEstimator()
    assert estimator_for(aware, "openai", "gpt-4o") is not aware


def test_the_shipped_heuristic_is_deliberately_not_target_aware() -> None:
    """It needed no change when the seam was added, which is the point of the seam."""
    assert not isinstance(HeuristicTokenEstimator(), TargetAwareTokenEstimator)
    assert isinstance(TiktokenEstimator(), TargetAwareTokenEstimator)


async def test_the_client_specializes_per_target_before_gating() -> None:
    """A counting fake proves the injected estimator reaches the gate, per target."""

    class _Counting:
        def __init__(self) -> None:
            self.asked: list[tuple[str, str]] = []

        def for_model(self, provider_id: str, model: str) -> _Counting:
            self.asked.append((provider_id, model))
            return self

        def estimate(self, text: str) -> TokenEstimate:
            return TokenEstimate(len(text), len(text))

    from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
    from support import make_client

    counting = _Counting()
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    client = make_client(server, estimator=counting, context_gate=True)
    try:
        await client.generate("hi", target="openai-compat:fake-model-small")
    finally:
        await client.aclose()

    assert ("openai-compat", "fake-model-small") in counting.asked


def test_the_missing_dependency_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """An optional dependency's absence must be actionable, not an ImportError traceback."""
    import builtins

    real_import = builtins.__import__

    def _refuse(name: str, *args: object, **kwargs: object) -> object:
        if name == "tiktoken":
            raise ImportError("no tiktoken here")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _refuse)
    monkeypatch.setattr(TiktokenEstimator, "_ENCODINGS", {})
    with pytest.raises(ai.ConfigError, match="tokenizers"):
        TiktokenEstimator()
