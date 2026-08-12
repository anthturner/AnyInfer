"""AnyInfer Confidential: Tiers 1-2 of the tiered confidentiality plan.

Never imported by `anyinfer` core, and never a dependency of it — this is an optional
add-on a vendor installs when they need to protect prompt *IP* (templates, orchestration)
from a customer running the vendor's client software on the customer's own
bring-your-own-key infrastructure. It does not protect the customer's own prompt data
from AnyInfer or the vendor; BYOK already provides that (see
`plans/TIERED_ENCRYPTED_PLANS.md` §0).

- **Tier 1** (`sealed_template`): `SealedTemplate`/`TemplateVault` — encrypted-at-rest
  prompt templates, decrypted only immediately before rendering.
- **Tier 2** (`relay`): the `AnyInfer Relay` — an optional service that owns prompt
  orchestration server-side so it never ships to the client at all.

Tiers 3 and 4 (attested local execution, model-weight verification) live in
`anyinfer.local.attestation` — they are execution-environment facts, not prompt-content
handling, so they stay in core. See the Confidentiality Tiers doc for the full picture.
"""

from __future__ import annotations

from .errors import (
    ConfidentialError,
    LicenseError,
    RevokedLicenseError,
    SealError,
    TemplateDecryptionError,
)
from .license import LicenseBlob, generate_signing_keypair, issue_license, verify_license
from .sealed_template import EncryptedTemplate, KeyRing, TemplateVault, generate_key, seal_template

__all__ = [
    "ConfidentialError",
    "EncryptedTemplate",
    "KeyRing",
    "LicenseBlob",
    "LicenseError",
    "RevokedLicenseError",
    "SealError",
    "TemplateDecryptionError",
    "TemplateVault",
    "generate_key",
    "generate_signing_keypair",
    "issue_license",
    "seal_template",
    "verify_license",
]
