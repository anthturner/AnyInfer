using AnyInfer.Capabilities;
using AnyInfer.Core;
using AnyInfer.Events;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Manifest;
using AnyInfer.Providers;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Internal request-scoped manifest builder controls derived from Python folding semantics.</summary>
public sealed class ManifestBuilderTests
{
    [Fact]
    public void Builder_folds_capabilities_attempts_correlation_cache_context_usage_and_terminal_result_without_mutating_partial_state()
    {
        var target = new ResolvedTarget("alpha", "model");
        var builder = CreateBuilder(payloads: true, schema: new SchemaSpec(new JsonBoolean(true), "answer"), capabilities: new ModelCapabilities(
            contextWindow: new Sourced<int>(0, Provenance.Catalog),
            maxOutputTokens: new Sourced<int>(128, Provenance.Discovered),
            features: new Sourced<Feature>(Feature.None, Provenance.Default)));
        builder.NoteCapabilities(Metadata(target, new StructuredOutputProfile(JsonSchema: true)));
        builder.NoteRepairText("repair-secret");
        builder.Fold(new AttemptStarted("r", target, 1));
        builder.Fold(new FirstToken("r", target, 2));
        builder.Fold(new RateLimitWaited("r", "alpha", 0.5, "quota", target));
        builder.Fold(new RetryScheduled("r", target, 1, 0.2, new ErrorInfo("retry", "alpha", "generate", true, null, "retry")));
        builder.Fold(new FallbackTriggered("r", target, "beta:model", new ErrorInfo("fallback", "alpha", "generate", false, null, "fallback")));
        builder.Fold(new ContextReduced("foreign", "summary", 4, 2, 2, 9, 10, ["system"]));
        builder.Fold(new UsageEstimated("r", target, "input_tokens", "estimate"));
        builder.Fold(new ProviderDiagnostic(null, new Diagnostic("note", "warning", "global note")));
        builder.Fold(new ProviderDiagnostic(null, new Diagnostic("skip", "warning", "foreign"), "other"));
        builder.Fold(new AttemptStarted("other", target, 9));
        builder.Fold(new RetryScheduled("other", target, 9, 9, new ErrorInfo("foreign", null, null, false, null, "foreign")));
        builder.Fold(new CachePlanned("other", target, "foreign", 9, 9));
        builder.Fold(new CachePlanned("r", target, "prefix", 1, 4));
        builder.Fold(new RepairAttempted("r", target, 1, "json_schema", ["invalid"], "repair-secret"));
        builder.Fold(new AttemptStarted("r", target, 2));
        builder.Fold(new RequestFailed("r", new ErrorInfo("failed", "alpha", "generate", false, null, "terminal")));

        var partial = builder.BuildPartial();
        var result = new Generation("answer", new JsonBoolean(true), target, usage: new Usage(InputTokens: 1, OutputTokens: 2, CacheReadTokens: 3, CacheWriteTokens: 4, SearchUnits: 9), timing: new Timing(firstTokenMs: 2, totalMs: 5), structuredMechanism: "json_schema", repairAttempts: 1, warnings: ["result warning"]);
        var terminal = builder.Build(result);
        var laterPartial = builder.BuildPartial();

        Assert.False(partial.Complete);
        Assert.True(terminal.Complete);
        Assert.False(laterPartial.Complete);
        Assert.Equal("alpha:model", terminal.Capability.Target);
        Assert.Contains(terminal.Capability.Facts, fact => fact.Name == "context_window" && Assert.IsType<JsonInteger>(fact.Value).Value == 0 && fact.Provenance == "catalog");
        Assert.Contains(terminal.Capability.Facts, fact => fact.Name == "features" && Assert.IsType<JsonArray>(fact.Value).Items.Count == 0 && fact.Provenance == "default");
        Assert.Equal("json_schema", terminal.Structured.Chosen);
        Assert.Contains(terminal.Structured.Ladder, rung => rung.Mechanism == "json_schema" && rung.Available && rung.Reason.Contains("legacy", StringComparison.Ordinal));
        Assert.Equal(2, terminal.Attempts.Count);
        Assert.Equal("retried", terminal.Attempts[0].Outcome);
        Assert.Equal(0.5, terminal.Attempts[0].PacedS["quota"]);
        Assert.Equal("failed", terminal.Attempts[1].Outcome);
        Assert.Equal("terminal", terminal.Attempts[1].Error!.Detail);
        Assert.Collection(terminal.Route.Considered,
            step => { Assert.Equal("alpha:model", step.Target); Assert.Equal("retried", step.Outcome); Assert.Equal("retry", step.Reason); },
            step => { Assert.Equal("alpha:model", step.Target); Assert.Equal("abandoned", step.Outcome); Assert.Equal("fallback", step.Reason); });
        Assert.Single(terminal.Context.Reductions);
        Assert.Equal("global note", terminal.Notes[0]);
        Assert.DoesNotContain("foreign", terminal.Notes);
        Assert.Equal("prefix", terminal.Cache.Mechanism);
        Assert.Equal(3, terminal.Cache.ReadTokens);
        Assert.Equal(4, terminal.Cache.WriteTokens);
        Assert.Equal("estimate", terminal.Usage.EstimatedFields["input_tokens"]);
        Assert.Null(terminal.Usage.SearchUnits);
        Assert.Equal(2, terminal.Payloads!.RepairTexts.Count);
        Assert.Equal("hello\n\nsystem", terminal.Payloads.PromptText);
        Assert.Equal("answer", terminal.Payloads.ResponseText);
        Assert.Contains("result warning", terminal.Notes);
    }

