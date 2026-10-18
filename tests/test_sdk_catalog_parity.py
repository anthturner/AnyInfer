"""Input-only catalog controls shared with the native C# catalog port."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from anyinfer.catalog.model import Catalog
from anyinfer.catalog.resolve import resolve_target
from anyinfer.errors import ConfigError
from anyinfer.providers.openai_compat import OpenAICompatAdapter
from anyinfer.registry import ProviderDescriptor, ProviderRegistry

_FIXTURE = Path(__file__).parent / "fixtures" / "sdk-catalog-v1" / "catalog-input.json"


def _input() -> dict[str, Any]:
    """Read the shared catalog input document without deriving expected observations from it."""
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _registry() -> ProviderRegistry:
    """Create only the registry metadata needed by the real target resolver."""
    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    for provider_id in ("primary", "backup", "local", "other", "raw-key"):
        registry.register(
            ProviderDescriptor(
                id=provider_id,
                display_name=provider_id.title(),
                factory=OpenAICompatAdapter,
            )
        )
    return registry


def test_shared_base_document_preserves_catalog_scalar_and_metadata_rules() -> None:
    """Exercise parser defaults, catalog-only metadata, and artifact derivation from shared input."""
    fixture = _input()
    catalog = Catalog.from_mapping(fixture["base"])

    assert catalog.format_version is True
    assert catalog.default_alias == "tier"

    chat = catalog.model("chat-alpha")
    assert chat.kind == "generation"
    assert chat.name == "False"
    assert chat.source == "True"
    assert chat.last_verified == "None"
    assert chat.matches_best_at("CODING")

    embedding = catalog.model("vector-beta")
    assert embedding.kind == "embedding"
    assert embedding.embedding is not None
    assert embedding.embedding.dimensions == 0
    assert embedding.embedding.max_input_tokens == 2048
    assert [entry.id for entry in catalog.models_for(kind="embedding", best_at="rag")] == [
        "vector-beta"
    ]
    assert [entry.id for entry in catalog.models_for(provider_id="llama-cpp")] == [
        "artifact-model"
    ]

    preferred = catalog.alias("tier").targets["primary"]
    assert preferred.context_window == 0
    assert preferred.max_output_tokens == 0
    assert preferred.description == "True"
    assert preferred.model_ref == "primary:stable"
    assert catalog.alias("tier").targets["backup"].model_ref == "backup:stable"
    assert catalog.alias("tier").targets["local"].model_ref == "explicit-artifact"

    explicit = catalog.artifact("derived-hf")
    assert [file.filename for file in explicit.files] == ["authoritative.gguf"]
    assert explicit.files[0].sha256 == "explicit-wins"

    derived = catalog.artifact("derived-url")
    assert [file.filename for file in derived.files] == ["url-model.gguf"]
    assert derived.files[0].role == "model"
    assert derived.files[0].sha256 == "url-model-digest"
    assert derived.files[0].size_bytes == 4567

    hf_variant = catalog.model("artifact-model").variant("hf-gguf")
    assert hf_variant.source.sizes["vision/projector.gguf"] == 1
    assert hf_variant.source.roles["vision/projector.gguf"] == "projector"


def test_shared_overlay_replaces_matching_rows_wholesale() -> None:
    """Exercise the real parser and overlay without embedding expected output in fixture data."""
    fixture = _input()
    merged = Catalog.from_mapping(fixture["base"]).overlay(Catalog.from_mapping(fixture["overlay"]))

    assert merged.default_alias == "overlay-tier"
    assert set(merged.alias("tier").targets) == {"primary"}
    assert merged.alias("tier").targets["primary"].model_ref == "overlay-primary"
    assert merged.artifact("explicit-artifact").files[0].filename == "overlay.gguf"
    assert merged.model("chat-alpha").name == "Overlay Chat"
    assert merged.model("chat-alpha").best_at == ("general-chat",)


def test_shared_resolution_input_keeps_first_colon_and_configured_order() -> None:
    """Exercise explicit and alias target resolution using real registry and catalog methods."""
    fixture = _input()
    catalog = Catalog.from_mapping(fixture["base"])
    registry = _registry()
    explicit, missing_model = fixture["requests"]["explicit_targets"]

    resolved = resolve_target(explicit, registry=registry, catalog=catalog)
    assert resolved.provider_id == "primary"
    assert resolved.model == "model:with:colon"
    assert resolved.via_alias is None

    selected = resolve_target(
        fixture["requests"]["alias_targets"][0],
        registry=registry,
        catalog=catalog,
        configured_providers=fixture["configured_instance_ids"],
    )
    assert selected.provider_id == "primary"
    assert selected.model == "primary:stable"
    assert selected.via_alias == "tier"

    with pytest.raises(ConfigError, match="no model"):
        resolve_target(missing_model, registry=registry, catalog=catalog)
    with pytest.raises(ConfigError, match="no target among"):
        resolve_target(
            fixture["requests"]["alias_targets"][1],
            registry=registry,
            catalog=catalog,
            configured_providers=fixture["configured_instance_ids"],
        )
    with pytest.raises(ConfigError, match="neither"):
        resolve_target(
            fixture["requests"]["alias_targets"][2],
            registry=registry,
            catalog=catalog,
            configured_providers=fixture["configured_instance_ids"],
        )
    for target in fixture["requests"]["unknown_targets"]:
        with pytest.raises(ConfigError):
            resolve_target(target, registry=registry, catalog=catalog)


def test_shared_invalid_documents_retain_the_closed_catalog_boundaries() -> None:
    """Keep general unknown-key tolerance separate from the intentionally closed embedding block."""
    invalid = _input()["invalid_documents"]

    with pytest.raises(ConfigError, match="unknown keys"):
        Catalog.from_mapping(invalid["closed_embedding"])
    with pytest.raises(ConfigError, match="unknown kind"):
        Catalog.from_mapping(invalid["unknown_kind"])
    with pytest.raises(ConfigError, match="repeats variant id"):
        Catalog.from_mapping(invalid["duplicate_variant_ids"])


def test_shared_boundary_documents_distinguish_omitted_and_null_values() -> None:
    """Exercise the parser's actual collection defaults and its null rejection boundaries."""
    boundaries = _input()["boundary_documents"]

    omitted = Catalog.from_mapping(boundaries["omitted_collections_and_version"])
    assert omitted.format_version == 1
    assert omitted.alias_names() == ()
    assert not omitted.models

    omitted_best_at = Catalog.from_mapping(boundaries["omitted_best_at"]).model(
        "omitted-best-at"
    )
    assert omitted_best_at.best_at == ()

    omitted_model = Catalog.from_mapping(
        boundaries["omitted_variants_and_sources"]
    ).model("omitted-variants-and-sources")
    assert omitted_model.variants == ()

    omitted_source = Catalog.from_mapping(boundaries["omitted_variant_source"]).model(
        "omitted-variant-source"
    ).variant("omitted-source-variant")
    assert omitted_source.source.files == ()

    for name in (
        "null_aliases",
        "null_models",
        "null_version",
        "null_best_at",
        "null_variants",
        "null_sources",
        "null_variant_source",
    ):
        with pytest.raises(ConfigError):
            Catalog.from_mapping(boundaries[name])

    with pytest.raises(ConfigError, match="no catalog files"):
        Catalog.from_files()


