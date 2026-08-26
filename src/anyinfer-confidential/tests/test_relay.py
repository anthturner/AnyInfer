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


# ---- the render offload (Phase 0) --------------------------------------------------------
#
# `TemplateVault.render` is synchronous and sits inside a coroutine. The crypto path is
# sub-millisecond — measured, not assumed — so it belongs on the event loop, and a thread
# hop would cost about as much as the render. The one real hazard is a *network-backed*
# revocation checker: one synchronous round trip there stalls every in-flight request in
# the process. So the offload is scoped to exactly that case.


def _vault_with_checker(checker: object) -> TemplateVault:
    key = generate_key()
    private_key, public_key = generate_signing_keypair()
    blob = issue_license("acme", private_key=private_key, valid_days=30)
    return TemplateVault(
        key_ring=KeyRing({"k1": key}),
        license_public_key=public_key,
        license_blob=blob,
        revocation_checker=checker,  # type: ignore[arg-type]
    )


def test_a_vault_declares_whether_its_renders_can_block() -> None:
    """A capability, not a private attribute a caller has to reach into."""
    assert not _relay()[0]._vault.renders_may_block
    assert _vault_with_checker(lambda _: True).renders_may_block


async def test_a_vault_without_a_checker_never_enters_a_thread() -> None:
    """The crypto path is faster than the hop; offloading it would halve throughput."""
    import asyncio

    relay, _registry, _key = _relay()
    calls: list[object] = []

    async def _fail(*args: object, **kwargs: object) -> object:
        calls.append(args)
        raise AssertionError("the no-checker path must not offload")

    original = asyncio.to_thread
    asyncio.to_thread = _fail  # type: ignore[assignment]
    try:
        result = await relay.handle(
            tenant_id="acme",
            routing_key="summarize",
            slots={"audience": "engineers", "document": "notes"},
        )
    finally:
        asyncio.to_thread = original  # type: ignore[assignment]

    assert "engineers" in result.assembled_prompt
    assert not calls


async def test_a_slow_revocation_check_does_not_stall_unrelated_requests() -> None:
    """The whole reason the offload exists: one blocking check must not freeze the loop."""
    import asyncio
    import time as _time

    key = generate_key()
    private_key, public_key = generate_signing_keypair()
    blob = issue_license("acme", private_key=private_key, valid_days=30)

    def _slow_checker(_deployment_id: str) -> bool:
        _time.sleep(0.25)  # stands in for one synchronous HTTP round trip
        return True

    vault = TemplateVault(
        key_ring=KeyRing({"k1": key}),
        license_public_key=public_key,
        license_blob=blob,
        revocation_checker=_slow_checker,
    )
    template = seal_template("Hello {audience}", key=key, template_id="t", key_id="k1")
    registry = RelayRegistry()
    registry.register("acme", RelayRoute(routing_key="s", template=template, target="ollama:m"))
    relay = Relay(vault=vault, registry=registry)

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    try:
        await relay.handle(tenant_id="acme", routing_key="s", slots={"audience": "x"})
    finally:
        beat.cancel()

    assert ticks > 5, (
        f"the event loop ticked only {ticks} times during a 0.25s blocking check: "
        "the render was not offloaded"
    )


async def test_concurrent_slow_renders_make_progress_together() -> None:
    import asyncio
    import time as _time

    key = generate_key()
    private_key, public_key = generate_signing_keypair()
    blob = issue_license("acme", private_key=private_key, valid_days=30)
    vault = TemplateVault(
        key_ring=KeyRing({"k1": key}),
        license_public_key=public_key,
        license_blob=blob,
        revocation_checker=lambda _id: (_time.sleep(0.15), True)[1],
    )
    template = seal_template("Hello {audience}", key=key, template_id="t", key_id="k1")
    registry = RelayRegistry()
    registry.register("acme", RelayRoute(routing_key="s", template=template, target="ollama:m"))
    relay = Relay(vault=vault, registry=registry)

    started = asyncio.get_running_loop().time()
    await asyncio.gather(
        *(
            relay.handle(tenant_id="acme", routing_key="s", slots={"audience": str(i)})
            for i in range(4)
        )
    )
    elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < 0.5, (
        f"four 0.15s checks took {elapsed:.2f}s: they serialized instead of overlapping"
    )


def test_revocation_state_stays_consistent_under_concurrent_threads() -> None:
    """`_last_revocation_ok` is the vault's one piece of mutable state, now guarded."""
    import threading

    from anyinfer_confidential.errors import RevokedLicenseError

    key = generate_key()
    private_key, public_key = generate_signing_keypair()
    blob = issue_license("acme", private_key=private_key, valid_days=30)
    answers = iter([True, False] * 50)
    lock = threading.Lock()

    def _flapping(_deployment_id: str) -> bool:
        with lock:
            return next(answers)

    vault = TemplateVault(
        key_ring=KeyRing({"k1": key}),
        license_public_key=public_key,
        license_blob=blob,
        revocation_checker=_flapping,
    )
    template = seal_template("Hello {audience}", key=key, template_id="t", key_id="k1")

    outcomes: list[str] = []

    def _render() -> None:
        try:
            vault.render(template, audience="x")
            outcomes.append("ok")
        except RevokedLicenseError:
            outcomes.append("revoked")

    threads = [threading.Thread(target=_render) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Every call resolved to one of the two honest answers; none corrupted the cache into
    # a state that raises something else or hangs.
    assert len(outcomes) == 20
    assert set(outcomes) <= {"ok", "revoked"}
