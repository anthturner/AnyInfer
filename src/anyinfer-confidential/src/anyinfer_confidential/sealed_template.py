"""Tier 1: `SealedTemplate` — encrypted-at-rest prompt assets.

**What this protects against:** static extraction of a template's plaintext — someone
unzipping the app bundle, grepping the binary, or reading the on-disk asset. **What it
does not protect against:** live network capture, memory inspection while the process
runs, or a debugger attached to a live render. That ceiling is deliberate and must be
stated up front — see `plans/TIERED_ENCRYPTED_PLANS.md` §2 for the full reasoning.

A template is authored as plaintext, sealed at build time into an `EncryptedTemplate`
asset (AES-256-GCM, keyed by a rotatable `key_id`), and shipped inside the vendor's
client bundle. At runtime, `TemplateVault.render()` decrypts a template into memory only
immediately before rendering it, and best-effort-zeroes the decrypted buffer afterward —
"best effort" because CPython strings are immutable and the interpreter may retain copies
the caller has no handle to; this module never claims stronger than that.

Decryption is gated on a vendor-issued, signed, time-boxed `LicenseBlob`. This is a
second, independent motivation beyond confidentiality: an install without a valid,
unexpired, correctly-signed license cannot produce a single rendered prompt. See
`license.py` for issuance and verification.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import RevokedLicenseError, SealError, TemplateDecryptionError
from .license import LicenseBlob, RevocationChecker, verify_license

__all__ = [
    "EncryptedTemplate",
    "KeyRing",
    "TemplateVault",
    "generate_key",
    "seal_template",
]

_NONCE_BYTES = 12
"""AES-GCM's standard nonce size; a fresh nonce is drawn for every seal call."""


def generate_key() -> bytes:
    """Generate a fresh 256-bit AES-GCM key for sealing templates."""
    return AESGCM.generate_key(bit_length=256)


