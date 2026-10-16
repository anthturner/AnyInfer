using System.Numerics;
using System.Text;
using AnyInfer.Json;

namespace AnyInfer.Schema;

public static class SchemaValidator
{
    public static NativeAssessment Assess(JsonValue schema, JsonValue instance, Guid operationId, int sourceEntryOrdinal)
    {
        ArgumentNullException.ThrowIfNull(schema);
        ArgumentNullException.ThrowIfNull(instance);
        if (FindMalformedSchema(schema, [], out var malformed))
        {
            return CreateAssessment(operationId, sourceEntryOrdinal, "validation", instance, [malformed!]);
        }
        var findings = new List<NativeFinding>();
        Validate((JsonObject)schema, instance, [], [], findings);
        return CreateAssessment(operationId, sourceEntryOrdinal, "validation", instance, findings);
    }

    public static NativeAssessment AssessResponse(JsonValue schema, string text, Guid operationId, int sourceEntryOrdinal)
    {
        var extraction = ResponseExtractor.Extract(text);
        return extraction.Failure is { } failure
            ? new NativeAssessment(operationId, sourceEntryOrdinal, "extraction", null, [failure], [failure])
            : Assess(schema, extraction.Value!, operationId, sourceEntryOrdinal);
    }

    private static NativeAssessment CreateAssessment(Guid operationId, int ordinal, string kind, JsonValue structured, IReadOnlyList<NativeFinding> all)
    {
        var selected = all.Select(static (finding, index) => (finding, index))
            .OrderByDescending(static item => item.finding.Issue.InstancePath?.Count ?? -1)
            .ThenBy(static item => item.finding.Issue.InstancePath, PathComparer.Instance)
                        .ThenBy(static item => item.index)
            .Take(5)
            .Select(static item => item.finding)
            .ToArray();
        return new NativeAssessment(operationId, ordinal, kind, structured, all, selected);
    }

    private static bool FindMalformedSchema(JsonValue schema, List<object> path, out NativeFinding? finding)
    {
        if (schema is not JsonObject obj)
        {
            finding = InvalidSchema(path, schema, "an object schema");
            return true;
        }
        foreach (var property in obj.Properties)
        {
            var next = Append(path, property.Name);
            var value = property.Value;
            switch (property.Name)
            {
                case "type" when value is not JsonString { Value: var type } || !IsKnownType(type):
                    finding = InvalidSchema(next, value, "a supported type string");
                    return true;
                case "properties" when value is not JsonObject properties:
                    finding = InvalidSchema(next, value, "an object of object schemas");
                    return true;
                case "properties":
                    foreach (var child in ((JsonObject)value).Properties)
                    {
                        if (FindMalformedSchema(child.Value, Append(next, child.Name), out finding))
                        {
                            return true;
                        }
                    }
                    break;
                case "required" when value is not JsonArray required:
                    finding = InvalidSchema(next, value, "an array of unique strings");
                    return true;
                case "required":
                    var names = new HashSet<string>(StringComparer.Ordinal);
                    for (var i = 0; i < ((JsonArray)value).Items.Count; i++)
                    {
                        if (((JsonArray)value).Items[i] is not JsonString name || !names.Add(name.Value))
                        {
                            finding = InvalidSchema(Append(next, i), ((JsonArray)value).Items[i], "a unique string");
                            return true;
                        }
                    }
                    break;
                case "additionalProperties" when value is not JsonBoolean:
                    finding = InvalidSchema(next, value, "a boolean");
                    return true;
                case "items" when value is not JsonObject:
                    finding = InvalidSchema(next, value, "an object schema");
                    return true;
                case "items":
                    if (FindMalformedSchema(value, next, out finding))
                    {
                        return true;
                    }
                    break;
                case "enum" when value is not JsonArray:
                    finding = InvalidSchema(next, value, "an array");
                    return true;
                case "minimum" or "maximum" when !IsNumber(value):
                    finding = InvalidSchema(next, value, "a finite number");
                    return true;
                case "minLength" or "maxLength" or "minItems" or "maxItems" when !IsNonNegativeInteger(value):
                    finding = InvalidSchema(next, value, "a non-negative integer");
                    return true;
                case "title" or "description" or "$comment" when value is not JsonString:
                    finding = InvalidSchema(next, value, "a string");
                    return true;
                case "examples" when value is not JsonArray:
                    finding = InvalidSchema(next, value, "an array");
                    return true;
            }
        }
        finding = null;
        return false;
    }

