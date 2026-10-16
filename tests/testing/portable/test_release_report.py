"""Focused controls for private final portable report production."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import shutil
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from . import reference, release_report
from .driver import _EXTENSIONS, observe_core
from .reference import ReferencePreflightError

_ROOT = Path(__file__).parents[3]


class _Helper:
    class ReleaseBindingError(ValueError):
        pass

    def __init__(self) -> None:
        self.qualified: list[Mapping[str, Any]] = []

    def validate_successful_cases(
        self,
        rows: object,
        cases: Mapping[str, Mapping[str, Any]],
        **_kwargs: object,
    ) -> Mapping[str, Mapping[str, Any]]:
        if not isinstance(rows, list):
            raise self.ReleaseBindingError("rows missing")
        found = {str(row["id"]): row for row in rows if isinstance(row, Mapping)}
        if set(found) != set(cases):
            raise self.ReleaseBindingError("rows are incomplete")
        if any(row.get("verdict") not in {"pass", "extension"} for row in found.values()):
            raise self.ReleaseBindingError("failing row")
        if "driver/proof" in cases:
            driver = found.get("driver/proof")
            if not isinstance(driver, Mapping) or not isinstance(driver.get("evidence"), Mapping):
                raise self.ReleaseBindingError("driver evidence missing")
        return found

    def _qualify_report_mapping(self, report: Mapping[str, Any], _assets: Any) -> Mapping[str, Any]:
        self.qualified.append(report)
        if report["counts"].get("fail") or report["counts"].get("error"):
            raise self.ReleaseBindingError("failing counts")
        return report


def _assets(release_sha256: str = "a" * 64) -> Any:
    return SimpleNamespace(
        specification_root=Path("selected-root"),
        release={"release": "core-generation-v0"},
        release_sha256=release_sha256,
        file_hashes={"specification/core-generation.md": "b" * 64},
        cases_by_id={
            "fixture/pass": {"id": "fixture/pass", "kind": "fixture", "extension": None},
            "fixture/extension": {
                "id": "fixture/extension",
                "kind": "fixture",
                "extension": "schema.ref",
            },
            "driver/proof": {"id": "driver/proof", "kind": "driver_assertion", "extension": None},
        },
    )


def _observation() -> dict[str, Any]:
    return {
        "development_observation": "UNRELEASED",
        "report_v0_eligible": False,
        "unexecuted": [],
        "extensions": ["schema.ref"],
        "counts": {"extension": 1, "pass": 2, "unexecuted": 0},
        "cases": [
            {
                "id": "fixture/pass",
                "verdict": "pass",
                "detail": None,
                "observations": {"status": "observed"},
                "evidence": None,
            },
            {
                "id": "fixture/extension",
                "verdict": "extension",
                "detail": "eligible extension",
                "observations": {"status": "observed"},
                "evidence": {"native_outcome": {"none": True}, "adapter_entries": []},
            },
            {
                "id": "driver/proof",
                "verdict": "pass",
                "detail": None,
                "evidence": {"recipe_ref": "proof", "observations": {"actual": True}},
            },
        ],
    }


@contextlib.contextmanager
def _strict() -> Iterator[dict[str, Any]]:
    yield {"mode": "error"}


@pytest.mark.asyncio
async def test_release_report_maps_development_rows_and_validates_before_publish(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    (repository / "specification").mkdir(parents=True)
    output = repository / "specification/reports/python-aaaaaaa.json"
    helper, assets = _Helper(), _assets()
    calls = 0

    def preflight(*_args: Any, **_kwargs: Any) -> tuple[Path, Path, str, Any, _Helper]:
        nonlocal calls
        calls += 1
        return repository, output, "a" * 40, assets, helper

    published: list[tuple[Path, bytes]] = []
    monkeypatch.setattr(release_report, "_preflight", preflight)
    monkeypatch.setattr(release_report, "_implementation", lambda *_args: {"name": "anyinfer-python", "version": "0", "source_revision": "a" * 40, "driver_revision": "a" * 40, "runtime": "runtime", "os": "os", "dependencies": {}, "extensions": ["schema.ref"]})
    monkeypatch.setattr(release_report, "strict_reference_warnings", _strict)
    monkeypatch.setattr(release_report, "_prepare_output", lambda *_args: None)

    def publish(path: Path, payload: bytes) -> Any:
        published.append((path, payload))
        return lambda: None

    monkeypatch.setattr(release_report, "_publish_new", publish)

    report = await release_report.write_release_report(
        Path("selected-root"), observe=lambda _root: _await(_observation())
    )

    assert calls == 2 and len(helper.qualified) == 2
    assert report["counts"] == {"pass": 2, "fail": 0, "error": 0, "extension": 1}
    assert report["cases"][0] == {
        "id": "fixture/pass",
        "verdict": "pass",
        "detail": None,
        "evidence": None,
    }
    assert report["cases"][1]["evidence"] == _observation()["cases"][1]["evidence"]
    assert report["cases"][2]["evidence"] == _observation()["cases"][2]["evidence"]
    assert published and published[0][0] == output and published[0][1].endswith(b"\n")


@pytest.mark.asyncio
async def test_release_report_refuses_release_drift_and_cancellation_without_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    (repository / "specification").mkdir(parents=True)
    output = repository / "specification/reports/python-aaaaaaa.json"
    helper, before, after = _Helper(), _assets(), _assets("c" * 64)
    values = iter(((repository, output, "a" * 40, before, helper), (repository, output, "a" * 40, after, helper)))
    published: list[Path] = []
    monkeypatch.setattr(release_report, "_preflight", lambda *_args, **_kwargs: next(values))
    monkeypatch.setattr(release_report, "_implementation", lambda *_args: {"name": "anyinfer-python", "version": "0", "source_revision": "a" * 40, "driver_revision": "a" * 40, "runtime": "runtime", "os": "os", "dependencies": {}, "extensions": ["schema.ref"]})
    monkeypatch.setattr(release_report, "strict_reference_warnings", _strict)
    def publish(path: Path, _payload: bytes) -> None:
        published.append(path)

    monkeypatch.setattr(release_report, "_publish_new", publish)

    with pytest.raises(release_report.ReleaseReportError, match="frozen release changed"):
        await release_report.write_release_report(
            Path("selected-root"), observe=lambda _root: _await(_observation())
        )
    assert not published

    monkeypatch.setattr(release_report, "_preflight", lambda *_args, **_kwargs: (repository, output, "a" * 40, before, helper))

    async def cancelled(_root: Path) -> Mapping[str, Any]:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await release_report.write_release_report(Path("selected-root"), observe=cancelled)
    assert not published

    async def fatal(_root: Path) -> Mapping[str, Any]:
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        await release_report.write_release_report(Path("selected-root"), observe=fatal)
    assert not published


def test_preflight_refuses_dirty_runtime_and_existing_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    selected = tmp_path / "selected"
    (repository / "specification").mkdir(parents=True)
    selected.mkdir()
    monkeypatch.setattr(release_report, "_revision", lambda _root: "a" * 40)
    monkeypatch.setattr(release_report, "_assets", lambda *_args: (_Helper(), _assets()))
    monkeypatch.setattr(
        release_report,
        "_clean_status",
        lambda *_args: (_ for _ in ()).throw(ReferencePreflightError("dirty source")),
    )
    with pytest.raises(release_report.ReleaseReportError, match="dirty source"):
        release_report._preflight(selected, Path("releases/core-generation-v0.json"), repository)

    monkeypatch.setattr(release_report, "_clean_status", lambda *_args: None)
    monkeypatch.setattr(
        release_report,
        "_runtime_provenance",
        lambda *_args: (_ for _ in ()).throw(ReferencePreflightError("foreign import")),
    )
    with pytest.raises(release_report.ReleaseReportError, match="foreign import"):
        release_report._preflight(selected, Path("releases/core-generation-v0.json"), repository)

    output = release_report.release_report_path(repository, "a" * 40)
    output.parent.mkdir()
    output.write_text("sealed", encoding="utf-8")
    with pytest.raises(release_report.ReleaseReportError, match="already exists"):
        release_report._output_path(repository, "a" * 40)


@pytest.mark.asyncio
async def test_release_report_refuses_foreign_observer_before_observation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected = tmp_path / "selected"
    selected.mkdir()
    foreign = tmp_path / "foreign_observer.py"
    foreign.write_text("# deliberately foreign observer\n", encoding="utf-8")
    observer = _observer("testing.portable.foreign_observer", foreign)
    monkeypatch.setattr(release_report, "_clean_status", lambda *_args: None)
    monkeypatch.setattr(release_report, "_revision", lambda *_args: "a" * 40)
    monkeypatch.setattr(
        release_report, "_output_path", lambda *_args: tmp_path / "python-aaaaaaa.json"
    )
    monkeypatch.setattr(
        release_report,
        "_assets",
        lambda *_args: pytest.fail("foreign observer must refuse before release loading"),
    )

    with pytest.raises(release_report.ReleaseReportError, match="native observer import"):
        await release_report.write_release_report(
            selected,
            repository_root=_ROOT,
            observe=observer,
        )


@pytest.mark.asyncio
async def test_release_report_rechecks_foreign_cached_anyinfer_before_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected = tmp_path / "selected"
    selected.mkdir()
    helper, assets = _Helper(), _assets()
    published: list[Path] = []
    monkeypatch.setattr(release_report, "_clean_status", lambda *_args: None)
    monkeypatch.setattr(release_report, "_revision", lambda *_args: "a" * 40)
    monkeypatch.setattr(
        release_report, "_output_path", lambda *_args: tmp_path / "python-aaaaaaa.json"
    )
    monkeypatch.setattr(release_report, "_assets", lambda *_args: (helper, assets))
    monkeypatch.setattr(
        release_report,
        "_implementation",
        lambda *_args: {
            "name": "anyinfer-python",
            "version": "0",
            "source_revision": "a" * 40,
            "driver_revision": "a" * 40,
            "runtime": "runtime",
            "os": "os",
            "dependencies": {},
            "extensions": list(_EXTENSIONS),
        },
    )
    monkeypatch.setattr(release_report, "strict_reference_warnings", _strict)
    monkeypatch.setattr(release_report, "_publish_new", lambda path, _payload: published.append(path))
    foreign = tmp_path / "foreign_anyinfer.py"
    foreign.write_text("# deliberately foreign cached module\n", encoding="utf-8")

    async def contaminate(_root: Path) -> Mapping[str, Any]:
        monkeypatch.setitem(
            sys.modules,
            "anyinfer.foreign_release_report_probe",
            _module("anyinfer.foreign_release_report_probe", foreign),
        )
        return _observation()

    with pytest.raises(release_report.ReleaseReportError, match="outside the committed checkout"):
        await release_report.write_release_report(
            selected,
            repository_root=_ROOT,
            observe=contaminate,
        )
    assert not published


def test_runtime_provenance_refuses_tracked_anyinfer_module_in_portable_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrong_role = _ROOT / "tests/testing/portable/release_report.py"
    monkeypatch.setitem(
        sys.modules,
        "anyinfer._release_report_wrong_role",
        _file_module("anyinfer._release_report_wrong_role", wrong_role),
    )
    with pytest.raises(ReferencePreflightError, match="not under repository src/python"):
        reference._runtime_provenance(_ROOT, Path(release_report.__file__), observe_core)


def test_development_mapping_refuses_stale_counts_and_missing_driver_evidence() -> None:
    helper, assets = _Helper(), _assets()
    stale = _observation()
    stale["counts"] = {"extension": 0, "pass": 3, "unexecuted": 0}
    with pytest.raises(release_report.ReleaseReportError, match="stale"):
        release_report._development_rows(stale, assets, cast(Any, helper))

    missing = _observation()
    missing["cases"][2]["evidence"] = None
    with pytest.raises(release_report.ReleaseReportError, match="driver evidence missing"):
        release_report._development_rows(missing, assets, cast(Any, helper))


@pytest.mark.asyncio
async def test_actual_native_observation_maps_to_a_qualified_candidate_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    specification = tmp_path / "specification"
    shutil.copytree(_ROOT / "specification", specification)
    assets_module = _module("portable_release_assets", _ROOT / "scripts/portable_release_assets.py")
    monkeypatch.setitem(sys.modules, "portable_release_assets", assets_module)
    freeze = _module("freeze_release_actual_report", _ROOT / "scripts/freeze_release.py")
    assets = freeze.freeze_release(specification, "reference/python-fc53787.json", "candidate")
    monkeypatch.setattr(
        release_report,
        "_implementation",
        lambda *_args: {
            "name": "anyinfer-python",
            "version": "0",
            "source_revision": "a" * 40,
            "driver_revision": "a" * 40,
            "runtime": "runtime",
            "os": "os",
            "dependencies": {},
            "extensions": list(_EXTENSIONS),
        },
    )
    qualified: list[Mapping[str, Any]] = []
    real_qualify = assets_module._qualify_report_mapping

    def qualify(report: Mapping[str, Any], release_assets: Any) -> Any:
        qualified.append(report)
        return real_qualify(report, release_assets)

    monkeypatch.setattr(assets_module, "_qualify_report_mapping", qualify)

    report = release_report._report(
        await observe_core(specification), assets, assets_module, _ROOT, "a" * 40
    )

    assert len(report["cases"]) == 102
    assert report["counts"] == {"pass": 93, "fail": 0, "error": 0, "extension": 9}
    assert report["implementation"]["extensions"] == list(_EXTENSIONS)
    assert all("observations" not in row for row in report["cases"])
    extension_rows = [row for row in report["cases"] if row["verdict"] == "extension"]
    driver_rows = [
        row for row in report["cases"] if assets.cases_by_id[row["id"]]["kind"] == "driver_assertion"
    ]
    ordinary_fixture_rows = [
        row
        for row in report["cases"]
        if row["verdict"] == "pass" and assets.cases_by_id[row["id"]]["kind"] == "fixture"
    ]
    assert len(extension_rows) == 9 and all(isinstance(row["evidence"], Mapping) for row in extension_rows)
    assert len(driver_rows) == 6 and all(isinstance(row["evidence"], Mapping) for row in driver_rows)
    assert ordinary_fixture_rows and all(row["evidence"] is None for row in ordinary_fixture_rows)
    assert qualified == [report]
    assert assets_module.load_release_assets(specification, Path("releases/candidate.json"))


async def _await(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return value


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return module


def _file_module(name: str, path: Path) -> ModuleType:
    module = ModuleType(name)
    module.__file__ = str(path)
    return module


def _observer(name: str, path: Path) -> Any:
    namespace: dict[str, Any] = {"__name__": name}
    exec(
        compile(
            "async def observe(root):\n    return {}\n",
            str(path),
            "exec",
        ),
        namespace,
    )
    return namespace["observe"]
