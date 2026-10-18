using System.Numerics;
using AnyInfer.Json;
using AnyInfer.Manifest;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Independent format-one manifest codec controls using only public boundaries and literal inputs.</summary>
public sealed class ManifestSerializationTests
{
    [Fact]
    public void Complete_nondefault_manifest_roundtrips_every_nested_facet_without_losing_nullable_or_scalar_facts()
    {
        var manifest = new RunManifest(
            anyinferVersion: "9.1", requestId: "req", complete: true,
            request: new RequestFacet(2, [new("user", 1)], 8, 3, true, "answer", "sha256:x", ["lookup"], "required", [new("temperature", new JsonNumber(0.25))], "high", 9.5, 2, ["trace"]),
            route: new RouteFacet(["alpha:model"], "alpha:model", [new RouteStep("alpha:model", "selected", "healthy")]),
            capability: new CapabilityFacet("alpha:model", [new SourcedFact("limit", new JsonObject([new JsonProperty("arbitrary", new JsonArray([new JsonInteger(BigInteger.Parse("100000000000000000000"))]))]), "catalog")]),
            attempts: [new AttemptFacet("alpha:model", 2, "ok", new ErrorInfo("Retry", "alpha", "generate", true, 429, null), 1, 2, 3, null, 0.5, [new("quota", 0.5)])],
            structured: new SchemaFacet(true, "json_schema", "json_schema", [new MechanismRung("json_schema", true)], 1, [new RepairRecord(1, null, ["type"])], true),
            cache: new CacheFacet("auto", "prefix", 1, 2, 3, 4),
            context: new ContextFacet([new ReductionRecord("trim", "summary", 4, 2, 2, 10, 11, ["system"], 1, false)]),
            dropped: [new DroppedParameter("alpha:model", "top_p", "unsupported")],
            usage: new UsageFacet(1, 2, 3, 4, 5, 6, "0.0000000000000000000000000000000001", [new("input_tokens", "estimate")], 7),
            timing: new TimingFacet(1, 2, 3, [new("decode", 4)]), notes: ["warn"],
            payloads: new PayloadFacet("prompt", "response", "schema", ["{}"], ["bad"]), operation: "embedding",
            embeddingSpace: new EmbeddingSpace("alpha", "embed", "r1", 0, true, false, "space"));

        var decoded = RunManifest.FromDictionary(manifest.ToDictionary());

        Assert.True(decoded.Complete);
        Assert.Equal("9.1", decoded.AnyinferVersion);
        Assert.Equal("required", decoded.Request.ToolChoice);
        Assert.Equal(EDecimalText(), decoded.Usage.CostUsd);
        Assert.Equal(7, decoded.Usage.SearchUnits);
        Assert.Equal("Retry", decoded.Attempts.Single().Error!.TypeName);
        Assert.Null(decoded.Attempts.Single().Error!.Detail);
        var factObject = Assert.IsType<JsonObject>(decoded.Capability.Facts.Single().Value);
        var factArray = Assert.IsType<JsonArray>(factObject.Properties.Single().Value);
        Assert.Equal(BigInteger.Parse("100000000000000000000"), Assert.IsType<JsonInteger>(Assert.Single(factArray.Items)).Value);
        Assert.False(decoded.Context.Reductions.Single().Complete);
        Assert.Equal(false, decoded.EmbeddingSpace!.Normalized);
        Assert.Equal("space", decoded.EmbeddingSpace.CompatibilityId);
    }

    [Fact]
    public void Missing_nullable_unknown_and_arbitrary_json_rules_are_distinct()
    {
        var literal = Assert.IsType<JsonObject>(JsonReader.ReadModern("""
        {"unknown_root":true,"request":{"unknown":1},"capability":{"facts":[{"name":"fact","value":{"unknown":true,"nested":[0,false]},"provenance":"catalog","ignored":"x"}],"ignored":false},"payloads":null}
        """));
        var decoded = RunManifest.FromDictionary(literal);
        var value = Assert.IsType<JsonObject>(decoded.Capability.Facts.Single().Value);

        Assert.Equal("1", decoded.Format);
        Assert.Null(decoded.Payloads);
        Assert.True(Assert.IsType<JsonBoolean>(Property(value, "unknown")).Value);
        Assert.IsType<JsonArray>(Property(value, "nested"));
        Assert.Empty(decoded.Request.ToolNames);
    }

