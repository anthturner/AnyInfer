# Confidentiality Tiers

BYOK (bring-your-own-key) inference already answers one confidentiality question: your
application's calls go straight from your process to the provider you configured,
AnyInfer is never a proxy, and [redaction](../concepts/credentials.md) keeps secrets out
of logs. That protects your *customer's* data from AnyInfer and from you.

It does not protect your own prompt IP (templates, orchestration, few-shot curation)
from a customer running your client software on infrastructure they own. No purely
client-side technique can: the customer owns the machine, the OS, and the network stack.
This page is a ladder from "raises the cost of extraction" (Tiers 1–2) up to the one
point where a real cryptographic guarantee becomes possible (Tier 3, hardware-attested
local execution), plus a verification layer on top of it (Tier 4). Each tier's
guarantee, cost, and limits are stated once, in the table:

| Tier | What it guarantees | What it costs | Ships in |
|---|---|---|---|
| 0 (BYOK) | Your customer's prompt data never passes through AnyInfer or you | Nothing; this is the default | `anyinfer` core |
| 1 (`SealedTemplate`) | Your template plaintext resists static extraction from the shipped bundle | No protection against a live debugger or memory inspection | `anyinfer-confidential` |
| 2 (`AnyInfer Relay`) | Your orchestration logic never ships to the client at all | You're back in the customer's data path for that call | `anyinfer-confidential` |
| 3 (Attested local execution) | Not even root on the host can read the prompt in transit to or during local inference | Requires specific TEE hardware (SEV-SNP/TDX today) | `anyinfer` core |
| 4 (Model provenance) | The model weights that ran are exactly what you signed, verified inside Tier 3's boundary | Only a Tier 4 claim when Tier 3 also holds | `anyinfer` core |

The full design record, including exclusions and open questions, is DESIGN.md §30 in the
repository.

## Tier 1 (Sealed Templates)

A template is authored as plaintext, sealed at build time with AES-256-GCM, and shipped
as an opaque asset. At runtime, `TemplateVault` decrypts a template into memory only
immediately before rendering and best-effort-zeroes the buffer afterward. Decryption is
gated on a signed, time-boxed license blob, so an install without a valid license cannot
render a single prompt (which doubles as a licensing mechanism).

```bash
pip install "anyinfer-confidential[relay]"   # relay is optional; Tier 1 alone needs no extra
```

```python
from anyinfer_confidential import (
    KeyRing, TemplateVault, generate_key, generate_signing_keypair,
    issue_license, seal_template,
)

# Build time, run once, keep the private outputs out of the client bundle:
key = generate_key()
private_key, public_key = generate_signing_keypair()   # public_key ships with clients
template = seal_template(
    "Summarize this for {audience}: {document}",
    key=key, template_id="summarize", key_id="k1",
)

# Deployment time, per customer install:
license_blob = issue_license("customer-42", private_key=private_key, valid_days=30)

# Runtime, inside the shipped client:
vault = TemplateVault(
    key_ring=KeyRing({"k1": key}),
    license_public_key=public_key,
    license_blob=license_blob,
)
prompt = vault.render(template, audience="engineers", document="the release notes")
```

Every sealed template carries a `key_id` and `KeyRing` holds as many keys as you
provision, so rotation is re-sealing under a new id; a compromised historical key stops
decrypting once dropped from the ring.

Entitlement is offline by default: the license blob validates entirely locally, so an
air-gapped deployment works. Online revocation is opt-in (`revocation_checker`), failing
open by default since offline operation is the baseline; set
`revocation_fail_closed=True` when guaranteed revocation matters more than availability.

The `anyinfer-confidential` CLI mirrors the library one-for-one (`keygen`, `seal`,
`issue-license`) for build pipelines that are not Python.

## Tier 2 (the Relay)

Tier 1 protects template *text*. The Relay protects the orchestration pipeline itself
(which templates fire in what order, routing logic, few-shot selection) by never
shipping it to the client. The cost is symmetric: for that call you are back in the
customer's data path, which trades against the Tier 0 posture. The Relay sees the
assembled request transiently and persists nothing, by design.

