using System.Net;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using AnyInfer.Providers;

namespace AnyInfer.Examples.Cases;

/// <summary>Scripted offline transports and adapters shared by the task-guide example cases.</summary>
/// <remarks>
/// Nothing here is shown in the documentation: these classes stand in for a hosted provider so the
/// streaming, structured-output, fallback and tool-loop recipes run and are asserted without a network.
/// </remarks>
internal static class GuideScripts
{
    /// <summary>Settings for one OpenAI-compatible instance whose HTTP goes to a scripted handler.</summary>
    internal static ProviderSettings Instance(HttpMessageHandler transport, string? alias = null) =>
        ProviderSettings.Of("openai-compat", ExampleSupport.BaseUrl, transport: transport, alias: alias);

    /// <summary>Answers with text, as server-sent events when the request streams and as JSON otherwise.</summary>
    internal static Func<JsonElement, HttpResponseMessage> Text(string content) => request =>
    {
        var literal = JsonSerializer.Serialize(content);
        if (request.TryGetProperty("stream", out var stream) && stream.ValueKind == JsonValueKind.True)
        {
            return Sse(
                $"{{\"choices\":[{{\"delta\":{{\"content\":{literal}}}}}]}}",
                "{\"choices\":[{\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":1,\"total_tokens\":2}}");
        }

        return Json($"{{\"choices\":[{{\"message\":{{\"content\":{literal}}},\"finish_reason\":\"stop\"}}],\"usage\":{{\"prompt_tokens\":1,\"completion_tokens\":1,\"total_tokens\":2}}}}");
    };

    /// <summary>Answers with one non-streaming tool call.</summary>
    internal static Func<JsonElement, HttpResponseMessage> ToolCall(string id, string name, string argumentsJson) => _ =>
        Json($"{{\"choices\":[{{\"message\":{{\"tool_calls\":[{{\"id\":{JsonSerializer.Serialize(id)},\"type\":\"function\",\"function\":{{\"name\":{JsonSerializer.Serialize(name)},\"arguments\":{JsonSerializer.Serialize(argumentsJson)}}}}}]}},\"finish_reason\":\"tool_calls\"}}],\"usage\":{{\"prompt_tokens\":1,\"completion_tokens\":1,\"total_tokens\":2}}}}");

    /// <summary>Answers with an HTTP failure status and a small JSON error body.</summary>
    internal static Func<JsonElement, HttpResponseMessage> Status(HttpStatusCode status, string message = "offline failure") => _ =>
        new HttpResponseMessage(status)
        {
            Content = new StringContent($"{{\"error\":{{\"message\":{JsonSerializer.Serialize(message)}}}}}", Encoding.UTF8, "application/json"),
        };

    /// <summary>Answers with literal server-sent event data records.</summary>
    internal static Func<JsonElement, HttpResponseMessage> Events(params string[] records) => _ => Sse(records);

    private static HttpResponseMessage Json(string body) => new(HttpStatusCode.OK)
    {
        Content = new StringContent(body, Encoding.UTF8, "application/json"),
    };

