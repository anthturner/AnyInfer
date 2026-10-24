using AnyInfer.Capabilities;
using AnyInfer.Json;
using AnyInfer.Internal;
using AnyInfer.Manifest;
using PeterO.Numbers;
using System.Collections.ObjectModel;

namespace AnyInfer;

public abstract record ContentPart;

/// <summary>Immutable snapshot helpers for rich generation values.</summary>
internal static class RichGenerationSnapshots
{
    internal static IReadOnlyList<byte>? Bytes(IEnumerable<byte>? values) => values is null
        ? null
        : Array.AsReadOnly(values.ToArray());

    internal static IReadOnlyList<T> List<T>(IEnumerable<T>? values, string parameterName)
    {
        var snapshot = (values ?? []).ToArray();
        if (snapshot.Any(static value => value is null)) throw new ArgumentException("Collections cannot contain null references.", parameterName);
        return Array.AsReadOnly(snapshot);
    }

    internal static JsonObject Object(JsonObject value) => new(value.Properties);
}

public sealed record Text : ContentPart
{
    public Text(string text)
    {
        Value = text ?? throw new ArgumentNullException(nameof(text));
    }

    public string Value { get; }
}

/// <summary>Represents a model-requested tool invocation in a message or terminal generation.</summary>
public sealed record ToolCall : ContentPart
{
    /// <summary>Creates an immutable tool invocation.</summary>
    public ToolCall(string id, string name, JsonObject arguments)
    {
        Id = id ?? throw new ArgumentNullException(nameof(id));
        Name = name ?? throw new ArgumentNullException(nameof(name));
        Arguments = arguments ?? throw new ArgumentNullException(nameof(arguments));
    }

    /// <summary>Gets the provider call identifier.</summary>
    public string Id { get; }

    /// <summary>Gets the requested tool name.</summary>
    public string Name { get; }

    /// <summary>Gets the parsed JSON object arguments.</summary>
    public JsonObject Arguments { get; }
}

/// <summary>Represents a tool result supplied to a subsequent model turn.</summary>
public sealed record ToolResult : ContentPart
{
    /// <summary>Creates an immutable tool result.</summary>
    public ToolResult(string callId, string content, bool isError = false)
    {
        CallId = callId ?? throw new ArgumentNullException(nameof(callId));
        Content = content ?? throw new ArgumentNullException(nameof(content));
        IsError = isError;
    }

    /// <summary>Gets the identifier of the answered tool call.</summary>
    public string CallId { get; }

    /// <summary>Gets text made available to the model.</summary>
    public string Content { get; }

    /// <summary>Gets whether the result describes a tool failure.</summary>
    public bool IsError { get; }
}

public sealed record UnsupportedContentPart : ContentPart
{
    public UnsupportedContentPart(string kind, JsonValue originalData)
    {
        Kind = kind ?? throw new ArgumentNullException(nameof(kind));
        OriginalData = originalData ?? throw new ArgumentNullException(nameof(originalData));
    }

    public string Kind { get; }

    public JsonValue OriginalData { get; }
}

public sealed record Message
{
    public Message(string role, IEnumerable<ContentPart> content)
    {
        Role = role ?? throw new ArgumentNullException(nameof(role));
        ArgumentNullException.ThrowIfNull(content);
        Content = Array.AsReadOnly(content.Select(static part => part ?? throw new ArgumentException("Message content cannot contain null references.")).ToArray());
    }

    public string Role { get; }

    public IReadOnlyList<ContentPart> Content { get; }

    /// <summary>Gets the concatenation of plain-text content parts only.</summary>
    public string Text => string.Concat(Content.OfType<AnyInfer.Text>().Select(static part => part.Value));

    public static Message User(string text) => new("user", [new Text(text)]);

    public static Message System(string text) => new("system", [new Text(text)]);

    public static Message Assistant(string text) => new("assistant", [new Text(text)]);
}

public sealed record ResolvedTarget
{
    public ResolvedTarget(string providerId, string model, string? viaAlias = null)
    {
        ProviderId = providerId ?? throw new ArgumentNullException(nameof(providerId));
        Model = model ?? throw new ArgumentNullException(nameof(model));
        ViaAlias = viaAlias;
    }

    public string ProviderId { get; }

    public string Model { get; }

    public string? ViaAlias { get; }

    public override string ToString() => $"{ProviderId}:{Model}";
}

