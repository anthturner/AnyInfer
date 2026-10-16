using AnyInfer.Json;

namespace AnyInfer.Schema;

public sealed record NativeFinding
{
    public NativeFinding(Issue issue, string message, string source, JsonObject nativeFacts)
    {
        Issue = issue ?? throw new ArgumentNullException(nameof(issue));
        Message = message ?? throw new ArgumentNullException(nameof(message));
        Source = source ?? throw new ArgumentNullException(nameof(source));
        NativeFacts = nativeFacts ?? throw new ArgumentNullException(nameof(nativeFacts));
    }

    public Issue Issue { get; }
    public string Message { get; }
    public string Source { get; }
    public JsonObject NativeFacts { get; }
}

public sealed record NativeAssessment
{
    public NativeAssessment(
        Guid operationId,
        int sourceEntryOrdinal,
        string kind,
        JsonValue? structured,
        IEnumerable<NativeFinding> allFindings,
        IEnumerable<NativeFinding> selectedFindings)
    {
        if (kind is not ("extraction" or "validation"))
        {
            throw new ArgumentOutOfRangeException(nameof(kind));
        }

        ArgumentNullException.ThrowIfNull(allFindings);
        ArgumentNullException.ThrowIfNull(selectedFindings);

        var all = allFindings
            .Select(static item => item ?? throw new ArgumentException("Findings cannot contain null values."))
            .ToArray();
        var selected = selectedFindings
            .Select(static item => item ?? throw new ArgumentException("Findings cannot contain null values."))
            .ToArray();
        var occurrences = new Dictionary<NativeFinding, int>(ReferenceEqualityComparer.Instance);

        foreach (var finding in all)
        {
            occurrences[finding] = occurrences.TryGetValue(finding, out var count) ? count + 1 : 1;
        }

        foreach (var finding in selected)
        {
            if (!occurrences.TryGetValue(finding, out var count) || count == 0)
            {
                throw new ArgumentException("Selected findings must be occurrences from all findings.", nameof(selectedFindings));
            }

            occurrences[finding] = count - 1;
        }

        AssessmentId = Guid.NewGuid();
        OperationId = operationId;
        SourceEntryOrdinal = sourceEntryOrdinal;
        Kind = kind;
        Structured = structured;
        AllFindings = Array.AsReadOnly(all);
        SelectedFindings = Array.AsReadOnly(selected);
        Issues = Array.AsReadOnly(selected.Select(static item => item.Issue).ToArray());
        Messages = Array.AsReadOnly(selected.Select(static item => item.Message).ToArray());
        IsValid = all.Length == 0;
    }

    public Guid AssessmentId { get; }
    public Guid OperationId { get; }
    public int SourceEntryOrdinal { get; }
    public string Kind { get; }
    public JsonValue? Structured { get; }
    public IReadOnlyList<NativeFinding> AllFindings { get; }
    public IReadOnlyList<NativeFinding> SelectedFindings { get; }
    public IReadOnlyList<Issue> Issues { get; }
    public IReadOnlyList<string> Messages { get; }
    public bool IsValid { get; }
}
