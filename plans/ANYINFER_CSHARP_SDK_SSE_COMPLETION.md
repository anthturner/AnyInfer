# Native chat SSE completion alignment

Resume from the first unchecked box. This is a bounded SDK.8a prerequisite under
`ANYINFER_CSHARP_SDK.md`, not a provider registration or completion of SDK.8a.
Root owns decisions, Git, generated metadata, shared plans and serialized execution.

## Settled scope

- Baseline is `784bb127297bb2a683a5517e292665a51058437f`, tree
  `e3905ccdc8a32dddb6fd0fb7f92b9aa6d59b6b0e`. The qualified Hyperbolic executable
  remains `b4456054d0d3f6d79113d04714b5c8baf99f2518` / tree
  `9fcf09fe47641d58d683466beadbabc29155055b`.
- The parent authorizes Python behavior as the SDK parity authority. Python's
  `providers/sse.py:iter_sse` consumes a final record at clean EOF and treats
  `[DONE]` as an early terminator. The generic adapter then finalizes with the
  reported finish reason, or `stop` when absent. Content-only, empty and
  comment-only clean EOF therefore succeed. Match that completion behavior.
- This explicitly supersedes the native proof's DONE-only implementation choice
  in `plans/language-neutral-foundation/ANYINFER_CSHARP_PROOF.md` M2.5a. Do not
  rewrite that historical acceptance record. It was not a shared/released
  mandatory-DONE invariant. The released `done-sentinel` fixture requires early
  termination and ignoring later records, which must remain unchanged.
- At clean body EOF, flush any pending final line and data record through the
  same line/JSON/event translation used for blank-delimited records. Then emit
  exactly one `AdapterFinal`, retaining the existing finish/usage/logprobs state.
  An open stream that has produced `finish_reason` is not EOF: continue reading
  trailing usage and detect later malformed data until DONE or actual EOF.
- Keep exact existing DONE early termination, CRLF and split UTF-8 behavior,
  strict native UTF-8 decoding, multiline data fields, first-choice selection,
  finish-reason accumulation, tools/logprobs, raw physical-chunk byte limits,
  caller cancellation and cleanup/primary-error precedence. This is completion
  alignment, not a claim that every parser edge already matches Python.
- Invalid/incomplete JSON or invalid UTF-8 in a trailing data record still fails
  with typed stream protocol error and no final. A thrown body-read I/O failure
  remains transport failure. A normal zero-byte read is EOF; no claim is made
  that every real network truncation must throw instead of ending cleanly.
- Apply the shared reader behavior to its existing native entry paths. Add no
  provider-specific branch, new option, retry, dependency or public domain/API.
  Do not change Python production semantics or any specification/release/frozen
  asset. Preserve all 102 released observations and existing paired profiles.
- This repairs a native implementation discrepancy against the existing Python
  reference, rather than adopting a newly verified upstream change. No provider
  declaration, revised shared specification, publisher/validator/CI policy or
  generated provider fact is needed. Update the native behavior note in the
  shared snapshot without changing upstream verification dates or claims.
- No Nscale or other provider is registered here. Exact upstream framing and
  streamed-usage claims remain unverified where the research says so. Native
  counts stay 6 descriptors / 9 bindings / 120 pending memberships; Python
  106 / 129 and the generated 86 rows remain fixed.

## Ownership and checks

Workers are not alone. Preserve peer edits, never change Git state, and use only
the named files. No worker runs builds, full suites, package operations or network
requests. Use `.venv/Scripts/python.exe` for permitted Python checks. Root grants
one minimal checklist-write lease at a time after validating the corresponding
gate; the owner re-reads this whole plan before ticking its box. Record deviations
as `> NOTE:` beside the box. Never stage or alter root `uv.lock` or `v/`.

