using System.Net;
using System.Net.Http;
using System.Text;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Transport-level causal controls for the internal redirect sender.</summary>
public sealed class RedirectTransportTests
{
    [Fact]
    public async Task Unsafe_crossing_strips_configured_credentials_and_stays_stripped_when_it_returns()
    {
        var handler = new RedirectingHandler(
            new Uri("https://second.example/next"),
            new Uri("https://first.example/return"));
        using var client = new HttpClient(handler, disposeHandler: true);
        var sender = new ProviderHttpRedirects(client);
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        using var exchange = await sender.SendAsync(
            new Uri("https://first.example/start"),
            HttpMethod.Post,
            context => Request(context, configured: true),
            "generate",
            budget.Token);

        Assert.Equal(HttpStatusCode.OK, exchange.Response.StatusCode);
        Assert.Equal(3, handler.Requests.Count);
        Assert.True(handler.Requests[0].Headers.Contains("Authorization"));
        Assert.False(handler.Requests[1].Headers.Contains("Authorization"));
        Assert.False(handler.Requests[2].Headers.Contains("Authorization"));
        Assert.False(handler.Requests[2].Headers.Contains("X-Configured"));
        Assert.False(handler.Requests[2].Headers.Contains("Accept"));
        Assert.Equal("first.example", handler.Requests[0].Headers.Host);
        Assert.Null(handler.Requests[1].Headers.Host);
        Assert.Null(handler.Requests[2].Headers.Host);
        Assert.Equal(new Uri("https://second.example/next"), handler.Requests[1].RequestUri);
        Assert.Equal(new Uri("https://first.example/return"), handler.Requests[2].RequestUri);
    }

    [Theory]
    [InlineData(HttpStatusCode.Moved)]
    [InlineData(HttpStatusCode.Redirect)]
    [InlineData(HttpStatusCode.RedirectMethod)]
    public async Task Post_rewrite_discards_body_and_old_framing(HttpStatusCode status)
    {
        var handler = new RedirectingHandler(new Uri("https://first.example/next"), status);
        using var client = new HttpClient(handler, disposeHandler: true);
        var sender = new ProviderHttpRedirects(client);

        using var exchange = await sender.SendAsync(
            new Uri("https://first.example/start"), HttpMethod.Post,
            context => Request(context, configured: false), "generate", CancellationToken.None);

        Assert.Equal(HttpMethod.Get, handler.Requests[1].Method);
        Assert.Null(handler.Requests[1].Content);
        Assert.True(handler.Requests[1].Content?.Headers.ContentLength is null or 0);
        Assert.Empty(handler.Requests[1].Headers.TransferEncoding);
        Assert.NotSame(handler.Requests[0], handler.Requests[1]);
    }

    [Theory]
    [InlineData(HttpStatusCode.TemporaryRedirect)]
    [InlineData(HttpStatusCode.PermanentRedirect)]
    public async Task Post_preserving_redirect_rebuilds_a_distinct_byte_identical_body(HttpStatusCode status)
    {
        var handler = new RedirectingHandler(new Uri("https://first.example/next"), status);
        using var client = new HttpClient(handler, disposeHandler: true);
        var sender = new ProviderHttpRedirects(client);

        using var exchange = await sender.SendAsync(
            new Uri("https://first.example/start"), HttpMethod.Post,
            context => Request(context, configured: false), "generate", CancellationToken.None);

        Assert.Equal(HttpMethod.Post, handler.Requests[1].Method);
        Assert.Equal("{}", await handler.Requests[1].Content!.ReadAsStringAsync());
        Assert.NotSame(handler.Requests[0], handler.Requests[1]);
    }

