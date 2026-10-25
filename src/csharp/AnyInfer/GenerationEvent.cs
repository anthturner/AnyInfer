namespace AnyInfer;

/// <summary>
/// Base type for the ordered events an <see cref="AsyncStream"/> or <see cref="SyncStream"/> yields while a
/// generation runs. Match on the concrete event type; a successful stream ends with <see cref="StreamEnded"/>.
/// </summary>
/// <remarks>
/// Content events are yielded for every provider call the route makes, including calls that later fail and
/// calls superseded by a schema repair, so a consumer that renders text as it arrives must be ready to restart
/// after an <see cref="AttemptFailed"/>. The terminal <see cref="Generation"/> holds only the winning call's content.
/// </remarks>
public abstract record StreamEvent
{
    // Declared explicitly only so the constructor the compiler would otherwise synthesize is documented.
    /// <summary>Initializes the base state of a derived stream event.</summary>
    protected StreamEvent() { }
}

/// <summary>A centrally measured timing point on the clock of the current provider call.</summary>
/// <param name="Name">
/// The point being marked: <c>attempt_start</c> when a provider call begins, or <c>first_token</c> when the call
/// produces its first text, reasoning, or tool-call fragment.
/// </param>
/// <param name="AtMs">
/// Milliseconds elapsed since the provider call began; always <c>0</c> for <c>attempt_start</c>.
/// </param>
public sealed record TimingMark(string Name, double AtMs) : StreamEvent;

/// <summary>A fragment of visible answer text.</summary>
/// <param name="Text">The text fragment, in the order the provider produced it.</param>
public sealed record TextDelta(string Text) : StreamEvent;

/// <summary>A fragment of reasoning text, excluded from visible answer text.</summary>
public sealed record ReasoningDelta : StreamEvent
{
    /// <summary>Creates a reasoning fragment.</summary>
    /// <param name="text">The reasoning text fragment.</param>
    /// <exception cref="ArgumentNullException"><paramref name="text"/> is <see langword="null"/>.</exception>
    public ReasoningDelta(string text) => Text = text ?? throw new ArgumentNullException(nameof(text));
    /// <summary>Gets the reasoning fragment.</summary>
    public string Text { get; }
}

/// <summary>One fragment of a model-requested tool call, correlated by native index.</summary>
/// <remarks>
/// Concatenate <see cref="ArgumentsFragment"/> values that share an <see cref="Index"/> to rebuild a call's JSON
/// arguments. The terminal <see cref="Generation.ToolCalls"/> already contains the assembled calls.
/// </remarks>
/// <param name="Index">The tool-call slot within the provider response that this fragment belongs to.</param>
/// <param name="CallId">
/// The provider-assigned call identifier, or <see langword="null"/> (or empty) on fragments that do not carry it.
/// </param>
/// <param name="Name">
/// The name of the requested tool, or <see langword="null"/> (or empty) on fragments that do not carry it.
/// </param>
/// <param name="ArgumentsFragment">The next piece of this slot's JSON argument text; may be empty.</param>
public sealed record ToolCallDelta(int Index, string? CallId, string? Name, string ArgumentsFragment) : StreamEvent;

/// <summary>A complete citation reported during generation.</summary>
public sealed record CitationDelta : StreamEvent
{
    /// <summary>Creates a citation update.</summary>
    /// <param name="citation">The citation reported by the provider.</param>
    /// <exception cref="ArgumentNullException"><paramref name="citation"/> is <see langword="null"/>.</exception>
    public CitationDelta(Citation citation) => Citation = citation ?? throw new ArgumentNullException(nameof(citation));
    /// <summary>Gets the citation reported by the provider.</summary>
    public Citation Citation { get; }
}

/// <summary>A provider-run tool lifecycle update.</summary>
/// <remarks>
/// This is not a content event: it does not start the first-token clock or mark content as emitted.
/// </remarks>
public sealed record ServerToolDelta : StreamEvent
{
    /// <summary>Creates a provider-run tool lifecycle update.</summary>
    /// <param name="kind">The normalized provider-run tool kind, such as <c>web_search</c> or <c>code_execution</c>.</param>
    /// <param name="status">The provider-reported lifecycle status.</param>
    /// <param name="sources">
    /// Sources the tool reported, in provider order; <see langword="null"/> means none. The sequence is copied.
    /// </param>
    /// <param name="output">Provider-reported tool output; empty when there is none.</param>
    /// <param name="detail">Provider-reported failure detail; empty when there is none.</param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="kind"/>, <paramref name="status"/>, <paramref name="output"/>, or <paramref name="detail"/> is
    /// <see langword="null"/>.
    /// </exception>
    /// <exception cref="ArgumentException"><paramref name="sources"/> contains a <see langword="null"/> element.</exception>
    public ServerToolDelta(string kind, string status, IEnumerable<ServerToolSource>? sources = null, string output = "", string detail = "")
    {
        Kind = kind ?? throw new ArgumentNullException(nameof(kind));
        Status = status ?? throw new ArgumentNullException(nameof(status));
        Sources = RichGenerationSnapshots.List(sources, nameof(sources));
        Output = output ?? throw new ArgumentNullException(nameof(output));
        Detail = detail ?? throw new ArgumentNullException(nameof(detail));
    }
    /// <summary>Gets the normalized provider-run tool kind.</summary>
    public string Kind { get; }
    /// <summary>Gets the provider-reported lifecycle status.</summary>
    public string Status { get; }
    /// <summary>Gets copied provider-reported sources.</summary>
    public IReadOnlyList<ServerToolSource> Sources { get; }
    /// <summary>Gets provider-reported tool output.</summary>
    public string Output { get; }
    /// <summary>Gets provider-reported failure detail.</summary>
    public string Detail { get; }
}

/// <summary>Token usage reported by the provider for the current provider call.</summary>
/// <param name="Usage">
/// The usage values reported so far. Fields the provider has not reported are <see langword="null"/>; later updates
/// for the same call can fill them in. The terminal <see cref="Generation.Usage"/> holds the combined values.
/// </param>
public sealed record UsageUpdate(Usage Usage) : StreamEvent;

/// <summary>A provider attempt failed; a retry of the same target or a fallback to the next target may follow.</summary>
/// <param name="Record">
/// The failed attempt's routing-trail entry, with outcome <c>retried</c> or <c>failed</c>, the error, and any
/// measured timing.
/// </param>
public sealed record AttemptFailed(AttemptRecord Record) : StreamEvent;

/// <summary>The final event of a successful stream.</summary>
/// <param name="Result">The committed terminal generation, which the stream also exposes as its result.</param>
public sealed record StreamEnded(Generation Result) : StreamEvent;
