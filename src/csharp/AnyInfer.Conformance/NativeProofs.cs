using System.Runtime.CompilerServices;
using AnyInfer.Core;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;

namespace AnyInfer.Conformance;

internal sealed record NativeProofResult(string Verdict, JsonObject Evidence, string? Detail = null);

internal sealed record ProofCaptureObservation(
    IReadOnlyList<EntryContext> Entries,
    IReadOnlyList<NativeAssessment> Assessments,
    IReadOnlyList<RepairPreparation> Repairs,
    IReadOnlyList<LifecycleObservation> Lifecycle);

internal static class NativeProofs
{
    private const string ConcurrentOperations = "driver/concurrent-operations-independent";
    private const string AssessmentCompleteness = "driver/assessment-completeness";
    private const string TimeoutEffectiveDefaultExplicit = "driver/timeout-effective-default-explicit";
    private const string TimeoutResetPerEntry = "driver/timeout-reset-per-entry";

    internal static bool IsSupported(string recipeRef) => recipeRef is
        ConcurrentOperations or
        AssessmentCompleteness or
        TimeoutEffectiveDefaultExplicit or
        TimeoutResetPerEntry;

    internal static async Task<NativeProofResult> RunAsync(
        string recipeRef,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(recipeRef);
        if (!IsSupported(recipeRef))
        {
            throw new ArgumentException("The recipe is not implemented by the first native proof slice.", nameof(recipeRef));
        }

        try
        {
            return recipeRef switch
            {
                ConcurrentOperations => await RunConcurrentOperationsAsync(cancellationToken).ConfigureAwait(false),
                AssessmentCompleteness => await RunAssessmentCompletenessAsync(cancellationToken).ConfigureAwait(false),
                TimeoutEffectiveDefaultExplicit => await ProofTimeouts.RunEffectiveDefaultExplicitAsync(cancellationToken).ConfigureAwait(false),
                TimeoutResetPerEntry => await ProofTimeouts.RunResetPerEntryAsync(cancellationToken).ConfigureAwait(false),
                _ => throw new ProofHarnessException("Supported recipe dispatch was incomplete."),
            };
        }
        catch (ObservationUnavailableException exception)
        {
            return Error(recipeRef, exception.Message);
        }
        catch (ProofHarnessException exception)
        {
            return Error(recipeRef, exception.Message);
        }
    }

    internal static void RequireAvailable(OperationCapture capture, string observation)
    {
        ArgumentNullException.ThrowIfNull(capture);
        ArgumentException.ThrowIfNullOrWhiteSpace(observation);
        if (!capture.IsAvailable)
        {
            throw new ObservationUnavailableException($"{observation}: {string.Join("; ", capture.UnavailableReasons)}");
        }
    }

    internal static ProofCaptureObservation ObserveCaptureForTest(OperationCapture capture)
    {
        ArgumentNullException.ThrowIfNull(capture);
        return new ProofCaptureObservation(capture.Entries, capture.Assessments, capture.Repairs, capture.Lifecycle);
    }

    internal static bool CapturesAreDisjointForTest(OperationCapture first, OperationCapture second) =>
        CapturesAreDisjoint(first, second);

    internal static bool HasCausalRepairForTest(OperationCapture capture) => HasCausalRepair(capture);

    internal static bool HasConcurrentShapeForTest(OperationCapture valid, OperationCapture invalid) =>
        valid.Entries.Count == 1 &&
        invalid.Entries.Count == 1 &&
        valid.Assessments.Count == 1 &&
        invalid.Assessments.Count == 1;