`Relay` accepts non-proprietary slot-fill inputs and a routing key, resolves them
against a server-side `RelayRoute`, and either returns the assembled prompt for the
client to send itself (`mode="assemble"`; no credential ever touches the Relay) or
forwards it using a credential supplied fresh on every call (`mode="forward"`, never
persisted). Tenant isolation is structural: a request scoped to one `tenant_id` cannot
resolve another tenant's routes.

```python
from anyinfer_confidential.relay import Relay, RelayRegistry, RelayRoute

registry = RelayRegistry()
registry.register(
    "customer-42",
    RelayRoute(routing_key="summarize", template=template, target="ollama:qwen3:8b"),
)
relay = Relay(vault=vault, registry=registry)

result = await relay.handle(
    tenant_id="customer-42",
    routing_key="summarize",
    slots={"audience": "engineers", "document": "the release notes"},
    mode="assemble",
)
print(result.assembled_prompt)
```

`anyinfer_confidential.app.build_app(relay)` serves it over ASGI with the `relay`
extra. Self-hosted and hosted deployments run the identical `Relay` class; AnyInfer does
not currently operate a hosted instance.

## Tier 3 (Attested Local Execution)

The one tier with a real cryptographic guarantee, because it targets AnyInfer's own
[local adapters](../concepts/local.md) instead of a cloud call. When the host supports a
trusted execution environment (AMD SEV-SNP or Intel TDX today), the local runtime can
run inside it, and `confidential_execution_status()` reports whether the guarantee holds
right now, on this box:

```python
from anyinfer.local import confidential_execution_status, available_backends

backend = available_backends()[0]
status = confidential_execution_status(backend=backend)
if status.end_to_end:
    print(f"attested: {status.detail}")
else:
    print(f"not attested: {status.detail}")   # render this to the caller, don't guess
```

