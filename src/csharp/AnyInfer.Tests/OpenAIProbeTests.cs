using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using AnyInfer.Capabilities;
using AnyInfer.Credentials;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public HTTP projections of the input-only OpenAI-compatible probe scripts.</summary>
public sealed class OpenAIProbeTests
{
    [Fact]
    public async Task Shared_probe_fixture_uses_literal_public_calls_and_preserves_ordered_observations()
    {
        var fixture = ReadFixture();
        var calls = ArrayProperty(fixture, "calls");
        var primary = new ProbeHandler("primary", Responses(calls, "primary"));
        var secondary = new ProbeHandler("secondary", Responses(calls, "secondary"));
        var empty = new ProbeHandler("empty", []);
        var inconclusive = new ProbeHandler("inconclusive", Responses(calls, "inconclusive"));
        var noRecord = new ProbeHandler("record-false", Responses(calls, "record-false"));
        var handlers = new Dictionary<string, ProbeHandler>(StringComparer.Ordinal)
        {
            ["primary"] = primary,
            ["secondary"] = secondary,
            ["empty"] = empty,
            ["inconclusive"] = inconclusive,
            ["record-false"] = noRecord,
        };
        var resolver = new ProbeResolver("env://ANYINFER_SDK_PROBE_TEST_KEY", "probe-secret");
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        var factoryIds = new List<string>();
        var registry = new ProviderRegistry([
            new ProviderDescriptor(builtin.Id, builtin.DisplayName, (bound, cancellationToken) =>
            {
                factoryIds.Add(bound.ProviderId);
                var handler = handlers[bound.ProviderId];
                var settings = ProviderSettings.Of(
                    bound.EngineId, bound.BaseUrl, bound.ApiKey, bound.ApiVersion, bound.Headers,
                    bound.Options, bound.TimeoutS, handler,
                    bound.ProviderId == bound.EngineId ? null : bound.ProviderId);
                return builtin.Factory(new ProviderConfig(settings, bound.EngineId, bound.ApiKey, bound.Options), cancellationToken);
            }, builtin.Aliases, builtin.Setup, builtin.DefaultBaseUrl, builtin.RequiresBaseUrl,
            builtin.StructuredOutputProfiles, builtin.MaxRepairAttempts),
        ]);

        await using var client = new AsyncClient(InstanceSettings(fixture), registry, new ResolverChain([resolver]));
        Assert.Equal("primary", client.Resolve("primary:model").ProviderId);
        var inert = client.StreamAsync("not advanced", target: "primary:model");
        Assert.Empty(factoryIds);
        Assert.Equal(0, resolver.ResolveCalls);
        Assert.All(handlers.Values, static handler => Assert.Empty(handler.Requests));
        await inert.DisposeAsync();

        var emptyReport = await client.ProbeAsync("empty:model", []);
        Assert.Empty(emptyReport.Probes);
        Assert.Equal(0, emptyReport.Requests);
        Assert.Equal(1, resolver.ResolveCalls);
        Assert.Equal(["empty"], factoryIds);
        Assert.Empty(empty.Requests);

        var report = await client.ProbeAsync("primary:model");
        Assert.Equal(CapabilityProbes.DefaultProbeFeatures, report.Probes.Select(static probe => probe.Feature));
        Assert.All(report.Probes, static probe => Assert.Equal(ProbeOutcome.Supported, probe.Outcome));
        Assert.Equal(4, report.Requests);
        Assert.Equal(5, report.Usage.InputTokens);
        Assert.Equal(8, report.Usage.OutputTokens);
        Assert.Equal(13, report.Usage.TotalTokens);
        Assert.NotNull(report.Capabilities);
        Assert.Equal(Provenance.Probed, report.Capabilities!.Features.Provenance);

        Assert.Equal(4, primary.Requests.Count);
        AssertProbeRequest(primary.Requests[0], "primary", body =>
        {
            Assert.Equal("json_schema", body.GetProperty("response_format").GetProperty("type").GetString());
            var schema = body.GetProperty("response_format").GetProperty("json_schema");
            Assert.Equal("capability_probe", schema.GetProperty("name").GetString());
            Assert.Equal("colour", schema.GetProperty("schema").GetProperty("required")[0].GetString());
            Assert.False(body.TryGetProperty("tools", out _));
        });
        AssertProbeRequest(primary.Requests[1], "primary", body =>
        {
            Assert.Equal("json_object", body.GetProperty("response_format").GetProperty("type").GetString());
            Assert.False(body.TryGetProperty("tools", out _));
        });
        AssertProbeRequest(primary.Requests[2], "primary", body =>
        {
            Assert.Equal("required", body.GetProperty("tool_choice").GetString());
            Assert.Equal("record_colour", body.GetProperty("tools")[0].GetProperty("function").GetProperty("name").GetString());
            Assert.False(body.TryGetProperty("response_format", out _));
        });
        AssertProbeRequest(primary.Requests[3], "primary", body =>
        {
            Assert.True(body.GetProperty("stream").GetBoolean());
            Assert.True(body.GetProperty("stream_options").GetProperty("include_usage").GetBoolean());
            Assert.False(body.TryGetProperty("tools", out _));
            Assert.False(body.TryGetProperty("response_format", out _));
        });

        var rejected = await client.ProbeAsync("secondary:model", [Feature.JsonSchema]);
        Assert.Equal(ProbeOutcome.Unsupported, rejected.OutcomeFor(Feature.JsonSchema));
        Assert.Single(secondary.Requests);

        var inconclusiveReport = await client.ProbeAsync("inconclusive:model", [Feature.JsonSchema]);
        Assert.Equal(ProbeOutcome.Inconclusive, inconclusiveReport.OutcomeFor(Feature.JsonSchema));
        Assert.Null(inconclusiveReport.Capabilities);
        var inconclusiveGeneration = await client.GenerateAsync(
            "use the schema", target: "inconclusive:model", schema: new SchemaSpec(CapabilityProbes.ProbeSchema, "capability_probe"));
        Assert.Equal("prompt", inconclusiveGeneration.StructuredMechanism);
        Assert.False(RequestBody(inconclusive.Requests[1]).TryGetProperty("response_format", out _));

        var beforeNoRecord = client.Capabilities("record-false:model");
        var unrecorded = await client.ProbeAsync("record-false:model", [Feature.JsonSchema], record: false);
        Assert.Equal(ProbeOutcome.Supported, unrecorded.OutcomeFor(Feature.JsonSchema));
        Assert.NotNull(unrecorded.Capabilities);
        Assert.Equal(beforeNoRecord, client.Capabilities("record-false:model"));
        var unrecordedGeneration = await client.GenerateAsync(
            "use the schema", target: "record-false:model", schema: new SchemaSpec(CapabilityProbes.ProbeSchema, "capability_probe"));
        Assert.Equal("prompt", unrecordedGeneration.StructuredMechanism);
        Assert.False(RequestBody(noRecord.Requests[1]).TryGetProperty("response_format", out _));

        var duplicates = await client.ProbeAsync("primary:model", [Feature.JsonMode, Feature.JsonMode]);
        Assert.Equal([Feature.JsonMode, Feature.JsonMode], duplicates.Probes.Select(static probe => probe.Feature));
        Assert.All(duplicates.Probes, static probe => Assert.Equal(ProbeOutcome.Supported, probe.Outcome));
        Assert.Equal(2, duplicates.Requests);

        Assert.Equal(["empty", "primary", "secondary", "inconclusive", "record-false"], factoryIds);
        Assert.Empty(primary.Remaining);
        Assert.Empty(secondary.Remaining);
        Assert.Empty(inconclusive.Remaining);
        Assert.Empty(noRecord.Remaining);
        await client.DisposeAsync();
        Assert.All(handlers.Values, static handler =>
        {
            Assert.All(handler.Responses, static response => Assert.True(response.Disposed));
            Assert.True(handler.Disposed);
        });
    }

