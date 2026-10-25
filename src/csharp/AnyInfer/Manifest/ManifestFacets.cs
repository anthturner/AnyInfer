using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Schema;

namespace AnyInfer.Manifest;

/// <summary>Records one consumed capability value and its provenance.</summary>
/// <remarks>Equality compares <see cref="Value"/> with <see cref="JsonEquality.TypeAwareEquals(JsonValue, JsonValue)"/>.</remarks>
public sealed record SourcedFact
{
    /// <summary>Initializes a provenance-preserving capability fact.</summary>
    /// <param name="name">The capability field name, such as <c>context_window</c> or <c>features</c>.</param>
    /// <param name="value">The consumed value.</param>
    /// <param name="provenance">The lowercase name of the value's provenance.</param>
    /// <exception cref="ArgumentNullException">Any argument is <see langword="null"/>.</exception>
    public SourcedFact(string name, JsonValue value, string provenance)
    {
        Name = name ?? throw new ArgumentNullException(nameof(name));
        Value = value ?? throw new ArgumentNullException(nameof(value));
        Provenance = provenance ?? throw new ArgumentNullException(nameof(provenance));
    }

    /// <summary>Gets capability field name.</summary>
    public string Name { get; }

    /// <summary>Gets an arbitrary JSON value with tagged structural semantics.</summary>
    public JsonValue Value { get; }

    /// <summary>Gets source provenance.</summary>
    public string Provenance { get; }

    /// <inheritdoc />
    public bool Equals(SourcedFact? other)
    {
        return other is not null
            && Name == other.Name
            && Provenance == other.Provenance
            && JsonEquality.TypeAwareEquals(Value, other.Value);
    }

