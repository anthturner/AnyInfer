"""Controlled-observer coverage for private reference publication."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.util
import json
import warnings
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from . import reference_writer
from .reference import ReferencePreflight, ReferencePreflightError


@pytest.mark.asyncio
async def test_writer_publishes_complete_development_observation_atomically(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = _assets(tmp_path)
    published: list[Path] = []
    real_publish = reference_writer._publish_new

    def publish(path: Path, payload: bytes) -> Callable[[], None]:
        published.append(path)
        return real_publish(path, payload)

    _install(monkeypatch, assets)
    monkeypatch.setattr(reference_writer, "_publish_new", publish)
    before = list(warnings.filters)

    async def observe(selected: Path) -> Mapping[str, Any]:
        assert selected == assets.root
        assert len(warnings.filters) == 1 and warnings.filters[0][0] == "error"
        return assets.observation

    result = await _write(assets, observe=observe)
    environment_bytes = assets.environment.read_bytes()
    manifest = json.loads(assets.manifest.read_text(encoding="utf-8"))

    assert result == assets.observation
    assert published == [assets.environment, assets.manifest]
    assert environment_bytes == reference_writer._json_bytes(assets.environment_facts)
    assert b"\r\n" not in environment_bytes and environment_bytes.endswith(b"\n")
    assert manifest["environment"]["sha256"] == hashlib.sha256(environment_bytes).hexdigest()
    assert manifest["packages"] == {
        name: row["version"] for name, row in assets.environment_facts["dependency_lock"].items()
    }
    assert _tree_bytes(assets.root) == assets.sealed_bytes
    assert warnings.filters == before


@pytest.mark.asyncio
async def test_writer_restores_strict_warnings_after_observer_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = _assets(tmp_path)
    _install(monkeypatch, assets)
    before = list(warnings.filters)

    async def observe(_selected: Path) -> Mapping[str, Any]:
        warnings.warn("native observer warning", UserWarning, stacklevel=2)
        raise AssertionError("warning policy did not apply")

    with pytest.raises(UserWarning):
        await _write(assets, observe=observe)
    assert warnings.filters == before
    assert not assets.environment.exists() and not assets.manifest.exists()


@pytest.mark.asyncio
async def test_writer_refuses_invalid_observation_matrix_before_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = _assets(tmp_path)
    _install(monkeypatch, assets)
    reference_writer._validate_observation(
        assets.observation, assets.cases, specification_root=assets.root
    )
    for name, observation, reason in _invalid_observations(assets):
        with pytest.raises(ReferencePreflightError, match=reason):
            reference_writer._validate_observation(
                observation, assets.cases, specification_root=assets.root
            )
        with pytest.raises(ReferencePreflightError, match=reason):
            await _write(assets, observe=_observer(observation))
        assert not assets.environment.exists(), name
        assert not assets.manifest.exists(), name


@pytest.mark.asyncio
async def test_writer_refuses_preflight_and_post_observation_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = _assets(tmp_path)
    calls = 0

    def preflight(*_args: Any, **_kwargs: Any) -> ReferencePreflight:
        nonlocal calls
        calls += 1
        if calls == 1:
            return assets.preflight
        return ReferencePreflight(
            "b" * 40,
            assets.preflight.repository_root,
            assets.root,
            assets.manifest,
            assets.environment,
            {"specification/README.md": "drifted"},
        )

    monkeypatch.setattr(reference_writer, "preflight_reference", preflight)
    monkeypatch.setattr(
        reference_writer, "capture_reference_environment", lambda _value: assets.environment_facts
    )
    with pytest.raises(ReferencePreflightError, match="changed during observation"):
        await _write(assets, observe=_observer(assets.observation))
    assert calls == 2
    assert not assets.environment.exists() and not assets.manifest.exists()

    monkeypatch.setattr(
        reference_writer,
        "preflight_reference",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ReferencePreflightError("rejected")),
    )
    with pytest.raises(ReferencePreflightError, match="rejected"):
        await _write(assets, observe=_observer(assets.observation))
    assert not assets.environment.exists() and not assets.manifest.exists()


@pytest.mark.asyncio
async def test_writer_propagates_cancellation_and_fatal_errors_without_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = _assets(tmp_path)
    _install(monkeypatch, assets)

    async def cancelled(_selected: Path) -> Mapping[str, Any]:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _write(assets, observe=cancelled)
    assert not assets.environment.exists() and not assets.manifest.exists()

    async def fatal(_selected: Path) -> Mapping[str, Any]:
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        await _write(assets, observe=fatal)
    assert not assets.environment.exists() and not assets.manifest.exists()


@pytest.mark.asyncio
async def test_writer_refuses_nonportable_environment_capture_before_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = _assets(tmp_path)
    _install(monkeypatch, assets)
    for value in ("bad\ud800", 2**63 + 1):
        environment = copy.deepcopy(assets.environment_facts)
        environment["captured_test_value"] = value
        monkeypatch.setattr(
            reference_writer,
            "capture_reference_environment",
            lambda _value, environment=environment: environment,
        )
        with pytest.raises(ReferencePreflightError):
            await _write(assets, observe=_observer(assets.observation))
        assert not assets.environment.exists() and not assets.manifest.exists()


@pytest.mark.asyncio
async def test_writer_preserves_existing_and_race_created_destinations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = _assets(tmp_path)
    _install(monkeypatch, assets)
    assets.environment.parent.mkdir(parents=True)
    staging = assets.environment.parent / ".preexisting-writer-stage.tmp"
    staging.write_bytes(b"preserve\n")
    assets.environment.write_bytes(b"sealed\n")

    with pytest.raises(ReferencePreflightError):
        await _write(assets, observe=_observer(assets.observation))
    assert assets.environment.read_bytes() == b"sealed\n"
    assert staging.read_bytes() == b"preserve\n"
    assert not assets.manifest.exists()

    assets.environment.unlink()
    real_publish = reference_writer._publish_new

    def race_manifest(path: Path, payload: bytes) -> Callable[[], None]:
        if path == assets.manifest:
            path.write_bytes(b"raced\n")
        return real_publish(path, payload)

    monkeypatch.setattr(reference_writer, "_publish_new", race_manifest)
    with pytest.raises(FileExistsError):
        await _write(assets, observe=_observer(assets.observation))
    assert not assets.environment.exists()
    assert assets.manifest.read_bytes() == b"raced\n"


@pytest.mark.asyncio
async def test_writer_publishes_observation_before_reference_pair_and_retains_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = _assets(tmp_path)
    _install(monkeypatch, assets)
    report = assets.preflight.repository_root / "observation.json"
    order: list[str] = []
    real_publish = reference_writer._publish_new

    def publish(path: Path, payload: bytes) -> Callable[[], None]:
        assert report.exists()
        order.append(path.name)
        return real_publish(path, payload)

    def publish_observation(observation: Mapping[str, Any]) -> Callable[[], None]:
        assert observation is assets.observation
        assert not assets.environment.exists()
        assert not assets.manifest.exists()
        report.write_bytes(reference_writer._json_bytes(dict(observation)))
        order.append("observation")

        def rollback() -> None:
            report.unlink(missing_ok=True)

        return rollback

    monkeypatch.setattr(reference_writer, "_publish_new", publish)
    assert (
        await _write(
            assets,
            observe=_observer(assets.observation),
            publish_observation=publish_observation,
        )
        == assets.observation
    )
    assert order == ["observation", assets.environment.name, assets.manifest.name]
    assert report.read_bytes() == reference_writer._json_bytes(assets.observation)
    assert assets.environment.exists() and assets.manifest.exists()


@pytest.mark.asyncio
async def test_writer_callback_failure_publishes_no_reference_pair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = _assets(tmp_path)
    _install(monkeypatch, assets)
    report = assets.preflight.repository_root / "existing-observation.json"
    report.write_bytes(b"existing\n")

    def publish_observation(_observation: Mapping[str, Any]) -> Callable[[], None]:
        assert not assets.environment.exists() and not assets.manifest.exists()
        assert report.read_bytes() == b"existing\n"
        raise FileExistsError("report already exists")

    with pytest.raises(FileExistsError, match="report already exists"):
        await _write(
            assets,
            observe=_observer(assets.observation),
            publish_observation=publish_observation,
        )
    assert report.read_bytes() == b"existing\n"
    assert not assets.environment.exists() and not assets.manifest.exists()


@pytest.mark.asyncio
async def test_writer_rolls_back_only_its_callback_report_after_reference_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = _assets(tmp_path)
    _install(monkeypatch, assets)
    owned_report = assets.preflight.repository_root / "owned-observation.json"
    raced_report = assets.preflight.repository_root / "raced-observation.json"
    real_publish = reference_writer._publish_new

    def publish(path: Path, payload: bytes) -> Callable[[], None]:
        if path == assets.manifest:
            raced_report.write_bytes(b"raced\n")
            raise OSError("manifest publication failed")
        return real_publish(path, payload)

    def publish_observation(_observation: Mapping[str, Any]) -> Callable[[], None]:
        owned_report.write_bytes(b"owned\n")

        def rollback() -> None:
            owned_report.unlink(missing_ok=True)

        return rollback

    monkeypatch.setattr(reference_writer, "_publish_new", publish)
    with pytest.raises(OSError, match="manifest publication failed"):
        await _write(
            assets,
            observe=_observer(assets.observation),
            publish_observation=publish_observation,
        )
    assert not owned_report.exists()
    assert raced_report.read_bytes() == b"raced\n"
    assert not assets.environment.exists() and not assets.manifest.exists()


@pytest.mark.asyncio
async def test_writer_keeps_replaced_environment_when_manifest_publication_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = _assets(tmp_path)
    _install(monkeypatch, assets)
    owned_report = assets.preflight.repository_root / "owned-observation.json"
    preexisting_report = assets.preflight.repository_root / "preexisting-observation.json"
    preexisting_report.write_bytes(b"preserve\n")
    real_publish = reference_writer._publish_new

    def publish(path: Path, payload: bytes) -> Callable[[], None]:
        if path == assets.manifest:
            raise OSError("manifest publication failed")
        rollback = real_publish(path, payload)
        replacement = path.parent / "replacement-environment.tmp"
        replacement.write_bytes(b"replacement\n")
        replacement.replace(path)
        return rollback

    def publish_observation(_observation: Mapping[str, Any]) -> Callable[[], None]:
        owned_report.write_bytes(b"owned\n")

        def rollback() -> None:
            owned_report.unlink(missing_ok=True)

        return rollback

    monkeypatch.setattr(reference_writer, "_publish_new", publish)
    with pytest.raises(OSError, match="manifest publication failed"):
        await _write(
            assets,
            observe=_observer(assets.observation),
            publish_observation=publish_observation,
        )
    assert assets.environment.read_bytes() == b"replacement\n"
    assert not assets.manifest.exists()
    assert not owned_report.exists()
    assert preexisting_report.read_bytes() == b"preserve\n"


@pytest.mark.asyncio
async def test_writer_attempts_callback_rollback_after_metadata_rollback_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = _assets(tmp_path)
    _install(monkeypatch, assets)
    report = assets.preflight.repository_root / "owned-observation.json"
    callback_rollback_attempted = False
    real_publish = reference_writer._publish_new

    def publish(path: Path, payload: bytes) -> Callable[[], None]:
        if path == assets.manifest:
            raise OSError("manifest publication failed")
        real_publish(path, payload)

        def fail_rollback() -> None:
            raise OSError("environment rollback failed")

        return fail_rollback

    def publish_observation(_observation: Mapping[str, Any]) -> Callable[[], None]:
        report.write_bytes(b"owned\n")

        def rollback() -> None:
            nonlocal callback_rollback_attempted
            callback_rollback_attempted = True
            report.unlink(missing_ok=True)

        return rollback

    monkeypatch.setattr(reference_writer, "_publish_new", publish)
    with pytest.raises(OSError):
        await _write(
            assets,
            observe=_observer(assets.observation),
            publish_observation=publish_observation,
        )
    assert callback_rollback_attempted
    assert not report.exists()


class _Assets:
    def __init__(
        self,
        root: Path,
        preflight: ReferencePreflight,
        manifest: Path,
        environment: Path,
        environment_facts: dict[str, Any],
        cases: dict[str, Mapping[str, Any]],
        observation: dict[str, Any],
        sealed_bytes: dict[Path, bytes],
    ) -> None:
        self.root = root
        self.preflight = preflight
        self.manifest = manifest
        self.environment = environment
        self.environment_facts = environment_facts
        self.cases = cases
        self.observation = observation
        self.sealed_bytes = sealed_bytes


def _assets(tmp_path: Path) -> _Assets:
    root, _release = _trusted_corpus_builder()._tree(tmp_path)
    sealed_bytes = _tree_bytes(root)
    executable = tmp_path / "A"
    (executable / "specification").mkdir(parents=True)
    manifest = executable / "specification/reference/python-aaaaaaa.json"
    environment = executable / "specification/reference/python-aaaaaaa.environment.json"
    environment_facts = json.loads(
        (root / "reference/python-aaaaaaa.environment.json").read_text(encoding="utf-8")
    )
    cases = reference_writer._inventory(root)
    preflight = ReferencePreflight(
        "a" * 40,
        executable,
        root,
        manifest,
        environment,
        {"specification/README.md": hashlib.sha256((root / "README.md").read_bytes()).hexdigest()},
    )
    return _Assets(
        root,
        preflight,
        manifest,
        environment,
        environment_facts,
        cases,
        _observation(root, cases),
        sealed_bytes,
    )


def _observation(root: Path, cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case_id, case in cases.items():
        row: dict[str, Any] = {"id": case_id, "verdict": "pass", "detail": None}
        if case.get("kind") == "driver_assertion":
            row["evidence"] = {"recipe_ref": case["recipe_ref"], "observations": {"native": True}}
        else:
            row["observations"] = {"status": "observed", "calls": [], "outcome": {"none": True}}
            row["evidence"] = {"captured": True}
        rows.append(row)
    extension_case = next(case for case in cases.values() if isinstance(case.get("extension"), str))
    _row({"cases": rows}, extension_case["id"]).update(
        {
            "verdict": "extension",
            "detail": "eligible native extension",
            "evidence": _extension_evidence(),
        }
    )
    return {
        "development_observation": "UNRELEASED",
        "report_v0_eligible": False,
        "report_v0_reason": "development observations do not carry release or reference qualification",
        "profile": {"name": "core-generation", "revision": "v0"},
        "selected_root": str(root),
        "inputs": _trusted_input_rows(root),
        "implementation": {"source": {}, "imports": {}, "runtime": {}, "dependencies": {}, "warning_policy": []},
        "extensions": sorted(
            {cast(str, case["extension"]) for case in cases.values() if isinstance(case.get("extension"), str)}
        ),
        "cases": rows,
        "unexecuted": [],
        "counts": {"pass": len(rows) - 1, "extension": 1, "unexecuted": 0},
    }


def _invalid_observations(assets: _Assets) -> list[tuple[str, dict[str, Any], str]]:
    missing = copy.deepcopy(assets.observation)
    missing["cases"].pop()
    extra = copy.deepcopy(assets.observation)
    extra["cases"].append({"id": "extra", "verdict": "pass", "detail": None, "evidence": None})
    duplicate = copy.deepcopy(assets.observation)
    duplicate["cases"].append(copy.deepcopy(duplicate["cases"][0]))
    stale = copy.deepcopy(assets.observation)
    stale["counts"]["pass"] -= 1
    outcomes: list[tuple[str, dict[str, Any], str]] = []
    for verdict in (None, "pending", "fail", "error", "unexecuted"):
        value = copy.deepcopy(assets.observation)
        value["cases"][0]["verdict"] = verdict
        outcomes.append(
            (f"verdict-{verdict}", value, "(schema validation|fail/error or invalid verdict)")
        )
    driver_case = next(case for case in assets.cases.values() if case.get("kind") == "driver_assertion")
    missing_evidence = copy.deepcopy(assets.observation)
    _row(missing_evidence, driver_case["id"])["evidence"] = None
    wrong_recipe = copy.deepcopy(assets.observation)
    _row(wrong_recipe, driver_case["id"])["evidence"]["recipe_ref"] = "wrong"
    fixture_case = next(case for case in assets.cases.values() if case.get("kind") == "fixture")
    missing_fixture_observations = copy.deepcopy(assets.observation)
    _row(missing_fixture_observations, fixture_case["id"]).pop("observations")
    extra_fixture_field = copy.deepcopy(assets.observation)
    _row(extra_fixture_field, fixture_case["id"])["extra"] = True
    driver_with_observations = copy.deepcopy(assets.observation)
    _row(driver_with_observations, driver_case["id"])["observations"] = {"wrong": True}
    nonempty_unexecuted = copy.deepcopy(assets.observation)
    nonempty_unexecuted["unexecuted"] = [{"id": "not-run"}]
    nonempty_unexecuted["counts"]["unexecuted"] = 1
    eligible = next(case for case in assets.cases.values() if isinstance(case.get("extension"), str))
    undeclared = copy.deepcopy(assets.observation)
    _row(undeclared, eligible["id"]).update({"verdict": "extension", "evidence": _extension_evidence()})
    undeclared["extensions"].remove(eligible["extension"])
    ineligible = copy.deepcopy(assets.observation)
    ordinary = next(
        case
        for case in assets.cases.values()
        if case.get("kind") == "fixture" and case.get("extension") is None
    )
    _row(ineligible, eligible["id"]).update({"verdict": "pass", "detail": None, "evidence": None})
    _row(ineligible, ordinary["id"]).update({"verdict": "extension", "evidence": _extension_evidence()})
    missing_outcome = copy.deepcopy(assets.observation)
    _row(missing_outcome, eligible["id"])["evidence"].pop("native_outcome")
    invalid_entry = copy.deepcopy(assets.observation)
    _row(invalid_entry, eligible["id"])["evidence"]["adapter_entries"][0]["entry_ordinal"] = -1
    fatal_evidence = copy.deepcopy(assets.observation)
    _row(fatal_evidence, eligible["id"])["evidence"]["native_outcome"] = {
        "error": {"category": None, "native_type": "KeyboardInterrupt", "message": "fatal"}
    }
    return [
        ("missing", missing, "incomplete or extra"),
        ("extra", extra, "incomplete or extra"),
        ("duplicate", duplicate, "duplicate or invalid"),
        ("stale", stale, "counts are stale"),
        *outcomes,
        ("missing-driver-evidence", missing_evidence, "report case schema validation"),
        ("wrong-driver-recipe", wrong_recipe, "driver evidence is missing or mismatched"),
        ("missing-fixture-observations", missing_fixture_observations, "invalid fields"),
        ("extra-fixture-field", extra_fixture_field, "invalid fields"),
        ("driver-with-observations", driver_with_observations, "invalid fields"),
        ("nonempty-unexecuted", nonempty_unexecuted, "unexecuted obligations"),
        ("undeclared-extension", undeclared, "extensions are invalid"),
        ("ineligible-extension", ineligible, "extension is not eligible and declared"),
        ("missing-extension-outcome", missing_outcome, "report case schema validation"),
        ("invalid-extension-entry", invalid_entry, "report case schema validation"),
        ("fatal-extension-evidence", fatal_evidence, "cancellation/fatal outcome"),
    ]


def _extension_evidence() -> dict[str, Any]:
    return {"native_outcome": {"none": True}, "adapter_entries": [{"entry_ordinal": 0, "model": "m", "role": "original", "timeout_s": 1.0, "max_response_bytes": 1}]}


def _trusted_input_rows(root: Path) -> list[dict[str, str]]:
    release = json.loads((root / "releases/core-generation-v0.json").read_text(encoding="utf-8"))
    files = cast(dict[str, str], release["files"])
    return [
        {"path": path.removeprefix("specification/"), "sha256": digest}
        for path, digest in files.items()
        if "/reference/" not in path
    ]


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _row(observation: dict[str, Any], case_id: str) -> dict[str, Any]:
    return next(row for row in observation["cases"] if row["id"] == case_id)


def _install(monkeypatch: pytest.MonkeyPatch, assets: _Assets) -> None:
    monkeypatch.setattr(reference_writer, "preflight_reference", lambda *_args, **_kwargs: assets.preflight)
    monkeypatch.setattr(reference_writer, "capture_reference_environment", lambda _value: assets.environment_facts)


def _observer(observation: Mapping[str, Any]) -> Callable[[Path], Awaitable[Mapping[str, Any]]]:
    async def observe(_selected: Path) -> Mapping[str, Any]:
        return observation

    return observe


async def _write(
    assets: _Assets,
    *,
    observe: Callable[[Path], Awaitable[Mapping[str, Any]]],
    publish_observation: Callable[[Mapping[str, Any]], Callable[[], None]] | None = None,
) -> Mapping[str, Any]:
    return await reference_writer.write_reference(
        assets.root,
        expected_revision=assets.preflight.revision,
        output_manifest=assets.manifest,
        output_environment=assets.environment,
        repository_root=assets.preflight.repository_root,
        observe=observe,
        publish_observation=publish_observation,
    )


def _trusted_corpus_builder() -> ModuleType:
    path = Path(__file__).parents[2] / "test_portable_release_assets.py"
    spec = importlib.util.spec_from_file_location("trusted_writer_release_assets", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
