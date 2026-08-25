# Reference

Look things up.

- **[SDK reference](api/README.md)**: the generated API reference: every public class,
  function, and event, from the docstrings.
- **[Error catalog](errors.md)**: every exception, when it is raised, whether it retries,
  and the `hint` the user will see.
- **[Conformance matrix](conformance-matrix.md)**: what each provider actually supports,
  from test results rather than assertion.
- **[Shared configuration](configuration.md)**: provider settings, environment variables,
  and the common JSON file.
- **[Run manifests](../concepts/run-manifests.md)**: the manifest format, serialization
  compatibility, and its executable JSON Schema.
- **[Glossary](glossary.md)**: the vocabulary this project uses precisely.

## API Stability

The public API is fully typed (the package ships a `py.typed` marker) and documented in
its docstrings. The stability commitments cover the top-level `anyinfer` namespace plus
the subpackage surfaces the guides teach: `anyinfer.config`, `anyinfer.local`,
`anyinfer.serve`, `anyinfer.testing`, and `anyinfer.otel`. Anything under
`anyinfer._client` is private, and within every module only the names in `__all__` are
public; everything else is an implementation detail that may change without notice.
`help(ai.AsyncClient.generate)` in a REPL always matches the published
[SDK reference](api/README.md), because both come from the same docstrings.

**Where changes are recorded.**
[GitHub Releases](https://github.com/anthturner/AnyInfer/releases) is the canonical change
record: every release carries generated notes covering what changed in it, and the project
publishes no separate changelog that could drift from them. AnyInfer is pre-1.0, so a minor
version may change a public signature — read the release notes for the version you are
moving to before upgrading.

## Module Map

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
| [`anyinfer.local`](api/local.md) | Hardware, backends, tuning, downloads, supervision. |
| [`anyinfer.providers`](api/registry.md) | One module per adapter. |
| [`anyinfer.testing`](api/testing.md) | Fakes, cassettes, and the conformance suite. |
| [`anyinfer.serve`](api/serve.md) | The OpenAI-compatible frontend. |
| [`anyinfer.otel`](api/telemetry.md) | The OpenTelemetry bridge. |
