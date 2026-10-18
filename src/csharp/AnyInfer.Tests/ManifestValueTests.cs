using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Manifest;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Value and snapshot controls for the format-one event and manifest DTOs.</summary>
public sealed class ManifestValueTests
{
    [Fact]
    public void All_telemetry_shapes_preserve_scalar_and_nullable_contracts()
    {
        var target = new ResolvedTarget("engine", "model", "alias");
        var usage = new Usage(InputTokens: 2, OutputTokens: 3);
        var timing = new Timing(totalMs: 4);
        var error = new ErrorInfo("Failure", "engine", "generate", false, 400, null);
        TelemetryEvent[] events =
        [
            new RequestStarted("r", ["a"], promptText: null),
            new ArenaCompleted("r", 2, "vote", null, 3, 0, false),
            new TargetResolved("r", target), new AttemptStarted("r", target, 1), new FirstToken("r", target, 1.5),
            new AttemptCompleted("r", target, usage, timing, "stop"), new RetryScheduled("r", target, 1, 0.1, error),
            new FallbackTriggered("r", target, "next"), new RepairAttempted("r", target, 1, null),
            new RequestCompleted("r", target, usage, timing), new RequestFailed("r", error),
            new ParameterDropped("r", target, "temperature", "unsupported"), new ProviderDiagnostic(null, new Diagnostic("x", "warning", "m")),
            new UsageEstimated("r", target, "input_tokens", "heuristic"), new ContextReduced("trim", "summary", 4, 2, 2, 8, 9),
            new CachePlanned("r", target, "prefix", 1, 2), new RateLimitWaited("r", "engine", 0.2, "quota"),
            new RateLimitObserved("engine"), new ServerLifecycle("srv", "ready"), new DownloadProgress("a", 1, null),
            new BatchSubmitted("b", target, 1), new BatchCompleted("b", target, "done", 1, 0), new CredentialRotated("engine"),
        ];

        Assert.Equal(23, events.Length);
        Assert.Null(Assert.IsType<FallbackTriggered>(events[7]).Error);
        var repaired = Assert.IsType<RepairAttempted>(events[8]);
        Assert.Null(repaired.Mechanism);
        Assert.Empty(repaired.Errors);
        Assert.Null(repaired.RawText);
        Assert.Null(Assert.IsType<ProviderDiagnostic>(events[12]).Target);
        Assert.Null(Assert.IsType<RateLimitObserved>(events[17]).RequestsRemaining);
        Assert.Null(Assert.IsType<DownloadProgress>(events[19]).TotalBytes);
    }

    [Fact]
    public void Event_and_manifest_inputs_are_defensively_snapshotted_with_ordinal_maps()
    {
        var targets = new List<string> { "first" };
        var metadata = new Dictionary<string, string>(StringComparer.Ordinal) { ["Z"] = "z" };
        var started = new RequestStarted("r", targets, metadata, "payload");
        targets.Add("later");
        metadata["Z"] = "changed";
        Assert.Equal(["first"], started.Targets);
        Assert.Equal("z", started.Metadata["Z"]);

        var phases = new Dictionary<string, double>(StringComparer.Ordinal) { ["b"] = 2, ["a"] = 1 };
        var notes = new List<string> { "one" };
        var manifest = new RunManifest(timing: new TimingFacet(phases: phases), notes: notes);
        phases["a"] = 99;
        notes.Add("two");
        Assert.Equal(1, manifest.Timing.Phases["a"]);
        Assert.Equal(["one"], manifest.Notes);
        Assert.False(manifest.Timing.Phases is IDictionary<string, double>);
        Assert.False(manifest.Notes is IList<string>);
    }

