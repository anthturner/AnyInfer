"""Render the checked Python built-in provider declaration inventory.

This maintenance exporter reads declaration data only.  It neither builds adapters nor
discovers plugins, resolves credentials, calls translators, or contacts a provider.
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import hashlib
import importlib.util
import inspect
import json
import math
import sys
from collections.abc import Mapping
from decimal import Decimal
from enum import Flag
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "python"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from anyinfer.providers import _BUILTIN_MODULES  # noqa: E402
from anyinfer.providers.presets import COMPAT_PRESETS, CompatPreset  # noqa: E402
from anyinfer.registry import (  # noqa: E402
    HostShorthand,
    ProviderDescriptor,
    ProviderSetupSpec,
    SetupField,
    normalize_provider_id,
)
from anyinfer.types.capabilities import (  # noqa: E402
    Feature,
    LocalModelInfo,
    ModelCapabilities,
    Pricing,
    RateLimitHeaders,
    Sourced,
    TokenCalibration,
)
from anyinfer.types.operations import EmbeddingCapabilities, RerankCapabilities  # noqa: E402


def _load_bindings_module() -> Any:
    """Load the authoritative binding helpers by their checkout path."""
    path = ROOT / "scripts" / "export_python_provider_bindings.py"
    spec = importlib.util.spec_from_file_location("_provider_parity_binding_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load binding helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_bindings = _load_bindings_module()

MAINTENANCE = ROOT / "maintenance" / "provider-parity"
SCHEMA_PATH = MAINTENANCE / "python-builtins.schema.json"
BASELINE = {
    "revision": "199c3f833e568334b629edd7d89f41a3b76efe2a",
    "descriptor_count": 106,
    "operation_counts": {"generation": 103, "embedding": 16, "rerank": 5, "batch": 5},
}

_SUPPORTED_DATACLASSES: dict[type[Any], tuple[str, ...]] = {
    ProviderDescriptor: (
        "id",
        "display_name",
        "factory",
        "aliases",
        "locality",
        "default_base_url",
        "requires_base_url",
        "honors_connection_settings",
        "setup",
        "reasoning_translator",
        "static_capabilities",
        "default_capabilities",
        "operations",
        "static_embedding_capabilities",
        "static_rerank_capabilities",
        "token_calibration",
        "rate_limit_headers",
        "governs_own_transport",
        "supports_sessions",
        "model_puller",
        "model_inventory",
        "uses_catalog",
        "reports_diagnostics",
        "cache_mechanism",
        "cache_max_marks",
        "cache_min_tokens",
        "grammar_needs_prompt_injection",
        "max_repair_attempts",
        "server_tools",
        "ignored_parameters",
        "derived_from",
    ),
    ProviderSetupSpec: (
        "fields",
        "model_selection",
        "host_shorthand",
        "any_of",
        "requirement_note",
    ),
    SetupField: (
        "key",
        "label",
        "kind",
        "required",
        "help_text",
        "placeholder",
        "env_var",
        "advanced",
        "default_value",
        "choices",
    ),
    HostShorthand: ("scheme", "default_port"),
    Sourced: ("value", "provenance"),
    TokenCalibration: ("multiplier", "overhead_tokens", "tokenizer", "tokenizer_provenance"),
    RateLimitHeaders: (
        "requests_remaining",
        "requests_reset",
        "tokens_remaining",
        "tokens_reset",
        "limit_requests",
        "limit_tokens",
    ),
    Pricing: (
        "input_per_1m",
        "output_per_1m",
        "cache_read_per_1m",
        "cache_write_per_1m",
        "currency",
        "per_search_unit",
        "per_server_tool_use",
    ),
    LocalModelInfo: (
        "artifact_size_bytes",
        "parameter_size",
        "quantization",
        "est_ram_bytes",
        "est_vram_bytes",
        "observed_vram_bytes",
    ),
    ModelCapabilities: (
        "context_window",
        "max_output_tokens",
        "features",
        "pricing",
        "default_temperature",
        "default_top_p",
        "local",
        "operations",
        "embedding",
    ),
    EmbeddingCapabilities: (
        "dimensions",
        "dimension_choices",
        "max_batch_inputs",
        "max_input_tokens",
        "max_input_bytes",
        "input_intents",
        "normalized",
    ),
    RerankCapabilities: (
        "max_documents",
        "max_tokens_per_document",
        "max_bytes_per_document",
        "native_top_n",
    ),
    CompatPreset: (
        "id",
        "display_name",
        "base_url",
        "aliases",
        "locality",
        "key_env",
        "requires_api_key",
        "accepts_api_key",
        "requires_base_url",
        "base_url_hint",
        "base_url_example",
        "models_listing",
        "auth_header",
        "output_tokens_field",
        "features",
        "ignored_parameters",
        "reasoning",
        "default_temperature",
        "default_top_p",
        "default_port",
        "embeddings",
        "batches",
        "note",
    ),
}
_SUPPORTED_FLAG_TYPES = {Feature}


def _checkout_path(path: Path, *, python_module: bool = False) -> str:
    """Normalize one existing repository-contained source path."""
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"inventory source is outside this checkout: {resolved}") from exc
    if not resolved.is_file():
        raise ValueError(f"inventory source is not a file: {relative.as_posix()}")
    if python_module and resolved.suffix != ".py":
        raise ValueError(f"inventory module source is not Python: {relative.as_posix()}")
    return relative.as_posix()


def _callable_target(value: Any) -> str:
    """Return a stable callable identity while refusing anonymous runtime objects."""
    module = getattr(value, "__module__", None)
    qualname = getattr(value, "__qualname__", None)
    if not isinstance(module, str) or not isinstance(qualname, str) or "<locals>" in qualname:
        raise ValueError(f"unsupported callable identity: {type(value).__name__}")
    return f"{module}.{qualname}"


class _Encoder:
    """Explicit declaration serializer and source-closure collector."""

    def __init__(self, presets: Mapping[str, CompatPreset]) -> None:
        self._presets = presets
        self.sources: set[str] = set()

    def _add_module_source(self, value: Any) -> None:
        source = inspect.getsourcefile(value)
        if source is None:
            raise ValueError(f"cannot locate source for {value!r}")
        self.sources.add(_checkout_path(Path(source), python_module=True))

    def _dataclass(self, value: Any, *, allow_preset_ref: bool) -> dict[str, Any]:
        value_type = type(value)
        try:
            expected = _SUPPORTED_DATACLASSES[value_type]
        except KeyError as exc:
            raise ValueError(
                f"unsupported dataclass type: {value_type.__module__}.{value_type.__qualname__}"
            ) from exc
        actual = tuple(field.name for field in dataclasses.fields(value))
        if actual != expected:
            raise ValueError(
                "unsupported dataclass field set for "
                f"{value_type.__module__}.{value_type.__qualname__}: "
                f"expected={expected!r}, actual={actual!r}"
            )
        self._add_module_source(value_type)
        if isinstance(value, CompatPreset) and allow_preset_ref:
            canonical = self._presets.get(value.id)
            if canonical is None or canonical != value:
                raise ValueError(f"partial bound unexpected preset data: {value.id!r}")
            return {"kind": "preset_ref", "id": value.id}
        return {
            field.name: self.encode(getattr(value, field.name), allow_preset_ref=allow_preset_ref)
            for field in dataclasses.fields(value)
        }

    def _flag(self, value: Flag) -> list[str]:
        value_type = type(value)
        if value_type not in _SUPPORTED_FLAG_TYPES:
            raise ValueError(
                f"unsupported flag type: {value_type.__module__}.{value_type.__qualname__}"
            )
        known = 0
        for member in value_type:
            known |= int(member.value)
        if int(value.value) & ~known:
            raise ValueError(f"unnamed {value_type.__name__} bit: {int(value.value)!r}")
        self._add_module_source(value_type)
        return sorted(member.name for member in value_type if member in value)

    def encode(self, value: Any, *, allow_preset_ref: bool = True) -> Any:
        """Encode one supported declaration value without invoking it."""
        if value is None or isinstance(value, (str, bool)):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"non-finite float in provider declaration: {value!r}")
            return value
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError(f"non-finite Decimal in provider declaration: {value!r}")
            return str(value)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return self._dataclass(value, allow_preset_ref=allow_preset_ref)
        if isinstance(value, Flag):
            return self._flag(value)
        if isinstance(value, functools.partial):
            self._add_module_source(value.func)
            return {
                "kind": "partial",
                "target": _callable_target(value.func),
                "args": [
                    self.encode(item, allow_preset_ref=allow_preset_ref) for item in value.args
                ],
                "keywords": {
                    key: self.encode(item, allow_preset_ref=allow_preset_ref)
                    for key, item in sorted((value.keywords or {}).items())
                },
            }
        if isinstance(value, Mapping):
            if not all(isinstance(key, str) for key in value):
                raise ValueError("provider declaration mapping has a non-string key")
            return {
                key: self.encode(item, allow_preset_ref=allow_preset_ref)
                for key, item in sorted(value.items())
            }
        if isinstance(value, (tuple, list)):
            return [self.encode(item, allow_preset_ref=allow_preset_ref) for item in value]
        if isinstance(value, (frozenset, set)):
            if not all(isinstance(item, str) for item in value):
                raise ValueError("provider declaration set has a non-string value")
            return sorted(value)
        if callable(value):
            self._add_module_source(value)
            return {"kind": "callable", "target": _callable_target(value)}
        raise ValueError(
            "unsupported provider declaration value type: "
            f"{type(value).__module__}.{type(value).__qualname__}"
        )


def _ensure_checkout_import() -> None:
    """Refuse an installed or foreign package shadowing this checkout's source tree."""
    import anyinfer

    package = Path(anyinfer.__file__).resolve()
    try:
        package.relative_to(SOURCE_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"foreign anyinfer import: {package}") from exc


