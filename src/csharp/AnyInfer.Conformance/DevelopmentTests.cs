using System.Numerics;
using System.Text;
using AnyInfer;
using AnyInfer.Core;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Conformance;

public sealed class DevelopmentTests : IDisposable
{
    private readonly List<string> _temporaryRoots = [];

    [Fact]
    public async Task Every_inventory_ordered_core_fixture_runs_from_input_only_and_compares_as_a_native_pass()
    {
        var assets = ReadCopiedAssets();
        var fixtures = CoreFixtures(assets);
        Assert.Equal(85, fixtures.Count);
        Assert.Equal(
            assets.Cases.Where(static item => item.Kind == FixtureKind.Fixture &&
                item.RelativePath?.StartsWith("specification/fixtures/core-generation/", StringComparison.Ordinal) == true)
                .Select(static item => item.Id),
            fixtures.Select(static item => item.Case.Id));

        var comparisons = new List<DevelopmentComparison>();
        var runs = new List<NativeRun>();
        foreach (var fixture in fixtures)
        {
            var input = Assert.IsType<CoreFixtureInput>(fixture.Input);
            var run = await NativeRunner.RunAsync(fixture.Case.Id, input);
            runs.Add(run);
            comparisons.Add(Comparison.Compare(fixture, run));
        }

        var failures = comparisons.Select((comparison, index) => (comparison, index))
            .Where(static pair => !string.Equals(pair.comparison.Verdict, "pass", StringComparison.Ordinal))
            .Select(pair => fixtures[pair.index].Case.Id + "=" + pair.comparison.Verdict + ":" + Bounded(pair.comparison.Detail))
            .ToArray();
        Assert.True(failures.Length == 0, string.Join("; ", failures));
        Assert.Equal(9, fixtures.Count(static fixture => fixture.Case.Extension is not null));
        Assert.All(
            fixtures.Zip(runs).Where(static pair => pair.First.Case.Extension is not null),
            static pair => Assert.Equal(0, pair.Second.AdapterCallCount));
    }