    [Fact]
    public void Every_manifest_collection_boundary_snapshots_inputs_and_maps_are_ordinal_last_wins()
    {
        var roles = new List<KeyValuePair<string, int>> { new("A", 1), new("A", 3), new("a", 2) };
        var tools = new List<string> { "first" };
        var sampling = new List<KeyValuePair<string, JsonValue>> { new("temperature", new JsonNumber(0.1)), new("temperature", new JsonNumber(0.2)) };
        var metadata = new List<string> { "m" };
        var request = new RequestFacet(roleCounts: roles, toolNames: tools, sampling: sampling, metadataKeys: metadata);
        roles.Add(new("later", 9)); tools.Add("later"); sampling.Add(new("later", JsonNull.Instance)); metadata.Add("later");

        var steps = new List<RouteStep> { new("a:m", "selected") };
        var facts = new List<SourcedFact> { new("f", new JsonString("v"), "catalog") };
        var paced = new List<KeyValuePair<string, double>> { new("gate", 1) };
        var constraints = new List<string> { "binding" };
        var reductions = new List<ReductionRecord> { new("trim", "summary", bindingConstraints: constraints) };
        var errors = new List<string> { "invalid" };
        var repairs = new List<RepairRecord> { new(1, errors: errors) };
        var ladder = new List<MechanismRung> { new("json_schema", true) };
        var estimates = new List<KeyValuePair<string, string>> { new("input_tokens", "estimate") };
        var phaseValues = new List<KeyValuePair<string, double>> { new("decode", 2) };
        var toolArguments = new List<string> { "{}" };
        var repairTexts = new List<string> { "raw" };
        var attempts = new List<AttemptFacet> { new("a:m", pacedS: paced) };
        var dropped = new List<DroppedParameter> { new("a:m", "temperature", "unsupported") };
        var notes = new List<string> { "note" };
        var manifest = new RunManifest(
            route: new RouteFacet(["a:m"], considered: steps),
            capability: new CapabilityFacet("a:m", facts),
            attempts: attempts,
            structured: new SchemaFacet(true, ladder: ladder, repairs: repairs),
            context: new ContextFacet(reductions),
            dropped: dropped,
            usage: new UsageFacet(estimatedFields: estimates),
            timing: new TimingFacet(phases: phaseValues),
            notes: notes,
            payloads: new PayloadFacet(toolArguments: toolArguments, repairTexts: repairTexts));

        steps.Add(new("b:m", "skipped")); facts.Add(new("later", JsonNull.Instance, "default")); paced.Add(new("later", 3)); constraints.Add("later"); errors.Add("later"); repairs.Add(new(2)); ladder.Add(new("json_mode", false)); estimates.Add(new("later", "x")); phaseValues.Add(new("later", 4)); toolArguments.Add("later"); repairTexts.Add("later"); attempts.Add(new("b:m")); dropped.Add(new("b:m", "top_p", "unsupported")); notes.Add("later");

        Assert.Equal(3, request.RoleCounts["A"]);
        Assert.Equal(2, request.RoleCounts["a"]);
        Assert.Single(request.ToolNames); Assert.Single(request.Sampling); Assert.Single(request.MetadataKeys);
        Assert.Single(manifest.Route.Considered); Assert.Single(manifest.Capability.Facts); Assert.Single(manifest.Attempts);
        Assert.Single(manifest.Attempts[0].PacedS); Assert.Single(manifest.Context.Reductions[0].BindingConstraints);
        Assert.Single(manifest.Structured.Ladder); Assert.Single(manifest.Structured.Repairs); Assert.Single(manifest.Structured.Repairs[0].Errors);
        Assert.Single(manifest.Usage.EstimatedFields); Assert.Single(manifest.Timing.Phases); Assert.Single(manifest.Payloads!.ToolArguments); Assert.Single(manifest.Payloads.RepairTexts);
        Assert.Single(manifest.Dropped); Assert.Single(manifest.Notes);
        Assert.False(request.RoleCounts is IDictionary<string, int>);
        Assert.False(manifest.Usage.EstimatedFields is IDictionary<string, string>);
    }

    [Fact]
    public void Direct_event_collection_inputs_are_snapshotted_independently_of_manifest_facets()
    {
        var target = new ResolvedTarget("engine", "model");
        var errors = new List<string> { "first" };
        var constraints = new List<string> { "must-keep" };
        var repair = new RepairAttempted("r", target, 1, null, errors);
        var reduced = new ContextReduced("trim", "summary", 2, 1, 1, 3, 4, constraints);
        errors.Add("later");
        constraints.Add("later");

        Assert.Equal(["first"], repair.Errors);
        Assert.Equal(["must-keep"], reduced.BindingConstraints);
        Assert.False(repair.Errors is IList<string>);
        Assert.False(reduced.BindingConstraints is IList<string>);
    }

    [Fact]
    public void Nested_json_facts_and_sampling_maps_have_semantic_value_equality_and_ordinal_hashes()
    {
        var first = new JsonObject([new JsonProperty("z", new JsonArray([new JsonInteger(2)])), new JsonProperty("a", new JsonString("x"))]);
        var second = new JsonObject([new JsonProperty("a", new JsonString("x")), new JsonProperty("z", new JsonArray([new JsonInteger(2)]))]);
        var one = new SourcedFact("fact", first, "catalog");
        var two = new SourcedFact("fact", second, "catalog");
        Assert.Equal(one, two);
        Assert.Equal(one.GetHashCode(), two.GetHashCode());

        var left = new RequestFacet(sampling: new Dictionary<string, JsonValue>(StringComparer.Ordinal) { ["top_p"] = first, ["temperature"] = new JsonNumber(0.2) });
        var right = new RequestFacet(sampling: new Dictionary<string, JsonValue>(StringComparer.Ordinal) { ["temperature"] = new JsonNumber(0.2), ["top_p"] = second });
        Assert.Equal(left, right);
        Assert.Equal(left.GetHashCode(), right.GetHashCode());
    }

    [Fact]
    public void Manifest_defaults_and_later_pure_values_keep_unknown_distinct_from_false_or_zero()
    {
        var manifest = new RunManifest();
        Assert.Equal("1", manifest.Format);
        Assert.False(manifest.Complete);
        Assert.Empty(manifest.Attempts);
        Assert.Null(manifest.Payloads);
        Assert.Equal("generation", manifest.Operation);

        var sameIdentity = new EmbeddingSpace("engine", "model", dimensions: 0, inputIntentAware: true, normalized: false);
        var changedFacts = new EmbeddingSpace("engine", "model", dimensions: 4096, inputIntentAware: false, normalized: null);
        Assert.True(sameIdentity.CompatibleWith(changedFacts));
        Assert.True(new EmbeddingSpace("a", "one", compatibilityId: "shared").CompatibleWith(new EmbeddingSpace("b", "two", compatibilityId: "shared")));
        Assert.False(new EmbeddingSpace("a", "one").CompatibleWith(new EmbeddingSpace("b", "one")));

        var rung = new MechanismRung("json_schema", false, "unsupported");
        Assert.False(rung.Available);
        Assert.Equal("unsupported", rung.Reason);
    }
}