public sealed record Sampling
{
    public Sampling(
        double? temperature = null,
        double? topP = null,
        int? maxOutputTokens = null,
        IEnumerable<string>? stop = null,
        long? seed = null,
        double? presencePenalty = null,
        double? frequencyPenalty = null)
    {
        Temperature = temperature;
        TopP = topP;
        MaxOutputTokens = maxOutputTokens;
        Stop = stop is null ? null : Array.AsReadOnly(stop.Select(static value => value ?? throw new ArgumentException("Stop values cannot be null.")).ToArray());
        Seed = seed;
        PresencePenalty = presencePenalty;
        FrequencyPenalty = frequencyPenalty;
    }

    public double? Temperature { get; }
    public double? TopP { get; }
    public int? MaxOutputTokens { get; }
    public IReadOnlyList<string>? Stop { get; }
    public long? Seed { get; }
    public double? PresencePenalty { get; }
    public double? FrequencyPenalty { get; }
}

public sealed record Repair(int MaxAttempts = 1);

public sealed record Retry(int MaxAttempts = 2, double BackoffBaseS = 0.5, double BackoffMaxS = 30);

public sealed record Route
{
    public Route(
        IEnumerable<string> targets,
        Retry? retry = null,
        bool healthGate = true,
        double healthTtlS = 30,
        IEnumerable<string>? contextWindowTargets = null)
    {
        ArgumentNullException.ThrowIfNull(targets);
        Targets = Array.AsReadOnly(targets.Select(static target => target ?? throw new ArgumentException("Route targets cannot be null.")).ToArray());
        Retry = retry ?? new Retry();
        HealthGate = healthGate;
        HealthTtlS = healthTtlS;
        ContextWindowTargets = Array.AsReadOnly((contextWindowTargets ?? []).Select(static target => target ?? throw new ArgumentException("Context-window targets cannot be null.")).ToArray());
    }

    public IReadOnlyList<string> Targets { get; }
    public Retry Retry { get; }
    public bool HealthGate { get; }
    public double HealthTtlS { get; }
    /// <summary>Gets the specialized fallback chain used after a context-window overflow.</summary>
    public IReadOnlyList<string> ContextWindowTargets { get; }
}

/// <summary>Provider-reported token and billing usage for one generation.</summary>
public sealed record Usage
{
    /// <summary>Creates an immutable usage snapshot.</summary>
    public Usage(
        long? InputTokens = null,
        long? OutputTokens = null,
        long? TotalTokens = null,
        long? CacheReadTokens = null,
        long? CacheWriteTokens = null,
        long? ReasoningTokens = null,
        EDecimal? CostUsd = null,
        long? SearchUnits = null,
        IReadOnlyDictionary<string, long>? ServerToolUses = null)
    {
        this.InputTokens = InputTokens;
        this.OutputTokens = OutputTokens;
        this.TotalTokens = TotalTokens;
        this.CacheReadTokens = CacheReadTokens;
        this.CacheWriteTokens = CacheWriteTokens;
        this.ReasoningTokens = ReasoningTokens;
        this.CostUsd = CostUsd;
        this.SearchUnits = SearchUnits;
        this.ServerToolUses = ServerToolUses ?? EmptyServerToolUses;
    }

    /// <summary>Gets prompt tokens, or <see langword="null"/> when unreported.</summary>
    public long? InputTokens { get; init; }
    /// <summary>Gets generated tokens, or <see langword="null"/> when unreported.</summary>
    public long? OutputTokens { get; init; }
    /// <summary>Gets total tokens, or <see langword="null"/> when unreported.</summary>
    public long? TotalTokens { get; init; }
    /// <summary>Gets prompt-cache read tokens, or <see langword="null"/> when unreported.</summary>
    public long? CacheReadTokens { get; init; }
    /// <summary>Gets prompt-cache write tokens, or <see langword="null"/> when unreported.</summary>
    public long? CacheWriteTokens { get; init; }
    /// <summary>Gets reasoning tokens, or <see langword="null"/> when unreported.</summary>
    public long? ReasoningTokens { get; init; }
    /// <summary>Gets reported United States dollar cost, or <see langword="null"/> when unknown.</summary>
    public EDecimal? CostUsd { get; init; }
    /// <summary>Gets provider-native billed search units, or <see langword="null"/> when unknown.</summary>
    public long? SearchUnits { get; init; }

    private IReadOnlyDictionary<string, long> _serverToolUses = EmptyServerToolUses;

