using System.Numerics;
using System.Text;

namespace AnyInfer.Json;

/// <summary>Structural comparisons for native <see cref="JsonValue"/> trees.</summary>
/// <remarks>
/// Every comparison compares strings ordinally, arrays element by element in order, and
/// objects by property name regardless of property order.
/// </remarks>
public static class JsonEquality
{
    /// <summary>Compares two values structurally, requiring the same JSON value kind at every position.</summary>
    /// <remarks>
    /// A <see cref="JsonInteger"/> never equals a <see cref="JsonNumber"/>, even with the same
    /// mathematical value, and numbers compare by exact bit pattern, so <c>0.0</c> and
    /// <c>-0.0</c> differ. Source lexemes are ignored.
    /// </remarks>
    /// <param name="left">The first value.</param>
    /// <param name="right">The second value.</param>
    /// <returns><see langword="true"/> when the values are structurally identical.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="left"/> or <paramref name="right"/> is <see langword="null"/>.</exception>
    public static bool TypeAwareEquals(JsonValue left, JsonValue right)
    {
        ArgumentNullException.ThrowIfNull(left);
        ArgumentNullException.ThrowIfNull(right);
        if (left.GetType() != right.GetType())
        {
            return false;
        }

        return (left, right) switch
        {
            (JsonNull, JsonNull) => true,
            (JsonBoolean a, JsonBoolean b) => a.Value == b.Value,
            (JsonInteger a, JsonInteger b) => a.Value == b.Value,
            (JsonNumber a, JsonNumber b) => BitConverter.DoubleToInt64Bits(a.Value) == BitConverter.DoubleToInt64Bits(b.Value),
            (JsonString a, JsonString b) => string.Equals(a.Value, b.Value, StringComparison.Ordinal),
            (JsonArray a, JsonArray b) => a.Items.Count == b.Items.Count && a.Items.Zip(b.Items).All(static pair => TypeAwareEquals(pair.First, pair.Second)),
            (JsonObject a, JsonObject b) => ObjectEquals(a, b, TypeAwareEquals),
            _ => false,
        };
    }

    /// <summary>Compares two values with JSON Schema equality, where numbers compare by mathematical value.</summary>
    /// <remarks>
    /// An integer equals a number with the same exact value (<c>1</c> equals <c>1.0</c>), and
    /// <c>0.0</c> equals <c>-0.0</c>. All other kinds must match.
    /// </remarks>
    /// <param name="left">The first value.</param>
    /// <param name="right">The second value.</param>
    /// <returns><see langword="true"/> when the values are equal under JSON Schema equality.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="left"/> or <paramref name="right"/> is <see langword="null"/>.</exception>
    public static bool SchemaEquals(JsonValue left, JsonValue right)
    {
        ArgumentNullException.ThrowIfNull(left);
        ArgumentNullException.ThrowIfNull(right);
        if (TryNumericEquals(left, right, out var numeric))
        {
            return numeric;
        }

        return (left, right) switch
        {
            (JsonNull, JsonNull) => true,
            (JsonBoolean a, JsonBoolean b) => a.Value == b.Value,
            (JsonString a, JsonString b) => string.Equals(a.Value, b.Value, StringComparison.Ordinal),
            (JsonArray a, JsonArray b) => a.Items.Count == b.Items.Count && a.Items.Zip(b.Items).All(static pair => SchemaEquals(pair.First, pair.Second)),
            (JsonObject a, JsonObject b) => ObjectEquals(a, b, SchemaEquals),
            _ => false,
        };
    }

    /// <summary>Compares two values exactly as <see cref="SchemaEquals(JsonValue, JsonValue)"/> does.</summary>
    /// <param name="left">The first value.</param>
    /// <param name="right">The second value.</param>
    /// <returns><see langword="true"/> when the values are equal under JSON Schema equality.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="left"/> or <paramref name="right"/> is <see langword="null"/>.</exception>
    public static bool NumericControlEquals(JsonValue left, JsonValue right) => SchemaEquals(left, right);

    /// <summary>Orders two strings by Unicode code point rather than by UTF-16 code unit.</summary>
    /// <remarks>An unpaired surrogate compares as U+FFFD.</remarks>
    /// <param name="left">The first string.</param>
    /// <param name="right">The second string.</param>
    /// <returns>
    /// A negative value when <paramref name="left"/> sorts first, zero when the strings are
    /// equal, or a positive value when <paramref name="right"/> sorts first.
    /// </returns>
    /// <exception cref="ArgumentNullException"><paramref name="left"/> or <paramref name="right"/> is <see langword="null"/>.</exception>
    public static int CompareCodePoints(string left, string right)
    {
        ArgumentNullException.ThrowIfNull(left);
        ArgumentNullException.ThrowIfNull(right);
        var leftRunes = left.EnumerateRunes().GetEnumerator();
        var rightRunes = right.EnumerateRunes().GetEnumerator();
        while (true)
        {
            var hasLeft = leftRunes.MoveNext();
            var hasRight = rightRunes.MoveNext();
            if (!hasLeft || !hasRight)
            {
                return hasLeft == hasRight ? 0 : hasLeft ? 1 : -1;
            }

            var comparison = leftRunes.Current.Value.CompareTo(rightRunes.Current.Value);
            if (comparison != 0)
            {
                return comparison;
            }
        }
    }

    private static bool ObjectEquals(JsonObject left, JsonObject right, Func<JsonValue, JsonValue, bool> equals)
    {
        if (left.Properties.Count != right.Properties.Count)
        {
            return false;
        }

        foreach (var property in left.Properties)
        {
            if (!right.TryGetValue(property.Name, out var other) || !equals(property.Value, other))
            {
                return false;
            }
        }

        return true;
    }

    private static bool TryNumericEquals(JsonValue left, JsonValue right, out bool result)
    {
        if (left is JsonInteger leftInteger && right is JsonInteger rightInteger)
        {
            result = leftInteger.Value == rightInteger.Value;
            return true;
        }

        if (left is JsonNumber leftNumber && right is JsonNumber rightNumber)
        {
            result = leftNumber.Value == rightNumber.Value;
            return true;
        }

        if (left is JsonInteger integer && right is JsonNumber number)
        {
            result = IntegerEqualsDouble(integer.Value, number.Value);
            return true;
        }

        if (left is JsonNumber reverseNumber && right is JsonInteger reverseInteger)
        {
            result = IntegerEqualsDouble(reverseInteger.Value, reverseNumber.Value);
            return true;
        }

        result = false;
        return false;
    }

    private static bool IntegerEqualsDouble(BigInteger integer, double number)
    {
        if (!double.IsFinite(number) || Math.Truncate(number) != number)
        {
            return false;
        }

        return integer == new BigInteger(number);
    }
}
