"""Provider registry, entry-point discovery, and target/alias resolution (§C1)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

import anyinfer as ai
from anyinfer.catalog.model import Catalog
from anyinfer.catalog.resolve import load_default_catalog, resolve_target
from anyinfer.registry import (
    ENTRY_POINT_GROUP,
    HostShorthand,
    ProviderDescriptor,
    ProviderRegistry,
    ProviderSetupSpec,
    SetupField,
    normalize_provider_id,
)
from anyinfer.types.requests import ReasoningEffort


def _descriptor(provider_id: str, *aliases: str) -> ProviderDescriptor:
    from anyinfer.providers.openai_compat import OpenAICompatAdapter

    return ProviderDescriptor(
        id=provider_id,
        display_name=provider_id.title(),
        aliases=tuple(aliases),
        factory=OpenAICompatAdapter,
    )


def _empty_registry() -> ProviderRegistry:
    return ProviderRegistry(load_builtins=False, load_entry_points=False)


# ---- normalization -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("OpenAI", "openai"),
        ("  anthropic  ", "anthropic"),
        ("azure_foundry", "azure-foundry"),
        ("M365_Copilot", "m365-copilot"),
    ],
)
def test_provider_ids_normalize(raw: str, expected: str) -> None:
    assert normalize_provider_id(raw) == expected


# ---- registration --------------------------------------------------------------------


def test_alias_resolves_to_the_canonical_id() -> None:
    registry = _empty_registry()
    registry.register(_descriptor("anthropic", "claude"))
    assert registry.resolve_alias("claude") == "anthropic"
    assert registry.resolve_alias("Claude") == "anthropic"


def test_duplicate_id_is_rejected() -> None:
    registry = _empty_registry()
    registry.register(_descriptor("openai"))
    with pytest.raises(ai.ConfigError, match="already registered"):
        registry.register(_descriptor("openai"))


def test_duplicate_id_can_be_replaced_explicitly() -> None:
    registry = _empty_registry()
    registry.register(_descriptor("openai"))
    registry.register(_descriptor("openai"), replace=True)
    assert registry.known_ids() == ("openai",)


def test_alias_collision_across_providers_is_rejected() -> None:
    registry = _empty_registry()
    registry.register(_descriptor("anthropic", "claude"))
    with pytest.raises(ai.ConfigError, match="already claimed"):
        registry.register(_descriptor("other", "claude"))


def test_unknown_provider_lists_the_known_ones() -> None:
    registry = _empty_registry()
    registry.register(_descriptor("openai"))
    with pytest.raises(ai.ConfigError) as excinfo:
        registry.resolve_alias("nope")

    assert excinfo.value.hint is not None
    assert "openai" in excinfo.value.hint


def test_unregister_removes_id_and_aliases() -> None:
    registry = _empty_registry()
    registry.register(_descriptor("anthropic", "claude"))
    registry.unregister("anthropic")
    assert not registry.has("anthropic")
    assert not registry.has("claude")


def test_builtins_are_discovered_lazily() -> None:
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    assert "openai-compat" in registry.known_ids()


def test_entry_point_providers_are_discovered(monkeypatch: pytest.MonkeyPatch) -> None:
    """A third-party package advertising a descriptor becomes resolvable."""
    plugin = _descriptor("acme-llm", "acme")

    class FakeEntryPoint:
        name = "acme"
        group = ENTRY_POINT_GROUP

        @staticmethod
        def load() -> Any:
            return lambda: [plugin]

    monkeypatch.setattr(
        "anyinfer.registry.entry_points", lambda group=None: [FakeEntryPoint()]
    )
    registry = ProviderRegistry(load_builtins=False, load_entry_points=True)

    assert registry.resolve_alias("acme") == "acme-llm"
    assert registry.get("acme-llm").display_name == "Acme-Llm"


def test_a_broken_plugin_does_not_break_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenEntryPoint:
        name = "broken"
        group = ENTRY_POINT_GROUP

        @staticmethod
        def load() -> Any:
            raise RuntimeError("this plugin is broken")

    monkeypatch.setattr(
        "anyinfer.registry.entry_points", lambda group=None: [BrokenEntryPoint()]
    )
    registry = ProviderRegistry(load_builtins=True, load_entry_points=True)
    assert "openai-compat" in registry.known_ids()


# ---- host shorthand ------------------------------------------------------------------


def test_host_shorthand_expansion() -> None:
    shorthand = HostShorthand(scheme="http", default_port=11434)
    assert shorthand.expand("myserver") == "http://myserver:11434"
    assert shorthand.expand("myserver:1234") == "http://myserver:1234"
    assert shorthand.expand("https://host/v1") == "https://host/v1"


# ---- target resolution ---------------------------------------------------------------


def _registry_with(*ids: str) -> ProviderRegistry:
    registry = _empty_registry()
    for provider_id in ids:
        registry.register(_descriptor(provider_id))
    return registry


def test_explicit_provider_and_model() -> None:
    resolved = resolve_target("ollama:qwen3", registry=_registry_with("ollama"))
    assert resolved == ai.ResolvedTarget("ollama", "qwen3", None)


def test_model_ids_may_contain_colons() -> None:
    """Split on the FIRST colon only — 'ollama:qwen3:8b' is one model named 'qwen3:8b'."""
    resolved = resolve_target("ollama:qwen3:8b", registry=_registry_with("ollama"))
    assert resolved.provider_id == "ollama"
    assert resolved.model == "qwen3:8b"


def test_provider_alias_is_normalized_during_resolution() -> None:
    registry = _empty_registry()
    registry.register(_descriptor("anthropic", "claude"))
    resolved = resolve_target("Claude:claude-sonnet-4-5", registry=registry)
    assert resolved.provider_id == "anthropic"


def test_empty_target_is_rejected() -> None:
    with pytest.raises(ai.ConfigError, match="empty"):
        resolve_target("   ", registry=_empty_registry())


def test_provider_without_a_model_is_rejected() -> None:
    with pytest.raises(ai.ConfigError, match="no model"):
        resolve_target("ollama:", registry=_registry_with("ollama"))


def test_bare_string_that_is_not_an_alias_is_rejected() -> None:
    with pytest.raises(ai.ConfigError) as excinfo:
        resolve_target("gpt-5", registry=_registry_with("openai"), catalog=load_default_catalog())

    assert excinfo.value.hint is not None
    assert "provider:model" in excinfo.value.hint
    assert "medium" in excinfo.value.hint


def test_alias_resolves_using_configured_provider_order() -> None:
    catalog = load_default_catalog()
    registry = _registry_with("ollama", "anthropic")

    resolved = resolve_target(
        "medium",
        registry=registry,
        catalog=catalog,
        configured_providers=("anthropic", "ollama"),
    )
    assert resolved.provider_id == "anthropic"
    assert resolved.via_alias == "medium"

    reversed_order = resolve_target(
        "medium",
        registry=registry,
        catalog=catalog,
        configured_providers=("ollama", "anthropic"),
    )
    assert reversed_order.provider_id == "ollama"


def test_alias_with_no_configured_candidate_is_actionable() -> None:
    with pytest.raises(ai.ConfigError) as excinfo:
        resolve_target(
            "medium",
            registry=_registry_with("openai-compat"),
            catalog=load_default_catalog(),
            configured_providers=("openai-compat",),
        )

    assert excinfo.value.hint is not None
    assert "supports:" in excinfo.value.hint


# ---- catalog parsing -----------------------------------------------------------------


def test_bundled_catalog_parses() -> None:
    catalog = load_default_catalog()
    assert catalog.default_alias == "medium"
    assert set(catalog.alias_names()) == {"small", "medium", "large"}
    assert catalog.artifact("qwen2.5-1.5b-instruct-q4-k-m").license == "apache-2.0"


def test_alias_targets_resolve_to_bundled_artifacts() -> None:
    """Every llama-cpp alias target must name an artifact models.json actually defines.

    The two files are maintained on different cadences — default.json by hand, models.json
    by the pin script — so a target that silently stops resolving is the failure mode this
    split introduces.
    """
    catalog = load_default_catalog()
    for alias in catalog.alias_names():
        target = catalog.targets_for_alias(alias).get("llama-cpp")
        assert target is not None and target.gguf
        assert target.gguf in catalog.artifacts


def test_sharded_artifacts_are_parsed() -> None:
    artifact = load_default_catalog().artifact("qwen2.5-7b-instruct-q4-k-m")
    assert artifact.is_sharded
    assert len(artifact.files) == 2
    assert all(f.sha256 for f in artifact.files)


def test_single_file_artifact_reports_total_size() -> None:
    artifact = load_default_catalog().artifact("qwen2.5-1.5b-instruct-q4-k-m")
    assert artifact.is_sharded is False
    # Pinned by scripts/pin_catalog.py from the Hugging Face tree API, so the number is
    # the file's real size rather than a figure copied between projects.
    assert artifact.total_size_bytes == 1117320736


def test_future_format_version_is_rejected() -> None:
    with pytest.raises(ai.ConfigError, match="unsupported catalog format_version"):
        Catalog.from_mapping({"format_version": 999})


def test_overlay_lets_an_application_win() -> None:
    base = load_default_catalog()
    overlay = Catalog.from_mapping(
        {
            "format_version": 1,
            "aliases": {
                "medium": {
                    "description": "our pinned medium",
                    "targets": {"openai": {"model": "gpt-5-pinned"}},
                }
            },
        }
    )
    merged = base.overlay(overlay)

    assert merged.alias("medium").description == "our pinned medium"
    assert set(merged.alias("medium").targets) == {"openai"}
    assert merged.alias("small").description == base.alias("small").description
    assert merged.artifacts == base.artifacts


def test_artifact_without_a_url_is_rejected() -> None:
    with pytest.raises(ai.ConfigError, match="missing a download url"):
        Catalog.from_mapping(
            {"format_version": 1, "gguf_artifacts": {"broken": {"filename": "x.gguf"}}}
        )


def test_target_entry_requires_a_model_or_gguf() -> None:
    catalog = Catalog.from_mapping(
        {
            "format_version": 1,
            "aliases": {"tiny": {"targets": {"ollama": {"description": "no ref"}}}},
        }
    )
    with pytest.raises(ai.ConfigError, match="neither"):
        _ = catalog.alias("tiny").targets["ollama"].model_ref


def test_unknown_alias_lists_the_known_ones() -> None:
    with pytest.raises(ai.ConfigError) as excinfo:
        load_default_catalog().alias("enormous")
    assert excinfo.value.hint is not None
    assert "medium" in excinfo.value.hint


# ---- catalog window facts feed capability assembly -----------------------------------


async def test_alias_entry_windows_reach_the_budget_at_catalog_provenance() -> None:
    """A window pinned on a catalog alias entry must inform budgeting for that alias."""
    from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

    catalog = Catalog.from_mapping(
        {
            "format_version": 1,
            "default_alias": "tiny",
            "aliases": {
                "tiny": {
                    "description": "test alias",
                    "targets": {
                        "openai-compat": {
                            "model": "m",
                            "context_window": 2048,
                            "max_output_tokens": 256,
                        }
                    },
                }
            },
        }
    )
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ],
        catalog=catalog,
    )
    async with client:
        budget = client.budget("hello", target="tiny")

    assert budget.context_window is not None
    assert budget.context_window.value == 2048
    assert budget.context_window.provenance == "catalog"


class TestSetupSpecInvariants:
    """Whole-registry invariants, so a new provider cannot reintroduce a fixed defect.

    These assert properties of *every* registered descriptor rather than of one
    provider, which is what makes them a guard rather than a spot check.
    """

    def test_every_secret_field_declares_a_placeholder(self) -> None:
        """A UI with no declared example has to guess, and guesses name one provider.

        The original defect: the demo suggested ``env://OPENAI_API_KEY`` for every
        provider's key field, which was wrong for all of them but OpenAI.
        """
        missing = [
            f"{d.id}.{f.key}"
            for d in ai.default_registry
            for f in d.setup.fields
            if f.kind == "secret" and not f.placeholder
        ]
        assert missing == []

    def test_no_placeholder_names_another_providers_variable(self) -> None:
        """A copied placeholder is the same defect wearing a different label."""
        wrong: list[str] = []
        for descriptor in ai.default_registry:
            token = descriptor.id.split("-")[0].upper()
            for setup_field in descriptor.setup.fields:
                if setup_field.kind != "secret" or "env://" not in setup_field.placeholder:
                    continue
                named = setup_field.placeholder.split("env://", 1)[1].split()[0]
                # A provider may legitimately use an unrelated variable name (HF_TOKEN,
                # CO_API_KEY); what it must never do is name a *different* provider's.
                for other in ai.default_registry:
                    other_token = other.id.split("-")[0].upper()
                    # Compare whole underscore-separated words, not substrings: z-ai's
                    # token is the single letter "Z", which as a substring matches every
                    # variable beginning with Z (ZHIPU_API_KEY) and reports a provider
                    # for naming its own key.
                    if other_token not in named.split("_"):
                        continue
                    if other.id != descriptor.id and token not in named:
                        wrong.append(f"{descriptor.id}.{setup_field.key} -> {named}")
        assert wrong == []

    def test_placeholder_and_env_var_never_drift(self) -> None:
        """The prose hint and the machine-readable fact must name the same variable.

        Two spellings of one fact is how they end up disagreeing: a provider changes the
        variable in its placeholder, discovery keeps looking for the old one, and the
        symptom is a key that is set and a provider that is never found.
        """
        generic = {"VARIABLE_NAME", "VAR", "VAR_NAME"}
        mismatched: list[str] = []
        for descriptor in ai.default_registry:
            for setup_field in descriptor.setup.fields:
                named = ""
                if "env://" in setup_field.placeholder:
                    named = setup_field.placeholder.split("env://", 1)[1].split()[0]
                if named and named not in generic:
                    if setup_field.env_var != named:
                        mismatched.append(
                            f"{descriptor.id}.{setup_field.key}: placeholder names "
                            f"{named!r} but env_var is {setup_field.env_var!r}"
                        )
                elif setup_field.env_var:
                    mismatched.append(
                        f"{descriptor.id}.{setup_field.key}: declares env_var "
                        f"{setup_field.env_var!r} but its placeholder does not name it"
                    )
        assert mismatched == []

    def test_env_var_is_never_a_credential_reference(self) -> None:
        """The bare name, never ``env://NAME`` — stored either way, every consumer strips."""
        for descriptor in ai.default_registry:
            for setup_field in descriptor.setup.fields:
                assert "://" not in setup_field.env_var, (
                    f"{descriptor.id}.{setup_field.key} stores a reference, not a name"
                )

    def test_every_hosted_provider_with_a_key_convention_declares_it(self) -> None:
        """Discovery is descriptor-driven; a provider that declares nothing is invisible.

        Not every provider has a conventional variable — a generic OpenAI-compatible
        endpoint genuinely does not — so this asserts the weaker, checkable thing: any
        provider whose own documentation names one has said so here.
        """
        for descriptor in ai.default_registry:
            for setup_field in descriptor.setup.fields:
                if "env://" not in setup_field.placeholder:
                    continue
                named = setup_field.placeholder.split("env://", 1)[1].split()[0]
                if named in {"VARIABLE_NAME", "VAR", "VAR_NAME"}:
                    continue
                assert setup_field.env_var, (
                    f"{descriptor.id}.{setup_field.key} names {named} in prose only"
                )

    def test_any_of_groups_reference_declared_fields(self) -> None:
        """A group naming a field that does not exist can never be satisfied."""
        for descriptor in ai.default_registry:
            keys = {f.key for f in descriptor.setup.fields}
            for group in descriptor.setup.any_of:
                assert set(group) <= keys, f"{descriptor.id}: {group} not in {keys}"
                assert len(group) > 1, f"{descriptor.id}: a one-field group is just required"

    def test_no_field_a_user_must_fill_in_is_hidden(self) -> None:
        """A save that refuses, naming a field that is not on screen, is a dead end.

        `ProviderSetupSpec` refuses the combination at construction, so this cannot
        currently fire — it is here because the invariant is about the whole registry
        rather than about one spec, and a future descriptor built some other way would
        still have to satisfy it.
        """
        for descriptor in ai.default_registry:
            blocking = {key for group in descriptor.setup.any_of for key in group}
            for setup_field in descriptor.setup.advanced_fields:
                assert not setup_field.required, f"{descriptor.id}.{setup_field.key}"
                assert setup_field.key not in blocking, f"{descriptor.id}.{setup_field.key}"

    def test_no_provider_asks_for_an_endpoint_it_already_knows(self) -> None:
        """A default base URL is an answered question; asking it again is noise.

        This is the defect the essential/advanced split exists to prevent: every hosted
        provider showing "Base URL" beside its API key made four of five fields on screen
        ones nobody was meant to touch.
        """
        for descriptor in ai.default_registry:
            if not descriptor.default_base_url:
                continue
            for setup_field in descriptor.setup.essential_fields:
                assert setup_field.kind != "endpoint", (
                    f"{descriptor.id}.{setup_field.key} is prompted for despite "
                    f"defaulting to {descriptor.default_base_url}"
                )

    def test_every_hidden_field_says_what_it_does(self) -> None:
        """Folded away with no default, no example, and no help text, it is a mystery box."""
        silent = [
            f"{d.id}.{f.key}"
            for d in ai.default_registry
            for f in d.setup.advanced_fields
            if not (f.default_value or f.placeholder or f.help_text)
        ]
        assert silent == []

    def test_a_required_advanced_field_is_rejected_at_construction(self) -> None:
        """Caught as a provider-authoring error rather than as a user's dead end."""
        with pytest.raises(ai.ConfigError):
            ProviderSetupSpec(
                fields=(
                    SetupField("api_key", "Key", "secret", required=True, advanced=True),
                )
            )

    def test_an_advanced_field_inside_an_any_of_group_is_rejected(self) -> None:
        """One of the group has to be filled in, so none of them may be hidden."""
        with pytest.raises(ai.ConfigError):
            ProviderSetupSpec(
                fields=(
                    SetupField("api_key", "Key", "secret"),
                    SetupField("oauth_token", "Token", "secret", advanced=True),
                ),
                any_of=(("api_key", "oauth_token"),),
            )

    def test_a_field_in_an_any_of_group_is_not_also_individually_required(self) -> None:
        """Marking both would demand both, contradicting the group's "either" meaning."""
        for descriptor in ai.default_registry:
            grouped = {key for group in descriptor.setup.any_of for key in group}
            for setup_field in descriptor.setup.fields:
                if setup_field.key in grouped:
                    assert not setup_field.required, (
                        f"{descriptor.id}.{setup_field.key} is in an any_of group "
                        "and individually required"
                    )


