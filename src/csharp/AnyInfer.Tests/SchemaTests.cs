using System.Numerics;
using AnyInfer;
using AnyInfer.Json;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

public sealed class SchemaTests
{
    [Theory]
    [InlineData("null")]
    [InlineData("true")]
    [InlineData("17")]
    [InlineData("17.5")]
    [InlineData("\"text\"")]
    [InlineData("[]")]
    [InlineData("{}")]
    public void Type_keyword_accepts_each_declared_json_kind(string instance)
    {
        var value = JsonReader.Read(instance);
        var type = value switch
        {
            JsonNull => "null",
            JsonBoolean => "boolean",
            JsonInteger => "integer",
            JsonNumber => "number",
            JsonString => "string",
            JsonArray => "array",
            JsonObject => "object",
            _ => throw new InvalidOperationException(),
        };

        var assessment = Assess($"{{\"type\":\"{type}\"}}", instance);

        Assert.True(assessment.IsValid);
        Assert.Empty(assessment.AllFindings);
        Assert.Empty(assessment.SelectedFindings);
        Assert.Empty(assessment.Messages);
    }

    [Fact]
    public void Type_keyword_reports_exact_expected_and_actual_without_treating_boolean_as_number()
    {
        var assessment = Assess("{\"type\":\"number\"}", "true");

        var issue = Assert.Single(assessment.Issues);
        Assert.Equal("type", issue.Rule);
        AssertPath(issue.InstancePath);
        AssertPath(issue.SchemaPath, "type");
        Assert.Equal("number", StringValue(issue.Parameters, "expected"));
        Assert.Equal("boolean", StringValue(issue.Parameters, "actual"));
        AssertNativeFailure(assessment);

        var integralFloat = Assess("{\"type\":\"integer\"}", "17.0");
        Assert.True(integralFloat.IsValid);
    }

    [Fact]
    public void Enum_and_const_use_schema_equality_for_numbers_and_nested_values()
    {
        var schema = """
            {"enum":[{"nested":[1,true]},2.0],"const":{"nested":[1,true]}}
            """;

        Assert.True(Assess(schema, "{\"nested\":[1.0,true]}").IsValid);
        var mismatch = Assess(schema, "{\"nested\":[true,1]}");
        Assert.Equal(new[] { "enum", "const" }, mismatch.Issues.Select(issue => issue.Rule));
        Assert.Equal("allowed", mismatch.Issues[0].Parameters.Properties.Single().Name);
        Assert.Equal("expected", mismatch.Issues[1].Parameters.Properties.Single().Name);
    }

    [Fact]
    public void Admitted_annotations_are_literal_schema_data_for_every_json_value_kind()
    {
        var schema = """
            {"title":"title","description":"description","$comment":"comment",
             "examples":[null,true,1,1.5,"text",[],{"$schema_prompt":true}],"enum":[{"nested":[null,false,2.0]}],
             "const":{"nested":[null,false,2.0]}}
            """;

        var assessment = Assess(schema, "{\"nested\":[null,false,2]}");

        Assert.True(assessment.IsValid);
        Assert.Empty(assessment.AllFindings);
    }

    [Fact]
    public void Numeric_bounds_are_inclusive_and_keep_large_integer_controls_exact()
    {
        const string limit = "9007199254740993";
        var schema = "{\"minimum\":" + limit + ",\"maximum\":" + limit + "}";

        Assert.True(Assess(schema, limit).IsValid);
        var below = Assess(schema, "9007199254740992");
        var above = Assess(schema, "9007199254740994");
        Assert.Equal("minimum", Assert.Single(below.Issues).Rule);
        Assert.Equal("maximum", Assert.Single(above.Issues).Rule);
        Assert.Equal(new JsonInteger(BigInteger.Parse(limit)), Value(below.Issues[0].Parameters, "limit"));
        Assert.Equal(new JsonInteger(BigInteger.Parse(limit)), Value(above.Issues[0].Parameters, "limit"));
    }

