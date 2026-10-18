using AnyInfer.Capabilities;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public provenance and pure capability-value controls aligned with the Python capability types.</summary>
public sealed class CapabilityTests
{
    [Fact]
    public void Sourced_provenance_ranks_ties_and_unknowns_are_distinct_from_real_values()
    {
        var catalog = new Sourced<int>(16, Provenance.Catalog);
        var equalCatalog = new Sourced<int>(32, Provenance.Catalog);
        var discovered = new Sourced<int>(8, Provenance.Discovered);

        Assert.True(catalog.Outranks(null));
        Assert.True(equalCatalog.Outranks(catalog));
        Assert.True(discovered.Outranks(catalog));
        Assert.False(catalog.Outranks(discovered));
        Assert.Throws<ArgumentOutOfRangeException>(() => new Sourced<int>(1, (Provenance)99));

        var unknown = new ModelCapabilities();
        var knownZeroFalse = new ModelCapabilities(
            contextWindow: new Sourced<int>(0, Provenance.Catalog),
            features: new Sourced<Feature>(Feature.None, Provenance.Catalog),
            operations: new Sourced<IReadOnlySet<InferenceOperation>>(
                new HashSet<InferenceOperation>(), Provenance.Catalog),
            embedding: new EmbeddingCapabilities(normalized: false));

        Assert.Null(unknown.ContextWindow);
        Assert.Equal(Feature.None, unknown.Features.Value);
        Assert.Equal(Provenance.Default, unknown.Features.Provenance);
        Assert.Null(unknown.Operations);
        Assert.Equal(0, knownZeroFalse.ContextWindow!.Value);
        Assert.Equal(Provenance.Catalog, knownZeroFalse.Features.Provenance);
        Assert.NotNull(knownZeroFalse.Operations);
        Assert.Empty(knownZeroFalse.Operations!.Value);
        Assert.False(knownZeroFalse.Embedding!.Normalized);
    }

    [Fact]
    public void Capability_constructors_copy_mutable_collections_and_overlay_equal_provenance()
    {
        var tools = new Dictionary<string, decimal> { ["web_search"] = 0.025m };
        var dimensions = new List<int> { 256, 1024 };
        var intents = new List<EmbeddingInputIntent> { EmbeddingInputIntent.Query };
        var operations = new HashSet<InferenceOperation> { InferenceOperation.Generation, InferenceOperation.Embedding };
        var pricing = new Pricing(1.25m, 10m, perServerToolUse: tools);
        var baseline = new ModelCapabilities(
            contextWindow: new Sourced<int>(4096, Provenance.Catalog),
            features: new Sourced<Feature>(Feature.Streaming, Provenance.Catalog),
            pricing: new Sourced<Pricing>(pricing, Provenance.Catalog),
            local: new LocalModelInfo(artifactSizeBytes: 0, parameterSize: "0B"),
            operations: new Sourced<IReadOnlySet<InferenceOperation>>(operations, Provenance.Catalog),
            embedding: new EmbeddingCapabilities(768, dimensions, inputIntents: intents, normalized: false));

        tools["web_search"] = 9m;
        dimensions.Add(1536);
        intents.Add(EmbeddingInputIntent.Document);
        operations.Add(InferenceOperation.Rerank);

        Assert.Equal(0.025m, baseline.Pricing!.Value.PerServerToolUse["web_search"]);
        Assert.Equal([256, 1024], baseline.Embedding!.DimensionChoices);
        Assert.Equal([EmbeddingInputIntent.Query], baseline.Embedding.InputIntents);
        Assert.DoesNotContain(InferenceOperation.Rerank, baseline.Operations!.Value);

        var sameOperationsReversed = new ModelCapabilities(
            contextWindow: new Sourced<int>(4096, Provenance.Catalog),
            features: new Sourced<Feature>(Feature.Streaming, Provenance.Catalog),
            pricing: new Sourced<Pricing>(new Pricing(1.25m, 10m, perServerToolUse: new Dictionary<string, decimal> { ["web_search"] = 0.025m }), Provenance.Catalog),
            local: new LocalModelInfo(artifactSizeBytes: 0, parameterSize: "0B"),
            operations: new Sourced<IReadOnlySet<InferenceOperation>>(
                new HashSet<InferenceOperation> { InferenceOperation.Embedding, InferenceOperation.Generation }, Provenance.Catalog),
            embedding: new EmbeddingCapabilities(768, [256, 1024], inputIntents: [EmbeddingInputIntent.Query], normalized: false));
        Assert.Equal(baseline, sameOperationsReversed);
        Assert.Equal(baseline.GetHashCode(), sameOperationsReversed.GetHashCode());
        Assert.Equal(Provenance.Catalog, sameOperationsReversed.Operations!.Provenance);

        var incoming = new ModelCapabilities(
            contextWindow: new Sourced<int>(8192, Provenance.Catalog),
            features: new Sourced<Feature>(Feature.JsonSchema, Provenance.Catalog),
            local: new LocalModelInfo(artifactSizeBytes: 123),
            embedding: new EmbeddingCapabilities(maxInputTokens: 2048, normalized: true));
        var overlaid = baseline.Overlay(incoming);

        Assert.Equal(8192, overlaid.ContextWindow!.Value);
        Assert.Equal(Feature.JsonSchema, overlaid.Features.Value);
        Assert.Equal(123, overlaid.Local!.ArtifactSizeBytes);
        Assert.Equal(768, overlaid.Embedding!.Dimensions);
        Assert.Equal([256, 1024], overlaid.Embedding.DimensionChoices);
        Assert.Equal(2048, overlaid.Embedding.MaxInputTokens);
        Assert.True(overlaid.Embedding.Normalized);
    }

