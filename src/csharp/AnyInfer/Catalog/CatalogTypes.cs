using AnyInfer.Capabilities;
using System.Collections.ObjectModel;
using System.Globalization;

namespace AnyInfer.Catalog;

/// <summary>Identifies the declared source kind for one model variant.</summary>
public enum ArtifactKind
{
    /// <summary>A llama.cpp GGUF file set.</summary>
    Gguf,
    /// <summary>A repository snapshot for a compatible local engine.</summary>
    HfRepo,
}

/// <summary>Identifies whether a catalog model generates text or embeddings.</summary>
public enum ModelKind
{
    /// <summary>A text or structured generation model.</summary>
    Generation,
    /// <summary>An embedding model.</summary>
    Embedding,
}

/// <summary>Declares one remote or local artifact source without performing resolution.</summary>
public sealed record SourceRef
{
    /// <summary>Creates immutable source metadata.</summary>
    public SourceRef(
        string resolver = "huggingface",
        string? repo = null,
        string? revision = null,
        IEnumerable<string>? files = null,
        IReadOnlyDictionary<string, string>? digests = null,
        IReadOnlyDictionary<string, long>? sizes = null,
        IReadOnlyDictionary<string, string>? roles = null,
        IEnumerable<string>? urls = null,
        IEnumerable<string>? include = null,
        IEnumerable<string>? exclude = null,
        string? path = null)
    {
        Resolver = resolver ?? throw new ArgumentNullException(nameof(resolver));
        Repo = repo;
        Revision = revision;
        Files = Copy(files);
        Digests = Copy(digests);
        Sizes = Copy(sizes);
        Roles = Copy(roles);
        Urls = Copy(urls);
        Include = Copy(include);
        Exclude = Copy(exclude);
        Path = path;
    }

    /// <summary>Gets the source resolver identifier; this metadata type never invokes it.</summary>
    public string Resolver { get; }
    /// <summary>Gets the repository identifier, when the resolver uses one.</summary>
    public string? Repo { get; }
    /// <summary>Gets the pinned source revision, when known.</summary>
    public string? Revision { get; }
    /// <summary>Gets immutable source-relative file names.</summary>
    public IReadOnlyList<string> Files { get; }
    /// <summary>Gets immutable file digest facts keyed by source-relative name.</summary>
    public IReadOnlyDictionary<string, string> Digests { get; }
    /// <summary>Gets immutable file-size facts in bytes keyed by source-relative name.</summary>
    public IReadOnlyDictionary<string, long> Sizes { get; }
    /// <summary>Gets immutable file roles keyed by source-relative name.</summary>
    public IReadOnlyDictionary<string, string> Roles { get; }
    /// <summary>Gets immutable direct source URLs.</summary>
    public IReadOnlyList<string> Urls { get; }
    /// <summary>Gets repository include patterns.</summary>
    public IReadOnlyList<string> Include { get; }
    /// <summary>Gets repository exclusion patterns.</summary>
    public IReadOnlyList<string> Exclude { get; }
    /// <summary>Gets a local path reference, when the resolver accepts one.</summary>
    public string? Path { get; }

    private static IReadOnlyList<string> Copy(IEnumerable<string>? values) =>
        Array.AsReadOnly((values ?? []).Select(static value => value ?? throw new ArgumentException("Source values cannot be null.")).ToArray());

    private static IReadOnlyDictionary<string, TValue> Copy<TValue>(IReadOnlyDictionary<string, TValue>? values) =>
        new ReadOnlyDictionary<string, TValue>(new Dictionary<string, TValue>(values ?? new Dictionary<string, TValue>(), StringComparer.Ordinal));
}

/// <summary>Describes one named file in a pinned GGUF artifact.</summary>
public sealed record GgufFile(string Filename, string Url, string Sha256 = "", long? SizeBytes = null, string Role = "model");

/// <summary>Describes a verifiable local GGUF artifact without acquiring it.</summary>
public sealed record GgufArtifact
{
    /// <summary>Creates an immutable artifact and validates its file ordering.</summary>
    public GgufArtifact(
        string id,
        IEnumerable<GgufFile> files,
        string license = "",
        string description = "",
        string? parameterSize = null,
        string? quantization = null,
        long? estRamBytes = null,
        long? estVramBytes = null,
        EmbeddingCapabilities? embedding = null)
    {
        Id = id ?? throw new ArgumentNullException(nameof(id));
        Files = Array.AsReadOnly(files?.ToArray() ?? throw new ArgumentNullException(nameof(files)));
        if (Files.Count == 0 || Files[0].Role != "model")
        {
            throw new ArgumentException("A GGUF artifact must begin with a model file.", nameof(files));
        }
        if (Files.Count(static file => file.Role == "projector") > 1)
        {
            throw new ArgumentException("A GGUF artifact may contain at most one projector.", nameof(files));
        }
        License = license ?? throw new ArgumentNullException(nameof(license));
        Description = description ?? throw new ArgumentNullException(nameof(description));
        ParameterSize = parameterSize;
        Quantization = quantization;
        EstRamBytes = estRamBytes;
        EstVramBytes = estVramBytes;
        Embedding = embedding;
    }

