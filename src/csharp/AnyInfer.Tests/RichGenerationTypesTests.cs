using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

public sealed class RichGenerationTypesTests
{
    [Fact]
    public void Media_parts_enforce_the_public_source_and_metadata_contract()
    {
        Assert.Throws<ArgumentException>(() => new ImagePart());
        Assert.Throws<ArgumentException>(() => new ImagePart([1], "https://example.invalid/image"));
        Assert.Throws<ArgumentException>(() => new ImagePart([1], mediaType: "audio/wav"));
        Assert.Throws<ArgumentException>(() => new ImagePart([1], detail: "medium"));

        Assert.Throws<ArgumentException>(() => new DocumentPart());
        Assert.Throws<ArgumentException>(() => new DocumentPart([1], "https://example.invalid/document"));
        Assert.Throws<ArgumentException>(() => new DocumentPart([1], mediaType: ""));

        Assert.Throws<ArgumentException>(() => new AudioPart(Array.Empty<byte>()));
        Assert.Throws<ArgumentException>(() => new AudioPart([1], "application/octet-stream"));

        Assert.Throws<ArgumentException>(() => new VideoPart());
        Assert.Throws<ArgumentException>(() => new VideoPart([1], "https://example.invalid/video"));
        Assert.Throws<ArgumentException>(() => new VideoPart([1], mediaType: "image/png"));
        Assert.Throws<ArgumentException>(() => new VideoPart([1], startOffsetS: -1));
        Assert.Throws<ArgumentException>(() => new VideoPart([1], startOffsetS: 3, endOffsetS: 3));
        Assert.Throws<ArgumentException>(() => new VideoPart([1], fps: 0));
    }

    [Fact]
    public void Inline_media_ceilings_count_each_inline_type_but_never_a_url_reference()
    {
        var atPartLimit = new ContentPart[]
        {
            new ImagePart([1, 2]),
            new DocumentPart([3, 4]),
            new AudioPart([5, 6]),
            new VideoPart([7, 8]),
        };
        var request = Request(atPartLimit, maxInputPartBytes: 2, maxInputBytes: 8);
        Assert.Equal(2, Assert.IsType<ImagePart>(request.Messages[0].Content[0]).Data!.Count);

        Assert.Throws<ArgumentOutOfRangeException>(() => Request([new ImagePart([1, 2, 3])], maxInputPartBytes: 2));
        Assert.Throws<ArgumentOutOfRangeException>(() => Request([new DocumentPart([1, 2, 3])], maxInputPartBytes: 2));
        Assert.Throws<ArgumentOutOfRangeException>(() => Request([new AudioPart([1, 2, 3])], maxInputPartBytes: 2));
        Assert.Throws<ArgumentOutOfRangeException>(() => Request([new VideoPart([1, 2, 3])], maxInputPartBytes: 2));
        Assert.Throws<ArgumentOutOfRangeException>(() => Request([.. atPartLimit, new ImagePart([9])], maxInputPartBytes: 2, maxInputBytes: 8));

        var urlReferences = Request(
            [
                new ImagePart(url: "https://example.invalid/image"),
                new DocumentPart(url: "https://example.invalid/document"),
                new VideoPart(url: "https://example.invalid/video"),
                new AudioPart([1]),
            ],
            maxInputPartBytes: 1,
            maxInputBytes: 1);
        Assert.Equal(4, urlReferences.Messages[0].Content.Count);
    }

    [Fact]
    public void Media_bytes_and_rich_collections_snapshot_caller_owned_containers()
    {
        var bytes = new List<byte> { 1, 2 };
        var image = new ImagePart(bytes);
        bytes[0] = 9;
        bytes.Add(3);
        Assert.Equal(new byte[] { 1, 2 }, image.Data);
        var publicBytes = Assert.IsAssignableFrom<IList<byte>>(image.Data!);
        Assert.True(publicBytes.IsReadOnly);
        Assert.Throws<NotSupportedException>(() => publicBytes[0] = 7);

        var options = new Dictionary<string, JsonObject>
        {
            ["*"] = new JsonObject([new JsonProperty("temperature", new JsonNumber(0.2))]),
        };
        var metadata = new Dictionary<string, string> { ["trace"] = "original" };
        var tools = new List<ServerToolSpec> { new("web_search", 2) };
        var request = Request([image], providerOptions: options, metadata: metadata, serverTools: tools);
        options.Clear();
        metadata.Clear();
        tools.Clear();
        Assert.True(request.ProviderOptions.ContainsKey("*"));
        Assert.Equal("original", request.Metadata["trace"]);
        Assert.Equal(new ServerToolSpec("web_search", 2), Assert.Single(request.ServerTools));

        var top = new List<TokenLogprob> { new("runner-up", -2) };
        var tokenBytes = new List<byte> { 0xF0, 0x9F, 0x98, 0x80 };
        var token = new TokenLogprob("😀", -0.5, top, tokenBytes);
        var citations = new List<Citation> { new(0, 1) };
        var uses = new List<ServerToolUse> { new("web_search", 1) };
        var result = new Generation("answer", logprobs: [token], citations: citations, serverToolUses: uses);
        top.Clear();
        tokenBytes.Clear();
        citations.Clear();
        uses.Clear();
        Assert.Single(result.Logprobs[0].Top);
        Assert.Equal(new byte[] { 0xF0, 0x9F, 0x98, 0x80 }, result.Logprobs[0].Bytes);
        Assert.Single(result.Citations);
        Assert.Single(result.ServerToolUses);
    }

