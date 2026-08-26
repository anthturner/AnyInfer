"""Exact token counts from the two services that own tokenizers nobody else can run.

Anthropic does not publish its vocabulary and a quantized GGUF's is not published
anywhere, so `POST /v1/messages/count_tokens` and llama-server's `POST /tokenize` are the
only exact counts available for those targets. Both need a round trip, which the
synchronous `TokenEstimator` protocol has no room for — so the fetch moves ahead of the
counting, and these tests pin that it stays there: a count that was not prewarmed falls
back rather than blocking, and a service that is down degrades rather than failing a
request that could have been sized approximately.
"""

from __future__ import annotations

import httpx2
import pytest

from anyinfer.capabilities.estimate import HeuristicTokenEstimator, TokenEstimate
from anyinfer.capabilities.remote_tokenizers import (
    AnthropicCountTokensEstimator,
    LlamaServerTokenizeEstimator,
    PrewarmsCounts,
    prewarm,
)
from anyinfer.capabilities.tokenizers import counts_exactly, estimator_for
from anyinfer.types.capabilities import TokenCalibration


class _Recorder:
    """A transport that answers counting requests and records what it was asked."""

    def __init__(self, *, handler) -> None:
        self.requests: list[dict] = []
        self._handler = handler

    def transport(self) -> httpx2.MockTransport:
        def handle(request: httpx2.Request) -> httpx2.Response:
            import json

            self.requests.append(
                {"path": request.url.path, "body": json.loads(request.content or b"{}")}
            )
            return self._handler(request)

        return httpx2.MockTransport(handle)


_OPEN: list[object] = []
"""Estimators built by this module's helpers, awaiting close.

An estimator owns an HTTP client, and one that is dropped without closing surfaces later
as an unraisable exception during whatever test happens to be running when the garbage
collector reaches it — a failure attributed to innocent code, appearing only on some
interpreters and some shardings. Closing them centrally is what keeps that from being a
thing each new test has to remember.
"""


@pytest.fixture(autouse=True)
async def _close_estimators():
    """Close every estimator this module's helpers built, however the test ended."""
    yield
    while _OPEN:
        await _OPEN.pop().aclose()  # type: ignore[attr-defined]


def _track(estimator):
    _OPEN.append(estimator)
    return estimator


def _anthropic(
    tokens: int = 42, *, status: int = 200
) -> tuple[_Recorder, AnthropicCountTokensEstimator]:
    recorder = _Recorder(
        handler=lambda _: httpx2.Response(status, json={"input_tokens": tokens})
    )
    return recorder, _track(
        AnthropicCountTokensEstimator(api_key="sk-test", transport=recorder.transport())
    )


def _llama(count: int = 9, *, status: int = 200) -> tuple[_Recorder, LlamaServerTokenizeEstimator]:
    recorder = _Recorder(
        handler=lambda _: httpx2.Response(status, json={"tokens": list(range(count))})
    )
    return recorder, _track(LlamaServerTokenizeEstimator(transport=recorder.transport()))


# ---- the counts themselves ------------------------------------------------------------------


async def test_a_prewarmed_count_is_exact_which_is_the_whole_point() -> None:
    """An exact count sets floor == tokens, which is what lets the gate refuse early."""
    _, estimator = _anthropic(tokens=42)
    await estimator.prewarm(["hello world"])
    assert estimator.estimate("hello world") == TokenEstimate(42, 42)


async def test_llama_server_counts_the_ids_it_returns() -> None:
    """The endpoint answers with the token ids; their count is the answer."""
    recorder, estimator = _llama(count=9)
    await estimator.prewarm(["hello world"])
    assert estimator.estimate("hello world") == TokenEstimate(9, 9)
    assert recorder.requests[0]["path"] == "/tokenize"
    assert recorder.requests[0]["body"] == {"content": "hello world"}


async def test_anthropic_counts_through_its_own_endpoint_with_a_model() -> None:
    """The count is model-specific, and the endpoint requires one."""
    recorder, estimator = _anthropic()
    await estimator.prewarm(["hi"])
    assert recorder.requests[0]["path"] == "/v1/messages/count_tokens"
    assert recorder.requests[0]["body"]["model"] == "claude-sonnet-4-5"
    assert recorder.requests[0]["body"]["messages"] == [{"role": "user", "content": "hi"}]


# ---- never blocking, never failing ----------------------------------------------------------


async def test_an_uncounted_text_falls_back_rather_than_blocking() -> None:
    """`estimate` is synchronous and shares the event loop; it may not do a round trip."""
    recorder, estimator = _anthropic()
    await estimator.prewarm(["counted"])

    fallback = HeuristicTokenEstimator().estimate("never counted")
    assert estimator.estimate("never counted") == fallback
    # One request, for the one text that was prewarmed. Nothing was fetched under the
    # synchronous call.
    assert len(recorder.requests) == 1


async def test_a_service_that_refuses_degrades_instead_of_failing_the_request() -> None:
    """A request that could have been sized approximately should not fail outright."""
    _, estimator = _anthropic(status=500)
    await estimator.prewarm(["hello"])
    assert estimator.estimate("hello") == HeuristicTokenEstimator().estimate("hello")


async def test_a_service_that_is_not_up_degrades_too() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("nothing listening", request=request)

    estimator = _track(LlamaServerTokenizeEstimator(transport=httpx2.MockTransport(refuse)))
    await estimator.prewarm(["hello"])
    assert estimator.estimate("hello") == HeuristicTokenEstimator().estimate("hello")


