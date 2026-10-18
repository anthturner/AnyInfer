using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.Json;

namespace AnyInfer.Json;

public static class JsonReader
{
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);
    private static readonly BigInteger IntegerLimit = BigInteger.One << 63;

    public static JsonValue Read(string json)
    {
        ArgumentNullException.ThrowIfNull(json);
        try
        {
            return Read(StrictUtf8.GetBytes(json));
        }
        catch (EncoderFallbackException exception)
        {
            throw new FormatException("JSON input contains an unpaired UTF-16 surrogate.", exception);
        }
    }

    public static JsonValue Read(ReadOnlySpan<byte> utf8)
        => ReadCore(utf8, allowLargeIntegers: false);

    internal static JsonValue ReadModern(string json)
    {
        ArgumentNullException.ThrowIfNull(json);
        try { return ReadCore(StrictUtf8.GetBytes(json), allowLargeIntegers: true); }
        catch (EncoderFallbackException exception) { throw new FormatException("JSON input contains an unpaired UTF-16 surrogate.", exception); }
    }

    private static JsonValue ReadCore(ReadOnlySpan<byte> utf8, bool allowLargeIntegers)
    {
        try
        {
            var reader = new Utf8JsonReader(utf8, new JsonReaderOptions
            {
                CommentHandling = JsonCommentHandling.Disallow,
                AllowTrailingCommas = false,
            });
            if (!reader.Read())
            {
                throw new FormatException("JSON input is empty.");
            }

            var value = ReadValue(ref reader, allowLargeIntegers);
            if (reader.Read())
            {
                throw new FormatException("JSON input contains more than one value.");
            }

            return value;
        }
        catch (JsonException exception)
        {
            throw new FormatException("JSON input is invalid.", exception);
        }
        catch (DecoderFallbackException exception)
        {
            throw new FormatException("JSON input is not valid UTF-8.", exception);
        }
    }

    private static JsonValue ReadValue(ref Utf8JsonReader reader, bool allowLargeIntegers)
    {
        return reader.TokenType switch
        {
            JsonTokenType.Null => JsonNull.Instance,
            JsonTokenType.True => new JsonBoolean(true),
            JsonTokenType.False => new JsonBoolean(false),
            JsonTokenType.String => new JsonString(ReadString(ref reader)),
            JsonTokenType.Number => ReadNumber(ref reader, allowLargeIntegers),
            JsonTokenType.StartArray => ReadArray(ref reader, allowLargeIntegers),
            JsonTokenType.StartObject => ReadObject(ref reader, allowLargeIntegers),
            _ => throw new FormatException($"Unexpected JSON token {reader.TokenType}.")
        };
    }

    private static JsonArray ReadArray(ref Utf8JsonReader reader, bool allowLargeIntegers)
    {
        var items = new List<JsonValue>();
        while (reader.Read() && reader.TokenType != JsonTokenType.EndArray)
        {
            items.Add(ReadValue(ref reader, allowLargeIntegers));
        }

        if (reader.TokenType != JsonTokenType.EndArray)
        {
            throw new FormatException("JSON array is incomplete.");
        }

        return new JsonArray(items);
    }

    private static JsonObject ReadObject(ref Utf8JsonReader reader, bool allowLargeIntegers)
    {
        var properties = new List<JsonProperty>();
        while (reader.Read() && reader.TokenType != JsonTokenType.EndObject)
        {
            if (reader.TokenType != JsonTokenType.PropertyName)
            {
                throw new FormatException("JSON object property is invalid.");
            }

            var name = ReadString(ref reader);
            if (!reader.Read())
            {
                throw new FormatException("JSON object property has no value.");
            }

            properties.Add(new JsonProperty(name, ReadValue(ref reader, allowLargeIntegers)));
        }

        if (reader.TokenType != JsonTokenType.EndObject)
        {
            throw new FormatException("JSON object is incomplete.");
        }

        return new JsonObject(properties);
    }

    private static JsonValue ReadNumber(ref Utf8JsonReader reader, bool allowLargeIntegers)
    {
        var lexeme = StrictUtf8.GetString(reader.ValueSpan);
        if (!lexeme.Contains('.', StringComparison.Ordinal) &&
            !lexeme.Contains('e', StringComparison.Ordinal) &&
            !lexeme.Contains('E', StringComparison.Ordinal))
        {
            var integer = BigInteger.Parse(lexeme, CultureInfo.InvariantCulture);
            if (!allowLargeIntegers && BigInteger.Abs(integer) > IntegerLimit)
            {
                throw new FormatException("JSON integer is outside the portable v0 range.");
            }

            return new JsonInteger(integer);
        }

        var value = reader.GetDouble();
        if (!double.IsFinite(value))
        {
            throw new FormatException("JSON non-integer number is not finite.");
        }

        return new JsonNumber(value, lexeme);
    }

    private static string ReadString(ref Utf8JsonReader reader)
    {
        ValidateEscapedUtf16(reader.ValueSpan);
        try
        {
            return reader.GetString() ?? throw new FormatException("JSON string is null.");
        }
        catch (InvalidOperationException exception) when (exception.InnerException is DecoderFallbackException)
        {
            throw new FormatException("JSON string is not valid UTF-8.", exception);
        }
    }

    private static void ValidateEscapedUtf16(ReadOnlySpan<byte> bytes)
    {
        for (var index = 0; index < bytes.Length; index++)
        {
            if (bytes[index] != (byte)'\\')
            {
                continue;
            }

            if (index + 1 >= bytes.Length)
            {
                throw new FormatException("JSON string escape is incomplete.");
            }

            if (bytes[index + 1] != (byte)'u')
            {
                // Consume the escaped byte. In particular, the second slash in
                // "\\\\uD800" is literal text, not the start of a Unicode escape.
                index++;
                continue;
            }

            if (index + 5 >= bytes.Length)
            {
                throw new FormatException("JSON Unicode escape is incomplete.");
            }
            var codeUnit = Hex(bytes[index + 2]) << 12 |
                           Hex(bytes[index + 3]) << 8 |
                           Hex(bytes[index + 4]) << 4 |
                           Hex(bytes[index + 5]);
            if (codeUnit is >= 0xD800 and <= 0xDBFF)
            {
                var nextEscape = index + 6;
                if (nextEscape + 5 >= bytes.Length ||
                    bytes[nextEscape] != (byte)'\\' ||
                    bytes[nextEscape + 1] != (byte)'u')
                {
                    throw new FormatException("JSON string has an unpaired high surrogate.");
                }

                var low = Hex(bytes[nextEscape + 2]) << 12 |
                          Hex(bytes[nextEscape + 3]) << 8 |
                          Hex(bytes[nextEscape + 4]) << 4 |
                          Hex(bytes[nextEscape + 5]);
                if (low is < 0xDC00 or > 0xDFFF)
                {
                    throw new FormatException("JSON string has an unpaired high surrogate.");
                }

                index = nextEscape + 5;
            }
            else if (codeUnit is >= 0xDC00 and <= 0xDFFF)
            {
                throw new FormatException("JSON string has an unpaired low surrogate.");
            }
            else
            {
                index += 5;
            }
        }
    }

    private static int Hex(byte value) => value switch
    {
        >= (byte)'0' and <= (byte)'9' => value - (byte)'0',
        >= (byte)'a' and <= (byte)'f' => value - (byte)'a' + 10,
        >= (byte)'A' and <= (byte)'F' => value - (byte)'A' + 10,
        _ => throw new FormatException("JSON Unicode escape is invalid."),
    };
}
