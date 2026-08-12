# Vector store add-on (follow-on plan)

> **Status:** proposed; not started. The `embed()`/`rerank()` public surfaces this package
> is built entirely on landed 2026-08-11; the remaining embedding/reranking work is
> consolidated in [EMBEDDING_RERANKING_CONTINUATION.md](EMBEDDING_RERANKING_CONTINUATION.md) and
> none of it blocks this package's core design, though batching (its Track A) will matter
> for bulk indexing performance.
> **Plan date:** 2026-08-11.
> **Authority:** living implementation plan, not an architecture decision. It proposes a new
> *package*, not a change to `anyinfer` core, so it does not amend `DESIGN.md` — it only cites
> the core boundary that DESIGN.md already draws (inference engine, not a database) and
> commits to staying on the inference side of it.

## 1. Why this is a separate package, not a client of the core roadmap

`EMBEDDING_RERANKING_CONTINUATION.md` §9 (the scope boundary carried forward from the
original support plan) explicitly excludes vector databases, ANN indexes, persistence, and
corpus lifecycle from AnyInfer core, and its decisions record (§10, D-3) keeps the
resolution to stay stateless-inference-only. That boundary is deliberate, not an oversight to patch
later: the moment AnyInfer core takes a dependency on a storage engine or an indexing
algorithm, "one adapter per provider" stops being the whole story, because now there is a
second axis (which store, which index type, which persistence format) that behaves nothing
like a provider descriptor.

The owner has asked for a middle path: ship something batteries-included-*adjacent* — an
optional, separately-versioned, separately-installed add-on package, listed alongside
AnyInfer's other features but never imported by `anyinfer` core and never a dependency of it.
It exists so a caller who just wants "embed some text and search it later" doesn't have to
learn a third-party vector database for a few thousand rows, while a caller who needs real
scale is pointed at one, not sold a toy that will fall over under their workload.

**The one-sentence boundary this package commits to:** *small-scale, single-process,
embedded persistence for personal/prototype-sized corpora — never a clustered, replicated,
or "production vector database" story.* Anything shaped like that is explicitly a non-goal
here, permanently, not just for v1.

## 2. What "small scale" means, concretely

This package must never market itself as horizontally scalable, and the docs must say so
in the first paragraph a reader sees. Concrete framing:

- **Target corpus size:** documents numbering in the thousands to low hundreds of thousands
  of vectors, at typical embedding dimensions (384–3072). Not millions; not billions.
- **Target deployment shape:** one process, one machine, one writer. No replication, no
  sharding, no distributed consensus, no multi-writer coordination.
- **Target workload:** prototyping, personal tools, small internal apps, notebooks, CLI
  utilities, single-tenant desktop/local-first applications — the same audience the
  `llama-cpp` local subsystem already serves.
- **Explicit escape hatch:** when a caller outgrows this (needs HA, needs millions of
  vectors, needs multi-region reads, needs a managed control plane), the documented answer
  is "point a real vector database (pgvector, Qdrant, Weaviate, Pinecone, etc.) at
  `anyinfer.embed()`/`anyinfer.rerank()`" — AnyInfer's embedding/reranking engines are
  exactly as usable from that path as from this package, since both consume the same public
  `EmbeddingResult`/`RerankResult` types. This package is never positioned as a stepping
  stone toward a hosted/scaled version of itself; there isn't going to be one.

## 3. Scope

### Included
- An embedded, single-file (or single-directory) persistent vector store: insert, update,
  delete, and brute-force or lightweight-approximate similarity search over stored vectors.
- Storing caller-supplied ids, vectors, and small metadata payloads per entry.
- Persisting the `EmbeddingSpace` identity (from the core plan) alongside stored vectors, and
  refusing a query whose embedding space does not match the store's — the same cross-space
  safety rule the core plan requires for routing, applied to persistence.
- A minimal query API: top-k similarity search, optional metadata filter, optional
  integration with `anyinfer.rerank()` as a second-stage reranking pass over the top-k
  candidates.
- Basic corpus lifecycle primitives scoped to *this store*: add, remove, rebuild-index,
  compact/vacuum, export/import a single store file.
- A stated, tested ceiling: the store documents (and, where practical, warns at runtime
  about) the point at which its brute-force or lightweight index degrades — so a caller
  gets a signal before performance quietly falls off a cliff, not silence.

### Explicitly excluded, permanently (not "for now")
- Clustering, replication, sharding, or any multi-node deployment story.
- A network service, control plane, or admin UI of its own — this is a library, matching the
  core's "no daemon" non-goal.
- Multi-writer concurrency guarantees beyond simple file-locking safety.
- Being positioned, marketed, or documented as competing with or replacing a real vector
  database at scale.
- Automatic corpus collection or synchronization — the app still owns collecting and
  approving what gets embedded and stored, exactly as `anyinfer.context` never collects.
- Cross-store federation or query fan-out.

## 4. Relationship to `anyinfer.context`

`anyinfer.context` remains a lexical, offline, no-I/O reduction subsystem per its ADR-011
boundary. This package is not a replacement for it and is not imported by it. If a caller
wants semantic ranking inside `context.select()`, the core plan's §9 (`ER.6.9`) already
covers supplying a semantic ranker as a protocol implementation — this package may supply
one such implementation later, as an *optional* bridge module, but `context`'s default stays
lexical and this store is never a hidden dependency of core.

## 5. Packaging and naming

- Ships as its own installable distribution (working name `anyinfer-store`; final name to be
  confirmed), depending on `anyinfer` (for the public embedding/rerank types and client) but
  never the reverse.
- No new mandatory dependency on `anyinfer` core. `anyinfer` never imports this package,
  never documents it as required, and its own test/lint/type gates are unaffected by whether
  it exists.
- Listed in AnyInfer's documentation as an available add-on ("batteries included, but not
  bolted on") alongside other optional pieces (`[serve]`, `[mcp]`, etc.), with the small-scale
  framing from §2 stated up front, not buried in a caveats section.

## 6. Suggested implementation order (once the core plan lands)

1. Confirm the core plan's `EmbeddingResult`, `EmbeddingSpace`, and `RerankResult` shapes are
   stable (public, documented, tested) — this package is built entirely on them.
2. Design the on-disk format: a single embedded file format (e.g. SQLite with a vector
   column, or a simple flat file + index), chosen for zero-external-service operation and
   easy backup/export.
3. Implement insert/update/delete/query against that format with brute-force search first;
   add an optional lightweight approximate index only if benchmark evidence shows it is
   needed within the stated scale ceiling.
4. Implement `EmbeddingSpace` compatibility checks at write and query time.
5. Add an optional second-stage rerank pass wired to `anyinfer.rerank()`.
6. Add CLI and/or a minimal example app demonstrating embed → store → query → rerank as one
   flow, entirely offline against fake providers in examples.
7. Write conformance tests: ordering, persistence across process restarts, embedding-space
   rejection, corpus size ceiling behavior, export/import round trip.
8. Document the scale boundary prominently, with a worked example of "when to graduate to a
   real vector database" and how the same `embed()`/`rerank()` calls carry over unchanged.

## 7. Open questions for the owner, deferred to when this plan is picked up

- Final package name and repository location (same monorepo vs. separate repo).
- Preferred on-disk format (SQLite+vector-column vs. a bespoke flat format).
- Whether an approximate index (e.g. HNSW-lite) is worth the added complexity within the
  stated scale ceiling, or whether brute-force cosine search is simply always fast enough at
  the sizes this package targets.
- Release/versioning cadence relative to `anyinfer` core.