    [Fact]
    public async Task Probe_timeout_and_public_cancellation_remain_distinct_and_cleanup_real_HTTP()
    {
        var timeout = new BlockingProbeHandler();
        await using (var client = CreateBuiltinClient(timeout, "timeout", timeoutS: 30))
        {
            var timeoutPending = client.ProbeAsync("timeout:model", [Feature.JsonSchema], timeoutS: 0.02);
            await timeout.Started.Task.WaitAsync(TimeSpan.FromSeconds(1));
            var report = await timeoutPending;
            Assert.Equal(ProbeOutcome.Inconclusive, report.OutcomeFor(Feature.JsonSchema));
            await timeout.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
        }
        Assert.True(timeout.Disposed);

        var caller = new BlockingProbeHandler();
        await using var callerClient = CreateBuiltinClient(caller, "caller", timeoutS: 30);
        using var cancellation = new CancellationTokenSource();
        var pending = callerClient.ProbeAsync("caller:model", [Feature.JsonSchema], cancellationToken: cancellation.Token);
        await caller.Started.Task.WaitAsync(TimeSpan.FromSeconds(1));
        cancellation.Cancel();
        var observed = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(cancellation.Token, observed.CancellationToken);
        await caller.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
        Assert.True(caller.LastToken.CanBeCanceled);
        await callerClient.DisposeAsync();
        Assert.True(caller.Disposed);
    }