    /// <summary>Gets the stable artifact identifier.</summary>
    public string Id { get; }
    /// <summary>Gets the ordered artifact files.</summary>
    public IReadOnlyList<GgufFile> Files { get; }
    /// <summary>Gets the declared license identifier.</summary>
    public string License { get; }
    /// <summary>Gets the display description.</summary>
    public string Description { get; }
    /// <summary>Gets the declared parameter size, or <see langword="null"/> when unknown.</summary>
    public string? ParameterSize { get; }
    /// <summary>Gets the declared quantization, or <see langword="null"/> when unknown.</summary>
    public string? Quantization { get; }
    /// <summary>Gets estimated CPU memory in bytes, or <see langword="null"/> when unknown.</summary>
    public long? EstRamBytes { get; }
    /// <summary>Gets estimated accelerator memory in bytes, or <see langword="null"/> when unknown.</summary>
    public long? EstVramBytes { get; }
    /// <summary>Gets embedding facts, or <see langword="null"/> for generation artifacts.</summary>
    public EmbeddingCapabilities? Embedding { get; }
    /// <summary>Gets total known bytes, or <see langword="null"/> when any file size is unknown.</summary>
    public long? TotalSizeBytes => Files.Any(static file => file.SizeBytes is null) ? null : Files.Sum(static file => file.SizeBytes!.Value);
    /// <summary>Gets whether more than one model shard is present.</summary>
    public bool IsSharded => Files.Count(static file => file.Role == "model") > 1;
    /// <summary>Gets the optional multimodal projector file.</summary>
    public GgufFile? Projector => Files.FirstOrDefault(static file => file.Role == "projector");
}

/// <summary>Describes one provider realization of a tier alias.</summary>
public sealed record TargetEntry(string ProviderId, string? Model = null, string? Gguf = null, int? ContextWindow = null, int? MaxOutputTokens = null, string Description = "")
{
    /// <summary>Gets the model reference, preferring an explicit model over a GGUF artifact.</summary>
    public string ModelRef => !string.IsNullOrEmpty(Model) ? Model : !string.IsNullOrEmpty(Gguf) ? Gguf : throw new ConfigException($"Catalog target for provider '{ProviderId}' has neither model nor gguf.");
}

/// <summary>Describes a tier alias and its provider targets.</summary>
public sealed record AliasEntry
{
    /// <summary>Creates an immutable alias entry.</summary>
    public AliasEntry(string name, string description = "", IReadOnlyDictionary<string, TargetEntry>? targets = null, long? minRamBytes = null, long? minVramBytes = null)
    {
        Name = name ?? throw new ArgumentNullException(nameof(name));
        Description = description ?? throw new ArgumentNullException(nameof(description));
        Targets = new ReadOnlyDictionary<string, TargetEntry>(new Dictionary<string, TargetEntry>(targets ?? new Dictionary<string, TargetEntry>(), StringComparer.Ordinal));
        MinRamBytes = minRamBytes;
        MinVramBytes = minVramBytes;
    }
    /// <summary>Gets the lower-case catalog alias name.</summary>
    public string Name { get; }
    /// <summary>Gets the display description.</summary>
    public string Description { get; }
    /// <summary>Gets immutable targets keyed by catalog provider spelling.</summary>
    public IReadOnlyDictionary<string, TargetEntry> Targets { get; }
    /// <summary>Gets the minimum system memory in bytes, or <see langword="null"/> when unknown.</summary>
    public long? MinRamBytes { get; }
    /// <summary>Gets the minimum accelerator memory in bytes, or <see langword="null"/> when unknown.</summary>
    public long? MinVramBytes { get; }
}

/// <summary>Describes an Ollama registry channel for a logical model.</summary>
public sealed record OllamaChannel(string Tag, string? Digest = null);

