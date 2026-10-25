using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;

namespace AnyInfer.Json;

/// <summary>Writes native <see cref="JsonValue"/> trees as JSON text.</summary>
/// <remarks>
/// Both public forms accept only integers whose magnitude is at most 2^63 and strings without
/// unpaired UTF-16 surrogates. Quotation marks, backslashes and characters below U+0020 are
/// always escaped. A <see cref="JsonNumber"/> with an integral value is written with a <c>.0</c>
/// suffix so it stays distinguishable from a <see cref="JsonInteger"/>.
/// </remarks>
public static partial class JsonWriter
{
    private static readonly BigInteger IntegerLimit = BigInteger.One << 63;

    private enum NumberFormat
    {
        Existing,
        Python,
    }

    private readonly record struct WritePolicy(
        bool SortKeys,
        bool AsciiOnly,
        bool AllowLargeIntegers,
        NumberFormat NumberFormat,
        int? Indent,
        bool Compact,
        bool SpaceAfterComma,
        bool SpaceAfterColon);

    private static readonly WritePolicy DefaultPolicy = new(false, false, false, NumberFormat.Existing, null, Compact: true, SpaceAfterComma: false, SpaceAfterColon: false);
    private static readonly WritePolicy CanonicalPolicy = new(true, true, false, NumberFormat.Existing, 2, Compact: false, SpaceAfterComma: false, SpaceAfterColon: true);
    private static readonly WritePolicy ModernPolicy = new(false, false, true, NumberFormat.Existing, null, Compact: true, SpaceAfterComma: false, SpaceAfterColon: false);
    private static readonly WritePolicy ModernCanonicalPolicy = new(true, true, true, NumberFormat.Existing, 2, Compact: false, SpaceAfterComma: false, SpaceAfterColon: true);
    private static readonly WritePolicy ManifestCanonicalPolicy = new(true, true, true, NumberFormat.Python, null, Compact: true, SpaceAfterComma: false, SpaceAfterColon: false);
    private static readonly WritePolicy AccountingPolicy = new(false, true, true, NumberFormat.Python, null, Compact: true, SpaceAfterComma: true, SpaceAfterColon: true);

    /// <summary>Writes compact JSON without insignificant whitespace.</summary>
    /// <remarks>
    /// Object properties keep their stored order and non-ASCII characters are written
    /// unescaped. A number keeps its <see cref="JsonNumber.SourceLexeme"/> when that lexeme
    /// still denotes exactly the same value; otherwise it is written in shortest round-trip form.
    /// </remarks>
    /// <param name="value">The value to write.</param>
    /// <returns>The compact JSON text.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="value"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentOutOfRangeException">An integer has a magnitude greater than 2^63.</exception>
    /// <exception cref="ArgumentException">A string or property name contains an unpaired UTF-16 surrogate.</exception>
    public static string Write(JsonValue value)
        => WriteCore(value, DefaultPolicy);

    /// <summary>Writes deterministic, ASCII-only, indented JSON.</summary>
    /// <remarks>
    /// Object properties are sorted by Unicode code point, every non-ASCII character is escaped
    /// as <c>\uXXXX</c>, nesting is indented by two spaces per level with <c>": "</c> after each
    /// property name, and numbers are written in shortest round-trip form regardless of their
    /// source lexeme.
    /// </remarks>
    /// <param name="value">The value to write.</param>
    /// <returns>The canonical JSON text, without a trailing newline.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="value"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentOutOfRangeException">An integer has a magnitude greater than 2^63.</exception>
    /// <exception cref="ArgumentException">A string or property name contains an unpaired UTF-16 surrogate.</exception>
    public static string WriteCanonical(JsonValue value)
        => WriteCore(value, CanonicalPolicy);

    internal static string WriteModern(JsonValue value) => WriteCore(value, ModernPolicy);

    internal static string WriteCanonicalModern(JsonValue value) => WriteCore(value, ModernCanonicalPolicy);

