"""Focused tests for the UNRELEASED portable observation driver."""

from __future__ import annotations

import asyncio
import builtins
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

from . import conftest, driver
from .values import MissingEvidenceError, ValueDomainError

pytest_plugins = ["pytester"]


def test_observation_is_unreleased_and_does_not_validate_as_report_v0() -> None:
    report = asyncio.run(driver.observe_core(driver._DEFAULT_ROOT))
    assert report["development_observation"] == "UNRELEASED"
    assert report["report_v0_eligible"] is False
    assert len(report["cases"]) == 102
    assert len({case["id"] for case in report["cases"]}) == 102
    assert report["unexecuted"] == []
    assert report["counts"]["unexecuted"] == 0
    schema = json.loads((driver._DEFAULT_ROOT / "schemas/report-v0.schema.json").read_text())
    assert list(Draft202012Validator(schema).iter_errors(report))


def test_selected_root_hashes_and_paths_are_isolated(tmp_path: Path) -> None:
    selected = tmp_path / "specification"
    for relative in driver._NORMATIVE_INPUTS:
        destination = selected / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((driver._DEFAULT_ROOT / relative).read_bytes())
    source_fixtures = driver._DEFAULT_ROOT / "fixtures"
    for source in source_fixtures.rglob("*.json"):
        destination = selected / "fixtures" / source.relative_to(source_fixtures)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    report = asyncio.run(driver.observe_core(selected))
    assert report["selected_root"] == str(selected.resolve())
    assert all(
        item["sha256"] is not None
        for item in report["inputs"]
        if "fixtures/transport" in item["path"]
    )


def test_proof_import_failure_keeps_fixture_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def fail_only_portable_proofs(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "proofs" and level == 1 and globals and globals.get("__package__") == __package__:
            raise ImportError("forced portable proof import failure")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_only_portable_proofs)
    report = asyncio.run(driver.observe_core(driver._DEFAULT_ROOT))
    inventory = driver._inventory(driver._DEFAULT_ROOT)
    fixture_ids = {str(record["id"]) for record in inventory if record["kind"] == "fixture"}
    driver_ids = {str(record["id"]) for record in inventory if record["kind"] == "driver_assertion"}

    assert len(fixture_ids) == 96
    assert {case["id"] for case in report["cases"] if case["id"] in fixture_ids} == fixture_ids
    driver_rows = [case for case in report["cases"] if case["id"] in driver_ids]
    assert len(driver_rows) == len(driver_ids) == 6
    assert all(
        row["verdict"] == "error"
        and str(row["detail"]).startswith("core proof driver unavailable:")
        and row["evidence"] is None
        for row in driver_rows
    )
    assert len(report["cases"]) == len({case["id"] for case in report["cases"]}) == 102
    assert report["unexecuted"] == [] and report["counts"]["unexecuted"] == 0