    [Fact]
    public void Embedding_and_rerank_metadata_preserve_known_false_and_monotonic_true()
    {
        var embedding = new EmbeddingCapabilities(
            dimensions: 512,
            dimensionChoices: [256, 512],
            maxBatchInputs: 4,
            inputIntents: [EmbeddingInputIntent.Query],
            normalized: false);
        var update = new EmbeddingCapabilities(maxInputBytes: 8192, normalized: true);
        var merged = embedding.Overlay(update);

        Assert.Equal(512, merged.Dimensions);
        Assert.Equal([256, 512], merged.DimensionChoices);
        Assert.Equal(4, merged.MaxBatchInputs);
        Assert.Equal(8192, merged.MaxInputBytes);
        Assert.True(merged.Normalized);

        var explicitFalse = new EmbeddingCapabilities(normalized: true)
            .Overlay(new EmbeddingCapabilities(normalized: false));
        Assert.False(explicitFalse.Normalized);

        var rerank = new RerankCapabilities(maxDocuments: 16, nativeTopN: false)
            .Overlay(new RerankCapabilities(maxTokensPerDocument: 512, nativeTopN: true));
        Assert.Equal(16, rerank.MaxDocuments);
        Assert.Equal(512, rerank.MaxTokensPerDocument);
        Assert.True(rerank.NativeTopN);
        Assert.True(new RerankCapabilities(nativeTopN: true)
            .Overlay(new RerankCapabilities(nativeTopN: false)).NativeTopN);

        var same = new EmbeddingCapabilities(dimensionChoices: [256, 512], inputIntents: [EmbeddingInputIntent.Query]);
        Assert.Equal(same, new EmbeddingCapabilities(dimensionChoices: [256, 512], inputIntents: [EmbeddingInputIntent.Query]));
        Assert.Equal(same.GetHashCode(), new EmbeddingCapabilities(dimensionChoices: [256, 512], inputIntents: [EmbeddingInputIntent.Query]).GetHashCode());
        Assert.NotEqual(same, new EmbeddingCapabilities(dimensionChoices: [512, 256], inputIntents: [EmbeddingInputIntent.Query]));
    }

    [Fact]
    public void Conjunction_requires_complete_known_bounds_and_intersects_only_guarantees()
    {
        var first = new ModelCapabilities(
            contextWindow: new Sourced<int>(8192, Provenance.Probed),
            maxOutputTokens: new Sourced<int>(2048, Provenance.Catalog),
            features: new Sourced<Feature>(Feature.Streaming | Feature.JsonSchema, Provenance.Probed),
            pricing: new Sourced<Pricing>(new Pricing(1m, 2m), Provenance.Catalog),
            defaultTemperature: new Sourced<double>(0.2, Provenance.Catalog),
            local: new LocalModelInfo(artifactSizeBytes: 1),
            operations: new Sourced<IReadOnlySet<InferenceOperation>>(
                new HashSet<InferenceOperation> { InferenceOperation.Generation, InferenceOperation.Embedding }, Provenance.Probed),
            embedding: new EmbeddingCapabilities(dimensions: 1024));
        var second = new ModelCapabilities(
            contextWindow: new Sourced<int>(4096, Provenance.Catalog),
            maxOutputTokens: new Sourced<int>(1024, Provenance.Discovered),
            features: new Sourced<Feature>(Feature.Streaming | Feature.Tools, Provenance.Discovered),
            operations: new Sourced<IReadOnlySet<InferenceOperation>>(
                new HashSet<InferenceOperation> { InferenceOperation.Generation, InferenceOperation.Rerank }, Provenance.Discovered));

        var conjunction = ModelCapabilities.Conjunction([first, second]);
        Assert.Equal(4096, conjunction.ContextWindow!.Value);
        Assert.Equal(Provenance.Catalog, conjunction.ContextWindow.Provenance);
        Assert.Equal(1024, conjunction.MaxOutputTokens!.Value);
        Assert.Equal(Provenance.Catalog, conjunction.MaxOutputTokens.Provenance);
        Assert.Equal(Feature.Streaming, conjunction.Features.Value);
        Assert.Equal(Provenance.Discovered, conjunction.Features.Provenance);
        Assert.Equal([InferenceOperation.Generation], conjunction.Operations!.Value.Order());
        Assert.Equal(Provenance.Discovered, conjunction.Operations.Provenance);
        Assert.Null(conjunction.Pricing);
        Assert.Null(conjunction.DefaultTemperature);
        Assert.Null(conjunction.Local);
        Assert.Null(conjunction.Embedding);

        var unknownBound = ModelCapabilities.Conjunction([first, new ModelCapabilities(features: first.Features)]);
        Assert.Null(unknownBound.ContextWindow);
        Assert.Null(unknownBound.Operations);
        var empty = ModelCapabilities.Conjunction([]);
        Assert.Null(empty.ContextWindow);
        Assert.Equal(Feature.None, empty.Features.Value);
        Assert.Equal(Provenance.Default, empty.Features.Provenance);
    }

