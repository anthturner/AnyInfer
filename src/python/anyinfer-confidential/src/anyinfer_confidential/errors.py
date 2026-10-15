"""Exception hierarchy for `anyinfer_confidential`.

Mirrors `anyinfer.errors`' own discipline: distinct, narrow exception types rather than
one catch-all, so a caller can tell "the license expired" from "the ciphertext was
tampered with" without parsing a message string.
"""

from __future__ import annotations

__all__ = [
    "ConfidentialError",
    "LicenseError",
    "RevokedLicenseError",
    "SealError",
    "TemplateDecryptionError",
]


class ConfidentialError(Exception):
    """Base class for every error this package raises."""


class SealError(ConfidentialError):
    """A sealed-template asset is malformed or could not be produced."""


class TemplateDecryptionError(ConfidentialError):
    """A sealed template could not be decrypted: wrong key, or tampered ciphertext."""


class LicenseError(ConfidentialError):
    """A license blob is missing, malformed, unsigned by the expected key, or expired."""


class RevokedLicenseError(ConfidentialError):
    """Revocation checking found the license revoked, or a fail-closed check failed."""
