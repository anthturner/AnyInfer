using System.Text.Json;
using System.Runtime.ExceptionServices;
using AnyInfer;
using AnyInfer.Capabilities;
using AnyInfer.Config;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Routing;
using PeterO.Numbers;

internal static class RetrievalCase
{
    internal static async Task<JsonObject> ObserveAsync(JsonElement item)
    {
        var id = item.GetProperty("id").GetString() ?? throw new FormatException("Case id is required.");
        var kind = item.GetProperty("kind").GetString() ?? throw new FormatException("Case kind is required.");
        var recorder = new CaseRecorder(item);
        Exception? primary = null;
        try
        {
            var value = await recorder.ExecuteAsync().ConfigureAwait(false);
            return FixtureJson.Object(
                ("id", FixtureJson.String(id)),
                ("kind", FixtureJson.String(kind)),
                ("status", FixtureJson.String("ok")),
                ("value", value));
        }
        catch (Exception exception)
        {
            primary = exception;
            throw;
        }
        finally
        {
            try
            {
                await recorder.DisposeAsync().ConfigureAwait(false);
            }
            catch when (primary is not null)
            {
            }
        }
    }
}

internal sealed class CaseRecorder : IAsyncDisposable
{
    private readonly JsonElement _case;
    private readonly List<ScriptedRetrievalAdapter> _adapters = [];
    private readonly List<JsonObject> _factories = [];
    private readonly List<JsonObject> _resources = [];
    private readonly object _resourceGate = new();
    private readonly List<JsonObject> _ledgerSnapshots = [];
    private readonly CaptureOrder _captureOrder = new();
    private readonly RecordingObserver _observer;
    private readonly BarrierCoordinator _barriers;
    private readonly ScriptConsumption _consumption;
    private SpendLedger? _ledger;
    private AsyncClient? _client;
    private bool _callerCancellationObserved;

    internal CaseRecorder(JsonElement item)
    {
        _case = item;
        _observer = new RecordingObserver(_captureOrder);
        _barriers = new BarrierCoordinator(_captureOrder);
        _consumption = new ScriptConsumption(item.GetProperty("scripts").EnumerateArray());
        foreach (var script in item.GetProperty("scripts").EnumerateArray())
        {
            foreach (var step in script.GetProperty("steps").EnumerateArray())
            {
                if (step.GetProperty("action").GetString() == "barrier") _barriers.Register(script, step);
            }
        }
    }

