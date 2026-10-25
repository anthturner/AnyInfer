using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Manifest;

namespace AnyInfer;

/// <summary>One immutable reranking operation result.</summary>
public sealed record RerankResult
{
    /// <summary>Creates a copied reranking result snapshot.</summary>
    /// <param name="items">
    /// The ranked items in provider result order, or <see langword="null"/> for none. When a request
    /// was split into batches, the clients concatenate each batch's ranking, and scores are
    /// comparable only within a batch. The sequence is copied.
    /// </param>
    /// <param name="target">The target that produced the ranking.</param>
    /// <param name="usage">The provider usage, with unknown counts left <see langword="null"/>.</param>
    /// <param name="timing">The operation timing.</param>
    /// <param name="attempts">The routing attempts in order, or <see langword="null"/> for none.</param>
    /// <param name="warnings">Nonfatal warnings, or <see langword="null"/> for none.</param>
    /// <param name="raw">The raw provider payload when retention was requested, or <see langword="null"/>.</param>
    /// <param name="manifest">The content-free operation manifest, or <see langword="null"/> when manifests are disabled.</param>
    /// <exception cref="ArgumentNullException"><paramref name="target"/>, <paramref name="usage"/> or <paramref name="timing"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">A supplied sequence contains <see langword="null"/>.</exception>
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