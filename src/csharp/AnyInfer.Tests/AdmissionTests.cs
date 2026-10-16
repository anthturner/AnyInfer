using AnyInfer;
using AnyInfer.Json;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

public sealed class AdmissionTests
{
    [Fact]
    public void Schema_admission_allows_absent_empty_and_exact_draft_schemas()
    {
        SchemaAdmission.Validate(null);
        SchemaAdmission.Validate(new JsonObject([]));
        SchemaAdmission.Validate(JsonReader.Read("{\"$schema\":\"https://json-schema.org/draft/2020-12/schema\"}"));
    }

    [Theory]
    [InlineData("true")]
    [InlineData("null")]
    [InlineData("17")]
    [InlineData("[]")]
    [InlineData("{\"$schema\":null}")]
    [InlineData("{\"$schema\":\"https://example.invalid/draft\"}")]
    [InlineData("{\"$ref\":\"#/x\"}")]
    [InlineData("{\"allOf\":[]}")]
    [InlineData("{\"type\":[\"string\"]}")]
    [InlineData("{\"properties\":{\"x\":true}}")]
    [InlineData("{\"items\":false}")]
    [InlineData("{\"items\":[]}")]
    [InlineData("{\"additionalProperties\":{}}")]
    [InlineData("{\"format\":\"email\"}")]
    [InlineData("{\"unknown\":true}")]
    public void Schema_admission_refuses_each_excluded_boundary(string source)
    {
        var error = Assert.Throws<ProviderException>(() => SchemaAdmission.Validate(JsonReader.Read(source)));

        AssertUnsupported(error);
    }

    [Fact]
    public void Schema_admission_visits_only_schema_positions_not_literal_data()
    {
        var schema = JsonReader.Read("""
            {"properties":{"$ref":{"type":"string"}},"enum":[{"$ref":"literal","allOf":true}],
             "const":{"items":false},"default":{"unknown":true},"examples":[{"format":"literal"}]}
            """);

        SchemaAdmission.Validate(schema);
    }

    [Theory]
    [InlineData("{\"type\":17}")]
    [InlineData("{\"required\":17}")]
    [InlineData("{\"properties\":17}")]
    [InlineData("{\"properties\":{\"x\":17}}")]
    [InlineData("{\"items\":17}")]
    [InlineData("{\"additionalProperties\":17}")]
    public void Malformed_admitted_keywords_remain_late_schema_assessment(string source)
    {
        var schema = JsonReader.Read(source);
        SchemaAdmission.Validate(schema);

        var assessment = SchemaValidator.Assess(schema, JsonNull.Instance, Guid.NewGuid(), 0);
        Assert.Equal("invalid_schema", Assert.Single(assessment.Issues).Rule);
    }

    [Fact]
    public void Explicit_excluded_forms_take_precedence_over_malformed_admitted_values()
    {
        var error = Assert.Throws<ProviderException>(() => SchemaAdmission.Validate(JsonReader.Read("{\"type\":17,\"$ref\":\"#/x\"}")));

        AssertUnsupported(error);
    }

    [Fact]
    public void Request_admission_forwards_schema_profile_checks_but_leaves_malformed_admitted_schema_late()
    {
        var excluded = Request([], schema: JsonReader.Read("{\"$ref\":\"#/x\"}"));
        var malformed = Request([], schema: JsonReader.Read("{\"required\":17}"));

        AssertUnsupported(Assert.Throws<ProviderException>(() => RequestAdmission.Validate(excluded)));
        RequestAdmission.Validate(malformed);

        var assessment = SchemaValidator.Assess(malformed.Schema!, JsonNull.Instance, Guid.NewGuid(), 0);
        Assert.Equal("invalid_schema", Assert.Single(assessment.Issues).Rule);
    }

    [Theory]
    [InlineData("{\"properties\":{\"child\":{\"$ref\":\"#/x\"}}}")]
    [InlineData("{\"properties\":{\"child\":{\"unknown\":true}}}")]
    [InlineData("{\"items\":{\"anyOf\":[]}}")]
    public void Schema_admission_recurses_only_into_actual_child_schema_positions(string source)
    {
        AssertUnsupported(Assert.Throws<ProviderException>(() => SchemaAdmission.Validate(JsonReader.Read(source))));
    }

