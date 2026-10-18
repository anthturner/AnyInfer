using System.Numerics;
using System.Text.Json;
using System.Text.Json.Serialization.Metadata;
using System.Text.RegularExpressions;
using AnyInfer;
using AnyInfer.Json;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

public sealed class ModernSchemaTests
{
    [Fact]
    public void Schema_spec_coercion_preserves_title_name_and_rejects_non_object_mappings()
    {
        var titled = Assert.IsType<JsonObject>(JsonReader.Read("{\"title\":\"  Exact title  \",\"type\":\"object\"}"));
        var spec = SchemaSpec.Coerce(titled);

        Assert.Same(titled, spec.JsonSchema);
        Assert.Equal("  Exact title  ", spec.Name);
        Assert.Same(spec, SchemaSpec.Coerce(spec));
        Assert.Equal("response", SchemaSpec.Coerce(Assert.IsType<JsonObject>(JsonReader.Read("{}"))).Name);
        Assert.Throws<ArgumentException>(() => SchemaSpec.Coerce(JsonReader.Read("true")));
        Assert.Null((SchemaSpec?)(JsonValue?)null);
    }

    [Fact]
    public void Schema_spec_json_bridges_are_object_only_and_retains_malformed_keyword_documents()
    {
        var fromText = SchemaSpec.FromJson("{\"title\":\"Record\",\"required\":17}");
        using var document = JsonDocument.Parse("{\"type\":\"object\"}");
        var fromElement = SchemaSpec.Coerce(document.RootElement);

        Assert.Equal("Record", fromText.Name);
        Assert.IsType<JsonObject>(fromText.JsonSchema);
        Assert.Equal("response", fromElement.Name);
        Assert.Throws<ArgumentException>(() => SchemaSpec.FromJson("[]"));
    }

    [Fact]
    public async Task Modern_schema_const_comparison_supports_values_beyond_the_frozen_int64_reader_within_native_decimal_range()
    {
        const string literal = "100000000000000000000";
        var expected = BigInteger.Parse(literal);
        var schema = SchemaSpec.FromJson("{\"const\":" + literal + "}");

        var result = await SchemaValidator.ValidateAsync(new JsonInteger(expected), schema);

        Assert.True(result.IsValid);
        Assert.Throws<FormatException>(() => JsonReader.Read(literal));
    }

    [Fact]
    public async Task Modern_schema_bridge_retains_arbitrary_integers_for_noncomparing_schemas_without_widening_frozen_json()
    {
        const string literal = "10000000000000000000000000000000000000000000000000000000000000000000000";
        var expected = BigInteger.Parse(literal);
        var bridge = SchemaSpec.FromJson("{\"x_anyinfer_retained\":" + literal + "}");
        Assert.True(Assert.IsType<JsonObject>(bridge.JsonSchema).TryGetValue("x_anyinfer_retained", out var retained));

        var result = await SchemaValidator.ValidateAsync(new JsonInteger(expected), SchemaSpec.FromJson("{}"));

        Assert.Equal(expected, Assert.IsType<JsonInteger>(retained).Value);
        Assert.True(result.IsValid);
        Assert.Throws<FormatException>(() => JsonReader.Read(literal));
        Assert.Throws<ArgumentOutOfRangeException>(() => JsonWriter.Write(new JsonInteger(expected)));
    }

    [Fact]
    public async Task Modern_out_of_range_const_evaluation_is_terminal_with_no_provider_at_standalone_boundary()
    {
        const string literal = "10000000000000000000000000000000000000000000000000000000000000000000000";
        var schema = SchemaSpec.FromJson("{\"const\":" + literal + "}");

        var error = await Assert.ThrowsAsync<SchemaEvaluationException>(() =>
            SchemaValidator.ValidateAsync(new JsonInteger(BigInteger.Parse(literal)), schema));

        Assert.IsType<FormatException>(error.NativeInner);
        Assert.Equal("validate", error.Phase);
        Assert.False(error.Retryable);
        Assert.Null(error.Provider);
    }

