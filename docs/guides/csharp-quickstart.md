# C# Quickstart (prerelease)

From a .NET 8 application that references the library to a first result, then cancellation,
both client lifetimes, and a test that needs no network or key. Every C# block on this page is
included from `examples/csharp-sdk/`, and the repository's offline runner executes and checks each
one. If your application does not reference `AnyInfer` yet, start with the
[installation](csharp-installation.md) steps.

The methods shown below belong to one static class, `QuickstartExample` in
`examples/csharp-sdk/QuickstartExample.cs`; the
[offline check](#test-without-a-network-or-key) copies that file into your application.

## Choose an endpoint

The built-in `openai-compat` descriptor sends OpenAI-style chat-completions requests to the base
URL you configure. Two settings cover the common cases:

```csharp
--8<-- "examples/csharp-sdk/QuickstartExample.cs:settings"
```

**A server on loopback, with no key.** Ollama and LM Studio serve an OpenAI-compatible API on
loopback, by default at `http://127.0.0.1:11434/v1` and `http://127.0.0.1:1234/v1`. The SDK sends
requests to `chat/completions` beneath the base URL, and without an API key they carry no
`Authorization` header. Name the model the server lists after `openai-compat:`, for example
`openai-compat:qwen3:8b`; everything after the first colon is the model name, so model names that
contain colons work. [List models](csharp-sdk.md#list-models-and-check-health) to see the names
the server reports. C# has no dedicated Ollama or LM Studio descriptor, so with Ollama it uses the
`/v1` compatibility layer rather than the native API that the
[Python Ollama adapter](../providers/ollama.md) uses. The SDK does not start or manage the server.

**A hosted endpoint, with a key.** Pass a credential reference such as `env://EXAMPLE_API_KEY`
rather than the key itself. Creating the settings or the client resolves nothing; the first call
resolves the reference and sends the key as a bearer token. When the variable is not set, that
call throws `CredentialException` before any request is sent. Cerebras, Hyperbolic, and Nscale
also have registered descriptors with their own default endpoints; see
[the registered providers](csharp-sdk.md#use-the-registered-cerebras-provider).

## Make the first call

```csharp
--8<-- "examples/csharp-sdk/QuickstartExample.cs:first-call"
```

For example, `await QuickstartExample.FirstCallAsync(QuickstartExample.LocalServer(),
"openai-compat:qwen3:8b")` asks a model served by Ollama, and `QuickstartExample.Describe` formats
the answer with its token counts.

`GenerateAsync` returns a buffered [`Generation`](/csharp/api/anyinfer.generation/) once the reply
is complete. `Text` is the visible answer. [`Usage`](/csharp/api/anyinfer.usage/) holds the token
counts the provider reported: it is `null` when the provider reports none, and each count is
`null` when that count is missing, so nothing is estimated in their place. `Target` names the
provider instance and model that answered, `FinishReason` says why generation stopped, and
`Attempts` records each attempt, including retries.

The method creates a client for a single call to keep the example short. A client builds each
provider's adapter the first time a call needs it and keeps it until the client is disposed, so an
application normally creates one [`AsyncClient`](/csharp/api/anyinfer.asyncclient/) and reuses it.

## Cancel a call or set a deadline

Every asynchronous call accepts a `CancellationToken`. To bound the whole call, retries included,
create a `CancellationTokenSource` with a delay and pass its token:

```csharp
--8<-- "examples/csharp-sdk/QuickstartExample.cs:deadline"
```

A cancelled call throws `OperationCanceledException`, exactly that type, carrying your token, and
is not retried. A token that is already cancelled stops the call before any request is sent; a
token cancelled while the request is in flight aborts that request. The `when` filter on your own
token keeps a cancellation you did not ask for from being mistaken for your deadline.

`timeoutS` is a different limit. It bounds each provider attempt: 120 seconds unless you set it
on `ProviderSettings` or pass it to the call. An attempt that runs out fails as a retryable
`ProviderException`, the route retries it under its `Retry` policy (two attempts by default), and
when no attempt succeeds the call throws
[`AllTargetsFailedException`](/csharp/api/anyinfer.alltargetsfailedexception/), whose `Attempts`
list each failure.

## Dispose the client

`await using var client = new AsyncClient(...)` disposes the client when the method exits, however
it exits. Disposal cancels calls still running, which then throw `OperationCanceledException`, and
disposes the provider adapters the client owns and their HTTP handlers. A `transport` you supplied
in `ProviderSettings` is disposed exactly once, even if no call used it. Disposing twice is
harmless, and a call made after disposal throws `ObjectDisposedException`. Objects you pass to the
client, such as observers and ledgers, stay yours.

## Use the synchronous facade

For code that cannot await, [`Client`](/csharp/api/anyinfer.client/) runs the same core and blocks
until each call completes. Dispose it with `using`:

```csharp
--8<-- "examples/csharp-sdk/QuickstartExample.cs:sync"
```

Failures are thrown directly rather than wrapped in an `AggregateException`, so a cancelled token
still surfaces as `OperationCanceledException`. Disposal follows the same rules as the
asynchronous client.

## Test without a network or key

`ProviderSettings` accepts a `transport`: an `HttpMessageHandler` that provider HTTP goes through
instead of a network connection. In an application's tests, a small scripted handler makes the
quickstart call deterministic, offline, and credential-free:

```csharp
--8<-- "examples/csharp-sdk/QuickstartTestingExample.cs"
```

The handler receives the request exactly as the OpenAI-compatible adapter built it, so a test can
also check its URL, headers, and body. Ownership passes to the client, which disposes the handler,
so give each `ProviderSettings` instance its own handler: one handler shared by two instances is
rejected with `ConfigException` when the client is created. A supplied handler also takes over
[connection behavior](csharp-sdk.md#configure-provider-connections), so the SDK's proxy, TLS, and
client-certificate settings do not apply to it. This helper scripts buffered responses; in your
own tests, replace the `if` check with your test framework's assertions.

To run it in the application from the installation page, copy both example files into it and
call the test from `Program.cs`, using the absolute path of your clone for `<checkout>`:

```bash
cd "<your-app>"
cp "<checkout>/examples/csharp-sdk/QuickstartExample.cs" .
cp "<checkout>/examples/csharp-sdk/QuickstartTestingExample.cs" .
echo 'Console.WriteLine(await AnyInfer.Examples.QuickstartTestingExample.RunOfflineAsync());' > Program.cs
dotnet run
```

It prints `Mars (9 input + 1 output tokens)` without contacting a server.

## Next Steps

- [Stream typed events](streaming.md), [enforce a JSON schema](structured-output.md),
  [add a fallback chain](fallback.md), and [run the tool loop](tool-loop.md#c-sdk-proof) show the
  C# form of each task.
- The [C# SDK overview](csharp-sdk.md) indexes the other native tasks: rich inputs, embeddings and
  reranking, metadata and probes, telemetry and manifests, accounting, and request policy.
- The [C# reference](../reference/csharp-sdk.md) explains native behavior and limits, and the
  [C# API reference](/csharp/api/) has a page for every public type, such as
  [`ProviderSettings`](/csharp/api/anyinfer.providersettings/).
- Coming from Python? The [migration map](python-to-csharp.md) pairs the two APIs.
