using System.Net;
using System.Runtime.CompilerServices;
using System.Text;
using AnyInfer.Config;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public caller-opted terminal raw-result retention controls.</summary>
public sealed class RawRetentionTests
{
    [Fact]
    public async Task Async_and_sync_clients_default_to_null_and_preserve_opted_in_terminal_raw_identity()
    {
        var raw = JsonReader.Read("{\"raw_marker\":\"literal-caller-data\"}");

        await using (var asyncDefault = AsyncClient.FromAdapters([new ProviderRegistration("fake", Terminal("answer", raw))]))
        {
            Assert.Null((await asyncDefault.GenerateAsync("prompt", target: "fake:model")).Raw);
        }

        await using (var asyncOptedIn = AsyncClient.FromAdapters([new ProviderRegistration("fake", Terminal("answer", raw))], retainRaw: true))
        {
            Assert.Same(raw, (await asyncOptedIn.GenerateAsync("prompt", target: "fake:model")).Raw);
        }

        using (var syncDefault = Client.FromAdapters([new ProviderRegistration("fake", Terminal("answer", raw))]))
        {
            Assert.Null(syncDefault.Generate("prompt", target: "fake:model").Raw);
        }

        using var syncOptedIn = Client.FromAdapters([new ProviderRegistration("fake", Terminal("answer", raw))], retainRaw: true);
        Assert.Same(raw, syncOptedIn.Generate("prompt", target: "fake:model").Raw);
    }