    /// <summary>Gets an ordinal immutable snapshot of provider-run tool invocation counts.</summary>
    public IReadOnlyDictionary<string, long> ServerToolUses
    {
        get => _serverToolUses;
        init => _serverToolUses = SnapshotServerToolUses(value);
    }

    /// <summary>Fills total tokens from known input and output token counts.</summary>
    public Usage Normalized() =>
        TotalTokens is not null || InputTokens is null || OutputTokens is null
            ? this
            : this with { TotalTokens = checked(InputTokens.Value + OutputTokens.Value) };

    /// <summary>Overlays later-known values from <paramref name="other"/>.</summary>
    public Usage Merge(Usage other)
    {
        ArgumentNullException.ThrowIfNull(other);
        return new Usage(
            other.InputTokens ?? InputTokens,
            other.OutputTokens ?? OutputTokens,
            other.TotalTokens ?? TotalTokens,
            other.CacheReadTokens ?? CacheReadTokens,
            other.CacheWriteTokens ?? CacheWriteTokens,
            other.ReasoningTokens ?? ReasoningTokens,
            other.CostUsd ?? CostUsd,
            other.SearchUnits ?? SearchUnits);
    }

    /// <summary>Sums dimensions only when every usage record reports that dimension.</summary>
    public static Usage Sum(IEnumerable<Usage> parts)
    {
        ArgumentNullException.ThrowIfNull(parts);
        var snapshot = parts.Select(static part => part ?? throw new ArgumentException("Usage parts cannot contain null references.")).ToArray();
        return new Usage(
            SumKnown(snapshot.Select(static part => part.InputTokens)),
            SumKnown(snapshot.Select(static part => part.OutputTokens)),
            SumKnown(snapshot.Select(static part => part.TotalTokens)),
            SumKnown(snapshot.Select(static part => part.CacheReadTokens)),
            SumKnown(snapshot.Select(static part => part.CacheWriteTokens)),
            SumKnown(snapshot.Select(static part => part.ReasoningTokens)),
            SumKnownDecimal(snapshot.Select(static part => part.CostUsd)),
            SumKnownLong(snapshot.Select(static part => part.SearchUnits)));
    }

    /// <summary>Compares scalar usage values and ordinal server-tool counts.</summary>
    public bool Equals(Usage? other) =>
        ReferenceEquals(this, other) ||
        other is not null &&
        InputTokens == other.InputTokens &&
        OutputTokens == other.OutputTokens &&
        TotalTokens == other.TotalTokens &&
        CacheReadTokens == other.CacheReadTokens &&
        CacheWriteTokens == other.CacheWriteTokens &&
        ReasoningTokens == other.ReasoningTokens &&
        NullableDecimalEquals(CostUsd, other.CostUsd) &&
        SearchUnits == other.SearchUnits &&
        ServerToolUses.Count == other.ServerToolUses.Count &&
        ServerToolUses.All(item => other.ServerToolUses.TryGetValue(item.Key, out var value) && item.Value == value);

    /// <summary>Returns a value hash independent of server-tool map insertion order.</summary>
    public override int GetHashCode()
    {
        var hash = new HashCode();
        hash.Add(InputTokens);
        hash.Add(OutputTokens);
        hash.Add(TotalTokens);
        hash.Add(CacheReadTokens);
        hash.Add(CacheWriteTokens);
        hash.Add(ReasoningTokens);
        hash.Add(CostUsd is null ? 0 : AccountingDecimal.NumericHashCode(CostUsd));
        hash.Add(SearchUnits);
        foreach (var (key, value) in ServerToolUses.OrderBy(static item => item.Key, StringComparer.Ordinal))
        {
            hash.Add(key, StringComparer.Ordinal);
            hash.Add(value);
        }
        return hash.ToHashCode();
    }

    private static readonly IReadOnlyDictionary<string, long> EmptyServerToolUses =
        new ReadOnlyDictionary<string, long>(new Dictionary<string, long>(StringComparer.Ordinal));

    private static IReadOnlyDictionary<string, long> SnapshotServerToolUses(IReadOnlyDictionary<string, long>? values) =>
        new ReadOnlyDictionary<string, long>(values is null
            ? new Dictionary<string, long>(StringComparer.Ordinal)
            : new Dictionary<string, long>(values, StringComparer.Ordinal));

