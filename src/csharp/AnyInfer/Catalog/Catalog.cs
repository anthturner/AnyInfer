using AnyInfer.Capabilities;
using AnyInfer.Json;
using AnyInfer.Providers;
using System.Collections.Frozen;
using System.Collections.ObjectModel;
using System.Globalization;
using System.Reflection;

namespace AnyInfer.Catalog;

/// <summary>Immutable catalog metadata loaded from bundled or application JSON.</summary>
public sealed class Catalog
{
    private const int CurrentFormatVersion = 1;
    /// <summary>Gets the closed ordinal vocabulary accepted by catalog <c>best_at</c> tags.</summary>
    public static IReadOnlySet<string> BestAtCategories { get; } = new[]
    {
        "agentic", "code-completion", "coding", "drafting", "embeddings", "general-chat", "long-context", "low-resource", "math", "multilingual", "rag", "reasoning", "tool-use", "vision",
    }.ToFrozenSet(StringComparer.Ordinal);

    /// <summary>Creates an immutable catalog snapshot, copying each dictionary.</summary>
    /// <remarks>
    /// Keys are kept exactly as given. <see cref="Alias"/> and <see cref="HasAlias"/> trim and lower-case the
    /// requested name, so alias keys should be lower-case to be reachable.
    /// </remarks>
    /// <param name="aliases">Tier aliases keyed by lower-case alias name; <see langword="null"/> means none.</param>
    /// <param name="artifacts">GGUF artifacts keyed by artifact identifier; <see langword="null"/> means none.</param>
    /// <param name="models">Logical models keyed by model identifier; <see langword="null"/> means none.</param>
    /// <param name="defaultAlias">Default alias name.</param>
    /// <param name="formatVersion">Declared catalog format version; not validated here.</param>
    /// <exception cref="ArgumentNullException"><paramref name="defaultAlias"/> is <see langword="null"/>.</exception>
    public Catalog(IReadOnlyDictionary<string, AliasEntry>? aliases = null, IReadOnlyDictionary<string, GgufArtifact>? artifacts = null, IReadOnlyDictionary<string, ModelEntry>? models = null, string defaultAlias = "medium", int formatVersion = CurrentFormatVersion)
    {
        Aliases = Copy(aliases); Artifacts = Copy(artifacts); Models = Copy(models);
        DefaultAlias = defaultAlias ?? throw new ArgumentNullException(nameof(defaultAlias));
        FormatVersion = formatVersion;
    }

    /// <summary>Gets aliases keyed by lower-cased catalog names.</summary>
    public IReadOnlyDictionary<string, AliasEntry> Aliases { get; }
    /// <summary>Gets explicit and derived GGUF artifacts keyed by identifier.</summary>
    public IReadOnlyDictionary<string, GgufArtifact> Artifacts { get; }
    /// <summary>Gets logical models keyed by identifier.</summary>
    public IReadOnlyDictionary<string, ModelEntry> Models { get; }
    /// <summary>Gets the default catalog alias.</summary>
    public string DefaultAlias { get; }
    /// <summary>Gets the declared catalog format version.</summary>
    public int FormatVersion { get; }

    /// <summary>Parses a catalog JSON object in the bundled catalog format.</summary>
    /// <remarks>
    /// Alias names are lower-cased, model <c>best_at</c> tags must belong to <see cref="BestAtCategories"/>,
    /// and GGUF model variants whose source lists files (a Hugging Face repository and revision, or direct URLs)
    /// also yield derived GGUF artifacts unless an explicit artifact already uses that identifier.
    /// </remarks>
    /// <param name="data">Parsed catalog object.</param>
    /// <returns>An immutable catalog containing the parsed aliases, artifacts, and models.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="data"/> is <see langword="null"/>.</exception>
    /// <exception cref="ConfigException">The format version is unsupported or a row is malformed.</exception>
    public static Catalog FromMapping(JsonObject data)
    {
        ArgumentNullException.ThrowIfNull(data);
        return Parser.Parse(data);
    }

    /// <summary>Parses one catalog JSON document from text.</summary>
    /// <param name="json">Catalog JSON text whose root must be an object.</param>
    /// <returns>An immutable catalog parsed from <paramref name="json"/>.</returns>
    /// <exception cref="ConfigException">The text is not valid JSON, its root is not an object, or a row is malformed.</exception>
    public static Catalog Loads(string json) => ParseDocument(ReadJson(json));

