using System.Collections.ObjectModel;
using System.Numerics;

namespace AnyInfer.Json;

/// <summary>
/// Base type of the immutable native JSON value model used for schemas, tool arguments,
/// provider options, raw payloads and manifests.
/// </summary>
/// <remarks>
/// A value is exactly one of <see cref="JsonNull"/>, <see cref="JsonBoolean"/>,
/// <see cref="JsonInteger"/>, <see cref="JsonNumber"/>, <see cref="JsonString"/>,
/// <see cref="JsonArray"/> or <see cref="JsonObject"/>. Integers and non-integer numbers are
/// distinct kinds. Record equality on arrays and objects compares their collections by
/// reference; use <see cref="JsonEquality"/> to compare JSON values structurally.
/// </remarks>
public abstract record JsonValue
{
    /// <summary>Initializes the base part of a derived JSON value.</summary>
    /// <remarks>
    /// This is the constructor the compiler would otherwise generate implicitly. The SDK handles
    /// only the value kinds listed on <see cref="JsonValue"/>; <see cref="JsonWriter"/> rejects
    /// any other derived type.
    /// </remarks>
    protected JsonValue()
    {
    }
}

/// <summary>The JSON <c>null</c> value.</summary>
public sealed record JsonNull : JsonValue
{
    /// <summary>Gets the shared JSON <c>null</c> value; this type has no public constructor.</summary>
    public static JsonNull Instance { get; } = new();

    private JsonNull()
    {
    }
}

/// <summary>A JSON <c>true</c> or <c>false</c> value.</summary>
/// <param name="Value">The Boolean value.</param>
public sealed record JsonBoolean(bool Value) : JsonValue;

/// <summary>A JSON integer of arbitrary size.</summary>
/// <remarks>
/// <see cref="JsonReader"/> produces this kind for number lexemes without a fraction or
/// exponent. <see cref="JsonReader"/> and <see cref="JsonWriter"/> accept only integers whose
/// magnitude is at most 2^63; other SDK paths, such as
/// <see cref="AnyInfer.SchemaSpec.FromJson(string)"/>, retain larger integers.
/// </remarks>
/// <param name="Value">The integer value.</param>
public sealed record JsonInteger(BigInteger Value) : JsonValue;

/// <summary>A finite JSON number that is not represented as an integer.</summary>
public sealed record JsonNumber : JsonValue
{
    /// <summary>Creates a finite JSON number.</summary>
    /// <param name="value">The finite double-precision value.</param>
    /// <param name="sourceLexeme">
    /// The original JSON number text, or <see langword="null"/> when the number was not read from
    /// text. <see cref="JsonWriter.Write(JsonValue)"/> reuses it only when it is a valid JSON
    /// number with a fraction or exponent that parses back to exactly <paramref name="value"/>.
    /// </param>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="value"/> is NaN or infinite.</exception>
    public JsonNumber(double value, string? sourceLexeme = null)
    {
        if (!double.IsFinite(value))
        {
            throw new ArgumentOutOfRangeException(nameof(value), "JSON numbers must be finite.");
        }

        Value = value;
        SourceLexeme = sourceLexeme;
    }

    /// <summary>Gets the finite double-precision value.</summary>
    public double Value { get; }

    /// <summary>Gets the original JSON number text, or <see langword="null"/> when none was retained.</summary>
    public string? SourceLexeme { get; }

    /// <summary>Gets whether <see cref="Value"/> is negative zero.</summary>
    public bool IsNegativeZero => BitConverter.DoubleToInt64Bits(Value) == long.MinValue;
}

/// <summary>A JSON string value.</summary>
public sealed record JsonString : JsonValue
{
    /// <summary>Creates a JSON string.</summary>
    /// <param name="value">
    /// The string content. <see cref="JsonWriter"/> rejects content that contains an unpaired
    /// UTF-16 surrogate.
    /// </param>
    /// <exception cref="ArgumentNullException"><paramref name="value"/> is <see langword="null"/>.</exception>
    public JsonString(string value)
    {
        Value = value ?? throw new ArgumentNullException(nameof(value));
    }

    /// <summary>Gets the string content.</summary>
    public string Value { get; }
}

/// <summary>An immutable ordered JSON array.</summary>
/// <remarks>
/// Record equality compares <see cref="Items"/> by reference; use <see cref="JsonEquality"/> for
/// structural comparison.
/// </remarks>
public sealed record JsonArray : JsonValue
{
    /// <summary>Creates an array from a copy of the supplied items.</summary>
    /// <param name="items">The items in array order; use <see cref="JsonNull.Instance"/> for JSON <c>null</c>.</param>
    /// <exception cref="ArgumentNullException"><paramref name="items"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="items"/> contains a <see langword="null"/> reference.</exception>
    public JsonArray(IEnumerable<JsonValue> items)
    {
        ArgumentNullException.ThrowIfNull(items);
        Items = Array.AsReadOnly(items.Select(static item => item ?? throw new ArgumentException("JSON arrays cannot contain null references.")).ToArray());
    }

    /// <summary>Gets the copied items in array order.</summary>
    public IReadOnlyList<JsonValue> Items { get; }
}

/// <summary>One immutable name and value pair of a <see cref="JsonObject"/>.</summary>
public sealed record JsonProperty
{
    /// <summary>Creates a property.</summary>
    /// <param name="name">The property name; <see cref="JsonObject"/> compares names ordinally.</param>
    /// <param name="value">The property value; use <see cref="JsonNull.Instance"/> for JSON <c>null</c>.</param>
    /// <exception cref="ArgumentNullException"><paramref name="name"/> or <paramref name="value"/> is <see langword="null"/>.</exception>
    public JsonProperty(string name, JsonValue value)
    {
        Name = name ?? throw new ArgumentNullException(nameof(name));
        Value = value ?? throw new ArgumentNullException(nameof(value));
    }

    /// <summary>Gets the property name.</summary>
    public string Name { get; }

    /// <summary>Gets the property value.</summary>
    public JsonValue Value { get; }
}

/// <summary>An immutable JSON object whose property names are unique under ordinal comparison.</summary>
/// <remarks>
/// Record equality compares the property collection by reference; use <see cref="JsonEquality"/>
/// for structural comparison.
/// </remarks>
public sealed record JsonObject : JsonValue
{
    private readonly IReadOnlyDictionary<string, JsonValue> _values;

    /// <summary>Creates an object from a copy of the supplied properties.</summary>
    /// <param name="properties">
    /// The properties in order. When a name repeats, the later value replaces the earlier one and
    /// keeps the position where the name first appeared.
    /// </param>
    /// <exception cref="ArgumentNullException"><paramref name="properties"/> or one of its elements is <see langword="null"/>.</exception>
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

    /// <summary>Gets the properties in their retained order, each name appearing once.</summary>
    public IReadOnlyList<JsonProperty> Properties { get; }

    /// <summary>Looks up a property value by exact, ordinal name.</summary>
    /// <param name="name">The property name to find.</param>
    /// <param name="value">
    /// When this method returns <see langword="true"/>, the property value; otherwise
    /// <see langword="null"/>.
    /// </param>
    /// <returns><see langword="true"/> when the object has a property with that name.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="name"/> is <see langword="null"/>.</exception>
    public bool TryGetValue(string name, out JsonValue value)
    {
        ArgumentNullException.ThrowIfNull(name);
        return _values.TryGetValue(name, out value!);
    }
}
