using System.Collections.ObjectModel;
using AnyInfer.Internal;
using PeterO.Numbers;

namespace AnyInfer.Capabilities;

/// <summary>Features a model may support.</summary>
[Flags]
public enum Feature
{
    /// <summary>No supported features are known.</summary>
    None = 0,
    /// <summary>Supports streamed generation events.</summary>
    Streaming = 1 << 0,
    /// <summary>Supports a native JSON Schema structured-output mechanism.</summary>
    JsonSchema = 1 << 1,
    /// <summary>Supports a native grammar structured-output mechanism.</summary>
    Grammar = 1 << 2,
    /// <summary>Supports a native JSON-mode structured-output mechanism.</summary>
    JsonMode = 1 << 3,
    /// <summary>Supports provider tool invocation.</summary>
    Tools = 1 << 4,
    /// <summary>Supports reasoning-model behavior.</summary>
    Reasoning = 1 << 5,
    /// <summary>Accepts system messages.</summary>
    SystemPrompt = 1 << 6,
    /// <summary>Reports prompt-cache usage.</summary>
    CacheUsage = 1 << 7,
    /// <summary>Accepts prompt-cache placement instructions.</summary>
    CachePlacement = 1 << 8,
    /// <summary>Accepts image input.</summary>
    Vision = 1 << 9,
    /// <summary>Accepts document input.</summary>
    Document = 1 << 10,
    /// <summary>Accepts audio input.</summary>
    AudioIn = 1 << 11,
    /// <summary>Reports token log probabilities.</summary>
    Logprobs = 1 << 12,
    /// <summary>Accepts video input.</summary>
    VideoIn = 1 << 13,
    /// <summary>Produces citations.</summary>
    Citations = 1 << 14,
    /// <summary>Supports provider-hosted web search.</summary>
    WebSearch = 1 << 15,
    /// <summary>Supports provider-hosted code execution.</summary>
    CodeExecution = 1 << 16,
}

/// <summary>Identifies an inference operation a model can serve.</summary>
public enum InferenceOperation
{
    /// <summary>Text or structured generation.</summary>
    Generation,
    /// <summary>Text-to-vector embedding.</summary>
    Embedding,
    /// <summary>Document reranking.</summary>
    Rerank,
    /// <summary>Provider-managed batch execution.</summary>
    /// <remarks>
    /// This release has no batch-job adapter protocol, so a descriptor that declares this operation cannot build
    /// an adapter.
    /// </remarks>
    Batch,
}

/// <summary>Identifies an embedding input role understood by a model.</summary>
public enum EmbeddingInputIntent
{
    /// <summary>Text used as a retrieval query.</summary>
    Query,
    /// <summary>Text used as a retrieval document.</summary>
    Document,
    /// <summary>Text used for classification.</summary>
    Classification,
    /// <summary>Text used for clustering.</summary>
    Clustering,
}

/// <summary>Identifies an exact token-counting strategy.</summary>
public enum TokenizerKind
{
    /// <summary>The published OpenAI-family tokenizer.</summary>
    Tiktoken,
    /// <summary>Anthropic's count-tokens endpoint.</summary>
    AnthropicCountTokens,
    /// <summary>A supervised llama-server tokenize endpoint.</summary>
    LlamaServerTokenize,
}