- [x] **SSE.0 — Scope and cold critique (root).** Record the authority and explicit
  historical-rule replacement above. Obtain independent artifact critique against
  the actual Python/native readers, tests, shared transport fixture and parent.
  **Gate:** no unresolved P1/P2 affecting this bounded implementation.
  > NOTE: Cold critique found the completion/control scope sound. Root checked
  > its sole P2 against the inventory's actual source list: the authorized
  > `contracts/openai-compat.md` edit is an export input. SSE.4 now explicitly
  > allows only its source digest and resulting inventory pins to change, or
  > requires a no-op if outputs are identical. No provider facts may change.
- [x] **SSE.1 — Shared reader (implementation worker).** Own only
  `src/csharp/AnyInfer/Providers/OpenAIChatAdapter.cs`. Implement EOF flushing and
  finalization without duplicating the record-to-events translation or changing
  unrelated buffered/status/redirect/retrieval logic. **Gate:** independent source
  review plus the root's SSE.4 focused native command passes.
  > NOTE: Independent reader/docs/provenance review was clean; root focused 47 Python /
  > 131 native plus later completion-class 13 passed. Full and clean acceptance remain pending.
- [x] **SSE.2 — Independent causal controls (test worker).** Own
  `src/csharp/AnyInfer.Tests/OpenAIChatTests.cs`, new
  `src/csharp/AnyInfer.Tests/OpenAISseCompletionTests.cs`, and
  `tests/test_openai_compat.py`. Replace only the obsolete EOF-failure portion of
  the existing combined test; keep malformed-after-finish and multibyte-byte-cap
  failures. Cover complete final-record EOF with and without trailing line/blank
  delimiters, CRLF and split UTF-8, trailing usage, missing finish/usage, empty and
  comment-only streams, tool/logprob preservation, sentinel-only/early stop and
  data after DONE, malformed trailing JSON/UTF-8 and actual body-read I/O failure.
  Prove an open finish-bearing stream does not finalize early. Add at least one
  ordinary public default-client streaming path through the real configured
  factory that reaches a successful result on clean EOF. Python controls must
  exercise the real generic adapter, not a reimplementation. Bound new waits by
  caller-linked 15-second deadlines; no sleeps or hosted traffic. **Gate:** cold
  controls review and root's SSE.4 focused Python/native batch passes.
  > NOTE: First 47 Python / 131 native batch used the prior test body; corrected
  > usage-after-finish plus blank/tail-DONE completion class passed 13, independent
  > review is clean, and the full-first gate passed. Clean acceptance remains pending.
- [x] **SSE.3 — Behavior documentation (docs worker).** Own only
  `contracts/openai-compat.md` and `docs/reference/csharp-sdk.md`. Explain DONE
  early termination versus clean EOF finalization, default stop and absent usage,
  and continued malformed/read-error failures. Keep provider wire facts and
  verification dates intact; state the implementation behavior as such. No plan
  links in docs or invented upstream guarantee. **Gate:** independent consistency
  review and root's strict docs phases in SSE.4 pass.
  > NOTE: Implementation-behavior notes passed independent review and the full-first
  > strict docs gate. Upstream verification dates and claims are unchanged; clean
  > executable acceptance remains pending.
