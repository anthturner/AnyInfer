using AnyInfer.Capabilities;
using AnyInfer.Json;
using Xunit;
using PeterO.Numbers;

namespace AnyInfer.Tests;

/// <summary>Public CAT.3 pricing-table parsing, lookup, and embedded-resource controls.</summary>
public sealed class PricingTableTests
{
    [Fact]
    public void Table_snapshots_rows_preserves_ordinal_identity_and_uses_exact_then_longest_boundary_prefix()
    {
        var rows = new List<PricingEntry>
        {
            new("gpt", new Pricing(EDecimal.FromString("1.01"), EDecimal.FromString("2.02")), "2026-01-01", "https://example.invalid/gpt"),
            new("gpt-4", new Pricing(EDecimal.FromString("3.03"), EDecimal.FromString("4.04")), "2026-01-02", "https://example.invalid/gpt-4", "example/gpt-4"),
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
        Assert.Equal(EDecimal.FromString("3.03"), table.Lookup("z-provider", "gpt-4")!.Value.InputPer1M);
        Assert.Equal(EDecimal.FromString("3.03"), table.Lookup("z-provider", "gpt-4-2026-01-01")!.Value.InputPer1M);
        Assert.Equal(EDecimal.FromString("3.03"), table.Lookup("z-provider", "gpt-4.preview")!.Value.InputPer1M);
        Assert.Equal(EDecimal.FromString("3.03"), table.Lookup("z-provider", "gpt-4:beta")!.Value.InputPer1M);
        Assert.Equal(EDecimal.FromString("3.03"), table.Lookup("z-provider", "gpt-4@latest")!.Value.InputPer1M);
        Assert.Equal(EDecimal.FromString("1.01"), table.Lookup("z-provider", "gpt-3")!.Value.InputPer1M);
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
        Assert.Equal(EDecimal.FromString("0.0000000000000000001"), pricing.InputPer1M);
        Assert.Equal(EDecimal.FromString("2.50"), pricing.OutputPer1M);
        Assert.Null(pricing.CacheReadPer1M);
        Assert.Equal(EDecimal.FromString("0.025"), pricing.PerSearchUnit);
        Assert.Equal(EDecimal.FromString("0.125"), pricing.PerServerToolUse["web_search"]);
        Assert.Equal(EDecimal.FromString("0.25"), pricing.PerServerToolUse["by_model"]);
        Assert.Equal(EDecimal.FromString("0.5"), table.Lookup("engine", "model-x")!.Value.PerServerToolUse["by_model"]);
        Assert.Equal(EDecimal.FromString("0"), pricing.PerServerToolUse["included"]);

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
    public void Mapping_uses_python_scalar_metadata_and_preserves_exact_rates()
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
        Assert.Equal(0, entry.Pricing.InputPer1M.CompareTo(EDecimal.FromString("123456789012345670000")));
        Assert.Equal("1.2345678901234567E+20", entry.Pricing.InputPer1M.ToString());
        Assert.Equal(EDecimal.FromString("2"), entry.Pricing.OutputPer1M);

        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "1", "output_per_1m": "1", "last_verified": "d", "source": "s" }] },
          "server_tools": { "engine": { "tool": { "per_use": null, "per_use_by_model": { "m": "1" }, "last_verified": "d", "source": "s" } } } }
        """))));
        var extended = PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "wide", "input_per_1m": "79228162514264337593543950336", "output_per_1m": "1e-29", "last_verified": "d", "source": "s" }] } }
        """)));
        var wide = extended.Lookup("engine", "wide")!.Value;
        Assert.Equal(EDecimal.FromString("79228162514264337593543950336"), wide.InputPer1M);
        Assert.Equal(EDecimal.FromString("1e-29"), wide.OutputPer1M);

        var outsideArithmeticRange = PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "tiny", "input_per_1m": "1e-2147483647", "output_per_1m": "1", "last_verified": "d", "source": "s" }] } }
        """)));
        Assert.Equal("1E-2147483647", outsideArithmeticRange.Lookup("engine", "tiny")!.Value.InputPer1M.ToString());

        var exactTool = PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "1", "output_per_1m": "1", "last_verified": "d", "source": "s" }] },
          "server_tools": { "engine": { "exact": { "per_use": "0.125", "last_verified": "d", "source": "s" } } } }
        """)));
        Assert.Equal(EDecimal.FromString("0.125"), exactTool.Lookup("engine", "m")!.Value.PerServerToolUse["exact"]);

        var exactExtremeZero = PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "m", "input_per_1m": "0e-2147483647", "output_per_1m": "0", "last_verified": "d", "source": "s" }] },
          "server_tools": { "engine": { "zero": { "per_use": "0e-2147483647", "last_verified": "d", "source": "s" } } } }
        """)));
        var extremeZeroPricing = exactExtremeZero.Lookup("engine", "m")!.Value;
        Assert.Equal(0, extremeZeroPricing.InputPer1M.CompareTo(EDecimal.Zero));
        Assert.Equal("0E-2147483647", extremeZeroPricing.InputPer1M.ToString());
        Assert.Equal(0, extremeZeroPricing.PerServerToolUse["zero"].CompareTo(EDecimal.Zero));
        Assert.Equal("0E-2147483647", extremeZeroPricing.PerServerToolUse["zero"].ToString());

        var positiveInfinity = PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "infinite", "input_per_1m": "Infinity", "output_per_1m": "1", "last_verified": "d", "source": "s" }] } }
        """)));
        Assert.Equal(EDecimal.FromString("Infinity"), positiveInfinity.Lookup("engine", "infinite")!.Value.InputPer1M);

        Assert.Throws<ConfigException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "negative-infinity", "input_per_1m": "-Infinity", "output_per_1m": "1", "last_verified": "d", "source": "s" }] } }
        """))));
        Assert.Throws<ETrapException>(() => PricingTable.FromMapping(Assert.IsType<JsonObject>(JsonReader.Read("""
        { "format_version": 1, "providers": { "engine": [{ "model": "nan", "input_per_1m": "NaN", "output_per_1m": "1", "last_verified": "d", "source": "s" }] } }
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
        Assert.Equal(EDecimal.FromString("1.25"), gpt!.Value.InputPer1M);
        Assert.Equal(EDecimal.FromString("10"), gpt.Value.OutputPer1M);
        Assert.Equal(Provenance.Catalog, gpt.Provenance);
    }
}
