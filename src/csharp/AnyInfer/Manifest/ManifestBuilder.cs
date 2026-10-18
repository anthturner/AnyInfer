using System.Text;
using AnyInfer.Capabilities;
using AnyInfer.Core;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;

namespace AnyInfer.Manifest;

/// <summary>Folds one normalized request's facts into immutable manifest snapshots.</summary>
internal sealed class ManifestBuilder
{
    private readonly object _gate = new();
    private readonly string _requestId;
    private readonly NormalizedRequest _request;
    private readonly Route _route;
    private readonly Func<TargetMetadata, ModelCapabilities> _capabilitiesFor;
    private readonly bool _capturePayloads;
    private readonly string _version;
    private readonly List<AttemptFacet> _attempts = [];
    private readonly List<RouteStep> _steps = [];
    private readonly List<RepairRecord> _repairs = [];
    private readonly List<DroppedParameter> _dropped = [];
    private readonly List<string> _notes = [];
    private readonly List<string> _repairTexts = [];
    private readonly List<ReductionRecord> _reductions = [];
    private readonly Dictionary<string, string> _usageEstimates = new(StringComparer.Ordinal);
    private AttemptFacet? _current;
    private ModelCapabilities? _capabilities;
    private StructuredOutputProfile _legacyProfile = new();
    private string _capabilityTarget = "";
    private CacheFacet _cache = new();

    internal ManifestBuilder(
        string requestId,
        NormalizedRequest request,
        Route route,
        Func<TargetMetadata, ModelCapabilities> capabilitiesFor,
        bool capturePayloads,
        string anyinferVersion)
    {
        _requestId = requestId ?? throw new ArgumentNullException(nameof(requestId));
        _request = request ?? throw new ArgumentNullException(nameof(request));
        _route = route ?? throw new ArgumentNullException(nameof(route));
        _capabilitiesFor = capabilitiesFor ?? throw new ArgumentNullException(nameof(capabilitiesFor));
        _capturePayloads = capturePayloads;
        _version = anyinferVersion ?? throw new ArgumentNullException(nameof(anyinferVersion));
    }

    /// <summary>Records the full resolved capabilities outside the builder gate.</summary>
    internal void NoteCapabilities(TargetMetadata metadata)
    {
        ArgumentNullException.ThrowIfNull(metadata);
        var capabilities = (metadata.ResolvedCapabilities ?? _capabilitiesFor(metadata))
            ?? throw new InvalidOperationException("Capability lookup returned null.");
        lock (_gate)
        {
            _capabilities = capabilities;
            _legacyProfile = metadata.Capabilities;
            _capabilityTarget = metadata.Target.ToString();
        }
    }

    /// <summary>Records one privately captured failed repair response.</summary>
    internal void NoteRepairText(string text)
    {
        if (!_capturePayloads || string.IsNullOrEmpty(text))
        {
            return;
        }

        lock (_gate)
        {
            _repairTexts.Add(Redaction.Redact(text));
        }
    }