/// <summary>Contains provider-stated per-million-unit pricing facts.</summary>
public sealed record Pricing
{
    /// <summary>Creates immutable pricing facts.</summary>
    /// <param name="inputPer1M">Price per one million input tokens.</param>
    /// <param name="outputPer1M">Price per one million output tokens.</param>
    /// <param name="cacheReadPer1M">Known cache-read price per one million tokens, or <see langword="null"/> when unknown.</param>
    /// <param name="cacheWritePer1M">Known cache-write price per one million tokens, or <see langword="null"/> when unknown.</param>
    /// <param name="currency">The quoted currency code.</param>
    /// <param name="perSearchUnit">Known price per billed search unit, or <see langword="null"/> when unknown.</param>
    /// <param name="perServerToolUse">Known provider-tool prices, copied with ordinal string keys.</param>
    public Pricing(
        EDecimal inputPer1M,
        EDecimal outputPer1M,
        EDecimal? cacheReadPer1M = null,
        EDecimal? cacheWritePer1M = null,
        string currency = "USD",
        EDecimal? perSearchUnit = null,
        IReadOnlyDictionary<string, EDecimal>? perServerToolUse = null)
    {
        InputPer1M = inputPer1M;
        OutputPer1M = outputPer1M;
        CacheReadPer1M = cacheReadPer1M;
        CacheWritePer1M = cacheWritePer1M;
        Currency = currency ?? throw new ArgumentNullException(nameof(currency));
        PerSearchUnit = perSearchUnit;
        PerServerToolUse = new ReadOnlyDictionary<string, EDecimal>(
            perServerToolUse is null
                ? new Dictionary<string, EDecimal>(StringComparer.Ordinal)
                : new Dictionary<string, EDecimal>(perServerToolUse, StringComparer.Ordinal));
    }

    /// <summary>Gets the price per one million input tokens.</summary>
    public EDecimal InputPer1M { get; }
    /// <summary>Gets the price per one million output tokens.</summary>
    public EDecimal OutputPer1M { get; }
    /// <summary>Gets the cache-read price per one million tokens, or <see langword="null"/> when unknown.</summary>
    public EDecimal? CacheReadPer1M { get; }
    /// <summary>Gets the cache-write price per one million tokens, or <see langword="null"/> when unknown.</summary>
    public EDecimal? CacheWritePer1M { get; }
    /// <summary>Gets the currency code for every amount in this record.</summary>
    public string Currency { get; }
    /// <summary>Gets the price per billed search unit, or <see langword="null"/> when unknown.</summary>
    public EDecimal? PerSearchUnit { get; }
    /// <summary>Gets an immutable snapshot of known prices per provider-run tool invocation.</summary>
    public IReadOnlyDictionary<string, EDecimal> PerServerToolUse { get; }

    /// <summary>Compares all pricing values and tool-price pairs independent of map insertion order.</summary>
    /// <remarks>Amounts compare numerically, so <c>1.0</c> equals <c>1.00</c>.</remarks>
    /// <param name="other">Pricing to compare with this instance.</param>
    /// <returns><see langword="true"/> when every amount, the currency, and every tool price are equal.</returns>
    public bool Equals(Pricing? other)
    {
        return ReferenceEquals(this, other) ||
            other is not null &&
            AccountingDecimal.NumericEquals(InputPer1M, other.InputPer1M) &&
            NullableEquals(CacheReadPer1M, other.CacheReadPer1M) &&
            NullableEquals(CacheWritePer1M, other.CacheWritePer1M) &&
            AccountingDecimal.NumericEquals(OutputPer1M, other.OutputPer1M) &&
            string.Equals(Currency, other.Currency, StringComparison.Ordinal) &&
            NullableEquals(PerSearchUnit, other.PerSearchUnit) &&
            ToolRatesEqual(PerServerToolUse, other.PerServerToolUse);
    }

    /// <summary>Returns a hash code consistent with value-based map equality.</summary>
    /// <returns>A hash code that is equal for pricing values that compare equal.</returns>
    public override int GetHashCode()
    {
        var hash = new HashCode();
        hash.Add(AccountingDecimal.NumericHashCode(InputPer1M));
        hash.Add(AccountingDecimal.NumericHashCode(OutputPer1M));
        hash.Add(NullableHashCode(CacheReadPer1M));
        hash.Add(NullableHashCode(CacheWritePer1M));
        hash.Add(Currency, StringComparer.Ordinal);
        hash.Add(NullableHashCode(PerSearchUnit));
        foreach (var (key, value) in PerServerToolUse.OrderBy(static item => item.Key, StringComparer.Ordinal))
        {
            hash.Add(key, StringComparer.Ordinal);
            hash.Add(AccountingDecimal.NumericHashCode(value));
        }
        return hash.ToHashCode();
    }

    private static bool NullableEquals(EDecimal? left, EDecimal? right) =>
        left is null ? right is null : right is not null && AccountingDecimal.NumericEquals(left, right);

