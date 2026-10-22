using System.Net;
using System.Net.Sockets;
using System.Text;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Lifecycle, cancellation, bounded-read, and cleanup controls for Voyage.</summary>
public sealed class VoyageLifecycleTests
{
    [Fact]
    public async Task Discovery_is_empty_without_send_and_health_accepts_404_and_401_as_reachable()
    {
        var discovery = new CountingHandler();
        await using (var adapter = Adapter(discovery))
        {
            Assert.Empty(await adapter.ListModelsAsync());
            Assert.Equal(0, discovery.SendCalls);
        }

        var handler = new ScriptHandler(
            new HttpResponseMessage(HttpStatusCode.NotFound),
            new HttpResponseMessage(HttpStatusCode.Unauthorized));
        await using var client = Client(handler);
        var missing = await client.HealthAsync("voyage");
        var denied = await client.HealthAsync("voyage");
        Assert.True(missing.Ok);
        Assert.True(denied.Ok);
        Assert.All(handler.Paths, static path => Assert.Equal("/base/v1/models", path));
    }

    [Fact]
    public async Task Health_treats_a_large_404_body_as_headers_only_reachability_and_preserves_configured_content_type()
    {
        var response = new HttpResponseMessage(HttpStatusCode.NotFound)
        {
            Content = new StringContent(new string('x', 70_000), Encoding.UTF8, "text/plain"),
        };
        var handler = new ScriptHandler(response);
        await using var adapter = Adapter(handler, new Dictionary<string, string> { ["Content-Type"] = "application/vnd.voyage-health+json" });

        var health = await adapter.HealthAsync();

        Assert.True(health.Ok);
        Assert.Equal("/base/v1/models", Assert.Single(handler.Paths));
        Assert.Equal("application/vnd.voyage-health+json", Assert.Single(handler.ContentTypes));
    }

    [Fact]
    public async Task Health_reports_bounded_redacted_transport_detail_and_propagates_the_caller_token()
    {
        Redaction.RegisterSecret("fixture-secret");
        var failed = new ThrowingHandler(new HttpRequestException("Bearer fixture-secret connection failed"));
        await using var failedAdapter = Adapter(failed);
        var health = await failedAdapter.HealthAsync();
        Assert.False(health.Ok);
        Assert.DoesNotContain("fixture-secret", health.Detail ?? string.Empty, StringComparison.Ordinal);

        var planted = new ThrowingHandler(new TransportException("transport failed", detail: "fixture-secret " + new string('x', 500)));
        await using var plantedAdapter = Adapter(planted);
        var bounded = await plantedAdapter.HealthAsync();
        Assert.False(bounded.Ok);
        Assert.Equal(200, bounded.Detail.Length);
        Assert.DoesNotContain("fixture-secret", bounded.Detail, StringComparison.Ordinal);
        Assert.Contains("[redacted]", bounded.Detail, StringComparison.Ordinal);

        var held = new HeldHandler();
        await using var cancellable = Adapter(held);
        using var caller = new CancellationTokenSource();
        var pending = cancellable.HealthAsync(caller.Token).AsTask();
        await held.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        caller.Cancel();
        var cancellation = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(caller.Token, cancellation.CancellationToken);
        Assert.True(held.CancellationObserved.Task.IsCompleted);
    }

    [Fact]
    public async Task Original_caller_cancellation_escapes_with_its_exact_token_and_joins_started_send()
    {
        var handler = new HeldHandler();
        await using var client = Client(handler);
        using var caller = new CancellationTokenSource();
        var pending = client.EmbedAsync("input", target: "voyage:model", cancellationToken: caller.Token);
        await handler.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        caller.Cancel();

        var failure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(caller.Token, failure.CancellationToken);
        Assert.True(handler.CancellationObserved.Task.IsCompleted);
    }

    [Fact]
    public async Task Typed_connection_refused_is_unavailable_while_other_io_is_transport()
    {
        var refused = new ThrowingHandler(new HttpRequestException("Connection refused", new SocketException((int)SocketError.ConnectionRefused)));
        await using var refusedClient = Client(refused);
        var refusedFailure = await Assert.ThrowsAsync<AllTargetsFailedException>(() => refusedClient.EmbedAsync("input", target: "voyage:model"));
        Assert.IsType<ProviderUnavailableException>(refusedFailure.InnerException);

        var io = new ThrowingHandler(new IOException("broken pipe"));
        await using var ioClient = Client(io);
        var outer = await Assert.ThrowsAsync<AllTargetsFailedException>(() => ioClient.EmbedAsync("input", target: "voyage:model"));
        var failure = Assert.IsType<TransportException>(outer.InnerException);
        Assert.Same(io.Failure, failure.NativeInner);
    }

