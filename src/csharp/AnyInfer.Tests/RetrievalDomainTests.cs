using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Literal public retrieval value and wire-contract controls.</summary>
public sealed class RetrievalDomainTests
{
    [Fact]
    public void Batch_policy_uses_the_literal_defaults_and_rejects_only_invalid_caps()
    {
        var policy = new BatchPolicy();

        Assert.Equal(4, policy.MaxConcurrency);
        Assert.Null(policy.MaxItemsOverride);
        Assert.True(policy.AllowSplit);
        Assert.False(policy.RerankCrossBatch);
        Assert.Throws<ArgumentOutOfRangeException>(() => new BatchPolicy(0));
        Assert.Throws<ArgumentOutOfRangeException>(() => new BatchPolicy(maxItemsOverride: 0));
    }

    [Fact]
    public void Embedding_request_copies_nested_provider_options_and_keeps_source_permitted_values()
    {
        var nested = new Dictionary<string, JsonValue>(StringComparer.Ordinal)
        {
            ["precision"] = new JsonString("float"),
        };
        var options = new Dictionary<string, IReadOnlyDictionary<string, JsonValue>>(StringComparer.Ordinal)
        {
            ["fixture"] = nested,
        };
        var metadata = new Dictionary<string, string>(StringComparer.Ordinal) { ["trace"] = "original" };
        var request = new EmbeddingRequest(["", "  "], dimensions: -1, timeoutS: null, metadata: metadata, providerOptions: options);

        nested["precision"] = new JsonString("mutated");
        metadata["trace"] = "mutated";
        options["later"] = new Dictionary<string, JsonValue>();

        Assert.Equal(["", "  "], request.Inputs);
        Assert.Equal(-1, request.Dimensions);
        Assert.Equal(120d, request.EffectiveTimeoutS);
        Assert.Equal(64 * 1024 * 1024, request.MaxResponseBytes);
        Assert.Equal("original", request.Metadata["trace"]);
        Assert.Equal("float", Assert.IsType<JsonString>(request.ProviderOptions["fixture"]["precision"]).Value);
        Assert.False(request.ProviderOptions.ContainsKey("later"));
        if (request.ProviderOptions is IDictionary<string, IReadOnlyDictionary<string, JsonValue>> outer)
        {
            Assert.Throws<NotSupportedException>(() => outer.Add("cannot-mutate", new Dictionary<string, JsonValue>()));
        }

        if (request.ProviderOptions["fixture"] is IDictionary<string, JsonValue> inner)
        {
            Assert.Throws<NotSupportedException>(() => inner["precision"] = new JsonString("cannot-mutate"));
        }
        Assert.Throws<ArgumentException>(() => new EmbeddingRequest([]));
    }

    [Fact]
    public void Rerank_request_keeps_whitespace_and_rejects_only_empty_duplicate_or_invalid_top_n_inputs()
    {
        var sourceMetadata = new Dictionary<string, string>(StringComparer.Ordinal) { ["source"] = "fixture" };
        var document = new RerankDocument(" ", " ", sourceMetadata);
        var request = new RerankRequest(" ", [document], timeoutS: null);
        sourceMetadata["source"] = "changed";

        Assert.Equal(" ", request.Query);
        Assert.Equal(" ", Assert.Single(request.Documents).Id);
        Assert.Equal("fixture", Assert.Single(request.Documents).Metadata["source"]);
        Assert.Equal(120d, request.EffectiveTimeoutS);
        Assert.Equal(8 * 1024 * 1024, request.MaxResponseBytes);
        Assert.Throws<ArgumentException>(() => new RerankRequest("", [document]));
        Assert.Throws<ArgumentException>(() => new RerankRequest("query", []));
        Assert.Throws<ArgumentException>(() => new RerankRequest("query", [document, new RerankDocument(" ", "second")]));
        Assert.Throws<ArgumentOutOfRangeException>(() => new RerankRequest("query", [document], topN: 0));
    }

    [Fact]
    public void Public_vectors_ranked_items_and_spaces_apply_their_narrow_contracts()
    {
        var sourceValues = new List<double> { 1d, 2d };
        var vector = new EmbeddingVector(sourceValues);
        sourceValues[0] = 99d;
        var values = vector.Values as IList<double>;
        if (values is not null)
        {
            Assert.Throws<NotSupportedException>(() => values[0] = 3d);
        }

        Assert.Equal([1d, 2d], vector.Values);
        Assert.Throws<ArgumentException>(() => new EmbeddingVector([]));
        Assert.Throws<ArgumentException>(() => new EmbeddingVector([double.NaN]));
        Assert.Throws<ArgumentOutOfRangeException>(() => new RankedItem(-1, "id", 0));
        Assert.Throws<ArgumentException>(() => new RankedItem(0, "", 0));
        Assert.Throws<ArgumentException>(() => new RankedItem(0, "id", double.PositiveInfinity));

        var left = new EmbeddingSpace("provider", "model", modelRevision: "r1", dimensions: 2);
        var sameIdentityDifferentDimension = new EmbeddingSpace("provider", "model", modelRevision: "r1", dimensions: 99);
        var compatibleId = new EmbeddingSpace("other", "other", compatibilityId: "portable");
        var matchingCompatibleId = new EmbeddingSpace("third", "third", compatibilityId: "portable");
        Assert.True(left.CompatibleWith(sameIdentityDifferentDimension));
        Assert.True(compatibleId.CompatibleWith(matchingCompatibleId));
        Assert.False(left.CompatibleWith(compatibleId));
    }

