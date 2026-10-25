# Move from Python to C# SDK (prerelease)

Python remains the supported published SDK. The native .NET 8 C# SDK is in development as
a prerelease local package (`0.1.0-proof`) and does not claim full parity. See the [shared
foundation](../concepts/foundation.md) for its current capabilities and limits. To set up a
.NET project, follow [C# installation](csharp-installation.md) and then the
[C# quickstart](csharp-quickstart.md); this page maps the Python API you already know onto
the native one.

| Python concept | C# SDK (prerelease) |
|---|---|
| `AsyncClient` | `AsyncClient` |
| `ProviderSettings.of(...)` | `ProviderSettings.Of(...)` |
| `Target` string | `target` string passed to each call |
| `Route` and `Retry` | `Route` and `Retry`; C# `Retry` has no `retry_on` predicate |
| `Route(context_window_targets=...)` | `new Route(targets, contextWindowTargets: ...)` |
| `Repair(max_attempts=...)` | `Repair(MaxAttempts: ...)` |
| JSON Schema mapping | `SchemaSpec` and typed `Generation.DeserializeStructured<T>()` |
| Pydantic model as `schema=` | No equivalent; write a `SchemaSpec` and deserialize into a record |
| `Text.text` | `Text.Value` |
| `ImagePart`, `DocumentPart`, `AudioPart`, `VideoPart` | Same public names; C# properties use PascalCase, and byte inputs are defensively copied. |
| `result.text` | `Generation.Text` |
| `result.structured`, `result.structured_mechanism`, `result.repair_attempts` | `Generation.Structured`, `Generation.StructuredMechanism`, `Generation.RepairAttempts` |
| `result.attempts` | `Generation.Attempts` of `AttemptRecord` (`Target`, `Outcome`, `Error`, `Timing`) |
| `result.logprobs`, `result.citations`, provider tool-use counts | `Generation.Logprobs`, `Generation.Citations`, `Generation.ServerToolUses`; reasoning is a separate event. |
| `client.stream(...)` | `AsyncClient.StreamAsync(...)`, which sends nothing until enumerated, or `Client.Stream(...)`, which starts at once |
| async stream and its events | `AsyncStream` and `StreamEvent` records: `TextDelta`, `ReasoningDelta`, `CitationDelta`, `ToolCallDelta`, `ServerToolDelta`, `UsageUpdate`, `TimingMark`, `AttemptFailed`, `StreamEnded` |
| `stream.result` | `AsyncStream.Result` / `SyncStream.Result`, which throw `InvalidOperationException` until the stream completes successfully; or `CollectAsync()` / `Collect()` |
| Python `Client` | .NET `Client` and `SyncStream` |
| `AnyInferError` and its subclasses | `AnyInferException` and its subclasses. Shared failures keep their Python names with `Exception` in place of `Error` (`AllTargetsFailedException`, `SchemaViolationException`, `ToolLoopException`, and so on); C# adds `SchemaReferenceException` and `SchemaEvaluationException` for native schema failures and has no `LocalRuntimeError` counterpart. |
| `AllTargetsFailedError.attempts` | `AllTargetsFailedException.Attempts` |
| `SchemaViolationError` (`raw_text`, `errors`, `partial`) | `SchemaViolationException.Issues`; no raw text or partial members |
| `client.models(...)`, `client.health(...)` | `ModelsAsync` / `HealthAsync`, or `Models` / `Health` |
| catalog and capability queries | `Catalog`, `Resolve(...)`, and `Capabilities(...)` |
| `client.probe(...)` | `ProbeAsync(...)` or `Probe(...)`, returning `ProbeReport` |
| telemetry observer | `IObserver` supplied to or subscribed on `AsyncClient` / `Client` |
| result manifest | `AsyncStream.Manifest`, `SyncStream.Manifest`, or `Generation.Manifest` |
| `ProviderSetupSpec` metadata | `ProviderSetupSpec`, `SetupField`, `HostShorthand`, and `AnyOf` |
| explicit pricing, budgets, and ledger snapshots | `PricingCalculator`, `Budget(...)`, `SpendLedger`, and `SpendStore` |
| request policy | `SpendPolicy`, `Route.ContextWindowTargets`, `CachePolicy`, and `ToolSpec` values |
| `@ai.tool` or a plain function passed to `run_tools` | `Tool.From(delegate, name:, description:)`, or `new Tool(ToolSpec, callback)` for an explicit schema |
| `client.run_tools(...)` / `async_client.run_tools(...)` | `Client.RunTools(...)` / `AsyncClient.RunToolsAsync(...)` |
| `ToolLoopError` | `ToolLoopException` |
| Provider proxy, TLS verification, and client certificate settings | `ProviderProxy`, `TlsVerification`, and `ClientCertificate` on `ProviderSettings` |

Python cancellation uses task cancellation; C# accepts a `CancellationToken` on each call, and
the tool loop passes it on to a handler that declares a `CancellationToken` parameter.
Python async clients and streams use `async with`; C# uses `await using` for the corresponding
client and stream lifetime, and leaving an `await foreach` early cancels the stream's request.
C# also has `Client`/`SyncStream` for synchronous callers, using the .NET default task scheduler
and `using`; it does not reproduce Python's loop facade. The task guides for
[streaming](streaming.md), [structured output](structured-output.md),
[fallback](fallback.md), and the [tool loop](tool-loop.md) show each Python recipe beside its
native C# form.

## Python-only features {#python-only-features}

These Python SDK features have no C# counterpart in this prerelease; keep them in Python, the
CLI, or the sidecar:

- Pydantic models as schemas, the `@ai.tool` decorator syntax (C# binds a delegate with
  `Tool.From`), and `Retry(retry_on=...)` predicates.
- MCP tool sources and the `mcp` configuration block.
- Sessions, history reduction, and context reduction (`anyinfer.context`); C# has only the
  standalone `ContextTuning` settings values.
- Arena runs, evaluation, and benchmarks.
- Local runtime lifecycle, including supervised llama.cpp.
- Batch inference jobs (C# retrieval input batching is a different feature), OpenTelemetry
  export, and keyring credentials.
- The `anyinfer` CLI and the OpenAI-compatible sidecar.
- Python's full provider breadth: the C# default registry has OpenAI-compatible, Cerebras,
  Hyperbolic, and Nscale generation plus TEI, Voyage, and Jina embedding and reranking.

## Registered Cerebras generation

The C# default registry includes the Cerebras generation descriptor. Configure it directly with
an `env://CEREBRAS_API_KEY` credential reference and use a `cerebras:model` target. The
[registered Cerebras provider example](csharp-sdk.md#use-the-registered-cerebras-provider) is
the source-linked executable example.

Its verifier uses a scripted handler, not hosted Cerebras traffic, so hosted behavior remains
unverified. Choose a model available to the configured account through discovery; the example's
`gpt-oss-120b` is not a static catalog guarantee.

## Registered Hyperbolic generation

The C# default registry also includes Hyperbolic generation. Configure the ordinary
`ProviderSettings.Of("hyperbolic", apiKey: "env://HYPERBOLIC_API_KEY")` and target
`hyperbolic:model`; see the
[source-linked Hyperbolic example](csharp-sdk.md#use-the-registered-hyperbolic-provider).
Its default endpoint migrated from the decommissioned `https://api.hyperbolic.xyz/v1` to
`https://api.hyperbolic.ai/inference/v1`. The included example checks the default request path
offline; hosted Hyperbolic traffic remains unverified. Choose a model available to the account
through discovery; `glm-5.3-flash` is an example identifier, not a static catalog guarantee.

## Registered Nscale generation

The C# default registry includes Nscale generation. Configure ordinary
`ProviderSettings.Of("nscale", apiKey: "env://NSCALE_API_KEY")` and target `nscale:model`; see
the [source-linked Nscale example](csharp-sdk.md#use-the-registered-nscale-provider). Nscale's
official examples use `NSCALE_SERVICE_TOKEN`, which callers can supply as their explicit
credential reference. The included handler is scripted and checks the default request offline;
hosted Nscale traffic remains unverified. The example's
`meta-llama/Llama-3.1-8B-Instruct` target is not an account catalog guarantee. Exact SSE framing,
terminal usage timing, and the accepted reasoning-effort enum remain unverified; generic typed
history does not retain `reasoning_content`.

Cerebras, Hyperbolic, and Nscale are the only provider-specific generation presets in the C#
default registry; the other compatibility-preset rows bundled in the assembly are inert data and
are not registered.

## Shared configuration

`ConfigurationExample.RunAsync` accepts version 1 configuration JSON and creates a configured
client. The C# loader reads `providers`, `default_route`, `repair`, `cache`, and
`operation_routes` (whose only keys are `embedding` and `rerank`). A provider entry accepts
`id`, `adapter` (or its legacy spelling `provider_id`), `alias`, `enabled`, `base_url`,
`api_key`, `api_version`, `headers`, `options`, `values`, `timeout_s`, `limits`, `proxy`,
`verify`, and `client_cert`, plus the setup fields its provider declares. The loader refuses
the `context`, `history`, `observers`, `arena`, `arenas`, and `mcp` blocks, which the C# SDK
does not implement, with a `ConfigException`, as it does any other unknown key. It accepts and
ignores `_comment` and the bundled demo's settings (`targets`, `system_prompt`, `theme`,
`context_window_tokens`, and `ignore_runtime_hardware_constraints`), so one file can be
shared. `default_route` loads as a plain target list with the default retry policy and health
gate; `Dumps` refuses a route with custom retry, health-gate, or context-window settings,
which version 1 cannot represent. Credential references remain references while configuration
is read; resolution belongs to the selected provider's first use. Schema validation covers
Draft 6, Draft 7, Draft 2019-09, and Draft 2020-12; Draft 3 and Draft 4 are not supported. The
enforcement mechanism is chosen from the target's capabilities rather than from the request, and
the chat adapter has no `grammar` mechanism. Native numeric
and regular-expression behavior applies, with a timeout per regular-expression match. Registered
resources are explicit and external schema retrieval requires an explicit retriever.

Modern C# schema input and generated values retain arbitrary-size integers. The native validator's
numeric comparisons for `const`, `enum`, and `uniqueItems` use .NET `decimal`, so a value outside
that range, such as `1e70`, raises a controlled schema-evaluation exception.

```csharp
--8<-- "examples/csharp-sdk/ConfigurationExample.cs"
```

Connection settings can be serialized in version 1 configuration, including literal proxy
credentials and client-key passwords. `ToString()` on the typed settings omits those values, but
`Dumps()` preserves them. Treat the JSON as secret-bearing. The source-shared construction and
round-trip example is deliberately inert and does not exercise TLS or load its illustrative PEM
paths:

```csharp
--8<-- "examples/csharp-sdk/ConnectionExample.cs"
```

For SDK-created handlers, C# accepts an explicit HTTP(S) proxy; omitted verification uses platform
defaults, `TlsVerification.Disabled` disables validation, and a PEM bundle replaces platform trust
with custom roots. OpenSSL CA directories are unsupported. Native .NET chain building has
platform-specific intermediate and explicit leaf-anchor behavior. A supplied handler controls its
own proxy and TLS behavior, and the SDK does not load configured connection files for it. Automatic
redirects use the shared [provider redirect
policy](../reference/configuration.md#provider-http-redirects) when each hop is returned to the
SDK; redirects or cookies handled inside a supplied handler remain caller-controlled. On Windows,
native TLS may use a temporary OS-managed user-key file for PEM client keys; the certificate is not
added to the system store, and native references can defer normal cleanup after the SDK releases
its handler and certificate.

## Metadata and lifecycle calls

Catalog resolution and capability or pricing metadata are pure queries over configured inputs;
their values can remain unknown and carry provenance. Model listing and health are separate,
explicit instance I/O calls. The executable examples show both the async and synchronous forms.

```csharp
--8<-- "examples/csharp-sdk/CatalogExample.cs"
```

```csharp
--8<-- "examples/csharp-sdk/LifecycleExample.cs"
```

## Capability probes and setup metadata

Probe calls are explicit and may spend up to four requests by default. The async and sync
facades return an immutable `ProbeReport`; `record: false` returns evidence without storing a
new measured capability record. The raw tool declaration used by the tools probe is a transport
translation detail, not a normal C# tool-execution API.

```csharp
--8<-- "examples/csharp-sdk/ProbeExample.cs"
```

Provider setup metadata is inert. It describes fields, host shorthand, and alternatives for an
application-owned setup surface without resolving a secret or constructing an adapter.

```csharp
--8<-- "examples/csharp-sdk/SetupExample.cs"
```

## Telemetry and manifests

C# observers receive typed events synchronously. They are payload-free unless a subscription
explicitly requests payloads, and caller-owned sinks are disposed by the caller. Manifests are
immutable call records: a stream exposes an incomplete one before it is consumed and a terminal
one after completion. They do not calculate account totals or create automatic pricing.

```csharp
--8<-- "examples/csharp-sdk/TelemetryExample.cs"
```

```csharp
--8<-- "examples/csharp-sdk/ManifestExample.cs"
```

## Explicit accounting helpers

`AsyncClient.Budget(...)` and `Client.Budget(...)` calculate a planning budget without choosing a
route winner, resolving credentials, constructing an adapter, or sending a request. Pricing applies
only when its provenance is catalog, discovered, probed, or caller override; default facts leave a
calculated cost unknown, while a trusted zero price is free. The request estimator counts text,
reports other content as unpriced, and has no offered-tools input.

`SpendLedger`, `SpendStore`, and `RateLimiter` are caller-owned helpers. Used on their own, as in
this example, they make no admission decision, pace no client request, and persist nothing
automatically. Passed to a client, a ledger records the client's completed spend and holds its
spend-policy reservations, and a `limiters` entry paces requests to that provider instance. None
of them represents a provider invoice or an all-wire total. Dispose every standalone limiter
lease, and serialize store updates when you need transactional read-modify-write behavior.

```csharp
--8<-- "examples/csharp-sdk/AccountingExample.cs"
```

## Request policy inputs

`SpendPolicy`, `Route.ContextWindowTargets`, and `CachePolicy` are explicit request-policy
inputs. A client commits only its winning request to a client-local or caller-supplied ledger.
Version 1 configuration keeps `default_route` as an ordinary target list; it has no specialized
context-chain encoding. The generic OpenAI-compatible descriptor declares no cache mechanism.
`ToolSpec`, `ToolCall`, and `ToolResult` are also available as typed raw values. The C# SDK
provides a separate bounded loop over explicitly registered `Tool` handlers.

```csharp
--8<-- "examples/csharp-sdk/RequestPolicyExample.cs"
```

Callers own supplied ledgers, estimators, limiters, and stores. When an instance has active
`RateLimits`, the SDK paces its requests inside the HTTP handler it creates or wraps around a
handler you supply, so time spent waiting counts against the request's deadline. An adapter whose
descriptor declares that it governs its own transport, or a prebuilt adapter registration given a
limiter through `limiters`, is paced around each call instead: it waits for its slot before the
request's deadline starts. The C# SDK does not provide provider-invoice or all-wire accounting,
context reduction, or history reduction.

## What to use in an application

Use the [Python SDK](python-sdk.md), sidecar, or CLI for supported application integration. The
native C# SDK gives .NET developers a source-linked async API and synchronous facade
implemented by its own C# core. Rich inputs and bounded tool execution are available in that
prerelease SDK. Python remains the supported published SDK; the local C# package is not published
to NuGet and makes no full-parity claim.