    private static async Task<NativeProofResult> RunConcurrentOperationsAsync(CancellationToken cancellationToken)
    {
        var adapter = new ConcurrentProofAdapter();
        await using var client = CreateClient(adapter);
        var validCapture = new OperationCapture();
        var invalidCapture = new OperationCapture();

        var validTask = RunNativeAsync(client, CreateRequest("valid", ValidSchema()), validCapture, cancellationToken);
        var invalidTask = RunNativeAsync(client, CreateRequest("invalid", ValidSchema()), invalidCapture, cancellationToken);
        await adapter.WaitForBothEntriesAsync(cancellationToken).ConfigureAwait(false);
        adapter.Release();
        var outcomes = await Task.WhenAll(validTask, invalidTask).ConfigureAwait(false);

        RequireAvailable(validCapture, "valid concurrent capture");
        RequireAvailable(invalidCapture, "invalid concurrent capture");
        var beforeValid = CaptureSnapshot.Create(validCapture);
        var beforeInvalid = CaptureSnapshot.Create(invalidCapture);

        var followUpCapture = new OperationCapture();
        var followUp = await RunNativeAsync(client, CreateRequest("follow-up", schema: null), followUpCapture, cancellationToken).ConfigureAwait(false);
        RequireAvailable(followUpCapture, "schema-free follow-up capture");

        var evidence = Object(
            Property("recipe_ref", Text(ConcurrentOperations)),
            Property("overlap_observed", Bool(adapter.OverlapObserved)),
            Property("valid", OperationEvidence(validCapture, outcomes[0])),
            Property("invalid", OperationEvidence(invalidCapture, outcomes[1])),
            Property("schema_free_follow_up", OperationEvidence(followUpCapture, followUp)),
            Property("prior_captures_unchanged", Bool(beforeValid.Matches(validCapture) && beforeInvalid.Matches(invalidCapture))));

        var message = FirstMismatch(
            !adapter.OverlapObserved ? "adapter entries did not overlap" : null,
            !HasConcurrentShapeForTest(validCapture, invalidCapture) ? "concurrent runs did not retain one entry and assessment each" : null,
            HasConcurrentShapeForTest(validCapture, invalidCapture) && validCapture.Entries[0].OperationId == invalidCapture.Entries[0].OperationId ? "concurrent runs shared an operation identity" : null,
            outcomes[0].Result is null || outcomes[0].Error is not null ? "valid concurrent operation did not retain a native result" : null,
            outcomes[1].Result is not null || outcomes[1].Error is not SchemaViolationException ? "invalid concurrent operation did not retain a native schema error" : null,
            !CapturesAreDisjoint(validCapture, invalidCapture) || !CapturesAreDisjoint(validCapture, followUpCapture) || !CapturesAreDisjoint(invalidCapture, followUpCapture) ? "concurrent or follow-up captures shared retained native objects" : null,
            HasConcurrentShapeForTest(validCapture, invalidCapture) && !validCapture.Assessments[0].IsValid ? "valid operation did not retain a valid assessment" : null,
            HasConcurrentShapeForTest(validCapture, invalidCapture) && invalidCapture.Assessments[0].IsValid ? "invalid operation did not retain selected native findings" : null,
            followUp.Result is null || followUp.Error is not null || followUpCapture.Assessments.Count != 0 || followUpCapture.Repairs.Count != 0 ? "schema-free follow-up retained residual schema or repair state" : null,
            !beforeValid.Matches(validCapture) || !beforeInvalid.Matches(invalidCapture) ? "follow-up mutated an earlier operation capture" : null);
        return Result(evidence, message);
    }

    private static async Task<NativeProofResult> RunAssessmentCompletenessAsync(CancellationToken cancellationToken)
    {
        var noCandidate = await RunAssessmentCaseAsync(
            "no-candidate",
            "not JSON at all",
            ValidSchema(),
            repairAttempts: 0,
            cancellationToken).ConfigureAwait(false);
        var malformedRequired = await RunAssessmentCaseAsync(
            "late-malformed-required",
            "{\"age\":7}",
            Object(Property("type", Text("object")), Property("required", Number(17))),
            repairAttempts: 0,
            cancellationToken).ConfigureAwait(false);
        var exhaustion = await RunAssessmentCaseAsync(
            "exhaustion",
            ["{}", "{}"],
            ValidSchema(),
            repairAttempts: 1,
            cancellationToken).ConfigureAwait(false);
        var nestedDotted = await RunAssessmentCaseAsync(
            "nested-dotted",
            "{\"outer\":{\"value\":\"wrong\"},\"a.b\":\"wrong\"}",
            NestedDottedSchema(),
            repairAttempts: 0,
            cancellationToken).ConfigureAwait(false);
        var repaired = await RunAssessmentCaseAsync(
            "invalid-then-valid",
            ["{}", "{\"age\":7}"],
            ValidSchema(),
            repairAttempts: 1,
            cancellationToken).ConfigureAwait(false);

        var normalControl = await RunAssessmentCaseAsync(
            "control-normal",
            ["{}", "{\"age\":7}"],
            ValidSchema(),
            repairAttempts: 1,
            cancellationToken).ConfigureAwait(false);
        var cappedControl = await RunAssessmentCaseAsync(
            "control-capped",
            ["{}", "{\"age\":7}"],
            ValidSchema(),
            repairAttempts: 1,
            cancellationToken,
            captureCapacity: 1).ConfigureAwait(false);
        var faultedControl = await RunAssessmentCaseAsync(
            "control-faulted",
            ["{}", "{\"age\":7}"],
            ValidSchema(),
            repairAttempts: 1,
            cancellationToken,
            evidenceFault: true).ConfigureAwait(false);

        var capGuardRejected = GuardRejected(cappedControl.Capture, "capacity control");
        var faultGuardRejected = GuardRejected(faultedControl.Capture, "fault control");
        var evidence = Object(
            Property("recipe_ref", Text(AssessmentCompleteness)),
            Property("no_candidate", AssessmentEvidence(noCandidate)),
            Property("late_malformed_required", AssessmentEvidence(malformedRequired)),
            Property("exhaustion", AssessmentEvidence(exhaustion)),
            Property("nested_dotted", AssessmentEvidence(nestedDotted)),
            Property("invalid_then_valid", AssessmentEvidence(repaired)),
            Property("cap_control", ControlEvidence(normalControl, cappedControl, capGuardRejected)),
            Property("fault_control", ControlEvidence(normalControl, faultedControl, faultGuardRejected)));
        if (!normalControl.Outcome.SemanticallyEquals(cappedControl.Outcome) ||
            !normalControl.Outcome.SemanticallyEquals(faultedControl.Outcome))
        {
            return Fail(evidence, "unavailable evidence control changed the actual native outcome");
        }

        RequireAvailable(noCandidate.Capture, "no-candidate assessment capture");
        RequireAvailable(malformedRequired.Capture, "late malformed required capture");
        RequireAvailable(exhaustion.Capture, "exhaustion capture");
        RequireAvailable(nestedDotted.Capture, "nested/dotted capture");
        RequireAvailable(repaired.Capture, "repair capture");
        var nestedAssessment = nestedDotted.Capture.Assessments.Count == 1 ? nestedDotted.Capture.Assessments[0] : null;
        var selectedPaths = nestedAssessment?.SelectedFindings.Select(static finding => finding.Issue.InstancePath).ToArray() ?? [];
        var message = FirstMismatch(
            noCandidate.Capture.Assessments.Count != 1 || SingleAssessment(noCandidate, "no-candidate").Kind != "extraction" ? "no-candidate stimulus did not retain extraction assessment" : null,
            malformedRequired.Capture.Assessments.Count != 1 || !HasRule(SingleAssessment(malformedRequired, "late malformed required"), "invalid_schema") ? "malformed required did not retain late invalid-schema finding" : null,
            exhaustion.Capture.Assessments.Count != 2 || exhaustion.Capture.Repairs.Count != 1 ? "exhaustion did not retain two assessments and one repair preparation" : null,
            nestedAssessment is null || nestedAssessment.SelectedFindings.Count < 2 || !HasLiteralDottedPath(selectedPaths) || !HasNestedPath(selectedPaths) ? "nested and dotted native paths were not distinguishable" : null,
            repaired.Capture.Assessments.Count != 2 || repaired.Capture.Repairs.Count != 1 || !HasCausalRepair(repaired.Capture) ? "repair did not retain causal assessment, preparation, and correction references" : null,
            !capGuardRejected || !faultGuardRejected ? "unavailable evidence control was not rejected by the capture guard" : null);
        return Result(evidence, message);
    }

