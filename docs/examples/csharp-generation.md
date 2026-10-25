# Summarize with Configured Fallback

A small release-notes summarizer service in native C#. It reads version 1 JSON configuration,
builds one `AsyncClient` from it, and summarizes each release note into an application record
through a two-target route: a hosted Cerebras model first, a self-hosted OpenAI-compatible server
second. Each summary carries the routing trail and the reported usage of the call that won, and a
release whose route is exhausted carries the trail of every attempt, so an operator can see which
provider answered and why.

The program calls the SDK for everything that is policy: the route's order, same-target retry,
the health gate, schema enforcement, validation and repair all happen inside `GenerateAsync`. The
application code only chooses inputs and reports results.

## Before You Start

- The .NET 8 SDK and a reference to the local C# prerelease, as described in
  [Install the C# SDK](../guides/csharp-installation.md). The C# SDK is a locally packaged
  `0.1.0-proof` prerelease, not a NuGet package.
- The first buffered call in the [C# quickstart](../guides/csharp-quickstart.md), which this
  program builds on.
- Nothing else to run it offline. Running it against real endpoints is optional; see
  [Hosted setup](#hosted-setup-optional).

## The Program

```csharp
--8<-- "examples/csharp-sdk/CookbookGenerationExample.cs"
```

## How It Works

- **Configuration is data, loaded without I/O.** `Configuration` is the text a deployment keeps in
  `anyinfer.json`; `AnyInferConfig.Load` reads such a file and `AnyInferConfig.Loads` reads a
  string. Loading validates the document and the provider entries but resolves no
  credential and builds no adapter. `AsyncClient.FromConfig` uses the configured providers,
  `default_route`, and `repair` budget as given.
- **The route is the fallback chain.** `default_route` lists `cerebras:gpt-oss-120b` and then
  `local:qwen3-8b`. Version 1 configuration has no retry block, so the route uses the `Retry`
  defaults: two attempts per target with a 0.5 second base backoff. A retryable failure such as
  HTTP 503 is retried once on the same target and then the route moves on; an authentication
  failure is never retried. When every target fails, the program receives
  `AllTargetsFailedException` with one `AttemptRecord` per attempt.
- **The health gate remembers failures across calls on the same client.** After the primary fails
  with a provider-unavailable or transport error, later calls on that client skip it for
  `Route.HealthTtlS` (30 seconds by default) and record the skip as `skipped_unhealthy`. That is
  why the program keeps one client for the whole batch.
- **Structured output ends in an application record.** The schema is a Draft 2020-12 document. The
  SDK picks the strongest mechanism the target is known to support (the local OpenAI-compatible
  target is not known to support JSON-schema output, so it gets prompt instructions), validates the
  response, and spends the configured repair budget on correction. `DeserializeStructured<T>`
  then converts the validated value with `System.Text.Json`. A response that still fails after the
  repair budget raises `SchemaViolationException`; it does not move on to the next target.
- **Usage is the winning call's.** `Generation.Usage` reports what the provider returned for the
  call that produced the result. Tokens spent on failed attempts or on a rejected first response
  are not added in; the SDK does not produce an all-wire or invoice total.
- **Metadata stays local.** The `release` label reaches telemetry observers, and its key the
  manifest; it is not sent to the provider.

## Offline Run

The example runner executes this program with the shipped configuration read through
`AnyInferConfig.Load`, after giving each configured instance a scripted HTTP handler, and asserts
what the program observed. The cases are in [`Cases/CookbookGenerationCases.cs`](../../examples/csharp-sdk/Cases/CookbookGenerationCases.cs);
from `src/csharp`, run:

```bash
dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj --configuration Release
```

The runner executes every example case, not only this page's, and prints
`example case <name>: ok` for each one that passes.

The `cookbook.generation.*` cases check that:

- the primary is retried once on HTTP 503 and then abandoned, the local server's first answer fails
  validation and is repaired, and the second release skips the unhealthy primary;
- the `env://CEREBRAS_API_KEY` reference reached only the hosted endpoint as a Bearer header, the
  keyless local server received no `Authorization` header, and neither release ID appears in any
  request to either target;
- an exhausted route is reported per release, and the second release fails without another
  request because both targets are marked unhealthy;
- an exhausted repair budget is reported as `schema_violation` with no request to the second
  target;
- with the environment variable unset, `CredentialException` stops the program before any
  request is sent;
- the client disposes each transport it was given exactly once.

## Hosted Setup (Optional)

To run the same program against real endpoints, save `Configuration` as `anyinfer.json`, load it
with `AnyInferConfig.Load`, and pass the result to `RunAsync`. Export
`CEREBRAS_API_KEY` in the environment; the configuration only names it. Start an OpenAI-compatible
server, such as vLLM, at `http://127.0.0.1:8000/v1` for the fallback. Choose model IDs that
your account and server actually list; `gpt-oss-120b` and `qwen3-8b` are illustrations, not a
catalog guarantee. This program's hosted Cerebras path is verified offline against scripted
responses only.

## Before Production

- Read configuration from a file path you control, and keep every `api_key` an `env://`
  reference. `AnyInferConfig.Dumps` writes configured literals back out as written.
- Treat `CredentialException` and `ConfigException` as startup or deployment errors, not
  per-request ones; the program lets them propagate.
- When the retry defaults do not suit you, construct a `Route` from the configured targets with
  your own `Retry` and pass it to `GenerateAsync` as `route`; version 1 configuration cannot
  express a retry policy.
- Set `timeout_s` per provider for your latency budget; it bounds each provider call separately.
- Keep one long-lived client per process so the health gate and adapter connections are shared.

## See Also

<div class="anyinfer-see-also" markdown>

- [Add a fallback chain](../guides/fallback.md) and [routing](../concepts/routing.md):
  route design, retry, and the health gate.
- [Enforce a JSON schema](../guides/structured-output.md) and
  [structured output](../concepts/structured-output.md): mechanisms and repair.
- [Shared configuration](../reference/configuration.md) and
  [credentials](../concepts/credentials.md).
- API: [`AnyInferConfig`](/csharp/api/anyinfer.config.anyinferconfig/),
  [`AsyncClient`](/csharp/api/anyinfer.asyncclient/), [`Route`](/csharp/api/anyinfer.route/),
  [`Retry`](/csharp/api/anyinfer.retry/), [`Repair`](/csharp/api/anyinfer.repair/),
  [`SchemaSpec`](/csharp/api/anyinfer.schemaspec/),
  [`Generation`](/csharp/api/anyinfer.generation/),
  [`AttemptRecord`](/csharp/api/anyinfer.attemptrecord/),
  [`AllTargetsFailedException`](/csharp/api/anyinfer.alltargetsfailedexception/),
  [`SchemaViolationException`](/csharp/api/anyinfer.schemaviolationexception/).
- The Python version of this pattern: [Structured summaries with a fallback chain](summarize-with-fallback.md).

</div>
