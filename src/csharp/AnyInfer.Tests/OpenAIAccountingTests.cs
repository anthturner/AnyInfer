using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using AnyInfer.Capabilities;
using AnyInfer.Credentials;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using PeterO.Numbers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public builtin HTTP accounting observations over input-only fixture traffic.</summary>
public sealed class OpenAIAccountingTests
{
    [Fact]
    public async Task Public_builtin_http_keeps_only_winning_usage_and_selected_target_price()
    {
        var fixture = ReadFixture();
        var primary = new ScriptHandler("primary", Calls(fixture, "success", "repair-discarded", "repair-winner", "primary-503", "primary-503-again"));
        var secondary = new ScriptHandler("secondary", Calls(fixture, "secondary-winner"));
        var ledger = new SpendLedger();
        var observer = new Collector();
        await using var client = CreateClient(fixture, new Dictionary<string, HttpMessageHandler> { ["primary"] = primary, ["secondary"] = secondary }, ledger, observer);
        var request = Object(fixture, "request");
        var schema = new SchemaSpec(Object(request, "schema"));

        var success = await client.GenerateAsync(Messages(request), target: Text(request, "success_target"), schema: schema);
        AssertUsage(success, "8", 2, 3);
        Assert.NotNull(success.Manifest);
        Assert.Equal("8.000000", success.Manifest!.Usage.CostUsd);

        var repaired = await client.GenerateAsync(Messages(request), target: "primary:model", schema: schema, repair: new Repair(1));
        Assert.Equal(1, repaired.RepairAttempts);
        Assert.Equal("{\"answer\":\"fixed\"}", repaired.Text);
        var structured = Assert.IsType<JsonObject>(repaired.Structured);
        Assert.Equal("fixed", Assert.IsType<JsonString>(structured.Properties.Single().Value).Value);
        AssertUsage(repaired, "8", 2, 3);
        Assert.NotNull(repaired.Manifest);
        Assert.Equal("8.000000", repaired.Manifest!.Usage.CostUsd);

        var fallback = await client.GenerateAsync(Messages(request), route: new Route(["primary:model", "secondary:model"], retry: new Retry(MaxAttempts: 2, BackoffBaseS: 0, BackoffMaxS: 0)));
        Assert.Equal("fallback", fallback.Text);
        AssertUsage(fallback, "7", 1, 1);
        Assert.NotNull(fallback.Manifest);
        Assert.Equal("7.000000", fallback.Manifest!.Usage.CostUsd);

        Assert.Equal(3, ledger.Totals().Requests);
        EqualDecimal("23", ledger.Totals().Cost);
        var completions = observer.Events.OfType<RequestCompleted>().ToArray();
        Assert.Equal(3, completions.Length);
        Assert.Equal(new[] { "primary:model", "primary:model", "secondary:model" }, completions.Select(item => item.Target.ToString()));
        Assert.Collection(
            completions,
            item => EqualDecimal("8", item.Usage.CostUsd),
            item => EqualDecimal("8", item.Usage.CostUsd),
            item => EqualDecimal("7", item.Usage.CostUsd));
        var repairedCompletion = Assert.Single(completions, item => item.RepairAttempts == 1);
        Assert.Equal("primary:model", repairedCompletion.Target.ToString());
        var fallbackCompletion = completions.Last();
        var fallbackFact = Assert.Single(observer.Events.OfType<FallbackTriggered>(), item => item.RequestId == fallbackCompletion.RequestId);
        Assert.Equal("primary:model", fallbackFact.FromTarget.ToString());
        Assert.Equal("secondary:model", fallbackFact.ToTarget);
        Assert.Equal(new[] { "success", "repair-discarded", "repair-winner", "primary-503", "primary-503-again" }, primary.Requests.Select(item => item.Id));
        Assert.Equal(new[] { "secondary-winner" }, secondary.Requests.Select(item => item.Id));
        Assert.Empty(primary.Remaining);
        Assert.Empty(secondary.Remaining);
        AssertRequest(primary.Requests[0], "primary", true);
        AssertRequest(primary.Requests[1], "primary", true);
        AssertRequest(primary.Requests[2], "primary", true);
        AssertRequest(primary.Requests[3], "primary", false);
        AssertRequest(primary.Requests[4], "primary", false);
        AssertRequest(secondary.Requests.Single(), "secondary", false);

        await client.DisposeAsync();
        AssertHandlersDisposed(primary, secondary);
    }