    private static async Task<AssessmentCase> RunAssessmentCaseAsync(
        string name,
        string response,
        JsonValue schema,
        int repairAttempts,
        CancellationToken cancellationToken,
        int? captureCapacity = null,
        bool evidenceFault = false) =>
        await RunAssessmentCaseAsync(name, [response], schema, repairAttempts, cancellationToken, captureCapacity, evidenceFault).ConfigureAwait(false);

    private static async Task<AssessmentCase> RunAssessmentCaseAsync(
        string name,
        IReadOnlyList<string> responses,
        JsonValue schema,
        int repairAttempts,
        CancellationToken cancellationToken,
        int? captureCapacity = null,
        bool evidenceFault = false)
    {
        var capture = new OperationCapture(captureCapacity ?? 4096);
        if (evidenceFault)
        {
            _ = new OperationContext(capture);
            _ = new OperationContext(capture);
        }

        var adapter = new ResponseSequenceAdapter(responses);
        await using var client = CreateClient(adapter);
        var outcome = await RunNativeAsync(
            client,
            CreateRequest(name, schema, new RepairOptions(repairAttempts)),
            capture,
            cancellationToken).ConfigureAwait(false);
        return new AssessmentCase(capture, outcome);
    }

    private static AsyncClient CreateClient(IProviderAdapter adapter) =>
        new([new ProviderRegistration("proof", adapter)]);

    private static GenerationRequest CreateRequest(string marker, JsonValue? schema, RepairOptions? repair = null) =>
        new(
            [new Message("user", [new TextPart(marker)])],
            new Route(["proof:model"], new RetryPolicy(MaxAttempts: 2, BackoffBaseS: 0, BackoffMaxS: 0)),
            repair: repair,
            schema: schema,
            stream: false);

    private static async Task<NativeOutcome> RunNativeAsync(
        AsyncClient client,
        GenerationRequest request,
        OperationCapture capture,
        CancellationToken cancellationToken)
    {
        try
        {
            var result = await client.GenerateAsync(request, capture, cancellationToken).ConfigureAwait(false);
            return NativeOutcome.Success(result);
        }
        catch (SchemaViolationException exception)
        {
            return NativeOutcome.Failure(exception);
        }
        catch (AllTargetsFailedException exception)
        {
            return NativeOutcome.Failure(exception);
        }
    }

    private static NativeProofResult Result(JsonObject evidence, string? mismatch) =>
        mismatch is null ? new NativeProofResult("pass", evidence) : Fail(evidence, mismatch);

    private static NativeProofResult Fail(JsonObject evidence, string detail) =>
        new("fail", evidence, BoundedDetail(detail));

    private static NativeProofResult Error(string recipeRef, string detail) =>
        new("error", Object(Property("recipe_ref", Text(recipeRef)), Property("diagnostic", Text(BoundedDetail(detail)))), BoundedDetail(detail));

