using System.Numerics;
using System.Text;
using AnyInfer;
using AnyInfer.Core;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Conformance;

public sealed class NativeProofsTests
{
    private const string Concurrent = "driver/concurrent-operations-independent";
    private const string Assessment = "driver/assessment-completeness";
    private const string EffectiveLimits = "driver/timeout-effective-default-explicit";
    private const string Reset = "driver/timeout-reset-per-entry";
    private const string CleanupDisposal = "driver/timeout-cleanup-disposal";
    private const string HttpCorrectionBudget = "driver/http-correction-byte-budget-reset";

    [Theory]
    [InlineData(Concurrent)]
    [InlineData(Assessment)]
    [InlineData(EffectiveLimits)]
    [InlineData(Reset)]
    [InlineData(CleanupDisposal)]
    [InlineData(HttpCorrectionBudget)]
    public async Task Supported_recipe_dispatches_to_nonempty_ordinary_evidence(string recipeRef)
    {
        Assert.True(NativeProofs.IsSupported(recipeRef));

        var result = await NativeProofs.RunAsync(recipeRef);

        Assert.Equal("pass", result.Verdict);
        Assert.Null(result.Detail);
        Assert.NotEmpty(result.Evidence.Properties);
        Assert.Equal(recipeRef, StringProperty(result.Evidence, "recipe_ref"));
        AssertOrdinary(result.Evidence);
    }

    [Fact]
    public async Task Unknown_recipe_is_not_supported_and_fails_closed()
    {
        const string unknown = "driver/not-a-first-native-proof";
        Assert.False(NativeProofs.IsSupported(unknown));
        await Assert.ThrowsAsync<ArgumentException>(async () => await NativeProofs.RunAsync(unknown));
    }

    [Fact]
    public async Task Concurrent_proof_observes_overlap_distinct_assessments_and_a_schema_free_follow_up()
    {
        var result = await NativeProofs.RunAsync(Concurrent);
        var evidence = AssertPassing(Concurrent, result);

        Assert.True(BooleanProperty(evidence, "overlap_observed"));
        Assert.True(BooleanProperty(evidence, "prior_captures_unchanged"));

        var valid = ObjectProperty(evidence, "valid");
        var invalid = ObjectProperty(evidence, "invalid");
        Assert.NotEqual(StringProperty(valid, "operation_id"), StringProperty(invalid, "operation_id"));
        Assert.Single(ArrayProperty(valid, "entries").Items);
        Assert.Single(ArrayProperty(invalid, "entries").Items);
        Assert.Equal("result", StringProperty(ObjectProperty(valid, "outcome"), "kind"));
        Assert.Equal("error", StringProperty(ObjectProperty(invalid, "outcome"), "kind"));
        Assert.True(BooleanProperty(Assert.IsType<JsonObject>(ArrayProperty(valid, "assessments").Items.Single()), "valid"));
        Assert.False(BooleanProperty(Assert.IsType<JsonObject>(ArrayProperty(invalid, "assessments").Items.Single()), "valid"));

        var validEntry = Assert.IsType<JsonObject>(ArrayProperty(valid, "entries").Items.Single());
        var invalidEntry = Assert.IsType<JsonObject>(ArrayProperty(invalid, "entries").Items.Single());
        Assert.Equal(StringProperty(valid, "operation_id"), StringProperty(validEntry, "operation_id"));
        Assert.Equal(StringProperty(invalid, "operation_id"), StringProperty(invalidEntry, "operation_id"));
        Assert.NotEqual(StringProperty(validEntry, "operation_id"), StringProperty(invalidEntry, "operation_id"));

        var followUp = ObjectProperty(evidence, "schema_free_follow_up");
        Assert.Empty(ArrayProperty(followUp, "assessments").Items);
        Assert.Single(ArrayProperty(followUp, "entries").Items);
    }

