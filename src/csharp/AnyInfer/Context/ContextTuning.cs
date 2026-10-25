using AnyInfer.Json;
using System.Numerics;

namespace AnyInfer.Context;

/// <summary>Immutable settings for context reduction algorithms.</summary>
/// <remarks>
/// This is a standalone settings object only. The C# SDK has no context reducers, history
/// reduction or request-path context handling, and no client, request or configuration reads
/// these values. The type validates the settings, holds them immutably, and converts them to
/// and from a mapping with snake_case keys.
/// </remarks>
public sealed record ContextTuning
{
    /// <summary>The default target token count for a context chunk.</summary>
    public const long DefaultChunkTokens = 512;
    /// <summary>The supported selection orders in their declared order.</summary>
    public static IReadOnlyList<string> SelectionOrders { get; } = Array.AsReadOnly(["rank", "density"]);
    /// <summary>The default immutable tuning instance.</summary>
    public static ContextTuning Default { get; } = new();

    /// <summary>Creates validated immutable context-tuning settings.</summary>
    /// <param name="collapseDuplicates">Whether exact duplicate documents should be collapsed; defaults to <see langword="true"/>.</param>
    /// <param name="nearDuplicateThreshold">The near-duplicate similarity threshold, from 0 to 1 inclusive; defaults to 0.</param>
    /// <param name="shingleSize">The word count in each near-duplicate comparison shingle, at least 1; defaults to 5.</param>
    /// <param name="selectionOrder">The candidate selection order, one of <see cref="SelectionOrders"/>; defaults to <c>rank</c>.</param>
    /// <param name="diversity">The selected-document similarity penalty, from 0 to 1 inclusive; defaults to 0.</param>
    /// <param name="splitIdentifiers">Whether identifiers should be split for token matching; defaults to <see langword="false"/>.</param>
    /// <param name="queryExpansion">Whether ranking should expand the query from feedback documents; defaults to <see langword="false"/>.</param>
    /// <param name="expansionTerms">The number of harvested expansion terms, at least 0; defaults to 8.</param>
    /// <param name="feedbackDocuments">The number of top documents used for expansion feedback, at least 0; defaults to 5.</param>
    /// <param name="expansionWeight">The relative weight of expansion terms, finite and at least 0; defaults to 0.4.</param>
    /// <param name="salienceWeight">The corpus-centrality contribution to ranking, finite and at least 0; defaults to 0.</param>
    /// <param name="salienceDamping">The restart damping for salience iteration, from 0 to 1 inclusive; defaults to 0.85.</param>
    /// <param name="salienceIterations">The fixed number of salience iterations, at least 1; defaults to 20.</param>
    /// <param name="compactFallback">Whether compact rendering should be used as a fallback; defaults to <see langword="false"/>.</param>
    /// <param name="chunkTokens">The target number of tokens per context chunk, at least 1; defaults to <see cref="DefaultChunkTokens"/>.</param>
    /// <param name="rollupShare">The budget share reserved for a tiered rollup, strictly between 0 and 1; defaults to 0.45.</param>
    /// <param name="carryOverBonus">The ranking bonus for documents carried over from a prior reduction, finite and at least 0; defaults to 0.</param>
    /// <exception cref="ArgumentNullException"><paramref name="selectionOrder"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentOutOfRangeException">A setting is outside its documented range or, for a <see cref="double"/> setting, not finite.</exception>
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
    /// <returns>
    /// A new instance with <see cref="NearDuplicateThreshold"/> 0.9, <see cref="SelectionOrder"/>
    /// <c>density</c>, <see cref="Diversity"/> 0.25, <see cref="SplitIdentifiers"/>,
    /// <see cref="QueryExpansion"/> and <see cref="CompactFallback"/> enabled,
    /// <see cref="SalienceWeight"/> 0.5 and <see cref="CarryOverBonus"/> 0.5; every other setting
    /// keeps its default.
    /// </returns>
    public static ContextTuning Recommended() => new(nearDuplicateThreshold: .9, selectionOrder: "density", diversity: .25, splitIdentifiers: true, queryExpansion: true, salienceWeight: .5, compactFallback: true, carryOverBonus: .5);

    /// <summary>Parses a strict JSON-shaped settings mapping.</summary>
    /// <remarks>
    /// Keys are the snake_case setting names, such as <c>collapse_duplicates</c> and
    /// <c>chunk_tokens</c>. Boolean settings need JSON Booleans, <c>selection_order</c> needs a
    /// string, count settings need integers in the <see cref="long"/> range, and fractional
    /// settings accept integers or numbers. Missing keys take their default values; JSON
    /// <c>null</c> is rejected like any other wrong type.
    /// </remarks>
    /// <param name="values">The mapping to parse.</param>
    /// <returns>A new validated instance.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="values"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">A key is unknown or a value has the wrong JSON type.</exception>
    /// <exception cref="ArgumentOutOfRangeException">A value is outside the setting's range.</exception>
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
    /// <returns>A new object holding all 17 settings in declaration order, readable by <see cref="FromMapping(JsonObject)"/>.</returns>
    public JsonObject ToMapping() => new(DefaultValues(this).Select(static pair => new JsonProperty(pair.Key, ToJson(pair.Value))));

    /// <summary>Returns this instance with non-null JSON overrides applied.</summary>
    /// <remarks>
    /// Properties whose value is JSON <c>null</c> are ignored; the rest are parsed with the same
    /// rules as <see cref="FromMapping(JsonObject)"/>. This instance is never modified.
    /// </remarks>
    /// <param name="overrides">The settings to override, keyed by snake_case name.</param>
    /// <returns>This same instance when no non-null override is present; otherwise a new validated instance.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="overrides"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">A non-null override has an unknown key or the wrong JSON type.</exception>
    /// <exception cref="ArgumentOutOfRangeException">An override is outside the setting's range.</exception>
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
