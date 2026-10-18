using System.Net;
using System.Net.Http.Headers;
using System.Text;
using AnyInfer.Credentials;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Lifecycle projection of the public OpenAI-compatible builtin.</summary>
public sealed class OpenAILifecycleTests
{
    [Fact]
    public async Task Shared_lifecycle_fixture_replays_literal_utf8_GETs_through_configured_public_instances()
    {
        var fixture = ReadFixture();
        var calls = ArrayProperty(fixture, "calls");
        var primary = new FixtureHandler("primary", Responses(calls, "primary"));
        var secondary = new FixtureHandler("secondary", Responses(calls, "secondary"));
        var resolver = new FixtureResolver("env://ANYINFER_SDK_LIFECYCLE_TEST_KEY", "lifecycle-secret");
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        var factoryCalls = 0;
        var registry = new ProviderRegistry([
            new ProviderDescriptor(builtin.Id, builtin.DisplayName, (bound, cancellationToken) =>
            {
                factoryCalls++;
                var handler = bound.ProviderId switch
                {
                    "primary" => primary,
                    "secondary" => secondary,
                    _ => throw new Xunit.Sdk.XunitException($"Unexpected configured lifecycle instance '{bound.ProviderId}'."),
                };
                var settings = ProviderSettings.Of(
                    bound.EngineId,
                    bound.BaseUrl,
                    bound.ApiKey,
                    bound.ApiVersion,
                    bound.Headers,
                    bound.Options,
                    bound.TimeoutS,
                    handler,
                    bound.ProviderId == bound.EngineId ? null : bound.ProviderId);
                return builtin.Factory(new ProviderConfig(settings, bound.EngineId, bound.ApiKey, bound.Options), cancellationToken);
            }, builtin.Aliases, builtin.Setup, builtin.DefaultBaseUrl, builtin.RequiresBaseUrl,
            builtin.StructuredOutputProfiles, builtin.MaxRepairAttempts),
        ]);
        var settings = InstanceSettings(fixture);

        await using (var client = new AsyncClient(settings, registry, new ResolverChain([resolver])))
        {
            var resolved = client.Resolve("primary:model");
            Assert.Equal("primary", resolved.ProviderId);
            var unadvanced = client.StreamAsync("not advanced", target: "primary:model");
            Assert.Equal(0, factoryCalls);
            Assert.Equal(0, resolver.ResolveCalls);
            Assert.Empty(primary.Requests);
            Assert.Empty(secondary.Requests);
            await unadvanced.DisposeAsync();

            var primaryModels = await client.ModelsAsync("primary");
            var primaryHealth = await client.HealthAsync("primary");
            var secondaryHealth = await client.HealthAsync("secondary");
            var secondaryModels = await client.ModelsAsync("secondary");

            Assert.Equal(["alpha", "alpha", "9"], primaryModels.Select(static model => model.Id));
            Assert.True(primaryHealth.Ok);
            Assert.False(secondaryHealth.Ok);
            Assert.Equal("HTTP 503", secondaryHealth.Detail);
            Assert.Equal(["beta", "beta", "None"], secondaryModels.Select(static model => model.Id));
            Assert.Equal(2, factoryCalls);
            Assert.Equal(2, resolver.ResolveCalls);
        }

        Assert.Empty(primary.Remaining);
        Assert.Empty(secondary.Remaining);
        Assert.Equal(["primary", "primary", "secondary", "secondary"],
            primary.Requests.Concat(secondary.Requests).OrderBy(static request => request.Ordinal).Select(static request => request.Instance));
        foreach (var request in primary.Requests.Concat(secondary.Requests))
        {
            Assert.Equal(HttpMethod.Get, request.Method);
            Assert.Equal("/v1/models", request.Path);
            Assert.Empty(request.Body);
            Assert.Equal("application/json", request.ContentHeaders["content-type"]);
            Assert.Equal("Bearer lifecycle-secret", request.Headers["authorization"]);
            Assert.Equal(request.Instance, request.Headers["x-lifecycle"]);
        }

        Assert.True(primary.IsDisposed);
        Assert.True(secondary.IsDisposed);
        Assert.All(primary.Responses.Concat(secondary.Responses), static response => Assert.True(response.Disposed));
    }

