using System.Net;
using System.Net.Http.Headers;
using System.Text;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Independent completion controls for native OpenAI-compatible SSE streams.</summary>
public sealed class OpenAISseCompletionTests
{
    [Theory]
    [InlineData("data: {\"choices\":[{\"delta\":{\"content\":\"final\"},\"finish_reason\":\"length\"}]}", "final", "length")]
    [InlineData("data: {\"choices\":[{\"delta\":{\"content\":\"line\"}}]}\n", "line", "stop")]
    [InlineData("data: {\"choices\":[{\"delta\":{\"content\":\"blank\"}}]}\n\n", "blank", "stop")]
    [InlineData("\n\n", "", "stop")]
    [InlineData(": keep-alive\n", "", "stop")]
    [InlineData(": keep-alive\n\n", "", "stop")]
    [InlineData("data: [DONE]", "", "stop")]
    [InlineData("", "", "stop")]
    public async Task Direct_adapter_clean_eof_flushes_final_record_or_synthesizes_stop(string body, string text, string finish)
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await using var adapter = Adapter(new ResponseHandler(Content(body)));

        var events = await Collect(adapter.GenerateAsync(Request(), deadline.Token), deadline.Token);

        Assert.Equal(text, string.Concat(events.OfType<AdapterTextDelta>().Select(static item => item.Text)));
        var final = Assert.IsType<AdapterFinal>(Assert.Single(events.OfType<AdapterFinal>()));
        Assert.Equal(finish, final.FinishReason);
        Assert.Null(final.Usage);
    }

    [Fact]
    public async Task Direct_adapter_handles_crlf_split_utf8_and_trailing_usage_at_clean_eof()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        var body = "data: {\"choices\":[{\"delta\":{\"content\":\"é\"}}]}\r\n\r\ndata: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\r\n\r\ndata: {\"choices\":[],\"usage\":{\"prompt_tokens\":2,\"completion_tokens\":1,\"total_tokens\":3}}";
        var bytes = Encoding.UTF8.GetBytes(body);
        var lead = Array.IndexOf(bytes, (byte)0xc3);
        Assert.True(lead >= 0);
        await using var adapter = Adapter(new ResponseHandler(Content(bytes[..(lead + 1)], bytes[(lead + 1)..])));

        var events = await Collect(adapter.GenerateAsync(Request(), deadline.Token), deadline.Token);

        Assert.Equal("é", Assert.IsType<AdapterTextDelta>(events[0]).Text);
        var usage = Assert.IsType<AdapterUsage>(events[1]).Usage;
        Assert.Equal(3, usage.TotalTokens);
        var final = Assert.IsType<AdapterFinal>(events[2]);
        Assert.Equal("stop", final.FinishReason);
        Assert.Same(usage, final.Usage);
    }

    [Fact]
    public async Task Direct_adapter_preserves_tool_and_logprob_events_when_final_record_arrives_at_eof()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        const string body = "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"call_1\",\"function\":{\"name\":\"lookup\",\"arguments\":\"{}\"}}]}}]}\n\ndata: {\"choices\":[{\"delta\":{},\"finish_reason\":\"tool_calls\",\"logprobs\":{\"content\":[{\"token\":\"x\",\"logprob\":-0.1}]}}]}";
        await using var adapter = Adapter(new ResponseHandler(Content(body)));

        var events = await Collect(adapter.GenerateAsync(ToolRequest(), deadline.Token), deadline.Token);

        var tool = Assert.IsType<AdapterToolCallDelta>(events[0]);
        Assert.Equal((0, "call_1", "lookup", "{}"), (tool.Index, tool.CallId, tool.Name, tool.ArgumentsFragment));
        var final = Assert.IsType<AdapterFinal>(events[^1]);
        Assert.Equal("tool_calls", final.FinishReason);
        Assert.Equal("x", Assert.Single(final.Logprobs).Token);
    }

    [Fact]
    public async Task Done_terminates_early_and_finish_bearing_stream_remains_open_until_eof()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        var released = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var first = Encoding.UTF8.GetBytes("data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"length\"}]}\n\n");
        var later = Encoding.UTF8.GetBytes("data: {not-json}\n\n");
        var content = new ChunkedContent([first, later], released);
        await using var adapter = Adapter(new ResponseHandler(content));
        await using var enumerator = adapter.GenerateAsync(Request(), deadline.Token).GetAsyncEnumerator(deadline.Token);

        var pending = enumerator.MoveNextAsync().AsTask();
        await content.Blocked.Task.WaitAsync(deadline.Token);
        Assert.False(pending.IsCompleted);
        released.TrySetResult();
        await Assert.ThrowsAsync<StreamProtocolException>(() => pending);

        await using var doneAdapter = Adapter(new ResponseHandler(Content(
            "data: [DONE]\n\ndata: {\"choices\":[{\"delta\":{\"content\":\"ignored\"}}]}\n\n")));
        var doneEvents = await Collect(doneAdapter.GenerateAsync(Request(), deadline.Token), deadline.Token);
        Assert.Equal("stop", Assert.IsType<AdapterFinal>(Assert.Single(doneEvents)).FinishReason);
    }

    [Fact]
    public async Task Trailing_malformed_json_invalid_utf8_and_read_io_remain_exact_typed_failures_without_final()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        foreach (var content in new HttpContent[]
        {
            Content("data: {not-json}"),
            Content(Encoding.UTF8.GetBytes("data: \""), [0xff]),
        })
        {
            await using var adapter = Adapter(new ResponseHandler(content));
            var events = new List<AdapterEvent>();
            var failure = await Assert.ThrowsAsync<StreamProtocolException>(async () =>
            {
                await foreach (var item in adapter.GenerateAsync(Request(), deadline.Token).WithCancellation(deadline.Token)) events.Add(item);
            });
            Assert.DoesNotContain(events, static item => item is AdapterFinal);
            Assert.Equal("stream_protocol", failure.Category);
            Assert.False(failure.Retryable);
            Assert.Equal("stream", failure.Phase);
        }

        var native = new IOException("read failed");
        await using var ioAdapter = Adapter(new ResponseHandler(new ThrowingContent(native)));
        var ioEvents = new List<AdapterEvent>();
        var ioFailure = await Assert.ThrowsAsync<TransportException>(async () =>
        {
            await foreach (var item in ioAdapter.GenerateAsync(Request(), deadline.Token).WithCancellation(deadline.Token)) ioEvents.Add(item);
        });
        Assert.DoesNotContain(ioEvents, static item => item is AdapterFinal);
        Assert.Equal("transport", ioFailure.Category);
        Assert.True(ioFailure.Retryable);
        Assert.Equal("stream", ioFailure.Phase);
        Assert.Same(native, ioFailure.NativeInner);
    }

    [Fact]
    public async Task Public_default_factory_streaming_path_reaches_clean_eof_result()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        var handler = new ResponseHandler(Content("data: {\"choices\":[{\"delta\":{\"content\":\"public\"},\"finish_reason\":\"stop\"}]}"));
        await using var client = new AsyncClient(
            [ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", "fixture-key", transport: handler)],
            ProviderRegistry.CreateDefault());

        var result = await client.StreamAsync("question", target: "openai-compat:fixture-model", cancellationToken: deadline.Token)
            .CollectAsync(deadline.Token);

        Assert.Equal("public", result.Text);
        Assert.Equal("stop", result.FinishReason);
    }

    private static OpenAIChatAdapter Adapter(HttpMessageHandler handler) =>
        new(new Uri("https://fixture.invalid/v1"), "fixture-key", null, handler);

    private static WireRequest Request() => new("fixture-model", [new Message("user", [new Text("question")])], new Sampling(), stream: true, timeoutS: 120);

    private static WireRequest ToolRequest() => new(
        "fixture-model",
        [new Message("user", [new Text("question")])],
        new Sampling(),
        stream: true,
        timeoutS: 120,
        tools: [new ToolSpec("lookup", "Look up a value", new AnyInfer.Json.JsonObject([]))]);

    private static async Task<List<AdapterEvent>> Collect(IAsyncEnumerable<AdapterEvent> source, CancellationToken cancellationToken)
    {
        var events = new List<AdapterEvent>();
        await foreach (var item in source.WithCancellation(cancellationToken)) events.Add(item);
        return events;
    }

    private static HttpContent Content(string value) => Content(Encoding.UTF8.GetBytes(value));
    private static HttpContent Content(params byte[][] chunks) => new ChunkedContent(chunks);

    private sealed class ResponseHandler(HttpContent content) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var response = new HttpResponseMessage(HttpStatusCode.OK) { Content = content };
            response.Content.Headers.ContentType = MediaTypeHeaderValue.Parse("text/event-stream");
            return Task.FromResult(response);
        }
    }

    private sealed class ChunkedContent(IReadOnlyList<byte[]> chunks, TaskCompletionSource? release = null) : HttpContent
    {
        internal TaskCompletionSource Blocked { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        protected override bool TryComputeLength(out long length) { length = 0; return false; }
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => Task.CompletedTask;
        protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(new ChunkedStream(chunks, release, Blocked));
        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) => CreateContentReadStreamAsync();
    }

    private sealed class ThrowingContent(IOException error) : HttpContent
    {
        protected override bool TryComputeLength(out long length) { length = 0; return false; }
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => Task.CompletedTask;
        protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(new ThrowingStream(error));
        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) => CreateContentReadStreamAsync();
    }

    private sealed class ChunkedStream(IReadOnlyList<byte[]> chunks, TaskCompletionSource? release, TaskCompletionSource blocked) : Stream
    {
        private int _index;
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
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            if (_index >= chunks.Count) return 0;
            if (release is not null && _index == chunks.Count - 1)
            {
                blocked.TrySetResult();
                await release.Task.WaitAsync(cancellationToken);
            }
            var chunk = chunks[_index++];
            chunk.CopyTo(buffer);
            return chunk.Length;
        }
    }

    private sealed class ThrowingStream(IOException error) : Stream
    {
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override void Flush() { }
        public override int Read(byte[] buffer, int offset, int count) => throw error;
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default) => ValueTask.FromException<int>(error);
    }
}