def _fixed_sources() -> set[str]:
    paths = {
        ROOT / "scripts" / "export_python_provider_parity.py",
        SCHEMA_PATH,
        ROOT / "scripts" / "export_python_provider_bindings.py",
        SOURCE_ROOT / "anyinfer" / "providers" / "__init__.py",
        SOURCE_ROOT / "anyinfer" / "providers" / "presets.py",
        SOURCE_ROOT / "anyinfer" / "registry.py",
        SOURCE_ROOT / "anyinfer" / "types" / "capabilities.py",
        SOURCE_ROOT / "anyinfer" / "types" / "operations.py",
    }
    for module_name in _BUILTIN_MODULES:
        paths.add(SOURCE_ROOT / "anyinfer" / "providers" / f"{module_name.replace('.', '/')}.py")
    for data_type in _SUPPORTED_DATACLASSES:
        source = inspect.getsourcefile(data_type)
        if source is None:
            raise ValueError(f"cannot locate source for supported type {data_type.__qualname__}")
        paths.add(Path(source))
    for flag_type in _SUPPORTED_FLAG_TYPES:
        source = inspect.getsourcefile(flag_type)
        if source is None:
            raise ValueError(f"cannot locate source for supported flag {flag_type.__qualname__}")
        paths.add(Path(source))
    return {_checkout_path(path, python_module=path.suffix == ".py") for path in paths}