class TestEveryProviderIsWellFormed:
    """Invariants asserted against all 100+ registered providers, adapters included.

    Adding a provider is the most common change this repository sees, and the mistakes
    it invites are structural rather than behavioral: a base URL that resolves but is
    wrong, an id that collides, a local engine quietly pointing off-box. Unit tests for
    one adapter cannot catch those. These run over the whole registry so a new entry has
    to satisfy them without anyone remembering to add a test.
    """

    def test_every_provider_is_instantiable(self) -> None:
        """A descriptor whose factory raises is a provider that exists only in a list.

        `ConfigError` is the one acceptable failure and is not a defect: it is how an
        adapter reports missing configuration it declared in its setup spec (Vertex
        needs a GCP project). Any *other* exception means the descriptor and its adapter
        disagree about how to construct it, which no per-adapter test would catch
        because each one passes its own known-good configuration.
        """
        from anyinfer.errors import ConfigError
        from anyinfer.providers.base import ProviderConfig

        for descriptor in ProviderRegistry(load_builtins=True, load_entry_points=False):
            config = ProviderConfig(
                provider_id=descriptor.id,
                base_url=descriptor.default_base_url or "https://fake.invalid/v1",
                api_key="test-key",
            )
            try:
                assert descriptor.factory(config) is not None
            except ConfigError:
                continue
            except Exception as exc:
                raise AssertionError(
                    f"{descriptor.id} failed to build: {type(exc).__name__}: {exc}"
                ) from exc

    def test_every_default_base_url_is_absolute_https_or_loopback(self) -> None:
        """A relative or scheme-less default silently becomes a different request."""
        for descriptor in ProviderRegistry(load_builtins=True, load_entry_points=False):
            url = descriptor.default_base_url
            if url is None:
                continue
            assert url.startswith(("https://", "http://")), f"{descriptor.id}: {url}"
            if url.startswith("http://"):
                host = url.removeprefix("http://").split("/")[0].split(":")[0]
                assert host in {"127.0.0.1", "localhost", "0.0.0.0"}, (
                    f"{descriptor.id} sends credentials over plaintext to {host}"
                )

    def test_a_preset_without_a_default_url_requires_one(self) -> None:
        """Scoped to presets, because only there is the rule actually universal.

        Dedicated adapters legitimately have neither a default nor a prompt: Bedrock and
        Vertex compute the endpoint from a region and project, and Copilot's host is
        GitHub's and not the caller's to change. A preset is the opposite case by
        construction — it is a base URL plus quirks — so one with neither a default nor
        `requires_base_url` would send requests to nowhere with nothing in the setup UI
        to fix it.
        """
        from anyinfer.providers.presets import COMPAT_PRESETS

        for preset in COMPAT_PRESETS:
            if preset.base_url is None:
                assert preset.requires_base_url and preset.base_url_hint, (
                    f"{preset.id} has no default base URL and does not ask for one"
                )

    def test_local_providers_never_default_off_box(self) -> None:
        """"Local" is a promise about where the data goes, not just a UI label.

        It also drives pricing: `capabilities/assemble.py` treats a local provider's
        absent price as free rather than unknown, which is only true on your own metal.
        """
        for descriptor in ProviderRegistry(load_builtins=True, load_entry_points=False):
            if descriptor.locality != "local" or not descriptor.default_base_url:
                continue
            host = (
                descriptor.default_base_url.split("://", 1)[-1].split("/")[0].split(":")[0]
            )
            assert host in {"127.0.0.1", "localhost", "0.0.0.0"}, (
                f"{descriptor.id} is declared local but defaults to {host}"
            )

    def test_reasoning_translators_accept_every_normalized_level(self) -> None:
        """The core may pass any of the four levels; a translator must not raise.

        A KeyError here surfaces as a failed generation at request time, on whichever
        provider the router happened to pick.
        """
        for descriptor in ProviderRegistry(load_builtins=True, load_entry_points=False):
            efforts: tuple[ReasoningEffort | None, ...] = (
                None, "minimal", "low", "medium", "high",
            )
            for effort in efforts:
                translated = descriptor.reasoning_translator(effort)
                assert isinstance(translated, Mapping), (
                    f"{descriptor.id} translator returned {type(translated)} for {effort}"
                )
                if effort is None:
                    assert translated == {}, (
                        f"{descriptor.id} invents a reasoning parameter when the caller "
                        "asked for none"
                    )

    def test_ignored_parameters_are_not_also_advertised_as_features(self) -> None:
        """Claiming a capability the provider discards is worse than claiming nothing."""
        from anyinfer.types.capabilities import Feature

        for descriptor in ProviderRegistry(load_builtins=True, load_entry_points=False):
            if "tools" not in descriptor.ignored_parameters:
                continue
            features = descriptor.default_capabilities.features.value
            assert not features & Feature.TOOLS, (
                f"{descriptor.id} both advertises TOOLS and drops the tools parameter"
            )

    def test_display_names_are_distinct(self) -> None:
        """Two providers rendering identically in a picker cannot be told apart.

        Engines only. A *derived* descriptor is a configured instance of an engine — two
        Azure tenants, two OpenAI-compatible endpoints — and deliberately inherits the
        engine's display name, so requiring uniqueness there would forbid the feature.
        """
        registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
        seen: dict[str, str] = {}
        for descriptor in registry:
            if descriptor.derived_from is not None:
                continue
            clash = seen.get(descriptor.display_name)
            assert clash is None, (
                f"{descriptor.id} and {clash} share the display name "
                f"{descriptor.display_name!r}"
            )
            seen[descriptor.display_name] = descriptor.id
