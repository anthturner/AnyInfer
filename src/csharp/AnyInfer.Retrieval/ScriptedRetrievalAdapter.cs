using System.Text.Json;
using AnyInfer;
using AnyInfer.Json;
using AnyInfer.Providers;

internal sealed class ScriptedRetrievalAdapter
{
    private readonly string _instance;
    private readonly string _model;
    private readonly IReadOnlyList<JsonElement> _scripts;
    private readonly CaptureOrder _captureOrder;
    private readonly BarrierCoordinator? _barriers;
    private readonly ScriptConsumption _consumption;
    private readonly Action<string> _onDispose;
    private readonly Action<string, JsonElement, JsonElement> _onResource;
    private readonly object _scriptGate = new();
    private readonly Dictionary<string, int> _nextStep = new(StringComparer.Ordinal);
    private int _disposed;

    internal ScriptedRetrievalAdapter(string instance, string model, IReadOnlyList<JsonElement> scripts, CaptureOrder captureOrder, ScriptConsumption consumption, BarrierCoordinator? barriers, Action<string> onDispose, Action<string, JsonElement, JsonElement> onResource)
    {
        _instance = instance;
        _model = model;
        _scripts = scripts;
        _captureOrder = captureOrder ?? throw new ArgumentNullException(nameof(captureOrder));
        _barriers = barriers;
        _consumption = consumption ?? throw new ArgumentNullException(nameof(consumption));
        _onDispose = onDispose ?? throw new ArgumentNullException(nameof(onDispose));
        _onResource = onResource ?? throw new ArgumentNullException(nameof(onResource));
    }

    private readonly object _wireGate = new();
    private readonly List<JsonObject> _wires = [];
    internal IReadOnlyList<JsonObject> Wires
    {
        get { lock (_wireGate) return _wires.ToArray(); }
    }