    [Fact]
    public void Request_admission_keeps_empty_messages_text_parts_and_lazy_target_shapes()
    {
        var empty = Request([], new Route([" ", "provider:", ":model"]));
        var text = Request([new Message("user", [new TextPart("literal")])], new Route(["provider:model"]));

        RequestAdmission.Validate(empty);
        RequestAdmission.Validate(text);
    }

    [Fact]
    public void Request_admission_rejects_raw_tool_role_and_non_text_content_without_rewriting_data()
    {
        var original = new JsonObject([new JsonProperty("url", new JsonString("https://example.invalid"))]);
        var part = new UnsupportedContentPart("image", original);
        var role = Assert.Throws<ProviderException>(() => RequestAdmission.Validate(Request([new Message("tool", [new TextPart("x")])])));
        var content = Assert.Throws<ProviderException>(() => RequestAdmission.Validate(Request([new Message("user", [part])])));

        AssertUnsupported(role);
        AssertUnsupported(content);
        Assert.Equal("image", part.Kind);
        Assert.Same(original, part.OriginalData);
    }

    [Fact]
    public void Request_admission_rejects_nonempty_alias_but_leaves_blank_and_colon_targets_lazy()
    {
        var alias = Assert.Throws<ProviderException>(() => RequestAdmission.Validate(Request([], new Route(["named-target"]))));

        AssertUnsupported(alias);
        RequestAdmission.Validate(Request([], new Route(["", "  ", "provider:", ":model"])));
    }

    [Fact]
    public void Construction_sampling_failures_are_invalid_request_before_profile_admission()
    {
        var samples = new[]
        {
            new Sampling(seed: -1),
            new Sampling(presencePenalty: double.PositiveInfinity),
            new Sampling(frequencyPenalty: double.NegativeInfinity),
        };

        foreach (var sample in samples)
        {
            var request = Request([new Message("tool", [new TextPart("would otherwise be unsupported")])], sampling: sample);
            var error = Assert.Throws<ProviderException>(() => RequestAdmission.Validate(request));

            Assert.Equal("invalid_request", error.Category);
            Assert.False(error.Retryable);
            Assert.Null(error.Phase);
        }
    }

    [Fact]
    public void NaN_sampling_penalties_fail_construction_before_profile_checks()
    {
        var samples = new[]
        {
            new Sampling(presencePenalty: double.NaN),
            new Sampling(frequencyPenalty: double.NaN),
        };

        foreach (var sample in samples)
        {
            var request = Request([new Message("tool", [new TextPart("would otherwise be unsupported")])], sampling: sample);
            var error = Assert.Throws<ProviderException>(() => RequestAdmission.Validate(request));

            Assert.Equal("invalid_request", error.Category);
            Assert.False(error.Retryable);
            Assert.Null(error.Phase);
        }
    }

    [Fact]
    public void Finite_penalties_and_each_admitted_role_pass_request_admission()
    {
        var sampling = new Sampling(presencePenalty: -1.25, frequencyPenalty: 2.5);

        foreach (var role in new[] { "system", "user", "assistant" })
        {
            RequestAdmission.Validate(Request([new Message(role, [new TextPart("literal")])], sampling: sampling));
        }
    }

    private static GenerationRequest Request(
        IEnumerable<Message> messages,
        Route? route = null,
        Sampling? sampling = null,
        JsonValue? schema = null) =>
        new(messages, route ?? new Route(["provider:model"]), sampling: sampling, schema: schema);

    private static void AssertUnsupported(ProviderException error)
    {
        Assert.Equal("unsupported_input", error.Category);
        Assert.False(error.Retryable);
        Assert.Equal("generate", error.Phase);
        Assert.False(string.IsNullOrWhiteSpace(error.Detail));
        Assert.False(string.IsNullOrWhiteSpace(error.Hint));
    }
}
