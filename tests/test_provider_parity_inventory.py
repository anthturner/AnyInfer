"""Controls for the checked Python built-in provider declaration inventory."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from enum import Flag, auto
from functools import partial
from pathlib import Path

import pytest
from jsonschema import ValidationError

from anyinfer.providers import builtin_descriptors
from anyinfer.providers.presets import PresetCompatAdapter
from anyinfer.registry import ProviderDescriptor
from anyinfer.types.capabilities import Feature, Pricing

ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = ROOT / "scripts" / "export_python_provider_parity.py"
SNAPSHOT_PATH = ROOT / "maintenance" / "provider-parity" / "python-builtins.json"
SCHEMA_PATH = ROOT / "maintenance" / "provider-parity" / "python-builtins.schema.json"
_factory_calls = 0


def _non_invoked_factory(*_args, **_kwargs):
    global _factory_calls
    _factory_calls += 1
    raise AssertionError("factory must not be invoked")


@pytest.fixture(scope="module")
def exporter():
    spec = importlib.util.spec_from_file_location("provider_parity_exporter", EXPORTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _document() -> dict[str, object]:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def test_snapshot_is_complete_sorted_and_has_the_pinned_baseline(exporter) -> None:
    document = _document()
    providers = document["providers"]
    assert document["python_baseline"] == exporter.BASELINE
    descriptors = tuple(builtin_descriptors())
    assert len(providers) == len(descriptors)
    assert [row["id"] for row in providers] == sorted(row["id"] for row in providers)
    assert sum(len(row["descriptor"]["operations"]) for row in providers) == sum(
        len(descriptor.operations) for descriptor in descriptors
    )
    assert {row["family"] for row in providers} == {"dedicated", "compat_preset"}
    assert sum(row["family"] == "compat_preset" for row in providers) == sum(
        descriptor.id in {preset.id for preset in exporter.COMPAT_PRESETS}
        for descriptor in descriptors
    )


def test_rendered_rows_match_actual_descriptors_and_preserve_null_defaults(exporter) -> None:
    document = exporter.build_inventory()
    by_id = {row["id"]: row for row in document["providers"]}
    descriptors = tuple(builtin_descriptors())
    assert set(by_id) == {descriptor.id for descriptor in descriptors}
    for descriptor in descriptors:
        row = by_id[descriptor.id]
        assert row["descriptor"]["id"] == descriptor.id
        assert row["descriptor"]["operations"] == sorted(descriptor.operations)
        assert set(row["descriptor"]) == set(exporter._SUPPORTED_DATACLASSES[type(descriptor)])
    assert by_id["openai-compat"]["descriptor"]["default_capabilities"]["pricing"] is None
    assert by_id["openai-compat"]["descriptor"]["default_capabilities"]["local"] is None
    assert "pricing" in json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$defs"]
    assert "local" in json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$defs"]


def test_sources_are_sorted_complete_and_hash_checked(exporter) -> None:
    document = exporter.build_inventory()
    paths = [record["path"] for record in document["sources"]]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))
    assert "scripts/export_python_provider_parity.py" in paths
    assert "scripts/export_python_provider_bindings.py" in paths
    assert "maintenance/provider-parity/python-builtins.schema.json" in paths
    assert all("\\" not in path for path in paths)
    exporter.validate_inventory(document)
    document["sources"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="stale source hash"):
        exporter.validate_inventory(document)


def test_source_closure_rejects_missing_and_extra_records(exporter) -> None:
    document = exporter.build_inventory()
    missing = json.loads(json.dumps(document))
    missing["sources"].pop()
    with pytest.raises(ValueError, match="source closure mismatch"):
        exporter.validate_inventory(missing)
    extra = json.loads(json.dumps(document))
    extra["sources"].append({"path": "extra.py", "sha256": "0" * 64})
    with pytest.raises(
        ValueError, match=r"sources must be sorted and unique|source closure mismatch"
    ):
        exporter.validate_inventory(extra)


def test_encoder_rejects_unknown_feature_bits_and_unsupported_values(exporter) -> None:
    encoder = exporter._Encoder({})
    with pytest.raises(ValueError, match="invalid value"):
        encoder.encode(Feature(1 << 20))

    class UnreviewedFlag(Flag):
        VALUE = auto()

    with pytest.raises(ValueError, match="unsupported flag type"):
        encoder.encode(UnreviewedFlag.VALUE)
    with pytest.raises(ValueError, match="unsupported provider declaration value type"):
        encoder.encode(object())
    with pytest.raises(ValueError, match="non-finite float"):
        encoder.encode(float("nan"))


def test_factory_is_recorded_without_invocation(exporter, monkeypatch) -> None:
    global _factory_calls
    _factory_calls = 0
    descriptor = replace(next(iter(builtin_descriptors())), factory=_non_invoked_factory)
    original = exporter._bindings._builtins
    monkeypatch.setattr(exporter._bindings, "_builtins", lambda: (descriptor, *original()[1:]))
    rendered = exporter.build_inventory()
    assert _factory_calls == 0
    row = next(row for row in rendered["providers"] if row["id"] == descriptor.id)
    assert row["descriptor"]["factory"]["kind"] == "callable"


def test_builtin_membership_and_alias_collision_fail_closed(exporter, monkeypatch) -> None:
    original_enumeration = exporter._bindings.builtin_descriptors
    descriptors = tuple(original_enumeration())
    monkeypatch.setattr(exporter._bindings, "builtin_descriptors", lambda: descriptors[:-1])
    with pytest.raises(ValueError, match="registration does not match"):
        exporter._bindings._builtins()
    monkeypatch.setattr(exporter._bindings, "builtin_descriptors", original_enumeration)
    collision = replace(descriptors[0], aliases=(descriptors[1].id,))
    monkeypatch.setattr(exporter._bindings, "_builtins", lambda: (collision, *descriptors[1:]))
    with pytest.raises(ValueError, match="identifier collision"):
        exporter.build_inventory()


def test_current_operation_drift_renders_without_rewriting_historical_baseline(
    exporter, monkeypatch
) -> None:
    original = exporter._bindings._builtins
    descriptors = original()
    target = next(
        descriptor for descriptor in descriptors if descriptor.operations == {"generation"}
    )
    changed = replace(target, operations=frozenset({"generation", "embedding"}))
    monkeypatch.setattr(
        exporter._bindings,
        "_builtins",
        lambda: tuple(
            changed if descriptor.id == target.id else descriptor for descriptor in descriptors
        ),
    )
    document = exporter.build_inventory()
    row = next(row for row in document["providers"] if row["id"] == target.id)
    assert row["descriptor"]["operations"] == ["embedding", "generation"]
    assert document["python_baseline"] == exporter.BASELINE


def test_preset_partial_keeps_target_and_checked_preset_reference() -> None:
    document = _document()
    row = next(row for row in document["providers"] if row["id"] == "ai21")
    factory = row["descriptor"]["factory"]
    assert factory["kind"] == "partial"
    assert factory["target"] == "anyinfer.providers.presets.PresetCompatAdapter"
    assert factory["keywords"]["preset"] == {"kind": "preset_ref", "id": "ai21"}


def test_schema_rejects_malformed_sourced_payload_and_accepts_numeric_partial(exporter) -> None:
    document = _document()
    row = next(row for row in document["providers"] if row["id"] == "ai21")
    row["descriptor"]["factory"]["args"] = [7, 1.5]
    row["descriptor"]["factory"]["keywords"]["numeric_test"] = 7
    exporter._validator().validate(document)
    row["descriptor"]["default_capabilities"]["features"]["value"] = {"unexpected": True}
    with pytest.raises(ValidationError):
        exporter._validator().validate(document)


def test_encoder_rejects_mismatched_preset_and_dataclass_drift(exporter, monkeypatch) -> None:
    preset = exporter.COMPAT_PRESETS[0]
    mismatched = replace(preset, display_name="not canonical")
    with pytest.raises(ValueError, match="unexpected preset"):
        exporter._Encoder({preset.id: preset}).encode(
            partial(PresetCompatAdapter, preset=mismatched)
        )
    descriptor = next(iter(builtin_descriptors()))
    monkeypatch.setitem(exporter._SUPPORTED_DATACLASSES, ProviderDescriptor, ("id",))
    with pytest.raises(ValueError, match="field set"):
        exporter._Encoder({}).encode(descriptor)


def test_decimal_is_exact_and_nonfinite_decimal_is_refused(exporter) -> None:
    encoder = exporter._Encoder({})
    pricing = Pricing(
        Decimal("0.125"), Decimal("1.000"), per_server_tool_use={"web": Decimal("2.50")}
    )
    encoded = encoder.encode(pricing)
    assert encoded["input_per_1m"] == "0.125"
    assert encoded["output_per_1m"] == "1.000"
    assert encoded["per_server_tool_use"] == {"web": "2.50"}
    with pytest.raises(ValueError, match="non-finite Decimal"):
        encoder.encode(Decimal("NaN"))


def _check(candidate: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(EXPORTER_PATH), "--check", str(candidate)],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src" / "python")},
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_accepts_committed_raw_rendering() -> None:
    completed = _check(SNAPSHOT_PATH)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "mutated",
    [
        lambda raw: raw + b" ",
        lambda raw: raw.replace(b"\n", b"\r\n"),
        lambda raw: b"\xef\xbb\xbf" + raw,
        lambda _raw: b'{"schema_version":1,"schema_version":1}',
        lambda _raw: b'{"schema_version":NaN}',
    ],
    ids=["whitespace", "crlf", "bom", "duplicate-member", "nonfinite"],
)
def test_check_refuses_noncanonical_raw_bytes_without_rewriting(tmp_path: Path, mutated) -> None:
    candidate = tmp_path / "snapshot.json"
    candidate.write_bytes(mutated(SNAPSHOT_PATH.read_bytes()))
    before = candidate.read_bytes()
    completed = _check(candidate)
    assert completed.returncode != 0
    assert candidate.read_bytes() == before


def test_committed_source_closure_has_lf_attributes_and_no_cr_bytes() -> None:
    paths = [record["path"] for record in _document()["sources"]]
    completed = subprocess.run(
        ["git", "check-attr", "-z", "eol", "--stdin"],
        cwd=ROOT,
        input=("\0".join(paths) + "\0").encode(),
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    fields = completed.stdout.decode().split("\0")
    triples = [fields[index : index + 3] for index in range(0, len(fields) - 1, 3)]
    assert {path for path, _attribute, _value in triples} == set(paths)
    assert all(attribute == "eol" and value == "lf" for _path, attribute, value in triples)
    assert all(b"\r" not in (ROOT / path).read_bytes() for path in paths)


def test_foreign_import_is_refused(exporter, monkeypatch) -> None:
    import anyinfer

    monkeypatch.setattr(anyinfer, "__file__", "/foreign/site-packages/anyinfer/__init__.py")
    with pytest.raises(ValueError, match="foreign anyinfer import"):
        exporter._ensure_checkout_import()
