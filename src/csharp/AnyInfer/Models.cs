using AnyInfer.Capabilities;
using AnyInfer.Json;
using AnyInfer.Internal;
using AnyInfer.Manifest;
using PeterO.Numbers;
using System.Collections.ObjectModel;

namespace AnyInfer;

/// <summary>Base type for one part of a <see cref="Message"/>'s content.</summary>
/// <remarks>
/// A generation request accepts <see cref="AnyInfer.Text"/>, <see cref="ToolCall"/>, <see cref="ToolResult"/>,
/// <see cref="ImagePart"/>, <see cref="DocumentPart"/>, <see cref="AudioPart"/>, and <see cref="VideoPart"/>.
/// Any other part, including <see cref="UnsupportedContentPart"/>, makes the request fail admission with a
/// <see cref="ProviderException"/> whose category is <c>unsupported_input</c>.
/// </remarks>
public abstract record ContentPart
{
    // Declared explicitly only so the constructor the compiler would otherwise synthesize is documented.
    /// <summary>Initializes the base state of a derived content part.</summary>
    protected ContentPart() { }
}

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

/// <summary>Plain text content.</summary>
public sealed record Text : ContentPart
{
    /// <summary>Creates a text part.</summary>
    /// <param name="text">The text; may be empty.</param>
    /// <exception cref="ArgumentNullException"><paramref name="text"/> is <see langword="null"/>.</exception>
    public Text(string text)
    {
        Value = text ?? throw new ArgumentNullException(nameof(text));
    }

    /// <summary>Gets the text.</summary>
    public string Value { get; }
}

/// <summary>Represents a model-requested tool invocation in a message or terminal generation.</summary>
public sealed record ToolCall : ContentPart
{
    /// <summary>Creates an immutable tool invocation.</summary>
    /// <param name="id">The provider call identifier; a <see cref="ToolResult"/> answers the call by this value.</param>
    /// <param name="name">The name of the requested tool.</param>
    /// <param name="arguments">The parsed JSON object arguments.</param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="id"/>, <paramref name="name"/>, or <paramref name="arguments"/> is <see langword="null"/>.
    /// </exception>
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
    /// <param name="callId">The <see cref="ToolCall.Id"/> of the call this result answers.</param>
    /// <param name="content">The text made available to the model.</param>
    /// <param name="isError"><see langword="true"/> when the content describes a tool failure.</param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="callId"/> or <paramref name="content"/> is <see langword="null"/>.
    /// </exception>
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

/// <summary>A content part of a kind this SDK does not model, kept with its original JSON data.</summary>
/// <remarks>
/// A generation request that contains one fails admission with a <see cref="ProviderException"/> whose category is
/// <c>unsupported_input</c>, before any provider is called.
/// </remarks>
public sealed record UnsupportedContentPart : ContentPart
{
    /// <summary>Creates a placeholder for content the SDK does not model.</summary>
    /// <param name="kind">The part's kind as named by its source data, such as <c>image</c>.</param>
    /// <param name="originalData">The part's original JSON value, kept by reference without rewriting.</param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="kind"/> or <paramref name="originalData"/> is <see langword="null"/>.
    /// </exception>
    public UnsupportedContentPart(string kind, JsonValue originalData)
    {
        Kind = kind ?? throw new ArgumentNullException(nameof(kind));
        OriginalData = originalData ?? throw new ArgumentNullException(nameof(originalData));
    }

    /// <summary>Gets the part's kind as named by its source data.</summary>
    public string Kind { get; }

