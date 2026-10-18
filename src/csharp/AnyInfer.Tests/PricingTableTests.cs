using AnyInfer.Capabilities;
using AnyInfer.Json;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public CAT.3 pricing-table parsing, lookup, and embedded-resource controls.</summary>
public sealed class PricingTableTests
{
    [Fact]
    public void Table_snapshots_rows_preserves_ordinal_identity_and_uses_exact_then_longest_boundary_prefix()
    {
        var rows = new List<PricingEntry>
        {
            new("gpt", new Pricing(1.01m, 2.02m), "2026-01-01", "https://example.invalid/gpt"),
            new("gpt-4", new Pricing(3.03m, 4.04m), "2026-01-02", "https://example.invalid/gpt-4", "example/gpt-4"),
        };
        var input = new Dictionary<string, IReadOnlyList<PricingEntry>>(StringComparer.Ordinal)
        {
            ["z-provider"] = rows,
            ["A-Provider"] = [],
        };
        var table = new PricingTable(input);
        rows.Clear();
        input.Clear();

        Assert.Equal(["A-Provider", "z-provider"], table.Providers);
        Assert.Equal(2, table.EntriesFor("z-provider").Count);
        Assert.Empty(table.EntriesFor("Z-Provider"));
        Assert.Equal(3.03m, table.Lookup("z-provider", "gpt-4")!.Value.InputPer1M);
        Assert.Equal(3.03m, table.Lookup("z-provider", "gpt-4-2026-01-01")!.Value.InputPer1M);
        Assert.Equal(3.03m, table.Lookup("z-provider", "gpt-4.preview")!.Value.InputPer1M);
        Assert.Equal(3.03m, table.Lookup("z-provider", "gpt-4:beta")!.Value.InputPer1M);
        Assert.Equal(3.03m, table.Lookup("z-provider", "gpt-4@latest")!.Value.InputPer1M);
        Assert.Equal(1.01m, table.Lookup("z-provider", "gpt-3")!.Value.InputPer1M);
        Assert.Null(table.Lookup("z-provider", "gpt4"));
        Assert.Null(table.Lookup("missing", "gpt-4"));
        Assert.Equal(Provenance.Catalog, table.Lookup("z-provider", "gpt-4")!.Provenance);
    }