    [Theory]
    [InlineData("{\"complete\":null}")]
    [InlineData("{\"request\":null}")]
    [InlineData("{\"request\":{\"message_count\":null}}")]
    [InlineData("{\"usage\":{\"input_tokens\":\"one\"}}")]
    public void Wrong_known_types_and_null_nonnullable_fields_fail_with_bounded_format_errors(string text)
    {
        var error = Assert.Throws<FormatException>(() => RunManifest.FromJson(text));
        Assert.DoesNotContain(text, error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Json_text_duplicate_keys_are_last_wins_while_large_arbitrary_fact_integers_survive()
    {
        var decoded = RunManifest.FromJson("""
        {"request_id":"first","request_id":"last","capability":{"facts":[{"name":"big","value":10000000000000000000000000000000000000000000000000000000000000000000001,"provenance":"probed"}]}}
        """);
        Assert.Equal("last", decoded.RequestId);
        Assert.Equal(BigInteger.Parse("10000000000000000000000000000000000000000000000000000000000000000000001"), Assert.IsType<JsonInteger>(decoded.Capability.Facts.Single().Value).Value);
    }

    [Fact]
    public void Present_null_arbitrary_fact_values_survive_but_absent_required_values_fail()
    {
        var present = RunManifest.FromJson("""{"capability":{"facts":[{"name":"nullable","value":null,"provenance":"catalog"}]}}""");
        Assert.IsType<JsonNull>(present.Capability.Facts.Single().Value);
        Assert.Throws<FormatException>(() => RunManifest.FromJson("""{"capability":{"facts":[{"name":"missing","provenance":"catalog"}]}}"""));
    }

    [Fact]
    public void Declared_double_fields_accept_representable_integer_spellings_but_integer_fields_do_not()
    {
        var decoded = RunManifest.FromJson("""{"request":{"timeout_s":9},"timing":{"total_ms":2,"phases":{"decode":3}},"attempts":[{"target":"a:m","paced_s":{"quota":4}}]}""");
        Assert.Equal(9, decoded.Request.TimeoutS);
        Assert.Equal(2, decoded.Timing.TotalMs);
        Assert.Equal(3, decoded.Timing.Phases["decode"]);
        Assert.Equal(4, decoded.Attempts.Single().PacedS["quota"]);

        Assert.Throws<FormatException>(() => RunManifest.FromJson("""{"request":{"message_count":1.5}}"""));
        Assert.Throws<FormatException>(() => RunManifest.FromJson("""{"request":{"message_count":true}}"""));
        Assert.Throws<FormatException>(() => RunManifest.FromJson("""{"timing":{"total_ms":100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000}}"""));
    }

    [Fact]
    public void Public_json_output_has_independent_sorted_ascii_indent_and_separator_oracles()
    {
        var manifest = new RunManifest(requestId: "é", notes: ["x"]);
        const string indentTwo = "{\n  \"anyinfer_version\": \"\",\n  \"attempts\": [],\n  \"cache\": {\n    \"estimated_cacheable_tokens\": 0,\n    \"mark_count\": 0,\n    \"mechanism\": null,\n    \"policy_mode\": null,\n    \"read_tokens\": null,\n    \"write_tokens\": null\n  },\n  \"capability\": {\n    \"facts\": [],\n    \"target\": \"\"\n  },\n  \"complete\": false,\n  \"context\": {\n    \"reductions\": []\n  },\n  \"dropped\": [],\n  \"embedding_space\": null,\n  \"format\": \"1\",\n  \"notes\": [\n    \"x\"\n  ],\n  \"operation\": \"generation\",\n  \"payloads\": null,\n  \"request\": {\n    \"char_count\": 0,\n    \"estimated_tokens\": null,\n    \"message_count\": 0,\n    \"metadata_keys\": [],\n    \"reasoning\": null,\n    \"repair_budget\": 0,\n    \"role_counts\": {},\n    \"sampling\": {},\n    \"schema_digest\": null,\n    \"schema_name\": null,\n    \"schema_present\": false,\n    \"timeout_s\": null,\n    \"tool_choice\": \"auto\",\n    \"tool_names\": []\n  },\n  \"request_id\": \"\\u00e9\",\n  \"route\": {\n    \"considered\": [],\n    \"requested\": [],\n    \"resolved\": null\n  },\n  \"structured\": {\n    \"chosen\": null,\n    \"ladder\": [],\n    \"repair_attempts\": 0,\n    \"repairs\": [],\n    \"requested\": false,\n    \"used\": null,\n    \"validated\": false\n  },\n  \"timing\": {\n    \"first_token_ms\": null,\n    \"output_tokens_per_s\": null,\n    \"phases\": {},\n    \"total_ms\": null\n  },\n  \"usage\": {\n    \"cache_read_tokens\": null,\n    \"cache_write_tokens\": null,\n    \"cost_usd\": null,\n    \"estimated_fields\": {},\n    \"input_tokens\": null,\n    \"output_tokens\": null,\n    \"reasoning_tokens\": null,\n    \"search_units\": null,\n    \"total_tokens\": null\n  }\n}";

        Assert.Equal(indentTwo, manifest.ToJson());
        Assert.Equal(indentTwo.Replace("  ", string.Empty), manifest.ToJson(0));
        Assert.Contains("\"format\": \"1\", \"notes\": [\"x\"]", manifest.ToJson(null), StringComparison.Ordinal);
        Assert.True(JsonEquality.TypeAwareEquals(manifest.ToDictionary(), RunManifest.FromDictionary(manifest.ToDictionary()).ToDictionary()));
    }

    private static JsonValue Property(JsonObject source, string name) => source.TryGetValue(name, out var value) ? value : throw new Xunit.Sdk.XunitException($"Missing {name}.");
    private static string EDecimalText() => "0.0000000000000000000000000000000001";
}
