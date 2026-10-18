using System.Text;
using AnyInfer.Json;

namespace AnyInfer.Manifest;

public static partial class ManifestUtilities
{
    private static readonly Lazy<JsonObject> EmbeddedSchema = new(LoadEmbeddedSchema);

    /// <summary>Loads the immutable format-one manifest JSON Schema embedded in this assembly.</summary>
    /// <returns>The schema generated from Python's public manifest schema helper.</returns>
    public static JsonObject JsonSchema() => EmbeddedSchema.Value;

    private static JsonObject LoadEmbeddedSchema()
    {
        var assembly = typeof(ManifestUtilities).Assembly;
        using var stream = assembly.GetManifestResourceStream("AnyInfer.Manifest.manifest.schema.json")
            ?? throw new InvalidOperationException("The embedded manifest schema resource is missing.");
        using var reader = new StreamReader(stream, new UTF8Encoding(false, true), detectEncodingFromByteOrderMarks: false);
        if (JsonReader.ReadModern(reader.ReadToEnd()) is not JsonObject schema)
        {
            throw new InvalidOperationException("The embedded manifest schema must be a JSON object.");
        }

        return schema;
    }
}