    /// <summary>Loads one catalog document from disk.</summary>
    /// <param name="path">Path of a UTF-8 catalog JSON file.</param>
    /// <returns>An immutable catalog parsed from the file.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="path"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="path"/> is empty.</exception>
    /// <exception cref="ConfigException">The file cannot be read, is not valid JSON, or is not a valid catalog.</exception>
    public static Catalog Load(string path)
    {
        ArgumentException.ThrowIfNullOrEmpty(path);
        try { return ParseDocument(ReadJson(File.ReadAllBytes(path))); }
        catch (IOException error) { throw new ConfigException("Catalog file cannot be read.", detail: error.Message, nativeInner: error); }
        catch (UnauthorizedAccessException error) { throw new ConfigException("Catalog file cannot be read.", detail: error.Message, nativeInner: error); }
    }

    /// <summary>Loads catalog documents and overlays them left to right.</summary>
    /// <param name="paths">Catalog file paths; each later file overlays the earlier ones with <see cref="Overlay"/>.</param>
    /// <returns>The merged immutable catalog.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="paths"/> is <see langword="null"/>.</exception>
    /// <exception cref="ConfigException"><paramref name="paths"/> is empty, or a file cannot be read or parsed.</exception>
    public static Catalog Load(IEnumerable<string> paths)
    {
        ArgumentNullException.ThrowIfNull(paths);
        using var enumerator = paths.GetEnumerator();
        if (!enumerator.MoveNext()) throw new ConfigException("No catalog files were given.");
        var merged = Load(enumerator.Current);
        while (enumerator.MoveNext()) merged = merged.Overlay(Load(enumerator.Current));
        return merged;
    }

    /// <summary>Loads the bundled default and model catalog resources.</summary>
    /// <remarks>Each call parses the embedded resources again and returns a new snapshot.</remarks>
    /// <returns>The bundled alias catalog overlaid with the bundled model catalog.</returns>
    /// <exception cref="ConfigException">A bundled resource is missing or invalid.</exception>
    public static Catalog LoadDefault() => ReadResource("AnyInfer.Catalog.default.json").Overlay(ReadResource("AnyInfer.Catalog.models.json"));

    /// <summary>Reports whether a catalog alias exists.</summary>
    /// <param name="name">Alias name; trimmed and lower-cased before lookup.</param>
    /// <returns><see langword="true"/> when the alias exists.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="name"/> is <see langword="null"/>.</exception>
    public bool HasAlias(string name) => Aliases.ContainsKey(CatalogKey(name));

    /// <summary>Gets a catalog alias.</summary>
    /// <param name="name">Alias name; trimmed and lower-cased before lookup.</param>
    /// <returns>The alias entry.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="name"/> is <see langword="null"/>.</exception>
    /// <exception cref="ConfigException">The alias is unknown.</exception>
    public AliasEntry Alias(string name) => Aliases.TryGetValue(CatalogKey(name), out var entry) ? entry : throw new ConfigException("Catalog alias is unknown.", detail: name);

    /// <summary>Gets the targets for a catalog alias.</summary>
    /// <param name="name">Alias name; trimmed and lower-cased before lookup.</param>
    /// <returns>The alias targets keyed by catalog provider spelling.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="name"/> is <see langword="null"/>.</exception>
    /// <exception cref="ConfigException">The alias is unknown.</exception>
    public IReadOnlyDictionary<string, TargetEntry> TargetsForAlias(string name) => Alias(name).Targets;

    /// <summary>Gets a GGUF artifact.</summary>
    /// <param name="id">Exact, case-sensitive artifact identifier.</param>
    /// <returns>The artifact with that identifier.</returns>
    /// <exception cref="ConfigException">The artifact is unknown.</exception>
    public GgufArtifact Artifact(string id) => Artifacts.TryGetValue(id, out var entry) ? entry : throw new ConfigException("Catalog artifact is unknown.", detail: id);

    /// <summary>Gets a logical model.</summary>
    /// <param name="id">Exact, case-sensitive model identifier.</param>
    /// <returns>The model with that identifier.</returns>
    /// <exception cref="ConfigException">The model is unknown.</exception>
    public ModelEntry Model(string id) => Models.TryGetValue(id, out var entry) ? entry : throw new ConfigException("Catalog model is unknown.", detail: id);

    /// <summary>Gets alias names in ordinal order.</summary>
    /// <returns>A new immutable list of alias keys.</returns>
    public IReadOnlyList<string> AliasNames() => System.Array.AsReadOnly(Aliases.Keys.OrderBy(static key => key, StringComparer.Ordinal).ToArray());

