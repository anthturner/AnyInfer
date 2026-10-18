using AnyInfer.Json;
using AnyInfer.Manifest;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public embedded format-one schema resource and validation controls.</summary>
public sealed class ManifestSchemaTests
{
    [Fact]
    public async Task Embedded_schema_exposes_literal_v1_facts_and_validates_default_manifest()
    {
        var schema = ManifestUtilities.JsonSchema();
        Assert.Equal("https://json-schema.org/draft/2020-12/schema", String(schema, "$schema"));
        Assert.Equal("AnyInfer run manifest", String(schema, "title"));
        Assert.Equal("object", String(schema, "type"));
        var required = Assert.IsType<JsonArray>(Property(schema, "required")).Items.Select(static value => Assert.IsType<JsonString>(value).Value).ToArray();
        Assert.Equal(["format", "request_id", "request", "route", "usage", "timing"], required);
        var properties = Assert.IsType<JsonObject>(Property(schema, "properties"));
        Assert.Equal("string", String(Assert.IsType<JsonObject>(Property(properties, "format")), "type"));
        Assert.Equal("generation", Assert.IsType<JsonArray>(Property(Assert.IsType<JsonObject>(Property(properties, "operation")), "enum")).Items.Select(static item => Assert.IsType<JsonString>(item).Value).First());

        var result = await SchemaValidator.ValidateAsync(new RunManifest().ToDictionary(), new SchemaSpec(schema, "manifest-v1"));
        Assert.True(result.IsValid);
        Assert.Empty(result.Issues);
    }

    [Fact]
    public async Task Embedded_schema_validates_nondefault_public_manifest_and_exposes_stable_immutable_value_semantics()
    {
        var schema = ManifestUtilities.JsonSchema();
        var again = ManifestUtilities.JsonSchema();
        Assert.True(JsonEquality.TypeAwareEquals(schema, again));
        var properties = Assert.IsType<JsonObject>(Property(schema, "properties"));
        var usage = Assert.IsType<JsonObject>(Property(properties, "usage"));
        Assert.True(usage.TryGetValue("properties", out var usageProperties));
        Assert.IsType<JsonObject>(usageProperties);

        var manifest = new RunManifest(
            anyinferVersion: "1.2", requestId: "request", complete: true,
            route: new RouteFacet(["alpha:model"], "alpha:model"),
            capability: new CapabilityFacet("alpha:model", [new SourcedFact("feature", new JsonBoolean(false), "probed")]),
            attempts: [new AttemptFacet("alpha:model")],
            usage: new UsageFacet(1, 2, 3, costUsd: "1E-34", searchUnits: 0),
            timing: new TimingFacet(totalMs: 2), notes: ["note"], operation: "embedding",
            embeddingSpace: new EmbeddingSpace("alpha", "embed", dimensions: 0, normalized: false));
        var encoded = manifest.ToDictionary();
        var result = await SchemaValidator.ValidateAsync(encoded, new SchemaSpec(schema, "manifest-v1"));

        Assert.True(result.IsValid);
        Assert.True(JsonEquality.TypeAwareEquals(encoded, manifest.ToDictionary()));
        Assert.IsType<JsonArray>(Property(encoded, "attempts"));
        Assert.IsType<JsonObject>(Property(encoded, "usage"));
    }

    private static JsonValue Property(JsonObject value, string name) => value.TryGetValue(name, out var item) ? item : throw new Xunit.Sdk.XunitException($"Missing {name}.");
    private static string String(JsonObject value, string name) => Assert.IsType<JsonString>(Property(value, name)).Value;
}
