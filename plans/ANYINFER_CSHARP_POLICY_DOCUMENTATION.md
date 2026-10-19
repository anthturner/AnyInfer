# C# request-policy documentation and package surface

Resume from the first unchecked box. This is the disjoint source-only part of POL.6 in
ANYINFER_CSHARP_SDK_POLICIES.md. Owner: c16. Read DESIGN.md, the whole parent policy plan
and this leaf before editing. Preserve concurrent changes, re-read before minimal edits,
and never change Git state. Root owns all native/shared builds and acceptance.

## Ownership and boundaries

- Own new examples/csharp-sdk/RequestPolicyExample.cs and minimal calls/offline assertions
  in examples/csharp-sdk/Program.cs; docs/guides/csharp-sdk.md,
  docs/guides/python-to-csharp.md, docs/reference/csharp-sdk.md, docs/guides/README.md,
  src/csharp/README.md; scripts/check_csharp_package.py and tests/test_csharp_packaging.py.
  Own D.1-D.4 below. Root owns D.5, shared plans, solution/workspace files and Git.
- All production policy/tool/cache/config sources are held after the POL.4 phase gate
  (657 unit plus 93 conformance tests). This work does not depend on the proposed POL.5
  corpus/schema. Do not edit observer/schema/fixtures, product sources, prior native tests,
  csproj/solution/package versions, released assets or another author's files.
- Use current public APIs only. Any API mismatch is a source-backed question to root;
  do not weaken a sample, change product behavior, add a friend hook, or invent a surface.
- Examples are compiled source referenced verbatim by both guides through the established
  source-include convention. The existing example harness must call every new method using
  offline public recording adapters/handlers and assert meaningful resulting behavior.
- Cover spend policy/ledger and winning-only charge, default context gate and opt-out,
  public specialized Route chain versus target-list-only config, typed raw tool feedback/
  deltas/calls without callable execution, request/client cache precedence and generic
  OpenAI's undeclared mechanism, and configured limits with transport ownership semantics.
  Small independent examples are preferable to one mixed-purpose application.
- Explain caller ownership of supplied estimator/ledger/limiter/store and auto-created
  policy ledger; ordinary governed HTTP queueing lies inside generation entry timeout,
  own-transport outer slots precede it, and lifecycle/probe paths have their existing rules.
  Document normal factory transport consumption, pool-owned raw versus wrapper ownership,
  and non-pool transferred raw rebuild refusal. Do not promise universal transport parity.
- Shared config adds actual provider limits/root cache only. Keep context/history and
  spend config claims unchanged. Do not add a specialized-chain config encoding.
- Keep the C# support ceiling precise: no automatic tool loop, rich-media breadth,
  context/history reducers, provider-invoice accounting or cache-specific provider claims.
  Do not claim POL.5/full SDK.5c acceptance. No plans links or ADR identifiers under docs.
  Reconcile repeated counts/lists/claims using actual source rather than estimates.
- Extend the existing isolated NuGet consumer proof with public policy/tool/cache/config
  construction and offline invocation, without source project references or production
  expected-result tables. Preserve dependency/license/hash and existing consumer controls.
- No native build/test/package/example/doc-build process in this grant. Targeted Ruff on
  the two owned Python files is permitted. Propose exact pure-Python test selectors if
  needed; root grants/runs serialized gates once the snapshot is held.

## Checklist

- [x] **D.1** Author public RequestPolicyExample methods and minimal offline harness
  invocation/assertions. Gate: statically trace every method to the current public API,
  include no uncalled method, and report the exact compile/runtime gate root should run.
- [x] **D.2** Update the named guides/reference/index/readme surfaces using exact compiled
  source includes and precise support/lifetime/config boundaries. Gate: all repeated claims
  agree with held source, source include paths exist, no docs-to-plan or ADR-number leak.
- [x] **D.3** Extend isolated package consumer proof and its meaningful existing controls.
  Gate: source inspection confirms package-only consumption and no weakened dependency,
  license/hash, consumer or source-revision checks; report targeted tests for root.
- [x] **D.4** Run targeted Ruff check/format/check on owned Python files, re-read/tick only
  these author boxes, NOTE any deviations and report coherent SAVED/HELD paths, API coverage,
  exclusions and unexecuted gates. No compiled/runtime acceptance claim.
