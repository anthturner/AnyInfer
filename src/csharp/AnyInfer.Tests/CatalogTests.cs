using AnyInfer.Catalog;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

using Catalog = global::AnyInfer.Catalog.Catalog;

/// <summary>Public CAT.2 catalog parsing, immutable metadata, overlay, and pure target-resolution controls.</summary>
public sealed class CatalogTests
{
    [Fact]
    public void Shared_input_parses_python_scalar_compatibility_and_derives_artifacts_without_acquisition()
    {
        var document = Fixture();
        var catalog = Catalog.FromMapping(ObjectProperty(document, "base"));

        Assert.Equal(1, catalog.FormatVersion);
        Assert.Equal("tier", catalog.DefaultAlias);
        var tier = catalog.Alias(" TIER ");
        var primary = tier.Targets["primary"];
        Assert.Equal("primary:stable", primary.ModelRef);
        Assert.Equal(0, primary.ContextWindow);
        Assert.Equal(0, primary.MaxOutputTokens);
        Assert.Equal("True", primary.Description);
        Assert.Equal("backup:stable", tier.Targets["backup"].ModelRef);
        Assert.Equal("explicit-artifact", tier.Targets["local"].ModelRef);

        var chat = catalog.Model("chat-alpha");
        Assert.Equal("False", chat.DisplayName);
        Assert.Equal("False", chat.Name);
        Assert.Equal("True", chat.Source);
        Assert.Equal("None", chat.LastVerified);
        Assert.Equal("coding", Assert.Single(chat.BestAt));
        var vector = catalog.Model("vector-beta");
        Assert.True(vector.IsEmbedding);
        Assert.Equal(0, vector.Embedding!.Dimensions);
        Assert.Equal(2048, vector.Embedding.MaxInputTokens);

        var variant = catalog.Model("artifact-model").Variant("hf-gguf");
        Assert.Equal(1, variant.Source.Sizes["vision/projector.gguf"]);
        var explicitArtifact = catalog.Artifact("derived-hf");
        Assert.Equal("authoritative.gguf", Assert.Single(explicitArtifact.Files).Filename);
        Assert.Equal(99, explicitArtifact.TotalSizeBytes);
        var derivedUrl = catalog.Artifact("derived-url");
        Assert.Equal(4567, derivedUrl.TotalSizeBytes);
        Assert.Equal("url-model.gguf", Assert.Single(derivedUrl.Files).Filename);
    }

    [Fact]
    public void Catalog_overlay_replaces_matching_rows_wholesale_and_filters_models_deterministically()
    {
        var input = Fixture();
        var baseCatalog = Catalog.FromMapping(ObjectProperty(input, "base"));
        var overlay = Catalog.FromMapping(ObjectProperty(input, "overlay"));
        var merged = baseCatalog.Overlay(overlay);

        Assert.Equal("overlay-tier", merged.DefaultAlias);
        Assert.Equal(["primary"], merged.Alias("tier").Targets.Keys);
        Assert.Equal("overlay-primary", merged.Alias("tier").Targets["primary"].ModelRef);
        Assert.Equal(22, merged.Artifact("explicit-artifact").TotalSizeBytes);
        Assert.Equal("Overlay Chat", merged.Model("chat-alpha").DisplayName);
        Assert.Equal(["general-chat"], merged.Model("chat-alpha").BestAt);
        Assert.Empty(merged.Model("chat-alpha").Variants);
        Assert.Equal(["vector-beta"], baseCatalog.ModelsFor(bestAt: " embeddings ").Select(static model => model.Id));
        Assert.Equal(["vector-beta"], baseCatalog.ModelsFor(kind: ModelKind.Embedding).Select(static model => model.Id));
        Assert.Equal(["artifact-model"], baseCatalog.ModelsFor(providerId: "llama-cpp").Select(static model => model.Id));
    }