    private static void Validate(
        JsonObject schema,
        JsonValue instance,
        List<object> instancePath,
        List<object> schemaPath,
        List<NativeFinding> findings)
    {
        foreach (var property in schema.Properties)
        {
            var keyPath = Append(schemaPath, property.Name);
            switch (property.Name)
            {
                case "type":
                    var expected = ((JsonString)property.Value).Value;
                    if (!MatchesType(instance, expected))
                    {
                        Add(
                            findings,
                            "type",
                            instancePath,
                            keyPath,
                            Params(("expected", new JsonString(expected)), ("actual", new JsonString(TypeName(instance)))),
                            property.Value,
                            instance,
                            $"Expected {expected}, got {TypeName(instance)}.");
                    }
                    break;

                case "properties" when instance is JsonObject objectValue:
                    foreach (var child in ((JsonObject)property.Value).Properties)
                    {
                        if (objectValue.TryGetValue(child.Name, out var childValue))
                        {
                            Validate((JsonObject)child.Value, childValue, Append(instancePath, child.Name), Append(keyPath, child.Name), findings);
                        }
                    }
                    break;

                case "required" when instance is JsonObject objectRequired:
                    foreach (var item in ((JsonArray)property.Value).Items)
                    {
                        var name = ((JsonString)item).Value;
                        if (!objectRequired.TryGetValue(name, out _))
                        {
                            Add(findings, "required", instancePath, keyPath, Params(("property", new JsonString(name))), property.Value, instance, $"Required property '{name}' is missing.");
                        }
                    }
                    break;

                case "additionalProperties" when property.Value is JsonBoolean { Value: false } && instance is JsonObject additional:
                    var known = schema.TryGetValue("properties", out var knownValue) && knownValue is JsonObject knownObject
                        ? new HashSet<string>(knownObject.Properties.Select(static item => item.Name), StringComparer.Ordinal)
                        : [];
                    var extra = additional.Properties
                        .Select(static item => item.Name)
                        .Where(name => !known.Contains(name))
                        .OrderBy(static name => name, Comparer<string>.Create(JsonEquality.CompareCodePoints))
                        .ToArray();
                    if (extra.Length > 0)
                    {
                        Add(findings, "additionalProperties", instancePath, keyPath, Params(("unexpected", new JsonArray(extra.Select(static name => (JsonValue)new JsonString(name))))), property.Value, instance, "Unexpected object properties are present.");
                    }
                    break;

                case "items" when instance is JsonArray array:
                    for (var index = 0; index < array.Items.Count; index++)
                    {
                        Validate((JsonObject)property.Value, array.Items[index], Append(instancePath, index), keyPath, findings);
                    }
                    break;

                case "enum":
                    var allowed = (JsonArray)property.Value;
                    if (!allowed.Items.Any(value => JsonEquality.SchemaEquals(value, instance)))
                    {
                        Add(findings, "enum", instancePath, keyPath, Params(("allowed", allowed)), property.Value, instance, "Value is not in enum.");
                    }
                    break;

                case "const" when !JsonEquality.SchemaEquals(property.Value, instance):
                    Add(findings, "const", instancePath, keyPath, Params(("expected", property.Value)), property.Value, instance, "Value does not match const.");
                    break;

                case "minimum" when IsNumber(instance) && CompareNumbers(instance, property.Value) < 0:
                    Add(findings, "minimum", instancePath, keyPath, Params(("limit", property.Value), ("actual", instance)), property.Value, instance, "Value is below minimum.");
                    break;

                case "maximum" when IsNumber(instance) && CompareNumbers(instance, property.Value) > 0:
                    Add(findings, "maximum", instancePath, keyPath, Params(("limit", property.Value), ("actual", instance)), property.Value, instance, "Value exceeds maximum.");
                    break;

                case "minLength" when instance is JsonString text:
                    ValidateBound(findings, "minLength", RuneCount(text.Value), property.Value, instancePath, keyPath, instance, static compare => compare < 0);
                    break;
                case "maxLength" when instance is JsonString text:
                    ValidateBound(findings, "maxLength", RuneCount(text.Value), property.Value, instancePath, keyPath, instance, static compare => compare > 0);
                    break;
                case "minItems" when instance is JsonArray items:
                    ValidateBound(findings, "minItems", items.Items.Count, property.Value, instancePath, keyPath, instance, static compare => compare < 0);
                    break;
                case "maxItems" when instance is JsonArray items:
                    ValidateBound(findings, "maxItems", items.Items.Count, property.Value, instancePath, keyPath, instance, static compare => compare > 0);
                    break;
            }
        }
    }
    private static void ValidateBound(List<NativeFinding> findings, string rule, int actual, JsonValue limit, List<object> instancePath, List<object> schemaPath, JsonValue instance, Func<int, bool> fails)
    {
        var comparison = CompareNumbers(new JsonInteger(actual), limit);
        if (fails(comparison))
        {
            Add(findings, rule, instancePath, schemaPath, Params(("limit", limit), ("actual", new JsonInteger(actual))), limit, instance, $"{rule} bound failed.");
        }
    }