    private static void AssertUsage(Generation generation, string cost, long input, long output)
    {
        Assert.NotNull(generation.Usage);
        Assert.Equal(input, generation.Usage!.InputTokens);
        Assert.Equal(output, generation.Usage.OutputTokens);
        EqualDecimal(cost, generation.Usage.CostUsd);
    }

    private static AsyncClient CreateClient(JsonObject fixture, IReadOnlyDictionary<string, HttpMessageHandler> handlers, SpendLedger ledger, IObserver observer)
    {
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        var registry = new ProviderRegistry([new ProviderDescriptor(builtin.Id, builtin.DisplayName, (bound, cancellationToken) =>
        {
            var handler = handlers[bound.ProviderId];
            var settings = ProviderSettings.Of(bound.EngineId, bound.BaseUrl, bound.ApiKey, bound.ApiVersion, bound.Headers, bound.Options, bound.TimeoutS, handler, bound.ProviderId == bound.EngineId ? null : bound.ProviderId);
            return builtin.Factory(new ProviderConfig(settings, bound.EngineId, bound.ApiKey, bound.Options), cancellationToken);
        }, builtin.Aliases, builtin.Setup, builtin.DefaultBaseUrl, builtin.RequiresBaseUrl, builtin.StructuredOutputProfiles, builtin.MaxRepairAttempts)]);
        return new AsyncClient(Instances(fixture).Where(settings => handlers.ContainsKey(settings.InstanceId)), registry, new ResolverChain([new FixtureResolver("env://ANYINFER_ACCOUNTING_TEST_KEY", "accounting-fixture-token")]), capabilityOverrides: Overrides(fixture, handlers.Keys), observers: [observer], ledger: ledger);
    }

