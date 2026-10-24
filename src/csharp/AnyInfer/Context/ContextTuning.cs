using AnyInfer.Json;
using System.Numerics;

namespace AnyInfer.Context;

/// <summary>Immutable settings for context reduction algorithms.</summary>
public sealed record ContextTuning
{
    /// <summary>The default target token count for a context chunk.</summary>
    public const long DefaultChunkTokens = 512;
    /// <summary>The supported selection orders in their declared order.</summary>
    public static IReadOnlyList<string> SelectionOrders { get; } = Array.AsReadOnly(["rank", "density"]);
    /// <summary>The default immutable tuning instance.</summary>
    public static ContextTuning Default { get; } = new();

    /// <summary>Creates validated immutable context-tuning settings.</summary>
    public ContextTuning(bool collapseDuplicates = true, double nearDuplicateThreshold = 0, long shingleSize = 5, string selectionOrder = "rank", double diversity = 0, bool splitIdentifiers = false, bool queryExpansion = false, long expansionTerms = 8, long feedbackDocuments = 5, double expansionWeight = .4, double salienceWeight = 0, double salienceDamping = .85, long salienceIterations = 20, bool compactFallback = false, long chunkTokens = DefaultChunkTokens, double rollupShare = .45, double carryOverBonus = 0)
    {
        ArgumentNullException.ThrowIfNull(selectionOrder);
        if (!SelectionOrders.Contains(selectionOrder, StringComparer.Ordinal)) throw new ArgumentOutOfRangeException(nameof(selectionOrder));
        Unit(nameof(nearDuplicateThreshold), nearDuplicateThreshold); Unit(nameof(diversity), diversity); Unit(nameof(salienceDamping), salienceDamping);
        NonNegative(nameof(expansionWeight), expansionWeight); NonNegative(nameof(salienceWeight), salienceWeight); NonNegative(nameof(carryOverBonus), carryOverBonus);
        Positive(nameof(shingleSize), shingleSize); Positive(nameof(salienceIterations), salienceIterations); Positive(nameof(chunkTokens), chunkTokens);
        NonNegative(nameof(expansionTerms), expansionTerms); NonNegative(nameof(feedbackDocuments), feedbackDocuments);
        if (!double.IsFinite(rollupShare) || rollupShare <= 0 || rollupShare >= 1) throw new ArgumentOutOfRangeException(nameof(rollupShare));
        CollapseDuplicates = collapseDuplicates; NearDuplicateThreshold = nearDuplicateThreshold; ShingleSize = shingleSize; SelectionOrder = selectionOrder; Diversity = diversity;
        SplitIdentifiers = splitIdentifiers; QueryExpansion = queryExpansion; ExpansionTerms = expansionTerms; FeedbackDocuments = feedbackDocuments; ExpansionWeight = expansionWeight;
        SalienceWeight = salienceWeight; SalienceDamping = salienceDamping; SalienceIterations = salienceIterations; CompactFallback = compactFallback; ChunkTokens = chunkTokens; RollupShare = rollupShare; CarryOverBonus = carryOverBonus;
    }

    /// <summary>Gets whether exact duplicate documents are collapsed.</summary>
    public bool CollapseDuplicates { get; }
    /// <summary>Gets the near-duplicate similarity threshold.</summary>
    public double NearDuplicateThreshold { get; }
    /// <summary>Gets the word count in each near-duplicate comparison shingle.</summary>
    public long ShingleSize { get; }
    /// <summary>Gets the candidate selection order.</summary>
    public string SelectionOrder { get; }
    /// <summary>Gets the selected-document similarity penalty.</summary>
    public double Diversity { get; }
    /// <summary>Gets whether identifiers are split for token matching.</summary>
    public bool SplitIdentifiers { get; }
    /// <summary>Gets whether ranking expands the query from feedback documents.</summary>
    public bool QueryExpansion { get; }
    /// <summary>Gets the number of harvested expansion terms.</summary>
    public long ExpansionTerms { get; }
    /// <summary>Gets the number of top documents used for expansion feedback.</summary>
    public long FeedbackDocuments { get; }
    /// <summary>Gets the relative weight assigned to expansion terms.</summary>
    public double ExpansionWeight { get; }
    /// <summary>Gets the corpus-centrality contribution to ranking.</summary>
    public double SalienceWeight { get; }
    /// <summary>Gets the restart damping used by salience iteration.</summary>
    public double SalienceDamping { get; }
    /// <summary>Gets the fixed number of salience iterations.</summary>
    public long SalienceIterations { get; }
    /// <summary>Gets whether compact rendering is used as a fallback.</summary>
    public bool CompactFallback { get; }
    /// <summary>Gets the target number of tokens in each context chunk.</summary>
    public long ChunkTokens { get; }
    /// <summary>Gets the budget share reserved for a tiered rollup.</summary>
    public double RollupShare { get; }
    /// <summary>Gets the ranking bonus for documents carried over from a prior reduction.</summary>
    public double CarryOverBonus { get; }
    /// <summary>Gets whether ranking uses its neutral algorithm settings.</summary>
    public bool RankingIsDefault => !SplitIdentifiers && !QueryExpansion && SalienceWeight == 0 && CarryOverBonus == 0;

