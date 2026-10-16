using System.Collections.ObjectModel;
using System.Numerics;

namespace AnyInfer.Json;

public abstract record JsonValue;

public sealed record JsonNull : JsonValue
{
    public static JsonNull Instance { get; } = new();

    private JsonNull()
    {
    }
}

public sealed record JsonBoolean(bool Value) : JsonValue;

public sealed record JsonInteger(BigInteger Value) : JsonValue;

public sealed record JsonNumber : JsonValue
{
    public JsonNumber(double value, string? sourceLexeme = null)
    {
        if (!double.IsFinite(value))
        {
            throw new ArgumentOutOfRangeException(nameof(value), "JSON numbers must be finite.");
        }

        Value = value;
        SourceLexeme = sourceLexeme;
    }

    public double Value { get; }

    public string? SourceLexeme { get; }

    public bool IsNegativeZero => BitConverter.DoubleToInt64Bits(Value) == long.MinValue;
}

public sealed record JsonString : JsonValue
{
    public JsonString(string value)
    {
        Value = value ?? throw new ArgumentNullException(nameof(value));
    }

    public string Value { get; }
}

public sealed record JsonArray : JsonValue
{
    public JsonArray(IEnumerable<JsonValue> items)
    {
        ArgumentNullException.ThrowIfNull(items);
        Items = Array.AsReadOnly(items.Select(static item => item ?? throw new ArgumentException("JSON arrays cannot contain null references.")).ToArray());
    }

    public IReadOnlyList<JsonValue> Items { get; }
}

public sealed record JsonProperty
{
    public JsonProperty(string name, JsonValue value)
    {
        Name = name ?? throw new ArgumentNullException(nameof(name));
        Value = value ?? throw new ArgumentNullException(nameof(value));
    }

    public string Name { get; }

    public JsonValue Value { get; }
}

public sealed record JsonObject : JsonValue
{
    private readonly IReadOnlyDictionary<string, JsonValue> _values;

    public JsonObject(IEnumerable<JsonProperty> properties)
    {
        ArgumentNullException.ThrowIfNull(properties);
        var ordered = new List<JsonProperty>();
        var positions = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var property in properties)
        {
            ArgumentNullException.ThrowIfNull(property);
            if (positions.TryGetValue(property.Name, out var index))
            {
                ordered[index] = property;
            }
            else
            {
                positions.Add(property.Name, ordered.Count);
                ordered.Add(property);
            }
        }

        Properties = Array.AsReadOnly(ordered.ToArray());
        _values = new ReadOnlyDictionary<string, JsonValue>(Properties.ToDictionary(
            static property => property.Name,
            static property => property.Value,
            StringComparer.Ordinal));
    }

    public IReadOnlyList<JsonProperty> Properties { get; }

    public bool TryGetValue(string name, out JsonValue value)
    {
        ArgumentNullException.ThrowIfNull(name);
        return _values.TryGetValue(name, out value!);
    }
}