    internal ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default)
    {
        return new ValueTask<EmbeddingWireResult>(EmbeddingAsync(request, cancellationToken));
    }

    internal ValueTask<RerankWireResult> RerankAsync(RerankWireRequest request, CancellationToken cancellationToken = default)
    {
        return new ValueTask<RerankWireResult>(RerankWireAsync(request, cancellationToken));
    }

    internal ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0) return ValueTask.CompletedTask;
        _onDispose("adapter_close_started");
        _onDispose("adapter_close_completed");
        return ValueTask.CompletedTask;
    }

    private async Task<EmbeddingWireResult> EmbeddingAsync(EmbeddingWireRequest request, CancellationToken cancellationToken)
    {
        var invocation = MatchAndConsume("embedding", request.Model, request.Inputs, null);
        var script = invocation.Script;
        var step = invocation.Step;
        var entered = NextOrder();
        AddResource("call_entered", script, step);
        try
        {
            JsonElement terminal;
            try
            {
                terminal = await TerminalAsync(step, cancellationToken).ConfigureAwait(false);
            }
            finally
            {
                if (step.GetProperty("action").GetString() == "barrier")
                {
                    AddResource("provider_cleanup_entered", script, step);
                }
            }
            if (terminal.GetProperty("action").GetString() == "provider_failure")
            {
                ThrowFailure(terminal.GetProperty("failure"));
            }

            var result = EmbeddingResponse(terminal.GetProperty("response"));
            AddWire(Projection.EmbeddingWire(script, step.GetProperty("ordinal").GetInt32(), _instance, request, entered, NextOrder(), "response", Projection.EmbeddingResponse(result), JsonNull.Instance));
            return result;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            AddWire(Projection.EmbeddingWire(script, step.GetProperty("ordinal").GetInt32(), _instance, request, entered, NextOrder(), "cancelled", JsonNull.Instance, JsonNull.Instance));
            throw;
        }
        catch (AnyInferException exception)
        {
            AddWire(Projection.EmbeddingWire(script, step.GetProperty("ordinal").GetInt32(), _instance, request, entered, NextOrder(), "provider_failure", JsonNull.Instance, Projection.Error(exception)));
            throw;
        }
    }

    private async Task<RerankWireResult> RerankWireAsync(RerankWireRequest request, CancellationToken cancellationToken)
    {
        var invocation = MatchAndConsume("rerank", request.Model, null, request.Documents);
        var script = invocation.Script;
        var step = invocation.Step;
        var entered = NextOrder();
        AddResource("call_entered", script, step);
        try
        {
            JsonElement terminal;
            try
            {
                terminal = await TerminalAsync(step, cancellationToken).ConfigureAwait(false);
            }
            finally
            {
                if (step.GetProperty("action").GetString() == "barrier")
                {
                    AddResource("provider_cleanup_entered", script, step);
                }
            }
            if (terminal.GetProperty("action").GetString() == "provider_failure")
            {
                ThrowFailure(terminal.GetProperty("failure"));
            }

            var result = RerankResponse(terminal.GetProperty("response"));
            AddWire(Projection.RerankWire(script, step.GetProperty("ordinal").GetInt32(), _instance, request, entered, NextOrder(), "response", Projection.RerankResponse(result), JsonNull.Instance));
            return result;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            AddWire(Projection.RerankWire(script, step.GetProperty("ordinal").GetInt32(), _instance, request, entered, NextOrder(), "cancelled", JsonNull.Instance, JsonNull.Instance));
            throw;
        }
        catch (AnyInferException exception)
        {
            AddWire(Projection.RerankWire(script, step.GetProperty("ordinal").GetInt32(), _instance, request, entered, NextOrder(), "provider_failure", JsonNull.Instance, Projection.Error(exception)));
            throw;
        }
    }

    private Invocation MatchAndConsume(string operation, string model, IReadOnlyList<string>? inputs, IReadOnlyList<RerankWireDocument>? documents)
    {
        lock (_scriptGate)
        {
            foreach (var script in _scripts)
            {
                if (script.GetProperty("operation").GetString() != operation || model != _model)
                {
                    continue;
                }

                var slice = script.GetProperty("slice");
                if (inputs is not null && SameInputs(slice.GetProperty("inputs"), inputs)) return Consume(script);
                if (documents is not null && SameDocuments(slice.GetProperty("documents"), documents)) return Consume(script);
            }
        }

        throw new InvalidOperationException("No literal retrieval script matches the provider wire request.");
    }

    private Invocation Consume(JsonElement script)
    {
        var id = script.GetProperty("id").GetString()!;
        var step = _nextStep.GetValueOrDefault(id);
        var steps = script.GetProperty("steps");
        if (step >= steps.GetArrayLength()) throw new InvalidOperationException("A retrieval script was consumed more than once.");
        _nextStep[id] = step + 1;
        _consumption.Consumed(id);
        return new Invocation(script, steps[step]);
    }

    private static EmbeddingWireResult EmbeddingResponse(JsonElement response)
    {
        return new EmbeddingWireResult(
            response.GetProperty("vectors").EnumerateArray().Select(vector => vector.EnumerateArray().Select(value => value.GetDouble())),
            NullableString(response, "model"), NullableInt(response, "dimensions"), NullableBool(response, "normalized"),
            usage: ReadUsage(response.GetProperty("usage")),
            phases: response.GetProperty("phases").EnumerateObject().ToDictionary(pair => pair.Name, pair => pair.Value.GetDouble(), StringComparer.Ordinal),
            raw: Raw(response.GetProperty("raw")));
    }

    private static RerankWireResult RerankResponse(JsonElement response)
    {
        return new RerankWireResult(response.GetProperty("items").EnumerateArray().Select(item => new WireRankedItem(item.GetProperty("index").GetInt32(), item.GetProperty("score").GetDouble())), NullableString(response, "model"), usage: ReadUsage(response.GetProperty("usage")), raw: Raw(response.GetProperty("raw")));
    }

    private async Task<JsonElement> TerminalAsync(JsonElement step, CancellationToken cancellationToken)
    {
        if (step.GetProperty("action").GetString() != "barrier") return step;
        if (_barriers is null) throw new InvalidOperationException("A barrier step requires a case coordinator.");
        await _barriers.WaitAsync(step.GetProperty("gate"), cancellationToken).ConfigureAwait(false);
        return step.GetProperty("continuation");
    }

    private static void ThrowFailure(JsonElement failure)
    {
        var message = failure.GetProperty("detail").GetString()!;
        var provider = NullableString(failure, "provider");
        var phase = NullableString(failure, "phase");
        var retryable = failure.GetProperty("retryable").GetBoolean();
        var retryAfter = NullableDouble(failure, "retry_after_s");
        var status = NullableInt(failure, "http_status");
        var detail = message;
        var hint = NullableString(failure, "hint");
        switch (failure.GetProperty("kind").GetString())
        {
            case "provider_unavailable": throw new ProviderUnavailableException(message, provider, phase, retryable, retryAfter, status, detail, hint);
            case "context_length": throw new ContextLengthException(message, provider, phase, retryable, retryAfter, status, detail, hint);
            default: throw new ProviderException(message, "provider", retryable, phase, retryAfter, status, provider, detail, hint);
        }
    }

    private static bool SameInputs(JsonElement expected, IReadOnlyList<string> actual) => expected.GetArrayLength() == actual.Count && expected.EnumerateArray().Select(static value => value.GetString()).SequenceEqual(actual);
    private static bool SameDocuments(JsonElement expected, IReadOnlyList<RerankWireDocument> actual) => expected.GetArrayLength() == actual.Count && expected.EnumerateArray().Select((value, index) => value.GetProperty("index").GetInt32() == actual[index].Index && value.GetProperty("text").GetString() == actual[index].Text).All(static match => match);
    private static string? NullableString(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? null : value.GetProperty(name).GetString();
    private static int? NullableInt(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? null : value.GetProperty(name).GetInt32();
    private static bool? NullableBool(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? null : value.GetProperty(name).GetBoolean();
    private static double? NullableDouble(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? null : value.GetProperty(name).GetDouble();
    private static JsonValue? Raw(JsonElement value) => value.ValueKind == JsonValueKind.Null ? null : FixtureJson.Read(value);
    private static Usage? ReadUsage(JsonElement value) => value.ValueKind == JsonValueKind.Null ? null : new Usage(
        value.GetProperty("input_tokens").ValueKind == JsonValueKind.Null ? null : value.GetProperty("input_tokens").GetInt64(),
        value.GetProperty("output_tokens").ValueKind == JsonValueKind.Null ? null : value.GetProperty("output_tokens").GetInt64(),
        value.GetProperty("total_tokens").ValueKind == JsonValueKind.Null ? null : value.GetProperty("total_tokens").GetInt64(),
        value.GetProperty("cache_read_tokens").ValueKind == JsonValueKind.Null ? null : value.GetProperty("cache_read_tokens").GetInt64(),
        value.GetProperty("cache_write_tokens").ValueKind == JsonValueKind.Null ? null : value.GetProperty("cache_write_tokens").GetInt64(),
        value.GetProperty("reasoning_tokens").ValueKind == JsonValueKind.Null ? null : value.GetProperty("reasoning_tokens").GetInt64(),
        CostUsd: value.GetProperty("cost_usd").ValueKind == JsonValueKind.Null ? null : PeterO.Numbers.EDecimal.FromString(value.GetProperty("cost_usd").GetString()!),
        SearchUnits: value.GetProperty("search_units").ValueKind == JsonValueKind.Null ? null : value.GetProperty("search_units").GetInt64(),
        ServerToolUses: value.GetProperty("server_tool_uses").EnumerateObject().ToDictionary(pair => pair.Name, pair => pair.Value.GetInt64(), StringComparer.Ordinal));
    private void AddWire(JsonObject wire)
    {
        lock (_wireGate) _wires.Add(wire);
    }

    private long NextOrder() => _captureOrder.Next();

    private void AddResource(string type, JsonElement script, JsonElement step)
    {
        _onResource(type, script, step);
    }

    private sealed record Invocation(JsonElement Script, JsonElement Step);
}

internal sealed class CaptureOrder
{
    private long _value;
    internal long Next() => Interlocked.Increment(ref _value);
}

internal sealed class EmbeddingScriptedAdapter : IAsyncDisposable, IEmbedsText
{
    private readonly ScriptedRetrievalAdapter _inner;
    internal EmbeddingScriptedAdapter(ScriptedRetrievalAdapter inner) => _inner = inner;
    public ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default) => _inner.EmbedAsync(request, cancellationToken);
    public ValueTask DisposeAsync() => _inner.DisposeAsync();
}

internal sealed class RerankScriptedAdapter : IAsyncDisposable, IReranksText
{
    private readonly ScriptedRetrievalAdapter _inner;
    internal RerankScriptedAdapter(ScriptedRetrievalAdapter inner) => _inner = inner;
    public ValueTask<RerankWireResult> RerankAsync(RerankWireRequest request, CancellationToken cancellationToken = default) => _inner.RerankAsync(request, cancellationToken);
    public ValueTask DisposeAsync() => _inner.DisposeAsync();
}

internal sealed class DualScriptedAdapter : IAsyncDisposable, IEmbedsText, IReranksText
{
    private readonly ScriptedRetrievalAdapter _inner;
    internal DualScriptedAdapter(ScriptedRetrievalAdapter inner) => _inner = inner;
    public ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default) => _inner.EmbedAsync(request, cancellationToken);
    public ValueTask<RerankWireResult> RerankAsync(RerankWireRequest request, CancellationToken cancellationToken = default) => _inner.RerankAsync(request, cancellationToken);
    public ValueTask DisposeAsync() => _inner.DisposeAsync();
}
