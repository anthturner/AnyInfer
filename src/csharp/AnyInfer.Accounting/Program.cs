using System.Numerics;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using AnyInfer;
using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Routing;
using PeterO.Numbers;

if (args.Length != 2)
{
    Console.Error.WriteLine("usage: AnyInfer.Accounting INPUT OUTPUT");
    return 2;
}

var inputBytes = File.ReadAllBytes(args[0]);
var sourceRevision = SourceRevision();
var sourceDirty = SourceDirty();
var corpusSha256 = Convert.ToHexString(SHA256.HashData(inputBytes)).ToLowerInvariant();
using var input = JsonDocument.Parse(inputBytes);
if (!input.RootElement.TryGetProperty("profile", out var profile) || profile.GetString() != "accounting-v1" ||
    !input.RootElement.TryGetProperty("cases", out var cases) || cases.ValueKind != JsonValueKind.Array)
{
    throw new FormatException("Expected an accounting-v1 input envelope.");
}

var observations = new List<object?>();
foreach (var item in cases.EnumerateArray())
{
    var id = item.GetProperty("id").GetString() ?? throw new FormatException("Case id is required.");
    var kind = item.GetProperty("kind").GetString() ?? throw new FormatException("Case kind is required.");
    try
    {
        observations.Add(new Dictionary<string, object?>
        {
            ["id"] = id,
            ["kind"] = kind,
            ["status"] = "ok",
            ["value"] = await ObserveAsync(kind, item),
        });
    }
    catch (Exception exception)
    {
        var observation = new Dictionary<string, object?>
        {
            ["id"] = id,
            ["kind"] = kind,
            ["status"] = "error",
            ["error_type"] = exception.GetType().Name,
            ["structured_flags"] = Flags(exception),
        };
        if (exception is ETrapException trap && DecimalCause(trap) is { } cause)
        {
            observation.Add("decimal_cause", cause);
        }

        observations.Add(observation);
    }
}

var serializerOptions = new JsonSerializerOptions { WriteIndented = true };
serializerOptions.Converters.Add(new ObserverDoubleConverter());
File.WriteAllText(args[1], JsonSerializer.Serialize(new Dictionary<string, object?>
{
    ["profile"] = "accounting-v1",
    ["runtime"] = "csharp",
    ["source_revision"] = sourceRevision,
    ["source_dirty"] = sourceDirty,
    ["corpus_sha256"] = corpusSha256,
    ["observations"] = observations,
}, serializerOptions));
return 0;

static Task<object> ObserveAsync(string kind, JsonElement input) => kind is "limiter" or "limiter_actions"
    ? LimiterAsync(input)
    : Task.FromResult(Observe(kind, input));

static object Observe(string kind, JsonElement input) => kind switch
{
    "usage" => new Dictionary<string, object?> { ["normalized"] = UsageValue(ReadUsage(input.GetProperty("input")).Normalized()) },
    "usage_merge" => new Dictionary<string, object?> { ["merged"] = UsageValue(ReadUsage(input.GetProperty("left")).Merge(ReadUsage(input.GetProperty("right")))) },
    "usage_sum" => new Dictionary<string, object?> { ["sum"] = UsageValue(Usage.Sum(input.GetProperty("parts").EnumerateArray().Select(ReadUsage))) },
    "generation_cost" => new Dictionary<string, object?> { ["cost"] = Cost(PricingCalculator.ComputeCost(ReadUsage(input.GetProperty("usage")), Capabilities(input))) },
    "with_cost" => new Dictionary<string, object?> { ["usage"] = UsageValue(PricingCalculator.WithCost(ReadUsage(input.GetProperty("usage")), Capabilities(input))) },
    "operation_cost" => new Dictionary<string, object?> { ["cost"] = Cost(PricingCalculator.ComputeOperationCost(ReadUsage(input.GetProperty("usage")), Capabilities(input), ParseOperation(input.GetProperty("operation").GetString()))) },
    "budget" => Budget(input),
    "estimate" => EstimateRequest(input),
    "budget_gate" => BudgetGate(input),
    "policy" => Policy(input),
    "ledger" => Ledger(input),
    "store" => Store(input),
    "store_seed" => StoreSeed(input),
    "native_only_range" => NativeRange(input),
    "native_only_lexical" => EDecimal.FromString(input.GetProperty("value").GetString() ?? string.Empty).ToString(),
    _ => throw new NotSupportedException($"Unsupported accounting fixture kind '{kind}'."),
};

