using System.Text.Json;
using AnyInfer.Json;

namespace AnyInfer;

/// <summary>Pairs a JSON Schema document with its provider-facing name.</summary>
public sealed record SchemaSpec
{
    /// <summary>Creates a schema specification without validating its schema keywords.</summary>
    public SchemaSpec(JsonValue jsonSchema, string name = "response")
    {
        JsonSchema = jsonSchema ?? throw new ArgumentNullException(nameof(jsonSchema));
        Name = name ?? throw new ArgumentNullException(nameof(name));
    }

    /// <summary>Gets the canonical JSON Schema document.</summary>
    public JsonValue JsonSchema { get; }

    /// <summary>Gets the provider-facing schema name.</summary>
    public string Name { get; }

    /// <summary>Returns an existing specification unchanged.</summary>
    public static SchemaSpec Coerce(SchemaSpec schema) => schema ?? throw new ArgumentNullException(nameof(schema));

    /// <summary>Creates a specification from an object-shaped JSON Schema document.</summary>
    public static SchemaSpec Coerce(JsonValue schema)
    {
        if (schema is not JsonObject value)
        {
            throw new ArgumentException("A schema specification must be a JSON object.", nameof(schema));
        }

        var name = value.TryGetValue("title", out var title) && title is JsonString { Value.Length: > 0 } text
            ? text.Value
            : "response";
        return new SchemaSpec(value, name);
    }

    /// <summary>Creates a specification from a System.Text.Json element.</summary>
    public static SchemaSpec Coerce(JsonElement schema) => FromJson(schema.GetRawText());

    /// <summary>Creates a specification from JSON text.</summary>
    public static SchemaSpec FromJson(string json) => Coerce(JsonReader.ReadModern(json));

    /// <summary>Converts a JSON object schema to a specification.</summary>
    public static implicit operator SchemaSpec?(JsonValue? schema) => schema is null ? null : Coerce(schema);
}
