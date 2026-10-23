using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

public sealed class OpenAIChatTests
{
    [Fact]
    public async Task Buffered_request_projects_method_path_headers_body_limits_and_native_event_order()
    {
        var handler = new ScriptedHandler(Response(HttpStatusCode.OK, "application/json", """
            {"choices":[{"message":{"content":"hello"},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}
            """));
        await using var adapter = Adapter(handler);

        var events = await Collect(adapter.GenerateAsync(Request(stream: false, sampling: new Sampling(stop: []))));

        var request = Assert.Single(handler.Requests);
        Assert.Equal(HttpMethod.Post, request.Method);
        Assert.Equal("/v1/chat/completions", request.Path);
        Assert.Equal("application/json", request.Headers["content-type"]);
        Assert.Equal("Bearer fixture-token", request.Headers["authorization"]);
        Assert.Equal("transport", request.Headers["x-fixture"]);
        Assert.Equal("fixture-model", request.Body.RootElement.GetProperty("model").GetString());
        Assert.Equal("Hello.", request.Body.RootElement.GetProperty("messages")[0].GetProperty("content").GetString());
        Assert.False(request.Body.RootElement.TryGetProperty("stream", out _));
        Assert.False(request.Body.RootElement.TryGetProperty("stream_options", out _));
        foreach (var omitted in new[] { "temperature", "top_p", "max_tokens", "stop", "seed", "presence_penalty", "frequency_penalty" })
        {
            Assert.False(request.Body.RootElement.TryGetProperty(omitted, out _));
        }
        Assert.Equal(3, events.Count);
        var text = Assert.IsType<AdapterTextDelta>(events[0]);
        var usage = Assert.IsType<AdapterUsage>(events[1]);
        var final = Assert.IsType<AdapterFinal>(events[2]);
        Assert.Equal("hello", text.Text);
        AssertUsage(usage.Usage, 2, 1, 3);
        Assert.Equal("stop", final.FinishReason);
        AssertUsage(Assert.IsType<Usage>(final.Usage), 2, 1, 3);
        Assert.Same(usage.Usage, final.Usage);
    }

    [Fact]
    public async Task Stream_mode_is_sole_mode_selector_and_projects_all_supplied_sampling_fields()
    {
        var handler = new ScriptedHandler(Response(HttpStatusCode.OK, "text/event-stream", Sse(
            """{"choices":[{"delta":{"content":"sample"}}]}""",
            """{"choices":[{"delta":{},"finish_reason":"stop"}]}""",
            "[DONE]")));
        await using var adapter = Adapter(handler);
        var sampling = new Sampling(temperature: 0.25, topP: 0.75, maxOutputTokens: 12, stop: ["END"], seed: 7, presencePenalty: 0.1, frequencyPenalty: -0.2);

        var events = await Collect(adapter.GenerateAsync(Request(stream: true, sampling: sampling)));

        var body = Assert.Single(handler.Requests).Body.RootElement;
        Assert.True(body.GetProperty("stream").GetBoolean());
        Assert.True(body.GetProperty("stream_options").GetProperty("include_usage").GetBoolean());
        Assert.Equal(0.25, body.GetProperty("temperature").GetDouble());
        Assert.Equal(0.75, body.GetProperty("top_p").GetDouble());
        Assert.Equal(12, body.GetProperty("max_tokens").GetInt32());
        Assert.Equal("END", body.GetProperty("stop")[0].GetString());
        Assert.Equal(7, body.GetProperty("seed").GetInt64());
        Assert.Equal(0.1, body.GetProperty("presence_penalty").GetDouble());
        Assert.Equal(-0.2, body.GetProperty("frequency_penalty").GetDouble());
        Assert.Collection(events,
            item => Assert.Equal("sample", Assert.IsType<AdapterTextDelta>(item).Text),
            item => Assert.Equal("stop", Assert.IsType<AdapterFinal>(item).FinishReason));
    }

