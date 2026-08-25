from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from anyinfer.errors import ConfidentialExecutionError, ConfigError
from anyinfer.local.provenance import (
    ModelManifest,
    WeightsProvenance,
    hash_model_weights,
    open_verified_weights,
    verify_model_manifest,
)


def _keypair() -> tuple[bytes, bytes]:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, encryption_algorithm=NoEncryption()
    )
    public_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private_bytes, public_bytes


def _sign(manifest_without_signature: ModelManifest, private_key_bytes: bytes) -> bytes:
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    return private_key.sign(manifest_without_signature._payload())


def _manifest(model_id: str, weight_hash: str, private_key: bytes) -> ModelManifest:
    unsigned = ModelManifest(
        model_id=model_id,
        weight_hash=weight_hash,
        vendor_key_id="k1",
        signed_at="2026-08-12T00:00:00Z",
        signature=b"",
    )
    signature = _sign(unsigned, private_key)
    return ModelManifest(
        model_id=unsigned.model_id,
        weight_hash=unsigned.weight_hash,
        vendor_key_id=unsigned.vendor_key_id,
        signed_at=unsigned.signed_at,
        signature=signature,
    )


def test_hash_model_weights_is_stable_for_a_single_file(tmp_path: Path) -> None:
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"fake weights content")
    assert hash_model_weights(weights) == hash_model_weights(weights)


def test_hash_model_weights_changes_when_content_changes(tmp_path: Path) -> None:
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"version one")
    first = hash_model_weights(weights)
    weights.write_bytes(b"version two")
    assert hash_model_weights(weights) != first


def test_hash_model_weights_over_a_directory_is_deterministic(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "a.bin").write_bytes(b"aaa")
    (snapshot / "b.bin").write_bytes(b"bbb")
    first = hash_model_weights(snapshot)

    other = tmp_path / "rebuilt"
    other.mkdir()
    (other / "b.bin").write_bytes(b"bbb")
    (other / "a.bin").write_bytes(b"aaa")
    assert hash_model_weights(other) == first


def test_hash_model_weights_directory_is_sensitive_to_a_swapped_file(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "a.bin").write_bytes(b"aaa")
    first = hash_model_weights(snapshot)
    (snapshot / "a.bin").write_bytes(b"tampered")
    assert hash_model_weights(snapshot) != first


def test_missing_weights_path_raises() -> None:
    with pytest.raises(ConfigError):
        hash_model_weights(Path("/nonexistent/path/does/not/exist"))


def test_verify_model_manifest_succeeds_for_a_genuine_manifest(tmp_path: Path) -> None:
    private_key, public_key = _keypair()
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"real weights")
    manifest = _manifest("acme-7b", hash_model_weights(weights), private_key)

    assert verify_model_manifest(manifest, weights_path=weights, vendor_public_key=public_key)


def test_verify_model_manifest_rejects_tampered_weights(tmp_path: Path) -> None:
    private_key, public_key = _keypair()
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"real weights")
    manifest = _manifest("acme-7b", hash_model_weights(weights), private_key)

    weights.write_bytes(b"tampered weights")
    assert not verify_model_manifest(manifest, weights_path=weights, vendor_public_key=public_key)


def test_verify_model_manifest_rejects_a_manifest_signed_by_a_different_key(
    tmp_path: Path,
) -> None:
    _, real_public_key = _keypair()
    other_private_key, _ = _keypair()
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"real weights")
    forged = _manifest("acme-7b", hash_model_weights(weights), other_private_key)

    assert not verify_model_manifest(
        forged, weights_path=weights, vendor_public_key=real_public_key
    )


def test_manifest_json_round_trip() -> None:
    private_key, _ = _keypair()
    manifest = _manifest("acme-7b", "deadbeef", private_key)
    restored = ModelManifest.from_dict(json.loads(json.dumps(manifest.to_dict())))
    assert restored == manifest


def test_from_dict_rejects_a_malformed_manifest() -> None:
    with pytest.raises(ConfigError):
        ModelManifest.from_dict({"model_id": "x"})


