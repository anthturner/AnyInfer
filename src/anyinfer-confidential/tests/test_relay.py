from __future__ import annotations

import anyinfer as ai
import pytest
from anyinfer.testing.fakes import FakeOllamaServer, FakeResponse

from anyinfer_confidential import (
    KeyRing,
    TemplateVault,
    generate_key,
    generate_signing_keypair,
    issue_license,
    seal_template,
)
from anyinfer_confidential.relay import Relay, RelayError, RelayRegistry, RelayRoute


def _relay() -> tuple[Relay, RelayRegistry, bytes]:
    key = generate_key()
    private_key, public_key = generate_signing_keypair()
    blob = issue_license("acme", private_key=private_key, valid_days=30)
    vault = TemplateVault(
        key_ring=KeyRing({"k1": key}), license_public_key=public_key, license_blob=blob
    )
    template = seal_template(
        "Summarize this for {audience}: {document}", key=key, template_id="summarize", key_id="k1"
    )
    registry = RelayRegistry()
    registry.register(
        "acme", RelayRoute(routing_key="summarize", template=template, target="ollama:qwen3:8b")
    )
    return Relay(vault=vault, registry=registry), registry, key


async def test_assemble_mode_returns_the_rendered_prompt_without_dispatching() -> None:
    relay, _, _ = _relay()
    result = await relay.handle(
        tenant_id="acme",
        routing_key="summarize",
        slots={"audience": "engineers", "document": "the release notes"},
        mode="assemble",
    )
    assert result.assembled_prompt == "Summarize this for engineers: the release notes"
    assert result.generation_text is None
    assert result.target == "ollama:qwen3:8b"


async def test_forward_mode_dispatches_and_returns_generation_text() -> None:
    relay, _, _ = _relay()
    server = FakeOllamaServer(FakeResponse(text="a short summary"))
    settings = ai.ProviderSettings.of(
        "ollama", base_url="http://127.0.0.1:11434", transport=server.transport()
    )
    result = await relay.handle(
        tenant_id="acme",
        routing_key="summarize",
        slots={"audience": "engineers", "document": "the release notes"},
        mode="forward",
        provider_settings=settings,
    )
    assert result.generation_text == "a short summary"


async def test_forward_mode_without_credentials_is_refused() -> None:
    relay, _, _ = _relay()
    with pytest.raises(RelayError):
        await relay.handle(
            tenant_id="acme", routing_key="summarize", slots={"audience": "x", "document": "y"},
            mode="forward",
        )


async def test_unknown_routing_key_is_refused() -> None:
    relay, _, _ = _relay()
    with pytest.raises(RelayError):
        await relay.handle(tenant_id="acme", routing_key="nonexistent", slots={})


async def test_a_route_registered_for_one_tenant_is_invisible_to_another() -> None:
    """Multi-tenant isolation is structural: tenant B can never resolve tenant A's route."""
    relay, _, _ = _relay()
    with pytest.raises(RelayError):
        await relay.handle(
            tenant_id="totally-different-vendor",
            routing_key="summarize",
            slots={"audience": "x", "document": "y"},
        )


async def test_the_same_routing_key_can_be_registered_independently_per_tenant() -> None:
    key = generate_key()
    private_key, public_key = generate_signing_keypair()
    blob = issue_license("dep", private_key=private_key, valid_days=30)
    vault = TemplateVault(
        key_ring=KeyRing({"k1": key}), license_public_key=public_key, license_blob=blob
    )
    registry = RelayRegistry()
    registry.register(
        "tenant-a",
        RelayRoute(
            routing_key="greet",
            template=seal_template("Hello from A, {x}", key=key, template_id="a", key_id="k1"),
            target="ollama:x",
        ),
    )
    registry.register(
        "tenant-b",
        RelayRoute(
            routing_key="greet",
            template=seal_template("Hello from B, {x}", key=key, template_id="b", key_id="k1"),
            target="ollama:x",
        ),
    )
    relay = Relay(vault=vault, registry=registry)
    a = await relay.handle(tenant_id="tenant-a", routing_key="greet", slots={"x": "!"})
    b = await relay.handle(tenant_id="tenant-b", routing_key="greet", slots={"x": "!"})
    assert a.assembled_prompt == "Hello from A, !"
    assert b.assembled_prompt == "Hello from B, !"
