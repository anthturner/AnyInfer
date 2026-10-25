using AnyInfer.Internal;
using AnyInfer.Json;
using PeterO.Numbers;

namespace AnyInfer.Capabilities;

/// <summary>Represents completed spend and the requests whose cost remains unknown.</summary>
public sealed record SpendTotals
{
    /// <summary>Creates an immutable completed-spend snapshot.</summary>
    /// <param name="cost">Sum of known completed costs; <see langword="null"/> means zero known cost.</param>
    /// <param name="currency">Currency code of <paramref name="cost"/>.</param>
    /// <param name="requests">Completed request count, including unknown-cost requests.</param>
    /// <param name="unknownRequests">Completed requests whose cost could not be determined and is excluded from <paramref name="cost"/>.</param>
    /// <param name="inputTokens">Reported input tokens.</param>
    /// <param name="outputTokens">Reported output tokens.</param>
    /// <param name="cacheReadTokens">Reported cache-read tokens.</param>
    /// <exception cref="ArgumentNullException"><paramref name="currency"/> is <see langword="null"/>.</exception>
    public SpendTotals(
        EDecimal? cost = null,
        string currency = "USD",
        long requests = 0,
        long unknownRequests = 0,
        long inputTokens = 0,
        long outputTokens = 0,
        long cacheReadTokens = 0)
    {
        Cost = cost ?? EDecimal.Zero;
        Currency = currency ?? throw new ArgumentNullException(nameof(currency));
        Requests = requests;
        UnknownRequests = unknownRequests;
        InputTokens = inputTokens;
        OutputTokens = outputTokens;
        CacheReadTokens = cacheReadTokens;
    }

    /// <summary>Gets the sum of known completed costs.</summary>
    /// <remarks>
    /// Requests with unknown cost add nothing here; read this together with <see cref="UnknownRequests"/>, because
    /// a total that omits unpriced requests understates spend.
    /// </remarks>
    public EDecimal Cost { get; }
    /// <summary>Gets the currency associated with <see cref="Cost"/>.</summary>
    public string Currency { get; }
    /// <summary>Gets the completed request count.</summary>
    public long Requests { get; }
    /// <summary>Gets completed requests whose cost could not be determined.</summary>
    public long UnknownRequests { get; }
    /// <summary>Gets reported input tokens, with missing values counted as zero.</summary>
    public long InputTokens { get; }
    /// <summary>Gets reported output tokens, with missing values counted as zero.</summary>
    public long OutputTokens { get; }
    /// <summary>Gets reported cache-read tokens, with missing values counted as zero.</summary>
    public long CacheReadTokens { get; }
    /// <summary>Gets whether every completed request had a known cost.</summary>
    public bool Complete => UnknownRequests == 0;

    /// <summary>Returns a snapshot after folding one completed usage report into this total.</summary>
    /// <param name="usage">Reported usage of one completed request; a <see langword="null"/> cost counts as unknown, not zero.</param>
    /// <returns>A new snapshot with one more request; this instance is unchanged.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="usage"/> is <see langword="null"/>.</exception>
    /// <exception cref="OverflowException">A count or token total exceeds the range of <see cref="long"/>.</exception>
    public SpendTotals Plus(Usage usage)
    {
        ArgumentNullException.ThrowIfNull(usage);
        return new SpendTotals(
            AccountingDecimal.Add(Cost, usage.CostUsd ?? EDecimal.Zero),
            Currency,
            checked(Requests + 1),
            checked(UnknownRequests + (usage.CostUsd is null ? 1 : 0)),
            checked(InputTokens + (usage.InputTokens ?? 0)),
            checked(OutputTokens + (usage.OutputTokens ?? 0)),
            checked(CacheReadTokens + (usage.CacheReadTokens ?? 0)));
    }

    /// <summary>Returns this snapshot in the persisted accounting-format object shape.</summary>
    /// <returns>
    /// A JSON object with <c>cost</c> as a decimal string, <c>currency</c>, and integer <c>requests</c>,
    /// <c>unknown_requests</c>, <c>input_tokens</c>, <c>output_tokens</c>, and <c>cache_read_tokens</c>.
    /// </returns>
    public JsonObject ToDictionary() => new([
        new JsonProperty("cost", new JsonString(AccountingDecimal.Format(Cost))),
        new JsonProperty("currency", new JsonString(Currency)),
        new JsonProperty("requests", new JsonInteger(Requests)),
        new JsonProperty("unknown_requests", new JsonInteger(UnknownRequests)),
        new JsonProperty("input_tokens", new JsonInteger(InputTokens)),
        new JsonProperty("output_tokens", new JsonInteger(OutputTokens)),
        new JsonProperty("cache_read_tokens", new JsonInteger(CacheReadTokens)),
    ]);

    /// <summary>Parses one strict persisted accounting bucket, returning <see langword="null"/> when unreadable.</summary>
    /// <param name="value">Bucket object in the <see cref="ToDictionary"/> shape; missing counts read as zero and a missing currency as <c>USD</c>.</param>
    /// <returns>The parsed snapshot, or <see langword="null"/> when <c>cost</c> is missing or any field has the wrong type or format.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="value"/> is <see langword="null"/>.</exception>
    public static SpendTotals? FromDictionary(JsonObject value)
    {
        ArgumentNullException.ThrowIfNull(value);
        if (!value.TryGetValue("cost", out var rawCost) || rawCost is not JsonString costText)
        {
            return null;
        }

        try
        {
            return new SpendTotals(
                EDecimal.FromString(costText.Value),
                OptionalString(value, "currency") ?? "USD",
                OptionalLong(value, "requests"),
                OptionalLong(value, "unknown_requests"),
                OptionalLong(value, "input_tokens"),
                OptionalLong(value, "output_tokens"),
                OptionalLong(value, "cache_read_tokens"));
        }
        catch (FormatException)
        {
            return null;
        }
        catch (InvalidOperationException)
        {
            return null;
        }
    }

    /// <summary>Compares monetary values numerically while preserving normal value equality for other fields.</summary>
    /// <param name="other">Snapshot to compare with this instance.</param>
    /// <returns><see langword="true"/> when the costs are numerically equal and every other field is equal.</returns>
    public bool Equals(SpendTotals? other) =>
        ReferenceEquals(this, other) || other is not null &&
        AccountingDecimal.NumericEquals(Cost, other.Cost) &&
        Currency == other.Currency &&
        Requests == other.Requests &&
        UnknownRequests == other.UnknownRequests &&
        InputTokens == other.InputTokens &&
        OutputTokens == other.OutputTokens &&
        CacheReadTokens == other.CacheReadTokens;

    /// <summary>Returns a hash code consistent with numeric monetary equality.</summary>
    /// <returns>A hash code that is equal for snapshots that compare equal.</returns>
    public override int GetHashCode() => HashCode.Combine(
        AccountingDecimal.NumericHashCode(Cost), Currency, Requests, UnknownRequests,
        InputTokens, OutputTokens, CacheReadTokens);

    private static string? OptionalString(JsonObject value, string name)
    {
        if (!value.TryGetValue(name, out var raw))
        {
            return null;
        }

        return raw is JsonString text ? text.Value : throw new InvalidOperationException();
    }

    private static long OptionalLong(JsonObject value, string name)
    {
        if (!value.TryGetValue(name, out var raw))
        {
            return 0;
        }

        return raw is JsonInteger integer && integer.Value >= long.MinValue && integer.Value <= long.MaxValue
            ? (long)integer.Value
            : throw new InvalidOperationException();
    }
}