    private static string BoundedDetail(string detail) => detail.Length <= 240 ? detail : detail[..240];

    private static string? FirstMismatch(params string?[] candidates) => candidates.FirstOrDefault(static candidate => candidate is not null);

    private static JsonObject OperationEvidence(OperationCapture capture, NativeOutcome outcome) => Object(
        Property("operation_id", Text(OperationId(capture))),
        Property("entries", new JsonArray(capture.Entries.Select(EntryEvidence))),
        Property("assessments", new JsonArray(capture.Assessments.Select(AssessmentJson))),
        Property("outcome", outcome.ToJson()));

    private static JsonObject AssessmentEvidence(AssessmentCase assessmentCase) => Object(
        Property("outcome", assessmentCase.Outcome.ToJson()),
        Property("available", Bool(assessmentCase.Capture.IsAvailable)),
        Property("assessments", new JsonArray(assessmentCase.Capture.Assessments.Select(AssessmentJson))),
        Property("repairs", new JsonArray(assessmentCase.Capture.Repairs.Select(RepairJson))),
        Property("entries", new JsonArray(assessmentCase.Capture.Entries.Select(EntryEvidence))));

    private static JsonObject ControlEvidence(AssessmentCase normal, AssessmentCase unavailable, bool guardRejected) => Object(
        Property("normal_outcome", normal.Outcome.ToJson()),
        Property("unavailable_outcome", unavailable.Outcome.ToJson()),
        Property("same_native_outcome", Bool(normal.Outcome.SemanticallyEquals(unavailable.Outcome))),
        Property("unavailable", Bool(!unavailable.Capture.IsAvailable)),
        Property("guard_rejected", Bool(guardRejected)),
        Property("reasons", new JsonArray(unavailable.Capture.UnavailableReasons.Select(Text))));

    private static JsonObject EntryEvidence(EntryContext entry) => Object(
        Property("operation_id", Text(entry.OperationId.ToString("D"))),
        Property("ordinal", Number(entry.Ordinal)),
        Property("role", Text(entry.Role.ToString().ToLowerInvariant())),
        Property("timeout_s", Number(entry.Request.TimeoutS)),
        Property("max_response_bytes", Number(entry.Request.MaxResponseBytes)));

    private static JsonObject AssessmentJson(NativeAssessment assessment) => Object(
        Property("assessment_id", Text(assessment.AssessmentId.ToString("D"))),
        Property("operation_id", Text(assessment.OperationId.ToString("D"))),
        Property("source_entry_ordinal", Number(assessment.SourceEntryOrdinal)),
        Property("kind", Text(assessment.Kind)),
        Property("valid", Bool(assessment.IsValid)),
        Property("all_findings", new JsonArray(assessment.AllFindings.Select(FindingJson))),
        Property("selected_findings", new JsonArray(assessment.SelectedFindings.Select(FindingJson))));

    private static JsonObject FindingJson(NativeFinding finding) => Object(
        Property("rule", Text(finding.Issue.Rule)),
        Property("instance_path", PathJson(finding.Issue.InstancePath)),
        Property("schema_path", PathJson(finding.Issue.SchemaPath)),
        Property("source", Text(finding.Source)),
        Property("native_facts", finding.NativeFacts));

    private static JsonObject RepairJson(RepairPreparation preparation) => Object(
        Property("assessment_id", Text(preparation.Assessment.AssessmentId.ToString("D"))),
        Property("response", Text(preparation.ResponseText)),
        Property("message_count", Number(preparation.Messages.Count)));

    private static JsonArray PathJson(IReadOnlyList<object>? path) =>
        new((path ?? []).Select(static segment => segment switch
        {
            string text => (JsonValue)Text(text),
            int index => Number(index),
            _ => throw new InvalidOperationException("Native issue path contains an unsupported segment."),
        }));

    private static string OperationId(OperationCapture capture) =>
        capture.Entries.FirstOrDefault()?.OperationId.ToString("D") ?? string.Empty;

    private static NativeAssessment SingleAssessment(AssessmentCase assessmentCase, string name)
    {
        if (assessmentCase.Capture.Assessments.Count != 1)
        {
            throw new ObservationUnavailableException($"{name} did not retain exactly one assessment.");
        }

        return assessmentCase.Capture.Assessments[0];
    }

    private static bool HasRule(NativeAssessment assessment, string rule) =>
        assessment.SelectedFindings.Any(finding => string.Equals(finding.Issue.Rule, rule, StringComparison.Ordinal));

    private static bool HasLiteralDottedPath(IEnumerable<IReadOnlyList<object>?> paths) =>
        paths.Any(path => path is { Count: 1 } && path[0] is string text && string.Equals(text, "a.b", StringComparison.Ordinal));

    private static bool HasNestedPath(IEnumerable<IReadOnlyList<object>?> paths) =>
        paths.Any(path => path is { Count: 2 } && path[0] is string first && path[1] is string second &&
            string.Equals(first, "outer", StringComparison.Ordinal) && string.Equals(second, "value", StringComparison.Ordinal));