    /// <inheritdoc />
    public override int GetHashCode()
    {
        var hash = new HashCode();
        hash.Add(Name, StringComparer.Ordinal);
        hash.Add(Provenance, StringComparer.Ordinal);
        ImmutableValues.AddJsonHash(ref hash, Value);
        return hash.ToHashCode();
    }
}
/// <summary>Records request shape and fingerprints without default payload content.</summary>
public sealed record RequestFacet
{
    /// <summary>Initializes an immutable request facet.</summary>
    /// <param name="messageCount">The number of request messages.</param>
    /// <param name="roleCounts">The number of messages per role, or <see langword="null"/> for none. The pairs are copied.</param>
    /// <param name="charCount">The total length of the messages' text parts; clients count Unicode scalar values.</param>
    /// <param name="estimatedTokens">A planning token estimate, or <see langword="null"/> when none was recorded.</param>
    /// <param name="schemaPresent">Whether the request had a schema.</param>
    /// <param name="schemaName">The schema's <see cref="SchemaSpec.Name"/>, or <see langword="null"/> without a schema.</param>
    /// <param name="schemaDigest">
    /// The <see cref="ManifestUtilities.SchemaDigest(JsonObject)"/>-style <c>sha256:</c> digest of the
    /// schema, or <see langword="null"/> without a schema or when it could not be computed.
    /// </param>
    /// <param name="toolNames">Declared tool names in request order, or <see langword="null"/> for none.</param>
    /// <param name="toolChoice">The tool-choice spelling; defaults to <c>auto</c>.</param>
    /// <param name="sampling">
    /// Explicitly set sampling values keyed by name, or <see langword="null"/> for none. Clients
    /// record <c>temperature</c>, <c>top_p</c>, <c>max_output_tokens</c> and <c>stop_count</c>,
    /// the number of stop sequences rather than their text.
    /// </param>
    /// <param name="reasoning">The requested reasoning effort, or <see langword="null"/>.</param>
    /// <param name="timeoutS">The request timeout in seconds, or <see langword="null"/> when none was set.</param>
    /// <param name="repairBudget">The maximum number of schema repair attempts allowed.</param>
    /// <param name="metadataKeys">Request metadata keys, without their values, or <see langword="null"/> for none. Clients record them in ordinal order.</param>
    /// <exception cref="ArgumentNullException"><paramref name="toolChoice"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">A supplied collection contains a <see langword="null"/> element, key or value.</exception>
    public RequestFacet(
        int messageCount = 0,
        IEnumerable<KeyValuePair<string, int>>? roleCounts = null,
        int charCount = 0,
        int? estimatedTokens = null,
        bool schemaPresent = false,
        string? schemaName = null,
        string? schemaDigest = null,
        IEnumerable<string>? toolNames = null,
        string toolChoice = "auto",
        IEnumerable<KeyValuePair<string, JsonValue>>? sampling = null,
        string? reasoning = null,
        double? timeoutS = null,
        int repairBudget = 0,
        IEnumerable<string>? metadataKeys = null)
    {
        MessageCount = messageCount;
        RoleCounts = ImmutableValues.Map(roleCounts, nameof(roleCounts));
        CharCount = charCount;
        EstimatedTokens = estimatedTokens;
        SchemaPresent = schemaPresent;
        SchemaName = schemaName;
        SchemaDigest = schemaDigest;
        ToolNames = ImmutableValues.List(toolNames, nameof(toolNames));
        ToolChoice = toolChoice ?? throw new ArgumentNullException(nameof(toolChoice));
        Sampling = ImmutableValues.Map(sampling, nameof(sampling));
        Reasoning = reasoning;
        TimeoutS = timeoutS;
        RepairBudget = repairBudget;
        MetadataKeys = ImmutableValues.List(metadataKeys, nameof(metadataKeys));
    }
    /// <summary>Gets message count.</summary>
    public int MessageCount { get; }
    /// <summary>Gets per-role counts.</summary>
    public IReadOnlyDictionary<string,int> RoleCounts { get; }
    /// <summary>Gets total text character count.</summary>
    public int CharCount { get; }
    /// <summary>Gets a planning estimate when known.</summary>
    public int? EstimatedTokens { get; }
    /// <summary>Gets whether a schema was present.</summary>
    public bool SchemaPresent { get; }
    /// <summary>Gets schema label when present.</summary>
    public string? SchemaName { get; }
    /// <summary>Gets schema digest when present.</summary>
    public string? SchemaDigest { get; }
    /// <summary>Gets tool names in request order.</summary>
    public IReadOnlyList<string> ToolNames { get; }
    /// <summary>Gets tool-choice spelling.</summary>
    public string ToolChoice { get; }
    /// <summary>Gets explicitly set sampling facts.</summary>
    public IReadOnlyDictionary<string,JsonValue> Sampling { get; }
    /// <summary>Gets requested reasoning effort.</summary>
    public string? Reasoning { get; }
    /// <summary>Gets attempt timeout.</summary>
    public double? TimeoutS { get; }
    /// <summary>Gets repair budget.</summary>
    public int RepairBudget { get; }
    /// <summary>Gets sorted metadata keys.</summary>
    public IReadOnlyList<string> MetadataKeys { get; }
}
/// <summary>Records one route target considered by routing.</summary>
public sealed record RouteStep
{
    /// <summary>Initializes one route target decision.</summary>
    /// <param name="target">The target, as written in <c>provider:model</c> form.</param>
    /// <param name="outcome">
    /// The outcome spelling; clients record values such as <c>ok</c>, <c>retried</c>,
    /// <c>failed</c>, <c>abandoned</c>, <c>redirected</c> and <c>skipped_unhealthy</c>.
    /// </param>
    /// <param name="reason">The recorded reason, or empty (the default) when none applies.</param>
    /// <exception cref="ArgumentNullException">Any argument is <see langword="null"/>.</exception>
    public RouteStep(string target, string outcome, string reason = "")
    {
        Target = target ?? throw new ArgumentNullException(nameof(target));
        Outcome = outcome ?? throw new ArgumentNullException(nameof(outcome));
        Reason = reason ?? throw new ArgumentNullException(nameof(reason));
    }

    /// <summary>Gets the target considered by routing.</summary>
    public string Target { get; }

    /// <summary>Gets the route outcome.</summary>
    public string Outcome { get; }