    /// <summary>Folds a single event using Python's nonempty foreign-ID correlation rule.</summary>
    internal void Fold(TelemetryEvent telemetryEvent)
    {
        ArgumentNullException.ThrowIfNull(telemetryEvent);
        lock (_gate)
        {
            switch (telemetryEvent)
            {
                case AttemptStarted e when Accepts(e.RequestId):
                    Flush();
                    _current = new AttemptFacet(target: e.Target.ToString(), attemptNumber: e.AttemptNumber);
                    break;
                case FirstToken e when Accepts(e.RequestId):
                    Update(firstTokenMs: e.AtMs);
                    break;
                case RateLimitWaited e when Accepts(e.RequestId):
                    RecordPacing(e);
                    break;
                case AttemptCompleted e when Accepts(e.RequestId):
                    Update(
                        outcome: "ok",
                        firstTokenMs: e.Timing.FirstTokenMs,
                        totalMs: e.Timing.TotalMs,
                        queuedMs: e.Timing.Phases.TryGetValue("queued_ms", out var queued) ? queued : null);
                    Flush();
                    _steps.Add(new RouteStep(target: e.Target.ToString(), outcome: "ok"));
                    break;
                case RetryScheduled e when Accepts(e.RequestId):
                    Update(outcome: "retried", error: e.Error, retryReason: e.Error.Detail, retryDelayS: e.DelayS);
                    Flush();
                    _steps.Add(new RouteStep(target: e.Target.ToString(), outcome: "retried", reason: e.Error.Detail ?? ""));
                    break;
                case FallbackTriggered e when Accepts(e.RequestId):
                    CloseFailed(e.Error);
                    _steps.Add(new RouteStep(
                        target: e.FromTarget.ToString(),
                        outcome: e.Error is null ? "redirected" : "abandoned",
                        reason: e.Error?.Detail ?? "a content-filter refusal redirected the route"));
                    break;
                case RepairAttempted e when Accepts(e.RequestId):
                    _repairs.Add(new RepairRecord(e.AttemptNumber, e.Mechanism, e.Errors));
                    // Deliberately duplicates a separately noted repair text, matching Python.
                    if (_capturePayloads && !string.IsNullOrEmpty(e.RawText))
                    {
                        _repairTexts.Add(Redaction.Redact(e.RawText));
                    }
                    break;
                case ParameterDropped e when Accepts(e.RequestId):
                    _dropped.Add(new DroppedParameter(e.Target.ToString(), e.Parameter, e.Reason));
                    break;
                case CachePlanned e when Accepts(e.RequestId):
                    _cache = new CacheFacet(
                        policyMode: _cache.PolicyMode,
                        mechanism: string.IsNullOrEmpty(e.Mechanism) ? _cache.Mechanism : e.Mechanism,
                        markCount: e.MarkCount,
                        estimatedCacheableTokens: e.EstimatedCacheableTokens,
                        readTokens: _cache.ReadTokens,
                        writeTokens: _cache.WriteTokens);
                    break;
                case ContextReduced e:
                    _reductions.Add(new ReductionRecord(
                        strategy: e.Strategy,
                        representation: e.Representation,
                        candidateCount: e.CandidateCount,
                        selectedCount: e.SelectedCount,
                        omittedCount: e.OmittedCount,
                        estimatedTokens: e.EstimatedTokens,
                        maxTokens: e.MaxTokens,
                        bindingConstraints: e.BindingConstraints,
                        calls: e.Calls,
                        complete: e.OmittedCount == 0));
                    break;
                case UsageEstimated e when Accepts(e.RequestId):
                    _usageEstimates[e.FieldName] = e.Method;
                    break;
                case ProviderDiagnostic e when Accepts(e.RequestId):
                    _notes.Add(Redaction.Redact(e.Diagnostic.Message));
                    break;
                case RequestFailed e when Accepts(e.RequestId):
                    CloseFailed(e.Error);
                    break;
            }
        }
    }

    /// <summary>Builds a nonterminal immutable snapshot.</summary>
    internal RunManifest BuildPartial() => Build();

    /// <summary>Builds a proposed terminal snapshot without publishing or retaining it.</summary>
    internal RunManifest Build(Generation? result = null)
    {
        lock (_gate)
        {
            var schema = _request.Schema;
            var usage = result?.Usage;
            var attempts = _current is null ? _attempts : [.. _attempts, _current];
            return new RunManifest(
                format: ManifestUtilities.Format,
                anyinferVersion: _version,
                requestId: _requestId,
                complete: result is not null,
                request: BuildRequestFacet(schema),
                route: new RouteFacet(requested: _route.Targets, resolved: result?.Target?.ToString(), considered: _steps),
                capability: BuildCapabilityFacet(),
                attempts: attempts,
                structured: BuildSchemaFacet(schema, result),
                cache: BuildCacheFacet(usage),
                context: new ContextFacet(_reductions),
                dropped: _dropped,
                usage: BuildUsageFacet(usage),
                timing: BuildTimingFacet(result?.Timing),
                notes: result is null ? _notes : [.. _notes, .. result.Warnings],
                payloads: BuildPayloadFacet(schema, result));
        }
    }