    /// <summary>Gets the part's original JSON value.</summary>
    public JsonValue OriginalData { get; }
}

/// <summary>One conversation turn: a role and its ordered content parts.</summary>
/// <remarks>
/// A generation request accepts the roles <c>system</c>, <c>user</c>, <c>assistant</c>, and <c>tool</c>. The
/// constructor does not check the role; a request containing any other role fails admission with a
/// <see cref="ProviderException"/> whose category is <c>unsupported_input</c>.
/// </remarks>
public sealed record Message
{
    /// <summary>Creates a message from a role and content parts.</summary>
    /// <param name="role">The speaker role, such as <c>user</c>.</param>
    /// <param name="content">The content parts in order; the sequence is copied.</param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="role"/> or <paramref name="content"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="ArgumentException"><paramref name="content"/> contains a <see langword="null"/> element.</exception>
    public Message(string role, IEnumerable<ContentPart> content)
    {
        Role = role ?? throw new ArgumentNullException(nameof(role));
        ArgumentNullException.ThrowIfNull(content);
        Content = Array.AsReadOnly(content.Select(static part => part ?? throw new ArgumentException("Message content cannot contain null references.")).ToArray());
    }

    /// <summary>Gets the speaker role.</summary>
    public string Role { get; }

    /// <summary>Gets the copied content parts in order.</summary>
    public IReadOnlyList<ContentPart> Content { get; }

    /// <summary>Gets the concatenation of plain-text content parts only.</summary>
    public string Text => string.Concat(Content.OfType<AnyInfer.Text>().Select(static part => part.Value));

    /// <summary>Creates a user message containing one text part.</summary>
    /// <param name="text">The message text.</param>
    /// <returns>A message with role <c>user</c>.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="text"/> is <see langword="null"/>.</exception>
    public static Message User(string text) => new("user", [new Text(text)]);

    /// <summary>Creates a system message containing one text part.</summary>
    /// <param name="text">The message text.</param>
    /// <returns>A message with role <c>system</c>.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="text"/> is <see langword="null"/>.</exception>
    public static Message System(string text) => new("system", [new Text(text)]);

    /// <summary>Creates an assistant message containing one text part.</summary>
    /// <param name="text">The message text.</param>
    /// <returns>A message with role <c>assistant</c>.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="text"/> is <see langword="null"/>.</exception>
    public static Message Assistant(string text) => new("assistant", [new Text(text)]);
}

/// <summary>A route target resolved to a configured provider instance and a provider-native model.</summary>
public sealed record ResolvedTarget
{
    /// <summary>Creates a resolved target.</summary>
    /// <param name="providerId">The configured provider instance identifier.</param>
    /// <param name="model">The provider-native model name.</param>
    /// <param name="viaAlias">
    /// The catalog alias that resolved to this target, or <see langword="null"/> when the target was written as
    /// <c>provider:model</c>.
    /// </param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="providerId"/> or <paramref name="model"/> is <see langword="null"/>.
    /// </exception>
    public ResolvedTarget(string providerId, string model, string? viaAlias = null)
    {
        ProviderId = providerId ?? throw new ArgumentNullException(nameof(providerId));
        Model = model ?? throw new ArgumentNullException(nameof(model));
        ViaAlias = viaAlias;
    }

    /// <summary>Gets the configured provider instance identifier.</summary>
    public string ProviderId { get; }

    /// <summary>Gets the provider-native model name.</summary>
    public string Model { get; }

    /// <summary>Gets the catalog alias that resolved to this target, or <see langword="null"/>.</summary>
    public string? ViaAlias { get; }

