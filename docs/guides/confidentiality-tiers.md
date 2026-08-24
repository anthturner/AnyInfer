# Confidentiality tiers

BYOK (bring-your-own-key) inference already answers one confidentiality question: your
application's calls go straight from your process to the provider you configured, AnyInfer
is never a proxy, and [credential and prompt redaction](../concepts/credentials.md) keeps
secrets out of logs. That protects *your customer's* data from AnyInfer and from you.

It does not protect *your* prompt IP — templates, orchestration, few-shot curation — from a
customer running your client software on infrastructure they own. Nobody selling a
client-side SDK has a real answer to that, because the customer owns the machine, the OS,
and the network stack: no purely client-side technique produces a cryptographic guarantee.
**Read that ceiling before you read anything else on this page.** What follows is an honest
ladder from "raises the cost of extraction" (Tiers 1–2) up to the one point where a real
cryptographic guarantee becomes possible (Tier 3, hardware attestation for local execution),
plus a verification layer on top of it (Tier 4). Every tier states what it does *not*
protect against as prominently as what it does — a tier that borrowed a stronger tier's
language would be worse than no claim at all.

| Tier | What it guarantees | What it costs | Ships in |
|---|---|---|---|
| 0 — BYOK | Your customer's prompt data never passes through AnyInfer or you | Nothing — this is the default | `anyinfer` core |
| 1 — `SealedTemplate` | Your template plaintext resists static extraction from the shipped bundle | No protection against a live debugger or memory inspection | `anyinfer-confidential` |
| 2 — `AnyInfer Relay` | Your orchestration logic never ships to the client at all | You're back in the customer's data path for that call | `anyinfer-confidential` |
| 3 — Attested local execution | Not even root on the host can read the prompt in transit to or during local inference | Requires specific TEE hardware (SEV-SNP/TDX today) | `anyinfer` core |
| 4 — Model provenance | The model weights that ran are exactly what you signed, verified inside Tier 3's boundary | Only a Tier 4 claim when Tier 3 also holds | `anyinfer` core |

The full design record — including the decisions behind each tier, what was explicitly
excluded, and open questions — lives in DESIGN.md §30 in the repository.

## Tier 1 — `SealedTemplate`: encrypted-at-rest prompt assets

**What it protects against:** static extraction — someone unzipping your app bundle,
grepping the binary, or reading the on-disk template file. **What it does not protect
against:** live network capture, memory inspection of a running process, or a debugger
attached during a render.

A template is authored as plaintext, sealed at build time with AES-256-GCM, and shipped as
an opaque asset. At runtime, `TemplateVault` decrypts a template into memory only
immediately before rendering it and best-effort-zeroes the buffer afterward. Decryption is
gated on a signed, time-boxed license blob — an install without a valid license cannot
render a single prompt, which doubles as a licensing mechanism independent of the
confidentiality motivation.

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

Key rotation is built into the asset format: every sealed template carries a `key_id`, and
`KeyRing` holds as many keys as you provision — re-seal under a new `key_id` on whatever
cadence you choose, and a compromised historical key simply stops decrypting anything once
it's dropped from the ring.

**Entitlement is hybrid, offline by default.** The license blob validates entirely locally
— no network call is required to decrypt, so a deployment works air-gapped. Online
revocation is opt-in per deployment (pass a `revocation_checker` to `TemplateVault`); the
recommended default on a check failure is to fail open to the last known-good answer,
because the baseline guarantee is already offline, so a transient network failure degrading
to "offline mode" is the expected state, not a new one. Set `revocation_fail_closed=True`
if your security posture needs guaranteed revocation over availability instead — that's a
real tradeoff, not a bug either way.

The CLI mirrors the library one-for-one:

```bash
anyinfer-confidential keygen --out template.key
anyinfer-confidential keygen-license --out-private vendor.priv --out-public vendor.pub
anyinfer-confidential seal prompt.txt --key template.key --key-id k1 \
    --template-id summarize --out summarize.sealed.json
anyinfer-confidential issue-license --private-key vendor.priv \
    --deployment-id customer-42 --days 30 --out customer-42.license
```