    [Fact]
    public void Numeric_bounds_do_not_narrow_finite_binary64_values_through_decimal()
    {
        var tinyPositive = Assess("{\"maximum\":0}", "1e-30");
        Assert.Equal("maximum", Assert.Single(tinyPositive.Issues).Rule);

        var largeFinite = Assess("{\"minimum\":0}", "1e100");
        Assert.True(largeFinite.IsValid);
        Assert.Equal("maximum", Assert.Single(Assess("{\"maximum\":0}", "1e100").Issues).Rule);

        var integralFloatLimit = Assess("{\"minimum\":1.0,\"maximum\":1.0}", "1");
        Assert.True(integralFloatLimit.IsValid);

        Assert.True(Assess("{\"minLength\":1.0,\"maxLength\":1.0}", "\"x\"").IsValid);
        Assert.True(Assess("{\"minItems\":1.0,\"maxItems\":1.0}", "[true]").IsValid);
    }

    [Fact]
    public void Numeric_bound_finding_retains_actual_constraint_and_instance_native_facts()
    {
        var schema = Assert.IsType<JsonObject>(JsonReader.Read("{\"maximum\":0}"));
        var instance = JsonReader.Read("1e-30");
        Assert.True(schema.TryGetValue("maximum", out var constraint));
        var assessment = SchemaValidator.Assess(schema, instance, Guid.NewGuid(), 0);

        var finding = Assert.Single(assessment.SelectedFindings);
        Assert.Equal("maximum", finding.Issue.Rule);
        Assert.Same(constraint, Value(finding.NativeFacts, "constraint"));
        Assert.Same(instance, Value(finding.NativeFacts, "instance"));
        Assert.Equal("maximum", StringValue(finding.NativeFacts, "rule"));
        AssertNativePath(finding.NativeFacts, "instance_path");
        AssertNativePath(finding.NativeFacts, "schema_path", "maximum");
        Assert.NotEqual(finding.Issue.Rule, finding.Message);
        Assert.Same(constraint, Value(finding.Issue.Parameters, "limit"));
        Assert.Same(instance, Value(finding.Issue.Parameters, "actual"));
    }

    [Theory]
    [InlineData("minLength", "\"\"", "2147483648")]
    [InlineData("minItems", "[]", "2147483648")]
    [InlineData("minLength", "\"\"", "9223372036854775808")]
    [InlineData("minItems", "[]", "9223372036854775808")]
    public void Nonnegative_length_and_item_bounds_are_admitted_without_int32_overflow(string keyword, string instance, string limit)
    {
        var assessment = Assess("{\"" + keyword + "\":" + limit + "}", instance);

        var issue = Assert.Single(assessment.Issues);
        Assert.Equal(keyword, issue.Rule);
        Assert.DoesNotContain(assessment.Issues, candidate => candidate.Rule == "invalid_schema");
        Assert.Equal(new JsonInteger(BigInteger.Parse(limit)), Value(issue.Parameters, "limit"));
    }

    [Fact]
    public void String_and_array_limits_use_codepoints_and_item_counts()
    {
        var stringAssessment = Assess("{\"minLength\":2,\"maxLength\":2}", "\"😀x\"");
        Assert.True(stringAssessment.IsValid);
        Assert.Equal("minLength", Assert.Single(Assess("{\"minLength\":3}", "\"😀x\"").Issues).Rule);
        Assert.Equal("maxLength", Assert.Single(Assess("{\"maxLength\":1}", "\"😀x\"").Issues).Rule);

        var items = Assess("{\"minItems\":2,\"maxItems\":2}", "[1]");
        Assert.Equal("minItems", Assert.Single(items.Issues).Rule);
        Assert.Equal("maxItems", Assert.Single(Assess("{\"maxItems\":2}", "[1,2,3]").Issues).Rule);
    }

    [Fact]
    public void Required_preserves_schema_array_order_and_selection_is_limited_to_five()
    {
        var assessment = Assess("{\"required\":[\"z\",\"a\",\"m\",\"b\",\"q\",\"lost\"]}", "{}");

        Assert.Equal(new[] { "z", "a", "m", "b", "q", "lost" }, assessment.AllFindings.Select(finding => StringValue(finding.Issue.Parameters, "property")));
        Assert.Equal(5, assessment.SelectedFindings.Count);
        Assert.Equal(new[] { "z", "a", "m", "b", "q" }, assessment.Issues.Select(issue => StringValue(issue.Parameters, "property")));
    }

