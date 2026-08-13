from __future__ import annotations

from pathlib import Path

import pytest

from anyinfer.local import attestation as attest
from anyinfer.local.backends import Backend
from anyinfer.local.store import ResolvedModel


def _backend(kind: str) -> Backend:
    return Backend(kind=kind, binary=Path("/usr/bin/llama-server"))  # type: ignore[arg-type]


def _model(*, n_gpu_layers: int) -> ResolvedModel:
    return ResolvedModel(
        entry_id="m",
        kind="gguf",
        path=Path("/models/m.gguf"),
        launch_hints={"n_gpu_layers": n_gpu_layers},
    )


def _no_devices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dev = tmp_path / "dev"
    dev.mkdir(exist_ok=True)
    monkeypatch.setattr(attest, "_DEV_ROOT", dev)
    monkeypatch.setattr(attest, "_run", lambda command: None)
    # Detection is gated on _IS_LINUX (see test_cpu_tee_detection_is_linux_only); force it
    # so these device-node fixtures behave the same on every CI runner OS, not just Linux.
    monkeypatch.setattr(attest, "_IS_LINUX", True)
    return dev


def _isolate_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(attest.ATTESTATION_CACHE_BYPASS_ENV, raising=False)
    monkeypatch.delenv(attest.ATTESTATION_CACHE_REFRESH_ENV, raising=False)
    monkeypatch.setattr(attest, "cache_path", lambda: tmp_path / "attestation.json")


# ---- CPU TEE detection -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("device_name", "expected"),
    [
        ("sev-guest", "sev-snp"),
        ("tdx_guest", "tdx"),
        ("nsm", "nitro"),
        ("sgx_enclave", "sgx"),
    ],
)
def test_each_cpu_tee_kind_is_detected_from_its_device_node(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, device_name: str, expected: str
) -> None:
    dev = _no_devices(tmp_path, monkeypatch)
    (dev / device_name).touch()
    assert attest._detect_cpu_tee() == expected


def test_no_device_nodes_means_no_cpu_tee(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _no_devices(tmp_path, monkeypatch)
    assert attest._detect_cpu_tee() is None


def test_cpu_tee_detection_is_linux_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dev = _no_devices(tmp_path, monkeypatch)
    (dev / "sev-guest").touch()
    monkeypatch.setattr(attest, "_IS_LINUX", False)
    assert attest._detect_cpu_tee() is None


# ---- GPU CC detection -------------------------------------------------------------------


def test_gpu_cc_capable_and_enabled_parses_nvidia_smi_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        attest, "_run", lambda command: "CC capable: TRUE\nCC status: ON\n"
    )
    capable, enabled = attest._detect_gpu_cc()
    assert capable is True
    assert enabled is True


def test_gpu_cc_capable_but_not_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        attest, "_run", lambda command: "CC capable: TRUE\nCC status: OFF\n"
    )
    capable, enabled = attest._detect_gpu_cc()
    assert capable is True
    assert enabled is False


def test_no_nvidia_smi_means_not_capable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attest, "_run", lambda command: None)
    assert attest._detect_gpu_cc() == (False, False)


def test_unparseable_nvidia_smi_output_means_not_detected_not_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attest, "_run", lambda command: "some future format we don't know")
    assert attest._detect_gpu_cc() == (False, False)


# ---- end_to_end combination matrix -------------------------------------------------------


def _status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    cpu_tee: str | None,
    gpu_cc_capable: bool = False,
    gpu_cc_enabled: bool = False,
    gpu_offload_required: bool,
) -> attest.ConfidentialExecutionStatus:
    dev = _no_devices(tmp_path, monkeypatch)
    device_by_kind = {"sev-snp": "sev-guest", "tdx": "tdx_guest", "nitro": "nsm", "sgx": "sgx_enclave"}
    if cpu_tee is not None:
        (dev / device_by_kind[cpu_tee]).touch()

    def fake_run(command: list[str]) -> str | None:
        if gpu_cc_capable or gpu_cc_enabled:
            cap = "TRUE" if gpu_cc_capable else "FALSE"
            status = "ON" if gpu_cc_enabled else "OFF"
            return f"CC capable: {cap}\nCC status: {status}\n"
        return None

    monkeypatch.setattr(attest, "_run", fake_run)
    _isolate_cache(monkeypatch, tmp_path)
    backend = _backend("cpu" if not gpu_offload_required else "cuda")
    model = _model(n_gpu_layers=1 if gpu_offload_required else 0)
    return attest.confidential_execution_status(backend=backend, model=model, use_cache=False)


