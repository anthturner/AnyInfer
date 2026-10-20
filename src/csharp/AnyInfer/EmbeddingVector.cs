using AnyInfer.Internal;

namespace AnyInfer;

/// <summary>One immutable, finite embedding vector.</summary>
public sealed record EmbeddingVector
{
    /// <summary>Copies and validates one embedding vector.</summary>
    /// <param name="values">Ordered finite vector components.</param>
    public EmbeddingVector(IEnumerable<double> values)
    {
        ArgumentNullException.ThrowIfNull(values);
        Values = ImmutableValues.List(values, nameof(values));
        if (Values.Count == 0 || Values.Any(static value => !double.IsFinite(value)))
        {
            throw new ArgumentException("Embedding vectors must contain one or more finite values.", nameof(values));
        }
    }

    /// <summary>Gets the copied vector components in order.</summary>
    public IReadOnlyList<double> Values { get; }
}