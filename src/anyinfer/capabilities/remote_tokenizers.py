"""Exact token counts from a service that owns the tokenizer.

`tokenizers` covers the models whose vocabulary is published. This module covers the two
that are not: Anthropic counts through `POST /v1/messages/count_tokens`, and a supervised
llama-server counts through `POST /tokenize`. Both are exact — they run the tokenizer that
will actually process the request — and neither can be replicated locally.

**Why these are not simply `TokenEstimator` implementations.** `TokenEstimator.estimate`
is synchronous, and a blocking HTTP call inside an async client stalls the event loop for
every concurrent request. Making the protocol async would change every implementation and
every call site for the benefit of two of them, so the counting stays synchronous and the
*fetching* moves ahead of it: an estimator here implements `PrewarmsCounts`, the client
awaits one round trip before it starts sizing, and `estimate` then reads a cache. A text
that was not prewarmed falls back to the base estimator rather than blocking — a slightly
worse number, never a stalled loop.

The cache is keyed by a digest of the text and bounded, so a long conversation re-counted
turn after turn pays for each turn's new content once rather than every time.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, ClassVar, Protocol, runtime_checkable

import httpx2

from ..types.capabilities import TokenizerKind
from .estimate import HeuristicTokenEstimator, TokenEstimate, TokenEstimator

__all__ = [
    "DEFAULT_CACHE_ENTRIES",
    "AnthropicCountTokensEstimator",
    "LlamaServerTokenizeEstimator",
    "PrewarmsCounts",
    "prewarm",
]

DEFAULT_CACHE_ENTRIES = 4_096
"""Counted texts an estimator remembers.

Sized for a long conversation re-counted on every turn: each turn adds a message or two,
and the ones before it are already counted. Bounded because a process that runs for weeks
should not accumulate one entry per message it ever saw.
"""


@runtime_checkable
class PrewarmsCounts(Protocol):
    """An estimator whose exact counts come from a service rather than from local code.

    The optional async half of `TokenEstimator`. A client that
    knows it is about to size a request awaits `prewarm` once, and the synchronous
    `estimate` calls that follow read what it fetched. An estimator that does not
    implement this is used exactly as before — this is an extension, not a requirement.
    """

    async def prewarm(self, texts: Sequence[str]) -> None:
        """Fetch exact counts for these texts, ignoring ones already known.

        Never raises for a service problem: an estimator that cannot reach its counting
        endpoint degrades to its base estimator, because a request that could have been
        sized approximately should not fail outright for want of an exact number.
        """
        ...


async def prewarm(estimator: TokenEstimator, texts: Iterable[str]) -> None:
    """Warm ``estimator`` for these texts if it counts remotely; otherwise do nothing.

    The call site for every path that is about to size a request. Written as a function
    rather than checked inline so the "estimators that do not prewarm are untouched" rule
    lives in one place.
    """
    if isinstance(estimator, PrewarmsCounts):
        await estimator.prewarm([text for text in texts if text])


class _RemoteCountingEstimator:
    """Shared machinery: a bounded cache, and a fallback that is never worse than before.

    Args:
        base: What to count a text with when its exact count is not cached. Defaults to
            the byte heuristic, the same thing the caller would have had otherwise.
        max_entries: Counted texts to remember.
    """

    def __init__(
        self,
        *,
        base: TokenEstimator | None = None,
        max_entries: int = DEFAULT_CACHE_ENTRIES,
    ) -> None:
        self._base = base or HeuristicTokenEstimator()
        self._max_entries = max(1, max_entries)
        self._counts: OrderedDict[str, int] = OrderedDict()

    def estimate(self, text: str) -> TokenEstimate:
        """Return the exact count when it was prewarmed, and the base estimate when not.

        An exact count sets ``floor == tokens``, which is the whole point: the
        pre-dispatch gate refuses on the floor, and a floor that is the real number lets
        it refuse before a round trip instead of after one.
        """
        exact = self._counts.get(_digest(text))
        if exact is None:
            return self._base.estimate(text)
        return TokenEstimate(exact, exact)

    def _remember(self, text: str, tokens: int) -> None:
        key = _digest(text)
        self._counts[key] = tokens
        self._counts.move_to_end(key)
        while len(self._counts) > self._max_entries:
            self._counts.popitem(last=False)

    def _unknown(self, texts: Sequence[str]) -> list[str]:
        return [text for text in texts if _digest(text) not in self._counts]


class AnthropicCountTokensEstimator(_RemoteCountingEstimator):
    """Exact counts from Anthropic's own ``POST /v1/messages/count_tokens``.

    Anthropic does not publish its tokenizer, so this endpoint is the only exact count
    available for Claude models — `TiktokenEstimator` falls back to an OpenAI encoding
    for them, which is a better guess than counting bytes but is still a guess.

    The endpoint counts a whole *message list*, not a string, so each text is counted as a
    single user turn. That includes Anthropic's own per-message framing, which makes the
    count marginally high for a text that will travel as part of a longer conversation —
    high is the safe direction for a planning figure, and the framing is exactly what
    `estimate_request` would otherwise add by heuristic.

    Args:
        api_key: The credential to count with. Counting is free but authenticated.
        model: The model whose tokenizer to count with. Anthropic requires one, and the
            count is model-specific.
        base_url: Override the API root, for a proxy or a test transport.
        base: Estimator for texts that were not prewarmed.
        transport: An HTTP transport to use instead of the default.
        max_entries: Counted texts to remember.
    """

    tokenizer_kind: ClassVar[TokenizerKind] = "anthropic_count_tokens"
    """Matched against a provider's declared `TokenCalibration.tokenizer` before these
    counts are trusted as exact."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        base_url: str = "https://api.anthropic.com",
        base: TokenEstimator | None = None,
        transport: Any = None,
        max_entries: int = DEFAULT_CACHE_ENTRIES,
    ) -> None:
        super().__init__(base=base, max_entries=max_entries)
        self._model = model
        self._client = httpx2.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            transport=transport,
        )

    async def prewarm(self, texts: Sequence[str]) -> None:
        """Count each unknown text, tolerating a service that will not answer."""
        for text in self._unknown(texts):
            counted = await self._count(text)
            if counted is not None:
                self._remember(text, counted)

    async def _count(self, text: str) -> int | None:
        try:
            response = await self._client.post(
                "/v1/messages/count_tokens",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": text}],
                },
            )
        except httpx2.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        body = response.json()
        tokens = body.get("input_tokens") if isinstance(body, Mapping) else None
        if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0:
            return tokens
        return None

    async def aclose(self) -> None:
        """Close the counting transport."""
        await self._client.aclose()


