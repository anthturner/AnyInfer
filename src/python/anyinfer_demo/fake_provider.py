"""An offline demo provider, declared with the library's own scripted-provider kit.

The point of routing this through `ProviderDescriptor` rather than special-casing it in
the UI is that the demo exercises the *real* path: the settings dialog renders it from its
`ProviderSetupSpec`, the router resolves ``demo-fake:...`` targets through the normal
registry, and the adapter is the stock OpenAI-compatible one talking to an in-process
transport.

Three model ids are served, and they behave differently on purpose so the demo has
something to show:

``demo-fake:reliable``
    Answers immediately, streams, reports usage.
``demo-fake:flaky``
    Fails its first call with a retryable 503, then succeeds, which makes retry, fallback,
    and the attempt trail visible without needing a real outage.
``demo-fake:slow``
    Streams the same answer in smaller chunks, so incremental rendering is easy to watch.
``demo-fake:tools``
    Answers a plain request with a tool call and a request carrying a tool result with
    text, which is the whole shape of a tool loop: the model asks, the application runs
    the function, the result goes back, the model answers. Without it the loop could only
    be demonstrated against a real provider, and the demo would stop being offline-capable
    exactly where it got interesting.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2

from anyinfer.registry import ProviderRegistry
from anyinfer.testing import (
    FakeEmbeddingRerankProvider,
    ScriptedFailure,
    ScriptedModel,
    ScriptedProvider,
)
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

__all__ = [
    "DEMO_EMBEDDING_MODEL",
    "DEMO_EMBEDDING_PROVIDER_ID",
    "DEMO_MODELS",
    "DEMO_PROVIDER_ID",
    "DEMO_RERANK_MODEL",
    "DEMO_TOOL_CALL",
    "TOOL_MODEL",
    "DemoFakeBackend",
    "register_demo_provider",
]

DEMO_PROVIDER_ID = "demo-fake"
"""Provider id the demo registers its offline endpoint under."""

DEMO_MODELS: tuple[str, ...] = ("reliable", "flaky", "slow", "tools")
"""Model ids the offline provider serves, each with a different personality."""

DEMO_EMBEDDING_PROVIDER_ID = "demo-fake-embed"
"""Provider id the demo registers its offline embedding/rerank endpoint under.

Kept separate from `DEMO_PROVIDER_ID` because the two operations need genuinely different
in-process fakes (`FakeEmbeddingRerankProvider` implements `EmbedsText`/`ReranksText`
directly rather than an HTTP dialect) — mirroring how a real deployment might point
embeddings at a different service than chat."""

DEMO_EMBEDDING_MODEL = "embed-small"
"""Model id the offline embedding fake serves."""

DEMO_RERANK_MODEL = "rerank-small"
"""Model id the offline rerank fake serves."""

TOOL_MODEL = "tools"
"""The model id whose scripted answer to a plain request is a tool call."""

DEMO_TOOL_CALL = ("call_demo_1", "current_time", '{"timezone": "UTC"}')
"""The scripted call the tool model makes: id, function name, JSON arguments.