    [Fact]
    public async Task Malformed_models_body_preserves_the_native_format_exception_and_closes_resources()
    {
        var handler = new FixtureHandler("primary", [new FixtureResponse(200, "application/json", "not-json")]);
        var adapter = CreateBuiltinAdapter(handler, "primary", "secret");
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("primary", adapter)]);

        var failure = await Assert.ThrowsAsync<FormatException>(() => client.ModelsAsync("primary"));

        Assert.NotNull(failure);
        await client.DisposeAsync();
        Assert.True(handler.IsDisposed);
        Assert.All(handler.Responses, static response => Assert.True(response.Disposed));
    }

    [Fact]
    public async Task Lifecycle_get_keeps_configured_authorization_and_content_type_overrides_on_the_empty_content()
    {
        var handler = new FixtureHandler("override", [new FixtureResponse(200, "application/json", "[]")]);
        var adapter = CreateBuiltinAdapter(
            handler,
            "override",
            "fallback-secret",
            new Dictionary<string, string>
            {
                ["Authorization"] = "Token explicit",
                ["Content-Type"] = "application/x-lifecycle",
                ["X-Lifecycle"] = "override",
            });
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("override", adapter)]);

        Assert.Empty(await client.ModelsAsync("override"));

        var request = Assert.Single(handler.Requests);
        Assert.Empty(request.Body);
        Assert.Equal("Token explicit", request.Headers["authorization"]);
        Assert.Equal("application/x-lifecycle", request.ContentHeaders["content-type"]);
    }

    [Fact]
    public async Task Lifecycle_timeout_and_caller_cancellation_remain_distinct_public_outcomes()
    {
        var timeoutHandler = new BlockingLifecycleHandler();
        var timeoutAdapter = CreateBuiltinAdapter(timeoutHandler, "timeout", "secret", timeoutS: 0.02);
        await using (var timeoutClient = AsyncClient.FromAdapters([new ProviderRegistration("timeout", timeoutAdapter)]))
        {
            var models = timeoutClient.ModelsAsync("timeout");
            await timeoutHandler.SendStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
            var timeout = await Assert.ThrowsAsync<TransportException>(() => models);
            Assert.Equal("discover", timeout.Phase);
            Assert.True(timeout.Retryable);
            await timeoutHandler.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));

            var health = await timeoutClient.HealthAsync("timeout");
            Assert.False(health.Ok);
            Assert.Equal("The provider request timed out.", health.Detail);
        }

        var callerHandler = new BlockingLifecycleHandler();
        var callerAdapter = CreateBuiltinAdapter(callerHandler, "caller", "secret", timeoutS: 30);
        await using var callerClient = AsyncClient.FromAdapters([new ProviderRegistration("caller", callerAdapter)]);
        using var cancellation = new CancellationTokenSource();
        var cancelled = callerClient.ModelsAsync("caller", cancellationToken: cancellation.Token);
        await callerHandler.SendStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
        cancellation.Cancel();
        var sendCancellation = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => cancelled);
        Assert.Equal(cancellation.Token, sendCancellation.CancellationToken);
        await callerHandler.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
        Assert.True(callerHandler.LastToken.CanBeCanceled);

        var readHandler = new BlockingReadLifecycleHandler();
        var readAdapter = CreateBuiltinAdapter(readHandler, "caller-read", "secret", timeoutS: 30);
        await using var readClient = AsyncClient.FromAdapters([new ProviderRegistration("caller-read", readAdapter)]);
        using var readCancellation = new CancellationTokenSource();
        var readCancelled = readClient.ModelsAsync("caller-read", cancellationToken: readCancellation.Token);
        await readHandler.Content.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
        readCancellation.Cancel();
        var physicalReadCancellation = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => readCancelled);
        Assert.Equal(readCancellation.Token, physicalReadCancellation.CancellationToken);
        await readHandler.Content.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
        Assert.True(readHandler.Content.LastReadToken.CanBeCanceled);
        await readClient.DisposeAsync();
        Assert.True(readHandler.Response.Disposed);
        Assert.True(readHandler.Content.Disposed);
        Assert.True(readHandler.Content.StreamDisposed);
    }

    [Fact]
    public async Task Lifecycle_drains_error_bodies_before_classification_and_releases_response_content_and_stream()
    {
        var modelsHandler = new ReadFaultLifecycleHandler(HttpStatusCode.ServiceUnavailable);
        var modelsAdapter = CreateBuiltinAdapter(modelsHandler, "models-fault", "secret");
        await using (var modelsClient = AsyncClient.FromAdapters([new ProviderRegistration("models-fault", modelsAdapter)]))
        {
            var failure = await Assert.ThrowsAsync<TransportException>(() => modelsClient.ModelsAsync("models-fault"));
            Assert.Equal("discover", failure.Phase);
            Assert.True(failure.Retryable);
            Assert.IsType<IOException>(failure.NativeInner);
        }
        AssertLifecycleResourcesDisposed(modelsHandler);

        var healthHandler = new ReadFaultLifecycleHandler(HttpStatusCode.ServiceUnavailable);
        var healthAdapter = CreateBuiltinAdapter(healthHandler, "health-fault", "secret");
        await using (var healthClient = AsyncClient.FromAdapters([new ProviderRegistration("health-fault", healthAdapter)]))
        {
            var health = await healthClient.HealthAsync("health-fault");
            Assert.False(health.Ok);
            Assert.NotEqual("HTTP 503", health.Detail);
            Assert.DoesNotContain("secret", health.Detail ?? string.Empty, StringComparison.Ordinal);
        }
        AssertLifecycleResourcesDisposed(healthHandler);
    }

    [Fact]
    public async Task Lifecycle_public_async_health_and_sync_facade_preserve_the_original_caller_token()
    {
        var asyncHealthHandler = new BlockingLifecycleHandler();
        var asyncHealthAdapter = CreateBuiltinAdapter(asyncHealthHandler, "async-health", "secret", timeoutS: 30);
        await using (var asyncHealthClient = AsyncClient.FromAdapters([new ProviderRegistration("async-health", asyncHealthAdapter)]))
        {
            using var cancellation = new CancellationTokenSource();
            var pending = asyncHealthClient.HealthAsync("async-health", cancellation.Token);
            await asyncHealthHandler.SendStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
            cancellation.Cancel();
            var observed = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
            Assert.Equal(cancellation.Token, observed.CancellationToken);
            await asyncHealthHandler.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
        }

        var syncModelsHandler = new BlockingLifecycleHandler();
        var syncModelsAdapter = CreateBuiltinAdapter(syncModelsHandler, "sync-models", "secret", timeoutS: 30);
        using (var syncModelsClient = Client.FromAdapters([new ProviderRegistration("sync-models", syncModelsAdapter)]))
        using (var cancellation = new CancellationTokenSource())
        {
            var pending = Task.Run(() => RecordCancellation(() => syncModelsClient.Models("sync-models", cancellationToken: cancellation.Token)));
            await syncModelsHandler.SendStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
            cancellation.Cancel();
            var observed = await pending;
            Assert.Equal(cancellation.Token, observed.CancellationToken);
            await syncModelsHandler.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
        }

        var syncHealthHandler = new BlockingReadLifecycleHandler();
        var syncHealthAdapter = CreateBuiltinAdapter(syncHealthHandler, "sync-health", "secret", timeoutS: 30);
        using (var syncHealthClient = Client.FromAdapters([new ProviderRegistration("sync-health", syncHealthAdapter)]))
        using (var cancellation = new CancellationTokenSource())
        {
            var pending = Task.Run(() => RecordCancellation(() => syncHealthClient.Health("sync-health", cancellation.Token)));
            await syncHealthHandler.Content.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
            cancellation.Cancel();
            var observed = await pending;
            Assert.Equal(cancellation.Token, observed.CancellationToken);
            await syncHealthHandler.Content.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
            Assert.True(syncHealthHandler.Content.LastReadToken.CanBeCanceled);
        }
        Assert.True(syncHealthHandler.Response.Disposed);
        Assert.True(syncHealthHandler.Content.Disposed);
        Assert.True(syncHealthHandler.Content.StreamDisposed);
        Assert.True(syncHealthHandler.Disposed);
    }

    [Fact]
    public async Task Active_lifecycle_close_cancels_the_real_body_read_before_disposal_returns_and_releases_every_resource()
    {
        var handler = new BlockingReadLifecycleHandler();
        var adapter = CreateBuiltinAdapter(handler, "close-read", "secret", timeoutS: 30);
        var client = AsyncClient.FromAdapters([new ProviderRegistration("close-read", adapter)]);
        var active = client.ModelsAsync("close-read");
        await handler.Content.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));

        await client.DisposeAsync();

        Assert.True(handler.Content.CancellationObserved.Task.IsCompleted);
        await handler.Content.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => active);
        Assert.True(handler.Response.Disposed);
        Assert.True(handler.Content.Disposed);
        Assert.True(handler.Content.StreamDisposed);
        Assert.True(handler.Disposed);
    }

    [Fact]
    public async Task Lifecycle_treats_all_sub_400_statuses_as_success_and_models_alone_exposes_malformed_json()
    {
        var successHandler = new FixtureHandler("sub400", [
            new FixtureResponse(307, "application/json", """{"data":[{"id":"redirect-model"}]}"""),
            new FixtureResponse(302, "application/json", "not-json"),
        ]);
        var adapter = CreateBuiltinAdapter(successHandler, "sub400", "secret");
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("sub400", adapter)]);

        Assert.Equal(["redirect-model"], (await client.ModelsAsync("sub400")).Select(static model => model.Id));
        Assert.True((await client.HealthAsync("sub400")).Ok);
        Assert.Empty(successHandler.Remaining);
        Assert.All(successHandler.Requests, static request =>
        {
            Assert.Equal(HttpMethod.Get, request.Method);
            Assert.Equal("/v1/models", request.Path);
            Assert.Empty(request.Body);
        });

        var malformedHandler = new FixtureHandler("malformed", [new FixtureResponse(200, "application/json", "not-json")]);
        var malformedAdapter = CreateBuiltinAdapter(malformedHandler, "malformed", "secret");
        await using var malformedClient = AsyncClient.FromAdapters([new ProviderRegistration("malformed", malformedAdapter)]);
        await Assert.ThrowsAsync<FormatException>(() => malformedClient.ModelsAsync("malformed"));
    }

    private static IProviderAdapter CreateBuiltinAdapter(
        HttpMessageHandler handler,
        string instanceId,
        string secret,
        IReadOnlyDictionary<string, string>? headers = null,
        double timeoutS = 120)
    {
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        var settings = ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", secret,
            headers: headers ?? new Dictionary<string, string> { ["X-Lifecycle"] = instanceId }, transport: handler, timeoutS: timeoutS, alias: instanceId);
        return builtin.Factory(new ProviderConfig(settings, "openai-compat", secret), CancellationToken.None).Result;
    }

    private static IEnumerable<ProviderSettings> InstanceSettings(JsonObject fixture) =>
        ArrayProperty(fixture, "instances").Items.Select(static value => Assert.IsType<JsonObject>(value)).Select(instance =>
            ProviderSettings.Of(
                StringProperty(instance, "adapter"),
                StringProperty(instance, "base_url"),
                StringProperty(instance, "credential"),
                headers: HeaderProperties(ObjectProperty(instance, "headers")),
                timeoutS: NumberProperty(instance, "timeout_s"),
                alias: StringProperty(instance, "id")));

    private static IEnumerable<FixtureResponse> Responses(JsonArray calls, string instance) =>
        calls.Items.Select(static value => Assert.IsType<JsonObject>(value))
            .Where(call => StringProperty(call, "instance") == instance)
            .Select(call => new FixtureResponse(
                checked((int)IntegerProperty(call, "status")),
                StringProperty(ObjectProperty(call, "headers"), "content-type"),
                StringProperty(call, "body_utf8")));

    private static JsonObject ReadFixture()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, "tests", "fixtures", "sdk-lifecycle-v1", "openai-compat-lifecycle.json");
            if (File.Exists(candidate))
            {
                return Assert.IsType<JsonObject>(JsonReader.Read(File.ReadAllText(candidate, Encoding.UTF8)));
            }

            directory = directory.Parent;
        }

        throw new Xunit.Sdk.XunitException("The shared SDK.4 lifecycle fixture was not found from the test base directory.");
    }

    private static JsonObject ObjectProperty(JsonObject source, string name) => Assert.IsType<JsonObject>(ValueProperty(source, name));
    private static JsonArray ArrayProperty(JsonObject source, string name) => Assert.IsType<JsonArray>(ValueProperty(source, name));
    private static string StringProperty(JsonObject source, string name) => Assert.IsType<JsonString>(ValueProperty(source, name)).Value;
    private static double NumberProperty(JsonObject source, string name) => Assert.IsType<JsonNumber>(ValueProperty(source, name)).Value;
    private static System.Numerics.BigInteger IntegerProperty(JsonObject source, string name) => Assert.IsType<JsonInteger>(ValueProperty(source, name)).Value;
    private static JsonValue ValueProperty(JsonObject source, string name) => source.TryGetValue(name, out var value) ? value : throw new Xunit.Sdk.XunitException($"Fixture property '{name}' is missing.");
    private static IReadOnlyDictionary<string, string> HeaderProperties(JsonObject source) => source.Properties.ToDictionary(static property => property.Name, static property => Assert.IsType<JsonString>(property.Value).Value, StringComparer.Ordinal);

    private static void AssertLifecycleResourcesDisposed(ReadFaultLifecycleHandler handler)
    {
        Assert.True(handler.Response.Disposed);
        Assert.True(handler.Content.Disposed);
        Assert.True(handler.Content.StreamDisposed);
        Assert.True(handler.Disposed);
    }

    private static OperationCanceledException RecordCancellation(Action action)
    {
        try
        {
            action();
        }
        catch (OperationCanceledException exception)
        {
            return exception;
        }

        throw new Xunit.Sdk.XunitException("The public lifecycle call unexpectedly completed.");
    }

    private sealed class FixtureResolver(string reference, string secret) : ICredentialResolver
    {
        internal int ResolveCalls { get; private set; }
        public bool Handles(string candidate) => candidate == reference;
        public ValueTask<string> ResolveAsync(string candidate, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Assert.Equal(reference, candidate);
            ResolveCalls++;
            return ValueTask.FromResult(secret);
        }
    }

    private sealed record FixtureResponse(int Status, string ContentType, string Body);
    private sealed record CapturedRequest(
        long Ordinal,
        string Instance,
        HttpMethod Method,
        string Path,
        IReadOnlyDictionary<string, string> Headers,
        IReadOnlyDictionary<string, string> ContentHeaders,
        byte[] Body);

    private sealed class FixtureHandler(string instance, IEnumerable<FixtureResponse> responses) : HttpMessageHandler
    {
        private static long _nextOrdinal;
        private readonly Queue<FixtureResponse> _remaining = new(responses);
        internal List<TrackingResponse> Responses { get; } = [];
        internal List<CapturedRequest> Requests { get; } = [];
        internal bool IsDisposed { get; private set; }
        internal IReadOnlyCollection<FixtureResponse> Remaining => _remaining;

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var response = _remaining.Count != 0 ? _remaining.Dequeue() : throw new Xunit.Sdk.XunitException("The input-only lifecycle script was exhausted.");
            var headers = request.Headers.ToDictionary(static header => header.Key.ToLowerInvariant(), static header => string.Join(",", header.Value), StringComparer.Ordinal);
            Assert.NotNull(request.Content);
            var contentHeaders = request.Content.Headers.ToDictionary(static header => header.Key.ToLowerInvariant(), static header => string.Join(",", header.Value), StringComparer.Ordinal);
            var body = await request.Content.ReadAsByteArrayAsync(cancellationToken);
            Requests.Add(new CapturedRequest(Interlocked.Increment(ref _nextOrdinal), instance, request.Method, request.RequestUri!.AbsolutePath, headers, contentHeaders, body));
            var tracked = new TrackingResponse((HttpStatusCode)response.Status)
            {
                Content = new ByteArrayContent(Encoding.UTF8.GetBytes(response.Body)),
            };
            tracked.Content.Headers.ContentType = MediaTypeHeaderValue.Parse(response.ContentType);
            Responses.Add(tracked);
            return tracked;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) IsDisposed = true;
            base.Dispose(disposing);
        }
    }

    private sealed class BlockingLifecycleHandler : HttpMessageHandler
    {
        internal TaskCompletionSource SendStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource CancellationObserved { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal CancellationToken LastToken { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            LastToken = cancellationToken;
            SendStarted.TrySetResult();
            try
            {
                await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                CancellationObserved.TrySetResult();
                throw;
            }
            throw new Xunit.Sdk.XunitException("The cancellation-aware lifecycle send unexpectedly completed.");
        }
    }

    private sealed class ReadFaultLifecycleHandler(HttpStatusCode status) : HttpMessageHandler
    {
        internal FaultingContent Content { get; } = new();
        internal TrackingResponse Response { get; } = new(status);
        internal bool Disposed { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Assert.Equal(HttpMethod.Get, request.Method);
            Assert.NotNull(request.Content);
            Assert.Empty(request.Content.ReadAsByteArrayAsync(cancellationToken).GetAwaiter().GetResult());
            Content.Headers.ContentType = MediaTypeHeaderValue.Parse("application/json");
            Response.Content = Content;
            return Task.FromResult<HttpResponseMessage>(Response);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) Disposed = true;
            base.Dispose(disposing);
        }
    }

    private sealed class BlockingReadLifecycleHandler : HttpMessageHandler
    {
        internal BlockingReadContent Content { get; } = new();
        internal TrackingResponse Response { get; } = new(HttpStatusCode.OK);
        internal bool Disposed { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Content.Headers.ContentType = MediaTypeHeaderValue.Parse("application/json");
            Response.Content = Content;
            return Task.FromResult<HttpResponseMessage>(Response);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) Disposed = true;
            base.Dispose(disposing);
        }
    }

    private sealed class FaultingContent : HttpContent
    {
        internal bool Disposed { get; private set; }
        internal bool StreamDisposed { get; private set; }

        protected override bool TryComputeLength(out long length)
        {
            length = 0;
            return false;
        }

        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => Task.CompletedTask;
        protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(new FaultingStream(this));
        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) => Task.FromResult<Stream>(new FaultingStream(this));

        protected override void Dispose(bool disposing)
        {
            if (disposing) Disposed = true;
            base.Dispose(disposing);
        }

        private sealed class FaultingStream(FaultingContent owner) : Stream
        {
            public override bool CanRead => true;
            public override bool CanSeek => false;
            public override bool CanWrite => false;
            public override long Length => throw new NotSupportedException();
            public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
            public override void Flush() { }
            public override Task FlushAsync(CancellationToken cancellationToken) => Task.CompletedTask;
            public override int Read(byte[] buffer, int offset, int count) => throw new IOException("fixture body read failed");
            public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default) =>
                ValueTask.FromException<int>(new IOException("fixture body read failed"));
            public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
            public override void SetLength(long value) => throw new NotSupportedException();
            public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

            protected override void Dispose(bool disposing)
            {
                if (disposing) owner.StreamDisposed = true;
                base.Dispose(disposing);
            }
        }
    }

    private sealed class BlockingReadContent : HttpContent
    {
        internal TaskCompletionSource ReadStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource CancellationObserved { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal bool Disposed { get; private set; }
        internal bool StreamDisposed { get; private set; }
        internal CancellationToken LastReadToken { get; private set; }

        protected override bool TryComputeLength(out long length)
        {
            length = 0;
            return false;
        }

        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => Task.CompletedTask;
        protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(new BlockingReadStream(this));
        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) => Task.FromResult<Stream>(new BlockingReadStream(this));

        protected override void Dispose(bool disposing)
        {
            if (disposing) Disposed = true;
            base.Dispose(disposing);
        }

        private sealed class BlockingReadStream(BlockingReadContent owner) : Stream
        {
            public override bool CanRead => true;
            public override bool CanSeek => false;
            public override bool CanWrite => false;
            public override long Length => throw new NotSupportedException();
            public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
            public override void Flush() { }
            public override Task FlushAsync(CancellationToken cancellationToken) => Task.CompletedTask;
            public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
            public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
            {
                owner.LastReadToken = cancellationToken;
                owner.ReadStarted.TrySetResult();
                try
                {
                    await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    owner.CancellationObserved.TrySetResult();
                    throw;
                }
                return 0;
            }
            public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
            public override void SetLength(long value) => throw new NotSupportedException();
            public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

            protected override void Dispose(bool disposing)
            {
                if (disposing) owner.StreamDisposed = true;
                base.Dispose(disposing);
            }
        }
    }

    private sealed class TrackingResponse(HttpStatusCode status) : HttpResponseMessage(status)
    {
        internal bool Disposed { get; private set; }
        protected override void Dispose(bool disposing)
        {
            if (disposing) Disposed = true;
            base.Dispose(disposing);
        }
    }
}
