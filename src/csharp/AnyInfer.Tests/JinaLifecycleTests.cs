using System.Net;
using System.Net.Sockets;
using System.Text;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Lifecycle, cancellation, bounded-read, and cleanup controls for Jina.</summary>
public sealed class JinaLifecycleTests
{
    [Fact]
    public async Task Discovery_is_empty_without_send_and_health_treats_any_status_as_reachable()
    {
        var discovery = new CountingHandler();
        await using (var adapter = Adapter(discovery))
        {
            Assert.Empty(await adapter.ListModelsAsync());
            Assert.Equal(0, discovery.SendCalls);
        }

        var handler = new ScriptHandler(new HttpResponseMessage(HttpStatusCode.NotFound), new HttpResponseMessage(HttpStatusCode.Unauthorized));
        await using var client = Client(handler);
        Assert.True((await client.HealthAsync("jina")).Ok);
        Assert.True((await client.HealthAsync("jina")).Ok);
        Assert.All(handler.Paths, static path => Assert.Equal("/base/v1/models", path));
    }

    [Fact]
    public async Task Health_is_headers_only_and_reports_bounded_redacted_transport_detail()
    {
        var response = new HttpResponseMessage(HttpStatusCode.NotFound) { Content = new StringContent(new string('x', 70_000), Encoding.UTF8, "text/plain") };
        var handler = new ScriptHandler(response);
        await using (var adapter = Adapter(handler, new Dictionary<string, string> { ["Content-Type"] = "application/vnd.jina-health+json" }))
        {
            Assert.True((await adapter.HealthAsync()).Ok);
            Assert.Equal("application/vnd.jina-health+json", Assert.Single(handler.ContentTypes));
        }

        Redaction.RegisterSecret("fixture-secret");
        var failed = new ThrowingHandler(new TransportException("failed", detail: "fixture-secret " + new string('x', 500)));
        await using var failedAdapter = Adapter(failed);
        var health = await failedAdapter.HealthAsync();
        Assert.False(health.Ok);
        Assert.Equal(200, health.Detail!.Length);
        Assert.DoesNotContain("fixture-secret", health.Detail, StringComparison.Ordinal);
        Assert.Contains("[redacted]", health.Detail, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Caller_cancellation_is_causal_and_joins_started_send()
    {
        var handler = new HeldHandler();
        await using var client = Client(handler);
        using var caller = new CancellationTokenSource();
        var pending = client.EmbedAsync("input", target: "jina:model", cancellationToken: caller.Token);
        await handler.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        caller.Cancel();
        var cancellation = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(caller.Token, cancellation.CancellationToken);
        Assert.True(handler.CancellationObserved.Task.IsCompleted);
    }

    [Fact]
    public async Task Health_propagates_the_exact_caller_token()
    {
        var held = new HeldHandler();
        await using var adapter = Adapter(held);
        using var caller = new CancellationTokenSource();
        var pending = adapter.HealthAsync(caller.Token).AsTask();
        await held.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        caller.Cancel();
        var cancellation = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(caller.Token, cancellation.CancellationToken);
    }

    [Fact]
    public async Task Connection_refused_is_unavailable_and_other_io_is_transport()
    {
        var refused = new ThrowingHandler(new HttpRequestException("Connection refused", new SocketException((int)SocketError.ConnectionRefused)));
        await using var refusedClient = Client(refused);
        Assert.IsType<ProviderUnavailableException>((await Assert.ThrowsAsync<AllTargetsFailedException>(() => refusedClient.EmbedAsync("input", target: "jina:model"))).InnerException);

        var io = new IOException("broken pipe");
        await using var ioClient = Client(new ThrowingHandler(io));
        var failure = Assert.IsType<TransportException>((await Assert.ThrowsAsync<AllTargetsFailedException>(() => ioClient.EmbedAsync("input", target: "jina:model"))).InnerException);
        Assert.Same(io, failure.NativeInner);
    }

    [Fact]
    public async Task Owned_handler_is_disposed_once_but_pool_owned_handler_is_preserved()
    {
        var owned = new CountingHandler();
        await using (var adapter = Adapter(owned)) { }
        Assert.Equal(1, owned.DisposeCalls);

        var pooled = new CountingHandler();
        var settings = ProviderSettings.Of("jina", "http://jina.test/base/v1", transport: pooled);
        var config = new ProviderConfig(settings, "jina", null).WithTransport(pooled, transportOwnedByPool: true);
        await using (var adapter = Assert.IsType<JinaAdapter>(JinaAdapter.Create(config, CancellationToken.None))) { }
        Assert.Equal(0, pooled.DisposeCalls);
        pooled.Dispose();
    }

    [Fact]
    public async Task Actual_unknown_length_success_body_obeys_cap_but_status_precedes_cap()
    {
        var capped = new ContentHandler(HttpStatusCode.OK, new UnknownLengthContent("""{"data":[{"index":0,"embedding":[1]}]}"""));
        await using var cappedAdapter = Adapter(capped);
        Assert.Equal("validate", (await Assert.ThrowsAsync<ProviderException>(() => cappedAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], maxResponseBytes: 1)).AsTask())).Phase);

