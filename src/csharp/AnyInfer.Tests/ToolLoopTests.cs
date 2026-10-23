using System.Runtime.CompilerServices;
using AnyInfer.Capabilities;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public bounded-loop controls over real client generation and registered tools.</summary>
public sealed class ToolLoopTests
{
    [Fact]
    public async Task Two_round_loop_replaces_request_tools_preserves_rich_fields_and_keeps_final_accounting()
    {
        var adapterIndex = 0;
        var adapter = new ScriptedAdapter((request, token) => adapterIndex++ == 0
            ? Events(token, new AdapterToolCallDelta(0, "repeat", "lookup", "{}"), new AdapterFinal("tool_calls"))
            : Events(token, new AdapterTextDelta("done"), new AdapterUsage(new Usage(OutputTokens: 3)), new AdapterFinal("stop")));
        var descriptor = new ProviderDescriptor(
            "fake",
            "fake",
            (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
            staticCapabilities: new Dictionary<string, ModelCapabilities>(),
            reasoningTranslator: effort => Object(("effort", new JsonString(effort ?? ""))),
            serverTools: ["web_search"]);
        await using var client = new AsyncClient([ProviderSettings.Of("fake")], new ProviderRegistry([descriptor]));
        var original = new ToolSpec("unregistered", "", new JsonObject([]));
        var registered = new Tool(new ToolSpec("lookup", "", new JsonObject([])), (_, _) => ValueTask.FromResult<object?>("value"));
        var request = new GenerationRequest(
            [Message.User("question")],
            new Route(["fake:model"]),
            tools: [original],
            reasoning: "low",
            providerOptions: new Dictionary<string, JsonObject> { ["fake"] = Object(("flag", new JsonBoolean(true))) },
            metadata: new Dictionary<string, string> { ["label"] = "kept" },
            logprobs: 0,
            citeDocuments: true,
            serverTools: [new ServerToolSpec("web_search")]);

        var result = await client.RunToolsAsync(request, [registered]);

        Assert.Equal("done", result.Text);
        Assert.Equal(3, result.Usage!.OutputTokens);
        Assert.NotNull(result.Manifest);
        Assert.Equal(2, adapter.Requests.Count);
        Assert.Equal(["lookup"], adapter.Requests[0].Tools.Select(static spec => spec.Name));
        Assert.Equal(["lookup"], adapter.Requests[1].Tools.Select(static spec => spec.Name));
        Assert.True(adapter.Requests[1].ReasoningWire.TryGetValue("effort", out var effort));
        Assert.Equal("low", Assert.IsType<JsonString>(effort).Value);
        Assert.Equal(0, adapter.Requests[1].Logprobs);
        Assert.True(adapter.Requests[1].CiteDocuments);
        Assert.Equal("low", request.WithMessages([Message.User("copy")]).Reasoning);
        Assert.Equal("assistant", adapter.Requests[1].Messages[^2].Role);
        Assert.Equal("tool", adapter.Requests[1].Messages[^1].Role);
        Assert.Equal("repeat", Assert.IsType<ToolResult>(adapter.Requests[1].Messages[^1].Content[0]).CallId);
    }

    [Fact]
    public async Task Shortcut_bounds_unknown_names_handler_errors_and_repeated_ids_follow_the_bounded_contract()
    {
        var noCalls = new ScriptedAdapter((_, token) => Events(token, new AdapterFinal("tool_calls")));
        await using var shortcut = AsyncClient.FromAdapters([new ProviderRegistration("fake", noCalls)]);
        var tool = new Tool(new ToolSpec("known", "", new JsonObject([])), (_, _) => ValueTask.FromResult<object?>("ok"));
        var request = new GenerationRequest([Message.User("question")], new Route(["fake:model"]));
        var completed = await shortcut.RunToolsAsync(request, [tool]);
        Assert.Equal("tool_calls", completed.FinishReason);
        Assert.Single(noCalls.Requests);

        var neverCalled = new ScriptedAdapter((_, token) => Events(token, new AdapterFinal("stop")));
        await using var bounded = AsyncClient.FromAdapters([new ProviderRegistration("fake", neverCalled)]);
        await Assert.ThrowsAsync<ToolLoopException>(() => bounded.RunToolsAsync(request, [tool], maxRounds: 0));
        await Assert.ThrowsAsync<ToolLoopException>(() => bounded.RunToolsAsync(request, [tool], maxRounds: -1));
        Assert.Empty(neverCalled.Requests);

        var calls = 0;
        var looping = new ScriptedAdapter((_, token) => Events(token,
            new AdapterToolCallDelta(0, "same", "known", "{}"),
            new AdapterToolCallDelta(1, "same", "missing", "{}"),
            new AdapterFinal("tool_calls")));
        await using var unknown = AsyncClient.FromAdapters([new ProviderRegistration("fake", looping)]);
        var counted = new Tool(new ToolSpec("known", "", new JsonObject([])), (_, _) =>
        {
            calls++;
            return ValueTask.FromResult<object?>("ok");
        });
        await Assert.ThrowsAsync<ToolLoopException>(() => unknown.RunToolsAsync(request, [counted], maxRounds: 1));
        Assert.Equal(1, calls);
    }

    [Fact]
    public void Sync_facade_forwards_registered_tools_and_returns_the_actual_final_round()
    {
        var turn = 0;
        var adapter = new ScriptedAdapter((_, token) => ++turn == 1
            ? Events(token, new AdapterToolCallDelta(0, "call", "lookup", "{}"), new AdapterFinal("tool_calls"))
            : Events(token, new AdapterTextDelta("sync done"), new AdapterFinal("stop")));
        using var client = Client.FromAdapters([new ProviderRegistration("fake", adapter)]);
        var tool = new Tool(new ToolSpec("lookup", "", new JsonObject([])), (_, _) => ValueTask.FromResult<object?>("ok"));

        var result = client.RunTools("question", [tool], target: "fake:model");

        Assert.Equal("sync done", result.Text);
        Assert.Equal(2, adapter.Requests.Count);
        Assert.Equal(["lookup"], adapter.Requests[0].Tools.Select(static spec => spec.Name));
    }

    private static async IAsyncEnumerable<AdapterEvent> Events(
        [EnumeratorCancellation] CancellationToken token,
        params AdapterEvent[] events)
    {
        foreach (var item in events)
        {
            token.ThrowIfCancellationRequested();
            yield return item;
            await Task.Yield();
        }
    }

    private static JsonObject Object(params (string Name, JsonValue Value)[] values) =>
        new(values.Select(static value => new JsonProperty(value.Name, value.Value)));

    private sealed class ScriptedAdapter(
        Func<WireRequest, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) : IProviderAdapter
    {
        internal List<WireRequest> Requests { get; } = [];

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(
            WireRequest request,
            CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            return script(request, cancellationToken);
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