    /// <summary>Formats the target as <c>provider:model</c>.</summary>
    /// <returns>The provider instance identifier and model joined by a colon; any alias is omitted.</returns>
    public override string ToString() => $"{ProviderId}:{Model}";
}

/// <summary>Optional sampling controls for one generation.</summary>
/// <remarks>
/// A <see langword="null"/> value leaves the provider default in place. A target that accepts but ignores a supplied
/// value reports it with a <see cref="Events.ParameterDropped"/> telemetry event. A negative seed or a non-finite
/// penalty makes the request fail admission with a <see cref="ProviderException"/> whose category is
/// <c>invalid_request</c>.
/// </remarks>
public sealed record Sampling
{
    /// <summary>Creates sampling controls.</summary>
    /// <param name="temperature">The sampling temperature, or <see langword="null"/> for the provider default.</param>
    /// <param name="topP">The nucleus-sampling probability mass, or <see langword="null"/> for the provider default.</param>
    /// <param name="maxOutputTokens">The most tokens to generate, or <see langword="null"/> for the provider default.</param>
    /// <param name="stop">
    /// Sequences that end generation, or <see langword="null"/> for none; copied. An empty sequence is treated as none.
    /// </param>
    /// <param name="seed">A non-negative seed for providers that support repeatable sampling, or <see langword="null"/>.</param>
    /// <param name="presencePenalty">A finite presence penalty, or <see langword="null"/> for the provider default.</param>
    /// <param name="frequencyPenalty">A finite frequency penalty, or <see langword="null"/> for the provider default.</param>
    /// <exception cref="ArgumentException"><paramref name="stop"/> contains a <see langword="null"/> element.</exception>
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

    /// <summary>Gets the sampling temperature, or <see langword="null"/> for the provider default.</summary>
    public double? Temperature { get; }
    /// <summary>Gets the nucleus-sampling probability mass, or <see langword="null"/> for the provider default.</summary>
    public double? TopP { get; }
    /// <summary>Gets the most tokens to generate, or <see langword="null"/> for the provider default.</summary>
    public int? MaxOutputTokens { get; }
    /// <summary>Gets the copied stop sequences, or <see langword="null"/> when none were given.</summary>
    public IReadOnlyList<string>? Stop { get; }
    /// <summary>Gets the sampling seed, or <see langword="null"/>.</summary>
    public long? Seed { get; }
    /// <summary>Gets the presence penalty, or <see langword="null"/> for the provider default.</summary>
    public double? PresencePenalty { get; }
    /// <summary>Gets the frequency penalty, or <see langword="null"/> for the provider default.</summary>
    public double? FrequencyPenalty { get; }
}

/// <summary>The schema-repair budget for a structured generation.</summary>
/// <remarks>
/// Applies only when the request has a schema. When a structured response fails validation, the library sends the
/// same target a correction request, up to this many times; when the budget is exhausted the request fails with
/// <see cref="SchemaViolationException"/>. A provider can allow fewer round trips, in which case the lower ceiling
/// applies and a <see cref="Events.ParameterDropped"/> event for <c>repair.max_attempts</c> is emitted.
/// </remarks>
/// <param name="MaxAttempts">The most correction round trips per target; values below <c>0</c> are treated as <c>0</c>.</param>
public sealed record Repair(int MaxAttempts = 1);

/// <summary>The same-target retry policy of a <see cref="Route"/>.</summary>
/// <remarks>
/// Only failures marked retryable are retried, and generation never retries authentication or context-length
/// failures. The delay before the next attempt is <see cref="BackoffBaseS"/> × 2^(n − 1) for failed attempt n,
/// raised to any provider-requested retry-after, then capped at <see cref="BackoffMaxS"/>.
/// </remarks>
/// <param name="MaxAttempts">The total attempts per target, including the first; generation treats values below <c>1</c> as <c>1</c>.</param>
/// <param name="BackoffBaseS">The base backoff delay, in seconds.</param>
/// <param name="BackoffMaxS">The longest delay between attempts, in seconds.</param>
public sealed record Retry(int MaxAttempts = 2, double BackoffBaseS = 0.5, double BackoffMaxS = 30);

/// <summary>An ordered fallback route with same-target retry and health-gate settings.</summary>
/// <remarks>
/// Targets are tried in order; when one fails without a successful retry, the route moves on to the next. When every
/// target fails, the request fails with <see cref="AllTargetsFailedException"/>.
/// </remarks>
public sealed record Route
{
    /// <summary>Creates a route.</summary>
    /// <param name="targets">The targets to try in order, each <c>provider:model</c> or a catalog alias; copied.</param>
    /// <param name="retry">The same-target retry policy, or <see langword="null"/> for the <see cref="AnyInfer.Retry"/> defaults.</param>
    /// <param name="healthGate">
    /// Whether to skip targets this client has recently marked unhealthy after a failure. A skipped target is recorded
    /// with the attempt outcome <c>skipped_unhealthy</c>.
    /// </param>
    /// <param name="healthTtlS">How long, in seconds, an unhealthy mark keeps a target skipped.</param>
    /// <param name="contextWindowTargets">
    /// Targets that replace the rest of the route after a generation fails with a context-length error, skipping any
    /// already tried; <see langword="null"/> or empty keeps the normal route. Copied.
    /// </param>
    /// <exception cref="ArgumentNullException"><paramref name="targets"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">
    /// <paramref name="targets"/> or <paramref name="contextWindowTargets"/> contains a <see langword="null"/> element.
    /// </exception>
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