    /// <summary>Gets the recorded route reason.</summary>
    public string Reason { get; }
}
/// <summary>Records requested, resolved and considered route facts.</summary>
public sealed record RouteFacet
{
    /// <summary>Initializes an immutable route facet.</summary>
    /// <param name="requested">The route's targets as requested, or <see langword="null"/> for none.</param>
    /// <param name="resolved">The target that produced the result, or <see langword="null"/> when none did.</param>
    /// <param name="considered">Target decisions in route order, or <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentException">A supplied list contains <see langword="null"/>.</exception>
    public RouteFacet(
        IEnumerable<string>? requested = null,
        string? resolved = null,
        IEnumerable<RouteStep>? considered = null)
    {
        Requested = ImmutableValues.List(requested, nameof(requested));
        Resolved = resolved;
        Considered = ImmutableValues.List(considered, nameof(considered));
    }
    /// <summary>Gets requested targets.</summary>
    public IReadOnlyList<string> Requested { get; }
    /// <summary>Gets successful target when any.</summary>
    public string? Resolved { get; }
    /// <summary>Gets considered targets in route order.</summary>
    public IReadOnlyList<RouteStep> Considered { get; }
}
/// <summary>Records capabilities consumed by an answering target.</summary>
public sealed record CapabilityFacet
{
    /// <summary>Initializes immutable capability facts.</summary>
    /// <param name="target">The target whose capabilities were consumed, or empty (the default) when none were recorded.</param>
    /// <param name="facts">The consumed facts in order, or <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="target"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="facts"/> contains <see langword="null"/>.</exception>
    public CapabilityFacet(string target = "", IEnumerable<SourcedFact>? facts = null)
    {
        Target = target ?? throw new ArgumentNullException(nameof(target));
        Facts = ImmutableValues.List(facts, nameof(facts));
    }

    /// <summary>Gets capability target.</summary>
    public string Target { get; }

    /// <summary>Gets facts in consumed order.</summary>
    public IReadOnlyList<SourcedFact> Facts { get; }
}
/// <summary>Records one attempt outcome.</summary>
public sealed record AttemptFacet
{
    /// <summary>Initializes an immutable attempt record.</summary>
    /// <param name="target">The attempted target in <c>provider:model</c> form.</param>
    /// <param name="attemptNumber">The one-based attempt number; defaults to 1.</param>
    /// <param name="outcome">The outcome spelling, such as <c>ok</c> (the default), <c>retried</c> or <c>failed</c>.</param>
    /// <param name="error">The error snapshot when the attempt failed or was retried, or <see langword="null"/>.</param>
    /// <param name="firstTokenMs">Time to first token in milliseconds, or <see langword="null"/> when not observed.</param>
    /// <param name="totalMs">Total attempt time in milliseconds, or <see langword="null"/> when not observed.</param>
    /// <param name="queuedMs">Time spent queued in milliseconds, or <see langword="null"/> when not observed.</param>
    /// <param name="retryReason">Why a retry was scheduled, or <see langword="null"/>.</param>
    /// <param name="retryDelayS">The scheduled retry delay in seconds, or <see langword="null"/>.</param>
    /// <param name="pacedS">Rate-limit pacing waits in seconds keyed by reason, or <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="target"/> or <paramref name="outcome"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="pacedS"/> contains a <see langword="null"/> key.</exception>
    public AttemptFacet(
        string target,
        int attemptNumber = 1,
        string outcome = "ok",
        ErrorInfo? error = null,
        double? firstTokenMs = null,
        double? totalMs = null,
        double? queuedMs = null,
        string? retryReason = null,
        double? retryDelayS = null,
        IEnumerable<KeyValuePair<string, double>>? pacedS = null)
    {
        Target = target ?? throw new ArgumentNullException(nameof(target));
        AttemptNumber = attemptNumber;
        Outcome = outcome ?? throw new ArgumentNullException(nameof(outcome));
        Error = error;
        FirstTokenMs = firstTokenMs;
        TotalMs = totalMs;
        QueuedMs = queuedMs;
        RetryReason = retryReason;
        RetryDelayS = retryDelayS;
        PacedS = ImmutableValues.Map(pacedS, nameof(pacedS));
    }

    /// <summary>Gets the attempted target.</summary>
    public string Target { get; }

    /// <summary>Gets the one-based attempt number.</summary>
    public int AttemptNumber { get; }

    /// <summary>Gets the attempt outcome.</summary>
    public string Outcome { get; }

    /// <summary>Gets the terminal error when the attempt failed.</summary>
    public ErrorInfo? Error { get; }

    /// <summary>Gets time to first token in milliseconds when observed.</summary>
    public double? FirstTokenMs { get; }

