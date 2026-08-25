# AnyInfer — Claude Code bootstrap

Read and follow [AGENTS.md](AGENTS.md) in full. It is the only authoritative repository
instruction set, including the core SDK, demo, CLI, sidecar, configuration, testing, and
documentation boundaries. This file adds no Claude-specific engineering policy.

Two skills are entry points only; each canonical procedure lives in one tool-neutral file:
`/add-provider` → [contracts/NEW-PROVIDER.md](contracts/NEW-PROVIDER.md),
`/check-provider-drift` → [contracts/DRIFT-CHECK.md](contracts/DRIFT-CHECK.md).