    [Fact]
    public void Required_finding_retains_native_constraint_and_parent_instance_without_expanding_portable_parameters()
    {
        var schema = Assert.IsType<JsonObject>(JsonReader.Read("{\"required\":[\"age\",\"name\"]}"));
        var instance = Assert.IsType<JsonObject>(JsonReader.Read("{\"name\":\"Ada\"}"));
        Assert.True(schema.TryGetValue("required", out var constraint));
        var assessment = SchemaValidator.Assess(schema, instance, Guid.NewGuid(), 0);

        var finding = Assert.Single(assessment.SelectedFindings);
        Assert.Same(finding, Assert.Single(assessment.AllFindings));
        Assert.Same(finding.Issue, Assert.Single(assessment.Issues));
        Assert.Equal(finding.Message, Assert.Single(assessment.Messages));
        Assert.NotEqual(finding.Issue.Rule, finding.Message);
        Assert.Same(constraint, Value(finding.NativeFacts, "constraint"));
        Assert.Same(instance, Value(finding.NativeFacts, "instance"));
        Assert.Equal("required", StringValue(finding.NativeFacts, "rule"));
        AssertNativePath(finding.NativeFacts, "instance_path");
        AssertNativePath(finding.NativeFacts, "schema_path", "required");
        Assert.Equal("age", StringValue(finding.Issue.Parameters, "property"));
        Assert.Single(finding.Issue.Parameters.Properties);
    }

    [Fact]
    public void Additional_properties_are_aggregated_in_codepoint_order()
    {
        var assessment = Assess("{\"type\":\"object\",\"additionalProperties\":false}", "{\"😀\":1,\"z\":2,\"a\":3}");

        var issue = Assert.Single(assessment.Issues);
        Assert.Equal("additionalProperties", issue.Rule);
        var unexpected = Assert.IsType<JsonArray>(Value(issue.Parameters, "unexpected"));
        Assert.Equal(new[] { "a", "z", "😀" }, unexpected.Items.Cast<JsonString>().Select(item => item.Value));
    }

    [Fact]
    public void Properties_and_items_follow_original_order_and_retain_typed_paths()
    {
        var schema = """
            {"properties":{"z":{"type":"string"},"a":{"type":"integer"}},"items":{"type":"boolean"}}
            """;
        var assessment = Assess(schema, "{\"z\":1,\"a\":true}");

        Assert.Equal(new[] { "type", "type" }, assessment.AllFindings.Select(finding => finding.Issue.Rule));
        AssertPath(assessment.AllFindings[0].Issue.InstancePath, "z");
        AssertPath(assessment.AllFindings[0].Issue.SchemaPath, "properties", "z", "type");
        AssertPath(assessment.AllFindings[1].Issue.InstancePath, "a");

        var itemAssessment = Assess("{\"items\":{\"type\":\"boolean\"}}", "[true,1,false]");
        AssertPath(Assert.Single(itemAssessment.Issues).InstancePath, 1);
        AssertPath(Assert.Single(itemAssessment.Issues).SchemaPath, "items", "type");
    }

    [Fact]
    public void Selection_prefers_deeper_paths_and_distinguishes_dotted_key_from_nested_path()
    {
        var schema = """
            {"properties":{"a.b":{"type":"string"},"a":{"properties":{"b":{"type":"string"}}}}}
            """;
        var assessment = Assess(schema, "{\"a.b\":1,\"a\":{\"b\":1}}");

        Assert.Equal(2, assessment.AllFindings.Count);
        AssertPath(assessment.SelectedFindings[0].Issue.InstancePath, "a", "b");
        AssertPath(assessment.SelectedFindings[1].Issue.InstancePath, "a.b");
    }

    [Theory]
    [InlineData("{\"required\":17}", "required")]
    [InlineData("{\"required\":[17]}", "required", 0)]
    [InlineData("{\"type\":17}", "type")]
    [InlineData("{\"title\":17}", "title")]
    [InlineData("{\"examples\":17}", "examples")]
    [InlineData("{\"properties\":17}", "properties")]
    [InlineData("{\"items\":17}", "items")]
    [InlineData("{\"minLength\":-1}", "minLength")]
    public void Malformed_admitted_keyword_is_late_invalid_schema_with_original_path(string schema, string first, object? second = null)
    {
        var assessment = Assess(schema, "null");

        Assert.Equal("validation", assessment.Kind);
        Assert.False(assessment.IsValid);
        var issue = Assert.Single(assessment.Issues);
        Assert.Equal("invalid_schema", issue.Rule);
        Assert.Null(issue.InstancePath);
        Assert.Empty(issue.Parameters.Properties);
        if (second is null)
        {
            AssertPath(issue.SchemaPath, first);
        }
        else
        {
            AssertPath(issue.SchemaPath, first, second);
        }
    }