    /// <summary>Gets total attempt time in milliseconds when observed.</summary>
    public double? TotalMs { get; }

    /// <summary>Gets queue time in milliseconds when observed.</summary>
    public double? QueuedMs { get; }

    /// <summary>Gets the retry reason when one was scheduled.</summary>
    public string? RetryReason { get; }

    /// <summary>Gets retry delay in seconds when one was scheduled.</summary>
    public double? RetryDelayS { get; }

    /// <summary>Gets named pacing delays in seconds.</summary>
    public IReadOnlyDictionary<string, double> PacedS { get; }
}

/// <summary>Records one schema repair.</summary>
public sealed record RepairRecord
{
    /// <summary>Initializes one immutable schema repair record.</summary>
    /// <param name="attemptNumber">The one-based repair attempt number.</param>
    /// <param name="mechanism">The structured-output mechanism in use, or <see langword="null"/> when unknown.</param>
    /// <param name="errors">The validation messages that triggered the repair, in observation order, or <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentException"><paramref name="errors"/> contains <see langword="null"/>.</exception>
    public RepairRecord(int attemptNumber, string? mechanism = null, IEnumerable<string>? errors = null)
    {
        AttemptNumber = attemptNumber;
        Mechanism = mechanism;
        Errors = ImmutableValues.List(errors, nameof(errors));
    }

    /// <summary>Gets the one-based repair attempt number.</summary>
    public int AttemptNumber { get; }

    /// <summary>Gets the repair mechanism when known.</summary>
    public string? Mechanism { get; }

    /// <summary>Gets native validation errors in observation order.</summary>
    public IReadOnlyList<string> Errors { get; }
}

/// <summary>Records structured-output selection and repair facts.</summary>
public sealed record SchemaFacet
{
    /// <summary>Initializes immutable structured-output facts.</summary>
    /// <param name="requested">Whether the request asked for structured output.</param>
    /// <param name="chosen">The mechanism selected before execution, or <see langword="null"/>.</param>
    /// <param name="used">The mechanism that produced the final response, or <see langword="null"/> when none did.</param>
    /// <param name="ladder">Mechanism rungs in preference order, or <see langword="null"/> for none.</param>
    /// <param name="repairAttempts">The number of repair attempts made.</param>
    /// <param name="repairs">Repair records in attempt order, or <see langword="null"/> for none.</param>
    /// <param name="validated">Whether the final output passed schema validation.</param>
    /// <exception cref="ArgumentException">A supplied list contains <see langword="null"/>.</exception>
    public SchemaFacet(
        bool requested = false,
        string? chosen = null,
        string? used = null,
        IEnumerable<MechanismRung>? ladder = null,
        int repairAttempts = 0,
        IEnumerable<RepairRecord>? repairs = null,
        bool validated = false)
    {
        Requested = requested;
        Chosen = chosen;
        Used = used;
        Ladder = ImmutableValues.List(ladder, nameof(ladder));
        RepairAttempts = repairAttempts;
        Repairs = ImmutableValues.List(repairs, nameof(repairs));
        Validated = validated;
    }

    /// <summary>Gets whether structured output was requested.</summary>
    public bool Requested { get; }

    /// <summary>Gets the selected mechanism before execution.</summary>
    public string? Chosen { get; }

    /// <summary>Gets the mechanism used by the successful response.</summary>
    public string? Used { get; }

    /// <summary>Gets available mechanism rungs in preference order.</summary>
    public IReadOnlyList<MechanismRung> Ladder { get; }

    /// <summary>Gets the number of repair attempts.</summary>
    public int RepairAttempts { get; }

    /// <summary>Gets repair records in attempt order.</summary>
    public IReadOnlyList<RepairRecord> Repairs { get; }

    /// <summary>Gets whether final output was validated.</summary>
    public bool Validated { get; }
}