    /// <summary>Filters models by optional channel, best-at category, and kind.</summary>
    /// <param name="providerId">Serving channel such as <c>llama-cpp</c>, <c>vllm</c>, or <c>ollama</c> (see <see cref="ModelEntry.Channels"/>), trimmed and lower-cased; <see langword="null"/> or empty matches every model.</param>
    /// <param name="bestAt">Best-at category, matched as by <see cref="ModelEntry.MatchesBestAt"/>; <see langword="null"/> or empty matches every model.</param>
    /// <param name="kind">Model kind, or <see langword="null"/> for every kind.</param>
    /// <returns>A new immutable list of matching models in ordinal identifier order.</returns>
    public IReadOnlyList<ModelEntry> ModelsFor(string? providerId = null, string? bestAt = null, ModelKind? kind = null)
    {
        var channel = string.IsNullOrEmpty(providerId) ? null : providerId.Trim().ToLowerInvariant();
        return System.Array.AsReadOnly(Models.Values.Where(model =>
            (channel is null || model.Channels.Contains(channel, StringComparer.Ordinal)) &&
            model.MatchesBestAt(bestAt) &&
            (kind is null || model.Kind == kind)).OrderBy(static model => model.Id, StringComparer.Ordinal).ToArray());
    }

    /// <summary>Returns a catalog with one alias target replaced by a selected model reference.</summary>
    /// <remarks>
    /// For <c>ollama</c> the target names the model's Ollama tag; for any other provider it names the model's
    /// headline GGUF artifact. The new target carries the model's context window and display name. This
    /// catalog is not changed.
    /// </remarks>
    /// <param name="alias">Existing alias name; trimmed and lower-cased.</param>
    /// <param name="providerId">Catalog provider spelling of the target to set; trimmed and lower-cased.</param>
    /// <param name="modelId">Exact identifier of a model in this catalog.</param>
    /// <returns>A new catalog in which the alias's target for <paramref name="providerId"/> refers to the model.</returns>
    /// <exception cref="ArgumentNullException">An argument is <see langword="null"/>.</exception>
    /// <exception cref="ConfigException">The alias or model is unknown, or the model has no reference for that provider.</exception>
    public Catalog WithAliasTarget(string alias, string providerId, string modelId)
    {
        var aliasKey = CatalogKey(alias);
        var providerKey = CatalogKey(providerId);
        var oldAlias = Alias(aliasKey);
        var model = Model(modelId);
        var reference = providerKey == "ollama" ? model.Ollama?.Tag : model.GgufArtifactId;
        if (string.IsNullOrEmpty(reference)) throw new ConfigException("Catalog model has no artifact for this provider.", detail: modelId);
        var targets = new Dictionary<string, TargetEntry>(oldAlias.Targets, StringComparer.Ordinal)
        {
            [providerKey] = providerKey == "ollama"
                ? new TargetEntry(providerKey, Model: reference, ContextWindow: model.ContextWindow, Description: model.Name)
                : new TargetEntry(providerKey, Gguf: reference, ContextWindow: model.ContextWindow, Description: model.Name),
        };
        var aliases = new Dictionary<string, AliasEntry>(Aliases, StringComparer.Ordinal)
        {
            [aliasKey] = new AliasEntry(oldAlias.Name, oldAlias.Description, targets, oldAlias.MinRamBytes, oldAlias.MinVramBytes),
        };
        return new Catalog(aliases, Artifacts, Models, DefaultAlias, FormatVersion);
    }

    /// <summary>Overlays aliases, artifacts, and models wholesale by key.</summary>
    /// <param name="other">Catalog whose entries replace same-keyed entries in this catalog.</param>
    /// <returns>
    /// A new catalog. Its default alias comes from <paramref name="other"/> unless that is empty, and its
    /// format version is the larger of the two.
    /// </returns>
    /// <exception cref="ArgumentNullException"><paramref name="other"/> is <see langword="null"/>.</exception>
    public Catalog Overlay(Catalog other)
    {
        ArgumentNullException.ThrowIfNull(other);
        var aliases = new Dictionary<string, AliasEntry>(Aliases, StringComparer.Ordinal); foreach (var item in other.Aliases) aliases[item.Key] = item.Value;
        var artifacts = new Dictionary<string, GgufArtifact>(Artifacts, StringComparer.Ordinal); foreach (var item in other.Artifacts) artifacts[item.Key] = item.Value;
        var models = new Dictionary<string, ModelEntry>(Models, StringComparer.Ordinal); foreach (var item in other.Models) models[item.Key] = item.Value;
        return new Catalog(aliases, artifacts, models, other.DefaultAlias.Length == 0 ? DefaultAlias : other.DefaultAlias, Math.Max(FormatVersion, other.FormatVersion));
    }