    [Fact]
    public void Wire_values_copy_snapshots_but_leave_core_only_numeric_and_index_validation_permissive()
    {
        var options = new Dictionary<string, JsonValue>(StringComparer.Ordinal) { ["nested"] = new JsonInteger(1) };
        var vector = new List<double> { double.NaN, -1d };
        var vectors = new List<IEnumerable<double>> { vector };
        var phases = new Dictionary<string, double>(StringComparer.Ordinal) { ["decode"] = double.PositiveInfinity };
        var embedding = new EmbeddingWireResult(vectors, dimensions: -5, phases: phases);
        var wire = new EmbeddingWireRequest("model", ["one"], timeoutS: -1d, maxResponseBytes: -1, extraOptions: options);
        var defaultEmbeddingWire = new EmbeddingWireRequest("model", ["one"]);
        var defaultRerankWire = new RerankWireRequest("model", "query", [new RerankWireDocument(0, "text")]);
        var rerank = new RerankWireResult([new WireRankedItem(-4, double.NaN)]);

        options["nested"] = new JsonInteger(2);
        vector[0] = 7d;
        vectors.Clear();
        phases["decode"] = 0;

        Assert.Equal(-1d, wire.TimeoutS);
        Assert.Equal(-1, wire.MaxResponseBytes);
        Assert.Equal(120d, defaultEmbeddingWire.TimeoutS);
        Assert.Equal(1 * 1024 * 1024, defaultEmbeddingWire.MaxResponseBytes);
        Assert.Equal(120d, defaultRerankWire.TimeoutS);
        Assert.Equal(1 * 1024 * 1024, defaultRerankWire.MaxResponseBytes);
        Assert.Equal("1", Assert.IsType<JsonInteger>(wire.ExtraOptions["nested"]).Value.ToString());
        Assert.Single(embedding.Vectors);
        Assert.True(double.IsNaN(Assert.Single(embedding.Vectors).First()));
        Assert.True(double.IsPositiveInfinity(embedding.Phases["decode"]));
        Assert.Equal(-4, Assert.Single(rerank.Items).Index);
        Assert.True(double.IsNaN(Assert.Single(rerank.Items).Score));
    }

    [Fact]
    public void Result_snapshots_copy_all_mutable_sequences_without_rewriting_json_values()
    {
        var vectors = new List<EmbeddingVector> { new([1d, 2d]) };
        var embeddingAttempts = new List<AttemptRecord> { new(new ResolvedTarget("fixture", "model"), "ok") };
        var embeddingWarnings = new List<string> { "embedding-warning" };
        var rankedItems = new List<RankedItem> { new(0, "id", 0.5, "text") };
        var rerankAttempts = new List<AttemptRecord> { new(new ResolvedTarget("fixture", "model"), "ok") };
        var rerankWarnings = new List<string> { "rerank-warning" };
        var raw = new JsonObject([new JsonProperty("raw", new JsonInteger(7))]);
        var embedding = new EmbeddingResult(
            vectors,
            new ResolvedTarget("fixture", "model"),
            new EmbeddingSpace("fixture", "model", dimensions: 2),
            new Usage(),
            new Timing(),
            attempts: embeddingAttempts,
            warnings: embeddingWarnings,
            raw: raw);
        var rerank = new RerankResult(
            rankedItems,
            new ResolvedTarget("fixture", "model"),
            new Usage(),
            new Timing(),
            attempts: rerankAttempts,
            warnings: rerankWarnings,
            raw: raw);
        vectors.Clear();
        embeddingAttempts.Clear();
        embeddingWarnings[0] = "changed";
        rankedItems.Clear();
        rerankAttempts.Clear();
        rerankWarnings[0] = "changed";

        Assert.Single(embedding.Vectors);
        Assert.Single(embedding.Attempts);
        Assert.Equal("embedding-warning", Assert.Single(embedding.Warnings));
        Assert.Single(rerank.Items);
        Assert.Single(rerank.Attempts);
        Assert.Equal("rerank-warning", Assert.Single(rerank.Warnings));
        Assert.Same(raw, embedding.Raw);
        Assert.Same(raw, rerank.Raw);
    }
}
