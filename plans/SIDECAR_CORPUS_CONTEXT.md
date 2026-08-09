# Corpus reduction over the sidecar — stateless, per request

**Scope:** an `anyinfer_context` request extension that lets a sidecar client supply
documents alongside `messages`, have them reduced against the resolved target's budget by
the same `anyinfer.context` strategies the SDK and CLI use, and receive the rendered
envelope as part of the prompt. **Goal:** close the one capability a non-Python client
pointed at `anyinfer-serve` genuinely cannot reach today. **Non-goal:** server-side corpus
storage of any kind — no upload-once-reference-later, no corpus ids, no vector store, no
document cache. The extension is stateless per request, permanently.

**Audience for this plan:** contributors editing the existing files directly. Code audit is
as of **2026-08-09**; re-verify before starting each task.

**Authority:** DESIGN.md §2 (non-goals), §15 (shared configuration), §22 (sidecar surface
and its four invariants), §26 (the context subsystem), §27 (**the section this plan
amends**); ADR-009 (the sidecar is a codec), ADR-011 (apps collect, the library reduces).

**Governance intent: §27 currently forbids this, and the amendment must say why the
original reasoning does not hold — not merely that a decision changed.** §27 keeps corpus
reduction out of the sidecar because "carrying documents over the wire would make the
sidecar decide what is safe to send about material it never collected". That conflates two
different things. A client that puts documents in a request body has *already* collected
and approved them — it read the files, chose them, and serialized them deliberately. The
sidecar would not be deciding **what exists** or **what is safe**; it would be deciding
**what fits**, from a set handed to it explicitly. That is exactly the ADR-011 split ("apps
collect, the library reduces") with the app on the far end of a socket rather than
in-process. What genuinely argues against it is bandwidth and scope creep, and the
amendment should say so plainly so this is not re-litigated on a premise that does not
survive scrutiny.

---

## 1. Motivation and evidence

`anyinfer.context` ships a real reduction subsystem — ranked, tiered, packed, distilled,
with duplicate collapse, structural extracts, and sixteen tuning knobs (§26). Two surfaces
can reach it:

- **SDK callers** import `anyinfer.context` and pass their own `ContextDocument`s.
- **`anyinfer context`** collects from the filesystem in the CLI — deliberately, because
  collection is where the security policy lives — then reduces
  ([cli.py:221](../src/anyinfer/cli.py#L221), whose help text states the boundary).

A developer who chose the standalone binary precisely to avoid Python in-process gets every
provider, alias, route, and supervised local model — and then has to hand-roll BM25
ranking, tiered rollups, and chunk packing, or abandon the integration path they chose.
That is the pigeonholing the parity requirement rules out, and it is the *only* remaining
instance of it once arena lands.

**The OpenAI wire format offers no ready-made shape for this, verified 2026-08-09.** There
is no top-level `attachments`/`files` parameter parallel to `messages`; files ride inside a
message's content array as a `file` content part (`file_data` + `filename`, or `file_id`),
and the Responses API spells the same idea `input_file`. The `attachments` array belonged
to the Assistants API, which is being retired.

**And those parts must not be reused for this**, which is the load-bearing design
constraint. A `file` content part means *"put this in front of the model"* — it is
already-selected input. A corpus is *"here are candidates; send the ones that fit"*. If the
sidecar reinterpreted `file` parts as a candidate pool, a stock client attaching five PDFs
and expecting five read would silently get three, breaking ADR-009 invariant 1:
`GenerationRequest` is a **superset** of the OpenAI surface, and a superset adds fields
rather than redefining existing ones. So this is an explicit AnyInfer extension, exactly
like `anyinfer_history` and `anyinfer_arena`, and never an overload of standard fields.

## 2. Design

### 2.1 The extension

```jsonc
{
  "model": "medium",
  "messages": [ { "role": "user", "content": "why does auth fail on refresh?" } ],
  "anyinfer_context": {
    "documents": [
      { "path": "src/auth/session.py", "content": "…", "pinned": true },
      { "path": "src/auth/refresh.py", "content": "…" }
    ],
    "query": "auth refresh failure",     // defaults to the last user message
    "strategy": "auto",                  // §26 strategies; "distill" excluded (§2.4)
    "max_tokens": null,                  // defaults to the resolved target's budget
    "placement": "system",               // or "prepend_user"
    "tuning": { "compact_fallback": true }   // ContextTuning field names, §15 vocabulary
  }
}
```

Decoded by a `_decode_context` beside `_decode_history`
([serve/openai_codec.py:233](../src/anyinfer/serve/openai_codec.py#L233)) into a typed
`ContextRequest` carried on `GenerationRequest`. **The sidecar does not reduce**: it
decodes, and the client applies the policy — the same division §27 established for
`HistoryPolicy`, and the reason ADR-009 survives this plan intact.

### 2.2 Where the reduction actually runs

On `AsyncClient`, beside the context gate that already runs pre-dispatch. This is the part
that makes the feature parity-shaped rather than sidecar-shaped: once
`GenerationRequest.context` exists as a client-layer field, the SDK gains a per-request
spelling of what it currently does by hand, `anyinfer run` can accept `--context-file`
without re-plumbing, and the sidecar is a decoder. One implementation, four spellings, the
§2.6 pattern from the arena plan.

Reduction happens **after** target resolution, because the budget depends on the resolved
target's window, and **before** the context gate, because the whole point is to fit. The
existing tri-state rule holds without change: an unknown window yields an unknown budget,
and an unknown budget with no explicit `max_tokens` is a `ConfigError` — the library does
not invent a window to justify discarding documents (§26, §27).

### 2.3 Response reporting

The reduction is already required to announce itself: every reduction returns a
content-free summary and emits `ContextReduced` (§26). Over the wire, the same summary is
attached as an `anyinfer_context` object on the response — selected and omitted counts,
estimated tokens, strategy actually used, `complete` flag. A client that sent 400 documents
and had 380 dropped must be able to see that without reading server logs. Stock clients
ignore the field; the server-side event fires either way.

### 2.4 Bounds, because this is a payload surface

The honest objections to this feature are size and scope, so both get hard limits rather
than guidance:

- **Request size.** The existing config-file ceiling (`MAX_CONFIG_BYTES`) has an analogue
  here: a configurable `max_request_documents` and `max_request_bytes`, defaulting
  conservatively, rejected with a clear error rather than truncated. For reference, the
  OpenAI file-input path caps combined file payload at 50 MB per request; this is a
  different mechanism but the same order of magnitude is a sane default ceiling.
- **`distill` is excluded.** It is the one strategy that spends inference calls (§26), and
  a gateway that fans out extra generations because of a field in a request body is a very
  different security and cost surface from one that ranks text. Deterministic strategies
  only; `distill` stays SDK-side where the caller owns the client.
- **Statelessness is enforced, not merely intended.** No document content is retained after
  the response, nothing is written to disk, and there is no id-addressable corpus. The
  first feature request will be "upload once, reference by id"; that is durable server-side
  state, which is the second core ADR-009 forbids, and it is named out of scope in the
  amendment so the answer is already written down.
- **Payload privacy is unchanged.** Documents are payload-bearing; `ContextReduced` stays
  content-free, observers still need `payloads=True` to see text, and redaction applies to
  everything logged (§14).
- **Non-loopback exposure.** The existing rule already requires `allow_remote_exposure`
  plus a bearer token (§22). Worth restating in the docs for this feature specifically,
  since it is the first one where the request body routinely carries source code.

## 3. Tasks

**SC.1 — §27 amendment**, before code. Rewrite the corpus-versus-conversation paragraph to
distinguish "the sidecar never collected this" (true, and irrelevant when the client sends
it explicitly) from "the sidecar must not decide what is safe to send" (true, and not what
reduction does). Record the real constraints: bandwidth, no server-side corpus state, no
`distill`. Cross-reference the new §2 non-goal wording.

**SC.2 — `ContextRequest` type + `GenerationRequest.context`.** Frozen dataclass, defaults
that reproduce today's behaviour (absent field = no reduction). *Acceptance:* an
unconfigured request is byte-identical in behaviour to today's.

**SC.3 — client-side application.** Reduce after target resolution, before the gate;
`ContextReduced` emitted; unknown budget raises rather than guessing. *Acceptance:*
`tests/` covers the unknown-window refusal, the pinned-document guarantee, and that the
envelope lands in the position `placement` names.

**SC.4 — sidecar codec.** `_decode_context`, the `anyinfer_context` response summary, size
limits with clear errors. **No reduction logic in `serve/`.** *Acceptance:* round-trip
codec test; oversized request rejected with an actionable `hint`; `serve/` imports nothing
from `anyinfer.context`.

**SC.5 — SDK and CLI spellings.** Per-request `context=` on `generate`/`stream`;
`anyinfer run --context-file`/`--context-dir` reusing the CLI's existing collection code.
*Acceptance:* the same corpus and query produce identical envelopes through all three
surfaces — the parity claim, asserted.

**SC.6 — parity test.** Every field of `ContextRequest` reachable from the config block, a
CLI flag, and the sidecar decoder, in the shape the arena plan's AR.12 establishes.

**SC.7 — docs.** A guide page and an addition to the serve-binary manual. State the
statelessness guarantee, the size ceilings, and the `distill` exclusion up front; show the
response summary, because "what got dropped" is the question every user will have second.

## 4. Risks

- **R-SC1 — upload economics.** Sending a corpus so most of it can be discarded inverts the
  point of reduction. Mitigate: documented as a real cost; `plan()` already exists
  client-side for callers who want to decide before uploading; the CLI path remains the
  better answer for large local corpora and the docs say so.
- **R-SC2 — the statelessness slope.** "Upload once, reference by id" will be requested
  within a week of shipping. Mitigate: named out of scope in SC.1's amendment, not just in
  this plan.
- **R-SC3 — payload surface growth.** The sidecar now routinely holds source code.
  Mitigate: no retention, no disk, existing redaction, and a docs note on non-loopback
  exposure.
- **R-SC4 — quality expectations at a distance** (R8 restated). A remote client cannot see
  the ranker's reasoning and will report "it didn't find X". Mitigate: the response summary
  carries counts and the `complete` flag; the ranking model is documented in plain words as
  it already is for the SDK.

## 5. Decisions

**Resolved 2026-08-09 (user):** build this as its own plan, stateless only, rather than
folding it into the arena workstream or leaving §27 as written. Ordering is independent of
arena — the two share the parity principle and the four-spellings pattern, but no code.

Open, and worth settling in SC.1: whether `max_request_bytes` defaults small (a few MB,
forcing large corpora to the CLI) or large (matching the 50 MB order of magnitude of
comparable file-input paths). The conservative default is easier to raise later than to
lower.