static object? Cost(EDecimal? value) => value?.ToString();
static object UsageValue(Usage usage) => new Dictionary<string, object?>
{
    ["input_tokens"] = usage.InputTokens, ["output_tokens"] = usage.OutputTokens,
    ["total_tokens"] = usage.TotalTokens, ["cache_read_tokens"] = usage.CacheReadTokens,
    ["cache_write_tokens"] = usage.CacheWriteTokens, ["reasoning_tokens"] = usage.ReasoningTokens,
    ["search_units"] = usage.SearchUnits, ["cost_usd"] = Cost(usage.CostUsd),
    ["server_tool_uses"] = usage.ServerToolUses,
};

static Usage ReadUsage(JsonElement item)
{
    return new Usage(
        Long(item, "input_tokens"), Long(item, "output_tokens"), Long(item, "total_tokens"),
        Long(item, "cache_read_tokens"), Long(item, "cache_write_tokens"), Long(item, "reasoning_tokens"),
        Decimal(item, "cost_usd"), Long(item, "search_units"), LongMap(item, "server_tool_uses"));
}

static ModelCapabilities? Capabilities(JsonElement item)
{
    if (!item.TryGetProperty("pricing", out var raw) || raw.ValueKind == JsonValueKind.Null)
    {
        return null;
    }

    var pricing = new Pricing(
        RequiredDecimal(raw, "input_per_1m"), RequiredDecimal(raw, "output_per_1m"),
        Decimal(raw, "cache_read_per_1m"), Decimal(raw, "cache_write_per_1m"),
        String(raw, "currency") ?? "USD", Decimal(raw, "per_search_unit"), DecimalMap(raw, "per_server_tool_use"));
    var provenance = Enum.Parse<Provenance>(String(item, "provenance") ?? String(item, "pricing_provenance") ?? "default", ignoreCase: true);
    return new ModelCapabilities(pricing: new Sourced<Pricing>(pricing, provenance));
}

static object Budget(JsonElement item)
{
    var request = Request(item);
    var window = Int(item, "context_window");
    var provenance = Enum.Parse<Provenance>(String(item, "window_provenance") ?? "default", true);
    var pricingCapabilities = Capabilities(item);
    var capabilities = new ModelCapabilities(
        contextWindow: window is null ? null : new Sourced<int>(window.Value, provenance),
        pricing: pricingCapabilities?.Pricing,
        maxOutputTokens: Int(item, "model_max_output_tokens") is { } maximum ? new Sourced<int>(maximum, provenance) : null);
    var budget = ContextBudgeting.BuildContextBudget(request, capabilities, outputReserveTokens: Long(item, "output_reserve_tokens"));
    return BudgetValue(budget);
}

static object BudgetValue(ContextBudget budget)
{
    return new Dictionary<string, object?>
    {
        ["estimate"] = new Dictionary<string, object?>
        {
            ["messages"] = Estimate(budget.Estimate.Messages), ["tools"] = Estimate(budget.Estimate.Tools),
            ["schema"] = Estimate(budget.Estimate.Schema), ["envelope"] = Estimate(budget.Estimate.Envelope),
            ["unpriced_parts"] = budget.Estimate.UnpricedParts, ["tokens"] = budget.Estimate.Tokens, ["floor"] = budget.Estimate.Floor,
        },
        ["reserve"] = budget.OutputReserveTokens, ["headroom"] = budget.HeadroomTokens,
        ["allowance"] = budget.InputAllowanceTokens, ["remaining"] = budget.RemainingTokens,
        ["fits"] = budget.Fits, ["estimated_cost"] = budget.EstimatedCost is { } cost ? new Dictionary<string, object?> { ["low"] = cost.Low.ToString(), ["high"] = cost.High.ToString(), ["currency"] = cost.Currency } : null,
    };
}

static object EstimateRequest(JsonElement item)
{
    var calls = new List<string>();
    var estimator = Estimator(item, calls);
    var calibration = Calibration(item);
    var estimate = TokenEstimation.EstimateRequest(Request(item), estimator, calibration);
    return new Dictionary<string, object?>
    {
        ["estimate"] = EstimateValue(estimate),
        ["calls"] = calls,
    };
}