    /// <summary>Gets the copied targets in the order they are tried.</summary>
    public IReadOnlyList<string> Targets { get; }
    /// <summary>Gets the same-target retry policy.</summary>
    public Retry Retry { get; }
    /// <summary>Gets whether targets recently marked unhealthy are skipped.</summary>
    public bool HealthGate { get; }
    /// <summary>Gets how long, in seconds, an unhealthy mark keeps a target skipped.</summary>
    public double HealthTtlS { get; }
    /// <summary>Gets the specialized fallback chain used after a context-window overflow.</summary>
    public IReadOnlyList<string> ContextWindowTargets { get; }
}

/// <summary>Provider-reported token and billing usage for one generation.</summary>
public sealed record Usage
{
    /// <summary>Creates an immutable usage snapshot.</summary>
    /// <param name="InputTokens">Prompt tokens, or <see langword="null"/> when unreported.</param>
    /// <param name="OutputTokens">Generated tokens, or <see langword="null"/> when unreported.</param>
    /// <param name="TotalTokens">Total tokens, or <see langword="null"/> when unreported.</param>
    /// <param name="CacheReadTokens">Prompt tokens read from the provider's prompt cache, or <see langword="null"/> when unreported.</param>
    /// <param name="CacheWriteTokens">Prompt tokens written to the provider's prompt cache, or <see langword="null"/> when unreported.</param>
    /// <param name="ReasoningTokens">Reasoning tokens, or <see langword="null"/> when unreported.</param>
    /// <param name="CostUsd">The cost in United States dollars, or <see langword="null"/> when unknown.</param>
    /// <param name="SearchUnits">Provider-native billed search units, or <see langword="null"/> when unknown.</param>
    /// <param name="ServerToolUses">
    /// Provider-run tool invocation counts keyed by tool kind, or <see langword="null"/> for none; copied with ordinal
    /// keys.
    /// </param>
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
    /// <returns>
    /// This instance when <see cref="TotalTokens"/> is already known or either count is unknown; otherwise a copy whose
    /// <see cref="TotalTokens"/> is <see cref="InputTokens"/> plus <see cref="OutputTokens"/>.
    /// </returns>
    /// <exception cref="OverflowException">The sum exceeds <see cref="long.MaxValue"/>.</exception>
    public Usage Normalized() =>
        TotalTokens is not null || InputTokens is null || OutputTokens is null
            ? this
            : this with { TotalTokens = checked(InputTokens.Value + OutputTokens.Value) };