    private static long? SumKnown(IEnumerable<long?> values)
    {
        var snapshot = values.ToArray();
        return snapshot.Length == 0 || snapshot.Any(static value => value is null)
            ? null
            : snapshot.Sum(static value => value!.Value);
    }

    private static long? SumKnownLong(IEnumerable<long?> values)
    {
        var snapshot = values.ToArray();
        return snapshot.Length == 0 || snapshot.Any(static value => value is null)
            ? null
            : snapshot.Sum(static value => value!.Value);
    }

    private static EDecimal? SumKnownDecimal(IEnumerable<EDecimal?> values)
    {
        var snapshot = values.ToArray();
        if (snapshot.Length == 0 || snapshot.Any(static value => value is null))
        {
            return null;
        }

        var total = EDecimal.Zero;
        foreach (var value in snapshot)
        {
            total = AccountingDecimal.Add(total, value!);
        }
        return total;
    }

    private static bool NullableDecimalEquals(EDecimal? left, EDecimal? right) =>
        left is null ? right is null : right is not null && AccountingDecimal.NumericEquals(left, right);
}

public sealed record Timing
{
    public Timing(
        double startedAt = 0,
        double? firstTokenMs = null,
        double totalMs = 0,
        double? outputTokensPerS = null,
        IEnumerable<KeyValuePair<string, double>>? phases = null)
    {
        StartedAt = startedAt;
        FirstTokenMs = firstTokenMs;
        TotalMs = totalMs;
        OutputTokensPerS = outputTokensPerS;
        Phases = new ReadOnlyDictionary<string, double>(
            (phases ?? []).ToDictionary(static phase => phase.Key, static phase => phase.Value, StringComparer.Ordinal));
    }

    public double StartedAt { get; }
    public double? FirstTokenMs { get; }
    public double TotalMs { get; }
    public double? OutputTokensPerS { get; }
    public IReadOnlyDictionary<string, double> Phases { get; }
}

public sealed record AttemptRecord
{
    public AttemptRecord(
        ResolvedTarget? target,
        string outcome,
        AnyInferException? error = null,
        Timing? timing = null)
    {
        Target = target;
        Outcome = outcome ?? throw new ArgumentNullException(nameof(outcome));
        Error = error;
        Timing = timing;
    }

    public ResolvedTarget? Target { get; }

    public string Outcome { get; }

    public AnyInferException? Error { get; }

    /// <summary>Gets attempt timing when the operation measured it.</summary>
    public Timing? Timing { get; }
}

public sealed record GenerationRequest
{
    public GenerationRequest(
        IEnumerable<Message> messages,
        Route route,
        Sampling? sampling = null,
        Repair? repair = null,
        SchemaSpec? schema = null,
        string? schemaMechanism = null,
        double? timeoutS = null,
        int? maxResponseBytes = null,
        bool stream = false,
        IEnumerable<ToolSpec>? tools = null,
        string toolChoice = "auto",
        CachePolicy? cache = null,
        string? reasoning = null,
        IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null,
        int? logprobs = null,
        bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null,
        int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024)
    {
        ArgumentNullException.ThrowIfNull(messages);
        Messages = Array.AsReadOnly(messages.Select(static message => message ?? throw new ArgumentException("Messages cannot contain null references.")).ToArray());
        Route = route ?? throw new ArgumentNullException(nameof(route));
        Sampling = sampling;
        Repair = repair;
        Schema = schema;
        SchemaMechanism = schemaMechanism;
        TimeoutS = timeoutS;
        MaxResponseBytes = maxResponseBytes;
        Stream = stream;
        Tools = Array.AsReadOnly((tools ?? []).Select(static tool => tool ?? throw new ArgumentException("Tools cannot contain null references.")).ToArray());
        ToolChoice = toolChoice ?? throw new ArgumentNullException(nameof(toolChoice));
        Cache = cache;
        Reasoning = reasoning;
        ProviderOptions = SnapshotProviderOptions(providerOptions);
        Metadata = new ReadOnlyDictionary<string, string>(new Dictionary<string, string>(metadata ?? new Dictionary<string, string>(), StringComparer.Ordinal));
        if (logprobs is < 0 or > 20) throw new ArgumentOutOfRangeException(nameof(logprobs));
        Logprobs = logprobs;
        CiteDocuments = citeDocuments;
        ServerTools = RichGenerationSnapshots.List(serverTools, nameof(serverTools));
        if (maxInputPartBytes < 1 || maxInputBytes < 1) throw new ArgumentOutOfRangeException(nameof(maxInputPartBytes));
        MaxInputPartBytes = maxInputPartBytes;
        MaxInputBytes = maxInputBytes;
        ValidateInlineMediaBytes(Messages);
    }