Named here rather than buried in the transport because the tools panel implements the
*same* function, and the two agreeing is what makes the round trip work.
"""

_CANNED_ANSWER = (
    "This answer came from AnyInfer's in-process fake provider, so the demo runs with no "
    "credentials and no network. Everything around it is real: the router picked this "
    "target, the core measured the first-token mark, and the text you are reading arrived "
    "as a stream of TextDelta events."
)

_TOOL_ANSWER = (
    "I called current_time(timezone='UTC') and used what it returned. The loop you just "
    "watched — tool call out, tool result back, final answer — was run by "
    "Client.run_tools(); the demo only supplied the function."
)

_CANNED_STRUCTURED = {
    "summary": "AnyInfer normalizes inference across hosted and local providers.",
    "sentiment": "positive",
    "keywords": ["routing", "streaming", "structured output"],
    "confidence": 0.92,
}


class DemoFakeBackend:
    """The demo's offline provider.

    Two providers are kept — one answering prose, one answering the canned structured
    object, and *each request* is routed to the right one by reading its own body. A
    single mutable "json mode" flag would be a global for something that is per request,
    and with several conversations streaming at once the last caller to set it would
    decide what the others got back.
    """

    def __init__(self) -> None:
        self._prose = _build(json_mode=False)
        self._structured = _build(json_mode=True)

    def set_json_mode(self, enabled: bool) -> None:
        """Rewind the scripted failure scripts.

        Kept as the demo's "start a fresh run" hook — the flaky model fails on the first
        call of *every* run rather than only the first of the session. The ``enabled``
        argument no longer selects an answer shape: that is decided per request from the
        wire body, so a structured turn in one tab cannot reshape a plain turn in
        another.
        """
        self._prose.reset()
        self._structured.reset()

    def transport(self) -> httpx2.MockTransport:
        """A transport that answers each request in the shape that request asked for.

        Two behaviours live here rather than in `ScriptedModel`, both because they depend
        on the request:

        - The ``tools`` model answers a plain request with a tool call and a request
          already carrying a ``tool``-role message with text — the two halves of a tool
          loop.
        - Any request carrying a ``response_format`` is served the structured provider;
          everything else gets prose. That is the same decision the caller's schema
          makes, read back off the wire.
        """

        def handle(request: httpx2.Request) -> httpx2.Response:
            body = _chat_body(request)
            if body is not None and body.get("model") == TOOL_MODEL:
                messages = body.get("messages") or []
                answered = any(isinstance(m, dict) and m.get("role") == "tool" for m in messages)
                response = (
                    FakeResponse(text=_TOOL_ANSWER)
                    if answered
                    else FakeResponse(tool_calls=(DEMO_TOOL_CALL,), finish_reason="tool_calls")
                )
                # Rendered through the published fake server, exactly as the scripted kit
                # does internally, so the wire framing stays the library's own.
                server = FakeOpenAIServer([response], models=list(DEMO_MODELS))
                rendered = server.transport().handler(request)
                if not isinstance(rendered, httpx2.Response):
                    raise RuntimeError("the synchronous fake returned an awaitable response")
                return rendered
            provider = self._structured if _wants_structured(body) else self._prose
            fallthrough = provider.transport().handler(request)
            if not isinstance(fallthrough, httpx2.Response):
                raise RuntimeError("the scripted fake returned an awaitable response")
            return fallthrough

        return httpx2.MockTransport(handle)


def _wants_structured(body: dict[str, Any] | None) -> bool:
    """Whether this request asked for a schema-shaped answer.

    ``response_format`` is how every structured-output mechanism the OpenAI dialect
    carries announces itself — ``json_schema`` and plain ``json_object`` alike, so one
    check covers both. A prompt-injected schema (the last-resort mechanism) sends no
    such field and legitimately gets prose, which is exactly the case the repair loop
    exists for.
    """
    return body is not None and body.get("response_format") is not None


def _chat_body(request: httpx2.Request) -> dict[str, Any] | None:
    """The parsed chat-completion body, or ``None`` for anything else (e.g. ``/models``)."""
    if not request.url.path.endswith("/chat/completions"):
        return None
    try:
        parsed = json.loads(request.content.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _build(*, json_mode: bool) -> ScriptedProvider:
    """The three personalities, as one declarative table."""
    answer = None if json_mode else _CANNED_ANSWER
    structured = _CANNED_STRUCTURED if json_mode else None

    def model(model_id: str, **overrides: object) -> ScriptedModel:
        return ScriptedModel(
            model_id,
            text=answer or "",
            structured=structured,
            **overrides,  # type: ignore[arg-type]
        )

    return ScriptedProvider(
        DEMO_PROVIDER_ID,
        [
            model("reliable"),
            # First call fails retryably; the second succeeds. The router's retry budget
            # turns this into a visible RetryScheduled event followed by a normal answer.
            model(
                "flaky",
                failures=(ScriptedFailure(status=503, message="fake upstream is warming up"),),
            ),
            model("slow", chunk_size=2),
            # Declared so discovery lists it and capabilities resolve; its two-phase
            # behaviour lives in `DemoFakeBackend.transport()`, which intercepts it.
            ScriptedModel(TOOL_MODEL, text=_TOOL_ANSWER),
        ],
        aliases=("demo",),
        display_name="Demo (offline fake)",
        base_url="http://demo.invalid/v1",
    )


def register_demo_provider(registry: ProviderRegistry) -> None:
    """Register the offline providers on ``registry``, replacing any prior registration.

    Args:
        registry: The registry the demo's client will use. A demo-owned registry rather
            than the process-wide one, so importing the demo never mutates library state
            for an embedding application.
    """
    _build(json_mode=False).register(registry)
    FakeEmbeddingRerankProvider(
        DEMO_EMBEDDING_PROVIDER_ID,
        embedding_dimensions={DEMO_EMBEDDING_MODEL: 32},
        rerank_models=[DEMO_RERANK_MODEL],
    ).register(registry)
