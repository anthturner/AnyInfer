using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Schema;

namespace AnyInfer.Events;

/// <summary>Base type for typed in-process telemetry facts.</summary>
/// <remarks>
/// Telemetry events are delivered to <see cref="IObserver"/> instances registered with a client. Events that
/// belong to one request share its <c>RequestId</c>. Fields that carry request or response text are filled only
/// for observers subscribed with payloads enabled; every other observer receives them as <see langword="null"/>.
/// </remarks>
public abstract record TelemetryEvent
{
    // Declared explicitly only so the constructor the compiler would otherwise synthesize is documented.
    /// <summary>Initializes the base state of a derived telemetry event.</summary>
    protected TelemetryEvent() { }

    /// <summary>Renders this event as a redacted immutable JSON object.</summary>
    /// <returns>
    /// A new JSON object whose <c>event</c> member holds the event type name, followed by the event's fields under
    /// snake_case names such as <c>request_id</c>. String values and map keys pass through
    /// <see cref="Redaction.Redact(string?)"/>, absent values are JSON <c>null</c>, and
    /// <see cref="Usage.CostUsd"/> is written as a decimal string.
    /// </returns>
    /// <exception cref="ArgumentOutOfRangeException">This event is a type derived outside the library.</exception>
    public JsonObject ToDictionary() => TelemetrySerialization.ToDictionary(this);
}

/// <summary>Records entry of an inference request into routing.</summary>
/// <remarks>
/// For a generation this is emitted when its stream is first enumerated; for an embedding or rerank request it is
/// emitted after spend admission and before the first provider call.
/// </remarks>
public sealed record RequestStarted : TelemetryEvent
{
    /// <summary>Initializes the request-start fact.</summary>
    /// <param name="requestId">The correlation identifier shared by every event of this request.</param>
    /// <param name="targets">
    /// The route targets in caller order, as written (<c>provider:model</c> or a catalog alias); copied.
    /// <see langword="null"/> is treated as empty.
    /// </param>
    /// <param name="metadata">The request's opaque metadata labels, or <see langword="null"/> for none; copied.</param>
    /// <param name="promptText">
    /// The redacted text parts of the request messages joined by blank lines, or <see langword="null"/>. The library
    /// fills it only when at least one observer is subscribed with payloads enabled.
    /// </param>
    /// <param name="operation">The inference operation: <c>generation</c>, <c>embedding</c>, or <c>rerank</c>.</param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="requestId"/> or <paramref name="operation"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="ArgumentException">
    /// <paramref name="targets"/> contains a <see langword="null"/> element, or <paramref name="metadata"/> contains a
    /// <see langword="null"/> key or value.
    /// </exception>
    public RequestStarted(
        string requestId,
        IEnumerable<string> targets,
        IEnumerable<KeyValuePair<string, string>>? metadata = null,
        string? promptText = null,
        string operation = "generation")
    {
        RequestId = requestId ?? throw new ArgumentNullException(nameof(requestId));
        Targets = ImmutableValues.List(targets, nameof(targets));
        Metadata = ImmutableValues.Map(metadata, nameof(metadata));
        PromptText = promptText;
        Operation = operation ?? throw new ArgumentNullException(nameof(operation));
    }

    /// <summary>Gets the shared correlation identifier.</summary>
    public string RequestId { get; }

    /// <summary>Gets requested targets in caller order.</summary>
    public IReadOnlyList<string> Targets { get; }

    /// <summary>Gets caller metadata as an ordinal snapshot.</summary>
    public IReadOnlyDictionary<string, string> Metadata { get; }

    /// <summary>Gets prompt payload when this observer was payload-enabled.</summary>
    public string? PromptText { get; }

