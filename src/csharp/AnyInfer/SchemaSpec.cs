using System.Text.Json;
using AnyInfer.Json;

namespace AnyInfer;

/// <summary>Pairs a JSON Schema document with its provider-facing name.</summary>
public sealed record SchemaSpec
{
    /// <summary>Creates a schema specification without validating its schema keywords.</summary>
    /// <param name="jsonSchema">
    /// The JSON Schema document, kept as supplied. <see cref="AnyInfer.Schema.SchemaValidator"/> supports
    /// Draft 6, Draft 7, Draft 2019-09 and Draft 2020-12 documents.
    /// </param>
    /// <param name="name">The schema name sent to providers that accept one; defaults to <c>response</c>.</param>
    /// <exception cref="ArgumentNullException"><paramref name="jsonSchema"/> or <paramref name="name"/> is <see langword="null"/>.</exception>
    public SchemaSpec(JsonValue jsonSchema, string name = "response")
    {
        JsonSchema = jsonSchema ?? throw new ArgumentNullException(nameof(jsonSchema));
        Name = name ?? throw new ArgumentNullException(nameof(name));
    }

    /// <summary>Gets the JSON Schema document as supplied.</summary>
    public JsonValue JsonSchema { get; }

    /// <summary>Gets the provider-facing schema name.</summary>
    public string Name { get; }

    /// <summary>Returns an existing specification unchanged.</summary>
    /// <param name="schema">The specification to return.</param>
    /// <returns>The same <paramref name="schema"/> instance.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="schema"/> is <see langword="null"/>.</exception>
    public static SchemaSpec Coerce(SchemaSpec schema) => schema ?? throw new ArgumentNullException(nameof(schema));

    /// <summary>Creates a specification from an object-shaped JSON Schema document.</summary>
    /// <param name="schema">The schema document, which must be a <see cref="JsonObject"/>.</param>
    /// <returns>
    /// A specification named after the schema's non-empty string <c>title</c>, or
    /// <c>response</c> when it has none.
    /// </returns>
    /// <exception cref="ArgumentException"><paramref name="schema"/> is <see langword="null"/> or not a JSON object.</exception>
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
    /// <param name="schema">The element holding an object-shaped schema; its raw JSON text is parsed as by <see cref="FromJson(string)"/>.</param>
    /// <returns>A specification named as described for <see cref="Coerce(JsonValue)"/>.</returns>
    /// <exception cref="FormatException">The element's JSON text cannot be read as strict JSON.</exception>
    /// <exception cref="ArgumentException">The element is not a JSON object.</exception>
    public static SchemaSpec Coerce(JsonElement schema) => FromJson(schema.GetRawText());

    /// <summary>Creates a specification from JSON text.</summary>
    /// <remarks>
    /// The text is read as strict JSON. Unlike <see cref="JsonReader.Read(string)"/>, integers of
    /// any size are retained.
    /// </remarks>
    /// <param name="json">JSON text holding an object-shaped schema.</param>
    /// <returns>A specification named as described for <see cref="Coerce(JsonValue)"/>.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="json"/> is <see langword="null"/>.</exception>
    /// <exception cref="FormatException"><paramref name="json"/> is not strict JSON.</exception>
    /// <exception cref="ArgumentException">The JSON value is not an object.</exception>
    public static SchemaSpec FromJson(string json) => Coerce(JsonReader.ReadModern(json));

    /// <summary>Converts a JSON object schema to a specification.</summary>
    /// <param name="schema">The object-shaped schema document, or <see langword="null"/>.</param>
    /// <returns>
    /// <see langword="null"/> for a <see langword="null"/> input; otherwise the result of
    /// <see cref="Coerce(JsonValue)"/>.
    /// </returns>
    /// <exception cref="ArgumentException"><paramref name="schema"/> is not a JSON object.</exception>
    public static implicit operator SchemaSpec?(JsonValue? schema) => schema is null ? null : Coerce(schema);
}