    [Fact]
    public void Options_copy_registered_resources_and_validate_identity_and_regex_boundaries()
    {
        var uri = new Uri("urn:test:shared");
        var input = new Dictionary<Uri, JsonValue> { [uri] = JsonReader.Read("{\"type\":\"integer\"}") };
        var options = new SchemaValidationOptions(input, baseUri: new Uri("urn:test:root"), regexTimeout: TimeSpan.FromMilliseconds(25));
        input.Clear();

        Assert.Single(options.Resources);
        Assert.Equal(uri, Assert.Single(options.Resources).Key);
        Assert.Equal(TimeSpan.FromMilliseconds(25), options.RegexTimeout);
        Assert.Throws<ArgumentException>(() => new SchemaValidationOptions(new Dictionary<Uri, JsonValue> { [new Uri("relative", UriKind.Relative)] = JsonReader.Read("{}") }));
        Assert.Throws<ArgumentException>(() => new SchemaValidationOptions(new Dictionary<Uri, JsonValue> { [new Uri("urn:test:root#child")] = JsonReader.Read("{}") }));
        Assert.Throws<ArgumentOutOfRangeException>(() => new SchemaValidationOptions(regexTimeout: TimeSpan.Zero));
    }

    [Fact]
    public void Options_are_inert_and_their_public_snapshots_cannot_be_used_to_mutate_registration()
    {
        var calls = 0;
        var source = new Dictionary<Uri, JsonValue>
        {
            [new Uri("urn:test:inert")] = JsonReader.Read("{\"type\":\"integer\"}"),
        };

        var options = new SchemaValidationOptions(source, retrieve: (_, _) =>
        {
            Interlocked.Increment(ref calls);
            return ValueTask.FromResult<JsonValue?>(null);
        });
        source[new Uri("urn:test:late")] = JsonReader.Read("{}");

        Assert.Equal(0, calls);
        Assert.Single(options.Resources);
        Assert.False(options.Resources.ContainsKey(new Uri("urn:test:late")));
        Assert.False(options.Resources is IDictionary<Uri, JsonValue> mutable && mutable.IsReadOnly is false);
    }

    [Fact]
    public void Terminal_schema_exceptions_preserve_the_public_reference_and_evaluation_contract()
    {
        var native = new InvalidOperationException("native");
        var reference = new SchemaReferenceException("missing", new Uri("https://example.invalid/schema#leaf"), "leaf", "configured", native);
        var timeout = new RegexMatchTimeoutException("pattern", "input", TimeSpan.FromMilliseconds(1));
        var evaluation = new SchemaEvaluationException("timed out", "configured", timeout);

        Assert.Equal("https://example.invalid/schema", reference.ResourceUri.AbsoluteUri);
        Assert.Equal("leaf", reference.Fragment);
        Assert.Equal("schema_reference", reference.Category);
        Assert.Equal("validate", reference.Phase);
        Assert.False(reference.Retryable);
        Assert.Equal("configured", reference.Provider);
        Assert.Same(native, reference.NativeInner);
        Assert.Equal("schema_evaluation", evaluation.Category);
        Assert.Equal("validate", evaluation.Phase);
        Assert.False(evaluation.Retryable);
        Assert.Same(timeout, evaluation.NativeInner);
    }