def test_no_cpu_tee_is_never_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    status = _status(monkeypatch, tmp_path, cpu_tee=None, gpu_offload_required=False)
    assert status.end_to_end is False


def test_cpu_only_with_attested_tee_is_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    status = _status(monkeypatch, tmp_path, cpu_tee="sev-snp", gpu_offload_required=False)
    assert status.end_to_end is True
    assert status.gpu_offload_required is False


def test_cpu_only_with_tdx_is_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    status = _status(monkeypatch, tmp_path, cpu_tee="tdx", gpu_offload_required=False)
    assert status.end_to_end is True


@pytest.mark.parametrize("kind", ["nitro", "sgx"])
def test_nitro_and_sgx_are_detected_but_not_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    status = _status(monkeypatch, tmp_path, cpu_tee=kind, gpu_offload_required=False)
    assert status.cpu_tee == kind
    assert status.end_to_end is False


def test_gpu_offload_with_cc_enabled_gpu_is_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    status = _status(
        monkeypatch,
        tmp_path,
        cpu_tee="sev-snp",
        gpu_cc_capable=True,
        gpu_cc_enabled=True,
        gpu_offload_required=True,
    )
    assert status.end_to_end is True


def test_gpu_offload_with_cc_capable_but_disabled_gpu_is_not_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    status = _status(
        monkeypatch,
        tmp_path,
        cpu_tee="sev-snp",
        gpu_cc_capable=True,
        gpu_cc_enabled=False,
        gpu_offload_required=True,
    )
    assert status.end_to_end is False