    [Fact]
    public async Task Runner_retains_real_deliberate_cancellation_and_external_cancellation_propagates()
    {
        var assets = ReadCopiedAssets();
        var fixture = Fixture(assets, "streaming/cancel-mid-stream");
        var input = Assert.IsType<CoreFixtureInput>(fixture.Input);

        var deliberate = await NativeRunner.RunAsync(fixture.Case.Id, input);
        Assert.True(deliberate.DeliberateCancellation);
        Assert.IsAssignableFrom<OperationCanceledException>(deliberate.TerminalException);
        Assert.Equal(new BigInteger(3), new BigInteger(deliberate.Events.Count));
        Assert.NotEmpty(deliberate.Capture.Entries);
        Assert.All(deliberate.Capture.Entries, static entry => Assert.True(entry.Timeout.IsDisposed));
        Assert.Null(deliberate.Result);
        Assert.DoesNotContain(deliberate.Events, static item => item is StreamEndedEvent);
        Assert.Equal("pass", Comparison.Compare(fixture, deliberate).Verdict);

        using var external = new CancellationTokenSource();
        external.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
            await NativeRunner.RunAsync(fixture.Case.Id, input, external.Token));
    }

    [Fact]
    public async Task Expected_only_changes_affect_comparison_but_never_native_input_or_execution_facts()
    {
        var assets = ReadCopiedAssets();
        var fixture = Fixture(assets, "streaming/buffered-equals-streamed");
        var input = Assert.IsType<CoreFixtureInput>(fixture.Input);
        var run = await NativeRunner.RunAsync(fixture.Case.Id, input);
        Assert.Equal("pass", Comparison.Compare(fixture, run).Verdict);

        var alteredExpected = WithProperty(CloneObject(fixture.Expected), "status", new JsonString("not-observed"));
        var altered = new FixtureDocument(fixture.Case, fixture.Input, alteredExpected);
        var comparison = Comparison.Compare(altered, run);

        Assert.NotEqual("pass", comparison.Verdict);
        Assert.Same(input, run.Input);
        Assert.NotEmpty(run.Events);
        Assert.NotNull(run.Mirror);
        Assert.NotSame(run.Capture, run.Mirror!.Capture);
    }

    [Fact]
    public async Task Projection_fails_closed_for_missing_or_inconsistent_causal_capture_and_fresh_mirror_identity()
    {
        var assets = ReadCopiedAssets();
        var repair = Fixture(assets, "repair/invalid-then-valid");
        var repairRun = await NativeRunner.RunAsync(repair.Case.Id, Assert.IsType<CoreFixtureInput>(repair.Input));
        var repairProjection = Projection.Project(repairRun);
        Assert.True(repairProjection.TryGetValue("calls", out var calls));
        Assert.Equal(2, Assert.IsType<JsonArray>(calls).Items.Count);
        var preparation = Assert.Single(repairRun.Capture.Repairs);
        var assessment = preparation.Assessment;
        Assert.Contains(repairRun.Capture.Assessments, candidate => ReferenceEquals(candidate, assessment));
        Assert.Equal(1, assessment.SourceEntryOrdinal);
        Assert.Same(assessment, repairRun.Capture.Entries[1].RepairAssessment);
        Assert.Throws<ObservationUnavailableException>(() => Projection.Project(repairRun with
        {
            AdapterCallCount = repairRun.AdapterCallCount + 1,
        }));

        var mirrored = Fixture(assets, "streaming/buffered-equals-streamed");
        var mirrorRun = await NativeRunner.RunAsync(mirrored.Case.Id, Assert.IsType<CoreFixtureInput>(mirrored.Input));
        Assert.NotNull(mirrorRun.Mirror);
        Assert.NotSame(mirrorRun.Capture, mirrorRun.Mirror!.Capture);
        Assert.NotEqual(mirrorRun.ConsumeMode, mirrorRun.Mirror.ConsumeMode);
        Assert.Throws<ObservationUnavailableException>(() => Projection.Project(mirrorRun with { Mirror = mirrorRun }));
    }

    [Fact]
    public async Task Comparison_fails_closed_for_missing_or_divergent_required_mirror_facts_and_fabricated_cancellation()
    {
        var assets = ReadCopiedAssets();
        var mirrorFixture = Fixture(assets, "streaming/buffered-equals-streamed");
        var mirrored = await NativeRunner.RunAsync(mirrorFixture.Case.Id, Assert.IsType<CoreFixtureInput>(mirrorFixture.Input));
        var mirror = Assert.IsType<NativeRun>(mirrored.Mirror);

        Assert.NotEqual("pass", Comparison.Compare(mirrorFixture, mirrored with { Mirror = null }).Verdict);
        Assert.NotEqual("pass", Comparison.Compare(mirrorFixture, mirrored with { Mirror = mirror with { ConsumeMode = mirrored.ConsumeMode } }).Verdict);
        Assert.NotEqual("pass", Comparison.Compare(mirrorFixture, mirrored with { Mirror = mirror with { CaseId = "copied/case-id" } }).Verdict);
        Assert.NotEqual("pass", Comparison.Compare(mirrorFixture, mirrored with { Mirror = mirror with { AdapterCallCount = mirror.AdapterCallCount + 1 } }).Verdict);

        var cancelledFixture = Fixture(assets, "streaming/cancel-mid-stream");
        var cancelled = await NativeRunner.RunAsync(cancelledFixture.Case.Id, Assert.IsType<CoreFixtureInput>(cancelledFixture.Input));
        Assert.NotEqual("pass", Comparison.Compare(cancelledFixture, cancelled with { TerminalException = null }).Verdict);
        var actualCancellation = Assert.IsAssignableFrom<OperationCanceledException>(cancelled.TerminalException);
        var propagated = Assert.Throws<OperationCanceledException>(() =>
            Comparison.Compare(cancelledFixture, cancelled with { DeliberateCancellation = false }));
        Assert.Same(actualCancellation, propagated);
    }

    [Fact]
    public async Task Comparison_rejects_partial_terminal_shapes_and_preserves_typed_numeric_controls()
    {
        var assets = ReadCopiedAssets();
        var resultFixture = CoreFixtures(assets).First(static fixture =>
            fixture.Expected.TryGetValue("outcome", out var outcome) && outcome is JsonObject objectValue && objectValue.TryGetValue("result", out _));
        var resultRun = await NativeRunner.RunAsync(resultFixture.Case.Id, Assert.IsType<CoreFixtureInput>(resultFixture.Input));

        var partialResult = CloneObject(resultFixture.Expected);
        var partialResultOutcome = Assert.IsType<JsonObject>(partialResult.Properties.Single(static property => property.Name == "outcome").Value);
        partialResult = WithProperty(partialResult, "outcome", WithProperty(partialResultOutcome, "result", new JsonObject([])));
        Assert.NotEqual("pass", Comparison.Compare(new FixtureDocument(resultFixture.Case, resultFixture.Input, partialResult), resultRun).Verdict);

        var errorFixture = CoreFixtures(assets).First(static fixture =>
            fixture.Expected.TryGetValue("outcome", out var outcome) && outcome is JsonObject objectValue && objectValue.TryGetValue("error", out _));
        var errorRun = await NativeRunner.RunAsync(errorFixture.Case.Id, Assert.IsType<CoreFixtureInput>(errorFixture.Input));
        var partialError = CloneObject(errorFixture.Expected);
        var partialErrorOutcome = Assert.IsType<JsonObject>(partialError.Properties.Single(static property => property.Name == "outcome").Value);
        partialError = WithProperty(partialError, "outcome", WithProperty(partialErrorOutcome, "error", new JsonObject([
            new JsonProperty("category", new JsonString("transport")),
        ])));
        Assert.NotEqual("pass", Comparison.Compare(new FixtureDocument(errorFixture.Case, errorFixture.Input, partialError), errorRun).Verdict);

        var retryFixture = Fixture(assets, "routing/backoff-cap");
        var retryInput = Assert.IsType<CoreFixtureInput>(retryFixture.Input);
        var halfSecondRoute = CloneObject(retryInput.Route);
        var retry = Assert.IsType<JsonObject>(halfSecondRoute.Properties.Single(static property => property.Name == "retry").Value);
        halfSecondRoute = WithProperty(halfSecondRoute, "retry", WithProperty(retry, "backoff_max_s", new JsonNumber(0.5d)));
        var halfSecondRun = await NativeRunner.RunAsync(retryFixture.Case.Id, retryInput with { Route = halfSecondRoute });
        var halfSecondObservation = Projection.Project(halfSecondRun);
        var advances = Assert.IsType<JsonArray>(halfSecondObservation.Properties.Single(static property => property.Name == "clock_advances_ms").Value);
        Assert.Equal(new BigInteger(500), Assert.IsType<JsonInteger>(Assert.Single(advances.Items)).Value);

        var successful = Fixture(assets, "repair/valid-no-correction");
        var successfulInput = Assert.IsType<CoreFixtureInput>(successful.Input);
        var numericTimeout = WithProperty(CloneObject(successfulInput.Request), "timeout_s", new JsonNumber(1.5d));
        _ = await NativeRunner.RunAsync(successful.Case.Id, successfulInput with { Request = numericTimeout });

        var boundedRequest = WithProperty(
            WithProperty(CloneObject(successfulInput.Request), "timeout_s", new JsonInteger(2)),
            "max_response_bytes",
            new JsonInteger(12));
        var boundedRun = await NativeRunner.RunAsync(successful.Case.Id, successfulInput with { Request = boundedRequest });
        Assert.Equal(2d, Assert.Single(boundedRun.Capture.Entries).Request.TimeoutS);
        Assert.Equal(12, Assert.Single(boundedRun.Capture.Entries).Request.MaxResponseBytes);
        var boundedExpected = CloneObject(successful.Expected);
        var boundedCalls = Assert.IsType<JsonArray>(boundedExpected.Properties.Single(static property => property.Name == "calls").Value);
        var boundedCall = Assert.IsType<JsonObject>(boundedCalls.Items[0]);
        boundedCall = WithProperty(WithProperty(boundedCall, "timeout_s", new JsonInteger(2)), "max_response_bytes", new JsonInteger(12));
        boundedExpected = WithProperty(boundedExpected, "calls", WithItem(boundedCalls, 0, boundedCall));
        var boundedFixture = new FixtureDocument(successful.Case, successfulInput with { Request = boundedRequest }, boundedExpected);
        Assert.Equal("pass", Comparison.Compare(boundedFixture, boundedRun).Verdict);

        var floatByteExpected = WithProperty(
            boundedExpected,
            "calls",
            WithItem(boundedCalls, 0, WithProperty(boundedCall, "max_response_bytes", new JsonNumber(12d))));
        Assert.NotEqual("pass", Comparison.Compare(boundedFixture with { Expected = floatByteExpected }, boundedRun).Verdict);

        var duplicateFixture = Fixture(assets, "extraction/duplicate-key-last-value-first-position");
        var duplicateRun = await NativeRunner.RunAsync(duplicateFixture.Case.Id, Assert.IsType<CoreFixtureInput>(duplicateFixture.Input));
        var duplicateObservation = Projection.Project(duplicateRun);
        var duplicateOutcome = Assert.IsType<JsonObject>(duplicateObservation.Properties.Single(static property => property.Name == "outcome").Value);
        var duplicateResult = Assert.IsType<JsonObject>(duplicateOutcome.Properties.Single(static property => property.Name == "result").Value);
        var duplicateStructured = Assert.IsType<JsonObject>(duplicateResult.Properties.Single(static property => property.Name == "structured").Value);
        Assert.Equal(["z", "a"], duplicateStructured.Properties.Select(static property => property.Name));
        Assert.Equal(new BigInteger(3), Assert.IsType<JsonInteger>(duplicateStructured.Properties[0].Value).Value);
        Assert.Equal("pass", Comparison.Compare(duplicateFixture, duplicateRun).Verdict);
    }

    [Fact]
    public async Task Comparison_rejects_a_real_reordered_duplicate_key_response_even_when_schema_values_match()
    {
        var assets = ReadCopiedAssets();
        var fixture = Fixture(assets, "extraction/duplicate-key-last-value-first-position");
        var input = Assert.IsType<CoreFixtureInput>(fixture.Input);
        var adapter = CloneObject(input.Adapter);
        var script = Assert.IsType<JsonArray>(adapter.Properties.Single(static property => property.Name == "script").Value);
        var firstEntry = Assert.IsType<JsonObject>(script.Items[0]);
        var events = Assert.IsType<JsonArray>(firstEntry.Properties.Single(static property => property.Name == "events").Value);
        var replacementEvent = WithProperty(Assert.IsType<JsonObject>(events.Items[0]), "text", new JsonString("{\"a\":2,\"z\":3}"));
        var replacementEvents = WithItem(events, 0, replacementEvent);
        var replacementEntry = WithProperty(firstEntry, "events", replacementEvents);
        adapter = WithProperty(adapter, "script", WithItem(script, 0, replacementEntry));

        var reordered = await NativeRunner.RunAsync(fixture.Case.Id, input with { Adapter = adapter });
        Assert.NotEqual("pass", Comparison.Compare(fixture, reordered).Verdict);
    }

    [Fact]
    public async Task Comparison_allows_omitted_null_usage_update_members_but_rejects_omitted_known_members()
    {
        var assets = ReadCopiedAssets();
        var fixture = Fixture(assets, "streaming/reported-total-not-recomputed");
        var run = await NativeRunner.RunAsync(fixture.Case.Id, Assert.IsType<CoreFixtureInput>(fixture.Input));

        var expected = CloneObject(fixture.Expected);
        var events = Assert.IsType<JsonArray>(expected.Properties.Single(static property => property.Name == "events").Value);
        var usageEventIndex = events.Items
            .Select((item, index) => (item: Assert.IsType<JsonObject>(item), index))
            .Single(static pair => pair.item.TryGetValue("usage_update", out _)).index;
        var usageEvent = Assert.IsType<JsonObject>(events.Items[usageEventIndex]);
        var usage = Assert.IsType<JsonObject>(usageEvent.Properties.Single(static property => property.Name == "usage_update").Value);
        var absentNulls = WithoutProperties(usage, "cache_read_tokens", "cache_write_tokens", "reasoning_tokens");
        var nullOmittedExpected = WithProperty(
            expected,
            "events",
            WithItem(events, usageEventIndex, WithProperty(usageEvent, "usage_update", absentNulls)));
        Assert.Equal("pass", Comparison.Compare(fixture with { Expected = nullOmittedExpected }, run).Verdict);

        var knownOmittedExpected = WithProperty(
            expected,
            "events",
            WithItem(events, usageEventIndex, WithProperty(usageEvent, "usage_update", WithoutProperties(usage, "input_tokens"))));
        Assert.NotEqual("pass", Comparison.Compare(fixture with { Expected = knownOmittedExpected }, run).Verdict);
    }

    [Fact]
    public async Task Schema_prompt_marker_is_not_interpreted_in_caller_user_content_even_when_its_literal_text_matches()
    {
        var assets = ReadCopiedAssets();
        var fixture = Fixture(assets, "repair/valid-no-correction");
        var input = Assert.IsType<CoreFixtureInput>(fixture.Input);
        var schema = Assert.IsType<JsonObject>(input.Request.Properties.Single(static property => property.Name == "schema").Value);
        var renderedSchema = SchemaPromptRenderer.Render(schema);
        var requestMessages = Assert.IsType<JsonArray>(input.Request.Properties.Single(static property => property.Name == "messages").Value);
        var sourceUser = Assert.IsType<JsonObject>(requestMessages.Items.Single());
        var literalRequest = WithProperty(
            input.Request,
            "messages",
            WithItem(requestMessages, 0, WithProperty(sourceUser, "text", new JsonString(renderedSchema))));
        var literalInput = input with { Request = literalRequest };
        var run = await NativeRunner.RunAsync(fixture.Case.Id, literalInput);

        var literalExpected = CloneObject(fixture.Expected);
        var calls = Assert.IsType<JsonArray>(literalExpected.Properties.Single(static property => property.Name == "calls").Value);
        var call = Assert.IsType<JsonObject>(calls.Items.Single());
        var messages = Assert.IsType<JsonArray>(call.Properties.Single(static property => property.Name == "messages").Value);
        var userIndex = messages.Items
            .Select((item, index) => (item: Assert.IsType<JsonObject>(item), index))
            .Single(static pair => Assert.IsType<JsonString>(pair.item.Properties.Single(static property => property.Name == "role").Value).Value == "user")
            .index;
        var user = Assert.IsType<JsonObject>(messages.Items[userIndex]);
        var literalMessages = WithItem(messages, userIndex, WithProperty(user, "text", new JsonString(renderedSchema)));
        literalExpected = WithProperty(literalExpected, "calls", WithItem(calls, 0, WithProperty(call, "messages", literalMessages)));
        var literalFixture = new FixtureDocument(fixture.Case, literalInput, literalExpected);
        Assert.Equal("pass", Comparison.Compare(literalFixture, run).Verdict);

        var typedUser = WithProperty(
            user,
            "text",
            new JsonArray([
                new JsonObject([new JsonProperty("$schema_prompt", new JsonBoolean(true))]),
            ]));
        var typedMessages = WithItem(messages, userIndex, typedUser);
        var typedExpected = WithProperty(literalExpected, "calls", WithItem(calls, 0, WithProperty(call, "messages", typedMessages)));
        Assert.NotEqual("pass", Comparison.Compare(literalFixture with { Expected = typedExpected }, run).Verdict);
    }

    [Fact]
    public async Task Projection_rejects_foreign_capture_ownership_stale_assessments_and_duplicate_preparations()
    {
        var assets = ReadCopiedAssets();
        var fixture = Fixture(assets, "repair/invalid-then-valid");
        var run = await NativeRunner.RunAsync(fixture.Case.Id, Assert.IsType<CoreFixtureInput>(fixture.Input));
        var preparation = Assert.Single(run.Capture.Repairs);
        var assessment = preparation.Assessment;
        Assert.Contains(run.Capture.Assessments, candidate => ReferenceEquals(candidate, assessment));
        Assert.Equal(1, assessment.SourceEntryOrdinal);

        var foreign = CopyCapture(run, assessments: [assessment], preparations: [preparation]);
        Assert.Throws<ObservationUnavailableException>(() => Projection.Project(run with { Capture = foreign }));

        var consistent = CopyConsistentRepairCapture(run, assessment, preparation);
        Assert.NotNull(Projection.Project(run with { Capture = consistent }));

        var stale = new NativeAssessment(
            assessment.OperationId,
            sourceEntryOrdinal: 0,
            assessment.Kind,
            assessment.Structured,
            assessment.AllFindings,
            assessment.SelectedFindings);
        var stalePreparation = new RepairPreparation(
            stale,
            preparation.ResponseText,
            preparation.OriginalMessages,
            preparation.Messages);
        var staleCapture = CopyConsistentRepairCapture(run, stale, stalePreparation);
        Assert.Throws<ObservationUnavailableException>(() => Projection.Project(run with { Capture = staleCapture }));

        var duplicatePreparation = CopyConsistentRepairCapture(run, assessment, preparation, duplicatePreparation: true);
        Assert.Throws<ObservationUnavailableException>(() => Projection.Project(run with { Capture = duplicatePreparation }));

        var originalWithRepair = CopyConsistentRepairCapture(
            run,
            assessment,
            preparation,
            originalRepairAssessment: assessment);
        Assert.Throws<ObservationUnavailableException>(() => Projection.Project(run with { Capture = originalWithRepair }));
    }

    [Fact]
    public async Task Comparison_rejects_bad_same_as_call_references_without_interpreting_literals_outside_typed_positions()
    {
        var assets = ReadCopiedAssets();
        var fixture = CoreFixtures(assets).First(static item => ExpectedCallCount(item) >= 2);
        var run = await NativeRunner.RunAsync(fixture.Case.Id, Assert.IsType<CoreFixtureInput>(fixture.Input));

        foreach (var invalid in new[] { "same_as_call_0", "same_as_call_2", "same_as_call_999" })
        {
            var expected = CloneObject(fixture.Expected);
            var calls = Assert.IsType<JsonArray>(expected.Properties.Single(static property => property.Name == "calls").Value);
            var replacementCall = WithProperty(Assert.IsType<JsonObject>(calls.Items[0]), "messages", new JsonString(invalid));
            expected = WithProperty(expected, "calls", WithItem(calls, 0, replacementCall));
            var comparison = Comparison.Compare(new FixtureDocument(fixture.Case, fixture.Input, expected), run);
            Assert.Equal("error", comparison.Verdict);
        }

        var literal = Fixture(assets, "validation/literal-reserved-key-objects");
        var literalRun = await NativeRunner.RunAsync(literal.Case.Id, Assert.IsType<CoreFixtureInput>(literal.Input));
        Assert.Equal("pass", Comparison.Compare(literal, literalRun).Verdict);
    }

    [Fact]
    public async Task Development_document_is_unqualified_inventory_ordered_and_explicit_about_unavailable_rows()
    {
        var assets = ReadCopiedAssets();
        var document = await ReportWriter.RunDevelopmentAsync(assets);

        Assert.Equal(BigInteger.Zero, Assert.IsType<JsonInteger>(document.Properties.Single(static property => property.Name == "development_version").Value).Value);
        Assert.Equal("DEVELOPMENT/UNRELEASED", Assert.IsType<JsonString>(document.Properties.Single(static property => property.Name == "status").Value).Value);
        Assert.Equal("all-released-cases", Assert.IsType<JsonString>(document.Properties.Single(static property => property.Name == "available_subset").Value).Value);
        Assert.DoesNotContain(document.Properties, static property => property.Name is "report_version" or "extensions" or "implementation");

        var cases = Assert.IsType<JsonArray>(document.Properties.Single(static property => property.Name == "cases").Value);
        var unavailable = Assert.IsType<JsonArray>(document.Properties.Single(static property => property.Name == "unavailable").Value);
        Assert.Equal(102, cases.Items.Count);
        Assert.Empty(unavailable.Items);
        Assert.Equal(
            assets.Cases.Select(static item => item.Id),
            cases.Items.Select(static item => Assert.IsType<JsonString>(Assert.IsType<JsonObject>(item).Properties.Single(static property => property.Name == "id").Value).Value));
        var counts = Assert.IsType<JsonObject>(document.Properties.Single(static property => property.Name == "counts").Value);
        Assert.Equal(new BigInteger(102), Assert.IsType<JsonInteger>(counts.Properties.Single(static property => property.Name == "pass").Value).Value);
        Assert.Equal(BigInteger.Zero, Assert.IsType<JsonInteger>(counts.Properties.Single(static property => property.Name == "fail").Value).Value);
        Assert.Equal(BigInteger.Zero, Assert.IsType<JsonInteger>(counts.Properties.Single(static property => property.Name == "error").Value).Value);
        Assert.Equal(BigInteger.Zero, Assert.IsType<JsonInteger>(counts.Properties.Single(static property => property.Name == "unavailable").Value).Value);
        var nonPassing = cases.Items
            .Select(static item => Assert.IsType<JsonObject>(item))
            .Select(static item =>
            {
                var id = Assert.IsType<JsonString>(item.Properties.Single(static property => property.Name == "id").Value).Value;
                var verdict = Assert.IsType<JsonString>(item.Properties.Single(static property => property.Name == "verdict").Value).Value;
                var detail = item.TryGetValue("detail", out var detailValue) && detailValue is JsonString text ? text.Value : null;
                return (id, verdict, detail);
            })
            .Where(static item => !string.Equals(item.verdict, "pass", StringComparison.Ordinal))
            .Select(item => item.id + "=" + item.verdict + ":" + Bounded(item.detail))
            .ToArray();
        Assert.True(nonPassing.Length == 0, string.Join("; ", nonPassing));
    }

    [Fact]
    public async Task Development_output_is_utf8_without_bom_and_confined_to_the_executable_tmp_tree()
    {
        var assets = ReadCopiedAssets();
        var outputRoot = Path.Combine(FindRepositoryRoot(), ".tmp-tests");
        Directory.CreateDirectory(outputRoot);
        var output = Path.Combine(outputRoot, "development-tests-" + Guid.NewGuid().ToString("N") + ".json");

        var written = await ReportWriter.WriteDevelopmentAsync(assets, output);
        Assert.Equal(Path.GetFullPath(output), written);
        var bytes = File.ReadAllBytes(written);
        Assert.False(bytes.AsSpan().StartsWith(new byte[] { 0xef, 0xbb, 0xbf }));
        var document = Assert.IsType<JsonObject>(JsonReader.Read(bytes));
        Assert.True(document.TryGetValue("development_version", out _));
        Assert.False(document.TryGetValue("report_version", out _));

        var outside = Path.Combine(Path.GetTempPath(), "outside-development-" + Guid.NewGuid().ToString("N") + ".json");
        await Assert.ThrowsAsync<ArgumentException>(async () =>
        {
            _ = await ReportWriter.WriteDevelopmentAsync(assets, outside);
        });
    }

    [Fact]
    public async Task Development_cli_uses_only_the_selected_root_and_refuses_unproven_report_mode()
    {
        var root = Path.Combine(Path.GetTempPath(), "anyinfer-development-cli-" + Guid.NewGuid().ToString("N"));
        CopyDirectory(FindSourceSpecificationRoot(), root);
        _temporaryRoots.Add(root);
        var output = new StringWriter();
        var error = new StringWriter();

        Assert.Equal(2, await Program.RunAsync(["--root", root, "--write-report"], output, error));
        Assert.Equal(string.Empty, output.ToString());
        Assert.Equal("error provenance ." + Environment.NewLine, error.ToString());

        File.AppendAllText(Path.Combine(root, "README.md"), "tampered\n", new UTF8Encoding(false));
        output.GetStringBuilder().Clear();
        error.GetStringBuilder().Clear();
        Assert.Equal(2, await Program.RunAsync(["--root", root, "--development"], output, error));
        Assert.Equal(string.Empty, output.ToString());
        Assert.Equal("error hash_mismatch specification/README.md" + Environment.NewLine, error.ToString());
    }

    public void Dispose()
    {
        foreach (var root in _temporaryRoots)
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    private ReleaseAssets ReadCopiedAssets()
    {
        var source = FindSourceSpecificationRoot();
        var destination = Path.Combine(Path.GetTempPath(), "anyinfer-development-" + Guid.NewGuid().ToString("N"));
        CopyDirectory(source, destination);
        _temporaryRoots.Add(destination);
        return ReleaseAssetsReader.ReadAndVerify(destination, "releases/core-generation-v0.json");
    }

    private static IReadOnlyList<FixtureDocument> CoreFixtures(ReleaseAssets assets) =>
        FixtureReader.ReadFixtures(assets)
            .Where(static document => document.Input is CoreFixtureInput)
            .ToArray();

    private static FixtureDocument Fixture(ReleaseAssets assets, string id) =>
        Assert.Single(CoreFixtures(assets), fixture => string.Equals(fixture.Case.Id, id, StringComparison.Ordinal));

    private static int ExpectedCallCount(FixtureDocument fixture) =>
        Assert.IsType<JsonArray>(fixture.Expected.Properties.Single(static property => property.Name == "calls").Value).Items.Count;

    private static JsonObject CloneObject(JsonObject source) =>
        Assert.IsType<JsonObject>(JsonReader.Read(JsonWriter.Write(source)));

    private static JsonObject WithProperty(JsonObject source, string name, JsonValue value)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentException.ThrowIfNullOrEmpty(name);
        ArgumentNullException.ThrowIfNull(value);

        var replaced = false;
        var properties = source.Properties.Select(property =>
        {
            if (!string.Equals(property.Name, name, StringComparison.Ordinal))
            {
                return property;
            }

            replaced = true;
            return new JsonProperty(name, value);
        }).ToList();
        if (!replaced)
        {
            properties.Add(new JsonProperty(name, value));
        }

        return new JsonObject(properties);
    }

    private static JsonArray WithItem(JsonArray source, int index, JsonValue value)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentNullException.ThrowIfNull(value);
        if ((uint)index >= (uint)source.Items.Count)
        {
            throw new ArgumentOutOfRangeException(nameof(index));
        }

        return new JsonArray(source.Items.Select((item, current) => current == index ? value : item));
    }

    private static JsonObject WithoutProperties(JsonObject source, params string[] names)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentNullException.ThrowIfNull(names);
        return new JsonObject(source.Properties.Where(property => !names.Contains(property.Name, StringComparer.Ordinal)));
    }

    private static OperationCapture CopyCapture(
        NativeRun run,
        IReadOnlyList<AnyInfer.Schema.NativeAssessment> assessments,
        IReadOnlyList<RepairPreparation> preparations,
        IReadOnlyList<EntryContext>? entries = null)
    {
        var capture = new OperationCapture();
        var operationId = Assert.Single(run.Capture.Entries.Select(static entry => entry.OperationId).Distinct());
        capture.BindOperation(operationId);
        foreach (var entry in entries ?? run.Capture.Entries)
        {
            capture.RecordEntry(entry);
        }

        foreach (var assessment in assessments)
        {
            capture.RecordAssessment(assessment);
        }

        foreach (var preparation in preparations)
        {
            capture.RecordRepair(operationId, preparation);
        }

        return capture;
    }

    private static OperationCapture CopyConsistentRepairCapture(
        NativeRun run,
        AnyInfer.Schema.NativeAssessment correctionAssessment,
        RepairPreparation preparation,
        bool duplicatePreparation = false,
        AnyInfer.Schema.NativeAssessment? originalRepairAssessment = null)
    {
        var capture = new OperationCapture();
        var operationId = Assert.Single(run.Capture.Entries.Select(static entry => entry.OperationId).Distinct());
        capture.BindOperation(operationId);

        foreach (var source in run.Capture.Entries)
        {
            var repairAssessment = source.Role == EntryRole.Correction
                ? correctionAssessment
                : originalRepairAssessment;
            var entry = new EntryContext(
                source.OperationId,
                source.Ordinal,
                source.Role,
                source.Request,
                repairAssessment,
                capture);
            foreach (var adapterEvent in source.AdapterEvents)
            {
                entry.RetainAdapterEvent(adapterEvent);
            }

            capture.RecordEntry(entry);
        }

        capture.RecordAssessment(correctionAssessment);
        capture.RecordRepair(operationId, preparation);
        if (duplicatePreparation)
        {
            capture.RecordRepair(operationId, preparation);
        }

        return capture;
    }

    private static string Bounded(string? detail) => detail is null
        ? string.Empty
        : detail.Length <= 160 ? detail : detail[..160];

    private static string FindSourceSpecificationRoot()
    {
        foreach (var start in new[] { Directory.GetCurrentDirectory(), AppContext.BaseDirectory })
        {
            for (var current = new DirectoryInfo(start); current is not null; current = current.Parent)
            {
                var candidate = Path.Combine(current.FullName, "specification", "releases", "core-generation-v0.json");
                if (File.Exists(candidate))
                {
                    return Path.GetDirectoryName(Path.GetDirectoryName(candidate))!;
                }
            }
        }

        throw new InvalidOperationException("The source specification tree could not be located.");
    }

    private static string FindRepositoryRoot()
    {
        foreach (var start in new[] { Directory.GetCurrentDirectory(), AppContext.BaseDirectory })
        {
            for (var current = new DirectoryInfo(start); current is not null; current = current.Parent)
            {
                if (File.Exists(Path.Combine(current.FullName, "AGENTS.md")))
                {
                    return current.FullName;
                }
            }
        }

        throw new InvalidOperationException("The repository root could not be located.");
    }

    private static void CopyDirectory(string source, string destination)
    {
        Directory.CreateDirectory(destination);
        foreach (var directory in Directory.EnumerateDirectories(source, "*", SearchOption.AllDirectories))
        {
            Directory.CreateDirectory(Path.Combine(destination, Path.GetRelativePath(source, directory)));
        }

        foreach (var file in Directory.EnumerateFiles(source, "*", SearchOption.AllDirectories))
        {
            File.Copy(file, Path.Combine(destination, Path.GetRelativePath(source, file)));
        }
    }
}
