using System.Runtime.CompilerServices;
using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public diagnostic spelling and predispatch-refusal parity controls.</summary>
public sealed class RichGenerationDiagnosticParityTests
{
    [Fact]
    public async Task Trusted_capability_notices_match_python_and_default_capabilities_keep_fields()
    {
        var trustedAdapter = new CapturingAdapter();
        var trustedObserver = new Collector();
        await using var trusted = Client(trustedAdapter, Feature.None, Provenance.Catalog, trustedObserver, ignored: ["seed"]);
        await trusted.GenerateAsync(new GenerationRequest(
            [Message.User("question")], new Route(["rich:model"]), sampling: new Sampling(seed: 0),
            reasoning: "low", citeDocuments: true, logprobs: 0));

        Assert.Equal(
            [
                ("reasoning", "rich's model does not support reasoning effort, so it was not sent"),
                ("cite_documents", "rich's model does not attribute answers to supplied documents, so no citations were requested"),
                ("logprobs", "rich's model does not report token log-probabilities, so none were requested"),
                ("seed", "rich accepts but ignores seed"),
            ],
            trustedObserver.Events.OfType<ParameterDropped>().Select(static item => (item.Parameter, item.Reason)));
        var withheld = Assert.Single(trustedAdapter.Requests);
        Assert.Empty(withheld.ReasoningWire.Properties);
        Assert.False(withheld.CiteDocuments);
        Assert.Null(withheld.Logprobs);

        var defaultAdapter = new CapturingAdapter();
        var defaultObserver = new Collector();
        await using var @default = Client(defaultAdapter, Feature.None, Provenance.Default, defaultObserver);
        await @default.GenerateAsync(new GenerationRequest([Message.User("question")], new Route(["rich:model"]), reasoning: "low", citeDocuments: true, logprobs: 0));

        Assert.Empty(defaultObserver.Events.OfType<ParameterDropped>());
        var passed = Assert.Single(defaultAdapter.Requests);
        Assert.True(passed.ReasoningWire.Properties.Count > 0);
        Assert.True(passed.CiteDocuments);
        Assert.Equal(0, passed.Logprobs);
    }

    [Fact]
    public async Task Trusted_multimodal_absence_groups_stable_missing_labels_while_default_dispatches()
    {
        ContentPart[] media = [
            (ContentPart)new ImagePart(data: [1]),
            new DocumentPart(data: [1]),
            new AudioPart(data: [1]),
            new VideoPart(data: [1]),
        ];
        var trustedAdapter = new CapturingAdapter();
        await using var trusted = Client(trustedAdapter, Feature.None, Provenance.Catalog);

        var refusal = await Refusal(() => trusted.GenerateAsync(new GenerationRequest([new Message("user", media)], new Route(["rich:model"]))));
        Assert.Equal("rich:model does not support attached vision, document, audio_in, video_in input", refusal.Message);
        Assert.Equal("choose a model whose capabilities include the required input modality", refusal.Hint);
        Assert.Empty(trustedAdapter.Requests);

        var defaultAdapter = new CapturingAdapter();
        await using var @default = Client(defaultAdapter, Feature.None, Provenance.Default);
        await @default.GenerateAsync(new GenerationRequest([new Message("user", media)], new Route(["rich:model"])));
        Assert.Single(defaultAdapter.Requests);
    }

    [Fact]
    public async Task Server_tool_refusals_group_sorted_kinds_and_preserve_unconditional_descriptor_gate()
    {
        var requested = new[] { new ServerToolSpec("web_search"), new ServerToolSpec("code_execution") };
        var noWireAdapter = new CapturingAdapter();
        await using var noWire = Client(noWireAdapter, Feature.WebSearch | Feature.CodeExecution, Provenance.Default, serverTools: []);

        var unspeakable = await Refusal(() => noWire.GenerateAsync(new GenerationRequest([Message.User("question")], new Route(["rich:model"]), serverTools: requested)));
        Assert.Equal("rich has no wire form for the requested server-side tool(s): code_execution, web_search", unspeakable.Message);
        Assert.Equal("choose a provider that runs these itself, or drop server_tools", unspeakable.Hint);
        Assert.Empty(noWireAdapter.Requests);

        var trustedAdapter = new CapturingAdapter();
        await using var trusted = Client(trustedAdapter, Feature.None, Provenance.Probed, serverTools: ["web_search", "code_execution"]);
        var unavailable = await Refusal(() => trusted.GenerateAsync(new GenerationRequest([Message.User("question")], new Route(["rich:model"]), serverTools: requested)));
        Assert.Equal("rich:model cannot run the requested server-side tool(s): code_execution, web_search", unavailable.Message);
        Assert.Equal("choose a model whose capabilities include them, or drop server_tools", unavailable.Hint);
        Assert.Empty(trustedAdapter.Requests);

        var defaultAdapter = new CapturingAdapter();
        await using var @default = Client(defaultAdapter, Feature.None, Provenance.Default, serverTools: ["web_search", "code_execution"]);
        await @default.GenerateAsync(new GenerationRequest([Message.User("question")], new Route(["rich:model"]), serverTools: requested));
        Assert.Single(defaultAdapter.Requests);
    }

    private static AsyncClient Client(CapturingAdapter adapter, Feature features, Provenance provenance, Collector? observer = null, IEnumerable<string>? ignored = null, IEnumerable<string>? serverTools = null)
    {
        var descriptor = new ProviderDescriptor(
            "rich", "rich", (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
            staticCapabilities: new Dictionary<string, ModelCapabilities>
            {
                ["model"] = new ModelCapabilities(features: new Sourced<Feature>(features, provenance)),
            },
            reasoningTranslator: effort => new AnyInfer.Json.JsonObject([new AnyInfer.Json.JsonProperty("effort", new AnyInfer.Json.JsonString(effort ?? ""))]),
            ignoredParameters: ignored,
            serverTools: serverTools);
        return new AsyncClient([ProviderSettings.Of("rich")], new ProviderRegistry([descriptor]), observers: observer is null ? null : [observer]);
    }

    private static async Task<UnsupportedInputException> Refusal(Func<Task> operation)
    {
        var aggregate = await Assert.ThrowsAsync<AllTargetsFailedException>(operation);
        var attempt = Assert.Single(aggregate.Attempts);
        return Assert.IsType<UnsupportedInputException>(attempt.Error);
    }

    private sealed class CapturingAdapter : IProviderAdapter
    {
        internal List<WireRequest> Requests { get; } = [];

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            return Events(cancellationToken);
        }

        private static async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            yield return new AdapterTextDelta("ok");
            await Task.Yield();
            yield return new AdapterFinal("stop");
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class Collector : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];
        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent);
    }
}