    private static int NullableHashCode(EDecimal? value) =>
        value is null ? 0 : AccountingDecimal.NumericHashCode(value);

    private static bool ToolRatesEqual(IReadOnlyDictionary<string, EDecimal> left, IReadOnlyDictionary<string, EDecimal> right) =>
        left.Count == right.Count && left.All(item => right.TryGetValue(item.Key, out var value) && AccountingDecimal.NumericEquals(item.Value, value));
}

/// <summary>Describes a provider envelope's token accounting calibration.</summary>
public sealed record TokenCalibration
{
    /// <summary>Creates a validated token calibration.</summary>
    /// <param name="multiplier">Finite positive factor for prompt-proportional tokens.</param>
    /// <param name="overheadTokens">Nonnegative flat tokens added by the provider envelope.</param>
    /// <param name="tokenizer">Exact tokenizer strategy, or <see langword="null"/> when none is known.</param>
    /// <param name="tokenizerProvenance">Closed provenance of the tokenizer claim.</param>
    public TokenCalibration(
        double multiplier = 1.0,
        int overheadTokens = 0,
        TokenizerKind? tokenizer = null,
        Provenance tokenizerProvenance = Provenance.Default)
    {
        CapabilityValidation.RequireDefinedProvenance(tokenizerProvenance, nameof(tokenizerProvenance));

        if (!double.IsFinite(multiplier) || multiplier <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(multiplier));
        }

        if (overheadTokens < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(overheadTokens));
        }

        Multiplier = multiplier;
        OverheadTokens = overheadTokens;
        Tokenizer = tokenizer;
        TokenizerProvenance = tokenizerProvenance;
    }

    /// <summary>Gets the prompt-proportional token multiplier.</summary>
    public double Multiplier { get; }
    /// <summary>Gets the flat envelope overhead in tokens.</summary>
    public int OverheadTokens { get; }
    /// <summary>Gets the exact tokenizer strategy, or <see langword="null"/> when unknown.</summary>
    public TokenizerKind? Tokenizer { get; }
    /// <summary>Gets the evidence provenance of <see cref="Tokenizer"/>.</summary>
    public Provenance TokenizerProvenance { get; }
    /// <summary>Gets whether this calibration leaves an estimate unchanged.</summary>
    public bool IsIdentity => Multiplier == 1.0 && OverheadTokens == 0;
}

/// <summary>Declares rate-limit response header names for one provider dialect.</summary>
public sealed record RateLimitHeaders
{
    /// <summary>Creates immutable header declarations.</summary>
    /// <param name="requestsRemaining">Header reporting requests remaining, or empty when undeclared.</param>
    /// <param name="requestsReset">Header reporting request-window reset, or empty when undeclared.</param>
    /// <param name="tokensRemaining">Header reporting tokens remaining, or empty when undeclared.</param>
    /// <param name="tokensReset">Header reporting token-window reset, or empty when undeclared.</param>
    /// <param name="limitRequests">Header reporting the request limit, or empty when undeclared.</param>
    /// <param name="limitTokens">Header reporting the token limit, or empty when undeclared.</param>
    public RateLimitHeaders(
        string requestsRemaining = "",
        string requestsReset = "",
        string tokensRemaining = "",
        string tokensReset = "",
        string limitRequests = "",
        string limitTokens = "")
    {
        RequestsRemaining = requestsRemaining ?? throw new ArgumentNullException(nameof(requestsRemaining));
        RequestsReset = requestsReset ?? throw new ArgumentNullException(nameof(requestsReset));
        TokensRemaining = tokensRemaining ?? throw new ArgumentNullException(nameof(tokensRemaining));
        TokensReset = tokensReset ?? throw new ArgumentNullException(nameof(tokensReset));
        LimitRequests = limitRequests ?? throw new ArgumentNullException(nameof(limitRequests));
        LimitTokens = limitTokens ?? throw new ArgumentNullException(nameof(limitTokens));
    }