static object BudgetGate(JsonElement item)
{
    var provenance = Enum.Parse<Provenance>(String(item, "window_provenance") ?? "default", true);
    var capabilities = new ModelCapabilities(
        contextWindow: Int(item, "context_window") is { } window ? new Sourced<int>(window, provenance) : null);
    try
    {
        var budget = ContextBudgeting.CheckContextFit(
            Request(item),
            capabilities,
            Estimator(item, calls: null),
            outputReserveTokens: Long(item, "output_reserve_tokens"),
            provider: String(item, "provider"),
            model: String(item, "model"));
        return new Dictionary<string, object?> { ["outcome"] = "accepted", ["budget"] = BudgetValue(budget) };
    }
    catch (ContextLengthException exception)
    {
        return new Dictionary<string, object?>
        {
            ["outcome"] = "context_length",
            ["error"] = new Dictionary<string, object?>
            {
                ["type"] = "ContextLengthError",
                ["provider"] = exception.Provider,
                ["phase"] = exception.Phase,
                ["retryable"] = exception.Retryable,
            },
        };
    }
}

static GenerationRequest Request(JsonElement item)
{
    var schema = item.TryGetProperty("schema", out var rawSchema) && rawSchema.ValueKind != JsonValueKind.Null
        ? SchemaSpec.FromJson(rawSchema.GetRawText())
        : null;
    return new GenerationRequest(
        item.GetProperty("messages").EnumerateArray().Select(value => Message.User(value.GetString() ?? string.Empty)),
        new Route(["fixture:model"]),
        sampling: new Sampling(maxOutputTokens: Int(item, "max_output_tokens")),
        schema: schema);
}

static ITokenEstimator? Estimator(JsonElement item, List<string>? calls)
{
    if (!item.TryGetProperty("literal_estimator", out var literal) || literal.ValueKind == JsonValueKind.Null)
    {
        return null;
    }

    return new LiteralEstimator(
        literal.GetProperty("tokens").GetInt64(),
        literal.GetProperty("floor").GetInt64(),
        calls);
}

static TokenCalibration? Calibration(JsonElement item)
{
    if (!item.TryGetProperty("calibration", out var calibration) || calibration.ValueKind == JsonValueKind.Null)
    {
        return null;
    }

    return new TokenCalibration(
        calibration.GetProperty("multiplier").GetDouble(),
        calibration.GetProperty("overhead_tokens").GetInt32());
}

static object EstimateValue(RequestEstimate estimate) => new Dictionary<string, object?>
{
    ["messages"] = Estimate(estimate.Messages), ["tools"] = Estimate(estimate.Tools),
    ["schema"] = Estimate(estimate.Schema), ["envelope"] = Estimate(estimate.Envelope),
    ["unpriced_parts"] = estimate.UnpricedParts, ["tokens"] = estimate.Tokens, ["floor"] = estimate.Floor,
};

static object Estimate(TokenEstimate value) => new Dictionary<string, object?> { ["tokens"] = value.Tokens, ["floor"] = value.Floor };
static object Policy(JsonElement item) { var value = new SpendPolicy(Decimal(item, "max_total_usd"), Decimal(item, "max_request_usd"), String(item, "on_unknown") ?? "allow"); return new { max_total_usd = Cost(value.MaxTotalUsd), max_request_usd = Cost(value.MaxRequestUsd), on_unknown = value.OnUnknown, active = value.Active }; }

static object Ledger(JsonElement item)
{
    var ledger = new SpendLedger(String(item, "currency") ?? "USD");
    var steps = new List<object?>();
    foreach (var action in item.GetProperty("actions").EnumerateArray())
    {
        var op = action.GetProperty("op").GetString();
        switch (op)
        {
            case "reserve":
                var reservation = ledger.Reserve(String(action, "request_id")!, RequiredDecimal(action, "estimate"), Decimal(action, "ceiling"));
                steps.Add(new { op, accepted = reservation.Accepted, spent = reservation.Spent.ToString(), reserved = reservation.Reserved.ToString() });
                break;
            case "record":
                var requestId = String(action, "request_id");
                if (action.TryGetProperty("metadata", out var metadata)) ledger.OnEvent(new RequestStarted(requestId!, [String(action, "target")!], StringMap(metadata)));
                var target = String(action, "target")!.Split(':', 2);
                ledger.Record(new ResolvedTarget(target[0], target[1]), ReadUsage(action.GetProperty("usage")), requestId);
                steps.Add(new { op, totals = Totals(ledger.Totals()), by_target = ledger.ByTarget().ToDictionary(pair => pair.Key, pair => Totals(pair.Value)), by_label = ledger.ByLabel("tenant").ToDictionary(pair => pair.Key, pair => Totals(pair.Value)) });
                break;
            case "release": ledger.Release(String(action, "request_id")!); steps.Add(new { op, reserved = ledger.Reserved().ToString() }); break;
            case "reset": ledger.Reset(); steps.Add(new { op, totals = Totals(ledger.Totals()), reserved = ledger.Reserved().ToString() }); break;
            default: throw new FormatException($"Unknown ledger action '{op}'.");
        }
    }
    return new { actions = steps };
}

