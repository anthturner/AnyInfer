using AnyInfer.Json;

namespace AnyInfer.Schema;

/// <summary>One structured-output problem identified by a rule name, with optional path segments.</summary>
/// <remarks>
/// <see cref="SchemaViolationException.Issues"/> carries these values. Issues produced by the
/// modern validator carry only <see cref="Rule"/>; their JSON Pointer locations are in the
/// owning <see cref="NativeFinding.NativeFacts"/>.
/// </remarks>
public sealed record Issue
{
    /// <summary>Creates an immutable issue.</summary>
    /// <param name="rule">
    /// The rule name, such as a failing schema keyword, <c>invalid_schema</c>, or an extraction
    /// rule such as <c>response_empty</c>, <c>no_json_candidate</c> or <c>malformed_json_candidate</c>.
    /// </param>
    /// <param name="instancePath">
    /// Path to the failing part of the instance as property-name strings and array-index integers,
    /// or <see langword="null"/> when not reported. The segments are copied.
    /// </param>
    /// <param name="schemaPath">
    /// Path to the failing schema keyword as strings and integers, or <see langword="null"/> when
    /// not reported. The segments are copied.
    /// </param>
    /// <param name="parameters">Rule-specific parameters, or <see langword="null"/> for an empty object.</param>
    /// <exception cref="ArgumentNullException"><paramref name="rule"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">A path segment is neither a <see cref="string"/> nor an <see cref="int"/>.</exception>
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

    /// <summary>Gets the rule name.</summary>
    public string Rule { get; }

    /// <summary>Gets the instance path as string and integer segments, or <see langword="null"/> when not reported.</summary>
    public IReadOnlyList<object>? InstancePath { get; }

    /// <summary>Gets the schema path as string and integer segments, or <see langword="null"/> when not reported.</summary>
    public IReadOnlyList<object>? SchemaPath { get; }

    /// <summary>Gets the rule-specific parameters, empty when none were supplied.</summary>
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