    /// <summary>Overlays later-known values from <paramref name="other"/>.</summary>
    /// <param name="other">The later usage report whose known values take precedence.</param>
    /// <returns>
    /// A new usage in which each scalar value is taken from <paramref name="other"/> when it reports one and from this
    /// instance otherwise. <see cref="ServerToolUses"/> is not carried over; the result's map is empty.
    /// </returns>
    /// <exception cref="ArgumentNullException"><paramref name="other"/> is <see langword="null"/>.</exception>
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
    /// <param name="parts">The usage records to add.</param>
    /// <returns>
    /// A new usage in which each scalar value is the sum across <paramref name="parts"/>, or <see langword="null"/>
    /// when any part leaves it unreported or <paramref name="parts"/> is empty. <see cref="ServerToolUses"/> is not
    /// summed; the result's map is empty.
    /// </returns>
    /// <exception cref="ArgumentNullException"><paramref name="parts"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="parts"/> contains a <see langword="null"/> element.</exception>
    /// <exception cref="OverflowException">A token or unit sum exceeds <see cref="long.MaxValue"/>.</exception>
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
    /// <param name="other">The usage to compare with, or <see langword="null"/>.</param>
    /// <returns>
    /// <see langword="true"/> when every scalar value is equal (costs compared numerically) and both server-tool maps
    /// hold the same entries; otherwise <see langword="false"/>.
    /// </returns>
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
    /// <returns>A hash code consistent with <see cref="Equals(Usage?)"/>.</returns>
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

/// <summary>Centrally measured timing for one provider call.</summary>
/// <remarks>
/// The library measures these values itself, so they mean the same thing for every provider. An all-default value
/// stands for timing that was not measured.
/// </remarks>
public sealed record Timing
{
    /// <summary>Creates a timing record.</summary>
    /// <param name="startedAt">
    /// A monotonic clock reading, in seconds, taken when the call began; meaningful only for computing intervals, not
    /// as wall-clock time. <c>0</c> when not measured.
    /// </param>
    /// <param name="firstTokenMs">
    /// Milliseconds from the start of the call to its first text, reasoning, or tool-call fragment, or
    /// <see langword="null"/> when no content arrived or it was not measured.
    /// </param>
    /// <param name="totalMs">Milliseconds from the start of the call to its completion.</param>
    /// <param name="outputTokensPerS">
    /// Output tokens per second, measured from the first fragment to completion, or <see langword="null"/> when the
    /// output token count or first-fragment time is unknown.
    /// </param>
    /// <param name="phases">
    /// Provider-reported sub-timings in milliseconds, keyed by phase name, or <see langword="null"/> for none; copied.
    /// The library adds <c>queued_ms</c> when client-side rate limiting delayed a generation call.
    /// </param>
    /// <exception cref="ArgumentException"><paramref name="phases"/> contains a duplicate key.</exception>
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

    /// <summary>Gets the monotonic clock reading, in seconds, taken when the call began.</summary>
    public double StartedAt { get; }
    /// <summary>Gets the milliseconds to the first content fragment, or <see langword="null"/>.</summary>
    public double? FirstTokenMs { get; }
    /// <summary>Gets the milliseconds from the start of the call to its completion.</summary>
    public double TotalMs { get; }
    /// <summary>Gets the output tokens per second from the first fragment to completion, or <see langword="null"/>.</summary>
    public double? OutputTokensPerS { get; }
    /// <summary>Gets the copied sub-timings in milliseconds, keyed by phase name.</summary>
    public IReadOnlyDictionary<string, double> Phases { get; }
}

/// <summary>One entry in a request's routing trail.</summary>
public sealed record AttemptRecord
{
    /// <summary>Creates a routing-trail entry.</summary>
    /// <param name="target">The target attempted or skipped, or <see langword="null"/> when none was resolved.</param>
    /// <param name="outcome">
    /// What happened: <c>ok</c>, <c>retried</c>, <c>failed</c>, or <c>skipped_unhealthy</c> for a target the health
    /// gate skipped.
    /// </param>
    /// <param name="error">The failure, for a retried or failed attempt; otherwise <see langword="null"/>.</param>
    /// <param name="timing">The attempt's measured timing, or <see langword="null"/> when it was not measured.</param>
    /// <exception cref="ArgumentNullException"><paramref name="outcome"/> is <see langword="null"/>.</exception>
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

    /// <summary>Gets the target attempted or skipped, or <see langword="null"/>.</summary>
    public ResolvedTarget? Target { get; }