    [Fact]
    public void Catalog_snapshots_and_bundled_resources_are_immutable_and_not_checkout_dependent()
    {
        var aliases = new Dictionary<string, AliasEntry>
        {
            ["small"] = new AliasEntry("small", targets: new Dictionary<string, TargetEntry> { ["primary"] = new TargetEntry("primary", "m") }),
        };
        var catalog = new Catalog(aliases: aliases);
        aliases.Clear();

        Assert.True(catalog.HasAlias("small"));
        Assert.False(catalog.Aliases is IDictionary<string, AliasEntry> mutable && TryMutate(mutable));
        Assert.Equal(["small"], catalog.AliasNames());

        var resources = typeof(Catalog).Assembly.GetManifestResourceNames();
        Assert.Contains("AnyInfer.Catalog.default.json", resources);
        Assert.Contains("AnyInfer.Catalog.models.json", resources);
        var bundled = Catalog.LoadDefault();
        Assert.NotEmpty(bundled.Aliases);
        Assert.NotEmpty(bundled.Models);
        var deepseek = bundled.Model("deepseek-r1-distill-llama-70b");
        Assert.NotNull(deepseek.Ollama);
        Assert.Equal("deepseek-r1:70b", deepseek.Ollama!.Tag);
        Assert.Equal("sha256:5e9a45d7d8b98eb61a65815d36008bfef6fd6ebad6f0be432fb61d83b70550f8", deepseek.Ollama.Digest);
    }

    [Fact]
    public void Shared_invalid_documents_reject_closed_embedding_and_unknown_model_kind()
    {
        var invalid = ObjectProperty(Fixture(), "invalid_documents");
        Assert.Throws<ConfigException>(() => Catalog.FromMapping(ObjectProperty(invalid, "closed_embedding")));
        Assert.Throws<ConfigException>(() => Catalog.FromMapping(ObjectProperty(invalid, "unknown_kind")));
        Assert.Throws<ConfigException>(() => Catalog.FromMapping(ObjectProperty(invalid, "duplicate_variant_ids")));
    }

    [Fact]
    public void Shared_boundary_documents_distinguish_omitted_defaults_from_present_null_and_empty_load_refuses()
    {
        var boundaries = ObjectProperty(Fixture(), "boundary_documents");
        var omitted = Catalog.FromMapping(ObjectProperty(boundaries, "omitted_collections_and_version"));
        Assert.Equal(1, omitted.FormatVersion);
        Assert.Empty(omitted.Aliases);
        Assert.Empty(omitted.Models);
        Assert.Empty(omitted.Artifacts);
        Assert.Throws<ConfigException>(() => Catalog.Load(Array.Empty<string>()));
        Assert.Throws<ConfigException>(() => Catalog.FromMapping(ObjectProperty(boundaries, "null_aliases")));
        Assert.Throws<ConfigException>(() => Catalog.FromMapping(ObjectProperty(boundaries, "null_models")));
        Assert.Throws<ConfigException>(() => Catalog.FromMapping(ObjectProperty(boundaries, "null_version")));

        var omittedLists = Catalog.FromMapping(ObjectProperty(boundaries, "omitted_best_at"));
        Assert.Empty(omittedLists.Model("omitted-best-at").BestAt);
        Assert.Empty(Catalog.FromMapping(ObjectProperty(boundaries, "omitted_variants_and_sources")).Model("omitted-variants-and-sources").Variants);
        Assert.NotNull(Catalog.FromMapping(ObjectProperty(boundaries, "omitted_variant_source")).Model("omitted-variant-source").Variant("omitted-source-variant").Source);
        Assert.Throws<ConfigException>(() => Catalog.FromMapping(ObjectProperty(boundaries, "null_best_at")));
        Assert.Throws<ConfigException>(() => Catalog.FromMapping(ObjectProperty(boundaries, "null_variants")));
        Assert.Throws<ConfigException>(() => Catalog.FromMapping(ObjectProperty(boundaries, "null_sources")));
        Assert.Throws<ConfigException>(() => Catalog.FromMapping(ObjectProperty(boundaries, "null_variant_source")));
    }