    private static IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>> Overrides(JsonObject fixture, IEnumerable<string> configured)
    {
        var enabled = configured.ToHashSet(StringComparer.Ordinal);
        var instances = Array(fixture, "instances").Items.Select(static value => Assert.IsType<JsonObject>(value)).ToDictionary(item => Text(item, "id"), StringComparer.Ordinal);
        var result = new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>(StringComparer.Ordinal);
        foreach (var entry in Array(fixture, "capability_overrides").Items.Select(static value => Assert.IsType<JsonObject>(value)))
        {
            var target = Text(entry, "target").Split(':', 2);
            if (!enabled.Contains(target[0])) continue;
            var features = Feature.None;
            foreach (var feature in Array(entry, "features").Items) features |= FeatureFor(Assert.IsType<JsonString>(feature).Value);
            var price = Object(instances[target[0]], "pricing");
            result[target[0]] = new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal)
            {
                [target[1]] = new ModelCapabilities(
                    features: new Sourced<Feature>(features, Provenance.Override),
                    pricing: new Sourced<Pricing>(new Pricing(EDecimal.FromString(Text(price, "input_per_1m")), EDecimal.FromString(Text(price, "output_per_1m"))), Provenance.Override)),
            };
        }
        return result;
    }

    private static IEnumerable<ProviderSettings> Instances(JsonObject fixture) => Array(fixture, "instances").Items.Select(static value => Assert.IsType<JsonObject>(value)).Select(instance => ProviderSettings.Of(Text(instance, "adapter"), Text(instance, "base_url"), Text(instance, "credential"), headers: Headers(Object(instance, "headers")), timeoutS: Number(instance, "timeout_s"), alias: Text(instance, "id")));
    private static IEnumerable<FixtureCall> Calls(JsonObject fixture, params string[] ids) => Array(fixture, "calls").Items.Select(static value => Assert.IsType<JsonObject>(value)).Where(call => ids.Contains(Text(call, "id"), StringComparer.Ordinal)).Select(call => new FixtureCall(Text(call, "id"), Text(call, "instance"), checked((int)Integer(call, "status")), Text(Object(call, "headers"), "content-type"), Text(call, "body_utf8")));
    private static IReadOnlyList<Message> Messages(JsonObject request) => Array(request, "messages").Items.Select(static value => Assert.IsType<JsonObject>(value)).Select(message => Text(message, "role") switch { "user" => Message.User(Text(message, "content")), "system" => Message.System(Text(message, "content")), _ => throw new Xunit.Sdk.XunitException("Unsupported fixture role.") }).ToArray();
    private static Feature FeatureFor(string literal) => literal == "JSON_SCHEMA" ? Feature.JsonSchema : throw new Xunit.Sdk.XunitException("Unsupported fixture feature.");
    private static void AssertRequest(CapturedRequest request, string instance, bool schema)
    {
        Assert.Equal(HttpMethod.Post, request.Method);
        Assert.Equal("/v1/chat/completions", request.Path);
        Assert.Equal($"Bearer accounting-fixture-token", request.Headers["authorization"]);
        Assert.Equal(instance, request.Headers["x-accounting"]);
        Assert.Equal("application/json", request.ContentHeaders["content-type"]);
        using var body = JsonDocument.Parse(request.Body);
        Assert.Equal("model", body.RootElement.GetProperty("model").GetString());
        Assert.Equal(schema, body.RootElement.TryGetProperty("response_format", out var responseFormat));
        if (schema)
        {
            Assert.Equal("json_schema", responseFormat.GetProperty("type").GetString());
            var jsonSchema = responseFormat.GetProperty("json_schema");
            Assert.Equal("response", jsonSchema.GetProperty("name").GetString());
            Assert.False(jsonSchema.GetProperty("strict").GetBoolean());
            var schemaValue = jsonSchema.GetProperty("schema");
            Assert.Equal("object", schemaValue.GetProperty("type").GetString());
            Assert.Equal("string", schemaValue.GetProperty("properties").GetProperty("answer").GetProperty("type").GetString());
            Assert.Equal(new[] { "answer" }, schemaValue.GetProperty("required").EnumerateArray().Select(static item => item.GetString()!).ToArray());
        }
        Assert.False(body.RootElement.TryGetProperty("stream", out _));
    }

    private static void AssertHandlersDisposed(params ScriptHandler[] handlers)
    {
        foreach (var handler in handlers)
        {
            Assert.All(handler.Responses, static response => Assert.True(response.Disposed));
            Assert.All(handler.Contents, static content => Assert.True(content.Disposed));
            Assert.True(handler.Disposed);
        }
    }
    private static void EqualDecimal(string expected, EDecimal? actual) { Assert.NotNull(actual); Assert.Equal(0, EDecimal.FromString(expected).CompareTo(actual!)); }
    private static JsonObject ReadFixture() { for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent) { var path = Path.Combine(directory.FullName, "tests", "fixtures", "accounting-v1", "openai-compat-accounting.json"); if (File.Exists(path)) return Assert.IsType<JsonObject>(JsonReader.Read(File.ReadAllText(path, Encoding.UTF8))); } throw new Xunit.Sdk.XunitException("The shared accounting fixture was not found."); }
    private static JsonObject Object(JsonObject source, string name) => Assert.IsType<JsonObject>(Value(source, name));
    private static JsonArray Array(JsonObject source, string name) => Assert.IsType<JsonArray>(Value(source, name));
    private static string Text(JsonObject source, string name) => Assert.IsType<JsonString>(Value(source, name)).Value;
    private static double Number(JsonObject source, string name) => Assert.IsType<JsonNumber>(Value(source, name)).Value;
    private static System.Numerics.BigInteger Integer(JsonObject source, string name) => Assert.IsType<JsonInteger>(Value(source, name)).Value;
    private static JsonValue Value(JsonObject source, string name) => source.TryGetValue(name, out var value) ? value : throw new Xunit.Sdk.XunitException($"Fixture property '{name}' is missing.");
    private static IReadOnlyDictionary<string, string> Headers(JsonObject source) => source.Properties.ToDictionary(static item => item.Name, static item => Assert.IsType<JsonString>(item.Value).Value, StringComparer.Ordinal);

    private sealed record FixtureCall(string Id, string Instance, int Status, string ContentType, string Body);
    private sealed record CapturedRequest(long Sequence, string Id, HttpMethod Method, string Path, IReadOnlyDictionary<string, string> Headers, IReadOnlyDictionary<string, string> ContentHeaders, byte[] Body);
    private sealed class Collector : IObserver { internal List<TelemetryEvent> Events { get; } = []; public void OnEvent(TelemetryEvent value) => Events.Add(value); }
    private sealed class FixtureResolver(string reference, string secret) : ICredentialResolver { public bool Handles(string candidate) => candidate == reference; public ValueTask<string> ResolveAsync(string candidate, CancellationToken cancellationToken = default) => ValueTask.FromResult(secret); }
    private sealed class ScriptHandler(string instance, IEnumerable<FixtureCall> calls) : HttpMessageHandler
    {
        private readonly Queue<FixtureCall> _calls = new(calls);
        private long _sequence;
        internal List<CapturedRequest> Requests { get; } = [];
        internal List<TrackingResponse> Responses { get; } = [];
        internal List<TrackingContent> Contents { get; } = [];
        internal IReadOnlyCollection<FixtureCall> Remaining => _calls;
        internal bool Disposed { get; private set; }
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var call = _calls.Count == 0 ? throw new Xunit.Sdk.XunitException("Accounting script exhausted.") : _calls.Dequeue();
            Assert.Equal(instance, call.Instance); Assert.NotNull(request.Content); Assert.Equal(string.Empty, request.RequestUri!.Query);
            Requests.Add(new CapturedRequest(Interlocked.Increment(ref _sequence), call.Id, request.Method, request.RequestUri.AbsolutePath, request.Headers.ToDictionary(static item => item.Key.ToLowerInvariant(), static item => string.Join(',', item.Value), StringComparer.Ordinal), request.Content.Headers.ToDictionary(static item => item.Key.ToLowerInvariant(), static item => string.Join(',', item.Value), StringComparer.Ordinal), await request.Content.ReadAsByteArrayAsync(cancellationToken)));
            var content = new TrackingContent(Encoding.UTF8.GetBytes(call.Body));
            var response = new TrackingResponse((HttpStatusCode)call.Status) { Content = content };
            response.Content.Headers.ContentType = MediaTypeHeaderValue.Parse(call.ContentType);
            Contents.Add(content);
            Responses.Add(response);
            return response;
        }
        protected override void Dispose(bool disposing) { if (disposing) Disposed = true; base.Dispose(disposing); }
    }
    private sealed class TrackingResponse(HttpStatusCode status) : HttpResponseMessage(status) { internal bool Disposed { get; private set; } protected override void Dispose(bool disposing) { if (disposing) Disposed = true; base.Dispose(disposing); } }
    private sealed class TrackingContent(byte[] bytes) : HttpContent
    {
        internal bool Disposed { get; private set; }

        protected override bool TryComputeLength(out long length)
        {
            length = bytes.Length;
            return true;
        }

        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => stream.WriteAsync(bytes).AsTask();

        protected override void Dispose(bool disposing)
        {
            if (disposing) Disposed = true;
            base.Dispose(disposing);
        }
    }
}