    /// <summary>Gets the attempt outcome, such as <c>ok</c> or <c>failed</c>.</summary>
    public string Outcome { get; }

    /// <summary>Gets the failure of a retried or failed attempt, or <see langword="null"/>.</summary>
    public AnyInferException? Error { get; }

    /// <summary>Gets attempt timing when the operation measured it.</summary>
    public Timing? Timing { get; }
}

/// <summary>An immutable generation request: messages, a route, and per-request options.</summary>
/// <remarks>
/// Construction copies every collection and checks argument shapes and inline media sizes. Roles, content part
/// types, and sampling values are checked when the request is sent.
/// </remarks>
public sealed record GenerationRequest
{
    /// <summary>Creates a generation request.</summary>
    /// <param name="messages">The conversation in order; copied.</param>
    /// <param name="route">The targets to try and the retry and health-gate settings.</param>
    /// <param name="sampling">Sampling controls, or <see langword="null"/> for provider defaults.</param>
    /// <param name="repair">
    /// The schema-repair budget, or <see langword="null"/> to use the client's default repair policy (no repairs when
    /// the client has none).
    /// </param>
    /// <param name="schema">A JSON Schema the response must satisfy, or <see langword="null"/> for unstructured text.</param>
    /// <param name="schemaMechanism">
    /// A requested structured-output mechanism, carried with the request. The library does not consult it: it selects
    /// the mechanism (<c>grammar</c>, <c>json_schema</c>, <c>json_mode</c>, or <c>prompt</c>) from the target's
    /// declared capabilities.
    /// </param>
    /// <param name="timeoutS">
    /// The timeout for each provider call, in seconds, or <see langword="null"/> to use the provider's configured timeout.
    /// </param>
    /// <param name="maxResponseBytes">
    /// The most bytes to read from a provider response, or <see langword="null"/> for 1 MiB (1,048,576 bytes).
    /// </param>
    /// <param name="stream">
    /// Whether adapters request a streamed provider response. Events are yielded either way; this selects only the
    /// provider wire mode.
    /// </param>
    /// <param name="tools">Tool declarations the model may call, or <see langword="null"/> for none; copied.</param>
    /// <param name="toolChoice">
    /// The tool-selection mode, <c>auto</c>, <c>none</c>, or <c>required</c>, or the name of one declared tool.
    /// </param>
    /// <param name="cache">A prompt-cache policy for this request, or <see langword="null"/> to use the client's policy.</param>
    /// <param name="reasoning">
    /// A normalized reasoning effort such as <c>none</c>, <c>minimal</c>, <c>low</c>, <c>medium</c>, or <c>high</c>, or
    /// <see langword="null"/> for the provider default. The value is not validated here; a target that does not support
    /// reasoning effort drops it and emits a <see cref="Events.ParameterDropped"/> event.
    /// </param>
    /// <param name="providerOptions">
    /// Provider-specific JSON options keyed by provider instance identifier, with <c>*</c> applying to every provider
    /// (a provider's own entry wins on conflicting keys), or <see langword="null"/> for none; copied.
    /// </param>
    /// <param name="metadata">
    /// Opaque labels passed to observers in <see cref="Events.RequestStarted"/> (manifests record only the keys), or
    /// <see langword="null"/> for none; copied with ordinal keys.
    /// </param>
    /// <param name="logprobs">
    /// <see langword="null"/> to request no log-probabilities, <c>0</c> to request them for generated tokens only, or
    /// 1 to 20 to also request that many alternatives per token. A target that does not report log-probabilities drops
    /// the request and emits a <see cref="Events.ParameterDropped"/> event.
    /// </param>
    /// <param name="citeDocuments">
    /// Whether to request citations that attribute the answer to supplied documents. A target that does not support
    /// them drops the request and emits a <see cref="Events.ParameterDropped"/> event.
    /// </param>
    /// <param name="serverTools">Provider-run capabilities to enable, or <see langword="null"/> for none; copied.</param>
    /// <param name="maxInputPartBytes">The most inline bytes one media part may hold; must be at least <c>1</c>.</param>
    /// <param name="maxInputBytes">
    /// The most inline media bytes across all messages; must be at least <c>1</c>. URL references do not count.
    /// </param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="messages"/>, <paramref name="route"/>, or <paramref name="toolChoice"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="ArgumentException">
    /// <paramref name="messages"/>, <paramref name="tools"/>, or <paramref name="serverTools"/> contains a
    /// <see langword="null"/> element, or <paramref name="providerOptions"/> contains a <see langword="null"/> key or
    /// value.
    /// </exception>
    /// <exception cref="ArgumentOutOfRangeException">
    /// <paramref name="logprobs"/> is outside 0 to 20, <paramref name="maxInputPartBytes"/> or
    /// <paramref name="maxInputBytes"/> is less than <c>1</c>, or the inline media exceeds either ceiling.
    /// </exception>
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