    [Fact]
    public async Task Assessment_proof_retains_actual_branch_evidence_and_rejects_unavailable_observation_without_changing_outcome()
    {
        var evidence = AssertPassing(Assessment, await NativeProofs.RunAsync(Assessment));

        var noCandidate = ObjectProperty(evidence, "no_candidate");
        Assert.Equal("extraction", StringProperty(Assert.IsType<JsonObject>(ArrayProperty(noCandidate, "assessments").Items.Single()), "kind"));

        var malformed = ObjectProperty(evidence, "late_malformed_required");
        var malformedFinding = Assert.IsType<JsonObject>(ArrayProperty(
            Assert.IsType<JsonObject>(ArrayProperty(malformed, "assessments").Items.Single()),
            "selected_findings").Items.Single());
        Assert.Equal("invalid_schema", StringProperty(malformedFinding, "rule"));

        var exhaustion = ObjectProperty(evidence, "exhaustion");
        Assert.Equal(2, ArrayProperty(exhaustion, "assessments").Items.Count);
        Assert.Single(ArrayProperty(exhaustion, "repairs").Items);

        var nestedDotted = ObjectProperty(evidence, "nested_dotted");
        var selected = ArrayProperty(Assert.IsType<JsonObject>(ArrayProperty(nestedDotted, "assessments").Items.Single()), "selected_findings");
        Assert.Contains(selected.Items, item => PathEquals(ArrayProperty(Assert.IsType<JsonObject>(item), "instance_path"), "a.b"));
        Assert.Contains(selected.Items, item => PathEquals(ArrayProperty(Assert.IsType<JsonObject>(item), "instance_path"), "outer", "value"));

        var repaired = ObjectProperty(evidence, "invalid_then_valid");
        Assert.Equal(2, ArrayProperty(repaired, "assessments").Items.Count);
        Assert.Single(ArrayProperty(repaired, "repairs").Items);

        AssertUnavailableControl(ObjectProperty(evidence, "cap_control"));
        AssertUnavailableControl(ObjectProperty(evidence, "fault_control"));
    }

    [Fact]
    public async Task Effective_limits_proof_uses_actual_default_explicit_and_native_timeout_lifecycle_facts()
    {
        var evidence = AssertPassing(EffectiveLimits, await NativeProofs.RunAsync(EffectiveLimits));

        var defaultEntry = ObjectProperty(evidence, "default_entry");
        Assert.Equal(120d, NumberProperty(defaultEntry, "timeout_s"));
        Assert.Equal(new BigInteger(1_048_576), IntegerProperty(defaultEntry, "max_response_bytes"));
        Assert.Equal(120d, NumberProperty(defaultEntry, "effective_timeout_s"));

        var explicitEntry = ObjectProperty(evidence, "explicit_entry");
        Assert.Equal(7.25, NumberProperty(explicitEntry, "timeout_s"));
        Assert.Equal(new BigInteger(4096), IntegerProperty(explicitEntry, "max_response_bytes"));
        Assert.Equal(7.25, NumberProperty(explicitEntry, "effective_timeout_s"));

        var timeout = ObjectProperty(evidence, "timeout_entry");
        Assert.Equal(0.05, NumberProperty(timeout, "timeout_s"));
        Assert.True(BooleanProperty(timeout, "disposed"));
        Assert.NotEmpty(StringProperty(timeout, "native_failure_type"));
        Assert.Equal("ProviderException", StringProperty(timeout, "terminal_failure_type"));
        var attempt = Assert.IsType<JsonObject>(ArrayProperty(evidence, "timeout_attempts").Items.Single());
        Assert.Equal("transport", StringProperty(attempt, "error_category"));
        Assert.Equal("generate", StringProperty(attempt, "error_phase"));
        var mapping = ObjectProperty(evidence, "timeout_mapping");
        Assert.True(BooleanProperty(mapping, "native_to_provider"));
        Assert.True(BooleanProperty(mapping, "provider_to_attempt"));
        AssertLifecycle(ArrayProperty(evidence, "default_lifecycle"), 1, ["created", "configured", "entered", "cleanup_start", "cleanup_end", "exited", "disposed"]);
        AssertLifecycle(ArrayProperty(evidence, "explicit_lifecycle"), 1, ["created", "configured", "entered", "cleanup_start", "cleanup_end", "exited", "disposed"]);
        AssertLifecycle(ArrayProperty(evidence, "timeout_lifecycle"), 1, ["created", "configured", "entered", "expired", "cleanup_start", "cleanup_end", "exited", "disposed"]);
    }