@dataclass(frozen=True, slots=True)
class EncryptedTemplate:
    """One sealed template asset — safe to ship inside a client bundle as-is.

    Attributes:
        template_id: Caller-assigned identifier, unique within one vendor's asset set.
        key_id: Which key in the `TemplateVault`'s `KeyRing` decrypts this asset — the
            hook key rotation is built on: re-sealing under a new `key_id` invalidates
            nothing already shipped until the old key is dropped from the ring.
        nonce: The AES-GCM nonce used for this specific seal (never reused per key).
        ciphertext: The encrypted template text, including the GCM authentication tag.
        sealed_at: ISO-8601 timestamp of when this asset was sealed, for audit trails.
    """

    template_id: str
    key_id: str
    nonce: bytes
    ciphertext: bytes
    sealed_at: str

    def to_dict(self) -> dict[str, Any]:
        """A JSON-safe mapping — the on-disk asset format."""
        return {
            "template_id": self.template_id,
            "key_id": self.key_id,
            "nonce": self.nonce.hex(),
            "ciphertext": self.ciphertext.hex(),
            "sealed_at": self.sealed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EncryptedTemplate:
        """Load an asset previously written by `to_dict`."""
        try:
            return cls(
                template_id=str(data["template_id"]),
                key_id=str(data["key_id"]),
                nonce=bytes.fromhex(data["nonce"]),
                ciphertext=bytes.fromhex(data["ciphertext"]),
                sealed_at=str(data["sealed_at"]),
            )
        except (KeyError, ValueError) as exc:
            raise SealError(f"malformed encrypted-template asset: {exc}") from exc

    def to_json(self) -> str:
        """Serialize to the JSON asset format `seal_template()`'s CLI step writes."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, text: str) -> EncryptedTemplate:
        """Parse the JSON asset format."""
        return cls.from_dict(json.loads(text))


def seal_template(
    plaintext: str, *, key: bytes, template_id: str, key_id: str
) -> EncryptedTemplate:
    """Encrypt one template's plaintext into a shippable `EncryptedTemplate` asset.

    This is the build-time step (`anyinfer-confidential seal`): plaintext never reaches
    the shipped asset, only its ciphertext does.

    Args:
        plaintext: The template source (e.g. containing ``{slot}`` placeholders).
        key: A 256-bit AES-GCM key, from `generate_key()`.
        template_id: Identifier this template will be looked up by at render time.
        key_id: Identifier for `key`, so a `TemplateVault`'s `KeyRing` can select the
            right key without guessing — required for key rotation to work at all.

    Returns:
        The sealed asset, safe to write to disk or bundle into a client build.
    """
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return EncryptedTemplate(
        template_id=template_id,
        key_id=key_id,
        nonce=nonce,
        ciphertext=ciphertext,
        sealed_at=_now_iso(),
    )


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class KeyRing:
    """Maps `key_id` to decryption key — the mechanism key rotation is built on.

    A compromised historical build's key is removed from the ring (or simply not
    provisioned to new deployments); templates still sealed under that `key_id` then
    stop decrypting, which is the intended effect of rotation, not a bug to work around.
    """

    def __init__(self, keys: dict[str, bytes] | None = None) -> None:
        self._keys = dict(keys or {})

    def add(self, key_id: str, key: bytes) -> None:
        """Provision one key under its id."""
        self._keys[key_id] = key

    def get(self, key_id: str) -> bytes | None:
        """The key for `key_id`, or `None` if it was never provisioned or was dropped."""
        return self._keys.get(key_id)


class TemplateVault:
    """Decrypts a `SealedTemplate` on demand, renders once, and discards the plaintext.

    No template cache in this class ever holds decrypted plaintext longer than one
    `render()` call — that is the whole confidentiality property Tier 1 offers, and it is
    enforced structurally (the decrypted buffer is a local variable, best-effort-zeroed
    before the call returns), not by convention.
    """

    def __init__(
        self,
        *,
        key_ring: KeyRing,
        license_public_key: bytes,
        license_blob: bytes,
        revocation_checker: RevocationChecker | None = None,
        revocation_fail_closed: bool = False,
    ) -> None:
        """Construct a vault bound to one deployment's license and key material.

        Args:
            key_ring: Decryption keys, keyed by `key_id`.
            license_public_key: The vendor's Ed25519 public key, for verifying
                `license_blob`'s signature.
            license_blob: The signed, time-boxed entitlement blob for this deployment
                (see `license.py`). Validated locally on every `render()` call — no
                network access is required for the baseline guarantee.
            revocation_checker: Optional online revocation check (deny-list by license
                id). When `None` (the default), revocation checking is off and only the
                offline blob's signature and expiry gate decryption — the deployment
                works air-gapped.
            revocation_fail_closed: When a `revocation_checker` is set and its check
                fails (e.g. network unreachable), the **recommended default** (`False`)
                degrades to the last cached good answer rather than refusing to render —
                a transient network failure degrading to "offline mode" is the *expected*
                degraded state for a feature whose baseline guarantee is already offline.
                Set `True` only when a deployment's security posture requires guaranteed
                revocation over availability; this is a real tradeoff, not a bug either
                way (see `plans/TIERED_ENCRYPTED_PLANS.md` §2, §7).
        """
        self._key_ring = key_ring
        self._license_public_key = license_public_key
        self._license_blob = license_blob
        self._revocation_checker = revocation_checker
        self._revocation_fail_closed = revocation_fail_closed
        self._last_revocation_ok: bool | None = None

    def render(self, template: EncryptedTemplate, **slots: object) -> str:
        """Decrypt `template`, render it against `slots`, and discard the plaintext.

        Raises:
            LicenseError: The bound license is missing, malformed, unsigned by the
                expected key, or expired.
            RevokedLicenseError: Online revocation checking is enabled and the license
                id is on the deny-list (or, under `revocation_fail_closed`, the check
                could not be completed at all).
            TemplateDecryptionError: `template.key_id` has no provisioned key, or
                decryption failed (wrong key, or the ciphertext was tampered with — GCM's
                authentication tag catches this).
        """
        license = verify_license(self._license_blob, public_key=self._license_public_key)
        self._check_revocation(license)

        key = self._key_ring.get(template.key_id)
        if key is None:
            raise TemplateDecryptionError(
                f"no key provisioned for key_id {template.key_id!r} "
                f"(template {template.template_id!r})"
            )
        try:
            plaintext_bytes = bytearray(
                AESGCM(key).decrypt(template.nonce, template.ciphertext, None)
            )
        except InvalidTag as exc:
            raise TemplateDecryptionError(
                f"template {template.template_id!r} failed to decrypt: wrong key or "
                "tampered ciphertext (GCM authentication failed)"
            ) from exc
        try:
            rendered = plaintext_bytes.decode("utf-8").format(**slots)
        finally:
            for i in range(len(plaintext_bytes)):
                plaintext_bytes[i] = 0
        return rendered

    def _check_revocation(self, license: LicenseBlob) -> None:
        if self._revocation_checker is None:
            return
        try:
            ok = self._revocation_checker(license.deployment_id)
        except Exception:  # noqa: BLE001 — any check failure is treated as unreachable
            ok = None
        if ok is None:
            if self._revocation_fail_closed:
                raise RevokedLicenseError(
                    f"revocation check for deployment {license.deployment_id!r} could "
                    "not be completed and revocation_fail_closed=True"
                )
            if self._last_revocation_ok is False:
                raise RevokedLicenseError(
                    f"deployment {license.deployment_id!r} was revoked as of the last "
                    "successful check, and a fresh check could not be completed"
                )
            return  # fail-open to the last known-good answer (or "never checked yet")
        self._last_revocation_ok = ok
        if not ok:
            raise RevokedLicenseError(f"deployment {license.deployment_id!r} is revoked")
