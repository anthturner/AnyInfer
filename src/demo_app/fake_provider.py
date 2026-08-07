"""An offline demo provider, registered through the same descriptor contract as any other.

The point of routing this through `ProviderDescriptor` rather than
special-casing it in the UI is that the demo then exercises the *real* path: the settings
dialog renders it from its `ProviderSetupSpec`, the router resolves
``demo-fake:...`` targets through the normal registry, and the adapter is the stock
OpenAI-compatible one talking to an in-process `httpx2.MockTransport`.

Three model ids are served, and they behave differently on purpose so the demo has
something to show:

``demo-fake:reliable``
    Answers immediately, streams, reports usage.
``demo-fake:flaky``
    Fails its first call with a retryable 503, then succeeds — which makes retry, fallback,
    and the attempt trail visible without needing a real outage.
``demo-fake:slow``
    Streams the same answer in smaller chunks, so incremental rendering is easy to watch.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx2

from anyinfer.providers.openai_compat import OpenAICompatAdapter
from anyinfer.registry import (
    ProviderDescriptor,
    ProviderRegistry,
    ProviderSetupSpec,
    SetupField,
)
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced

__all__ = [
    "DEMO_MODELS",
    "DEMO_PROVIDER_ID",
    "DemoFakeBackend",
    "register_demo_provider",
]

DEMO_PROVIDER_ID = "demo-fake"
"""Provider id the demo registers its offline endpoint under."""

DEMO_MODELS: tuple[str, ...] = ("reliable", "flaky", "slow")
"""Model ids the offline provider serves, each with a different failure personality."""

_CANNED_ANSWER = (
    "This answer came from AnyInfer's in-process fake provider, so the demo runs with no "
    "credentials and no network. Everything around it is real: the router picked this "
    "target, the core measured the first-token mark, and the text you are reading arrived "
    "as a stream of TextDelta events."
)

_CANNED_JSON = json.dumps(
    {
        "summary": "AnyInfer normalizes inference across hosted and local providers.",
        "sentiment": "positive",
        "keywords": ["routing", "streaming", "structured output"],
        "confidence": 0.92,
    }
)


class DemoFakeBackend:
    """Routes the demo provider's traffic to per-model fake servers.

    One `FakeOpenAIServer` per model id keeps each model's
    scripted behaviour independent, so exercising the flaky model does not consume the
    reliable model's responses.
    """

    def __init__(self) -> None:
        self._servers: dict[str, FakeOpenAIServer] = {}
        self.set_json_mode(False)

    def set_json_mode(self, enabled: bool) -> None:
        """Serve schema-shaped answers, so the structured-output panel has valid input.

        A fake that always returns prose would make every structured request fail
        validation, which would demonstrate the repair loop and nothing else.

        Rebuilding unconditionally also rewinds each scripted server, so the flaky model
        fails on its first call of *every* run rather than only the first of the session.
        """
        text = _CANNED_JSON if enabled else _CANNED_ANSWER
        for model in DEMO_MODELS:
            self._servers[model] = FakeOpenAIServer(
                self._script_for(model, text),
                models=list(DEMO_MODELS),
                chunk_size=2 if model == "slow" else 4,
            )

    @staticmethod
    def _script_for(model: str, text: str) -> Sequence[FakeResponse]:
        """The scripted responses for one model's personality."""
        if model == "flaky":
            # First call fails retryably; the second succeeds. The router's retry budget
            # turns this into a visible RetryScheduled event followed by a normal answer.
            return [
                FakeResponse(status=503, error_message="fake upstream is warming up"),
                FakeResponse(text=text),
            ]
        return [FakeResponse(text=text)]

    def transport(self) -> httpx2.MockTransport:
        """A transport that dispatches to the fake server matching the requested model."""
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        model = self._model_for(request)
        server = self._servers.get(model) or self._servers["reliable"]
        # FakeOpenAIServer exposes its handler through the transport it builds; going
        # through that keeps this demo honest about using the published fake API.
        # `MockTransport.handler` is typed as sync-or-async; the fakes are always sync.
        response = server.transport().handler(request)
        assert isinstance(response, httpx2.Response)
        return response

    def _model_for(self, request: httpx2.Request) -> str:
        if not request.content:
            return "reliable"
        try:
            body: dict[str, Any] = json.loads(request.content)
        except (ValueError, TypeError):
            return "reliable"
        model = str(body.get("model") or "reliable")
        return model.split(":", 1)[-1]


def register_demo_provider(registry: ProviderRegistry) -> None:
    """Register the offline provider on ``registry``, replacing any prior registration.

    Args:
        registry: The registry the demo's client will use. A demo-owned registry rather
            than the process-wide one, so importing the demo never mutates library state
            for an embedding application.
    """
    descriptor = ProviderDescriptor(
        id=DEMO_PROVIDER_ID,
        display_name="Demo (offline fake)",
        aliases=("demo",),
        factory=OpenAICompatAdapter,
        locality="local",
        default_base_url="http://demo.invalid/v1",
        requires_base_url=False,
        setup=ProviderSetupSpec(
            fields=(
                SetupField(
                    key="base_url",
                    label="Base URL",
                    kind="endpoint",
                    required=False,
                    help_text=(
                        "Ignored — requests are served in-process by "
                        "anyinfer.testing.fakes, never over a socket."
                    ),
                ),
            ),
            model_selection="discover-or-manual",
        ),
        default_capabilities=ModelCapabilities(
            # A stated context window gives the auto-detect display something honest to
            # show offline; "default" provenance keeps it labelled as an assumption.
            context_window=Sourced(32_768, "default"),
            features=Sourced(
                Feature.STREAMING | Feature.TOOLS | Feature.SYSTEM_PROMPT | Feature.JSON_MODE,
                "default",
            ),
        ),
    )
    registry.register(descriptor, replace=True)
