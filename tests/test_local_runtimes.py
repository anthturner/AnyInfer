"""Runtime variants: manifests, the CUDA gate, backend selection, and installation.

No binary is ever fetched here. Archives are built in-memory and served through
``httpx2.MockTransport``, and the contract under test is that a manifest which fails *any*
check makes its variant simply not exist — advisory, never raising, exactly like hardware
detection.
"""

from __future__ import annotations

import hashlib
import io
import json
import platform
import zipfile
from pathlib import Path

import httpx2
import pytest

from anyinfer.errors import LocalRuntimeError
from anyinfer.local.backends import available_backends, select_backend
from anyinfer.local.hardware import Accelerator, HardwareProfile
from anyinfer.local.runtimes import (
    MANIFEST_NAME,
    RuntimeArtifact,
    RuntimeTable,
    check_cuda_preconditions,
    default_runtime_kind,
    install_runtime,
    installed_runtimes,
    load_runtime_table,
    read_manifest,
    remove_runtime,
)

GIB = 1024**3
BUILD = "b9999"


def _arch() -> str:
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        platform.machine().lower(), platform.machine().lower()
    )


def _profile(
    *, cuda: bool = False, capability: str = "8.9", driver: str = "580.0"
) -> HardwareProfile:
    accelerators: tuple[Accelerator, ...] = ()
    if cuda:
        accelerators = (
            Accelerator(
                kind="cuda",
                name="Test GPU",
                total_vram_bytes=24 * GIB,
                compute_capability=capability,
                driver_version=driver,
            ),
        )
    return HardwareProfile(
        os_name="linux", arch="x86_64", total_ram_bytes=32 * GIB, accelerators=accelerators
    )


