# SOC 2 control mapping for the confidentiality tiers

This is a translation exercise, not new engineering: the [Confidentiality
tiers](confidentiality-tiers.md) guide already states each tier's guarantee precisely. This
page restates the same facts against SOC 2 Trust Services Criteria language, because an
auditor evaluating a vendor built on AnyInfer needs that vocabulary, not AnyInfer's own.
SOC 2 was chosen as the first framework mapped (over HIPAA or FedRAMP) because it has the
broadest applicability for a B2B software vendor and is typically the first ask from any
enterprise procurement process, regardless of industry. HIPAA/FedRAMP mappings are deferred
until a concrete healthcare or public-sector conversation makes the need real, not built
speculatively.

**Every row below cites the specific typed fact it rests on, so this table can be
re-verified against running code rather than going stale the way a policy document usually
does.** That traceability is the actual differentiator here — most vendors in this space can
only offer prose assurances about data handling, because their architecture produces no
falsifiable fact to point to.

**This page is a starting point for your own auditor conversation, not a substitute for
one.** AnyInfer is a library; your organization holds the SOC 2 report, and your auditor
makes the final call about how a control is worded and evidenced for your specific
environment.

## Confidentiality criteria (CC6, CC7 — logical access and system operations)

| SOC 2 control area | Confidentiality tier | The typed fact | Caveat |
|---|---|---|---|
| Confidentiality of data in transit | Tier 0 (BYOK) | AnyInfer's adapters call the provider directly; no proxy hop exists in the call graph | Applies to customer data, not vendor prompt IP — that's what Tiers 1-4 answer |
| Confidentiality of data at rest | Tier 1 (`SealedTemplate`) | `EncryptedTemplate.ciphertext` — AES-256-GCM; plaintext never touches the on-disk asset ([`anyinfer_confidential.seal_template`](confidentiality-tiers.md#tier-1-sealedtemplate-encrypted-at-rest-prompt-assets)) | Protects against static extraction only — not a live-memory or debugger control |
| Access control / authentication | Tier 1 entitlement | `TemplateVault` refuses to decrypt without a signature-verified, unexpired `LicenseBlob` ([`anyinfer_confidential.verify_license`](confidentiality-tiers.md#tier-1-sealedtemplate-encrypted-at-rest-prompt-assets)) | Offline by default; online revocation is opt-in per deployment |
| Data retention / minimization | Tier 2 (`AnyInfer Relay`) | `Relay.handle()` — no request or response body is written to any durable store; the zero-retention property is structural, not policy-enforced | You still operate the Relay process, so its own hosting environment's logging discipline is your responsibility, not AnyInfer's |
| Logical access — tenant isolation | Tier 2 multi-tenant | `RelayRegistry.resolve(tenant_id, routing_key)` — a request scoped to one tenant cannot resolve another tenant's routes, structurally | Only relevant if you operate a shared hosted Relay serving more than one downstream vendor |
| Confidentiality of data in use | Tier 3 (attested local execution) | `ConfidentialExecutionStatus.end_to_end` — not even an operator with root on the host can read the prompt during local inference, when `True` | Requires specific TEE hardware (SEV-SNP/TDX today); `False` on hardware without it, reported honestly rather than silently degraded |
| Change management / fail-safe defaults | Tier 3 enforcement | `ConfidentialExecutionAdapter` raises `ConfidentialExecutionError` and never calls the inner adapter when attestation is unavailable — fails closed, never silently downgrades | Enforcement and any pre-flight check share one function (`confidential_execution_status`), so they cannot drift apart |
| Integrity of processing | Tier 4 (model provenance) | `ConfidentialExecutionStatus.model_verified` — the running model's weights hash-match a vendor-signed manifest, checked fresh on every call (never cached) | Only a Tier 4 claim in combination with `end_to_end`; a hash check alone on an unattested host is a weaker, different guarantee |

## Availability criteria (CC7, CC9 — a note on scope)

None of Tiers 1-4 are availability controls, and none should be cited as one. Tier 1
validates entirely offline by design (no availability dependency introduced). Tier 2's
zero-retention Relay, when self-hosted, inherits whatever availability posture your own
infrastructure has; AnyInfer does not currently operate a hosted Relay instance, so no
AnyInfer-operated availability commitment exists to cite yet.

## What this mapping deliberately does not claim

- **No claim about customer data confidentiality beyond BYOK's existing architecture** — that
  was already true before these tiers existed and is unaffected by them.
- **No claim of GPU-offloaded attestation being broadly available** — Tier 3's GPU-CC claim
  is scoped to specific cloud/hardware pairings; see the [deployment scope
  section](confidentiality-tiers.md#deployment-scope-today) before citing it in a customer
  conversation.
- **No claim that detection equals cryptographic attestation** — Tier 3 today detects TEE
  guest device presence; it does not yet generate and verify a signed hardware attestation
  quote. See [the honest gap
  section](confidentiality-tiers.md#the-honest-gap-between-detection-and-cryptographic-attestation)
  before an auditor asks the follow-up question.
- **No availability, business continuity, or incident response commitment of any kind** —
  those are your organization's controls, not a property of this library.

## See also

- [Confidentiality tiers](confidentiality-tiers.md) for the full technical detail behind
  every row above.
- `plans/TIERED_ENCRYPTED_PLANS.md` §5 in the repository for the design record this mapping
  was drafted from.
