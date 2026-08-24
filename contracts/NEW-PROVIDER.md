# Adding a Provider — Canonical Procedure

Tool-agnostic procedure for adding a provider to AnyInfer, or for binding a new operation
(embeddings, reranking) onto a provider that already exists. Entry points: the
`add-provider` skill (Codex, Claude Code), the Copilot prompt
`.github/prompts/add-provider.prompt.md`, or any agent following this file directly.

It is the counterpart to [DRIFT-CHECK.md](DRIFT-CHECK.md): that procedure keeps a contract
snapshot true over time, this one produces the snapshot and the adapter in the first place.
Both exist because the failure mode is the same — protocol details believed rather than
verified.

Read [AGENTS.md](../AGENTS.md) first for the architecture rules this procedure assumes;
[docs/contributing/writing-an-adapter.md](../docs/contributing/writing-an-adapter.md) is the
prose companion explaining *why* an adapter is shaped the way it is. Neither repeats the
steps below.

## Step 0 — decide what you are actually adding

Four shapes, in ascending cost. Pick the smallest one that is honest.

| Shape | When | What you write |
|---|---|---|
| **Preset** | The service differs from OpenAI's `/chat/completions` only by base URL, auth spelling, output-token field name, listing shape, or a list of ignored parameters. | A `CompatPreset` entry in `providers/presets.py` plus a verified section in `contracts/openai-compat-presets.md`. |
| **Dedicated adapter** | Real protocol translation: a different request/response body, its own streaming framing, its own auth flow, or usage accounting the shared dialect cannot express. | `providers/<id>.py`, `contracts/<id>.md`, `docs/providers/<id>.md`, tests. |
| **New operation on an existing provider** | The provider is already here and upstream also serves embeddings or reranking. | An `embed()` / `rerank()` method, a `operations` widening on its descriptor, contract and docs updates. |
| **Out-of-tree adapter** | The provider is proprietary, private, or specific to one application. | Nothing in this repository — follow [docs/guides/custom-providers.md](../docs/guides/custom-providers.md) and ship an entry point. |

Choosing "dedicated adapter" for something a preset covers costs a permanent maintenance
surface; choosing "preset" for something that genuinely translates ships a provider that
fails the first time a user sends anything non-trivial. When the deciding fact is unknown,
Step 1 answers it — do not guess it here.

## Step 1 — research first, live

**No adapter code before this step is finished.** Every wire fact the adapter depends on
comes from a document fetched in this session, not from memory, not from another provider's
shape, and not from an earlier plan's sketch of it.

1. Fetch the provider's current API reference, model-listing reference, and changelog or
   versioning page. Record the fetch date.
2. Record, per assertion: endpoints and methods, auth header shape and its conventional
   environment variable, version pins (header, query parameter, or path segment), request
   fields sent, response fields read, streaming framing and terminator, error status codes
   and body shape, rate-limit and retry headers, and any documented request ceilings.
3. **Say what you could not verify.** A page that is bot-blocked, JS-only, or 404 gets an
   explicit `Unverified:` marker on everything that depended on it — never a plausible
   value. Known cases: `platform.openai.com` blocks automated fetches while
   `developers.openai.com` serves the same reference; TEI's canonical spec is the raw
   `openapi.json` on GitHub rather than its rendered docs page; several pricing pages
   render their numbers client-side and genuinely do not contain them in the served HTML.
4. When a fetched page and a summarizing tool disagree, or when a limits table is the fact
   you need, re-read the raw response. Summarization silently drops tables.
5. Where the provider ships a machine-readable service model (an OpenAPI document, a
   botocore service model already installed as a dependency), cross-check the prose against
   it. Two independent sources agreeing is what lets the snapshot claim a fact.

Write the findings into `contracts/<id>.md` from [TEMPLATE.md](TEMPLATE.md) *now*, before
the adapter — the snapshot is the specification you then implement against, and writing it
afterward turns it into a description of whatever the code happens to do.