/// <summary>Records cache plan and provider-reported cache usage.</summary>
public sealed record CacheFacet
{
    /// <summary>Initializes immutable cache facts.</summary>
    /// <param name="policyMode">
    /// The lowercase <see cref="CacheMode"/> name of the effective cache policy (<c>off</c>,
    /// <c>auto</c> or <c>explicit</c>), or <see langword="null"/> when no policy applied.
    /// </param>
    /// <param name="mechanism">The planned cache mechanism, or <see langword="null"/> when none engaged.</param>
    /// <param name="markCount">The number of cache marks placed.</param>
    /// <param name="estimatedCacheableTokens">The planner's estimate of cacheable prefix tokens.</param>
    /// <param name="readTokens">Provider-reported cache read tokens, or <see langword="null"/> when not reported.</param>
    /// <param name="writeTokens">Provider-reported cache write tokens, or <see langword="null"/> when not reported.</param>
    public CacheFacet(string? policyMode = null, string? mechanism = null, int markCount = 0, long estimatedCacheableTokens = 0, long? readTokens = null, long? writeTokens = null)
    {
        PolicyMode = policyMode;
        Mechanism = mechanism;
        MarkCount = markCount;
        EstimatedCacheableTokens = estimatedCacheableTokens;
        ReadTokens = readTokens;
        WriteTokens = writeTokens;
    }

    /// <summary>Gets cache policy mode.</summary>
    public string? PolicyMode { get; }

    /// <summary>Gets the provider cache mechanism.</summary>
    public string? Mechanism { get; }

    /// <summary>Gets number of cache marks.</summary>
    public int MarkCount { get; }

    /// <summary>Gets estimated cacheable tokens.</summary>
    public long EstimatedCacheableTokens { get; }

    /// <summary>Gets provider-reported cache read tokens.</summary>
    public long? ReadTokens { get; }

    /// <summary>Gets provider-reported cache write tokens.</summary>
    public long? WriteTokens { get; }
}

/// <summary>Records one context reduction.</summary>
/// <remarks>
/// The C# SDK performs no context reduction, so manifests it produces contain no reduction
/// records; this type represents the format-1 shape, for example in a manifest read with
/// <see cref="RunManifest.FromJson(string)"/>.
/// </remarks>
public sealed record ReductionRecord
{
    /// <summary>Initializes one immutable context reduction.</summary>
    /// <param name="strategy">The reduction strategy name.</param>
    /// <param name="representation">The representation the selected content was rendered in.</param>
    /// <param name="candidateCount">The number of candidates considered.</param>
    /// <param name="selectedCount">The number of candidates selected.</param>
    /// <param name="omittedCount">The number of candidates omitted.</param>
    /// <param name="estimatedTokens">The estimated token count of the reduced content.</param>
    /// <param name="maxTokens">The token budget of the reduction.</param>
    /// <param name="bindingConstraints">The constraints that limited the reduction, in source order, or <see langword="null"/> for none.</param>
    /// <param name="calls">The number of reduction calls.</param>
    /// <param name="complete">Whether the reduction completed; defaults to <see langword="true"/>.</param>
    /// <exception cref="ArgumentNullException"><paramref name="strategy"/> or <paramref name="representation"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="bindingConstraints"/> contains <see langword="null"/>.</exception>
    public ReductionRecord(string strategy, string representation, int candidateCount = 0, int selectedCount = 0, int omittedCount = 0, int estimatedTokens = 0, int maxTokens = 0, IEnumerable<string>? bindingConstraints = null, int calls = 0, bool complete = true)
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
        Complete = complete;
    }

    /// <summary>Gets the reduction strategy.</summary>
    public string Strategy { get; }

    /// <summary>Gets the selected representation.</summary>
    public string Representation { get; }

    /// <summary>Gets number of candidates considered.</summary>
    public int CandidateCount { get; }

    /// <summary>Gets number of selected candidates.</summary>
    public int SelectedCount { get; }

    /// <summary>Gets number of omitted candidates.</summary>
    public int OmittedCount { get; }

    /// <summary>Gets estimated token count.</summary>
    public int EstimatedTokens { get; }

    /// <summary>Gets configured maximum token count.</summary>
    public int MaxTokens { get; }

    /// <summary>Gets binding constraints in source order.</summary>
    public IReadOnlyList<string> BindingConstraints { get; }

    /// <summary>Gets number of reduction calls.</summary>
    public int Calls { get; }

    /// <summary>Gets whether reduction completed.</summary>
    public bool Complete { get; }
}

