using System.Numerics;
using System.Runtime.CompilerServices;
using System.Text;
using AnyInfer;
using AnyInfer.Core;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;

namespace AnyInfer.Conformance;

/// <summary>Runs the two transport/lifetime native proof recipes from actual core and HTTP execution.</summary>
internal static class ProofTransport
{
    private const string CleanupRecipe = "driver/timeout-cleanup-disposal";
    private const string HttpRecipe = "driver/http-correction-byte-budget-reset";

    internal static async Task<NativeProofResult> RunTimeoutCleanupDisposalAsync(CancellationToken cancellationToken)
    {
        try
        {
            var capture = new OperationCapture();
            var adapter = new CleanupBlockingAdapter(capture);
            var client = new AsyncClient([new ProviderRegistration("proof", adapter)], new VirtualClock(0));
            var publicEvents = new List<StreamEvent>();
            AnyInferException? terminal = null;
            try
            {
                await using var stream = client.StreamAsync(
                    new GenerationRequest(
                        [new Message("user", [new Text("cleanup")])],
                        new Route(["proof:model"], new Retry(MaxAttempts: 1)),
            schema: new SchemaSpec(PersonSchema(), "response"),
                        timeoutS: 0.05,
                        maxResponseBytes: 80),
                    capture,
                    cancellationToken);
                var execution = ConsumePublicAsync(stream, publicEvents, cancellationToken);
                var first = await Task.WhenAny(execution, adapter.CleanupReady, Task.Delay(TimeSpan.FromSeconds(2), cancellationToken)).ConfigureAwait(false);
                if (first == execution)
                {
                    await execution.ConfigureAwait(false);
                }
                else if (first != adapter.CleanupReady)
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    throw new TransportHarnessException("cleanup adapter did not enter its iterator cleanup");
                }
                else
                {
                    await execution.ConfigureAwait(false);
                }
            }
            catch (AnyInferException exception)
            {
                terminal = exception;
            }
            finally
            {
                await client.DisposeAsync().ConfigureAwait(false);
            }

            var entry = capture.Entries.Count == 1 ? capture.Entries[0] : null;
            var lifecycle = capture.Lifecycle;
            var mapped = entry?.TerminalFailure as ProviderException;
            var allTargets = terminal as AllTargetsFailedException;
            var attempts = allTargets?.Attempts ?? [];
            var evidence = Obj(
                P("recipe_ref", S(CleanupRecipe)),
                P("capture_available", B(capture.IsAvailable)),
                P("entry", entry is null ? JsonNull.Instance : Entry(entry)),
                P("lifecycle", Lifecycle(lifecycle)),
                P("cleanup_ready", B(adapter.CleanupReached)),
                P("adapter_disposed", B(adapter.IsDisposed)),
                P("terminal", terminal is null ? JsonNull.Instance : S(terminal.GetType().Name)),
                P("attempts", new JsonArray(attempts.Select(Attempt))),
                P("public_events", new JsonArray(publicEvents.Select(static item => S(item.GetType().Name)))),
                P("assessment_count", N(capture.Assessments.Count)),
                P("native_cleanup", adapter.CleanupObservation is null ? JsonNull.Instance : CleanupObservation(adapter.CleanupObservation)),
                P("native_to_provider", B(entry?.NativeFailure is OperationCanceledException native && mapped is not null && ReferenceEquals(native, mapped.NativeInner))),
                P("provider_to_attempt", B(mapped is not null && attempts.Count == 1 && ReferenceEquals(mapped, attempts[0].Error))));
            if (!capture.IsAvailable)
            {
                return Error(CleanupRecipe, "cleanup capture was unavailable");
            }

            var names = entry is null ? [] : lifecycle.Where(item => item.EntryOrdinal == entry.Ordinal).Select(static item => item.Name).ToArray();
            var requiredLifecycle = new[] { "created", "configured", "entered", "expired", "cleanup_start", "cleanup_end", "exited", "disposed" };
            if (entry is not null && requiredLifecycle.Any(name => !names.Contains(name, StringComparer.Ordinal)))
            {
                return Error(CleanupRecipe, "cleanup lifecycle instrumentation was incomplete");
            }

            var nativeCleanup = adapter.CleanupObservation;
            if (nativeCleanup is null)
            {
                return Error(CleanupRecipe, "native iterator cleanup observation was unavailable");
            }

            var passed = entry is not null && adapter.CleanupReached && allTargets is not null &&
                entry.Timeout.IsExpired && entry.Timeout.IsDisposed && entry.NativeFailure is OperationCanceledException &&
                mapped is { Category: "transport", Retryable: true, Phase: "generate" } &&
                ReferenceEquals(entry.NativeFailure, mapped.NativeInner) && attempts.Count == 1 && attempts[0].Outcome == "failed" && ReferenceEquals(mapped, attempts[0].Error) && adapter.IsDisposed &&
                capture.Assessments.Count == 0 && publicEvents.All(static item => item is not UsageUpdate and not StreamEnded) &&
                nativeCleanup.FinalCaptured && !nativeCleanup.ExpiredBefore && !nativeCleanup.DisposedBefore && !nativeCleanup.TokenRequestedBefore && nativeCleanup.LastLifecycleBefore == "entered" &&
                nativeCleanup.ExpiredAfter && !nativeCleanup.DisposedAfter && nativeCleanup.TokenRequestedAfter && nativeCleanup.LastLifecycleAfter == "expired" &&
                names.SequenceEqual(requiredLifecycle, StringComparer.Ordinal);
            return Result(CleanupRecipe, passed, evidence, "cleanup timeout, terminal mapping, lifecycle, or disposal observation differed");
        }
        catch (TransportHarnessException exception)
        {
            return Error(CleanupRecipe, exception.Message);
        }
    }

    internal static async Task<NativeProofResult> RunHttpCorrectionByteBudgetResetAsync(CancellationToken cancellationToken)
    {
        try
        {
            var correction = await RunCorrectionAsync(cancellationToken).ConfigureAwait(false);
            var bufferedOverflow = await RunOverflowAsync(stream: false, cancellationToken).ConfigureAwait(false);
            var streamingOverflow = await RunOverflowAsync(stream: true, cancellationToken).ConfigureAwait(false);
            var exchanges = correction.Handler.Exchanges;
            var entryCount = correction.Capture.Entries.Count;
            var repair = correction.Capture.Repairs.Count == 1 ? correction.Capture.Repairs[0] : null;
            var evidence = Obj(
                P("recipe_ref", S(HttpRecipe)),
                P("correction_result", correction.Result is null ? JsonNull.Instance : S(correction.Result.Text)),
                P("correction_terminal", correction.Terminal is null ? JsonNull.Instance : S(correction.Terminal.GetType().Name)),
                P("correction_repair_attempts", correction.Result is null ? JsonNull.Instance : N(correction.Result.RepairAttempts)),
                P("correction_entries", new JsonArray(correction.Capture.Entries.Select(Entry))),
                P("correction_assessments", new JsonArray(correction.Capture.Assessments.Select(Assessment))),
                P("correction_repairs", new JsonArray(correction.Capture.Repairs.Select(Repair))),
                P("http_exchanges", new JsonArray(exchanges.Select(Exchange))),
                P("buffered_overflow", OverflowEvidence(bufferedOverflow)),
                P("streaming_overflow", OverflowEvidence(streamingOverflow)));
            if (!correction.Capture.IsAvailable)
            {
                return Error(HttpRecipe, "correction capture was unavailable");
            }

            var rawLengths = exchanges.Select(static exchange => exchange.ConfiguredRawChunks.Sum(static chunk => chunk.Length)).ToArray();
            var correctionLinked = entryCount == 2 && repair is not null && correction.Capture.Assessments.Count == 2 &&
                correction.Capture.Entries[1].Role == EntryRole.Correction &&
                ReferenceEquals(correction.Capture.Entries[1].RepairAssessment, repair.Assessment) &&
                repair.Assessment.SourceEntryOrdinal == correction.Capture.Entries[0].Ordinal &&
                exchanges.Count == 2 && ReferenceEquals(exchanges[0].BoundWireRequest, correction.Capture.Entries[0].Request) &&
                ReferenceEquals(exchanges[1].BoundWireRequest, correction.Capture.Entries[1].Request) &&
                exchanges.Select(static exchange => exchange.Ordinal).SequenceEqual([0, 1]) &&
                string.Equals(NativeProofs.AdapterText(correction.Capture.Entries[0]), repair.ResponseText, StringComparison.Ordinal) &&
                NativeProofs.HasCausalRepair(correction.Capture) &&
                NativeProofs.MessageListsEqual(NativeProofs.PreparedWireMessages(repair, correction.Capture.Entries[1].Request), correction.Capture.Entries[1].Request.Messages) &&
                ExchangeMatchesMessages(exchanges[1], correction.Capture.Entries[1].Request.Messages);
            var passed = correction.Result?.Structured is JsonObject structured && HasAge(structured) && correction.Result.RepairAttempts == 1 &&
                rawLengths.SequenceEqual([78, 74]) && rawLengths.Sum() > 100 && correctionLinked &&
                correction.Capture.Entries.All(static entry => entry.Request.MaxResponseBytes == 100) &&
                OverflowPasses(bufferedOverflow) && OverflowPasses(streamingOverflow);
            return Result(HttpRecipe, passed, evidence, "HTTP correction budget reset, causal repair, or raw-byte overflow evidence differed");
        }
        catch (TransportHarnessException exception)
        {
            return Error(HttpRecipe, exception.Message);
        }
    }

    private static async Task<CorrectionRun> RunCorrectionAsync(CancellationToken cancellationToken)
    {
        var responses = Responses(Response(78, "{\"choices\":[{\"message\":{\"content\":\"{\\\"age\\\":\\\"x\\\"}\"}}]}"), Response(74, "{\"choices\":[{\"message\":{\"content\":\"{\\\"age\\\":7}\"}}]}"));
        var handler = new ScriptedHttpMessageHandler(responses);
        var http = new OpenAIChatAdapter(new Uri("https://proof.invalid/v1"), "proof-token", handler: handler);
        var adapter = new RecordingHttpAdapter(http, handler);
        var capture = new OperationCapture();
        await using var client = new AsyncClient([new ProviderRegistration("proof", adapter)], new VirtualClock(0));
        Generation? result = null;
        AnyInferException? terminal = null;
        try
        {
            result = await client.GenerateAsync(
                new GenerationRequest(
                    [new Message("user", [new Text("Return age.")])],
                    new Route(["proof:model"], new Retry(MaxAttempts: 1)),
                    repair: new Repair(1),
            schema: new SchemaSpec(PersonSchema(), "response"),
                    maxResponseBytes: 100),
                capture,
                cancellationToken).ConfigureAwait(false);
        }
        catch (AnyInferException exception)
        {
            terminal = exception;
        }
        return new CorrectionRun(result, terminal, capture, handler);
    }

    private static async Task<OverflowRun> RunOverflowAsync(bool stream, CancellationToken cancellationToken)
    {
        var payload = stream
            ? "data: {\"choices\":[{\"delta\":{\"content\":\"" + new string('é', 24) + "\"}}]}\n\n"
            : "{\"choices\":[{\"message\":{\"content\":\"" + new string('é', 24) + "\"}}]}";
        var bytes = Encoding.UTF8.GetBytes(payload);
        var chunks = Split(bytes, 60);
        var handler = new ScriptedHttpMessageHandler(Responses(Chunks(stream ? "text/event-stream" : "application/json", chunks)));
        var http = new OpenAIChatAdapter(new Uri("https://proof.invalid/v1"), "proof-token", handler: handler);
        var adapter = new RecordingHttpAdapter(http, handler);
        var wire = new WireRequest("model", [new Message("user", [new Text("overflow")])], new Sampling(), stream: stream, maxResponseBytes: 80);
        var events = new List<AdapterEvent>();
        ProviderException? error = null;
        try
        {
            await foreach (var item in adapter.GenerateAsync(wire, cancellationToken).ConfigureAwait(false))
            {
                events.Add(item);
            }
        }
        catch (ProviderException exception)
        {
            error = exception;
        }
        await adapter.DisposeAsync().ConfigureAwait(false);
        var exchanges = handler.Exchanges;
        if (exchanges.Count != 1 || handler.RemainingResponses != 0)
        {
            throw new TransportHarnessException("overflow proof retained a missing or surplus HTTP exchange");
        }

        return new OverflowRun(events, error, exchanges[0], handler.IsDisposed);
    }

    private static async Task AwaitReadyAsync(Task ready, string message, CancellationToken cancellationToken)
    {
        try { await ready.WaitAsync(TimeSpan.FromSeconds(2), cancellationToken).ConfigureAwait(false); }
        catch (TimeoutException exception) { throw new TransportHarnessException(message + ": " + exception.Message); }
    }

    private static async Task ConsumePublicAsync(
        AsyncStream stream,
        ICollection<StreamEvent> events,
        CancellationToken cancellationToken)
    {
        await foreach (var item in stream.WithCancellation(cancellationToken).ConfigureAwait(false))
        {
            events.Add(item);
        }
    }

    private static bool OverflowPasses(OverflowRun run) => run.Exchange is not null && run.Error is { Category: "stream_protocol", Retryable: false, Phase: "stream" } &&
        run.Events.All(static item => item is not AdapterFinal) && run.Exchange.ConfiguredRawChunks.Sum(static chunk => chunk.Length) > 80 &&
        run.Exchange.ConfiguredRawChunks.All(static chunk => chunk.Length <= 80) && RawCodePoints(run.Exchange) <= 80 &&
        run.Exchange.ResponseDisposed && run.Exchange.ContentDisposed && run.Exchange.DisposedStreamCount > 0 && run.HandlerDisposed;

    private static JsonObject OverflowEvidence(OverflowRun run) => Obj(
        P("events", new JsonArray(run.Events.Select(static item => S(item.GetType().Name)))),
        P("error_category", run.Error is null ? JsonNull.Instance : S(run.Error.Category)),
        P("error_phase", run.Error?.Phase is null ? JsonNull.Instance : S(run.Error.Phase)),
        P("exchange", run.Exchange is null ? JsonNull.Instance : Exchange(run.Exchange)),
        P("raw_code_points", run.Exchange is null ? JsonNull.Instance : N(RawCodePoints(run.Exchange))),
        P("handler_disposed", B(run.HandlerDisposed)));

    private static JsonObject Exchange(RecordedHttpExchange exchange) => Obj(
        P("ordinal", N(exchange.Ordinal)),
        P("raw_chunk_bytes", new JsonArray(exchange.ConfiguredRawChunks.Select(static chunk => N(chunk.Length)))),
        P("actual_reads", new JsonArray(exchange.ActualReadByteCounts.Select(static count => N(count)))),
        P("response_disposed", B(exchange.ResponseDisposed)), P("content_disposed", B(exchange.ContentDisposed)),
        P("disposed_streams", N(exchange.DisposedStreamCount)), P("wire_stream", B(exchange.Stream)));
    private static bool ExchangeMatchesMessages(RecordedHttpExchange exchange, IReadOnlyList<Message> messages)
    {
        if (!exchange.Body.TryGetValue("messages", out var value) || value is not JsonArray bodyMessages || bodyMessages.Items.Count != messages.Count)
        {
            return false;
        }

        return bodyMessages.Items.Zip(messages).All(pair => pair.First is JsonObject body &&
            body.TryGetValue("role", out var role) && role is JsonString { Value: var actualRole } && actualRole == pair.Second.Role &&
            body.TryGetValue("content", out var content) && content is JsonString { Value: var actualContent } &&
            actualContent == string.Concat(pair.Second.Content.OfType<Text>().Select(static part => part.Value)));
    }
    private static int RawCodePoints(RecordedHttpExchange exchange) => Encoding.UTF8.GetString(exchange.ConfiguredRawChunks.SelectMany(static chunk => chunk.ToArray()).ToArray()).EnumerateRunes().Count();

    private static JsonObject Entry(EntryContext entry) => Obj(P("ordinal", N(entry.Ordinal)), P("role", S(entry.Role.ToString().ToLowerInvariant())), P("timeout_context_id", S(entry.Timeout.ContextId.ToString("D"))), P("timeout_s", D(entry.Request.TimeoutS)), P("max_response_bytes", N(entry.Request.MaxResponseBytes)), P("expired", B(entry.Timeout.IsExpired)), P("disposed", B(entry.Timeout.IsDisposed)), P("native_failure", entry.NativeFailure is null ? JsonNull.Instance : S(entry.NativeFailure.GetType().Name)), P("terminal_failure", entry.TerminalFailure is null ? JsonNull.Instance : S(entry.TerminalFailure.GetType().Name)));
    private static JsonObject CleanupObservation(CleanupNativeObservation value) => Obj(P("final_captured", B(value.FinalCaptured)), P("expired_before", B(value.ExpiredBefore)), P("disposed_before", B(value.DisposedBefore)), P("token_requested_before", B(value.TokenRequestedBefore)), P("last_lifecycle_before", value.LastLifecycleBefore is null ? JsonNull.Instance : S(value.LastLifecycleBefore)), P("expired_after", B(value.ExpiredAfter)), P("disposed_after", B(value.DisposedAfter)), P("token_requested_after", B(value.TokenRequestedAfter)), P("last_lifecycle_after", value.LastLifecycleAfter is null ? JsonNull.Instance : S(value.LastLifecycleAfter)));
    private static JsonObject Assessment(NativeAssessment assessment) => Obj(P("id", S(assessment.AssessmentId.ToString("D"))), P("source_entry", N(assessment.SourceEntryOrdinal)), P("valid", B(assessment.IsValid)));
    private static JsonObject Repair(RepairPreparation repair) => Obj(P("assessment_id", S(repair.Assessment.AssessmentId.ToString("D"))), P("response", S(repair.ResponseText)), P("messages", new JsonArray(repair.Messages.Select(static message => S(string.Concat(message.Content.OfType<Text>().Select(static part => part.Value)))))));
    private static JsonObject Attempt(AttemptRecord attempt) => Obj(P("outcome", S(attempt.Outcome)), P("error", attempt.Error is null ? JsonNull.Instance : S(attempt.Error.Category)));
    private static JsonArray Lifecycle(IReadOnlyList<LifecycleObservation> items) => new(items.Select(static item => Obj(P("sequence", N(item.Sequence)), P("entry", N(item.EntryOrdinal)), P("name", S(item.Name)))));
    private static JsonObject Obj(params JsonProperty[] properties) => new(properties);
    private static JsonProperty P(string name, JsonValue value) => new(name, value);
    private static JsonString S(string value) => new(value);
    private static JsonBoolean B(bool value) => new(value);
    private static JsonInteger N(long value) => new(new BigInteger(value));
    private static JsonNumber D(double value) => new(value);
    private static NativeProofResult Result(string recipe, bool pass, JsonObject evidence, string detail) => new(pass ? "pass" : "fail", evidence, pass ? null : detail);
    private static NativeProofResult Error(string recipe, string detail) => new("error", Obj(P("recipe_ref", S(recipe)), P("diagnostic", S(detail.Length <= 240 ? detail : detail[..240]))), detail.Length <= 240 ? detail : detail[..240]);
    private static bool HasAge(JsonObject value) => value.TryGetValue("age", out var age) && age is JsonInteger { Value: var number } && number == new BigInteger(7);
    private static JsonObject PersonSchema() => Obj(P("type", S("object")), P("properties", Obj(P("age", Obj(P("type", S("integer")))))), P("required", new JsonArray([S("age")] )));
    private static JsonArray Responses(params JsonObject[] items) => new(items);
    private static JsonObject Response(int length, string body) => Chunks("application/json", [Pad(body, length)]);
    private static JsonObject Chunks(string contentType, IReadOnlyList<byte[]> chunks) => Obj(P("status", N(200)), P("headers", Obj(P("content-type", S(contentType)))), P("byte_chunks", new JsonArray(chunks.Select(chunk => Obj(P("bytes", S(Convert.ToBase64String(chunk))))))));
    private static byte[] Pad(string body, int length) { var bytes = Encoding.UTF8.GetBytes(body); if (bytes.Length > length) throw new TransportHarnessException("proof HTTP body exceeded its required raw length"); return Encoding.UTF8.GetBytes(body + new string(' ', length - bytes.Length)); }
    private static IReadOnlyList<byte[]> Split(byte[] bytes, int size) => Enumerable.Range(0, (bytes.Length + size - 1) / size).Select(index => bytes.Skip(index * size).Take(size).ToArray()).ToArray();

    private sealed record CorrectionRun(Generation? Result, AnyInferException? Terminal, OperationCapture Capture, ScriptedHttpMessageHandler Handler);
    private sealed record OverflowRun(IReadOnlyList<AdapterEvent> Events, ProviderException? Error, RecordedHttpExchange? Exchange, bool HandlerDisposed);

    private sealed class CleanupBlockingAdapter : IProviderAdapter
    {
        private readonly OperationCapture _capture;
        private readonly TaskCompletionSource _cleanupReady = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private int _disposed;
        private CleanupNativeObservation? _cleanupObservation;
        internal CleanupBlockingAdapter(OperationCapture capture) => _capture = capture ?? throw new ArgumentNullException(nameof(capture));
        internal Task CleanupReady => _cleanupReady.Task;
        internal bool CleanupReached => _cleanupReady.Task.IsCompletedSuccessfully;
        internal bool IsDisposed => Volatile.Read(ref _disposed) != 0;
        internal CleanupNativeObservation? CleanupObservation => Volatile.Read(ref _cleanupObservation);
        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) => GenerateCoreAsync(cancellationToken);
        public ValueTask DisposeAsync() { Interlocked.Exchange(ref _disposed, 1); return ValueTask.CompletedTask; }
        private async IAsyncEnumerable<AdapterEvent> GenerateCoreAsync([EnumeratorCancellation] CancellationToken cancellationToken)
        {
            try { yield return new AdapterFinal("stop", new Usage(1, 1, 2)); }
            finally
            {
                var entry = _capture.Entries.Count == 1 ? _capture.Entries[0] : null;
                if (entry is not null)
                {
                    _cleanupObservation = Snapshot(entry);
                }

                _cleanupReady.TrySetResult();
                try
                {
                    await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken).ConfigureAwait(false);
                }
                finally
                {
                    if (entry is not null)
                    {
                        var before = _cleanupObservation ?? throw new TransportHarnessException("native cleanup observation was not recorded");
                        _cleanupObservation = before with
                        {
                            ExpiredAfter = entry.Timeout.IsExpired,
                            DisposedAfter = entry.Timeout.IsDisposed,
                            TokenRequestedAfter = entry.Timeout.Token.IsCancellationRequested,
                            LastLifecycleAfter = _capture.Lifecycle.LastOrDefault()?.Name,
                        };
                    }
                }
            }
        }

        private CleanupNativeObservation Snapshot(EntryContext entry) => new(
            entry.AdapterEvents.OfType<AdapterFinal>().Any(),
            entry.Timeout.IsExpired,
            entry.Timeout.IsDisposed,
            entry.Timeout.Token.IsCancellationRequested,
            _capture.Lifecycle.LastOrDefault()?.Name,
            false,
            false,
            false,
            null);
    }

    private sealed record CleanupNativeObservation(bool FinalCaptured, bool ExpiredBefore, bool DisposedBefore, bool TokenRequestedBefore, string? LastLifecycleBefore, bool ExpiredAfter, bool DisposedAfter, bool TokenRequestedAfter, string? LastLifecycleAfter);
}
