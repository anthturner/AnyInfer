using AnyInfer.Json;

namespace AnyInfer.Schema;

/// <summary>Admits only the frozen v0 JSON Schema surface before native execution.</summary>
public static class SchemaAdmission
{
    private const string Draft202012 = "https://json-schema.org/draft/2020-12/schema";

    private static readonly HashSet<string> ReferenceKeywords = new(StringComparer.Ordinal)
    {
        "$ref", "$defs", "$id", "$anchor",
    };

    private static readonly HashSet<string> ExcludedKeywords = new(StringComparer.Ordinal)
    {
        "allOf", "anyOf", "oneOf", "not", "if", "then", "else",
        "prefixItems", "contains", "uniqueItems", "multipleOf",
        "exclusiveMinimum", "exclusiveMaximum", "minProperties", "maxProperties",
        "pattern", "patternProperties", "propertyNames", "format",
        "dependentRequired", "dependentSchemas", "unevaluatedProperties", "unevaluatedItems",
    };

    private static readonly HashSet<string> AdmittedKeywords = new(StringComparer.Ordinal)
    {
        "$schema", "type", "properties", "required", "additionalProperties", "items",
        "enum", "const", "minimum", "maximum", "minLength", "maxLength", "minItems",
        "maxItems", "title", "description", "$comment", "default", "examples",
    };

    /// <summary>Validates the profile-admitted schema subset; a null reference means no schema.</summary>
    public static void Validate(JsonValue? schema)
    {
        if (schema is null)
        {
            return;
        }

        if (schema is not JsonObject root)
        {
            ThrowUnsupported("The v0 profile requires an object schema.");
            return;
        }

        Scan(root);
    }

    private static void Scan(JsonObject schema)
    {
        // Explicitly excluded forms take precedence over malformed admitted values.
        foreach (var property in schema.Properties)
        {
            if (ReferenceKeywords.Contains(property.Name))
            {
                ThrowUnsupported("Schema references are outside the v0 profile.");
            }

            if (ExcludedKeywords.Contains(property.Name))
            {
                ThrowUnsupported("This schema keyword is outside the v0 profile.");
            }

            if (!AdmittedKeywords.Contains(property.Name))
            {
                ThrowUnsupported("Unknown schema keywords are outside the v0 profile.");
            }

            if (property.Name == "$schema" &&
                property.Value is not JsonString { Value: Draft202012 })
            {
                ThrowUnsupported("Only the draft 2020-12 schema dialect is admitted.");
            }

            if (property.Name == "type" && property.Value is JsonArray)
            {
                ThrowUnsupported("Union schema types are outside the v0 profile.");
            }

            if (property.Name == "additionalProperties" && property.Value is JsonObject)
            {
                ThrowUnsupported("Schema-valued additionalProperties is outside the v0 profile.");
            }

            if (property.Name == "items" && property.Value is JsonBoolean or JsonArray)
            {
                ThrowUnsupported("This items form is outside the v0 profile.");
            }
        }

        foreach (var property in schema.Properties)
        {
            switch (property.Name)
            {
                case "properties" when property.Value is JsonObject properties:
                    foreach (var child in properties.Properties)
                    {
                        if (child.Value is JsonBoolean)
                        {
                            ThrowUnsupported("Boolean subschemas are outside the v0 profile.");
                        }

                        if (child.Value is JsonObject childSchema)
                        {
                            Scan(childSchema);
                        }
                    }

                    break;
                case "items" when property.Value is JsonObject itemSchema:
                    Scan(itemSchema);
                    break;
            }
        }
    }

    private static void ThrowUnsupported(string detail) =>
        throw new ProviderException(
            "The request uses a schema feature outside the core-generation v0 profile.",
            "unsupported_input",
            retryable: false,
            phase: "generate",
            detail: detail,
            hint: "Use the admitted core-generation v0 schema subset.");
}