/// <summary>Describes one engine and quantization variant of a logical model.</summary>
public sealed record ModelVariant
{
    /// <summary>Creates immutable model-variant metadata.</summary>
    public ModelVariant(string id, string engine = "llama.cpp", ArtifactKind kind = ArtifactKind.Gguf, string quantization = "", int qualityRank = 0, long? estFileBytes = null, long? estRamBytes = null, long? estVramBytes = null, string? minComputeCapability = null, SourceRef? source = null, string? artifactId = null)
    {
        Id = id ?? throw new ArgumentNullException(nameof(id));
        Engine = engine ?? throw new ArgumentNullException(nameof(engine));
        Kind = kind;
        Quantization = quantization ?? throw new ArgumentNullException(nameof(quantization));
        QualityRank = qualityRank;
        EstFileBytes = estFileBytes;
        EstRamBytes = estRamBytes;
        EstVramBytes = estVramBytes;
        MinComputeCapability = minComputeCapability;
        Source = source ?? new SourceRef();
        ArtifactId = artifactId ?? (kind == ArtifactKind.Gguf ? id : null);
    }
    /// <summary>Gets the stable variant identifier.</summary>
    public string Id { get; }
    /// <summary>Gets the serving engine spelling.</summary>
    public string Engine { get; }
    /// <summary>Gets the source artifact kind.</summary>
    public ArtifactKind Kind { get; }
    /// <summary>Gets the declared quantization.</summary>
    public string Quantization { get; }
    /// <summary>Gets the relative quality rank.</summary>
    public int QualityRank { get; }
    /// <summary>Gets estimated downloaded bytes, or <see langword="null"/> when unknown.</summary>
    public long? EstFileBytes { get; }
    /// <summary>Gets estimated system memory bytes, or <see langword="null"/> when unknown.</summary>
    public long? EstRamBytes { get; }
    /// <summary>Gets estimated accelerator memory bytes, or <see langword="null"/> when unknown.</summary>
    public long? EstVramBytes { get; }
    /// <summary>Gets the minimum compute capability, or <see langword="null"/> when unknown.</summary>
    public string? MinComputeCapability { get; }
    /// <summary>Gets pure source metadata, defaulting to a Hugging Face reference.</summary>
    public SourceRef Source { get; }
    /// <summary>Gets the GGUF artifact identifier, defaulted from the variant ID for GGUF rows.</summary>
    public string? ArtifactId { get; }
    /// <summary>Gets whether the declared source contains the pins required by its resolver shape.</summary>
    public bool IsPinned => Source.Resolver == "huggingface"
        ? !string.IsNullOrEmpty(Source.Revision) && Source.Revision.Length >= 40 && (Source.Files.Count == 0 || Source.Files.All(name => Source.Digests.ContainsKey(name)))
        : Source.Urls.Count != 0 && Source.Urls.All(url => Source.Digests.TryGetValue(url[(url.LastIndexOf('/') + 1)..], out var digest) && !string.IsNullOrEmpty(digest));
}

