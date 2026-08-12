"""Vendor-issued, signed, time-boxed entitlement blobs gating `TemplateVault` decryption.

**Hybrid entitlement, decided 2026-08-12 (see `plans/TIERED_ENCRYPTED_PLANS.md` §2):**
the default artifact is a signed, time-boxed license blob validated entirely offline — no
network call is required to decrypt a template, so a deployment works air-gapped. Online
revocation (`sealed_template.TemplateVault`'s `revocation_checker`) is a separate, opt-in
layer on top, never a replacement for offline validation.

Signing uses Ed25519 (via `cryptography`): small keys and signatures, no parameter choices
to get wrong, and it is the same primitive family this project already depends on through
the `vertex` extra for JWT signing — not a new algorithm class for this codebase.
"""

from __future__ import annotations

import base64
import calendar
import json
import time
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .errors import LicenseError

__all__ = [
    "LicenseBlob",
    "RevocationChecker",
    "generate_signing_keypair",
    "issue_license",
    "verify_license",
]


class RevocationChecker(Protocol):
    """Checks whether a deployment's license has been revoked.

    Returns `True` (not revoked), `False` (revoked), or raises when the check could not
    be completed at all (network unreachable, etc.) — `TemplateVault` treats a raised
    exception the same as an unreachable check, never as "not revoked."
    """

    def __call__(self, deployment_id: str) -> bool:
        """Return whether `deployment_id` is currently entitled (not revoked)."""
        ...


@dataclass(frozen=True, slots=True)
class LicenseBlob:
    """A verified license's contents, returned by `verify_license` on success.

    Attributes:
        deployment_id: The vendor-assigned identifier this license was issued for — the
            key `RevocationChecker` deny-lists are keyed on.
        issued_at: ISO-8601 issuance timestamp.
        expires_at: ISO-8601 expiry timestamp; `verify_license` rejects an expired blob.
    """

    deployment_id: str
    issued_at: str
    expires_at: str


def generate_signing_keypair() -> tuple[bytes, bytes]:
    """Generate an Ed25519 keypair for license issuance.

    Returns:
        `(private_key_bytes, public_key_bytes)`, both raw 32-byte encodings. The private
        key is the vendor's signing secret — it never ships in a client bundle; only
        `public_key_bytes` does, for `verify_license`.
    """
    private_key = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return private_bytes, public_bytes


def issue_license(
    deployment_id: str, *, private_key: bytes, valid_days: int
) -> bytes:
    """Issue a signed, time-boxed license blob for one deployment.

    Args:
        deployment_id: Identifier the issued license is bound to.
        private_key: The vendor's Ed25519 private key (`generate_signing_keypair()`'s
            first element).
        valid_days: How many days from now the license remains valid.

    Returns:
        An opaque signed blob: pass it to the deployment for `TemplateVault` to consume.
    """
    now = time.time()
    payload = {
        "deployment_id": deployment_id,
        "issued_at": _iso(now),
        "expires_at": _iso(now + valid_days * 86400),
    }
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    signature = Ed25519PrivateKey.from_private_bytes(private_key).sign(payload_bytes)
    return _b64(payload_bytes) + b"." + _b64(signature)


def verify_license(blob: bytes, *, public_key: bytes) -> LicenseBlob:
    """Verify a license blob's signature and expiry.

    Raises:
        LicenseError: The blob is malformed, its signature does not verify against
            `public_key`, or it has expired.
    """
    try:
        payload_b64, signature_b64 = blob.split(b".", 1)
        payload_bytes = _unb64(payload_b64)
        signature = _unb64(signature_b64)
    except ValueError as exc:
        raise LicenseError(f"license blob is malformed: {exc}") from exc

    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload_bytes)
    except InvalidSignature as exc:
        raise LicenseError("license blob signature does not verify") from exc

    try:
        payload = json.loads(payload_bytes)
        deployment_id = str(payload["deployment_id"])
        issued_at = str(payload["issued_at"])
        expires_at = str(payload["expires_at"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise LicenseError(f"license blob payload is malformed: {exc}") from exc

    if _parse_iso(expires_at) < time.time():
        raise LicenseError(
            f"license for deployment {deployment_id!r} expired at {expires_at}"
        )
    return LicenseBlob(deployment_id=deployment_id, issued_at=issued_at, expires_at=expires_at)


def _iso(epoch_seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_seconds))


def _parse_iso(text: str) -> float:
    return float(calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")))


def _b64(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data)


def _unb64(data: bytes) -> bytes:
    return base64.urlsafe_b64decode(data)
