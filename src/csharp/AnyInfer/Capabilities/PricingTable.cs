using AnyInfer.Json;
using AnyInfer.Catalog;
using System.Collections.ObjectModel;
using System.Globalization;
using System.Numerics;
using System.Reflection;

namespace AnyInfer.Capabilities;

/// <summary>Provides immutable exact and boundary-prefix model pricing facts.</summary>
public sealed class PricingTable
{
    private readonly IReadOnlyDictionary<string, IReadOnlyList<PricingEntry>> _entries;

    /// <summary>Creates an immutable table with ordinal provider and model spellings.</summary>
    public PricingTable(IReadOnlyDictionary<string, IReadOnlyList<PricingEntry>> entries)
    {
        ArgumentNullException.ThrowIfNull(entries);
        var copy = new Dictionary<string, IReadOnlyList<PricingEntry>>(StringComparer.Ordinal);
        foreach (var (provider, rows) in entries)
        {
            ArgumentNullException.ThrowIfNull(provider);
            copy.Add(provider, Array.AsReadOnly((rows ?? throw new ArgumentNullException(nameof(entries))).ToArray()));
        }
        _entries = new ReadOnlyDictionary<string, IReadOnlyList<PricingEntry>>(copy);
    }

    /// <summary>Gets covered provider IDs in ordinal order.</summary>
    public IReadOnlyList<string> Providers => Array.AsReadOnly(_entries.Keys.OrderBy(static key => key, StringComparer.Ordinal).ToArray());
    /// <summary>Gets a provider's rows, or an empty immutable list.</summary>
    public IReadOnlyList<PricingEntry> EntriesFor(string providerId) => _entries.TryGetValue(providerId, out var entries) ? entries : Array.Empty<PricingEntry>();
    /// <summary>Looks up exact pricing first, then the longest valid model-prefix row.</summary>
    public Sourced<Pricing>? Lookup(string providerId, string model)
    {
        PricingEntry? best = null;
        foreach (var entry in EntriesFor(providerId))
        {
            if (model == entry.Model) { best = entry; break; }
            if (model.Length > entry.Model.Length && "-.:@".Contains(model[entry.Model.Length]) && model.StartsWith(entry.Model, StringComparison.Ordinal) && (best is null || entry.Model.Length > best.Model.Length)) best = entry;
        }
        return best is null ? null : new Sourced<Pricing>(best.Pricing, Provenance.Catalog);
    }

    /// <summary>Parses the bundled pricing JSON representation.</summary>
    public static PricingTable FromMapping(JsonObject data)
    {
        ArgumentNullException.ThrowIfNull(data);
        if (!data.TryGetValue("format_version", out var version) || !IsVersionOne(version))
        {
            throw new ConfigException("Pricing table format is unsupported.");
        }
        if (!data.TryGetValue("providers", out var rawProviders) || rawProviders is not JsonObject providers) throw new ConfigException("Pricing table is missing providers.");
        var parsed = new Dictionary<string, IReadOnlyList<PricingEntry>>(StringComparer.Ordinal);
        var toolRates = ParseServerTools(data);
        foreach (var provider in providers.Properties)
        {
            if (provider.Name.StartsWith('_')) continue;
            if (provider.Value is not JsonArray rows) throw new ConfigException("Pricing provider rows must be arrays.");
            var entries = new List<PricingEntry>();
            foreach (var rowValue in rows.Items)
            {
                if (rowValue is not JsonObject row) throw new ConfigException("Pricing row must be an object.");
                var model = ScalarText(row, "model", required: true)!;
                var perToolUse = ResolveToolRates(toolRates.TryGetValue(provider.Name, out var rates) ? rates : null, model);
                entries.Add(new PricingEntry(model, new Pricing(DecimalValue(row, "input_per_1m"), DecimalValue(row, "output_per_1m"), currency: ScalarText(row, "currency") ?? "USD", perSearchUnit: OptionalDecimal(row, "per_search_unit"), perServerToolUse: perToolUse), ScalarText(row, "last_verified", required: true)!, ScalarText(row, "source", required: true)!, ScalarText(row, "openrouter_id") ?? ""));
            }
            parsed.Add(provider.Name, entries);
        }
        return new PricingTable(parsed);
    }

    /// <summary>Loads the pricing resource embedded in this assembly.</summary>
    public static PricingTable LoadDefault()
    {
        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("AnyInfer.Capabilities.pricing.json") ?? throw new ConfigException("Bundled pricing resource is unavailable.");
        using var data = new MemoryStream(); stream.CopyTo(data); return FromMapping(JsonReader.Read(data.ToArray()) as JsonObject ?? throw new ConfigException("Bundled pricing must be an object."));
    }

    private static bool IsVersionOne(JsonValue value) => value is JsonInteger integer && integer.Value == 1 || value is JsonNumber number && number.Value == 1 || value is JsonBoolean { Value: true };
    private static decimal DecimalValue(JsonObject row, string name) => OptionalDecimal(row, name) ?? throw new ConfigException($"Pricing row requires '{name}'.");
    private static decimal? OptionalDecimal(JsonObject row, string name)
    {
        if (!row.TryGetValue(name, out var value) || value is JsonNull) return null;
        return DecimalValue(value);
    }

    private static string? ScalarText(JsonObject row, string name, bool required = false)
    {
        if (!row.TryGetValue(name, out var value))
        {
            return required ? throw new ConfigException($"Pricing row requires '{name}'.") : null;
        }
        return global::AnyInfer.Catalog.Catalog.PythonString(value);
    }