/// <summary>Records context reductions in applied order.</summary>
/// <remarks>The C# SDK performs no context reduction, so this facet is empty in manifests it produces.</remarks>
public sealed record ContextFacet
{
    /// <summary>Initializes immutable context facts.</summary>
    /// <param name="reductions">Reductions in application order, or <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentException"><paramref name="reductions"/> contains <see langword="null"/>.</exception>
    public ContextFacet(IEnumerable<ReductionRecord>? reductions = null)
    {
        Reductions = ImmutableValues.List(reductions, nameof(reductions));
    }

    /// <summary>Gets reductions in application order.</summary>
    public IReadOnlyList<ReductionRecord> Reductions { get; }
}

/// <summary>Records a parameter degradation.</summary>
public sealed record DroppedParameter
{
    /// <summary>Initializes one parameter degradation record.</summary>
    /// <param name="target">The target in <c>provider:model</c> form where the parameter was dropped.</param>
    /// <param name="parameter">The dropped parameter name.</param>
    /// <param name="reason">Why the parameter was dropped.</param>
    /// <exception cref="ArgumentNullException">Any argument is <see langword="null"/>.</exception>
    public DroppedParameter(string target, string parameter, string reason)
    {
        Target = target ?? throw new ArgumentNullException(nameof(target));
        Parameter = parameter ?? throw new ArgumentNullException(nameof(parameter));
        Reason = reason ?? throw new ArgumentNullException(nameof(reason));
    }

    /// <summary>Gets the target where the parameter was dropped.</summary>
    public string Target { get; }

    /// <summary>Gets the dropped parameter name.</summary>
    public string Parameter { get; }

    /// <summary>Gets why the parameter was dropped.</summary>
    public string Reason { get; }
}

/// <summary>Records usage and the provenance of estimates without treating unknown cost as zero.</summary>
public sealed record UsageFacet
{
    /// <summary>Initializes immutable usage facts.</summary>
    /// <remarks>A <see langword="null"/> count or cost means unknown, never zero.</remarks>
    /// <param name="inputTokens">Input tokens, or <see langword="null"/> when unknown.</param>
    /// <param name="outputTokens">Output tokens, or <see langword="null"/> when unknown.</param>
    /// <param name="totalTokens">Total tokens, or <see langword="null"/> when unknown.</param>
    /// <param name="cacheReadTokens">Cache read tokens, or <see langword="null"/> when unknown.</param>
    /// <param name="cacheWriteTokens">Cache write tokens, or <see langword="null"/> when unknown.</param>
    /// <param name="reasoningTokens">Reasoning tokens, or <see langword="null"/> when unknown.</param>
    /// <param name="costUsd">The cost in US dollars as decimal text, or <see langword="null"/> when no trusted price applied.</param>
    /// <param name="estimatedFields">
    /// The estimation method for each usage field that was estimated rather than provider-reported,
    /// keyed by field name, or <see langword="null"/> for none.
    /// </param>
    /// <param name="searchUnits">Provider-reported search units, or <see langword="null"/> when unknown.</param>
    /// <exception cref="ArgumentException"><paramref name="estimatedFields"/> contains a <see langword="null"/> key or value.</exception>
    public UsageFacet(long? inputTokens = null, long? outputTokens = null, long? totalTokens = null, long? cacheReadTokens = null, long? cacheWriteTokens = null, long? reasoningTokens = null, string? costUsd = null, IEnumerable<KeyValuePair<string, string>>? estimatedFields = null, long? searchUnits = null)
    {
        InputTokens = inputTokens;
        OutputTokens = outputTokens;
        TotalTokens = totalTokens;
        CacheReadTokens = cacheReadTokens;
        CacheWriteTokens = cacheWriteTokens;
        ReasoningTokens = reasoningTokens;
        CostUsd = costUsd;
        EstimatedFields = ImmutableValues.Map(estimatedFields, nameof(estimatedFields));
        SearchUnits = searchUnits;
    }

    /// <summary>Gets input tokens when known.</summary>
    public long? InputTokens { get; }

    /// <summary>Gets output tokens when known.</summary>
    public long? OutputTokens { get; }

    /// <summary>Gets total tokens when known.</summary>
    public long? TotalTokens { get; }

    /// <summary>Gets cache read tokens when known.</summary>
    public long? CacheReadTokens { get; }

