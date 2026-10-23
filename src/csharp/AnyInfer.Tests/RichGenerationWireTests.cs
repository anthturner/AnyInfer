using System.Net;
using System.Text;
using System.Text.Json;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Focused HTTP controls for the native chat-completions rich projection.</summary>
public sealed class RichGenerationWireTests
{
    [Fact]
    public async Task Inline_media_preserves_order_and_encodes_document_audio_and_image_detail()
    {
        var handler = new Handler(
            Response("""{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}"""),
            Response("""{"choices":[{"message":{"content":"ordinary"},"finish_reason":"stop"}]}"""));
        await using var adapter = Adapter(handler);
        var request = Request(messages:
        [
            new Message("user", [
                new Text("before"),
                new ImagePart(url: "https://image.invalid/a.png", detail: "low"),
                new Text("between"),
                new DocumentPart(data: [112, 100, 102], filename: "report.pdf"),
                new AudioPart([109, 112, 51], "audio/mpeg"),
                new Text("after"),
            ]),
        ]);

        _ = await Collect(adapter.GenerateAsync(request));

        var content = Assert.Single(handler.Bodies).RootElement.GetProperty("messages")[0].GetProperty("content");
        Assert.Equal(["text", "image_url", "text", "file", "input_audio", "text"], content.EnumerateArray().Select(static item => item.GetProperty("type").GetString()));
        Assert.Equal("https://image.invalid/a.png", content[1].GetProperty("image_url").GetProperty("url").GetString());
        Assert.Equal("low", content[1].GetProperty("image_url").GetProperty("detail").GetString());
        Assert.Equal("data:application/pdf;base64,cGRm", content[3].GetProperty("file").GetProperty("file_data").GetString());
        Assert.Equal("report.pdf", content[3].GetProperty("file").GetProperty("filename").GetString());
        Assert.Equal("bXAz", content[4].GetProperty("input_audio").GetProperty("data").GetString());
        Assert.Equal("mp3", content[4].GetProperty("input_audio").GetProperty("format").GetString());
        Assert.NotNull(Assert.IsType<AdapterFinal>((await Collect(adapter.GenerateAsync(Request()))).Last()).Raw);
    }

    [Fact]
    public async Task Document_url_and_video_refuse_before_http_send()
    {
        var handler = new Handler(Response("""{"choices":[{"message":{"content":"unused"}}]}"""));
        await using var adapter = Adapter(handler);

        await Assert.ThrowsAsync<UnsupportedInputException>(() => Collect(adapter.GenerateAsync(Request(messages: [new Message("user", [new DocumentPart(url: "https://file.invalid/a.pdf")])]))));
        await Assert.ThrowsAsync<UnsupportedInputException>(() => Collect(adapter.GenerateAsync(Request(messages: [new Message("user", [new VideoPart(url: "https://video.invalid/a.mp4")])]))));
        Assert.Empty(handler.Bodies);
    }

    [Fact]
    public async Task Logprob_request_and_buffered_response_keep_actual_raw_and_skip_malformed_entries()
    {
        var handler = new Handler(Response("""
            {"choices":[{"message":{"content":"ok"},"finish_reason":"stop","logprobs":{"content":[{"token":"o","logprob":-0.1,"bytes":[111],"top_logprobs":[{"token":"x","logprob":-1.0,"bytes":[120]}]},{"token":7,"logprob":0}]}}]}
            """));
        await using var adapter = Adapter(handler);

        var events = await Collect(adapter.GenerateAsync(Request(logprobs: 2)));

        var body = Assert.Single(handler.Bodies).RootElement;
        Assert.True(body.GetProperty("logprobs").GetBoolean());
        Assert.Equal(2, body.GetProperty("top_logprobs").GetInt32());
        var final = Assert.IsType<AdapterFinal>(events.Last());
        Assert.NotNull(final.Raw);
        var token = Assert.Single(final.Logprobs);
        Assert.Equal("o", token.Token);
        Assert.Equal([111], token.Bytes);
        Assert.Equal("x", Assert.Single(token.Top).Token);
    }

    [Fact]
    public async Task Streamed_logprobs_accumulate_including_a_textless_chunk_and_raw_stays_null()
    {
        var handler = new Handler(Response("data: {\"choices\":[{\"delta\":{\"content\":\"o\"},\"logprobs\":{\"content\":[{\"token\":\"o\",\"logprob\":-0.1,\"bytes\":[111]}]}}]}\n\ndata: {\"choices\":[{\"delta\":{},\"logprobs\":{\"content\":[{\"token\":\"k\",\"logprob\":-0.2,\"bytes\":[107]}]},\"finish_reason\":\"stop\"}]}\n\ndata: [DONE]\n\n", "text/event-stream"));
        await using var adapter = Adapter(handler);

        var events = await Collect(adapter.GenerateAsync(Request(stream: true, logprobs: 0)));

        var body = Assert.Single(handler.Bodies).RootElement;
        Assert.True(body.GetProperty("logprobs").GetBoolean());
        Assert.False(body.TryGetProperty("top_logprobs", out _));
        var final = Assert.IsType<AdapterFinal>(events.Last());
        Assert.Null(final.Raw);
        Assert.Equal(["o", "k"], final.Logprobs.Select(static entry => entry.Token));
    }

