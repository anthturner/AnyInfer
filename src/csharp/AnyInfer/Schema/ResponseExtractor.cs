using JsonParseException = System.Text.Json.JsonException;
using AnyInfer.Json;

namespace AnyInfer.Schema;

public sealed record ExtractionResult
{
    public ExtractionResult(JsonValue? value, NativeFinding? failure)
    {
        if ((value is null) == (failure is null))
        {
            throw new ArgumentException("Extraction must contain exactly one of a value or failure.");
        }

        Value = value;
        Failure = failure;
    }

    public JsonValue? Value { get; }
    public NativeFinding? Failure { get; }
}

public static class ResponseExtractor
{
    public static ExtractionResult Extract(string text)
    {
        ArgumentNullException.ThrowIfNull(text);
        var trimmed = TrimAscii(text);
        if (trimmed.Length == 0)
        {
            return ScannerFailure("response_empty", "Response text is empty.");
        }

        try
        {
            return new ExtractionResult(JsonReader.Read(trimmed), null);
        }
        catch (FormatException)
        {
            var candidate = FirstCandidate(trimmed);
            if (candidate is null)
            {
                return ScannerFailure("no_json_candidate", "No balanced JSON object or array candidate was found.");
            }

            try
            {
                return new ExtractionResult(JsonReader.Read(candidate), null);
            }
            catch (FormatException exception)
            {
                return ParserFailure(exception);
            }
        }
    }

    private static ExtractionResult ScannerFailure(string rule, string message)
    {
        var issue = new Issue(rule);
        var facts = new JsonObject([new JsonProperty("rule", new JsonString(rule))]);
        return new ExtractionResult(null, new NativeFinding(issue, message, "response-extractor.scanner", facts));
    }

    private static ExtractionResult ParserFailure(FormatException exception)
    {
        var parserException = exception.InnerException as JsonParseException;
        var inner = exception.InnerException;
        var properties = new List<JsonProperty>
        {
            new("exception_type", new JsonString(exception.GetType().FullName ?? exception.GetType().Name)),
            new("exception_message", new JsonString(exception.Message)),
            new("inner_exception_type", TypeOrNull(inner)),
            new("inner_exception_message", MessageOrNull(inner)),
        };
        if (parserException is not null)
        {
            properties.Add(new JsonProperty("line_number", NullableNumber(parserException.LineNumber)));
            properties.Add(new JsonProperty("byte_position_in_line", NullableNumber(parserException.BytePositionInLine)));
        }

        var issue = new Issue("malformed_json_candidate");
        var message = inner?.Message ?? exception.Message;
        return new ExtractionResult(null, new NativeFinding(issue, message, "response-extractor.parser", new JsonObject(properties)));
    }

    private static JsonValue TypeOrNull(Exception? exception) => exception is null
        ? JsonNull.Instance
        : new JsonString(exception.GetType().FullName ?? exception.GetType().Name);

    private static JsonValue MessageOrNull(Exception? exception) => exception is null
        ? JsonNull.Instance
        : new JsonString(exception.Message);

    private static JsonValue NullableNumber(long? value) => value is long number
        ? new JsonInteger(number)
        : JsonNull.Instance;

    private static string TrimAscii(string value)
    {
        var start = 0;
        var end = value.Length;
        while (start < end && IsAsciiWhitespace(value[start]))
        {
            start++;
        }

        while (end > start && IsAsciiWhitespace(value[end - 1]))
        {
            end--;
        }

        return value[start..end];
    }

    private static bool IsAsciiWhitespace(char value) => value is ' ' or '\t' or '\r' or '\n' or '\f' or '\v';

    private static string? FirstCandidate(string value)
    {
        var start = -1;
        var depth = 0;
        var inString = false;
        var escaped = false;
        var opener = '\0';
        var closer = '\0';
        for (var index = 0; index < value.Length; index++)
        {
            var character = value[index];
            if (start < 0)
            {
                if (character is '{' or '[')
                {
                    start = index;
                    opener = character;
                    closer = character == '{' ? '}' : ']';
                    depth = 1;
                }

                continue;
            }

            if (escaped)
            {
                escaped = false;
                continue;
            }

            if (character == '\\')
            {
                escaped = inString;
                continue;
            }

            if (character == '"')
            {
                inString = !inString;
                continue;
            }

            if (inString)
            {
                continue;
            }

            if (character == opener)
            {
                depth++;
            }
            else if (character == closer && --depth == 0)
            {
                return value[start..(index + 1)];
            }
        }

        return null;
    }
}
