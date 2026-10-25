using AnyInfer.Json;

namespace AnyInfer.Schema;

/// <summary>Builds the prompt instruction used when structured output falls back to prompting.</summary>
public static class SchemaPromptRenderer
{
    private const string Prefix = "Respond with ONLY a JSON value matching this JSON Schema. No prose. Schema:\n";

    /// <summary>Renders the schema instruction text.</summary>
    /// <remarks>
    /// The text is a fixed instruction line followed by the schema written with
    /// <see cref="JsonWriter.WriteCanonical(JsonValue)"/>.
    /// </remarks>
    /// <param name="schema">The JSON Schema document to embed.</param>
    /// <returns>The instruction text.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="schema"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentOutOfRangeException">The schema contains an integer whose magnitude exceeds 2^63.</exception>
    /// <exception cref="ArgumentException">The schema contains a string with an unpaired UTF-16 surrogate.</exception>
    public static string Render(JsonValue schema) => RenderCore(schema, modern: false);

    internal static string RenderModern(JsonValue schema) => RenderCore(schema, modern: true);

    private static string RenderCore(JsonValue schema, bool modern)
    {
        ArgumentNullException.ThrowIfNull(schema);
        return Prefix + (modern ? JsonWriter.WriteCanonicalModern(schema) : JsonWriter.WriteCanonical(schema));
    }

    /// <summary>Returns a copy of the messages with the schema instruction added.</summary>
    /// <remarks>
    /// The instruction from <see cref="Render(JsonValue)"/> is appended, after a blank line, as a
    /// new text part of the last <c>system</c> message; when there is no system message, a new one
    /// holding only the instruction is inserted first. The input list is not modified.
    /// </remarks>
    /// <param name="input">The conversation messages.</param>
    /// <param name="schema">The JSON Schema document to embed.</param>
    /// <returns>A new read-only message list.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="input"/> or <paramref name="schema"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">
    /// <paramref name="input"/> contains <see langword="null"/>, or the schema contains a string with
    /// an unpaired UTF-16 surrogate.
    /// </exception>
    /// <exception cref="ArgumentOutOfRangeException">The schema contains an integer whose magnitude exceeds 2^63.</exception>
    public static IReadOnlyList<Message> InjectPrompt(IReadOnlyList<Message> input, JsonValue schema) =>
        InjectPromptCore(input, schema, modern: false);

    internal static IReadOnlyList<Message> InjectPromptModern(IReadOnlyList<Message> input, JsonValue schema) =>
        InjectPromptCore(input, schema, modern: true);

    private static IReadOnlyList<Message> InjectPromptCore(IReadOnlyList<Message> input, JsonValue schema, bool modern)
    {
        ArgumentNullException.ThrowIfNull(input);
        var instruction = RenderCore(schema, modern);
        var messages = input.Select(static message => message ?? throw new ArgumentException("Messages cannot contain null values.")).ToList();
        for (var index = messages.Count - 1; index >= 0; index--)
        {
            if (string.Equals(messages[index].Role, "system", StringComparison.Ordinal))
            {
                var content = messages[index].Content.Concat([new Text("\n\n" + instruction)]).ToArray();
                messages[index] = new Message(messages[index].Role, content);
                return Array.AsReadOnly(messages.ToArray());
            }
        }

        messages.Insert(0, new Message("system", [new Text(instruction)]));
        return Array.AsReadOnly(messages.ToArray());
    }
}
