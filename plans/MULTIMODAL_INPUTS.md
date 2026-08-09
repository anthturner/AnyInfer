# Multimodal inputs — activating the reservation

**Scope:** implement the multimodal *input* parts the message model has always reserved —
images, documents (PDF), and audio-in — as first-class `ContentPart` types, projected per
provider by adapters, gated by provenance-tagged capabilities, and reachable identically
from the SDK, the CLI, and the sidecar. **Goal:** a stock OpenAI client that attaches a PDF
or an image to `anyinfer-serve` gets an answer instead of a dropped field.
**Non-goal:** *outputs*. No image generation, no text-to-speech, no embeddings, no
fine-tuning. Those remain §2 non-goals, untouched.

**Audience for this plan:** contributors editing the existing files directly. Code audit is
as of **2026-08-09**; re-verify before starting each task. Every wire detail below is
*indicative* and must be established from live provider documentation into
`contracts/<id>.md` as part of the work — this plan does not assert protocol facts it has
not verified.

**Authority:** DESIGN.md §2 (non-goals — "No embeddings, images, audio, or fine-tuning
APIs. Text generation only. (Multimodal *inputs* are structurally reserved in the message
model but not implemented.)"), §5 (`ContentPart`), §7 (capabilities and `Feature`), §14
(payload privacy), §20 item 1 (token estimation and budgeting), §22 (sidecar), §24
(conformance matrix and contract snapshots); ADR-003 (adapters only translate), ADR-005
(provenance), ADR-009 (sidecar codec).

**Governance intent: this is the narrowest reading of a non-goal, not a reversal of it.**
§2 already carves out the distinction — *inputs* are "structurally reserved", and §5's
`ContentPart` union carries the comment "multimodal parts reserved for future". This plan
activates that reservation and changes nothing about outputs, embeddings, or fine-tuning.
The amendment should say exactly that, and should re-state the output non-goals in the same
breath so the boundary is legible to the next reader.

---

## 1. Motivation and evidence

- **The reservation is load-bearing and unused.** `ContentPart = Text | ToolCall |
  ToolResult` today. Every adapter, the codec, and the schema layer already pattern-match on
  that union, so adding members is a typed, compiler-visible change rather than an
  archaeology exercise — which is precisely what the reservation bought.
- **It is the largest remaining parity gap.** The sidecar accepts the OpenAI chat-completions
  surface, and that surface carries `image_url`, `input_audio`, and `file` content parts
  (verified 2026-08-09: files ride *inside* message content, not as a top-level parameter).
  A stock client attaching a PDF has nowhere for it to go, and no amount of configuration
  fixes that — unlike corpus reduction, this one cannot be worked around client-side by
  sending text instead, because the whole point is that the bytes are not text.
- **It is the widest gap between the stated ambition and what ships.** A hybrid inference
  runtime whose local subsystem downloads and supervises vision-capable GGUFs, and which
  cannot pass an image to any of them, is text-only in practice regardless of what the
  message model reserves.
- **Every dedicated adapter's provider supports it.** The seventeen adapters cover engines
  that all take image input in some spelling; the translation work is exactly the kind
  ADR-003 says belongs in adapters.

## 2. Design

### 2.1 The content parts

```python
@dataclass(frozen=True, slots=True)
class ImagePart:
    data: bytes | None            # inline bytes; the library base64-encodes at the wire
    url: str | None               # remote reference, when the provider fetches
    media_type: str               # "image/png", "image/jpeg", …
    detail: Literal["auto", "low", "high"] | None = None

@dataclass(frozen=True, slots=True)
class DocumentPart:
    data: bytes | None
    url: str | None
    media_type: str               # "application/pdf", …
    filename: str | None = None

@dataclass(frozen=True, slots=True)
class AudioPart:
    data: bytes
    media_type: str               # "audio/wav", "audio/mp3", …

ContentPart = Text | ToolCall | ToolResult | ImagePart | DocumentPart | AudioPart
```

Bytes, not base64 strings, in the domain type: base64 is a wire encoding, and holding the
encoded form in memory inflates every payload by a third for the entire request lifetime.
Adapters encode at projection. `detail` is carried normalized and dropped with a typed
event where a provider has no equivalent — the same treatment `reasoning` effort already
gets.

### 2.2 Capability gating is the hard part, not the encoding

Sending an image to a text-only model must fail *before* dispatch, or degrade visibly —
never silently. `Feature` gains `VISION`, `DOCUMENT`, `AUDIO_IN`, assembled through the
existing layered, provenance-tagged path (§7): static catalog, then live discovery, then
opt-in probes. The rules that already exist apply unchanged and are the reason this is
tractable:

- A `default`-provenance capability never gates (§20 item 1) — an unknown vision capability
  is not treated as absence.
- Copilot's `auto` sentinel takes the conjunction across candidate models (§7), so a
  delegating target is vision-capable only if everything it might pick is.
- Degradation emits `ParameterDropped`; refusal raises a `ProviderError` subclass with an
  actionable `hint`. Silence is not an option the codebase permits.

### 2.3 Token accounting, honestly

This is where the plan is most likely to go wrong. Image cost is not a byte count: providers
bill by tiles, patches, or resolution buckets, with per-provider formulas, and the
dependency-free byte heuristic (`capabilities/estimate.py`) has no defensible answer for
`ImagePart`.

The tri-state rule decides it: **an image whose token cost is not known from catalog data
makes the estimate unknown, not approximate.** `RequestEstimate` gains an
`unpriced_parts` count; a budget containing unpriced parts is `unknown`; the pre-dispatch
gate declines to gate on it rather than gating on a guess. Where a provider publishes a
formula it goes in the capability layer with `catalog` provenance and is applied; where it
does not, the number stays honestly absent. This preserves the property that makes the cost
and budget surfaces trustworthy, and it means the first release can ship correct-and-partial
rather than complete-and-wrong.

### 2.4 Wire projection, per adapter

One projection hook per adapter, no core branching. Each adapter's snapshot records its own
spelling — inline base64 versus uploaded-file reference, media-type constraints, size
ceilings, whether the provider fetches remote URLs itself, and what it does with a document
it cannot parse. Those are wire facts, so they belong in `contracts/<id>.md` with real
`last_verified` dates and are audited by the existing drift check (§24). **No adapter is
implemented from this plan's guesses**; each lands with its verified snapshot, its
conformance column, and its provider-docs page, exactly as a new adapter does.

Local inference is deliberately sequenced last: vision on `llama-server` needs a projector
artifact alongside the GGUF, which is a catalog, acquisition, and fit question
(`local/gguf.py`, `local/variants.py`, `local/fit.py`) rather than a protocol one, and it
should not block hosted support.

### 2.5 Size, privacy, and the sidecar

- **Request-side ceilings.** `GenerationRequest.max_response_bytes` has no request-side
  counterpart; multimodal needs one — a per-part and per-request byte cap, rejected with an
  actionable error rather than sent and refused remotely.
- **Payload privacy is unchanged but higher-stakes.** Image and document bytes are payloads:
  events stay content-free, observers need `payloads=True`, and no part content ever reaches
  an error `detail` or a log line. Add an explicit test that a redaction failure cannot leak
  bytes through `ErrorInfo`.
- **Sidecar parity comes free once the parts exist.** The codec already decodes message
  content arrays; `image_url`, `input_audio`, and `file` parts map onto the new types, and
  `request_to_openai` round-trips them. This is the ADR-009 invariant-1 test doing its job:
  the gap exists today precisely *because* `GenerationRequest` is not currently a superset
  of the OpenAI surface, which the invariant says is a design bug. Framing the work that way
  is more accurate than calling it a new feature.

## 3. Tasks

**MM.1 — §2 amendment**, before code: activate the input reservation, restate the output
non-goals, and record that ADR-009 invariant 1 is currently violated by the missing content
parts. Take an ADR number in landing order.

**MM.2 — content-part types + message model.** `ImagePart`, `DocumentPart`, `AudioPart`;
union extended; exhaustive-match sites updated. *Acceptance:* every existing pattern-match
site handles the new members explicitly; a text-only request is unchanged.

**MM.3 — `Feature` flags + capability assembly.** `VISION`, `DOCUMENT`, `AUDIO_IN` through
the layered provenance path. *Acceptance:* a `default`-provenance unknown does not gate; the
`auto` conjunction rule holds; a text-only target refuses an image with an actionable
`hint`.

**MM.4 — estimation and budgeting.** `unpriced_parts`, unknown-propagating budget, gate
declines rather than guesses. *Acceptance:* a request with one image against a model with no
published formula yields an unknown budget, and the gate lets it through rather than
inventing a number.

**MM.5 — request-side size caps.** Per-part and per-request ceilings with clear errors.
*Acceptance:* an oversized part is refused before any provider call.

**MM.6 — sidecar codec.** Decode and encode `image_url`, `input_audio`, `file` parts;
round-trip test. *Acceptance:* the ADR-009 invariant-1 round-trip test covers multimodal and
passes; a stock client's PDF attachment reaches a capable target.

**MM.7 — adapters, one at a time.** Each lands with: projection hook, verified
`contracts/<id>.md` update with a real date, conformance column, provider-docs page.
Sequence by coverage value, not alphabetically. *Acceptance:* per adapter, the shared
conformance suite passes in cassette and fake modes.

**MM.8 — CLI.** `anyinfer run --image`/`--document` with the same collection-side-only rule
the `context` verb follows. *Acceptance:* flags read files in the frontend; the library
receives bytes.

**MM.9 — local/vision.** Projector artifacts in the catalog, fit and variant handling,
llama-server flags. Sequenced last and separable. *Acceptance:* a vision GGUF plus projector
acquires, fits, and serves; a machine that cannot fit it gets the existing honest `no`
rather than a crash.

**MM.10 — docs.** Concepts page on multimodal inputs and their capability gating; the
unknown-token-cost rule stated plainly, because it is the surprising one; conformance matrix
rows.

## 4. Risks

- **R-MM1 — silent capability mismatch.** An image dropped on the way to a text model
  produces a confidently wrong answer about nothing. Mitigate: refusal by default, typed
  degradation events, and a conformance case per adapter asserting the refusal.
- **R-MM2 — token accounting fiction.** Guessing image tokens would poison budgeting, cost,
  and the spend ceiling at once. Mitigate: §2.3's unknown-propagation; no formula is
  invented, and `unpriced_parts` makes the gap visible rather than absorbed.
- **R-MM3 — memory and payload size.** Multi-megabyte parts through an async pipeline with
  base64 inflation at the edges. Mitigate: bytes in the domain type, encoding at projection,
  request-side caps, and no retention.
- **R-MM4 — matrix and snapshot sprawl** (R2 restated). Multimodal multiplies the
  conformance surface across seventeen adapters plus presets. Mitigate: MM.7 lands adapters
  individually; presets are covered by representatives per quirk axis as they already are;
  an unimplemented cell is `➖ documented`, not a blank.
- **R-MM5 — scope gravity toward outputs.** Image input makes image *output* look adjacent.
  Mitigate: MM.1 restates the output non-goals in the same amendment that activates inputs.
- **R-MM6 — local vision is a different project.** Projector artifacts, fit estimation, and
  runtime flags could consume the whole plan. Mitigate: MM.9 is last, separable, and
  droppable without affecting hosted support.

## 5. Decisions

**Resolved 2026-08-09 (user):** write this as a plan rather than recording it as an open
question or leaving it unexamined. It surfaced from the parity review, and it is the largest
gap between "swiss army knife of AI interaction" and what ships.

Open, and worth settling in MM.1:

1. **Which modality first.** Recommendation: images, then documents, then audio. Images have
   the broadest provider support and the clearest capability signal; audio-in is the
   thinnest and could be deferred indefinitely without much loss.
2. **Whether `AudioPart` ships at all in the first pass**, given that transcription is
   usually a separate API rather than a chat content part on most providers.
3. **Sequencing against the other plans.** This is larger than arena and SPEND_LEDGER
   combined and should not be interleaved with them; it wants a milestone, not a slot.
