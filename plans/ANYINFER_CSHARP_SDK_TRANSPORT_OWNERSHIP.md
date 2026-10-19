# C# configured transport ownership prerequisite

Resume from the first unchecked box. This is a bounded SDK.5c prerequisite under the
authorized SDK execution, following accepted source `cc989e84069f09cb985e4f82fa40514f1aad5ffe`
and acceptance `56fab143687f5a9b4a1feeb28e958c8a287e8054`. Root owns this checklist,
Git, and all build/test execution; authors report saved source and independent reviews.

## Settled mechanism

The built-in OpenAI-compatible factory currently gives every transient HttpClient ownership
of the exact handler retained in ProviderSettings. A cancelled late factory result is
correctly disposed before adoption, but its disposal makes a subsequent build reuse a
disposed handler. One configured instance must own that supplied transport across builds.

- Add internal declarative `ProviderDescriptor.PoolOwnsConfiguredTransport` opt-in, false
  by default. Only the cooperative built-in descriptor opts in. No provider-ID branch and
  no public constructor/API change.
- Add internal `ProviderConfig.TransportOwnedByPool`, false for public construction.
  Pool BuildAsync sets it only for an opted-in descriptor with a supplied handler.
- OpenAIChatAdapter.Create forwards this flag to its internal constructor. A supplied
  borrowed handler is not disposed by transient HttpClients. A handler created internally
  by the adapter remains adapter-owned. Direct construction and arbitrary descriptors
  retain their existing ownership-transfer behavior by default.
- ProviderPool disposes opted-in configured raw handlers exactly once after joining builds,
  creation gates, and all adopted adapter disposals. This includes unused settings and
  factory failures. Continue remaining cleanup and preserve the first failure. Registration
  paths, source exception identity, cancellation priority, and Frozen behavior stay exact.
- The internal opt-in is a cooperative factory contract: opting in requires respecting the
  config ownership flag. Future transport governance can use this same instance lifetime.

## Execution

- [x] **OWN.1** c708 owns `Providers/ProviderDescriptor.cs`, `ProviderConfig.cs`,
  `ProviderRegistry.cs`, `OpenAIChatAdapter.cs`, and `Core/ProviderRegistry.cs` only.
  Implement the mechanism above with concise internal comments. No processes or Git.
  Gate: 500e protocol/compatibility and ec8 lifetime reviews close without findings.
  > NOTE: All five source files are saved. Both independent reviews closed cleanly.
  > The subsequent native/full gates are recorded below.
- [x] **OWN.2** 04f owns new `AnyInfer.Tests/ConfiguredTransportOwnershipTests.cs` only.
  Use a real tracking HttpMessageHandler and actual OpenAIChatAdapter inside a held,
  cooperative factory. Caller cancellation and direct stream close must discard the first
  adapter, retain a usable handler, avoid Generate/cache adoption, then make a fresh
  request successfully. Final client close disposes the raw handler once. Also cover
  default built-in opt-in, unused/factory-failed instance teardown, cleanup after one
  handler disposal fails, and non-opted-in factory transfer compatibility. No sleeps,
  production hooks, synthetic HTTP success adapters, processes, or Git.
  Gate: independent 500e/ec8 test reviews and root focused native gate.
  > NOTE: Both test reviews are clean. Root's focused native gate passes 43/43 tests,
  > including six new ownership controls plus provider/schema/late-cancellation/HTTP
  > accounting coverage, with zero compiler warnings.
- [x] **OWN.3** Root reconciles source/tests and public ownership wording if required;
  run the focused provider/schema/cancellation/HTTP tests, then one full `workspace check`.
  Preserve released specification files and all 102 frozen observations. Gate: all checks
  pass with zero compiler warnings and exact diff review.
  > NOTE: Full `workspace check` passed all 19 steps in 138.4s: 538 native unit tests,
  > 93 conformance tests, 42 shared accounting matches and two native-only controls,
  > strict docs/examples and isolated package consumption. No compiler warnings,
  > specification edits or changed frozen observations. Full gate shell:
  > `df91f9ed-5e89-405d-8818-daa84fb44eea`. Existing public transport ownership wording
  > remains accurate; only the internal built-in lifetime boundary changes.
- [x] **OWN.4** Root commits explicit paths, runs clean-revision accounting and isolated
  package proofs, and records source/evidence/acceptance. Gate: clean tree, stamped
  observers and isolated consumer pass. Resume the SDK.5c request-policy contract next;
  no automatic admission, pacing, cache placement, or broad SDK.7/9 completion is implied.
  > NOTE: Source `c7dc295d680fe51b39309fa7e17d65bf2cd7e307` is committed. Its clean-revision
  > accounting proof passes at `.tmp-tests/transport-ownership-clean-observations/run-7uo6sh3n/`:
  > both observers report that exact revision with `source_dirty=false`, 42 shared matches,
  > no mismatches and two observed native-only boundaries. The exact same source's package
  > proof passes at `.tmp-tests/transport-ownership-clean-package/run-mtkj2_29/`, including
  > the pinned five-dependency archive/license/hash closure and fresh consumer restore/build/run
  > with zero warnings. Proof shell: `e345e3f5-31f4-405f-b1e9-19c3c3e515ec` (exit 0).
  > This prerequisite is complete. Resume parent SDK.5c request-policy contract; SDK.5c
  > itself remains unchecked.
