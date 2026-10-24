using AnyInfer.Context;
using AnyInfer.Json;
using System.Numerics;
using Xunit;

namespace AnyInfer.Tests;

public sealed class ContextTuningTests
{
    [Fact]
    public void Recommended_changes_only_the_documented_default_fields()
    {
        var defaults = ContextTuning.Default;
        var recommended = ContextTuning.Recommended();
        Assert.Equal(defaults.CollapseDuplicates, recommended.CollapseDuplicates);
        Assert.Equal(defaults.ShingleSize, recommended.ShingleSize);
        Assert.Equal(defaults.ExpansionTerms, recommended.ExpansionTerms);
        Assert.Equal(defaults.FeedbackDocuments, recommended.FeedbackDocuments);
        Assert.Equal(defaults.ExpansionWeight, recommended.ExpansionWeight);
        Assert.Equal(defaults.SalienceDamping, recommended.SalienceDamping);
        Assert.Equal(defaults.SalienceIterations, recommended.SalienceIterations);
        Assert.Equal(defaults.ChunkTokens, recommended.ChunkTokens);
        Assert.Equal(defaults.RollupShare, recommended.RollupShare);
        Assert.Equal(.9, recommended.NearDuplicateThreshold);
        Assert.Equal("density", recommended.SelectionOrder);
        Assert.Equal(.25, recommended.Diversity);
        Assert.True(recommended.SplitIdentifiers);
        Assert.True(recommended.QueryExpansion);
        Assert.Equal(.5, recommended.SalienceWeight);
        Assert.True(recommended.CompactFallback);
        Assert.Equal(.5, recommended.CarryOverBonus);
    }

    [Fact]
    public void Defaults_recommended_and_ranking_predicate_match_the_settled_contract()
    {
        var value = ContextTuning.Default;
        Assert.True(value.CollapseDuplicates); Assert.Equal(0, value.NearDuplicateThreshold); Assert.Equal(5, value.ShingleSize); Assert.Equal("rank", value.SelectionOrder); Assert.Equal(0, value.Diversity);
        Assert.False(value.SplitIdentifiers); Assert.False(value.QueryExpansion); Assert.Equal(8, value.ExpansionTerms); Assert.Equal(5, value.FeedbackDocuments); Assert.Equal(.4, value.ExpansionWeight);
        Assert.Equal(0, value.SalienceWeight); Assert.Equal(.85, value.SalienceDamping); Assert.Equal(20, value.SalienceIterations); Assert.False(value.CompactFallback); Assert.Equal(512, value.ChunkTokens); Assert.Equal(.45, value.RollupShare); Assert.Equal(0, value.CarryOverBonus);
        Assert.Equal(["rank", "density"], ContextTuning.SelectionOrders); Assert.True(value.RankingIsDefault);
        var recommended = ContextTuning.Recommended();
        Assert.Equal(.9, recommended.NearDuplicateThreshold); Assert.Equal("density", recommended.SelectionOrder); Assert.Equal(.25, recommended.Diversity); Assert.True(recommended.SplitIdentifiers); Assert.True(recommended.QueryExpansion); Assert.Equal(.5, recommended.SalienceWeight); Assert.True(recommended.CompactFallback); Assert.Equal(.5, recommended.CarryOverBonus);
        Assert.True(new ContextTuning(diversity: 1, expansionWeight: 99, salienceDamping: 1, rollupShare: .5).RankingIsDefault);
    }