    [Fact]
    public async Task Sse_frame_split_and_trailing_usage_preserve_event_order_until_done()
    {
        var complete = Encoding.UTF8.GetBytes("data: {\"choices\":[{\"delta\":{\"content\":\"é\"}}]}\n\ndata: {\"choices\":[],\"usage\":{\"prompt_tokens\":2,\"completion_tokens\":1,\"total_tokens\":3}}\n\ndata: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\ndata: [DONE]\n\n");
        var utf8Lead = Array.IndexOf(complete, (byte)0xc3);
        Assert.True(utf8Lead >= 0);
        var split = complete[..(utf8Lead + 1)];
        var remainder = complete[(utf8Lead + 1)..];
        var handler = new ScriptedHandler(Response(HttpStatusCode.OK, "text/event-stream", split, remainder));
        await using var adapter = Adapter(handler);

        var events = await Collect(adapter.GenerateAsync(Request(stream: true)));

        Assert.Equal(2, handler.Content!.ReadCount);
        Assert.Equal(3, events.Count);
        var text = Assert.IsType<AdapterTextDelta>(events[0]);
        var usage = Assert.IsType<AdapterUsage>(events[1]);
        var final = Assert.IsType<AdapterFinal>(events[2]);
        Assert.Equal("é", text.Text);
        AssertUsage(usage.Usage, 2, 1, 3);
        Assert.Equal("stop", final.FinishReason);
        AssertUsage(Assert.IsType<Usage>(final.Usage), 2, 1, 3);
        Assert.Same(usage.Usage, final.Usage);
    }

    [Fact]
    public async Task Finish_chunk_does_not_emit_final_until_done_and_sentinel_only_synthesizes_stop()
    {
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var finish = Encoding.UTF8.GetBytes("data: {\"choices\":[{\"delta\":{\"content\":\"kept\"}}]}\n\ndata: {\"choices\":[{\"delta\":{},\"finish_reason\":\"length\"}]}\n\n");
        var done = Encoding.UTF8.GetBytes("data: [DONE]\n\n");
        var handler = new ScriptedHandler(Response(HttpStatusCode.OK, "text/event-stream", new[] { finish, done }, release));
        await using var adapter = Adapter(handler);

        await using var enumerator = adapter.GenerateAsync(Request(stream: true)).GetAsyncEnumerator();
        Assert.True(await enumerator.MoveNextAsync());
        Assert.Equal("kept", Assert.IsType<AdapterTextDelta>(enumerator.Current).Text);
        var pendingFinal = enumerator.MoveNextAsync().AsTask();
        await handler.Content!.Blocked.Task.WaitAsync(TimeSpan.FromSeconds(1));
        Assert.False(pendingFinal.IsCompleted);
        release.TrySetResult();
        Assert.True(await pendingFinal);
        Assert.Equal("length", Assert.IsType<AdapterFinal>(enumerator.Current).FinishReason);

        var sentinelHandler = new ScriptedHandler(Response(HttpStatusCode.OK, "text/event-stream", Sse("[DONE]")));
        await using var sentinelAdapter = Adapter(sentinelHandler);
        var sentinelEvents = await Collect(sentinelAdapter.GenerateAsync(Request(stream: true)));
        var sentinelFinal = Assert.IsType<AdapterFinal>(Assert.Single(sentinelEvents));
        Assert.Equal("stop", sentinelFinal.FinishReason);
        Assert.Null(sentinelFinal.Usage);
    }

