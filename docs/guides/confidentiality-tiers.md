# Confidentiality Tiers

BYOK (bring-your-own-key) inference already answers one confidentiality question: your
application's calls go straight from your process to the provider you configured,
AnyInfer is never a proxy, and [redaction](../concepts/credentials.md) keeps secrets out
of logs. That protects your *customer's* data from AnyInfer and from you.

It does not protect your own prompt IP (templates, orchestration, few-shot curation)
from a customer running your client software on infrastructure they own. No purely
client-side technique can: the customer owns the machine, the OS, and the network stack.
This page is a ladder from "raises the cost of extraction" (Tiers 1–2) up to the one
point where a real cryptographic guarantee becomes *possible* (Tier 3, hardware-attested
local execution — today detection, with quote verification planned), plus a verification
layer on top of it (Tier 4). Each tier's
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
immediately before rendering and best-effort-zeroes the buffer afterward. `TemplateVault.render()` is
gated on a signed, time-boxed license blob, so an install without a valid license gets no
rendered prompt from the vault — which doubles as a licensing mechanism.

That gate lives in the vault's code path, not in the ciphertext. The vault holds both the
key and the sealed asset, so a bundle holder can decrypt directly and bypass the check;
expiry is a signed field checked against local wall-clock, so a clock rollback defeats it.
This is inherent to client-side sealing — the adversary owns the machine, which is the same
ceiling Tier 1's confidentiality claim states. The gate makes unlicensed use unambiguous
and detectable, not impossible. Cite it that way.

```bash
# Ships as a separate package. Until a first PyPI release, install from a repository
# checkout — see [installation](installation.md#optional-add-on-packages).
pip install -e "src/anyinfer-confidential[relay]"   # relay is optional; Tier 1 needs no extra
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
open by default since offline operation is the baseline.

**Set `revocation_fail_closed=True` for high-assurance deployments** — anywhere a revoked
license must stop working even at the cost of availability. Two things to know before you
do. First, fail-open means an unreachable service degrades to the last cached good answer,
and a checker that has *never* completed a successful check has no cached answer to fall
back to, so it degrades to "not revoked". Second, fail-closed makes your revocation
endpoint a hard dependency of every render: if it is down, nothing renders. That is the
trade, and it is a real one in both directions.

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

`anyinfer_confidential.app.build_app(relay, tokens=...)` serves it over ASGI with the
`relay` extra. Self-hosted and hosted deployments run the identical `Relay` class;
AnyInfer does not currently operate a hosted instance.

### Deploying the Relay

The endpoint's response body is the decrypted, assembled prompt, so authentication is
not optional and `build_app` has no unauthenticated mode. `tokens` maps a bearer token to
the tenant it authenticates, and the tenant is taken from the token — a `tenant_id` in the
request body is never trusted, and one that disagrees with the token is rejected.

```python
import secrets

from anyinfer_confidential.app import build_app
from anyinfer_confidential.relay import load_registry

registry = load_registry("relay-routes.json")   # sealed templates: ciphertext, not secret
app = build_app(relay, tokens={secrets.token_urlsafe(32): "customer-42"})
```

A self-hosting checklist:

- **Terminate TLS in front of the app.** A bearer token on a plaintext connection is
  readable by anything on the path.
- **Issue one long random token per tenant** and record which tenant each belongs to.
  Rotate by replacing the mapping and rebuilding the app.
- **Provision routes from a file** with `load_registry`, so the tenant-to-route binding
  is under configuration management rather than in a bespoke script. The file holds
  sealed templates, so it is ciphertext and can live in a config repository; decryption
  still needs the deployment's vault, key ring, and a valid license.
- **Do not expose `mode="forward"` expectations to HTTP clients.** The endpoint assembles
  only, and answers a forward-mode request with 400. Forwarding needs short-lived
  provider credentials that the wire format deliberately does not accept; call
  `Relay.handle` in-process for that mode.

## Tier 3 (Attested Local Execution)

The one tier designed for a real cryptographic guarantee, because it targets AnyInfer's
own [local adapters](../concepts/local.md) instead of a cloud call. What ships today is
detection rather than attestation — see
[detection versus cryptographic attestation](#detection-versus-cryptographic-attestation)
below, and read `end_to_end` as an advisory local signal until then. When the host supports a
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

**State the ceiling when you cite this.** Two limits are separate and both hold:

- **CPU.** SEV-SNP and TDX are *detected* through their guest device nodes. Quote
  generation and chain verification against AMD's or Intel's roots is planned, not
  shipped.
- **GPU.** Even once CPU quotes are verified, NVIDIA confidential computing will remain
  **detected but not quote-verified**: GPU attestation goes through the SPDM path in
  NVIDIA's own tooling, which is substantially harder than the CPU path and needs
  sustained access to CC-capable hardware. The accurate phrasing at that point is
  "CPU-attested; GPU CC detected but not quote-verified" — not "attested end to end".

Neither is a reason to avoid Tier 3: the fail-closed refusal is real, and the detection is
accurate about what it detects. They are a reason to say precisely what you have.

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
`model_verified` on the status. Treat `model_verified is True` as meaningful only when
`end_to_end is True` too; a hash-and-signature check on an unattested host is a weaker,
different guarantee.

### Verify at the Point of Load

`model_verified` is a point-in-time answer: it describes the weights when the status was
computed, not the weights a server later opens. If the check runs at startup and the model
loads an hour later, the gap between them is an hour.

To bind verification to the load, hand the provenance to whatever starts the server:

```python
from anyinfer.local import WeightsProvenance

provenance = WeightsProvenance(manifest=manifest, vendor_public_key=public_key)
managed = await supervisor.acquire(key, model_path, plan, provenance=provenance)
```

The weights are hashed through open file descriptors *inside* the start path, and their
identity is re-confirmed in the instant before the process is spawned. A file renamed over,
replaced, truncated, or deleted after verification is refused with a
[`ConfidentialExecutionError`](../reference/errors.md#confidentialexecutionerror) and no
server starts — including when the replacement is byte-identical, because a replacement is
a different file whatever it contains.

Two residual windows remain, and neither closes from inside a library. `llama-server` opens
the path itself, so the microseconds between the last check and that open are not covered;
and because llama.cpp maps weights lazily, a writer with access to the *same* file can
still alter pages that have not been read yet. Both need the bytes to be immutable while
they load — a read-only mount, or a directory only root can write. That is a property of
how you deploy, and Tier 3's attested boundary is what makes it checkable rather than
assumed.

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
    - Everything fails closed *in AnyInfer's own code paths*: no valid license, no
      rendered prompt from the vault; no attestation, no generation; no matching hash,
      `model_verified=False`. Tiers 1–2 gate code paths on a machine the adversary owns;
      only Tier 3's hardware boundary is not bypassable by whoever holds the bundle.
    - Tier 3 today detects TEE presence rather than verifying a signed hardware quote;
      cite it accordingly.
    - The SOC 2 mapping restates the same typed facts in auditor vocabulary; it does not
      add guarantees.

## See Also

<div class="anyinfer-see-also" markdown>

- [Confidentiality add-ons API reference](../reference/api/confidential.md): every
  signature on this page, generated from the source.
- [The local subsystem](../concepts/local.md) and its
  [API reference](../reference/api/local.md): Tiers 3–4's machinery.
- [Credentials and redaction](../concepts/credentials.md): the Tier 0 posture.
- [Why and when to use AnyInfer](../why-anyinfer.md): where confidentiality fits the
  larger case.

</div>
