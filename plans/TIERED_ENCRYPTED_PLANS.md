# Tiered confidential execution (follow-on plan)

> **Status:** Tiers 1-4 implemented and tested 2026-08-12 (same day as the plan). Sketched
> from a brainstorm about differentiation once provider/adapter breadth (>100 providers, >20
> adapters) stops being a distinguishing feature on its own.
> **Plan date:** 2026-08-12.
> **Authority:** living implementation plan, not an architecture decision. It proposes
> confidentiality features layered around AnyInfer's existing surfaces; where it touches
> prompt content it explicitly follows the `VECTOR_STORE_ADDON.md` precedent of shipping as
> an optional add-on rather than amending core, because DESIGN.md's non-goals forbid core
> from doing so (see §1).

## Implementation status (2026-08-12)

Delivered in one session, gate-passing at every step (pytest, mypy --strict, ruff,
lint-imports, mkdocs --strict):

- **§1 packaging** — `src/anyinfer-confidential/` and `src/anyinfer-shared/` stood up
  exactly per the decided layout: own `pyproject.toml` each, hyphenated directory /
  underscored importable package, `anyinfer-confidential` depending on `anyinfer` (never
  the reverse), `anyinfer-shared` never imported by either. `anyinfer_shared` is not empty:
  it holds `ConfidentialityReport`, the composite type §7 asked whether would materialize —
  it did, once all four tiers existed in the same session to know its real shape.
- **§2 Tier 1** — `SealedTemplate`/`TemplateVault`/`KeyRing` (AES-256-GCM), the hybrid
  entitlement model (offline signed Ed25519 license blob always-on; opt-in online
  revocation with the recommended fail-open-to-cached-answer default, and a
  `revocation_fail_closed` override for the alternative posture §7 flagged as the owner's
  call), key rotation via `key_id`, and the `anyinfer-confidential` CLI's `seal`/`keygen`/
  `keygen-license`/`issue-license` subcommands. 13 tests.
- **§3 Tier 2** — `Relay`/`RelayRegistry`/`RelayRoute`, deployment-agnostic from the start
  (self-hosted and any future hosted offering run the identical class), structural
  multi-tenant isolation, `mode="assemble"` (no credential touches the Relay) and
  `mode="forward"` (a per-call, never-persisted credential). The optional `relay` extra
  wraps it in a thin Starlette app. **Not delivered, and out of scope for a code session**:
  actually operating a hosted Relay instance — that's infrastructure (hosting platform,
  SLA, on-call), not code; §7's open question about that operational plan is still open.
  6 tests.
- **§4 Tier 3** — `anyinfer.local.attestation.confidential_execution_status()` and
  `ConfidentialExecutionAdapter`, exactly per §4d's implementation-grade spec: CPU TEE
  device-node detection (SEV-SNP/TDX/Nitro/SGX, Linux-only v1), NVIDIA GPU CC detection via
  `nvidia-smi conf-compute`, the full `end_to_end` combination matrix, disk caching mirroring
  `hardware.py`'s own convention, and fail-closed enforcement sharing one function with
  pre-flight checks. **One honesty gap flagged prominently in the docs, not glossed over**:
  what's implemented is TEE *detection* (device-node presence), not yet cryptographic
  *attestation-quote verification* — that remains the `attest`-extra-gated addition §4
  itself scoped as needing real per-cloud SDK integration (NVAT, Azure/GCP attestation
  services), which this session's environment cannot build against. GPU-offload attestation
  is detected but the deployment-scope caveats from §4c are carried into the shipped docs
  verbatim. 27 tests.
- **§4a Tier 4** — `anyinfer.local.provenance` (`ModelManifest`, `hash_model_weights`,
  `verify_model_manifest`), verification-only as decided (never signs, never touches a
  private key), reusing the `attest` extra. `model_verified` added to
  `ConfidentialExecutionStatus` and deliberately **never cached** (unlike the hardware
  fields) — caching a manifest-verification result would let a file swapped between calls
  go undetected until the next cache expiry, defeating the point. Its docstring is explicit
  that it's only a real Tier 4 claim combined with `end_to_end`. 10 tests.
