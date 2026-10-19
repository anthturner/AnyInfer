using AnyInfer.Providers;
using System.Net;
using System.Net.Http.Headers;
using System.Text;
using Xunit;

namespace AnyInfer.Tests;

public sealed class ModernStreamHeaderTests
{
    [Fact]
    public async Task Public_modern_streaming_requests_event_stream_but_buffered_generation_does_not()
    {
        var streaming = new RecordingHandler(Response("text/event-stream", Sse(
            """{"choices":[{"delta":{"content":"streamed"}}]}""",
            """{"choices":[{"delta":{},"finish_reason":"stop"}]}""",
            "[DONE]")));
        await using (var client = CreateClient(streaming))
        {
            await foreach (var _ in client.StreamAsync("hello", target: "fixture:model")) { }
        }

        Assert.Equal(["text/event-stream"], Assert.Single(streaming.Requests).Accept);

        var buffered = new RecordingHandler(Response("application/json", """
            {"choices":[{"message":{"content":"buffered"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1}}
            """));
        await using (var client = CreateClient(buffered))
        {
            Assert.Equal("buffered", (await client.GenerateAsync("hello", target: "fixture:model")).Text);
        }

        Assert.Empty(Assert.Single(buffered.Requests).Accept);
    }

    [Fact]
    public async Task Modern_streaming_accept_overrides_the_configured_default_but_buffered_generation_preserves_it()
    {
        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["aCcEpT"] = "application/x-fixture-stream",
        };
        var streaming = new RecordingHandler(Response("text/event-stream", Sse(
            """{"choices":[{"delta":{"content":"configured"}}]}""",
            """{"choices":[{"delta":{},"finish_reason":"stop"}]}""",
            "[DONE]")));
        await using (var client = CreateClient(streaming, headers))
        {
            await foreach (var _ in client.StreamAsync("hello", target: "fixture:model")) { }
        }

        Assert.Equal(["text/event-stream"], Assert.Single(streaming.Requests).Accept);

        var buffered = new RecordingHandler(Response("application/json", """
            {"choices":[{"message":{"content":"configured-buffered"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1}}
            """));
        await using (var client = CreateClient(buffered, headers))
        {
            Assert.Equal("configured-buffered", (await client.GenerateAsync("hello", target: "fixture:model")).Text);
        }

        Assert.Equal(["application/x-fixture-stream"], Assert.Single(buffered.Requests).Accept);
    }

    [Fact]
    public async Task Direct_frozen_wire_stream_keeps_its_existing_accept_behavior()
    {
        var handler = new RecordingHandler(Response("text/event-stream", Sse(
            """{"choices":[{"delta":{"content":"legacy"}}]}""",
            """{"choices":[{"delta":{},"finish_reason":"stop"}]}""",
            "[DONE]")));
        await using var adapter = new OpenAIChatAdapter(new Uri("https://fixture.invalid/v1"), "fixture-token", handler: handler);

        await foreach (var _ in adapter.GenerateAsync(new WireRequest(
            "fixture-model",
            [Message.User("legacy")],
            new Sampling(),
            stream: true,
            timeoutS: 120,
            maxResponseBytes: 1_048_576))) { }

        Assert.Empty(Assert.Single(handler.Requests).Accept);
    }

    private static AsyncClient CreateClient(RecordingHandler handler, IReadOnlyDictionary<string, string>? headers = null) =>
        new([ProviderSettings.Of(
            "openai-compat",
            baseUrl: "https://fixture.invalid/v1",
            apiKey: "fixture-token",
            headers: headers,
            transport: handler,
            alias: "fixture")]);

    private static HttpResponseMessage Response(string contentType, string body)
    {
        var content = new ByteArrayContent(Encoding.UTF8.GetBytes(body));
        content.Headers.ContentType = MediaTypeHeaderValue.Parse(contentType);
        return new HttpResponseMessage(HttpStatusCode.OK) { Content = content };
    }

    private static string Sse(params string[] events) => string.Concat(events.Select(static item => "data: " + item + "\n\n"));

    private sealed record CapturedRequest(IReadOnlyList<string> Accept);

    private sealed class RecordingHandler(HttpResponseMessage response) : HttpMessageHandler
    {
        private HttpResponseMessage? _response = response;

        internal List<CapturedRequest> Requests { get; } = [];

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var accept = request.Headers.TryGetValues("Accept", out var values) ? values.ToArray() : [];
            Requests.Add(new CapturedRequest(accept));
            return Task.FromResult(_response ?? throw new InvalidOperationException("The real handler received an unexpected extra request."));
        }
    }
}