    /// <summary>Returns the documented source-code corpus preset.</summary>
    public static ContextTuning Recommended() => new(nearDuplicateThreshold: .9, selectionOrder: "density", diversity: .25, splitIdentifiers: true, queryExpansion: true, salienceWeight: .5, compactFallback: true, carryOverBonus: .5);

    /// <summary>Parses a strict JSON-shaped settings mapping.</summary>
    public static ContextTuning FromMapping(JsonObject values)
    {
        ArgumentNullException.ThrowIfNull(values);
        var data = DefaultValues();
        foreach (var property in values.Properties)
        {
            if (!data.ContainsKey(property.Name)) throw new ArgumentException("Unknown context tuning setting.", nameof(values));
            data[property.Name] = Value(property.Name, property.Value);
        }
        return Build(data);
    }

    /// <summary>Returns all settings with their snake-case mapping keys.</summary>
    public JsonObject ToMapping() => new(DefaultValues(this).Select(static pair => new JsonProperty(pair.Key, ToJson(pair.Value))));

    /// <summary>Returns this instance with non-null JSON overrides applied.</summary>
    public ContextTuning Merged(JsonObject overrides)
    {
        ArgumentNullException.ThrowIfNull(overrides);
        var applied = overrides.Properties.Where(static property => property.Value is not JsonNull).ToArray();
        if (applied.Length == 0) return this;
        var data = DefaultValues(this);
        foreach (var property in applied)
        {
            if (!data.ContainsKey(property.Name)) throw new ArgumentException("Unknown context tuning setting.", nameof(overrides));
            data[property.Name] = Value(property.Name, property.Value);
        }
        return Build(data);
    }

    private static Dictionary<string, object> DefaultValues(ContextTuning? value = null)
    {
        value ??= Default;
        return new(StringComparer.Ordinal) { ["collapse_duplicates"] = value.CollapseDuplicates, ["near_duplicate_threshold"] = value.NearDuplicateThreshold, ["shingle_size"] = value.ShingleSize, ["selection_order"] = value.SelectionOrder, ["diversity"] = value.Diversity, ["split_identifiers"] = value.SplitIdentifiers, ["query_expansion"] = value.QueryExpansion, ["expansion_terms"] = value.ExpansionTerms, ["feedback_documents"] = value.FeedbackDocuments, ["expansion_weight"] = value.ExpansionWeight, ["salience_weight"] = value.SalienceWeight, ["salience_damping"] = value.SalienceDamping, ["salience_iterations"] = value.SalienceIterations, ["compact_fallback"] = value.CompactFallback, ["chunk_tokens"] = value.ChunkTokens, ["rollup_share"] = value.RollupShare, ["carry_over_bonus"] = value.CarryOverBonus };
    }
    private static ContextTuning Build(Dictionary<string, object> v) => new((bool)v["collapse_duplicates"], (double)v["near_duplicate_threshold"], (long)v["shingle_size"], (string)v["selection_order"], (double)v["diversity"], (bool)v["split_identifiers"], (bool)v["query_expansion"], (long)v["expansion_terms"], (long)v["feedback_documents"], (double)v["expansion_weight"], (double)v["salience_weight"], (double)v["salience_damping"], (long)v["salience_iterations"], (bool)v["compact_fallback"], (long)v["chunk_tokens"], (double)v["rollup_share"], (double)v["carry_over_bonus"]);
    private static object Value(string name, JsonValue value) => name switch
    {
        "collapse_duplicates" or "split_identifiers" or "query_expansion" or "compact_fallback" => value is JsonBoolean b ? b.Value : throw new ArgumentException($"{name} must be a boolean."),
        "selection_order" => value is JsonString s ? s.Value : throw new ArgumentException($"{name} must be a string."),
        "shingle_size" or "expansion_terms" or "feedback_documents" or "salience_iterations" or "chunk_tokens" => value is JsonInteger i && i.Value >= long.MinValue && i.Value <= long.MaxValue ? (long)i.Value : throw new ArgumentException($"{name} must be an Int64 integer."),
        _ => value is JsonNumber n ? n.Value : value is JsonInteger i ? checked((double)i.Value) : throw new ArgumentException($"{name} must be a number."),
    };
    private static JsonValue ToJson(object value) => value switch { bool b => new JsonBoolean(b), long i => new JsonInteger(new BigInteger(i)), double n => new JsonNumber(n), string s => new JsonString(s), _ => throw new InvalidOperationException() };
    private static void Unit(string name, double value) { if (!double.IsFinite(value) || value < 0 || value > 1) throw new ArgumentOutOfRangeException(name); }
    private static void NonNegative(string name, double value) { if (!double.IsFinite(value) || value < 0) throw new ArgumentOutOfRangeException(name); }
    private static void Positive(string name, long value) { if (value < 1) throw new ArgumentOutOfRangeException(name); }
    private static void NonNegative(string name, long value) { if (value < 0) throw new ArgumentOutOfRangeException(name); }
}