    /// <summary>Writes a compact, scalar-sorted ASCII manifest representation.</summary>
    internal static string WriteManifestCanonical(JsonValue value) => WriteCore(value, ManifestCanonicalPolicy);

    /// <summary>Writes a scalar-sorted ASCII manifest representation with Python-compatible separators.</summary>
    internal static string WriteManifest(JsonValue value, int? indent = 2) =>
        WriteCore(value, ManifestCanonicalPolicy with { Indent = indent, Compact = indent is null, SpaceAfterComma = indent is null, SpaceAfterColon = true });

    /// <summary>Writes insertion-ordered ASCII accounting JSON with Python-compatible formatting.</summary>
    internal static string WriteAccounting(JsonValue value, int? indent = null) =>
        WriteCore(value, AccountingPolicy with { Indent = indent, Compact = indent is null, SpaceAfterComma = indent is null, SpaceAfterColon = true });

    /// <summary>Writes scalar-sorted ASCII JSON with Python-compatible default separators for cache diagnostics.</summary>
    internal static string WriteCacheSignature(JsonValue value) =>
        WriteCore(value, AccountingPolicy with { SortKeys = true });

    private static string WriteCore(JsonValue value, WritePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(value);
        var builder = new StringBuilder();
        Append(value, builder, policy, depth: 0);
        return builder.ToString();
    }

    private static void Append(JsonValue value, StringBuilder builder, WritePolicy policy, int depth)
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
                if (!policy.AllowLargeIntegers && BigInteger.Abs(integer.Value) > IntegerLimit)
                {
                    throw new ArgumentOutOfRangeException(nameof(value), "JSON integer is outside the portable v0 range.");
                }