def _install(
    root: Path,
    backend: str,
    *,
    build: str = BUILD,
    overrides: dict[str, object] | None = None,
) -> Path:
    """Write a plausible installed variant, with optional manifest corruptions."""
    directory = root / backend
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / "llama-server"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    manifest: dict[str, object] = {
        "format_version": 1,
        "backend": backend,
        "build": build,
        "architecture": _arch(),
        "executable": "llama-server",
    }
    manifest.update(overrides or {})
    (directory / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    return directory


# ---- the pinned table ------------------------------------------------------------------


def test_the_bundled_table_pins_a_build_and_real_digests() -> None:
    table = load_runtime_table()
    assert table.build
    assert table.artifacts
    assert all(len(a.sha256) == 64 for a in table.artifacts)
    assert all(a.url.startswith("https://") for a in table.artifacts)
    assert table.min_compute_capability > 0
    assert table.min_cuda_driver_major > 0


def test_every_platform_has_at_least_a_cpu_or_metal_build() -> None:
    table = load_runtime_table()
    platforms = {a.platform for a in table.artifacts}
    for key in platforms:
        backends = {a.backend for a in table.artifacts if a.platform == key}
        assert backends & {"cpu", "metal"}, f"{key} has no fallback build"


# ---- manifests --------------------------------------------------------------------------


def test_a_valid_manifest_makes_a_variant_discoverable(tmp_path: Path) -> None:
    _install(tmp_path, "vulkan")
    manifests = installed_runtimes(tmp_path)
    assert [m.backend for m in manifests] == ["vulkan"]
    assert manifests[0].executable.name == "llama-server"


@pytest.mark.parametrize(
    "corruption",
    [
        {"backend": "quantum"},
        {"architecture": "s390x-not-this-one"},
        {"executable": "../../../../bin/sh"},
        {"executable": "missing-binary"},
    ],
)
def test_a_manifest_that_fails_any_check_means_the_variant_does_not_exist(
    tmp_path: Path, corruption: dict[str, object]
) -> None:
    directory = _install(tmp_path, "cuda", overrides=corruption)
    assert read_manifest(directory) is None
    assert installed_runtimes(tmp_path) == []


def test_a_stale_build_is_rejected_when_a_build_is_demanded(tmp_path: Path) -> None:
    directory = _install(tmp_path, "vulkan", build="b0001")
    assert read_manifest(directory) is not None
    assert read_manifest(directory, build=BUILD) is None


def test_a_missing_manifest_is_not_an_error(tmp_path: Path) -> None:
    (tmp_path / "vulkan").mkdir()
    assert read_manifest(tmp_path / "vulkan") is None
    assert installed_runtimes(tmp_path) == []


# ---- backend selection --------------------------------------------------------------------


def test_cuda_wins_when_installed_and_nvidia_is_present(tmp_path: Path) -> None:
    _install(tmp_path, "cuda")
    _install(tmp_path, "vulkan")
    chosen = select_backend(_profile(cuda=True), runtime_root=tmp_path)
    assert chosen is not None
    assert chosen.kind == "cuda"


def test_an_explicit_installed_runtime_overrides_the_automatic_ranking(tmp_path: Path) -> None:
    _install(tmp_path, "cuda")
    _install(tmp_path, "vulkan")
    chosen = select_backend(_profile(cuda=True), preferred="vulkan", runtime_root=tmp_path)
    assert chosen is not None
    assert chosen.kind == "vulkan"


def test_an_explicit_missing_runtime_is_actionable(tmp_path: Path) -> None:
    _install(tmp_path, "vulkan")
    with pytest.raises(LocalRuntimeError, match=r"cpu.*not installed"):
        select_backend(_profile(), preferred="cpu", runtime_root=tmp_path)


def test_deleting_the_cuda_manifest_falls_back_to_vulkan_and_says_so(tmp_path: Path) -> None:
    _install(tmp_path, "cuda")
    _install(tmp_path, "vulkan")
    (tmp_path / "cuda" / MANIFEST_NAME).unlink()

    chosen = select_backend(_profile(cuda=True), runtime_root=tmp_path)
    assert chosen is not None
    assert chosen.kind == "vulkan"
    assert "no cuda runtime is installed" in chosen.detail.lower()


def test_with_only_cpu_installed_the_fallback_is_stated(tmp_path: Path) -> None:
    _install(tmp_path, "cpu")
    chosen = select_backend(_profile(cuda=True), runtime_root=tmp_path)
    assert chosen is not None
    assert chosen.kind == "cpu"
    assert "cuda" in chosen.detail.lower()


def test_a_manifest_validated_variant_outranks_a_name_inferred_one(tmp_path: Path) -> None:
    _install(tmp_path, "vulkan")
    other = tmp_path / "elsewhere" / "vulkan"
    other.mkdir(parents=True)
    (other / "llama-server").write_text("#!/bin/sh\n", encoding="utf-8")

    found = available_backends(search_paths=[other], hardware=_profile(), runtime_root=tmp_path)
    assert found[0].detail.startswith("installed runtime variant")


def test_no_installed_runtime_means_no_backend(tmp_path: Path) -> None:
    assert (
        available_backends(hardware=_profile(), runtime_root=tmp_path, include_runtime_root=True)
        == []
        or select_backend(_profile(), runtime_root=tmp_path) is not None
    )


# ---- the CUDA gate --------------------------------------------------------------------------


def _table(**overrides: object) -> RuntimeTable:
    base: dict[str, object] = {
        "build": BUILD,
        "cuda_toolkit": "13.3",
        "min_cuda_driver_major": 580,
        "min_compute_capability": 7.5,
        "warn_below_vram_bytes": 6 * GIB,
        "artifacts": (),
    }
    base.update(overrides)
    return RuntimeTable(**base)  # type: ignore[arg-type]


def test_the_cuda_gate_refuses_a_machine_with_no_nvidia_device() -> None:
    blocking, _ = check_cuda_preconditions(_profile(), _table())
    assert blocking
    assert "no NVIDIA device" in blocking[0]


def test_the_cuda_gate_refuses_an_old_compute_capability() -> None:
    blocking, _ = check_cuda_preconditions(_profile(cuda=True, capability="7.0"), _table())
    assert any("compute capability" in reason for reason in blocking)


def test_the_cuda_gate_refuses_an_old_driver() -> None:
    blocking, _ = check_cuda_preconditions(_profile(cuda=True, driver="535.1"), _table())
    assert any("driver" in reason for reason in blocking)


def test_an_unreported_compute_capability_blocks_rather_than_assumes() -> None:
    profile = HardwareProfile(
        os_name="linux",
        arch="x86_64",
        total_ram_bytes=32 * GIB,
        accelerators=(Accelerator(kind="cuda", name="Mystery", driver_version="580.0"),),
    )
    blocking, _ = check_cuda_preconditions(profile, _table())
    assert any("did not report a compute capability" in reason for reason in blocking)


def test_a_capable_machine_passes_the_gate() -> None:
    blocking, warnings = check_cuda_preconditions(_profile(cuda=True), _table())
    assert blocking == ()
    assert warnings == ()


def test_installing_cuda_without_a_profile_refuses_rather_than_guessing() -> None:
    with pytest.raises(LocalRuntimeError, match="hardware profile"):
        install_runtime("cuda", table=_table())


def test_installing_cuda_on_an_unsupported_machine_refuses_and_names_the_alternative() -> None:
    with pytest.raises(LocalRuntimeError) as excinfo:
        install_runtime("cuda", hardware=_profile(), table=_table())
    assert "Vulkan" in excinfo.value.hint


# ---- default choice ---------------------------------------------------------------------------


def test_the_default_variant_is_never_cuda() -> None:
    """A several-hundred-megabyte download is a decision a user makes, not the library."""
    assert default_runtime_kind(_profile(cuda=True)) != "cuda"


# Both cases below describe a non-macOS machine, and `default_runtime_kind` asks
# `platform.system()` rather than `sys.platform` for that (see the note on the function:
# `sys.platform` is narrowed by mypy and makes the branch below it read as dead code).
# Patch the call the function actually makes, or these silently assert nothing on Linux
# and Windows while failing outright on a macOS runner.
def test_a_gpu_machine_defaults_to_the_vendor_neutral_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("anyinfer.local.runtimes.platform.system", lambda: "Linux")
    assert default_runtime_kind(_profile(cuda=True)) == "vulkan"


def test_a_cpu_only_machine_defaults_to_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("anyinfer.local.runtimes.platform.system", lambda: "Linux")
    assert default_runtime_kind(_profile()) == "cpu"


# ---- installation ------------------------------------------------------------------------------


def _zip_archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("build/bin/llama-server", "#!/bin/sh\necho hi\n")
        bundle.writestr("build/bin/libggml.so", "binary")
    return buffer.getvalue()


def _hostile_archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("../../escaped.sh", "pwned")
    return buffer.getvalue()


def _serving(payload: bytes) -> httpx2.Client:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=payload, headers={"content-length": str(len(payload))})

    return httpx2.Client(transport=httpx2.MockTransport(handler))


