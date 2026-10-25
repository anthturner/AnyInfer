using JsonParseException = System.Text.Json.JsonException;
using AnyInfer.Json;

namespace AnyInfer.Schema;

/// <summary>The outcome of extracting one JSON value from response text: either a value or a failure.</summary>
public sealed record ExtractionResult
{
    /// <summary>Creates an extraction outcome.</summary>
    /// <param name="value">The extracted value, or <see langword="null"/> when extraction failed.</param>
    /// <param name="failure">The extraction failure, or <see langword="null"/> when a value was extracted.</param>
    /// <exception cref="ArgumentException">Both or neither of <paramref name="value"/> and <paramref name="failure"/> are supplied.</exception>
    public ExtractionResult(JsonValue? value, NativeFinding? failure)
    {
        if ((value is null) == (failure is null))
        {
            throw new ArgumentException("Extraction must contain exactly one of a value or failure.");
        }

        Value = value;
        Failure = failure;
    }

    /// <summary>Gets the extracted value, or <see langword="null"/> when extraction failed.</summary>
    public JsonValue? Value { get; }
    /// <summary>Gets the extraction failure, or <see langword="null"/> when a value was extracted.</summary>
    public NativeFinding? Failure { get; }
}

/// <summary>Extracts a single JSON value from model response text.</summary>
public static class ResponseExtractor
{
    /// <summary>Extracts one JSON value, tolerating prose around a single JSON object or array.</summary>
    /// <remarks>
    /// Leading and trailing ASCII whitespace is ignored. When the remaining text is one strict JSON
    /// value it is returned as is. Otherwise the first balanced <c>{...}</c> or <c>[...]</c>
    /// candidate, found while skipping string contents, is parsed. Parsing follows
    /// <see cref="JsonReader.Read(string)"/>, so integers whose magnitude exceeds 2^63 are
    /// rejected. Failures are returned, not thrown, with the rule <c>response_empty</c>,
    /// <c>no_json_candidate</c> or <c>malformed_json_candidate</c>.
    /// </remarks>
    /// <param name="text">The response text.</param>
    /// <returns>The extracted value or the extraction failure.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="text"/> is <see langword="null"/>.</exception>
    public static ExtractionResult Extract(string text)
        => ExtractCore(text, JsonReader.Read);

    internal static ExtractionResult ExtractModern(string text)
        => ExtractCore(text, JsonReader.ReadModern);

    private static ExtractionResult ExtractCore(string text, Func<string, JsonValue> read)
    {
        ArgumentNullException.ThrowIfNull(text);
        var trimmed = TrimAscii(text);
        if (trimmed.Length == 0)
        {
            return ScannerFailure("response_empty", "Response text is empty.");
        }

        try
        {
            return new ExtractionResult(read(trimmed), null);
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
                return new ExtractionResult(read(candidate), null);
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
