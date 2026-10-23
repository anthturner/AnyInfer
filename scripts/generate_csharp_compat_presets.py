"""Render inert C# compatibility-preset metadata from the checked Python inventory."""
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "maintenance" / "provider-parity" / "python-builtins.json"


def _exporter() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_preset_inventory", ROOT / "scripts" / "export_python_provider_parity.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load provider inventory exporter")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _strict_json(raw: bytes) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
        raise ValueError("inventory must be UTF-8, BOM-free, and LF-only")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("inventory is not UTF-8") from error

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON member: {key!r}")
            result[key] = value
        return result

    def nonfinite(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ValueError("inventory root must be an object")
    return value


def load_inventory(path: Path) -> tuple[dict[str, Any], str]:
    """Read a current canonical inventory and prove its source closure is fresh."""
    raw = path.read_bytes()
    document = _strict_json(raw)
    exporter = _exporter()
    exporter.validate_inventory(document)
    rendered = exporter.render_inventory().encode("utf-8")
    if raw != rendered:
        raise ValueError("inventory bytes are stale or noncanonical")
    return document, hashlib.sha256(raw).hexdigest()


_ROW_KEYS = {"id", "family", "contract_dependencies", "descriptor", "preset"}
_DESCRIPTOR_KEYS = {
    "aliases",
    "cache_max_marks",
    "cache_mechanism",
    "cache_min_tokens",
    "default_base_url",
    "default_capabilities",
    "derived_from",
    "display_name",
    "factory",
    "governs_own_transport",
    "grammar_needs_prompt_injection",
    "honors_connection_settings",
    "id",
    "ignored_parameters",
    "locality",
    "max_repair_attempts",
    "model_inventory",
    "model_puller",
    "operations",
    "rate_limit_headers",
    "reasoning_translator",
    "reports_diagnostics",
    "requires_base_url",
    "server_tools",
    "setup",
    "static_capabilities",
    "static_embedding_capabilities",
    "static_rerank_capabilities",
    "supports_sessions",
    "token_calibration",
    "uses_catalog",
}
_PRESET_KEYS = {
    "accepts_api_key",
    "aliases",
    "auth_header",
    "base_url",
    "base_url_example",
    "base_url_hint",
    "batches",
    "default_port",
    "default_temperature",
    "default_top_p",
    "display_name",
    "embeddings",
    "features",
    "id",
    "ignored_parameters",
    "key_env",
    "locality",
    "models_listing",
    "note",
    "output_tokens_field",
    "reasoning",
    "requires_api_key",
    "requires_base_url",
}
_FACTORY_TARGETS = {
    "anyinfer.providers.presets.PresetCompatAdapter",
    "anyinfer.providers.presets.PresetEmbeddingAdapter",
}
_REASONING = {
    None: ("anyinfer.providers.presets._no_reasoning", "None"),
    "effort": ("anyinfer.providers.presets._translate_effort", "Effort"),
    "effort-min-low": ("anyinfer.providers.presets._translate_effort_min_low", "EffortMinLow"),
    "effort-three-level": (
        "anyinfer.providers.presets._translate_effort_three_level",
        "EffortThreeLevel",
    ),
    "effort-min-named": (
        "anyinfer.providers.presets._translate_effort_min_named",
        "EffortMinNamed",
    ),
    "reasoning-object": (
        "anyinfer.providers.presets._translate_reasoning_object",
        "ReasoningObject",
    ),
}
_MODEL_INVENTORY = {
    "served": "Served",
    "available": "Available",
    "installed": "Installed",
}


def project(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the closed compat-preset projection without evaluating source callables."""
    rows = document.get("providers")
    if not isinstance(rows, list):
        raise ValueError("inventory providers must be a list")
    output: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            raise ValueError("provider row has unknown or missing fields")
        if row["family"] != "compat_preset":
            continue
        descriptor, preset = row["descriptor"], row["preset"]
        if not isinstance(descriptor, dict) or not isinstance(preset, dict):
            raise ValueError("compat row lacks descriptor or preset")
        if set(descriptor) != _DESCRIPTOR_KEYS or set(preset) != _PRESET_KEYS:
            raise ValueError("compat descriptor or preset has unknown or missing fields")
        identifier = row["id"]
        if (
            not isinstance(identifier, str)
            or descriptor.get("id") != identifier
            or preset.get("id") != identifier
        ):
            raise ValueError("compat row IDs must agree")
        if not isinstance(descriptor.get("honors_connection_settings"), bool):
            raise ValueError(f"{identifier}: unsupported connection source fact")
        if descriptor.get("model_inventory") not in _MODEL_INVENTORY:
            raise ValueError(f"{identifier}: unsupported model inventory")
        if descriptor["model_inventory"] != "served":
            raise ValueError(f"{identifier}: compat source inventory must remain served")
        operations = descriptor.get("operations")
        if (
            not isinstance(operations, list)
            or "generation" not in operations
            or any(not isinstance(item, str) for item in operations)
        ):
            raise ValueError(f"{identifier}: invalid source operations")
        factory = descriptor.get("factory")
        if (
            not isinstance(factory, dict)
            or factory.get("kind") != "partial"
            or factory.get("target") not in _FACTORY_TARGETS
        ):
            raise ValueError(f"{identifier}: unsupported source factory")
        if factory.get("args") != [] or factory.get("keywords") != {
            "preset": {"kind": "preset_ref", "id": identifier}
        }:
            raise ValueError(f"{identifier}: source factory is not the checked preset partial")
        if factory["target"].endswith("PresetEmbeddingAdapter") != bool(preset.get("embeddings")):
            raise ValueError(f"{identifier}: embedding factory mismatch")
        style = preset.get("reasoning")
        if style not in _REASONING or descriptor.get("reasoning_translator") != {
            "kind": "callable",
            "target": _REASONING[style][0],
        }:
            raise ValueError(f"{identifier}: unsupported reasoning binding")
        if preset.get("auth_header") not in {"bearer", "x-api-key"} or preset.get(
            "output_tokens_field"
        ) not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError(f"{identifier}: unsupported dialect spelling")
        output.append(row)
    output.sort(key=lambda item: item["id"])
    if len({row["id"] for row in output}) != len(output):
        raise ValueError("compat preset IDs are not unique")
    return output


def _cs(value: str) -> str:
    """Return one regular C# string literal without raw line-separator characters."""
    return json.dumps(value, ensure_ascii=True).replace("\\/", "/")


def _provenance(value: str) -> str:
    names = {
        "default": "Default",
        "catalog": "Catalog",
        "discovered": "Discovered",
        "probed": "Probed",
        "override": "Override",
    }
    try:
        return f"Provenance.{names[value]}"
    except KeyError as error:
        raise ValueError(f"unknown provenance: {value!r}") from error


def _features(value: dict[str, Any]) -> str:
    known = {
        "STREAMING": "Streaming",
        "JSON_SCHEMA": "JsonSchema",
        "GRAMMAR": "Grammar",
        "JSON_MODE": "JsonMode",
        "TOOLS": "Tools",
        "REASONING": "Reasoning",
        "SYSTEM_PROMPT": "SystemPrompt",
        "CACHE_USAGE": "CacheUsage",
        "CACHE_PLACEMENT": "CachePlacement",
        "VISION": "Vision",
        "DOCUMENT": "Document",
        "AUDIO_IN": "AudioIn",
        "LOGPROBS": "Logprobs",
        "VIDEO_IN": "VideoIn",
        "CITATIONS": "Citations",
        "WEB_SEARCH": "WebSearch",
        "CODE_EXECUTION": "CodeExecution",
    }
    items = value.get("value")
    if not isinstance(items, list) or any(item not in known for item in items):
        raise ValueError("unknown feature flag")
    union = " | ".join(f"Feature.{known[item]}" for item in items) or "Feature.None"
    return f"new Sourced<Feature>({union}, {_provenance(value['provenance'])})"


def _setup_cs(value: dict[str, Any]) -> str:
    fields: list[str] = []
    for field in value["fields"]:
        choices = ", ".join(_cs(choice) for choice in field["choices"])
        fields.append(
            "new SetupField("
            + ", ".join(
                [
                    f"key: {_cs(field['key'])}",
                    f"label: {_cs(field['label'])}",
                    f"kind: {_cs(field['kind'])}",
                    f"required: {str(field['required']).lower()}",
                    f"helpText: {_cs(field['help_text'])}",
                    f"placeholder: {_cs(field['placeholder'])}",
                    f"envVar: {_cs(field['env_var'])}",
                    f"advanced: {str(field['advanced']).lower()}",
                    f"defaultValue: {_cs(field['default_value'])}",
                    f"choices: new string[] {{ {choices} }}",
                ]
            )
            + ")"
        )
    host = value["host_shorthand"]
    host_cs = (
        "null"
        if host is None
        else f"new HostShorthand(scheme: {_cs(host['scheme'])}, defaultPort: {host['default_port']})"
    )
    groups = ", ".join(
        "new string[] { " + ", ".join(_cs(item) for item in group) + " }"
        for group in value["any_of"]
    )
    return (
        "new ProviderSetupSpec(fields: new[] { "
        + ", ".join(fields)
        + " }, modelSelection: "
        + _cs(value["model_selection"])
        + f", hostShorthand: {host_cs}, anyOf: new IEnumerable<string>[] {{ {groups} }}, requirementNote: {_cs(value['requirement_note'])})"
    )


def _capabilities_cs(value: dict[str, Any]) -> str:
    for name in (
        "context_window",
        "max_output_tokens",
        "pricing",
        "local",
        "operations",
        "embedding",
    ):
        if value.get(name) is not None:
            raise ValueError(f"non-neutral capability field: {name}")

    def sourced(name: str) -> str:
        item = value[name]
        return (
            "null"
            if item is None
            else f"new Sourced<double>({item['value']!r}, {_provenance(item['provenance'])})"
        )

    return f"new ModelCapabilities(features: {_features(value['features'])}, defaultTemperature: {sourced('default_temperature')}, defaultTopP: {sourced('default_top_p')})"


def render(document: dict[str, Any], inventory_sha256: str) -> str:
    """Render deterministic inert table source; input strings remain C# string literals only."""
    rows = project(document)
    lines = [
        "// <auto-generated />",
        "// Source: maintenance/provider-parity/python-builtins.json",
        f"// Inventory SHA-256: {inventory_sha256}",
        "using AnyInfer.Capabilities;",
        "namespace AnyInfer.Providers;",
        "internal static partial class CompatPresetTable",
        "{",
        "    internal const int SchemaVersion = 1;",
        "    internal const int GeneratorVersion = 3;",
        f"    internal const string InventorySha256 = {_cs(inventory_sha256)};",
        "    internal static readonly IReadOnlyList<CompatPresetDefinition> Rows = Array.AsReadOnly(new CompatPresetDefinition[]",
        "    {",
    ]
    for row in rows:
        descriptor, preset = row["descriptor"], row["preset"]
        aliases = ", ".join(_cs(value) for value in descriptor["aliases"])
        operations = ", ".join(_cs(value) for value in descriptor["operations"])
        dependencies = ", ".join(_cs(value) for value in row["contract_dependencies"])
        ignored = ", ".join(_cs(value) for value in descriptor["ignored_parameters"])
        locality = {"hosted": "Hosted", "local": "Local"}.get(descriptor["locality"])
        if locality is None:
            raise ValueError(f"{row['id']}: unknown locality")
        style = _REASONING[preset["reasoning"]][1]
        inventory = _MODEL_INVENTORY[descriptor["model_inventory"]]
        lines.extend(
            [
                "        new CompatPresetDefinition(",
                f"            new CompatPresetSourceFacts({_cs(row['id'])}, new string[] {{ {operations} }}, {str(descriptor['honors_connection_settings']).lower()}, {_cs(descriptor['model_inventory'])}, new string[] {{ {dependencies} }}, {_cs(descriptor['factory']['target'])}),",
                "            new CompatPresetGenerationRow(",
                f"                {_cs(row['id'])}, {_cs(descriptor['display_name'])}, new string[] {{ {aliases} }}, "
                + (
                    "null"
                    if descriptor["default_base_url"] is None
                    else _cs(descriptor["default_base_url"])
                )
                + f", {str(descriptor['requires_base_url']).lower()}, ProviderLocality.{locality},",
                f"                {_setup_cs(descriptor['setup'])},",
                f"                {_capabilities_cs(descriptor['default_capabilities'])},",
                f"                new string[] {{ {ignored} }}, new OpenAICompatDialectOptions({_cs(preset['auth_header'])}, {str(preset['models_listing']).lower()}, {_cs(preset['output_tokens_field'])}), CompatPresetReasoningStyle.{style}, new InferenceOperation[] {{ InferenceOperation.Generation }}, ModelInventoryKind.{inventory}, {str(descriptor['honors_connection_settings']).lower()})),",
            ]
        )
    lines.extend(["    });", "}", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Render or check one deterministic generated C# table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--check", type=Path)
    args = parser.parse_args(argv)
    document, digest = load_inventory(args.input)
    rendered = render(document, digest).encode("utf-8")
    target = args.output or args.check
    if target is None:
        raise ValueError("one output mode is required")
    if args.output:
        target.write_bytes(rendered)
    elif target.read_bytes() != rendered:
        raise SystemExit("generated C# compatibility preset table is stale")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
