# Shared C# observation mechanics

Resume from the first unchecked box. This is the mechanical helper subtask of POL.5 in
`ANYINFER_CSHARP_SDK_POLICIES.md`; it grants no new request-policy case semantics.

Owner: 2ff. Read the whole parent policy plan and this checklist before editing. You are
not alone in the workspace; preserve all other changes and re-read each file immediately
before a minimal edit. Never change Git state or run native/shared builds. Tick only H.1-H.3
after their named targeted gates pass; root owns H.4 and the parent checklist.

## Settled boundaries

- Own only `scripts/_csharp_observation.py`, the mechanical extraction in
  `scripts/check_csharp_accounting.py`, retained `tests/test_csharp_accounting.py`, new
  `tests/test_csharp_observation.py`, and H.1-H.3 below.
- Share strict raw-byte JSON loading, case identity indexing, observer envelope/provenance
  validation, fresh run/copy mechanics and stamped process orchestration. Use immutable
  runner configuration and profile-local observation validation callbacks.
- Keep accounting's Comparison/report, error mappings, decimal causes, ordered-map rules,
  `_value_difference`, `_errors_match`, native-boundary qualification and comparator
  literally profile-local. No generalized value normalizer or mutable profile registry.
- Preserve all accounting CLI options, default paths, report fields, 42 shared/two native
  evidence rules and existing test assertions. Keep the `_run` monkeypatch seam by passing
  its wrapper/callback into shared orchestration. Preserve import-by-spec test loading and
  direct script execution; any loader adjustment must be mechanical, with assertions intact.
- Strict JSON reads actual bytes: reject non-UTF8, BOM, duplicate object keys and nonstandard
  NaN/Infinity; no newline/BOM normalization. Hash actual input bytes, including CRLF.
- Validate literal profile/runtime, lowercase full revision/digest, exact boolean dirty
  flag and complete unique id/kind coverage. Profile-local callbacks retain status/body
  rules. Default execution checks both headers against the source identity used to stamp
  the build; compare mode copies evidence byte-for-byte into a fresh run directory.
- Build commands retain positional csproj + `--no-restore`, SourceRevisionId and the
  profile-specific dirty property. Python uses `--observe INPUT OUTPUT`; native uses
  `dotnet run --no-build --no-restore --project PROJECT -- INPUT OUTPUT`.
- Do not create request-policy checker, corpus, observers, workspace wiring or source
  calculations in this subtask. Escalate a contract change with evidence before editing it.

## Checklist

- [x] **H.1** Extract mechanics into the private helper and adapt accounting through narrow
  wrappers while preserving its comparator/report and test seams. Gate:
  `.venv/Scripts/python.exe -m pytest tests/test_csharp_accounting.py -q`.
- [x] **H.2** Add helper regression controls for strict raw JSON, raw CRLF digest, duplicate/
  missing/extra identity, metadata shape/mismatch, fresh compare copying and stamped command
  shape. Keep accounting assertions intact. Gate:
  `.venv/Scripts/python.exe -m pytest tests/test_csharp_accounting.py tests/test_csharp_observation.py -q`.
- [x] **H.3** Run targeted Ruff check/format/check on the four owned Python files, re-run
  H.2 after any correction, and send a coherent SAVED/HELD API/diff/check report. Gate:
  zero targeted Ruff/pytest failures, with exact helper imports/signatures reported.
- [x] **H.4** Root cold-reviews extraction and executes actual accounting observer proof
  before acceptance, requiring all 42 shared/two native controls and unchanged comparator
  semantics. Root owns native execution and the parent POL.5 checkbox.

> NOTE: No request-policy value/error schema is settled by this helper extraction.
> NOTE: H.1-H.3 passed on 2026-10-19 with `.venv/Scripts/python.exe -m pytest
> tests/test_csharp_accounting.py tests/test_csharp_observation.py -q -o
> cache_dir=.tmp-tests/observation-helper-pytest-cache` (32 passed) and targeted Ruff
> check/format/check. The configured shared `.pytest_cache` was inaccessible during the
> initial H.1-only invocation, so the approved targeted gate used a unique cache directory;
> no source or test semantics changed for that environmental contention.
> NOTE: Root independently accepted H.4 on 2026-10-19 after the clean cold review in
> Traycer's sdk-five-observation-helper-review and a 32-test rerun with
> cache_dir=.tmp-tests/root-observation-helper-pytest-cache. Actual accounting execution
> produced .tmp-tests/accounting/helper-extraction/run-gjhzscqx/report.json: 42 shared
> matches, no mismatches, and both native-only controls observed. Both observer headers
> carry ce71c5ee8a87aff3c137eba843d443feb642fbca, source_dirty=true, and raw corpus SHA-256
> 7a65142d5e32fade8476fce8a20e3033de340e6eb46db48c1a5cebadd4bcff0d. This closes the
> mechanical extraction only; request-policy consumers and parent POL.5 remain open.
