using AnyInfer.Json;
using AnyInfer.Catalog;
using AnyInfer.Internal;
using PeterO.Numbers;
using System.Collections.ObjectModel;
using System.Reflection;

namespace AnyInfer.Capabilities;

/// <summary>Provides immutable exact and boundary-prefix model pricing facts.</summary>
public sealed class PricingTable
{
    private readonly IReadOnlyDictionary<string, IReadOnlyList<PricingEntry>> _entries;

    /// <summary>Creates an immutable table with ordinal provider and model spellings.</summary>
    /// <param name="entries">Pricing rows keyed by provider identifier; each row list is copied in order.</param>
    /// <exception cref="ArgumentNullException"><paramref name="entries"/>, a provider key, or a row list is <see langword="null"/>.</exception>
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
    /// <param name="providerId">Exact, case-sensitive provider identifier.</param>
    /// <returns>The provider's rows in table order, or an empty list when the provider is not covered.</returns>
    public IReadOnlyList<PricingEntry> EntriesFor(string providerId) => _entries.TryGetValue(providerId, out var entries) ? entries : Array.Empty<PricingEntry>();
    /// <summary>Looks up exact pricing first, then the longest valid model-prefix row.</summary>
    /// <remarks>
    /// A prefix row matches only at a boundary: the model must continue with <c>-</c>, <c>.</c>, <c>:</c>, or
    /// <c>@</c> after the row's model spelling.
    /// </remarks>
    /// <param name="providerId">Exact, case-sensitive provider identifier.</param>
    /// <param name="model">Exact, case-sensitive model identifier.</param>
    /// <returns>The matching pricing at <see cref="Provenance.Catalog"/> provenance, or <see langword="null"/> when no row matches.</returns>
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
    /// <remarks>
    /// Rates must be non-negative decimal strings. Provider and tool keys beginning with an underscore are
    /// skipped, and provider-run tool prices from the <c>server_tools</c> section are attached to matching rows.
    /// </remarks>
    /// <param name="data">Parsed pricing object with <c>format_version</c> 1 and a <c>providers</c> object.</param>
    /// <returns>An immutable table of the parsed rows.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="data"/> is <see langword="null"/>.</exception>
    /// <exception cref="ConfigException">The format version is unsupported or a row or rate is malformed.</exception>
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
    /// <remarks>
    /// The bundled prices are a snapshot from when this assembly was built; each row records when and against
    /// what source it was last verified. Each call parses the resource again.
    /// </remarks>
    /// <returns>An immutable table of the bundled catalog prices.</returns>
    /// <exception cref="ConfigException">The bundled resource is missing or invalid.</exception>
    public static PricingTable LoadDefault()
    {
        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("AnyInfer.Capabilities.pricing.json") ?? throw new ConfigException("Bundled pricing resource is unavailable.");
        using var data = new MemoryStream(); stream.CopyTo(data); return FromMapping(JsonReader.Read(data.ToArray()) as JsonObject ?? throw new ConfigException("Bundled pricing must be an object."));
    }

    private static bool IsVersionOne(JsonValue value) => value is JsonInteger integer && integer.Value == 1 || value is JsonNumber number && number.Value == 1 || value is JsonBoolean { Value: true };
    private static EDecimal DecimalValue(JsonObject row, string name) => OptionalDecimal(row, name) ?? throw new ConfigException($"Pricing row requires '{name}'.");
    private static EDecimal? OptionalDecimal(JsonObject row, string name)
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

    private static IReadOnlyDictionary<string, EDecimal> ResolveToolRates(IReadOnlyDictionary<string, ToolRate>? rates, string model)
    {
        if (rates is null) return new Dictionary<string, EDecimal>(StringComparer.Ordinal);
        var result = new Dictionary<string, EDecimal>(StringComparer.Ordinal);
        foreach (var (kind, rate) in rates)
        {
            var value = rate.Resolve(model);
            if (value is not null) result.Add(kind, value);
        }
        return result;
    }

    private sealed record ToolRate(EDecimal? Flat, IReadOnlyDictionary<string, EDecimal> ByModel)
    {
        internal static ToolRate Parse(JsonObject entry)
        {
            if (ScalarText(entry, "billed_as") == "tokens") return new ToolRate(EDecimal.Zero, new Dictionary<string, EDecimal>());
            if (entry.TryGetValue("per_use", out var rawFlat)) return new ToolRate(DecimalValue(rawFlat), new Dictionary<string, EDecimal>());
            if (!entry.TryGetValue("per_use_by_model", out var raw) || raw is not JsonObject models || models.Properties.Count == 0) throw new ConfigException("Pricing server-tool rate is incomplete.");
            return new ToolRate(null, models.Properties.ToDictionary(static item => item.Name, static item => DecimalValue(item.Value), StringComparer.Ordinal));
        }
        internal EDecimal? Resolve(string model)
        {
            if (Flat is not null) return Flat;
            var match = ByModel.Keys.Where(candidate => model == candidate || model.StartsWith(candidate, StringComparison.Ordinal)).OrderByDescending(static candidate => candidate.Length).FirstOrDefault();
            return match is null ? null : ByModel[match];
        }
    }

    private static EDecimal DecimalValue(JsonValue value)
    {
        if (value is not JsonString text)
        {
            throw new ConfigException("Pricing rate must be a non-negative decimal string.");
        }

        EDecimal parsed;
        try
        {
            parsed = EDecimal.FromString(text.Value);
        }
        catch (FormatException exception)
        {
            throw new ConfigException("Pricing rate must be a non-negative decimal string.", nativeInner: exception);
        }

        if (AccountingDecimal.IsNegativeCatalogRate(parsed)) throw new ConfigException("Pricing rate must be a non-negative decimal string.");
        return parsed;
    }
}