    [Fact]
    public async Task Limit_fails_after_twenty_followed_redirects_without_a_twenty_second_dispatch()
    {
        var handler = new EndlessRedirectHandler();
        using var client = new HttpClient(handler, disposeHandler: true);
        var sender = new ProviderHttpRedirects(client);

        var failure = await Assert.ThrowsAsync<HttpRequestException>(() => sender.SendAsync(
            new Uri("https://first.example/start"), HttpMethod.Get,
            context => Request(context, configured: false), "generate", CancellationToken.None).AsTask());

        Assert.Equal(21, handler.SendCount);
        Assert.DoesNotContain("Location", failure.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Missing_location_is_terminal_and_userinfo_target_is_a_safe_failure()
    {
        using var missingClient = new HttpClient(new StaticHandler(new HttpResponseMessage(HttpStatusCode.Redirect)), true);
        var sender = new ProviderHttpRedirects(missingClient);
        using var terminal = await sender.SendAsync(new Uri("https://first.example/start"), HttpMethod.Get,
            context => Request(context, configured: false), "models", CancellationToken.None);
        Assert.Equal(HttpStatusCode.Redirect, terminal.Response.StatusCode);

        using var unsafeClient = new HttpClient(new StaticHandler(new HttpResponseMessage(HttpStatusCode.TemporaryRedirect)
        {
            Headers = { Location = new Uri("https://u:p@second.example/next") },
        }), true);
        sender = new ProviderHttpRedirects(unsafeClient);
        var error = await Assert.ThrowsAsync<HttpRequestException>(() => sender.SendAsync(
            new Uri("https://first.example/start"), HttpMethod.Get, context => Request(context, configured: false), "models", CancellationToken.None).AsTask());
        Assert.DoesNotContain("u:p", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Safe_default_port_upgrade_keeps_credentials_but_derives_the_destination_host()
    {
        var handler = new RedirectingHandler(new Uri("https://first.example:443/next"));
        using var client = new HttpClient(handler, true);
        var sender = new ProviderHttpRedirects(client);

        using var exchange = await sender.SendAsync(
            new Uri("http://first.example:80/start"), HttpMethod.Get,
            context => Request(context, configured: true), "models", CancellationToken.None);

        Assert.True(handler.Requests[1].Headers.Contains("Authorization"));
        Assert.Equal("first.example", handler.Requests[0].Headers.Host);
        Assert.Null(handler.Requests[1].Headers.Host);
        Assert.Equal(new Uri("https://first.example:443/next"), handler.Requests[1].RequestUri);
    }

    [Theory]
    [InlineData("http:/next", "http://first.example/next##prior", false)]
    [InlineData("https:?page=2", "https://first.example/?page=2##prior", false)]
    [InlineData("https:#fragment", "https://first.example/#fragment", false)]
    [InlineData("http:////next??q=1##frag", "http://first.example//next??q=1##frag", false)]
    [InlineData("https:////next", "https://first.example//next##prior", false)]
    [InlineData("https:??page=2", "https://first.example/??page=2##prior", false)]
    [InlineData("https:##fragment", "https://first.example/##fragment", false)]
    [InlineData("#", "https://first.example:8080/base??old=1##prior", true)]
    [InlineData("https:#", "https://first.example/##prior", false)]
    [InlineData("/next", "https://first.example:8080/next##prior", true)]
    [InlineData("https://first.example:8080//next", "https://first.example:8080//next##prior", true)]
    public async Task Raw_location_sender_controls_repair_hostless_references_and_preserve_only_safe_origin_state(
        string location, string expectedUri, bool preservesConfiguredState)
    {
        var handler = new RawLocationRecorderHandler(location);
        using var client = new HttpClient(handler, true);
        var sender = new ProviderHttpRedirects(client);
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        using var exchange = await sender.SendAsync(
            new Uri("https://first.example:8080/base??old=1##prior"), HttpMethod.Get,
            context => Request(context, configured: true), "models", budget.Token);

        Assert.Equal(HttpStatusCode.OK, exchange.Response.StatusCode);
        Assert.Equal(2, handler.Requests.Count);
        var initial = handler.Requests[0];
        var followed = handler.Requests[1];
        Assert.Equal("https://first.example:8080/base??old=1##prior", initial.RequestUri.AbsoluteUri);
        Assert.True(initial.HasAuthorization);
        Assert.Equal("first.example:8080", initial.Host);
        Assert.Equal(expectedUri, followed.RequestUri.AbsoluteUri);
        Assert.Equal(preservesConfiguredState, followed.HasAuthorization);
        Assert.Equal(preservesConfiguredState ? "first.example:8080" : null, followed.Host);
        Assert.Equal(2, handler.SendCount);
    }

    [Fact]
    public async Task Scheme_without_host_location_repairs_the_current_host_and_relative_query_inherits_fragment()
    {
        var handler = new RedirectingHandler(
            new Uri("http:/next", UriKind.RelativeOrAbsolute),
            new Uri("?page=2", UriKind.RelativeOrAbsolute));
        using var client = new HttpClient(handler, true);
        var sender = new ProviderHttpRedirects(client);

        using var exchange = await sender.SendAsync(
            new Uri("https://first.example/catalog/base#prior"), HttpMethod.Get,
            context => Request(context, configured: false), "models", CancellationToken.None);

        Assert.Equal("http://first.example/next", handler.Requests[1].RequestUri!.GetLeftPart(UriPartial.Path));
        Assert.Equal("http://first.example/next?page=2#prior", handler.Requests[2].RequestUri!.AbsoluteUri);
    }

    [Fact]
    public async Task Owned_handler_returns_each_loopback_hop_to_the_redirect_sender()
    {
        await using var fixture = LoopbackRedirectFixture.Start(
            new LoopbackRedirectResponse(307, "", "redirect-pending"),
            new LoopbackRedirectResponse(200, "{}"));
        // Different host spelling reaches the same loopback listener, while still proving
        // origin-bound headers do not travel to the redirected destination.
        var crossOrigin = new UriBuilder(fixture.OriginUri) { Host = "localhost", Path = "/next" }.Uri;
        fixture.ReplaceFirstLocation(crossOrigin.ToString());
        var settings = ProviderSettings.Of("openai-compat", fixture.OriginUri.ToString(), "key");
        var config = new ProviderConfig(settings, "openai-compat", "key");
        using var client = new HttpClient(ConnectionHandlerFactory.CreateOwned(config, CancellationToken.None), true);
        var sender = new ProviderHttpRedirects(client);
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        using var exchange = await sender.SendAsync(
            new Uri(fixture.OriginUri, "start"), HttpMethod.Post,
            context => Request(context, configured: true), "generate", budget.Token);

        Assert.Equal(HttpStatusCode.OK, exchange.Response.StatusCode);
        var requests = fixture.Requests.ToArray();
        Assert.Equal(2, requests.Length);
        Assert.Equal("POST /start HTTP/1.1", requests[0].RequestLine);
        Assert.Equal("POST /next HTTP/1.1", requests[1].RequestLine);
        Assert.DoesNotContain("Authorization", requests[1].Headers.Keys, StringComparer.OrdinalIgnoreCase);
        Assert.DoesNotContain("X-Configured", requests[1].Headers.Keys, StringComparer.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Concurrent_chains_keep_unsafe_origin_state_private()
    {
        var handler = new ConcurrentOriginHandler();
        using var client = new HttpClient(handler, true);
        var sender = new ProviderHttpRedirects(client);
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        var unsafeChain = sender.SendAsync(new Uri("https://first.example/a"), HttpMethod.Get,
            context => Request(context, configured: true), "generate", budget.Token).AsTask();
        var safeChain = sender.SendAsync(new Uri("https://first.example/b"), HttpMethod.Get,
            context => Request(context, configured: true), "generate", budget.Token).AsTask();
        await handler.BothInitial.Task.WaitAsync(TimeSpan.FromSeconds(15), budget.Token);
        handler.Release.TrySetResult();
        var exchanges = await Task.WhenAll(unsafeChain, safeChain).WaitAsync(TimeSpan.FromSeconds(15), budget.Token);
        foreach (var exchange in exchanges) exchange.Dispose();

        var unsafeHeaders = Assert.Single(handler.UnsafeHopHeaders);
        var safeHeaders = Assert.Single(handler.SafeHopHeaders);
        Assert.False(unsafeHeaders.Contains("Authorization"));
        Assert.True(safeHeaders.Contains("Authorization"));
    }

    [Fact]
    public async Task Caller_and_foreign_cancellation_preserve_the_original_operation_identity()
    {
        using var caller = new CancellationTokenSource();
        var callerHandler = new BlockingHandler();
        using var callerClient = new HttpClient(callerHandler, true);
        var sender = new ProviderHttpRedirects(callerClient);
        var pending = sender.SendAsync(new Uri("https://first.example/start"), HttpMethod.Get,
            context => Request(context, configured: false), "generate", caller.Token).AsTask();
        await callerHandler.Entered.Task.WaitAsync(TimeSpan.FromSeconds(15));
        caller.Cancel();
        var callerFailure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(caller.Token, callerFailure.CancellationToken);

        using var foreign = new CancellationTokenSource();
        using var foreignClient = new HttpClient(new ForeignCancellationHandler(foreign.Token), true);
        sender = new ProviderHttpRedirects(foreignClient);
        var foreignFailure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => sender.SendAsync(
            new Uri("https://first.example/start"), HttpMethod.Get, context => Request(context, configured: false), "generate", CancellationToken.None).AsTask());
        Assert.Equal(foreign.Token, foreignFailure.CancellationToken);
    }

    [Fact]
    public async Task Intermediate_body_read_failure_remains_primary_when_owned_cleanup_also_fails()
    {
        var primary = new IOException("read failed");
        var cleanup = new InvalidOperationException("dispose failed");
        var handler = new FaultingRedirectHandler(primary, cleanup);
        using var client = new HttpClient(handler, true);
        var sender = new ProviderHttpRedirects(client);

        var failure = await Assert.ThrowsAsync<HttpRequestException>(() => sender.SendAsync(
            new Uri("https://first.example/start"), HttpMethod.Get,
            context => Request(context, configured: false), "generate", CancellationToken.None).AsTask());

        Assert.Same(primary, FindInner<IOException>(failure));
        Assert.True(handler.Content.CleanupAttempted);
        Assert.Equal(1, handler.SendCount);
    }

    private static HttpRequestMessage Request(RedirectRequestContext context, bool configured)
    {
        var request = new HttpRequestMessage(context.Method, context.Uri);
        if (context.IncludeBody) request.Content = new StringContent("{}", Encoding.UTF8, "application/json");
        if (configured && context.IncludeOriginBoundHeaders)
        {
            request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", "key");
            request.Headers.Add("X-Configured", "value");
            request.Headers.TryAddWithoutValidation("Accept", "application/configured");
            request.Headers.Host = context.OriginalConfiguredHostEligible ? context.Uri.Authority : null;
        }
        return request;
    }

    private sealed class RedirectingHandler : HttpMessageHandler
    {
        private readonly Uri _firstLocation;
        private readonly Uri? _secondLocation;
        private readonly HttpStatusCode _status;
        internal List<HttpRequestMessage> Requests { get; } = [];
        internal RedirectingHandler(Uri firstLocation, HttpStatusCode status = HttpStatusCode.TemporaryRedirect)
        { _firstLocation = firstLocation; _status = status; }
        internal RedirectingHandler(Uri firstLocation, Uri secondLocation)
        { _firstLocation = firstLocation; _secondLocation = secondLocation; _status = HttpStatusCode.TemporaryRedirect; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Requests.Add(request);
            if (Requests.Count == 1 || Requests.Count == 2 && _secondLocation is not null)
                return Task.FromResult(new HttpResponseMessage(_status) { Headers = { Location = Requests.Count == 1 ? _firstLocation : _secondLocation } });
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK));
        }
    }

    private sealed class EndlessRedirectHandler : HttpMessageHandler
    {
        internal int SendCount { get; private set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        { SendCount++; return Task.FromResult(new HttpResponseMessage(HttpStatusCode.TemporaryRedirect) { Headers = { Location = new Uri("/next", UriKind.Relative) } }); }
    }

    private sealed class RawLocationRecorderHandler(string location) : HttpMessageHandler
    {
        internal List<RecordedRequest> Requests { get; } = [];
        internal int SendCount { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            SendCount++;
            Requests.Add(new RecordedRequest(
                request.RequestUri ?? throw new InvalidOperationException("Redirect request must have a URI."),
                request.Headers.Authorization is not null,
                request.Headers.Host));
            if (SendCount == 1)
            {
                var redirect = new HttpResponseMessage(HttpStatusCode.TemporaryRedirect);
                redirect.Headers.TryAddWithoutValidation("Location", location);
                return Task.FromResult(redirect);
            }
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK));
        }
    }

    private sealed record RecordedRequest(Uri RequestUri, bool HasAuthorization, string? Host);

    private sealed class ConcurrentOriginHandler : HttpMessageHandler
    {
        internal System.Collections.Concurrent.ConcurrentQueue<IReadOnlySet<string>> UnsafeHopHeaders { get; } = [];
        internal System.Collections.Concurrent.ConcurrentQueue<IReadOnlySet<string>> SafeHopHeaders { get; } = [];
        internal TaskCompletionSource BothInitial { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource UnsafeFollowEntered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private int _initial;

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var path = request.RequestUri!.AbsolutePath;
            if (path is "/a" or "/b")
            {
                if (Interlocked.Increment(ref _initial) == 2) BothInitial.TrySetResult();
                await Release.Task.WaitAsync(TimeSpan.FromSeconds(15), cancellationToken);
                if (path == "/b") await UnsafeFollowEntered.Task.WaitAsync(TimeSpan.FromSeconds(15), cancellationToken);
                return new HttpResponseMessage(HttpStatusCode.TemporaryRedirect)
                { Headers = { Location = new Uri(path == "/a" ? "https://second.example/a-follow" : "https://first.example/b-follow") } };
            }
            if (path == "/a-follow")
            {
                UnsafeFollowEntered.TrySetResult();
                UnsafeHopHeaders.Enqueue(request.Headers.Select(static header => header.Key).ToHashSet(StringComparer.OrdinalIgnoreCase));
                return new HttpResponseMessage(HttpStatusCode.OK);
            }
            if (path == "/b-follow")
            {
                SafeHopHeaders.Enqueue(request.Headers.Select(static header => header.Key).ToHashSet(StringComparer.OrdinalIgnoreCase));
                return new HttpResponseMessage(HttpStatusCode.OK);
            }
            throw new InvalidOperationException($"Unexpected redirect path '{path}'.");
        }
    }

    private sealed class BlockingHandler : HttpMessageHandler
    {
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Entered.TrySetResult();
            await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
            return new HttpResponseMessage(HttpStatusCode.OK);
        }
    }

    private sealed class ForeignCancellationHandler(CancellationToken token) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            Task.FromException<HttpResponseMessage>(new OperationCanceledException(token));
    }