## Tier 2 — the `AnyInfer Relay`: zero-retention remote prompt assembly

**What it protects:** the orchestration pipeline itself — which templates fire in what
order, routing logic, few-shot selection — the part of your IP that isn't prompt text at
all, and that a single captured request on the wire wouldn't reveal even under Tier 1's
weaker guarantee. **What it costs:** you're back in the customer's data path for that call,
which trades directly against the BYOK privacy posture Tier 0 already gives you — document
exactly what the Relay sees (the assembled request, transiently) and what it persists
(nothing, by design).

`Relay` accepts non-proprietary slot-fill inputs and a routing key, resolves them against a
server-side `RelayRoute` (which template, which target), and either returns the assembled
prompt for the client to send itself (`mode="assemble"`, no credential ever touches the
Relay process) or forwards it using a credential the caller supplies fresh on every call
(`mode="forward"`, never persisted). Multi-tenant isolation is structural: a request scoped
to one `tenant_id` cannot resolve another tenant's routes, by construction, not by policy —
this is what a shared hosted deployment relies on.

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

Serve it over ASGI with the `relay` extra:

```python
from anyinfer_confidential.app import build_app
# uvicorn.run(build_app(relay), ...) from your own deployment script
```

Self-hosted and any AnyInfer-hosted offering run the identical `Relay` class — nothing in
this module assumes who operates it. AnyInfer does not currently operate a hosted Relay
instance; the code ships self-hostable today, and hosting it as a managed offering is
tracked separately as an operational (not code) commitment.

## Tier 3 — attested local execution

The one tier with a real cryptographic guarantee, because it targets AnyInfer's own local
adapters (`llama_cpp`, `lm_studio`, `ollama`) instead of a cloud provider call. When the
host supports a trusted execution environment — AMD SEV-SNP or Intel TDX today — the local
runtime can run inside it, and `confidential_execution_status()` reports whether that
guarantee actually holds *right now*, on *this* box.

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
precondition: it refuses to `generate()` — never silently falling back to unattested
execution — unless `end_to_end` is `True`, raising `ConfidentialExecutionError` with the
same `detail` a pre-flight check would have shown. Enforcement and pre-flight both call the
identical function, so they cannot drift out of sync with each other.

```python
from anyinfer.providers.confidential_execution import ConfidentialExecutionAdapter

adapter = ConfidentialExecutionAdapter(inner_llama_cpp_adapter, backend=backend, model=model)
# adapter.generate(req) now fails closed instead of silently running unattested
```

**What `end_to_end=True` actually means, precisely:** the CPU package this process runs in
is inside an attestable TEE, and — if the selected model offloads any layers to a GPU —
that GPU is itself confidential-computing-capable *and* has CC mode enabled, closing the
PCIe bridge rather than leaving it in plaintext between an attested CPU and an unprotected
GPU. `ConfidentialExecutionStatus` carries every intermediate fact (`cpu_tee`,
`gpu_cc_capable`, `gpu_cc_enabled`, `gpu_offload_required`) so your application can render a
*specific* reason ("your GPU supports CC mode but it isn't enabled" reads very differently
from "no TEE hardware detected at all") instead of a bare `False`.

### The honest gap between detection and cryptographic attestation