    /// <summary>Gets the copied conversation in order.</summary>
    public IReadOnlyList<Message> Messages { get; }
    /// <summary>Gets the route of targets to try.</summary>
    public Route Route { get; }
    /// <summary>Gets the sampling controls, or <see langword="null"/> for provider defaults.</summary>
    public Sampling? Sampling { get; }
    /// <summary>Gets the schema-repair budget, or <see langword="null"/> to use the client's default.</summary>
    public Repair? Repair { get; }
    /// <summary>Gets the JSON Schema the response must satisfy, or <see langword="null"/>.</summary>
    public SchemaSpec? Schema { get; }
    /// <summary>Gets the requested structured-output mechanism, which the library carries but does not consult.</summary>
    public string? SchemaMechanism { get; }
    /// <summary>Gets the per-call timeout in seconds, or <see langword="null"/> for the provider's configured timeout.</summary>
    public double? TimeoutS { get; }
    /// <summary>Gets the provider response byte ceiling, or <see langword="null"/> for 1 MiB.</summary>
    public int? MaxResponseBytes { get; }
    /// <summary>Gets whether adapters request a streamed provider response.</summary>
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
    /// <param name="messages">The replacement conversation; copied.</param>
    /// <returns>A new request with <paramref name="messages"/> and this request's other values.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="messages"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="messages"/> contains a <see langword="null"/> element.</exception>
    /// <exception cref="ArgumentOutOfRangeException">The replacement messages' inline media exceed this request's ceilings.</exception>
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

/// <summary>The terminal result of a successful generation.</summary>
/// <remarks>
/// The library builds this from the provider call that produced the accepted answer. Applications normally receive
/// it from a client or stream rather than constructing it.
/// </remarks>
public sealed record Generation
{
    /// <summary>Creates a generation result.</summary>
    /// <param name="text">The visible answer text.</param>
    /// <param name="structured">The structured value that satisfied the request schema, or <see langword="null"/>.</param>
    /// <param name="target">The target that produced the result, or <see langword="null"/>.</param>
    /// <param name="finishReason">The finish reason, such as <c>stop</c> or <c>tool_calls</c>, or <see langword="null"/>.</param>
    /// <param name="usage">The usage of the producing call, or <see langword="null"/> when unknown.</param>
    /// <param name="timing">The timing of the producing call, or <see langword="null"/> when not measured.</param>
    /// <param name="structuredMechanism">
    /// The structured-output mechanism used, such as <c>json_schema</c> or <c>prompt</c>, or <see langword="null"/>.
    /// </param>
    /// <param name="repairAttempts">The number of schema-repair round trips the result needed.</param>
    /// <param name="attempts">The routing trail in order, or <see langword="null"/> for none; copied.</param>
    /// <param name="warnings">Non-fatal warnings, or <see langword="null"/> for none; copied.</param>
    /// <param name="manifest">The terminal run manifest, or <see langword="null"/> when manifest capture was off.</param>
    /// <param name="toolCalls">Model-requested tool calls, or <see langword="null"/> for none; copied.</param>
    /// <param name="raw">The raw terminal provider payload, or <see langword="null"/> when it was not retained.</param>
    /// <param name="logprobs">Token log-probabilities in generation order, or <see langword="null"/> for none; copied.</param>
    /// <param name="citations">Citations in provider order, or <see langword="null"/> for none; copied.</param>
    /// <param name="serverToolUses">Provider-run tool invocation counts, or <see langword="null"/> for none; copied.</param>
    /// <param name="cacheMechanism">The prompt-cache mechanism used, or <see langword="null"/> when none engaged.</param>
    /// <exception cref="ArgumentNullException"><paramref name="text"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">
    /// <paramref name="attempts"/>, <paramref name="warnings"/>, <paramref name="toolCalls"/>,
    /// <paramref name="logprobs"/>, <paramref name="citations"/>, or <paramref name="serverToolUses"/> contains a
    /// <see langword="null"/> element.
    /// </exception>
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

