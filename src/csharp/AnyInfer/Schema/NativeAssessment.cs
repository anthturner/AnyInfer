using AnyInfer.Json;

namespace AnyInfer.Schema;

/// <summary>One extraction or validation finding together with the native facts behind it.</summary>
public sealed record NativeFinding
{
    /// <summary>Creates an immutable finding.</summary>
    /// <param name="issue">The rule-level issue.</param>
    /// <param name="message">The human-readable diagnostic, as used in repair feedback.</param>
    /// <param name="source">
    /// The component that produced the finding, such as <c>schema-validator</c>,
    /// <c>response-extractor.scanner</c> or <c>response-extractor.parser</c>.
    /// </param>
    /// <param name="nativeFacts">
    /// Component-specific facts, such as <c>instance_location</c> and <c>schema_location</c> JSON
    /// Pointer strings or parser exception details.
    /// </param>
    /// <exception cref="ArgumentNullException">Any argument is <see langword="null"/>.</exception>
    public NativeFinding(Issue issue, string message, string source, JsonObject nativeFacts)
    {
        Issue = issue ?? throw new ArgumentNullException(nameof(issue));
        Message = message ?? throw new ArgumentNullException(nameof(message));
        Source = source ?? throw new ArgumentNullException(nameof(source));
        NativeFacts = nativeFacts ?? throw new ArgumentNullException(nameof(nativeFacts));
    }

    /// <summary>Gets the rule-level issue.</summary>
    public Issue Issue { get; }
    /// <summary>Gets the human-readable diagnostic.</summary>
    public string Message { get; }
    /// <summary>Gets the name of the component that produced the finding.</summary>
    public string Source { get; }
    /// <summary>Gets the component-specific facts.</summary>
    public JsonObject NativeFacts { get; }
}

/// <summary>The structured-output assessment of one response: extraction, validation and selected findings.</summary>
public sealed record NativeAssessment
{
    /// <summary>Creates an immutable assessment with a new <see cref="AssessmentId"/>.</summary>
    /// <param name="operationId">Identifier of the operation the assessed response belongs to.</param>
    /// <param name="sourceEntryOrdinal">Ordinal of the provider invocation within that operation whose response was assessed.</param>
    /// <param name="kind">
    /// <c>extraction</c> when no JSON value could be extracted, <c>validation</c> when an extracted
    /// value was validated, or <c>invalid_schema</c> when the schema itself was rejected.
    /// </param>
    /// <param name="structured">The extracted JSON value, or <see langword="null"/> when extraction failed.</param>
    /// <param name="allFindings">Every finding, in report order. The sequence is copied.</param>
    /// <param name="selectedFindings">
    /// The findings chosen for repair feedback. Each must be an occurrence, by reference, of an
    /// element of <paramref name="allFindings"/>, respecting how often it occurs there.
    /// </param>
    /// <param name="isValid">
    /// The validity verdict, or <see langword="null"/> to treat the assessment as valid exactly
    /// when <paramref name="allFindings"/> is empty.
    /// </param>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="kind"/> is not one of the three spellings.</exception>
    /// <exception cref="ArgumentNullException"><paramref name="allFindings"/> or <paramref name="selectedFindings"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">
    /// A finding sequence contains <see langword="null"/>, or a selected finding is not an
    /// occurrence from <paramref name="allFindings"/>.
    /// </exception>
    public NativeAssessment(
        Guid operationId,
        int sourceEntryOrdinal,
        string kind,
        JsonValue? structured,
        IEnumerable<NativeFinding> allFindings,
        IEnumerable<NativeFinding> selectedFindings,
        bool? isValid = null)
    {
        if (kind is not ("extraction" or "validation" or "invalid_schema"))
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
        IsValid = isValid ?? all.Length == 0;
    }

    /// <summary>Gets the random identifier assigned when this assessment was constructed.</summary>
    public Guid AssessmentId { get; }
    /// <summary>Gets the identifier of the operation the assessed response belongs to.</summary>
    public Guid OperationId { get; }
    /// <summary>Gets the ordinal of the provider invocation whose response was assessed.</summary>
    public int SourceEntryOrdinal { get; }
    /// <summary>Gets <c>extraction</c>, <c>validation</c> or <c>invalid_schema</c>.</summary>
    public string Kind { get; }
    /// <summary>Gets the extracted JSON value, or <see langword="null"/> when extraction failed.</summary>
    public JsonValue? Structured { get; }
    /// <summary>Gets every finding in report order.</summary>
    public IReadOnlyList<NativeFinding> AllFindings { get; }
    /// <summary>Gets the findings chosen for repair feedback.</summary>
    public IReadOnlyList<NativeFinding> SelectedFindings { get; }
    /// <summary>Gets the issues of <see cref="SelectedFindings"/>, in the same order.</summary>
    public IReadOnlyList<Issue> Issues { get; }
    /// <summary>Gets the messages of <see cref="SelectedFindings"/>, in the same order.</summary>
    public IReadOnlyList<string> Messages { get; }
    /// <summary>Gets whether the assessed response satisfied the schema.</summary>
    public bool IsValid { get; }
}