def _artifact(payload: bytes) -> RuntimeArtifact:
    from anyinfer.local.runtimes import platform_key

    return RuntimeArtifact(
        platform=platform_key(),
        backend="vulkan",
        filename="llama-vulkan.zip",
        url="https://host.invalid/llama-vulkan.zip",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def test_installing_unpacks_verifies_and_writes_a_manifest(tmp_path: Path) -> None:
    payload = _zip_archive()
    table = _table(artifacts=(_artifact(payload),))
    report = install_runtime(
        "vulkan",
        hardware=_profile(),
        root=tmp_path,
        table=table,
        client=_serving(payload),
    )
    assert report.executable.exists()
    assert report.executable.name == "llama-server"
    assert read_manifest(report.directory, build=BUILD) is not None
    assert not (tmp_path / ".staging").exists() or not any((tmp_path / ".staging").iterdir())


def test_a_second_install_reuses_a_valid_one(tmp_path: Path) -> None:
    payload = _zip_archive()
    table = _table(artifacts=(_artifact(payload),))
    install_runtime(
        "vulkan", hardware=_profile(), root=tmp_path, table=table, client=_serving(payload)
    )
    again = install_runtime(
        "vulkan", hardware=_profile(), root=tmp_path, table=table, client=_serving(payload)
    )
    assert again.reused
    assert again.downloaded_bytes == 0


def test_an_archive_that_escapes_its_directory_is_refused(tmp_path: Path) -> None:
    payload = _hostile_archive()
    table = _table(artifacts=(_artifact(payload),))
    with pytest.raises(LocalRuntimeError, match="outside the runtime directory"):
        install_runtime(
            "vulkan", hardware=_profile(), root=tmp_path, table=table, client=_serving(payload)
        )
    assert not (tmp_path.parent / "escaped.sh").exists()


def test_a_backend_with_no_build_for_this_platform_says_what_is_available(tmp_path: Path) -> None:
    payload = _zip_archive()
    table = _table(artifacts=(_artifact(payload),))
    with pytest.raises(LocalRuntimeError) as excinfo:
        install_runtime("rocm", hardware=_profile(), root=tmp_path, table=table)
    assert "vulkan" in excinfo.value.hint


def test_removing_a_runtime_reports_whether_anything_went(tmp_path: Path) -> None:
    _install(tmp_path, "vulkan")
    assert remove_runtime("vulkan", root=tmp_path) is True
    assert remove_runtime("vulkan", root=tmp_path) is False