static object Totals(SpendTotals value) => new { cost = value.Cost.ToString(), currency = value.Currency, requests = value.Requests, unknown_requests = value.UnknownRequests, input_tokens = value.InputTokens, output_tokens = value.OutputTokens, cache_read_tokens = value.CacheReadTokens };

static object Store(JsonElement item)
{
    var path = Path.Combine(Path.GetTempPath(), $"anyinfer-accounting-{Guid.NewGuid():N}.json");
    try
    {
        var store = new SpendStore(path);
        var count = item.GetProperty("buckets").GetInt32();
        for (var index = 0; index < count; index++)
        {
            var ledger = new SpendLedger(String(item, "currency") ?? "USD");
            ledger.Record(new ResolvedTarget("fixture", "model"), new Usage(CostUsd: RequiredDecimal(item, "cost")));
            store.Accumulate(ledger, $"b{index}");
        }
        return new { buckets = store.Load().Keys.ToArray(), bytes = Encoding.UTF8.GetString(File.ReadAllBytes(path)) };
    }
    finally { try { File.Delete(path); } catch (IOException) { } }
}

static object StoreSeed(JsonElement item)
{
    var path = Path.Combine(Path.GetTempPath(), $"anyinfer-accounting-{Guid.NewGuid():N}.json");
    try
    {
        if (String(item, "seed_bytes_base64") is { } encoded)
        {
            File.WriteAllBytes(path, Convert.FromBase64String(encoded));
        }

        var store = new SpendStore(path);
        var before = TotalsMap(store.Load());
        var ledger = new SpendLedger(String(item, "currency") ?? "USD");
        ledger.Record(new ResolvedTarget("fixture", "model"), new Usage(CostUsd: RequiredDecimal(item, "cost")));
        store.Accumulate(ledger, String(item, "bucket") ?? "total");
        return new Dictionary<string, object?>
        {
            ["before"] = before,
            ["buckets"] = TotalsMap(store.Load()),
            ["bytes"] = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true)
                .GetString(File.ReadAllBytes(path)),
        };
    }
    finally { try { File.Delete(path); } catch (IOException) { } }
}

static Dictionary<string, object> TotalsMap(IReadOnlyDictionary<string, SpendTotals> totals)
{
    var result = new Dictionary<string, object>(StringComparer.Ordinal);
    foreach (var (bucket, value) in totals)
    {
        result.Add(bucket, Totals(value));
    }

    return result;
}

static async Task<object> LimiterAsync(JsonElement item)
{
    var limits = item.GetProperty("limits");
    var clock = new FixtureTimeProvider(item.GetProperty("clock").GetDouble());
    var limiter = new RateLimiter(ReadLimits(limits), ReadDialect(item), timeProvider: clock);
    var actions = new List<object>();
    foreach (var action in item.GetProperty("actions").EnumerateArray())
    {
        var op = action.ValueKind == JsonValueKind.String ? action.GetString() : String(action, "op");
        switch (op)
        {
            case "slot":
                var pending = limiter.AcquireAsync().AsTask();
                while (!pending.IsCompleted)
                {
                    var advanced = clock.AdvanceNextTimer();
                    await Task.Yield();
                    if (!advanced && !pending.IsCompleted)
                    {
                        throw new InvalidOperationException("Limiter pacing did not schedule a virtual timer.");
                    }
                }

                using (var lease = await pending)
                {
                }

                actions.Add(new Dictionary<string, object?> { ["op"] = "slot" });
                break;
            case "observe":
                limiter.Observe(StringMap(action.GetProperty("headers")));
                actions.Add(new Dictionary<string, object?> { ["op"] = "observe" });
                break;
            case "observed_wait":
                actions.Add(new Dictionary<string, object?> { ["op"] = "observed_wait", ["value"] = limiter.ObservedWaitS() });
                break;
            default:
                throw new FormatException("Unknown limiter action.");
        }
    }
    return new { sleeps = clock.Delays, clock = clock.Now, actions };
}