    [Fact]
    public void Extraction_distinguishes_null_root_from_absent_value_and_does_not_rescue_later_candidate()
    {
        var parsedNull = ResponseExtractor.Extract("  null\n");
        Assert.Same(JsonNull.Instance, parsedNull.Value);
        Assert.Null(parsedNull.Failure);

        AssertExtractionFailure("", "response_empty");
        AssertExtractionFailure("prose only", "no_json_candidate");
        AssertExtractionFailure("prefix \"{ignored}\" then {\"ok\":true}", "malformed_json_candidate");
        AssertExtractionFailure("prefix {broken} later {\"ok\":true}", "malformed_json_candidate");
        AssertExtractionFailure("prefix {\"unfinished\": [", "no_json_candidate");
    }

    [Fact]
    public void First_malformed_candidate_retains_native_parser_cause_and_never_rescues_later_json()
    {
        var result = ResponseExtractor.Extract("prefix {\"broken\":} later {\"valid\":true}");

        Assert.Null(result.Value);
        var finding = Assert.IsType<NativeFinding>(result.Failure);
        Assert.Equal("malformed_json_candidate", finding.Issue.Rule);
        Assert.Null(finding.Issue.InstancePath);
        Assert.Null(finding.Issue.SchemaPath);
        Assert.Empty(finding.Issue.Parameters.Properties);
        Assert.False(string.IsNullOrWhiteSpace(finding.Message));
        Assert.True(finding.NativeFacts.TryGetValue("exception_type", out var exceptionType));
        Assert.Equal(typeof(FormatException).FullName, Assert.IsType<JsonString>(exceptionType).Value);
        Assert.True(finding.NativeFacts.TryGetValue("exception_message", out var exceptionMessage));
        Assert.False(string.IsNullOrWhiteSpace(Assert.IsType<JsonString>(exceptionMessage).Value));
        Assert.True(finding.NativeFacts.TryGetValue("inner_exception_type", out var innerType));
        var innerTypeName = Assert.IsType<JsonString>(innerType).Value;
        Assert.False(string.IsNullOrWhiteSpace(innerTypeName));
        var resolvedInnerType = typeof(System.Text.Json.JsonException).Assembly.GetType(innerTypeName, throwOnError: true)!;
        Assert.True(typeof(System.Text.Json.JsonException).IsAssignableFrom(resolvedInnerType));
        Assert.True(finding.NativeFacts.TryGetValue("inner_exception_message", out var innerMessage));
        var expectedMessage = Assert.IsType<JsonString>(innerMessage).Value;
        Assert.False(string.IsNullOrWhiteSpace(expectedMessage));
        Assert.NotEqual(finding.Issue.Rule, expectedMessage);
        Assert.Equal(expectedMessage, finding.Message);
        Assert.True(finding.NativeFacts.TryGetValue("line_number", out var lineNumber));
        Assert.True(Assert.IsType<JsonInteger>(lineNumber).Value >= BigInteger.Zero);
        Assert.True(finding.NativeFacts.TryGetValue("byte_position_in_line", out var bytePosition));
        Assert.True(Assert.IsType<JsonInteger>(bytePosition).Value >= BigInteger.Zero);
    }

    [Theory]
    [InlineData("17")]
    [InlineData("\"scalar\"")]
    [InlineData("[1,2]")]
    [InlineData("prose ```json\n{\"x\":1}\n```")]
    [InlineData("prefix \"unterminated quote is ignored then {\"text\":\"} and { remain text\"}")]
    public void Extraction_accepts_whole_values_and_scans_first_balanced_candidate(string text)
    {
        var result = ResponseExtractor.Extract(text);
        Assert.NotNull(result.Value);
        Assert.Null(result.Failure);
    }

    [Fact]
    public void Extraction_keeps_duplicate_first_position_last_value_and_large_integer()
    {
        var value = Assert.IsType<JsonObject>(ResponseExtractor.Extract("{\"x\":1,\"x\":9007199254740993}").Value);
        Assert.Single(value.Properties);
        Assert.Equal("x", value.Properties[0].Name);
        Assert.Equal(new JsonInteger(new BigInteger(9007199254740993)), value.Properties[0].Value);
    }