    private static bool HasCausalRepair(OperationCapture capture)
    {
        if (capture.Repairs.Count != 1 || capture.Entries.Count != 2 || capture.Assessments.Count < 1)
        {
            return false;
        }

        var preparation = capture.Repairs[0];
        var source = capture.Entries[0];
        var correction = capture.Entries[1];
        return correction.Role == EntryRole.Correction &&
               ReferenceEquals(preparation.Assessment, correction.RepairAssessment) &&
               ReferenceEquals(preparation.Assessment, capture.Assessments[0]) &&
               correction.RepairAssessment.SourceEntryOrdinal == source.Ordinal &&
               string.Equals(preparation.ResponseText, AdapterText(source), StringComparison.Ordinal) &&
               MessageListsEqual(PreparedWireMessages(preparation, correction.Request), correction.Request.Messages);
    }

    private static bool CapturesAreDisjoint(OperationCapture first, OperationCapture second) =>
        first.Entries.All(firstEntry => second.Entries.All(secondEntry => !ReferenceEquals(firstEntry, secondEntry))) &&
        first.Assessments.All(firstAssessment => second.Assessments.All(secondAssessment => !ReferenceEquals(firstAssessment, secondAssessment))) &&
        first.Repairs.All(firstRepair => second.Repairs.All(secondRepair => !ReferenceEquals(firstRepair, secondRepair))) &&
        first.Lifecycle.All(firstObservation => second.Lifecycle.All(secondObservation => !ReferenceEquals(firstObservation, secondObservation)));

    private static IReadOnlyList<Message> PreparedWireMessages(RepairPreparation preparation, WireRequest request)
    {
        var messages = preparation.Messages;
        if (request.Schema is not null && request.Mechanism is "prompt" or "json_mode")
        {
            messages = SchemaPromptRenderer.InjectPrompt(messages, request.Schema);
        }

        return messages;
    }

    private static string AdapterText(EntryContext entry) =>
        string.Concat(entry.AdapterEvents.OfType<AdapterTextDelta>().Select(static item => item.Text));

    private static bool MessageListsEqual(IReadOnlyList<Message> first, IReadOnlyList<Message> second) =>
        first.Count == second.Count && first.Zip(second).All(pair => MessageEquals(pair.First, pair.Second));

    private static bool MessageEquals(Message first, Message second) =>
        string.Equals(first.Role, second.Role, StringComparison.Ordinal) &&
        first.Content.Count == second.Content.Count &&
        first.Content.Zip(second.Content).All(pair => Equals(pair.First, pair.Second));

    private static bool GuardRejected(OperationCapture capture, string observation)
    {
        try
        {
            RequireAvailable(capture, observation);
            return false;
        }
        catch (ObservationUnavailableException)
        {
            return true;
        }
    }

    private static JsonObject ValidSchema() => Object(
        Property("type", Text("object")),
        Property("required", new JsonArray([Text("age")])),
        Property("properties", Object(Property("age", Object(Property("type", Text("integer")))))));

    private static JsonObject NestedDottedSchema() => Object(
        Property("type", Text("object")),
        Property("required", new JsonArray([Text("outer"), Text("a.b")])),
        Property("properties", Object(
            Property("outer", Object(
                Property("type", Text("object")),
                Property("required", new JsonArray([Text("value")])),
                Property("properties", Object(Property("value", Object(Property("type", Text("integer")))))))),
            Property("a.b", Object(Property("type", Text("integer")))))));

    private static JsonObject Object(params JsonProperty[] properties) => new(properties);
    private static JsonProperty Property(string name, JsonValue value) => new(name, value);
    private static JsonString Text(string value) => new(value);
    private static JsonBoolean Bool(bool value) => new(value);
    private static JsonInteger Number(int value) => new(value);
    private static JsonNumber Number(double value) => new(value);

    private static bool ResultsEqual(GenerationResult? first, GenerationResult? second)
    {
        if (first is null || second is null)
        {
            return first is null && second is null;
        }

        return string.Equals(first.Text, second.Text, StringComparison.Ordinal) &&
               JsonEquality.TypeAwareEquals(first.Structured ?? JsonNull.Instance, second.Structured ?? JsonNull.Instance) &&
               Equals(first.Target, second.Target) &&
               string.Equals(first.FinishReason, second.FinishReason, StringComparison.Ordinal) &&
               Equals(first.Usage, second.Usage) &&
               string.Equals(first.StructuredMechanism, second.StructuredMechanism, StringComparison.Ordinal) &&
               first.RepairAttempts == second.RepairAttempts &&
               AttemptsEqual(first.Attempts, second.Attempts) &&
               first.Warnings.SequenceEqual(second.Warnings, StringComparer.Ordinal) &&
               TimingPresenceEqual(first.Timing, second.Timing);
    }

