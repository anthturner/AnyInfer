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
    Fails its first call with a retryable 503, then succeeds — which makes retry, fallback,
    and the attempt trail visible without needing a real outage.
``demo-fake:slow``
    Streams the same answer in smaller chunks, so incremental rendering is easy to watch.
``demo-fake:tools``
    Answers a plain request with a tool call and a request carrying a tool result with
    text — which is the whole shape of a tool loop: the model asks, the application runs
    the function, the result goes back, the model answers. Without it the loop could only
    be demonstrated against a real provider, and the demo would stop being offline-capable
    exactly where it got interesting.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2

from anyinfer.registry import ProviderRegistry
from anyinfer.testing import ScriptedFailure, ScriptedModel, ScriptedProvider
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

__all__ = [
    "DEMO_MODELS",
    "DEMO_PROVIDER_ID",
    "DEMO_TOOL_CALL",
    "TOOL_MODEL",
    "DemoFakeBackend",
    "register_demo_provider",
]

DEMO_PROVIDER_ID = "demo-fake"
"""Provider id the demo registers its offline endpoint under."""

DEMO_MODELS: tuple[str, ...] = ("reliable", "flaky", "slow", "tools")
"""Model ids the offline provider serves, each with a different personality."""

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
    """The demo's offline provider, rebuilt when the answer shape changes."""

    def __init__(self) -> None:
        self._provider = _build(json_mode=False)

    def set_json_mode(self, enabled: bool) -> None:
        """Serve schema-shaped answers, so the structured-output panel has valid input.

        A fake that always returned prose would make every structured request fail
        validation, which would demonstrate the repair loop and nothing else.

        Rebuilding unconditionally also rewinds the scripted failures, so the flaky model
        fails on its first call of *every* run rather than only the first of the session.
        """
        self._provider = _build(json_mode=enabled)

    def transport(self) -> httpx2.MockTransport:
        """A transport that dispatches to the scripted model the request names.

        The ``tools`` model needs one behaviour `ScriptedModel` cannot declare: a
        *different* answer depending on where the loop is. It is intercepted here with a
        stateless rule — a request already carrying a ``tool``-role message gets the final
        text, anything else gets the scripted call — and every other model falls through
        to the scripted provider unchanged. Stateless on purpose: the demonstration
        replays identically no matter how many loops have run.

        The scripted provider is looked up per request rather than captured here: the
        client keeps this transport for its whole lifetime, and `set_json_mode()` swaps
        the provider underneath it — a captured reference would silently pin the mode
        the client was built under.
        """

        def handle(request: httpx2.Request) -> httpx2.Response:
            body = _chat_body(request)
            if body is not None and body.get("model") == TOOL_MODEL:
                messages = body.get("messages") or []
                answered = any(
                    isinstance(m, dict) and m.get("role") == "tool" for m in messages
                )
                response = (
                    FakeResponse(text=_TOOL_ANSWER)
                    if answered
                    else FakeResponse(tool_calls=(DEMO_TOOL_CALL,), finish_reason="tool_calls")
                )
                # Rendered through the published fake server, exactly as the scripted kit
                # does internally, so the wire framing stays the library's own.
                server = FakeOpenAIServer([response], models=list(DEMO_MODELS))
                rendered = server.transport().handler(request)
                assert isinstance(rendered, httpx2.Response)
                return rendered
            fallthrough = self._provider.transport().handler(request)
            assert isinstance(fallthrough, httpx2.Response)
            return fallthrough

        return httpx2.MockTransport(handle)


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
    """Register the offline provider on ``registry``, replacing any prior registration.

    Args:
        registry: The registry the demo's client will use. A demo-owned registry rather
            than the process-wide one, so importing the demo never mutates library state
            for an embedding application.
    """
    _build(json_mode=False).register(registry)
