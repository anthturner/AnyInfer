using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Manifest;

namespace AnyInfer;

/// <summary>One immutable reranking operation result.</summary>
public sealed record RerankResult
{
    /// <summary>Creates a copied reranking result snapshot.</summary>
    public RerankResult(
        IEnumerable<RankedItem> items,
        ResolvedTarget target,
        Usage usage,
        Timing timing,
        IEnumerable<AttemptRecord>? attempts = null,
        IEnumerable<string>? warnings = null,
        JsonValue? raw = null,
        RunManifest? manifest = null)
    {
        Items = ImmutableValues.List(items, nameof(items));
        Target = target ?? throw new ArgumentNullException(nameof(target));
        Usage = usage ?? throw new ArgumentNullException(nameof(usage));
        Timing = timing ?? throw new ArgumentNullException(nameof(timing));
        Attempts = ImmutableValues.List(attempts, nameof(attempts));
        Warnings = ImmutableValues.List(warnings, nameof(warnings));
        Raw = raw;
        Manifest = manifest;
    }

    /// <summary>Gets ranked items in provider result order.</summary>
    public IReadOnlyList<RankedItem> Items { get; }
    /// <summary>Gets the target that produced the ranking.</summary>
    public ResolvedTarget Target { get; }
    /// <summary>Gets normalized provider usage.</summary>
    public Usage Usage { get; }
    /// <summary>Gets operation timing facts.</summary>
    public Timing Timing { get; }
    /// <summary>Gets copied routing attempts.</summary>
    public IReadOnlyList<AttemptRecord> Attempts { get; }
    /// <summary>Gets copied nonfatal warnings.</summary>
    public IReadOnlyList<string> Warnings { get; }
    /// <summary>Gets the immutable raw provider payload when retained.</summary>
    public JsonValue? Raw { get; }
    /// <summary>Gets the optional operation manifest.</summary>
    public RunManifest? Manifest { get; }
}