    [Fact]
    public async Task Eof_malformed_sse_and_raw_multibyte_overflow_preserve_typed_stream_protocol_failure()
    {
        var eof = new ScriptedHandler(Response(HttpStatusCode.OK, "text/event-stream", Sse("""{"choices":[{"delta":{"content":"partial"}}]}""")));
        await using var eofAdapter = Adapter(eof);
        var eofEvents = new List<AdapterEvent>();
        var eofFailure = await Assert.ThrowsAsync<StreamProtocolException>(async () =>
        {
            await foreach (var item in eofAdapter.GenerateAsync(Request(stream: true))) eofEvents.Add(item);
        });
        Assert.Equal("stream_protocol", eofFailure.Category);
        Assert.False(eofFailure.Retryable);
        Assert.Equal("stream", eofFailure.Phase);
        Assert.DoesNotContain(eofEvents, static item => item is AdapterFinal);

        var malformed = new ScriptedHandler(Response(HttpStatusCode.OK, "text/event-stream", Sse(
            """{"choices":[{"delta":{"content":"before"}}]}""",
            """{"choices":[{"delta":{},"finish_reason":"stop"}]}""",
            "{not-json}")));
        await using var malformedAdapter = Adapter(malformed);
        var malformedEvents = new List<AdapterEvent>();
        var malformedFailure = await Assert.ThrowsAsync<StreamProtocolException>(async () =>
        {
            await foreach (var item in malformedAdapter.GenerateAsync(Request(stream: true))) malformedEvents.Add(item);
        });
        Assert.Equal("stream_protocol", malformedFailure.Category);
        Assert.Contains(malformedEvents, static item => item is AdapterTextDelta delta && delta.Text == "before");
        Assert.DoesNotContain(malformedEvents, static item => item is AdapterFinal);

        var multibyte = new string('é', 20);
        var payload = Sse($"{{\"choices\":[{{\"delta\":{{\"content\":\"{multibyte}\"}}}}]}}", """{"choices":[{"delta":{},"finish_reason":"stop"}]}""", "[DONE]");
        Assert.True(Encoding.UTF8.GetByteCount(payload) > 147);
        Assert.True(CountRunes(payload) <= 147);
        var bytes = Encoding.UTF8.GetBytes(payload);
        var splitAt = Enumerable.Range(77, 4).First(index => (bytes[index] & 0xc0) != 0x80);
        var firstChunk = bytes[..splitAt];
        var secondChunk = bytes[splitAt..];
        Assert.True(firstChunk.Length <= 80 && secondChunk.Length <= 80);
        var overflow = new ScriptedHandler(Response(HttpStatusCode.OK, "text/event-stream", firstChunk, secondChunk));
        await using var overflowAdapter = Adapter(overflow);
        var overflowEvents = new List<AdapterEvent>();
        var overflowFailure = await Assert.ThrowsAsync<StreamProtocolException>(async () =>
        {
            await foreach (var item in overflowAdapter.GenerateAsync(Request(stream: true, maxResponseBytes: 147))) overflowEvents.Add(item);
        });
        Assert.Equal("stream_protocol", overflowFailure.Category);
        Assert.False(overflowFailure.Retryable);
        Assert.Equal("stream", overflowFailure.Phase);
        Assert.DoesNotContain(overflowEvents, static item => item is AdapterFinal);
    }

    [Fact]
    public async Task Status_503_maps_to_provider_unavailable_with_actual_status()
    {
        var handler = new ScriptedHandler(Response(HttpStatusCode.ServiceUnavailable, "application/json", """{"error":{"message":"unavailable"}}"""));
        await using var adapter = Adapter(handler);

        var failure = await Assert.ThrowsAsync<ProviderUnavailableException>(() => Collect(adapter.GenerateAsync(Request(stream: true))));

        Assert.Equal("provider_unavailable", failure.Category);
        Assert.True(failure.Retryable);
        Assert.Equal("generate", failure.Phase);
        Assert.Equal(503, failure.HttpStatus);
    }

    [Fact]
    public async Task Terminal_missing_location_307_with_error_body_uses_buffered_completion_parser()
    {
        var handler = new ScriptedHandler(Response((HttpStatusCode)307, "application/json", """{"error":{"message":"redirect"}}"""));
        await using var adapter = Adapter(handler);

        var failure = await Assert.ThrowsAsync<StreamProtocolException>(() => Collect(adapter.GenerateAsync(Request(stream: false))));

        Assert.Single(handler.Requests);
        Assert.Equal("stream_protocol", failure.Category);
        Assert.False(failure.Retryable);
        Assert.Equal("stream", failure.Phase);
    }

    [Fact]
    public async Task Terminal_missing_location_307_with_completion_body_yields_buffered_events()
    {
        var handler = new ScriptedHandler(Response((HttpStatusCode)307, "application/json", """
            {"choices":[{"message":{"content":"hello"},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}
            """));
        await using var adapter = Adapter(handler);

        var events = await Collect(adapter.GenerateAsync(Request(stream: false)));

        Assert.Single(handler.Requests);
        Assert.Collection(events,
            item => Assert.Equal("hello", Assert.IsType<AdapterTextDelta>(item).Text),
            item => AssertUsage(Assert.IsType<AdapterUsage>(item).Usage, 2, 1, 3),
            item =>
            {
                var final = Assert.IsType<AdapterFinal>(item);
                Assert.Equal("stop", final.FinishReason);
                AssertUsage(Assert.IsType<Usage>(final.Usage), 2, 1, 3);
            });
    }

