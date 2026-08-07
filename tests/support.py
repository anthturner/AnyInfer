"""Test helpers shared across modules."""

from __future__ import annotations

from collections.abc import Sequence

import anyinfer as ai
from anyinfer.testing.fakes import FakeOpenAIServer


def make_client(server: FakeOpenAIServer, **client_kwargs: object) -> ai.AsyncClient:
    """Build an async client wired to a fake server."""
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ],
        **client_kwargs,  # type: ignore[arg-type]
    )


def make_sync_client(server: FakeOpenAIServer, **client_kwargs: object) -> ai.Client:
    """Build a sync client wired to a fake server."""
    return ai.Client(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ],
        **client_kwargs,  # type: ignore[arg-type]
    )


def make_multi_client(
    servers: Sequence[tuple[str, FakeOpenAIServer]],
    **client_kwargs: object,
) -> ai.AsyncClient:
    """Build a client with several providers, each backed by its own fake server.

    Used for fallback tests: the providers are distinct registrations of the same dialect,
    which is exactly how a fallback chain across two OpenAI-compatible endpoints behaves.
    """
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                provider_id,
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
            for provider_id, server in servers
        ],
        **client_kwargs,  # type: ignore[arg-type]
    )
