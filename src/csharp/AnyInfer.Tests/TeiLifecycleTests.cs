using System.Net;
using System.Net.Sockets;
using System.Text;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Lifecycle controls for TEI's buffered HTTP operations.</summary>
public sealed class TeiLifecycleTests
{
    [Fact]
    public async Task Original_caller_cancellation_escapes_with_its_exact_token_and_joins_started_send()
    {
        var handler = new HeldHandler();
        await using var client = new AsyncClient([ProviderSettings.Of("tei", "http://tei.test", transport: handler)], ProviderRegistry.CreateDefault());
        using var caller = new CancellationTokenSource();

        var pending = client.EmbedAsync("input", target: "tei:model", cancellationToken: caller.Token);
        await handler.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        caller.Cancel();

        var failure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(caller.Token, failure.CancellationToken);
        Assert.True(handler.CancellationObserved.Task.IsCompleted);
    }

    [Fact]
    public async Task Typed_connection_refused_is_unavailable_while_other_io_is_transport_with_base_url_hint()
    {
        var refused = new ThrowingHandler(new HttpRequestException("Connection refused", new SocketException((int)SocketError.ConnectionRefused)));
        await using var refusedClient = new AsyncClient([ProviderSettings.Of("tei", "http://tei.test", transport: refused)], ProviderRegistry.CreateDefault());
        var refusedFailure = await Assert.ThrowsAsync<AllTargetsFailedException>(() => refusedClient.EmbedAsync("input", target: "tei:model"));
        var unavailable = Assert.IsType<ProviderUnavailableException>(refusedFailure.InnerException);
        Assert.Contains("base URL", unavailable.Hint ?? string.Empty, StringComparison.OrdinalIgnoreCase);

        var io = new ThrowingHandler(new IOException("broken pipe"));
        await using var ioClient = new AsyncClient([ProviderSettings.Of("tei", "http://tei.test", transport: io)], ProviderRegistry.CreateDefault());
        var outer = await Assert.ThrowsAsync<AllTargetsFailedException>(() => ioClient.EmbedAsync("input", target: "tei:model"));
        var failure = Assert.IsType<TransportException>(outer.InnerException);
        Assert.Equal("generate", failure.Phase);
        Assert.Same(io.Failure, failure.NativeInner);
    }

    [Fact]
    public async Task Adapter_disposes_owned_handler_once_but_preserves_pool_owned_handler()
    {
        var owned = new CountingHandler();
        await using (var adapter = Adapter(owned)) { }
        Assert.Equal(1, owned.DisposeCalls);

        var pooled = new CountingHandler();
        var settings = ProviderSettings.Of("tei", "http://tei.test", transport: pooled);
        var config = new ProviderConfig(settings, "tei", null).WithTransport(pooled, transportOwnedByPool: true);
        await using (var adapter = Assert.IsType<TeiAdapter>(TeiAdapter.Create(config, CancellationToken.None))) { }
        Assert.Equal(0, pooled.DisposeCalls);
        pooled.Dispose();
    }