    [Fact]
    public void Shared_scalar_document_uses_exact_representable_python_string_coercions()
    {
        var scalar = Catalog.FromMapping(ObjectProperty(ObjectProperty(Fixture(), "scalar_documents"), "python_string_coercion"));
        var model = scalar.Model("scalar-coercion");

        Assert.Equal("1e+16", model.Family);
        Assert.Equal("['quote\"', 'line\\nbreak', None, True, False]", model.DisplayName);
        Assert.Equal("{'quote': '\"', 'newline': 'x\\ny', 'none': None, 'true': True, 'false': False}", model.License);
        Assert.Equal("1000.0", model.LastVerified);
        Assert.Equal("1e-05", model.Source);
        Assert.Equal("-0.0", model.Description);
        Assert.Equal("None", scalar.Model("null-scalar-coercion").Family);
    }

    [Fact]
    public void Catalog_scalar_coercion_keeps_direct_strings_distinct_from_nested_python_repr_and_finite_float_boundaries()
    {
        var catalog = Catalog.Loads("""
        {
          "models": [{
            "id": "scalar-boundaries",
            "family": 1.2345678901234567e20,
            "display_name": 2.2250738585072014e-308,
            "license": ["\b", "\f", "\u000b", "\u0085", "\u00a0", "\u2028", "\u200d", "😀"],
            "description": "\u2028😀"
          }]
        }
        """);

        var model = catalog.Model("scalar-boundaries");
        Assert.Equal("1.2345678901234567e+20", model.Family);
        Assert.Equal("2.2250738585072014e-308", model.DisplayName);
        Assert.Equal("['\\x08', '\\x0c', '\\x0b', '\\x85', '\\xa0', '\\u2028', '\\u200d', '😀']", model.License);
        Assert.Equal("\u2028😀", model.Description);
    }

    [Fact]
    public void Catalog_load_entrypoints_wrap_malformed_utf8_and_text_with_the_native_format_cause()
    {
        var path = Path.Combine(Path.GetTempPath(), $"anyinfer-catalog-{Guid.NewGuid():N}.json");
        try
        {
            File.WriteAllBytes(path, [0x7B, 0xFF, 0x7D]);
            Assert.IsType<FormatException>(Assert.Throws<ConfigException>(() => Catalog.Load(path)).NativeInner);

            File.WriteAllText(path, "{");
            Assert.IsType<FormatException>(Assert.Throws<ConfigException>(() => Catalog.Load(path)).NativeInner);
        }
        finally
        {
            File.Delete(path);
        }

        Assert.IsType<FormatException>(Assert.Throws<ConfigException>(() => Catalog.Loads("{")).NativeInner);
        Assert.IsType<FormatException>(Assert.Throws<ConfigException>(() => Catalog.Loads("{\"models\":[\"\uD800\"]}")).NativeInner);
    }

    [Fact]
    public void Direct_url_variant_requires_nonempty_digest_value_to_be_pinned()
    {
        var sourceUrl = "https://example.invalid/weights.gguf";
        var empty = new ModelVariant("empty", source: new SourceRef(resolver: "url", urls: [sourceUrl], digests: new Dictionary<string, string> { ["weights.gguf"] = "" }));
        var pinned = new ModelVariant("pinned", source: new SourceRef(resolver: "url", urls: [sourceUrl], digests: new Dictionary<string, string> { ["weights.gguf"] = "sha256:verified" }));

        Assert.False(empty.IsPinned);
        Assert.True(pinned.IsPinned);
    }

    [Fact]
    public void Catalog_ollama_source_forms_ignore_scalar_absence_but_require_tag_for_mappings()
    {
        var absent = Catalog.Loads("""{ "models": [{ "id": "empty", "sources": { "ollama": "" } }, { "id": "false", "sources": { "ollama": false } }] }""");
        Assert.Null(absent.Model("empty").Ollama);
        Assert.Null(absent.Model("false").Ollama);

        var channels = Catalog.Loads("""{ "models": [{ "id": "string", "sources": { "ollama": "channel-tag" } }, { "id": "mapping", "sources": { "ollama": { "tag": "mapping-tag", "digest": "sha256:pinned" } } }] }""");
        Assert.Equal("channel-tag", channels.Model("string").Ollama!.Tag);
        Assert.Null(channels.Model("string").Ollama!.Digest);
        Assert.Equal("mapping-tag", channels.Model("mapping").Ollama!.Tag);
        Assert.Equal("sha256:pinned", channels.Model("mapping").Ollama!.Digest);
        Assert.Throws<ConfigException>(() => Catalog.Loads("""{ "models": [{ "id": "missing-tag", "sources": { "ollama": {} } }] }"""));
    }