    /// <summary>Resolves a target without resolving credentials, invoking factories, or doing network I/O.</summary>
    /// <remarks>
    /// A <c>provider:model</c> target resolves its provider part to a configured instance with that identity,
    /// or else to the canonical identifier of a registered descriptor or descriptor alias. Any other target is
    /// treated as a catalog alias: the first configured instance, in <paramref name="configured"/> order, whose
    /// identity matches one of the alias's provider keys supplies the target.
    /// </remarks>
    /// <param name="target">A <c>provider:model</c> target or a catalog alias name; surrounding whitespace is ignored.</param>
    /// <param name="registry">Registry used to resolve provider identifiers and aliases.</param>
    /// <param name="configured">Configured instances, in preference order for alias resolution.</param>
    /// <returns>
    /// The resolved instance and model; for an alias, <see cref="ResolvedTarget.ViaAlias"/> holds the trimmed alias text.
    /// </returns>
    /// <exception cref="ArgumentNullException">An argument is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">The provider part of a <c>provider:model</c> target is blank.</exception>
    /// <exception cref="ConfigException">
    /// The target is empty, names no model, names an unregistered provider, names an unknown alias, or names an
    /// alias with no target among the configured instances.
    /// </exception>
    public ResolvedTarget ResolveTarget(string target, ProviderRegistry registry, IReadOnlyList<CatalogProviderBinding> configured)
    {
        ArgumentNullException.ThrowIfNull(target); ArgumentNullException.ThrowIfNull(registry); ArgumentNullException.ThrowIfNull(configured);
        var text = target.Trim();
        if (text.Length == 0) throw new ConfigException("Target is empty.");
        var separator = text.IndexOf(':');
        if (separator >= 0)
        {
            var provider = ProviderRegistry.NormalizeProviderId(text[..separator]);
            var model = text[(separator + 1)..].Trim();
            if (model.Length == 0) throw new ConfigException("Target names a provider but no model.");
            var bound = configured.FirstOrDefault(item => item.InstanceId == provider);
            return new ResolvedTarget(bound?.InstanceId ?? registry.ResolveId(provider), model);
        }
        var alias = Alias(text);
        foreach (var binding in configured)
        {
            var candidate = alias.Targets.FirstOrDefault(item => ProviderRegistry.NormalizeProviderId(item.Key) == binding.InstanceId);
            if (candidate.Value is not null) return new ResolvedTarget(binding.InstanceId, candidate.Value.ModelRef, text);
        }
        throw new ConfigException("Catalog alias has no target among configured instances.", detail: text);
    }