    private sealed class FaultingRedirectHandler(IOException primary, Exception cleanup) : HttpMessageHandler
    {
        internal FaultingContent Content { get; } = new(primary, cleanup);
        internal int SendCount { get; private set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            SendCount++;
            var response = new HttpResponseMessage(HttpStatusCode.TemporaryRedirect)
            {
                Content = Content,
            };
            response.Headers.Location = new Uri("/next", UriKind.Relative);
            return Task.FromResult(response);
        }
    }

    private sealed class FaultingContent(IOException primary, Exception cleanup) : HttpContent
    {
        internal bool CleanupAttempted { get; private set; }
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => Task.CompletedTask;

        protected override bool TryComputeLength(out long length)
        {
            length = 0;
            return true;
        }

        protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(new FaultingReadStream(primary));
        protected override void Dispose(bool disposing)
        {
            if (disposing) { CleanupAttempted = true; throw cleanup; }
            base.Dispose(disposing);
        }
    }

    private sealed class FaultingReadStream(IOException primary) : Stream
    {
        public override bool CanRead => true; public override bool CanSeek => false; public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override void Flush() { }
        public override Task FlushAsync(CancellationToken cancellationToken) => Task.CompletedTask;
        public override int Read(byte[] buffer, int offset, int count) => throw primary;
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default) => ValueTask.FromException<int>(primary);
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }

    private static T FindInner<T>(Exception exception) where T : Exception
    {
        for (Exception? current = exception; current is not null; current = current.InnerException)
            if (current is T typed) return typed;
        throw new InvalidOperationException($"Expected an inner {typeof(T).Name}.");
    }

    private sealed class StaticHandler(HttpResponseMessage response) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => Task.FromResult(response);
    }
}
