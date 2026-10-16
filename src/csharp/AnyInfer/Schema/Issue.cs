using AnyInfer.Json;

namespace AnyInfer.Schema;

public sealed record Issue
{
    public Issue(
        string rule,
        IEnumerable<object>? instancePath = null,
        IEnumerable<object>? schemaPath = null,
        JsonObject? parameters = null)
    {
        Rule = rule ?? throw new ArgumentNullException(nameof(rule));
        InstancePath = CopySegments(instancePath, nameof(instancePath));
        SchemaPath = CopySegments(schemaPath, nameof(schemaPath));
        Parameters = parameters ?? new JsonObject([]);
    }

    public string Rule { get; }

    public IReadOnlyList<object>? InstancePath { get; }

    public IReadOnlyList<object>? SchemaPath { get; }

    public JsonObject Parameters { get; }

    private static IReadOnlyList<object>? CopySegments(IEnumerable<object>? segments, string parameterName)
    {
        if (segments is null)
        {
            return null;
        }

        var copy = segments.ToArray();
        if (copy.Any(static segment => segment is not string and not int))
        {
            throw new ArgumentException("Path segments must be strings or integers.", parameterName);
        }

        return Array.AsReadOnly(copy);
    }
}
