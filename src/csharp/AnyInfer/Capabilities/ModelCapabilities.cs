using System.Collections.Frozen;

namespace AnyInfer.Capabilities;

/// <summary>Represents model capability facts while retaining their provenance.</summary>
public sealed record ModelCapabilities
{
    /// <summary>Creates immutable model capability facts.</summary>
    /// <param name="contextWindow">Maximum input-context tokens with provenance, or <see langword="null"/> when unknown.</param>
    /// <param name="maxOutputTokens">Maximum output tokens with provenance, or <see langword="null"/> when unknown.</param>
    /// <param name="features">Supported feature flags with provenance; defaults to the unknown baseline.</param>
    /// <param name="pricing">Per-million-unit pricing with provenance, or <see langword="null"/> when unknown.</param>
    /// <param name="defaultTemperature">Documented default temperature with provenance, or <see langword="null"/> when unknown.</param>
    /// <param name="defaultTopP">Documented default top-p with provenance, or <see langword="null"/> when unknown.</param>
    /// <param name="local">Local-artifact facts, or <see langword="null"/> for a nonlocal or unknown model.</param>
    /// <param name="operations">Supported operations with provenance; the set is copied before exposure.</param>
    /// <param name="embedding">Embedding metadata, or <see langword="null"/> when no model-level embedding facts are known.</param>
    public ModelCapabilities(
        Sourced<int>? contextWindow = null,
        Sourced<int>? maxOutputTokens = null,
        Sourced<Feature>? features = null,
        Sourced<Pricing>? pricing = null,
        Sourced<double>? defaultTemperature = null,
        Sourced<double>? defaultTopP = null,
        LocalModelInfo? local = null,
        Sourced<IReadOnlySet<InferenceOperation>>? operations = null,
        EmbeddingCapabilities? embedding = null)
    {
        ContextWindow = contextWindow;
        MaxOutputTokens = maxOutputTokens;
        Features = features ?? new Sourced<Feature>(Feature.None, Provenance.Default);
        Pricing = pricing;
        DefaultTemperature = defaultTemperature;
        DefaultTopP = defaultTopP;
        Local = local;
        Operations = operations is null
            ? null
            : new Sourced<IReadOnlySet<InferenceOperation>>(
                operations.Value.ToFrozenSet(),
                operations.Provenance);
        Embedding = embedding;
    }

    /// <summary>Gets maximum input-context tokens with provenance, or <see langword="null"/> when unknown.</summary>
    public Sourced<int>? ContextWindow { get; }
    /// <summary>Gets maximum output tokens with provenance, or <see langword="null"/> when unknown.</summary>
    public Sourced<int>? MaxOutputTokens { get; }
    /// <summary>Gets supported features with provenance; <see cref="Feature.None"/> at default provenance is the unknown baseline.</summary>
    public Sourced<Feature> Features { get; }
    /// <summary>Gets per-million-unit pricing with provenance, or <see langword="null"/> when unknown.</summary>
    public Sourced<Pricing>? Pricing { get; }
    /// <summary>Gets documented default temperature with provenance, or <see langword="null"/> when unknown.</summary>
    public Sourced<double>? DefaultTemperature { get; }
    /// <summary>Gets documented default top-p with provenance, or <see langword="null"/> when unknown.</summary>
    public Sourced<double>? DefaultTopP { get; }
    /// <summary>Gets local-artifact facts, or <see langword="null"/> when no local facts are known.</summary>
    public LocalModelInfo? Local { get; }
    /// <summary>Gets an immutable snapshot of supported operations with provenance, or <see langword="null"/> when unknown.</summary>
    public Sourced<IReadOnlySet<InferenceOperation>>? Operations { get; }
    /// <summary>Gets model-level embedding facts, or <see langword="null"/> when unknown.</summary>
    public EmbeddingCapabilities? Embedding { get; }

    /// <summary>Compares scalar facts, copied operation membership and nested SDK-owned metadata by value.</summary>
    public bool Equals(ModelCapabilities? other)
    {
        return ReferenceEquals(this, other) ||
            other is not null &&
            EqualityComparer<Sourced<int>?>.Default.Equals(ContextWindow, other.ContextWindow) &&
            EqualityComparer<Sourced<int>?>.Default.Equals(MaxOutputTokens, other.MaxOutputTokens) &&
            EqualityComparer<Sourced<Feature>>.Default.Equals(Features, other.Features) &&
            EqualityComparer<Sourced<Pricing>?>.Default.Equals(Pricing, other.Pricing) &&
            EqualityComparer<Sourced<double>?>.Default.Equals(DefaultTemperature, other.DefaultTemperature) &&
            EqualityComparer<Sourced<double>?>.Default.Equals(DefaultTopP, other.DefaultTopP) &&
            EqualityComparer<LocalModelInfo?>.Default.Equals(Local, other.Local) &&
            OperationsEqual(Operations, other.Operations) &&
            EqualityComparer<EmbeddingCapabilities?>.Default.Equals(Embedding, other.Embedding);
    }