    /// <summary>Gets the header name for requests remaining.</summary>
    public string RequestsRemaining { get; }
    /// <summary>Gets the header name for request-window reset.</summary>
    public string RequestsReset { get; }
    /// <summary>Gets the header name for tokens remaining.</summary>
    public string TokensRemaining { get; }
    /// <summary>Gets the header name for token-window reset.</summary>
    public string TokensReset { get; }
    /// <summary>Gets the header name for the request limit.</summary>
    public string LimitRequests { get; }
    /// <summary>Gets the header name for the token limit.</summary>
    public string LimitTokens { get; }
    /// <summary>Gets whether any readable remaining or reset header is declared.</summary>
    public bool Declared => !string.IsNullOrEmpty(RequestsRemaining) || !string.IsNullOrEmpty(RequestsReset) ||
                            !string.IsNullOrEmpty(TokensRemaining) || !string.IsNullOrEmpty(TokensReset);
}

/// <summary>Describes local-artifact facts without acquiring or running an artifact.</summary>
public sealed record LocalModelInfo
{
    /// <summary>Creates local-artifact facts; each nullable parameter remains unknown when omitted.</summary>
    /// <param name="artifactSizeBytes">Artifact size on disk in bytes, or <see langword="null"/> when unknown.</param>
    /// <param name="parameterSize">Runtime-reported parameter-size label, or <see langword="null"/> when unknown.</param>
    /// <param name="quantization">Artifact quantization label, or <see langword="null"/> when unknown.</param>
    /// <param name="estRamBytes">Estimated system RAM in bytes, or <see langword="null"/> when unknown.</param>
    /// <param name="estVramBytes">Estimated GPU memory in bytes, or <see langword="null"/> when unknown.</param>
    /// <param name="observedVramBytes">Observed GPU memory in bytes, or <see langword="null"/> when unmeasured.</param>
    public LocalModelInfo(
        long? artifactSizeBytes = null,
        string? parameterSize = null,
        string? quantization = null,
        long? estRamBytes = null,
        long? estVramBytes = null,
        long? observedVramBytes = null)
    {
        ArtifactSizeBytes = artifactSizeBytes;
        ParameterSize = parameterSize;
        Quantization = quantization;
        EstRamBytes = estRamBytes;
        EstVramBytes = estVramBytes;
        ObservedVramBytes = observedVramBytes;
    }

    /// <summary>Gets artifact bytes on disk, or <see langword="null"/> when unknown.</summary>
    public long? ArtifactSizeBytes { get; }
    /// <summary>Gets the runtime-reported parameter-size label, or <see langword="null"/> when unknown.</summary>
    public string? ParameterSize { get; }
    /// <summary>Gets the artifact quantization label, or <see langword="null"/> when unknown.</summary>
    public string? Quantization { get; }
    /// <summary>Gets estimated system RAM bytes, or <see langword="null"/> when unknown.</summary>
    public long? EstRamBytes { get; }
    /// <summary>Gets estimated GPU memory bytes, or <see langword="null"/> when unknown.</summary>
    public long? EstVramBytes { get; }
    /// <summary>Gets observed GPU memory bytes, or <see langword="null"/> when unmeasured.</summary>
    public long? ObservedVramBytes { get; }
}

/// <summary>Describes embedding metadata a model states about itself.</summary>
public sealed record EmbeddingCapabilities
{
    /// <summary>Creates copied embedding capability metadata.</summary>
    /// <param name="dimensions">Fixed output dimensions, or <see langword="null"/> when unknown.</param>
    /// <param name="dimensionChoices">Supported output dimension choices, copied in order.</param>
    /// <param name="maxBatchInputs">Maximum inputs per request, or <see langword="null"/> when unknown.</param>
    /// <param name="maxInputTokens">Maximum tokens per input, or <see langword="null"/> when unknown.</param>
    /// <param name="maxInputBytes">Maximum bytes per input, or <see langword="null"/> when unknown.</param>
    /// <param name="inputIntents">Supported input roles, copied in order.</param>
    /// <param name="normalized">Whether vectors are unit-normalized, or <see langword="null"/> when undocumented.</param>
    public EmbeddingCapabilities(
        int? dimensions = null,
        IEnumerable<int>? dimensionChoices = null,
        int? maxBatchInputs = null,
        int? maxInputTokens = null,
        int? maxInputBytes = null,
        IEnumerable<EmbeddingInputIntent>? inputIntents = null,
        bool? normalized = null)
    {
        Dimensions = dimensions;
        DimensionChoices = Array.AsReadOnly((dimensionChoices ?? []).ToArray());
        MaxBatchInputs = maxBatchInputs;
        MaxInputTokens = maxInputTokens;
        MaxInputBytes = maxInputBytes;
        InputIntents = Array.AsReadOnly((inputIntents ?? []).ToArray());
        Normalized = normalized;
    }

