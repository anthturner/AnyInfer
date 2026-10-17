using System.Numerics;
using AnyInfer.Core;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;

namespace AnyInfer.Conformance;

/// <summary>Runs the timeout-focused native proof recipes with proof-local adapters.</summary>
internal static class ProofTimeouts
{
    private const string EffectiveRecipe = "driver/timeout-effective-default-explicit";
    private const string ResetRecipe = "driver/timeout-reset-per-entry";

    internal static async Task<NativeProofResult> RunEffectiveDefaultExplicitAsync(CancellationToken cancellationToken)
    {
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            var defaultRun = await RunSuccessfulEntryAsync("default", null, null, cancellationToken).ConfigureAwait(false);
            var explicitRun = await RunSuccessfulEntryAsync("explicit", 7.25, 4096, cancellationToken).ConfigureAwait(false);
            var timeout = await RunNativeTimeoutAsync(cancellationToken).ConfigureAwait(false);
            if (!defaultRun.Capture.IsAvailable || !explicitRun.Capture.IsAvailable || !timeout.Capture.IsAvailable)
            {
                return Error(EffectiveRecipe, "Native timeout capture was unavailable.");
            }

            var defaultEntry = SingleEntryOrNull(defaultRun.Capture);
            var explicitEntry = SingleEntryOrNull(explicitRun.Capture);
            var timeoutEntry = SingleEntryOrNull(timeout.Capture);
            var evidence = new JsonObject([
                new JsonProperty("recipe_ref", new JsonString(EffectiveRecipe)),
                new JsonProperty("default_outcome", RunEvidence(defaultRun.Result, defaultRun.Terminal)),
                new JsonProperty("explicit_outcome", RunEvidence(explicitRun.Result, explicitRun.Terminal)),
                new JsonProperty("timeout_outcome", RunEvidence(timeout.Result, timeout.Terminal)),
                new JsonProperty("default_entry", defaultEntry is null ? JsonNull.Instance : EntryEvidence(defaultEntry)),
                new JsonProperty("explicit_entry", explicitEntry is null ? JsonNull.Instance : EntryEvidence(explicitEntry)),
                new JsonProperty("timeout_entry", timeoutEntry is null ? JsonNull.Instance : EntryEvidence(timeoutEntry)),
                new JsonProperty("default_lifecycle", LifecycleEvidence(defaultRun.Capture)),
                new JsonProperty("explicit_lifecycle", LifecycleEvidence(explicitRun.Capture)),
                new JsonProperty("timeout_lifecycle", LifecycleEvidence(timeout.Capture)),
                new JsonProperty("timeout_attempts", timeout.Terminal is null ? new JsonArray([]) : AttemptsEvidence(timeout.Terminal)),
                new JsonProperty("timeout_mapping", TimeoutMappingEvidence(ObserveTimeoutMapping(timeoutEntry, timeout.Terminal))),
            ]);

            if (defaultEntry is null || explicitEntry is null || timeoutEntry is null)
            {
                return Result(EffectiveRecipe, false, evidence, "Native runs retained an unexpected entry count.");
            }

            var defaultLifecycle = LifecycleState(defaultRun.Capture, defaultEntry, "created", "configured", "entered", "cleanup_start", "cleanup_end", "exited", "disposed");
            var explicitLifecycle = LifecycleState(explicitRun.Capture, explicitEntry, "created", "configured", "entered", "cleanup_start", "cleanup_end", "exited", "disposed");
            var timeoutLifecycle = LifecycleState(timeout.Capture, timeoutEntry, "created", "configured", "entered", "expired", "cleanup_start", "cleanup_end", "exited", "disposed");
            if (defaultLifecycle == LifecycleStatus.Missing || explicitLifecycle == LifecycleStatus.Missing || timeoutLifecycle == LifecycleStatus.Missing)
            {
                return Error(EffectiveRecipe, "Native timeout lifecycle capture was incomplete.");
            }

            var passed = defaultRun.Result is not null && defaultRun.Terminal is null &&
                explicitRun.Result is not null && explicitRun.Terminal is null &&
                timeout.Result is null && timeout.Terminal is not null &&
                defaultLifecycle == LifecycleStatus.Exact && explicitLifecycle == LifecycleStatus.Exact && timeoutLifecycle == LifecycleStatus.Exact &&
                defaultEntry.Request.TimeoutS == 120 && defaultEntry.Request.MaxResponseBytes == 1_048_576 && defaultEntry.Timeout.EffectiveTimeoutS == 120 &&
                explicitEntry.Request.TimeoutS == 7.25 && explicitEntry.Request.MaxResponseBytes == 4096 && explicitEntry.Timeout.EffectiveTimeoutS == 7.25 &&
                timeoutEntry.Request.TimeoutS == 0.05 && timeoutEntry.Request.MaxResponseBytes == 80 && timeoutEntry.Timeout.IsExpired && timeoutEntry.Timeout.IsDisposed &&
                ObserveTimeoutMapping(timeoutEntry, timeout.Terminal).IsNativeToProvider &&
                ObserveTimeoutMapping(timeoutEntry, timeout.Terminal).IsProviderToAttempt;
            return Result(EffectiveRecipe, passed, evidence, "Native timeout limits, expiry mapping, outcome, or lifecycle evidence differed.");
        }
        catch (ProofHarnessException exception)
        {
            return Error(EffectiveRecipe, exception.Message);
        }
    }

    internal static async Task<NativeProofResult> RunResetPerEntryAsync(CancellationToken cancellationToken)
    {
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            var adapter = new ProofAdapter([
                ProofStep.Success("{\"name\":\"x\"}"),
                ProofStep.FromFailure(new ProviderException("proof retry", "transport", retryable: true, phase: "generate")),
                ProofStep.Success("{\"name\":\"x\"}"),
                ProofStep.Success("{\"age\":7}"),
            ]);
            var capture = new OperationCapture();
            await using var client = new AsyncClient([new ProviderRegistration("proof", adapter)]);
            var schema = PersonSchema();
            var request = new GenerationRequest(
                [new Message("user", [new TextPart("Give me a person.")])],
                new Route(["proof:reset"], new RetryPolicy(MaxAttempts: 2, BackoffBaseS: 0, BackoffMaxS: 0)),
                repair: new RepairOptions(1), schema: schema, timeoutS: 7.25, maxResponseBytes: 4096);
            GenerationResult? result = null;
            AnyInferException? terminal = null;
            try { result = await client.GenerateAsync(request, capture, cancellationToken).ConfigureAwait(false); }
            catch (AnyInferException exception) { terminal = exception; }

            if (!capture.IsAvailable)
            {
                return Error(ResetRecipe, "Native reset capture was unavailable.");
            }

            var entries = capture.Entries;
            var evidence = new JsonObject([
                new JsonProperty("recipe_ref", new JsonString(ResetRecipe)),
                new JsonProperty("outcome", RunEvidence(result, terminal)),
                new JsonProperty("entries", new JsonArray(entries.Select(EntryEvidence))),
                new JsonProperty("lifecycle", LifecycleEvidence(capture)),
                new JsonProperty("assessments", new JsonArray(capture.Assessments.Select(AssessmentEvidence))),
                new JsonProperty("repairs", new JsonArray(capture.Repairs.Select(RepairEvidence))),
                new JsonProperty("repair_wire_bindings", RepairWireEvidence(capture)),
            ]);
            if (entries.Count != 4 || capture.Assessments.Count != 3 || capture.Repairs.Count != 2)
            {
                return Result(ResetRecipe, false, evidence, "Native reset retained an unexpected entry, assessment, or repair count.");
            }

            var roles = new[] { EntryRole.Original, EntryRole.Correction, EntryRole.Original, EntryRole.Correction };
            var lifecycleStates = entries.Select(entry => LifecycleState(capture, entry, "created", "configured", "entered", "cleanup_start", "cleanup_end", "exited", "disposed")).ToArray();
            if (lifecycleStates.Any(static state => state == LifecycleStatus.Missing))
            {
                return Error(ResetRecipe, "Native reset lifecycle capture was incomplete.");
            }

            var contexts = entries.Select(static entry => entry.Timeout.ContextId).ToArray();
            var timeoutSources = entries.Select(static entry => entry.Timeout.TimeoutSource).ToArray();
            var linkedSources = entries.Select(static entry => entry.Timeout.LinkedSource).ToArray();
            var lifecycleOrdered = entries.Zip(entries.Skip(1), (prior, next) => LastSequence(capture, prior, "disposed") < FirstSequence(capture, next, "created")).All(static value => value);
            var assessments = capture.Assessments;
            var repairAssessments = capture.Repairs.Select(static repair => repair.Assessment).ToArray();
            var assessmentSources = assessments.Select(static assessment => assessment.SourceEntryOrdinal).ToArray();
            var invalidAssessments = assessments.Where(static assessment => !assessment.IsValid).ToArray();
            var finalAssessment = assessments.LastOrDefault();
            var repairWiresMatch = RepairWiresMatch(entries, capture.Repairs, schema);
            var passed = result is not null && terminal is null && result.Structured is JsonObject structured && HasInteger(structured, "age", 7) && result.RepairAttempts == 1 &&
                entries.Select(static entry => entry.Role).SequenceEqual(roles) &&
                entries.All(static entry => entry.Request.TimeoutS == 7.25 && entry.Request.MaxResponseBytes == 4096 && entry.Timeout.EffectiveTimeoutS == 7.25 && entry.Timeout.IsDisposed) &&
                lifecycleStates.All(static state => state == LifecycleStatus.Exact) && lifecycleOrdered &&
                contexts.Distinct().Count() == 4 && timeoutSources.Distinct(ReferenceEqualityComparer.Instance).Count() == 4 && linkedSources.Distinct(ReferenceEqualityComparer.Instance).Count() == 4 &&
                assessmentSources.SequenceEqual([1, 3, 4]) && invalidAssessments.Length == 2 && finalAssessment is { IsValid: true, SourceEntryOrdinal: 4 } &&
                repairAssessments.Length == 2 && repairAssessments.SequenceEqual(invalidAssessments, ReferenceEqualityComparer.Instance) &&
                ReferenceEquals(entries[1].RepairAssessment, repairAssessments[0]) && ReferenceEquals(entries[3].RepairAssessment, repairAssessments[1]) && repairWiresMatch;
            return Result(ResetRecipe, passed, evidence, "Native reset entry, timeout-source, assessment, repair, wire, result, or lifecycle evidence differed.");
        }
        catch (ProofHarnessException exception)
        {
            return Error(ResetRecipe, exception.Message);
        }
    }

    private static async Task<SuccessfulRun> RunSuccessfulEntryAsync(string model, double? timeoutS, int? maxResponseBytes, CancellationToken cancellationToken)
    {
        var adapter = new ProofAdapter([ProofStep.Success("ok")]);
        var capture = new OperationCapture();
        await using var client = new AsyncClient([new ProviderRegistration("proof", adapter)]);
        try
        {
            var result = await client.GenerateAsync(new GenerationRequest([new Message("user", [new TextPart("proof")])], new Route([$"proof:{model}"], new RetryPolicy(MaxAttempts: 1)), timeoutS: timeoutS, maxResponseBytes: maxResponseBytes), capture, cancellationToken).ConfigureAwait(false);
            return new SuccessfulRun(result, null, capture);
        }
        catch (AllTargetsFailedException terminal) { return new SuccessfulRun(null, terminal, capture); }
    }

    private static async Task<TimeoutRun> RunNativeTimeoutAsync(CancellationToken cancellationToken)
    {
        var adapter = new ProofAdapter([ProofStep.WaitForCancellation()]);
        var capture = new OperationCapture();
        await using var client = new AsyncClient([new ProviderRegistration("proof", adapter)]);
        var request = new GenerationRequest([new Message("user", [new TextPart("proof")])], new Route(["proof:timeout"], new RetryPolicy(MaxAttempts: 1)), timeoutS: 0.05, maxResponseBytes: 80);
        var execution = client.GenerateAsync(request, capture, cancellationToken);
        try { await adapter.Ready.WaitAsync(TimeSpan.FromSeconds(2), cancellationToken).ConfigureAwait(false); }
        catch (TimeoutException exception) { throw new ProofHarnessException("Timeout proof adapter did not enter its native iterator gate.", exception); }
        try { return new TimeoutRun(await execution.ConfigureAwait(false), null, capture); }
        catch (AllTargetsFailedException terminal) { return new TimeoutRun(null, terminal, capture); }
    }

    private static NativeProofResult Result(string recipe, bool passed, JsonObject evidence, string detail) => new(passed ? "pass" : "fail", evidence, passed ? null : detail);
    private static NativeProofResult Error(string recipe, string detail) => new("error", new JsonObject([new JsonProperty("recipe_ref", new JsonString(recipe))]), detail);
    private static EntryContext? SingleEntryOrNull(OperationCapture capture) => capture.Entries.Count == 1 ? capture.Entries[0] : null;

    internal static TimeoutMappingObservation ObserveTimeoutMapping(EntryContext? entry, AllTargetsFailedException? terminal)
    {
        var mapped = entry?.TerminalFailure as ProviderException;
        var nativeToProvider = entry?.NativeFailure is OperationCanceledException native && mapped is not null &&
            ReferenceEquals(native, mapped.NativeInner) && mapped.Category == "transport" && mapped.Retryable && mapped.Phase == "generate";
        var providerToAttempt = mapped is not null && terminal is not null && terminal.Attempts.Count == 1 &&
            terminal.Attempts[0].Outcome == "failed" && ReferenceEquals(mapped, terminal.Attempts[0].Error);
        return new TimeoutMappingObservation(nativeToProvider, providerToAttempt);
    }

    private static bool RepairWiresMatch(IReadOnlyList<EntryContext> entries, IReadOnlyList<RepairPreparation> repairs, JsonValue schema) => repairs.Count == 2 && entries.Count == 4 &&
        MatchesRepairWire(entries[0], entries[1], repairs[0], schema) && MatchesRepairWire(entries[2], entries[3], repairs[1], schema);

    private static bool MatchesRepairWire(EntryContext source, EntryContext correction, RepairPreparation repair, JsonValue schema) => string.Equals(repair.ResponseText, AdapterText(source), StringComparison.Ordinal) &&
        ReferenceEquals(correction.RepairAssessment, repair.Assessment) && MessagesEqual(correction.Request.Messages, SchemaPromptRenderer.InjectPrompt(repair.Messages, schema));

    private static string AdapterText(EntryContext entry) => string.Concat(entry.AdapterEvents.OfType<AdapterTextDelta>().Select(static value => value.Text));
    private static bool MessagesEqual(IReadOnlyList<Message> actual, IReadOnlyList<Message> expected) => actual.Count == expected.Count && actual.Zip(expected, static (left, right) =>
        string.Equals(left.Role, right.Role, StringComparison.Ordinal) && left.Content.Count == right.Content.Count &&
        left.Content.Zip(right.Content, static (leftPart, rightPart) => leftPart is TextPart leftText && rightPart is TextPart rightText && string.Equals(leftText.Text, rightText.Text, StringComparison.Ordinal)).All(static equal => equal)).All(static equal => equal);
    private static bool HasInteger(JsonObject value, string name, int expected) => value.TryGetValue(name, out var actual) && actual is JsonInteger integer && integer.Value == new BigInteger(expected);

    private static JsonObject EntryEvidence(EntryContext entry) => new([
        new JsonProperty("ordinal", new JsonInteger(entry.Ordinal)), new JsonProperty("role", new JsonString(entry.Role.ToString().ToLowerInvariant())), new JsonProperty("context_id", new JsonString(entry.Timeout.ContextId.ToString("D"))),
        new JsonProperty("timeout_s", Number(entry.Request.TimeoutS)), new JsonProperty("max_response_bytes", new JsonInteger(entry.Request.MaxResponseBytes)), new JsonProperty("effective_timeout_s", Number(entry.Timeout.EffectiveTimeoutS)), new JsonProperty("disposed", new JsonBoolean(entry.Timeout.IsDisposed)),
        new JsonProperty("timeout_source_id", new JsonString(System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(entry.Timeout.TimeoutSource).ToString(System.Globalization.CultureInfo.InvariantCulture))), new JsonProperty("linked_source_id", new JsonString(System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(entry.Timeout.LinkedSource).ToString(System.Globalization.CultureInfo.InvariantCulture))),
        new JsonProperty("native_failure_type", entry.NativeFailure is null ? JsonNull.Instance : new JsonString(entry.NativeFailure.GetType().Name)), new JsonProperty("terminal_failure_type", entry.TerminalFailure is null ? JsonNull.Instance : new JsonString(entry.TerminalFailure.GetType().Name)),
    ]);
    private static JsonObject AssessmentEvidence(NativeAssessment assessment) => new([new JsonProperty("assessment_id", new JsonString(assessment.AssessmentId.ToString("D"))), new JsonProperty("source_entry_ordinal", new JsonInteger(assessment.SourceEntryOrdinal)), new JsonProperty("kind", new JsonString(assessment.Kind)), new JsonProperty("valid", new JsonBoolean(assessment.IsValid))]);
    private static JsonObject RepairEvidence(RepairPreparation repair) => new([new JsonProperty("assessment_id", new JsonString(repair.Assessment.AssessmentId.ToString("D"))), new JsonProperty("response_text", new JsonString(repair.ResponseText)), new JsonProperty("message_count", new JsonInteger(repair.Messages.Count))]);
    private static JsonArray RepairWireEvidence(OperationCapture capture) => new(capture.Repairs.Select(repair => new JsonObject([new JsonProperty("assessment_id", new JsonString(repair.Assessment.AssessmentId.ToString("D"))), new JsonProperty("response_text", new JsonString(repair.ResponseText)), new JsonProperty("messages", new JsonArray(repair.Messages.Select(MessageEvidence)))])));
    private static JsonObject MessageEvidence(Message message) => new([new JsonProperty("role", new JsonString(message.Role)), new JsonProperty("text", new JsonString(string.Concat(message.Content.OfType<TextPart>().Select(static part => part.Text))))]);
    private static JsonArray LifecycleEvidence(OperationCapture capture) => new(capture.Lifecycle.Select(item => new JsonObject([new JsonProperty("sequence", new JsonInteger(item.Sequence)), new JsonProperty("entry_ordinal", new JsonInteger(item.EntryOrdinal)), new JsonProperty("name", new JsonString(item.Name))])));
    private static JsonObject RunEvidence(GenerationResult? result, Exception? terminal) => new([new JsonProperty("result_text", result is null ? JsonNull.Instance : new JsonString(result.Text)), new JsonProperty("structured", result?.Structured ?? JsonNull.Instance), new JsonProperty("repair_attempts", result is null ? JsonNull.Instance : new JsonInteger(result.RepairAttempts)), new JsonProperty("terminal_type", terminal is null ? JsonNull.Instance : new JsonString(terminal.GetType().Name))]);
    private static JsonArray AttemptsEvidence(AllTargetsFailedException terminal) => new(terminal.Attempts.Select(attempt => new JsonObject([new JsonProperty("outcome", new JsonString(attempt.Outcome)), new JsonProperty("error_category", attempt.Error is null ? JsonNull.Instance : new JsonString(attempt.Error.Category)), new JsonProperty("error_phase", attempt.Error?.Phase is null ? JsonNull.Instance : new JsonString(attempt.Error.Phase))])));
    private static JsonObject TimeoutMappingEvidence(TimeoutMappingObservation observation) => new([new JsonProperty("native_to_provider", new JsonBoolean(observation.IsNativeToProvider)), new JsonProperty("provider_to_attempt", new JsonBoolean(observation.IsProviderToAttempt))]);

    private static LifecycleStatus LifecycleState(OperationCapture capture, EntryContext entry, params string[] expected)
    {
        var actual = capture.Lifecycle.Where(item => item.EntryOrdinal == entry.Ordinal).Select(static item => item.Name).ToArray();
        return expected.All(name => actual.Contains(name, StringComparer.Ordinal)) ? (actual.SequenceEqual(expected, StringComparer.Ordinal) ? LifecycleStatus.Exact : LifecycleStatus.WrongOrder) : LifecycleStatus.Missing;
    }

    private static long FirstSequence(OperationCapture capture, EntryContext entry, string name) => capture.Lifecycle.Single(item => item.EntryOrdinal == entry.Ordinal && item.Name == name).Sequence;
    private static long LastSequence(OperationCapture capture, EntryContext entry, string name) => capture.Lifecycle.Single(item => item.EntryOrdinal == entry.Ordinal && item.Name == name).Sequence;
    private static JsonValue Number(double value) => new JsonNumber(value);
    private static JsonObject PersonSchema() => new([new JsonProperty("type", new JsonString("object")), new JsonProperty("properties", new JsonObject([new JsonProperty("age", new JsonObject([new JsonProperty("type", new JsonString("integer"))]))])), new JsonProperty("required", new JsonArray([new JsonString("age")]))]);

    private sealed record SuccessfulRun(GenerationResult? Result, AllTargetsFailedException? Terminal, OperationCapture Capture);
    private sealed record TimeoutRun(GenerationResult? Result, AllTargetsFailedException? Terminal, OperationCapture Capture);
    internal sealed record TimeoutMappingObservation(bool IsNativeToProvider, bool IsProviderToAttempt);
    private enum LifecycleStatus { Exact, WrongOrder, Missing }
    private sealed class ProofHarnessException(string message, Exception? inner = null) : Exception(message, inner);
    private sealed record ProofStep(string? Text, ProviderException? Failure, bool Wait)
    {
        internal static ProofStep Success(string text) => new(text, null, false);
        internal static ProofStep FromFailure(ProviderException failure) => new(null, failure, false);
        internal static ProofStep WaitForCancellation() => new(null, null, true);
    }

    private sealed class ProofAdapter : IProviderAdapter
    {
        private readonly IReadOnlyList<ProofStep> _steps;
        private readonly TaskCompletionSource _ready = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private int _next;
        internal ProofAdapter(IEnumerable<ProofStep> steps) => _steps = steps.ToArray();
        internal Task Ready => _ready.Task;
        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) => GenerateCoreAsync(cancellationToken);
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
        private async IAsyncEnumerable<AdapterEvent> GenerateCoreAsync([System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken)
        {
            var index = Interlocked.Increment(ref _next) - 1;
            if ((uint)index >= (uint)_steps.Count) throw new ProofHarnessException("Proof adapter script is exhausted.");
            var step = _steps[index];
            if (step.Wait) { _ready.TrySetResult(); await Task.Delay(System.Threading.Timeout.InfiniteTimeSpan, cancellationToken).ConfigureAwait(false); yield break; }
            if (step.Failure is not null) throw step.Failure;
            yield return new AdapterTextDelta(step.Text!);
            yield return new AdapterFinal("stop");
        }
    }
}