    private static IReadOnlyDictionary<string, IReadOnlyDictionary<string, ToolRate>> ParseServerTools(JsonObject data)
    {
        if (!data.TryGetValue("server_tools", out var raw) || raw is JsonNull) return new Dictionary<string, IReadOnlyDictionary<string, ToolRate>>(StringComparer.Ordinal);
        if (raw is not JsonObject providers) throw new ConfigException("Pricing server_tools must be an object.");
        var parsed = new Dictionary<string, IReadOnlyDictionary<string, ToolRate>>(StringComparer.Ordinal);
        foreach (var provider in providers.Properties)
        {
            if (provider.Name.StartsWith('_')) continue;
            if (provider.Value is not JsonObject tools) throw new ConfigException("Pricing server-tool provider must be an object.");
            var providerRates = new Dictionary<string, ToolRate>(StringComparer.Ordinal);
            foreach (var tool in tools.Properties)
            {
                if (tool.Name.StartsWith('_')) continue;
                if (tool.Value is not JsonObject entry || ScalarText(entry, "last_verified", required: true) is null || ScalarText(entry, "source", required: true) is null) throw new ConfigException("Pricing server-tool metadata is invalid.");
                providerRates.Add(tool.Name, ToolRate.Parse(entry));
            }
            parsed.Add(provider.Name, providerRates);
        }
        return parsed;
    }

    private static IReadOnlyDictionary<string, decimal> ResolveToolRates(IReadOnlyDictionary<string, ToolRate>? rates, string model)
    {
        if (rates is null) return new Dictionary<string, decimal>(StringComparer.Ordinal);
        var result = new Dictionary<string, decimal>(StringComparer.Ordinal);
        foreach (var (kind, rate) in rates)
        {
            var value = rate.Resolve(model);
            if (value is not null) result.Add(kind, value.Value);
        }
        return result;
    }

    private sealed record ToolRate(decimal? Flat, IReadOnlyDictionary<string, decimal> ByModel)
    {
        internal static ToolRate Parse(JsonObject entry)
        {
            if (ScalarText(entry, "billed_as") == "tokens") return new ToolRate(0m, new Dictionary<string, decimal>());
            if (entry.TryGetValue("per_use", out var rawFlat)) return new ToolRate(DecimalValue(rawFlat), new Dictionary<string, decimal>());
            if (!entry.TryGetValue("per_use_by_model", out var raw) || raw is not JsonObject models || models.Properties.Count == 0) throw new ConfigException("Pricing server-tool rate is incomplete.");
            return new ToolRate(null, models.Properties.ToDictionary(static item => item.Name, static item => DecimalValue(item.Value), StringComparer.Ordinal));
        }
        internal decimal? Resolve(string model)
        {
            if (Flat is not null) return Flat;
            var match = ByModel.Keys.Where(candidate => model == candidate || model.StartsWith(candidate, StringComparison.Ordinal)).OrderByDescending(static candidate => candidate.Length).FirstOrDefault();
            return match is null ? null : ByModel[match];
        }
    }

    private static decimal DecimalValue(JsonValue value)
    {
        if (value is not JsonString text || !decimal.TryParse(text.Value, NumberStyles.Float, CultureInfo.InvariantCulture, out var parsed) || parsed < 0)
        {
            throw new ConfigException("Pricing rate must be a non-negative decimal string.");
        }
        if (!IsExactDecimal(text.Value, parsed))
        {
            throw new ConfigException("Pricing rate exceeds the supported decimal precision.");
        }
        return parsed;
    }

    private static bool IsExactDecimal(string text, decimal value)
    {
        var source = text.Trim();
        var negative = source.StartsWith("-", StringComparison.Ordinal);
        if (negative || source.StartsWith("+", StringComparison.Ordinal)) source = source[1..];
        var exponent = 0;
        var marker = source.IndexOfAny(['e', 'E']);
        if (marker >= 0)
        {
            if (!int.TryParse(source[(marker + 1)..], NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out exponent)) return false;
            source = source[..marker];
        }
        var point = source.IndexOf('.');
        var fractional = point < 0 ? 0 : source.Length - point - 1;
        var digits = source.Replace(".", "", StringComparison.Ordinal);
        if (digits.Length == 0 || !digits.All(char.IsAsciiDigit)) return false;
        var sourceValue = BigInteger.Parse((negative ? "-" : "") + digits, CultureInfo.InvariantCulture);
        var sourceScale = (long)fractional - exponent;
        var bits = decimal.GetBits(value);
        var decimalValue = new BigInteger((uint)bits[0]) | (new BigInteger((uint)bits[1]) << 32) | (new BigInteger((uint)bits[2]) << 64);
        if ((bits[3] & unchecked((int)0x80000000)) != 0) decimalValue = -decimalValue;
        var decimalScale = (long)((bits[3] >> 16) & 0x7f);
        if (sourceValue.IsZero || decimalValue.IsZero)
        {
            return sourceValue.IsZero && decimalValue.IsZero;
        }

        NormalizeDecimal(ref sourceValue, ref sourceScale);
        NormalizeDecimal(ref decimalValue, ref decimalScale);
        return sourceValue == decimalValue && sourceScale == decimalScale;
    }

    private static void NormalizeDecimal(ref BigInteger coefficient, ref long scale)
    {
        while (coefficient % 10 == 0)
        {
            coefficient /= 10;
            scale--;
        }
    }
}
