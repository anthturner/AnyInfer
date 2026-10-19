using System.Collections.ObjectModel;
using System.Globalization;
using System.Text;
using AnyInfer.Json;

namespace AnyInfer.Capabilities;

/// <summary>Describes how a target engages its prompt cache.</summary>
public enum CacheMechanism
{
    /// <summary>The provider accepts explicit prompt-segment marks.</summary>
    Explicit,
    /// <summary>The provider caches stable prefixes without a wire mark.</summary>
    Implicit,
}

/// <summary>One selected prompt segment for an explicit cache mark.</summary>
public sealed record CacheMark
{
    /// <summary>Creates a segment mark with its planning-side token estimate.</summary>
    public CacheMark(int segment, long estimatedTokens)
    {
        Segment = segment;
        EstimatedTokens = estimatedTokens;
    }

    /// <summary>Gets -2 for tools, -1 for system, or a zero-based message index.</summary>
    public int Segment { get; }

    /// <summary>Gets the planning-side size used to decide whether the segment was worthwhile.</summary>
    public long EstimatedTokens { get; }
}

/// <summary>Immutable prompt-cache recommendation for one request and selected target.</summary>
public sealed record CachePlan
{
    /// <summary>Creates an immutable cache plan.</summary>
    public CachePlan(
        CacheMechanism? mechanism = null,
        IEnumerable<CacheMark>? marks = null,
        long estimatedCacheableTokens = 0,
        IEnumerable<string>? reasons = null)
    {
        if (mechanism is not null && !Enum.IsDefined(mechanism.Value))
        {
            throw new ArgumentOutOfRangeException(nameof(mechanism));
        }

        Mechanism = mechanism;
        Marks = Array.AsReadOnly((marks ?? []).Select(mark =>
            mark ?? throw new ArgumentException("Cache marks cannot contain null references.", nameof(marks))).ToArray());
        EstimatedCacheableTokens = estimatedCacheableTokens;
        Reasons = Array.AsReadOnly((reasons ?? []).Select(reason =>
            reason ?? throw new ArgumentException("Cache reasons cannot contain null references.", nameof(reasons))).ToArray());
    }

    /// <summary>Gets the selected mechanism, or <see langword="null"/> when caching is inactive.</summary>
    public CacheMechanism? Mechanism { get; }

    /// <summary>Gets copied explicit marks in wire order. Implicit plans have no marks.</summary>
    public IReadOnlyList<CacheMark> Marks { get; }

    /// <summary>Gets the planning-side cacheable-token estimate, never a reported saving.</summary>
    public long EstimatedCacheableTokens { get; }

    /// <summary>Gets content-free reasons explaining an inactive or constrained plan.</summary>
    public IReadOnlyList<string> Reasons { get; }

    /// <summary>Gets whether this plan engages a target cache mechanism.</summary>
    public bool Active => Mechanism is not null;

    /// <summary>
    /// Computes a process-local prefix-change diagnostic from system text and sorted tool declarations.
    /// </summary>
    /// <remarks>The returned hash portions are not stable across processes or runtimes.</remarks>
    public string PrefixSignature(GenerationRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        var system = string.Join("\n", request.Messages
            .Where(static message => string.Equals(message.Role, "system", StringComparison.Ordinal))
            .Select(static message => string.Concat(message.Content.OfType<Text>().Select(static part => part.Value))));
        var tools = new JsonArray(request.Tools.Select(static tool => new JsonArray(
        [
            new JsonString(tool.Name),
            new JsonString(tool.Description),
            tool.Parameters,
        ])));
        var toolsJson = JsonWriter.WriteCacheSignature(tools);
        return system.EnumerateRunes().Count().ToString(CultureInfo.InvariantCulture) + ":" +
            unchecked((uint)StringComparer.Ordinal.GetHashCode(system)).ToString("x8", CultureInfo.InvariantCulture) + ":" +
            unchecked((uint)StringComparer.Ordinal.GetHashCode(toolsJson)).ToString("x8", CultureInfo.InvariantCulture);
    }
}