    /// <summary>Gets the inference operation.</summary>
    public string Operation { get; }
}
/// <summary>Records a completed bounded arena.</summary>
/// <remarks>The C# SDK does not currently emit this event.</remarks>
/// <param name="RequestId">The arena's correlation identifier.</param>
/// <param name="TargetCount">The number of candidate targets the arena ran.</param>
/// <param name="Strategy">The selection strategy that was applied.</param>
/// <param name="Agreement">
/// The size of the largest agreeing group under a consensus selection, or <see langword="null"/> when the applied
/// strategy does not measure agreement.
/// </param>
/// <param name="Calls">The number of generation calls the arena spent.</param>
/// <param name="MemoizedToolCalls">The number of tool calls answered from memoized results instead of being run again.</param>
/// <param name="Synthesized">Whether the final answer was synthesized from the candidates rather than selected from one.</param>
public sealed record ArenaCompleted(string RequestId,int TargetCount,string Strategy,int? Agreement,int Calls,int MemoizedToolCalls,bool Synthesized) : TelemetryEvent;
/// <summary>Records resolution of one target.</summary>
/// <remarks>
/// Emitted when a route entry resolves to a provider target, before the health gate is consulted, so a target that
/// is then skipped as unhealthy is still reported here. A generation skips, without this event, an entry that
/// resolves to a target it has already tried.
/// </remarks>
/// <param name="RequestId">The correlation identifier shared by every event of this request.</param>
/// <param name="Target">The resolved provider instance and model.</param>
public sealed record TargetResolved(string RequestId, ResolvedTarget Target) : TelemetryEvent;
/// <summary>Records start of one attempt.</summary>
/// <param name="RequestId">The correlation identifier shared by every event of this request.</param>
/// <param name="Target">The target being attempted.</param>
/// <param name="AttemptNumber">The one-based attempt number for this target, counting retries of the same target.</param>
public sealed record AttemptStarted(string RequestId, ResolvedTarget Target, int AttemptNumber) : TelemetryEvent;
/// <summary>Records first-content timing for an attempt.</summary>
/// <remarks>Emitted once per generation provider call, including schema-repair calls, when its first content arrives.</remarks>
/// <param name="RequestId">The correlation identifier shared by every event of this request.</param>
/// <param name="Target">The target that produced the content.</param>
/// <param name="AtMs">
/// Milliseconds from the start of the provider call to its first text, reasoning, or tool-call fragment.
/// </param>
public sealed record FirstToken(string RequestId, ResolvedTarget Target, double AtMs) : TelemetryEvent;
/// <summary>Records successful completion of one attempt.</summary>
/// <remarks>For a generation this is emitted only for the attempt whose result was accepted, after any schema repairs.</remarks>
/// <param name="RequestId">The correlation identifier shared by every event of this request.</param>
/// <param name="Target">The target that succeeded.</param>
/// <param name="Usage">The usage reported for the successful call, or an empty <see cref="AnyInfer.Usage"/> when none was reported.</param>
/// <param name="Timing">The timing measured for the successful call; an all-default value when none was measured.</param>
/// <param name="FinishReason">
/// The result's finish reason, such as <c>stop</c> or <c>tool_calls</c>; empty when the provider gave none.
/// Embedding and rerank attempts report <c>stop</c>.
/// </param>
public sealed record AttemptCompleted(string RequestId, ResolvedTarget Target, Usage Usage, Timing Timing, string FinishReason) : TelemetryEvent;
/// <summary>Records a scheduled same-target retry.</summary>
/// <param name="RequestId">The correlation identifier shared by every event of this request.</param>
/// <param name="Target">The target that will be retried.</param>
/// <param name="AttemptNumber">The one-based number of the attempt that failed; the retry is the next number.</param>
/// <param name="DelayS">
/// Seconds the client waits before retrying: the <see cref="Retry"/> exponential backoff, raised to any
/// provider-requested retry-after, and capped at <see cref="Retry.BackoffMaxS"/>.
/// </param>
/// <param name="Error">A redacted summary of the failure that caused the retry.</param>
public sealed record RetryScheduled(string RequestId, ResolvedTarget Target, int AttemptNumber, double DelayS, ErrorInfo Error) : TelemetryEvent;
/// <summary>Records a route advance.</summary>
/// <param name="RequestId">The correlation identifier shared by every event of this request.</param>
/// <param name="FromTarget">The target the route is leaving.</param>
/// <param name="ToTarget">
/// The next route entry exactly as written (<c>provider:model</c> or a catalog alias); it has not been resolved yet.
/// </param>
/// <param name="Error">
/// A redacted summary of the failure that ended <paramref name="FromTarget"/>, or <see langword="null"/> when the route
/// advanced without a failure.
/// </param>
public sealed record FallbackTriggered(string RequestId, ResolvedTarget FromTarget, string ToTarget, ErrorInfo? Error = null) : TelemetryEvent;
/// <summary>Records one schema repair attempt.</summary>
/// <remarks>Emitted when a structured response fails validation and the library asks the same target to correct it.</remarks>
public sealed record RepairAttempted : TelemetryEvent
{
    /// <summary>Initializes a repair fact.</summary>
    /// <param name="requestId">The correlation identifier shared by every event of this request.</param>
    /// <param name="target">The target asked to repair its response.</param>
    /// <param name="attemptNumber">The one-based repair count for this target.</param>
    /// <param name="mechanism">
    /// The structured-output mechanism in use, such as <c>json_schema</c> or <c>prompt</c>, or <see langword="null"/>.
    /// </param>
    /// <param name="errors">The validation messages, in source order; <see langword="null"/> means none. Copied.</param>
    /// <param name="rawText">
    /// The response text that failed validation, or <see langword="null"/>. The library fills it only when at least
    /// one observer is subscribed with payloads enabled.
    /// </param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="requestId"/> or <paramref name="target"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="ArgumentException"><paramref name="errors"/> contains a <see langword="null"/> element.</exception>
    public RepairAttempted(
        string requestId,
        ResolvedTarget target,
        int attemptNumber,
        string? mechanism,
        IEnumerable<string>? errors = null,
        string? rawText = null)
    {
        RequestId = requestId ?? throw new ArgumentNullException(nameof(requestId));
        Target = target ?? throw new ArgumentNullException(nameof(target));
        AttemptNumber = attemptNumber;
        Mechanism = mechanism;
        Errors = ImmutableValues.List(errors, nameof(errors));
        RawText = rawText;
    }

