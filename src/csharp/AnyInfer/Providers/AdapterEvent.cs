namespace AnyInfer.Providers;

/// <summary>Raw event emitted by a provider adapter.</summary>
public abstract record AdapterEvent;

/// <summary>Raw text delta emitted by a provider adapter.</summary>
public sealed record AdapterTextDelta(string Text) : AdapterEvent;

/// <summary>Raw reasoning delta emitted by a provider adapter.</summary>
public sealed record AdapterReasoningDelta : AdapterEvent
{
    /// <summary>Creates a raw reasoning fragment.</summary>
    public AdapterReasoningDelta(string text) => Text = text ?? throw new ArgumentNullException(nameof(text));
    /// <summary>Gets the raw reasoning fragment.</summary>
    public string Text { get; }
}

/// <summary>Raw citation update emitted by a provider adapter.</summary>
public sealed record AdapterCitationDelta : AdapterEvent
{
    /// <summary>Creates a raw citation update.</summary>
    public AdapterCitationDelta(Citation citation) => Citation = citation ?? throw new ArgumentNullException(nameof(citation));
    /// <summary>Gets the raw provider citation.</summary>
    public Citation Citation { get; }
}

/// <summary>Raw provider-run tool update emitted by a provider adapter.</summary>
public sealed record AdapterServerToolDelta : AdapterEvent
{
    /// <summary>Creates a raw provider-run tool lifecycle update.</summary>
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
public sealed record AdapterUsage(Usage Usage) : AdapterEvent;

/// <summary>Raw terminal event emitted by a provider adapter.</summary>
public sealed record AdapterFinal : AdapterEvent
{
    /// <summary>Creates a terminal adapter event with copied rich terminal fields.</summary>
    public AdapterFinal(string FinishReason, Usage? Usage = null, AnyInfer.Json.JsonValue? Raw = null, IEnumerable<KeyValuePair<string, double>>? phases = null, IEnumerable<TokenLogprob>? logprobs = null, IEnumerable<ServerToolUse>? serverToolUses = null)
    {
        this.FinishReason = FinishReason ?? throw new ArgumentNullException(nameof(FinishReason));
        this.Usage = Usage;
        this.Raw = Raw;
        Phases = new System.Collections.ObjectModel.ReadOnlyDictionary<string, double>((phases ?? []).ToDictionary(static pair => pair.Key, static pair => pair.Value, StringComparer.Ordinal));
        Logprobs = RichGenerationSnapshots.List(logprobs, nameof(logprobs));
        ServerToolUses = RichGenerationSnapshots.List(serverToolUses, nameof(serverToolUses));
    }
    public string FinishReason { get; }
    public Usage? Usage { get; }
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
