"""Private clean-source preflight and environment evidence for reference observations."""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.metadata
import importlib.util
import inspect
import json
import re
import subprocess
import sys
import warnings
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType, ModuleType
from typing import Any, NoReturn

from jsonschema.validators import validator_for

_HEX = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_PACKAGES = frozenset(
    {
        "anyinfer",
        "httpx2",
        "jsonschema",
        "jsonschema-specifications",
        "referencing",
        "attrs",
        "rpds-py",
    }
)
_SCHEMAS = (
    "fixture-v0.schema.json",
    "transport-v0.schema.json",
    "inventory-v0.schema.json",
    "report-v0.schema.json",
)
_REGISTRY = importlib.import_module("jsonschema_specifications").REGISTRY
_RUNTIME_PREFIXES = (
    "anyinfer",
    "httpx",
    "httpx2",
    "jsonschema",
    "jsonschema_specifications",
    "referencing",
    "attr",
    "attrs",
    "rpds",
)
_PORTABLE_NAMESPACES = ("portable", "testing.portable", "tests.testing.portable")


class ReferencePreflightError(ValueError):
    """A clean reference environment cannot be established safely."""


@dataclass(frozen=True, slots=True)
class ReferencePreflight:
    """Validated clean execution and selected-data binding, with no output written."""

    revision: str
    repository_root: Path
    specification_root: Path
    manifest_path: Path
    environment_path: Path
    input_hashes: Mapping[str, str]


def _fail(message: str) -> NoReturn:
    raise ReferencePreflightError(message)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _inside(root: Path, path: Path, label: str, *, file: bool = True) -> Path:
    lexical_root, lexical_path = root.absolute(), path.absolute()
    try:
        relative = lexical_path.relative_to(lexical_root)
    except ValueError:
        _fail(f"{label} escapes its root")
    current = lexical_root
    for part in relative.parts:
        current /= part
        if current.is_symlink() or bool(getattr(current, "is_junction", lambda: False)()):
            _fail(f"{label} uses a link/reparse point")
    resolved = lexical_path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        _fail(f"{label} escapes its root")
    if file and not resolved.is_file():
        _fail(f"{label} is missing")
    return resolved


def _safe_root(path: Path, label: str) -> Path:
    lexical = path.absolute()
    ancestors = (*tuple(reversed(lexical.parents)), lexical)
    for ancestor in ancestors:
        if ancestor.is_symlink() or bool(getattr(ancestor, "is_junction", lambda: False)()):
            _fail(f"{label} uses a link/reparse point")
    if not lexical.is_dir():
        _fail(f"{label} is missing")
    return lexical.resolve()