- [x] **D.4R** Correct the isolated-consumer fixture oracle, make raw feedback and inbound
  tool calls/deltas traverse actual public generation/HTTP or adapter paths in the example
  and package consumer, and reconcile transport-pacing/timeout claims across the owned
  docs. Gate: current public source and meaningful offline assertions are statically
  aligned, targeted Ruff passes, and a coherent SAVED/HELD handoff is sent for root rerun.
  This is author-owned; no native/shared process grant.
- [x] **D.4S** Reconcile tool-only empty-text/finish assertions and exact outgoing/inbound
  call ID/name/Boston arguments, assistant null content and tool-result clear feedback in
  both offline example and package consumer. Gate: meaningful boundary assertions/static
  source controls and targeted Ruff; report SAVED/HELD without native processes.
- [x] **D.5** Root cold-reviews the held snapshot and runs compiled offline examples,
  targeted package controls/isolated consumer and strict docs gates, resolving findings
  before closing parent POL.6. Root-only.

> NOTE: Root grants this independent source-only wave while POL.5 schemas are revised.
> Production APIs are already held; ownership is disjoint and no shared build runs during
> authoring. This parallelism does not close POL.5, POL.6 or SDK.5c acceptance.
>
> NOTE: D.1-D.4 saved 2026-10-19. RequestPolicyExample is source-linked from both C# guides,
> the offline harness calls it, and the isolated consumer covers public spend, route, cache,
> raw-tool, and config values. Ruff check and format check pass for the two Python paths.
> Compiled example, package-consumer, and documentation gates remain D.5 root work.
> NOTE: Initial root D.5 gates: all 23 tests/test_csharp_packaging.py controls pass with
> a unique cache, and the Release offline example executable exits zero. Actual isolated
> package execution at .tmp-tests/nuget/policy-documentation/run-_thpdkc7 builds with zero
> warnings/errors but its new policy block expects hello from a fresh DemoAdapter that
> emits buffered. Package acceptance remains open pending the fixture correction and cold
> source review; no successful package or documentation acceptance is claimed.
>
> NOTE: D.4R saved 2026-10-19. The source-linked example sends raw tool feedback in a
> modern request, consumes streamed public tool deltas and terminal calls, and the offline
> handler verifies the projected HTTP message shape. The package consumer uses a dedicated
> adapter for the same causal path and consumes configuration through `FromConfig`.
> Documentation now distinguishes normal configured-handler pacing inside entry from the
> own-transport or opaque-prebuilt outer slot. Ruff check and format check pass; D.5 remains
> root-owned and unexecuted.
> NOTE: Root executed the D.4R Release example: compilation succeeds, but its policy
> Require still expects hello although the new SSE fixture emits only tool calls. The
> bounded rereview is active, including exact outgoing feedback/inbound argument values.
> Do not treat the initial example pass as verification of the revised snapshot; D.5,
> isolated-consumer rerun and strict documentation acceptance remain open.

> NOTE: D.4S saved 2026-10-19. The offline handler verifies the projected assistant and tool
> feedback messages, including null assistant content, both call IDs/names, parsed Boston
> arguments, and clear tool content. The source-linked example and package-only consumer
> require empty tool-only terminal text, `tool_calls`, terminal calls, and streamed delta
> fields. Targeted Ruff passes; all native, package, example, and documentation gates remain
> root-owned.

> NOTE: D.5 mechanical package-template fix saved 2026-10-19. The generated consumer now
> declares the Boston argument literal as a `const string`, so its exact `ToolCallDelta`
> property-pattern comparison remains a constant-pattern field check. No package behavior or
> dependency policy changed; the package rerun remains root-owned.
> NOTE: D.5 package fixture alignment saved 2026-10-19. The generated raw-tool declaration
> now includes the asserted object `properties.city.type == string` schema. This changes only
> the package fixture input; its exact boundary assertions and dependency policy remain intact.

> NOTE: Root accepted D.5 on 2026-10-19 after the final cold review and actual gates.
> The revised Release offline executable passes after a missing AnyInfer.Json import was
> added to Program.cs. All 23 packaging controls pass. The actual isolated local-feed
> consumer at .tmp-tests/nuget/policy-documentation/run-f4awn2fr builds with zero warnings
> and errors and exits zero; dependency archives, licenses, hashes, package contents and
> source revision checks remain enabled. All four workspace documentation steps pass:
> documentation coverage, relative links, 50 runnable examples and strict site build.
> Both guides source-include the exact compiled RequestPolicyExample.cs. Initial fixture
> failures are superseded by these successful reruns. No publication/version bump occurred;
> POL.5 and clean-revision/full-workspace POL.7 acceptance remain separate.