    public IReadOnlyList<Message> Messages { get; }
    public Route Route { get; }
    public Sampling? Sampling { get; }
    public Repair? Repair { get; }
    public SchemaSpec? Schema { get; }
    public string? SchemaMechanism { get; }
    public double? TimeoutS { get; }
    public int? MaxResponseBytes { get; }
    public bool Stream { get; }
    /// <summary>Gets copied tool declarations in request order.</summary>
    public IReadOnlyList<ToolSpec> Tools { get; }
    /// <summary>Gets the requested tool-selection mode or tool name.</summary>
    public string ToolChoice { get; }
    /// <summary>Gets the per-request prompt-cache policy override.</summary>
    public CachePolicy? Cache { get; }
    /// <summary>Gets the requested normalized reasoning effort, or <see langword="null"/> for the provider default.</summary>
    public string? Reasoning { get; }
    /// <summary>Gets copied provider-specific option objects keyed by provider namespace.</summary>
    public IReadOnlyDictionary<string, JsonObject> ProviderOptions { get; }
    /// <summary>Gets copied opaque request labels.</summary>
    public IReadOnlyDictionary<string, string> Metadata { get; }
    /// <summary>Gets the requested number of alternative log-probabilities, or <see langword="null"/>.</summary>
    public int? Logprobs { get; }
    /// <summary>Gets whether citations were requested for supplied documents.</summary>
    public bool CiteDocuments { get; }
    /// <summary>Gets copied provider-run tool declarations.</summary>
    public IReadOnlyList<ServerToolSpec> ServerTools { get; }
    /// <summary>Gets the per-inline-part byte ceiling.</summary>
    public int MaxInputPartBytes { get; }
    /// <summary>Gets the aggregate inline-media byte ceiling.</summary>
    public int MaxInputBytes { get; }

    /// <summary>Returns a request with replacement messages and every other field preserved.</summary>
    public GenerationRequest WithMessages(IEnumerable<Message> messages) =>
        WithMessagesAndTools(messages, Tools);

    internal GenerationRequest WithMessagesAndTools(
        IEnumerable<Message> messages,
        IEnumerable<ToolSpec> tools) =>
        new(
            messages,
            Route,
            Sampling,
            Repair,
            Schema,
            SchemaMechanism,
            TimeoutS,
            MaxResponseBytes,
            Stream,
            tools,
            ToolChoice,
            Cache,
            Reasoning,
            ProviderOptions,
            Metadata,
            Logprobs,
            CiteDocuments,
            ServerTools,
            MaxInputPartBytes,
            MaxInputBytes);

    private static IReadOnlyDictionary<string, JsonObject> SnapshotProviderOptions(IReadOnlyDictionary<string, JsonObject>? values) =>
        new ReadOnlyDictionary<string, JsonObject>((values ?? new Dictionary<string, JsonObject>()).ToDictionary(
            static pair => pair.Key ?? throw new ArgumentException("Provider option namespaces cannot be null."),
            static pair => RichGenerationSnapshots.Object(pair.Value ?? throw new ArgumentException("Provider option objects cannot be null.")),
            StringComparer.Ordinal));

    private void ValidateInlineMediaBytes(IEnumerable<Message> messages)
    {
        long total = 0;
        foreach (var data in messages.SelectMany(static message => message.Content).Select(static part => part switch
        {
            ImagePart image => image.Data,
            DocumentPart document => document.Data,
            AudioPart audio => audio.Data,
            VideoPart video => video.Data,
            _ => null,
        }))
        {
            if (data is null) continue;
            if (data.Count > MaxInputPartBytes) throw new ArgumentOutOfRangeException(nameof(MaxInputPartBytes));
            total += data.Count;
            if (total > MaxInputBytes) throw new ArgumentOutOfRangeException(nameof(MaxInputBytes));
        }
    }
}

