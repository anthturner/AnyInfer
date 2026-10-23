using System.Runtime.CompilerServices;
using System.Text.Json;
using AnyInfer;
using AnyInfer.Json;
using AnyInfer.Providers;
using PeterO.Numbers;

/// <summary>Literal, in-memory provider actions with observable dispatch and barrier lifetime.</summary>
internal sealed class ScriptedGenerationAdapter : IProviderAdapter
{
    private readonly IReadOnlyList<JsonElement> _scripts;
    private readonly string _provider;
    private readonly Action<WireRequest, JsonElement> _onWire;
    private readonly Action<string, string> _onCleanup;
    private readonly TaskCompletionSource _ready = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly TaskCompletionSource _released = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private string? _releaseId;
    private int _next;
    private int _disposed;

    internal ScriptedGenerationAdapter(string provider, IReadOnlyList<JsonElement> scripts, Action<WireRequest, JsonElement> onWire, Action<string, string> onCleanup)
    {
        _provider = provider;
        _scripts = scripts;
        _onWire = onWire;
        _onCleanup = onCleanup;
    }

    internal int Consumed => Volatile.Read(ref _next);
    internal Task BarrierReady => _ready.Task;
    internal void ReleaseBarrier(string releaseId)
    {
        if (!StringComparer.Ordinal.Equals(_releaseId, releaseId)) throw new ArgumentException("Unknown barrier release ID.", nameof(releaseId));
        _released.TrySetResult();
    }

    public async IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var index = Interlocked.Increment(ref _next) - 1;
        if ((uint)index >= (uint)_scripts.Count) throw new InvalidOperationException("No scripted adapter action remains.");
        var script = _scripts[index];
        _onWire(request, script);
        foreach (var action in script.GetProperty("actions").EnumerateArray())
        {
            cancellationToken.ThrowIfCancellationRequested();
            switch (action.GetProperty("action").GetString())
            {
                case "text_delta": yield return new AdapterTextDelta(action.GetProperty("text").GetString()!); break;
                case "reasoning_delta": yield return new AdapterReasoningDelta(action.GetProperty("text").GetString()!); break;
                case "tool_call_delta":
                    yield return new AdapterToolCallDelta(action.GetProperty("index").GetInt32(), NullableString(action, "call_id"), NullableString(action, "name"), action.GetProperty("arguments_fragment").GetString()!);
                    break;
                case "citation_delta": yield return new AdapterCitationDelta(BuildCitation(action.GetProperty("citation"))); break;
                case "server_tool_delta":
                    yield return new AdapterServerToolDelta(action.GetProperty("kind").GetString()!, action.GetProperty("status").GetString()!,
                        action.GetProperty("sources").EnumerateArray().Select(static source => new ServerToolSource(source.GetProperty("url").GetString()!, source.GetProperty("title").GetString()!)),
                        action.GetProperty("output").GetString()!, action.GetProperty("detail").GetString()!);
                    break;
                case "usage_update": yield return new AdapterUsage(BuildUsage(action.GetProperty("usage"))); break;
                case "adapter_final":
                    yield return BuildFinal(action);
                    break;
                case "provider_failure":
                    var failure = action.GetProperty("failure");
                    throw new ProviderException(failure.GetProperty("detail").GetString()!, OptionalString(failure, "kind") ?? "provider_unavailable",
                        failure.GetProperty("retryable").GetBoolean(),
                        phase: OptionalString(failure, "phase") ?? "generate", retryAfterS: OptionalDouble(failure, "retry_after_s"),
                        httpStatus: OptionalInt(failure, "http_status"), provider: OptionalString(failure, "provider") ?? _provider,
                        detail: failure.GetProperty("detail").GetString(), hint: OptionalString(failure, "hint"));
                case "barrier":
                    _releaseId = action.GetProperty("release").GetString()!;
                    _ready.TrySetResult();
                    try
                    {
                        await _released.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
                        foreach (var next in action.GetProperty("next_actions").EnumerateArray())
                            yield return BuildFinal(next);
                    }
                    finally { _onCleanup("barrier_finally", action.GetProperty("finally_cleanup").GetString()!); }
                    break;
                default: throw new FormatException("Unknown scripted adapter action.");
            }
        }
    }

    public ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) == 0) _onCleanup("adapter_close", _provider);
        return ValueTask.CompletedTask;
    }

    private static Citation BuildCitation(JsonElement value) => new(
        OptionalInt(value, "start_index"), OptionalInt(value, "end_index"), OptionalString(value, "quoted_text") ?? "",
        OptionalInt(value, "document_index"), OptionalString(value, "title") ?? "", OptionalString(value, "uri") ?? "");

    private static AdapterFinal BuildFinal(JsonElement action) => new(action.GetProperty("finish_reason").GetString()!,
        Usage: action.TryGetProperty("usage", out var usage) && usage.ValueKind != JsonValueKind.Null ? BuildUsage(usage) : null,
        Raw: action.GetProperty("raw").ValueKind == JsonValueKind.Null ? null : JsonReader.Read(action.GetProperty("raw").GetRawText()),
        phases: action.TryGetProperty("phases", out var phases) && phases.ValueKind != JsonValueKind.Null
            ? phases.EnumerateObject().Select(static value => new KeyValuePair<string, double>(value.Name, value.Value.GetDouble())) : null,
        logprobs: action.GetProperty("logprobs").EnumerateArray().Select(BuildLogprob),
        serverToolUses: action.GetProperty("server_tool_uses").EnumerateArray().Select(static value => new ServerToolUse(value.GetProperty("kind").GetString()!, value.GetProperty("uses").GetInt64())));

    private static Usage BuildUsage(JsonElement value) => new(
        OptionalLong(value, "input_tokens"), OptionalLong(value, "output_tokens"), OptionalLong(value, "total_tokens"),
        OptionalLong(value, "cache_read_tokens"), OptionalLong(value, "cache_write_tokens"), OptionalLong(value, "reasoning_tokens"),
        value.TryGetProperty("cost_usd", out var cost) && cost.ValueKind != JsonValueKind.Null ? EDecimal.FromString(cost.GetRawText()) : null,
        OptionalLong(value, "search_units"),
        value.TryGetProperty("server_tool_uses", out var tools) && tools.ValueKind != JsonValueKind.Null
            ? tools.EnumerateObject().ToDictionary(static item => item.Name, static item => item.Value.GetInt64(), StringComparer.Ordinal) : null);

    private static TokenLogprob BuildLogprob(JsonElement value) => new(value.GetProperty("token").GetString()!, value.GetProperty("logprob").GetDouble(),
        value.TryGetProperty("top", out var top) ? top.EnumerateArray().Select(BuildLogprob) : [],
        value.TryGetProperty("bytes", out var bytes) && bytes.ValueKind != JsonValueKind.Null ? bytes.EnumerateArray().Select(static item => item.GetByte()) : null);

    private static string? OptionalString(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind != JsonValueKind.Null ? item.GetString() : null;
    private static int? OptionalInt(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind != JsonValueKind.Null ? item.GetInt32() : null;
    private static long? OptionalLong(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind != JsonValueKind.Null ? item.GetInt64() : null;
    private static double? OptionalDouble(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind != JsonValueKind.Null ? item.GetDouble() : null;
    private static string? NullableString(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? null : value.GetProperty(name).GetString();
}