    [Fact]
    public async Task Stream_disposal_io_failure_preserves_emitted_events_and_actual_native_inner_while_cleaning_resources()
    {
        var native = new IOException("fixture stream disposal failed");
        var response = TrackedResponse(
            HttpStatusCode.OK,
            "text/event-stream",
            Sse(
                """{"choices":[{"delta":{"content":"delivered"}}]}""",
                """{"choices":[{"delta":{},"finish_reason":"stop"}]}""",
                "[DONE]"),
            disposeException: native);
        var handler = new ScriptedHandler(response);
        var adapter = Adapter(handler);
        var events = new List<AdapterEvent>();

        var failure = await Assert.ThrowsAsync<TransportException>(async () =>
        {
            await foreach (var item in adapter.GenerateAsync(Request(stream: true))) events.Add(item);
        });

        Assert.Collection(events,
            item => Assert.Equal("delivered", Assert.IsType<AdapterTextDelta>(item).Text),
            item => Assert.Equal("stop", Assert.IsType<AdapterFinal>(item).FinishReason));
        Assert.Equal("transport", failure.Category);
        Assert.True(failure.Retryable);
        Assert.Equal("stream", failure.Phase);
        Assert.Same(native, failure.NativeInner);
        await adapter.DisposeAsync();
        Assert.True(response.Disposed);
        Assert.True(handler.Content!.Disposed);
        Assert.True(handler.Content.StreamDisposed);
        Assert.True(handler.Disposed);

        var earlyNative = new IOException("fixture early stream disposal failed");
        var earlyResponse = TrackedResponse(
            HttpStatusCode.OK,
            "text/event-stream",
            Sse("""{"choices":[{"delta":{"content":"early"}}]}""", "[DONE]"),
            disposeException: earlyNative);
        var earlyHandler = new ScriptedHandler(earlyResponse);
        var earlyAdapter = Adapter(earlyHandler);
        var earlyEnumerator = earlyAdapter.GenerateAsync(Request(stream: true)).GetAsyncEnumerator();

        Assert.True(await earlyEnumerator.MoveNextAsync());
        Assert.Equal("early", Assert.IsType<AdapterTextDelta>(earlyEnumerator.Current).Text);
        var earlyFailure = await Assert.ThrowsAsync<TransportException>(() => earlyEnumerator.DisposeAsync().AsTask());
        Assert.Equal("transport", earlyFailure.Category);
        Assert.Equal("stream", earlyFailure.Phase);
        Assert.Same(earlyNative, earlyFailure.NativeInner);
        await earlyAdapter.DisposeAsync();
        Assert.True(earlyResponse.Disposed);
        Assert.True(earlyHandler.Content!.Disposed);
        Assert.True(earlyHandler.Content.StreamDisposed);
        Assert.True(earlyHandler.Disposed);
    }

    [Fact]
    public async Task Iterator_is_lazy_and_caller_cancellation_interrupts_a_blocked_physical_read_and_cleans_resources()
    {
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var first = Encoding.UTF8.GetBytes("data: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}]}\n\n");
        var blocked = Encoding.UTF8.GetBytes("data: [DONE]\n\n");
        var response = TrackedResponse(HttpStatusCode.OK, "text/event-stream", new[] { first, blocked }, release);
        var handler = new ScriptedHandler(response);
        var adapter = Adapter(handler);
        using var cancellation = new CancellationTokenSource();
        var sequence = adapter.GenerateAsync(Request(stream: true), cancellation.Token);

        await using (var untouched = sequence.GetAsyncEnumerator(cancellation.Token))
        {
            Assert.Empty(handler.Requests);
            Assert.Equal(0, handler.SendCount);
            Assert.Equal(0, handler.Content!.ReadCount);
        }

        await using (var active = sequence.GetAsyncEnumerator(cancellation.Token))
        {
            Assert.True(await active.MoveNextAsync());
            Assert.True(handler.LastToken.CanBeCanceled);
            Assert.True(handler.Content!.ReadCount > 0);
            var blockedRead = active.MoveNextAsync().AsTask();
            await handler.Content.Blocked.Task.WaitAsync(TimeSpan.FromSeconds(1));
            cancellation.Cancel();
            var propagated = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => blockedRead);
            Assert.Same(handler.Content.CaughtReadCancellation, propagated);
            Assert.True(handler.Content.LastReadToken.CanBeCanceled);
        }