def test_shared_derived_huggingface_artifact_preserves_nested_source_metadata() -> None:
    """Exercise derived artifact filenames and lookups from nested Hugging Face source paths."""
    document = _input()["derived_documents"]["nested_huggingface"]
    catalog = Catalog.from_mapping(document)
    model = catalog.model("nested-hf-model")
    artifact = catalog.artifact("derived-nested-hf")

    assert artifact.description == model.name == "Nested HF Name"
    assert artifact.description != model.description
    assert [file.filename for file in artifact.files] == ["model.gguf", "projector.gguf"]
    assert [(file.sha256, file.size_bytes, file.role) for file in artifact.files] == [
        ("nested-model-digest", 321, "model"),
        ("nested-projector-digest", 654, "projector"),
    ]


def test_shared_models_for_and_aliases_preserve_normalization_boundaries() -> None:
    """Exercise empty filters, whitespace filters, raw target keys, and normalized alias lookup."""
    fixture = _input()
    catalog = Catalog.from_mapping(fixture["base"])
    all_ids = sorted(catalog.models)

    assert [entry.id for entry in catalog.models_for(provider_id="", best_at="")] == all_ids
    assert catalog.models_for(provider_id=" ") == ()
    assert catalog.models_for(best_at=" ") == ()

    alias_input = fixture["alias_documents"]["underscore_alias"]
    alias_catalog = Catalog.from_mapping(alias_input)
    assert alias_catalog.alias_names() == ("tier_name",)
    assert set(alias_catalog.alias("TIER_NAME").targets) == {"Raw_Key"}

    resolved = resolve_target(
        "tier_name",
        registry=_registry(),
        catalog=alias_catalog,
        configured_providers=fixture["alias_documents"]["configured_instance_ids"],
    )
    assert resolved.provider_id == "raw-key"
    assert resolved.model == "raw-key-model"
    assert resolved.via_alias == "tier_name"


def test_shared_scalar_document_uses_python_string_coercion() -> None:
    """Assert model scalar storage follows Python string representations rather than JSON tokens."""
    document = _input()["scalar_documents"]["python_string_coercion"]
    catalog = Catalog.from_mapping(document)
    model = catalog.model("scalar-coercion")

    assert model.family == str(1e16)
    assert model.display_name == str(["quote\"", "line\nbreak", None, True, False])
    assert model.license == str(
        {"quote": "\"", "newline": "x\ny", "none": None, "true": True, "false": False}
    )
    assert model.last_verified == str(1e3)
    assert model.source == str(1e-5)
    assert model.description == str(-0.0)
    assert catalog.model("null-scalar-coercion").family == str(None)
