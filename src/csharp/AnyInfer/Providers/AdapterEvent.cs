namespace AnyInfer.Providers;

/// <summary>Raw event emitted by a provider adapter.</summary>
/// <remarks>
/// An <see cref="IGeneratesText"/> adapter yields these while translating one provider response. The client
/// projects them into public stream events and result fields; the event types carry translated provider facts
/// only.
/// </remarks>
public abstract record AdapterEvent
{
    /// <summary>Initializes the base state of a derived adapter event.</summary>
    protected AdapterEvent()
    {
    }
}

/// <summary>Raw text delta emitted by a provider adapter.</summary>
/// <param name="Text">Output text fragment, appended to the generated text in emission order.</param>
public sealed record AdapterTextDelta(string Text) : AdapterEvent;

/// <summary>Raw reasoning delta emitted by a provider adapter.</summary>
public sealed record AdapterReasoningDelta : AdapterEvent
{
    /// <summary>Creates a raw reasoning fragment.</summary>
    /// <param name="text">Provider-reported reasoning text fragment.</param>
    /// <exception cref="ArgumentNullException"><paramref name="text"/> is <see langword="null"/>.</exception>
    public AdapterReasoningDelta(string text) => Text = text ?? throw new ArgumentNullException(nameof(text));
    /// <summary>Gets the raw reasoning fragment.</summary>
    public string Text { get; }
}

/// <summary>Raw citation update emitted by a provider adapter.</summary>
public sealed record AdapterCitationDelta : AdapterEvent
{
    /// <summary>Creates a raw citation update.</summary>
    /// <param name="citation">Provider-reported citation, collected into the result's citations.</param>
    /// <exception cref="ArgumentNullException"><paramref name="citation"/> is <see langword="null"/>.</exception>
    public AdapterCitationDelta(Citation citation) => Citation = citation ?? throw new ArgumentNullException(nameof(citation));
    /// <summary>Gets the raw provider citation.</summary>
    public Citation Citation { get; }
}

/// <summary>Raw provider-run tool update emitted by a provider adapter.</summary>
public sealed record AdapterServerToolDelta : AdapterEvent
{
    /// <summary>Creates a raw provider-run tool lifecycle update.</summary>
    /// <param name="kind">Normalized provider-run tool kind, such as <c>web_search</c>.</param>
    /// <param name="status">Provider-reported lifecycle status.</param>
    /// <param name="sources">Provider-reported sources, copied; <see langword="null"/> means none.</param>
    /// <param name="output">Provider-reported tool output, or an empty string.</param>
    /// <param name="detail">Provider-reported failure detail, or an empty string.</param>
    /// <exception cref="ArgumentNullException"><paramref name="kind"/>, <paramref name="status"/>, <paramref name="output"/>, or <paramref name="detail"/> is <see langword="null"/>.</exception>
    public AdapterServerToolDelta(string kind, string status, IEnumerable<ServerToolSource>? sources = null, string output = "", string detail = "")
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

/// <summary>Raw usage observation emitted by a provider adapter.</summary>
/// <param name="Usage">Provider-reported usage; fields the provider did not report stay <see langword="null"/>.</param>
public sealed record AdapterUsage(Usage Usage) : AdapterEvent;

/// <summary>Raw terminal event emitted by a provider adapter.</summary>
/// <remarks>
/// The client reads the finish reason, terminal usage, raw payload, phase timings, log-probabilities, and
/// provider-run tool-use counts from this event.
/// </remarks>
public sealed record AdapterFinal : AdapterEvent
{
    /// <summary>Creates a terminal adapter event with copied rich terminal fields.</summary>
    /// <param name="FinishReason">Provider finish reason, such as <c>stop</c> or <c>length</c>.</param>
    /// <param name="Usage">Terminal provider-reported usage, or <see langword="null"/> when the provider reported none.</param>
    /// <param name="Raw">Raw provider payload, or <see langword="null"/>; the client keeps it only when raw retention is enabled.</param>
    /// <param name="phases">Provider-reported phase timings in milliseconds keyed by phase name; <see langword="null"/> means none.</param>
    /// <param name="logprobs">Terminal token log-probabilities, copied; <see langword="null"/> means none.</param>
    /// <param name="serverToolUses">Terminal provider-run tool-use counts, copied; <see langword="null"/> means none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="FinishReason"/> is <see langword="null"/>.</exception>
    public AdapterFinal(string FinishReason, Usage? Usage = null, AnyInfer.Json.JsonValue? Raw = null, IEnumerable<KeyValuePair<string, double>>? phases = null, IEnumerable<TokenLogprob>? logprobs = null, IEnumerable<ServerToolUse>? serverToolUses = null)
    {
        this.FinishReason = FinishReason ?? throw new ArgumentNullException(nameof(FinishReason));
        this.Usage = Usage;
        this.Raw = Raw;
        Phases = new System.Collections.ObjectModel.ReadOnlyDictionary<string, double>((phases ?? []).ToDictionary(static pair => pair.Key, static pair => pair.Value, StringComparer.Ordinal));
        Logprobs = RichGenerationSnapshots.List(logprobs, nameof(logprobs));
        ServerToolUses = RichGenerationSnapshots.List(serverToolUses, nameof(serverToolUses));
    }
    /// <summary>Gets the provider finish reason.</summary>
    public string FinishReason { get; }
    /// <summary>Gets terminal provider-reported usage, or <see langword="null"/> when none was reported.</summary>
    public Usage? Usage { get; }
    /// <summary>Gets the raw provider payload, or <see langword="null"/>.</summary>
    public AnyInfer.Json.JsonValue? Raw { get; }
    /// <summary>Gets copied provider-reported phase timings in milliseconds.</summary>
    public IReadOnlyDictionary<string, double> Phases { get; }
    /// <summary>Gets copied terminal token log-probabilities.</summary>
    public IReadOnlyList<TokenLogprob> Logprobs { get; }
    /// <summary>Gets copied terminal provider-run tool-use counts.</summary>
    public IReadOnlyList<ServerToolUse> ServerToolUses { get; }
}

/// <summary>One raw provider tool-call delta; argument fragments are not assembled at this layer.</summary>
/// <param name="Index">Native signed 32-bit correlation index; out-of-range wire integers are refused, while absent or noninteger indexes use positional fallback.</param>
/// <param name="CallId">Optional provider call identifier.</param>
/// <param name="Name">Optional provider tool name.</param>
/// <param name="ArgumentsFragment">Raw provider argument fragment.</param>
public sealed record AdapterToolCallDelta(int Index, string? CallId, string? Name, string ArgumentsFragment) : AdapterEvent;