    private RequestFacet BuildRequestFacet(SchemaSpec? schema) => new(
        messageCount: _request.Messages.Count,
        roleCounts: RoleCounts(),
        charCount: _request.Messages.Sum(MessageLength),
        schemaPresent: schema is not null,
        schemaName: schema?.Name,
        schemaDigest: schema is null ? null : TrySchemaDigest(schema.JsonSchema),
        toolNames: [],
        toolChoice: "auto",
        sampling: Sampling(_request.Sampling),
        reasoning: null,
        timeoutS: _request.TimeoutS,
        repairBudget: _request.RepairBudget,
        metadataKeys: []);

    private CapabilityFacet BuildCapabilityFacet()
    {
        if (_capabilities is null)
        {
            return new CapabilityFacet();
        }

        var facts = new List<SourcedFact>();
        AddFact(facts, "context_window", _capabilities.ContextWindow, static value => new JsonInteger(value));
        AddFact(facts, "max_output_tokens", _capabilities.MaxOutputTokens, static value => new JsonInteger(value));
        AddFact(facts, "default_temperature", _capabilities.DefaultTemperature, static value => new JsonNumber(value));
        AddFact(facts, "default_top_p", _capabilities.DefaultTopP, static value => new JsonNumber(value));
        facts.Add(new SourcedFact(
            "features",
            new JsonArray(Enum.GetValues<Feature>()
                .Where(flag => flag != Feature.None && _capabilities.Features.Value.HasFlag(flag))
                .OrderBy(static flag => FeatureName(flag), StringComparer.Ordinal)
                .Select(static flag => (JsonValue)new JsonString(FeatureName(flag)))),
            ProvenanceName(_capabilities.Features.Provenance)));
        if (_capabilities.Pricing is { } pricing)
        {
            facts.Add(new SourcedFact(
                "pricing",
                new JsonObject([
                    new JsonProperty("input_per_1m", new JsonString(pricing.Value.InputPer1M.ToString())),
                    new JsonProperty("output_per_1m", new JsonString(pricing.Value.OutputPer1M.ToString())),
                    new JsonProperty("currency", new JsonString(pricing.Value.Currency)),
                ]),
                ProvenanceName(pricing.Provenance)));
        }

        return new CapabilityFacet(target: _capabilityTarget, facts: facts);
    }

    private SchemaFacet BuildSchemaFacet(SchemaSpec? schema, Generation? result)
    {
        if (schema is null)
        {
            return new SchemaFacet();
        }

        var ladder = Ladder();
        return new SchemaFacet(
            requested: true,
            chosen: ladder.FirstOrDefault(static rung => rung.Available)?.Mechanism,
            used: result?.StructuredMechanism,
            ladder: ladder,
            repairAttempts: result?.RepairAttempts ?? _repairs.Count,
            repairs: _repairs,
            validated: result?.Structured is not null);
    }

    private CacheFacet BuildCacheFacet(Usage? usage) => usage is null
        ? _cache
        : new CacheFacet(
            policyMode: _cache.PolicyMode,
            mechanism: _cache.Mechanism,
            markCount: _cache.MarkCount,
            estimatedCacheableTokens: _cache.EstimatedCacheableTokens,
            readTokens: usage.CacheReadTokens,
            writeTokens: usage.CacheWriteTokens);