    [Theory]
    [InlineData(false, false, 0)]
    [InlineData(false, true, 0)]
    [InlineData(true, false, 1)]
    [InlineData(true, true, 2)]
    public void Repair_text_capture_has_exact_explicit_and_event_duplication_matrix(bool capturePayloads, bool includeEvent, int expected)
    {
        var target = new ResolvedTarget("alpha", "model");
        var builder = CreateBuilder(capturePayloads);
        builder.NoteRepairText("repair");
        if (includeEvent) builder.Fold(new RepairAttempted("r", target, 1, null, rawText: "repair"));
        var manifest = builder.BuildPartial();
        Assert.Equal(expected, manifest.Payloads?.RepairTexts.Count ?? 0);
    }

    [Fact]
    public void Compound_feature_facts_use_python_enum_names()
    {
        var target = new ResolvedTarget("alpha", "model");
        var builder = CreateBuilder(false, capabilities: new ModelCapabilities(features: new Sourced<Feature>(Feature.JsonSchema | Feature.CacheUsage, Provenance.Probed)));
        builder.NoteCapabilities(Metadata(target, new StructuredOutputProfile()));
        var values = Assert.IsType<JsonArray>(builder.BuildPartial().Capability.Facts.Single(fact => fact.Name == "features").Value).Items.Select(static value => Assert.IsType<JsonString>(value).Value);
        Assert.Equal(["CACHE_USAGE", "JSON_SCHEMA"], values);
    }

    [Fact]
    public void Nonlegacy_structured_ladder_reports_exact_native_availability_reasons()
    {
        var target = new ResolvedTarget("alpha", "model");
        var schema = new SchemaSpec(new JsonObject([new JsonProperty("type", new JsonString("object"))]));
        var builder = CreateBuilder(false, schema, new ModelCapabilities(features: new Sourced<Feature>(Feature.JsonSchema | Feature.JsonMode, Provenance.Probed)));
        builder.NoteCapabilities(Metadata(target, new StructuredOutputProfile()));

        var ladder = builder.BuildPartial().Structured.Ladder;
        Assert.Collection(ladder,
            rung => { Assert.Equal("grammar", rung.Mechanism); Assert.False(rung.Available); Assert.Equal("the target is not known to support grammar (capability provenance: probed)", rung.Reason); },
            rung => { Assert.Equal("json_schema", rung.Mechanism); Assert.True(rung.Available); Assert.Equal("", rung.Reason); },
            rung => { Assert.Equal("json_mode", rung.Mechanism); Assert.True(rung.Available); Assert.Equal("a stronger mechanism was available", rung.Reason); },
            rung => { Assert.Equal("prompt", rung.Mechanism); Assert.True(rung.Available); Assert.Equal("a native mechanism was available", rung.Reason); });
    }