    private static bool ErrorsEqual(AnyInferException? first, AnyInferException? second)
    {
        if (first is null || second is null)
        {
            return first is null && second is null;
        }

        return first.GetType() == second.GetType() &&
               string.Equals(first.Category, second.Category, StringComparison.Ordinal) &&
               first.Retryable == second.Retryable &&
               string.Equals(first.Phase, second.Phase, StringComparison.Ordinal) &&
               first.RetryAfterS == second.RetryAfterS &&
               first.HttpStatus == second.HttpStatus &&
               string.Equals(first.Provider, second.Provider, StringComparison.Ordinal) &&
               string.Equals(first.Detail, second.Detail, StringComparison.Ordinal) &&
               string.Equals(first.Hint, second.Hint, StringComparison.Ordinal) &&
               (first, second) switch
               {
                   (SchemaViolationException left, SchemaViolationException right) => left.Issues.SequenceEqual(right.Issues),
                   (AllTargetsFailedException left, AllTargetsFailedException right) => AttemptsEqual(left.Attempts, right.Attempts),
                   _ => true,
               };
    }

    private static bool AttemptsEqual(IReadOnlyList<AttemptRecord> first, IReadOnlyList<AttemptRecord> second) =>
        first.Count == second.Count && first.Zip(second).All(pair =>
            Equals(pair.First.Target, pair.Second.Target) &&
            string.Equals(pair.First.Outcome, pair.Second.Outcome, StringComparison.Ordinal) &&
            ErrorsEqual(pair.First.Error, pair.Second.Error));

    private static bool TimingPresenceEqual(GenerationTiming? first, GenerationTiming? second) =>
        first is null
            ? second is null
            : second is not null && first.FirstTokenMs.HasValue == second.FirstTokenMs.HasValue && first.TotalMs.HasValue == second.TotalMs.HasValue;

    private static JsonObject ResultJson(GenerationResult result) => Object(
        Property("text", Text(result.Text)),
        Property("structured", result.Structured ?? JsonNull.Instance),
        Property("target", result.Target is null ? JsonNull.Instance : Object(Property("provider", Text(result.Target.ProviderId)), Property("model", Text(result.Target.Model)))),
        Property("finish_reason", result.FinishReason is null ? JsonNull.Instance : Text(result.FinishReason)),
        Property("usage", UsageJson(result.Usage)),
        Property("timing_presence", Object(Property("first_token", Bool(result.Timing?.FirstTokenMs is not null)), Property("total", Bool(result.Timing?.TotalMs is not null)))),
        Property("structured_mechanism", result.StructuredMechanism is null ? JsonNull.Instance : Text(result.StructuredMechanism)),
        Property("repair_attempts", Number(result.RepairAttempts)),
        Property("attempts", new JsonArray(result.Attempts.Select(AttemptJson))),
        Property("warnings", new JsonArray(result.Warnings.Select(Text))));

    private static JsonObject ErrorJson(AnyInferException error) => Object(
        Property("type", Text(error.GetType().Name)),
        Property("category", Text(error.Category)),
        Property("retryable", Bool(error.Retryable)),
        Property("phase", error.Phase is null ? JsonNull.Instance : Text(error.Phase)),
        Property("retry_after_s", error.RetryAfterS is null ? JsonNull.Instance : Number(error.RetryAfterS.Value)),
        Property("http_status", error.HttpStatus is null ? JsonNull.Instance : Number(error.HttpStatus.Value)),
        Property("provider", error.Provider is null ? JsonNull.Instance : Text(error.Provider)),
        Property("detail", error.Detail is null ? JsonNull.Instance : Text(error.Detail)),
        Property("hint", error.Hint is null ? JsonNull.Instance : Text(error.Hint)),
        Property("issues", error is SchemaViolationException schema ? new JsonArray(schema.Issues.Select(IssueJson)) : new JsonArray([])),
        Property("attempts", error is AllTargetsFailedException failures ? new JsonArray(failures.Attempts.Select(AttemptJson)) : new JsonArray([])));

    private static JsonObject AttemptJson(AttemptRecord attempt) => Object(
        Property("target", attempt.Target is null ? JsonNull.Instance : Object(Property("provider", Text(attempt.Target.ProviderId)), Property("model", Text(attempt.Target.Model)))),
        Property("outcome", Text(attempt.Outcome)),
        Property("error", attempt.Error is null ? JsonNull.Instance : ErrorJson(attempt.Error)));

    private static JsonObject UsageJson(Usage? usage) => Object(
        Property("input_tokens", NullableNumber(usage?.InputTokens)),
        Property("output_tokens", NullableNumber(usage?.OutputTokens)),
        Property("total_tokens", NullableNumber(usage?.TotalTokens)),
        Property("cache_read_tokens", NullableNumber(usage?.CacheReadTokens)),
        Property("cache_write_tokens", NullableNumber(usage?.CacheWriteTokens)),
        Property("reasoning_tokens", NullableNumber(usage?.ReasoningTokens)));

    private static JsonObject IssueJson(Issue issue) => Object(
        Property("rule", Text(issue.Rule)),
        Property("instance_path", PathJson(issue.InstancePath)),
        Property("schema_path", PathJson(issue.SchemaPath)),
        Property("parameters", issue.Parameters));