    [Fact]
    public void Catalog_preserves_raw_target_identity_but_normalizes_catalog_alias_and_resolution_matching()
    {
        var fixture = Fixture();
        var aliases = ObjectProperty(fixture, "alias_documents");
        var catalog = Catalog.FromMapping(ObjectProperty(aliases, "underscore_alias"));
        var configuredIds = ArrayProperty(aliases, "configured_instance_ids").Items
            .Select(item => Assert.IsType<JsonString>(item).Value)
            .ToArray();
        var registry = new ProviderRegistry([Descriptor("openai-compat", new FactoryCounter())]);
        var configured = configuredIds.Select(id => new CatalogProviderBinding(id, "openai-compat")).ToArray();

        Assert.True(catalog.HasAlias("TIER_NAME"));
        var targets = catalog.TargetsForAlias("tier_name");
        Assert.True(targets.ContainsKey("Raw_Key"));
        Assert.Equal("Raw_Key", targets["Raw_Key"].ProviderId);
        var resolved = catalog.ResolveTarget("Tier_Name", registry, configured);
        Assert.Equal("raw-key", resolved.ProviderId);
        Assert.Equal("raw-key-model", resolved.Model);
        Assert.Equal("Tier_Name", resolved.ViaAlias);

        var spaced = Catalog.Loads("""{"aliases":{" Tier ":{"targets":{}}}}""");
        Assert.Equal([" tier "], spaced.AliasNames());
        Assert.False(spaced.HasAlias(" Tier "));
    }

    [Fact]
    public void With_alias_target_records_non_ollama_artifacts_in_gguf_not_model()
    {
        var catalog = Catalog.FromMapping(ObjectProperty(Fixture(), "base"));
        var updated = catalog.WithAliasTarget("tier", "llama-cpp", "artifact-model");
        var target = updated.TargetsForAlias("tier")["llama-cpp"];

        Assert.Null(target.Model);
        Assert.Equal("derived-hf", target.Gguf);
        Assert.Equal("derived-hf", target.ModelRef);
    }

    [Fact]
    public void Shared_nested_huggingface_document_retains_relative_lookup_and_derives_public_basename()
    {
        var nested = Catalog.FromMapping(ObjectProperty(ObjectProperty(Fixture(), "derived_documents"), "nested_huggingface"));
        var model = nested.Model("nested-hf-model");
        var artifact = nested.Artifact("derived-nested-hf");

        Assert.Equal("Nested HF Name", model.Name);
        Assert.Equal("Nested HF Name", artifact.Description);
        Assert.Equal(["model.gguf", "projector.gguf"], artifact.Files.Select(static file => file.Filename));
        Assert.Equal("https://huggingface.co/example/nested-hf/resolve/abcdefabcdefabcdefabcdefabcdefabcdefabcd/deep/model/model.gguf", artifact.Files[0].Url);
        Assert.Equal("projector", artifact.Files[1].Role);
        Assert.Equal(975, artifact.TotalSizeBytes);
    }