    [Fact]
    public void Constructor_rejects_invalid_domains_and_accepts_endpoints()
    {
        _ = new ContextTuning(nearDuplicateThreshold: 0, diversity: 1, salienceDamping: 0, expansionWeight: 0, salienceWeight: 0, carryOverBonus: 0, rollupShare: double.Epsilon);
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(nearDuplicateThreshold: double.NaN));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(diversity: double.PositiveInfinity));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(shingleSize: 0));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(rollupShare: 0));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(rollupShare: 1));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(selectionOrder: "other"));
    }

    [Fact]
    public void Strict_mapping_merge_and_round_trip_preserve_all_fields()
    {
        var all = new JsonObject([
            P("collapse_duplicates", false), P("near_duplicate_threshold", .1), P("shingle_size", 2), P("selection_order", "density"), P("diversity", .2), P("split_identifiers", true), P("query_expansion", true), P("expansion_terms", 3), P("feedback_documents", 4), P("expansion_weight", .5), P("salience_weight", .6), P("salience_damping", .7), P("salience_iterations", 8), P("compact_fallback", true), P("chunk_tokens", 9), P("rollup_share", .8), P("carry_over_bonus", .9),
        ]);
        var value = ContextTuning.FromMapping(all);
        Assert.Equal(value, ContextTuning.FromMapping(value.ToMapping())); Assert.Equal(17, value.ToMapping().Properties.Count);
        Assert.Throws<ArgumentException>(() => ContextTuning.FromMapping(new JsonObject([P("unknown", 1)])));
        Assert.Throws<ArgumentException>(() => ContextTuning.FromMapping(new JsonObject([new JsonProperty("collapse_duplicates", new JsonInteger(BigInteger.One))])));
        Assert.Throws<ArgumentException>(() => ContextTuning.FromMapping(new JsonObject([new JsonProperty("chunk_tokens", new JsonNumber(1))])));
        var merged = value.Merged(new JsonObject([new JsonProperty("unknown", JsonNull.Instance), new JsonProperty("chunk_tokens", JsonNull.Instance), P("diversity", 1)]));
        Assert.Equal(1, merged.Diversity); Assert.Equal(value.ChunkTokens, merged.ChunkTokens); Assert.Equal(.2, value.Diversity); Assert.Same(value, value.Merged(new JsonObject([new JsonProperty("unknown", JsonNull.Instance)])));
        Assert.Throws<ArgumentException>(() => value.Merged(new JsonObject([P("unknown", 1)])));
    }

    [Fact]
    public void Constructor_covers_every_numeric_validation_family_and_boundary()
    {
        _ = new ContextTuning(nearDuplicateThreshold: 0, diversity: 1, salienceDamping: 0, rollupShare: double.Epsilon);
        _ = new ContextTuning(nearDuplicateThreshold: 1, diversity: 0, salienceDamping: 1, rollupShare: Math.BitDecrement(1));
        _ = new ContextTuning(shingleSize: 1, salienceIterations: 1, chunkTokens: 1, expansionTerms: 0, feedbackDocuments: 0);

        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(nearDuplicateThreshold: -.01));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(nearDuplicateThreshold: 1.01));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(diversity: -.01));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(diversity: 1.01));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(salienceDamping: -.01));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(salienceDamping: 1.01));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(shingleSize: 0));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(salienceIterations: 0));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(chunkTokens: 0));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(expansionTerms: -1));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(feedbackDocuments: -1));
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(double.NegativeInfinity)]
    [InlineData(-.1)]
    public void Nonnegative_weights_reject_nonfinite_and_negative_values(double value)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(expansionWeight: value));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(salienceWeight: value));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(carryOverBonus: value));
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(double.NegativeInfinity)]
    [InlineData(0)]
    [InlineData(1)]
    public void Rollup_share_rejects_nonfinite_and_its_exclusive_endpoints(double value)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => new ContextTuning(rollupShare: value));
    }

    [Fact]
    public void Mapping_constructs_all_nondefault_values_and_serializes_their_actual_json_types()
    {
        var input = new JsonObject([
            P("collapse_duplicates", false), P("near_duplicate_threshold", .1), P("shingle_size", 2), P("selection_order", "density"), P("diversity", .2), P("split_identifiers", true), P("query_expansion", true), P("expansion_terms", 3), P("feedback_documents", 4), P("expansion_weight", .5), P("salience_weight", .6), P("salience_damping", .7), P("salience_iterations", 8), P("compact_fallback", true), P("chunk_tokens", 9), P("rollup_share", .8), P("carry_over_bonus", .9),
        ]);
        var expected = new ContextTuning(false, .1, 2, "density", .2, true, true, 3, 4, .5, .6, .7, 8, true, 9, .8, .9);
        var actual = ContextTuning.FromMapping(input);

        Assert.Equal(expected, actual);
        var output = actual.ToMapping();
        Assert.Equal(17, output.Properties.Count);
        Assert.Equal(["collapse_duplicates", "near_duplicate_threshold", "shingle_size", "selection_order", "diversity", "split_identifiers", "query_expansion", "expansion_terms", "feedback_documents", "expansion_weight", "salience_weight", "salience_damping", "salience_iterations", "compact_fallback", "chunk_tokens", "rollup_share", "carry_over_bonus"], output.Properties.Select(property => property.Name));
        Assert.False(Assert.IsType<JsonBoolean>(output.Properties[0].Value).Value);
        Assert.Equal(.1, Assert.IsType<JsonNumber>(output.Properties[1].Value).Value);
        Assert.Equal(new BigInteger(2), Assert.IsType<JsonInteger>(output.Properties[2].Value).Value);
        Assert.Equal("density", Assert.IsType<JsonString>(output.Properties[3].Value).Value);
        Assert.Equal(.2, Assert.IsType<JsonNumber>(output.Properties[4].Value).Value);
        Assert.True(Assert.IsType<JsonBoolean>(output.Properties[5].Value).Value);
        Assert.True(Assert.IsType<JsonBoolean>(output.Properties[6].Value).Value);
        Assert.Equal(new BigInteger(3), Assert.IsType<JsonInteger>(output.Properties[7].Value).Value);
        Assert.Equal(new BigInteger(4), Assert.IsType<JsonInteger>(output.Properties[8].Value).Value);
        Assert.Equal(.5, Assert.IsType<JsonNumber>(output.Properties[9].Value).Value);
        Assert.Equal(.6, Assert.IsType<JsonNumber>(output.Properties[10].Value).Value);
        Assert.Equal(.7, Assert.IsType<JsonNumber>(output.Properties[11].Value).Value);
        Assert.Equal(new BigInteger(8), Assert.IsType<JsonInteger>(output.Properties[12].Value).Value);
        Assert.True(Assert.IsType<JsonBoolean>(output.Properties[13].Value).Value);
        Assert.Equal(new BigInteger(9), Assert.IsType<JsonInteger>(output.Properties[14].Value).Value);
        Assert.Equal(.8, Assert.IsType<JsonNumber>(output.Properties[15].Value).Value);
        Assert.Equal(.9, Assert.IsType<JsonNumber>(output.Properties[16].Value).Value);
    }

    [Theory]
    [MemberData(nameof(InvalidMappingValues))]
    public void Mapping_rejects_strict_json_types_and_checked_integer_bounds(string key, JsonValue value)
    {
        Assert.Throws<ArgumentException>(() => ContextTuning.FromMapping(new JsonObject([new JsonProperty(key, value)])));
    }

    public static IEnumerable<object[]> InvalidMappingValues()
    {
        yield return ["collapse_duplicates", new JsonInteger(BigInteger.One)];
        yield return ["expansion_terms", new JsonBoolean(true)];
        yield return ["feedback_documents", new JsonNumber(1)];
        yield return ["shingle_size", new JsonString("1")];
        yield return ["chunk_tokens", JsonNull.Instance];
        yield return ["salience_iterations", new JsonInteger(BigInteger.Parse("9223372036854775808"))];
        yield return ["salience_iterations", new JsonInteger(BigInteger.Parse("-9223372036854775809"))];
    }

    [Fact]
    public void Mapping_and_merge_distinguish_unknown_null_and_preserve_original_instances()
    {
        var original = new ContextTuning(diversity: .2, chunkTokens: 17);
        Assert.Throws<ArgumentException>(() => ContextTuning.FromMapping(new JsonObject([new JsonProperty("unknown", JsonNull.Instance)])));
        Assert.Same(original, original.Merged(new JsonObject([new JsonProperty("unknown", JsonNull.Instance), new JsonProperty("chunk_tokens", JsonNull.Instance)])));
        var changed = original.Merged(new JsonObject([P("diversity", .8)]));
        Assert.Equal(.2, original.Diversity); Assert.Equal(17, original.ChunkTokens); Assert.Equal(.8, changed.Diversity); Assert.Equal(17, changed.ChunkTokens);
    }

    [Fact]
    public void Selection_orders_are_ordered_and_immutable()
    {
        var orders = Assert.IsAssignableFrom<IList<string>>(ContextTuning.SelectionOrders);
        Assert.Throws<NotSupportedException>(() => orders[0] = "density");
        Assert.Equal(["rank", "density"], ContextTuning.SelectionOrders);
    }

    private static JsonProperty P(string name, bool value) => new(name, new JsonBoolean(value));
    private static JsonProperty P(string name, long value) => new(name, new JsonInteger(new BigInteger(value)));
    private static JsonProperty P(string name, double value) => new(name, new JsonNumber(value));
    private static JsonProperty P(string name, string value) => new(name, new JsonString(value));
}