What's implemented today is **detection**: `confidential_execution_status()` checks for the
TEE guest device nodes (`/dev/sev-guest`, `/dev/tdx_guest`) and NVIDIA's `nvidia-smi
conf-compute` surface. That tells you the guest kernel believes it's running inside a TEE.
It is not yet the stronger claim of **cryptographic attestation** — generating and
verifying a signed hardware attestation report against AMD's or Intel's root of trust,
which is what actually rules out a compromised or lying hypervisor. That verification step
is scoped (an `attest`-extra-gated addition using each cloud's attestation service and
NVIDIA's NVAT SDK) but not yet built. Detection is real and useful — it's what a fail-closed
adapter needs to refuse execution on hardware that plainly lacks the capability at all — but
don't read `end_to_end=True` today as "a cryptographic quote was checked." This section will
be updated the moment that changes.

### Deployment scope, today

- **CPU-only (SEV-SNP or TDX): broadly available now.** Both are GA lift-and-shift
  confidential VMs on AWS, Azure, and GCP, with zero application changes required — all
  three local backends run inside one unmodified. This is the low-risk, high-confidence
  case to lead with.
- **GPU-offload (NVIDIA H100 confidential computing): narrower.** Confirmed GA only on
  Azure (paired with SEV-SNP) and Google Cloud (paired with TDX), and only for H100
  specifically — H200/Blackwell CC was not confirmed GA on a major cloud at the time this
  was researched. AWS's GPU-CC status is unconfirmed either way. Treat this as the newer,
  narrower claim, not the headline one.
- **AWS Nitro Enclaves and Intel SGX are detected, not attested.** Both are real TEE
  families and `ConfidentialExecutionStatus.cpu_tee` reports them honestly when found, but
  neither is part of the `end_to_end` claim in this release: Nitro's storage/networking
  constraints and SGX's enclave-shaped programming model mean neither is the lift-and-shift
  story SEV-SNP/TDX give.

## Tier 4 — model provenance verification

Tier 3 proves *where* a prompt ran. It says nothing about *what* ran inside it — whether
the model weights are the exact artifact you shipped, or something swapped or tampered with
in place. Tier 4 closes that gap with a signed manifest and a hash check.

**This is verification-only software. It never signs anything, and AnyInfer never touches
a private key.** You sign your own model manifests with your own keys, using whatever
signing process you already trust (a raw `cryptography.Ed25519PrivateKey.sign()` call is
enough) — the same way you already own your runtime manifests today. AnyInfer ships the
verifier, never a signing service.

```python
from anyinfer.local import ModelManifest, hash_model_weights, verify_model_manifest

# At sign time, on infrastructure you control (never AnyInfer's):
weight_hash = hash_model_weights(model_path)
# ... sign {model_id, weight_hash, vendor_key_id, signed_at} with your Ed25519 key ...

# At verify time, inside a Tier 3-attested process:
ok = verify_model_manifest(manifest, weights_path=model_path, vendor_public_key=public_key)
```

`confidential_execution_status()` accepts `manifest=`/`vendor_public_key=` directly and
populates `model_verified` on the returned status — verification is never cached, unlike
the hardware-detection fields, so a swapped file is caught on the very next call rather
than masked by a stale cache entry.

**Only a Tier 4 claim in combination with Tier 3.** A hash-and-signature check on an
unattested host is a real, useful check, but a weaker and different guarantee — there's no
protection for who else could have read or swapped the file before or during the check.
Treat `model_verified is True` as meaningful only when `end_to_end is True` too; the field
is documented that way precisely so the two can't be silently conflated.

## What genuinely doesn't exist anywhere else

The underlying cryptography here is not undiscovered territory — NVIDIA ships the CC driver
and attestation SDK, Azure and Google Cloud both have GA confidential-GPU offerings, and
hosted confidential-GPU clouds already sell attested inference as a service. Claiming no one
is doing confidential AI would be false. What we could not find anywhere in this research:
**a portable capability check packaged inside a multi-provider BYOK library.** Every
existing option is either a confidential-GPU *cloud* you rent, not one you bring your own
hardware to, or a research protocol wired to a single specific backend. The defensible claim
is narrower and more specific: *the integration and honesty layer — one function that tells
a caller what it can actually guarantee, across providers and local runtimes, failing closed
when it can't — doesn't exist anywhere else.* That's also the harder thing to copy, since it
needs the multi-provider breadth AnyInfer already has as a prerequisite, not just access to
hardware everyone else already has access to.

## See also

- [The local subsystem](../concepts/local.md) and its [API reference](../reference/api/local.md)
  for Tiers 3–4.
- [Errors](../reference/errors.md#confidentialexecutionerror) for `ConfidentialExecutionError`.
- DESIGN.md §30 in the repository for the full design record, including
  every explicitly-excluded scope item and open question.