    /// <summary>Gets the shared correlation identifier.</summary>
    public string RequestId { get; }

    /// <summary>Gets the repaired target.</summary>
    public ResolvedTarget Target { get; }

    /// <summary>Gets the one-based repair count.</summary>
    public int AttemptNumber { get; }

    /// <summary>Gets the active mechanism, when any.</summary>
    public string? Mechanism { get; }

    /// <summary>Gets validation messages in source order.</summary>
    public IReadOnlyList<string> Errors { get; }

    /// <summary>Gets failed response payload when enabled.</summary>
    public string? RawText { get; }
}
/// <summary>Records terminal request completion.</summary>
/// <remarks>For a generation this is emitted after its stream commits the successful result.</remarks>
/// <param name="RequestId">The correlation identifier shared by every event of this request.</param>
/// <param name="Target">The target that produced the result.</param>
/// <param name="Usage">The result's usage, or an empty <see cref="AnyInfer.Usage"/> when none was reported.</param>
/// <param name="Timing">The result's timing; an all-default value when none was measured.</param>
/// <param name="RepairAttempts">The number of schema-repair round trips the result needed; <c>0</c> for embedding and rerank.</param>
/// <param name="ResponseText">
/// The redacted answer text, or <see langword="null"/>. The library fills it only for a nonempty generation answer
/// when at least one observer is subscribed with payloads enabled.
/// </param>
public sealed record RequestCompleted(string RequestId, ResolvedTarget Target, Usage Usage, Timing Timing, int RepairAttempts = 0, string? ResponseText = null) : TelemetryEvent;
/// <summary>Records terminal routed request failure.</summary>
/// <remarks>Caller cancellation does not produce this event.</remarks>
/// <param name="RequestId">The correlation identifier shared by every event of this request.</param>
/// <param name="Error">A redacted summary of the failure that ended the request.</param>
public sealed record RequestFailed(string RequestId, ErrorInfo Error) : TelemetryEvent;
/// <summary>Records a parameter the target did not honour.</summary>
/// <param name="RequestId">The correlation identifier shared by every event of this request.</param>
/// <param name="Target">The target that did not honour the parameter.</param>
/// <param name="Parameter">
/// The request parameter in snake_case, dotted for nested settings, such as <c>temperature</c>, <c>reasoning</c>,
/// <c>cache.mode</c>, or <c>repair.max_attempts</c>.
/// </param>
/// <param name="Reason">A human-readable explanation of why the parameter was dropped or capped.</param>
public sealed record ParameterDropped(string RequestId, ResolvedTarget Target, string Parameter, string Reason) : TelemetryEvent;
/// <summary>Records an advisory provider diagnostic.</summary>
/// <param name="Target">The target the diagnostic concerns, or <see langword="null"/> when it concerns none.</param>
/// <param name="Diagnostic">The advisory diagnostic.</param>
/// <param name="RequestId">
/// The correlation identifier of the related request, or <see langword="null"/> when the emitter did not correlate
/// the diagnostic with a request. The library's prompt-cache prefix diagnostic currently carries none.
/// </param>
public sealed record ProviderDiagnostic(ResolvedTarget? Target, Diagnostic Diagnostic, string? RequestId = null) : TelemetryEvent;
/// <summary>Marks a usage value as estimated rather than provider-reported.</summary>
/// <param name="RequestId">The correlation identifier shared by every event of this request.</param>
/// <param name="Target">The target the estimate was made for.</param>
/// <param name="FieldName">The usage field in snake_case, such as <c>input_tokens</c>.</param>
/// <param name="Method">A description of how the value was estimated.</param>
public sealed record UsageEstimated(string RequestId, ResolvedTarget Target, string FieldName, string Method) : TelemetryEvent;
/// <summary>Records context reduction counts and limits.</summary>
/// <remarks>The C# SDK does not currently emit this event.</remarks>
public sealed record ContextReduced : TelemetryEvent
{
    /// <summary>Initializes a context-reduction fact.</summary>
    /// <param name="strategy">The reduction strategy that was requested.</param>
    /// <param name="representation">The representation that was actually applied.</param>
    /// <param name="candidateCount">The number of candidates (documents or messages) offered for reduction.</param>
    /// <param name="selectedCount">The number of candidates kept in full detail.</param>
    /// <param name="omittedCount">The number of candidates not kept in full detail.</param>
    /// <param name="estimatedTokens">The planning-side token estimate of the reduced result.</param>
    /// <param name="maxTokens">The token budget the reduction was held to.</param>
    /// <param name="bindingConstraints">
    /// The limits that excluded at least one candidate, in source order; <see langword="null"/> means none. Copied.
    /// </param>
    /// <param name="calls">The number of generation calls spent on the reduction.</param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="strategy"/> or <paramref name="representation"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="ArgumentException">
    /// <paramref name="bindingConstraints"/> contains a <see langword="null"/> element.
    /// </exception>
    public ContextReduced(
        string strategy,
        string representation,
        int candidateCount,
        int selectedCount,
        int omittedCount,
        int estimatedTokens,
        int maxTokens,
        IEnumerable<string>? bindingConstraints = null,
        int calls = 0)
    {
        Strategy = strategy ?? throw new ArgumentNullException(nameof(strategy));
        Representation = representation ?? throw new ArgumentNullException(nameof(representation));
        CandidateCount = candidateCount;
        SelectedCount = selectedCount;
        OmittedCount = omittedCount;
        EstimatedTokens = estimatedTokens;
        MaxTokens = maxTokens;
        BindingConstraints = ImmutableValues.List(bindingConstraints, nameof(bindingConstraints));
        Calls = calls;
    }