- **§5 docs** — `docs/guides/confidentiality-tiers.md` (the full tiered doc, ceiling stated
  in the first paragraph per the plan's own discipline) and `docs/guides/soc2-mapping.md`
  (SOC 2 drafted first, per the decided framework choice; every row cites the typed fact it
  rests on). `why-anyinfer.md`'s "on the horizon" section rewritten to reflect what's
  actually shipped rather than staying speculative.
- **§6 implementation order** — followed items 1-4 and 7-8 in the suggested sequence; item 5
  (Relay) delivered as code, not as a hosted deployment (see above); item 6 (this section)
  is this update.
- **Not attempted, honestly**: operating a hosted Relay or hosted entitlement-revocation
  service (infrastructure, not code); GPU-offload attestation-quote verification (the
  `attest` extra's NVAT/cloud-attestation-service integration); Nitro Enclaves as a
  supported v1 deployment target (detected, deliberately not claimed, per §4c's own
  recommendation). §7's open questions about AWS GPU-CC status, OpenRM driver support, and
  H200/Blackwell availability remain genuinely open — this session did not re-research them.

## 0. The problem this answers, and the one it doesn't

Two distinct confidentiality problems came out of the brainstorm, and this plan only
addresses the second one:

1. **Protecting the *customer's* prompt data from AnyInfer / the vendor.** BYOK already
   answers most of this: the call goes straight from the caller's process to the provider
   the caller configured, AnyInfer is never a proxy, and `redaction.py` already keeps
   secrets out of logs/errors/events. No new feature needed here beyond what exists.
2. **Protecting the *vendor's* prompt IP (templates, orchestration, few-shot curation) from
   the customer**, when the vendor's client software runs entirely on the customer's own
   BYOK infrastructure. This is the hard, interesting problem, and it's what this plan
   scopes. The customer owns the machine, the OS, and the network stack, so no purely
   client-side technique can produce a real cryptographic guarantee — the honest ceiling is
   raising cost/friction (Tiers 1–2) up to one case where a real guarantee is possible
   (Tier 3, hardware attestation for local execution).

## 1. Why this is an add-on, not a core change — for Tiers 1 and 2

DESIGN.md §2 states the non-goal directly: AnyInfer does "no prompt templating" — ADR-011
narrows this to "the library owns one mechanical envelope format, apps own all prompt
language around it." A `SealedTemplate` type that stores, decrypts, and assembles prompt
*content* is prompt templating by definition — the exact thing core has declined to own,
for the same reason `context` collection stays app-side: it's "where the security policy
lives... and where every app differs." Baking template ownership into core would also
undercut the plan's own goal, since a vendor's proprietary template shape is precisely the
kind of app-specific policy DESIGN.md keeps out of the library.

Tier 3 is different in kind: it doesn't touch prompt content at all. It's an execution
*environment* constraint on the local adapters (`llama_cpp`, `lm_studio`, `ollama`) that
already live in core, sitting alongside the existing hardware/runtime detection in
`src/anyinfer/local/` (`hardware.py`, `backends.py`, `runtimes.py`). That work is scoped to
core in §6.

So, mirroring `VECTOR_STORE_ADDON.md`: Tiers 1 and 2 ship as a separate, optionally-installed
package that depends on `anyinfer` (for typed request/result surfaces and the client) but is
never imported by it and never a dependency of it.

**Decided (2026-08-12): `src/anyinfer-confidential/`, its own sub-project, not a bag of
extra files under core's `pyproject.toml`.** The owner's explicit direction is broader than
this one plan: AnyInfer is moving toward sharding into subcomponents with clear maintenance
boundaries, of which this is the first. Concretely:

- `src/anyinfer-confidential/` is its own directory with its **own `pyproject.toml`**,
  independently versioned and independently releasable, not folded into the root
  `pyproject.toml`'s `[tool.hatch.build.targets.wheel] packages = [...]` list the way
  `demo_app` currently is. It depends on `anyinfer` (a normal PyPI/path dependency), never
  the reverse.
- Directory name carries the hyphen (`anyinfer-confidential`) to match the eventual
  distribution name; the importable Python package inside it uses an underscore
  (`anyinfer_confidential`), since hyphens aren't legal in Python module names — same split
  every hyphenated-name PyPI package already has (`anyinfer-confidential` the install name,
  `import anyinfer_confidential` the module name). Concrete layout:
  `src/anyinfer-confidential/pyproject.toml` +
  `src/anyinfer-confidential/src/anyinfer_confidential/__init__.py`.
- **`src/anyinfer-shared/`** (own `pyproject.toml`, importable as `anyinfer_shared`) holds
  types genuinely needed by more than one package that isn't itself core — the concrete case
  here being a composite "what confidentiality actually happened for this call" result type,
  since a single call can combine facts from core (Tier 3/4 execution) and the add-on
  (Tier 1/2 assembly), and neither package should have to import the other's internals to
  describe that. If no real cross-package type need materializes beyond what `anyinfer` core
  already exports publicly, `anyinfer-shared` stays empty rather than accumulating speculative
  types — same discipline the `mcp` extra already applies ("no dependencies... the extra
  exists so importing anyinfer never pulls in [x]").
- Local dev: each sub-project is `pip install -e`-able from its own path; no new monorepo
  workspace tool (uv workspaces, etc.) is assumed necessary yet — revisit only if managing
  several independent `pyproject.toml` files by hand becomes real friction.
- This packaging shape is the template going forward for AnyInfer's other optional pieces
  too (it also fits `VECTOR_STORE_ADDON.md`'s still-open "package name/location" question in
  its own §7), not a one-off for confidentiality specifically.

## 2. Tier 1 — `SealedTemplate`: encrypted-at-rest prompt assets

**What it is.** A template object whose plaintext never lives on disk unencrypted. The
vendor authors templates as usual, then the add-on's build step encrypts them into an opaque
asset shipped inside the vendor's client bundle. At runtime, the add-on decrypts a template
into memory only immediately before it's rendered into a request, and the plaintext
`str`/structure is dropped (not just dereferenced — actively overwritten where the runtime
allows it) as soon as the render is handed to `anyinfer`'s request construction.

**What it actually protects against:** static extraction — someone unzipping the app bundle,
grepping the binary, or reading the on-disk asset. **What it does not protect against:**
live network capture, memory inspection while the process runs, or a debugger attached to a
live render. The package's docs must state this ceiling in the first paragraph, the same way
`VECTOR_STORE_ADDON.md` states its scale ceiling up front rather than in a caveats section.

**Included**
- An `EncryptedTemplate` asset format (template plaintext + envelope), and a build-time CLI
  step (`anyinfer-confidential seal`) that produces it from source templates.
- A runtime `TemplateVault` that decrypts on demand, renders once, and discards; no template
  cache holds plaintext longer than one render.
- A license/entitlement check gating decryption — the vault refuses to decrypt without a
  valid, vendor-issued key for the calling deployment. This doubles as a licensing hook
  (an install without a valid entitlement literally cannot produce prompts), which is a
  second, independent motivation for building this beyond confidentiality.
- A key-rotation story: templates re-sealed under a new key on a cadence the vendor chooses,
  so a compromised historical build's key doesn't decrypt current templates.

**Decided (2026-08-12): hybrid entitlement — offline by default, online optional for
revocation.** Concretely:
- The default artifact is a **signed, time-boxed license blob** (vendor-issued, e.g. a JWT
  or equivalent signed structure with an expiry) shipped or provisioned to the deployment.
  `TemplateVault` validates its signature and expiry locally; no network call is required to
  decrypt, so the vault works air-gapped and adds no availability dependency — consistent
  with DESIGN.md §2's "no daemon in the core" posture even though this lives in the add-on,
  not core.
- **Online revocation is opt-in per deployment**, not always-on: when enabled, the vault
  additionally checks a revocation endpoint (deny-list by license id) on a caller-configured
  cadence (e.g. once per process start, or every N hours), caching the last good answer.
  This is how a vendor kills a specific compromised license without waiting for blob expiry.
- **Recommended default for revocation-check failure (network unreachable): fail open to the
  last cached good answer, not hard-fail.** Reasoning: the baseline guarantee is offline
  validation, so a transient network failure degrading to "offline mode" is the *expected*
  degraded state, not a new failure — while fail-closed-on-network-error would make an
  otherwise-offline-capable feature secretly online-required. This is a judgment call, not
  yet confirmed with the owner — flagged in §7.

**Explicitly excluded**
- Any claim of protecting against live traffic capture or an attached debugger — that's
  Tier 2/3 territory, not this tier's.
- Runtime obfuscation/anti-tamper of the vault code itself (out of scope for a first cut;
  revisit only if demand is real, since anti-debug measures are themselves easily defeated
  friction, not protection).

## 3. Tier 2 — `AnyInfer Relay`: zero-retention remote prompt assembly

**What it is.** An optional network service (vendor-hosted, or self-hostable by the vendor
for their own compliance needs) that owns prompt *orchestration* — which templates fire in
what order, routing/scoring logic, few-shot example selection — so that logic never ships to
the client at all. The client sends structured, non-proprietary slot-fill inputs; the relay
assembles the final request server-side and either (a) forwards it directly to the provider
the customer configured, using a short-lived, non-persisted credential the client supplies
per-call, or (b) returns a single-use assembled request for the client to fire itself.

**What it actually protects:** the pipeline — the part of the vendor's IP that isn't prompt
text at all, and that a single captured request on the wire wouldn't reveal even under Tier
1's weaker guarantee. **What it costs:** the vendor is now back in the customer's data path
for that call, which directly trades against the BYOK privacy posture from the earlier
brainstorm (§0.1). That tension must be surfaced to the vendor's own customers, not hidden:
document exactly what the relay sees (the assembled request, transiently) and what it
persists (nothing, by design and by audit).

**Included**
- A relay service with a minimal surface: accept slot-fill inputs + a routing key, return an
  assembled request or forward it.
- A documented zero-retention contract: no request or response body written to durable
  storage, logs carry metadata only (latency, token counts, routing key) — reusing the same
  redaction discipline `anyinfer.redaction` already applies to secrets, extended to prompt
  content.
- Self-hosting instructions so a vendor with their own compliance requirements can run the
  relay inside their own infra rather than the add-on author's, keeping the "who's in the
  data path" answer under the vendor's control.
- Credential handling: the customer's provider key is used per-call and never persisted by
  the relay, mirroring `anyinfer.credentials`' existing resolver pattern rather than
  inventing a new one.

**Decided (2026-08-12): both self-hosted and AnyInfer-hosted offered from day one, as equal
options — no default to pick between them.** Consequences worth being explicit about, since
this is more scope than "ship software only":
- The Relay's implementation must be genuinely deployment-agnostic from the start (no
  assumptions baked in about who operates it), rather than built self-hosted-first and
  retrofitted for multi-tenancy later.
- An AnyInfer-hosted offering means AnyInfer itself operates infrastructure with uptime,
  scaling, and its own security posture — a new operational surface for the project, not
  just a code deliverable. That operational plan (hosting platform, SLA, multi-tenant
  isolation between vendors' relay traffic) is real scope not yet designed; flagged in §7.
- Multi-tenant isolation is a hard requirement for the hosted option specifically: one
  vendor's relay traffic must be provably unreadable by another vendor's, even though both
  run against the same hosted service — this is a new constraint beyond the zero-retention
  contract, which was written assuming a single vendor's traffic per deployment.

**Decided (2026-08-12): the Relay and Tier 1's entitlement/licensing service stay strictly
separate services, even under the hosted option.** Keeps the Relay's zero-retention claim
simple to audit — it only ever sees assembled prompts, never license/entitlement state — and
keeps licensing as its own small, independently scalable and independently revocable
service. A vendor using the hosted Relay is not required to also use hosted entitlement
checking, and vice versa.

**Explicitly excluded**
- Any request/response logging or analytics product built on relay traffic — that would
  quietly turn "zero retention" into a lie.
- Multi-tenant routing intelligence, caching, or optimization across customers — the relay
  assembles one request for one caller; it is not a shared-state system.

## 4. Tier 3 — `ConfidentialExecutionAdapter`: attested local execution (core-adjacent)

**What it is.** The one tier with a real cryptographic guarantee, because it targets
AnyInfer's existing local-model adapters (`llama_cpp`, `lm_studio`, `ollama`) rather than a
cloud provider call. When the operator's hardware supports a trusted execution environment —
AWS Nitro Enclaves, Intel TDX/SGX, AMD SEV-SNP, NVIDIA confidential-computing GPUs — the
local runtime can run inside it, and remote attestation can prove to the *vendor's* client
software that it's really running inside an unmodified enclave before any prompt is sent.
Under that guarantee, not even someone with root on the host can read the prompt in transit
to or during execution by the enclaved process.

**Where it lives:** as an extension of the existing `src/anyinfer/local/` hardware/runtime
detection, not the add-on package — this doesn't touch prompt content or templating, so
ADR-011's boundary doesn't apply, and `hardware.py`/`backends.py` already model "what
acceleration is available and how much do we trust what we found" (the `_MANIFEST_BONUS`
confidence-ranking pattern in `backends.py` is directly analogous to what an attestation
check needs to express).

**Included**
- Attestation detection alongside existing `AcceleratorKind` detection: does this host
  expose an attestable TEE, and can the runtime binary be verified to run inside it.
- A `ConfidentialExecutionAdapter` mode on the local adapters that requires attestation to
  succeed before executing, and fails closed (refuses execution) rather than silently
  degrading to unattested execution — silent downgrade would make the guarantee a lie the
  same way silent relay logging would.
- A visible, typed signal (mirroring `ParameterDropped`/`CachePlanned`'s pattern from
  ADR-012) when a caller *requests* confidential execution but the host can't provide it —
  never a quiet fallback.
- Documentation of exactly which of the three current local backends can plausibly run
  inside an attestable enclave today versus which need real engineering lift — this is
  unknown going in and must be scoped before promising it (see open questions).
- `confidential_execution_status()` (below) as the one queryable capability check every
  other Tier 3 behavior is built on.

**`confidential_execution_status()` — the queryable capability check.** Apps embedding
AnyInfer need to ask "can this box actually give me the guarantee I want" *before*
committing to a request, so they can degrade gracefully with a message the caller sees
instead of the adapter failing mid-call. Advisory, never raises — same contract as
`available_backends()`. Modeled on ADR-012's typed-fact pattern rather than a bare `bool`:
"can it do TEE" is really several separable facts, and collapsing them into one boolean
upfront would hide exactly the information a caller needs to explain *why* to its own user.

**Full implementation-grade spec — concrete types, real field names (`ResolvedModel`, not an
invented `ModelSpec`), detection algorithm per CPU TEE family, and a caching/testing
strategy — moved to §4d** once the CPU-only path was scoped in enough detail to write real
code against. The summary that follows is unchanged in substance from §4d, only compressed:

`end_to_end` is `True` only when `cpu_tee is not None` and either `gpu_offload_required` is
`False` (a CPU-only path — no bridge to worry about, per §4's caveat) or both
`gpu_cc_capable` and `gpu_cc_enabled` are `True` (the GPU closes its own leg of the bridge).
Every other field exists so a caller can render a specific fix ("your GPU supports CC mode
but it isn't enabled" reads very differently from "no TEE hardware detected at all"), the
same way `Backend.detail` already explains a runtime selection rather than just ranking it.

`ConfidentialExecutionAdapter`'s fail-closed behavior calls this same function and refuses
to execute unless `end_to_end` is `True` — one source of truth, so the adapter's enforcement
and an app's pre-flight check can never drift out of sync with each other.

Lives next to `hardware.py`/`backends.py` in `src/anyinfer/local/`, not the add-on package:
it answers the same "what does this box actually have" question they already answer, and it
never touches prompt content, so ADR-011's boundary doesn't apply to it.

**Packaging: base, not an add-on — with one thin extra for the crypto-heavy piece.** Unlike
Tiers 1–2, Tier 3 as a whole ships in `anyinfer` core, not `anyinfer-confidential`, because
it's a hardware-capability question in the same category as everything already in `local/`,
not prompt handling. But it isn't monolithically base either: `confidential_execution_status()`
is pure advisory detection with no dependency beyond stdlib, so it belongs in base exactly
like `hardware.py`/`backends.py` do today. Actually *verifying* a signed attestation quote
(the enclave's signature chain, an NVIDIA CC attestation token) needs real crypto/vendor-SDK
dependencies, which is the same situation `vertex = ["cryptography>=42"]` already solves for
JWT signing — so that verification step gets its own small extra (working name: `attest`)
rather than pulling crypto dependencies into every `anyinfer` install. `ConfidentialExecutionAdapter`
stays in base (it wraps already-base local adapters) but fails closed with an explicit
"install `anyinfer[attest]`" message if verification is requested and that extra isn't
installed — never a silent `end_to_end=False` with no explanation, and never a silent skip
of verification.

**Explicitly excluded**
- Attesting cloud-provider execution. Providers would have to expose attestation themselves
  (a few are starting to, e.g. confidential-computing offerings from some hyperscalers) —
  out of scope until a concrete provider contract exists to audit against, per this
  project's usual "don't build against a protocol that isn't pinned in `contracts/`" rule.
  **A concrete one now exists, researched 2026-08-12**: Azure's "AI Confidential
  Inferencing" preview runs a model inside a TEE (the same SEV-SNP + H100 CC stack as §4's
  local-execution case) and exposes a signed SBOM plus Azure Attestation so a *caller* can
  remotely verify the hosted service itself, with no VM of the caller's own involved at all.
  This is genuinely a **different capability from Tier 3, not a variant of it** — attested
  *hosted* execution (verifying a provider's claim about infrastructure the caller never
  touches) versus attested *local* execution (the operator's own box) — and would need its
  own tier/design if pursued, not a bolt-on to `ConfidentialExecutionAdapter`. Still narrow
  enough to leave excluded for now: the source names Whisper as the first Azure AI
  Model-as-a-Service model with this protection, reading as preview-stage and
  model-specific, not a general Foundry-catalog capability yet. Revisit once broader
  coverage or GA status is confirmed, and note for whoever asks "does this work with Azure AI
  Foundry": Foundry's Managed Compute (the no-VM abstraction most Foundry users deploy
  through) shows no evidence of exposing confidential-GPU options — Tier 3's actual
  local-execution guarantee via Azure requires deploying on Azure's real confidential-VM SKUs
  directly (SEV-SNP CPU + H100 CC), not through Foundry's managed abstraction, which trades
  away exactly the VM-level visibility attestation needs.
  Source: [Azure AI Confidential Inferencing Preview](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/azure-ai-confidential-inferencing-preview/4248181).
- Building or maintaining enclave images/toolchains — this adapts to attestable runtimes
  operators already run, it does not ship or manage enclave infrastructure itself.

**The CPU↔GPU bridge caveat — this is where Tier 3's guarantee actually lives or dies.** A
CPU-only TEE (Nitro Enclaves, SGX, SEV-SNP) protects memory and execution inside the CPU
package only. Historically, once the CPU hands work to a GPU over PCIe for acceleration, the
boundary ends at the bus: PCIe traffic and GPU VRAM are plaintext, readable by a compromised
hypervisor or a physical bus tap. That gap is closed only on GPUs that participate in
confidential computing themselves (NVIDIA H100/H200/Blackwell CC mode, which attests its own
firmware, negotiates a session key with the CPU TEE, and encrypts the PCIe link and VRAM) —
and only when that mode is actually enabled in the software stack. `ConfidentialExecutionAdapter`
must therefore attest the GPU's CC mode specifically for any backend that offloads to a GPU,
not just the CPU enclave, and must fail closed (never silently fall back to "CPU TEE only,
GPU unprotected") when a GPU is in play but isn't CC-capable or CC-enabled. CPU-only local
backends (e.g., llama.cpp on CPU) have no bridge problem at all, since nothing ever leaves
the CPU TEE — those are the easy, unambiguous Tier 3 case.

## 4c. Tier 3 feasibility findings (researched 2026-08-12)

Implementation order item 1 asked "which of `llama_cpp`/`lm_studio`/`ollama` can run under
an attestable TEE today." Research shows that framing was slightly wrong: **feasibility
isn't gated by which backend it is — all three can run headless and completely unmodified
inside the relevant TEE. It's gated by deployment topology** (which TEE, which cloud, CPU-only
vs. GPU-offload), the same axis the CPU↔GPU bridge caveat in §4 already flagged.

**CPU-only path — available today, zero application changes, for all three backends.**
AMD SEV-SNP and Intel TDX confidential VMs are explicitly designed for lift-and-shift: no
application code changes are required, the entire guest OS and process tree runs encrypted
and isolated from the host/hypervisor. Both are GA today on AWS, Azure, and GCP. This means
`llama_cpp` (CPU build), `ollama`, and `lm_studio`'s headless server core (`lms`/`llmster` —
LM Studio ships a genuine headless mode explicitly built for "Linux boxes, cloud servers,
GPU rigs," not GUI-only as this plan assumed earlier) can all be deployed inside a SEV-SNP or
TDX CVM today with no upstream engineering work, verified by attesting the CVM itself.
**AWS Nitro Enclaves are a narrower, harder case, not equivalent to SEV-SNP/TDX CVMs**: Nitro
Enclaves have no GPU support at all (confirmed — still true as of this research, no roadmap
found) and, more importantly for the CPU-only case, are a stricter sub-VM model with no
persistent storage and vsock-only networking, so loading model weights and serving requests
needs real integration work, unlike the "just boot it" lift-and-shift story SEV-SNP/TDX give.
Recommendation: **lead Tier 3's CPU-only claim with SEV-SNP/TDX CVMs, not Nitro Enclaves.**

**GPU-offload path — available today, but only on two specific cloud/hardware pairings, and
only for NVIDIA H100 so far.** Confirmed GA:
- **Azure**: NVIDIA H100 NVL confidential VMs, paired with **AMD SEV-SNP** for the CPU TEE.
  Single GPU per node GA in East US 2; `ND H100 v5` SKUs support multi-GPU (up to 8) nodes.
- **Google Cloud**: Confidential VM / Confidential Space on H100, `A3` machine series, paired
  with **Intel TDX** for the CPU TEE (A3 uses Intel Xeon hosts).
- **AWS**: no evidence found of a confidential-GPU offering at all — flagged as an open item
  to verify directly against AWS docs before asserting either way, rather than assumed absent.
- **H200/Blackwell CC**: not confirmed GA on any major cloud in this research (only found via
  a third-party GPU-rental provider, not a hyperscaler) — Tier 3's GPU claim should scope to
  H100 specifically until H200/Blackwell CC availability is separately confirmed.
- Existing CUDA applications reportedly run on a CC-enabled H100 unmodified once the VM+GPU
  pairing and NVIDIA's CC-capable driver (**535.86+**, proprietary — whether the open-source
  `OpenRM` kernel module also supports CC mode is unconfirmed and flagged as an open item) are
  in place — so `llama_cpp`'s CUDA build and `ollama`'s GPU path should both work without
  modification, same as the CPU-only case, once the deployment prerequisites are met.

**No project-level (llama.cpp/Ollama/LM Studio) attestation integration exists anywhere** —
only third-party/research work was found, e.g. Stanford Hazy Research's "Secure Minions"
(an external protocol that *integrates with* Ollama, published as a research preview around
ICML 2025 — not part of official Ollama releases, and not evidence Ollama has any native TEE
support). This confirms §4's design is the correct one: AnyInfer must do CVM/GPU attestation
verification itself from the client side, since the backends never will.

**Concrete verification tooling identified for the `attest` extra's GPU-verification piece**:
NVIDIA's own `nvTrust`/**NVAT** (NVIDIA Attestation SDK), Apache-2.0, actively maintained (a
Python SDK and Local GPU Verifier are being deprecated in favor of a newer C++ SDK + CLI),
including a **Protected PCIe verifier for multi-GPU setups** — directly relevant to §4's
CPU↔GPU bridge attestation requirement. CPU-side attestation (the SEV-SNP/TDX report) uses
each cloud's own attestation service (e.g. Azure Attestation) or the CVM's own hardware
attestation report — no single cross-cloud library found; this is a real design surface for
implementation order item 2, not yet resolved here.

**Net effect on the plan:** Tier 3 ships in two honestly distinct claims, not one — worth
keeping visibly separate in `confidential_execution_status()` and in marketing:
1. CPU-only, SEV-SNP/TDX: broadly available today, near-zero engineering lift, all three
   backends.
2. GPU-offload, H100 CC: available today only on Azure (SEV-SNP) and GCP (TDX) specifically,
   real engineering lift (NVAT integration, per-cloud attestation-service integration,
   multi-GPU PPCIE verification), and should be marketed as narrower and newer than claim 1.

Sources: [AWS Nitro Enclaves GPU issue #543](https://github.com/aws/aws-nitro-enclaves-cli/issues/543), [AWS Nitro Enclaves docs](https://docs.aws.amazon.com/enclaves/latest/user/nitro-enclave.html), [NVIDIA H100 Azure confidential VM GA](https://blogs.nvidia.com/blog/azure-confidential-vm-h100-general-availability), [Google Cloud confidential accelerators](https://cloud.google.com/blog/products/identity-security/how-confidential-accelerators-can-boost-ai-workload-security), [AMD SEV-SNP confidential computing](https://www.amd.com/en/products/processors/server/epyc/confidential-computing.html), [Azure confidential VMs (SEV-SNP) GA](https://techcommunity.microsoft.com/blog/azureconfidentialcomputingblog/azure-confidential-vms-dcasv5ecasv5-using-amd-sev-snp-processors-are-now-general/2993530), [LM Studio headless server docs](https://lmstudio.ai/docs/developer/core/headless), [LM Studio 0.4 headless deployment](https://www.sitepoint.com/lm-studio-04-headless-deployment-local-llm-apis-without-the-gui/), [Ollama Secure Minions blog post](https://ollama.com/blog/secureminions), [NVIDIA nvTrust repository](https://github.com/NVIDIA/nvtrust), [NVIDIA Confidential Computing deployment guide (TDX)](https://docs.nvidia.com/cc-deployment-guide-tdx.pdf).

## 4d. Implementation-grade detail — the CPU-only path

Per §4c's findings and the recommended sequencing in implementation order item 1: spec the
CPU-only path first, since it's buildable today with no open feasibility questions blocking
it. GPU-offload detail (NVAT integration, per-cloud attestation-service wiring, PPCIE
verification) is deliberately left at the §4/§4c level of detail until the AWS-GPU-CC and
OpenRM open items resolve — speccing it now would mean guessing at exactly the kind of detail
this addendum exists to stop guessing at.

**New module: `src/anyinfer/local/attestation.py`.** Mirrors `hardware.py`'s conventions
exactly (advisory-only, never raises; disk-cached keyed by a probe signature; env-var cache
bypass/refresh), since it answers the same category of question ("what does this box actually
have") right next to it:

```python
# src/anyinfer/local/attestation.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from .backends import Backend
from .store import ResolvedModel

__all__ = [
    "ATTESTATION_CACHE_BYPASS_ENV",
    "ATTESTATION_CACHE_REFRESH_ENV",
    "CpuTeeKind",
    "ConfidentialExecutionStatus",
    "confidential_execution_status",
]

ATTESTATION_CACHE_BYPASS_ENV = "ANYINFER_ATTESTATION_CACHE_BYPASS"
ATTESTATION_CACHE_REFRESH_ENV = "ANYINFER_ATTESTATION_CACHE_REFRESH"

CpuTeeKind = Literal["sev-snp", "tdx", "nitro", "sgx"]
"""CPU TEE families this module can detect. `sgx` and `nitro` are detected and reported
for completeness but are not part of the v1 `end_to_end` claim — see below."""

@dataclass(frozen=True, slots=True)
class ConfidentialExecutionStatus:
    """What this box can actually guarantee for confidential local execution.

    Attributes:
        cpu_tee: Detected CPU TEE, or `None`.
        gpu_cc_capable: Detected GPU supports CC mode at all (hardware fact).
        gpu_cc_enabled: CC mode is actually active in the current driver/runtime config.
        gpu_offload_required: Whether the selected model's launch plan offloads to GPU
            at all (from `ResolvedModel.launch_hints["n_gpu_layers"]`); when `False`,
            `gpu_cc_capable`/`gpu_cc_enabled` don't gate `end_to_end`.
        end_to_end: The one field most callers branch on.
        detail: Human-readable why, same role as `Backend.detail`.
    """
    cpu_tee: CpuTeeKind | None
    gpu_cc_capable: bool
    gpu_cc_enabled: bool
    gpu_offload_required: bool
    end_to_end: bool
    detail: str

def confidential_execution_status(
    *, backend: Backend, model: ResolvedModel | None = None, use_cache: bool = True
) -> ConfidentialExecutionStatus: ...
```

**CPU TEE detection (`_detect_cpu_tee()`), Linux guests only for v1** (Windows/macOS
confidential-guest detection returns `cpu_tee=None` with a `detail` note, not attempted —
matching the "unknown is always preferred to guessed" discipline `hardware.py`'s docstring
already states):
- **SEV-SNP**: presence of the `/dev/sev-guest` character device (the standard AMD SEV-SNP
  guest driver node).
- **TDX**: presence of `/dev/tdx_guest` (the standard Intel TDX guest driver node).
- **Nitro**: presence of `/dev/nsm` (the Nitro Secure Module device Nitro Enclaves expose for
  requesting attestation documents) — detected and reported, but per §4c's recommendation,
  not treated as a supported v1 deployment target given its storage/networking constraints;
  `detail` should say so explicitly rather than silently omitting it.
- **SGX**: presence of `/dev/sgx_enclave` — detected and reported, but SGX's enclave-shaped
  programming model (not lift-and-shift) means it isn't part of v1's `end_to_end` claim
  either; same "detected but explained, not silently dropped" treatment as Nitro.
- **Secondary corroboration where available**: the generic in-kernel TSM (TEE Security
  Manager) configfs report interface at `/sys/kernel/config/tsm/report/` (present on newer
  kernels for both TDX and SEV-SNP guests) can confirm a device-node finding the same way
  `backends.py`'s `_MANIFEST_BONUS` corroborates a ranked guess — implementation should treat
  this as raising confidence, not as a second independent source of truth, since both paths
  describe the same underlying fact.
- Each of these is a simple existence/readability check (`Path(...).exists()`), matching the
  cheap, best-effort style of `hardware.py`'s own probes — no privileged access or attestation
  report generation happens in the detection step itself, only in the (separate, `attest`-extra-gated) verification step §4 already scopes.

**GPU CC detection (`_detect_gpu_cc()`)**, only invoked when `hardware.detect()` already
found an NVIDIA `Accelerator`: shell out to `nvidia-smi conf-compute -f`, reusing
`hardware.py`'s existing `_run(command: list[str])` subprocess helper rather than adding a
second one. This is newer, less-stable `nvidia-smi` surface than the flags `hardware.py`
already depends on — **pin the exact expected output format (`"CC status: ON"`-shaped) as a
small internal contract once implementation starts**, the same discipline
`contracts/*.md` already applies to provider wire formats, since this is exactly the same
"external tool's interface we depend on and must notice changing" situation.

**Combining into `end_to_end`** (unchanged from §4's original definition, now grounded in
real types): `True` when `cpu_tee in ("sev-snp", "tdx")` and either
`gpu_offload_required` is `False`, or both `gpu_cc_capable` and `gpu_cc_enabled` are `True`.
`gpu_offload_required` reads `model.launch_hints.get("n_gpu_layers", 0) > 0` when a
`ResolvedModel` is supplied (confirmed real field, `local/acquire.py`); when no model is
supplied (a caller checking capability before choosing one), `gpu_offload_required` is
conservatively `True` unless the caller is known to be CPU-only-only, so a capability check
never over-promises before a model is even chosen.

**`ConfidentialExecutionAdapter`**: a thin wrapper implementing the same `ProviderAdapter`/
`GeneratesText` Protocol (`providers/base.py`) as the local adapters it wraps
(`llama_cpp.py`, `lm_studio.py`, `ollama.py`), composing over an inner adapter instance rather
than subclassing any of them. Its `generate()` calls `confidential_execution_status()` first;
if `end_to_end` is `False`, it raises a new `ConfidentialExecutionError(LocalRuntimeError)`
(new subclass in `errors.py`, next to `LocalRuntimeError`) carrying the status's `detail`,
and never calls the inner adapter — the fail-closed behavior §4 already specifies, now with a
concrete exception type and insertion point.

**Caching**: disk-cached exactly like `hardware.py` (`cache_path()`/`_read_cache()`/
`_write_cache()` pattern), keyed by a probe signature covering the checked device paths and
the `nvidia-smi` binary (when present) — reuses `hardware.py`'s `probe_signature()` shape
rather than inventing a parallel caching scheme.

**Test strategy — must be injectable without real TEE hardware in CI**, matching this
project's offline-test-kit ethos (`why-anyinfer.md` §1): the device-existence checks and the
`nvidia-smi` subprocess call need a seam (an injectable root path / injectable `_run`
callable, mirroring how `hardware.py`'s own probes are already structured around a `_run()`
helper) so tests can simulate "SEV-SNP guest, no GPU," "TDX guest with CC-enabled H100,"
"bare metal, no TEE," etc. as plain fixtures. Conformance-test list for this module
specifically: each `CpuTeeKind` detected correctly from a faked device-path set; `end_to_end`
true/false for every combination of `(cpu_tee present/absent) × (gpu_offload_required) ×
(gpu_cc_capable) × (gpu_cc_enabled)`; `ConfidentialExecutionAdapter` never calls the inner
adapter when `end_to_end` is `False`; cache hit/bypass/refresh behavior matches `hardware.py`'s
existing tests for the same three cases.

## 4a. Tier 4 — model/weight provenance attestation (natural extension of Tier 3)

**What it is.** Tier 3 proves *where* a prompt ran (an unmodified enclave). It says nothing
about *what* ran inside it — whether the model weights are the exact, certified artifact the
vendor shipped, or something swapped or tampered in place. `local/` already tracks this
partially: `runtime.json` manifests pin architecture, backend, and build id for the
*runtime* (per `runtimes.py`'s module docstring), and `GgufArtifact`/`GgufFile` in
`artifacts.py` model the *model* file itself. Tier 4 extends that existing manifest
discipline from "which runtime build is this" to "which exact model weights are these, and
were they modified since the vendor signed them" — a content hash/signature check against a
vendor-published manifest, verified inside the same attested boundary Tier 3 already
establishes.

**Why this is worth doing next, not just noting.** It's nearly free given the Tier 3
groundwork — same manifest/attestation machinery, same `local/` home, same `attest` extra
for the signature-verification piece — and it converts "confidential execution" into
"confidential *and verified* execution," which is the stronger of the two claims for buyers
who care as much about model integrity as prompt secrecy (a tampered or substituted model is
its own compliance/safety failure mode, independent of who could read the prompt).

**Included**
- A signed manifest format for model weights (hash + vendor signature), extending the
  existing `runtime.json` pattern rather than inventing a parallel one.
- A verification check, run inside the attested boundary, added to
  `ConfidentialExecutionStatus` as an additional field (e.g. `model_verified: bool`) rather
  than a separate status object — callers already have one place to look.
- Reuse of the `attest` extra from §4 for the signature-verification dependency; no new
  extra needed.

**Decided (2026-08-12): each vendor signs their own model manifests with their own keys —
AnyInfer never operates a shared signing service.** This mirrors how the local runtime
manifests already work today (the operator/vendor owns the artifact and its manifest, per
`runtimes.py`'s existing model), keeps AnyInfer out of key-custody liability, and means the
signing-key question is the vendor's own PKI/secrets-management problem, not a new service
AnyInfer has to build, host, or be trusted to secure. `anyinfer-confidential` (or core, for
the Tier 3/4 verification path) ships **verification** tooling — public-key registration and
signature-check logic — never a signing endpoint or private-key handling of any kind.

**Explicitly excluded**
- Any model-integrity claim outside the Tier 3 attested path (verifying a hash on an
  unattested host is a weaker, different claim and must not be marketed as Tier 4).
- Vendor key management/signing infrastructure — this verifies signatures, it does not
  operate a signing service. (Confirmed as a deliberate decision above, not just a default.)

## 4b. Considered and deliberately not pursued: BYOK fleet governance/allowlisting

An admin-set policy layer (which providers/models/keys are permitted org-wide) was floated
alongside 1–3 and set aside, on the owner's own reasoning (2026-08-12): it's structurally
close to imposing GPO/MDM-style device policy, which is a different product category, and —
more concretely — it's hard-to-impossible to test meaningfully with what AnyInfer currently
has, since "does this policy actually hold" requires the kind of fleet/device-state
observability this project has never taken on. It also sits close to DESIGN.md's explicit
non-goal boundary against anything that looks like adaptive routing or load balancing, so
pursuing it would mean fighting that boundary as well as the testability problem. Recorded
here so it isn't re-proposed without this context; revisit only if a concrete customer need
makes the testing problem tractable (e.g., a customer willing to co-design the observability
surface), not as a speculative feature.

## 5. Honest tiering as the differentiator, and compliance packaging built on it

Ship a single "Confidentiality Tiers" doc (Tier 0: none, through Tier 3: attested, plus
Tier 4: verified from §4a) mapped against the provider/adapter matrix, so a customer can see
per-deployment what's actually guaranteed. The differentiation isn't any one tier — it's
that AnyInfer would be the only BYOK framework in this market with an articulated, audited
trust boundary at all, versus the usual unverifiable "your data is safe with us" marketing
copy. Marketing claims must map 1:1 to the tier actually in use; lower-tier language must
never borrow a higher tier's guarantee strength.

**Compliance packaging is the GTM layer on top of that doc, not new engineering.** Once the
tiers are honestly documented, the same facts can be re-expressed as a control-language
mapping for the frameworks enterprise buyers actually evaluate against — SOC2, HIPAA,
FedRAMP-style language. This is closer to a translation exercise than a build:

- **Content, not code.** A mapping table: each tier's concrete guarantee (e.g. Tier 3's
  "not even root on the host can read the prompt, when `end_to_end` is true") restated
  against the specific control language auditors look for (e.g. confidentiality-of-data-
  in-use controls). No new runtime behavior — it's documentation over §2–4a's existing facts.
- **One asset per framework**, since SOC2/HIPAA/FedRAMP auditors expect their own vocabulary
  even when the underlying control is identical.
- **Decided (2026-08-12): draft SOC2 first.** Reasoning given: broadest applicability for a
  B2B software vendor selling to other companies, and the framework most likely to be the
  first ask from any enterprise procurement process regardless of the buyer's industry —
  versus HIPAA/FedRAMP, which are worth building only once a specific healthcare or
  public-sector customer conversation makes the need concrete. HIPAA/FedRAMP mappings stay
  deferred until that happens, not built speculatively.
- **Must stay mechanically traceable to real behavior**, not aspirational: every claim in the
  compliance doc should cite the specific typed fact it rests on (`ConfidentialExecutionStatus.end_to_end`,
  the Relay's zero-retention contract, `model_verified`) so the mapping can be re-verified
  against the code rather than going stale the way marketing docs usually do. This is the
  same discipline as ADR-012's typed-fact pattern applied to a sales artifact instead of an API.
- **Sequencing:** this genuinely can't start before §4a's Tier 4 language stabilizes (it's
  being mapped), but the mapping table itself has no engineering dependency — it can be
  drafted in parallel with implementation once the tier definitions stop moving, rather than
  waiting for code to ship first.

**Why this is a real rarity, not just positioning.** Most competitors in this market can only
offer prose assurances about data handling because their architecture doesn't produce a
falsifiable fact to point to. A compliance doc that cites a specific typed field an auditor
could ask to see verified — rather than a paragraph of policy language — is the differentiator;
the tiers are what make the doc honest instead of aspirational.

**Calibrated competitive claim (researched 2026-08-12, see §4c for sources) — get this
precise before it's ever said to a customer or a journalist.** The underlying cryptography is
*not* undiscovered territory: NVIDIA ships the CC driver and NVAT attestation SDK, Azure and
GCP both have GA confidential-GPU offerings, and hosted confidential-GPU clouds already exist
(Phala, Spheron sell attested inference as a service). Claiming "no one is doing confidential
AI" would be false and trivially fact-checked. What genuinely doesn't exist, as far as this
research found: **a portable capability check packaged inside a multi-provider BYOK library**
— every existing player is either a confidential-GPU *cloud* you rent (not bring-your-own),
or a research protocol wired to one specific backend (Secure Minions only talks to Ollama, and
is an unshipped research preview). The correct claim is narrower and more defensible: *"the
integration and honesty layer — one function that tells a caller what it can actually
guarantee, across providers and local runtimes, failing closed when it can't — doesn't exist
anywhere else."* That's also the harder thing to copy, since it requires the multi-provider
breadth AnyInfer already has as a prerequisite, not just access to the same hardware everyone
else already has access to. Marketing copy, the Confidentiality Tiers doc, and
`docs/why-anyinfer.md`'s forward-looking section must all use this narrower framing, not the
broader one.

## 6. Suggested implementation order

1. **Tier 3 feasibility — researched 2026-08-12, see §4c for full findings and sources.**
   Build the CPU-only path first (SEV-SNP/TDX CVMs, all three backends unmodified, GA on all
   three major clouds today) — it's the low-lift, high-confidence case. Treat GPU-offload
   (H100 CC on Azure/SEV-SNP or GCP/TDX specifically) as a second, harder milestone requiring
   real integration work (NVAT, per-cloud attestation services, PPCIE multi-GPU verification)
   gated behind confirming AWS's GPU-CC status and the OpenRM-vs-proprietary-driver question
   flagged in §4c, not a blocker to shipping the CPU-only claim.
2. Implement `confidential_execution_status()` first, ahead of the adapter wrapper: CPU TEE
   detection, GPU CC-capability and CC-enabled detection, in `local/hardware.py`'s advisory,
   never-raising style. Then build `ConfidentialExecutionAdapter` as a thin fail-closed
   consumer of that same function, so enforcement and pre-flight checks share one
   implementation from day one rather than being reconciled later.
3. Stand up `src/anyinfer-shared/` and `src/anyinfer-confidential/` as independent
   sub-projects per §1's decided layout: own `pyproject.toml` each, own importable package
   (`anyinfer_shared`, `anyinfer_confidential`), editable-installable, `anyinfer-confidential`
   depending on `anyinfer` (and `anyinfer-shared` only once a real shared type exists — leave
   it empty otherwise).
4. Implement `SealedTemplate`/`TemplateVault` (Tier 1) end to end: seal step, runtime
   decrypt-render-discard, the hybrid entitlement model from §2 (offline signed license blob
   validation as the always-on path; opt-in online revocation check with cached
   last-good-answer and fail-open-to-offline behavior on network failure, per §2's flagged
   default), key rotation.
5. Implement the `AnyInfer Relay` (Tier 2) as a deployment-agnostic service from the start
   (no self-host-only assumptions to retrofit later): minimal assemble-and-forward surface,
   zero-retention logging discipline, multi-tenant isolation between vendors' traffic (needed
   specifically because the hosted option exists), self-hosting docs, credential handling
   reusing `anyinfer.credentials` resolver patterns. Ship self-hosted-capable first if
   sequencing forces a choice — it's the version required regardless of whether hosted ever
   launches — then add the hosted deployment/ops layer (see open question on hosting
   platform) as a parallel track rather than blocking Relay code on it.
6. Implement Tier 4 (§4a) once Tier 3 is stable: signed model-weight manifest format (vendor
   signs with their own keys, per the decided signing model), `model_verified` field on
   `ConfidentialExecutionStatus`, verification (public-key registration + signature check,
   never signing) reusing the `attest` extra already built for Tier 3.
7. Write the Confidentiality Tiers doc (Tiers 0–4) and wire it into the same docs surface
   that lists other optional add-ons (`[serve]`, `[mcp]`, the vector store add-on).
8. Draft the SOC2 compliance-packaging mapping doc from §5 (decided first framework) —
   content work, can start once tier definitions stop moving, doesn't block on the rest of
   the implementation order.
9. Conformance tests per tier: Tier 1 — no plaintext template reachable on disk after seal,
   entitlement rejection behavior, key-rotation invalidation, offline validation with no
   network access, revocation-check fail-open behavior under simulated network failure;
   Tier 2 — zero-retention audit (nothing durable written across a request lifecycle),
   credential non-persistence, cross-vendor isolation under the hosted deployment; Tier 3 —
   fail-closed behavior when attestation is unavailable or fails verification; Tier 4 —
   tampered-weight rejection, unsigned-manifest rejection, rejection of a manifest signed by
   an unregistered/wrong vendor key.

## 7. Open questions for the owner, deferred to when this plan is picked up

Resolved 2026-08-12 by direct interview (package location, Relay hosting, Tier 1 licensing
model, Tier 4 signing model, Relay/entitlement service separation, compliance framework) —
see the "Decided" call-outs inline in §1–§5. Also resolved 2026-08-12 by research (§4c, with
sources): Tier 3 feasibility is gated by deployment topology, not by backend choice — all
three backends run unmodified in a CVM. Genuinely still open:

- **AWS GPU-CC status.** No evidence of an AWS confidential-GPU offering was found in this
  research pass; that's an absence-of-evidence finding, not a confirmed "AWS doesn't have
  this" — needs a direct check against current AWS docs before the Confidentiality Tiers doc
  asserts anything about AWS one way or the other.
- **OpenRM vs. proprietary NVIDIA driver for CC mode.** Whether the open-source `OpenRM`
  kernel module supports Hopper Confidential Computing mode, or whether CC mode requires
  NVIDIA's closed-source driver, wasn't confirmed — matters for documenting deployment
  prerequisites accurately.
- **H200/Blackwell CC availability on a major cloud.** Only H100 CC was confirmed GA on
  Azure/GCP in this pass; H200/Blackwell CC was only found via a third-party GPU-rental
  provider. Tier 3's GPU marketing claim should scope to H100 until this is separately
  checked, and should be revisited as the market moves (this is exactly the kind of claim
  that needs periodic re-verification, similar in spirit to `contracts/DRIFT-CHECK.md`'s
  discipline for provider claims, even though it's not a provider contract itself).
- Whether Nitro Enclaves' storage/networking constraints (§4c) are worth the engineering lift
  for the CPU-only case given SEV-SNP/TDX CVMs already cover it with near-zero lift — leaning
  "skip Nitro Enclaves for v1," but worth the owner's explicit call before it's dropped from
  scope entirely.
- Tier 3 GPU-offload sizing: even with H100 CC confirmed available on two clouds, how much of
  the real local-inference audience that actually covers (vs. the CPU-only case, or vs.
  non-H100 GPU hardware operators run locally) still isn't sized — worth doing before treating
  GPU-accelerated Tier 3 as a headline claim rather than the CPU-only case.
- **New, from the "both hosted and self-hosted from day one" decision:** the operational plan
  for AnyInfer's own hosted Relay — hosting platform, SLA commitments, on-call/incident
  posture, and pricing/business model for the hosted offering — none of that is designed yet,
  and it's real scope (operating infrastructure, not just shipping code) the owner should
  weigh in on before implementation order item 5 reaches the hosted half.
- **New, from the hybrid entitlement decision:** whether fail-open-to-last-cached-answer is
  actually the right default for revocation-check network failures (§2's flagged
  recommendation), or whether some/all vendors will want hard fail-closed enforcement as a
  configurable option — this is a real security-posture tradeoff (availability vs. guaranteed
  revocation) worth the owner's explicit sign-off rather than resting on the recommended
  default alone.
- Whether `anyinfer-shared` ends up holding a real type (the composite confidentiality-result
  case sketched in §1) or stays empty — can't be resolved until Tier 1/2 and Tier 3/4 are far
  enough along to know if that composite reporting need is real.