    [Fact]
    public async Task Reset_proof_retains_four_fresh_contexts_roles_and_repair_links()
    {
        var evidence = AssertPassing(Reset, await NativeProofs.RunAsync(Reset));
        var entries = ArrayProperty(evidence, "entries").Items.Select(Assert.IsType<JsonObject>).ToArray();

        Assert.Equal(4, entries.Length);
        Assert.Equal(["original", "correction", "original", "correction"], entries.Select(entry => StringProperty(entry, "role")));
        Assert.Equal(4, entries.Select(entry => StringProperty(entry, "context_id")).Distinct(StringComparer.Ordinal).Count());
        Assert.All(entries, entry =>
        {
            Assert.Equal(7.25, NumberProperty(entry, "timeout_s"));
            Assert.Equal(new BigInteger(4096), IntegerProperty(entry, "max_response_bytes"));
            Assert.Equal(7.25, NumberProperty(entry, "effective_timeout_s"));
            Assert.True(BooleanProperty(entry, "disposed"));
        });

        var assessments = ArrayProperty(evidence, "assessments").Items.Select(Assert.IsType<JsonObject>).ToArray();
        var repairs = ArrayProperty(evidence, "repairs").Items.Select(Assert.IsType<JsonObject>).ToArray();
        Assert.Equal(3, assessments.Length);
        Assert.Equal([new BigInteger(1), new BigInteger(3), new BigInteger(4)], assessments.Select(assessment => IntegerProperty(assessment, "source_entry_ordinal")));
        Assert.True(BooleanProperty(assessments[2], "valid"));
        Assert.Equal(2, repairs.Length);
        var invalidAssessmentIds = assessments.Take(2).Select(assessment => StringProperty(assessment, "assessment_id")).ToArray();
        Assert.All(repairs, repair => Assert.Contains(StringProperty(repair, "assessment_id"), invalidAssessmentIds));
        var outcome = ObjectProperty(evidence, "outcome");
        Assert.Equal("{\"age\":7}", StringProperty(outcome, "result_text"));
        Assert.IsType<JsonNull>(ValueProperty(outcome, "terminal_type"));
        Assert.Equal(new BigInteger(1), IntegerProperty(outcome, "repair_attempts"));
        var structured = ObjectProperty(outcome, "structured");
        Assert.Equal(new BigInteger(7), IntegerProperty(structured, "age"));
        var lifecycle = ArrayProperty(evidence, "lifecycle");
        foreach (var ordinal in Enumerable.Range(1, 4))
        {
            AssertLifecycle(lifecycle, ordinal, ["created", "configured", "entered", "cleanup_start", "cleanup_end", "exited", "disposed"]);
        }

        var lifecycleEntries = lifecycle.Items.Select(Assert.IsType<JsonObject>).ToArray();
        for (var index = 1; index < 4; index++)
        {
            var priorDisposed = LifecycleSequence(lifecycleEntries, index, "disposed");
            var nextCreated = LifecycleSequence(lifecycleEntries, index + 1, "created");
            Assert.True(priorDisposed < nextCreated, $"Entry {index} must dispose before entry {index + 1} is created.");
        }

        var repairWires = ArrayProperty(evidence, "repair_wire_bindings").Items.Select(Assert.IsType<JsonObject>).ToArray();
        Assert.Equal(2, repairWires.Length);
        Assert.Equal(repairs.Select(repair => StringProperty(repair, "assessment_id")), repairWires.Select(repair => StringProperty(repair, "assessment_id")));
        Assert.All(repairWires, repair =>
        {
            Assert.Equal("{\"name\":\"x\"}", StringProperty(repair, "response_text"));
            Assert.NotEmpty(ArrayProperty(repair, "messages").Items);
        });
    }