    [Fact]
    public async Task Invalid_logprob_bytes_degrade_only_bytes_in_buffered_and_sse_responses()
    {
        var buffered = new Handler(Response("""
            {"choices":[{"message":{"content":"ok"},"logprobs":{"content":[{"token":"a","logprob":-1,"bytes":"wrong"},{"token":"b","logprob":-2,"bytes":[true]},{"token":"c","logprob":-3,"bytes":[256]},{"token":"d","logprob":-4,"bytes":[100]}]}}]}
            """));
        await using var bufferedAdapter = Adapter(buffered);
        var bufferedFinal = Assert.IsType<AdapterFinal>((await Collect(bufferedAdapter.GenerateAsync(Request(logprobs: 1)))).Last());
        Assert.Equal(["a", "b", "c", "d"], bufferedFinal.Logprobs.Select(static entry => entry.Token));
        Assert.All(bufferedFinal.Logprobs.Take(3), static entry => Assert.Null(entry.Bytes));
        Assert.Equal([100], bufferedFinal.Logprobs[3].Bytes);

        var streamed = new Handler(Response("data: {\"choices\":[{\"delta\":{},\"logprobs\":{\"content\":[{\"token\":\"e\",\"logprob\":-5,\"bytes\":false},{\"token\":\"f\",\"logprob\":-6,\"bytes\":[102]}]}}]}\n\ndata: [DONE]\n\n", "text/event-stream"));
        await using var streamedAdapter = Adapter(streamed);
        var streamedFinal = Assert.IsType<AdapterFinal>((await Collect(streamedAdapter.GenerateAsync(Request(stream: true, logprobs: 1)))).Last());
        Assert.Equal(["e", "f"], streamedFinal.Logprobs.Select(static entry => entry.Token));
        Assert.Null(streamedFinal.Logprobs[0].Bytes);
        Assert.Equal([102], streamedFinal.Logprobs[1].Bytes);
    }

    [Fact]
    public async Task Extra_options_win_after_reasoning_wire_and_buffered_requests_remove_stream_overrides()
    {
        var handler = new Handler(Response("""{"choices":[{"message":{"content":"ok"}}]}"""));
        await using var adapter = Adapter(handler);
        var request = new WireRequest(
            "model",
            [Message.User("question")],
            new Sampling(),
            stream: false,
            timeoutS: 30,
            maxResponseBytes: 1_048_576,
            reasoningWire: Object("{\"collision\":\"reasoning\",\"stream\":true}"),
            extraOptions: Object("{\"collision\":\"extra\",\"stream\":true,\"stream_options\":{\"include_usage\":false}}"));

        _ = await Collect(adapter.GenerateAsync(request));

        var body = Assert.Single(handler.Bodies).RootElement;
        Assert.Equal("extra", body.GetProperty("collision").GetString());
        Assert.False(body.TryGetProperty("stream", out _));
        Assert.False(body.TryGetProperty("stream_options", out _));
    }

    [Fact]
    public async Task Tool_history_uses_first_result_and_call_only_null_content()
    {
        var handler = new Handler(Response("""{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}"""), Response("""{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}"""));
        await using var adapter = Adapter(handler);
        await Collect(adapter.GenerateAsync(Request(messages: [new Message("assistant", [new Text("ignored"), new ToolResult("first", "first output"), new ToolResult("second", "second output")])] )));
        await Collect(adapter.GenerateAsync(Request(messages: [new Message("assistant", [new ToolCall("call-1", "weather", Object("{\"city\":\"Boston\"}"))])] )));

        var result = handler.Bodies[0].RootElement.GetProperty("messages")[0];
        Assert.Equal("tool", result.GetProperty("role").GetString());
        Assert.Equal("first", result.GetProperty("tool_call_id").GetString());
        var call = handler.Bodies[1].RootElement.GetProperty("messages")[0];
        Assert.Equal(JsonValueKind.Null, call.GetProperty("content").ValueKind);
        Assert.Equal("{\"city\": \"Boston\"}", call.GetProperty("tool_calls")[0].GetProperty("function").GetProperty("arguments").GetString());
    }

    private static OpenAIChatAdapter Adapter(Handler handler) => new(new Uri("https://fixture.invalid/v1"), "token", handler: handler);
    private static WireRequest Request(IEnumerable<Message>? messages = null, bool stream = false, int? logprobs = null) => new("model", messages ?? [Message.User("question")], new Sampling(), stream: stream, timeoutS: 30, maxResponseBytes: 1_048_576, logprobs: logprobs);
    private static JsonObject Object(string text) => Assert.IsType<JsonObject>(JsonReader.Read(text));
    private static async Task<List<AdapterEvent>> Collect(IAsyncEnumerable<AdapterEvent> source) { var result = new List<AdapterEvent>(); await foreach (var item in source) result.Add(item); return result; }
    private static HttpResponseMessage Response(string body, string contentType = "application/json") => new(HttpStatusCode.OK) { Content = new StringContent(body, Encoding.UTF8, contentType) };

    private sealed class Handler(params HttpResponseMessage[] responses) : HttpMessageHandler
    {
        private readonly Queue<HttpResponseMessage> _responses = new(responses);
        internal List<JsonDocument> Bodies { get; } = [];
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Bodies.Add(JsonDocument.Parse(await request.Content!.ReadAsStringAsync(cancellationToken)));
            return _responses.Dequeue();
        }
    }
}