    private static HttpResponseMessage Sse(params string[] records)
    {
        var payload = new StringBuilder();
        foreach (var record in records)
        {
            payload.Append("data: ").Append(record).Append("\n\n");
        }

        payload.Append("data: [DONE]\n\n");
        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(payload.ToString(), Encoding.UTF8, "text/event-stream"),
        };
    }

    /// <summary>Replays one scripted response per chat request, in order, and records each request body.</summary>
    internal sealed class ChatHandler(params Func<JsonElement, HttpResponseMessage>[] responses) : HttpMessageHandler
    {
        private readonly List<string> _bodies = [];
        private readonly object _gate = new();

        /// <summary>Gets the number of requests received.</summary>
        public int RequestCount
        {
            get
            {
                lock (_gate)
                {
                    return _bodies.Count;
                }
            }
        }

        /// <summary>Gets the number of times the handler was disposed.</summary>
        public int DisposeCount { get; private set; }

        /// <summary>Parses the request body at <paramref name="index"/>.</summary>
        public JsonDocument Request(int index)
        {
            lock (_gate)
            {
                return JsonDocument.Parse(_bodies[index]);
            }
        }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (request.Method != HttpMethod.Post || request.RequestUri?.AbsolutePath != "/v1/chat/completions")
            {
                throw new InvalidOperationException("A guide case sent an unexpected request.");
            }

            var body = await request.Content!.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            int index;
            lock (_gate)
            {
                _bodies.Add(body);
                index = _bodies.Count - 1;
            }

            if (index >= responses.Length)
            {
                throw new InvalidOperationException($"A guide case sent request {index + 1} but scripted only {responses.Length}.");
            }

            using var document = JsonDocument.Parse(body);
            return responses[index](document.RootElement);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                DisposeCount++;
            }

            base.Dispose(disposing);
        }
    }

    /// <summary>
    /// Streams one text delta and then stalls, as a long generation would, until the reader cancels or
    /// the response is disposed.
    /// </summary>
    internal sealed class StallingStreamHandler(string firstDelta) : HttpMessageHandler
    {
        private readonly TaskCompletionSource _stalled = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private int _requests;
        private int _bodyDisposed;

        /// <summary>Gets the number of requests received.</summary>
        public int RequestCount => Volatile.Read(ref _requests);

        /// <summary>Gets whether the stalled response body was released; it never reaches its end.</summary>
        public bool BodyReleased => Volatile.Read(ref _bodyDisposed) == 1;

        /// <summary>Completes when the reader is waiting for the next chunk after the first delta.</summary>
        public Task Stalled => _stalled.Task;

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _requests);
            var first = Encoding.UTF8.GetBytes($"data: {{\"choices\":[{{\"delta\":{{\"content\":{JsonSerializer.Serialize(firstDelta)}}}}}]}}\n\n");
            var content = new StreamContent(new StallingStream(this, first));
            content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("text/event-stream");
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = content });
        }

        private void NoteStalled() => _stalled.TrySetResult();

        private void NoteDisposed() => Interlocked.Exchange(ref _bodyDisposed, 1);

        private sealed class StallingStream(StallingStreamHandler owner, byte[] first) : Stream
        {
            private readonly CancellationTokenSource _disposed = new();
            private bool _servedFirst;

            public override bool CanRead => true;
            public override bool CanSeek => false;
            public override bool CanWrite => false;
            public override long Length => throw new NotSupportedException();
            public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }

            public override void Flush()
            {
            }

            public override int Read(byte[] buffer, int offset, int count) =>
                ReadAsync(buffer.AsMemory(offset, count)).AsTask().GetAwaiter().GetResult();

            public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken) =>
                ReadAsync(buffer.AsMemory(offset, count), cancellationToken).AsTask();

            public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
            {
                if (!_servedFirst)
                {
                    _servedFirst = true;
                    first.CopyTo(buffer);
                    return first.Length;
                }

                owner.NoteStalled();
                using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, _disposed.Token);
                await Task.Delay(Timeout.Infinite, linked.Token).ConfigureAwait(false);
                return 0;
            }

            public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
            public override void SetLength(long value) => throw new NotSupportedException();
            public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

            protected override void Dispose(bool disposing)
            {
                if (disposing)
                {
                    owner.NoteDisposed();
                    _disposed.Cancel();
                }

                base.Dispose(disposing);
            }
        }
    }

    /// <summary>An application-owned adapter that replays fixed events, including reasoning and citations.</summary>
    internal sealed class EventAdapter(params AdapterEvent[] events) : IGeneratesText, IAsyncDisposable
    {
        /// <summary>Gets the number of generations requested.</summary>
        public int Calls { get; private set; }

        /// <summary>Gets the number of times the client disposed this adapter.</summary>
        public int DisposeCount { get; private set; }

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
            WireRequest request,
            [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            Calls++;
            foreach (var item in events)
            {
                await Task.Yield();
                cancellationToken.ThrowIfCancellationRequested();
                yield return item;
            }
        }

        public ValueTask DisposeAsync()
        {
            DisposeCount++;
            return ValueTask.CompletedTask;
        }
    }

    /// <summary>An application-owned adapter whose every generation fails with one provider error.</summary>
    internal sealed class FailingAdapter(ProviderException failure) : IGeneratesText, IAsyncDisposable
    {
        /// <summary>Gets the number of generations requested.</summary>
        public int Calls { get; private set; }

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
            WireRequest request,
            [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            Calls++;
            await Task.Yield();
            if (Calls > 0)
            {
                throw failure;
            }

            yield break;
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    /// <summary>Requires <paramref name="action"/> to throw <typeparamref name="TException"/>.</summary>
    internal static void ExpectThrows<TException>(Action action, string message)
        where TException : Exception
    {
        try
        {
            action();
        }
        catch (TException)
        {
            return;
        }

        throw new InvalidOperationException(message);
    }

    /// <summary>Requires <paramref name="action"/> to fail with <typeparamref name="TException"/> and returns it.</summary>
    internal static async Task<TException> ExpectThrowsAsync<TException>(Func<Task> action, string message)
        where TException : Exception
    {
        try
        {
            await action();
        }
        catch (TException exception)
        {
            return exception;
        }

        throw new InvalidOperationException(message);
    }
}