        await adapter.DisposeAsync();
        Assert.True(response.Disposed);
        Assert.True(handler.Disposed);
        Assert.True(handler.Content!.Disposed);
        Assert.True(handler.Content.StreamDisposed);
    }

    private static OpenAIChatAdapter Adapter(ScriptedHandler handler) => new(new Uri("https://fixture.invalid/v1"), "fixture-token", new Dictionary<string, string> { ["x-fixture"] = "transport" }, handler);

    private static WireRequest Request(bool stream, Sampling? sampling = null, int maxResponseBytes = 1_048_576) =>
        new("fixture-model", [new Message("user", [new Text("Hel"), new Text("lo.")])], sampling ?? new Sampling(), stream: stream, timeoutS: 120, maxResponseBytes: maxResponseBytes);

    private static async Task<List<AdapterEvent>> Collect(IAsyncEnumerable<AdapterEvent> source)
    {
        var items = new List<AdapterEvent>();
        await foreach (var item in source) items.Add(item);
        return items;
    }

    private static void AssertUsage(Usage usage, long input, long output, long total)
    {
        Assert.Equal(input, usage.InputTokens);
        Assert.Equal(output, usage.OutputTokens);
        Assert.Equal(total, usage.TotalTokens);
        Assert.Null(usage.CacheReadTokens);
        Assert.Null(usage.CacheWriteTokens);
        Assert.Null(usage.ReasoningTokens);
    }

    private static HttpResponseMessage Response(HttpStatusCode status, string contentType, string body) => Response(status, contentType, Encoding.UTF8.GetBytes(body));
    private static HttpResponseMessage Response(HttpStatusCode status, string contentType, params byte[][] chunks) => Response(status, contentType, (IReadOnlyList<byte[]>)chunks, null);
    private static HttpResponseMessage Response(HttpStatusCode status, string contentType, IReadOnlyList<byte[]> chunks, TaskCompletionSource? release) =>
        new(status) { Content = new ChunkedContent(chunks, release, contentType) };
    private static TrackingResponse TrackedResponse(HttpStatusCode status, string contentType, string body, IOException? disposeException = null) =>
        TrackedResponse(status, contentType, new[] { Encoding.UTF8.GetBytes(body) }, null, disposeException);
    private static TrackingResponse TrackedResponse(HttpStatusCode status, string contentType, IReadOnlyList<byte[]> chunks, TaskCompletionSource? release = null, IOException? disposeException = null) =>
        new(status) { Content = new ChunkedContent(chunks, release, contentType, disposeException) };
    private static string Sse(params string[] values) => string.Concat(values.Select(static value => "data: " + value + "\n\n"));

    private static int CountRunes(string value)
    {
        var count = 0;
        foreach (var _ in value.EnumerateRunes()) count++;
        return count;
    }

    private sealed record CapturedRequest(HttpMethod Method, string Path, IReadOnlyDictionary<string, string> Headers, JsonDocument Body);

    private sealed class TrackingResponse(HttpStatusCode status) : HttpResponseMessage(status)
    {
        internal bool Disposed { get; private set; }

        protected override void Dispose(bool disposing)
        {
            Disposed = true;
            base.Dispose(disposing);
        }
    }

    private sealed class ScriptedHandler : HttpMessageHandler
    {
        private readonly Queue<HttpResponseMessage> _responses;

        internal ScriptedHandler(params HttpResponseMessage[] responses)
        {
            _responses = new Queue<HttpResponseMessage>(responses);
            Content = responses.SingleOrDefault()?.Content as ChunkedContent;
        }

        internal List<CapturedRequest> Requests { get; } = [];
        internal ChunkedContent? Content { get; }
        internal int SendCount { get; private set; }
        internal CancellationToken LastToken { get; private set; }
        internal bool Disposed { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            SendCount++;
            LastToken = cancellationToken;
            if (_responses.Count == 0) throw new InvalidOperationException("Unexpected HTTP request.");
            var headers = request.Headers.Concat(request.Content!.Headers)
                .ToDictionary(static item => item.Key.ToLowerInvariant(), static item => string.Join(",", item.Value), StringComparer.Ordinal);
            var body = JsonDocument.Parse(await request.Content.ReadAsStringAsync(cancellationToken));
            Requests.Add(new CapturedRequest(request.Method, request.RequestUri!.AbsolutePath, headers, body));
            return _responses.Dequeue();
        }

        protected override void Dispose(bool disposing)
        {
            Disposed = true;
            base.Dispose(disposing);
        }
    }

    private sealed class ChunkedContent : HttpContent
    {
        private readonly IReadOnlyList<byte[]> _chunks;
        private readonly TaskCompletionSource? _release;

        private readonly IOException? _disposeException;

        internal ChunkedContent(IReadOnlyList<byte[]> chunks, TaskCompletionSource? release, string contentType, IOException? disposeException = null)
        {
            _chunks = chunks;
            _release = release;
            _disposeException = disposeException;
            Headers.ContentType = MediaTypeHeaderValue.Parse(contentType);
        }

        internal int ReadCount { get; private set; }
        internal bool Disposed { get; private set; }
        internal bool StreamDisposed { get; private set; }
        internal OperationCanceledException? CaughtReadCancellation { get; private set; }
        internal CancellationToken LastReadToken { get; private set; }
        internal TaskCompletionSource Blocked { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        protected override bool TryComputeLength(out long length) { length = 0; return false; }
        protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(new ChunkedReadStream(this, _chunks, _release, _disposeException));
        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) =>
            Task.FromResult<Stream>(new ChunkedReadStream(this, _chunks, _release, _disposeException));
        protected override async Task SerializeToStreamAsync(Stream stream, TransportContext? context)
        {
            foreach (var chunk in _chunks) await stream.WriteAsync(chunk).ConfigureAwait(false);
        }
        protected override void Dispose(bool disposing) { Disposed = true; base.Dispose(disposing); }
        internal void RecordRead() => ReadCount++;
        internal void RecordReadToken(CancellationToken token) => LastReadToken = token;
        internal void RecordReadCancellation(OperationCanceledException exception) => CaughtReadCancellation = exception;
        internal void RecordStreamDispose() => StreamDisposed = true;

        private sealed class ChunkedReadStream(ChunkedContent owner, IReadOnlyList<byte[]> chunks, TaskCompletionSource? release, IOException? disposeException) : Stream
        {
            private int _chunkIndex;
            private int _offset;
            public override bool CanRead => true;
            public override bool CanSeek => false;
            public override bool CanWrite => false;
            public override long Length => throw new NotSupportedException();
            public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
            public override void Flush() { }
            public override Task FlushAsync(CancellationToken cancellationToken) => Task.CompletedTask;
            public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
            public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
            public override void SetLength(long value) => throw new NotSupportedException();
            public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
            protected override void Dispose(bool disposing)
            {
                owner.RecordStreamDispose();
                base.Dispose(disposing);
                if (disposeException is not null) throw disposeException;
            }
            public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
            {
                if (_chunkIndex >= chunks.Count) return 0;
                owner.RecordReadToken(cancellationToken);
                if (release is not null && _chunkIndex == chunks.Count - 1)
                {
                    owner.Blocked.TrySetResult();
                    try
                    {
                        await release.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
                    }
                    catch (OperationCanceledException exception)
                    {
                        owner.RecordReadCancellation(exception);
                        throw;
                    }
                }

                owner.RecordRead();
                var current = chunks[_chunkIndex];
                var copied = Math.Min(buffer.Length, current.Length - _offset);
                current.AsMemory(_offset, copied).CopyTo(buffer);
                _offset += copied;
                if (_offset == current.Length) { _chunkIndex++; _offset = 0; }
                return copied;
            }
        }
    }
}
