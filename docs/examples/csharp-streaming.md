# Stream to a Console with Cancellation

A console answer renderer in native C#. It writes text as it streams in, cancels on Ctrl+C or an
overall deadline, starts the answer over when an attempt fails after showing some text, says so
when a stream breaks beyond repair, and prints the terminal `Generation` once the stream
completes. A synchronous variant shows the same loop for code that cannot be asynchronous.

The route, its retries and fallback, and the cancellation of a provider call in progress are the
SDK's; the renderer only decides what to show.

## Before You Start

- The .NET 8 SDK and a reference to the local C# prerelease, as described in
  [Install the C# SDK](../guides/csharp-installation.md), and the first call from the
  [C# quickstart](../guides/csharp-quickstart.md). The C# SDK is a locally packaged
  `0.1.0-proof` prerelease, not a NuGet package.
- Nothing else to run it offline. To stream from a real endpoint, pass `ProviderSettings` for it,
  for example a self-hosted OpenAI-compatible server or the built-in Cerebras, Hyperbolic, or
  Nscale descriptors with an `env://` credential reference.

## The Program

```csharp
--8<-- "examples/csharp-sdk/CookbookStreamingExample.cs"
```

## How It Works

- **One token cancels everything.** `RunConsoleAsync` creates a `CancellationTokenSource` with the
  deadline and cancels the same source from `Console.CancelKeyPress`, setting `args.Cancel` so the
  process keeps running to report. The token is passed to `StreamAsync` and to enumeration, so
  cancelling it stops the provider call that is in progress and the route does not fall back. The
  renderer catches `OperationCanceledException` only when its own token was cancelled.
- **A stream is lazy and single-use.** `AsyncStream` sends nothing until it is first enumerated,
  has one consumer, and is disposed with `await using`. `Result` holds the terminal `Generation`
  after a successful end; reading it earlier throws.
- **Text from a failed attempt is not the answer.** Text events are yielded for every provider call
  the route makes, including calls that fail later. When an `AttemptFailed` event follows visible
  text, a retry or the next target may stream a new answer, so the renderer starts over on the next
  `TextDelta`. The terminal `Generation.Text` holds only the winning call's text.
- **Not every failure continues.** A failure before any text follows the route's normal rules: an
  authentication error moves straight to the next target, and a retryable error is retried first.
  A transport error in the middle of the body is retryable too, so the same target streams again. A
  malformed stream after visible text is neither retried nor sent to the next target; the SDK
  raises `StreamProtocolException` and the renderer reports the answer as incomplete.
- **Deadlines differ.** The caller's token bounds the whole answer, retries and fallback included.
  A provider instance's `TimeoutS` (or a request's `timeoutS`) bounds each provider call
  separately.
- **The synchronous variant.** `Client.Stream` returns a `SyncStream` that starts its generation as
  soon as it is created and buffers events for one consumer. Enumerate it once, dispose it with
  `using`, and pass the cancellation token when you create it; cancelling the token makes the next
  wait throw `OperationCanceledException`.

## Offline Run

The example runner streams scripted server-sent events through each path and asserts the outcome.
The cases are in `examples/csharp-sdk/Cases/CookbookStreamingCases.cs`; from `src/csharp`, run:

```bash
dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj --configuration Release
```

The `cookbook.streaming.*` cases check that:

- a connection reset after the first fragment is retried on the same target, the renderer discards
  the partial text once, the result holds only the second attempt's text, and the attempt trail is
  `retried` then `ok` with a `TransportException`;
- an HTTP 401 on the primary is not retried and the backup answers;
- when both targets fail after their retries, the outcome is `Failed` with all four attempts in
  the `AllTargetsFailedException`;
- a stalled body is cancelled by a 300 ms deadline: the stall observes the cancellation, the backup
  receives no request, and the outcome is `Cancelled` with the partial text;
- a malformed record after visible text ends the answer as `Broken` with
  `StreamProtocolException`, and the backup receives no request;
- the synchronous variant streams the same answer and stops when its token is cancelled;
- every transport given to the client is disposed once when the client is disposed, including a
  target's transport that was never used.

The Ctrl+C handler shares the deadline's token; the runner exercises the deadline path.

## Before Production

- Choose a deadline that covers the retries and fallback you allow, not one provider call.
- Decide how your interface shows a restart; a terminal cannot erase printed text, so this renderer
  marks the failed attempt and continues on a new line.
- Use `stream.Manifest` or an observer from [the audit-trail example](csharp-observability.md)
  when you need a record of what was streamed and why.
- Dispose the client at shutdown; it cancels streams it still owns.

## See Also

<div class="anyinfer-see-also" markdown>

- [Stream typed events](../guides/streaming.md) and [events](../concepts/events.md).
- [Add a fallback chain](../guides/fallback.md) for retry and fallback rules.
- API: [`AsyncStream`](/csharp/api/anyinfer.asyncstream/),
  [`SyncStream`](/csharp/api/anyinfer.syncstream/),
  [`StreamEvent`](/csharp/api/anyinfer.streamevent/),
  [`TextDelta`](/csharp/api/anyinfer.textdelta/),
  [`AttemptFailed`](/csharp/api/anyinfer.attemptfailed/),
  [`StreamEnded`](/csharp/api/anyinfer.streamended/),
  [`StreamProtocolException`](/csharp/api/anyinfer.streamprotocolexception/),
  [`Client`](/csharp/api/anyinfer.client/).

</div>
