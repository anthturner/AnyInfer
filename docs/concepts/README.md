# Concepts

Twenty ideas. Read them once and the rest of the API follows from them.

They build on each other roughly in this order, but each page stands alone.

| Page | The idea in one line |
|---|---|
| [Targets and aliases](targets.md) | Where a request goes, spelled three ways that resolve to one thing. |
| [The event stream](events.md) | A generation *is* an ordered stream of typed events; everything else is a projection of it. |
| [Routing](routing.md) | Retries, fallback chains, and health gating — deterministic and fully traceable. |
| [Structured output](structured-output.md) | A schema is a contract: strongest native mechanism, always client-side validated, optional bounded repair. |
| [Embeddings and reranking](embeddings.md) | Typed, routed inference operations too, with a fallback safety rule generation does not need. |
| [Sessions](sessions.md) | Letting a provider keep what it already knows, without changing any answer. |
| [Capabilities and provenance](capabilities.md) | Every capability value records where it came from, so you know how much to trust it. |
| [Token estimation and context budgets](budgeting.md) | How many tokens a request will spend, whether it fits, and when to refuse before dispatch. |
| [Prompt caching](caching.md) | Reuse provider-side prompt work without confusing cache hints with guarantees. |
| [Cost and spending](cost.md) | Unknown cost stays unknown, while trusted usage and prices support real ceilings. |
| [Rate limits](rate-limits.md) | Normalize provider limits and coordinate concurrency without hiding throttling. |
| [Context reduction](context-reduction.md) | Fitting more material than the window holds, and reporting exactly what was dropped. |
| [Credentials and redaction](credentials.md) | Secrets are referenced, not embedded, and can never reach a log. |
| [Telemetry and observers](telemetry.md) | Typed in-process events, payload-free by default. |
| [Run manifests](run-manifests.md) | One serializable, diffable explanation of a call's decisions. |
| [Multimodal inputs](multimodal-inputs.md) | Images, documents, and audio enter as typed payloads without fictional token estimates. |
| [Arena runs](arena.md) | Compare a fixed target set concurrently, select deterministically, and retain every candidate. |
| [The local subsystem](local.md) | Hardware detection through supervised llama-server, so local models are one target string. |
| [The model catalog](catalog.md) | What you could run locally, annotated with whether this machine can actually run it. |
| [Acquiring models](models.md) | Downloading weights with verification: chosen quantization, aggregate progress, verified bytes, and a path you can find again. |

## The one rule underneath all of them

> **Adapters only translate. The core orchestrates.**

Retry, fallback, health gating, schema validation, repair, TTFT measurement, usage
normalization, cost computation, telemetry, and redaction all live in the core — implemented
once, behaving identically no matter which provider served the request.

A provider adapter does exactly four things: list models, report health, translate a request
into its wire format and its responses back into events, and close.

That is what makes the "flat ground" promise real: when you change `target=` from a hosted
model to a local one, the behavior you depend on does not change with it.
