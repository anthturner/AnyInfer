---
mode: agent
description: Audit AnyInfer provider contract snapshots against current provider documentation and report protocol drift.
---

Read and execute `contracts/DRIFT-CHECK.md` in full. It is the only authoritative audit
procedure. Limit the scope to these provider ids when supplied; otherwise use the
procedure's default scope:

${input:providers:Optional space-separated provider ids, for example "anthropic openai"}