    private static Catalog ParseDocument(JsonValue value) => value is JsonObject root ? FromMapping(root) : throw new ConfigException("Catalog document must be a JSON object.");
    private static Catalog ReadResource(string name)
    {
        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name) ?? throw new ConfigException("Bundled catalog resource is unavailable.", detail: name);
        using var bytes = new MemoryStream(); stream.CopyTo(bytes); return ParseDocument(ReadJson(bytes.ToArray()));
    }
    private static JsonValue ReadJson(string json)
    {
        try { return JsonReader.Read(json); }
        catch (FormatException error) { throw new ConfigException("Catalog JSON is invalid.", detail: error.Message, nativeInner: error); }
    }
    private static JsonValue ReadJson(ReadOnlySpan<byte> utf8)
    {
        try { return JsonReader.Read(utf8); }
        catch (FormatException error) { throw new ConfigException("Catalog JSON is invalid.", detail: error.Message, nativeInner: error); }
    }
    private static string CatalogKey(string value) => (value ?? throw new ArgumentNullException(nameof(value))).Trim().ToLowerInvariant();
    private static IReadOnlyDictionary<string, T> Copy<T>(IReadOnlyDictionary<string, T>? values) => new ReadOnlyDictionary<string, T>(new Dictionary<string, T>(values ?? new Dictionary<string, T>(), StringComparer.Ordinal));
    internal static string PythonString(JsonValue value) => Parser.Py(value);

    private static class Parser
    {
        internal static Catalog Parse(JsonObject root)
        {
            var version = root.TryGetValue("format_version", out var versionValue) ? Version(versionValue) : CurrentFormatVersion;
            if (version > CurrentFormatVersion) throw new ConfigException("Catalog format version is unsupported.");
            var aliases = ParseAliases(OptionalObject(root, "aliases"));
            var artifacts = ParseArtifacts(OptionalObject(root, "gguf_artifacts"));
            var models = ParseModels(root);
            foreach (var model in models.Values) foreach (var variant in model.Variants)
                if (DeriveArtifact(model, variant) is { } artifact && !artifacts.ContainsKey(artifact.Id)) artifacts.Add(artifact.Id, artifact);
            var defaultAlias = root.TryGetValue("default_alias", out var defaultValue) ? Py(defaultValue) : "medium";
            return new Catalog(aliases, artifacts, models, defaultAlias, version);
        }

        private static Dictionary<string, AliasEntry> ParseAliases(JsonObject? raw)
        {
            var aliases = new Dictionary<string, AliasEntry>(StringComparer.Ordinal);
            if (raw is null) return aliases;
            foreach (var property in raw.Properties)
            {
                var name = property.Name.ToLowerInvariant();
                aliases[name] = ParseAlias(name, RequireObject(property.Value, "alias"));
            }
            return aliases;
        }

        private static AliasEntry ParseAlias(string name, JsonObject row)
        {
            var targets = new Dictionary<string, TargetEntry>(StringComparer.Ordinal);
            var rawTargets = OptionalObject(row, "targets");
            if (rawTargets is not null) foreach (var property in rawTargets.Properties)
            {
                var target = RequireObject(property.Value, "target");
                var provider = property.Name;
                targets[provider] = new TargetEntry(property.Name, OptionalString(target, "model"), OptionalString(target, "gguf"), OptionalInt(target, "context_window"), OptionalInt(target, "max_output_tokens"), Scalar(target, "description", ""));
            }
            return new AliasEntry(name, Scalar(row, "description", ""), targets, OptionalLong(row, "min_ram_bytes"), OptionalLong(row, "min_vram_bytes"));
        }

        private static Dictionary<string, GgufArtifact> ParseArtifacts(JsonObject? raw)
        {
            var artifacts = new Dictionary<string, GgufArtifact>(StringComparer.Ordinal);
            if (raw is not null) foreach (var property in raw.Properties) artifacts[property.Name] = ParseArtifact(property.Name, RequireObject(property.Value, "artifact"));
            return artifacts;
        }

        private static GgufArtifact ParseArtifact(string id, JsonObject row)
        {
            IReadOnlyList<JsonValue> rawFiles;
            if (row.TryGetValue("files", out var value) && value is JsonArray files && files.Items.Count != 0) rawFiles = files.Items;
            else rawFiles = [row];
            var entries = new List<GgufFile>();
            foreach (var raw in rawFiles)
            {
                var file = RequireObject(raw, "artifact file");
                var url = OptionalString(file, "url") ?? throw new ConfigException("Catalog artifact file has no URL.", detail: id);
                var role = Scalar(file, "role", "model");
                if (role is not ("model" or "projector")) throw new ConfigException("Catalog artifact role is unknown.", detail: role);
                entries.Add(new GgufFile(OptionalString(file, "filename") ?? url[(url.LastIndexOf('/') + 1)..], url, Scalar(file, "sha256", ""), OptionalLong(file, "size_bytes"), role));
            }
            return new GgufArtifact(id, entries, Scalar(row, "license", ""), Scalar(row, "description", ""), OptionalString(row, "parameter_size"), OptionalString(row, "quantization"), OptionalLong(row, "est_ram_bytes"), OptionalLong(row, "est_vram_bytes"), ParseEmbedding(row, "artifact"));
        }

        private static Dictionary<string, ModelEntry> ParseModels(JsonObject root)
        {
            var models = new Dictionary<string, ModelEntry>(StringComparer.Ordinal);
            if (!root.TryGetValue("models", out var raw)) return models;
            if (raw is JsonObject map)
            {
                foreach (var property in map.Properties)
                {
                    var row = RequireObject(property.Value, "model");
                    if (!row.TryGetValue("id", out _)) row = new JsonObject(new[] { new JsonProperty("id", new JsonString(property.Name)) }.Concat(row.Properties));
                    var model = ParseModel(row); models[model.Id] = model;
                }
                return models;
            }
            foreach (var item in RequireArray(raw, "models").Items) { var model = ParseModel(RequireObject(item, "model")); models[model.Id] = model; }
            return models;
        }

        private static ModelEntry ParseModel(JsonObject row)
        {
            var id = OptionalString(row, "id") ?? throw new ConfigException("Catalog model has no id.");
            var kindText = Scalar(row, "kind", "generation").Trim().ToLowerInvariant();
            var kind = kindText switch { "" or "generation" => ModelKind.Generation, "embedding" => ModelKind.Embedding, _ => throw new ConfigException("Catalog model kind is unknown.", detail: kindText) };
            var embedding = ParseEmbedding(row, $"model {id}");
            if (embedding is not null && kind != ModelKind.Embedding) throw new ConfigException("Only embedding models may carry embedding metadata.");
            var tags = OptionalArray(row, "best_at")?.Items.Select(Py).Select(static tag => tag.Trim().ToLowerInvariant()).ToArray() ?? [];
            if (tags.Any(tag => !BestAtCategories.Contains(tag))) throw new ConfigException("Catalog best_at category is unknown.");
            var variants = OptionalArray(row, "variants")?.Items.Select(item => ParseVariant(id, RequireObject(item, "variant"))).ToArray() ?? [];
            if (variants.Select(static variant => variant.Id).Distinct(StringComparer.Ordinal).Count() != variants.Length)
            {
                throw new ConfigException("Catalog model repeats a variant identifier.", detail: id);
            }
            var sources = OptionalObject(row, "sources") ?? new JsonObject([]);
            var ollama = ParseOllama(sources);
            return new ModelEntry(id, kind, Scalar(row, "family", ""), Scalar(row, "display_name", ""), OptionalString(row, "parameter_size"), OptionalString(row, "quantization"), OptionalInt(row, "context_window"), Scalar(row, "license", ""), tags, OptionalLong(row, "est_file_bytes"), OptionalLong(row, "est_ram_bytes"), OptionalLong(row, "est_vram_bytes"), Scalar(row, "last_verified", ""), Scalar(row, "source", ""), variants, ollama, embedding, Scalar(row, "description", ""));
        }

        private static ModelVariant ParseVariant(string modelId, JsonObject row)
        {
            var id = OptionalString(row, "id") ?? throw new ConfigException("Catalog variant has no id.", detail: modelId);
            var engine = Scalar(row, "engine", "llama.cpp"); if (engine is not ("llama.cpp" or "vllm")) throw new ConfigException("Catalog variant engine is unknown.", detail: engine);
            var kindText = Scalar(row, "kind", engine == "llama.cpp" ? "gguf" : "hf_repo");
            var kind = kindText switch { "gguf" => ArtifactKind.Gguf, "hf_repo" => ArtifactKind.HfRepo, _ => throw new ConfigException("Catalog artifact kind is unknown.", detail: kindText) };
            return new ModelVariant(id, engine, kind, Scalar(row, "quantization", ""), OptionalInt(row, "quality_rank") ?? 0, OptionalLong(row, "est_file_bytes"), OptionalLong(row, "est_ram_bytes"), OptionalLong(row, "est_vram_bytes"), OptionalString(row, "min_compute_capability"), ParseSource(OptionalObject(row, "source") ?? new JsonObject([])), OptionalString(row, "artifact_id"));
        }

        private static SourceRef ParseSource(JsonObject row) => new(Scalar(row, "resolver", "huggingface"), OptionalString(row, "repo"), OptionalString(row, "revision"), Strings(row, "files"), StringMap(row, "sha256"), LongMap(row, "size_bytes", true), StringMap(row, "roles"), Strings(row, "urls"), Strings(row, "include"), Strings(row, "exclude"), OptionalString(row, "path"));
        private static OllamaChannel? ParseOllama(JsonObject sources)
        {
            if (!sources.TryGetValue("ollama", out var value) || value is JsonNull) return null;
            if (value is JsonString tag && tag.Value.Length != 0) return new OllamaChannel(tag.Value);
            if (value is not JsonObject row) return null;
            return new OllamaChannel(OptionalString(row, "tag") ?? throw new ConfigException("Ollama metadata has no tag."), OptionalString(row, "digest"));
        }

        private static EmbeddingCapabilities? ParseEmbedding(JsonObject row, string where)
        {
            if (!row.TryGetValue("embedding", out var value) || value is JsonNull) return null;
            var embedding = RequireObject(value, "embedding");
            var unknown = embedding.Properties.Select(static property => property.Name).Where(name => name is not ("dimensions" or "max_input_tokens")).ToArray();
            if (unknown.Length != 0) throw new ConfigException("Catalog embedding metadata has unknown keys.", detail: string.Join(",", unknown));
            return new EmbeddingCapabilities(dimensions: OptionalInt(embedding, "dimensions"), maxInputTokens: OptionalInt(embedding, "max_input_tokens"));
        }

        private static GgufArtifact? DeriveArtifact(ModelEntry model, ModelVariant variant)
        {
            if (variant.Kind != ArtifactKind.Gguf || variant.ArtifactId is null) return null;
            var files = new List<GgufFile>(); var source = variant.Source;
            if (source.Resolver == "huggingface" && source.Repo is not null && source.Revision is not null)
                foreach (var path in source.Files) files.Add(DerivedFile(path, $"https://huggingface.co/{source.Repo}/resolve/{source.Revision}/{path}", source));
            else foreach (var url in source.Urls) { var name = url[(url.LastIndexOf('/') + 1)..]; files.Add(DerivedFile(name, url, source)); }
            if (files.Count == 0) return null;
            return new GgufArtifact(variant.ArtifactId, files, model.License, model.Name, model.ParameterSize, string.IsNullOrEmpty(variant.Quantization) ? model.Quantization : variant.Quantization, variant.EstRamBytes is 0 ? model.EstRamBytes : variant.EstRamBytes ?? model.EstRamBytes, variant.EstVramBytes is 0 ? model.EstVramBytes : variant.EstVramBytes ?? model.EstVramBytes, model.Embedding);
        }

        private static GgufFile DerivedFile(string sourceName, string url, SourceRef source)
        {
            var filename = sourceName[(sourceName.LastIndexOf('/') + 1)..];
            return new GgufFile(filename, url, source.Digests.TryGetValue(sourceName, out var digest) ? digest : "", source.Sizes.TryGetValue(sourceName, out var size) ? size : null, source.Roles.TryGetValue(sourceName, out var role) && role == "projector" ? "projector" : "model");
        }

        private static JsonObject? OptionalObject(JsonObject row, string name) => row.TryGetValue(name, out var value) ? RequireObject(value, name) : null;
        private static JsonArray? OptionalArray(JsonObject row, string name) => row.TryGetValue(name, out var value) ? RequireArray(value, name) : null;
        private static JsonObject RequireObject(JsonValue value, string what) => value as JsonObject ?? throw new ConfigException($"Catalog {what} must be an object.");
        private static JsonArray RequireArray(JsonValue value, string what) => value as JsonArray ?? throw new ConfigException($"Catalog {what} must be an array.");
        private static string? OptionalString(JsonObject row, string name) => row.TryGetValue(name, out var value) && value is JsonString text && text.Value.Length != 0 ? text.Value : null;
        private static int? OptionalInt(JsonObject row, string name) => row.TryGetValue(name, out var value) ? Integer(value, name, int.MinValue, int.MaxValue) : null;
        private static long? OptionalLong(JsonObject row, string name) => row.TryGetValue(name, out var value) ? Integer(value, name, long.MinValue, long.MaxValue) : null;
        private static T? Integer<T>(JsonValue value, string name, T minimum, T maximum) where T : struct
        {
            if (value is not JsonInteger integer) return null;
            if (integer.Value < Convert.ToInt64(minimum, CultureInfo.InvariantCulture) || integer.Value > Convert.ToInt64(maximum, CultureInfo.InvariantCulture)) throw new ConfigException("Catalog integer is outside the native range.", detail: name);
            return (T)Convert.ChangeType((long)integer.Value, typeof(T), CultureInfo.InvariantCulture);
        }
        private static int Version(JsonValue value) => value switch { JsonBoolean boolean => boolean.Value ? 1 : 0, JsonInteger integer when integer.Value >= int.MinValue && integer.Value <= int.MaxValue => (int)integer.Value, JsonInteger => throw new ConfigException("Catalog format version is outside the native range."), _ => throw new ConfigException("Catalog format version must be an integer.") };
        private static string Scalar(JsonObject row, string name, string fallback) => row.TryGetValue(name, out var value) ? Py(value) : fallback;
        internal static string Py(JsonValue value) => value switch { JsonNull => "None", JsonString text => text.Value, JsonBoolean boolean => boolean.Value ? "True" : "False", JsonInteger integer => integer.Value.ToString(CultureInfo.InvariantCulture), JsonNumber number => PythonFloat(number.Value), JsonArray array => "[" + string.Join(", ", array.Items.Select(Repr)) + "]", JsonObject obj => "{" + string.Join(", ", obj.Properties.Select(property => Repr(new JsonString(property.Name)) + ": " + Repr(property.Value))) + "}", _ => "" };
        private static string Repr(JsonValue value) => value is JsonString text ? PythonStringRepr(text.Value) : Py(value);
        private static string PythonStringRepr(string value)
        {
            var quote = value.Contains('\'') && !value.Contains('"') ? '"' : '\'';
            var result = new System.Text.StringBuilder().Append(quote);
            foreach (var rune in value.EnumerateRunes())
            {
                var scalar = rune.Value;
                if (scalar == quote || scalar == '\\') result.Append('\\').Append(rune.ToString());
                else if (scalar == '\n') result.Append("\\n");
                else if (scalar == '\r') result.Append("\\r");
                else if (scalar == '\t') result.Append("\\t");
                else if (NeedsPythonEscape(rune)) AppendPythonEscape(result, scalar);
                else result.Append(rune.ToString());
            }
            return result.Append(quote).ToString();
        }
        private static string PythonFloat(double value)
        {
            if (double.IsNegative(value) && value == 0) return "-0.0";
            var raw = value.ToString("R", CultureInfo.InvariantCulture).ToLowerInvariant();
            var negative = raw.StartsWith("-", StringComparison.Ordinal);
            if (negative) raw = raw[1..];
            var exponentIndex = raw.IndexOf('e');
            var sourceExponent = 0;
            if (exponentIndex >= 0)
            {
                sourceExponent = int.Parse(raw[(exponentIndex + 1)..], CultureInfo.InvariantCulture);
                raw = raw[..exponentIndex];
            }
            var point = raw.IndexOf('.');
            if (point < 0) point = raw.Length;
            var digits = raw.Replace(".", "", StringComparison.Ordinal);
            var leading = 0;
            while (leading < digits.Length - 1 && digits[leading] == '0') leading++;
            digits = digits[leading..];
            var decimalExponent = point - leading - 1 + sourceExponent;
            digits = digits.TrimEnd('0');
            if (digits.Length == 0) return "0.0";
            var sign = negative ? "-" : "";
            if (decimalExponent < -4 || decimalExponent >= 16)
            {
                var magnitude = Math.Abs(decimalExponent).ToString(CultureInfo.InvariantCulture).PadLeft(2, '0');
                return sign + digits[0] + (digits.Length == 1 ? "" : "." + digits[1..]) + "e" + (decimalExponent < 0 ? "-" : "+") + magnitude;
            }
            if (decimalExponent >= 0)
            {
                var before = decimalExponent + 1;
                return sign + (digits.Length <= before ? digits.PadRight(before, '0') + ".0" : digits[..before] + "." + digits[before..]);
            }
            return sign + "0." + new string('0', -decimalExponent - 1) + digits;
        }
        private static bool NeedsPythonEscape(System.Text.Rune rune) =>
            rune.Value != 0x20 &&
            System.Text.Rune.GetUnicodeCategory(rune) is
                UnicodeCategory.Control or
                UnicodeCategory.Format or
                UnicodeCategory.LineSeparator or
                UnicodeCategory.ParagraphSeparator or
                UnicodeCategory.SpaceSeparator or
                UnicodeCategory.PrivateUse or
                UnicodeCategory.OtherNotAssigned;
        private static void AppendPythonEscape(System.Text.StringBuilder result, int scalar)
        {
            if (scalar <= 0xff) result.Append("\\x").Append(scalar.ToString("x2", CultureInfo.InvariantCulture));
            else if (scalar <= 0xffff) result.Append("\\u").Append(scalar.ToString("x4", CultureInfo.InvariantCulture));
            else result.Append("\\U").Append(scalar.ToString("x8", CultureInfo.InvariantCulture));
        }
        private static IReadOnlyList<string> Strings(JsonObject row, string name) => row.TryGetValue(name, out var value) && value is JsonArray array ? System.Array.AsReadOnly(array.Items.Select(Py).Where(static item => item.Length != 0).ToArray()) : System.Array.Empty<string>();
        private static IReadOnlyDictionary<string, string> StringMap(JsonObject row, string name)
        {
            if (!row.TryGetValue(name, out var value)) return new ReadOnlyDictionary<string, string>(new Dictionary<string, string>(StringComparer.Ordinal));
            var map = RequireObject(value, name);
            return new ReadOnlyDictionary<string, string>(map.Properties.ToDictionary(static property => property.Name, static property => Py(property.Value), StringComparer.Ordinal));
        }
        private static IReadOnlyDictionary<string, long> LongMap(JsonObject row, string name, bool acceptBoolean) { var map = new Dictionary<string, long>(StringComparer.Ordinal); if (!row.TryGetValue(name, out var value)) return new ReadOnlyDictionary<string, long>(map); foreach (var property in RequireObject(value, name).Properties) { if (property.Value is JsonInteger integer) { if (integer.Value < long.MinValue || integer.Value > long.MaxValue) throw new ConfigException("Catalog source size is outside the native range."); map[property.Name] = (long)integer.Value; } else if (acceptBoolean && property.Value is JsonBoolean boolean) map[property.Name] = boolean.Value ? 1 : 0; } return new ReadOnlyDictionary<string, long>(map); }
    }
}