    internal async Task<JsonObject> ExecuteAsync()
    {
        var registry = new ProviderRegistry(_case.GetProperty("descriptors").EnumerateArray().Select(CreateDescriptor));
        var settings = _case.GetProperty("descriptors").EnumerateArray().Select(descriptor =>
            ProviderSettings.Of(
                descriptor.GetProperty("id").GetString()!,
                alias: descriptor.GetProperty("instance").GetString()!)).ToArray();
        var clientInput = _case.GetProperty("client");
        var operationRoutes = new Dictionary<InferenceOperation, Route>();
        if (ReadRoute(clientInput.GetProperty("operation_route")) is { } operationRoute)
        {
            operationRoutes[_case.GetProperty("kind").GetString() == "embedding"
                ? InferenceOperation.Embedding : InferenceOperation.Rerank] = operationRoute;
        }
        _ledger = _case.GetProperty("ledger").GetBoolean() ? new SpendLedger() : null;
        var spendPolicy = ReadSpendPolicy(_case.GetProperty("spend_policy"));
        var estimator = ReadEstimator(clientInput.GetProperty("estimator"));
        var observers = new IObserver[] { _observer };
        foreach (var secret in clientInput.GetProperty("registered_secrets").EnumerateArray())
        {
            Redaction.RegisterSecret(secret.GetString());
        }

        var defaultRoute = ReadRoute(clientInput.GetProperty("default_route"));
        var capabilityOverrides = ReadCapabilityOverrides();
        var client = clientInput.GetProperty("source").GetString() == "from_config"
            ? AsyncClient.FromConfig(
                new AnyInferConfig(settings, defaultRoute, operationRoutes: operationRoutes), registry,
                observers: observers, manifests: true, manifestPayloads: false, estimator: estimator,
                ledger: _ledger, spendPolicy: spendPolicy, capabilityOverrides: capabilityOverrides)
            : new AsyncClient(settings, registry, route: defaultRoute, observers: observers,
                manifests: true, manifestPayloads: false, operationRoutes: operationRoutes,
                estimator: estimator, ledger: _ledger, spendPolicy: spendPolicy, capabilityOverrides: capabilityOverrides);
        _client = client;
        CaptureLedger("before_call");
        var request = _case.GetProperty("request");
        var kind = _case.GetProperty("kind").GetString();
        var route = ReadRoute(clientInput.GetProperty("per_call_route"));
        var target = NullableString(clientInput, "per_call_target");
        Exception? terminal = null;
        EmbeddingResult? embedding = null;
        RerankResult? rerankResult = null;
        try
        {
            if (kind == "embedding")
            {
                embedding = await EmbedAsync(client, request, target, route).ConfigureAwait(false);
            }
            else
            {
                rerankResult = await RerankAsync(client, request, target, route).ConfigureAwait(false);
            }
        }
        catch (Exception exception)
        {
            terminal = exception;
        }

        CaptureLedger("after_operation");
        Exception? closeFailure = null;
        try
        {
            await CloseClientAsync().ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            closeFailure = exception;
        }

        EnsureScriptsConsumed();
        if (terminal is not null)
        {
            if (terminal is OperationCanceledException && !_callerCancellationObserved)
            {
                ExceptionDispatchInfo.Capture(terminal).Throw();
            }
            if (terminal is OperationCanceledException or AnyInferException)
            {
                _observer.ValidateCorrelation(null);
                return Projection.Failure(terminal, _adapters, _factories, _observer, LedgerSnapshots(), kind!, Resources(), _callerCancellationObserved);
            }
            ExceptionDispatchInfo.Capture(terminal).Throw();
        }
        if (closeFailure is not null)
        {
            ExceptionDispatchInfo.Capture(closeFailure).Throw();
        }

        _observer.ValidateCorrelation(embedding?.Manifest ?? rerankResult?.Manifest);
        return embedding is not null
            ? Projection.Embedding(embedding, _adapters, _factories, _observer, LedgerSnapshots(), Resources())
            : Projection.Rerank(rerankResult!, _adapters, _factories, _observer, LedgerSnapshots(), Resources());
    }

    private async Task<EmbeddingResult> EmbedAsync(AsyncClient client, JsonElement rawRequest, string? target, Route? route)
    {
        if (!HasBarrier()) return await StartEmbeddingAsync(client, rawRequest, target, route, CancellationToken.None).ConfigureAwait(false);
        using var cancellation = new CancellationTokenSource();
        var pending = StartEmbeddingAsync(client, rawRequest, target, route, cancellation.Token);
        try
        {
            var ready = _barriers.WaitReadyAsync();
            if (await Task.WhenAny(ready, pending).ConfigureAwait(false) == pending)
            {
                return await pending.ConfigureAwait(false);
            }
            await ready.ConfigureAwait(false);
            CaptureLedger("while_provider_held");
            _barriers.MarkCallerCancellation();
            cancellation.Cancel();
            return await pending.ConfigureAwait(false);
        }
        catch (OperationCanceledException exception) when (
            cancellation.IsCancellationRequested && exception.CancellationToken == cancellation.Token)
        {
            _callerCancellationObserved = true;
            throw;
        }
        finally
        {
            _barriers.ReleaseAll();
            await ObserveAsync(pending).ConfigureAwait(false);
            _barriers.MarkOperationFinally();
        }
    }

    private async Task<RerankResult> RerankAsync(AsyncClient client, JsonElement request, string? target, Route? route)
    {
        if (!HasBarrier()) return await StartRerankAsync(client, request, target, route, CancellationToken.None).ConfigureAwait(false);
        using var cancellation = new CancellationTokenSource();
        var pending = StartRerankAsync(client, request, target, route, cancellation.Token);
        try
        {
            var ready = _barriers.WaitReadyAsync();
            if (await Task.WhenAny(ready, pending).ConfigureAwait(false) == pending)
            {
                return await pending.ConfigureAwait(false);
            }
            await ready.ConfigureAwait(false);
            CaptureLedger("while_provider_held");
            _barriers.MarkCallerCancellation();
            cancellation.Cancel();
            return await pending.ConfigureAwait(false);
        }
        catch (OperationCanceledException exception) when (
            cancellation.IsCancellationRequested && exception.CancellationToken == cancellation.Token)
        {
            _callerCancellationObserved = true;
            throw;
        }
        finally
        {
            _barriers.ReleaseAll();
            await ObserveAsync(pending).ConfigureAwait(false);
            _barriers.MarkOperationFinally();
        }
    }