    [Fact]
    public void Assess_response_short_circuits_extraction_before_malformed_schema()
    {
        var assessment = SchemaValidator.AssessResponse(JsonReader.Read("{\"required\":17}"), "not json", Guid.NewGuid(), 3);

        Assert.Equal("extraction", assessment.Kind);
        Assert.Equal("no_json_candidate", Assert.Single(assessment.Issues).Rule);
        Assert.Null(assessment.Structured);
    }

    [Fact]
    public void Late_invalid_schema_retains_defective_schema_value_and_expected_form_in_native_facts()
    {
        var schema = Assert.IsType<JsonObject>(JsonReader.Read("{\"required\":17}"));
        Assert.True(schema.TryGetValue("required", out var defective));
        var assessment = SchemaValidator.Assess(schema, JsonNull.Instance, Guid.NewGuid(), 0);

        var finding = Assert.Single(assessment.SelectedFindings);
        var issue = Assert.Single(assessment.Issues);
        Assert.Equal("invalid_schema", issue.Rule);
        Assert.Null(issue.InstancePath);
        AssertPath(issue.SchemaPath, "required");
        Assert.Empty(issue.Parameters.Properties);
        Assert.Same(defective, Value(finding.NativeFacts, "schema_value"));
        var expectedForm = StringValue(finding.NativeFacts, "expected_form");
        Assert.False(string.IsNullOrWhiteSpace(expectedForm));
        AssertNativePath(finding.NativeFacts, "schema_path", "required");
        Assert.NotEqual(issue.Rule, finding.Message);
    }

    [Fact]
    public void Assessments_preserve_identity_and_native_findings_without_regenerating_feedback()
    {
        var operation = Guid.NewGuid();
        var first = SchemaValidator.Assess(JsonReader.Read("{\"required\":[\"age\"]}"), JsonReader.Read("{}"), operation, 7);
        var second = SchemaValidator.Assess(JsonReader.Read("{\"required\":[\"age\"]}"), JsonReader.Read("{}"), operation, 7);

        Assert.Equal(operation, first.OperationId);
        Assert.Equal(7, first.SourceEntryOrdinal);
        Assert.NotEqual(first.AssessmentId, second.AssessmentId);
        Assert.Contains(first.SelectedFindings[0], first.AllFindings);
        Assert.Same(first.SelectedFindings[0].Issue, first.Issues[0]);
        Assert.Equal(first.SelectedFindings.Select(finding => finding.Message), first.Messages);
        AssertNativeFailure(first);
    }

    [Fact]
    public void Assessment_constructor_requires_selected_findings_to_be_an_identity_counted_subset()
    {
        var issue = new Issue("required", [], ["required"], new JsonObject([new JsonProperty("property", new JsonString("age"))]));
        var facts = new JsonObject([new JsonProperty("rule", new JsonString("required"))]);
        var finding = new NativeFinding(issue, "native required message", "test", facts);
        var clone = new NativeFinding(issue, "native required message", "test", facts);

        Assert.Throws<ArgumentException>(() => new NativeAssessment(Guid.NewGuid(), 0, "validation", new JsonObject([]), [finding], [clone]));
        Assert.Throws<ArgumentException>(() => new NativeAssessment(Guid.NewGuid(), 0, "validation", new JsonObject([]), [finding], [finding, finding]));

        var duplicateOccurrence = new NativeFinding(issue, "native required message", "test", facts);
        var accepted = new NativeAssessment(Guid.NewGuid(), 0, "validation", new JsonObject([]), [finding, duplicateOccurrence], [finding, duplicateOccurrence]);
        Assert.Same(finding, accepted.SelectedFindings[0]);
        Assert.Same(duplicateOccurrence, accepted.SelectedFindings[1]);
        Assert.Equal(2, accepted.Messages.Count);
    }

    [Fact]
    public void Prompt_renderer_has_exact_literal_instruction_and_canonical_two_space_schema()
    {
        var schema = JsonReader.Read("{\"😀\":\"é\",\"a\":[true,null,1.0]}");
        var expected = "Respond with ONLY a JSON value matching this JSON Schema. No prose. Schema:\n{\n  \"a\": [\n    true,\n    null,\n    1.0\n  ],\n  \"\\ud83d\\ude00\": \"\\u00e9\"\n}";

        Assert.Equal(expected, SchemaPromptRenderer.Render(schema));
    }

