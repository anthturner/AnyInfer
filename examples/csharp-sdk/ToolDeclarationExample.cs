using System.ComponentModel;
using AnyInfer.Json;

namespace AnyInfer.Examples;

/// <summary>Declares tools from a CLR method and from an explicit schema with a tagged-JSON callback.</summary>
public static class ToolDeclarationExample
{
    // --8<-- [start:delegate]
    /// <summary>Searches a small in-memory documentation index.</summary>
    [Description("Search the documentation index.")]
    public static string[] SearchDocs(string query, int limit = 10) =>
        new[] { "guides/fallback.md", "guides/streaming.md", "guides/tool-loop.md" }
            .Where(page => page.Contains(query, StringComparison.OrdinalIgnoreCase))
            .Take(limit)
            .ToArray();

    /// <summary>Binds <see cref="SearchDocs"/> as a tool: the schema comes from its parameters.</summary>
    public static Tool Search() =>
        Tool.From((Func<string, int, string[]>)SearchDocs, name: "search_docs");
    // --8<-- [end:delegate]

    // --8<-- [start:explicit-spec]
    /// <summary>Creates a stock tool from an explicit declaration and a tagged-JSON callback.</summary>
    public static Tool Inventory(IReadOnlyDictionary<string, int> stock)
    {
        var spec = new ToolSpec(
            "check_stock",
            "Returns how many units of one SKU are in stock.",
            (JsonObject)JsonReader.Read("""
                {
                  "type": "object",
                  "properties": {"sku": {"type": "string", "pattern": "^[A-Z]{3}-[0-9]{4}$"}},
                  "required": ["sku"],
                  "additionalProperties": false
                }
                """));
        return new Tool(spec, (arguments, cancellationToken) =>
        {
            cancellationToken.ThrowIfCancellationRequested();
            // The callback receives the model's raw arguments: the declared schema is not enforced for you.
            if (!arguments.TryGetValue("sku", out var value) || value is not JsonString { Value: var sku })
            {
                throw new ArgumentException("sku must be a string.");
            }

            if (!stock.TryGetValue(sku, out var units))
            {
                throw new KeyNotFoundException($"Unknown SKU {sku}.");
            }

            // A dictionary, list or JsonValue result reaches the model as compact JSON.
            return ValueTask.FromResult<object?>(new Dictionary<string, object> { ["sku"] = sku, ["units"] = units });
        });
    }
    // --8<-- [end:explicit-spec]
}