- [x] **SSE.4 — Metadata, review and held-source gate (root).** After sources are
  stable, regenerate `maintenance/provider-parity/python-builtins.json` with
  `scripts/export_python_provider_parity.py`, then
  `src/csharp/AnyInfer/Providers/CompatPresetTable.g.cs` with
  `scripts/generate_csharp_compat_presets.py`. The authorized SSE.3 edit to
  `contracts/openai-compat.md` is an inventory source input: require every
  provider fact and non-source field to remain structurally identical, with only
  that existing source digest changed. If regeneration changes output bytes,
  update only the expected inventory digest in
  `src/csharp/AnyInfer.Tests/CompatPresetDataTests.cs` and verify the table changes
  only its inventory pin. If output is identical, leave pins unchanged. Independently
  verify this provenance-only delta and fixed counts. Run the focused commands below, inspect actual JUnit/TRX and cold
  source/controls/docs review. Then run one coherent full
  `.venv/Scripts/python.exe workspace.py check`. Retain the actual full output,
  primary Python JUnit, five paired reports and Frozen summary. Record failures
  without relabeling them. **Gate:** every applicable phase passes; before/after
  tracked/nonignored source maps, Git identity/status and root user pins agree.
  > NOTE: Canonical regeneration changed only the existing shared contract source
  > digest; all provider structures and the 49-path source set are unchanged.
  > Inventory is `5e2a30f3c9fbb39b35cc2c02c46d9aa1e506fbb62b1c2461ba70c532fd045e55`;
  > generated table changes only its inventory pin. Independent provenance review is clean.
  > First focused evidence at `.tmp-tests/sse-completion-focused-first/` passes
  > 47 Python / 131 native / zero skips, with 1,275 protected inputs and state/pins
  > unchanged. A subsequent test-only coverage correction passes 13 completion cases
  > at `.tmp-tests/sse-completion-coverage-closure/native.trx`; the first batch used
  > the prior test body. Full and clean acceptance remain pending.
  > NOTE: Full-first `.tmp-tests/sse-completion-full-first/` passes all 25 workspace
  > steps: 4,536 Python passes / 10 documented platform skips / zero failures/errors,
  > 1,130 native unit and 93 conformance cases, five paired profiles 42/29/32/43/10
  > with zero mismatches, strict docs/package/examples and Frozen DEVELOPMENT102/0/0/0.
  > All 1,275 maps, nine source bodies, actual Git roots/states, helpers and user pins
  > are unchanged. Independent actual evidence review is bounded clean. Facts SHA
  > `2f75fcbdae48d494e2d3d50ac7f2d5e8aaed2d5c5ae79e69292922a07b54d871`;
  > command log `1b54163317d970e6f212657a637c975b7e9a0af3caa9c9faf05cefa7ff7ac0ae`.
  > Held source is intentionally dirty at baseline 784bb127; clean acceptance is SSE.5.