                builder.Append(integer.Value.ToString(CultureInfo.InvariantCulture));
                return;
            case JsonNumber number:
                builder.Append(policy.NumberFormat == NumberFormat.Python ? FormatPythonNumber(number) : FormatNumber(number, policy.SortKeys));
                return;
            case JsonString text:
                AppendString(text.Value, builder, policy.AsciiOnly);
                return;
            case JsonArray array:
                AppendArray(array, builder, policy, depth);
                return;
            case JsonObject obj:
                AppendObject(obj, builder, policy, depth);
                return;
            default:
                throw new ArgumentOutOfRangeException(nameof(value), "Unknown JSON value.");
        }
    }

    private static void AppendArray(JsonArray array, StringBuilder builder, WritePolicy policy, int depth)
    {
        if (array.Items.Count == 0)
        {
            builder.Append("[]");
            return;
        }

        builder.Append('[');
        for (var index = 0; index < array.Items.Count; index++)
        {
            if (!policy.Compact && index > 0)
            {
                builder.Append(',');
            }
            else if (policy.Compact && index > 0)
            {
                builder.Append(',');
                if (policy.SpaceAfterComma)
                {
                    builder.Append(' ');
                }
            }

            if (!policy.Compact)
            {
                AppendIndent(builder, depth + 1, policy.Indent);
            }

            Append(array.Items[index], builder, policy, depth + 1);
        }

        if (!policy.Compact)
        {
            AppendIndent(builder, depth, policy.Indent);
        }

        builder.Append(']');
    }

    private static void AppendObject(JsonObject value, StringBuilder builder, WritePolicy policy, int depth)
    {
        if (value.Properties.Count == 0)
        {
            builder.Append("{}");
            return;
        }

        IEnumerable<JsonProperty> properties = policy.SortKeys
            ? value.Properties.OrderBy(static item => item.Name, Comparer<string>.Create(JsonEquality.CompareCodePoints))
            : value.Properties;
        builder.Append('{');
        var first = true;
        foreach (var property in properties)
        {
            if (!first)
            {
                builder.Append(',');
                if (policy.Compact && policy.SpaceAfterComma)
                {
                    builder.Append(' ');
                }
            }

            if (!policy.Compact)
            {
                AppendIndent(builder, depth + 1, policy.Indent);
            }

            AppendString(property.Name, builder, policy.AsciiOnly);
            builder.Append(policy.SpaceAfterColon ? ": " : ":");
            Append(property.Value, builder, policy, depth + 1);
            first = false;
        }

        if (!policy.Compact)
        {
            AppendIndent(builder, depth, policy.Indent);
        }

        builder.Append('}');
    }

    private static void AppendIndent(StringBuilder builder, int depth, int? indent)
    {
        builder.Append('\n');
        if (indent is > 0)
        {
            builder.Append(' ', depth * indent.Value);
        }
    }

    private static void AppendString(string value, StringBuilder builder, bool asciiOnly)
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

                if (asciiOnly)
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
                case var _ when character < 0x20 || (asciiOnly && character >= 0x7f):
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

    private static string FormatPythonNumber(JsonNumber number)
    {
        if (!double.IsFinite(number.Value))
        {
            throw new ArgumentOutOfRangeException(nameof(number), "JSON numbers must be finite.");
        }

        var value = number.Value;
        if (value == 0d)
        {
            return number.IsNegativeZero ? "-0.0" : "0.0";
        }

        var roundTrip = value.ToString("R", CultureInfo.InvariantCulture);
        var marker = roundTrip.IndexOfAny(['E', 'e']);
        if (marker < 0)
        {
            return PythonFixedOrScientific(roundTrip);
        }

        var mantissa = roundTrip[..marker];
        var exponent = int.Parse(roundTrip[(marker + 1)..], NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture);
        if (exponent is >= -4 and < 16)
        {
            return PythonFixedFromScientific(mantissa, exponent);
        }

        var trimmed = mantissa.EndsWith(".0", StringComparison.Ordinal) ? mantissa[..^2] : mantissa;
        return trimmed + "e" + (exponent >= 0 ? "+" : "-") + Math.Abs(exponent).ToString("00", CultureInfo.InvariantCulture);
    }

    private static string PythonFixedOrScientific(string fixedText)
    {
        var negative = fixedText.StartsWith("-", StringComparison.Ordinal);
        var unsigned = negative ? fixedText[1..] : fixedText;
        var point = unsigned.IndexOf('.');
        var wholeLength = point < 0 ? unsigned.Length : point;
        var digits = unsigned.Replace(".", string.Empty, StringComparison.Ordinal);
        var firstNonzero = digits.IndexOfAny("123456789".ToCharArray());
        if (firstNonzero < 0)
        {
            return negative ? "-0.0" : "0.0";
        }

        var exponent = wholeLength - firstNonzero - 1;
        if (exponent is >= -4 and < 16)
        {
            return fixedText.IndexOf('.') >= 0 ? fixedText : fixedText + ".0";
        }

        var significant = digits[firstNonzero..].TrimEnd('0');
        var mantissa = significant.Length == 1 ? significant : significant[0] + "." + significant[1..];
        return (negative ? "-" : string.Empty) + mantissa + "e" + (exponent >= 0 ? "+" : "-") + Math.Abs(exponent).ToString("00", CultureInfo.InvariantCulture);
    }

    private static string PythonFixedFromScientific(string mantissa, int exponent)
    {
        var negative = mantissa.StartsWith("-", StringComparison.Ordinal);
        var unsigned = negative ? mantissa[1..] : mantissa;
        var point = unsigned.IndexOf('.');
        var wholeLength = point < 0 ? unsigned.Length : point;
        var digits = unsigned.Replace(".", string.Empty, StringComparison.Ordinal);
        var decimalIndex = wholeLength + exponent;
        string result;
        if (decimalIndex <= 0)
        {
            result = "0." + new string('0', -decimalIndex) + digits;
        }
        else if (decimalIndex >= digits.Length)
        {
            result = digits + new string('0', decimalIndex - digits.Length) + ".0";
        }
        else
        {
            result = digits[..decimalIndex] + "." + digits[decimalIndex..];
        }

        return negative ? "-" + result : result;
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