    /// <summary>Gets fixed output dimensions, or <see langword="null"/> when unknown.</summary>
    public int? Dimensions { get; }
    /// <summary>Gets an immutable, ordered snapshot of supported output dimension choices.</summary>
    public IReadOnlyList<int> DimensionChoices { get; }
    /// <summary>Gets the maximum inputs per request, or <see langword="null"/> when unknown.</summary>
    public int? MaxBatchInputs { get; }
    /// <summary>Gets the maximum tokens per input, or <see langword="null"/> when unknown.</summary>
    public int? MaxInputTokens { get; }
    /// <summary>Gets the maximum bytes per input, or <see langword="null"/> when unknown.</summary>
    public int? MaxInputBytes { get; }
    /// <summary>Gets an immutable, ordered snapshot of supported input roles.</summary>
    public IReadOnlyList<EmbeddingInputIntent> InputIntents { get; }
    /// <summary>Gets vector normalization, or <see langword="null"/> when undocumented.</summary>
    public bool? Normalized { get; }

    /// <summary>Compares copied dimension and intent sequences in order with all scalar metadata.</summary>
    /// <param name="other">Embedding metadata to compare with this instance.</param>
    /// <returns><see langword="true"/> when every scalar and both ordered sequences are equal.</returns>
    public bool Equals(EmbeddingCapabilities? other)
    {
        return ReferenceEquals(this, other) ||
            other is not null &&
            Dimensions == other.Dimensions &&
            CapabilityValueEquality.SequenceEquals(DimensionChoices, other.DimensionChoices) &&
            MaxBatchInputs == other.MaxBatchInputs &&
            MaxInputTokens == other.MaxInputTokens &&
            MaxInputBytes == other.MaxInputBytes &&
            CapabilityValueEquality.SequenceEquals(InputIntents, other.InputIntents) &&
            Normalized == other.Normalized;
    }

    /// <summary>Returns a hash code consistent with ordered sequence equality.</summary>
    /// <returns>A hash code that is equal for embedding metadata that compares equal.</returns>
    public override int GetHashCode()
    {
        var hash = new HashCode();
        hash.Add(Dimensions);
        CapabilityValueEquality.AddSequenceHash(ref hash, DimensionChoices);
        hash.Add(MaxBatchInputs);
        hash.Add(MaxInputTokens);
        hash.Add(MaxInputBytes);
        CapabilityValueEquality.AddSequenceHash(ref hash, InputIntents);
        hash.Add(Normalized);
        return hash.ToHashCode();
    }

    /// <summary>Layers known metadata from <paramref name="other"/> over this instance.</summary>
    /// <remarks>Nonempty sequences replace prior sequences; explicit <see langword="false"/> normalization replaces <see langword="true"/>.</remarks>
    /// <param name="other">Metadata whose known values take precedence.</param>
    /// <returns>New metadata in which each value known in <paramref name="other"/> replaces this instance's value.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="other"/> is <see langword="null"/>.</exception>
    public EmbeddingCapabilities Overlay(EmbeddingCapabilities other)
    {
        ArgumentNullException.ThrowIfNull(other);
        return new EmbeddingCapabilities(
            other.Dimensions ?? Dimensions,
            other.DimensionChoices.Count != 0 ? other.DimensionChoices : DimensionChoices,
            other.MaxBatchInputs ?? MaxBatchInputs,
            other.MaxInputTokens ?? MaxInputTokens,
            other.MaxInputBytes ?? MaxInputBytes,
            other.InputIntents.Count != 0 ? other.InputIntents : InputIntents,
            other.Normalized ?? Normalized);
    }
}

