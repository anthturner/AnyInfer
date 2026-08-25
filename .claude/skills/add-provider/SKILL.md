---
name: add-provider
description: Add a provider to AnyInfer — a preset, a dedicated adapter, or a new embedding/rerank binding on an existing one — following the repository's research-first procedure. Use when asked to add or support a provider, write an adapter, or bind a new operation onto one.
---

# Add a Provider

Read and execute [`contracts/NEW-PROVIDER.md`](../../../contracts/NEW-PROVIDER.md) in full.
It is the only authoritative procedure for adding a provider. Its Step 1 comes before any
adapter code: every wire fact must be fetched live and cited, never recalled or copied from
a neighboring provider. Finish with its "What done means" checklist, and report verified and
unverified facts separately.
