using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Manifest;

namespace AnyInfer;

/// <summary>One immutable embedding operation result.</summary>
public sealed record EmbeddingResult
{
    /// <summary>Creates a copied embedding result snapshot.</summary>
    public EmbeddingResult(
        IEnumerable<EmbeddingVector> vectors,
        ResolvedTarget target,
        EmbeddingSpace space,
        Usage usage,
        Timing timing,
        IEnumerable<AttemptRecord>? attempts = null,
        IEnumerable<string>? warnings = null,
        JsonValue? raw = null,
        RunManifest? manifest = null)
    {
        Vectors = ImmutableValues.List(vectors, nameof(vectors));
        Target = target ?? throw new ArgumentNullException(nameof(target));
        Space = space ?? throw new ArgumentNullException(nameof(space));
        Usage = usage ?? throw new ArgumentNullException(nameof(usage));
        Timing = timing ?? throw new ArgumentNullException(nameof(timing));
        Attempts = ImmutableValues.List(attempts, nameof(attempts));
        Warnings = ImmutableValues.List(warnings, nameof(warnings));
        Raw = raw;
        Manifest = manifest;
    }

    /// <summary>Gets vectors in request input order.</summary>
    public IReadOnlyList<EmbeddingVector> Vectors { get; }
    /// <summary>Gets the target that produced the vectors.</summary>
    public ResolvedTarget Target { get; }
    /// <summary>Gets the produced embedding-space identity.</summary>
    public EmbeddingSpace Space { get; }
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