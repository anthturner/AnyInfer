# Reference

Look things up.

- **[SDK reference](api/README.md)** — the generated API reference: every public class,
  function, and event, from the docstrings.
- **[Error catalog](errors.md)** — every exception, when it is raised, whether it retries,
  and the `hint` your user will see.
- **[Conformance matrix](conformance-matrix.md)** — what each provider actually supports,
  from test results rather than assertion.
- **[Shared configuration](configuration.md)** — provider settings, environment variables,
  and the common JSON file.
- **[Glossary](glossary.md)** — the vocabulary this project uses precisely.

## API stability

The public API is fully typed (the package ships a `py.typed` marker) and documented in
its docstrings; CI fails if any exported symbol lacks a docstring or a reference page.
The stability commitments cover the top-level `anyinfer` namespace plus the subpackage
surfaces the guides teach: `anyinfer.config`, `anyinfer.local`, `anyinfer.serve`,
`anyinfer.testing`, and `anyinfer.otel`. Anything under `anyinfer._client` is private, and within every module
only the names in `__all__` are public — everything else is an implementation detail
that may change without notice. `help(ai.AsyncClient.generate)` in a REPL always
matches the published [SDK reference](api/README.md), because both come from the same
docstrings.

## Module map

| Module | Responsibility |
|---|---|
| `anyinfer.types` | Frozen domain types. Zero I/O. |
| `anyinfer.errors` | The exception hierarchy. |
| `anyinfer._client` | `AsyncClient`, the sync `Client`, and the tool loop. |
| `anyinfer.registry` | Provider descriptors and collision-safe registration. |
| `anyinfer.config` | Shared, versioned JSON configuration. |
| `anyinfer.routing` | Routes, retries, health gating, attempt accounting. |
| `anyinfer.schema` | Mechanism selection, projection, validation, repair. |
| `anyinfer.events` | Telemetry events and observer dispatch. |
| `anyinfer.redaction` | The secret-redaction registry. |
| `anyinfer.credentials` | Credential resolvers. |
| `anyinfer.catalog` | Alias catalog and target resolution. |
| `anyinfer.capabilities` | Capability assembly, cost computation, token estimation, context budgets, and the pre-dispatch gate. |
| `anyinfer.local` | Hardware, backends, tuning, downloads, supervision. |
| `anyinfer.providers` | One module per adapter. |
| `anyinfer.testing` | Fakes, cassettes, and the conformance suite. |
| `anyinfer.serve` | The OpenAI-compatible frontend. |
| `anyinfer.otel` | The OpenTelemetry bridge. |
