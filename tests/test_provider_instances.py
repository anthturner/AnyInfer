"""Multiple instances of one provider engine, addressed by alias.

Two Azure tenants, a local and a remote Ollama, two OpenAI-compatible endpoints: the same
adapter configured more than once, each instance with its own credentials, endpoint, and
identity in a target string. The instance id — the alias, when there is one — is what
`AdapterPool` keys adapters by and what ``alias:model`` resolves to.
"""

from __future__ import annotations

import pytest

from anyinfer import ProviderSettings
from anyinfer._client.providers import AdapterPool
from anyinfer.errors import ConfigError
from anyinfer.providers.base import ProviderAdapter, ProviderConfig
from anyinfer.registry import ProviderDescriptor, ProviderRegistry, ProviderSetupSpec, SetupField
from anyinfer.types.capabilities import Health


class _RecordingAdapter(ProviderAdapter):
    """A stand-in adapter that remembers the configuration it was built with."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    async def list_models(self):
        return ()

    async def health(self) -> Health:
        return Health(ok=True)

    async def generate(self, request):  # pragma: no cover - never generated in these tests
        raise NotImplementedError
        yield

    async def aclose(self) -> None:
        return None


def _registry() -> ProviderRegistry:
    """A registry holding one engine that requires a base URL, and nothing else."""
    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id="fake-engine",
            display_name="Fake Engine",
            factory=_RecordingAdapter,
            requires_base_url=True,
            setup=ProviderSetupSpec(
                fields=(SetupField("base_url", "Endpoint", "endpoint", required=True),)
            ),
        )
    )
    return registry


class TestProviderSettings:
    def test_instance_id_defaults_to_the_provider_id(self):
        settings = ProviderSettings.of("openai")
        assert settings.instance_id == "openai"
        assert settings.alias is None

    def test_an_alias_becomes_the_instance_id(self):
        settings = ProviderSettings.of("azure-foundry", alias="work-azure")
        assert settings.instance_id == "work-azure"
        assert settings.provider_id == "azure-foundry"

    def test_the_alias_is_normalized_like_a_provider_id(self):
        settings = ProviderSettings.of("azure-foundry", alias="  Work_Azure  ")
        assert settings.instance_id == "work-azure"


class TestAdapterPool:
    async def test_two_instances_of_one_engine_get_separate_adapters(self):
        registry = _registry()
        pool = AdapterPool(
            [
                ProviderSettings.of("fake-engine", alias="tenant-a", base_url="https://a.example"),
                ProviderSettings.of("fake-engine", alias="tenant-b", base_url="https://b.example"),
            ],
            registry=registry,
        )

        a = await pool.get("tenant-a")
        b = await pool.get("tenant-b")

        assert a is not b
        assert a.config.base_url == "https://a.example"
        assert b.config.base_url == "https://b.example"
        # Each adapter is told the identity it was configured under.
        assert a.config.provider_id == "tenant-a"
        assert b.config.provider_id == "tenant-b"

    async def test_an_instance_is_cached_like_any_adapter(self):
        registry = _registry()
        pool = AdapterPool(
            [ProviderSettings.of("fake-engine", alias="one", base_url="https://x.example")],
            registry=registry,
        )
        assert await pool.get("one") is await pool.get("one")

    def test_configured_ids_are_instance_ids_in_order(self):
        registry = _registry()
        pool = AdapterPool(
            [
                ProviderSettings.of("fake-engine", alias="second", base_url="https://b"),
                ProviderSettings.of("fake-engine", alias="first", base_url="https://a"),
            ],
            registry=registry,
        )
        assert pool.configured_ids == ("second", "first")

    def test_an_alias_becomes_resolvable_as_a_target_provider(self):
        registry = _registry()
        AdapterPool(
            [ProviderSettings.of("fake-engine", alias="work", base_url="https://w")],
            registry=registry,
        )
        assert registry.resolve_alias("work") == "work"
        assert registry.get("work").derived_from == "fake-engine"
        # The derived descriptor is the engine's, re-labelled: same requirements.
        assert registry.get("work").requires_base_url is True

    def test_omitting_an_alias_keeps_single_instance_behaviour(self):
        registry = _registry()
        pool = AdapterPool(
            [ProviderSettings.of("fake-engine", base_url="https://x")], registry=registry
        )
        assert pool.configured_ids == ("fake-engine",)
        # No derived descriptor is created when the instance *is* the engine.
        assert registry.get("fake-engine").derived_from is None

    def test_a_duplicate_instance_id_is_rejected(self):
        registry = _registry()
        with pytest.raises(ConfigError, match="configured twice"):
            AdapterPool(
                [
                    ProviderSettings.of("fake-engine", alias="same", base_url="https://a"),
                    ProviderSettings.of("fake-engine", alias="same", base_url="https://b"),
                ],
                registry=registry,
            )

    def test_an_alias_may_not_shadow_a_registered_provider(self):
        registry = _registry()
        registry.register(
            ProviderDescriptor(id="other-engine", display_name="Other", factory=_RecordingAdapter)
        )
        with pytest.raises(ConfigError, match="already registered"):
            AdapterPool(
                [ProviderSettings.of("fake-engine", alias="other-engine", base_url="https://a")],
                registry=registry,
            )

    def test_rebuilding_a_client_re_derives_the_same_instances(self):
        """An app that rebuilds its client on every settings change must not accumulate."""
        registry = _registry()
        for _ in range(3):
            AdapterPool(
                [ProviderSettings.of("fake-engine", alias="work", base_url="https://w")],
                registry=registry,
            )
        assert registry.resolve_alias("work") == "work"

    async def test_a_missing_required_field_still_fails_per_instance(self):
        registry = _registry()
        pool = AdapterPool([ProviderSettings.of("fake-engine", alias="no-url")], registry=registry)
        with pytest.raises(ConfigError, match="requires a base URL"):
            await pool.get("no-url")

    async def test_secret_options_are_resolved_like_the_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A second credential must not bypass the resolver just because it rides options.

        Driven off the setup spec's `secret` fields, so this holds for any provider that
        declares one, including third-party adapters the core has never heard of.
        """
        monkeypatch.setenv("FAKE_ENGINE_TOKEN", "resolved-secret")
        registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
        registry.register(
            ProviderDescriptor(
                id="two-credentials",
                display_name="Two Credentials",
                factory=_RecordingAdapter,
                setup=ProviderSetupSpec(
                    fields=(
                        SetupField("api_key", "Key", "secret"),
                        SetupField("oauth_token", "Token", "secret"),
                        SetupField("region", "Region", "host-profile"),
                    )
                ),
            )
        )
        pool = AdapterPool(
            [
                ProviderSettings.of(
                    "two-credentials",
                    options={
                        "oauth_token": "env://FAKE_ENGINE_TOKEN",
                        "region": "env://FAKE_ENGINE_TOKEN",
                    },
                )
            ],
            registry=registry,
        )

        adapter = await pool.get("two-credentials")
        assert isinstance(adapter, _RecordingAdapter)
        assert adapter.config.options["oauth_token"] == "resolved-secret"
        # A non-secret field is passed through verbatim: resolving it would corrupt any
        # value that merely looks like a reference.
        assert adapter.config.options["region"] == "env://FAKE_ENGINE_TOKEN"