def test_write_json_is_lf_and_preserves_member_order(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "report.json"
    driver.write_json(path, {"z": {"second": 2, "first": 1}, "a": [1, 2]})
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    assert list(json.loads(raw)) == ["z", "a"]
    assert list(json.loads(raw)["z"]) == ["second", "first"]


def test_write_reference_requires_a_lowercase_nonzero_revision(tmp_path: Path) -> None:
    output = tmp_path / "reference.json"
    with pytest.raises(SystemExit):
        driver.main(
            ["--portable-report", str(tmp_path / "report.json"), "--write-reference", "A" * 40]
        )
    assert not output.exists()


@pytest.mark.parametrize("revision", ["0" * 40, "A" * 40, "a" * 39, "g" * 40])
def test_reference_revision_requires_nonzero_lowercase_hex(revision: str) -> None:
    with pytest.raises(driver.DriverInputError, match="nonzero lowercase"):
        driver._reference_revision(revision)


def test_main_requires_an_output_mode() -> None:
    with pytest.raises(SystemExit):
        driver.main([])


def test_main_reference_mode_passes_raw_observation_and_optional_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    async def fake_writer(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["root"] = args[0]
        captured.update(kwargs)
        publisher = kwargs["publish_observation"]
        assert publisher is not None
        publisher({"development_observation": "UNRELEASED"})
        return {"development_observation": "UNRELEASED"}

    monkeypatch.setattr(driver, "write_reference", fake_writer)
    report = tmp_path / "report.json"
    revision = "a" * 40
    assert driver.main(["--write-reference", revision, "--portable-report", str(report)]) == 0
    assert captured["expected_revision"] == revision
    assert captured["repository_root"] == driver._REPOSITORY_ROOT
    assert captured["observe"] is driver.observe_core
    assert json.loads(report.read_text(encoding="utf-8")) == {
        "development_observation": "UNRELEASED"
    }


def test_reference_mode_report_rejects_checkout_and_selected_root_collisions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def should_not_run(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("writer must not run for an unsafe report destination")

    monkeypatch.setattr(driver, "write_reference", should_not_run)
    revision = "a" * 40
    with pytest.raises(SystemExit):
        driver.main(
            [
                "--write-reference",
                revision,
                "--portable-report",
                str(driver._DEFAULT_ROOT / "report.json"),
            ]
        )


def test_reference_mode_report_allows_new_a_scratch_but_rejects_canonical_aliases(
    tmp_path: Path,
) -> None:
    revision = "a" * 40
    manifest, environment = driver.reference_output_paths("a" * 40)
    allowed = driver._REPOSITORY_ROOT / ".tmp-tests" / "reference-report-safe.json"
    assert driver._safe_reference_report_path(
        allowed,
        selected_root=tmp_path / "selected",
        manifest_path=manifest,
        environment_path=environment,
    ) == allowed.resolve(strict=False)
    selected = tmp_path / "selected"
    selected.mkdir()
    a_alias = (
        driver._REPOSITORY_ROOT.parent
        / "outside"
        / ".."
        / driver._REPOSITORY_ROOT.name
        / "specification"
        / "report.json"
    )
    b_alias = selected.parent / "outside" / ".." / selected.name / "report.json"
    for path in (a_alias, b_alias):
        with pytest.raises(driver.DriverInputError, match="under"):
            driver._safe_reference_report_path(
                path,
                selected_root=selected,
                manifest_path=manifest,
                environment_path=environment,
            )
    selected = tmp_path / "specification"
    selected.mkdir()
    with pytest.raises(SystemExit):
        driver.main(
            [
                "--root",
                str(selected),
                "--write-reference",
                revision,
                "--portable-report",
                str(selected / "x.json"),
            ]
        )


def test_reference_report_is_new_only_and_rollback_is_owned(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    publisher = driver.reference_report_publisher(
        report,
        selected_root=tmp_path / "selected",
        manifest_path=tmp_path / "manifest.json",
        environment_path=tmp_path / "environment.json",
    )
    rollback = publisher({"z": 1})
    assert report.exists()
    rollback()
    assert not report.exists()
    report.write_text("sealed", encoding="utf-8")
    with pytest.raises(driver.DriverInputError, match="already exists"):
        publisher({"z": 1})


def test_selected_root_uses_trusted_validator_for_semantic_and_domain_failures(
    tmp_path: Path,
) -> None:
    selected = _copy_selected_core(tmp_path)
    assert driver._asset_problems(selected) == []
    fixture = next(
        path
        for path in selected.joinpath("fixtures/core-generation").rglob("*.json")
        if isinstance(json.loads(path.read_text(encoding="utf-8")).get("request"), dict)
        and isinstance(
            json.loads(path.read_text(encoding="utf-8"))["request"].get("sampling"), dict
        )
    )
    document = json.loads(fixture.read_text(encoding="utf-8"))
    document["request"]["sampling"]["temperature"] = float("nan")
    fixture.write_text(json.dumps(document), encoding="utf-8")
    assert driver._asset_problems(selected)

    selected = _copy_selected_core(tmp_path / "surrogate")
    fixture = next(selected.joinpath("fixtures/core-generation").rglob("*.json"))
    document = json.loads(fixture.read_text(encoding="utf-8"))
    document["description"] = chr(0xD800)
    fixture.write_text(json.dumps(document), encoding="utf-8")
    assert any("lone surrogate" in problem for problem in driver._asset_problems(selected))

    selected = _copy_selected_core(tmp_path / "schema")
    (selected / "schemas/fixture-v0.schema.json").write_text(
        '{"$ref":"missing"}', encoding="utf-8"
    )
    assert driver._asset_problems(selected)

    selected = _copy_selected_core(tmp_path / "marker")
    fixture = next(selected.joinpath("fixtures/core-generation").rglob("*.json"))
    document = json.loads(fixture.read_text(encoding="utf-8"))
    document["expected"] = {
        **document["expected"],
        "status": "observed",
        "calls": [
            {
                "model": "alpha",
                "role": "original",
                "mechanism": "prompt",
                "timeout_s": 1.0,
                "max_response_bytes": 1,
                "messages": [{"role": "system", "text": [{"$schema_prompt": True}]}],
            }
        ],
    }
    fixture.write_text(json.dumps(document), encoding="utf-8")
    assert driver._asset_problems(selected) == []
    document["expected"]["calls"][0]["messages"][0]["text"] = [{"$repair_feedback": True}]
    fixture.write_text(json.dumps(document), encoding="utf-8")
    assert any("repair_feedback" in problem for problem in driver._asset_problems(selected))


def test_present_transport_uses_trusted_base64_validation(tmp_path: Path) -> None:
    selected = _copy_selected_core(tmp_path)
    inventory = driver._load_json(selected / "inventories/core-generation-v0.json")
    record = next(
        item
        for item in inventory["cases"]
        if isinstance(item, dict)
        and str(item.get("path", "")).startswith(driver._TRANSPORT_PREFIX)
    )
    path = selected / str(record["path"]).removeprefix("specification/")
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "fixture_version": "0",
        "id": record["id"],
        "family": record["family"],
        "profile": "core-generation",
        "description": "base64 validation",
        "kind": "adapter",
        "input": {
            "adapter_config": {
                "provider_id": "openai-compat",
                "base_url": "https://fixture.invalid/v1",
                "api_key": "fixture-token",
                "headers": {},
                "timeout_s": 120,
            },
            "wire": {
                "model": "fixture-model",
                "messages": [{"role": "user", "text": "hello"}],
                "sampling": {},
                "mechanism": None,
                "stream": False,
                "timeout_s": 120,
                "max_response_bytes": 1048576,
            },
        },
        "responses": [{"status": 200, "headers": {}, "byte_chunks": [{"bytes": ""}]}],
        "expected": {"status": "to_be_observed"},
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    assert driver._asset_problems(selected) == []
    document["responses"][0]["byte_chunks"][0]["bytes"] = "!"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert any("strict base64" in problem for problem in driver._asset_problems(selected))


def test_plugin_reference_failure_never_calls_writer_and_writes_truthful_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_path = tmp_path / "failed.json"
    config = _Config(
        {
            "portable_report": report_path,
            "portable_root": driver._DEFAULT_ROOT,
            "write_reference": "a" * 40,
        }
    )

    async def should_not_write(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("failed pytest session must not invoke writer")

    async def observed(_root: Path) -> dict[str, Any]:
        return {"development_observation": "UNRELEASED"}

    monkeypatch.setattr(conftest, "write_reference", should_not_write)
    monkeypatch.setattr(conftest, "observe_core", observed)
    conftest.pytest_sessionfinish(_session(config), 1)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["development_observation"] == "UNRELEASED"
    assert report["pytest"] == {"exit_status": 1, "passed": False}


def test_plugin_reference_success_is_controller_only_and_passes_metadata_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_path = tmp_path / "success.json"
    config = _Config(
        {
            "portable_report": report_path,
            "portable_root": driver._DEFAULT_ROOT,
            "write_reference": "a" * 40,
        }
    )
    captured: dict[str, Any] = {}

    async def fake_writer(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["root"] = args[0]
        captured.update(kwargs)
        publisher = kwargs["publish_observation"]
        assert publisher is not None
        publisher({"development_observation": "UNRELEASED"})
        return {"development_observation": "UNRELEASED"}

    monkeypatch.setattr(conftest, "write_reference", fake_writer)
    conftest.pytest_sessionfinish(_session(config), pytest.ExitCode.OK)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["pytest"] == {"exit_status": pytest.ExitCode.OK, "passed": True}
    assert captured["observe"] is driver.observe_core

    worker = _Config(config.values, workerinput={})
    conftest.pytest_sessionfinish(_session(worker), pytest.ExitCode.OK)
    assert report_path.exists()


def test_plugin_reference_preflight_happens_before_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _Config(
        {
            "portable_report": None,
            "portable_root": driver._DEFAULT_ROOT,
            "write_reference": "a" * 40,
        }
    )
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        conftest, "preflight_reference", lambda *args, **kwargs: calls.append(kwargs)
    )
    conftest.pytest_sessionstart(_session(config))
    assert calls and calls[0]["expected_revision"] == "a" * 40


def test_real_pytest_plugin_reference_lifecycle_is_controller_only(
    monkeypatch: pytest.MonkeyPatch, pytester: pytest.Pytester, tmp_path: Path
) -> None:
    """Exercise actual parser/hooks while replacing only native writer seams."""
    source_path = os.pathsep.join(
        [str(driver._REPOSITORY_ROOT / "tests"), str(driver._REPOSITORY_ROOT / "src" / "python")]
    )
    monkeypatch.setenv("PYTHONPATH", source_path)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    marker = tmp_path / "lifecycle.txt"
    success_report = tmp_path / "success.json"
    failure_report = tmp_path / "failure.json"
    pytester.makeini("""
        [pytest]
        testpaths = .
        addopts = --confcutdir=.
    """)
    config_path = pytester.path / "tox.ini"
    pytester.makeconftest(
        f"""
from pathlib import Path
from testing.portable import conftest as portable

marker = Path({str(marker)!r})
selected_root = Path({str(driver._DEFAULT_ROOT)!r})
raw_observation = {{"development_observation": "UNRELEASED", "sentinel": "raw"}}

def event(value):
    prior = marker.read_text(encoding="utf-8") if marker.exists() else ""
    marker.write_text(prior + value + "\\n", encoding="utf-8")

def preflight(*args, **kwargs):
    event("startup")

async def observe(root):
    assert Path(root) == selected_root
    return raw_observation

async def writer(*args, **kwargs):
    event("writer")
    observed = await kwargs["observe"](args[0])
    assert observed is raw_observation
    assert observed["sentinel"] == "raw"
    publisher = kwargs["publish_observation"]
    if publisher is not None:
        publisher(observed)
    assert "pytest" not in raw_observation
    return observed

portable.preflight_reference = preflight
portable.observe_core = observe
portable.write_reference = writer
"""
    )
    success_test = pytester.makepyfile(
        test_lifecycle_success=f"""
from pathlib import Path

def test_body_runs_after_startup():
    marker = Path({str(marker)!r})
    assert marker.read_text(encoding="utf-8").splitlines() == ["startup"]
"""
    )
    success = pytester.runpytest_subprocess(
        "-c",
        str(config_path),
        "-p",
        "xdist.plugin",
        "-p",
        "testing.portable.conftest",
        "-n2",
        "--dist=loadfile",
        "--portable-root",
        str(driver._DEFAULT_ROOT),
        "--write-reference",
        "a" * 40,
        "--portable-report",
        str(success_report),
        str(success_test),
        timeout=60,
    )
    assert success.ret == 0
    assert marker.read_text(encoding="utf-8").splitlines() == ["startup", "writer"]
    success_observation = json.loads(success_report.read_text(encoding="utf-8"))
    assert success_observation["sentinel"] == "raw"
    assert success_observation["pytest"]["passed"] is True

    failure_test = pytester.makepyfile(
        test_lifecycle_failure="def test_body_fails():\n    assert False\n"
    )
    marker.unlink()
    failure = pytester.runpytest_subprocess(
        "-c",
        str(config_path),
        "-p",
        "testing.portable.conftest",
        "--portable-root",
        str(driver._DEFAULT_ROOT),
        "--write-reference",
        "a" * 40,
        "--portable-report",
        str(failure_report),
        str(failure_test),
        timeout=60,
    )
    assert failure.ret == 1
    assert marker.read_text(encoding="utf-8").splitlines() == ["startup"]
    assert json.loads(failure_report.read_text(encoding="utf-8"))["pytest"]["passed"] is False

    refusal_report = tmp_path / "refusal.json"
    marker.unlink()
    refusal = pytester.runpytest_subprocess(
        "-c",
        str(config_path),
        "-p",
        "testing.portable.conftest",
        "--portable-root",
        str(driver._DEFAULT_ROOT),
        "--write-reference",
        "A" * 40,
        "--portable-report",
        str(refusal_report),
        str(success_test),
        timeout=60,
    )
    assert refusal.ret == pytest.ExitCode.USAGE_ERROR
    assert not marker.exists() and not refusal_report.exists()


def test_missing_selected_transport_fixture_fails_closed(tmp_path: Path) -> None:
    selected = _copy_selected_core(tmp_path)
    transport = next(selected.joinpath("fixtures/transport").rglob("*.json"))
    transport.unlink()
    with pytest.raises(driver.DriverInputError, match="missing from selected root"):
        asyncio.run(driver.observe_core(selected))


def test_transport_hash_mutation_and_identity_are_bound(tmp_path: Path) -> None:
    selected = _copy_selected_core(tmp_path)
    inventory = driver._load_json(selected / "inventories/core-generation-v0.json")
    record = next(
        case
        for case in inventory["cases"]
        if str(case.get("path")).startswith("specification/fixtures/transport/")
    )
    destination = selected / str(record["path"]).removeprefix("specification/")
    before = next(
        item["sha256"]
        for item in driver._hashes(selected, driver._inventory(selected))
        if item["path"] == str(record["path"]).removeprefix("specification/")
    )
    document = json.loads(destination.read_text(encoding="utf-8"))
    document["description"] = "selected-root transport hash mutation"
    destination.write_text(json.dumps(document), encoding="utf-8")
    after = next(
        item["sha256"]
        for item in driver._hashes(selected, driver._inventory(selected))
        if item["path"] == str(record["path"]).removeprefix("specification/")
    )
    assert after != before
    document["id"] = "transport/openai-chat/wrong"
    destination.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(driver.DriverInputError, match="fixture ID is absent from fixture tree"):
        asyncio.run(driver.observe_core(selected))


def test_missing_selected_core_fixture_fails_closed(tmp_path: Path) -> None:
    selected = _copy_selected_core(tmp_path)
    (selected / "fixtures/core-generation/extraction/empty-response.json").unlink()
    with pytest.raises(driver.DriverInputError, match="missing from selected root"):
        asyncio.run(driver.observe_core(selected))


def test_proof_dispatcher_accepts_agreed_envelope() -> None:
    record = driver._check_recipe(
        {
            "id": "driver/assessment-completeness",
            "verdict": "pass",
            "detail": None,
            "evidence": {
                "recipe_ref": "driver/assessment-completeness",
                "observations": {"native": True},
            },
        },
        "driver/assessment-completeness",
        "driver/assessment-completeness",
    )
    assert record["evidence"]["recipe_ref"] == "driver/assessment-completeness"


@pytest.mark.parametrize(
    ("record", "error", "match"),
    [
        (None, driver.DriverInputError, "non-object"),
        (
            {
                "id": "driver/wrong",
                "verdict": "pass",
                "detail": None,
                "evidence": {"recipe_ref": "driver/assessment-completeness", "observations": {"native": True}},
            },
            driver.DriverInputError,
            "wrong identity",
        ),
        (
            {
                "id": "driver/assessment-completeness",
                "verdict": "pending",
                "detail": None,
                "evidence": None,
            },
            driver.DriverInputError,
            "invalid verdict",
        ),
        (
            {
                "id": "driver/assessment-completeness",
                "verdict": "pass",
                "detail": None,
                "evidence": None,
            },
            MissingEvidenceError,
            "lacks observations",
        ),
        (
            {
                "id": "driver/assessment-completeness",
                "verdict": "pass",
                "detail": None,
                "evidence": {"recipe_ref": "driver/wrong", "observations": {"native": True}},
            },
            MissingEvidenceError,
            "lacks observations",
        ),
        (
            {
                "id": "driver/assessment-completeness",
                "verdict": "pass",
                "detail": None,
                "evidence": {"recipe_ref": "driver/assessment-completeness", "observations": {}},
            },
            MissingEvidenceError,
            "lacks observations",
        ),
        (
            {
                "id": "driver/assessment-completeness",
                "verdict": "pass",
                "detail": None,
                "evidence": {
                    "recipe_ref": "driver/assessment-completeness",
                    "observations": {"native": float("nan")},
                },
            },
            ValueDomainError,
            "finite",
        ),
    ],
)
def test_proof_dispatcher_rejects_invalid_envelopes(
    record: object, error: type[Exception], match: str
) -> None:
    with pytest.raises(error, match=match):
        driver._check_recipe(record, "driver/assessment-completeness", "driver/assessment-completeness")


def _copy_selected_core(tmp_path: Path) -> Path:
    selected = tmp_path / "specification"
    for relative in driver._NORMATIVE_INPUTS:
        destination = selected / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((driver._DEFAULT_ROOT / relative).read_bytes())
    source_fixtures = driver._DEFAULT_ROOT / "fixtures"
    for source in source_fixtures.rglob("*.json"):
        destination = selected / "fixtures" / source.relative_to(source_fixtures)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    return selected


class _Config:
    def __init__(self, values: dict[str, Any], workerinput: dict[str, Any] | None = None) -> None:
        self.values = values
        if workerinput is not None:
            self.workerinput = workerinput

    def getoption(self, name: str) -> Any:
        return self.values[name]


def _session(config: _Config) -> pytest.Session:
    return cast(pytest.Session, SimpleNamespace(config=config))
