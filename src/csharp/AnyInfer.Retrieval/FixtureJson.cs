using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.Json;
using AnyInfer;
using AnyInfer.Json;
using JsonProperty = AnyInfer.Json.JsonProperty;

internal static class FixtureJson
{
    private static readonly UTF8Encoding StrictUtf8 = new(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true);

    internal static JsonObject Object(params (string Name, JsonValue Value)[] properties) =>
        new(properties.Select(static property => new JsonProperty(property.Name, property.Value)));

    internal static JsonArray Array(IEnumerable<JsonValue> values) => new(values);

    internal static JsonValue String(string value) => new JsonString(value);

    internal static JsonValue Integer(long value) => new JsonInteger(value);

    internal static JsonValue Integer(BigInteger value) => new JsonInteger(value);

    internal static JsonValue Number(double value) =>
        double.IsFinite(value)
            ? new JsonNumber(value, value.ToString("R", CultureInfo.InvariantCulture))
            : throw new FormatException("JSON number must be finite.");

    internal static JsonValue Boolean(bool value) => new JsonBoolean(value);

    internal static JsonValue Null() => JsonNull.Instance;

    internal static JsonValue Read(JsonElement element) => Read(element.GetRawText());

    internal static JsonValue Read(string source)
    {
        ArgumentNullException.ThrowIfNull(source);
        var utf8 = StrictUtf8.GetBytes(source);
        var reader = new Utf8JsonReader(utf8, new JsonReaderOptions { CommentHandling = JsonCommentHandling.Disallow });
        if (!reader.Read()) throw new FormatException("A JSON value is required.");
        var value = ReadValue(ref reader);
        if (reader.Read()) throw new FormatException("JSON input contains more than one value.");
        return value;
    }

    internal static string Write(JsonValue value)
    {
        var builder = new StringBuilder();
        WriteValue(builder, value);
        return builder.ToString();
    }

    internal static void WriteToFile(string path, JsonValue value)
    {
        ArgumentNullException.ThrowIfNull(path);
        File.WriteAllText(path, Write(value), new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
    }

    private static JsonValue ReadValue(ref Utf8JsonReader reader) => reader.TokenType switch
    {
        JsonTokenType.Null => JsonNull.Instance,
        JsonTokenType.True => new JsonBoolean(true),
        JsonTokenType.False => new JsonBoolean(false),
        JsonTokenType.String => new JsonString(reader.GetString()!),
        JsonTokenType.Number => ReadNumber(ref reader),
        JsonTokenType.StartArray => ReadArray(ref reader),
        JsonTokenType.StartObject => ReadObject(ref reader),
        _ => throw new FormatException($"Unexpected JSON token {reader.TokenType}.")
    };

    private static JsonValue ReadNumber(ref Utf8JsonReader reader)
    {
        var lexeme = Encoding.UTF8.GetString(reader.ValueSpan);
        if (!lexeme.Contains('.', StringComparison.Ordinal) &&
            !lexeme.Contains('e', StringComparison.OrdinalIgnoreCase))
        {
            if (lexeme == "-0")
            {
                return new JsonNumber(-0d, lexeme);
            }

            return new JsonInteger(BigInteger.Parse(lexeme, CultureInfo.InvariantCulture));
        }

        if (!double.TryParse(lexeme, NumberStyles.Float, CultureInfo.InvariantCulture, out var value) || !double.IsFinite(value))
        {
            throw new FormatException("JSON number must be finite and representable as a public JsonNumber.");
        }

        return new JsonNumber(value, lexeme);
    }

    private static JsonArray ReadArray(ref Utf8JsonReader reader)
    {
        var items = new List<JsonValue>();
        while (reader.Read() && reader.TokenType != JsonTokenType.EndArray)
        {
            items.Add(ReadValue(ref reader));
        }

        if (reader.TokenType != JsonTokenType.EndArray) throw new FormatException("JSON array is incomplete.");
        return new JsonArray(items);
    }

    private static JsonObject ReadObject(ref Utf8JsonReader reader)
    {
        var properties = new List<JsonProperty>();
        var names = new HashSet<string>(StringComparer.Ordinal);
        while (reader.Read() && reader.TokenType != JsonTokenType.EndObject)
        {
            if (reader.TokenType != JsonTokenType.PropertyName) throw new FormatException("JSON object property is invalid.");
            var name = reader.GetString()!;
            if (!names.Add(name)) throw new FormatException("JSON object contains a duplicate property.");
            if (!reader.Read()) throw new FormatException("JSON object property has no value.");
            properties.Add(new JsonProperty(name, ReadValue(ref reader)));
        }

        if (reader.TokenType != JsonTokenType.EndObject) throw new FormatException("JSON object is incomplete.");
        return new JsonObject(properties);
    }

    private static void WriteValue(StringBuilder builder, JsonValue value)
    {
        switch (value)
        {
            case JsonNull: builder.Append("null"); return;
            case JsonBoolean boolean: builder.Append(boolean.Value ? "true" : "false"); return;
            case JsonInteger integer: builder.Append(integer.Value.ToString(CultureInfo.InvariantCulture)); return;
            case JsonNumber number:
                WriteNumber(builder, number);
                return;
            case JsonString text: builder.Append(JsonSerializer.Serialize(Redaction.Redact(text.Value))); return;
            case JsonArray array:
                builder.Append('[');
                for (var index = 0; index < array.Items.Count; index++)
                {
                    if (index > 0) builder.Append(',');
                    WriteValue(builder, array.Items[index]);
                }
                builder.Append(']');
                return;
            case JsonObject obj:
                builder.Append('{');
                for (var index = 0; index < obj.Properties.Count; index++)
                {
                    if (index > 0) builder.Append(',');
                    builder.Append(JsonSerializer.Serialize(Redaction.Redact(obj.Properties[index].Name)));
                    builder.Append(':');
                    WriteValue(builder, obj.Properties[index].Value);
                }
                builder.Append('}');
                return;
            default: throw new ArgumentOutOfRangeException(nameof(value));
        }
    }

    private static void WriteNumber(StringBuilder builder, JsonNumber number)
    {
        if (!double.IsFinite(number.Value))
        {
            throw new FormatException("JSON number must be finite.");
        }

        if (number.SourceLexeme is { } lexeme && IsConsistentNumberLexeme(lexeme, number.Value))
        {
            builder.Append(lexeme);
            return;
        }

        builder.Append(FormatFloating(number.Value));
    }

    private static bool IsConsistentNumberLexeme(string lexeme, double value)
    {
        try
        {
            var parsed = Read(lexeme);
            return parsed is JsonNumber source &&
                BitConverter.DoubleToInt64Bits(source.Value) == BitConverter.DoubleToInt64Bits(value);
        }
        catch (Exception exception) when (exception is FormatException or EncoderFallbackException or JsonException)
        {
            return false;
        }
    }

    private static string FormatFloating(double value)
    {
        if (BitConverter.DoubleToInt64Bits(value) == BitConverter.DoubleToInt64Bits(-0d))
        {
            return "-0.0";
        }

        var formatted = value.ToString("R", CultureInfo.InvariantCulture);
        return formatted.Contains('.', StringComparison.Ordinal) ||
            formatted.Contains('e', StringComparison.OrdinalIgnoreCase)
            ? formatted
            : formatted + ".0";
    }
}
