"""Exact token counting, and what exactness is actually for.

An estimate carries two numbers with opposite biases. The planning figure should err high
so a caller deciding "does more context fit?" errs small; the **floor** should err low
because the pre-dispatch gate *refuses* on it. The byte heuristic's floor divides by 8 and
so under-counts badly. That gap, not the planning figure, is what installing a tokenizer
buys, and it is what most of these tests measure.

**These tests never touch the network.** `tiktoken.get_encoding` downloads a vocabulary
file on first use, so a suite that loaded a real encoding would need network access — for
CI on a fresh runner, on every run. The behaviour is therefore exercised against a fake
encoder, and the fake is kept honest by `test_the_real_module_has_the_surface_the_fake_
stands_in_for`, which introspects the installed `tiktoken` without loading anything. That
pairing is deliberate: a fake more permissive than the thing it replaces is precisely how
the dependency-contract drift in this project's own history went unnoticed.
"""

from __future__ import annotations

import re
import types
from typing import Any

import pytest

import anyinfer as ai
from anyinfer.capabilities.estimate import HeuristicTokenEstimator, TokenEstimate
from anyinfer.capabilities.tokenizers import (
    DEFAULT_ENCODING,
    TargetAwareTokenEstimator,
    TiktokenEstimator,
    estimator_for,
)

PROSE = "The quick brown fox jumps over the lazy dog, repeatedly and with some enthusiasm."
CODE = "def f(x):\n    return [y for y in x if y > 0]\n" * 4

_KNOWN_MODELS = {"gpt-4o": "o200k_base", "gpt-3.5-turbo": "cl100k_base"}

_REAL_MODULE_LOADER = TiktokenEstimator._module.__func__
"""The genuine importer, captured before the autouse fixture replaces it.

One test needs the real import path — the one asserting that a missing dependency is
reported actionably — and by the time a fixture could restore it, the fixture's own
replacement is what `__func__` would hand back."""


class _FakeEncoding:
    """Counts tokens the way a BPE tokenizer roughly does, without a vocabulary file.

    Splits on word boundaries and punctuation, which lands within the right order of
    magnitude of a real encoding — enough for the ratio assertions below, and irrelevant
    to the ones about *which* numbers are reported as exact.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def encode(self, text: str, *, disallowed_special: Any = ()) -> list[int]:
        del disallowed_special
        return [hash(piece) for piece in re.findall(r"\w+|[^\w\s]", text)]


def _fake_tiktoken() -> types.ModuleType:
    """A stand-in for the installed `tiktoken`, with only the two functions we call."""
    module = types.ModuleType("tiktoken")

    def get_encoding(name: str) -> _FakeEncoding:
        return _FakeEncoding(name)

    def encoding_for_model(model: str) -> _FakeEncoding:
        if model not in _KNOWN_MODELS:
            raise KeyError(f"could not automatically map {model} to a tokeniser")
        return _FakeEncoding(_KNOWN_MODELS[model])

    module.get_encoding = get_encoding  # type: ignore[attr-defined]
    module.encoding_for_model = encoding_for_model  # type: ignore[attr-defined]
    return module


@pytest.fixture(autouse=True)
def offline_tiktoken(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the estimator at the fake module and clear the process-wide encoding cache."""
    module = _fake_tiktoken()
    monkeypatch.setattr(TiktokenEstimator, "_module", classmethod(lambda cls: module))
    monkeypatch.setattr(TiktokenEstimator, "_ENCODINGS", {})


# ---- what is reported as exact ------------------------------------------------------------


def test_a_known_model_counts_exactly_and_says_so() -> None:
    """`floor == tokens` is the signal the gate reads to act with full force."""
    estimate = TiktokenEstimator().for_model("openai", "gpt-4o").estimate(PROSE)
    assert estimate.tokens == estimate.floor
    assert estimate.tokens > 0


@pytest.mark.parametrize("text", [PROSE, CODE, PROSE * 20])
def test_an_exact_floor_is_meaningfully_tighter_than_the_heuristic_it_replaces(
    text: str,
) -> None:
    """The reason to install this at all.

    The gate refuses on the floor, so every point of the gap between the byte floor and
    the true count is a request the gate lets through and the provider then rejects.
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


def test_the_default_encoding_is_the_newer_one() -> None:
    """An unknown model is likelier newer than older, and the newer encoding packs tighter.

    Guessing the tighter encoding under-counts, which keeps a floor a floor.
    """
    assert DEFAULT_ENCODING == "o200k_base"


def test_an_unrecognized_model_falls_back_without_raising() -> None:
    """Tiktoken raises `KeyError` for a model it does not know; that is an answer, not a failure."""
    estimator = TiktokenEstimator().for_model("someone", "a-model-shipped-last-tuesday")
    assert estimator.estimate(PROSE).tokens > 0


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


# ---- the dependency itself ------------------------------------------------------------------


def test_the_missing_dependency_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """An optional dependency's absence must be actionable, not an ImportError traceback."""
    import builtins

    real_import = builtins.__import__

    def _refuse(name: str, *args: object, **kwargs: object) -> object:
        if name == "tiktoken":
            raise ImportError("no tiktoken here")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    # Undo the autouse fake so the real import path runs.
    monkeypatch.setattr(TiktokenEstimator, "_module", classmethod(_REAL_MODULE_LOADER))
    monkeypatch.setattr(builtins, "__import__", _refuse)
    with pytest.raises(ai.ConfigError, match="tokenizers"):
        TiktokenEstimator()


def test_the_real_module_has_the_surface_the_fake_stands_in_for() -> None:
    """Keeps the fake above honest without loading a vocabulary over the network.

    A fake more permissive than the thing it replaces is exactly how a dependency's API
    moves underneath a project unnoticed — this repository has three logged instances of
    it. Introspection only: nothing here calls `get_encoding`, which would download.
    """
    import inspect

    tiktoken = pytest.importorskip("tiktoken", reason="the tokenizers extra is optional")

    assert callable(tiktoken.get_encoding)
    assert callable(tiktoken.encoding_for_model)
    assert "disallowed_special" in inspect.signature(tiktoken.Encoding.encode).parameters