`ConfidentialExecutionAdapter` wraps a local adapter and enforces the same check as a
precondition: it refuses to `generate()` unless `end_to_end` is `True`, raising
[`ConfidentialExecutionError`](../reference/errors.md#confidentialexecutionerror)
instead of falling back to unattested execution. Enforcement and pre-flight call the
identical function, so they cannot drift apart.

```python
from anyinfer.providers.confidential_execution import ConfidentialExecutionAdapter

adapter = ConfidentialExecutionAdapter(inner_llama_cpp_adapter, backend=backend, model=model)
# adapter.generate(req) now fails closed instead of silently running unattested
```

`end_to_end=True` means precisely: the CPU package this process runs in is inside an
attestable TEE, and, if the selected model offloads any layers to a GPU, that GPU is
confidential-computing-capable *and* has CC mode enabled, closing the PCIe bridge.
`ConfidentialExecutionStatus` carries every intermediate fact (`cpu_tee`,
`gpu_cc_capable`, `gpu_cc_enabled`, `gpu_offload_required`) so an application can render
a specific reason rather than a bare `False`.

### Detection Versus Cryptographic Attestation

What is implemented today is detection: the check reads the TEE guest device nodes
(`/dev/sev-guest`, `/dev/tdx_guest`) and NVIDIA's `nvidia-smi conf-compute` surface,
which tells you the guest kernel believes it is inside a TEE. It is not yet the stronger
claim of cryptographic attestation: generating and verifying a signed hardware quote
against AMD's or Intel's root of trust, which is what rules out a lying hypervisor. That
verification step is scoped (an `attest`-extra addition) but not built. Do not read
`end_to_end=True` today as "a cryptographic quote was checked"; this section will change
when that lands.

### Deployment Scope, Today

- CPU-only (SEV-SNP or TDX): broadly available as GA lift-and-shift confidential VMs on
  AWS, Azure, and GCP, no application changes.
- GPU-offload (NVIDIA H100 CC): confirmed GA only on Azure (with SEV-SNP) and Google
  Cloud (with TDX), and only for H100. Treat this as the newer, narrower claim.
- AWS Nitro Enclaves and Intel SGX are detected and reported in `cpu_tee`, but are not
  part of the `end_to_end` claim in this release.

## Tier 4 (Model Provenance)

Tier 3 proves where a prompt ran; Tier 4 proves what ran inside it, with a signed
manifest and a hash check. This is verification-only software: AnyInfer never signs
anything and never touches a private key. You sign your own model manifests with your
own keys; AnyInfer ships the verifier.

```python
from anyinfer.local import ModelManifest, hash_model_weights, verify_model_manifest

# At sign time, on infrastructure you control (never AnyInfer's):
weight_hash = hash_model_weights(model_path)
# ... sign {model_id, weight_hash, vendor_key_id, signed_at} with your Ed25519 key ...

# At verify time, inside a Tier 3-attested process:
ok = verify_model_manifest(manifest, weights_path=model_path, vendor_public_key=public_key)
```

`confidential_execution_status()` accepts `manifest=`/`vendor_public_key=` and populates
`model_verified` on the status. Verification is never cached, so a swapped file is
caught on the next call. Treat `model_verified is True` as meaningful only when
`end_to_end is True` too; a hash-and-signature check on an unattested host is a weaker,
different guarantee.

## Appendix: SOC 2 Control Mapping

An auditor evaluating a vendor built on AnyInfer needs the tiers restated in Trust
Services Criteria vocabulary. Each row cites the typed fact it rests on, so the claim
can be re-verified against running code. This table is a starting point for your own
auditor conversation, not a substitute for one: your organization holds the SOC 2
report, and your auditor decides how a control is worded for your environment.

| SOC 2 control area | Confidentiality tier | The typed fact | Caveat |
|---|---|---|---|
| Confidentiality of data in transit | Tier 0 (BYOK) | AnyInfer's adapters call the provider directly; no proxy hop exists in the call graph | Applies to customer data, not vendor prompt IP; that's what Tiers 1-4 answer |
| Confidentiality of data at rest | Tier 1 (`SealedTemplate`) | `EncryptedTemplate.ciphertext` (AES-256-GCM); plaintext never touches the on-disk asset | Protects against static extraction only, not a live-memory or debugger control |
| Access control / authentication | Tier 1 entitlement | `TemplateVault` refuses to decrypt without a signature-verified, unexpired `LicenseBlob` | Offline by default; online revocation is opt-in per deployment |
| Data retention / minimization | Tier 2 (`AnyInfer Relay`) | `Relay.handle()` writes no request or response body to any durable store; zero retention is structural | You operate the Relay process, so its hosting environment's logging discipline is yours |
| Logical access / tenant isolation | Tier 2 multi-tenant | `RelayRegistry.resolve(tenant_id, routing_key)` cannot resolve another tenant's routes | Relevant only for a shared Relay serving more than one downstream vendor |
| Confidentiality of data in use | Tier 3 (attested local execution) | `ConfidentialExecutionStatus.end_to_end`: root on the host cannot read the prompt during local inference, when `True` | Requires TEE hardware (SEV-SNP/TDX today); `False` reported plainly otherwise |
| Change management / fail-safe defaults | Tier 3 enforcement | `ConfidentialExecutionAdapter` raises and never calls the inner adapter when attestation is unavailable | Enforcement and pre-flight share one function, so they cannot drift apart |
| Integrity of processing | Tier 4 (model provenance) | `ConfidentialExecutionStatus.model_verified`: weights hash-match a vendor-signed manifest, checked fresh on every call | Only a Tier 4 claim in combination with `end_to_end` |

Three scope notes an auditor will ask about: none of the tiers are availability
controls, and none should be cited as one; the GPU-attestation claim is scoped to the
[deployment pairings above](#deployment-scope-today); and Tier 3 today is
[detection, not cryptographic attestation](#detection-versus-cryptographic-attestation);
read that section before the follow-up question arrives.

!!! tip "Key Takeaways"
    - Tiers 1–2 raise the cost of extracting prompt IP; only Tier 3 (TEE-attested local
      execution) carries a cryptographic guarantee, and Tier 4 is meaningful only
      inside it.
    - Everything fails closed: no valid license, no rendered prompt; no attestation, no
      generation; no matching hash, `model_verified=False`.
    - Tier 3 today detects TEE presence rather than verifying a signed hardware quote;
      cite it accordingly.
    - The SOC 2 mapping restates the same typed facts in auditor vocabulary; it does not
      add guarantees.

## See Also

<div class="anyinfer-see-also" markdown>

- [The local subsystem](../concepts/local.md) and its
  [API reference](../reference/api/local.md): Tiers 3–4's machinery.
- [Credentials and redaction](../concepts/credentials.md): the Tier 0 posture.
- [Why and when to use AnyInfer](../why-anyinfer.md): where confidentiality fits the
  larger case.

</div>