    /// <summary>Returns a hash code consistent with value-based operation-set equality.</summary>
    public override int GetHashCode()
    {
        var hash = new HashCode();
        hash.Add(ContextWindow);
        hash.Add(MaxOutputTokens);
        hash.Add(Features);
        hash.Add(Pricing);
        hash.Add(DefaultTemperature);
        hash.Add(DefaultTopP);
        hash.Add(Local);
        if (Operations is not null)
        {
            hash.Add(Operations.Provenance);
            CapabilityValueEquality.AddSetHash(ref hash, Operations.Value);
        }

        hash.Add(Embedding);
        return hash.ToHashCode();
    }

    /// <summary>Layers stronger or equally sourced fields from <paramref name="other"/> over this instance.</summary>
    /// <remarks>Equal provenance lets <paramref name="other"/> replace this instance's sourced field.</remarks>
    public ModelCapabilities Overlay(ModelCapabilities other)
    {
        ArgumentNullException.ThrowIfNull(other);
        return new ModelCapabilities(
            Stronger(ContextWindow, other.ContextWindow),
            Stronger(MaxOutputTokens, other.MaxOutputTokens),
            Stronger(Features, other.Features) ?? Features,
            Stronger(Pricing, other.Pricing),
            Stronger(DefaultTemperature, other.DefaultTemperature),
            Stronger(DefaultTopP, other.DefaultTopP),
            other.Local ?? Local,
            Stronger(Operations, other.Operations),
            Embedding is not null && other.Embedding is not null
                ? Embedding.Overlay(other.Embedding)
                : other.Embedding ?? Embedding);
    }

    /// <summary>Returns only facts guaranteed by every candidate model.</summary>
    /// <param name="candidates">Candidate capability records.</param>
    /// <returns>Unknown bounds when any candidate lacks them; otherwise minimum bounds and feature/operation intersections.</returns>
    public static ModelCapabilities Conjunction(IEnumerable<ModelCapabilities> candidates)
    {
        ArgumentNullException.ThrowIfNull(candidates);
        var values = candidates.ToArray();
        if (values.Length == 0)
        {
            return new ModelCapabilities();
        }

        var features = values[0].Features.Value;
        var featureProvenance = values[0].Features.Provenance;
        foreach (var capability in values.Skip(1))
        {
            features &= capability.Features.Value;
            featureProvenance = Weaker(featureProvenance, capability.Features.Provenance);
        }

        Sourced<IReadOnlySet<InferenceOperation>>? operations = null;
        if (values.All(static value => value.Operations is not null))
        {
            var first = values[0].Operations!;
            var intersection = first.Value.ToHashSet();
            var provenance = first.Provenance;
            foreach (var capability in values.Skip(1))
            {
                intersection.IntersectWith(capability.Operations!.Value);
                provenance = Weaker(provenance, capability.Operations.Provenance);
            }

            operations = new Sourced<IReadOnlySet<InferenceOperation>>(intersection.ToFrozenSet(), provenance);
        }

        return new ModelCapabilities(
            Minimum(values.Select(static value => value.ContextWindow)),
            Minimum(values.Select(static value => value.MaxOutputTokens)),
            new Sourced<Feature>(features, featureProvenance),
            operations: operations);
    }

    private static Sourced<T>? Stronger<T>(Sourced<T>? current, Sourced<T>? incoming) =>
        incoming is null ? current : incoming.Outranks(current) ? incoming : current;

    private static Sourced<int>? Minimum(IEnumerable<Sourced<int>?> values)
    {
        var known = values.ToArray();
        if (known.Any(static value => value is null))
        {
            return null;
        }

        var entries = known.Select(static value => value!).ToArray();
        var minimum = entries.MinBy(static entry => entry.Value)!;
        var provenance = entries.Aggregate(Provenance.Override, static (current, entry) => Weaker(current, entry.Provenance));
        return new Sourced<int>(minimum.Value, provenance);
    }

    private static Provenance Weaker(Provenance first, Provenance second) => first <= second ? first : second;

    private static bool OperationsEqual(
        Sourced<IReadOnlySet<InferenceOperation>>? first,
        Sourced<IReadOnlySet<InferenceOperation>>? second)
    {
        return first is null
            ? second is null
            : second is not null &&
                first.Provenance == second.Provenance &&
                CapabilityValueEquality.SetEquals(first.Value, second.Value);
    }
}