        var status = new ContentHandler(HttpStatusCode.Unauthorized, new UnknownLengthContent($$"""{"detail":"{{new string('x', 2048)}}"}"""));
        await using var statusAdapter = Adapter(status);
        Assert.Equal(401, (await Assert.ThrowsAsync<AuthException>(() => statusAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], maxResponseBytes: 1)).AsTask())).HttpStatus);
    }

    [Fact]
    public async Task Owned_timeout_is_transport_but_unrelated_operation_cancellation_escapes_unchanged()
    {
        var held = new HeldHandler();
        await using var timeoutAdapter = Adapter(held);
        var pending = timeoutAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], timeoutS: 0.01)).AsTask();
        await held.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.True((await held.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(5))).IsCancellationRequested);
        Assert.Equal("generate", (await Assert.ThrowsAsync<TransportException>(() => pending)).Phase);

        using var unrelated = new CancellationTokenSource();
        var planted = new OperationCanceledException(unrelated.Token);
        await using var unrelatedAdapter = Adapter(new ThrowingHandler(planted));
        Assert.Same(planted, await Assert.ThrowsAnyAsync<OperationCanceledException>(() => unrelatedAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask()));
    }

    [Theory]
    [InlineData("{")]
    [InlineData("{}")]
    public async Task Json_and_shape_primary_failures_survive_throwing_cleanup(string body)
    {
        var content = new TrackingContent(body, streamDisposeFailure: new IOException("cleanup"));
        var response = new TrackingResponse(HttpStatusCode.OK, content);
        await using var adapter = Adapter(new ResponseHandler(response));
        Assert.Equal("validate", (await Assert.ThrowsAsync<ProviderException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask())).Phase);
        Assert.Equal(2, content.StreamDisposeCalls);
        Assert.Equal(1, content.DisposeCalls);
        Assert.Equal(1, response.DisposeCalls);
    }

    [Fact]
    public async Task Read_and_status_failures_survive_throwing_cleanup_but_success_cleanup_escapes()
    {
        var read = new IOException("read failed");
        await using (var adapter = Adapter(new ResponseHandler(new TrackingResponse(HttpStatusCode.OK, new TrackingContent("{}", read, new IOException("cleanup"))))))
            Assert.Same(read, (await Assert.ThrowsAsync<TransportException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask())).NativeInner);

        await using (var adapter = Adapter(new ResponseHandler(new TrackingResponse(HttpStatusCode.ServiceUnavailable, new TrackingContent("""{"detail":"down"}""", streamDisposeFailure: new IOException("cleanup"))))))
            Assert.Equal(503, (await Assert.ThrowsAsync<ProviderUnavailableException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask())).HttpStatus);

        var successAdapter = Adapter(new ResponseHandler(new TrackingResponse(HttpStatusCode.OK, new TrackingContent("""{"data":[{"index":0,"embedding":[1]}]}""", streamDisposeFailure: new IOException("cleanup")))));
        Assert.Equal("cleanup", (await Assert.ThrowsAsync<IOException>(() => successAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask())).Message);
        await successAdapter.DisposeAsync();
    }

    private static AsyncClient Client(HttpMessageHandler handler) => new([ProviderSettings.Of("jina", "http://jina.test/base/v1", "fixture-secret", transport: handler)], ProviderRegistry.CreateDefault());
    private static JinaAdapter Adapter(HttpMessageHandler handler, IReadOnlyDictionary<string, string>? headers = null) => Assert.IsType<JinaAdapter>(JinaAdapter.Create(new ProviderConfig(ProviderSettings.Of("jina", "http://jina.test/base/v1", "fixture-secret", headers: headers, transport: handler), "jina", "fixture-secret"), CancellationToken.None));
    private sealed class HeldHandler : HttpMessageHandler { internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously); internal TaskCompletionSource<CancellationToken> CancellationObserved { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously); protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) { Entered.TrySetResult(); try { await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken); } catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { CancellationObserved.TrySetResult(cancellationToken); throw; } return new HttpResponseMessage(HttpStatusCode.OK); } }
    private sealed class ThrowingHandler(Exception failure) : HttpMessageHandler { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => Task.FromException<HttpResponseMessage>(failure); }
    private sealed class CountingHandler : HttpMessageHandler { internal int SendCalls { get; private set; } internal int DisposeCalls { get; private set; } protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) { SendCalls++; return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)); } protected override void Dispose(bool disposing) { if (disposing) DisposeCalls++; base.Dispose(disposing); } }
    private sealed class ScriptHandler(params HttpResponseMessage[] responses) : HttpMessageHandler { private readonly Queue<HttpResponseMessage> _responses = new(responses); internal List<string> Paths { get; } = []; internal List<string?> ContentTypes { get; } = []; protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) { Paths.Add(request.RequestUri!.AbsolutePath); ContentTypes.Add(request.Content?.Headers.ContentType?.ToString()); return Task.FromResult(_responses.Dequeue()); } }
    private sealed class ContentHandler(HttpStatusCode status, HttpContent content) : HttpMessageHandler { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => Task.FromResult(new HttpResponseMessage(status) { Content = content }); }
    private sealed class UnknownLengthContent(string body) : HttpContent { private readonly byte[] _bytes = Encoding.UTF8.GetBytes(body); protected override bool TryComputeLength(out long length) { length = 0; return false; } protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => stream.WriteAsync(_bytes).AsTask(); }
    private sealed class ResponseHandler(HttpResponseMessage response) : HttpMessageHandler { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => Task.FromResult(response); }
    private sealed class TrackingResponse : HttpResponseMessage { internal int DisposeCalls { get; private set; } internal TrackingResponse(HttpStatusCode status, HttpContent content) : base(status) => Content = content; protected override void Dispose(bool disposing) { if (disposing) DisposeCalls++; base.Dispose(disposing); } }
    private sealed class TrackingContent : HttpContent { private readonly byte[] _bytes; private readonly Exception? _readFailure; private readonly Exception? _streamDisposeFailure; internal TrackingContent(string body, Exception? readFailure = null, Exception? streamDisposeFailure = null) { _bytes = Encoding.UTF8.GetBytes(body); _readFailure = readFailure; _streamDisposeFailure = streamDisposeFailure; } internal int StreamDisposeCalls { get; private set; } internal int DisposeCalls { get; private set; } protected override bool TryComputeLength(out long length) { length = _bytes.Length; return true; } protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => stream.WriteAsync(_bytes).AsTask(); protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(new TrackingStream(this)); protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) => Task.FromResult<Stream>(new TrackingStream(this)); protected override void Dispose(bool disposing) { if (disposing) DisposeCalls++; base.Dispose(disposing); } private sealed class TrackingStream(TrackingContent owner) : MemoryStream(owner._bytes, writable: false) { public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default) { if (owner._readFailure is not null) throw owner._readFailure; return base.ReadAsync(buffer, cancellationToken); } protected override void Dispose(bool disposing) { if (disposing) owner.StreamDisposeCalls++; base.Dispose(disposing); if (disposing && owner._streamDisposeFailure is not null) throw owner._streamDisposeFailure; } } }
}