def test_gpu_offload_with_a_non_cc_gpu_is_not_end_to_end_even_with_a_cpu_tee(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    status = _status(
        monkeypatch,
        tmp_path,
        cpu_tee="sev-snp",
        gpu_cc_capable=False,
        gpu_cc_enabled=False,
        gpu_offload_required=True,
    )
    assert status.end_to_end is False


def test_missing_model_is_conservative_about_gpu_offload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No model chosen yet + a GPU-capable backend -> assume offload, don't over-promise."""
    dev = _no_devices(tmp_path, monkeypatch)
    (dev / "sev-guest").touch()
    monkeypatch.setattr(attest, "_run", lambda command: None)  # no CC-capable GPU
    _isolate_cache(monkeypatch, tmp_path)
    status = attest.confidential_execution_status(
        backend=_backend("cuda"), model=None, use_cache=False
    )
    assert status.gpu_offload_required is True
    assert status.end_to_end is False  # no CC GPU detected, so it must not over-promise


def test_missing_model_with_a_cpu_only_backend_is_not_conservative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dev = _no_devices(tmp_path, monkeypatch)
    (dev / "sev-guest").touch()
    _isolate_cache(monkeypatch, tmp_path)
    status = attest.confidential_execution_status(
        backend=_backend("cpu"), model=None, use_cache=False
    )
    assert status.gpu_offload_required is False
    assert status.end_to_end is True


# ---- caching --------------------------------------------------------------------------


def test_cache_hit_avoids_a_second_probe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dev = _no_devices(tmp_path, monkeypatch)
    (dev / "sev-guest").touch()
    _isolate_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(attest, "_probe_signature", lambda: "sig-a")

    first = attest.confidential_execution_status(backend=_backend("cpu"), model=None)
    assert (tmp_path / "attestation.json").exists()

    calls: list[int] = []

    def counting_probe(**kwargs: object) -> attest.ConfidentialExecutionStatus:
        calls.append(1)
        return first

    monkeypatch.setattr(attest, "_probe", counting_probe)
    attest.confidential_execution_status(backend=_backend("cpu"), model=None)
    assert not calls, "a matching signature must be served from cache"


def test_cache_refresh_env_forces_a_reprobe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dev = _no_devices(tmp_path, monkeypatch)
    (dev / "sev-guest").touch()
    _isolate_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(attest, "_probe_signature", lambda: "same-signature")

    first = attest.confidential_execution_status(backend=_backend("cpu"), model=None)
    assert first.cpu_tee == "sev-snp"

    # Same signature, but the underlying device changed (a real signature would also
    # change here — this isolates the refresh-env behavior from signature computation).
    dev2 = tmp_path / "dev2"
    dev2.mkdir()
    (dev2 / "tdx_guest").touch()
    monkeypatch.setattr(attest, "_DEV_ROOT", dev2)

    unrefreshed = attest.confidential_execution_status(backend=_backend("cpu"), model=None)
    assert unrefreshed.cpu_tee == "sev-snp", "a matching signature must be served from cache"

    monkeypatch.setenv(attest.ATTESTATION_CACHE_REFRESH_ENV, "1")
    refreshed = attest.confidential_execution_status(backend=_backend("cpu"), model=None)
    assert refreshed.cpu_tee == "tdx"


def test_cache_bypass_env_never_writes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _no_devices(tmp_path, monkeypatch)
    _isolate_cache(monkeypatch, tmp_path)
    monkeypatch.setenv(attest.ATTESTATION_CACHE_BYPASS_ENV, "1")
    attest.confidential_execution_status(backend=_backend("cpu"), model=None)
    assert not (tmp_path / "attestation.json").exists()


# ---- Tier 4 overlay (model_verified) ----------------------------------------------------


def _signed_model(tmp_path: Path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    from anyinfer.local.provenance import ModelManifest, hash_model_weights

    weights = tmp_path / "weights.gguf"
    weights.write_bytes(b"real weights")
    model = _model(n_gpu_layers=0)
    model = type(model)(
        entry_id=model.entry_id,
        kind=model.kind,
        path=weights,
        launch_hints=model.launch_hints,
    )

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    private_bytes = private_key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, encryption_algorithm=NoEncryption()
    )
    unsigned = ModelManifest(
        model_id="m", weight_hash=hash_model_weights(weights), vendor_key_id="k1",
        signed_at="2026-08-12T00:00:00Z", signature=b"",
    )
    signature = Ed25519PrivateKey.from_private_bytes(private_bytes).sign(unsigned._payload())
    manifest = type(unsigned)(
        model_id=unsigned.model_id,
        weight_hash=unsigned.weight_hash,
        vendor_key_id=unsigned.vendor_key_id,
        signed_at=unsigned.signed_at,
        signature=signature,
    )
    return model, manifest, public_key, weights


def test_model_verified_is_none_when_no_manifest_supplied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dev = _no_devices(tmp_path, monkeypatch)
    (dev / "sev-guest").touch()
    _isolate_cache(monkeypatch, tmp_path)
    status = attest.confidential_execution_status(backend=_backend("cpu"), model=None)
    assert status.model_verified is None


def test_model_verified_true_for_a_genuine_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dev = _no_devices(tmp_path, monkeypatch)
    (dev / "sev-guest").touch()
    _isolate_cache(monkeypatch, tmp_path)
    model, manifest, public_key, _ = _signed_model(tmp_path)

    status = attest.confidential_execution_status(
        backend=_backend("cpu"), model=model, manifest=manifest, vendor_public_key=public_key
    )
    assert status.model_verified is True
    assert status.end_to_end is True


def test_model_verified_is_never_served_stale_from_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A tampered weight file must be caught on the very next call, cache or not."""
    dev = _no_devices(tmp_path, monkeypatch)
    (dev / "sev-guest").touch()
    _isolate_cache(monkeypatch, tmp_path)
    model, manifest, public_key, weights = _signed_model(tmp_path)

    first = attest.confidential_execution_status(
        backend=_backend("cpu"), model=model, manifest=manifest, vendor_public_key=public_key
    )
    assert first.model_verified is True
    assert (tmp_path / "attestation.json").exists(), "the hardware portion is still cached"

    weights.write_bytes(b"tampered weights")
    second = attest.confidential_execution_status(
        backend=_backend("cpu"), model=model, manifest=manifest, vendor_public_key=public_key
    )
    assert second.model_verified is False