class LlamaServerTokenizeEstimator(_RemoteCountingEstimator):
    """Exact counts from a running llama-server's ``POST /tokenize``.

    The tokenizer here is the one loaded with the weights, so the count is exact for
    whatever GGUF the server is serving — including quantized community models whose
    vocabulary is not published anywhere a local tokenizer could find it.

    Unlike the hosted case this is a loopback call, but the reasoning is the same: the
    estimator protocol is synchronous and the event loop is shared, so the fetch happens
    ahead of the counting rather than inside it.

    Args:
        base_url: Where the server is listening.
        api_key: A credential, for a server started with ``--api-key`` or behind a proxy.
        base: Estimator for texts that were not prewarmed.
        transport: An HTTP transport to use instead of the default.
        max_entries: Counted texts to remember.
    """

    tokenizer_kind: ClassVar[TokenizerKind] = "llama_server_tokenize"
    """Matched against a provider's declared `TokenCalibration.tokenizer` before these
    counts are trusted as exact."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8080",
        api_key: str | None = None,
        base: TokenEstimator | None = None,
        transport: Any = None,
        max_entries: int = DEFAULT_CACHE_ENTRIES,
    ) -> None:
        super().__init__(base=base, max_entries=max_entries)
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        self._client = httpx2.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, transport=transport
        )

    async def prewarm(self, texts: Sequence[str]) -> None:
        """Tokenize each unknown text, tolerating a server that is not up."""
        for text in self._unknown(texts):
            counted = await self._count(text)
            if counted is not None:
                self._remember(text, counted)

    async def _count(self, text: str) -> int | None:
        try:
            response = await self._client.post("/tokenize", json={"content": text})
        except httpx2.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        body = response.json()
        tokens = body.get("tokens") if isinstance(body, Mapping) else None
        # The server answers with the token ids themselves; their count is the answer.
        return len(tokens) if isinstance(tokens, list) else None

    async def aclose(self) -> None:
        """Close the counting transport."""
        await self._client.aclose()


def _digest(text: str) -> str:
    """Key a cache entry by content rather than by identity.

    A conversation is re-counted turn after turn from freshly built message objects, so
    identity would miss every repeat. Not a security boundary — it keys a local cache —
    but sha256 costs nothing at these sizes and avoids collisions being a real question.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
