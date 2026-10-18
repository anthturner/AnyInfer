using AnyInfer.Json;

namespace AnyInfer.Capabilities;

/// <summary>What a single capability probe established.</summary>
public enum ProbeOutcome
{
    /// <summary>The provider honored the tested feature.</summary>
    Supported,
    /// <summary>The provider rejected the tested feature.</summary>
    Unsupported,
    /// <summary>The result did not establish whether the feature was honored.</summary>
    Inconclusive,
}

/// <summary>One ordered result from testing a feature against a target.</summary>
public sealed record FeatureProbe
{
    /// <summary>Creates an immutable feature-probe result.</summary>
    public FeatureProbe(Feature feature, ProbeOutcome outcome, string detail = "")
    {
        if (!Enum.IsDefined(outcome))
        {
            throw new ArgumentOutOfRangeException(nameof(outcome));
        }

        Feature = feature;
        Outcome = outcome;
        Detail = detail ?? throw new ArgumentNullException(nameof(detail));
    }

    /// <summary>Gets the feature that was tested.</summary>
    public Feature Feature { get; }
    /// <summary>Gets what the probe established.</summary>
    public ProbeOutcome Outcome { get; }
    /// <summary>Gets the provider rejection or observed result detail.</summary>
    public string Detail { get; }
    /// <summary>Gets whether this probe settled a feature bit.</summary>
    public bool Conclusive => Outcome is ProbeOutcome.Supported or ProbeOutcome.Unsupported;
}

/// <summary>Ordered observations and cost from one capability-probe run.</summary>
public sealed record ProbeReport
{
    /// <summary>Creates an immutable probe report.</summary>
    public ProbeReport(
        ResolvedTarget target,
        IEnumerable<FeatureProbe>? probes = null,
        ModelCapabilities? capabilities = null,
        int requests = 0,
        Usage? usage = null)
    {
        ArgumentNullException.ThrowIfNull(target);
        Target = target;
        Probes = Array.AsReadOnly((probes ?? []).Select(static probe => probe ?? throw new ArgumentException("Probes cannot contain null.")).ToArray());
        Capabilities = capabilities;
        Requests = requests;
        Usage = usage ?? new Usage();
    }

    /// <summary>Gets the concrete target that was probed.</summary>
    public ResolvedTarget Target { get; }
    /// <summary>Gets the copied results in probe order.</summary>
    public IReadOnlyList<FeatureProbe> Probes { get; }
    /// <summary>Gets measured capabilities merged with prior facts, or <see langword="null"/>.</summary>
    public ModelCapabilities? Capabilities { get; }
    /// <summary>Gets the number of generation requests spent.</summary>
    public int Requests { get; }
    /// <summary>Gets usage reported by the probe requests.</summary>
    public Usage Usage { get; }

    /// <summary>Gets the first recorded outcome for a feature, or <see langword="null"/>.</summary>
    public ProbeOutcome? OutcomeFor(Feature feature)
    {
        foreach (var probe in Probes)
        {
            if (probe.Feature == feature)
            {
                return probe.Outcome;
            }
        }

        return null;
    }

    /// <summary>Gets a concise ordered account of conclusive probe results.</summary>
    public string Summary
    {
        get
        {
            var supported = Probes.Where(static probe => probe.Outcome == ProbeOutcome.Supported).Select(static probe => probe.Feature.ToString());
            var unsupported = Probes.Where(static probe => probe.Outcome == ProbeOutcome.Unsupported).Select(static probe => probe.Feature.ToString());
            var parts = new List<string>();
            if (supported.Any()) parts.Add($"supports {string.Join(", ", supported)}");
            if (unsupported.Any()) parts.Add($"does not support {string.Join(", ", unsupported)}");
            return $"{Target}: {(parts.Count == 0 ? "nothing conclusive" : string.Join("; ", parts))}";
        }
    }
}

/// <summary>Literal inputs and pure helpers for generation capability probes.</summary>
public static class CapabilityProbes
{
    private static readonly IReadOnlyList<Feature> Probeable = Array.AsReadOnly(new[]
    {
        Feature.JsonSchema, Feature.JsonMode, Feature.Grammar, Feature.Tools, Feature.Streaming,
    });
    private static readonly IReadOnlyList<Feature> Defaults = Array.AsReadOnly(new[]
    {
        Feature.JsonSchema, Feature.JsonMode, Feature.Tools, Feature.Streaming,
    });

    /// <summary>Gets the complete ordered features a generation probe can settle.</summary>
    public static IReadOnlyList<Feature> ProbeableFeatures => Probeable;
    /// <summary>Gets the ordered default feature selection.</summary>
    public static IReadOnlyList<Feature> DefaultProbeFeatures => Defaults;
    /// <summary>Gets the output-token ceiling for every probe request.</summary>
    public const int ProbeMaxOutputTokens = 64;
    /// <summary>Gets the immutable one-field schema used by structured-output probes.</summary>
    public static JsonObject ProbeSchema { get; } = new([
        new JsonProperty("type", new JsonString("object")),
        new JsonProperty("title", new JsonString("capability_probe")),
        new JsonProperty("properties", new JsonObject([
            new JsonProperty("colour", new JsonObject([new JsonProperty("type", new JsonString("string"))])),
        ])),
        new JsonProperty("required", new JsonArray([new JsonString("colour")])),
        new JsonProperty("additionalProperties", new JsonBoolean(false)),
    ]);
    /// <summary>Gets the immutable tool used by the tool-capability probe.</summary>
    public static ToolSpec ProbeTool { get; } = new(
        "record_colour",
        "Record a colour the user mentioned.",
        new JsonObject([
            new JsonProperty("type", new JsonString("object")),
            new JsonProperty("properties", new JsonObject([
                new JsonProperty("colour", new JsonObject([new JsonProperty("type", new JsonString("string"))])),
            ])),
            new JsonProperty("required", new JsonArray([new JsonString("colour")])),
        ]));

    /// <summary>Gets the forced structured-output mechanism for a feature, if any.</summary>
    public static string? MechanismFor(Feature feature) => feature switch
    {
        Feature.JsonSchema => "json_schema",
        Feature.JsonMode => "json_mode",
        Feature.Grammar => "grammar",
        _ => null,
    };

    /// <summary>Gets the literal request text for a feature probe.</summary>
    public static string ProbePrompt(Feature feature) => feature switch
    {
        Feature.Tools => "The user mentioned the colour blue. Record it with the tool provided.",
        Feature.Streaming => "Count from one to twenty in words, separated by commas. No other text.",
        _ => "Reply with a JSON object whose \"colour\" field is the string \"blue\".",
    };

    /// <summary>Applies conclusive probe bits to known features at probed provenance.</summary>
    public static Sourced<Feature>? ProbedFeatures(Sourced<Feature>? known, IEnumerable<FeatureProbe> probes)
    {
        ArgumentNullException.ThrowIfNull(probes);
        var value = known?.Value ?? Feature.None;
        var conclusive = false;
        foreach (var probe in probes)
        {
            ArgumentNullException.ThrowIfNull(probe);
            if (!probe.Conclusive) continue;
            conclusive = true;
            value = probe.Outcome == ProbeOutcome.Supported ? value | probe.Feature : value & ~probe.Feature;
        }

        return conclusive ? new Sourced<Feature>(value, Provenance.Probed) : null;
    }
}