def _git(repository_root: Path, *args: str) -> str:
    try:
        run = subprocess.run(
            ["git", *args],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as error:
        _fail(f"cannot inspect repository state: {error}")
    return run.stdout


def _validator_module() -> ModuleType:
    path = Path(__file__).parents[3] / "scripts" / "validate_fixtures.py"
    spec = importlib.util.spec_from_file_location("_portable_reference_validator", path)
    if spec is None or spec.loader is None:
        _fail("trusted fixture validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release_assets_module() -> ModuleType:
    path = Path(__file__).parents[3] / "scripts" / "portable_release_assets.py"
    spec = importlib.util.spec_from_file_location("_portable_reference_release_assets", path)
    if spec is None or spec.loader is None:
        _fail("trusted release-asset loader is unavailable")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(spec.name)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous
        raise
    return module


def _bind_external_assets(root: Path, expected_revision: str, hashes: Mapping[str, str]) -> None:
    try:
        loader = _release_assets_module()
        assets = loader.load_release_assets(root, Path("releases/core-generation-v0.json"))
    except Exception as error:
        _fail(f"external selected root has no trusted frozen release binding: {error}")
    reference = assets.reference_manifest
    if reference.get("reference_run_revision") != expected_revision:
        _fail("external frozen release reference revision does not match executable source A")
    frozen = assets.file_hashes
    if any(frozen.get(path) != digest for path, digest in hashes.items()):
        _fail("external selected input hashes do not match its frozen release binding")


def _inventory_paths(root: Path, validator: ModuleType) -> tuple[list[Path], dict[str, str]]:
    inventory_path = _inside(root, root / "inventories/core-generation-v0.json", "inventory")
    try:
        inventory = validator.read_json(inventory_path)
    except (OSError, ValueError) as error:
        _fail(f"cannot read selected inventory: {error}")
    if not isinstance(inventory, dict) or not isinstance(inventory.get("cases"), list):
        _fail("selected inventory is invalid")
    fixtures: list[Path] = []
    seen: set[str] = set()
    for case in inventory["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            _fail("selected inventory contains an invalid case")
        if case["id"] in seen:
            _fail("selected inventory contains duplicate case IDs")
        seen.add(case["id"])
        if case.get("kind") == "fixture":
            raw = case.get("path")
            if not isinstance(raw, str) or "\\" in raw:
                _fail("selected inventory fixture path is unsafe")
            parts = PurePosixPath(raw).parts
            if len(parts) < 4 or parts[:2] != ("specification", "fixtures") or ".." in parts:
                _fail("selected inventory fixture path is non-canonical")
            fixtures.append(_inside(root, root.joinpath(*parts[1:]), "selected fixture"))
        elif case.get("kind") != "driver_assertion" or case.get("path") is not None:
            _fail("selected inventory driver assertion is invalid")
    problems = validator.validate(
        root / "fixtures", coverage=True, specification_root=root, fixture_paths=fixtures
    )
    if problems:
        _fail("selected corpus validation failed: " + "; ".join(problems))
    required = [
        Path("README.md"),
        Path("core-generation.md"),
        Path("MAINTENANCE.md"),
        Path("inventories/core-generation-v0.json"),
        *(Path("schemas") / name for name in _SCHEMAS),
        *(item.relative_to(root) for item in fixtures),
    ]
    hashes: dict[str, str] = {}
    for relative in required:
        path = _inside(root, root / relative, f"required selected input {relative.as_posix()}")
        hashes[f"specification/{relative.as_posix()}"] = _hash(path)
        if path.suffix == ".json":
            document = validator.read_json(path)
            if (
                isinstance(document, dict)
                and document.get("expected", {}).get("status") == "to_be_observed"
            ):
                _fail(f"selected corpus has pending expectation: {relative.as_posix()}")
    return fixtures, dict(sorted(hashes.items()))


def _output_path(root: Path, value: Path, name: str) -> Path:
    candidate, expected = value.absolute(), (root / "reference" / name).absolute()
    if candidate != expected:
        _fail("reference outputs must use the exact canonical generated filenames")
    _inside(root, candidate.parent, "reference output directory", file=False)
    if candidate.is_symlink() or bool(getattr(candidate, "is_junction", lambda: False)()):
        _fail("reference output uses a link/reparse point")
    if candidate.exists():
        _fail("reference output would overwrite an existing sealed or required input")
    return candidate


def _clean_status(repository: Path, output_paths: set[Path]) -> None:
    status = _git(repository, "status", "--porcelain=v1", "-z")
    allowed = {path.relative_to(repository).as_posix() for path in output_paths}
    for entry in (item for item in status.split("\0") if item):
        if len(entry) < 4 or entry[2] != " " or "R" in entry[:2] or "C" in entry[:2]:
            _fail("repository status has an unsafe porcelain record")
        if entry[3:].replace("\\", "/") not in allowed:
            _fail("required executable or corpus inputs are dirty or untracked")


def _require_tracked(repository: Path, path: Path, label: str) -> None:
    try:
        relative = path.relative_to(repository).as_posix()
    except ValueError:
        _fail(f"{label} is outside the committed checkout")
    _git(repository, "ls-files", "--error-unmatch", "--", relative)


def _runtime_import_paths(repository: Path, driver_path: Path) -> tuple[Path, Path]:
    """Bind the loaded AnyInfer package and an executing portable driver to one checkout."""
    import anyinfer

    anyinfer_path = _inside(repository, Path(anyinfer.__file__), "anyinfer import")
    portable_driver = _inside(repository, driver_path, "portable driver import")
    if not anyinfer_path.is_relative_to(repository / "src" / "python"):
        _fail("captured AnyInfer import is not under repository src/python")
    if not portable_driver.is_relative_to(repository / "tests" / "testing" / "portable"):
        _fail("captured private driver import is not under repository portable tests")
    _require_tracked(repository, anyinfer_path, "anyinfer import")
    _require_tracked(repository, portable_driver, "portable driver import")
    return anyinfer_path, portable_driver


def _loaded_runtime_modules(repository: Path) -> dict[str, dict[str, str]]:
    """Bind every loaded runtime/private module that can affect portable execution."""
    modules: dict[str, dict[str, str]] = {}
    root = repository.resolve()
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, "__file__", None)
        if not isinstance(path, str):
            continue
        candidate = Path(path).resolve()
        private_name = any(
            name == item or name.startswith(f"{item}.") for item in _PORTABLE_NAMESPACES
        )
        private = candidate.is_relative_to(root / "tests" / "testing" / "portable")
        anyinfer_module = name == "anyinfer" or name.startswith("anyinfer.")
        required_runtime = any(
            name == prefix or name.startswith(f"{prefix}.") for prefix in _RUNTIME_PREFIXES
        )
        if anyinfer_module or private_name or private:
            if not candidate.is_file() or not candidate.is_relative_to(root):
                _fail(f"loaded runtime module {name} is outside the committed checkout")
            if anyinfer_module and not candidate.is_relative_to(root / "src" / "python"):
                _fail(f"loaded AnyInfer module {name} is not under repository src/python")
            if private_name and not private:
                _fail(f"loaded private module {name} is outside portable tests")
            _require_tracked(root, candidate, f"loaded runtime module {name}")
        if required_runtime or private:
            if not candidate.is_file():
                _fail(f"loaded runtime module {name} has no hashable code file")
            modules[name] = {"path": str(candidate), "sha256": _hash(candidate)}
    for name, path in {
        "trusted_validator": root / "scripts" / "validate_fixtures.py",
        "trusted_release_assets": root / "scripts" / "portable_release_assets.py",
    }.items():
        _require_tracked(root, path, name)
        modules[name] = {"path": str(path), "sha256": _hash(path)}
    if not modules:
        _fail("no loaded AnyInfer runtime modules have a committed source identity")
    return modules


def _runtime_provenance(
    repository: Path, driver_path: Path, observer: object | None = None
) -> tuple[Path, Path, dict[str, dict[str, str]]]:
    """Require the executing observer and loaded runtime code to remain checkout-bound."""
    anyinfer_path, portable_driver = _runtime_import_paths(repository, driver_path)
    if observer is not None:
        if not callable(observer):
            _fail("native observer is not callable")
        source = inspect.getsourcefile(observer)
        module_name = getattr(observer, "__module__", None)
        if not isinstance(source, str) or not isinstance(module_name, str):
            _fail("native observer has no source module identity")
        observer_path = _inside(repository, Path(source), "native observer import")
        if not observer_path.is_relative_to(repository / "tests" / "testing" / "portable"):
            _fail("native observer import is not under repository portable tests")
        if not any(
            module_name == item or module_name.startswith(f"{item}.")
            for item in _PORTABLE_NAMESPACES
        ):
            _fail("native observer module is not a private portable module")
        _require_tracked(repository, observer_path, "native observer import")
    return anyinfer_path, portable_driver, _loaded_runtime_modules(repository)


def preflight_reference(
    root: Path,
    *,
    expected_revision: str,
    output_manifest: Path,
    output_environment: Path,
    repository_root: Path,
) -> ReferencePreflight:
    """Fail closed before reference-output writing or native reference execution."""
    if not _REVISION.fullmatch(expected_revision) or expected_revision == "0" * 40:
        _fail("expected revision must be a nonzero 40-character lowercase Git revision")
    repository = _safe_root(repository_root, "repository root")
    specification = _safe_root(root, "selected specification root")
    if _git(repository, "rev-parse", "HEAD").strip() != expected_revision:
        _fail("checked-out source revision does not match expected reference revision")
    manifest_name = f"python-{expected_revision[:7]}.json"
    environment_name = f"python-{expected_revision[:7]}.environment.json"
    executable_specification = repository / "specification"
    manifest = _output_path(executable_specification, output_manifest, manifest_name)
    environment = _output_path(executable_specification, output_environment, environment_name)
    _clean_status(repository, {manifest, environment})
    validator = _validator_module()
    _fixtures, hashes = _inventory_paths(specification, validator)
    if specification != (repository / "specification").resolve():
        _bind_external_assets(specification, expected_revision, hashes)
    _runtime_import_paths(repository, Path(__file__))
    return ReferencePreflight(
        expected_revision,
        repository,
        specification,
        manifest,
        environment,
        MappingProxyType(dict(hashes)),
    )


@contextlib.contextmanager
def strict_reference_warnings() -> Iterator[dict[str, Any]]:
    """Scope and expose exactly the reference warning policy without changing ambient state."""
    with warnings.catch_warnings():
        warnings.resetwarnings()
        warnings.simplefilter("error")
        policy = {
            "mode": "error",
            "filters": [
                {
                    "action": "error",
                    "message": None,
                    "category": "builtins.Warning",
                    "module": None,
                    "lineno": 0,
                }
            ],
        }
        if len(warnings.filters) != 1 or warnings.filters[0][0] != "error":
            _fail("strict reference warning policy was not established")
        yield policy


def _distribution_lock() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for distribution in importlib.metadata.distributions():
        metadata = distribution.metadata
        try:
            name = metadata["Name"]
        except KeyError:
            _fail("installed distribution has no canonical name")
        if not name:
            _fail("installed distribution has no canonical name")
        canonical = _canonical_name(str(name))
        metadata_path = _distribution_file(distribution, {"METADATA", "PKG-INFO"})
        if metadata_path is None:
            _fail(f"installed distribution {canonical} lacks METADATA/PKG-INFO")
        if canonical in result:
            _fail(f"installed distributions collide after canonicalization: {canonical}")

        result[canonical] = {
            "version": distribution.version,
            "requires": sorted(distribution.requires or ()),
            "metadata_sha256": _hash(metadata_path),
            "record_sha256": _optional_distribution_hash(distribution, "RECORD"),
            "direct_url_sha256": _optional_distribution_hash(distribution, "direct_url.json"),
        }
    if not _REQUIRED_PACKAGES.issubset(result):
        _fail("complete installed lock omits required runtime distributions")
    return dict(sorted(result.items()))


def _distribution_file(
    distribution: importlib.metadata.Distribution, names: set[str]
) -> Path | None:
    for file in distribution.files or ():
        if file.name in names:
            candidate = Path(str(distribution.locate_file(file)))
            if candidate.is_file():
                return candidate
    return None


def _optional_distribution_hash(
    distribution: importlib.metadata.Distribution, name: str
) -> str | None:
    path = _distribution_file(distribution, {name})
    return _hash(path) if path is not None else None


def _identity(value: object) -> str:
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}:{value!r}"


def _validator_identity() -> dict[str, Any]:
    selected = validator_for({"$schema": "https://json-schema.org/draft/2020-12/schema"})
    instance = selected({})
    resources = []
    for uri in sorted(str(item) for item in _REGISTRY):
        content = _REGISTRY[uri].contents
        encoded = json.dumps(
            content, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        resources.append({"uri": uri, "sha256": hashlib.sha256(encoded).hexdigest()})
    if not resources:
        _fail("JSON Schema registry exposes no resource identities")
    return {
        "selected": f"{selected.__module__}.{selected.__qualname__}",
        "defaults": {
            "type_checker": _identity(selected.TYPE_CHECKER),
            "format_checker": _identity(instance.format_checker)
            if instance.format_checker is not None
            else "none",
            "class_format_checker": _identity(selected.FORMAT_CHECKER),
            "id_of": f"{selected.ID_OF.__module__}.{selected.ID_OF.__qualname__}",
            "meta_schema": selected.META_SCHEMA.get("$id"),
        },
        "resource_identities": resources,
    }


def capture_reference_environment(preflight: ReferencePreflight) -> dict[str, Any]:
    """Capture actual runtime evidence after a successful clean reference preflight."""
    anyinfer_path, driver_path, modules = _runtime_provenance(
        preflight.repository_root, Path(__file__)
    )
    imports = {
        "anyinfer": {
            "path": str(anyinfer_path),
            "sha256": _hash(anyinfer_path),
        },
        "driver": {"path": str(driver_path), "sha256": _hash(driver_path)},
    }
    with strict_reference_warnings() as warning_policy:
        return {
            "environment_version": "0",
            "reference_run_revision": preflight.revision,
            "interpreter": {
                "implementation": sys.implementation.name,
                "version": sys.version,
                "executable": str(Path(sys.executable).resolve()),
                "executable_sha256": _hash(Path(sys.executable)),
            },
            "dependency_lock": _distribution_lock(),
            "imports": imports,
            "loaded_modules": modules,
            "validator": _validator_identity(),
            "warning_policy": warning_policy,
        }