    private static JsonValue NullableNumber(long? value) => value is null ? JsonNull.Instance : new JsonInteger(value.Value);

    private sealed record AssessmentCase(OperationCapture Capture, NativeOutcome Outcome);

    private sealed record NativeOutcome(GenerationResult? Result, AnyInferException? Error)
    {
        internal static NativeOutcome Success(GenerationResult result) => new(result, null);
        internal static NativeOutcome Failure(AnyInferException exception) => new(null, exception);

        internal bool SemanticallyEquals(NativeOutcome other) =>
            ResultsEqual(Result, other.Result) && ErrorsEqual(Error, other.Error);

        internal JsonObject ToJson() => Result is not null
            ? Object(Property("kind", Text("result")), Property("result", ResultJson(Result)))
            : Object(Property("kind", Text("error")), Property("error", ErrorJson(Error ?? throw new InvalidOperationException("Native outcome has no terminal object."))));
    }

    private sealed class CaptureSnapshot
    {
        private readonly IReadOnlyList<EntrySnapshot> _entries;
        private readonly IReadOnlyList<AssessmentSnapshot> _assessments;
        private readonly IReadOnlyList<RepairSnapshot> _repairs;
        private readonly IReadOnlyList<LifecycleObservation> _lifecycle;

        private CaptureSnapshot(
            IReadOnlyList<EntrySnapshot> entries,
            IReadOnlyList<AssessmentSnapshot> assessments,
            IReadOnlyList<RepairSnapshot> repairs,
            IReadOnlyList<LifecycleObservation> lifecycle)
        {
            _entries = entries;
            _assessments = assessments;
            _repairs = repairs;
            _lifecycle = lifecycle;
        }

        internal static CaptureSnapshot Create(OperationCapture capture) => new(
            capture.Entries.Select(EntrySnapshot.Create).ToArray(),
            capture.Assessments.Select(AssessmentSnapshot.Create).ToArray(),
            capture.Repairs.Select(RepairSnapshot.Create).ToArray(),
            capture.Lifecycle.ToArray());

        internal bool Matches(OperationCapture capture) =>
            _entries.Count == capture.Entries.Count &&
            _assessments.Count == capture.Assessments.Count &&
            _repairs.Count == capture.Repairs.Count &&
            _lifecycle.Count == capture.Lifecycle.Count &&
            _entries.Zip(capture.Entries).All(pair => pair.First.Matches(pair.Second)) &&
            _assessments.Zip(capture.Assessments).All(pair => pair.First.Matches(pair.Second)) &&
            _repairs.Zip(capture.Repairs).All(pair => pair.First.Matches(pair.Second)) &&
            _lifecycle.Zip(capture.Lifecycle).All(pair => ReferenceEquals(pair.First, pair.Second));

        private sealed record EntrySnapshot(
            EntryContext Entry,
            WireRequest Request,
            NativeAssessment? RepairAssessment,
            EntryTimeoutScope Timeout,
            IReadOnlyList<AdapterEvent> Events,
            Exception? NativeFailure,
            Exception? TerminalFailure,
            Exception? PriorNativeFailure,
            Exception? PriorTerminalFailure,
            bool TimeoutExpired,
            bool TimeoutDisposed)
        {
            internal static EntrySnapshot Create(EntryContext entry) => new(
                entry,
                entry.Request,
                entry.RepairAssessment,
                entry.Timeout,
                entry.AdapterEvents.ToArray(),
                entry.NativeFailure,
                entry.TerminalFailure,
                entry.PriorNativeFailure,
                entry.PriorTerminalFailure,
                entry.Timeout.IsExpired,
                entry.Timeout.IsDisposed);

            internal bool Matches(EntryContext entry) =>
                ReferenceEquals(Entry, entry) &&
                ReferenceEquals(Request, entry.Request) &&
                ReferenceEquals(RepairAssessment, entry.RepairAssessment) &&
                ReferenceEquals(Timeout, entry.Timeout) &&
                TimeoutExpired == entry.Timeout.IsExpired &&
                TimeoutDisposed == entry.Timeout.IsDisposed &&
                ReferenceEquals(NativeFailure, entry.NativeFailure) &&
                ReferenceEquals(TerminalFailure, entry.TerminalFailure) &&
                ReferenceEquals(PriorNativeFailure, entry.PriorNativeFailure) &&
                ReferenceEquals(PriorTerminalFailure, entry.PriorTerminalFailure) &&
                Events.Count == entry.AdapterEvents.Count &&
                Events.Zip(entry.AdapterEvents).All(pair => ReferenceEquals(pair.First, pair.Second));
        }

