using System.Numerics;
using System.Text;

namespace AnyInfer.Json;

public static class JsonEquality
{
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

    public static bool NumericControlEquals(JsonValue left, JsonValue right) => SchemaEquals(left, right);

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