    private bool HasBarrier() => _case.GetProperty("scripts").EnumerateArray()
        .SelectMany(static script => script.GetProperty("steps").EnumerateArray())
        .Any(static step => step.GetProperty("action").GetString() == "barrier");

    private static async Task ObserveAsync(Task task)
    {
        try { await task.ConfigureAwait(false); }
        catch { }
    }

    private static Task<EmbeddingResult> StartEmbeddingAsync(AsyncClient client, JsonElement request, string? target, Route? route, CancellationToken cancellationToken)
    {
        if (request.GetProperty("entry_point").GetString() == "embed_scalar")
        {
            return client.EmbedAsync(
                request.GetProperty("input").GetString()!, target, route,
                inputType: ReadIntent(request.GetProperty("input_type")),
                dimensions: NullableInt(request, "dimensions"), expectedSpace: ReadExpectedSpace(request.GetProperty("expected_space")),
                allowIncompatibleFallback: request.GetProperty("allow_incompatible_fallback").GetBoolean(), batch: ReadBatch(request.GetProperty("batch")),
                timeoutS: NullableDouble(request, "timeout_s"), providerOptions: Options(request.GetProperty("provider_options")),
                metadata: Strings(request.GetProperty("metadata")), maxResponseBytes: ResponseCap(request),
                retainRaw: request.GetProperty("retain_raw").GetBoolean(), cancellationToken: cancellationToken);
        }

        return client.EmbedAsync(
            request.GetProperty("inputs").EnumerateArray().Select(static value => value.GetString()!), target, route,
            inputType: ReadIntent(request.GetProperty("input_type")),
            dimensions: NullableInt(request, "dimensions"), expectedSpace: ReadExpectedSpace(request.GetProperty("expected_space")),
            allowIncompatibleFallback: request.GetProperty("allow_incompatible_fallback").GetBoolean(), batch: ReadBatch(request.GetProperty("batch")),
            timeoutS: NullableDouble(request, "timeout_s"), providerOptions: Options(request.GetProperty("provider_options")),
            metadata: Strings(request.GetProperty("metadata")), maxResponseBytes: ResponseCap(request),
            retainRaw: request.GetProperty("retain_raw").GetBoolean(), cancellationToken: cancellationToken);
    }

    private static Task<RerankResult> StartRerankAsync(AsyncClient client, JsonElement request, string? target, Route? route, CancellationToken cancellationToken) =>
        client.RerankAsync(
            request.GetProperty("query").GetString()!,
            request.GetProperty("documents").EnumerateArray().Select(document => new RerankDocument(
                document.GetProperty("id").GetString()!, document.GetProperty("text").GetString()!, Strings(document.GetProperty("metadata")))),
            target, route, topN: NullableInt(request, "top_n"), batch: ReadBatch(request.GetProperty("batch")),
            timeoutS: NullableDouble(request, "timeout_s"), providerOptions: Options(request.GetProperty("provider_options")),
            metadata: Strings(request.GetProperty("metadata")), maxResponseBytes: ResponseCap(request),
            returnDocuments: request.GetProperty("return_documents").GetBoolean(), retainRaw: request.GetProperty("retain_raw").GetBoolean(),
            cancellationToken: cancellationToken);

    private void EnsureScriptsConsumed()
    {
        _consumption.RequireComplete();
    }

    private IEnumerable<JsonObject> Resources()
    {
        lock (_resourceGate)
        {
            return _resources.Concat(_barriers.Resources).ToArray();
        }
    }
    private IEnumerable<JsonObject>? LedgerSnapshots() => _ledger is null ? null : _ledgerSnapshots;
    private void CaptureLedger(string label)
    {
        if (_ledger is not null) _ledgerSnapshots.Add(Projection.LedgerSnapshot(_ledger, label));
    }