- [x] **SSE.5 — Clean executable acceptance (root).** Commit only the explicit
  functional paths after SSE.4. Create a fresh clean checkout at that exact commit
  and tree. Use root's external Python with controlled `PYTHONPATH` selecting only
  the checkout's `src/python`, and an explicit selected-source import assertion.
  Execute the selected `workspace.py check --only csharp` (the registered C# gate)
  plus a no-build/no-restore focused completion TRX. Bind the nine functional paths
  below via root/selected LF-normalized bodies; compare every selected tracked
  input, selected clean identity, root user pins and proof helper hashes before/
  after. Require all 12 C# steps, existing paired reports/Frozen and explicit EOF
  controls to pass with independent evidence review. Do not rerun unrelated full
  Python gates solely for a plan record. **Gate:** clean source, no input drift,
  all required results present and passing; historical evidence unchanged.
  > NOTE: The exact nine functional paths are committed at
  > `d388e6832c0436d9aae3f884ca753cff3837bf0e`, tree
  > `faf3154e8091a617902dfc1c97d4482886d4d881`. Root plans and user inputs were not
  > staged. Fresh checkout is
  > `C:/Users/antho/.traycer/worktrees/anthturner__anyinfer/feature-sse-completion-clean-d388e68`.
  > Clean execution/acceptance is pending; this is not a qualification claim.
  > NOTE: Clean-first remains `invalid-or-incomplete`: all 12 registered C# steps
  > and 134 focused native cases passed, and every root/selected state/map/pin stayed
  > unchanged. The extra Frozen command exited 2 because the root-owned report path
  > was outside the selected executable's permitted `.tmp-tests` output root.
  > No product source or test change is required. Preserve original facts/log/TRX.
  > The old full/clean launcher stays byte-identical; separate ignored v2 chooses
  > the selected checkout's `.tmp-tests/<label>/frozen-development.json` for clean
  > mode and records its actual path/hash. Rerun coherent clean qualification from
  > unchanged source A with a new label; do not relabel the first attempt.
  > NOTE: Clean-second is independently accepted at the same executable commit/tree.
  > `.tmp-tests/sse-completion-clean-second/` passes the selected-source import,
  > all 12 C# steps (1,130 unit / 93 conformance), package/examples, and 134 focused
  > cases including all 13 EOF completion cases. Five paired profiles pass with
  > 42/29/32/43/10 matches and zero mismatches; selected Frozen remains
  > DEVELOPMENT/UNRELEASED 102/0/0/0. Root's 1,275-input map and selected checkout's
  > 1,272-input map are individually unchanged; all nine normalized functional
  > bodies agree across checkouts. Selected identity/status, root user pins and
  > helper hashes are unchanged. Facts SHA is
  > `170b5fb9d37fc45d27c239e4dfc5fd2e8d53c65b6481e792c54a8bbf497d8545`;
  > command log `eff1c67ef09362fda40a3c247a3f2209b47d4ecad84e8c2e555b3c4745831e82`.
  > The first invalid attempt and original launcher remain intact. This later
  > acceptance supersedes the intermediate pending notes above.
- [x] **SSE.6 — Reconciliation (root).** Re-read this leaf and the entire parent;
  record the accepted executable commit/tree, actual gates and remaining limits
  in both and active SDK artifacts. Obtain cold consistency critique, tick this
  box and commit only the two plans separately. **Gate:** executable and plan
  identities remain distinct; SDK.8a and other unfinished milestones remain open.
  > NOTE: Cold four-record critique confirmed identities, actual gates, fixed counts
  > and remaining limits. Its sole closure note is addressed by marking both active
  > artifacts complete with these plan records. Commit only the two plans; preserve
  > executable A above, all failed evidence and root user files separately.

## Exact commands and functional paths

Root's focused Python command uses selected Python:
`-m pytest tests/test_sse.py tests/test_openai_compat.py -p no:cacheprovider`,
with an explicit absolute JUnit output and fresh external basetemp. Quote POSIX
paths as pytest option tokens; never put raw Windows backslashes in addopts.

Root's focused native command, cwd `src/csharp`:
`dotnet test AnyInfer.Tests/AnyInfer.Tests.csproj --no-restore -m:1 --filter "FullyQualifiedName~OpenAIChatTests|FullyQualifiedName~OpenAISseCompletionTests|FullyQualifiedName~CompatPresetDataTests|FullyQualifiedName~ConfiguredTransportOwnershipTests|FullyQualifiedName~Redirect"`,
with TRX output in an ignored retained attempt directory. Join TRX result test IDs
to definitions; require actual `OpenAIChatTests` and `OpenAISseCompletionTests` cases.

The nine functional paths are the adapter; the three SSE.2 test paths; the two
SSE.3 docs paths; the inventory; generated table; and `CompatPresetDataTests.cs`.
Plans, artifacts and ignored proof tools are separate. No source map may quietly
exclude another tracked input; selected checkout absence of root-only untracked
`uv.lock` and `v/cache/nodeids` is handled by hashing those root files independently,
not by pretending they are selected tracked inputs.

## Resume

SSE.0–6 are complete with independent consistency critique. Executable
`d388e6832c0436d9aae3f884ca753cff3837bf0e`, tree
`faf3154e8091a617902dfc1c97d4482886d4d881`, is independently qualified by the full
held-source and second clean gates above. Preserve the first invalid clean attempt.
Resume SDK.8a researched provider registration after the separate two-plan record.
No Nscale or other additional provider is selected. Native counts stay
6/9/120, Python 106/129 and the generated table 86 rows. SDK.8a, SDK.6c, SDK.8b–c,
SDK.9–12 and all 235 API rows remain open. Hosted behavior and the separate reasoning-
history issue remain unverified or unresolved; existing evidence and user files are intact.