    [Fact]
    public async Task Unknown_length_success_body_obeys_cap_while_large_error_is_classified_first()
    {
        var capped = new ContentHandler(HttpStatusCode.OK, new UnknownLengthContent("[[1,2,3]]"));
        await using var cappedAdapter = Adapter(capped);
        var capFailure = await Assert.ThrowsAsync<ProviderException>(() => cappedAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], maxResponseBytes: 1)).AsTask());
        Assert.Equal("validate", capFailure.Phase);

        var error = new ContentHandler(HttpStatusCode.Unauthorized, new UnknownLengthContent($$"""{"error":"{{new string('x', 2048)}}"}"""));
        await using var errorAdapter = Adapter(error);
        var auth = await Assert.ThrowsAsync<AuthException>(() => errorAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], maxResponseBytes: 1)).AsTask());
        Assert.Equal(401, auth.HttpStatus);
    }

    [Fact]
    public async Task Owned_timeout_wraps_as_transport_but_unrelated_operation_cancellation_escapes_unchanged()
    {
        var timeoutHandler = new HeldHandler();
        await using var timeoutAdapter = Adapter(timeoutHandler);
        var pending = timeoutAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], timeoutS: 0.01)).AsTask();
        await timeoutHandler.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var observedTimeoutToken = await timeoutHandler.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.True(observedTimeoutToken.IsCancellationRequested);
        var timeout = await Assert.ThrowsAsync<TransportException>(() => pending);
        Assert.Equal("generate", timeout.Phase);

        using var unrelated = new CancellationTokenSource();
        var planted = new OperationCanceledException(unrelated.Token);
        var unrelatedHandler = new ThrowingHandler(planted);
        await using var unrelatedAdapter = Adapter(unrelatedHandler);
        var observed = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => unrelatedAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());
        Assert.Same(planted, observed);
    }

    [Fact]
    public async Task Success_only_stream_cleanup_failure_escapes_after_all_owned_resources_are_attempted()
    {
        var content = new TrackingContent("[[1,2,3]]", streamDisposeFailure: new IOException("stream cleanup"));
        var response = new TrackingResponse(HttpStatusCode.OK, content);
        var handler = new ResponseHandler(response);
        var adapter = Adapter(handler);

        var failure = await Assert.ThrowsAsync<IOException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());

        Assert.Equal("stream cleanup", failure.Message);
        Assert.Equal(2, content.StreamDisposeCalls); // transport disposal, then response/content disposal
        Assert.Equal(1, content.DisposeCalls);
        Assert.Equal(1, response.DisposeCalls);
        await adapter.DisposeAsync();
        Assert.Equal(1, handler.DisposeCalls);
    }

    [Fact]
    public async Task Read_primary_failure_wins_over_stream_cleanup_and_all_owned_resources_are_attempted()
    {
        var readFailure = new IOException("read failed");
        var content = new TrackingContent("[]", readFailure, new IOException("stream cleanup"));
        var response = new TrackingResponse(HttpStatusCode.OK, content);
        var handler = new ResponseHandler(response);
        await using var adapter = Adapter(handler);

        var failure = await Assert.ThrowsAsync<TransportException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());

        Assert.Same(readFailure, failure.NativeInner);
        Assert.Equal(2, content.StreamDisposeCalls); // transport disposal, then response/content disposal
        Assert.Equal(1, content.DisposeCalls);
        Assert.Equal(1, response.DisposeCalls);
    }

    [Fact]
    public async Task Caller_cancellation_wins_over_stream_cleanup_and_joins_started_read()
    {
        var content = new TrackingContent("[]", blockReads: true, streamDisposeFailure: new IOException("stream cleanup"));
        var response = new TrackingResponse(HttpStatusCode.OK, content);
        var handler = new ResponseHandler(response);
        await using var adapter = Adapter(handler);
        using var caller = new CancellationTokenSource();

        var pending = adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"]), caller.Token).AsTask();
        await content.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        caller.Cancel();

        var failure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(caller.Token, failure.CancellationToken);
        Assert.True(content.ReadCancellationObserved.Task.IsCompleted);
        Assert.Equal(2, content.StreamDisposeCalls); // transport disposal, then response/content disposal
        Assert.Equal(1, content.DisposeCalls);
        Assert.Equal(1, response.DisposeCalls);
    }

    [Fact]
    public async Task Owned_timeout_wins_over_stream_cleanup_and_joins_started_read()
    {
        var content = new TrackingContent("[]", blockReads: true, streamDisposeFailure: new IOException("stream cleanup"));
        var response = new TrackingResponse(HttpStatusCode.OK, content);
        var handler = new ResponseHandler(response);
        await using var adapter = Adapter(handler);

        var pending = adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], timeoutS: 0.01)).AsTask();
        await content.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        await content.ReadCancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(5));

        var failure = await Assert.ThrowsAsync<TransportException>(() => pending);
        Assert.Equal("generate", failure.Phase);
        Assert.Equal(2, content.StreamDisposeCalls); // transport disposal, then response/content disposal
        Assert.Equal(1, content.DisposeCalls);
        Assert.Equal(1, response.DisposeCalls);
    }

    [Fact]
    public async Task Http_primary_failure_wins_over_stream_cleanup_and_all_owned_resources_are_attempted()
    {
        var content = new TrackingContent("{\"error\":\"down\"}", streamDisposeFailure: new IOException("stream cleanup"));
        var response = new TrackingResponse(HttpStatusCode.ServiceUnavailable, content);
        var handler = new ResponseHandler(response);
        await using var adapter = Adapter(handler);

        var failure = await Assert.ThrowsAsync<ProviderUnavailableException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());

        Assert.Equal(503, failure.HttpStatus);
        Assert.Equal(2, content.StreamDisposeCalls); // transport disposal, then response/content disposal
        Assert.Equal(1, content.DisposeCalls);
        Assert.Equal(1, response.DisposeCalls);
    }

    [Fact]
    public async Task Malformed_json_validation_failure_wins_over_stream_cleanup_and_disposes_response()
    {
        var content = new TrackingContent("{", streamDisposeFailure: new IOException("stream cleanup"));
        var response = new TrackingResponse(HttpStatusCode.OK, content);
        var handler = new ResponseHandler(response);
        await using var adapter = Adapter(handler);

        var failure = await Assert.ThrowsAsync<ProviderException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());

        Assert.Equal("validate", failure.Phase);
        Assert.False(failure.Retryable);
        Assert.IsType<FormatException>(failure.NativeInner);
        Assert.Equal(2, content.StreamDisposeCalls); // transport disposal, then response/content disposal
        Assert.Equal(1, content.DisposeCalls);
        Assert.Equal(1, response.DisposeCalls);
    }

    [Fact]
    public async Task Invalid_response_shape_validation_failure_wins_over_stream_cleanup_and_disposes_response()
    {
        var content = new TrackingContent("{}", streamDisposeFailure: new IOException("stream cleanup"));
        var response = new TrackingResponse(HttpStatusCode.OK, content);
        var handler = new ResponseHandler(response);
        await using var adapter = Adapter(handler);

        var failure = await Assert.ThrowsAsync<ProviderException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());

        Assert.Equal("validate", failure.Phase);
        Assert.False(failure.Retryable);
        Assert.Null(failure.NativeInner);
        Assert.Equal(2, content.StreamDisposeCalls); // transport disposal, then response/content disposal
        Assert.Equal(1, content.DisposeCalls);
        Assert.Equal(1, response.DisposeCalls);
    }

    private static TeiAdapter Adapter(HttpMessageHandler handler) => Assert.IsType<TeiAdapter>(TeiAdapter.Create(new ProviderConfig(ProviderSettings.Of("tei", "http://tei.test", transport: handler), "tei", null), CancellationToken.None));

    private sealed class HeldHandler : HttpMessageHandler
    {
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource<CancellationToken> CancellationObserved { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Entered.TrySetResult();
            try { await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken); }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                // The held operation itself observed the token, rather than a separate
                // registration whose callback ordering can race Task.Delay's callback.
                CancellationObserved.TrySetResult(cancellationToken);
                throw;
            }
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("[]", Encoding.UTF8, "application/json") };
        }
    }

    private sealed class ThrowingHandler(Exception failure) : HttpMessageHandler
    {
        internal Exception Failure { get; } = failure;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => Task.FromException<HttpResponseMessage>(Failure);
    }

    private sealed class CountingHandler : HttpMessageHandler
    {
        internal int DisposeCalls { get; private set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK));
        protected override void Dispose(bool disposing) { if (disposing) DisposeCalls++; base.Dispose(disposing); }
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
        internal int DisposeCalls { get; private set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => Task.FromResult(response);
        protected override void Dispose(bool disposing) { if (disposing) DisposeCalls++; base.Dispose(disposing); }
    }

    private sealed class TrackingResponse : HttpResponseMessage
    {
        internal int DisposeCalls { get; private set; }
        public TrackingResponse(HttpStatusCode status, HttpContent content) : base(status) => Content = content;
        protected override void Dispose(bool disposing) { if (disposing) DisposeCalls++; base.Dispose(disposing); }
    }

    private sealed class TrackingContent : HttpContent
    {
        private readonly byte[] _bytes;
        private readonly Exception? _readFailure;
        private readonly Exception? _streamDisposeFailure;
        private readonly bool _blockReads;

        internal TrackingContent(string body, Exception? readFailure = null, Exception? streamDisposeFailure = null, bool blockReads = false)
        {
            _bytes = Encoding.UTF8.GetBytes(body);
            _readFailure = readFailure;
            _streamDisposeFailure = streamDisposeFailure;
            _blockReads = blockReads;
        }

        internal int StreamDisposeCalls { get; private set; }
        internal int DisposeCalls { get; private set; }
        internal TaskCompletionSource ReadStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource ReadCancellationObserved { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        protected override bool TryComputeLength(out long length) { length = _bytes.Length; return true; }
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => stream.WriteAsync(_bytes).AsTask();
        protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(new TrackingStream(this));
        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) => Task.FromResult<Stream>(new TrackingStream(this));
        protected override void Dispose(bool disposing) { if (disposing) DisposeCalls++; base.Dispose(disposing); }

        private sealed class TrackingStream(TrackingContent owner) : MemoryStream(owner._bytes, writable: false)
        {
            public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
            {
                owner.ReadStarted.TrySetResult();
                if (owner._blockReads)
                {
                    try { await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken); }
                    catch (OperationCanceledException) { owner.ReadCancellationObserved.TrySetResult(); throw; }
                }
                if (owner._readFailure is not null) throw owner._readFailure;
                return await base.ReadAsync(buffer, cancellationToken);
            }

            protected override void Dispose(bool disposing)
            {
                if (disposing) owner.StreamDisposeCalls++;
                base.Dispose(disposing);
                if (disposing && owner._streamDisposeFailure is not null) throw owner._streamDisposeFailure;
            }
        }
    }
}
