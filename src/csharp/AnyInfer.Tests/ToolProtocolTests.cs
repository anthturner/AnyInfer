using System.Net;
using System.Numerics;
using System.Text;
using System.Text.Json;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;
using JsonProperty = AnyInfer.Json.JsonProperty;

namespace AnyInfer.Tests;

/// <summary>Public raw-tool wire and adapter protocol coverage; this deliberately bypasses generation orchestration.</summary>
public sealed class ToolProtocolTests
{
    [Fact]
    public void Tool_values_and_wire_request_snapshot_preserve_explicit_false_empty_and_named_choice_without_eager_matching()
    {
        var annotations = new ToolAnnotations(title: "", readOnly: false);
        Assert.True(annotations.Stated);
        Assert.Equal("", annotations.Title);
        Assert.False(annotations.ReadOnly);
        Assert.False(new ToolAnnotations().Stated);

        var inputParameters = new JsonObject([new JsonProperty("type", new JsonString("object"))]);
        var supplied = new List<ToolSpec> { new ToolSpec("record_colour", "Tool description", inputParameters) };
        var request = Request(tools: supplied, toolChoice: "not-present");
        supplied.Clear();
        Assert.Single(request.Tools);
        Assert.Equal("not-present", request.ToolChoice);
        Assert.Same(inputParameters, request.Tools[0].Parameters);

        var noTools = Request();
        Assert.Empty(noTools.Tools);
        Assert.Equal("auto", noTools.ToolChoice);
        Assert.Throws<ArgumentException>(() => Request(tools: [], toolChoice: "required"));
        Assert.Throws<ArgumentNullException>(() => new ToolSpec("tool", "description", null!));
    }

    [Fact]
    public async Task Tools_enable_exact_function_payload_named_choice_and_tool_only_buffered_order_with_modern_integer_lexeme()
    {
        const string giant = "100000000000000000000000000000000000000000000000000000000000000000000000000";
        var parameters = new JsonObject([
            new JsonProperty("type", new JsonString("object")),
            new JsonProperty("const", new JsonInteger(BigInteger.Parse(giant))),
        ]);
        var tool = new ToolSpec("record_colour", "Record the colour.", parameters, new ToolAnnotations("hidden", destructive: false));
        var response = CreateTrackingResponse(HttpStatusCode.OK, "application/json", """
            {"choices":[{"message":{"content":null,"tool_calls":[{"index":0,"id":"call-1","function":{"name":"record_colour","arguments":"{\"colour\":\"blue\"}"}}]},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}
            """);
        var handler = new RecordingHandler(response);
        await using var adapter = Builtin(handler);

        var events = await Collect(adapter.GenerateAsync(Request(tools: [tool], toolChoice: "record_colour")));

        using var body = JsonDocument.Parse(Assert.Single(handler.Bodies));
        var root = body.RootElement;
        var function = root.GetProperty("tools")[0].GetProperty("function");
        Assert.Equal("function", root.GetProperty("tools")[0].GetProperty("type").GetString());
        Assert.Equal("record_colour", function.GetProperty("name").GetString());
        Assert.Equal("Record the colour.", function.GetProperty("description").GetString());
        Assert.Equal(giant, function.GetProperty("parameters").GetProperty("const").GetRawText());
        Assert.False(function.TryGetProperty("annotations", out _));
        Assert.Equal("function", root.GetProperty("tool_choice").GetProperty("type").GetString());
        Assert.Equal("record_colour", root.GetProperty("tool_choice").GetProperty("function").GetProperty("name").GetString());
        Assert.Collection(events,
            item =>
            {
                var toolDelta = Assert.IsType<AdapterToolCallDelta>(item);
                Assert.Equal(0, toolDelta.Index);
                Assert.Equal("call-1", toolDelta.CallId);
                Assert.Equal("record_colour", toolDelta.Name);
                Assert.Equal("{\"colour\":\"blue\"}", toolDelta.ArgumentsFragment);
            },
            item => Assert.Equal(3, Assert.IsType<AdapterUsage>(item).Usage.TotalTokens),
            item => Assert.Equal("tool_calls", Assert.IsType<AdapterFinal>(item).FinishReason));

        Assert.True(response.Disposed);
        await adapter.DisposeAsync();
        Assert.True(handler.Disposed);
    }

    [Theory]
    [InlineData("auto")]
    [InlineData("required")]
    [InlineData("none")]
    public async Task Standard_tool_choices_encode_as_their_exact_raw_strings(string choice)
    {
        var handler = new RecordingHandler(CreateTrackingResponse(HttpStatusCode.OK, "application/json", BufferedText("ok")));
        await using var adapter = Builtin(handler);

        await Collect(adapter.GenerateAsync(Request(tools: [Tool("known")], toolChoice: choice)));

        using var body = JsonDocument.Parse(Assert.Single(handler.Bodies));
        Assert.Equal(choice, body.RootElement.GetProperty("tool_choice").GetString());
    }

