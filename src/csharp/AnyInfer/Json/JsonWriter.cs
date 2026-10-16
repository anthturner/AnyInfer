using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;

namespace AnyInfer.Json;

public static partial class JsonWriter
{
    private static readonly BigInteger IntegerLimit = BigInteger.One << 63;

    public static string Write(JsonValue value)
    {
        ArgumentNullException.ThrowIfNull(value);
        var builder = new StringBuilder();
        Append(value, builder, canonical: false, depth: 0);
        return builder.ToString();
    }

    public static string WriteCanonical(JsonValue value)
    {
        ArgumentNullException.ThrowIfNull(value);
        var builder = new StringBuilder();
        Append(value, builder, canonical: true, depth: 0);
        return builder.ToString();
    }

    private static void Append(JsonValue value, StringBuilder builder, bool canonical, int depth)
    {
        switch (value)
        {
            case JsonNull:
                builder.Append("null");
                return;
            case JsonBoolean boolean:
                builder.Append(boolean.Value ? "true" : "false");
                return;
            case JsonInteger integer:
                if (BigInteger.Abs(integer.Value) > IntegerLimit)
                {
                    throw new ArgumentOutOfRangeException(nameof(value), "JSON integer is outside the portable v0 range.");
                }

                builder.Append(integer.Value.ToString(CultureInfo.InvariantCulture));
                return;
            case JsonNumber number:
                builder.Append(FormatNumber(number, canonical));
                return;
            case JsonString text:
                AppendString(text.Value, builder, canonical);
                return;
            case JsonArray array:
                AppendArray(array, builder, canonical, depth);
                return;
            case JsonObject obj:
                AppendObject(obj, builder, canonical, depth);
                return;
            default:
                throw new ArgumentOutOfRangeException(nameof(value), "Unknown JSON value.");
        }
    }

    private static void AppendArray(JsonArray array, StringBuilder builder, bool canonical, int depth)
    {
        if (array.Items.Count == 0)
        {
            builder.Append("[]");
            return;
        }

        builder.Append('[');
        for (var index = 0; index < array.Items.Count; index++)
        {
            if (canonical)
            {
                if (index > 0)
                {
                    builder.Append(',');
                }

                builder.Append('\n').Append(' ', (depth + 1) * 2);
            }
            else if (index > 0)
            {
                builder.Append(',');
            }

            Append(array.Items[index], builder, canonical, depth + 1);
        }

        if (canonical)
        {
            builder.Append('\n').Append(' ', depth * 2);
        }

        builder.Append(']');
    }

    private static void AppendObject(JsonObject value, StringBuilder builder, bool canonical, int depth)
    {
        if (value.Properties.Count == 0)
        {
            builder.Append("{}");
            return;
        }

        IEnumerable<JsonProperty> properties = canonical
            ? value.Properties.OrderBy(static item => item.Name, Comparer<string>.Create(JsonEquality.CompareCodePoints))
            : value.Properties;
        builder.Append('{');
        var first = true;
        foreach (var property in properties)
        {
            if (!first)
            {
                builder.Append(',');
            }

            if (canonical)
            {
                builder.Append('\n').Append(' ', (depth + 1) * 2);
            }

            AppendString(property.Name, builder, canonical);
            builder.Append(canonical ? ": " : ":");
            Append(property.Value, builder, canonical, depth + 1);
            first = false;
        }

        if (canonical)
        {
            builder.Append('\n').Append(' ', depth * 2);
        }

        builder.Append('}');
    }

    private static void AppendString(string value, StringBuilder builder, bool canonical)
    {
        ArgumentNullException.ThrowIfNull(value);
        builder.Append('"');
        for (var index = 0; index < value.Length; index++)
        {
            var character = value[index];
            if (char.IsHighSurrogate(character))
            {
                if (index + 1 >= value.Length || !char.IsLowSurrogate(value[index + 1]))
                {
                    throw new ArgumentException("JSON strings cannot contain an unpaired surrogate.", nameof(value));
                }

                if (canonical)
                {
                    AppendUnicodeEscape(character, builder);
                    AppendUnicodeEscape(value[++index], builder);
                }
                else
                {
                    builder.Append(character).Append(value[++index]);
                }

                continue;
            }

            if (char.IsLowSurrogate(character))
            {
                throw new ArgumentException("JSON strings cannot contain an unpaired surrogate.", nameof(value));
            }

            switch (character)
            {
                case '"': builder.Append("\\\""); break;
                case '\\': builder.Append("\\\\"); break;
                case '\b': builder.Append("\\b"); break;
                case '\t': builder.Append("\\t"); break;
                case '\n': builder.Append("\\n"); break;
                case '\f': builder.Append("\\f"); break;
                case '\r': builder.Append("\\r"); break;
                case var _ when character < 0x20 || (canonical && character >= 0x7f):
                    AppendUnicodeEscape(character, builder);
                    break;
                default:
                    builder.Append(character);
                    break;
            }
        }

        builder.Append('"');
    }

    private static void AppendUnicodeEscape(char value, StringBuilder builder)
    {
        builder.Append("\\u").Append(((int)value).ToString("x4", CultureInfo.InvariantCulture));
    }

    private static string FormatNumber(JsonNumber number, bool canonical)
    {
        if (!double.IsFinite(number.Value))
        {
            throw new ArgumentOutOfRangeException(nameof(number), "JSON numbers must be finite.");
        }

        if (!canonical && number.SourceLexeme is { } lexeme && IsVerifiedLexeme(lexeme, number.Value))
        {
            return lexeme;
        }

        var text = number.IsNegativeZero ? "-0.0" : number.Value.ToString("R", CultureInfo.InvariantCulture);
        text = NormalizeExponent(text);
        return text.IndexOfAny(['.', 'e']) >= 0 ? text : text + ".0";
    }

    private static bool IsVerifiedLexeme(string lexeme, double value)
    {
        if ((!lexeme.Contains('.', StringComparison.Ordinal) &&
             !lexeme.Contains('e', StringComparison.Ordinal) &&
             !lexeme.Contains('E', StringComparison.Ordinal)) ||
            !NumberLexeme().IsMatch(lexeme) ||
            !double.TryParse(lexeme, NumberStyles.Float, CultureInfo.InvariantCulture, out var parsed))
        {
            return false;
        }

        return BitConverter.DoubleToInt64Bits(parsed) == BitConverter.DoubleToInt64Bits(value);
    }

    private static string NormalizeExponent(string value)
    {
        var exponent = value.IndexOfAny(['E', 'e']);
        if (exponent < 0)
        {
            return value;
        }

        var mantissa = value[..exponent];
        var suffix = value[(exponent + 1)..];
        var sign = "+";
        if (suffix.StartsWith("-", StringComparison.Ordinal))
        {
            sign = "-";
            suffix = suffix[1..];
        }
        else if (suffix.StartsWith("+", StringComparison.Ordinal))
        {
            suffix = suffix[1..];
        }

        suffix = suffix.TrimStart('0');
        return mantissa + "e" + sign + (suffix.Length == 0 ? "0" : suffix);
    }

    [GeneratedRegex("^-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")]
    private static partial Regex NumberLexeme();
}
