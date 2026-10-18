using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Schema;

namespace AnyInfer.Events;

/// <summary>Base type for typed in-process telemetry facts.</summary>
public abstract record TelemetryEvent
{
    /// <summary>Renders this event as a redacted immutable JSON object.</summary>
    public JsonObject ToDictionary() => TelemetrySerialization.ToDictionary(this);
}

/// <summary>Records entry of an inference request into routing.</summary>
public sealed record RequestStarted : TelemetryEvent
{
    /// <summary>Initializes the request-start fact.</summary>
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
public sealed record ArenaCompleted(string RequestId,int TargetCount,string Strategy,int? Agreement,int Calls,int MemoizedToolCalls,bool Synthesized) : TelemetryEvent;
/// <summary>Records resolution of one target.</summary>
public sealed record TargetResolved(string RequestId, ResolvedTarget Target) : TelemetryEvent;
/// <summary>Records start of one attempt.</summary>
public sealed record AttemptStarted(string RequestId, ResolvedTarget Target, int AttemptNumber) : TelemetryEvent;
/// <summary>Records first-content timing for an attempt.</summary>
public sealed record FirstToken(string RequestId, ResolvedTarget Target, double AtMs) : TelemetryEvent;
/// <summary>Records successful completion of one attempt.</summary>
public sealed record AttemptCompleted(string RequestId, ResolvedTarget Target, Usage Usage, Timing Timing, string FinishReason) : TelemetryEvent;
/// <summary>Records a scheduled same-target retry.</summary>
public sealed record RetryScheduled(string RequestId, ResolvedTarget Target, int AttemptNumber, double DelayS, ErrorInfo Error) : TelemetryEvent;
/// <summary>Records a route advance.</summary>
public sealed record FallbackTriggered(string RequestId, ResolvedTarget FromTarget, string ToTarget, ErrorInfo? Error = null) : TelemetryEvent;
/// <summary>Records one schema repair attempt.</summary>
public sealed record RepairAttempted : TelemetryEvent
{
    /// <summary>Initializes a repair fact.</summary>
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
public sealed record RequestCompleted(string RequestId, ResolvedTarget Target, Usage Usage, Timing Timing, int RepairAttempts = 0, string? ResponseText = null) : TelemetryEvent;
/// <summary>Records terminal routed request failure.</summary>
public sealed record RequestFailed(string RequestId, ErrorInfo Error) : TelemetryEvent;
/// <summary>Records a parameter the target did not honour.</summary>
public sealed record ParameterDropped(string RequestId, ResolvedTarget Target, string Parameter, string Reason) : TelemetryEvent;
/// <summary>Records an advisory provider diagnostic.</summary>
public sealed record ProviderDiagnostic(ResolvedTarget? Target, Diagnostic Diagnostic, string? RequestId = null) : TelemetryEvent;
/// <summary>Marks a usage value as estimated rather than provider-reported.</summary>
public sealed record UsageEstimated(string RequestId, ResolvedTarget Target, string FieldName, string Method) : TelemetryEvent;
/// <summary>Records context reduction counts and limits.</summary>
public sealed record ContextReduced : TelemetryEvent
{
    /// <summary>Initializes a context-reduction fact.</summary>
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
public sealed record CachePlanned(string RequestId, ResolvedTarget Target, string Mechanism, int MarkCount, int EstimatedCacheableTokens) : TelemetryEvent;
/// <summary>Records client-side rate-limit waiting.</summary>
public sealed record RateLimitWaited(string RequestId,string ProviderId,double WaitedS,string Reason,ResolvedTarget? Target=null) : TelemetryEvent;
/// <summary>Records provider-reported rate-limit state.</summary>
public sealed record RateLimitObserved(string ProviderId,int? RequestsRemaining=null,int? TokensRemaining=null,double? ResetsInS=null) : TelemetryEvent;
/// <summary>Records supervised-server lifecycle state.</summary>
public sealed record ServerLifecycle(string ServerId,string State,string Detail="") : TelemetryEvent;
/// <summary>Records aggregate model-download progress.</summary>
public sealed record DownloadProgress(string ArtifactId,long DownloadedBytes,long? TotalBytes,bool Done=false,string Phase="",int FileIndex=0,int FileCount=0,string Filename="",long SessionBytes=0) : TelemetryEvent;
/// <summary>Records provider batch submission.</summary>
public sealed record BatchSubmitted(string BatchId,ResolvedTarget Target,int LineCount) : TelemetryEvent;
/// <summary>Records provider batch collection.</summary>
public sealed record BatchCompleted(string BatchId,ResolvedTarget Target,string Status,int Completed,int Failed) : TelemetryEvent;
/// <summary>Records a provider credential rotation without revealing the credential.</summary>
public sealed record CredentialRotated(string Provider,string Trigger="ttl") : TelemetryEvent;