    [Fact]
    public async Task Default_raw_request_omits_tools_and_ignores_unsolicited_tool_calls_without_changing_event_shape()
    {
        var response = CreateTrackingResponse(HttpStatusCode.OK, "application/json", """
            {"choices":[{"message":{"content":"text","tool_calls":[{"index":0,"id":"ignored","function":{"name":"ignored","arguments":"{}"}}]},"finish_reason":"stop"}]}
            """);
        var handler = new RecordingHandler(response);
        await using var adapter = Builtin(handler);

        var events = await Collect(adapter.GenerateAsync(Request()));

        using var body = JsonDocument.Parse(Assert.Single(handler.Bodies));
        Assert.False(body.RootElement.TryGetProperty("tools", out _));
        Assert.False(body.RootElement.TryGetProperty("tool_choice", out _));
        Assert.Collection(events,
            item => Assert.Equal("text", Assert.IsType<AdapterTextDelta>(item).Text),
            item => Assert.Equal("stop", Assert.IsType<AdapterFinal>(item).FinishReason));
        Assert.True(response.Disposed);
    }

    [Fact]
    public async Task Buffered_tool_decoder_keeps_python_boolean_indices_and_position_fallbacks_without_synthesizing_fields()
    {
        var handler = new RecordingHandler(CreateTrackingResponse(HttpStatusCode.OK, "application/json", """
            {"choices":[{"message":{"tool_calls":[null,{"id":5,"function":"invalid"},{"index":false,"id":null,"function":{"name":null,"arguments":null}},{"index":"bad","function":{"name":"later","arguments":"x"}},{"index":true,"function":{"arguments":"yes"}}]},"finish_reason":"stop"}]}
            """));
        await using var adapter = Builtin(handler);

        var events = await Collect(adapter.GenerateAsync(Request(tools: [Tool("declared")] )));
        var deltas = events.OfType<AdapterToolCallDelta>().ToArray();
        Assert.Collection(deltas,
            first => { Assert.Equal(1, first.Index); Assert.Null(first.CallId); Assert.Null(first.Name); Assert.Equal("", first.ArgumentsFragment); },
            second => { Assert.Equal(0, second.Index); Assert.Null(second.CallId); Assert.Null(second.Name); Assert.Equal("", second.ArgumentsFragment); },
            third => { Assert.Equal(3, third.Index); Assert.Null(third.CallId); Assert.Equal("later", third.Name); Assert.Equal("x", third.ArgumentsFragment); },
            fourth => { Assert.Equal(1, fourth.Index); Assert.Null(fourth.CallId); Assert.Null(fourth.Name); Assert.Equal("yes", fourth.ArgumentsFragment); });
        Assert.Equal("stop", Assert.IsType<AdapterFinal>(events[^1]).FinishReason);
    }

    [Fact]
    public async Task Out_of_native_range_tool_index_is_instance_attributed_nonretryable_protocol_failure()
    {
        var content = new TrackingContent(Encoding.UTF8.GetBytes("""
            {"choices":[{"message":{"tool_calls":[{"index":999999999999999999999999999999,"function":{"arguments":""}}]}}]}
            """), "application/json");
        var response = new TrackingResponse(HttpStatusCode.OK, content);
        var handler = new RecordingHandler(response);
        await using var adapter = Builtin(handler, "raw-tools");

        var failure = await Assert.ThrowsAsync<StreamProtocolException>(() => Collect(adapter.GenerateAsync(Request(tools: [Tool("declared")]))));
        Assert.Equal("raw-tools", failure.Provider);
        Assert.Equal("stream", failure.Phase);
        Assert.False(failure.Retryable);
        Assert.DoesNotContain("999999999999999999999999999999", failure.Detail, StringComparison.Ordinal);
        Assert.True(response.Disposed);
        Assert.True(content.Disposed);
    }

