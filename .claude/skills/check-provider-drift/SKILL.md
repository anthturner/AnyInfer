---
name: check-provider-drift
description: Audit AnyInfer provider contract snapshots (contracts/*.md) against each hosted service's current public API documentation and changelogs, and report protocol drift with proposed contract/adapter/conformance-matrix updates. Use when asked to check provider drift, verify API contracts, or refresh protocol snapshots.
---

# Check Provider Drift

Read and execute
[contracts/DRIFT-CHECK.md](../../../contracts/DRIFT-CHECK.md) in full. It is the only
authoritative audit procedure. Provider ids supplied after `/check-provider-drift` limit
the scope; with no ids, use the procedure's default scope.