    [Fact]
    public async Task Caller_cancellation_propagates_instead_of_becoming_a_proof_verdict()
    {
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
            await NativeProofs.RunAsync(Concurrent, cancellation.Token));
    }

    [Fact]
    public void Unavailable_capture_guard_fails_closed_before_evidence_projection()
    {
        var capture = new AnyInfer.Internal.OperationCapture();
        _ = new AnyInfer.Internal.OperationContext(capture);
        _ = new AnyInfer.Internal.OperationContext(capture);

        Assert.False(capture.IsAvailable);
        Assert.Throws<ObservationUnavailableException>(() => NativeProofs.RequireAvailable(capture, "test evidence"));
    }

    [Fact]
    public async Task Capture_shape_and_disjointness_helpers_reject_wrong_or_missing_native_identity()
    {
        var emptyFirst = new AnyInfer.Internal.OperationCapture();
        var emptySecond = new AnyInfer.Internal.OperationCapture();

        Assert.False(NativeProofs.HasConcurrentShapeForTest(emptyFirst, emptySecond));
        Assert.True(NativeProofs.CapturesAreDisjointForTest(emptyFirst, emptySecond));
        Assert.False(NativeProofs.HasCausalRepairForTest(emptyFirst));

        var first = await CreateRealRepairCaptureAsync();
        var second = await CreateRealRepairCaptureAsync();
        Assert.True(NativeProofs.CapturesAreDisjointForTest(first, second));

        var observed = NativeProofs.ObserveCaptureForTest(first);
        AssertSameElements(first.Entries, observed.Entries);
        AssertSameElements(first.Assessments, observed.Assessments);
        AssertSameElements(first.Repairs, observed.Repairs);
        AssertSameElements(first.Lifecycle, observed.Lifecycle);

        var consistent = CopyRepairCapture(first, Assert.Single(first.Repairs));
        Assert.True(NativeProofs.HasCausalRepairForTest(consistent));
        Assert.False(NativeProofs.CapturesAreDisjointForTest(first, consistent));
    }

    [Fact]
    public async Task Causal_repair_guard_accepts_a_real_capture_then_rejects_isolated_response_and_wire_mutations()
    {
        var capture = await CreateRealRepairCaptureAsync();
        var preparation = Assert.Single(capture.Repairs);
        Assert.True(NativeProofs.HasCausalRepairForTest(capture));

        var consistent = CopyRepairCapture(capture, preparation);
        Assert.True(NativeProofs.HasCausalRepairForTest(consistent));
        Assert.False(NativeProofs.CapturesAreDisjointForTest(consistent, consistent));

        var staleResponse = new RepairPreparation(
            preparation.Assessment,
            "{\"age\":999}",
            preparation.OriginalMessages,
            preparation.Messages);
        Assert.False(NativeProofs.HasCausalRepairForTest(CopyRepairCapture(capture, staleResponse)));

        var rewrittenWire = new RepairPreparation(
            preparation.Assessment,
            preparation.ResponseText,
            preparation.OriginalMessages,
            [new Message("user", [new Text("rewritten repair prompt")])]);
        Assert.False(NativeProofs.HasCausalRepairForTest(CopyRepairCapture(capture, rewrittenWire)));
    }

    private static JsonObject AssertPassing(string recipeRef, NativeProofResult result)
    {
        Assert.Equal("pass", result.Verdict);
        Assert.Equal(recipeRef, StringProperty(result.Evidence, "recipe_ref"));
        Assert.NotEmpty(result.Evidence.Properties);
        return result.Evidence;
    }

    private static void AssertUnavailableControl(JsonObject control)
    {
        Assert.Equal(JsonWriter.Write(ObjectProperty(control, "normal_outcome")), JsonWriter.Write(ObjectProperty(control, "unavailable_outcome")));
        Assert.True(BooleanProperty(control, "same_native_outcome"));
        Assert.True(BooleanProperty(control, "unavailable"));
        Assert.True(BooleanProperty(control, "guard_rejected"));
        Assert.NotEmpty(ArrayProperty(control, "reasons").Items);
    }

    private static void AssertLifecycle(JsonArray lifecycle, int ordinal, IReadOnlyList<string> names)
    {
        var entries = lifecycle.Items
            .Select(Assert.IsType<JsonObject>)
            .Where(item => IntegerProperty(item, "entry_ordinal") == new BigInteger(ordinal))
            .ToArray();
        Assert.Equal(names, entries.Select(item => StringProperty(item, "name")));
        Assert.True(entries.Zip(entries.Skip(1), (first, second) => IntegerProperty(first, "sequence") < IntegerProperty(second, "sequence")).All(static ordered => ordered));
    }

    private static BigInteger LifecycleSequence(IEnumerable<JsonObject> lifecycle, int ordinal, string name) =>
        IntegerProperty(lifecycle.Single(item => IntegerProperty(item, "entry_ordinal") == new BigInteger(ordinal) && string.Equals(StringProperty(item, "name"), name, StringComparison.Ordinal)), "sequence");

    private static async Task<OperationCapture> CreateRealRepairCaptureAsync()
    {
        var script = Assert.IsType<JsonArray>(JsonReader.Read(Encoding.UTF8.GetBytes("""
            [
              {"events":[{"text":"{}"},{"final":{"finish_reason":"stop"}}]},
              {"events":[{"text":"{\"age\":7}"},{"final":{"finish_reason":"stop"}}]}
            ]
            """)));
        var capture = new OperationCapture();
        await using var client = new AsyncClient([new ProviderRegistration("proof", FixtureAdapter.Create(script))], new VirtualClock(0));
        var schema = new JsonObject([
            new JsonProperty("type", new JsonString("object")),
            new JsonProperty("required", new JsonArray([new JsonString("age")])),
            new JsonProperty("properties", new JsonObject([
                new JsonProperty("age", new JsonObject([
                    new JsonProperty("type", new JsonString("integer")),
                ])),
            ])),
        ]);
        var request = new GenerationRequest(
            [new Message("user", [new Text("repair proof")])],
            new Route(["proof:model"], new Retry(MaxAttempts: 2, BackoffBaseS: 0, BackoffMaxS: 0)),
            repair: new Repair(1),
            schema: new SchemaSpec(schema, "response"),
            stream: false);

        var result = await client.GenerateAsync(request, capture);
        Assert.Equal("{\"age\":7}", result.Text);
        return capture;
    }

    private static OperationCapture CopyRepairCapture(OperationCapture source, RepairPreparation preparation)
    {
        var capture = new OperationCapture();
        var operationId = Assert.Single(source.Entries.Select(static entry => entry.OperationId).Distinct());
        capture.BindOperation(operationId);
        foreach (var sourceEntry in source.Entries)
        {
            var repairAssessment = sourceEntry.Role == EntryRole.Correction ? preparation.Assessment : null;
            var entry = new EntryContext(
                sourceEntry.OperationId,
                sourceEntry.Ordinal,
                sourceEntry.Role,
                sourceEntry.Request,
                repairAssessment,
                capture);
            foreach (var adapterEvent in sourceEntry.AdapterEvents)
            {
                entry.RetainAdapterEvent(adapterEvent);
            }

            capture.RecordEntry(entry);
        }

        foreach (var assessment in source.Assessments)
        {
            capture.RecordAssessment(assessment);
        }

        capture.RecordRepair(operationId, preparation);
        return capture;
    }

    private static bool PathEquals(JsonArray path, params string[] expected) =>
        path.Items.OfType<JsonString>().Select(static item => item.Value).SequenceEqual(expected) && path.Items.Count == expected.Length;

    private static void AssertSameElements<T>(IReadOnlyList<T> expected, IReadOnlyList<T> actual)
        where T : class
    {
        Assert.Equal(expected.Count, actual.Count);
        foreach (var pair in expected.Zip(actual))
        {
            Assert.Same(pair.First, pair.Second);
        }
    }

    private static void AssertOrdinary(JsonValue value)
    {
        switch (value)
        {
            case JsonNull or JsonBoolean or JsonString or JsonInteger:
                return;
            case JsonNumber number:
                Assert.True(double.IsFinite(number.Value), "Proof evidence must contain only finite JSON numbers.");
                return;
            case JsonArray array:
                foreach (var item in array.Items)
                {
                    AssertOrdinary(item);
                }

                return;
            case JsonObject obj:
                foreach (var property in obj.Properties)
                {
                    AssertOrdinary(property.Value);
                }

                return;
            default:
                throw new Xunit.Sdk.XunitException("Proof evidence contained a non-ordinary JSON value.");
        }
    }

    private static JsonValue ValueProperty(JsonObject source, string name) =>
        source.TryGetValue(name, out var value)
            ? value
            : throw new Xunit.Sdk.XunitException($"Missing evidence property '{name}'.");

    private static JsonObject ObjectProperty(JsonObject source, string name) => Assert.IsType<JsonObject>(ValueProperty(source, name));

    private static JsonArray ArrayProperty(JsonObject source, string name) => Assert.IsType<JsonArray>(ValueProperty(source, name));

    private static string StringProperty(JsonObject source, string name) => Assert.IsType<JsonString>(ValueProperty(source, name)).Value;

    private static bool BooleanProperty(JsonObject source, string name) => Assert.IsType<JsonBoolean>(ValueProperty(source, name)).Value;

    private static BigInteger IntegerProperty(JsonObject source, string name) => Assert.IsType<JsonInteger>(ValueProperty(source, name)).Value;

    private static double NumberProperty(JsonObject source, string name) => Assert.IsType<JsonNumber>(ValueProperty(source, name)).Value;
}
