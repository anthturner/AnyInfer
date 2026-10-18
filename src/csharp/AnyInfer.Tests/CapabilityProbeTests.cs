using AnyInfer.Capabilities;
using AnyInfer.Json;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Pure, immutable PRB.3 probe values and merge-oracle coverage.</summary>
public sealed class CapabilityProbeTests
{
    [Fact]
    public void Literal_probe_inputs_preserve_the_complete_ordered_default_and_immutable_raw_declarations()
    {
        Assert.Equal(
            [Feature.JsonSchema, Feature.JsonMode, Feature.Grammar, Feature.Tools, Feature.Streaming],
            CapabilityProbes.ProbeableFeatures);
        Assert.Equal(
            [Feature.JsonSchema, Feature.JsonMode, Feature.Tools, Feature.Streaming],
            CapabilityProbes.DefaultProbeFeatures);
        Assert.Equal(64, CapabilityProbes.ProbeMaxOutputTokens);
        Assert.Equal("json_schema", CapabilityProbes.MechanismFor(Feature.JsonSchema));
        Assert.Equal("json_mode", CapabilityProbes.MechanismFor(Feature.JsonMode));
        Assert.Equal("grammar", CapabilityProbes.MechanismFor(Feature.Grammar));
        Assert.Null(CapabilityProbes.MechanismFor(Feature.Tools));
        Assert.Equal("The user mentioned the colour blue. Record it with the tool provided.", CapabilityProbes.ProbePrompt(Feature.Tools));
        Assert.Equal("Count from one to twenty in words, separated by commas. No other text.", CapabilityProbes.ProbePrompt(Feature.Streaming));
        Assert.Equal("Reply with a JSON object whose \"colour\" field is the string \"blue\".", CapabilityProbes.ProbePrompt(Feature.JsonSchema));

        Assert.Equal("capability_probe", StringValue(CapabilityProbes.ProbeSchema, "title"));
        Assert.Equal("record_colour", CapabilityProbes.ProbeTool.Name);
        Assert.Equal("Record a colour the user mentioned.", CapabilityProbes.ProbeTool.Description);
        Assert.False(CapabilityProbes.ProbeTool.Annotations.Stated);
        Assert.IsType<JsonObject>(CapabilityProbes.ProbeTool.Parameters);
        var defaults = Assert.IsAssignableFrom<IList<Feature>>(CapabilityProbes.DefaultProbeFeatures);
        var probeable = Assert.IsAssignableFrom<IList<Feature>>(CapabilityProbes.ProbeableFeatures);
        Assert.Throws<NotSupportedException>(() => defaults[0] = Feature.Grammar);
        Assert.Throws<NotSupportedException>(() => probeable.Add(Feature.None));
    }

    [Fact]
    public void Probe_report_copies_ordered_entries_uses_first_duplicate_outcome_and_excludes_inconclusive_from_summary()
    {
        var source = new List<FeatureProbe>
        {
            new(Feature.JsonMode, ProbeOutcome.Inconclusive, "accepted but wrong"),
            new(Feature.JsonMode, ProbeOutcome.Unsupported, "rejected"),
            new(Feature.Streaming, ProbeOutcome.Supported, "two deltas"),
        };
        var report = new ProbeReport(new ResolvedTarget("primary", "model"), source, requests: 3);
        source.Clear();

        Assert.Equal(3, report.Probes.Count);
        Assert.Equal(ProbeOutcome.Inconclusive, report.OutcomeFor(Feature.JsonMode));
        Assert.Equal(ProbeOutcome.Supported, report.OutcomeFor(Feature.Streaming));
        Assert.Null(report.OutcomeFor(Feature.Grammar));
        Assert.Equal("primary:model: supports Streaming; does not support JsonMode", report.Summary);
        var probes = Assert.IsAssignableFrom<IList<FeatureProbe>>(report.Probes);
        Assert.Throws<NotSupportedException>(() => probes.RemoveAt(0));
        Assert.Null(report.Usage.InputTokens);
        Assert.Null(report.Usage.OutputTokens);
    }

    [Fact]
    public void Conclusive_results_apply_in_order_at_probed_provenance_without_erasing_untested_bits()
    {
        var known = new Sourced<Feature>(Feature.Streaming | Feature.JsonSchema | Feature.Tools, Provenance.Discovered);
        var measured = CapabilityProbes.ProbedFeatures(known,
        [
            new FeatureProbe(Feature.JsonMode, ProbeOutcome.Supported),
            new FeatureProbe(Feature.JsonSchema, ProbeOutcome.Unsupported),
            new FeatureProbe(Feature.JsonMode, ProbeOutcome.Unsupported),
        ]);

        Assert.NotNull(measured);
        Assert.Equal(Provenance.Probed, measured.Provenance);
        Assert.Equal(Feature.Streaming | Feature.Tools, measured.Value);
    }

    [Fact]
    public void Inconclusive_only_results_record_nothing_while_an_unsupported_final_bit_records_active_none_at_probed_provenance()
    {
        var unknownSentinel = new Sourced<Feature>(Feature.None, Provenance.Default);
        Assert.Null(CapabilityProbes.ProbedFeatures(unknownSentinel, [new FeatureProbe(Feature.JsonSchema, ProbeOutcome.Inconclusive)]));
        Assert.Null(CapabilityProbes.ProbedFeatures(null, []));

        var measured = CapabilityProbes.ProbedFeatures(new Sourced<Feature>(Feature.JsonSchema, Provenance.Default), [new FeatureProbe(Feature.JsonSchema, ProbeOutcome.Unsupported)]);
        Assert.NotNull(measured);
        Assert.Equal(Feature.None, measured.Value);
        Assert.Equal(Provenance.Probed, measured.Provenance);
    }

    private static string StringValue(JsonObject source, string name)
    {
        Assert.True(source.TryGetValue(name, out var value), $"Missing property '{name}'.");
        return Assert.IsType<JsonString>(value).Value;
    }
}