static RateLimits ReadLimits(JsonElement item) => new(
    maxConcurrent: Int(item, "max_concurrent"),
    requestsPerMinute: Double(item, "requests_per_minute"),
    minIntervalS: Double(item, "min_interval_s") ?? 0,
    respectHeaders: Bool(item, "respect_headers") ?? true,
    reserveFraction: Double(item, "reserve_fraction") ?? 0);

static RateLimitHeaders? ReadDialect(JsonElement item)
{
    if (!item.TryGetProperty("dialect", out var dialect) || dialect.ValueKind == JsonValueKind.Null)
    {
        return null;
    }

    return new RateLimitHeaders(
        String(dialect, "requests_remaining") ?? "",
        String(dialect, "requests_reset") ?? "",
        String(dialect, "tokens_remaining") ?? "",
        String(dialect, "tokens_reset") ?? "",
        String(dialect, "limit_requests") ?? "",
        String(dialect, "limit_tokens") ?? "");
}

static string SourceRevision()
{
    var revision = typeof(Usage).Assembly
        .GetCustomAttributes<AssemblyMetadataAttribute>()
        .SingleOrDefault(static attribute => attribute.Key == "AnyInferSourceRevision")
        ?.Value;
    if (revision is null || revision.Length != 40 || revision.Any(static character =>
        !(character is >= '0' and <= '9' or >= 'a' and <= 'f')))
    {
        throw new InvalidOperationException("The AnyInfer SDK must be built with lowercase 40-hex AnyInferSourceRevision metadata.");
    }

    return revision;
}

static bool SourceDirty()
{
    var dirty = Assembly.GetEntryAssembly()?
        .GetCustomAttributes<AssemblyMetadataAttribute>()
        .SingleOrDefault(static attribute => attribute.Key == "AccountingSourceDirty")
        ?.Value;
    return bool.TryParse(dirty, out var value)
        ? value
        : throw new InvalidOperationException("The accounting observer must be built with boolean AccountingSourceDirty metadata.");
}

static object NativeRange(JsonElement item) => checked(long.Parse(String(item, "value")!, System.Globalization.CultureInfo.InvariantCulture));
static IReadOnlyDictionary<string, long>? LongMap(JsonElement item, string name) => item.TryGetProperty(name, out var value) && value.ValueKind != JsonValueKind.Null ? value.EnumerateObject().ToDictionary(pair => pair.Name, pair => pair.Value.GetInt64(), StringComparer.Ordinal) : null;
static IReadOnlyDictionary<string, EDecimal>? DecimalMap(JsonElement item, string name) => item.TryGetProperty(name, out var value) && value.ValueKind != JsonValueKind.Null ? value.EnumerateObject().ToDictionary(pair => pair.Name, pair => EDecimal.FromString(pair.Value.GetString()!), StringComparer.Ordinal) : null;
static IReadOnlyDictionary<string, string> StringMap(JsonElement item) => item.EnumerateObject().ToDictionary(pair => pair.Name, pair => pair.Value.GetString()!, StringComparer.Ordinal);
static long? Long(JsonElement item, string name) => item.TryGetProperty(name, out var value) && value.ValueKind != JsonValueKind.Null ? value.GetInt64() : null;
static int? Int(JsonElement item, string name) => item.TryGetProperty(name, out var value) && value.ValueKind != JsonValueKind.Null ? value.GetInt32() : null;
static double? Double(JsonElement item, string name) => item.TryGetProperty(name, out var value) && value.ValueKind != JsonValueKind.Null ? value.GetDouble() : null;
static bool? Bool(JsonElement item, string name) => item.TryGetProperty(name, out var value) && value.ValueKind != JsonValueKind.Null ? value.GetBoolean() : null;
static string? String(JsonElement item, string name) => item.TryGetProperty(name, out var value) && value.ValueKind != JsonValueKind.Null ? value.GetString() : null;
static EDecimal? Decimal(JsonElement item, string name) => String(item, name) is { } text ? EDecimal.FromString(text) : null;
static EDecimal RequiredDecimal(JsonElement item, string name) => Decimal(item, name) ?? throw new FormatException($"'{name}' is required.");
static InferenceOperation ParseOperation(string? value) => value?.ToLowerInvariant() switch { "embedding" => InferenceOperation.Embedding, "rerank" => InferenceOperation.Rerank, _ => InferenceOperation.Generation };
static IReadOnlyDictionary<string, object?> Flags(Exception exception) => new Dictionary<string, object?> { ["native_only"] = exception is OverflowException or FormatException, ["exception"] = exception.GetType().Name };
static string? DecimalCause(ETrapException exception) => exception.Error switch
{
    EContext.FlagInvalid => "invalid_operation",
    EContext.FlagOverflow => "overflow",
    EContext.FlagDivideByZero => "division_by_zero",
    _ => null,
};