def _dependency_sources(
    descriptors: tuple[ProviderDescriptor, ...], preset_ids: frozenset[str]
) -> set[str]:
    result: set[str] = set()
    for descriptor in descriptors:
        for dependency in _bindings._dependencies(descriptor, preset_ids):
            result.add(_checkout_path(_bindings._contract_path(dependency)))
    return result


def _source_records(paths: set[str]) -> list[dict[str, str]]:
    return [
        {"path": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}
        for path in sorted(paths)
    ]


def _operation_counts(descriptors: tuple[ProviderDescriptor, ...]) -> dict[str, int]:
    counts = {"generation": 0, "embedding": 0, "rerank": 0, "batch": 0}
    for descriptor in descriptors:
        for operation in descriptor.operations:
            try:
                counts[operation] += 1
            except KeyError as exc:
                raise ValueError(f"unsupported descriptor operation: {operation!r}") from exc
    return counts


def _validate_identifiers(descriptors: tuple[ProviderDescriptor, ...]) -> None:
    """Reject a built-in alias collision before it can hide a declaration row."""
    owners: dict[str, str] = {}
    for descriptor in descriptors:
        for identifier in (descriptor.id, *descriptor.aliases):
            normalized = normalize_provider_id(identifier)
            previous = owners.setdefault(normalized, descriptor.id)
            if previous != descriptor.id:
                raise ValueError(
                    "built-in provider identifier collision: "
                    f"{normalized!r} belongs to both {previous!r} and {descriptor.id!r}"
                )


