using AnyInfer.Schema;

namespace AnyInfer.Core;

internal sealed record RepairPreparation
{
    internal RepairPreparation(
        NativeAssessment assessment,
        string responseText,
        IEnumerable<Message> originalMessages,
        IEnumerable<Message> messages)
    {
        ArgumentNullException.ThrowIfNull(assessment);
        ArgumentNullException.ThrowIfNull(responseText);
        ArgumentNullException.ThrowIfNull(originalMessages);
        ArgumentNullException.ThrowIfNull(messages);
        Assessment = assessment;
        ResponseText = responseText;
        OriginalMessages = Array.AsReadOnly(originalMessages.Select(CopyMessage).ToArray());
        Messages = Array.AsReadOnly(messages.Select(CopyMessage).ToArray());
    }

    internal NativeAssessment Assessment { get; }
    internal string ResponseText { get; }
    internal IReadOnlyList<Message> OriginalMessages { get; }
    internal IReadOnlyList<Message> Messages { get; }

    private static Message CopyMessage(Message message)
    {
        ArgumentNullException.ThrowIfNull(message);
        return new Message(message.Role, message.Content);
    }
}

internal static class RepairBuilder
{
    internal static RepairPreparation Build(
        IReadOnlyList<Message> originalMessages,
        string rawResponse,
        NativeAssessment actualAssessment)
    {
        ArgumentNullException.ThrowIfNull(originalMessages);
        ArgumentNullException.ThrowIfNull(rawResponse);
        ArgumentNullException.ThrowIfNull(actualAssessment);

        var copiedOriginal = originalMessages.Select(static message => new Message(message.Role, message.Content)).ToArray();
        var repaired = copiedOriginal
            .Concat([
                new Message("assistant", [new TextPart(rawResponse)]),
                new Message("user", [new TextPart(Feedback(actualAssessment))]),
            ])
            .ToArray();
        return new RepairPreparation(actualAssessment, rawResponse, copiedOriginal, repaired);
    }

    private static string Feedback(NativeAssessment assessment) =>
        "Your previous response did not match the required JSON schema. Errors:\n" +
        string.Join("\n", assessment.Messages.Select(static message => "- " + message)) +
        "\nRespond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences.";
}