    private async Task CloseClientAsync()
    {
        if (_client is null) return;
        var client = _client;
        AddResource(Resource("normal_client_close_started"));
        try
        {
            await client.DisposeAsync().ConfigureAwait(false);
            AddResource(Resource("normal_client_close_completed"));
            CaptureLedger("after_client_close");
        }
        finally
        {
            _client = null;
        }
    }

    private JsonObject Resource(string type) => FixtureJson.Object(
        ("type", FixtureJson.String(type)), ("order", FixtureJson.Integer(_captureOrder.Next())),
        ("selector_id", FixtureJson.Null()), ("step_ordinal", FixtureJson.Null()), ("instance", FixtureJson.Null()));

    private JsonObject AdapterResource(string type, string instance) => FixtureJson.Object(
        ("type", FixtureJson.String(type)), ("order", FixtureJson.Integer(_captureOrder.Next())),
        ("selector_id", FixtureJson.Null()), ("step_ordinal", FixtureJson.Null()), ("instance", FixtureJson.String(instance)));

    private void AddResource(JsonObject resource)
    {
        lock (_resourceGate) _resources.Add(resource);
    }

    private void AddInvocationResource(string type, string instance, JsonElement script, JsonElement step)
    {
        lock (_resourceGate)
        {
            _resources.Add(FixtureJson.Object(
                ("type", FixtureJson.String(type)), ("order", FixtureJson.Integer(_captureOrder.Next())),
                ("selector_id", FixtureJson.String(script.GetProperty("id").GetString()!)),
                ("step_ordinal", FixtureJson.Integer(step.GetProperty("ordinal").GetInt32())),
                ("instance", FixtureJson.String(instance))));
        }
    }

