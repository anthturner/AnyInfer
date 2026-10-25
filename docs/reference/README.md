# Reference

Look things up.

The Python reference documents the supported published SDK. The native .NET 8 SDK is in
development as a prerelease local package (`0.1.0-proof`) with a generated API reference and
an authored reference for the behavior its signatures do not show. It is not published to
NuGet and does not claim full parity. See the
[foundation capability map](../concepts/foundation.md).

- **[Python API reference](api/README.md)**: the generated API reference for the supported
  published Python SDK: every public class,
  function, and event, from the docstrings.
- **[C# API reference](/csharp/api/)**: the generated reference for the prerelease .NET
  SDK: every public type, constructor, overload, property, and operator, from the source
  documentation comments.
- **[C# SDK reference](csharp-sdk.md)**: native behavior, limits, and differences from
  Python that the C# signatures do not show, with a map into the generated reference.
- **[Python error catalog](errors.md)**: every Python exception, when it is raised, whether
  it retries, and the `hint` the user will see. C# exceptions are in the generated C# API
  reference.
- **[Python conformance matrix](conformance-matrix.md)**: what each Python provider actually
  supports, from test results rather than assertion.
- **[Shared configuration](configuration.md)**: the common JSON file, which top-level
  blocks and provider settings each SDK accepts, provider settings, and the Python
  environment variables.
- **[Run manifests](../concepts/run-manifests.md)**: the manifest format, serialization
  compatibility, and its executable JSON Schema.
- **[Glossary](glossary.md)**: the vocabulary this project uses precisely.

## API Stability

The following stability commitments apply to the published Python API. It is fully typed (the
package ships a `py.typed` marker) and documented in
its docstrings. The stability commitments cover the top-level `anyinfer` namespace plus
the subpackage surfaces the guides teach: `anyinfer.config`, `anyinfer.local`,
`anyinfer.serve`, `anyinfer.testing`, and `anyinfer.otel`. Anything under
`anyinfer._client` is private, and within every module only the names in `__all__` are
public; everything else is an implementation detail that may change without notice.
`help(ai.AsyncClient.generate)` in a REPL always matches the published
[SDK reference](api/README.md), because both come from the same docstrings.

**Where changes are recorded.**
[`CHANGELOG.md`](https://github.com/anthturner/AnyInfer/blob/main/CHANGELOG.md) is the
canonical change record, curated to what a caller would act on. Each
[GitHub Release](https://github.com/anthturner/AnyInfer/releases) carries that version's
section verbatim as its notes, so the two cannot drift. AnyInfer is pre-1.0, so a minor
version may change a public signature — read the entries for the version you are moving to
before upgrading. What earns an entry is in
[the changelog rules](../contributing/changelog.md).

## Module Map

This module map is for the Python SDK. The native C# prerelease has its own
[generated API reference](/csharp/api/), organized by namespace, and does not claim this
module layout or Python API stability.

| Module | Responsibility |
|---|---|
| [`anyinfer.types`](api/requests.md) | Frozen domain types. Zero I/O. |
| [`anyinfer.errors`](api/errors.md) | The exception hierarchy. |
| [`anyinfer._client`](api/client.md) | `AsyncClient`, the sync `Client`, and the tool loop. |
| [`anyinfer.registry`](api/registry.md) | Provider descriptors and collision-safe registration. |
| [`anyinfer.config`](api/configuration.md) | Shared, versioned JSON configuration. |
| [`anyinfer.routing`](api/routing.md) | Routes, retries, health gating, attempt accounting. |
| [`anyinfer.schema`](api/requests.md) | Mechanism selection, projection, validation, repair. |
| [`anyinfer.events`](api/telemetry.md) | Telemetry events and observer dispatch. |
| [`anyinfer.redaction`](api/telemetry.md) | The secret-redaction registry. |
| [`anyinfer.credentials`](api/registry.md) | Credential resolvers. |
| [`anyinfer.catalog`](api/registry.md) | Alias catalog and target resolution. |
| [`anyinfer.capabilities`](api/capabilities.md) | Capability assembly, cost computation, token estimation, context budgets, and the pre-dispatch gate. |
| [`anyinfer.context`](api/context.md) | Context reduction and history compaction. |
| [`anyinfer.evaluate`](api/compare-diff.md) | The portability diff over `compare()` snapshots. |
| [`anyinfer.local`](api/local.md) | Hardware, backends, tuning, downloads, supervision. |
| [`anyinfer.providers`](api/registry.md) | One module per adapter. |
| [`anyinfer.testing`](api/testing.md) | Fakes, cassettes, and the conformance suite. |
| [`anyinfer.serve`](api/serve.md) | The OpenAI-compatible frontend. |
| [`anyinfer.otel`](api/telemetry.md) | The OpenTelemetry bridge. |