    [Fact]
    public async Task Probe_read_cancellation_and_active_close_join_the_physical_HTTP_read()
    {
        var callerRead = new BlockingReadProbeHandler();
        await using (var client = CreateBuiltinClient(callerRead, "caller-read", timeoutS: 30))
        using (var cancellation = new CancellationTokenSource())
        {
            var pending = client.ProbeAsync("caller-read:model", [Feature.JsonSchema], cancellationToken: cancellation.Token);
            await callerRead.Content.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
            cancellation.Cancel();
            var observed = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
            Assert.Equal(cancellation.Token, observed.CancellationToken);
            await callerRead.Content.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
            Assert.True(callerRead.Content.LastReadToken.CanBeCanceled);
        }
        AssertProbeReadDisposed(callerRead);

        var closeRead = new BlockingReadProbeHandler();
        var closing = CreateBuiltinClient(closeRead, "close-read", timeoutS: 30);
        var active = closing.ProbeAsync("close-read:model", [Feature.JsonSchema]);
        await closeRead.Content.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
        await closing.DisposeAsync();
        Assert.True(closeRead.Content.CancellationObserved.Task.IsCompleted);
        await closeRead.Content.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => active);
        AssertProbeReadDisposed(closeRead);
    }

    [Fact]
    public async Task Generic_openai_grammar_probe_is_truthful_and_never_sends_HTTP()
    {
        var handler = new ProbeHandler("generic", []);
        await using var client = CreateBuiltinClient(handler, "generic");

        var report = await client.ProbeAsync("generic:model", [Feature.Grammar]);

        Assert.Equal(ProbeOutcome.Unsupported, report.OutcomeFor(Feature.Grammar));
        Assert.Equal(1, report.Requests);
        Assert.Empty(handler.Requests);
    }

    [Fact]
    public async Task Recorded_builtin_probe_changes_the_following_schema_wire_projection()
    {
        const string colour = "{\"choices\":[{\"message\":{\"content\":\"{\\\"colour\\\":\\\"blue\\\"}\"},\"finish_reason\":\"stop\"}]}";
        var handler = new ProbeHandler("recorded", [
            new FixtureResponse(200, "application/json", colour),
            new FixtureResponse(200, "application/json", colour),
        ]);
        await using var client = CreateBuiltinClient(handler, "recorded");

        var probe = await client.ProbeAsync("recorded:model", [Feature.JsonSchema]);
        var generation = await client.GenerateAsync(
            "use recorded capability", target: "recorded:model", schema: new SchemaSpec(CapabilityProbes.ProbeSchema, "capability_probe"));

        Assert.Equal(ProbeOutcome.Supported, probe.OutcomeFor(Feature.JsonSchema));
        Assert.Equal("json_schema", generation.StructuredMechanism);
        Assert.Equal("json_schema", RequestBody(handler.Requests[1]).GetProperty("response_format").GetProperty("type").GetString());
    }

    private static AsyncClient CreateBuiltinClient(HttpMessageHandler handler, string alias, double timeoutS = 120)
    {
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        var settings = ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", "probe-secret",
            headers: new Dictionary<string, string> { ["X-Probe"] = alias }, timeoutS: timeoutS, transport: handler, alias: alias);
        var adapter = builtin.Factory(new ProviderConfig(settings, "openai-compat", "probe-secret"), CancellationToken.None).Result;
        return AsyncClient.FromAdapters([new ProviderRegistration(alias, adapter)]);
    }

    private static void AssertProbeRequest(CapturedRequest request, string instance, Action<JsonElement> assertion)
    {
        Assert.Equal(HttpMethod.Post, request.Method);
        Assert.Equal("/v1/chat/completions", request.Path);
        Assert.Equal($"Bearer probe-secret", request.Headers["authorization"]);
        Assert.Equal(instance, request.Headers["x-probe"]);
        Assert.Equal("application/json", request.ContentHeaders["content-type"]);
        using var document = JsonDocument.Parse(request.Body);
        var body = document.RootElement;
        Assert.Equal("model", body.GetProperty("model").GetString());
        Assert.Equal(64, body.GetProperty("max_tokens").GetInt32());
        Assert.Equal(0, body.GetProperty("temperature").GetDouble());
        assertion(body);
    }

    private static JsonElement RequestBody(CapturedRequest request)
    {
        using var document = JsonDocument.Parse(request.Body);
        return document.RootElement.Clone();
    }

    private static IEnumerable<ProviderSettings> InstanceSettings(JsonObject fixture) =>
        ArrayProperty(fixture, "instances").Items.Select(static value => Assert.IsType<JsonObject>(value)).Select(instance =>
            ProviderSettings.Of(StringProperty(instance, "adapter"), StringProperty(instance, "base_url"), StringProperty(instance, "credential"),
                headers: HeaderProperties(ObjectProperty(instance, "headers")), timeoutS: NumberProperty(instance, "timeout_s"), alias: StringProperty(instance, "id")));

    private static IEnumerable<FixtureResponse> Responses(JsonArray calls, string instance) =>
        calls.Items.Select(static value => Assert.IsType<JsonObject>(value)).Where(call => StringProperty(call, "instance") == instance)
            .Select(call => new FixtureResponse(checked((int)IntegerProperty(call, "status")), StringProperty(ObjectProperty(call, "headers"), "content-type"), StringProperty(call, "body_utf8")));

    private static JsonObject ReadFixture()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
        {
            var path = Path.Combine(directory.FullName, "tests", "fixtures", "sdk-probes-v1", "openai-compat-probes.json");
            if (File.Exists(path)) return Assert.IsType<JsonObject>(JsonReader.Read(File.ReadAllText(path, Encoding.UTF8)));
        }
        throw new Xunit.Sdk.XunitException("The shared SDK.4 probe fixture was not found.");
    }

    private static JsonObject ObjectProperty(JsonObject source, string name) => Assert.IsType<JsonObject>(ValueProperty(source, name));
    private static JsonArray ArrayProperty(JsonObject source, string name) => Assert.IsType<JsonArray>(ValueProperty(source, name));
    private static string StringProperty(JsonObject source, string name) => Assert.IsType<JsonString>(ValueProperty(source, name)).Value;
    private static double NumberProperty(JsonObject source, string name) => Assert.IsType<JsonNumber>(ValueProperty(source, name)).Value;
    private static System.Numerics.BigInteger IntegerProperty(JsonObject source, string name) => Assert.IsType<JsonInteger>(ValueProperty(source, name)).Value;
    private static JsonValue ValueProperty(JsonObject source, string name) => source.TryGetValue(name, out var value) ? value : throw new Xunit.Sdk.XunitException($"Fixture property '{name}' is missing.");
    private static IReadOnlyDictionary<string, string> HeaderProperties(JsonObject source) => source.Properties.ToDictionary(static property => property.Name, static property => Assert.IsType<JsonString>(property.Value).Value, StringComparer.Ordinal);

    private static void AssertProbeReadDisposed(BlockingReadProbeHandler handler)
    {
        Assert.True(handler.Response.Disposed);
        Assert.True(handler.Content.Disposed);
        Assert.True(handler.Content.StreamDisposed);
        Assert.True(handler.Disposed);
    }

    private sealed record FixtureResponse(int Status, string ContentType, string Body);
    private sealed record CapturedRequest(HttpMethod Method, string Path, IReadOnlyDictionary<string, string> Headers, IReadOnlyDictionary<string, string> ContentHeaders, byte[] Body);

    private sealed class ProbeResolver(string reference, string secret) : ICredentialResolver
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

    private sealed class ProbeHandler(string instance, IEnumerable<FixtureResponse> responses) : HttpMessageHandler
    {
        private readonly Queue<FixtureResponse> _responses = new(responses);
        internal List<CapturedRequest> Requests { get; } = [];
        internal List<TrackingResponse> Responses { get; } = [];
        internal IReadOnlyCollection<FixtureResponse> Remaining => _responses;
        internal bool Disposed { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var script = _responses.Count == 0
                ? throw new Xunit.Sdk.XunitException($"The input-only probe script for '{instance}' was exhausted.")
                : _responses.Dequeue();
            Assert.NotNull(request.Content);
            Requests.Add(new CapturedRequest(
                request.Method,
                request.RequestUri!.AbsolutePath,
                request.Headers.ToDictionary(static item => item.Key.ToLowerInvariant(), static item => string.Join(",", item.Value), StringComparer.Ordinal),
                request.Content.Headers.ToDictionary(static item => item.Key.ToLowerInvariant(), static item => string.Join(",", item.Value), StringComparer.Ordinal),
                await request.Content.ReadAsByteArrayAsync(cancellationToken)));
            var response = new TrackingResponse((HttpStatusCode)script.Status)
            {
                Content = new ByteArrayContent(Encoding.UTF8.GetBytes(script.Body)),
            };
            response.Content.Headers.ContentType = MediaTypeHeaderValue.Parse(script.ContentType);
            Responses.Add(response);
            return response;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) Disposed = true;
            base.Dispose(disposing);
        }
    }

    private sealed class BlockingProbeHandler : HttpMessageHandler
    {
        internal TaskCompletionSource Started { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource CancellationObserved { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal CancellationToken LastToken { get; private set; }
        internal bool Disposed { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            LastToken = cancellationToken;
            Started.TrySetResult();
            try { await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken).ConfigureAwait(false); }
            catch (OperationCanceledException) { CancellationObserved.TrySetResult(); throw; }
            throw new Xunit.Sdk.XunitException("The cancellation-aware probe send unexpectedly completed.");
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) Disposed = true;
            base.Dispose(disposing);
        }
    }

    private sealed class BlockingReadProbeHandler : HttpMessageHandler
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
        protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(new BlockingStream(this));
        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) => Task.FromResult<Stream>(new BlockingStream(this));

        protected override void Dispose(bool disposing)
        {
            if (disposing) Disposed = true;
            base.Dispose(disposing);
        }

        private sealed class BlockingStream(BlockingReadContent owner) : Stream
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
                try { await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken).ConfigureAwait(false); }
                catch (OperationCanceledException) { owner.CancellationObserved.TrySetResult(); throw; }
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
