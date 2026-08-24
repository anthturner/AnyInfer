---
mode: agent
description: Add a provider to AnyInfer — preset, dedicated adapter, or a new operation binding — following the repository's research-first procedure.
---

Read and execute `contracts/NEW-PROVIDER.md` in full. It is the only authoritative procedure
for adding a provider. Its Step 1 comes before any adapter code: every wire fact must be
fetched live and cited, never recalled or copied from a neighboring provider. Finish with
its "What done means" checklist, and report verified and unverified facts separately. Add
the provider named here; if none is supplied, ask which one:

${input:provider:The provider to add, for example "mistral" or "together"}
