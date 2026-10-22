"""Export built-in Python provider bindings for provider-change maintenance.

The exporter deliberately reads only the built-in descriptor declaration graph.  It does
not construct adapters, discover entry points, resolve credentials, or contact a provider.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from anyinfer.providers import builtin_descriptors
from anyinfer.providers.presets import COMPAT_PRESETS
from anyinfer.registry import ProviderDescriptor

ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE = ROOT / "maintenance"
_SCHEMA_PATH = MAINTENANCE / "binding-inventory.schema.json"
_COMPAT_CONTRACT = "contracts/openai-compat.md"
_PRESET_CONTRACT = "contracts/openai-compat-presets.md"

# Dedicated adapters own a matching snapshot.  Extra entries record only actual adapter
# inheritance whose base dialect has a separate upstream contract snapshot.
_DEDICATED_CONTRACTS: dict[str, tuple[str, ...]] = {
    "anthropic": ("contracts/anthropic.md",),
    "azure-foundry": ("contracts/azure-foundry.md", _COMPAT_CONTRACT),
    "bedrock": ("contracts/bedrock.md",),
    "cohere": ("contracts/cohere.md",),
    "copilot": ("contracts/copilot.md",),
    "deepseek": ("contracts/deepseek.md", _COMPAT_CONTRACT),
    "gemini": ("contracts/gemini.md",),
    "jina": ("contracts/jina.md",),
    "llama-cpp": ("contracts/llama-cpp.md", _COMPAT_CONTRACT),
    "lm-studio": ("contracts/lm-studio.md", _COMPAT_CONTRACT),
    "m365-copilot": ("contracts/m365-copilot.md",),
    "nebius": ("contracts/nebius.md", _COMPAT_CONTRACT),
    "ollama": ("contracts/ollama.md",),
    "openai": ("contracts/openai.md",),
    "openai-compat": (_COMPAT_CONTRACT,),
    "openrouter": ("contracts/openrouter.md", _COMPAT_CONTRACT),
    "tei": ("contracts/tei.md",),
    "vertex": ("contracts/vertex.md", "contracts/gemini.md"),
    "voyage": ("contracts/voyage.md",),
    "xai": ("contracts/xai.md", _COMPAT_CONTRACT),
}


def _validator() -> Draft202012Validator:
    """Return the frozen inventory-envelope validator."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _require_valid_context(context: dict[str, Any]) -> None:
    """Reject a context other than the dispatcher-owned empty envelope."""
    _validator().validate(context)
    if context["implementation_id"] != "anyinfer-python":
        raise ValueError("context implementation_id must be 'anyinfer-python'")
    if context["producer"] != {"id": "provider-change-dispatcher", "version": "1"}:
        raise ValueError("context producer must be provider-change-dispatcher version 1")
    if context["bindings"]:
        raise ValueError("context bindings must be empty before the exporter runs")


def _contract_path(dependency: str) -> Path:
    """Resolve a schema-form dependency path under the repository root."""
    return ROOT / dependency.split("#", maxsplit=1)[0]


def _validate_dependency(dependency: str) -> None:
    """Fail closed for an absent contract or an absent branded-preset section."""
    contract = _contract_path(dependency)
    if not contract.is_file():
        raise ValueError(f"mapped contract does not exist: {dependency}")
    if "#" not in dependency:
        return
    section = dependency.partition("#")[2]
    heading = re.compile(rf"^#{{2,3}}\s+{re.escape(section)}(?:\s|—|-|$)")
    if not any(heading.match(line) for line in contract.read_text(encoding="utf-8").splitlines()):
        raise ValueError(f"mapped contract section does not exist: {dependency}")


def _dependencies(descriptor: ProviderDescriptor, preset_ids: frozenset[str]) -> tuple[str, ...]:
    """Return every checked snapshot dependency for one actual descriptor."""
    if descriptor.id in preset_ids:
        dependencies = (_COMPAT_CONTRACT, _PRESET_CONTRACT, f"{_PRESET_CONTRACT}#{descriptor.id}")
    else:
        try:
            dependencies = _DEDICATED_CONTRACTS[descriptor.id]
        except KeyError as exc:
            raise ValueError(
                f"built-in provider {descriptor.id!r} has no checked contract dependency mapping"
            ) from exc
    for dependency in dependencies:
        _validate_dependency(dependency)
    return tuple(sorted(dependencies))


def _builtins() -> tuple[ProviderDescriptor, ...]:
    """Load only declared built-ins and reject a registration/mapping mismatch."""
    descriptors = tuple(builtin_descriptors())
    ids = {descriptor.id for descriptor in descriptors}
    preset_ids = {preset.id for preset in COMPAT_PRESETS}
    expected = set(_DEDICATED_CONTRACTS) | preset_ids
    if ids != expected:
        missing = sorted(expected - ids)
        unexpected = sorted(ids - expected)
        raise ValueError(
            "built-in provider registration does not match the checked contract mapping: "
            f"missing={missing!r}, unexpected={unexpected!r}"
        )
    return descriptors


def build_inventory(context: dict[str, Any]) -> dict[str, Any]:
    """Build a schema-valid, deterministic inventory from a validated dispatcher context."""
    _require_valid_context(context)
    result = copy.deepcopy(context)
    preset_ids = frozenset(preset.id for preset in COMPAT_PRESETS)
    bindings = [
        {
            "provider_id": descriptor.id,
            "operation": operation,
            "contract_dependencies": list(_dependencies(descriptor, preset_ids)),
        }
        for descriptor in _builtins()
        for operation in sorted(descriptor.operations)
    ]
    result["producer"] = {"id": "python-provider-bindings", "version": "1"}
    result["bindings"] = sorted(
        bindings, key=lambda item: (item["provider_id"], item["operation"])
    )
    _validator().validate(result)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """Read dispatcher context and write the inventory without producing stdout metadata."""
    args = _parse_args()
    context = json.loads(args.context.read_text(encoding="utf-8"))
    inventory = build_inventory(context)
    args.output.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