    [Fact]
    public void Pricing_retains_decimal_unknown_and_real_zero_rate_distinctions()
    {
        var unknownRates = new Pricing(1.25m, 10.5m, currency: "EUR", perServerToolUse: new Dictionary<string, decimal> { ["web_search"] = 0m });
        Assert.Equal(1.25m, unknownRates.InputPer1M);
        Assert.Equal(10.5m, unknownRates.OutputPer1M);
        Assert.Null(unknownRates.CacheReadPer1M);
        Assert.Null(unknownRates.CacheWritePer1M);
        Assert.Null(unknownRates.PerSearchUnit);
        Assert.Equal(0m, unknownRates.PerServerToolUse["web_search"]);
        Assert.Equal("EUR", unknownRates.Currency);
        Assert.False(unknownRates.PerServerToolUse.ContainsKey("code_execution"));

        var reverseMap = new Dictionary<string, decimal>
        {
            ["tool_b"] = 2m,
            ["tool_a"] = 1m,
        };
        var forwardMap = new Dictionary<string, decimal>
        {
            ["tool_a"] = 1m,
            ["tool_b"] = 2m,
        };
        var reverse = new Pricing(1m, 2m, perServerToolUse: reverseMap);
        var forward = new Pricing(1m, 2m, perServerToolUse: forwardMap);
        Assert.Equal(forward, reverse);
        Assert.Equal(forward.GetHashCode(), reverse.GetHashCode());

        var genuineFree = new Pricing(0m, 0m, cacheReadPer1M: 0m, cacheWritePer1M: 0m, perSearchUnit: 0m);
        Assert.Equal(0m, genuineFree.InputPer1M);
        Assert.Equal(0m, genuineFree.CacheReadPer1M);
        Assert.Equal(0m, genuineFree.PerSearchUnit);
    }

    [Fact]
    public void Token_calibration_preserves_tokenizer_provenance_and_rejects_invalid_facts()
    {
        var identity = new TokenCalibration();
        var calibrated = new TokenCalibration(1.25, 12, TokenizerKind.LlamaServerTokenize, Provenance.Probed);

        Assert.True(identity.IsIdentity);
        Assert.Null(identity.Tokenizer);
        Assert.Equal(Provenance.Default, identity.TokenizerProvenance);
        Assert.False(calibrated.IsIdentity);
        Assert.Equal(TokenizerKind.LlamaServerTokenize, calibrated.Tokenizer);
        Assert.Equal(Provenance.Probed, calibrated.TokenizerProvenance);
        Assert.Throws<ArgumentOutOfRangeException>(() => new TokenCalibration(0));
        Assert.Throws<ArgumentOutOfRangeException>(() => new TokenCalibration(double.NaN));
        Assert.Throws<ArgumentOutOfRangeException>(() => new TokenCalibration(double.PositiveInfinity));
        Assert.Throws<ArgumentOutOfRangeException>(() => new TokenCalibration(overheadTokens: -1));
        Assert.Throws<ArgumentOutOfRangeException>(() => new TokenCalibration(tokenizerProvenance: (Provenance)99));
    }

    [Fact]
    public void Rate_limit_header_declaration_uses_only_the_four_observation_headers()
    {
        var none = new RateLimitHeaders();
        var limitsOnly = new RateLimitHeaders(limitRequests: "x-limit-requests", limitTokens: "x-limit-tokens");
        var declared = new RateLimitHeaders("x-remaining", "x-reset", "x-token-remaining", "x-token-reset", "x-limit-requests", "x-limit-tokens");

        Assert.False(none.Declared);
        Assert.False(limitsOnly.Declared);
        Assert.True(declared.Declared);
        Assert.Equal("x-limit-requests", declared.LimitRequests);
        Assert.Equal("x-limit-tokens", declared.LimitTokens);
    }
}
