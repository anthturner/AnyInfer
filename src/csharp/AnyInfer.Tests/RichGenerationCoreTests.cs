using System.Runtime.CompilerServices;
using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public rich-generation controls independent of adapter wire codecs.</summary>
public sealed class RichGenerationCoreTests
{
    [Fact]
    public async Task Default_repair_copy_preserves_every_rich_request_field_on_actual_wire_request()
    {
        var adapter = new CaptureAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        var descriptor = Descriptor(adapter);
        var observer = new Collector();
        await using var client = new AsyncClient([ProviderSettings.Of("rich")], new ProviderRegistry([descriptor]), repair: new Repair(1), observers: [observer]);
        var options = new Dictionary<string, JsonObject> { ["*"] = Object("{\"wild\":true}"), ["rich"] = Object("{\"instance\":true}") };
        var request = new GenerationRequest(
            [new Message("user", [new ImagePart(data: [1, 2, 3])])],
            new Route(["rich:model"]),
            reasoning: "high",
            providerOptions: options,
            metadata: new Dictionary<string, string> { ["label"] = "allowed" },
            logprobs: 2,
            citeDocuments: true,
            serverTools: [new ServerToolSpec("web_search")],
            maxInputPartBytes: 7,
            maxInputBytes: 9);

        var result = await client.GenerateAsync(request);

        var wire = Assert.Single(adapter.Requests);
        Assert.Equal("high", wire.ReasoningWire.TryGetValue("effort", out var effort) ? Assert.IsType<JsonString>(effort).Value : null);
        Assert.Equal(2, wire.Logprobs);
        Assert.True(wire.CiteDocuments);
        Assert.Equal([new ServerToolSpec("web_search")], wire.ServerTools);
        Assert.Equal(7, request.MaxInputPartBytes);
        Assert.Equal(9, request.MaxInputBytes);
        Assert.True(wire.ExtraOptions.TryGetValue("wild", out _));
        Assert.True(wire.ExtraOptions.TryGetValue("instance", out _));
        Assert.False(wire.ExtraOptions.TryGetValue("label", out _));
        Assert.Equal("allowed", Assert.Single(observer.Events.OfType<RequestStarted>()).Metadata["label"]);
        Assert.NotNull(result.Manifest);
        Assert.Equal("high", result.Manifest.Request.Reasoning);
        Assert.Equal(["label"], result.Manifest.Request.MetadataKeys);
        Assert.DoesNotContain("allowed", result.Manifest.ToJson(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Prompt_message_stream_and_sync_conveniences_forward_appended_rich_arguments_after_cache()
    {
        var adapter = new CaptureAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        await using var asyncClient = new AsyncClient([ProviderSettings.Of("rich")], new ProviderRegistry([Descriptor(adapter)]));
        var options = new Dictionary<string, JsonObject> { ["rich"] = Object("{\"flag\":true}") };

        _ = await asyncClient.GenerateAsync("prompt", target: "rich:model", cache: null, reasoning: "low", providerOptions: options, metadata: new Dictionary<string, string> { ["m"] = "v" }, logprobs: 0, citeDocuments: true, serverTools: [new ServerToolSpec("web_search")], maxInputPartBytes: 11, maxInputBytes: 12);
        _ = await asyncClient.GenerateAsync([Message.User("messages")], target: "rich:model", cache: null, reasoning: "low", providerOptions: options, metadata: new Dictionary<string, string> { ["m"] = "v" }, logprobs: 0, citeDocuments: true, serverTools: [new ServerToolSpec("web_search")], maxInputPartBytes: 11, maxInputBytes: 12);
        _ = await asyncClient.StreamAsync("stream", target: "rich:model", cache: null, reasoning: "low", providerOptions: options, metadata: new Dictionary<string, string> { ["m"] = "v" }, logprobs: 0, citeDocuments: true, serverTools: [new ServerToolSpec("web_search")], maxInputPartBytes: 11, maxInputBytes: 12).CollectAsync();
        _ = await asyncClient.StreamAsync([Message.User("stream messages")], target: "rich:model", cache: null, reasoning: "low", providerOptions: options, metadata: new Dictionary<string, string> { ["m"] = "v" }, logprobs: 0, citeDocuments: true, serverTools: [new ServerToolSpec("web_search")], maxInputPartBytes: 11, maxInputBytes: 12).CollectAsync();

        Assert.Equal(4, adapter.Requests.Count);
        Assert.All(adapter.Requests, static request =>
        {
            Assert.Equal(0, request.Logprobs);
            Assert.True(request.CiteDocuments);
            Assert.Equal("low", request.ReasoningWire.TryGetValue("effort", out var effort) ? Assert.IsType<JsonString>(effort).Value : null);
            Assert.Equal([new ServerToolSpec("web_search")], request.ServerTools);
            Assert.True(request.ExtraOptions.TryGetValue("flag", out _));
        });

        var syncAdapter = new CaptureAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        using var syncClient = new Client([ProviderSettings.Of("rich")], new ProviderRegistry([Descriptor(syncAdapter)]));
        _ = syncClient.Generate("sync", target: "rich:model", cache: null, reasoning: "low", providerOptions: options, metadata: new Dictionary<string, string> { ["m"] = "v" }, logprobs: 0, citeDocuments: true, serverTools: [new ServerToolSpec("web_search")], maxInputPartBytes: 11, maxInputBytes: 12);
        _ = syncClient.Generate([Message.User("sync messages")], target: "rich:model", cache: null, reasoning: "low", providerOptions: options, metadata: new Dictionary<string, string> { ["m"] = "v" }, logprobs: 0, citeDocuments: true, serverTools: [new ServerToolSpec("web_search")], maxInputPartBytes: 11, maxInputBytes: 12);
        _ = syncClient.Stream("sync stream", target: "rich:model", cache: null, reasoning: "low", providerOptions: options, metadata: new Dictionary<string, string> { ["m"] = "v" }, logprobs: 0, citeDocuments: true, serverTools: [new ServerToolSpec("web_search")], maxInputPartBytes: 11, maxInputBytes: 12).Collect();
        _ = syncClient.Stream([Message.User("sync stream messages")], target: "rich:model", cache: null, reasoning: "low", providerOptions: options, metadata: new Dictionary<string, string> { ["m"] = "v" }, logprobs: 0, citeDocuments: true, serverTools: [new ServerToolSpec("web_search")], maxInputPartBytes: 11, maxInputBytes: 12).Collect();
        Assert.Equal(4, syncAdapter.Requests.Count);

        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(() => asyncClient.GenerateAsync(
            [new Message("user", [new ImagePart(data: [1, 2])])], target: "rich:model", maxInputPartBytes: 1, maxInputBytes: 2));
        Assert.Equal(4, adapter.Requests.Count);
        Assert.Throws<ArgumentOutOfRangeException>(() => syncClient.Generate(
            [new Message("user", [new ImagePart(data: [1, 2])])], target: "rich:model", maxInputPartBytes: 1, maxInputBytes: 2));
        Assert.Equal(4, syncAdapter.Requests.Count);
    }

    [Fact]
    public async Task Rich_events_mark_first_content_without_joining_reasoning_and_terminal_fields_survive_manifest()
    {
        var citation = new Citation(0, 1, "answer", title: "source");
        var observer = new Collector();
        var adapter = new CaptureAdapter((_, token) => Events(token,
            new AdapterCitationDelta(citation),
            new AdapterServerToolDelta("web_search", "completed"),
            new AdapterUsage(new Usage(InputTokens: 2)),
            new AdapterReasoningDelta("think"),
            new AdapterToolCallDelta(0, "id", "weather", "{\"city\":"),
            new AdapterTextDelta("answer"),
            new AdapterToolCallDelta(0, null, null, "\"Boston\"}"),
            new AdapterFinal("stop", Raw: Object("{\"raw\":\"marker\"}"), phases: [new KeyValuePair<string, double>("decode", 2)], logprobs: [new TokenLogprob("a", -0.1)], serverToolUses: [new ServerToolUse("web_search", 1), new ServerToolUse("web_search", 2)])));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("rich", adapter)], observers: [observer], retainRaw: true);
        var events = new List<StreamEvent>();
        var stream = client.StreamAsync(new GenerationRequest([Message.User("question")], new Route(["rich:model"])));
        await foreach (var item in stream) events.Add(item);

        Assert.Equal("answer", stream.Result.Text);
        Assert.Contains(events, static item => item is ReasoningDelta { Text: "think" });
        Assert.DoesNotContain(stream.Result.Text, "think", StringComparison.Ordinal);
        Assert.Equal("weather", Assert.Single(stream.Result.ToolCalls).Name);
        Assert.Equal("Boston", Assert.IsType<JsonString>(Assert.Single(stream.Result.ToolCalls).Arguments.Properties.Single().Value).Value);
        Assert.Equal([citation], stream.Result.Citations);
        Assert.Equal("a", Assert.Single(stream.Result.Logprobs).Token);
        Assert.Equal([new ServerToolUse("web_search", 1), new ServerToolUse("web_search", 2)], stream.Result.ServerToolUses);
        Assert.Equal(2, stream.Result.Usage!.ServerToolUses["web_search"]);
        Assert.Equal(2, Assert.Single(observer.Events.OfType<AttemptCompleted>()).Usage.ServerToolUses["web_search"]);
        Assert.Equal(2, Assert.Single(observer.Events.OfType<RequestCompleted>()).Usage.ServerToolUses["web_search"]);
        Assert.NotNull(stream.Result.Manifest);
        Assert.Equal(stream.Result.Logprobs, stream.Result.WithManifest(stream.Result.Manifest).Logprobs);
    }

    [Fact]
    public async Task Failed_fallback_entry_cannot_leak_its_rich_terminal_values_into_winner()
    {
        var first = new CaptureAdapter((_, token) => FailAfterCitation(token));
        var second = new CaptureAdapter((_, token) => Events(token,
            new AdapterTextDelta("winner"),
            new AdapterFinal("stop", logprobs: [new TokenLogprob("good", -0.1)], serverToolUses: [new ServerToolUse("web_search", 1)])));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("first", first), new ProviderRegistration("second", second)]);