/// <summary>Describes one logical model a caller can browse or select.</summary>
public sealed record ModelEntry
{
    /// <summary>Creates immutable logical-model metadata.</summary>
    public ModelEntry(string id, ModelKind kind = ModelKind.Generation, string family = "", string displayName = "", string? parameterSize = null, string? quantization = null, int? contextWindow = null, string license = "", IEnumerable<string>? bestAt = null, long? estFileBytes = null, long? estRamBytes = null, long? estVramBytes = null, string lastVerified = "", string source = "", IEnumerable<ModelVariant>? variants = null, OllamaChannel? ollama = null, EmbeddingCapabilities? embedding = null, string description = "")
    {
        Id = id ?? throw new ArgumentNullException(nameof(id)); Kind = kind; Family = family ?? throw new ArgumentNullException(nameof(family)); DisplayName = displayName ?? throw new ArgumentNullException(nameof(displayName)); ParameterSize = parameterSize; Quantization = quantization; ContextWindow = contextWindow; License = license ?? throw new ArgumentNullException(nameof(license)); BestAt = Array.AsReadOnly((bestAt ?? []).ToArray()); EstFileBytes = estFileBytes; EstRamBytes = estRamBytes; EstVramBytes = estVramBytes; LastVerified = lastVerified ?? throw new ArgumentNullException(nameof(lastVerified)); Source = source ?? throw new ArgumentNullException(nameof(source)); Variants = Array.AsReadOnly((variants ?? []).ToArray()); Ollama = ollama; Embedding = embedding; Description = description ?? throw new ArgumentNullException(nameof(description));
    }
    /// <summary>Gets the stable model identifier.</summary>
    public string Id { get; }
    /// <summary>Gets whether this model is generation or embedding oriented.</summary>
    public ModelKind Kind { get; }
    /// <summary>Gets the model family label.</summary>
    public string Family { get; }
    /// <summary>Gets the stored display-name value.</summary>
    public string DisplayName { get; }
    /// <summary>Gets the parameter-size label, or <see langword="null"/> when unknown.</summary>
    public string? ParameterSize { get; }
    /// <summary>Gets the headline quantization, or <see langword="null"/> when unknown.</summary>
    public string? Quantization { get; }
    /// <summary>Gets native context tokens, or <see langword="null"/> when unknown.</summary>
    public int? ContextWindow { get; }
    /// <summary>Gets the declared license identifier.</summary>
    public string License { get; }
    /// <summary>Gets immutable best-at categories in source order.</summary>
    public IReadOnlyList<string> BestAt { get; }
    /// <summary>Gets estimated download bytes, or <see langword="null"/> when unknown.</summary>
    public long? EstFileBytes { get; }
    /// <summary>Gets estimated system memory bytes, or <see langword="null"/> when unknown.</summary>
    public long? EstRamBytes { get; }
    /// <summary>Gets estimated accelerator memory bytes, or <see langword="null"/> when unknown.</summary>
    public long? EstVramBytes { get; }
    /// <summary>Gets the upstream verification date text.</summary>
    public string LastVerified { get; }
    /// <summary>Gets the upstream source reference text.</summary>
    public string Source { get; }
    /// <summary>Gets immutable variants in source order.</summary>
    public IReadOnlyList<ModelVariant> Variants { get; }
    /// <summary>Gets the optional Ollama channel.</summary>
    public OllamaChannel? Ollama { get; }
    /// <summary>Gets optional embedding metadata.</summary>
    public EmbeddingCapabilities? Embedding { get; }
    /// <summary>Gets the display description.</summary>
    public string Description { get; }
    /// <summary>Gets the display name, falling back to the stable identifier.</summary>
    public string Name => string.IsNullOrEmpty(DisplayName) ? Id : DisplayName;
    /// <summary>Gets whether this row describes an embedding model.</summary>
    public bool IsEmbedding => Kind == ModelKind.Embedding;
    /// <summary>Gets serving channels in ordinal order.</summary>
    public IReadOnlyList<string> Channels => Array.AsReadOnly((Variants.Where(static variant => variant.Engine is "llama.cpp" or "vllm").Select(static variant => variant.Engine == "llama.cpp" ? "llama-cpp" : "vllm").Append(Ollama is null ? null : "ollama").Where(static value => value is not null).Cast<string>().Distinct(StringComparer.Ordinal).OrderBy(static value => value, StringComparer.Ordinal).ToArray()));
    /// <summary>Gets the headline GGUF artifact identifier, or <see langword="null"/> when no GGUF variant exists.</summary>
    public string? GgufArtifactId
    {
        get
        {
            var gguf = Variants.Where(static variant => variant.Kind == ArtifactKind.Gguf && variant.ArtifactId is not null).ToArray();
            var headline = gguf.FirstOrDefault(variant => string.Equals(variant.Quantization, Quantization, StringComparison.OrdinalIgnoreCase));
            return headline?.ArtifactId ?? gguf.OrderByDescending(static variant => variant.QualityRank).FirstOrDefault()?.ArtifactId;
        }
    }
    /// <summary>Gets variants for an optional engine, sorted by descending quality then identifier.</summary>
    public IReadOnlyList<ModelVariant> VariantsFor(string? engine = null) => Array.AsReadOnly(Variants.Where(variant => engine is null || variant.Engine == engine).OrderByDescending(static variant => variant.QualityRank).ThenBy(static variant => variant.Id, StringComparer.Ordinal).ToArray());
    /// <summary>Gets one variant or raises a configuration error when it is absent.</summary>
    public ModelVariant Variant(string variantId) => Variants.FirstOrDefault(variant => variant.Id == variantId) ?? throw new ConfigException($"Model '{Id}' has no variant '{variantId}'.");
    /// <summary>Gets whether this model carries an optional best-at category.</summary>
    public bool MatchesBestAt(string? category) => string.IsNullOrEmpty(category) || BestAt.Contains(category.Trim().ToLowerInvariant(), StringComparer.Ordinal);
}

/// <summary>Captures one configured provider instance for pure catalog resolution.</summary>
public sealed record CatalogProviderBinding
{
    /// <summary>Creates an immutable configured-instance binding.</summary>
    public CatalogProviderBinding(string instanceId, string providerId)
    {
        InstanceId = ProviderSettings.NormalizeId(instanceId, nameof(instanceId));
        ProviderId = ProviderSettings.NormalizeId(providerId, nameof(providerId));
    }
    /// <summary>Gets the normalized configured instance identity.</summary>
    public string InstanceId { get; }
    /// <summary>Gets the normalized descriptor provider identity.</summary>
    public string ProviderId { get; }
}