def build_inventory() -> dict[str, Any]:
    """Render the complete built-in declaration graph and its source closure."""
    _ensure_checkout_import()
    descriptors = _bindings._builtins()
    presets = {preset.id: preset for preset in COMPAT_PRESETS}
    if len(presets) != len(COMPAT_PRESETS):
        raise ValueError("compat preset ids are not unique")
    preset_ids = frozenset(presets)
    if len({descriptor.id for descriptor in descriptors}) != len(descriptors):
        raise ValueError("built-in descriptor ids are not unique")
    _validate_identifiers(descriptors)

    encoder = _Encoder(presets)
    providers: list[dict[str, Any]] = []
    for descriptor in descriptors:
        preset = presets.get(descriptor.id)
        providers.append(
            {
                "id": descriptor.id,
                "family": "compat_preset" if preset is not None else "dedicated",
                "contract_dependencies": list(_bindings._dependencies(descriptor, preset_ids)),
                "descriptor": encoder.encode(descriptor),
                "preset": encoder.encode(preset, allow_preset_ref=False)
                if preset is not None
                else None,
            }
        )
    providers.sort(key=lambda provider: provider["id"])
    if [provider["id"] for provider in providers] != sorted(
        provider["id"] for provider in providers
    ):
        raise ValueError("provider rows are not sorted")
    if len(providers) != len(descriptors):
        raise ValueError("provider rendering lost a descriptor")

    source_paths = (
        _fixed_sources() | encoder.sources | _dependency_sources(descriptors, preset_ids)
    )
    inventory = {
        "schema_version": 1,
        "purpose": "provider-parity-inventory",
        "python_baseline": BASELINE,
        "sources": _source_records(source_paths),
        "providers": providers,
    }
    validate_inventory(inventory)
    current_counts = _operation_counts(descriptors)
    rendered_counts = {
        operation: sum(operation in row["descriptor"]["operations"] for row in providers)
        for operation in current_counts
    }
    if current_counts != rendered_counts:
        raise ValueError(
            "rendered operation counts differ from source: "
            f"{current_counts!r} != {rendered_counts!r}"
        )
    if len(providers) != len(descriptors):
        raise ValueError("rendered provider count differs from source")
    return inventory


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_inventory(inventory: dict[str, Any]) -> None:
    """Validate closed schema, exact source membership, and every raw source hash."""
    _validator().validate(inventory)
    descriptors = _bindings._builtins()
    presets = {preset.id: preset for preset in COMPAT_PRESETS}
    encoder = _Encoder(presets)
    for descriptor in descriptors:
        encoder.encode(descriptor)
    expected_paths = (
        _fixed_sources() | encoder.sources | _dependency_sources(descriptors, frozenset(presets))
    )
    records = inventory["sources"]
    actual_paths = [record["path"] for record in records]
    if actual_paths != sorted(actual_paths) or len(actual_paths) != len(set(actual_paths)):
        raise ValueError("sources must be sorted and unique")
    if set(actual_paths) != expected_paths:
        raise ValueError(
            f"source closure mismatch: missing={sorted(expected_paths - set(actual_paths))!r}, "
            f"extra={sorted(set(actual_paths) - expected_paths)!r}"
        )
    for record in records:
        actual_hash = hashlib.sha256((ROOT / record["path"]).read_bytes()).hexdigest()
        if record["sha256"] != actual_hash:
            raise ValueError(f"stale source hash: {record['path']}")


def render_inventory() -> str:
    """Return canonical UTF-8 JSON text with LF line endings and one final newline."""
    return json.dumps(build_inventory(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--output", type=Path)
    modes.add_argument("--check", type=Path)
    return parser.parse_args()


def main() -> None:
    """Write a fresh deterministic snapshot or reject a malformed/stale one."""
    args = _parse_args()
    rendered = render_inventory()
    if args.output is not None:
        args.output.write_bytes(rendered.encode("utf-8"))
        return
    try:
        stored_bytes = args.check.read_bytes()
        stored = stored_bytes.decode("utf-8")

        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON member: {key!r}")
                result[key] = value
            return result

        def reject_nonfinite(value: str) -> None:
            raise ValueError(f"non-finite JSON number: {value}")

        document = json.loads(
            stored,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid provider parity snapshot: {exc}") from exc
    try:
        validate_inventory(document)
    except (ValueError, TypeError) as exc:
        raise SystemExit(f"invalid provider parity snapshot: {exc}") from exc
    if stored_bytes != rendered.encode("utf-8"):
        raise SystemExit("provider parity snapshot is stale")


if __name__ == "__main__":
    main()
