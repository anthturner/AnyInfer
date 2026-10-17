using AnyInfer.Json;

namespace AnyInfer.Schema;

public static class SchemaPromptRenderer
{
    private const string Prefix = "Respond with ONLY a JSON value matching this JSON Schema. No prose. Schema:\n";

    public static string Render(JsonValue schema)
    {
        ArgumentNullException.ThrowIfNull(schema);
        return Prefix + JsonWriter.WriteCanonical(schema);
    }

    public static IReadOnlyList<Message> InjectPrompt(IReadOnlyList<Message> input, JsonValue schema)
    {
        ArgumentNullException.ThrowIfNull(input);
        var instruction = Render(schema);
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
