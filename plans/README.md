# Plan directory

## Current branch-preparation status

As of 2026-10-24, the C# SDK work is paused for branch handoff. The committed plan-only
baseline before this maintenance is B `552abd2dde65217ca8b2fb35277270ba567167d6`, tree
`b736e72a820fff400cb464eebbda63a85fe3f815`. The last qualified executable source is A
`952b678d2dc020075c09bc6f8d11e2879fc992bd`, tree
`f5ddbe6d8f12bb9c04ee2b84bb393800908593f8`.

The qualified A checkpoint recorded 25 full workspace steps: 4,536 Python passes and 10
documented platform skips, 1,135 native unit tests, and 93 conformance tests. Its clean
qualification added 12 steps and 67 focused controls; the paired profiles (42/29/32/43/10)
and Frozen 102 profile passed. Native defaults are 7 descriptors, 10 bindings, and 119
pending source memberships; Python remains 106 descriptors/129 bindings and the generated
table has 86 rows. This is not a hosted-provider, release, or full-SDK qualification.

Branch preparation preserves the implementation as-is. Inactive repository/epic scratch,
caches, and build outputs have been removed after evidence preservation; the root
`.pytest_cache` remains because Windows denies access. All 22 ancillary AnyInfer worktree
entries were individually approved and removed through Traycer; Git now lists only the
current checkout. The user subsequently authorized removal of the untracked, unused
`uv.lock` and empty pytest cache under `v/`; both are removed. The final repository gate
passed all 25 steps again (4,536 Python passes, 10 documented skips, 1,135 native unit
passes, and 93 conformance passes). Generated artifacts from that run were preserved as
reports and cleaned again. The branch is ready for remote review. Further provider and
SDK implementation stays paused until separately resumed after handoff; the next SDK
direction is the parent plan's SDK.8a researched-provider work.

## Plan index

- [Python-aligned AnyInfer C# SDK](ANYINFER_CSHARP_SDK.md) is the active parent plan and is
  paused for branch preparation. It has 15 genuine unchecked milestone boxes: SDK.6c,
  SDK.8a–c, SDK.9a–b, SDK.10a–c, SDK.11a–c, and SDK.12a–c.
- [C# SDK API parity inventory](CSHARP_SDK_API_PARITY.md) is the open inventory used by the
  parent plan. Its 235 root API rows remain unchecked pending their assigned semantics and
  the SDK.11c reconciliation; rows are not completion claims.
- [C# SDK retrieval operations](ANYINFER_CSHARP_SDK_RETRIEVAL.md) retains one genuine
  outstanding item, 6c.0 provider research preflight. It is subordinate to the parent
  plan's still-open SDK.6c scope.
- [Language-neutral foundation](language-neutral-foundation/ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md)
  has five genuine future boxes: M3.1 operation accounting and M4.1–M4.G additional native
  ports. Its M0–M2 execution is complete, and its completed C# proof leaves are historical.
- The other completed `ANYINFER_CSHARP_*.md` execution leaves record their named checkpoint
  evidence. Their resume wording, test totals, and descriptor/binding counts are historical
  facts for those checkpoints; they do not replace this parent plan's current status.
- [Codebase status](CODEBASE_STATUS.md) and [Debloat hitlist](DEBLOAT.md) are dated
  2026-08-25 snapshots with unfinished items. They are not current system-status reports or
  branch-preparation checklists.

No plan checkbox is changed by this index. Use the parent plan for C# SDK work after the
branch-preparation pause; do not infer completion from historical execution leaves.
