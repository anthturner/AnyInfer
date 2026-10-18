using AnyInfer.Json;

namespace AnyInfer.Schema;

public static class SchemaPromptRenderer
{
    private const string Prefix = "Respond with ONLY a JSON value matching this JSON Schema. No prose. Schema:\n";

    public static string Render(JsonValue schema) => RenderCore(schema, modern: false);

    internal static string RenderModern(JsonValue schema) => RenderCore(schema, modern: true);

    private static string RenderCore(JsonValue schema, bool modern)
    {
        ArgumentNullException.ThrowIfNull(schema);
        return Prefix + (modern ? JsonWriter.WriteCanonicalModern(schema) : JsonWriter.WriteCanonical(schema));
    }

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