    [Fact]
    public void Payload_schema_uses_sorted_default_separators_while_digest_is_compact()
    {
        var schema = new SchemaSpec(new JsonObject([
            new JsonProperty("b", new JsonInteger(2)),
            new JsonProperty("a", new JsonInteger(1)),
        ]));
        var manifest = CreateBuilder(true, schema).BuildPartial();

        Assert.Equal("{\"a\": 1, \"b\": 2}", manifest.Payloads!.SchemaBody);
        Assert.Equal("sha256:43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777", manifest.Request.SchemaDigest);
    }

    [Fact]
    public void Request_telemetry_redacts_typed_repair_event_and_keeps_manifest_payload_capture_causal()
    {
        var secret = "manifest-repair-secret-" + Guid.NewGuid().ToString("N");
        Redaction.RegisterSecret(secret);
        var target = new ResolvedTarget("alpha", "model");
        var builder = CreateBuilder(true);
        var dispatcher = new EventDispatcher();
        var observer = new Observer();
        dispatcher.Subscribe(observer, payloads: true);
        var telemetry = new RequestTelemetry(Normalized(schema: null), new Route(["alpha:model"]), dispatcher, builder, "r");

        telemetry.Emit(new RepairAttempted("r", target, 1, "json_schema", [$"invalid {secret}"], $"raw {secret}"));

        var observed = Assert.IsType<RepairAttempted>(Assert.Single(observer.Events));
        Assert.DoesNotContain(secret, Assert.IsType<string>(observed.RawText), StringComparison.Ordinal);
        Assert.DoesNotContain(secret, Assert.Single(observed.Errors), StringComparison.Ordinal);
        var captured = Assert.Single(builder.BuildPartial().Payloads!.RepairTexts);
        Assert.DoesNotContain(secret, captured, StringComparison.Ordinal);
    }

    [Fact]
    public void Request_telemetry_start_is_idempotent_and_payload_demand_is_observed_after_context_creation()
    {
        var normalized = Normalized(schema: null);
        var route = new Route(["alpha:model"]);
        var dispatcher = new EventDispatcher();
        var collector = new Observer();
        var telemetry = new RequestTelemetry(normalized, route, dispatcher, null, "r");
        dispatcher.Subscribe(collector, payloads: true);
        telemetry.Start(); telemetry.Start();

        Assert.Single(collector.Events);
        Assert.Equal("hello\n\nsystem", Assert.IsType<RequestStarted>(collector.Events.Single()).PromptText);
    }

    private static ManifestBuilder CreateBuilder(bool payloads, SchemaSpec? schema = null, ModelCapabilities? capabilities = null) =>
        new("r", Normalized(schema), new Route(["alpha:model", "beta:model"]), _ => capabilities ?? new ModelCapabilities(), payloads, "v");

    private static NormalizedRequest Normalized(SchemaSpec? schema) =>
        new([Message.User("hello"), Message.System("system")], [], "auto", new Sampling(stop: ["one", "two"], seed: 7), schema, 2, 10, 1024, false, SchemaExecutionProfile.FrozenV0, null);

    private static TargetMetadata Metadata(ResolvedTarget target, StructuredOutputProfile profile) =>
        new(target, null, null, new ProviderSettings("alpha"), profile, null);

    private sealed class Observer : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];
        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent);
    }
}
