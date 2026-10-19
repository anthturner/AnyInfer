using System.Runtime.CompilerServices;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using AnyInfer.Capabilities;
using AnyInfer.Core;
using AnyInfer.Credentials;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public raw-tool request, result assembly, feedback, and sizing controls.</summary>
public sealed class RawToolGenerationTests
{
    [Fact]
    public async Task Public_tools_and_choice_survive_normalization_and_typed_feedback_survives_messages()
    {
        var adapter = new CaptureAdapter((_, token) => Events(token, new AdapterTextDelta("ok"), new AdapterFinal("stop")));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("fake", adapter)]);
        var tool = Tool("weather", "weather lookup", "city");
        var request = new GenerationRequest(
            [new Message("assistant", [new Text("call"), new ToolCall("call-1", "weather", Object("{\"city\":\"Boston\"}"))])], new Route(["fake:model"]),
            tools: [tool], toolChoice: "required");

        var result = await client.GenerateAsync(request);
        Assert.Equal("ok", result.Text);
        var wire = Assert.Single(adapter.Requests);
        Assert.Equal([tool], wire.Tools);
        Assert.Equal("required", wire.ToolChoice);
        var call = Assert.IsType<ToolCall>(wire.Messages.Single().Content[1]);
        Assert.Equal("call-1", call.Id);
        Assert.Equal("weather", call.Name);
        Assert.True(JsonEquality.TypeAwareEquals(Object("{\"city\":\"Boston\"}"), call.Arguments));
    }

    [Fact]
    public async Task Empty_tools_with_none_choice_are_accepted_and_omitted_from_modern_wire()
    {
        var adapter = new CaptureAdapter((_, token) => Events(token, new AdapterFinal("stop")));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("fake", adapter)]);

        await client.GenerateAsync(new GenerationRequest([Message.User("empty")], new Route(["fake:model"]), tools: [], toolChoice: "none"));

        var wire = Assert.Single(adapter.Requests);
        Assert.Empty(wire.Tools);
        Assert.Equal("none", wire.ToolChoice);
    }

    [Fact]
    public async Task Fragmented_tool_calls_use_index_order_latest_truthy_identity_object_arguments_and_tool_finish()
    {
        var adapter = new CaptureAdapter((_, token) => Events(token,
            new AdapterToolCallDelta(2, null, null, "{\"b\":"),
            new AdapterToolCallDelta(0, "first", "alpha", "not-object"),
            new AdapterToolCallDelta(2, "last", "beta", "2}"),
            new AdapterToolCallDelta(1, null, null, "[1]"),
            new AdapterFinal("stop")));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("fake", adapter)]);

        var result = await client.GenerateAsync("tools", target: "fake:model");

        Assert.Equal("tool_calls", result.FinishReason);
        Assert.Collection(result.ToolCalls,
            call => { Assert.Equal("first", call.Id); Assert.Equal("alpha", call.Name); Assert.Empty(call.Arguments.Properties); },
            call => { Assert.Equal("call_1", call.Id); Assert.Equal(string.Empty, call.Name); Assert.Empty(call.Arguments.Properties); },
            call => { Assert.Equal("last", call.Id); Assert.Equal("beta", call.Name); Assert.True(JsonEquality.TypeAwareEquals(Object("{\"b\":2}"), call.Arguments)); });
        Assert.Equal(2, result.Warnings.Count);
    }

    [Fact]
    public async Task Empty_tool_delta_marks_first_content_and_prevents_retry_after_stream_protocol_failure()
    {
        var calls = new Counter();
        var retryable = new StreamProtocolException("after empty tool delta", phase: "stream", retryable: true);
        var adapter = new CaptureAdapter((_, token) => EmptyDeltaThenThrow(token, calls, retryable));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("fake", adapter)]);
        var stream = client.StreamAsync(new GenerationRequest([Message.User("tool")], new Route(["fake:model"], new Retry(2, 0, 0))));
        var publicEvents = new List<StreamEvent>();

        var thrown = await Assert.ThrowsAsync<StreamProtocolException>(async () =>
        {
            await foreach (var item in stream) publicEvents.Add(item);
        });

        Assert.Same(retryable, thrown);
        Assert.Contains(publicEvents, static item => item is TimingMark { Name: "first_token" });
        Assert.Contains(publicEvents, static item => item is ToolCallDelta { Index: 0, ArgumentsFragment: "" });
        Assert.Equal(1, calls.Value);
    }

    [Fact]
    public async Task Frozen_profile_ignores_tool_deltas_without_first_content_or_terminal_calls()
    {
        var adapter = new CaptureAdapter((_, token) => Events(token, new AdapterToolCallDelta(0, "id", "tool", "{}"), new AdapterFinal("stop")));
        await using var client = new AsyncClient([new ProviderRegistration("fake", adapter)], new SystemOperationClock());
        var stream = client.StreamAsync(new GenerationRequest([Message.User("frozen")], new Route(["fake:model"])));
        var events = new List<StreamEvent>();

        await foreach (var item in stream) events.Add(item);

        Assert.DoesNotContain(events, static item => item is ToolCallDelta or TimingMark { Name: "first_token" });
        Assert.Empty(stream.Result.ToolCalls);
    }

    [Fact]
    public async Task Typed_tool_feedback_survives_public_normalization_for_adapter_projection()
    {
        var handler = new CaptureAdapter((_, token) => Events(token, new AdapterFinal("stop")));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("fake", handler)]);
        var request = new GenerationRequest(
            [new Message("assistant", [new Text("before"), new ToolResult("call-a", "first", isError: true), new ToolResult("call-b", "second"), new Text("after")])],
            new Route(["fake:model"]));

        await client.GenerateAsync(request);
        var message = Assert.Single(Assert.Single(handler.Requests).Messages);
        Assert.Equal("assistant", message.Role);
        var result = Assert.IsType<ToolResult>(message.Content[1]);
        Assert.Equal("call-a", result.CallId);
        Assert.Equal("first", result.Content);
        Assert.True(result.IsError);
    }

    [Fact]
    public void Estimation_flattens_typed_parts_then_each_tool_then_schema_in_literal_accounting_order()
    {
        var estimator = new RecordingEstimator();
        var request = new GenerationRequest(
            [new Message("assistant", [new Text("a"), new ToolCall("id", "fn", Object("{\"z\":1}")), new ToolResult("id", "done")])],
            new Route(["fake:model"]),
            schema: new SchemaSpec(Object("{\"type\":\"object\"}")),
            tools: [Tool("one", "first", "a"), Tool("two", "second", "b")]);

        _ = TokenEstimation.EstimateRequest(request, estimator);

        Assert.Equal([
            "afn{\"z\": 1}done",
            "{\"name\": \"one\", \"description\": \"first\", \"parameters\": {\"type\": \"object\", \"properties\": {\"a\": {\"type\": \"string\"}}}}",
            "{\"name\": \"two\", \"description\": \"second\", \"parameters\": {\"type\": \"object\", \"properties\": {\"b\": {\"type\": \"string\"}}}}",
            "{\"type\": \"object\"}",
        ], estimator.Inputs);
    }

    [Fact]
    public async Task Builtin_projects_only_first_tool_result_and_call_only_messages_with_python_argument_spaces()
    {
        var handler = new ToolProjectionHandler();
        var adapter = new OpenAIChatAdapter(new Uri("https://fixture.invalid/v1"), "secret", handler: handler);
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("openai-compat", adapter)]);
        var arguments = Object("{\"city\":\"Böstön\"}");

        await client.GenerateAsync(
            new GenerationRequest([new Message("assistant", [new Text("ignored"), new ToolResult("first", "first-output", true), new ToolResult("second", "second-output")])], new Route(["openai-compat:model"])));
        await client.GenerateAsync(
            new GenerationRequest([new Message("assistant", [new ToolCall("call-1", "weather", arguments)])], new Route(["openai-compat:model"])));
        await client.GenerateAsync(
            new GenerationRequest([new Message("tool", [new Text("attached text"), new ToolCall("call-role", "weather", Object("{\"unit\":\"c\"}"))])], new Route(["openai-compat:model"])));

        var feedback = handler.Bodies[0].RootElement.GetProperty("messages")[0];
        Assert.Equal("tool", feedback.GetProperty("role").GetString());
        Assert.Equal("first", feedback.GetProperty("tool_call_id").GetString());
        Assert.Equal("first-output", feedback.GetProperty("content").GetString());
        Assert.False(feedback.TryGetProperty("is_error", out _));

        var call = handler.Bodies[1].RootElement.GetProperty("messages")[0];
        Assert.Equal("assistant", call.GetProperty("role").GetString());
        Assert.Equal(JsonValueKind.Null, call.GetProperty("content").ValueKind);
        var function = call.GetProperty("tool_calls")[0].GetProperty("function");
        Assert.Equal("weather", function.GetProperty("name").GetString());
        Assert.Equal("{\"city\": \"B\\u00f6st\\u00f6n\"}", function.GetProperty("arguments").GetString());

        var roleTool = handler.Bodies[2].RootElement.GetProperty("messages")[0];
        Assert.Equal("tool", roleTool.GetProperty("role").GetString());
        Assert.Equal("attached text", roleTool.GetProperty("content").GetString());
        Assert.Equal("weather", roleTool.GetProperty("tool_calls")[0].GetProperty("function").GetProperty("name").GetString());
    }

    [Fact]
    public async Task Tool_argument_payloads_are_default_private_and_explicitly_captured_redacted_in_call_order()
    {
        const string secret = "raw-tool-secret-unique";
        Redaction.RegisterSecret(secret);
        var events = new AdapterEvent[]
        {
            new AdapterToolCallDelta(1, "second", "two", "{\"token\":\"" + secret + "\"}"),
            new AdapterToolCallDelta(0, "first", "one", "{\"z\":1,\"a\":2}"),
            new AdapterFinal("stop"),
        };
        var privateAdapter = new CaptureAdapter((_, token) => Events(token, events));
        await using var privateClient = AsyncClient.FromAdapters([new ProviderRegistration("fake", privateAdapter)]);
        var privateResult = await privateClient.GenerateAsync("private", target: "fake:model");
        Assert.NotNull(privateResult.Manifest);
        Assert.Null(privateResult.Manifest!.Payloads);
        Assert.Null(privateResult.WithManifest(privateResult.Manifest).Manifest!.Payloads);

        var capturedAdapter = new CaptureAdapter((_, token) => Events(token, events));
        var observer = new Collector();
        await using var capturedClient = AsyncClient.FromAdapters([new ProviderRegistration("fake", capturedAdapter)], observers: [observer], manifestPayloads: true);
        var stream = capturedClient.StreamAsync("captured", target: "fake:model");
        var captured = await stream.CollectAsync();
        Assert.Same(captured.Manifest, stream.Manifest);
        Assert.NotNull(captured.Manifest!.Payloads);
        Assert.Equal(["{\"a\": 2, \"z\": 1}", "{\"token\": \"[redacted]\"}"], captured.Manifest.Payloads!.ToolArguments);
        Assert.DoesNotContain(secret, string.Concat(captured.Manifest.Payloads.ToolArguments));
        Assert.Same(captured.Manifest, captured.WithManifest(captured.Manifest).Manifest);
        Assert.Single(observer.Events.OfType<RequestCompleted>());
    }

    [Fact]
    public async Task Builtin_decodes_undeclared_tool_calls_in_buffered_and_sse_public_modern_requests_without_sending_tools()
    {
        var handler = new UndeclaredToolCallsHandler(
            ("application/json", """
                {"choices":[{"message":{"content":null,"tool_calls":[{"index":0,"id":"buffered","function":{"name":"weather","arguments":"{\"city\":\"Boston\"}"}}]},"finish_reason":"tool_calls"}]}
                """),
            ("text/event-stream", """
                data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"sse","function":{"name":"weather","arguments":"{\"city\":\"Boston\"}"}}]}}]}

                data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}

                data: [DONE]
                """ + "\n\n"));
        var adapter = new OpenAIChatAdapter(new Uri("https://fixture.invalid/v1"), "secret", handler: handler);
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("openai-compat", adapter)]);

        var buffered = await client.GenerateAsync("buffered", target: "openai-compat:model");
        var stream = client.StreamAsync(new GenerationRequest([Message.User("sse")], new Route(["openai-compat:model"]), stream: true));
        var publicEvents = new List<StreamEvent>();
        await foreach (var item in stream) publicEvents.Add(item);

        Assert.Collection(buffered.ToolCalls, call =>
        {
            Assert.Equal("buffered", call.Id);
            Assert.Equal("weather", call.Name);
            Assert.True(JsonEquality.TypeAwareEquals(Object("{\"city\":\"Boston\"}"), call.Arguments));
        });
        Assert.Equal("tool_calls", buffered.FinishReason);
        Assert.Contains(publicEvents, static item => item is TimingMark { Name: "first_token" });
        Assert.Contains(publicEvents, static item => item is ToolCallDelta { Index: 0, CallId: "sse", Name: "weather" });
        Assert.Equal("tool_calls", stream.Result.FinishReason);
        Assert.Equal("sse", Assert.Single(stream.Result.ToolCalls).Id);

        Assert.Equal(2, handler.Bodies.Count);
        foreach (var body in handler.Bodies)
        {
            Assert.False(body.RootElement.TryGetProperty("tools", out _));
            Assert.False(body.RootElement.TryGetProperty("tool_choice", out _));
        }
    }

    [Fact]
    public async Task Retry_and_schema_correction_publish_only_the_winning_tool_call_state()
    {
        var retryCalls = new Counter();
        var retryAdapter = new CaptureAdapter((_, token) =>
        {
            if (Interlocked.Increment(ref retryCalls.Value) == 1)
            {
                return ToolDeltaThenThrow(token,
                    new AdapterToolCallDelta(7, "discarded-retry", "discarded-tool", "not-an-object"),
                    new TransportException("retry", retryable: true, phase: "generate"));
            }

            return Events(token,
                new AdapterToolCallDelta(0, "retry-winner", "weather", "{}"),
                new AdapterFinal("tool_calls"));
        });
        await using var retryClient = AsyncClient.FromAdapters([new ProviderRegistration("fake", retryAdapter)]);
        var retried = await retryClient.GenerateAsync(new GenerationRequest(
            [Message.User("retry")], new Route(["fake:model"], new Retry(2, 0, 0))));

        Assert.Equal(2, retryCalls.Value);
        Assert.Equal("retry-winner", Assert.Single(retried.ToolCalls).Id);
        Assert.Equal("tool_calls", retried.FinishReason);
        Assert.DoesNotContain(retried.ToolCalls, static call => call.Id == "discarded-retry");
        Assert.Empty(retried.Warnings);

        var correctionCalls = new Counter();
        var correctionAdapter = new CaptureAdapter((_, token) =>
        {
            if (Interlocked.Increment(ref correctionCalls.Value) == 1)
            {
                return Events(token,
                    new AdapterToolCallDelta(0, "discarded-correction", "weather", "not-an-object"),
                    new AdapterTextDelta("\"wrong\""),
                    new AdapterFinal("stop"));
            }

            return Events(token,
                new AdapterToolCallDelta(0, "correction-winner", "weather", "{}"),
                new AdapterTextDelta("\"correct\""),
                new AdapterFinal("stop"));
        });
        await using var correctionClient = AsyncClient.FromAdapters([new ProviderRegistration("fake", correctionAdapter)]);
        var corrected = await correctionClient.GenerateAsync(new GenerationRequest(
            [Message.User("correct")], new Route(["fake:model"]),
            schema: new SchemaSpec(Object("{\"const\":\"correct\"}")), repair: new Repair(1)));

        Assert.Equal(2, correctionCalls.Value);
        Assert.Equal("correction-winner", Assert.Single(corrected.ToolCalls).Id);
        Assert.Equal("correct", Assert.IsType<JsonString>(corrected.Structured).Value);
        Assert.DoesNotContain(corrected.ToolCalls, static call => call.Id == "discarded-correction");
        Assert.Empty(corrected.Warnings);
    }

    private static ToolSpec Tool(string name, string description, string property) => new(name, description, Object($"{{\"type\":\"object\",\"properties\":{{\"{property}\":{{\"type\":\"string\"}}}}}}"));
    private static JsonObject Object(string value) => Assert.IsType<JsonObject>(JsonReader.Read(value));
    private static async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken token, params AdapterEvent[] events)
    {
        foreach (var item in events) { token.ThrowIfCancellationRequested(); yield return item; await Task.Yield(); }
    }
    private static async IAsyncEnumerable<AdapterEvent> EmptyDeltaThenThrow([EnumeratorCancellation] CancellationToken token, Counter calls, Exception failure)
    {
        Interlocked.Increment(ref calls.Value);
        yield return new AdapterToolCallDelta(0, null, null, "");
        await Task.Yield();
        token.ThrowIfCancellationRequested();
        System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        yield break;
    }
    private static async IAsyncEnumerable<AdapterEvent> ToolDeltaThenThrow([EnumeratorCancellation] CancellationToken token, AdapterToolCallDelta delta, Exception failure)
    {
        token.ThrowIfCancellationRequested();
        yield return delta;
        await Task.Yield();
        token.ThrowIfCancellationRequested();
        System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        yield break;
    }

    private sealed class CaptureAdapter(Func<WireRequest, CancellationToken, IAsyncEnumerable<AdapterEvent>> events) : IProviderAdapter
    {
        internal List<WireRequest> Requests { get; } = [];
        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) { Requests.Add(request); return events(request, cancellationToken); }
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
    private sealed class RecordingEstimator : ITokenEstimator
    {
        internal List<string> Inputs { get; } = [];
        public TokenEstimate Estimate(string value) { Inputs.Add(value); return new TokenEstimate(1, 1); }
    }
    private sealed class Counter { internal int Value; }

    private sealed class Collector : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];
        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent);
    }

    private sealed class ToolProjectionHandler : HttpMessageHandler
    {
        internal List<JsonDocument> Bodies { get; } = [];
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Assert.Equal(HttpMethod.Post, request.Method);
            Bodies.Add(JsonDocument.Parse(await request.Content!.ReadAsStringAsync(cancellationToken)));
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("""{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}""", Encoding.UTF8, "application/json"),
            };
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing) foreach (var body in Bodies) body.Dispose();
            base.Dispose(disposing);
        }
    }

    private sealed class UndeclaredToolCallsHandler(params (string ContentType, string Body)[] responses) : HttpMessageHandler
    {
        private readonly Queue<(string ContentType, string Body)> _responses = new(responses);
        internal List<JsonDocument> Bodies { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Bodies.Add(JsonDocument.Parse(await request.Content!.ReadAsStringAsync(cancellationToken)));
            var response = _responses.Dequeue();
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(response.Body, Encoding.UTF8, response.ContentType),
            };
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) foreach (var body in Bodies) body.Dispose();
            base.Dispose(disposing);
        }
    }
}