    [Fact]
    public void Prompt_renderer_uses_the_original_malformed_schema_without_rewriting_it()
    {
        var malformed = JsonReader.Read("{\"required\":17,\"type\":\"object\"}");

        Assert.Equal(
            "Respond with ONLY a JSON value matching this JSON Schema. No prose. Schema:\n{\n  \"required\": 17,\n  \"type\": \"object\"\n}",
            SchemaPromptRenderer.Render(malformed));
    }

    [Fact]
    public void Prompt_injection_copies_messages_and_appends_to_last_system_or_prepends()
    {
        var schema = JsonReader.Read("{\"type\":\"object\"}");
        var original = new[]
        {
            new Message("system", [new Text("first")]),
            new Message("user", [new Text("literal $repair_feedback text")]),
            new Message("system", [new Text("last")]),
        };
        var injected = SchemaPromptRenderer.InjectPrompt(original, schema);

        Assert.NotSame(original, injected);
        Assert.Equal(3, injected.Count);
        Assert.Single(original[2].Content);
        var last = Assert.IsType<Text>(injected[2].Content[1]);
        Assert.StartsWith("\n\nRespond with ONLY", last.Value, StringComparison.Ordinal);
        Assert.Equal("literal $repair_feedback text", Assert.IsType<Text>(injected[1].Content[0]).Value);

        var withoutSystem = SchemaPromptRenderer.InjectPrompt([new Message("user", [new Text("caller literal prompt")])], schema);
        Assert.Equal("system", withoutSystem[0].Role);
        Assert.Equal("user", withoutSystem[1].Role);
        Assert.Single(SchemaPromptRenderer.InjectPrompt([], schema));
    }

    private static NativeAssessment Assess(string schema, string instance) =>
        SchemaValidator.Assess(JsonReader.Read(schema), JsonReader.Read(instance), Guid.NewGuid(), 0);

    private static void AssertExtractionFailure(string text, string rule)
    {
        var result = ResponseExtractor.Extract(text);
        Assert.Null(result.Value);
        var finding = Assert.IsType<NativeFinding>(result.Failure);
        Assert.Equal(rule, finding.Issue.Rule);
        Assert.Null(finding.Issue.InstancePath);
        Assert.Null(finding.Issue.SchemaPath);
        Assert.Empty(finding.Issue.Parameters.Properties);
        Assert.False(string.IsNullOrWhiteSpace(finding.Message));
        Assert.NotEmpty(finding.NativeFacts.Properties);
    }

    private static void AssertNativeFailure(NativeAssessment assessment)
    {
        Assert.NotEmpty(assessment.AllFindings);
        Assert.NotEmpty(assessment.SelectedFindings);
        Assert.All(assessment.SelectedFindings, finding =>
        {
            Assert.False(string.IsNullOrWhiteSpace(finding.Message));
            Assert.NotEqual(finding.Issue.Rule, finding.Message);
            Assert.NotEmpty(finding.NativeFacts.Properties);
        });
    }

    private static JsonValue Value(JsonObject objectValue, string name)
    {
        Assert.True(objectValue.TryGetValue(name, out var value));
        return value;
    }

    private static string StringValue(JsonObject objectValue, string name) => Assert.IsType<JsonString>(Value(objectValue, name)).Value;

    private static void AssertNativePath(JsonObject facts, string name, params object[] expected)
    {
        var actual = Assert.IsType<JsonArray>(Value(facts, name));
        Assert.Equal(expected.Length, actual.Items.Count);
        for (var index = 0; index < expected.Length; index++)
        {
            var value = expected[index] switch
            {
                string text => (JsonValue)new JsonString(text),
                int number => new JsonInteger(number),
                _ => throw new InvalidOperationException(),
            };
            Assert.Equal(value, actual.Items[index]);
        }
    }

    private static void AssertPath(IReadOnlyList<object>? path, params object[] expected)
    {
        var actual = Assert.IsAssignableFrom<IReadOnlyList<object>>(path);
        Assert.Equal(expected, actual);
    }
}
