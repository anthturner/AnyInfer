# AnyInfer language-neutral foundation

**Start here: [master plan](ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).** Its §5 checklist is the only
active execution list. The [shared specification](../../specification/core-generation.md)
carries the profile, schema domain, issue model, fixture format and case inventory obligations.
The [maintenance contract](../../specification/MAINTENANCE.md) defines release and reference
rules. The [original draft](SPECIFICATION_DRAFT.md) is retained as input history.

| State | Goal |
|---|---|
| **Current: Python** | Preserve the existing implementation; its observed behaviour seeds the reference corpus. |
| **Next: Python + C#** | Both pass the same frozen `core-generation` corpus through their own drivers. |
| **Future: more languages** | Each port repeats milestone 4 against the same corpus revision. |

Milestones: M0 common source root (`src/python/`, `src/csharp/`), M1 specification and corpus
with the Python driver, M2 C# proof, M3 operation accounting (separate plan), M4 further ports.

The bounded proof includes structured-output repair, native timeout and byte-limit behavior,
and outgoing as well as incoming OpenAI-compatible HTTP behavior. Coverage determines the
corpus size. Python's existing behavior and error strings are preserved; the private
assessment observation seam adds no SDK integration requirement. Unknown schema keywords
are an explicitly reported Python extension.

The [rewrite review](evidence/REWRITTEN_PLAN_REVIEW.md) records the reviewed snapshot,
findings, and their subsequent dispositions. It supplies review evidence; the master
remains the execution authority. The user authorized M0–M2 implementation on 2026-10-15;
the [execution log](EXECUTION_LOG.md) records the preserved baseline and validation evidence.
Publishing and later product-scope decisions retain the gates named in the master plan.

[evidence/](evidence/README.md) holds planning history, audits, and the six superseded contract
drafts. They inform milestone 3 and supply rationale; they are not alternate plans.