    private UsageFacet BuildUsageFacet(Usage? usage) => usage is null
        ? new UsageFacet(estimatedFields: _usageEstimates)
        : new UsageFacet(
            inputTokens: usage.InputTokens,
            outputTokens: usage.OutputTokens,
            totalTokens: usage.TotalTokens,
            cacheReadTokens: usage.CacheReadTokens,
            cacheWriteTokens: usage.CacheWriteTokens,
            reasoningTokens: usage.ReasoningTokens,
            costUsd: usage.CostUsd?.ToString(),
            estimatedFields: _usageEstimates);

    private static TimingFacet BuildTimingFacet(Timing? timing) => timing is null
        ? new TimingFacet()
        : new TimingFacet(
            firstTokenMs: timing.FirstTokenMs,
            totalMs: timing.TotalMs,
            outputTokensPerS: timing.OutputTokensPerS,
            phases: timing.Phases);

    private PayloadFacet? BuildPayloadFacet(SchemaSpec? schema, Generation? result)
    {
        if (!_capturePayloads)
        {
            return null;
        }

        var prompt = Prompt();
        return new PayloadFacet(
            promptText: string.IsNullOrEmpty(prompt) ? null : Redaction.Redact(prompt),
            responseText: string.IsNullOrEmpty(result?.Text) ? null : Redaction.Redact(result.Text),
            schemaBody: schema is null ? null : TrySchemaPayload(schema.JsonSchema),
            toolArguments: [],
            repairTexts: _repairTexts);
    }

    private IReadOnlyList<MechanismRung> Ladder()
    {
        var features = _capabilities?.Features.Value ?? Feature.None;
        var fallback = _capabilities is not null && features == Feature.None && _capabilities.Features.Provenance == Provenance.Default;
        var candidates = new (string Mechanism, Feature Feature, bool LegacyFallback)[]
        {
            ("grammar", Feature.Grammar, fallback && _legacyProfile.Grammar),
            ("json_schema", Feature.JsonSchema, fallback && _legacyProfile.JsonSchema),
            ("json_mode", Feature.JsonMode, fallback && _legacyProfile.JsonMode),
        };
        var chosen = candidates.FirstOrDefault(candidate => features.HasFlag(candidate.Feature) || candidate.LegacyFallback).Mechanism ?? "prompt";
        var provenance = ProvenanceName(_capabilities?.Features.Provenance ?? Provenance.Default);
        var rungs = new List<MechanismRung>();
        foreach (var candidate in candidates)
        {
            var nativeAvailable = features.HasFlag(candidate.Feature);
            var available = nativeAvailable || candidate.LegacyFallback;
            var reason = !available
                ? $"the target is not known to support {FeatureName(candidate.Feature).ToLowerInvariant()} (capability provenance: {provenance})"
                : candidate.Mechanism != chosen
                    ? "a stronger mechanism was available"
                    : candidate.LegacyFallback && !nativeAvailable
                        ? "legacy structured-output profile compatibility fallback"
                        : "";
            rungs.Add(new MechanismRung(candidate.Mechanism, available, reason));
        }

        rungs.Add(new MechanismRung("prompt", available: true, reason: chosen == "prompt" ? "" : "a native mechanism was available"));
        return rungs;
    }

    private bool Accepts(string? eventRequestId) => string.IsNullOrEmpty(eventRequestId) || eventRequestId == _requestId;

    private void RecordPacing(RateLimitWaited waited)
    {
        if (_current is null)
        {
            return;
        }

        var paced = _current.PacedS.ToDictionary(static item => item.Key, static item => item.Value, StringComparer.Ordinal);
        paced[waited.Reason] = paced.GetValueOrDefault(waited.Reason) + waited.WaitedS;
        Update(pacedS: paced);
    }

    private void CloseFailed(ErrorInfo? error)
    {
        if (_current is null)
        {
            return;
        }

        if (_current.Outcome == "ok")
        {
            Update(outcome: "failed", error: error);
        }
        else if (error is not null && _current.Error is null)
        {
            Update(error: error);
        }

        Flush();
    }

