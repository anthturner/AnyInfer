namespace AnyInfer;

public abstract record StreamEvent;

public sealed record TimingMark(string Name, double AtMs) : StreamEvent;

public sealed record TextDelta(string Text) : StreamEvent;

/// <summary>A fragment of reasoning text, excluded from visible answer text.</summary>
public sealed record ReasoningDelta : StreamEvent
{
    /// <summary>Creates a reasoning fragment.</summary>
    public ReasoningDelta(string text) => Text = text ?? throw new ArgumentNullException(nameof(text));
    /// <summary>Gets the reasoning fragment.</summary>
    public string Text { get; }
}

/// <summary>One fragment of a model-requested tool call, correlated by native index.</summary>
public sealed record ToolCallDelta(int Index, string? CallId, string? Name, string ArgumentsFragment) : StreamEvent;

/// <summary>A complete citation reported during generation.</summary>
public sealed record CitationDelta : StreamEvent
{
    /// <summary>Creates a citation update.</summary>
    public CitationDelta(Citation citation) => Citation = citation ?? throw new ArgumentNullException(nameof(citation));
    /// <summary>Gets the citation reported by the provider.</summary>
    public Citation Citation { get; }
}

/// <summary>A provider-run tool lifecycle update.</summary>
public sealed record ServerToolDelta : StreamEvent
{
    /// <summary>Creates a provider-run tool lifecycle update.</summary>
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

public sealed record UsageUpdate(Usage Usage) : StreamEvent;

public sealed record AttemptFailed(AttemptRecord Record) : StreamEvent;

public sealed record StreamEnded(Generation Result) : StreamEvent;