sealed class LiteralEstimator(long tokens, long floor, List<string>? calls) : ITokenEstimator
{
    public TokenEstimate Estimate(string text)
    {
        calls?.Add(text);
        return new TokenEstimate(tokens, floor);
    }
}

sealed class ObserverDoubleConverter : JsonConverter<double>
{
    public override double Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options) => reader.GetDouble();

    public override void Write(Utf8JsonWriter writer, double value, JsonSerializerOptions options)
    {
        var raw = AnyInfer.Json.JsonWriter.Write(new AnyInfer.Json.JsonNumber(value));
        writer.WriteRawValue(raw, skipInputValidation: false);
    }
}

sealed class FixtureTimeProvider(double initial) : TimeProvider
{
    private DateTimeOffset _utc = DateTimeOffset.UnixEpoch;
    private long _ticks = checked((long)(initial * TimeSpan.TicksPerSecond));
    private readonly List<FixtureTimer> _timers = [];
    public List<double> Delays { get; } = [];
    public double Now => _ticks / (double)TimeSpan.TicksPerSecond;
    public override DateTimeOffset GetUtcNow() => _utc;
    public override long GetTimestamp() => _ticks;
    public override long TimestampFrequency => TimeSpan.TicksPerSecond;
    public override ITimer CreateTimer(TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period)
    {
        var timer = new FixtureTimer(this, callback, state, dueTime, period);
        _timers.Add(timer);
        return timer;
    }

    public void Advance(TimeSpan span)
    {
        var target = _utc + span;
        while (_timers.Where(timer => timer.Active && timer.Due <= target).OrderBy(timer => timer.Due).FirstOrDefault() is { } timer)
        {
            var elapsed = timer.Due - _utc;
            _utc = timer.Due;
            _ticks += elapsed.Ticks;
            timer.Fire();
        }

        _ticks += (target - _utc).Ticks;
        _utc = target;
        Delays.Add(span.TotalSeconds);
    }

    public bool AdvanceNextTimer()
    {
        var timer = _timers.Where(timer => timer.Active).OrderBy(timer => timer.Due).FirstOrDefault();
        if (timer is null)
        {
            return false;
        }

        Advance(timer.Due - _utc);
        return true;
    }

    private sealed class FixtureTimer : ITimer
    {
        private readonly FixtureTimeProvider _owner;
        private readonly TimerCallback _callback;
        private readonly object? _state;
        private TimeSpan _period;
        private bool _disposed;

        internal FixtureTimer(FixtureTimeProvider owner, TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period)
        {
            _owner = owner;
            _callback = callback;
            _state = state;
            _period = period;
            Due = owner._utc + dueTime;
        }

        internal DateTimeOffset Due { get; private set; }
        internal bool Active => !_disposed;
        public bool Change(TimeSpan dueTime, TimeSpan period)
        {
            if (_disposed) return false;
            _period = period;
            Due = _owner._utc + dueTime;
            return true;
        }

        public void Dispose() => _disposed = true;
        public ValueTask DisposeAsync() { Dispose(); return ValueTask.CompletedTask; }
        internal void Fire()
        {
            if (_disposed) return;
            if (_period <= TimeSpan.Zero || _period == Timeout.InfiniteTimeSpan) _disposed = true;
            else Due = _owner._utc + _period;
            _callback(_state);
        }
    }
}