    /// <summary>Gets the visible answer text of the producing call.</summary>
    public string Text { get; }
    /// <summary>Gets the structured value that satisfied the request schema, or <see langword="null"/> when the request had none.</summary>
    public JsonValue? Structured { get; }
    /// <summary>Gets the target that produced the result.</summary>
    public ResolvedTarget? Target { get; }
    /// <summary>
    /// Gets the finish reason, such as <c>stop</c>; the library reports <c>tool_calls</c> when the model stopped to
    /// request tools.
    /// </summary>
    public string? FinishReason { get; }
    /// <summary>
    /// Gets the usage of the producing call, with total tokens and cost filled in when they can be derived, or
    /// <see langword="null"/> when the provider reported none.
    /// </summary>
    public Usage? Usage { get; }
    /// <summary>Gets the timing of the producing call.</summary>
    public Timing? Timing { get; }
    /// <summary>Gets the structured-output mechanism used, or <see langword="null"/> when the request had no schema.</summary>
    public string? StructuredMechanism { get; }
    /// <summary>Gets the number of schema-repair round trips the result needed.</summary>
    public int RepairAttempts { get; }
    /// <summary>Gets the copied routing trail in attempt order.</summary>
    public IReadOnlyList<AttemptRecord> Attempts { get; }
    /// <summary>Gets copied non-fatal warnings, such as tool-call arguments that could not be parsed.</summary>
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
    /// <typeparam name="T">The type to deserialize the structured value into.</typeparam>
    /// <param name="options">The serializer options, or <see langword="null"/> for the serializer defaults.</param>
    /// <returns>The deserialized value; <see langword="null"/> when the structured value is JSON <c>null</c>.</returns>
    /// <exception cref="InvalidOperationException">This generation has no structured result.</exception>
    /// <exception cref="System.Text.Json.JsonException">The structured value cannot be converted to <typeparamref name="T"/>.</exception>
    public T? DeserializeStructured<T>(System.Text.Json.JsonSerializerOptions? options = null)
    {
        if (Structured is null)
        {
            throw new InvalidOperationException("This generation has no structured result to deserialize.");
        }

        return System.Text.Json.JsonSerializer.Deserialize<T>(Json.JsonWriter.WriteModern(Structured), options);
    }

    /// <summary>Deserializes the structured result with supplied type metadata.</summary>
    /// <typeparam name="T">The type to deserialize the structured value into.</typeparam>
    /// <param name="typeInfo">The serializer metadata for <typeparamref name="T"/>, for example from a source-generated context.</param>
    /// <returns>The deserialized value; <see langword="null"/> when the structured value is JSON <c>null</c>.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="typeInfo"/> is <see langword="null"/>.</exception>
    /// <exception cref="InvalidOperationException">This generation has no structured result.</exception>
    /// <exception cref="System.Text.Json.JsonException">The structured value cannot be converted to <typeparamref name="T"/>.</exception>
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