    [Fact]
    public void Citation_uses_unicode_scalar_offsets_clamps_and_preserves_null_vs_zero()
    {
        const string text = "A😀BC";

        Assert.Equal("😀", new Citation(startIndex: 1, endIndex: 2).SpanOf(text));
        Assert.Equal("A", new Citation(startIndex: 0, endIndex: 1).SpanOf(text));
        Assert.Equal(text, new Citation(startIndex: -9, endIndex: 99).SpanOf(text));
        Assert.Equal("", new Citation(startIndex: 9, endIndex: 2).SpanOf(text));
        Assert.Equal("", new Citation(quotedText: "source").SpanOf(text));
        Assert.Null(new Citation().StartIndex);
        Assert.Equal(0, new Citation(startIndex: 0).StartIndex);
    }

    [Fact]
    public void Token_logprob_keeps_snapshots_and_exposes_probability()
    {
        var alternatives = new List<TokenLogprob> { new("other", -2) };
        var bytes = new List<byte> { 120 };
        var value = new TokenLogprob("x", Math.Log(0.25), alternatives, bytes);
        alternatives.Clear();
        bytes[0] = 0;

        Assert.Equal(0.25, value.Probability, 12);
        Assert.Equal("other", Assert.Single(value.Top).Token);
        Assert.Equal(new byte[] { 120 }, value.Bytes);
    }

    [Fact]
    public void Server_tool_spec_validates_only_its_real_construction_contract_and_request_defaults_are_stable()
    {
        Assert.Throws<ArgumentException>(() => new ServerToolSpec("telepathy"));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ServerToolSpec("web_search", 0));

        var spec = new ServerToolSpec("code_execution");
        var request = Request([new Text("hi")]);
        Assert.Equal("code_execution", spec.Kind);
        Assert.Null(spec.MaxUses);
        Assert.Null(request.Reasoning);
        Assert.Empty(request.ProviderOptions);
        Assert.Empty(request.Metadata);
        Assert.Null(request.Logprobs);
        Assert.False(request.CiteDocuments);
        Assert.Empty(request.ServerTools);
        Assert.Equal(20 * 1024 * 1024, request.MaxInputPartBytes);
        Assert.Equal(50 * 1024 * 1024, request.MaxInputBytes);
        Assert.Equal(-1L, new ServerToolUse("not-normalized", -1).Uses);
    }

    [Fact]
    public void Generation_request_keeps_logprob_boundaries_and_positive_byte_ceiling_contracts()
    {
        Assert.Null(Request([new Text("hi")]).Logprobs);
        Assert.Equal(0, Request([new Text("hi")], logprobs: 0).Logprobs);
        Assert.Equal(20, Request([new Text("hi")], logprobs: 20).Logprobs);
        Assert.Throws<ArgumentOutOfRangeException>(() => Request([new Text("hi")], logprobs: -1));
        Assert.Throws<ArgumentOutOfRangeException>(() => Request([new Text("hi")], logprobs: 21));
        Assert.Throws<ArgumentOutOfRangeException>(() => Request([new Text("hi")], maxInputPartBytes: 0));
        Assert.Throws<ArgumentOutOfRangeException>(() => Request([new Text("hi")], maxInputBytes: 0));
    }

    [Fact]
    public void Rich_events_remain_public_and_adapter_events_remain_a_separate_hierarchy()
    {
        Assert.IsAssignableFrom<StreamEvent>(new ReasoningDelta(""));
        Assert.IsAssignableFrom<StreamEvent>(new CitationDelta(new Citation()));
        Assert.IsAssignableFrom<StreamEvent>(new ServerToolDelta("web_search", "started"));
        Assert.IsAssignableFrom<AdapterEvent>(new AdapterReasoningDelta(""));
        Assert.IsAssignableFrom<AdapterEvent>(new AdapterCitationDelta(new Citation()));
        Assert.IsAssignableFrom<AdapterEvent>(new AdapterServerToolDelta("web_search", "started"));

        var message = new Message("assistant", [new Text("first"), new AudioPart([1]), new Text(" last")]);
        Assert.Equal("first last", message.Text);
    }

    [Fact]
    public void Existing_constructor_parameter_names_remain_compatible_with_rich_appends()
    {
        var request = new GenerationRequest(
            [Message.User("hello")],
            new Route(["fixture:model"]),
            sampling: new Sampling(temperature: 0.2),
            repair: new Repair(1),
            schema: new SchemaSpec(new JsonObject([]), "answer"),
            schemaMechanism: "prompt",
            timeoutS: 4,
            maxResponseBytes: 1024,
            stream: true,
            tools: [new ToolSpec("lookup", "Find it", new JsonObject([]))],
            toolChoice: "required",
            cache: null);
        var final = new AdapterFinal(FinishReason: "stop", Usage: new Usage(InputTokens: 1), Raw: JsonNull.Instance);

        Assert.True(request.Stream);
        Assert.Equal("required", request.ToolChoice);
        Assert.Equal("stop", final.FinishReason);
        Assert.Equal(1, final.Usage!.InputTokens);
        Assert.Same(JsonNull.Instance, final.Raw);
    }

    private static GenerationRequest Request(
        IEnumerable<ContentPart> parts,
        int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024,
        int? logprobs = null,
        IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null,
        IEnumerable<ServerToolSpec>? serverTools = null) =>
        new([new Message("user", parts)], new Route(["fixture:model"]),
            logprobs: logprobs, providerOptions: providerOptions, metadata: metadata, serverTools: serverTools,
            maxInputPartBytes: maxInputPartBytes, maxInputBytes: maxInputBytes);
}