        var result = await client.GenerateAsync(new GenerationRequest([Message.User("question")], new Route(["first:model", "second:model"])));

        Assert.Equal("winner", result.Text);
        Assert.Equal("good", Assert.Single(result.Logprobs).Token);
        Assert.Equal(1, Assert.Single(result.ServerToolUses).Uses);
        Assert.Empty(result.Citations);
    }

    [Fact]
    public async Task Schema_repair_discards_rejected_rich_terminal_values_and_keeps_only_repair_final()
    {
        var rejectedRaw = Object("{\"raw\":\"rejected\"}");
        var winningRaw = Object("{\"raw\":\"winner\"}");
        var options = new Dictionary<string, JsonObject> { ["*"] = Object("{\"wild\":true}"), ["rich"] = Object("{\"instance\":true}") };
        var calls = 0;
        var adapter = new CaptureAdapter((_, token) => ++calls == 1
            ? Events(token,
                new AdapterCitationDelta(new Citation(0, 1, "rejected citation")),
                new AdapterTextDelta("\"wrong\""),
                new AdapterFinal("stop", Raw: rejectedRaw, logprobs: [new TokenLogprob("wrong", -1)], serverToolUses: [new ServerToolUse("web_search", 9)]))
            : Events(token,
                new AdapterCitationDelta(new Citation(0, 1, "winning citation")),
                new AdapterTextDelta("\"correct\""),
                new AdapterFinal("stop", Raw: winningRaw, logprobs: [new TokenLogprob("correct", -0.1)], serverToolUses: [new ServerToolUse("web_search", 1)])));
        await using var client = new AsyncClient([ProviderSettings.Of("rich")], new ProviderRegistry([Descriptor(adapter)]), retainRaw: true);

        var result = await client.GenerateAsync(new GenerationRequest(
            [Message.User("repair")], new Route(["rich:model"]),
            schema: new SchemaSpec(JsonReader.Read("{\"const\":\"correct\"}")), repair: new Repair(1),
            reasoning: "high", providerOptions: options, logprobs: 2, citeDocuments: true,
            serverTools: [new ServerToolSpec("web_search")]));

        Assert.Equal(2, calls);
        Assert.Equal(2, adapter.Requests.Count);
        Assert.All(adapter.Requests, static wire =>
        {
            Assert.Equal("high", wire.ReasoningWire.TryGetValue("effort", out var effort) ? Assert.IsType<JsonString>(effort).Value : null);
            Assert.Equal(2, wire.Logprobs);
            Assert.True(wire.CiteDocuments);
            Assert.Equal([new ServerToolSpec("web_search")], wire.ServerTools);
            Assert.True(wire.ExtraOptions.TryGetValue("wild", out _));
            Assert.True(wire.ExtraOptions.TryGetValue("instance", out _));
        });
        var correction = adapter.Requests[1];
        var originalPrefix = adapter.Requests[0].Messages;
        var correctionPrefix = correction.Messages.Take(originalPrefix.Count).ToArray();
        Assert.All(originalPrefix, static message => Assert.All(message.Content, static part => Assert.IsType<Text>(part)));
        Assert.All(correctionPrefix, static message => Assert.All(message.Content, static part => Assert.IsType<Text>(part)));
        Assert.Equal(
            originalPrefix.Select(static message => (message.Role, message.Text)),
            correctionPrefix.Select(static message => (message.Role, message.Text)));
        Assert.Equal("assistant", correction.Messages[^2].Role);
        Assert.Equal("\"wrong\"", correction.Messages[^2].Text);
        Assert.Equal("user", correction.Messages[^1].Role);
        Assert.StartsWith("Your previous response did not match the required JSON schema. Errors:\n", correction.Messages[^1].Text, StringComparison.Ordinal);
        Assert.Equal("\"correct\"", result.Text);
        Assert.Equal("correct", Assert.IsType<JsonString>(result.Structured).Value);
        Assert.Equal([new Citation(0, 1, "winning citation")], result.Citations);
        Assert.Equal("correct", Assert.Single(result.Logprobs).Token);
        Assert.Equal(1, Assert.Single(result.ServerToolUses).Uses);
        Assert.Same(winningRaw, result.Raw);
    }

    [Fact]
    public async Task Ignored_parameters_emit_once_across_repair_without_stripping_requested_wire_values()
    {
        var calls = 0;
        var adapter = new CaptureAdapter((_, token) => ++calls == 1
            ? Events(token, new AdapterTextDelta("\"wrong\""), new AdapterFinal("stop"))
            : Events(token, new AdapterTextDelta("\"correct\""), new AdapterFinal("stop")));
        var descriptor = new ProviderDescriptor(
            "rich", "rich", (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
            ignoredParameters: ["seed", "logprobs", "stop", "cite_documents", "tools", "server_tools.max_uses"],
            serverTools: ["web_search"]);
        var observer = new Collector();
        await using var client = new AsyncClient([ProviderSettings.Of("rich")], new ProviderRegistry([descriptor]), observers: [observer]);

        var result = await client.GenerateAsync(new GenerationRequest(
            [Message.User("repair")], new Route(["rich:model"]),
            sampling: new Sampling(seed: 0, stop: []), repair: new Repair(1),
            schema: new SchemaSpec(JsonReader.Read("{\"const\":\"correct\"}")),
            logprobs: 0, citeDocuments: false, tools: [],
            serverTools: [new ServerToolSpec("web_search", maxUses: 2)]));

        Assert.Equal("\"correct\"", result.Text);
        Assert.Equal(2, calls);
        Assert.Equal(2, adapter.Requests.Count);
        Assert.All(adapter.Requests, static wire =>
        {
            Assert.Equal(0, wire.Sampling.Seed);
            Assert.Null(wire.Sampling.Stop);
            Assert.Equal(0, wire.Logprobs);
            Assert.False(wire.CiteDocuments);
            Assert.Empty(wire.Tools);
            Assert.Equal([new ServerToolSpec("web_search", maxUses: 2)], wire.ServerTools);
        });
        Assert.Equal(
            ["seed", "logprobs", "server_tools.max_uses"],
            observer.Events.OfType<ParameterDropped>().Select(static item => item.Parameter));
    }

    [Theory]
    [InlineData(Provenance.Catalog)]
    [InlineData(Provenance.Discovered)]
    [InlineData(Provenance.Probed)]
    [InlineData(Provenance.Override)]
    public async Task Trusted_known_feature_absence_drops_reasoning_logprobs_and_citations_once(Provenance provenance)
    {
        var adapter = new CaptureAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        var observer = new Collector();
        var capabilities = new ModelCapabilities(features: new Sourced<Feature>(Feature.None, provenance));
        await using var client = PolicyClient(adapter, capabilities, observer);
        var request = new GenerationRequest([Message.User("question")], new Route(["rich:model"]), reasoning: "low", logprobs: 1, citeDocuments: true);

        _ = await client.GenerateAsync(request);

        var wire = Assert.Single(adapter.Requests);
        Assert.Empty(wire.ReasoningWire.Properties);
        Assert.Null(wire.Logprobs);
        Assert.False(wire.CiteDocuments);
        Assert.Equal(["reasoning", "cite_documents", "logprobs"], observer.Events.OfType<ParameterDropped>().Select(static item => item.Parameter));
    }

    [Fact]
    public async Task Default_feature_absence_does_not_withhold_rich_request_fields_but_missing_server_wire_support_refuses_before_dispatch()
    {
        var adapter = new CaptureAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        var defaultCapabilities = new ModelCapabilities(features: new Sourced<Feature>(Feature.None, Provenance.Default));
        await using var client = PolicyClient(adapter, defaultCapabilities);
        await client.GenerateAsync(new GenerationRequest([Message.User("question")], new Route(["rich:model"]), reasoning: "low", logprobs: 0, citeDocuments: true));
        var wire = Assert.Single(adapter.Requests);
        Assert.Equal(0, wire.Logprobs);
        Assert.True(wire.CiteDocuments);

        var noWireAdapter = new CaptureAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        await using var noWire = PolicyClient(noWireAdapter, new ModelCapabilities(features: new Sourced<Feature>(Feature.WebSearch, Provenance.Default)), declareServerTools: false);
        await AssertSingleUnsupportedInput(() => noWire.GenerateAsync(new GenerationRequest([Message.User("question")], new Route(["rich:model"]), serverTools: [new ServerToolSpec("web_search")])));
        Assert.Empty(noWireAdapter.Requests);
    }

    [Theory]
    [InlineData("reasoning")]
    [InlineData("text")]
    [InlineData("tool")]
    public async Task Each_empty_content_kind_marks_first_token_after_noncontent_prefix(string kind)
    {
        var content = kind switch
        {
            "reasoning" => new AdapterEvent[] { new AdapterReasoningDelta("") },
            "text" => new AdapterEvent[] { new AdapterTextDelta("") },
            "tool" => new AdapterEvent[] { new AdapterToolCallDelta(0, "id", "tool", ""), new AdapterToolCallDelta(0, null, null, "{}") },
            _ => throw new ArgumentOutOfRangeException(nameof(kind)),
        };
        var adapter = new CaptureAdapter((_, token) => Events(token,
            [
                new AdapterCitationDelta(new Citation()),
                new AdapterServerToolDelta("web_search", "started"),
                new AdapterUsage(new Usage()),
                .. content,
                new AdapterFinal("stop"),
            ]));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("rich", adapter)]);

        var events = new List<StreamEvent>();
        await foreach (var item in client.StreamAsync(new GenerationRequest([Message.User("question")], new Route(["rich:model"])))) events.Add(item);

        Assert.Equal("attempt_start", Assert.IsType<TimingMark>(events[0]).Name);
        Assert.IsType<CitationDelta>(events[1]);
        Assert.IsType<ServerToolDelta>(events[2]);
        Assert.IsType<UsageUpdate>(events[3]);
        Assert.Equal("first_token", Assert.IsType<TimingMark>(events[4]).Name);
        switch (kind)
        {
            case "reasoning": Assert.IsType<ReasoningDelta>(events[5]); break;
            case "text": Assert.IsType<TextDelta>(events[5]); break;
            case "tool": Assert.IsType<ToolCallDelta>(events[5]); break;
        }
        Assert.Single(((StreamEnded)events.Last()).Result.Citations);
    }

    [Fact]
    public void Frozen_profile_refuses_active_rich_knobs_before_legacy_text_cast_and_keeps_text_path()
    {
        var refusal = Assert.Throws<ProviderException>(() => RequestAdmission.Validate(
            new GenerationRequest([Message.User("question")], new Route(["rich:model"]), reasoning: "low")));
        Assert.Equal("unsupported_input", refusal.Category);
        RequestAdmission.Validate(new GenerationRequest([Message.User("text")], new Route(["rich:model"])));
    }

    [Fact]
    public async Task Trusted_media_and_server_feature_absence_refuse_while_default_absence_permits()
    {
        var trustedMediaAdapter = new CaptureAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        await using var trustedMedia = PolicyClient(trustedMediaAdapter, new ModelCapabilities(features: new Sourced<Feature>(Feature.None, Provenance.Catalog)));
        await AssertSingleUnsupportedInput(() => trustedMedia.GenerateAsync(new GenerationRequest([new Message("user", [new ImagePart(data: [1])])], new Route(["rich:model"]))));
        Assert.Empty(trustedMediaAdapter.Requests);

        var defaultMediaAdapter = new CaptureAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        await using var defaultMedia = PolicyClient(defaultMediaAdapter, new ModelCapabilities(features: new Sourced<Feature>(Feature.None, Provenance.Default)));
        await defaultMedia.GenerateAsync(new GenerationRequest([new Message("user", [new ImagePart(data: [1])])], new Route(["rich:model"])));
        Assert.Single(defaultMediaAdapter.Requests);

        var trustedToolAdapter = new CaptureAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        await using var trustedTool = PolicyClient(trustedToolAdapter, new ModelCapabilities(features: new Sourced<Feature>(Feature.None, Provenance.Probed)));
        await AssertSingleUnsupportedInput(() => trustedTool.GenerateAsync(new GenerationRequest([Message.User("question")], new Route(["rich:model"]), serverTools: [new ServerToolSpec("web_search")])));
        Assert.Empty(trustedToolAdapter.Requests);
    }

    [Fact]
    public async Task Rich_input_refusal_advances_normal_route_without_selecting_context_window_chain()
    {
        var rejected = new CaptureAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        var winner = new CaptureAdapter(static (_, token) => Events(token, new AdapterTextDelta("winner"), new AdapterFinal("stop")));
        var context = new CaptureAdapter(static (_, token) => Events(token, new AdapterTextDelta("context"), new AdapterFinal("stop")));
        var descriptors = new ProviderRegistry([
            PolicyDescriptor("first", rejected, new ModelCapabilities(features: new Sourced<Feature>(Feature.None, Provenance.Catalog))),
            PolicyDescriptor("second", winner, new ModelCapabilities(features: new Sourced<Feature>(Feature.Vision, Provenance.Catalog))),
            PolicyDescriptor("context", context, new ModelCapabilities(features: new Sourced<Feature>(Feature.Vision, Provenance.Catalog))),
        ]);
        await using var client = new AsyncClient([ProviderSettings.Of("first"), ProviderSettings.Of("second"), ProviderSettings.Of("context")], descriptors);

        var result = await client.GenerateAsync(new GenerationRequest([new Message("user", [new ImagePart(data: [1])])], new Route(["first:model", "second:model"], contextWindowTargets: ["context:model"])));

        Assert.Equal("winner", result.Text);
        Assert.Empty(rejected.Requests);
        Assert.Single(winner.Requests);
        Assert.Empty(context.Requests);
    }

    [Fact]
    public async Task Media_is_unpriced_and_public_budget_withholds_fit_and_cost_without_fetching_urls()
    {
        var request = new GenerationRequest([new Message("user", [new Text("question"), new ImagePart(url: "https://image.invalid/a.png")])], new Route(["rich:model"]));
        var estimate = TokenEstimation.EstimateRequest(request);
        Assert.Equal(1, estimate.UnpricedParts);

        var adapter = new CaptureAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        await using var client = PolicyClient(adapter, new ModelCapabilities(contextWindow: new Sourced<int>(100, Provenance.Catalog)));
        var budget = client.Budget(request, "rich:model", outputReserveTokens: 0);
        Assert.Null(budget.Fits);
        Assert.Null(budget.EstimatedCost);
        Assert.Empty(adapter.Requests);
    }

    private static ProviderDescriptor Descriptor(IProviderAdapter adapter) => new(
        "rich", "rich", (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
        staticCapabilities: new Dictionary<string, ModelCapabilities>(),
        reasoningTranslator: effort => new JsonObject([new JsonProperty("effort", new JsonString(effort ?? ""))]),
        serverTools: ["web_search"]);

    private static AsyncClient PolicyClient(CaptureAdapter adapter, ModelCapabilities capabilities, Collector? observer = null, bool declareServerTools = true)
    {
        var descriptor = PolicyDescriptor("rich", adapter, capabilities, declareServerTools);
        return new AsyncClient([ProviderSettings.Of("rich")], new ProviderRegistry([descriptor]), observers: observer is null ? null : [observer]);
    }

    private static ProviderDescriptor PolicyDescriptor(string id, CaptureAdapter adapter, ModelCapabilities capabilities, bool declareServerTools = true) => new(
        id, id, (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
        staticCapabilities: new Dictionary<string, ModelCapabilities> { ["model"] = capabilities },
        reasoningTranslator: effort => new JsonObject([new JsonProperty("effort", new JsonString(effort ?? ""))]),
        serverTools: declareServerTools ? ["web_search"] : []);

    private static JsonObject Object(string text) => Assert.IsType<JsonObject>(JsonReader.Read(text));
    private static async Task AssertSingleUnsupportedInput(Func<Task> operation)
    {
        var aggregate = await Assert.ThrowsAsync<AllTargetsFailedException>(operation);
        var attempt = Assert.Single(aggregate.Attempts);
        var error = Assert.IsType<UnsupportedInputException>(attempt.Error);
        Assert.Equal("unsupported_input", error.Category);
    }
    private static async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken token, params AdapterEvent[] values)
    {
        foreach (var value in values) { token.ThrowIfCancellationRequested(); yield return value; await Task.Yield(); }
    }

    private static async IAsyncEnumerable<AdapterEvent> FailAfterCitation([EnumeratorCancellation] CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        yield return new AdapterCitationDelta(new Citation(0, 1, "bad"));
        await Task.Yield();
        throw new ProviderUnavailableException("retry", retryable: false);
    }

    private sealed class CaptureAdapter(Func<WireRequest, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) : IProviderAdapter
    {
        internal List<WireRequest> Requests { get; } = [];
        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) { Requests.Add(request); return script(request, cancellationToken); }
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class Collector : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];
        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent);
    }
}