    [Fact]
    public void Mapping_preserves_decimal_and_tool_rates_and_rejects_malformed_documents()
    {
        var table = PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        {
          "format_version": 1,
          "providers": {
            "engine": [{
              "model": "model",
              "input_per_1m": "0.0000000000000000001",
              "output_per_1m": "2.50",
              "cache_read_per_1m": "9",
              "per_search_unit": "0.025",
              "last_verified": "2026-01-03",
              "source": "https://example.invalid/prices"
            }, {
              "model": "model-x",
              "input_per_1m": "1",
              "output_per_1m": "2",
              "last_verified": "2026-01-03",
              "source": "https://example.invalid/prices"
            }]
          },
          "server_tools": {
            "engine": {
              "web_search": { "per_use": "0.125", "last_verified": "2026-01-03", "source": "https://example.invalid/tools" },
              "by_model": { "per_use_by_model": { "model": "0.25", "model-x": "0.5" }, "last_verified": "2026-01-03", "source": "https://example.invalid/tools" },
              "included": { "billed_as": "tokens", "last_verified": "2026-01-03", "source": "https://example.invalid/tools" }
            }
          }
        }
        """)));

        var pricing = table.Lookup("engine", "model")!.Value;
        Assert.Equal(0.0000000000000000001m, pricing.InputPer1M);
        Assert.Equal(2.50m, pricing.OutputPer1M);
        Assert.Null(pricing.CacheReadPer1M);
        Assert.Equal(0.025m, pricing.PerSearchUnit);
        Assert.Equal(0.125m, pricing.PerServerToolUse["web_search"]);
        Assert.Equal(0.25m, pricing.PerServerToolUse["by_model"]);
        Assert.Equal(0.5m, table.Lookup("engine", "model-x")!.Value.PerServerToolUse["by_model"]);
        Assert.Equal(0m, pricing.PerServerToolUse["included"]);

        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("{}"))));
        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("{\"format_version\":1,\"providers\":{\"engine\":{}}}"))));
        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("{\"format_version\":1,\"providers\":{\"engine\":[{\"model\":\"m\",\"input_per_1m\":1,\"output_per_1m\":\"1\",\"last_verified\":\"d\",\"source\":\"s\"}]}}"))));
        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("{\"format_version\":1,\"providers\":{\"engine\":[{\"model\":\"m\",\"input_per_1m\":\"-1\",\"output_per_1m\":\"1\",\"last_verified\":\"d\",\"source\":\"s\"}]}}"))));
        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("{\"format_version\":1,\"providers\":{\"engine\":[{\"model\":\"m\",\"input_per_1m\":\"not-a-decimal\",\"output_per_1m\":\"1\",\"last_verified\":\"d\",\"source\":\"s\"}]}}"))));

        var legacy = PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("{\"format_version\":true,\"providers\":{\"engine\":[{\"model\":true,\"input_per_1m\":\"1\",\"output_per_1m\":\"2\",\"last_verified\":false,\"source\":5}]}}")));
        var legacyEntry = Assert.Single(legacy.EntriesFor("engine"));
        Assert.Equal("True", legacyEntry.Model);
        Assert.Equal("False", legacyEntry.LastVerified);
        Assert.Equal("5", legacyEntry.Source);
    }

    [Fact]
    public void Mapping_uses_python_scalar_metadata_and_rejects_present_null_or_imprecise_rates()
    {
        var table = PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        {
          "format_version": 1.0,
          "providers": {
            "engine": [{
              "model": ["model", {"nested": null, "line": "x\ny"}],
              "input_per_1m": "1.2345678901234567e20",
              "output_per_1m": "2",
              "last_verified": [true, null],
              "source": {"items": ["quoted ' value", "line\nbreak"]}
            }]
          }
        }
        """)));

        var entry = Assert.Single(table.EntriesFor("engine"));
        Assert.Equal("['model', {'nested': None, 'line': 'x\\ny'}]", entry.Model);
        Assert.Equal("[True, None]", entry.LastVerified);
        Assert.Equal("{'items': [\"quoted ' value\", 'line\\nbreak']}", entry.Source);
        Assert.Equal(123456789012345670000m, entry.Pricing.InputPer1M);
        Assert.Equal(2m, entry.Pricing.OutputPer1M);

        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "1", "output_per_1m": "1", "last_verified": "d", "source": "s" }] },
          "server_tools": { "engine": { "tool": { "per_use": null, "per_use_by_model": { "m": "1" }, "last_verified": "d", "source": "s" } } } }
        """))));
        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "79228162514264337593543950336", "output_per_1m": "1", "last_verified": "d", "source": "s" }] } }
        """))));
        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "1e-100", "output_per_1m": "1", "last_verified": "d", "source": "s" }] } }
        """))));
        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "2.2250738585072014e-308", "output_per_1m": "1", "last_verified": "d", "source": "s" }] } }
        """))));
        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "1e-2147483647", "output_per_1m": "1", "last_verified": "d", "source": "s" }] } }
        """))));

        var exactTool = PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "1", "output_per_1m": "1", "last_verified": "d", "source": "s" }] },
          "server_tools": { "engine": { "exact": { "per_use": "0.125", "last_verified": "d", "source": "s" } } } }
        """)));
        Assert.Equal(0.125m, exactTool.Lookup("engine", "m")!.Value.PerServerToolUse["exact"]);

        var exactExtremeZero = PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "0e-2147483647", "output_per_1m": "0", "last_verified": "d", "source": "s" }] },
          "server_tools": { "engine": { "zero": { "per_use": "0e-2147483647", "last_verified": "d", "source": "s" } } } }
        """)));
        Assert.Equal(0m, exactExtremeZero.Lookup("engine", "m")!.Value.InputPer1M);
        Assert.Equal(0m, exactExtremeZero.Lookup("engine", "m")!.Value.PerServerToolUse["zero"]);

        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "1", "output_per_1m": "1", "last_verified": "d", "source": "s" }] },
          "server_tools": { "engine": { "flat": { "per_use": "1e-29", "last_verified": "d", "source": "s" } } } }
        """))));
        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "1", "output_per_1m": "1", "last_verified": "d", "source": "s" }] },
          "server_tools": { "engine": { "flat": { "per_use": "79228162514264337593543950336", "last_verified": "d", "source": "s" } } } }
        """))));
        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "1", "output_per_1m": "1", "last_verified": "d", "source": "s" }] },
          "server_tools": { "engine": { "by-model": { "per_use_by_model": { "m": "1e-29" }, "last_verified": "d", "source": "s" } } } }
        """))));
        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "1", "output_per_1m": "1", "last_verified": "d", "source": "s" }] },
          "server_tools": { "engine": { "by-model": { "per_use_by_model": { "m": "1e-2147483647" }, "last_verified": "d", "source": "s" } } } }
        """))));
    }

    [Fact]
    public void Mapping_preserves_ascii_space_and_uses_python_escapes_for_nonprintable_unicode_metadata()
    {
        var document = new JsonObject([
            new JsonProperty("format_version", new JsonInteger(1)),
            new JsonProperty("providers", new JsonObject([
                new JsonProperty("engine", new JsonArray([
                    new JsonObject([
                        new JsonProperty("model", new JsonString("model")),
                        new JsonProperty("input_per_1m", new JsonString("1")),
                        new JsonProperty("output_per_1m", new JsonString("1")),
                        new JsonProperty("last_verified", new JsonString("verified")),
                        new JsonProperty("source", new JsonArray([
                            new JsonString(" "), new JsonString("\u00a0"), new JsonString("\ue000"), new JsonString("\u0378"),
                        ])),
                    ]),
                ])),
            ])),
        ]);

        var entry = Assert.Single(PricingTable.FromMapping(document).EntriesFor("engine"));
        Assert.Equal("[' ', '\\xa0', '\\ue000', '\\u0378']", entry.Source);
    }

    [Fact]
    public void Embedded_default_is_assembly_backed_and_preserves_known_decimal_catalog_facts()
    {
        Assert.Contains("AnyInfer.Capabilities.pricing.json", typeof(PricingTable).Assembly.GetManifestResourceNames());
        var table = PricingTable.LoadDefault();

        var gpt = table.Lookup("openai", "gpt-5-2025-08-07");
        Assert.NotNull(gpt);
        Assert.Equal(1.25m, gpt!.Value.InputPer1M);
        Assert.Equal(10m, gpt.Value.OutputPer1M);
        Assert.Equal(Provenance.Catalog, gpt.Provenance);
    }
}