    [Theory]
    [InlineData("{\"$schema\":\"https://json-schema.org/draft/2020-12/schema\",\"prefixItems\":[{\"type\":\"integer\"}]}", "[\"wrong\"]")]
    [InlineData("{\"$schema\":\"https://json-schema.org/draft/2019-09/schema\",\"$recursiveAnchor\":true,\"type\":\"object\",\"properties\":{\"next\":{\"$recursiveRef\":\"#\"}}}", "{\"next\":1}")]
    [InlineData("{\"$schema\":\"http://json-schema.org/draft-07/schema#\",\"if\":{\"properties\":{\"kind\":{\"const\":\"number\"}}},\"then\":{\"required\":[\"value\"]}}", "{\"kind\":\"number\"}")]
    [InlineData("{\"$schema\":\"http://json-schema.org/draft-06/schema#\",\"exclusiveMinimum\":1}", "1")]
    public async Task Modern_dialects_select_their_native_rules_and_report_instance_validation(string schemaJson, string instanceJson)
    {
        var result = await SchemaValidator.ValidateAsync(JsonReader.Read(instanceJson), SchemaSpec.Coerce(JsonReader.Read(schemaJson)));

        Assert.Equal(SchemaValidationKind.Validation, result.Kind);
        Assert.False(result.IsValid);
        Assert.NotEmpty(result.Issues);
        Assert.All(result.Issues, issue => Assert.NotNull(issue.SchemaLocation));
    }

    [Fact]
    public async Task Invalid_schema_is_distinct_from_instance_invalid_and_format_is_off_by_default()
    {
        var invalidSchema = await SchemaValidator.ValidateAsync(JsonReader.Read("{}"), new SchemaSpec(JsonReader.Read("{\"type\":\"not-a-real-type\"}")));
        var invalidInstance = await SchemaValidator.ValidateAsync(JsonReader.Read("\"x\""), SchemaSpec.Coerce(JsonReader.Read("{\"type\":\"integer\"}")));
        var formatDisabled = await SchemaValidator.ValidateAsync(JsonReader.Read("\"not-an-email\""), SchemaSpec.Coerce(JsonReader.Read("{\"type\":\"string\",\"format\":\"email\"}")));

        Assert.Equal(SchemaValidationKind.InvalidSchema, invalidSchema.Kind);
        Assert.False(invalidSchema.IsValid);
        Assert.NotEmpty(invalidSchema.Issues);
        Assert.All(invalidSchema.Issues, issue =>
        {
            Assert.Null(issue.InstanceLocation);
            Assert.True(Uri.TryCreate(issue.SchemaLocation, UriKind.Absolute, out var schemaLocation));
            Assert.StartsWith("urn:anyinfer:schema:", schemaLocation.AbsoluteUri, StringComparison.Ordinal);
            Assert.Equal("#/type", schemaLocation.Fragment);
        });
        Assert.Equal(SchemaValidationKind.Validation, invalidInstance.Kind);
        Assert.False(invalidInstance.IsValid);
        Assert.True(formatDisabled.IsValid);
    }

    [Theory]
    [InlineData("http://json-schema.org/draft-03/schema#")]
    [InlineData("http://json-schema.org/draft-04/schema#")]
    public async Task Legacy_dialects_are_explicitly_refused_in_the_modern_profile(string dialect)
    {
        var result = await SchemaValidator.ValidateAsync(
            JsonReader.Read("{}"),
            SchemaSpec.Coerce(JsonReader.Read("{\"$schema\":\"" + dialect + "\",\"type\":\"object\"}")));

        Assert.Equal(SchemaValidationKind.InvalidSchema, result.Kind);
        Assert.False(result.IsValid);
        Assert.NotEmpty(result.Messages);
    }

    [Fact]
    public async Task Native_numeric_and_regex_boundaries_do_not_copy_python_binary_float_or_named_group_semantics()
    {
        var exactMultiple = await SchemaValidator.ValidateAsync(
            JsonReader.Read("0.3"), SchemaSpec.Coerce(JsonReader.Read("{\"multipleOf\":0.1}")));
        var pythonNamedGroup = await SchemaValidator.ValidateAsync(
            JsonReader.Read("\"a\""), SchemaSpec.Coerce(JsonReader.Read("{\"pattern\":\"^(?P<letter>a)$\"}")));

        Assert.True(exactMultiple.IsValid);
        Assert.Equal(SchemaValidationKind.InvalidSchema, pythonNamedGroup.Kind);
    }

