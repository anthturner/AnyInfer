# Context reduction subsystem (`anyinfer.context`) — token-reduction strategies

**Scope:** a new optional, dependency-free subpackage `anyinfer.context` that reduces an
app-supplied document corpus to fit a model's context budget, shipping five strategies:
`whole`, `ranked`, `tiered`, `packed`, and `distill` (map/reduce). **Goal:** stop Frisket
and mote-cli from each maintaining their own context machinery; give every AnyInfer
consumer a batteries-included "fit this corpus to this window" answer that composes the
D25 estimator/budget surfaces. **Non-goal:** collection. The library never walks a
filesystem, never decides what is safe to send, and never embeds anything.

**Audience for this plan:** contributors editing the existing files
directly. Every section includes concrete file paths, exact constants, and acceptance
checks. Code audit below is as of **2026-08-07** (Frisket, mote-cli, and AnyInfer working
trees); re-verify before starting each task.

**Authority:** DESIGN.md §2 (non-goals — amended by this plan), §7, §18, §20 item 1,
§21, §23 (ADR-005, ADR-007), §25; NOTES.md D1, D2, D3, D15, D20, D25, D27; the L5
"degradations are typed events" rule (NOTES.md comparative review).

**Governance intent:** this is **new scope** that conflicts with the DESIGN.md §2
non-goal "No prompt templating" and brushes "Not an agent framework." Per the repo rule
(flag, don't pick silently) it must land a NOTES.md decision row and an ADR before
implementation. **Numbering resolved at landing:** this shipped as **D28** and
**ADR-011** on 2026-08-07; the local-model catalog and model-retrieval plans that the
original caveat expected to take those numbers landed later, as **D30** and **D31**.
The library-side work (TC.1–TC.8) is complete; what remains is TC.9 and TC.10, the
Frisket and mote-cli migrations, which are separate change sets in those repositories
and are the acceptance test for D1.

---

## 1. Motivation and evidence

Two of the three v1 customer apps (D1) have independently built this layer:

- **Frisket** — `src/frisket/context_selector.py` (378 lines), `context_tiers.py`
  (260), `_context_structure.py` (241), plus the collection-side `context.py` (413):
  a BM25-style lexical ranker with path-match boosting and anchor-file bonuses, four
  strategies (`auto`, `whole-file`, `structural`, `structural+digest`), and a tiered
  rollup/extract/verbatim representation. Stdlib-only.
- **mote-cli** — `src/mote/runtime/chunking.py` (1,025 lines): chunk planning with
  boundary-aware splitting, parallel map workers, a single-pass LLM (or deterministic)
  merge, and its **own token estimator** — duplicating what D25 just centralized
  (`estimation.estimate_text_tokens` delegates to chunking's `_estimate_tokens`).

Both already sit on the arithmetic AnyInfer ships: Frisket's `estimate_tokens` is
`math.ceil(bytes / 3)` (`prompt_budget.py:110`) — **identical to the planning side of
`HeuristicTokenEstimator`** (`capabilities/estimate.py`, `ESTIMATE_BYTES_PER_TOKEN = 3`).
Frisket's `resolve_context_budget` consumes the same allowance arithmetic D25 ported.
The seam is real: this subsystem is the packing layer D25's `ContextBudget.remaining_tokens`
docstring already anticipates ("the number an app packs context against").

This mirrors the pattern that justified AnyInfer itself: shared machinery, independently
reinvented, drifting apart. Unlike the tool loop (risk R5, zero consumers at ship time),
this subsystem has two consumers with working code to port, and the sibling migrations
are the acceptance test (D1: "published after migrations prove the API").

## 2. The boundary: apps collect, the library reduces

The port boundary follows Frisket's own internal seam:

**Stays app-side (never ports):**

- Filesystem walking, ignore rules, secret-name exclusion (`context.py`
  `DEFAULT_EXCLUDED_DIRECTORIES`, `SECRET_NAMES`, `SECRET_SUFFIXES`), size caps,
  symlink policy, user approval, named-context config — the app decides *what exists*
  and *what is safe to send*.
- Binary-format text extraction (`_context_extractors.py`: .docx/.xlsx/.pdf) — reading
  bytes off disk is collection.
- Digest *generation* and its cache (`_context_digest.py` cache files) — issuing model
  calls to summarize modules is an app policy decision; the library only *renders*
  digests it is handed (§5.3).
- mote's VRAM/RAM worker heuristics (`platform.py` probes) — hardware admission belongs
  to `anyinfer.local` (D16), not to a reduction algorithm.
- mote's JSON parse/repair stack (`_parse_model_json`, unfinished-JSON retries) —
  superseded by AnyInfer's native structured output + bounded repair (D6).

**Ports into `anyinfer.context`:**

- The ranker (scoring formula, constants, tie-breaking, pinning) — §5.2.
- Selection loops and budget accounting (fast path, greedy skip-and-continue) — §5.2.
- The tiered representation (rollup share, depth sweep, extract/verbatim tiers,
  digest rendering, `module_surfaces`) — §5.3.
- The structural-extract projector (`_context_structure.py`: 12-language regex table,
  generated-file exclusion) — §5.3.
- Boundary-aware chunk splitting and the map/reduce shape (mote), rebuilt on
  `AsyncClient` with asyncio concurrency and a hierarchical-merge fix — §5.4, §5.5.

**Non-goal tension, addressed head-on.** "No prompt templating" exists so apps own
their prompt *language*. The reducer emits a **mechanical, documented data envelope**
(file/extract/rollup blocks — §6), not a template engine: no user-visible prose, no
placeholders, no per-app phrasing. The core already performs exactly this kind of
mechanical, contract-serving prompt construction: the C3 repair prompt, C4 schema
prompt-injection, and F1 grammar injection. "Not an agent framework" excludes planning,
memory, and multi-agent constructs; `distill` is a bounded, deterministic two-phase
fan-out (fixed map→reduce, no planning loop), the same class of bounded extra calls as
the D6 repair loop. Both carve-outs are written into the amendment (§3.2) rather than
argued case-by-case later.

**Capability-parity framing (flat-ground objective):** context reduction is an
*emulation* of a larger window — state 2 of the three-state model. Emulation must
announce itself: every reduction is observable (typed event + content-free summary,
§7), never silent.

## 3. Governance package (ready-to-apply text)

### 3.1 NOTES.md decision row (append to the table; renumber if D28/D29 land first)

```markdown
| D29 | Context reduction subsystem (2026-08-07, amends the §2 "No prompt templating"
non-goal; see plans/TOKEN_REDUCTION_ALGS.md) | Optional dependency-free subpackage
`anyinfer.context`: apps collect documents (filesystem, approval, secrets policy stay
app-side), the library reduces them to a caller-supplied token budget. Five strategies:
`whole` (passthrough when the corpus fits), `ranked` (lexical BM25-style greedy
selection ported from Frisket `context_selector.py`, constants preserved), `tiered`
(rollup/extract/verbatim coverage ported from Frisket `context_tiers.py` +
`_context_structure.py`), `packed` (chunk-level rank-and-pack, new), `distill`
(map/reduce over the client, generalizing mote-cli `runtime/chunking.py`; the only
strategy that spends inference, async-first with a sequential sync facade). Packing
targets `ContextBudget.remaining_tokens` (planning side); unknown windows stay unknown —
the caller must supply an explicit budget (no 16k fallback, ADR-005 discipline).
Reduction is always observable: `ContextReduced` telemetry event (content-free) +
`Reduction.summary()`. Rendering is deterministic and path-ordered by default for
prompt-cache stability. No embeddings (open question 8 stands), no filesystem access,
no new dependencies (slim core, ADR-007). Frisket and mote migrations are the
acceptance test (D1). |
```

### 3.2 DESIGN.md §2 non-goals amendment (exact replacement)

Replace the single bullet at DESIGN.md line 67:

```markdown
- **No prompt templating.** Frisket/mote keep their own prompt construction.
```

with:

```markdown
- **No prompt templating.** Frisket/mote keep their own prompt construction. *Amended
  (D29, 2026-08-07):* the optional `anyinfer.context` subsystem renders a mechanical,
  documented context envelope (file/extract/rollup blocks) as reducer output — a data
  format like the C3/C4 injection prompts, not a template engine. Apps still own all
  surrounding prompt text, and the core client never constructs prompts on their behalf.
```

And extend the "Not an agent framework" bullet (DESIGN.md lines 61–62) with one
sentence:

```markdown
- **Not an agent framework.** A tool-execution loop is provided (late in v1), but no
  planning, memory, or multi-agent constructs. *Clarified (D29, 2026-08-07):*
  `anyinfer.context.distill` is a bounded, deterministic map/reduce fan-out — fixed
  two-phase shape, no planning — permitted on the same grounds as the schema-repair
  loop's bounded extra calls.
```

### 3.3 DESIGN.md new section (append as §26; full text)

```markdown
## 26. Context reduction subsystem (`anyinfer.context`)

*Added by D29 (2026-08-07); see plans/TOKEN_REDUCTION_ALGS.md for algorithms and port
provenance.*

An optional, dependency-free subpackage that answers one question: **given documents
the app has already collected and approved, what should actually be sent to fit a
token budget?** The boundary is strict — apps collect (filesystem, approval, secrets
policy), the library reduces (rank, select, represent). The subsystem never performs
I/O, never reads paths off disk, and adds no dependencies.

Inputs are `ContextDocument` values (path, content, sha256, pinned flag, optional
language + structural extract) and an explicit token budget. The budget is the app's
number, normally `ContextBudget.remaining_tokens` from a preflight `client.budget()`
call; when the window is unknown the budget is unknown, and the caller must choose —
the library never invents a window (same tri-state rule as §7 and cost).

Strategies: `whole` (send everything when it fits), `ranked` (lexical
relevance-ranked whole documents, greedy skip-and-continue), `tiered` (full corpus
coverage at decreasing fidelity: module rollup → structural extracts → verbatim
files, with optional app-supplied module digests), `packed` (chunk-level
rank-and-pack for sub-document granularity), and `distill` (map/reduce through the
client itself — the only strategy that spends inference calls, async-first). `auto`
dispatches `whole` when the corpus fits, else `tiered`.

Reduction is emulation of a larger context window, and emulation announces itself:
every reduction returns full metadata plus a content-free summary, and emits a
`ContextReduced` telemetry event when an observer is supplied. Rendering is
deterministic and path-ordered by default so repeated turns over the same corpus
keep a stable prompt prefix (provider prompt caches, llama-server slot reuse).

Ranking is lexical (a BM25-style scorer ported from Frisket, with path-match
boosting and anchor-file bonuses). Embeddings-based ranking remains out of scope
(a §2 non-goal; NOTES.md open question 8) — the ranker protocol accepts a
replacement when that changes.
```

### 3.4 DESIGN.md §23 new ADR (append after ADR-010; full text)

```markdown
### ADR-012 — Context reduction: apps collect, the library reduces

**Decision.** Ship an optional `anyinfer.context` subpackage implementing corpus
reduction (rank / select / represent / distill) against an explicit token budget, with
collection (filesystem traversal, approval, secret exclusion) permanently app-side.
Reduction composes the D25 estimator/budget surfaces; it never performs I/O and adds
no dependencies. **Why.** Two of the three v1 customers independently built and now
maintain divergent copies of this layer (Frisket's selector/tiers, mote's chunker);
both already depend on the same byte-heuristic arithmetic D25 centralized. Collection
stays out because it is where the security policy lives (what exists, what is safe to
send) and where every app differs; reduction is where the apps converge.
**Consequences.** The §2 "No prompt templating" non-goal is narrowed: the library owns
one mechanical envelope format, apps own all prompt language around it. `distill`
spends inference calls, so it is separated by construction (async function taking the
client, aggregate `Usage` reported) from the pure strategies. Lexical ranking sets
retrieval-quality expectations the docs must manage (risk R8); embeddings stay out
until NOTES.md open question 8 reopens.
```

### 3.5 DESIGN.md §18 package layout (add under `src/anyinfer/`)

```markdown
  context/           # D29 corpus reduction: documents.py rank.py structure.py
                     # envelope.py select.py tiers.py pack.py distill.py
```

### 3.6 DESIGN.md §21 new risk

```markdown
- **R8 — Retrieval-quality expectations creep** — a lexical ranker invites "why didn't
  it find X" reports and pressure toward embeddings/rerankers the slim core forbids.
  Mitigate: docs state the ranking model plainly (ASCII-alphanumeric lexical matching,
  path boosting); the ranker sits behind a protocol so exact/semantic implementations
  can be supplied by apps; NOTES.md open question 8 owns the embeddings decision. The
  12-language structural-extract table is a staleness surface like the catalog (R6) —
  languages are added by one suffix-map entry + one extract branch, covered by tests.
```

### 3.7 What this plan does **not** amend

- IMPLEMENTATION.md §D is not amended *by this plan document* — but per the SIDECAR
  precedent (its design-doc obligations fold its plan-local tasks into
  IMPLEMENTATION.md at landing), §13's tasks are drafted plan-local in §D format and
  **folded into IMPLEMENTATION.md** (an M5 follow-on or a new milestone) when this
  plan lands; TC.1 owns that fold.
- contracts/ — a pure client-side module has no wire behavior, so no
  `contracts/<name>.md` snapshot exists or is needed (D24 applies only if reduction
  ever alters per-provider wire output). The D24 date discipline (never fabricate
  dates) still binds this plan's tables.
- CLAUDE.md/AGENTS.md/`.github/copilot-instructions.md` "D1–D24" staleness — flagged
  here; fix in the landing change set alongside the new decision row, not silently.

## 4. Package design

### 4.1 Modules

```
src/anyinfer/context/
  __init__.py    # public re-exports, sorted __all__
  documents.py   # ContextDocument, RankCache
  rank.py        # tokenize, score, rank(), build_rank_cache()
  structure.py   # language table, structural_extract(), is_generated_path()
                 # (imported by documents.py for ContextDocument.of auto-detection)
  envelope.py    # block renderers + byte accounting (single source of truth)
  select.py      # select(), Reduction, whole/ranked strategies, auto dispatch
  tiers.py       # tiered strategy, module_surfaces()
  pack.py        # chunk splitting, packed strategy
  distill.py     # async distill(), sync sequential facade, SupportsGenerate protocol
tests/context/   # mirrors the package (AGENTS.md: tests mirror the package)
```

Conventions (all per AGENTS.md / IMPLEMENTATION.md §A): every public type
`@dataclass(frozen=True, slots=True)`; interfaces are `typing.Protocol`; Google
docstrings on every public symbol (docs build gates on it); no ADR/D numbers in
docstrings or docs pages — cite decisions in plain words; module docstrings may cite
internal anchors the way `capabilities/estimate.py` does.

### 4.2 Packaging and exports

- **No new dependencies.** Everything is stdlib (`collections`, `math`, `re`, `html`,
  `hashlib`, `pathlib`, `asyncio`) + intra-package imports. Slim core (ADR-007) is
  untouched. `anyinfer.context` follows the `anyinfer.local` precedent exactly — a
  plain, always-importable subpackage **with a reserved empty extra** (`context = []`,
  mirroring the existing `local = []`), so `pip install "anyinfer[context]"` is valid
  and forward-compatible if a dependency ever appears.
- **Own-path imports** (`from anyinfer.context import select, distill`), like
  `local`/`serve`/`testing` — not re-exported from top-level `anyinfer/__init__.py`.
  Exception: the `ContextReduced` event class lives in `events/telemetry.py` (§7) and
  re-exports wherever the other events do.
- Wheel packaging is automatic (`packages = ["src/anyinfer", ...]`).
- mypy `--strict` covers it automatically via `files = ["src/anyinfer", ...]`.

### 4.3 Import-linter contracts (pyproject.toml, verification ledger §E.4)

New packages are not covered automatically; add:

1. To **"Adapters never orchestrate"** `forbidden_modules`: add `"anyinfer.context"`
   (adapters translate; they never reduce prompts).
2. To **"Serve is a codec around the client, never a second core"**
   `forbidden_modules`: add `"anyinfer.context"` (the codec must stay a wire
   projection; reduction is app-side policy).
3. To **"Types are leaf modules (zero I/O)"** `forbidden_modules`: add
   `"anyinfer.context"`.
4. New contract:

```toml
[[tool.importlinter.contracts]]
# Context reduction composes the core's leaf surfaces; it never reaches the client,
# adapters, or the wire. distill takes the client by structural Protocol, so even the
# one strategy that generates text has no _client import.
name = "Context reduction is a leaf consumer"
type = "forbidden"
source_modules = ["anyinfer.context"]
forbidden_modules = [
  "anyinfer.providers",
  "anyinfer.routing",
  "anyinfer._client",
  "anyinfer.serve",
  "anyinfer.local",
  "anyinfer.schema",
  "anyinfer.catalog",
  "anyinfer.credentials",
  "httpx2",
]
```

Allowed imports for `anyinfer.context`: `anyinfer.types`; the
`anyinfer.capabilities.estimate` and `anyinfer.capabilities.budget` submodules **by
full path only** — never the `anyinfer.capabilities` package root, whose `__init__`
imports `pricing_table` and therefore `httpx2`, which would trip this contract's own
forbidden list (import-linter walks the whole chain, and `include_external_packages =
true` puts `httpx2` in the graph); `anyinfer.events` (the `Observer` protocol,
`EventDispatcher`, and `ContextReduced`; `events.telemetry` carries no policy — same
reasoning as deviation I4); and `anyinfer.errors` (`ConfigError` for distill's
unknown-window case).

### 4.4 Core types

```python
@dataclass(frozen=True, slots=True)
class ContextDocument:
    path: str                      # posix-style relative path; identity + rank signal
    content: str
    sha256: str                    # hex digest of content (utf-8); identity in envelopes
    pinned: bool = False           # ports Frisket explicitly_selected: sorts before all
    language: str | None = None    # from structure.py table, or app-supplied
    extract: str = ""              # structural extract; "" = none

    @classmethod
    def of(cls, path: str, content: str, *, pinned: bool = False,
           language: str | None = None, extract: str | None = None) -> ContextDocument:
        """Compute sha256; detect language and extract via structure.py when omitted.

        Explicit language/extract values pass through untouched; extract="" opts out.
        """
```

```python
@dataclass(frozen=True, slots=True)
class Reduction:
    strategy: str                          # requested strategy ("auto" preserved — see §5.1)
    representation: str                    # "whole" | "ranked" | "tiered" | "packed"
    documents: tuple[ContextDocument, ...] # documents represented at detail level
    candidate_count: int
    text: str                              # the rendered envelope — ALWAYS rendered
    estimated_tokens: int                  # planning-side estimate of `text`
    max_tokens: int
    max_bytes: int
    max_documents: int
    total_bytes: int                       # byte length of `text` (utf-8)
    binding_constraints: tuple[str, ...]   # subset of ("document count","bytes","tokens")
    budget_source: str = "explicit"        # caller-supplied label, e.g. "budget()"
    tier_metadata: Mapping[str, object] | None = None

    @property
    def omitted_count(self) -> int: ...
    def metadata(self) -> dict[str, object]: ...   # Frisket-compatible keys (scoped — see deviations)
    def summary(self) -> str:                      # content-free, ports context_selection_message
```

Deviations from Frisket recorded here (the port's I-table equivalents):

- `text` is **always rendered** (Frisket's fast path returned `context_text=None` and
  apps called `context_envelope` themselves — two code paths for one job).
- In `tiered`, `documents` is the set actually represented at extract/verbatim detail,
  **not** the ranked prefix (fixes the Frisket quirk where `ContextSelection.files`
  disagreed with tier composition).
- `strategy` preserves the requested value even on the fast path (`auto` stays
  observable; Frisket rewrote it to `whole-file`).
- `metadata()` parity is **scoped**: Frisket's `context_window_tokens` /
  `max_prompt_tokens` keys are dropped — underivable once the budget is a bare caller
  int; the Frisket migration re-adds them app-side in its own metadata wrapper.
  `selection_mode` stays (derivable from `omitted_count`). The summary's
  "using the {source} budget" clause survives via the caller-supplied `budget_source`
  label (`select(..., budget_source="budget()")`).
- The greedy path always reports `representation="ranked"`, including for
  `strategy="whole"` that did not fit (Frisket hardcoded `"whole-file"` for both
  paths).
- `auto` renders module digests whenever `module_digests` is supplied; Frisket's
  `auto` never rendered digests (only the explicit `structural+digest` strategy did).

### 4.5 Budget flow (the D25 seam — normative)

- `select()` takes `max_tokens: int` — **an explicit caller number**. The intended
  source is `client.budget(messages_without_context, target=...).remaining_tokens`
  (the app builds its request skeleton, asks what's left, hands that number to the
  packer). This composes D25/D27 without duplicating them.
- **Unknown stays unknown**: when `remaining_tokens` is `None` (unknown window) the
  library does not guess. `select()` requires an int; the app chooses its own
  fallback explicitly. Frisket's 16k fallback is deliberately not ported (same
  decision D25 already made once).
- Packing arithmetic uses the estimator's **planning figure** (`TokenEstimate.tokens`,
  conservative-high — safe for packing). The floor is the gate's number
  (`capabilities/gating.py`) and is never used here. Estimator is pluggable:
  `estimator: TokenEstimator | None = None` defaults to `HeuristicTokenEstimator()`,
  whose planning side (`ceil(bytes/3)`) is numerically identical to Frisket's
  `estimate_tokens` — ported behavior is unchanged by construction.
- Byte ceilings remain first-class (`max_bytes`, default 4 MiB; `max_documents`,
  default 200 — Frisket's `DEFAULT_MAX_SELECTED_BYTES` / `DEFAULT_MAX_SELECTED_FILES`)
  because transports cap bytes independently of tokens
  (`GenerationRequest.max_response_bytes` precedent).

## 5. The five strategies

### 5.1 Strategy surface

```python
VALID_STRATEGIES = ("auto", "whole", "ranked", "tiered", "packed")

def select(
    documents: Iterable[ContextDocument],
    query: str,
    *,
    max_tokens: int,
    strategy: str = "auto",
    max_documents: int = 200,
    max_bytes: int = 4 * 1024 * 1024,
    estimator: TokenEstimator | None = None,
    rank_cache: RankCache | None = None,
    module_digests: Mapping[str, str] | None = None,   # tiered only; rendered, never generated
    render_order: Literal["path", "rank"] = "path",
    budget_source: str = "explicit",       # echoed into Reduction/metadata/summary
    chunk_target_tokens: int = 512,        # packed only
    min_chunk_tokens: int = 64,            # packed only
    observer: Observer | None = None,
) -> Reduction: ...
```

`normalize_strategy()` ports Frisket's normalizer (None/blank → `"auto"`, strip+lower,
`ValueError` listing valid names on unknown). **`auto` dispatch (Frisket parity):**
`whole` when the whole enveloped corpus fits all three ceilings, else `tiered`.
`packed` is explicit opt-in (it changes granularity, which is an app-visible semantic
change, not an escalation). `distill` is a separate async function (§5.5), not a
`select()` strategy, because it spends money.

**Renamed from Frisket** (library-neutral): `whole-file`→`whole`,
`structural`→`tiered`, `structural+digest`→`tiered` + `module_digests=` (digest
rendering is gated on the argument being supplied, not on a strategy name — one less
strategy string; note `auto` thereby honors supplied digests, which Frisket's `auto`
never did — recorded deviation, §4.4). Frisket's migration shim maps old names.

**Determinism guarantee (all strategies):** identical inputs produce byte-identical
`Reduction.text`, independent of document iteration order. `render_order="path"`
(default) renders selected documents sorted by `(path, sha256)` regardless of rank, so
consecutive turns over the same corpus share a stable prompt prefix (provider prompt
caches; llama-server slot reuse). `render_order="rank"` preserves Frisket's
rank-ordered rendering for apps that want strongest-first ordering.

### 5.2 `whole` and `ranked` (port of `context_selector.py`)

**Ranking — ported exactly, constants and all** (`rank.py`):

- Tokenization: `re.compile(r"[A-Za-z0-9]+")`, lowercased, minus the 51-word
  `STOP_WORDS` set (ported verbatim). ASCII-only by design; documented limitation.
- Per-document score against query term counts `qf`:
  - IDF: `idf = log((N + 1) / (df + 1)) + 1`
  - Lexical: `Σ  qf · idf · f / (f + 1.2 + 0.001 · doc_len)` (saturation 1.2,
    length-normalization 0.001 · total token count)
  - Path score: `Σ qf · path_token_count(term)`, weighted **4.0**
  - Anchor bonus **0.25** when `PurePosixPath(path.lower()).name` or `.stem` is in
    `ANCHOR_NAMES` (ported set: architecture, changelog, contributing, design,
    overview, readme, cargo.toml, go.mod, package.json, pom.xml, pyproject.toml)
- Sort key: `(not pinned, -score, path.count("/"), path, sha256)` — every pinned
  document outranks every unpinned one; then score, shallower path, path, sha256.
  Fully deterministic.
- `RankCache` ports `ContextRankCache` (per-doc term Counters + document frequency);
  `build_rank_cache()` public. Cache validity is the **caller's** job (key it on a
  corpus hash, as Frisket's planner keys on `snapshot.sha256`) — the O(corpus)
  tuple-equality revalidation inside Frisket's `_rank` is not ported; passing a stale
  cache is documented as undefined ranking (not an error).
- `rank(documents, query, *, rank_cache=None)` is **public** (Frisket kept `_rank`
  private; both other strategies and apps need it).

**Selection (`select.py`):**

- Envelope byte accounting is exact and lives only in `envelope.py`: per-document
  block bytes = rendered block bytes (§6); corpus base = wrapper bytes. Fast path:
  `whole`/`auto` return everything when `count ≤ max_documents and bytes ≤ max_bytes
  and estimator.estimate(text).tokens ≤ max_tokens`, `binding_constraints=()`.
- Greedy loop (`ranked`, or `whole` that does not fit): iterate rank order;
  - document-count ceiling reached → record `"document count"`, **break** (no later
    document can satisfy a count limit — Frisket's asymmetry is correct; keep it);
  - byte overflow → record `"bytes"`, **skip and continue** (a smaller lower-ranked
    document may still fit);
  - token overflow → record `"tokens"`, skip and continue.
  - Per-document token estimates are computed per block and summed (per-file `ceil`
    may slightly exceed a whole-envelope estimate; keep Frisket's per-file basis —
    it is the conservative direction and the greedy loop needs per-item numbers).
  - The greedy path reports `representation="ranked"` regardless of the requested
    strategy (deviation from Frisket's `"whole-file"` reporting, §4.4).
- `binding_constraints` = names of every ceiling that excluded at least one document,
  fixed order `("document count", "bytes", "tokens")`; `()` when nothing was excluded.
- `ValueError` on `max_documents < 1 or max_bytes < 1 or max_tokens < 1` ("Context
  selection budgets must be positive.").

### 5.3 `tiered` (port of `context_tiers.py` + `_context_structure.py`)

Full-coverage representation: every document appears somewhere; fidelity decreases
down the tiers. Ported algorithm with constants:

1. **Module rollup** (45% share: `DEFAULT_ROLLUP_SHARE = 0.45` of both token and byte
   budgets, byte floor 256): group documents by path prefix at the deepest depth whose
   rendering fits the share (sweep from max depth down to 1 at `symbol_limit=18`;
   degrade at depth 1 through symbol limits `(12, 8, 4, 2, 0)`; a symbol-free depth-1
   rollup always renders, even over budget). Groups ordered `(-member_count, name)`.
   Per group: member count, corpus share (`.3f`), sorted unique languages,
   `dependencies:` line (exact line prefixes `"import "`, `"using "`, `"# include"` —
   hash-space, an upstream Frisket quirk ported verbatim and flagged as such —
   `"package "`, `"from "`; at most `symbol_limit` deduped entries, **each entry**
   capped at 120 chars — the cap is per entry, not per line),
   `symbols:` line (class/interface/function/def/enum/widget:/namespace matches from
   member extracts; at most `symbol_limit` deduped entries, each capped at 120 chars).
2. **Module digests** (only when `module_digests=` supplied): rendered block of
   app-provided per-module summary strings, admitted only if it fits remaining
   budgets. The library never generates digests; `module_surfaces(documents, *,
   depth=2)` ports as the public helper apps use to build digest inputs (deterministic
   module→surface-text map; a cookbook recipe shows generating digests with the
   client and caching them keyed on `sha256(surface)`, mirroring Frisket's cache key
   discipline — cache storage stays app-side).
3. **Extract tier**: rank order; documents with non-empty `extract` render as extract
   blocks while they fit (skip-and-continue).
4. **Verbatim tier**: rank order again; documents not already in the extract tier
   (including extract-less ones) render whole while they fit.

Tiers **admit** documents in rank order (budget flows to the strongest matches) but
**render** each tier's admitted set per `render_order` (path default, preserving the
§5.1 cache-stability guarantee; `"rank"` restores Frisket's iteration-order
rendering). Rollup groups keep their own `(-member_count, name)` ordering in both
modes.

Ported quirk **fixes** (each is a deliberate deviation, tested):

- No bare `dependencies:` line when the symbol limit is 0 (Frisket renders an empty
  label).
- `binding_constraints` reports the ceiling that actually bound (bytes vs tokens),
  not always `("tokens",)`.
- `Reduction.documents` = extract-tier ∪ verbatim-tier documents (what is actually
  at detail level), with rollup coverage reported via `tier_metadata`
  (`coverage_fraction` stays 1.0 by construction).

`structure.py` ports `_context_structure.py` unchanged in behavior: the
suffix→language table (12 languages: csharp, typescript, javascript, java, c, cpp,
dart, powershell, markdown, python, xml, shell; `.h`/`.txt` deliberately `None`),
`MAX_EXTRACT_CHARS = 12_000`, `MAX_SECTION_CHARS = 2_000`,
`SMALL_FILE_VERBATIM_BYTES = 512` (small files verbatim regardless of language),
regex-only extraction (no `ast`), truncation marker `"[truncated structural
extract]"`, and `is_generated_path()` (vendor/third_party segments, `.min.js`,
`.g.dart`, `moc_*.cpp`, `.designer.cs`, etc.) as a public helper apps may use at
collection time. One fix: the bare `except Exception` around extraction narrows to
`except (re.error, ValueError)` — mypy-strict-friendly and honest (`BLE` ruff rule is
already enabled in this repo).

### 5.4 `packed` (new; chunk-level rank-and-pack)

Neither app has this: Frisket ranks whole files; mote chunks without ranking. RAG-lite
without retrieval infrastructure:

1. **Split** each unpinned document into chunks targeting
   `chunk_target_tokens = 512` (planning tokens). Char budget per chunk =
   `chunk_target_tokens × 3` (the explicit inverse of the byte heuristic — an
   intentional, documented conversion, unlike mote's silent token/char conflation).
   Boundary rule ports mote's `_split_text_into_chunks`: prefer the last `"\n\n"`
   within budget; if that lands before ¼ of the budget, fall back to the last `"\n"`;
   if still before ¼, hard-cut. Chunks record `(start_line, end_line)`.
2. **Rank.** Pinned documents rank first, whole, via `rank()` (§5.2). Chunks do not
   go through `rank()` (its sort key needs `sha256`/`pinned` and its document
   frequencies are corpus-wide): `pack.py` builds per-chunk pseudo-documents (chunk
   text as body; the parent document's path supplies the path score and anchor
   bonus), computes document frequency **over the chunk set**, calls the public
   scoring primitive in `rank.py` directly, and sorts by `(-score, path,
   chunk_index)`.
3. **Pack** greedily: pinned documents whole (skip-and-continue on overflow), then
   chunks by rank (skip-and-continue on bytes/tokens; `max_documents` counts
   *documents represented*, not chunks).
4. **Render**: group selected chunks by path (path order), within a path by position;
   **coalesce adjacent chunks** into one block (no duplicate headers, no fake gaps);
   non-contiguous chunks of one document render as separate blocks with line spans
   (§6). Reading order is stable and cache-friendly.

Defaults: `chunk_target_tokens = 512` (about 1,536 bytes — big enough for a whole
function, small enough for four chunks per typical budget-thousand); `min_chunk_tokens
= 64` (tail chunks merge backward). Both are keyword parameters of `select()` (§5.1),
documented as packed-only alongside `module_digests`.

### 5.5 `distill` (map/reduce; generalizes mote `runtime/chunking.py`)

The only strategy that spends inference. Async-first (D3), takes the client by
structural protocol so `anyinfer.context` never imports `_client`:

```python
class SupportsGenerate(Protocol):
    async def generate(self, messages, *, target: str,
                       sampling: Sampling | None = None) -> Generation: ...
    def budget(self, messages, *, target: str,
               sampling: Sampling | None = None) -> ContextBudget: ...
    # AsyncClient satisfies this structurally; verify signature compatibility in TC.7.

async def distill(
    source: str | Iterable[ContextDocument],
    query: str,
    *,
    client: SupportsGenerate,
    target: str,
    max_output_tokens: int = 1024,          # final answer budget
    chunk_tokens: int | None = None,        # None → derive from client.budget()
    concurrency: int = 4,
    sampling: Sampling | None = None,       # applied to every call; per-phase output caps override
    map_instructions: str | None = None,    # replaces the default map prompt
    reduce_instructions: str | None = None, # replaces the default reduce prompt
    reducer: Callable[[Sequence[str]], str] | None = None,  # deterministic reduce hook
    observer: Observer | None = None,
) -> Distillation: ...

@dataclass(frozen=True, slots=True)
class Distillation:
    text: str
    chunk_count: int
    calls: int                    # total generate() calls (maps + reduces)
    usage: Usage                  # SUMMED across all calls — never Usage.merge (see below)
    reduce_depth: int             # 1 = single-pass; >1 = hierarchical
    notes: tuple[str, ...] = field(repr=False)   # intermediate map outputs
```

Algorithm (ported shapes marked):

1. **Plan.** `chunk_tokens` unset → `client.budget(map_skeleton, target=target)
   .remaining_tokens` where `map_skeleton` is the map prompt with an empty chunk
   (ports mote's measure-overhead-with-empty-text trick, in tokens). If that is
   `None` (unknown window), raise `ConfigError("distill needs an explicit
   chunk_tokens for <target>: its context window is unknown", hint="pass
   chunk_tokens=, or choose a target with a known context window")` — unknown stays
   unknown.
2. **Split** with the §5.4 boundary rules. Document inputs split per-document
   (document boundaries are natural chunk boundaries — subsumes mote's
   `file`/`diff-file` granularities); string input splits as one stream.
3. **Map.** Each chunk → `generate()` with the map prompt: the app's `query`, the
   chunk in a `<chunk>` block, and a ported processing note ("chunk i of n …
   produce partial notes, preserve specific facts, no final answer, no chunk
   labels"). Concurrency via `asyncio.Semaphore(concurrency)` + `gather` (mote's
   ThreadPoolExecutor shape, async-native; per-adapter fairness is future routing
   work). Map output cap ports mote's `_map_max_tokens` table: single chunk or
   `max_output_tokens ≤ 768` → uncapped; ≥16 chunks → 384; ≥8 → 512; else 1024.
   Failed chunks propagate their `ProviderError` (the app's `Route` already owns
   retry/fallback policy; distill adds none — ADR-003 spirit).
4. **Reduce.** `reducer` callable set → deterministic reduce, zero extra calls
   (ports mote's `deterministic_reduce`; mote's structured merge helpers stay
   app-side). Otherwise one `generate()` over
   `<intermediate-note index="i">` blocks with the merge instructions (ported
   prompt language, neutralized: synthesize, don't mention chunks/notes).
   **Fix over mote:** the reduce input is estimated first; when the notes exceed the
   target's remaining allowance, reduce **hierarchically** — group notes into
   allowance-sized batches, reduce each, recurse (depth reported as
   `reduce_depth`; mote's single-pass merge silently overflows with many chunks).
5. **Sanitize.** Port mote's `_strip_private_chunk_labels` (drop `## Chunk 3` /
   `Intermediate note 2 of 5:`-style leakage, collapse blank runs) on the final text.

**Normative defaults.** The default per-chunk processing note ports mote's
`_default_chunk_processing_note` (chunking.py:709-715) verbatim: "This is chunk
{index} of {total} from a larger input. Produce concise partial notes for final
synthesis, preserve specific facts and implications, and do not write a full final
answer yet. Do not label the notes with chunk, part, or section headings." The
default reduce instructions port `_MERGE_PROMPT` / `_MERGE_SYSTEM`
(chunking.py:223-235) with the merge-system text folded into the single reduce
message (distill sets no system message — the app's prompt language stays app-owned).
Message shape: each map call is **one `user` message** — `query`, blank line, the
`<chunk>` block, blank line, the processing note; the reduce call is one `user`
message — reduce instructions with the `<intermediate-note>` blocks inline.
`map_skeleton` (step 1) is exactly that map message list with an empty chunk body.
Sampling: the caller's `sampling=` is applied to every call with `max_output_tokens`
overridden per phase (map cap table; `max_output_tokens` for the final reduce);
temperature inherits the provider default when unset.

Deliberately **not** ported: worker-count VRAM/RAM probing (hardware admission is
`anyinfer.local`'s job; local targets serialize at the llama-server slot level
anyway), the unfinished-JSON detect/retry/repair stack (superseded by native
structured output + repair, D6 — a flat-ground win), engine-name-keyed worker
policy, env-var knobs, private-engine spawning.

**Sync facade** (D3/ADR-002; AGENTS.md rule 3: "never add sync-only paths" — and
mote is sync): `distill_sync`
takes the sync `Client` via the mirrored `SupportsGenerateSync` protocol and runs
chunks **sequentially** (documented; mote's integrated engine is serial by default
anyway). Concurrency is the async path's feature.

**Cost honesty:** `Distillation.usage` **sums** every call's reported usage
component-wise via a private `_sum_usage()` in `distill.py` (`None` is the additive
identity per field; `Decimal` addition for `cost_usd`). `Usage.merge` must **not** be
used here — it is a last-wins *overlay* built for incremental streaming reports
within one attempt (`types/results.py` "Later usage reports win"), and folding N
calls through it would report roughly the last call's numbers, silently
under-counting spend. `calls` makes the multiplier visible; the concept page states
plainly that distill trades inference spend for window size. Preflight: the cookbook shows estimating map-phase
cost with `client.budget()` per chunk before committing (D27's `CostEstimate` range).

### 5.6 Rejected-alternative note the docs must carry

"Send it as multiple messages" does not help: every message in a request shares one
context window. What works is fidelity reduction within one request (`ranked` /
`tiered` / `packed`) or multiple requests (`distill`). This goes in the concept page's
opening (it is the first question every integrator asks).

## 6. Envelope format (normative)

Neutral tags (Frisket's `frisket-` prefix dropped); attribute values HTML-escaped with
`quote=True`; **module-digest bodies HTML-escaped too** (Frisket parity — file,
chunk, and extract bodies stay raw); sha256 raw hex; blocks newline-joined; no
trailing newline. Byte
accounting in `select()`/`tiers.py`/`pack.py` is defined as **the byte length of these
exact renderings** — one implementation in `envelope.py`, used by both accounting and
rendering (Frisket keeps them equal by hand; the port makes it structural).

```
<context>                                          # wrapper, whole/ranked/packed
  <file path="P" sha256="H">…content…</file>       # whole document
  <file-chunk path="P" sha256="H" lines="A-B">…</file-chunk>   # packed, per span
</context>

<context-tiers coverage_files="N">                 # tiered wrapper
  <module path="G" files="N" corpus_share="0.NNN" languages="L1, L2">
    dependencies: …                  # ≤symbol_limit entries, each ≤120 chars; omitted when empty
    symbols: …                       # ≤symbol_limit entries, each ≤120 chars; omitted when empty
  </module>
</context-tiers>
<module-digests>                                   # only when module_digests supplied
  <module path="NAME">DIGEST</module>
</module-digests>
<file-extract path="P" sha256="H">…extract…</file-extract>
<file path="P" sha256="H">…content…</file>
```

The envelope is versioned prose in the concept page (apps may parse it back out of
transcripts); changing it is a documented breaking change. The app places
`Reduction.text` in its own message — typically one `user`-role part above the
question; the library never touches `GenerationRequest.messages`.

## 7. Telemetry and observability

- New event in `events/telemetry.py` (added to the `TelemetryEvent` union, `__all__`,
  `events/__init__`, top-level re-export — the four-site checklist; **not** in
  `PAYLOAD_FIELDS`, it is content-free by construction):

```python
@dataclass(frozen=True, slots=True)
class ContextReduced:
    """A context corpus was reduced to fit a budget.

    Reduction emulates a larger context window; emulation is observable, never
    silent. Carries counts and ceilings only — no paths, no content.
    """
    strategy: str
    representation: str
    candidate_count: int
    selected_count: int
    omitted_count: int
    estimated_tokens: int
    max_tokens: int
    binding_constraints: tuple[str, ...]
    calls: int = 0                # distill: generate() calls spent; 0 for pure strategies
```

- **Distill field mapping** (distill performs no selection, so the selection-shaped
  fields are defined here, not invented per-implementer): `representation="distill"`
  (the one value beyond `Reduction.representation`'s four — the event's field is
  wider than `Reduction`'s), `candidate_count = selected_count = chunk_count`,
  `omitted_count = 0`, `binding_constraints = ()`, `max_tokens = chunk_tokens`, and
  `estimated_tokens` = the planning-side estimate of the source text.
- `select()`/`distill()` emit it via the optional `observer: Observer | None`
  parameter, **wrapped in `EventDispatcher`** (exported from `anyinfer.events`) so a
  raising observer is isolated — swallowed and warned exactly as on the client's
  emission path; a broken telemetry sink must never fail a reduction.
  There is no `request_id` — reduction is preflight, before any request exists;
  distill's individual sub-requests are already fully observable through the client's
  own event stream.
- `Reduction.summary()` ports `context_selection_message`: human-readable, truthful,
  and content-free (counts, tokens, ceilings, binding constraints — never paths or
  content). `Reduction.metadata()` carries the full machine-readable record
  (Frisket-compatible keys; paths appear only in `documents`, which the app already
  holds).

## 8. Security posture (D20)

- **No I/O.** The subpackage never opens files, sockets, or subprocesses (the leaf
  import contract in §4.3 partially enforces this by forbidding `httpx2`).
- **The app owns the safety boundary.** Secret-file exclusion, ignore rules, and
  approval happen at collection, before the library ever sees content. The concept
  page states this plainly and points Frisket users at their existing exclusion lists
  as the pattern.
- Events and summaries are content-free (no paths in events — path names themselves
  can be sensitive). `Distillation.notes` carries model output text; it is
  `repr=False` and documented as payload-bearing.
- Nothing here is redacted by `anyinfer.redaction` (that registry redacts *secrets
  registered by resolvers*, not user content) — reduction neither registers nor
  bypasses it.

## 9. Testing (per-task ACs in §13; the bar, stated once)

- **Ported-behavior parity:** every behavior Frisket's tests pin, re-pinned here:
  pinning beats a strictly-more-relevant document at `max_documents=1` with
  `binding_constraints == ("document count",)`; determinism under corpus reversal;
  path relevance outranking content-only matches; byte-overflow skip-and-continue;
  token binding with budget echo in `metadata()`; content-free `summary()`; tiered
  coverage fraction 1.0; `auto` and `whole` produce byte-identical `Reduction.text`
  when the corpus fits (the `strategy` field intentionally differs);
  strategy normalization (case, unknown-name `ValueError`); digest block only when
  digests supplied; language table incl. `.h` → `None` and the 512-byte small-file
  verbatim rule; annotation preservation (Java `@Service`, Dart `widget:` lines).
- **New-behavior tests:** path-ordered rendering stability (same selection ⇒
  byte-identical text across query rewordings that select the same set); packed
  coalescing (adjacent chunks merge, spans correct); packed pinned-whole precedence;
  quirk fixes (no empty `dependencies:` label; bytes-vs-tokens binding attribution;
  tiered `documents` = rendered set); distill hierarchical reduce triggering on
  many-chunk inputs; distill unknown-window `ConfigError`; distill against
  `testing/fakes.py` with deterministic fake responses (component-wise usage
  summing, call counts, label sanitization); sync facade sequential parity; a
  raising observer never fails a reduction (dispatcher isolation).
- **Gates:** mypy `--strict`, ruff (incl. `BLE`), docstring coverage via docs build,
  import-linter §E.4 green with the new contract, doc examples executed against fake
  providers in CI (§25 rule).
- Optional: port Frisket's `scripts/benchmark_context.py` shape as
  `scripts/benchmark_context_reduction.py` (rank + tier construction latency on a
  synthetic corpus) — nice-to-have, not a gate.

## 10. Documentation deliverables (D23; §25 obligations)

All user-facing text in plain words — no ADR/D numbers in docs or docstrings:

- `docs/concepts/context-reduction.md` — the boundary (collect vs reduce), the five
  strategies and when each wins, the multiple-messages misconception (§5.6), the
  lexical-ranking expectations statement (R8), envelope format reference, cache-stable
  ordering. Nav under `Concepts:`; listed in `docs/concepts/README.md` and
  `docs/README.md`.
- `docs/guides/fitting-context.md` — task-oriented: build documents → `client.budget()`
  → `select()` → place `Reduction.text` → observe `ContextReduced`. Runs against fake
  providers in CI.
- `docs/examples/distill-a-repository.md` — cookbook: chunk a large corpus, map/reduce
  with cost preflight, deterministic-reducer variant, digest generation + caching
  recipe (the app-side pattern).
- `docs/reference/api/context.md` — mkdocstrings page; grouped per §4 module list.
- Error catalog: no new exception classes (reuses `ConfigError`/`ValueError`), so
  `docs/reference/errors.md` gains only the new `ConfigError` emission note.
- `mkdocs.yml` nav entries for all of the above.

## 11. Migration plans (separate change sets, sibling repos — never edited from here)

**Frisket** (replaces `context_selector.py`, `context_tiers.py`,
`_context_structure.py`; keeps `context.py` collection, GUI, digest cache, binary
extractors):

- `ContextFile` → `ContextDocument.of(...)` (`context_name` stays app-side, wrapped or
  carried in a parallel map; `explicitly_selected` → `pinned`).
- Strategy names map: `whole-file`→`whole`, `structural`→`tiered`,
  `structural+digest`→`tiered` + `module_digests=`; settings shim accepts old names.
- `resolve_context_budget` → `client.budget(...).remaining_tokens` (Frisket keeps its
  own conservative fallback for unknown windows — its 16k default becomes an
  app-side choice, exactly where ADR-005 wants it).
- Envelope tag change (`frisket-context` → `context`): the inline assertions that
  pin envelope tags — `tests/test_provider_prompt_budget.py:438-439` (tag ordering
  inside the assembled prompt) and `tests/test_context_tiers.py:158` — update in the
  migration change set. (Frisket's `tests/golden/` files contain no envelope text.)
- Deleted: ~880 lines (`context_selector` + `context_tiers` + `_context_structure`).

**mote-cli** (replaces the map/merge core of `runtime/chunking.py`; keeps engine
plumbing, steering notes, structured-merge helpers):

- `run_chunked` → `distill_sync` (sequential — matches mote's integrated-serial
  default) or `distill` where mote goes async; `ActionChunkingStrategy.map_prompt` /
  `reduce_prompt` → `map_instructions` / `reduce_instructions`;
  `deterministic_reduce` → `reducer` (mote's `_structured_chunking.py` merge helpers
  stay in mote and pass through unchanged).
- mote's `_estimate_tokens` content-aware heuristic (minified/punctuation branches) is
  **not** ported into the default estimator; mote can keep it as its own
  `TokenEstimator` implementation — the protocol exists for exactly this.
- firehose.py does **not** migrate (it never used `run_chunked`; its streaming window
  is different machinery).

Both migrations are the D1 acceptance test; neither happens in this repo's change set.

## 12. Explicitly rejected (recorded so they are not revisited casually)

- **Embeddings/semantic ranking** — open question 8 owns it; the ranker protocol is
  the extension point.
- **Filesystem walking / collection helpers** — the security boundary lives there;
  permanently app-side.
- **Automatic client integration** (`client.generate(..., corpus=...)`) — the request
  stays explicit; reduction output placement is prompt construction, which apps own.
- **Multi-message splitting as a "fit" technique** — shares one window; documented
  misconception (§5.6).
- **Porting mote's VRAM worker heuristics** — hardware admission is `anyinfer.local`
  (D16).
- **Porting mote's JSON parse/repair stack** — superseded by D6 structured output +
  repair.
- **A 16k fallback window** — ADR-005; unknown stays unknown.
- **Digest generation in the library** — spending inference implicitly is exactly
  what D27's "the library never fetches implicitly" discipline forbids by analogy;
  rendering yes, generating no.

## 13. Task plan (IMPLEMENTATION.md §D format; plan-local, per SIDECAR precedent)

Legend: each task = **id · name → files · [depends on]**, then acceptance criteria
(AC). Work strictly in order.

- **TC.1 · governance landing → NOTES.md, DESIGN.md, AGENTS.md, CLAUDE.md,
  .github/copilot-instructions.md, IMPLEMENTATION.md · []** — AC: decision row
  appended with the next free D-number (verify against the LLAMACPP plan's D28
  claim); §2 non-goal bullets amended per §3.2; §26 + ADR (next free number ≥ 012) +
  §18 layout + R8 appended per §3.3–3.6; the "D1–D24" staleness fixed in all three
  agent-instruction files; §13's tasks folded into IMPLEMENTATION.md §D (M5
  follow-on or a new milestone) per §3.7; all cross-references resolve.
- **TC.2 · documents + rank + structure → context/{__init__,documents,rank,
  structure}.py, tests/context/test_{rank,structure}.py · [TC.1]** — AC: scorer
  reproduces §5.2 formula with ported constants (golden scores on a fixture corpus);
  pinning, determinism-under-reversal, path-relevance, tie-break tests green;
  `RankCache` reuse produces identical ranking to cold rank; `structure.py` language
  table parity incl. `.h`→`None`, the 512-byte small-file verbatim rule, annotation
  preservation (Java `@Service`, Dart `widget:`), `is_generated_path()`. **structure
  lands here, not later, because `ContextDocument.of()` calls it** for language and
  extract detection (§4.4).
- **TC.3 · envelope + select → context/{__init__,envelope,select}.py,
  tests/context/test_select.py · [TC.2]** — AC: `whole`/`ranked`/`auto` per §5.1–5.2;
  byte accounting equals rendered bytes structurally (property test: accounting ==
  `len(text.encode())` for arbitrary selections); binding-constraint semantics;
  greedy path reports `representation="ranked"`; path-vs-rank render order;
  `Reduction.metadata()`/`summary()` content-free test. The `tiered`/`packed`
  dispatch branches exist but raise `NotImplementedError` until TC.4/TC.5.
- **TC.4 · tiers → context/{__init__,select,tiers}.py, tests/context/test_tiers.py ·
  [TC.3]** — AC: tier budget split (0.45 share, byte floor 256, depth sweep
  18→(12,8,4,2,0)); per-entry 120-char caps; digest rendering gated on the argument
  and HTML-escaped; the recorded quirk fixes asserted; coverage fraction 1.0;
  `select()`'s `tiered` branch wired. `tiers.py` returns an internal tier result that
  `select.py` wraps into `Reduction` — imports stay one-directional (select → tiers).
- **TC.5 · packed → context/{__init__,select,pack}.py, tests/context/test_pack.py ·
  [TC.3]** — AC: boundary rules (¶/newline/hard-cut with ¼ threshold) ported with
  span tracking; chunk pseudo-document scoring per §5.4 step 2 (chunk-set document
  frequency, `(-score, path, chunk_index)` sort); pinned-whole precedence;
  coalescing; deterministic byte-identical output; `select()`'s `packed` branch
  wired, same one-directional wrapping as TC.4.
- **TC.6 · telemetry + gates → events/telemetry.py, events/__init__.py,
  anyinfer/__init__.py, context/select.py, pyproject.toml · [TC.3]** — AC:
  `ContextReduced` in the `TelemetryEvent` union + all re-export sites, absent from
  `PAYLOAD_FIELDS`; **emitted by `select()`** through `EventDispatcher` when an
  observer is supplied (distill's emission lands with distill in TC.7); a raising
  observer does not fail the reduction; import-linter green with the §4.3 contract
  additions **including the capabilities-submodule-path rule** (no
  `anyinfer.capabilities` package-root import anywhere in the subpackage); `context
  = []` extra added; mypy strict + ruff green for the whole subpackage.
- **TC.7 · distill → context/{__init__,distill}.py, tests/context/test_distill.py ·
  [TC.5, TC.6]** — AC: `SupportsGenerate` satisfied structurally by `AsyncClient`
  (assert via a typing test; adjust the protocol to the real `generate`/`budget`
  signatures); budget-derived chunk sizing from `map_skeleton`; unknown-window
  `ConfigError` with hint; ported map/reduce default instruction text and message
  shape (§5.5); `_map_max_tokens` table ported; hierarchical reduce triggers and
  reports `reduce_depth`; **component-wise usage summing (never `Usage.merge`)** and
  call count; label sanitization; `ContextReduced` emission with the §7 distill field
  mapping; sync facade sequential parity — all against `testing/fakes.py`.
- **TC.8 · docs → docs/concepts/context-reduction.md, docs/guides/fitting-context.md,
  docs/examples/distill-a-repository.md, docs/reference/api/context.md,
  docs/reference/errors.md, mkdocs.yml, docs/README.md, docs/concepts/README.md,
  docs/guides/README.md, docs/examples/README.md, docs/reference/api/README.md ·
  [TC.7]** — AC: docs build green (docstring coverage); guide + cookbook execute
  against fake providers in CI; every section index lists its new page; no ADR/D
  numbers anywhere user-facing; R8 expectations statement present.
- **TC.9 · Frisket migration → ../Frisket (separate change set) · [TC.8]** — AC per
  §11; Frisket suite green with `anyinfer.context`; ~880 app lines deleted.
- **TC.10 · mote migration → ../mote-cli (separate change set) · [TC.8]** — AC per
  §11; mote actions green on `distill_sync`; chunking.py reduced to app-policy shims.

## 14. Open questions (append to NOTES.md open questions on landing)

1. Should `packed` ever join `auto`'s escalation chain (whole → tiered → packed?), or
   does granularity change remain forever opt-in? Decide after both migrations report.
2. Does mote's content-aware estimator (minified/punctuation branches) belong in core
   as an alternative shipped `TokenEstimator`? It is stdlib-only and strictly more
   conservative on code — but D25 chose one deliberately simple default. Revisit with
   migration calibration data.
3. Envelope versioning: is prose documentation enough, or should `<context>` carry a
   `format=` attribute from day one? (Cheap now, awkward later.)
