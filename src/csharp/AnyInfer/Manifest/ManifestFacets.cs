using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Schema;

namespace AnyInfer.Manifest;

/// <summary>Records one consumed capability value and its provenance.</summary>
public sealed record SourcedFact
{
    /// <summary>Initializes a provenance-preserving capability fact.</summary>
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
public sealed record ReductionRecord
{
    /// <summary>Initializes one immutable context reduction.</summary>
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
public sealed record ContextFacet
{
    /// <summary>Initializes immutable context facts.</summary>
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
public sealed record PayloadFacet
{
    /// <summary>Initializes immutable redacted payload facts.</summary>
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
