# Specification and corpus maintenance

This document governs immutable specification releases, their reference evidence, and the
review required to change or rebaseline them.

## Release identity and retrieval

A release is the immutable unit consumed by implementations and their independent drivers. Its
manifest lists the normative `specification/README.md`, `core-generation.md`, and
`MAINTENANCE.md`, every schema, the case inventory, all exact fixture inputs, and the reference
manifest and environment artifact. It records SHA-256 hashes of raw bytes, with forward-slash
paths in code-point order. Generated reports and the release file itself are excluded. The
release case inventory is the complete unique ID set derived from the inventory asset and names
each case's kind, path (or `null` for a driver assertion), family, and extension name (or `null`).
The embedded case set must equal the inventory, with no pending expectations. Drivers and
verification tools reject missing, changed, or unexpected release inputs; later fixtures are never
globbed into an earlier release. Conformance reports cite the SHA-256 of the actual release-file
bytes.

A sealed release is retrieved by an annotated Git tag targeting the commit that contains its
manifest and every hashed asset. An external support declaration records both the tag and its
resolved commit, avoiding a self-reference from the release file. Each driver accepts `--root`
pointing to an extracted matching corpus tree. Prior releases remain retrievable after newer
ones are created. Any changed release asset requires a new release ID.

### Reference manifest

The reference manifest has this shape; values shown as examples are replaced by the actual
committed run evidence:

```json
{
  "implementation": "anyinfer-python",
  "reference_run_revision": "<40 hex>",
  "source_tree": { "clean": true },
  "driver": { "path": "tests/testing/portable/", "git_revision": "<same committed revision>" },
  "interpreter": "CPython 3.x.y",
  "environment": { "path": "specification/reference/python-<rev7>.environment.json", "sha256": "<sha256>" },
  "packages": { "httpx2": "...", "jsonschema": "...", "jsonschema-specifications": "...", "referencing": "...", "attrs": "...", "rpds-py": "..." },
  "validator": { "selected": "...", "defaults": "...", "resource_identities": ["..."] },
  "warning_policy": "error",
  "produced_at": "<ISO 8601>"
}
```

`reference_run_revision` identifies the committed source revision that executed the reference
implementation and driver. The manifest records the actual interpreter and dependency versions,
selected validator and defaults, resource identities, warning policy, source-tree cleanliness,
and the environment artifact path and hash. The environment artifact contains the complete
dependency lock and selected resource identities; these evidence pins do not alter production
dependency ranges. Required fields cannot be omitted or replaced with pending values in a sealed
release.

### Release manifest

The release file has this shape:

```json
{
  "release": "core-generation-v0",
  "profile": "core-generation",
  "profile_revision": "v0",
  "created_at": "<ISO 8601>",
  "reference_manifest": "specification/reference/python-<rev7>.json",
  "files": { "specification/core-generation.md": "<sha256 hex>" },
  "case_inventory": [
    { "id": "repair/zero-budget", "path": "specification/fixtures/core-generation/repair/zero-budget.json", "family": "repair", "extension": null }
  ]
}
```

`files` includes the normative README, profile and maintenance documents, every schema, the
inventory asset, exact corpus fixtures, and the reference manifest and environment artifact. It
uses forward-slash paths in code-point order and SHA-256 of each file's raw bytes. Generated
reports and the release file itself are excluded. A repository rule keeps files under
`specification/` at LF endings so hashes are stable across platforms. `case_inventory` contains
every unique case from the inventory asset, including kind, path (or `null` for a driver
assertion), family, and extension (or `null`). Its set must exactly match the inventory. No
pending expectations are permitted in a sealed release. Verification rejects missing, changed,
or unexpected inputs and never includes later fixtures by globbing.

## Reference evidence and bootstrap