    private void Flush()
    {
        if (_current is not null)
        {
            _attempts.Add(_current);
            _current = null;
        }
    }

    private void Update(
        string? outcome = null,
        ErrorInfo? error = null,
        double? firstTokenMs = null,
        double? totalMs = null,
        double? queuedMs = null,
        string? retryReason = null,
        double? retryDelayS = null,
        IReadOnlyDictionary<string, double>? pacedS = null)
    {
        if (_current is null)
        {
            return;
        }

        _current = new AttemptFacet(
            target: _current.Target,
            attemptNumber: _current.AttemptNumber,
            outcome: outcome ?? _current.Outcome,
            error: error ?? _current.Error,
            firstTokenMs: firstTokenMs ?? _current.FirstTokenMs,
            totalMs: totalMs ?? _current.TotalMs,
            queuedMs: queuedMs ?? _current.QueuedMs,
            retryReason: retryReason ?? _current.RetryReason,
            retryDelayS: retryDelayS ?? _current.RetryDelayS,
            pacedS: pacedS ?? _current.PacedS);
    }

    private IReadOnlyDictionary<string, int> RoleCounts() => _request.Messages
        .GroupBy(static message => message.Role, StringComparer.Ordinal)
        .ToDictionary(static group => group.Key, static group => group.Count(), StringComparer.Ordinal);

    private static int MessageLength(Message message) => message.Content.OfType<Text>().Sum(static text => text.Value.EnumerateRunes().Count());

    private string Prompt() => string.Join("\n\n", _request.Messages
        .Select(static message => string.Concat(message.Content.OfType<Text>().Select(static text => text.Value)))
        .Where(static text => !string.IsNullOrEmpty(text)));

    private static IReadOnlyDictionary<string, JsonValue> Sampling(Sampling value)
    {
        var values = new Dictionary<string, JsonValue>(StringComparer.Ordinal);
        if (value.Temperature is { } temperature) values["temperature"] = new JsonNumber(temperature);
        if (value.TopP is { } topP) values["top_p"] = new JsonNumber(topP);
        if (value.MaxOutputTokens is { } maximum) values["max_output_tokens"] = new JsonInteger(maximum);
        if (value.Stop is { Count: > 0 } stop) values["stop_count"] = new JsonInteger(stop.Count);
        return values;
    }

    private static string? TrySchemaDigest(JsonValue schema)
    {
        try { return ManifestUtilities.SchemaDigestValue(schema); }
        catch (Exception) { return null; }
    }

    private static string? TrySchemaPayload(JsonValue schema)
    {
        try { return Redaction.Redact(JsonWriter.WriteManifest(schema, indent: null)); }
        catch (Exception) { return null; }
    }

    private static void AddFact<T>(List<SourcedFact> facts, string name, Sourced<T>? source, Func<T, JsonValue> value)
    {
        if (source is null)
        {
            return;
        }

        try
        {
            facts.Add(new SourcedFact(name, value(source.Value), ProvenanceName(source.Provenance)));
        }
        catch (Exception)
        {
            // Manifest observation must not make an otherwise valid generation fail.
        }
    }

    private static string ProvenanceName(Provenance provenance) => provenance.ToString().ToLowerInvariant();

    private static string FeatureName(Feature feature) => feature switch
    {
        Feature.JsonSchema => "JSON_SCHEMA",
        Feature.JsonMode => "JSON_MODE",
        Feature.SystemPrompt => "SYSTEM_PROMPT",
        Feature.CacheUsage => "CACHE_USAGE",
        Feature.CachePlacement => "CACHE_PLACEMENT",
        Feature.AudioIn => "AUDIO_IN",
        Feature.VideoIn => "VIDEO_IN",
        Feature.WebSearch => "WEB_SEARCH",
        Feature.CodeExecution => "CODE_EXECUTION",
        _ => feature.ToString().ToUpperInvariant(),
    };
}