Local engines (llama.cpp, Ollama, TEI) drift by release, not by documentation. For those,
the snapshot pins a release tag, and a documentation-only claim about a flag or an endpoint
is not sufficient evidence — see Step 6.

## Step 2 — write the adapter

`src/anyinfer/providers/<id>.py`. An adapter exposes exactly `list_models`, `health`,
`generate`, `aclose`, plus `embed` / `rerank` when it serves those operations. It
translates and nothing else: no retry, no backoff, no schema validation or repair, no
timing, no routing or catalog lookups, no redaction policy. `lint-imports` enforces the
boundary.

Start from the nearest existing adapter rather than from scratch:

| Situation | Read first |
|---|---|
| Speaks OpenAI with header or field deltas | `openai_compat.py`, `openrouter.py`, `azure_foundry.py` |
| Its own generation protocol | `anthropic.py`, `gemini.py`, `cohere.py` |
| Cloud auth and project-scoped addressing | `vertex.py`, `bedrock.py` |
| Embeddings on an OpenAI-shaped surface | `openai_compat_embeddings.py` mixin, composed by `openai.py` / `lm_studio.py` |
| Hosted, retrieval-only, no listing endpoint | `voyage.py`, `jina.py` |
| Local, retrieval-only, discovery-driven | `tei.py` |
| Both operations on an existing generation adapter | `cohere.py` |
| A supervised local server | `llama_cpp.py` |

Rules that every one of them already encodes, and that reviews check for:

- **Unknown facts stay `None`.** Never default a limit, a dimension count, or a price to a
  neighbor's value.
- **Usage comes only from what the provider reports.** Voyage and Jina report
  `total_tokens` only — copying it into `input_tokens` invents a breakdown. A provider that
  reports no usage at all gets `usage=None`.
- **Billed units are not tokens.** Search units belong in `Usage.search_units`, never
  converted into a token count.
- **Rerank `index` is positional** in every provider that has one; map it to
  `RerankWireDocument.index` rather than assuming input order survives.
- **Unsupported intents are never sent.** Translate the normalized intent to the provider's
  own vocabulary, or omit the field.
- **Every response body is size-checked** before parsing — `providers.http.check_response_size()`
  on the retrieval paths, the `max_response_bytes` check on the generation path.
- **Errors are `ProviderError` subclasses** built through `classify_status` /
  `map_transport_error` / `read_error_detail`, each carrying an actionable `hint`.
- **Credentials go through `anyinfer.credentials`** and are registered for redaction.

## Step 3 — register and describe it

1. Add the module name to `_BUILTIN_MODULES` in `src/anyinfer/providers/__init__.py`.
2. Fill in the `ProviderDescriptor`. Four invariants are enforced by
   `tests/test_registry_and_catalog.py`, and each one exists because the alternative
   silently misconfigures a user:
   - a `kind="secret"` field declares a `placeholder` naming its own `env_var`
     (`"env://X_API_KEY or a literal key"`) — a placeholder naming *another* provider's
     variable is a copy-paste bug the tests reject by name;
   - a field carrying a `default_value` is `advanced=True`, and a `required` field is never
     advanced;
   - `model_selection` is `"discover-or-manual"` or `"manual-only"`, matching whether the
     provider actually has a listing endpoint;
   - every field carries at least one of `default_value`, `placeholder`, or `help_text`.
3. Declare capability data honestly. `operations` widens beyond `{"generation"}` only for
   operations the adapter implements *and* the provider serves.
   `static_capabilities` / `static_embedding_capabilities` / `static_rerank_capabilities`
   are keyed by model id — so they are for providers with a fixed public catalog. A
   provider whose model ids are tenant-chosen (Azure deployment names) or artifact-derived
   (a local GGUF) must leave them empty: keying a limit by an unknowable id is a wrong
   answer wearing a confident face.
