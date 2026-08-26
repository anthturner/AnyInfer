# Confidentiality Add-Ons

Two separate installable distributions, neither imported by `anyinfer` core nor a
dependency of it. `anyinfer_confidential` implements Tier 1 (`SealedTemplate`) and Tier 2
(the `AnyInfer Relay`); `anyinfer_shared` holds the one composite type both sides report
into. See the [confidentiality tiers guide](../../guides/confidentiality-tiers.md) for what
each tier guarantees, what it costs, and the ceiling it states.

```python
from anyinfer_confidential import TemplateVault, seal_template
from anyinfer_confidential.relay import Relay, RelayRegistry, load_registry
from anyinfer_shared import ConfidentialityReport
```

## Tier 1 — Sealed Templates

<div class="anyinfer-api-block" markdown>

::: anyinfer_confidential.seal_template

::: anyinfer_confidential.EncryptedTemplate

::: anyinfer_confidential.TemplateVault

::: anyinfer_confidential.KeyRing

::: anyinfer_confidential.generate_key

</div>

## Licensing

The license gate is enforcement in `TemplateVault.render`'s code path, not a cryptographic
lock on the ciphertext — the guide's
[Tier 1 section](../../guides/confidentiality-tiers.md#tier-1-sealed-templates) states the
ceiling precisely.

<div class="anyinfer-api-block" markdown>

::: anyinfer_confidential.generate_signing_keypair

::: anyinfer_confidential.issue_license

::: anyinfer_confidential.verify_license

::: anyinfer_confidential.LicenseBlob

::: anyinfer_confidential.license.RevocationChecker

</div>

## Tier 2 — The Relay

`build_app` requires a token-to-tenant mapping and has no unauthenticated mode: the
response body is the decrypted, assembled prompt.

<div class="anyinfer-api-block" markdown>

::: anyinfer_confidential.relay.Relay

::: anyinfer_confidential.relay.RelayRoute

::: anyinfer_confidential.relay.RelayResult

::: anyinfer_confidential.relay.RelayRegistry

::: anyinfer_confidential.relay.load_registry

::: anyinfer_confidential.app.build_app

</div>

## Composing a Report

<div class="anyinfer-api-block" markdown>

::: anyinfer_shared.ConfidentialityReport

</div>

## Errors

<div class="anyinfer-api-block" markdown>

::: anyinfer_confidential.ConfidentialError

::: anyinfer_confidential.SealError

::: anyinfer_confidential.TemplateDecryptionError

::: anyinfer_confidential.LicenseError

::: anyinfer_confidential.RevokedLicenseError

::: anyinfer_confidential.relay.RelayError

</div>