    [Fact]
    public async Task Adapter_disposes_owned_handler_once_but_preserves_pool_owned_handler()
    {
        var owned = new CountingHandler();
        await using (var adapter = Adapter(owned)) { }
        Assert.Equal(1, owned.DisposeCalls);

        var pooled = new CountingHandler();
        var settings = ProviderSettings.Of("voyage", "http://voyage.test/base/v1", transport: pooled);
        var config = new ProviderConfig(settings, "voyage", null).WithTransport(pooled, transportOwnedByPool: true);
        await using (var adapter = Assert.IsType<VoyageAdapter>(VoyageAdapter.Create(config, CancellationToken.None))) { }
        Assert.Equal(0, pooled.DisposeCalls);
        pooled.Dispose();
    }

    [Fact]
    public async Task Unknown_length_success_body_obeys_cap_while_status_is_classified_first()
    {
        var capped = new ContentHandler(HttpStatusCode.OK, new UnknownLengthContent("""{"data":[{"index":0,"embedding":[1]}]}"""));
        await using var cappedAdapter = Adapter(capped);
        var cap = await Assert.ThrowsAsync<ProviderException>(() => cappedAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], maxResponseBytes: 1)).AsTask());
        Assert.Equal("validate", cap.Phase);

        var error = new ContentHandler(HttpStatusCode.Unauthorized, new UnknownLengthContent($$"""{"detail":"{{new string('x', 2048)}}"}"""));
        await using var errorAdapter = Adapter(error);
        Assert.Equal(401, (await Assert.ThrowsAsync<AuthException>(() => errorAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], maxResponseBytes: 1)).AsTask())).HttpStatus);
    }

    [Fact]
    public async Task Owned_timeout_wraps_as_transport_but_unrelated_operation_cancellation_escapes_unchanged()
    {
        var timeoutHandler = new HeldHandler();
        await using var timeoutAdapter = Adapter(timeoutHandler);
        var pending = timeoutAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], timeoutS: 0.01)).AsTask();
        await timeoutHandler.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var observed = await timeoutHandler.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.True(observed.IsCancellationRequested);
        Assert.Equal("generate", (await Assert.ThrowsAsync<TransportException>(() => pending)).Phase);

        using var unrelated = new CancellationTokenSource();
        var planted = new OperationCanceledException(unrelated.Token);
        await using var unrelatedAdapter = Adapter(new ThrowingHandler(planted));
        Assert.Same(planted, await Assert.ThrowsAnyAsync<OperationCanceledException>(() => unrelatedAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask()));
    }

    [Theory]
    [InlineData("{")]
    [InlineData("{}")]
    public async Task Json_and_shape_primary_failures_survive_throwing_stream_cleanup(string body)
    {
        var content = new TrackingContent(body, streamDisposeFailure: new IOException("cleanup"));
        var response = new TrackingResponse(HttpStatusCode.OK, content);
        await using var adapter = Adapter(new ResponseHandler(response));

        var failure = await Assert.ThrowsAsync<ProviderException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());
        Assert.Equal("validate", failure.Phase);
        Assert.Equal(2, content.StreamDisposeCalls);
        Assert.Equal(1, content.DisposeCalls);
        Assert.Equal(1, response.DisposeCalls);
    }

    [Fact]
    public async Task Read_and_503_primary_failures_survive_throwing_cleanup_but_success_cleanup_escapes()
    {
        var read = new IOException("read failed");
        var readContent = new TrackingContent("{}", read, new IOException("cleanup"));
        await using (var adapter = Adapter(new ResponseHandler(new TrackingResponse(HttpStatusCode.OK, readContent))))
        {
            Assert.Same(read, (await Assert.ThrowsAsync<TransportException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask())).NativeInner);
        }

        var unavailable = new TrackingContent("""{"detail":"down"}""", streamDisposeFailure: new IOException("cleanup"));
        await using (var adapter = Adapter(new ResponseHandler(new TrackingResponse(HttpStatusCode.ServiceUnavailable, unavailable))))
        {
            Assert.Equal(503, (await Assert.ThrowsAsync<ProviderUnavailableException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask())).HttpStatus);
        }

        var success = new TrackingContent("""{"data":[{"index":0,"embedding":[1]}]}""", streamDisposeFailure: new IOException("cleanup"));
        var successAdapter = Adapter(new ResponseHandler(new TrackingResponse(HttpStatusCode.OK, success)));
        Assert.Equal("cleanup", (await Assert.ThrowsAsync<IOException>(() => successAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask())).Message);
        await successAdapter.DisposeAsync();
    }

    private static AsyncClient Client(HttpMessageHandler handler) => new([ProviderSettings.Of("voyage", "http://voyage.test/base/v1", "fixture-secret", transport: handler)], ProviderRegistry.CreateDefault());
    private static VoyageAdapter Adapter(HttpMessageHandler handler, IReadOnlyDictionary<string, string>? headers = null) => Assert.IsType<VoyageAdapter>(VoyageAdapter.Create(new ProviderConfig(ProviderSettings.Of("voyage", "http://voyage.test/base/v1", "fixture-secret", headers: headers, transport: handler), "voyage", "fixture-secret"), CancellationToken.None));

    private sealed class HeldHandler : HttpMessageHandler
    {
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource<CancellationToken> CancellationObserved { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Entered.TrySetResult();
            try { await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken); }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { CancellationObserved.TrySetResult(cancellationToken); throw; }
            return new HttpResponseMessage(HttpStatusCode.OK);
        }
    }
    private sealed class ThrowingHandler(Exception failure) : HttpMessageHandler
    {
        internal Exception Failure { get; } = failure;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => Task.FromException<HttpResponseMessage>(Failure);
    }
    private sealed class CountingHandler : HttpMessageHandler
    {
        internal int SendCalls { get; private set; }
        internal int DisposeCalls { get; private set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) { SendCalls++; return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)); }
        protected override void Dispose(bool disposing) { if (disposing) DisposeCalls++; base.Dispose(disposing); }
    }
    private sealed class ScriptHandler(params HttpResponseMessage[] responses) : HttpMessageHandler
    {
        private readonly Queue<HttpResponseMessage> _responses = new(responses);
        internal List<string> Paths { get; } = [];
        internal List<string?> ContentTypes { get; } = [];
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) { Paths.Add(request.RequestUri!.AbsolutePath); ContentTypes.Add(request.Content?.Headers.ContentType?.ToString()); return Task.FromResult(_responses.Dequeue()); }
    }
    private sealed class ContentHandler(HttpStatusCode status, HttpContent content) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => Task.FromResult(new HttpResponseMessage(status) { Content = content });
    }
    private sealed class UnknownLengthContent(string body) : HttpContent
    {
        private readonly byte[] _bytes = Encoding.UTF8.GetBytes(body);
        protected override bool TryComputeLength(out long length) { length = 0; return false; }
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => stream.WriteAsync(_bytes).AsTask();
    }
    private sealed class ResponseHandler(HttpResponseMessage response) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => Task.FromResult(response);
    }
    private sealed class TrackingResponse : HttpResponseMessage
    {
        internal int DisposeCalls { get; private set; }
        internal TrackingResponse(HttpStatusCode status, HttpContent content) : base(status) => Content = content;
        protected override void Dispose(bool disposing) { if (disposing) DisposeCalls++; base.Dispose(disposing); }
    }
    private sealed class TrackingContent : HttpContent
    {
        private readonly byte[] _bytes;
        private readonly Exception? _readFailure;
        private readonly Exception? _streamDisposeFailure;
        internal TrackingContent(string body, Exception? readFailure = null, Exception? streamDisposeFailure = null) { _bytes = Encoding.UTF8.GetBytes(body); _readFailure = readFailure; _streamDisposeFailure = streamDisposeFailure; }
        internal int StreamDisposeCalls { get; private set; }
        internal int DisposeCalls { get; private set; }
        protected override bool TryComputeLength(out long length) { length = _bytes.Length; return true; }
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => stream.WriteAsync(_bytes).AsTask();
        protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(new TrackingStream(this));
        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) => Task.FromResult<Stream>(new TrackingStream(this));
        protected override void Dispose(bool disposing) { if (disposing) DisposeCalls++; base.Dispose(disposing); }
        private sealed class TrackingStream(TrackingContent owner) : MemoryStream(owner._bytes, writable: false)
        {
            public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default) { if (owner._readFailure is not null) throw owner._readFailure; return base.ReadAsync(buffer, cancellationToken); }
            protected override void Dispose(bool disposing) { if (disposing) owner.StreamDisposeCalls++; base.Dispose(disposing); if (disposing && owner._streamDisposeFailure is not null) throw owner._streamDisposeFailure; }
        }
    }
}