# ---- verification bound to the bytes that get loaded ---------------------------------


def _provenance(weights: Path) -> tuple[WeightsProvenance, bytes]:
    private_key, public_key = _keypair()
    manifest = _manifest("m", hash_model_weights(weights), private_key)
    return WeightsProvenance(manifest=manifest, vendor_public_key=public_key), public_key


def test_open_verified_weights_agrees_with_the_path_based_digest(tmp_path: Path) -> None:
    """Manifests signed before descriptor-based verification existed must still verify."""
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"weights" * 1000)
    provenance, _ = _provenance(weights)

    with open_verified_weights(provenance, weights) as verified:
        assert verified.digest == hash_model_weights(weights)


def test_open_verified_weights_agrees_on_a_directory_snapshot(tmp_path: Path) -> None:
    weights = tmp_path / "snapshot"
    (weights / "nested").mkdir(parents=True)
    (weights / "a.safetensors").write_bytes(b"aaa" * 500)
    (weights / "nested" / "b.json").write_text('{"k": 1}')
    provenance, _ = _provenance(weights)

    with open_verified_weights(provenance, weights) as verified:
        assert verified.digest == hash_model_weights(weights)


def test_a_file_replaced_after_verification_is_caught(tmp_path: Path) -> None:
    """The whole point: a rename over the path is a different inode, and is refused.

    This is the swap the old path-based check could not see — it hashed, returned True,
    and whatever happened to the path afterwards was invisible.
    """
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"genuine" * 1000)
    provenance, _ = _provenance(weights)

    with open_verified_weights(provenance, weights) as verified:
        verified.assert_unchanged()  # still the same file

        impostor = tmp_path / "impostor.gguf"
        impostor.write_bytes(b"genuine" * 1000)  # identical bytes, different inode
        impostor.replace(weights)

        with pytest.raises(ConfidentialExecutionError, match="replaced after verification"):
            verified.assert_unchanged()


def test_a_file_truncated_after_verification_is_caught(tmp_path: Path) -> None:
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"genuine" * 1000)
    provenance, _ = _provenance(weights)

    with open_verified_weights(provenance, weights) as verified:
        with weights.open("r+b") as handle:
            handle.truncate(10)
        with pytest.raises(ConfidentialExecutionError, match="changed size"):
            verified.assert_unchanged()


def test_a_file_deleted_after_verification_is_caught(tmp_path: Path) -> None:
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"genuine" * 1000)
    provenance, _ = _provenance(weights)

    with open_verified_weights(provenance, weights) as verified:
        weights.unlink()
        with pytest.raises(ConfidentialExecutionError, match="no longer readable"):
            verified.assert_unchanged()


def test_tampered_weights_never_open_at_all(tmp_path: Path) -> None:
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"genuine" * 1000)
    provenance, _ = _provenance(weights)
    weights.write_bytes(b"tampered" * 1000)

    with pytest.raises(ConfidentialExecutionError, match="do not match the signed manifest"):
        with open_verified_weights(provenance, weights):
            pytest.fail("must not yield for weights that do not match")


def test_a_manifest_signed_by_another_key_never_opens(tmp_path: Path) -> None:
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"genuine" * 1000)
    provenance, _ = _provenance(weights)
    other_private, _ = _keypair()
    forged = WeightsProvenance(
        manifest=_manifest("m", hash_model_weights(weights), other_private),
        vendor_public_key=provenance.vendor_public_key,
    )

    with pytest.raises(ConfidentialExecutionError, match="not signed by the expected"):
        with open_verified_weights(forged, weights):
            pytest.fail("must not yield for a forged manifest")


def test_descriptors_are_released_when_the_block_exits(tmp_path: Path) -> None:
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"genuine" * 1000)
    provenance, _ = _provenance(weights)

    with open_verified_weights(provenance, weights) as verified:
        held = verified._fds
    for fd in held:
        with pytest.raises(OSError):
            os.fstat(fd)