    private ProviderDescriptor CreateDescriptor(JsonElement descriptor)
    {
        var id = descriptor.GetProperty("id").GetString()!;
        var instance = descriptor.GetProperty("instance").GetString()!;
        var model = descriptor.GetProperty("model").GetString()!;
        var scripts = _case.GetProperty("scripts").EnumerateArray()
            .Where(script => script.GetProperty("instance").GetString() == instance && script.GetProperty("model").GetString() == model)
            .ToArray();
        var capabilities = descriptor.GetProperty("capabilities");
        var staticEmbedding = capabilities.GetProperty("embedding").ValueKind == JsonValueKind.Null ? null :
            new Dictionary<string, EmbeddingCapabilities>(StringComparer.Ordinal) { [model] = ReadEmbeddingCapabilities(capabilities.GetProperty("embedding")) };
        var staticRerank = capabilities.GetProperty("rerank").ValueKind == JsonValueKind.Null ? null :
            new Dictionary<string, RerankCapabilities>(StringComparer.Ordinal) { [model] = ReadRerankCapabilities(capabilities.GetProperty("rerank")) };
        var staticCapabilities = new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal)
        {
            [model] = new ModelCapabilities(
                pricing: ReadPricing(capabilities.GetProperty("pricing"), includeOverride: false),
                embedding: staticEmbedding?.GetValueOrDefault(model)),
        };
        return new ProviderDescriptor(
            id,
            id,
            (config, _) =>
            {
                var declared = descriptor.GetProperty("operations").EnumerateArray().Select(static value => value.GetString()!).ToArray();
                _factories.Add(FixtureJson.Object(
                    ("type", FixtureJson.String("factory_entered")), ("order", FixtureJson.Integer(_captureOrder.Next())),
                    ("instance", FixtureJson.String(instance)), ("model", FixtureJson.String(model)),
                    ("declared_operations", FixtureJson.Array(declared.Select(FixtureJson.String)))));
                var adapter = new ScriptedRetrievalAdapter(instance, model, scripts, _captureOrder, _consumption, _barriers,
                    type => AddResource(AdapterResource(type, instance)),
                    (type, script, step) => AddInvocationResource(type, instance, script, step));
                _adapters.Add(adapter);
                var runtimeProtocolList = descriptor.GetProperty("runtime_protocols").EnumerateArray().Select(static value => value.GetString()!).ToArray();
                var protocols = runtimeProtocolList.ToHashSet(StringComparer.Ordinal);
                IAsyncDisposable publicAdapter = protocols.SetEquals(["embedding"])
                    ? new EmbeddingScriptedAdapter(adapter)
                    : protocols.SetEquals(["rerank"])
                        ? new RerankScriptedAdapter(adapter)
                        : protocols.SetEquals(["embedding", "rerank"])
                            ? new DualScriptedAdapter(adapter)
                            : throw new InvalidOperationException("The fixture runtime protocols have no public retrieval adapter composition.");
                _factories.Add(FixtureJson.Object(
                    ("type", FixtureJson.String("factory_returned")), ("order", FixtureJson.Integer(_captureOrder.Next())),
                    ("instance", FixtureJson.String(instance)), ("model", FixtureJson.String(model)),
                    ("declared_operations", FixtureJson.Array(declared.Select(FixtureJson.String))),
                    ("runtime_protocols", FixtureJson.Array(runtimeProtocolList.Select(FixtureJson.String)))));
                return new ValueTask<IAsyncDisposable>(publicAdapter);
            },
            operations: descriptor.GetProperty("operations").EnumerateArray()
                .Select(operation => operation.GetString() == "embedding" ? InferenceOperation.Embedding : InferenceOperation.Rerank),
            staticCapabilities: staticCapabilities,
            staticEmbeddingCapabilities: staticEmbedding,
            staticRerankCapabilities: staticRerank);
    }

    private static EmbeddingSpace? ReadExpectedSpace(JsonElement value) => value.ValueKind == JsonValueKind.Null ? null : new EmbeddingSpace(
        value.GetProperty("provider_id").GetString()!, value.GetProperty("model").GetString()!,
        NullableString(value, "model_revision"), NullableInt(value, "dimensions"),
        value.GetProperty("input_intent_aware").GetBoolean(),
        value.GetProperty("normalized").ValueKind == JsonValueKind.Null ? null : value.GetProperty("normalized").GetBoolean(),
        NullableString(value, "compatibility_id"));

    private static Route? ReadRoute(JsonElement value) => value.ValueKind == JsonValueKind.Null ? null : new Route(
        value.GetProperty("targets").EnumerateArray().Select(static target => target.GetString()!),
        new Retry(value.GetProperty("retry").GetProperty("max_attempts").GetInt32(), value.GetProperty("retry").GetProperty("backoff_base_s").GetDouble(), value.GetProperty("retry").GetProperty("backoff_max_s").GetDouble()),
        value.GetProperty("health_gate").GetBoolean());
    private static BatchPolicy ReadBatch(JsonElement value) => new(value.GetProperty("max_concurrency").GetInt32(), NullableInt(value, "max_items_override"), value.GetProperty("allow_split").GetBoolean(), value.GetProperty("rerank_cross_batch").GetBoolean());
    private static EmbeddingInputIntent? ReadIntent(JsonElement value) => value.ValueKind == JsonValueKind.Null ? null : Enum.Parse<EmbeddingInputIntent>(value.GetString()!, true);
    private static string? NullableString(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? null : value.GetProperty(name).GetString();
    private static int? NullableInt(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? null : value.GetProperty(name).GetInt32();
    private static int? ResponseCap(JsonElement request) =>
        request.TryGetProperty("max_response_bytes", out var cap) && cap.ValueKind != JsonValueKind.Null
            ? cap.GetInt32() : null;
    private static double? NullableDouble(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? null : value.GetProperty(name).GetDouble();
    private static IReadOnlyDictionary<string, string> Strings(JsonElement value) => value.EnumerateObject().ToDictionary(pair => pair.Name, pair => pair.Value.GetString()!, StringComparer.Ordinal);
    private static IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>> Options(JsonElement value) => value.EnumerateObject().ToDictionary(
        pair => pair.Name,
        pair => (IReadOnlyDictionary<string, JsonValue>)pair.Value.EnumerateObject().ToDictionary(option => option.Name, option => FixtureJson.Read(option.Value), StringComparer.Ordinal),
        StringComparer.Ordinal);

    private static EmbeddingCapabilities ReadEmbeddingCapabilities(JsonElement value) => new(
        NullableInt(value, "dimensions"), value.GetProperty("dimension_choices").EnumerateArray().Select(static choice => choice.GetInt32()),
        NullableInt(value, "max_batch_inputs"), NullableInt(value, "max_input_tokens"), NullableInt(value, "max_input_bytes"),
        value.GetProperty("input_intents").EnumerateArray().Select(intent => Enum.Parse<EmbeddingInputIntent>(intent.GetString()!, true)),
        value.GetProperty("normalized").ValueKind == JsonValueKind.Null ? null : value.GetProperty("normalized").GetBoolean());
    private static RerankCapabilities ReadRerankCapabilities(JsonElement value) => new(NullableInt(value, "max_documents"), NullableInt(value, "max_tokens_per_document"), NullableInt(value, "max_bytes_per_document"), value.GetProperty("native_top_n").GetBoolean());
    private IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>? ReadCapabilityOverrides()
    {
        var outer = new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>(StringComparer.Ordinal);
        foreach (var descriptor in _case.GetProperty("descriptors").EnumerateArray())
        {
            var pricing = descriptor.GetProperty("capabilities").GetProperty("pricing");
            if (pricing.ValueKind == JsonValueKind.Null || pricing.GetProperty("source").GetString() != "override") continue;
            var instance = descriptor.GetProperty("instance").GetString()!;
            var model = descriptor.GetProperty("model").GetString()!;
            outer.Add(instance, new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal)
            {
                [model] = new ModelCapabilities(pricing: ReadPricing(pricing, includeOverride: true)),
            });
        }

        return outer.Count == 0 ? null : outer;
    }

    private static Sourced<Pricing>? ReadPricing(JsonElement value, bool includeOverride = true)
    {
        if (value.ValueKind == JsonValueKind.Null) return null;
        var isOverride = value.GetProperty("source").GetString() == "override";
        if (isOverride && !includeOverride) return null;
        var provenance = isOverride ? Provenance.Override : Provenance.Default;
        var rates = value.GetProperty("per_server_tool_use").EnumerateObject().ToDictionary(pair => pair.Name, pair => EDecimal.FromString(pair.Value.GetString()!), StringComparer.Ordinal);
        return new Sourced<Pricing>(new Pricing(
            EDecimal.FromString(value.GetProperty("input_per_1m").GetString()!),
            EDecimal.FromString(value.GetProperty("output_per_1m").GetString()!),
            value.GetProperty("cache_read_per_1m").ValueKind == JsonValueKind.Null ? null : EDecimal.FromString(value.GetProperty("cache_read_per_1m").GetString()!),
            value.GetProperty("cache_write_per_1m").ValueKind == JsonValueKind.Null ? null : EDecimal.FromString(value.GetProperty("cache_write_per_1m").GetString()!),
            value.GetProperty("currency").GetString()!,
            value.GetProperty("per_search_unit").ValueKind == JsonValueKind.Null ? null : EDecimal.FromString(value.GetProperty("per_search_unit").GetString()!),
            rates), provenance);
    }
    private static SpendPolicy? ReadSpendPolicy(JsonElement value) => value.ValueKind == JsonValueKind.Null ? null : new SpendPolicy(
        value.GetProperty("max_total_usd").ValueKind == JsonValueKind.Null ? null : EDecimal.FromString(value.GetProperty("max_total_usd").GetString()!),
        value.GetProperty("max_request_usd").ValueKind == JsonValueKind.Null ? null : EDecimal.FromString(value.GetProperty("max_request_usd").GetString()!),
        value.GetProperty("on_unknown").GetString()!);
    private static ITokenEstimator? ReadEstimator(JsonElement value) => value.ValueKind == JsonValueKind.Null ? null : new FixedEstimator(value.GetProperty("tokens").GetInt64(), value.GetProperty("floor").GetInt64());

    public async ValueTask DisposeAsync()
    {
        if (_client is not null) await CloseClientAsync().ConfigureAwait(false);
    }
}

internal sealed class FixedEstimator : ITokenEstimator
{
    private readonly TokenEstimate _estimate;
    internal FixedEstimator(long tokens, long floor) => _estimate = new TokenEstimate(tokens, floor);
    public TokenEstimate Estimate(string text)
    {
        ArgumentNullException.ThrowIfNull(text);
        return _estimate;
    }
}