    /// <summary>Gets cache write tokens when known.</summary>
    public long? CacheWriteTokens { get; }

    /// <summary>Gets reasoning tokens when known.</summary>
    public long? ReasoningTokens { get; }

    /// <summary>Gets monetary cost in USD when known.</summary>
    public string? CostUsd { get; }

    /// <summary>Gets fields derived from an estimate.</summary>
    public IReadOnlyDictionary<string, string> EstimatedFields { get; }

    /// <summary>Gets provider-reported search units when known.</summary>
    public long? SearchUnits { get; }
}

/// <summary>Records request timing.</summary>
public sealed record TimingFacet
{
    /// <summary>Initializes immutable timing facts.</summary>
    /// <param name="firstTokenMs">Time to first token in milliseconds, or <see langword="null"/> when not observed.</param>
    /// <param name="totalMs">Total time in milliseconds, or <see langword="null"/> when not observed.</param>
    /// <param name="outputTokensPerS">Output tokens per second, or <see langword="null"/> when not observed.</param>
    /// <param name="phases">Named timing phases in milliseconds, or <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentException"><paramref name="phases"/> contains a <see langword="null"/> key.</exception>
    public TimingFacet(double? firstTokenMs = null, double? totalMs = null, double? outputTokensPerS = null, IEnumerable<KeyValuePair<string, double>>? phases = null)
    {
        FirstTokenMs = firstTokenMs;
        TotalMs = totalMs;
        OutputTokensPerS = outputTokensPerS;
        Phases = ImmutableValues.Map(phases, nameof(phases));
    }

    /// <summary>Gets time to first token in milliseconds when observed.</summary>
    public double? FirstTokenMs { get; }

    /// <summary>Gets total request time in milliseconds when observed.</summary>
    public double? TotalMs { get; }

    /// <summary>Gets output tokens per second when observed.</summary>
    public double? OutputTokensPerS { get; }

    /// <summary>Gets named timing phases in milliseconds.</summary>
    public IReadOnlyDictionary<string, double> Phases { get; }
}

/// <summary>Records redacted payload content when explicitly captured.</summary>
/// <remarks>
/// Clients record this facet only when payload capture is enabled, and only for generation.
/// Redaction replaces secret values registered with <see cref="AnyInfer.Redaction"/>; all
/// other content, including personal data, is kept.
/// </remarks>
public sealed record PayloadFacet
{
    /// <summary>Initializes immutable redacted payload facts.</summary>
    /// <param name="promptText">The text parts of the request messages joined by blank lines, or <see langword="null"/> when empty.</param>
    /// <param name="responseText">The final response text, or <see langword="null"/> when empty.</param>
    /// <param name="schemaBody">The request schema as compact JSON, or <see langword="null"/> without a schema.</param>
    /// <param name="toolArguments">The arguments of each returned tool call as compact JSON, in call order, or <see langword="null"/> for none.</param>
    /// <param name="repairTexts">
    /// Response texts that triggered schema repairs, in repair order, or <see langword="null"/> for
    /// none; the same response can appear more than once.
    /// </param>
    /// <exception cref="ArgumentException">A supplied list contains <see langword="null"/>.</exception>
    public PayloadFacet(string? promptText = null, string? responseText = null, string? schemaBody = null, IEnumerable<string>? toolArguments = null, IEnumerable<string>? repairTexts = null)
    {
        PromptText = promptText;
        ResponseText = responseText;
        SchemaBody = schemaBody;
        ToolArguments = ImmutableValues.List(toolArguments, nameof(toolArguments));
        RepairTexts = ImmutableValues.List(repairTexts, nameof(repairTexts));
    }

    /// <summary>Gets redacted prompt text when captured.</summary>
    public string? PromptText { get; }

    /// <summary>Gets redacted response text when captured.</summary>
    public string? ResponseText { get; }

    /// <summary>Gets redacted schema text when captured.</summary>
    public string? SchemaBody { get; }

    /// <summary>Gets redacted tool arguments in call order.</summary>
    public IReadOnlyList<string> ToolArguments { get; }

    /// <summary>Gets redacted repair text in repair order.</summary>
    public IReadOnlyList<string> RepairTexts { get; }
}
