# Architecture

The condensed version. [DESIGN.md](https://github.com/anthturner/AnyInfer/blob/main/DESIGN.md) §23 has the complete rationale;
[the glossary](../reference/glossary.md) defines the vocabulary these rules use.

## The Shape

The Python SDK's layers:

<div class="anyinfer-hero-diagram" markdown>
```mermaid
flowchart TD
  A[Application] --> B["Client / AsyncClient — orchestration"]
  B --> C["catalog · schema · routing · events · capabilities"]
  C -->|WireRequest / AdapterEvent| D["registry — descriptors, entry points"]
  D --> E["adapters — openai, anthropic, ollama, copilot, ... (translation only)"]
  E --> F[local subsystem]
```
</div>

## Independent C# SDK

`src/csharp/` contains a native .NET 8 SDK in development, locally packaged as
`0.1.0-proof`. Its conformance driver reads the frozen contract corpus and compares observations from
native execution; ordinary SDK calls use public requests and execute independently. Shared
declarative assets supply data to both implementations. Python remains the supported published
SDK; C# is prerelease and does not claim full parity. See the [foundation](../concepts/foundation.md)
for its capability map and [C# development workflow](csharp-proof.md) for local workflow.

The C# SDK follows rules 1, 2, 3, 5, 6, and 8 below in native form: `GenerationRequest` and a
typed event stream, `AnyInfer.Providers.IProviderAdapter` adapters that only translate, an
async `AsyncClient` with a synchronous `Client` facade, provenance-bearing `ModelCapabilities`,
in-process `IObserver` telemetry with no OpenTelemetry bridge, and declarative
`ProviderDescriptor` setup metadata. Rules 4, 7, and 9 describe Python-only parts: the
supervised `llama.cpp` runtime, the Python dependency floor, and the sidecar. The Python method
and module names below are the Python contract.

## The Load-Bearing Rules

**1. The primitive is `GenerationRequest → typed event stream`.**
Never make the OpenAI wire format the internal representation. It is one dialect at the
edges. This is what makes the sidecar a thin projection rather than a second core.

**2. Adapters only translate.**
Four methods: `list_models`, `health`, `generate`, `aclose`. Retry, fallback, validation,
repair, timing, usage normalization, cost, telemetry, and redaction live in the core. Thin
adapters are coverable by one shared conformance suite; thick ones are not.
[Writing a provider adapter](writing-an-adapter.md) covers the contract.

**3. Async core, sync facade.**
One implementation. `Client` wraps `AsyncClient` with a background event-loop thread.

**4. llama.cpp is a supervised subprocess.**
No `llama-cpp-python`.

**5. Capability data is provenance-tagged.**
`catalog | discovered | probed | default`. Never present an estimate as authoritative, and
never coerce unknown to zero.

**6. Telemetry is typed in-process events.**
OTel is a lazy optional bridge. Nothing is written anywhere by default; events are
payload-free by default.

**7. Slim core.**
Mandatory dependencies are `httpx2` and `jsonschema`. Everything else is an extra.

**8. Providers register via frozen descriptors.**
Declarative setup specs mean no per-engine `if/elif` in core, config, or UI code.

**9. The sidecar is a wire codec.**
Four invariants, enforced from M0 and round-trip tested: request-surface superset,
event-stream sufficiency, target-in-model-string, concurrent streams. See
[the sidecar](../serve/README.md).

## Enforcement

The Python package's boundaries are checked mechanically by `lint-imports`, not left to
review. Four contracts in `pyproject.toml` enforce them:

| Contract | Forbids |
|---|---|
| Adapters never orchestrate | `anyinfer.providers` importing routing, schema validation or repair, the client, capabilities, or context reduction |
| Sidecar is a codec around the client, never a second core | `anyinfer.serve` importing providers, routing, schema, catalog, credentials, the local subsystem, or context reduction |
| Types are leaf modules (zero I/O) | `anyinfer.types` importing providers, routing, the client, schema, events, the local subsystem, context reduction, or `httpx2` |
| Context reduction is a leaf consumer | `anyinfer.context` importing providers, routing, the client, the sidecar, the local subsystem, schema, catalog, credentials, or `httpx2` |

The first, as written:

```toml
[[tool.importlinter.contracts]]
name = "Adapters never orchestrate"
type = "forbidden"
allow_indirect_imports = true
source_modules = ["anyinfer.providers"]
forbidden_modules = [
  "anyinfer.routing",
  "anyinfer.schema.validate",
  "anyinfer.schema.repair",
  "anyinfer._client",
  "anyinfer.capabilities",
  "anyinfer.context",
]
```

When one fails, move the code. Loosening a contract requires a documented reason;
`anyinfer.local` is absent from the adapter contract on purpose, because composing the
local subsystem is translation, not orchestration.

## Request Lifecycle

The Python client's path for one generation:

1. Resolve the target: alias or `provider:model` → `ResolvedTarget`.
2. Gate on health, if the target recently failed.
3. Assemble capabilities from the layered sources.
4. Build the wire request: choose the mechanism, project the schema, translate reasoning
   effort, inject a schema prompt when needed.
5. Stream adapter events, marking first token and accumulating buffers.
6. Validate structured output against the *original* schema; repair within budget.
7. Assemble the `Generation`: timings, usage, cost, warnings, attempt trail.
8. Emit `StreamEnded`.

On failure: record the attempt, emit `AttemptFailed`, then retry or advance to the next
target. Exhaustion raises `AllTargetsFailedError` with the whole trail.

Behaviors that look like bugs but are intended (unknown cost reported as `None`, no
fallback on a schema violation, a mid-stream error raising after content) are listed in
[the error catalog](../reference/errors.md#things-that-look-like-bugs-but-are-not).