    [Theory]
    [InlineData("{\"pattern\":\"(?P<letter>a)\"}", "\"a\"")]
    [InlineData("{\"patternProperties\":{\"(?P<letter>a)\":{\"type\":\"integer\"}}}", "{\"a\":1}")]
    public async Task Invalid_native_regex_syntax_is_schema_invalid_not_a_validation_timeout(string schemaJson, string instanceJson)
    {
        var result = await SchemaValidator.ValidateAsync(JsonReader.Read(instanceJson), SchemaSpec.Coerce(JsonReader.Read(schemaJson)));

        Assert.Equal(SchemaValidationKind.InvalidSchema, result.Kind);
        Assert.False(result.IsValid);
    }

    [Fact]
    public async Task Internal_and_registered_references_are_available_without_global_retrieval()
    {
        var internalSchema = SchemaSpec.Coerce(JsonReader.Read("{\"$defs\":{\"positive\":{\"type\":\"integer\",\"minimum\":1}},\"$ref\":\"#/$defs/positive\"}"));
        var registeredUri = new Uri("urn:test:positive");
        var externalSchema = SchemaSpec.Coerce(JsonReader.Read("{\"$ref\":\"urn:test:positive\"}"));
        var options = new SchemaValidationOptions(new Dictionary<Uri, JsonValue> { [registeredUri] = JsonReader.Read("{\"type\":\"integer\",\"minimum\":1}") });

        Assert.False((await SchemaValidator.ValidateAsync(JsonReader.Read("0"), internalSchema)).IsValid);
        Assert.True((await SchemaValidator.ValidateAsync(JsonReader.Read("2"), externalSchema, options)).IsValid);
    }

    [Fact]
    public async Task Missing_reference_refuses_without_retrieval_but_explicit_retriever_is_awaited_once()
    {
        var requested = new Uri("urn:test:late");
        var schema = SchemaSpec.Coerce(JsonReader.Read("{\"$ref\":\"urn:test:late\"}"));
        var calls = 0;
        var noRetrieval = Assert.ThrowsAsync<SchemaReferenceException>(() => SchemaValidator.ValidateAsync(JsonReader.Read("1"), schema));
        var options = new SchemaValidationOptions(retrieve: (uri, token) =>
        {
            Assert.Equal(requested, uri);
            Interlocked.Increment(ref calls);
            return ValueTask.FromResult<JsonValue?>(JsonReader.Read("{\"type\":\"integer\"}"));
        });

        var result = await SchemaValidator.ValidateAsync(JsonReader.Read("1"), schema, options);

        await noRetrieval;
        Assert.Equal(1, calls);
        Assert.True(result.IsValid);
    }

    [Fact]
    public async Task Registered_requested_alias_and_declared_canonical_uri_share_one_document_and_fetch_its_child_once()
    {
        var requested = new Uri("https://example.invalid/requested.json");
        var declared = new Uri("https://example.invalid/canonical/root.json");
        var child = new Uri("https://example.invalid/canonical/child.json");
        var calls = new List<Uri>();
        var options = new SchemaValidationOptions(
            new Dictionary<Uri, JsonValue>
            {
                [requested] = JsonReader.Read("{\"$id\":\"https://example.invalid/canonical/root.json\",\"type\":\"object\",\"properties\":{\"child\":{\"$ref\":\"child.json\"}}}"),
            },
            retrieve: (uri, _) =>
            {
                calls.Add(uri);
                return uri == child
                    ? ValueTask.FromResult<JsonValue?>(JsonReader.Read("{\"type\":\"integer\"}"))
                    : ValueTask.FromResult<JsonValue?>(null);
            });
        var root = SchemaSpec.Coerce(JsonReader.Read("{\"allOf\":[{\"$ref\":\"https://example.invalid/canonical/root.json\"},{\"$ref\":\"https://example.invalid/requested.json\"}]}"));

        var result = await SchemaValidator.ValidateAsync(JsonReader.Read("{\"child\":1}"), root, options);

        Assert.True(result.IsValid);
        Assert.Equal([child], calls);
        Assert.NotEqual(requested, declared);
    }