async def test_a_malformed_answer_is_not_trusted_as_a_count() -> None:
    recorder = _Recorder(handler=lambda _: httpx2.Response(200, json={"input_tokens": "many"}))
    estimator = _track(
        AnthropicCountTokensEstimator(api_key="k", transport=recorder.transport())
    )
    await estimator.prewarm(["hello"])
    assert estimator.estimate("hello") == HeuristicTokenEstimator().estimate("hello")


# ---- the cache ------------------------------------------------------------------------------


async def test_a_text_is_counted_once_however_often_it_is_re_estimated() -> None:
    """A conversation is re-sized every turn; each turn's new content is counted once."""
    recorder, estimator = _anthropic()
    await estimator.prewarm(["turn one"])
    await estimator.prewarm(["turn one", "turn two"])
    await estimator.prewarm(["turn one", "turn two", "turn three"])

    assert [request["body"]["messages"][0]["content"] for request in recorder.requests] == [
        "turn one",
        "turn two",
        "turn three",
    ]


async def test_the_cache_is_bounded_so_a_long_lived_process_does_not_grow_forever() -> None:
    _, estimator = _anthropic()
    estimator._max_entries = 2
    await estimator.prewarm(["a", "b", "c"])
    # The oldest was evicted, so it re-counts rather than remembering everything ever seen.
    assert estimator.estimate("a") == HeuristicTokenEstimator().estimate("a")
    assert estimator.estimate("c").floor == 42


async def test_counting_is_keyed_by_content_not_by_object_identity() -> None:
    """Messages are rebuilt every turn; identity would miss every repeat."""
    recorder, estimator = _anthropic()
    await estimator.prewarm(["same text"])
    await estimator.prewarm(["".join(["same ", "text"])])
    assert len(recorder.requests) == 1


# ---- the seam the client uses ---------------------------------------------------------------


async def test_prewarm_leaves_a_local_estimator_alone() -> None:
    """This is an extension, not a requirement; the heuristic is untouched by it."""
    estimator = HeuristicTokenEstimator()
    assert not isinstance(estimator, PrewarmsCounts)
    await prewarm(estimator, ["anything"])  # does nothing, raises nothing


async def test_prewarm_skips_empty_texts() -> None:
    recorder, estimator = _anthropic()
    await prewarm(estimator, ["", "real", ""])
    assert len(recorder.requests) == 1


# ---- exactness is a claim the provenance rules govern (E.6.2) --------------------------------


async def test_an_exact_floor_requires_the_provider_to_declare_that_tokenizer() -> None:
    """A count is exact only if it counts the tokenizer the provider actually runs."""
    _, estimator = _anthropic()
    anthropic_says = TokenCalibration(
        tokenizer="anthropic_count_tokens", tokenizer_provenance="catalog"
    )
    openai_says = TokenCalibration(tokenizer="tiktoken", tokenizer_provenance="catalog")

    assert counts_exactly(estimator, anthropic_says)
    assert not counts_exactly(estimator, openai_says)


async def test_a_guessed_tokenizer_claim_does_not_make_a_floor_exact() -> None:
    """The gate *refuses* on the floor, so a default-provenance guess may not license one."""
    _, estimator = _anthropic()
    guessed = TokenCalibration(
        tokenizer="anthropic_count_tokens", tokenizer_provenance="default"
    )
    assert not counts_exactly(estimator, guessed)


async def test_a_provider_declaring_no_tokenizer_claims_no_exactness() -> None:
    _, estimator = _anthropic()
    assert not counts_exactly(estimator, TokenCalibration())
    assert not counts_exactly(HeuristicTokenEstimator(), TokenCalibration())


def test_the_heuristic_is_never_exact_even_where_a_tokenizer_is_declared() -> None:
    assert not counts_exactly(
        HeuristicTokenEstimator(),
        TokenCalibration(tokenizer="tiktoken", tokenizer_provenance="catalog"),
    )


async def test_selection_does_not_specialize_an_estimator_for_the_wrong_provider() -> None:
    """Asked to count Claude with a tiktoken estimator, it stays as it is.

    Specializing would produce an OpenAI encoding presented as a Claude count; leaving it
    keeps a near-miss number, and `counts_exactly` reports the truth about it either way.
    """
    _, estimator = _anthropic()
    same = estimator_for(
        estimator,
        "openai",
        "gpt-5",
        calibration=TokenCalibration(tokenizer="tiktoken", tokenizer_provenance="catalog"),
    )
    assert same is estimator


@pytest.mark.parametrize(
    ("provider_id", "expected"),
    [
        ("openai", "tiktoken"),
        ("anthropic", "anthropic_count_tokens"),
        ("llama-cpp", "llama_server_tokenize"),
    ],
)
def test_each_provider_declares_where_its_exact_count_comes_from(
    provider_id: str, expected: str
) -> None:
    from anyinfer.registry import default_registry

    calibration = default_registry.get(provider_id).token_calibration
    assert calibration.tokenizer == expected
    assert calibration.tokenizer_provenance == "catalog"


def test_a_provider_whose_tokenizer_is_neither_published_nor_exposed_declares_nothing() -> None:
    """Gemini's vocabulary is not published and it exposes no counting endpoint."""
    from anyinfer.registry import default_registry

    assert default_registry.get("gemini").token_calibration.tokenizer is None