        private sealed record AssessmentSnapshot(
            NativeAssessment Assessment,
            IReadOnlyList<NativeFinding> All,
            IReadOnlyList<NativeFinding> Selected)
        {
            internal static AssessmentSnapshot Create(NativeAssessment assessment) => new(assessment, assessment.AllFindings.ToArray(), assessment.SelectedFindings.ToArray());

            internal bool Matches(NativeAssessment assessment) =>
                ReferenceEquals(Assessment, assessment) &&
                All.Count == assessment.AllFindings.Count &&
                Selected.Count == assessment.SelectedFindings.Count &&
                All.Zip(assessment.AllFindings).All(pair => ReferenceEquals(pair.First, pair.Second)) &&
                Selected.Zip(assessment.SelectedFindings).All(pair => ReferenceEquals(pair.First, pair.Second));
        }

        private sealed record RepairSnapshot(RepairPreparation Preparation, NativeAssessment Assessment, string ResponseText, IReadOnlyList<Message> Messages)
        {
            internal static RepairSnapshot Create(RepairPreparation preparation) => new(preparation, preparation.Assessment, preparation.ResponseText, preparation.Messages.ToArray());

            internal bool Matches(RepairPreparation preparation) =>
                ReferenceEquals(Preparation, preparation) &&
                ReferenceEquals(Assessment, preparation.Assessment) &&
                string.Equals(ResponseText, preparation.ResponseText, StringComparison.Ordinal) &&
                MessageListsEqual(Messages, preparation.Messages);
        }
    }

    private sealed class ConcurrentProofAdapter : IProviderAdapter
    {
        private readonly TaskCompletionSource<bool> _validEntered = NewSignal();
        private readonly TaskCompletionSource<bool> _invalidEntered = NewSignal();
        private readonly TaskCompletionSource<bool> _release = NewSignal();
        private int _active;
        private int _bothEntered;

        internal bool OverlapObserved => Volatile.Read(ref _bothEntered) != 0;

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) =>
            GenerateCoreAsync(Marker(request), cancellationToken);

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;

        internal async Task WaitForBothEntriesAsync(CancellationToken cancellationToken)
        {
            var ready = Task.WhenAll(_validEntered.Task, _invalidEntered.Task);
            var watchdog = Task.Delay(TimeSpan.FromSeconds(10), cancellationToken);
            if (await Task.WhenAny(ready, watchdog).ConfigureAwait(false) != ready)
            {
                cancellationToken.ThrowIfCancellationRequested();
                throw new ObservationUnavailableException("concurrent proof readiness watchdog expired");
            }

            await ready.ConfigureAwait(false);
        }

        internal void Release() => _release.TrySetResult(true);

        private async IAsyncEnumerable<AdapterEvent> GenerateCoreAsync(
            string marker,
            [EnumeratorCancellation] CancellationToken cancellationToken)
        {
            if (marker == "follow-up")
            {
                yield return new AdapterTextDelta("follow-up");
                yield return new AdapterFinal("stop");
                yield break;
            }

            var entered = marker switch
            {
                "valid" => _validEntered,
                "invalid" => _invalidEntered,
                _ => throw new ProofHarnessException("Concurrent proof request marker was not recognized."),
            };
            Interlocked.Increment(ref _active);
            entered.TrySetResult(true);
            if (Volatile.Read(ref _active) >= 2)
            {
                Volatile.Write(ref _bothEntered, 1);
            }

            try
            {
                await _release.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
                yield return new AdapterTextDelta(marker == "valid" ? "{\"age\":7}" : "{}");
                yield return new AdapterFinal("stop");
            }
            finally
            {
                Interlocked.Decrement(ref _active);
            }
        }
    }

    private sealed class ResponseSequenceAdapter : IProviderAdapter
    {
        private readonly IReadOnlyList<string> _responses;
        private int _nextResponse;

        internal ResponseSequenceAdapter(IReadOnlyList<string> responses)
        {
            if (responses.Count == 0)
            {
                throw new ArgumentException("Proof response sequence cannot be empty.", nameof(responses));
            }

            _responses = responses;
        }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) =>
            GenerateCoreAsync(cancellationToken);

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;

        private async IAsyncEnumerable<AdapterEvent> GenerateCoreAsync([EnumeratorCancellation] CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var index = Interlocked.Increment(ref _nextResponse) - 1;
            if (index >= _responses.Count)
            {
                throw new ProofHarnessException("Proof response sequence was exhausted.");
            }

            await Task.Yield();
            yield return new AdapterTextDelta(_responses[index]);
            yield return new AdapterFinal("stop");
        }
    }

    private static string Marker(WireRequest request)
    {
        var callers = request.Messages.Where(static message => string.Equals(message.Role, "user", StringComparison.Ordinal)).ToArray();
        if (callers.Length != 1)
        {
            throw new ProofHarnessException("Proof request does not contain exactly one caller user message.");
        }

        if (callers[0].Content.Any(static part => part is not TextPart))
        {
            throw new ProofHarnessException("Proof caller message contains non-text content.");
        }

        return string.Concat(callers[0].Content.Cast<TextPart>().Select(static text => text.Text));
    }

    private static TaskCompletionSource<bool> NewSignal() =>
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    private sealed class ProofHarnessException : Exception
    {
        internal ProofHarnessException(string message)
            : base(message)
        {
        }
    }
}