    private static void Add(List<NativeFinding> findings, string rule, IEnumerable<object> instancePath, IEnumerable<object> schemaPath, JsonObject parameters, JsonValue constraint, JsonValue instance, string message)
    {
        var issue = new Issue(rule, instancePath, schemaPath, parameters);
        var facts = new JsonObject([
            new JsonProperty("rule", new JsonString(rule)), new JsonProperty("instance_path", Paths(issue.InstancePath)), new JsonProperty("schema_path", Paths(issue.SchemaPath)),
            new JsonProperty("constraint", constraint), new JsonProperty("instance", instance),
        ]);
        findings.Add(new NativeFinding(issue, message, "schema-validator", facts));
    }

    private static NativeFinding InvalidSchema(IEnumerable<object> path, JsonValue defective, string expectedForm)
    {
        var issue = new Issue("invalid_schema", null, path, new JsonObject([]));
        var facts = new JsonObject([
            new JsonProperty("rule", new JsonString("invalid_schema")), new JsonProperty("instance_path", JsonNull.Instance), new JsonProperty("schema_path", Paths(issue.SchemaPath)),
            new JsonProperty("schema_value", defective), new JsonProperty("expected_form", new JsonString(expectedForm)),
        ]);
        return new NativeFinding(issue, $"Schema keyword must be {expectedForm}.", "schema-validator.meta", facts);
    }

    private static JsonValue Paths(IReadOnlyList<object>? path) => path is null ? JsonNull.Instance : new JsonArray(path.Select(static item => item is string text ? (JsonValue)new JsonString(text) : new JsonInteger((int)item)));
    private static JsonObject Params(params (string Name, JsonValue Value)[] values) => new(values.Select(static item => new JsonProperty(item.Name, item.Value)));
    private static List<object> Append(IEnumerable<object> source, object segment)
    {
        var result = source.ToList();
        result.Add(segment);
        return result;
    }
    private static bool IsKnownType(string value) => value is "object" or "array" or "string" or "number" or "integer" or "boolean" or "null";
    private static bool IsNumber(JsonValue value) => value is JsonInteger or JsonNumber;
    private static bool IsNonNegativeInteger(JsonValue value) => value is JsonInteger integer && integer.Value >= BigInteger.Zero || value is JsonNumber number && double.IsFinite(number.Value) && number.Value >= 0 && Math.Truncate(number.Value) == number.Value;
    private static int RuneCount(string value) => value.EnumerateRunes().Count();
    private static bool MatchesType(JsonValue value, string type) => type switch { "object" => value is JsonObject, "array" => value is JsonArray, "string" => value is JsonString, "number" => IsNumber(value), "integer" => value is JsonInteger || value is JsonNumber number && Math.Truncate(number.Value) == number.Value, "boolean" => value is JsonBoolean, "null" => value is JsonNull, _ => false };
    private static string TypeName(JsonValue value) => value switch { JsonNull => "null", JsonBoolean => "boolean", JsonInteger => "integer", JsonNumber number when Math.Truncate(number.Value) == number.Value => "integer", JsonNumber => "number", JsonString => "string", JsonArray => "array", JsonObject => "object", _ => throw new ArgumentOutOfRangeException(nameof(value)) };

    private static int CompareNumbers(JsonValue left, JsonValue right)
    {
        if (left is JsonInteger leftInteger && right is JsonInteger rightInteger) return leftInteger.Value.CompareTo(rightInteger.Value);
        if (left is JsonNumber leftNumber && right is JsonNumber rightNumber) return leftNumber.Value.CompareTo(rightNumber.Value);
        if (left is JsonInteger integer && right is JsonNumber number) return CompareIntegerDouble(integer.Value, number.Value);
        if (left is JsonNumber reverseNumber && right is JsonInteger reverseInteger) return -CompareIntegerDouble(reverseInteger.Value, reverseNumber.Value);
        throw new ArgumentException("Values must be JSON numbers.");
    }

    private static int CompareIntegerDouble(BigInteger integer, double number)
    {
        var truncated = new BigInteger(Math.Truncate(number));
        var comparison = integer.CompareTo(truncated);
        if (comparison != 0) return comparison;
        if (number == Math.Truncate(number)) return 0;
        return number > 0 ? -1 : 1;
    }

    private sealed class PathComparer : IComparer<IReadOnlyList<object>?>
    {
        public static PathComparer Instance { get; } = new();
        public int Compare(IReadOnlyList<object>? left, IReadOnlyList<object>? right)
        {
            if (ReferenceEquals(left, right))
            {
                return 0;
            }
            if (left is null)
            {
                return -1;
            }

            if (right is null)
            {
                return 1;
            }
            for (var index = 0; index < Math.Min(left.Count, right.Count); index++)
            {
                var comparison = CompareSegment(left[index], right[index]);
                if (comparison != 0)
                {
                    return comparison;
                }
            }
            return left.Count.CompareTo(right.Count);
        }
        private static int CompareSegment(object left, object right) => left is int li && right is int ri ? li.CompareTo(ri) : left is string ls && right is string rs ? JsonEquality.CompareCodePoints(ls, rs) : left is int ? -1 : 1;
    }
}