    [Fact]
    public async Task Mutually_recursive_resources_fetch_each_fragment_free_document_once()
    {
        var a = new Uri("urn:test:cycle-a");
        var b = new Uri("urn:test:cycle-b");
        var calls = new List<Uri>();
        var options = new SchemaValidationOptions(retrieve: (uri, _) =>
        {
            calls.Add(uri);
            return uri == a
                ? ValueTask.FromResult<JsonValue?>(JsonReader.Read("{\"type\":\"object\",\"properties\":{\"next\":{\"$ref\":\"urn:test:cycle-b\"}}}"))
                : uri == b
                    ? ValueTask.FromResult<JsonValue?>(JsonReader.Read("{\"type\":\"object\",\"properties\":{\"next\":{\"$ref\":\"urn:test:cycle-a\"}}}"))
                    : ValueTask.FromResult<JsonValue?>(null);
        });
        var root = SchemaSpec.Coerce(JsonReader.Read("{\"$ref\":\"urn:test:cycle-a\"}"));

        var result = await SchemaValidator.ValidateAsync(JsonReader.Read("{\"next\":{\"next\":{}}}"), root, options);

        Assert.True(result.IsValid);
        Assert.Equal([a, b], calls);
    }

    [Fact]
    public async Task Conflicting_declared_canonical_identity_refuses_before_registration_overwrite()
    {
        var first = new Uri("https://example.invalid/first.json");
        var second = new Uri("https://example.invalid/second.json");
        var canonical = new Uri("https://example.invalid/shared.json");
        var options = new SchemaValidationOptions(new Dictionary<Uri, JsonValue>
        {
            [first] = JsonReader.Read("{\"$id\":\"https://example.invalid/shared.json\",\"type\":\"integer\"}"),
            [second] = JsonReader.Read("{\"$id\":\"https://example.invalid/shared.json\",\"type\":\"string\"}"),
        });
        var root = SchemaSpec.Coerce(JsonReader.Read("{\"allOf\":[{\"$ref\":\"https://example.invalid/first.json\"},{\"$ref\":\"https://example.invalid/second.json\"}]}"));

        var error = await Assert.ThrowsAsync<SchemaReferenceException>(() => SchemaValidator.ValidateAsync(JsonReader.Read("1"), root, options));

        Assert.Equal(canonical, error.ResourceUri);
        Assert.NotNull(error.NativeInner);
    }

    [Fact]
    public void Structured_deserialization_uses_framework_json_and_preserves_absence_and_metadata_failures()
    {
        var generation = new Generation("", JsonReader.Read("{\"name\":\"Ada\",\"age\":36}"));
        var options = new JsonSerializerOptions
        {
            TypeInfoResolver = new DefaultJsonTypeInfoResolver(),
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            PropertyNameCaseInsensitive = false,
        };
        var typed = generation.DeserializeStructured<StructuredPerson>(options);
        var typeInfo = Assert.IsType<JsonTypeInfo<StructuredPerson>>(options.GetTypeInfo(typeof(StructuredPerson)));

        Assert.Equal("Ada", typed!.Name);
        Assert.Equal(36, generation.DeserializeStructured(typeInfo)!.Age);
        Assert.Throws<InvalidOperationException>(() => new Generation("").DeserializeStructured<StructuredPerson>(options));
        Assert.Throws<JsonException>(() => new Generation("", JsonReader.Read("{\"name\":\"Ada\",\"age\":\"wrong\"}")).DeserializeStructured<StructuredPerson>(options));
    }

    private sealed record StructuredPerson(string Name, int Age);
}