    /// <summary>Gets requested reduction strategy.</summary>
    public string Strategy { get; }

    /// <summary>Gets applied representation.</summary>
    public string Representation { get; }

    /// <summary>Gets offered candidate count.</summary>
    public int CandidateCount { get; }

    /// <summary>Gets retained candidate count.</summary>
    public int SelectedCount { get; }

    /// <summary>Gets omitted candidate count.</summary>
    public int OmittedCount { get; }

    /// <summary>Gets estimated resulting tokens.</summary>
    public int EstimatedTokens { get; }

    /// <summary>Gets reduction budget.</summary>
    public int MaxTokens { get; }

    /// <summary>Gets binding constraints in source order.</summary>
    public IReadOnlyList<string> BindingConstraints { get; }

    /// <summary>Gets reduction generation calls.</summary>
    public int Calls { get; }
}
/// <summary>Records an engaged prompt-cache plan.</summary>
/// <remarks>Emitted when the active prompt-cache policy engages a cache mechanism for a target.</remarks>
/// <param name="RequestId">The correlation identifier shared by every event of this request.</param>
/// <param name="Target">The target the plan applies to.</param>
/// <param name="Mechanism">The engaged mechanism: <c>explicit</c> or <c>implicit</c>.</param>
/// <param name="MarkCount">The number of explicit cache marks placed in the request.</param>
/// <param name="EstimatedCacheableTokens">The planning-side estimate of cacheable prompt tokens.</param>
public sealed record CachePlanned(string RequestId, ResolvedTarget Target, string Mechanism, int MarkCount, long EstimatedCacheableTokens) : TelemetryEvent;
/// <summary>Records client-side rate-limit waiting.</summary>
/// <remarks>Emitted by a provider's configured rate limiter each time it holds a request back.</remarks>
/// <param name="RequestId">The correlation identifier of the delayed request, or empty when the wait was not attributed to one.</param>
/// <param name="ProviderId">The provider instance whose limiter imposed the wait.</param>
/// <param name="WaitedS">The time waited, in seconds; always greater than zero.</param>
/// <param name="Reason">Why the limiter waited: <c>concurrency</c>, <c>interval</c>, or <c>provider-headers</c>.</param>
/// <param name="Target">The delayed target, or <see langword="null"/> when the wait was not attributed to one.</param>
public sealed record RateLimitWaited(string RequestId,string ProviderId,double WaitedS,string Reason,ResolvedTarget? Target=null) : TelemetryEvent;
/// <summary>Records provider-reported rate-limit state.</summary>
/// <remarks>
/// Emitted when a provider response carries remaining-allowance headers in the dialect the provider declares.
/// </remarks>
/// <param name="ProviderId">The provider instance the headers came from.</param>
/// <param name="RequestsRemaining">The requests remaining in the current window, or <see langword="null"/> when not reported.</param>
/// <param name="TokensRemaining">The tokens remaining in the current window, or <see langword="null"/> when not reported.</param>
/// <param name="ResetsInS">
/// Seconds until the request window resets (or, when that is not reported, the token window), or
/// <see langword="null"/> when neither is reported.
/// </param>
public sealed record RateLimitObserved(string ProviderId,long? RequestsRemaining=null,long? TokensRemaining=null,double? ResetsInS=null) : TelemetryEvent;
/// <summary>Records supervised-server lifecycle state.</summary>
/// <remarks>The C# SDK does not currently emit this event.</remarks>
/// <param name="ServerId">Identifies the supervised server.</param>
/// <param name="State">The state the server entered.</param>
/// <param name="Detail">Human-readable context for the change; empty when there is nothing to add.</param>
public sealed record ServerLifecycle(string ServerId,string State,string Detail="") : TelemetryEvent;
/// <summary>Records aggregate model-download progress.</summary>
/// <remarks>The C# SDK does not currently emit this event.</remarks>
/// <param name="ArtifactId">The artifact being acquired.</param>
/// <param name="DownloadedBytes">Bytes present across every file of the acquisition, including bytes already on disk.</param>
/// <param name="TotalBytes">The total expected bytes, or <see langword="null"/> when unknown.</param>
/// <param name="Done">Whether the acquisition finished.</param>
/// <param name="Phase">The stage that reported progress; empty when none was given.</param>
/// <param name="FileIndex">The one-based index of the file that most recently advanced, or <c>0</c> when not reported.</param>
/// <param name="FileCount">The number of files the acquisition covers, or <c>0</c> when not reported.</param>
/// <param name="Filename">The name of the file that most recently advanced; empty when not reported.</param>
/// <param name="SessionBytes">Bytes transferred by this run, as opposed to resumed from disk.</param>
public sealed record DownloadProgress(string ArtifactId,long DownloadedBytes,long? TotalBytes,bool Done=false,string Phase="",int FileIndex=0,int FileCount=0,string Filename="",long SessionBytes=0) : TelemetryEvent;
/// <summary>Records provider batch submission.</summary>
/// <remarks>The C# SDK does not currently emit this event.</remarks>
/// <param name="BatchId">The provider's identifier for the batch job.</param>
/// <param name="Target">The target the batch was submitted to.</param>
/// <param name="LineCount">The number of requests in the batch.</param>
public sealed record BatchSubmitted(string BatchId,ResolvedTarget Target,int LineCount) : TelemetryEvent;
/// <summary>Records provider batch collection.</summary>
/// <remarks>The C# SDK does not currently emit this event.</remarks>
/// <param name="BatchId">The provider's identifier for the batch job.</param>
/// <param name="Target">The target the batch ran on.</param>
/// <param name="Status">The batch's terminal status.</param>
/// <param name="Completed">The number of requests that produced a result.</param>
/// <param name="Failed">The number of requests that did not.</param>
public sealed record BatchCompleted(string BatchId,ResolvedTarget Target,string Status,int Completed,int Failed) : TelemetryEvent;
/// <summary>Records a provider credential rotation without revealing the credential.</summary>
/// <remarks>The C# SDK does not currently emit this event.</remarks>
/// <param name="Provider">The provider instance whose credential changed.</param>
/// <param name="Trigger">What prompted the credential to be resolved again, such as <c>ttl</c>.</param>
public sealed record CredentialRotated(string Provider,string Trigger="ttl") : TelemetryEvent;
