"""Tier 4: model-weight provenance verification.

Tier 3 (`attestation.py`) proves *where* a prompt ran. It says nothing about *what* ran
inside it — whether the model weights are the exact, certified artifact a vendor shipped,
or something swapped or tampered with in place. This module extends the manifest
discipline `local/runtimes.py` already applies to *runtime* builds (`runtime.json` pins
architecture, backend, and build id) to the *model weights* themselves: a content hash and
signature check against a vendor-published manifest.

**This module verifies signatures. It never signs anything, and never handles a private
key.** Each vendor signs their own model manifests with their own keys — AnyInfer never
operates a shared signing service or takes custody of vendor key material, mirroring how
`runtimes.py`'s own manifests are already owned by whoever built the runtime, not by
AnyInfer. A vendor's own tooling (e.g. `cryptography`'s `Ed25519PrivateKey` directly, or
any signing process they already trust) produces the signature; this module only checks it.

**Only a Tier 4 claim when it runs inside Tier 3's attested boundary.** A hash-and-signature
check on an unattested host is a real, valid check, but a *weaker and different* claim —
verifying that the file on disk matches a signature, with no guarantee about who else
could have read or swapped it before or during the check. Marketing that as "Tier 4" would
misrepresent the guarantee `plans/TIERED_ENCRYPTED_PLANS.md` §4a defines; the field this
module populates (`ConfidentialExecutionStatus.model_verified`) is documented accordingly
— a caller must additionally check `end_to_end` before treating it as the full claim.

**Requires the `attest` extra** (``pip install anyinfer[attest]``) for the signature
verification dependency (`cryptography`) — never imported at module scope, so importing
`anyinfer.local` never pulls it in for callers who don't use Tier 4 at all.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import ConfigError

__all__ = ["ModelManifest", "hash_model_weights", "verify_model_manifest"]

_ATTEST_EXTRA_HINT = (
    "install the 'attest' extra: pip install anyinfer[attest]"
)


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """A vendor-signed record of what one set of model weights should hash to.

    Attributes:
        model_id: The vendor's identifier for this model variant.
        weight_hash: SHA-256 of the weight file (or, for a multi-file snapshot, of the
            sorted ``relative_path:sha256`` listing — see `hash_model_weights`), as a hex
            string.
        vendor_key_id: Which vendor key this manifest was signed with, for a caller
            managing more than one registered vendor public key.
        signed_at: ISO-8601 signing timestamp, for audit trails.
        signature: The vendor's signature over this manifest's canonical payload.
    """

    model_id: str
    weight_hash: str
    vendor_key_id: str
    signed_at: str
    signature: bytes

    def _payload(self) -> bytes:
        """The exact bytes the signature covers — canonical, so signing and verifying
        never drift from a formatting difference.
        """  # noqa: D205
        payload = {
            "model_id": self.model_id,
            "weight_hash": self.weight_hash,
            "vendor_key_id": self.vendor_key_id,
            "signed_at": self.signed_at,
        }
        return json.dumps(payload, sort_keys=True).encode("utf-8")

    def to_dict(self) -> dict[str, Any]:
        """A JSON-safe mapping — the on-disk manifest format."""
        return {
            "model_id": self.model_id,
            "weight_hash": self.weight_hash,
            "vendor_key_id": self.vendor_key_id,
            "signed_at": self.signed_at,
            "signature": self.signature.hex(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelManifest:
        """Load a manifest previously written by `to_dict`."""
        try:
            return cls(
                model_id=str(data["model_id"]),
                weight_hash=str(data["weight_hash"]),
                vendor_key_id=str(data["vendor_key_id"]),
                signed_at=str(data["signed_at"]),
                signature=bytes.fromhex(data["signature"]),
            )
        except (KeyError, ValueError) as exc:
            raise ConfigError(f"malformed model manifest: {exc}") from exc


def hash_model_weights(path: Path) -> str:
    r"""Hash the weights at `path`, hex-encoded SHA-256.

    A single file (the GGUF case) is hashed directly. A directory (an `hf_repo` snapshot)
    is hashed as the SHA-256 of a sorted ``relative_path:sha256\n`` listing over every
    file it contains — deterministic regardless of filesystem enumeration order, and
    sensitive to every file's content, name, and presence.
    """
    if path.is_file():
        return _hash_file(path)
    if path.is_dir():
        lines = []
        for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
            rel = file_path.relative_to(path).as_posix()
            lines.append(f"{rel}:{_hash_file(file_path)}")
        return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    raise ConfigError(f"model weights not found at {path}")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_manifest(
    manifest: ModelManifest, *, weights_path: Path, vendor_public_key: bytes
) -> bool:
    """Verify a manifest's signature and that it matches the weights on disk.

    Args:
        manifest: The vendor-signed manifest to check.
        weights_path: Where the model weights actually are — re-hashed and compared
            against `manifest.weight_hash`; a manifest is never trusted for the hash
            alone, since that would make the signature pointless.
        vendor_public_key: The registered vendor's Ed25519 public key.

    Returns:
        `True` only when the signature verifies against `vendor_public_key` **and** the
        recomputed hash of `weights_path` matches `manifest.weight_hash` exactly.

    Raises:
        anyinfer.errors.ConfigError: The `attest` extra is not installed.
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise ConfigError(
            f"model manifest verification needs the 'cryptography' package: {_ATTEST_EXTRA_HINT}"
        ) from exc

    try:
        Ed25519PublicKey.from_public_bytes(vendor_public_key).verify(
            manifest.signature, manifest._payload()
        )
    except InvalidSignature:
        return False

    actual_hash = hash_model_weights(weights_path)
    return actual_hash == manifest.weight_hash
