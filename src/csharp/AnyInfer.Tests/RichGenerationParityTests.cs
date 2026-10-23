using System.Runtime.CompilerServices;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public modern-wire schema parity controls for rich-generation requests.</summary>
public sealed class RichGenerationParityTests
{
    [Theory]
    [InlineData("none")]
    [InlineData("prompt")]
    [InlineData("json_mode")]
    [InlineData("json_schema")]
    public async Task Configured_public_client_projects_schema_name_schema_and_prompt_by_selected_mechanism(string mode)
    {
        var profile = mode switch
        {
            "none" or "prompt" => new StructuredOutputProfile(),
            "json_mode" => new StructuredOutputProfile(JsonMode: true),
            "json_schema" => new StructuredOutputProfile(JsonSchema: true),
            _ => throw new ArgumentOutOfRangeException(nameof(mode)),
        };
        var adapter = new CapturingAdapter(mode == "none" ? "plain" : "\"ok\"");
        var descriptor = new ProviderDescriptor(
            "rich", "rich", (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
            structuredOutputProfiles: new Dictionary<string, StructuredOutputProfile> { ["model"] = profile });
        await using var client = new AsyncClient([ProviderSettings.Of("rich")], new ProviderRegistry([descriptor]));
        var schema = new SchemaSpec(SchemaSpec.FromJson("{\"type\":\"string\"}").JsonSchema, "answer");

        _ = mode == "none"
            ? await client.GenerateAsync(Message.User("question").Text, target: "rich:model")
            : await client.GenerateAsync(Message.User("question").Text, target: "rich:model", schema: schema);

        var wire = Assert.Single(adapter.Requests);
        switch (mode)
        {
            case "none":
                Assert.Null(wire.Mechanism);
                Assert.Null(wire.Schema);
                Assert.Null(wire.SchemaName);
                Assert.Single(wire.Messages);
                Assert.Equal("user", wire.Messages[0].Role);
                break;
            case "prompt":
            case "json_mode":
                Assert.Equal(mode, wire.Mechanism);
                Assert.Null(wire.Schema);
                Assert.Equal("answer", wire.SchemaName);
                Assert.Equal(2, wire.Messages.Count);
                Assert.Equal("system", wire.Messages[0].Role);
                Assert.StartsWith("Respond with ONLY a JSON value matching this JSON Schema. No prose. Schema:\n", wire.Messages[0].Text, StringComparison.Ordinal);
                Assert.Equal("user", wire.Messages[1].Role);
                break;
            case "json_schema":
                Assert.Equal("json_schema", wire.Mechanism);
                Assert.Same(schema.JsonSchema, wire.Schema);
                Assert.Equal("answer", wire.SchemaName);
                Assert.Single(wire.Messages);
                Assert.Equal("user", wire.Messages[0].Role);
                break;
        }
    }

    [Fact]
    public void Legacy_public_wire_request_constructor_keeps_named_schema_name_and_response_default()
    {
        var schema = JsonReader.Read("{\"type\":\"string\"}");
        var named = new WireRequest(
            model: "model",
            messages: [Message.User("question")],
            sampling: new Sampling(),
            schema: schema,
            schemaName: "legacy-name");
        var defaulted = new WireRequest(
            model: "model",
            messages: [Message.User("question")],
            sampling: new Sampling());

        Assert.Same(schema, named.Schema);
        Assert.Equal("legacy-name", named.SchemaName);
        Assert.Equal("response", defaulted.SchemaName);
    }

    private sealed class CapturingAdapter(string response) : IProviderAdapter
    {
        internal List<WireRequest> Requests { get; } = [];

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            return Events(cancellationToken);
        }

        private async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            yield return new AdapterTextDelta(response);
            await Task.Yield();
            yield return new AdapterFinal("stop");
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