    [Fact]
    public void Resolve_target_preserves_instance_priority_suffix_and_alias_provenance_without_factory_work()
    {
        var catalog = Catalog.FromMapping(ObjectProperty(Fixture(), "base"));
        var factoryCalls = new FactoryCounter();
        var registry = new ProviderRegistry([Descriptor("openai-compat", factoryCalls)]);
        var configured = new[]
        {
            new CatalogProviderBinding("primary", "openai-compat"),
            new CatalogProviderBinding("backup", "openai-compat"),
            new CatalogProviderBinding("local", "openai-compat"),
        };

        var explicitTarget = catalog.ResolveTarget(" Primary : model:with:colon ", registry, configured);
        Assert.Equal("primary", explicitTarget.ProviderId);
        Assert.Equal("model:with:colon", explicitTarget.Model);
        Assert.Null(explicitTarget.ViaAlias);

        var alias = catalog.ResolveTarget("tier", registry, configured);
        Assert.Equal("primary", alias.ProviderId);
        Assert.Equal("primary:stable", alias.Model);
        Assert.Equal("tier", alias.ViaAlias);
        Assert.Equal(0, factoryCalls.Value);

        Assert.Throws<ConfigException>(() => catalog.ResolveTarget("primary:", registry, configured));
        Assert.Throws<ConfigException>(() => catalog.ResolveTarget("no-candidate", registry, configured));
        Assert.Throws<ConfigException>(() => catalog.ResolveTarget("empty-ref", registry, configured));
        Assert.Throws<ConfigException>(() => catalog.ResolveTarget("unknown-alias", registry, configured));
        Assert.Throws<ConfigException>(() => catalog.ResolveTarget("   ", registry, configured));
        Assert.Equal(0, factoryCalls.Value);
    }

    [Fact]
    public void Catalog_derives_non_overridden_hugging_face_artifacts_and_model_name_from_public_metadata()
    {
        var catalog = Catalog.Loads("""
        {
          "models": [{
            "id": "derived-model",
            "variants": [{
              "id": "derived-variant",
              "kind": "gguf",
              "artifact_id": "derived-hf-only",
              "source": {
                "resolver": "huggingface",
                "repo": "example/derived-model",
                "revision": "0123456789012345678901234567890123456789",
                "files": ["weights/model.gguf"],
                "sha256": { "weights/model.gguf": "digest" },
                "size_bytes": { "weights/model.gguf": 7 }
              }
            }]
          }]
        }
        """);

        Assert.Equal("derived-model", catalog.Model("derived-model").Name);
        var artifact = catalog.Artifact("derived-hf-only");
        Assert.Equal("derived-model", artifact.Description);
        var file = Assert.Single(artifact.Files);
        Assert.Equal("model.gguf", file.Filename);
        Assert.Equal("https://huggingface.co/example/derived-model/resolve/0123456789012345678901234567890123456789/weights/model.gguf", file.Url);
        Assert.Equal(7, file.SizeBytes);
    }

    private static ProviderDescriptor Descriptor(string id, FactoryCounter factoryCalls) =>
        new(id, id, (_, _) =>
        {
            factoryCalls.Value++;
            return ValueTask.FromException<IAsyncDisposable>(new InvalidOperationException("Catalog resolution must not construct adapters."));
        });

    private static JsonObject Fixture() => Assert.IsType<JsonObject>(JsonReader.Read(File.ReadAllText(FixturePath())));

    private static string FixturePath()
    {
        const string relative = "tests/fixtures/sdk-catalog-v1/catalog-input.json";
        for (var directory = new DirectoryInfo(Directory.GetCurrentDirectory()); directory is not null; directory = directory.Parent)
        {
            var candidate = Path.Combine(directory.FullName, relative);
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        throw new Xunit.Sdk.XunitException($"Shared catalog fixture was not found from '{Directory.GetCurrentDirectory()}'.");
    }

    private static JsonObject ObjectProperty(JsonValue value, string name)
    {
        var objectValue = Assert.IsType<JsonObject>(value);
        Assert.True(objectValue.TryGetValue(name, out var property), $"Missing fixture property '{name}'.");
        return Assert.IsType<JsonObject>(property);
    }

    private static JsonArray ArrayProperty(JsonValue value, string name)
    {
        var objectValue = Assert.IsType<JsonObject>(value);
        Assert.True(objectValue.TryGetValue(name, out var property), $"Missing fixture property '{name}'.");
        return Assert.IsType<JsonArray>(property);
    }

    private static bool TryMutate(IDictionary<string, AliasEntry> values)
    {
        try
        {
            values["mutated"] = new AliasEntry("mutated");
            return true;
        }
        catch (NotSupportedException)
        {
            return false;
        }
    }

    private sealed class FactoryCounter
    {
        internal int Value { get; set; }
    }
}
