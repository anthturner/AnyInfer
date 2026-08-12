from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from anyinfer.errors import ConfigError
from anyinfer.local.provenance import ModelManifest, hash_model_weights, verify_model_manifest


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