    [Fact]
    public async Task Retained_raw_survives_real_manifest_installation_without_leaking_to_default_manifest_or_telemetry_payloads()
    {
        const string marker = "literal-retained-raw-marker";
        var raw = JsonReader.Read($"{{\"raw_marker\":\"{marker}\"}}");
        var observer = new Collector();
        await using var client = AsyncClient.FromAdapters(
            [new ProviderRegistration("fake", Terminal("answer", raw))],
            observers: [observer],
            retainRaw: true);

        var result = await client.GenerateAsync("prompt", target: "fake:model");

        Assert.Same(raw, result.Raw);
        Assert.NotNull(result.Manifest);
        Assert.DoesNotContain(marker, result.Manifest!.ToJson(), StringComparison.Ordinal);
        Assert.DoesNotContain(
            observer.Events.Select(static item => JsonWriter.Write(item.ToDictionary())),
            value => value.Contains(marker, StringComparison.Ordinal));
        Assert.NotNull(result.Raw);
        Assert.Contains(marker, JsonWriter.Write(result.Raw), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Winning_fallback_and_repair_results_keep_only_their_selected_terminal_raw_payload()
    {
        var fallbackRaw = JsonReader.Read("{\"winner\":\"fallback\"}");
        var repairRaw = JsonReader.Read("{\"winner\":\"repair\"}");
        var rejectedRaw = JsonReader.Read("{\"winner\":\"rejected\"}");
        var unavailable = new ScriptedAdapter(static (_, _) => ThrowUnavailable());
        await using (var fallback = AsyncClient.FromAdapters(
            [
                new ProviderRegistration("first", unavailable),
                new ProviderRegistration("second", Terminal("recovered", fallbackRaw)),
            ],
            retainRaw: true))
        {
            var result = await fallback.GenerateAsync(
                new GenerationRequest([Message.User("fallback")], new Route(["first:model", "second:model"])));
            Assert.Same(fallbackRaw, result.Raw);
        }

        var calls = 0;
        var repairing = new ScriptedAdapter((_, token) =>
        {
            calls++;
            return calls == 1
                ? Events(token, new AdapterTextDelta("\"wrong\""), new AdapterFinal("stop", null, rejectedRaw))
                : Events(token, new AdapterTextDelta("\"correct\""), new AdapterFinal("stop", null, repairRaw));
        });
        await using var repair = AsyncClient.FromAdapters([new ProviderRegistration("repair", repairing)], retainRaw: true);
        var repaired = await repair.GenerateAsync(
            "repair",
            target: "repair:model",
            schema: new SchemaSpec(JsonReader.Read("{\"const\":\"correct\"}")),
            repair: new Repair(1));

        Assert.Equal(2, calls);
        Assert.Equal(1, repaired.RepairAttempts);
        Assert.Same(repairRaw, repaired.Raw);
    }

    [Fact]
    public async Task Async_client_construction_paths_forward_retain_raw()
    {
        var raw = JsonReader.Read("{\"path\":\"async\"}");

        var constructorRegistry = Registry("constructor", Terminal("answer", raw));
        await using (var constructor = new AsyncClient([ProviderSettings.Of("constructor")], constructorRegistry, retainRaw: true))
        {
            Assert.Same(raw, (await constructor.GenerateAsync("prompt", target: "constructor:model")).Raw);
        }

        await using (var adapters = AsyncClient.FromAdapters([new ProviderRegistration("adapters", Terminal("answer", raw))], retainRaw: true))
        {
            Assert.Same(raw, (await adapters.GenerateAsync("prompt", target: "adapters:model")).Raw);
        }

        var configRegistry = Registry("config", Terminal("answer", raw));
        var config = new AnyInferConfig([ProviderSettings.Of("config")]);
        await using var configured = AsyncClient.FromConfig(config, configRegistry, retainRaw: true);
        Assert.Same(raw, (await configured.GenerateAsync("prompt", target: "config:model")).Raw);
    }

    [Fact]
    public async Task Constructor_and_config_default_retain_raw_arguments_are_false_for_async_and_sync_clients()
    {
        var raw = JsonReader.Read("{\"path\":\"omitted-default\"}");

        await using (var asyncConstructor = new AsyncClient(
            [ProviderSettings.Of("async-constructor")],
            Registry("async-constructor", Terminal("answer", raw))))
        {
            Assert.Null((await asyncConstructor.GenerateAsync("prompt", target: "async-constructor:model")).Raw);
        }

        using (var syncConstructor = new Client(
            [ProviderSettings.Of("sync-constructor")],
            Registry("sync-constructor", Terminal("answer", raw))))
        {
            Assert.Null(syncConstructor.Generate("prompt", target: "sync-constructor:model").Raw);
        }

        var asyncConfig = new AnyInferConfig([ProviderSettings.Of("async-config")]);
        await using (var asyncFromConfig = AsyncClient.FromConfig(
            asyncConfig,
            Registry("async-config", Terminal("answer", raw))))
        {
            Assert.Null((await asyncFromConfig.GenerateAsync("prompt", target: "async-config:model")).Raw);
        }

        var syncConfig = new AnyInferConfig([ProviderSettings.Of("sync-config")]);
        using var syncFromConfig = Client.FromConfig(
            syncConfig,
            Registry("sync-config", Terminal("answer", raw)));
        Assert.Null(syncFromConfig.Generate("prompt", target: "sync-config:model").Raw);
    }

    [Fact]
    public void Sync_client_construction_paths_forward_retain_raw()
    {
        var raw = JsonReader.Read("{\"path\":\"sync\"}");

        using (var constructor = new Client([ProviderSettings.Of("constructor")], Registry("constructor", Terminal("answer", raw)), retainRaw: true))
        {
            Assert.Same(raw, constructor.Generate("prompt", target: "constructor:model").Raw);
        }

        using (var adapters = Client.FromAdapters([new ProviderRegistration("adapters", Terminal("answer", raw))], retainRaw: true))
        {
            Assert.Same(raw, adapters.Generate("prompt", target: "adapters:model").Raw);
        }

        var config = new AnyInferConfig([ProviderSettings.Of("config")]);
        using var configured = Client.FromConfig(config, Registry("config", Terminal("answer", raw)), retainRaw: true);
        Assert.Same(raw, configured.Generate("prompt", target: "config:model").Raw);
    }

    [Fact]
    public async Task Builtin_buffered_openai_response_retains_its_actual_parsed_payload_only_when_opted_in()
    {
        const string marker = "buffered-raw-marker";
        var body = """{"id":"__MARKER__","choices":[{"message":{"content":"buffered"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}"""
            .Replace("__MARKER__", marker, StringComparison.Ordinal);

        await using (var defaultClient = BuiltinClient(new ScriptedHttpHandler(Response("application/json", body))))
        {
            var result = await defaultClient.GenerateAsync("prompt", target: "openai-compat:model");
            Assert.Equal("buffered", result.Text);
            Assert.Null(result.Raw);
        }

        await using var optedIn = BuiltinClient(new ScriptedHttpHandler(Response("application/json", body)), retainRaw: true);
        var retained = await optedIn.GenerateAsync("prompt", target: "openai-compat:model");
        Assert.Equal("buffered", retained.Text);
        Assert.NotNull(retained.Raw);
        Assert.Contains(marker, JsonWriter.Write(retained.Raw), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Builtin_sse_does_not_fabricate_a_terminal_raw_aggregate_when_opted_in()
    {
        const string marker = "sse-frame-marker";
        var sse = """
            data: {"id":"__MARKER__","choices":[{"delta":{"content":"streamed"}}]}

            data: {"choices":[{"delta":{},"finish_reason":"stop"}]}

            data: [DONE]

            """.Replace("__MARKER__", marker, StringComparison.Ordinal) + "\n\n";
        await using var client = BuiltinClient(new ScriptedHttpHandler(Response("text/event-stream", sse)), retainRaw: true);

        var result = await client.GenerateAsync(new GenerationRequest([Message.User("stream")], new Route(["openai-compat:model"]), stream: true));

        Assert.Equal("streamed", result.Text);
        Assert.Null(result.Raw);
    }

    private static AsyncClient BuiltinClient(HttpMessageHandler handler, bool retainRaw = false) =>
        AsyncClient.FromAdapters(
            [new ProviderRegistration("openai-compat", new OpenAIChatAdapter(new Uri("https://fixture.invalid/v1"), "fixture-token", handler: handler))],
            retainRaw: retainRaw);

    private static ProviderRegistry Registry(string id, IProviderAdapter adapter) =>
        new([new ProviderDescriptor(id, id, (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter))]);

    private static ScriptedAdapter Terminal(string text, JsonValue raw) =>
        new((_, token) => Events(token, new AdapterTextDelta(text), new AdapterFinal("stop", null, raw)));

    private static async IAsyncEnumerable<AdapterEvent> ThrowUnavailable()
    {
        await Task.Yield();
        throw new ProviderUnavailableException("fixture unavailable");
#pragma warning disable CS0162
        yield break;
#pragma warning restore CS0162
    }

    private static async IAsyncEnumerable<AdapterEvent> Events(
        [EnumeratorCancellation] CancellationToken cancellationToken,
        params AdapterEvent[] events)
    {
        foreach (var item in events)
        {
            cancellationToken.ThrowIfCancellationRequested();
            yield return item;
            await Task.Yield();
        }
    }

    private static HttpResponseMessage Response(string mediaType, string body) =>
        new(HttpStatusCode.OK)
        {
            Content = new StringContent(body, Encoding.UTF8, mediaType),
        };

    private sealed class ScriptedAdapter(Func<WireRequest, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) : IProviderAdapter
    {
        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) =>
            script(request, cancellationToken);

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class Collector : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];

        public void OnEvent(TelemetryEvent item) => Events.Add(item);
    }

    private sealed class ScriptedHttpHandler(params HttpResponseMessage[] responses) : HttpMessageHandler
    {
        private readonly Queue<HttpResponseMessage> _responses = new(responses);

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Assert.Equal(HttpMethod.Post, request.Method);
            Assert.Equal("/v1/chat/completions", request.RequestUri!.AbsolutePath);
            return Task.FromResult(_responses.Dequeue());
        }
    }
}