public sealed record Generation
{
    public Generation(
        string text,
        JsonValue? structured = null,
        ResolvedTarget? target = null,
        string? finishReason = null,
        Usage? usage = null,
        Timing? timing = null,
        string? structuredMechanism = null,
        int repairAttempts = 0,
        IEnumerable<AttemptRecord>? attempts = null,
        IEnumerable<string>? warnings = null,
        RunManifest? manifest = null,
        IEnumerable<ToolCall>? toolCalls = null,
        JsonValue? raw = null,
        IEnumerable<TokenLogprob>? logprobs = null,
        IEnumerable<Citation>? citations = null,
        IEnumerable<ServerToolUse>? serverToolUses = null,
        CacheMechanism? cacheMechanism = null)
    {
        Text = text ?? throw new ArgumentNullException(nameof(text));
        Structured = structured;
        Target = target;
        FinishReason = finishReason;
        Usage = usage;
        Timing = timing;
        StructuredMechanism = structuredMechanism;
        RepairAttempts = repairAttempts;
        Attempts = Array.AsReadOnly((attempts ?? []).Select(static attempt => attempt ?? throw new ArgumentException("Attempts cannot contain null references.")).ToArray());
        Warnings = Array.AsReadOnly((warnings ?? []).Select(static warning => warning ?? throw new ArgumentException("Warnings cannot contain null references.")).ToArray());
        Manifest = manifest;
        ToolCalls = Array.AsReadOnly((toolCalls ?? []).Select(static call => call ?? throw new ArgumentException("Tool calls cannot contain null references.")).ToArray());
        Raw = raw;
        Logprobs = RichGenerationSnapshots.List(logprobs, nameof(logprobs));
        Citations = RichGenerationSnapshots.List(citations, nameof(citations));
        ServerToolUses = RichGenerationSnapshots.List(serverToolUses, nameof(serverToolUses));
        CacheMechanism = cacheMechanism;
    }

    public string Text { get; }
    public JsonValue? Structured { get; }
    public ResolvedTarget? Target { get; }
    public string? FinishReason { get; }
    public Usage? Usage { get; }
    public Timing? Timing { get; }
    public string? StructuredMechanism { get; }
    public int RepairAttempts { get; }
    public IReadOnlyList<AttemptRecord> Attempts { get; }
    public IReadOnlyList<string> Warnings { get; }
    /// <summary>Gets the immutable terminal manifest when manifest capture was enabled.</summary>
    public RunManifest? Manifest { get; }
    /// <summary>Gets model-requested tool calls from the winning entry.</summary>
    public IReadOnlyList<ToolCall> ToolCalls { get; }
    /// <summary>Gets the caller-retained raw terminal provider payload when enabled.</summary>
    public JsonValue? Raw { get; }
    /// <summary>Gets copied token log-probabilities in generation order.</summary>
    public IReadOnlyList<TokenLogprob> Logprobs { get; }
    /// <summary>Gets copied citations in provider-reported order.</summary>
    public IReadOnlyList<Citation> Citations { get; }
    /// <summary>Gets copied counts of provider-run tool invocations.</summary>
    public IReadOnlyList<ServerToolUse> ServerToolUses { get; }
    /// <summary>Gets the prompt-cache mechanism used by the winning attempt, or <see langword="null"/> when none engaged.</summary>
    public CacheMechanism? CacheMechanism { get; }

    internal Generation WithManifest(RunManifest? manifest) => new(
        Text,
        Structured,
        Target,
        FinishReason,
        Usage,
        Timing,
        StructuredMechanism,
        RepairAttempts,
        Attempts,
        Warnings,
        manifest,
        ToolCalls,
        Raw,
        Logprobs,
        Citations,
        ServerToolUses,
        CacheMechanism);

    /// <summary>Deserializes the structured result with the supplied serializer options.</summary>
    public T? DeserializeStructured<T>(System.Text.Json.JsonSerializerOptions? options = null)
    {
        if (Structured is null)
        {
            throw new InvalidOperationException("This generation has no structured result to deserialize.");
        }

        return System.Text.Json.JsonSerializer.Deserialize<T>(Json.JsonWriter.WriteModern(Structured), options);
    }

    /// <summary>Deserializes the structured result with supplied type metadata.</summary>
    public T? DeserializeStructured<T>(System.Text.Json.Serialization.Metadata.JsonTypeInfo<T> typeInfo)
    {
        ArgumentNullException.ThrowIfNull(typeInfo);
        if (Structured is null)
        {
            throw new InvalidOperationException("This generation has no structured result to deserialize.");
        }

        return System.Text.Json.JsonSerializer.Deserialize(Json.JsonWriter.WriteModern(Structured), typeInfo);
    }
}
