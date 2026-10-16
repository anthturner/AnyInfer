using AnyInfer.Json;

namespace AnyInfer;

public abstract record ContentPart;

public sealed record TextPart : ContentPart
{
    public TextPart(string text)
    {
        Text = text ?? throw new ArgumentNullException(nameof(text));
    }

    public string Text { get; }
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
}

public sealed record Target
{
    public Target(string providerId, string model)
    {
        ProviderId = providerId ?? throw new ArgumentNullException(nameof(providerId));
        Model = model ?? throw new ArgumentNullException(nameof(model));
    }

    public string ProviderId { get; }

    public string Model { get; }
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

public sealed record RepairOptions(int MaxAttempts = 1);

public sealed record RetryPolicy(int MaxAttempts = 2, double BackoffBaseS = 0.5, double BackoffMaxS = 30);

public sealed record Route
{
    public Route(
        IEnumerable<string> targets,
        RetryPolicy? retry = null,
        bool healthGate = true,
        double healthTtlS = 30)
    {
        ArgumentNullException.ThrowIfNull(targets);
        Targets = Array.AsReadOnly(targets.Select(static target => target ?? throw new ArgumentException("Route targets cannot be null.")).ToArray());
        Retry = retry ?? new RetryPolicy();
        HealthGate = healthGate;
        HealthTtlS = healthTtlS;
    }

    public IReadOnlyList<string> Targets { get; }
    public RetryPolicy Retry { get; }
    public bool HealthGate { get; }
    public double HealthTtlS { get; }
}

public sealed record Usage(
    long? InputTokens = null,
    long? OutputTokens = null,
    long? TotalTokens = null,
    long? CacheReadTokens = null,
    long? CacheWriteTokens = null,
    long? ReasoningTokens = null);

public sealed record GenerationTiming(double? FirstTokenMs = null, double? TotalMs = null);

public sealed record AttemptRecord
{
    public AttemptRecord(Target? target, string outcome, AnyInferException? error = null)
    {
        Target = target;
        Outcome = outcome ?? throw new ArgumentNullException(nameof(outcome));
        Error = error;
    }

    public Target? Target { get; }

    public string Outcome { get; }

    public AnyInferException? Error { get; }
}

public sealed record GenerationRequest
{
    public GenerationRequest(
        IEnumerable<Message> messages,
        Route route,
        Sampling? sampling = null,
        RepairOptions? repair = null,
        JsonValue? schema = null,
        string? schemaMechanism = null,
        double? timeoutS = null,
        int? maxResponseBytes = null,
        bool stream = false)
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
    }

    public IReadOnlyList<Message> Messages { get; }
    public Route Route { get; }
    public Sampling? Sampling { get; }
    public RepairOptions? Repair { get; }
    public JsonValue? Schema { get; }
    public string? SchemaMechanism { get; }
    public double? TimeoutS { get; }
    public int? MaxResponseBytes { get; }
    public bool Stream { get; }
}

public sealed record GenerationResult
{
    public GenerationResult(
        string text,
        JsonValue? structured = null,
        Target? target = null,
        string? finishReason = null,
        Usage? usage = null,
        GenerationTiming? timing = null,
        string? structuredMechanism = null,
        int repairAttempts = 0,
        IEnumerable<AttemptRecord>? attempts = null,
        IEnumerable<string>? warnings = null)
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
    }

    public string Text { get; }
    public JsonValue? Structured { get; }
    public Target? Target { get; }
    public string? FinishReason { get; }
    public Usage? Usage { get; }
    public GenerationTiming? Timing { get; }
    public string? StructuredMechanism { get; }
    public int RepairAttempts { get; }
    public IReadOnlyList<AttemptRecord> Attempts { get; }
    public IReadOnlyList<string> Warnings { get; }
}