/// <summary>Describes reranking metadata a model states about itself.</summary>
public sealed record RerankCapabilities
{
    /// <summary>Creates reranking capability metadata.</summary>
    /// <param name="maxDocuments">Maximum documents per request, or <see langword="null"/> when unknown.</param>
    /// <param name="maxTokensPerDocument">Maximum tokens per document, or <see langword="null"/> when unknown.</param>
    /// <param name="maxBytesPerDocument">Maximum bytes per document, or <see langword="null"/> when unknown.</param>
    /// <param name="nativeTopN">Whether the provider natively accepts a top-N limit.</param>
    public RerankCapabilities(
        int? maxDocuments = null,
        int? maxTokensPerDocument = null,
        int? maxBytesPerDocument = null,
        bool nativeTopN = false)
    {
        MaxDocuments = maxDocuments;
        MaxTokensPerDocument = maxTokensPerDocument;
        MaxBytesPerDocument = maxBytesPerDocument;
        NativeTopN = nativeTopN;
    }

    /// <summary>Gets the maximum documents per request, or <see langword="null"/> when unknown.</summary>
    public int? MaxDocuments { get; }
    /// <summary>Gets the maximum tokens per document, or <see langword="null"/> when unknown.</summary>
    public int? MaxTokensPerDocument { get; }
    /// <summary>Gets the maximum bytes per document, or <see langword="null"/> when unknown.</summary>
    public int? MaxBytesPerDocument { get; }
    /// <summary>Gets whether native top-N support is known.</summary>
    public bool NativeTopN { get; }

    /// <summary>Layers known metadata from <paramref name="other"/> over this instance.</summary>
    /// <remarks>Native top-N remains true once either side reports it.</remarks>
    /// <param name="other">Metadata whose known limits take precedence.</param>
    /// <returns>New metadata in which each limit known in <paramref name="other"/> replaces this instance's limit.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="other"/> is <see langword="null"/>.</exception>
    public RerankCapabilities Overlay(RerankCapabilities other)
    {
        ArgumentNullException.ThrowIfNull(other);
        return new RerankCapabilities(
            other.MaxDocuments ?? MaxDocuments,
            other.MaxTokensPerDocument ?? MaxTokensPerDocument,
            other.MaxBytesPerDocument ?? MaxBytesPerDocument,
            other.NativeTopN || NativeTopN);
    }
}

/// <summary>Reports a provider's cheap readiness result.</summary>
public sealed record Health
{
    /// <summary>Creates a readiness result.</summary>
    /// <param name="ok">Whether the provider answered its readiness check successfully.</param>
    /// <param name="detail">Explanation, typically of a failure; may be empty on success.</param>
    /// <exception cref="ArgumentNullException"><paramref name="detail"/> is <see langword="null"/>.</exception>
    public Health(bool ok, string detail = "")
    {
        Ok = ok;
        Detail = detail ?? throw new ArgumentNullException(nameof(detail));
    }

    /// <summary>Gets whether the provider answered its readiness check.</summary>
    public bool Ok { get; }
    /// <summary>Gets the readiness detail, which may be empty on success.</summary>
    public string Detail { get; }
}

/// <summary>Names a model returned by a provider listing and its reported facts, if any.</summary>
public sealed record DiscoveredModel
{
    /// <summary>Creates a discovered model entry.</summary>
    /// <param name="id">Model identifier exactly as the provider listing reports it.</param>
    /// <param name="capabilities">
    /// Facts the listing itself reported, normally tagged <see cref="Provenance.Discovered"/>, or
    /// <see langword="null"/> for an identifier-only listing. Never fill this with guesses.
    /// </param>
    /// <exception cref="ArgumentNullException"><paramref name="id"/> is <see langword="null"/>.</exception>
    public DiscoveredModel(string id, ModelCapabilities? capabilities = null)
    {
        Id = id ?? throw new ArgumentNullException(nameof(id));
        Capabilities = capabilities;
    }

    /// <summary>Gets the provider-listed model identifier.</summary>
    public string Id { get; }
    /// <summary>Gets only facts the listing supplied, or <see langword="null"/> for an ID-only listing.</summary>
    public ModelCapabilities? Capabilities { get; }
}