4. `ignored_parameters` declares whatever the provider accepts and discards, so the core
   can emit `ParameterDropped`.

## Step 4 — documentation and the generated surfaces

A new built-in provider trips several enumeration gates. All of them, in one change:

- `contracts/<id>.md` — written in Step 1; confirm it now matches the code.
- `docs/providers/<id>.md` — with the `provider:` and `icon:` frontmatter the other pages
  carry.
- `mkdocs.yml` nav, in the providers section.
- `scripts/generate_provider_index.py` — an `ADAPTER_PAGES` entry **and** an
  `ADAPTER_SUMMARIES` entry; the script raises "provider guide mapping mismatch" when only
  one is present.
- Any page that states a provider *count* (`docs/index.md`, `README.md`, `docs/why-anyinfer.md`
  and their mirrors) — grep for the old number, do not estimate the new one.

Then regenerate rather than hand-editing:

```bash
python scripts/generate_provider_index.py     # docs/providers/all.md
python workspace.py matrix                    # docs/reference/conformance-matrix.md
```

## Step 5 — tests

- `tests/test_<id>.py`: wire-mapping tests driving the adapter through
  `httpx2.MockTransport` with response bodies copied from the Step 1 research, plus one
  end-to-end client call. Include the oversized-response refusal.
- A conformance harness (`ConformanceHarness` + a fake server for the scenario strings) and
  its registration in `workspace.py` `_matrix_collect`, so the published matrix reports
  real results rather than an absence.
- `Capabilities` flags declare what the provider genuinely cannot do. **A new operation
  flag defaults `False`**; generation flags default `True`, so a flag added the other way
  around breaks every existing harness row.
- Cassettes, when credentials exist: recording **appends** to an existing cassette file, so
  delete it before re-recording, and sweep the result for credentials before committing.

## Step 6 — verify against something real

Documentation is evidence about a protocol; it is not evidence that our code speaks it.
Before claiming a provider works:

- **Hosted, with credentials:** record a cassette from real traffic and commit it, so the
  lane replays offline in CI afterward.
- **Hosted, without credentials:** say so. The contract's watchlist carries the
  not-live-verified items as an explicit burn-down list, and the provider docs page does not
  claim verification it does not have.
- **Local engines:** run the pinned build and probe it. This is not optional ceremony — it
  is where documentation has actually been wrong here. `llama-server`'s `--embeddings` turned
  out to be a *startup-only* flag, so a running generation server answers every embedding
  request with a 501; no documentation said so, and only a live probe found it.

## Step 7 — gates

```bash
python -m pytest -q
python -m mypy src/
python -m ruff check src/ tests/
lint-imports
python -m mkdocs build --strict
```

Regenerate when the relevant shape changed:

```bash
python -m pytest -q --update-manifests        # golden run-manifests, after RunManifest/UsageFacet changes
python scripts/generate_provider_index.py     # after adding or renaming a provider
python workspace.py matrix                    # after conformance case or harness changes
```

`ruff --fix` re-sorts imports and may rewrite a file you are mid-edit in; re-read before
editing again.

## What "done" means

A provider is done when a reader can check every claim it makes:

- [ ] Every wire fact in `contracts/<id>.md` cites a source and a real fetch date, and
      everything unverified is marked `Unverified:` rather than omitted.
- [ ] The adapter only translates.
- [ ] Declared capabilities and operations match what was verified — no inherited limits,
      no invented usage breakdowns, no static capabilities keyed by an unknowable id.
- [ ] Generated index, conformance matrix, and provider counts regenerated, not hand-edited.
- [ ] Live or cassette verification exists, or its absence is stated in the contract
      watchlist and the docs page.
- [ ] Every gate in Step 7 passes.

Report what was verified and what was not, in those words. A provider shipped with a named
gap is a provider someone can finish; a provider shipped with a guessed field is a bug with
a documentation page vouching for it.