    [Fact]
    public async Task Sse_tool_argument_fragments_preserve_per_index_order_before_usage_and_final()
    {
        var sse = Sse(
            """{"choices":[{"delta":{"content":"prefix","tool_calls":[{"index":2,"id":"call-2","function":{"name":"record_colour","arguments":"{\"co"}}]}}]}""",
            """{"choices":[{"delta":{"tool_calls":[{"index":2,"function":{"arguments":"lour\":\"blue\"}"}},{"index":0,"id":"call-0","function":{"name":"other","arguments":"{}"}}]}}]}""",
            """{"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}""",
            """{"choices":[{"delta":{},"finish_reason":"tool_calls"}]}""",
            "[DONE]");
        var response = CreateTrackingResponse(HttpStatusCode.OK, "text/event-stream", sse);
        var handler = new RecordingHandler(response);
        await using var adapter = Builtin(handler);

        var events = await Collect(adapter.GenerateAsync(Request(stream: true, tools: [Tool("record_colour"), Tool("other")], toolChoice: "required")));

        Assert.Collection(events,
            item => Assert.Equal("prefix", Assert.IsType<AdapterTextDelta>(item).Text),
            item => { var delta = Assert.IsType<AdapterToolCallDelta>(item); Assert.Equal(2, delta.Index); Assert.Equal("call-2", delta.CallId); Assert.Equal("{\"co", delta.ArgumentsFragment); },
            item => { var delta = Assert.IsType<AdapterToolCallDelta>(item); Assert.Equal(2, delta.Index); Assert.Null(delta.CallId); Assert.Equal("lour\":\"blue\"}", delta.ArgumentsFragment); },
            item => { var delta = Assert.IsType<AdapterToolCallDelta>(item); Assert.Equal(0, delta.Index); Assert.Equal("call-0", delta.CallId); Assert.Equal("other", delta.Name); },
            item => Assert.Equal(6, Assert.IsType<AdapterUsage>(item).Usage.TotalTokens),
            item => Assert.Equal("tool_calls", Assert.IsType<AdapterFinal>(item).FinishReason));
        Assert.True(response.Disposed);
    }

    private static ToolSpec Tool(string name) => new(name, "Tool description", new JsonObject([
        new JsonProperty("type", new JsonString("object")),
        new JsonProperty("properties", new JsonObject([])),
    ]));

    private static WireRequest Request(bool stream = false, IEnumerable<ToolSpec>? tools = null, string toolChoice = "auto") =>
        new("fixture-model", [new Message("user", [new Text("hello")])], new Sampling(), stream: stream, tools: tools, toolChoice: toolChoice);

    private static IProviderAdapter Builtin(RecordingHandler handler, string instance = "fixture")
    {
        var descriptor = ProviderRegistry.CreateDefault().Get("openai-compat");
        var settings = ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", "fixture-secret", transport: handler, alias: instance);
        return (IProviderAdapter)descriptor.Factory(new ProviderConfig(settings, "openai-compat", "fixture-secret"), CancellationToken.None).Result;
    }

    private static async Task<List<AdapterEvent>> Collect(IAsyncEnumerable<AdapterEvent> source)
    {
        var events = new List<AdapterEvent>();
        await foreach (var item in source) events.Add(item);
        return events;
    }

    private static string BufferedText(string text) => $$"""{"choices":[{"message":{"content":"{{text}}"},"finish_reason":"stop"}]}""";
    private static string Sse(params string[] frames) => string.Concat(frames.Select(static frame => "data: " + frame + "\n\n"));

    private static TrackingResponse CreateTrackingResponse(HttpStatusCode status, string contentType, string body) =>
        new(status, new TrackingContent(Encoding.UTF8.GetBytes(body), contentType));

    private sealed class RecordingHandler(params HttpResponseMessage[] responses) : HttpMessageHandler
    {
        private readonly Queue<HttpResponseMessage> _responses = new(responses);
        internal List<string> Bodies { get; } = [];
        internal bool Disposed { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Bodies.Add(Encoding.UTF8.GetString(await request.Content!.ReadAsByteArrayAsync(cancellationToken)));
            return _responses.Dequeue();
        }

        protected override void Dispose(bool disposing)
        {
            Disposed = true;
            base.Dispose(disposing);
        }
    }

    private sealed class TrackingResponse : HttpResponseMessage
    {
        public TrackingResponse(HttpStatusCode status, HttpContent content) : base(status) => Content = content;
        internal bool Disposed { get; private set; }
        protected override void Dispose(bool disposing) { Disposed = true; base.Dispose(disposing); }
    }

    private sealed class TrackingContent : HttpContent
    {
        private readonly byte[] _bytes;
        public TrackingContent(byte[] bytes, string contentType)
        {
            _bytes = bytes;
            Headers.ContentType = System.Net.Http.Headers.MediaTypeHeaderValue.Parse(contentType);
        }
        internal bool Disposed { get; private set; }
        protected override bool TryComputeLength(out long length) { length = _bytes.Length; return true; }
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => stream.WriteAsync(_bytes, 0, _bytes.Length);
        protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(new MemoryStream(_bytes, writable: false));
        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) => Task.FromResult<Stream>(new MemoryStream(_bytes, writable: false));
        protected override void Dispose(bool disposing) { Disposed = true; base.Dispose(disposing); }
    }
}