The reference manifest identifies the committed revision that executed the Python reference
source and driver, source-tree cleanliness, driver revision, interpreter, environment artifact and
its hash, dependency versions, validator selection/defaults/resource identities, warning policy,
and production timestamp. The environment artifact records the complete dependency lock and
actual selected resource identities; production dependency ranges are unchanged. Development runs
may use pending placeholders. A reference run requires committed implementation, driver,
specification, and fixture inputs; it refuses missing, mismatched, or dirty required bindings and
verifies import provenance against the committed input tree.

The reference execution revision A may precede commit B that adds generated release assets.
Reproduction checks out A and may obtain frozen assets from B through `--root`. This baseline
preflight applies only to oracle reproduction or reference writing. Later Python and native runs
verify frozen release assets and report their own source and environment binding; they need not
match A.

Before a release exists, development and clean reference runs produce explicitly unreleased
observations against the hashed case inventory. These private diagnostics record cases, counts,
input identity, and source/environment binding; they are not qualified reports and cannot qualify
a port or release comparison. Development observations fill pending expectations. After
reconciled inputs are committed at A, a clean reference run writes the reference manifest and
environment artifact. The release-generation step creates a candidate manifest, verifies hashes
and inventory, then runs the full Python corpus again to produce the first qualified report with a
real release hash. Only a complete report with zero failures and errors and an independent cold
review permit sealing. Reports are not release inputs, so there is no report/hash dependency cycle.
Additional tooling commits are reported honestly: A remains the reference-run revision and B is
the later commit containing sealed release assets, not necessarily A's immediate child.

While a native driver or HTTP adapter is incomplete, selected-family runs produce development
observations only. A partial core/driver proof is not a qualified report or profile claim; the full
inventory must execute after HTTP support is complete.

## Compatibility and rebaseline review

Every proposed change is reviewed against the last sealed release and its complete corpus. A
compatible change creates a new release without changing any old release asset. A breaking
change increments the profile revision and requires explicit migration and rebaseline review.
Reference expectations are never regenerated silently to make a changed implementation pass.

| Change trigger | Required checks and review | Disposition |
|---|---|---|
| Python reference implementation behavior changes | Run the frozen release against the changed reference and review every changed observation against the normative text and case inventory. Distinguish an implementation regression from an intended profile change. Run the full reference corpus and the native driver gates for every implementation claiming the candidate release. | If behavior still matches the contract, fix the implementation without changing expectations. If the intended contract changes compatibly, add cases/release assets under a new release ID. If it changes incompatibly, increment the profile revision and review migration and rebaseline. Never silently move the oracle. |
| Provider protocol or adapter behavior changes | Review the applicable provider contract snapshot and affected transport fixtures; run the complete transport and core-generation corpus for the candidate release, then run native driver gates for each claiming implementation. Review any changed observable result against the profile contract. | A provider change that leaves profile observations unchanged does not change the oracle. If an observable profile behavior is intentionally changed, follow the compatible or breaking profile-change path above and create new immutable release assets. |
| Normative specification, schema, inventory, or fixture changes | Review requirement-to-case coverage and all affected expectations; verify the full inventory and release hashes; run the complete Python reference corpus and native driver gates. Require independent corpus review before sealing. | Create a new release ID. Preserve every prior release asset. Use a profile revision change when the behavior is breaking. |
| Reference environment, dependency, validator, or resource identity changes | Re-run the committed reference source and driver; record the complete new environment lock and selected identities; compare the full corpus with the prior sealed release and review all differences. Run native driver gates against the candidate release. | If outputs are unchanged, record a new reference binding only in a new release. If outputs differ, classify the difference as implementation/environment drift or an intentional profile change; never accept it as a new baseline without review and the compatible/breaking path. |

Reference rebaselining records a new reference source/environment binding and release ID only
after the applicable checks above pass. Candidate release reports must cover the full inventory;
each report must be complete and have zero `fail` and `error` verdicts before that implementation
can claim conformance to the candidate. Every implementation declares the releases it supports
and verifies each by immutable retrieval. The specification does not set support windows or
designate a publishing authority. Decisions about publishing, ownership, and support windows
must precede independently supported public releases.
