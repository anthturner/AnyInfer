using AnyInfer;
using AnyInfer.Events;
using AnyInfer.Providers;
using AnyInfer.Config;
using AnyInfer.Capabilities;
using PeterO.Numbers;
using System.Net;
using System.Net.Http.Headers;
using System.Runtime.ExceptionServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

internal sealed class PolicyCase
{
    private static readonly TimeSpan JoinTimeout = TimeSpan.FromSeconds(10);
    private readonly JsonElement _source;
    private readonly List<JsonObject> _http = [];
    private readonly List<JsonObject> _wires = [];
    private readonly List<JsonObject> _resources = [];
    private readonly List<JsonObject> _streamEvents = [];
    private readonly List<CapturedTelemetry> _telemetry = [];
    private readonly List<JsonObject> _operations = [];
    private readonly List<JsonObject> _checkpoints = [];
    private readonly List<string> _estimatorInputs = [];
    private readonly object _captureGate = new();
    private readonly Dictionary<string, int> _requestOperations = new(StringComparer.Ordinal);
    private readonly Dictionary<int, HashSet<string>> _operationRequests = [];
    private readonly Dictionary<(string RequestId, string Target), int> _attemptStarts = [];
    private readonly Dictionary<int, List<int>> _admissionOrdinals = [];
    private readonly Dictionary<int, HashSet<string>> _pendingAdmissionCheckpoints = [];
    private readonly Dictionary<int, TaskCompletionSource> _requestStarted = [];
    private readonly HashSet<string> _capturedCheckpoints = new(StringComparer.Ordinal);
    private int? _noAdmissionBeforeRelease;
    private bool _observerReleasedGate;
    private Exception? _observerFailure;
    private ScriptQueue? _scripts;
    private SpendLedger? _ledger;
    private ProviderRegistry? _registry;
    private CapabilityComposition? _capabilityComposition;
    private IObserver? _collector;
    private JsonElement _procedure;
    private string _caseId = string.Empty;
    private readonly AsyncLocal<int?> _currentOperation = new();

    private sealed record CapturedTelemetry(TelemetryEvent Value, int? Operation);

    private PolicyCase(JsonElement source) => _source = source;

    internal static async Task<JsonObject> RunAsync(JsonElement source)
    {
        var runner = new PolicyCase(source);
        return await runner.RunCoreAsync().ConfigureAwait(false);
    }

    private async Task<JsonObject> RunCoreAsync()
    {
        _caseId = RequestPolicyProgram.RequiredString(_source, "id");
        var kind = RequestPolicyProgram.RequiredString(_source, "kind");
        RegisterDeclaredSecrets();
        var procedure = _source.GetProperty("procedure");
        _procedure = procedure;
        var scripts = ScriptQueue.Create(_source.GetProperty("scripts"), _resources, _http, ObserveAdmission, _captureGate);
        _scripts = scripts;
        var capabilities = BuildCapabilityComposition();
        _capabilityComposition = capabilities;
        var registry = BuildRegistry(scripts, capabilities);
        _registry = registry;
        var collector = new EventCollector(ObserveTelemetry, RecordObserverFailure);
        _collector = collector;
        var ledger = _source.TryGetProperty("spend_policy", out _) ? new SpendLedger() : null;
        _ledger = ledger;
        AsyncClient? client = null;
        JsonObject? configuration = null;
        Exception? failure = null;
        try
        {
            (client, configuration) = CreateClient(kind, registry, scripts, collector, ledger, capabilities, manifestPayloads: false);
            var request = Request();
            Trace("procedure_schedule");
            var procedureTask = Task.Run(() => RunProcedureAsync(client, request, procedure, scripts));
            try
            {
                Trace("procedure_guard_begin");
                await JoinAsync(procedureTask).ConfigureAwait(false);
                Trace("procedure_guard_end");
            }
            catch (Exception exception)
            {
                failure = exception;
                scripts.ReleaseGates();
                Trace("procedure_guard_cleanup_begin");
                await RetainCleanupAsync(procedureTask, cleanupFailure => failure ??= cleanupFailure).ConfigureAwait(false);
                Trace("procedure_guard_cleanup_end");
            }
            if (failure is not null) ExceptionDispatchInfo.Capture(failure).Throw();
            ThrowObserverFailure();
            CaptureCheckpointIfDeclared(procedure, "after_terminal_cleanup");
            scripts.RequireConsumed();
            EnsureDeclaredCheckpoints(procedure);
        }
        catch (Exception exception)
        {
            failure = exception;
        }

        scripts.ReleaseGates();
        try
        {
            if (client is not null)
            {
                Trace("client_dispose_invoke");
                var disposal = client.DisposeAsync().AsTask();
                Trace("client_dispose_join_begin");
                await JoinAsync(disposal).ConfigureAwait(false);
                Trace("client_dispose_join_end");
            }
        }
        catch (Exception cleanupFailure)
        {
            failure ??= cleanupFailure;
        }
        try
        {
            scripts.Dispose();
        }
        catch (Exception cleanupFailure)
        {
            failure ??= cleanupFailure;
        }
        finally
        {
            AddResource(Resource("client_closed", null, null, null));
        }

        if (failure is not null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }

        JsonObject[] checkpoints;
        JsonObject[] http;
        JsonObject[] wires;
        JsonObject[] streamEvents;
        JsonObject[] resources;
        lock (_captureGate)
        {
            checkpoints = _checkpoints.ToArray();
            http = _http.ToArray();
            wires = _wires.ToArray();
            streamEvents = _streamEvents.ToArray();
            resources = _resources.ToArray();
        }

        return new JsonObject
        {
            ["id"] = RequestPolicyProgram.RequiredString(_source, "id"),
            ["kind"] = kind,
            ["status"] = "ok",
            ["value"] = new JsonObject
            {
                ["operations"] = OperationsValue(),
                ["ledger"] = ledger is null ? null : LedgerValue(ledger),
                ["checkpoints"] = new JsonArray(checkpoints.Cast<JsonNode?>().ToArray()),
                ["telemetry"] = TelemetryValue(),
                ["http"] = new JsonArray(http.Cast<JsonNode?>().ToArray()),
                ["adapter_wires"] = new JsonArray(wires.Cast<JsonNode?>().ToArray()),
                ["stream_events"] = new JsonArray(streamEvents.Cast<JsonNode?>().ToArray()),
                ["resources"] = new JsonArray(resources.Cast<JsonNode?>().ToArray()),
                ["configuration"] = configuration,
            },
        };
    }

    private void Trace(string phase) => RequestPolicyProgram.Diagnostic(_caseId, phase);

    private void RegisterDeclaredSecrets()
    {
        if (!_source.TryGetProperty("client", out var client) || !client.TryGetProperty("registered_secrets", out var secrets)) return;
        foreach (var value in secrets.EnumerateArray()) Redaction.RegisterSecret(value.GetString());
    }

    private (AsyncClient Client, JsonObject? Configuration) CreateClient(
        string kind,
        ProviderRegistry registry,
        ScriptQueue scripts,
        IObserver collector,
        SpendLedger? ledger,
        CapabilityComposition capabilities,
        bool manifestPayloads)
    {
        if (kind != "config_policy")
        {
            return (new AsyncClient(
                Settings(scripts), registry, observers: [collector], manifests: true,
                manifestPayloads: manifestPayloads, estimator: ReadEstimator(), ledger: ledger,
                spendPolicy: ReadSpendPolicy(), contextGate: ReadContextGate(), cachePolicy: ReadCachePolicy(),
                capabilityOverrides: capabilities.Overrides), null);
        }

        var parsed = AnyInferConfig.Loads(_source.GetProperty("config").GetRawText(), registry);
        var attached = parsed.Providers.Select(setting => new ProviderSettings(
            setting.ProviderId, setting.BaseUrl, setting.ApiKey, setting.ApiVersion,
            setting.Headers, setting.Options, setting.TimeoutS, scripts.CreateHandler(setting.InstanceId), setting.Alias, setting.Limits)).ToArray();
        for (var index = 0; index < attached.Length; index++)
        {
            var before = parsed.Providers[index];
            var after = attached[index];
            if (before.ProviderId != after.ProviderId || before.BaseUrl != after.BaseUrl || before.ApiKey != after.ApiKey ||
                before.ApiVersion != after.ApiVersion || !ReferenceEquals(before.Limits, after.Limits) ||
                !ReferenceEquals(before.Options, after.Options) || before.TimeoutS != after.TimeoutS || before.Alias != after.Alias)
            {
                throw new InvalidOperationException("Observer transport attachment changed parsed configuration policy values.");
            }
        }

        var configured = new AnyInferConfig(attached, parsed.Route, parsed.Repair, parsed.FormatVersion, parsed.Cache);
        return (AsyncClient.FromConfig(
            configured,
            registry,
            capabilityOverrides: capabilities.Overrides,
            observers: [collector],
            manifests: true,
            manifestPayloads: manifestPayloads,
            estimator: ReadEstimator(),
            ledger: ledger), new JsonObject
        {
            ["provider_ids"] = new JsonArray(configured.Providers.Select(static provider => JsonValue.Create(provider.InstanceId)).ToArray()),
            ["default_route"] = configured.Route is null ? new JsonArray() : new JsonArray(configured.Route.Targets.Select(static target => JsonValue.Create(target)).ToArray()),
            ["cache_mode"] = configured.Cache?.Mode.ToString().ToLowerInvariant(),
        });
    }

    private static bool HasCaptureModes(JsonElement procedure) => procedure.TryGetProperty("capture_modes", out var modes) && modes.GetArrayLength() != 0;

    private static string RequiredScalarString(JsonElement value, string name)
    {
        if (value.ValueKind != JsonValueKind.String || string.IsNullOrEmpty(value.GetString()))
        {
            throw new FormatException($"'{name}' must be a nonempty string.");
        }
        return value.GetString()!;
    }

    private async Task RunProcedureAsync(AsyncClient client, GenerationRequest request, JsonElement procedure, ScriptQueue scripts)
    {
        var name = RequestPolicyProgram.RequiredString(procedure, "name");
        CaptureCheckpointIfDeclared(procedure, "before_dispatch");
        switch (name)
        {
            case "stream_early_close":
                using (var cancellation = new CancellationTokenSource())
                {
                Exception? failure = null;
                CurrentOperation = 0;
                scripts.CurrentOperation = 0;
                var stream = client.StreamAsync(request, cancellation.Token);
                var enumerator = stream.GetAsyncEnumerator();
                try
                {
                    var sawContent = false;
                    while (!sawContent && await enumerator.MoveNextAsync().ConfigureAwait(false))
                    {
                        RecordStreamEvent(enumerator.Current, 0);
                        sawContent = enumerator.Current is TextDelta;
                    }
                    if (!sawContent) throw new InvalidOperationException("The declared early-close stream did not yield public content.");
                    var pendingRead = enumerator.MoveNextAsync().AsTask();
                    await scripts.WaitForGateAsync().ConfigureAwait(false);
                    AddResource(Resource("pending_observed", 0, null, null));
                    CaptureCheckpointIfDeclared(procedure, "while_stream_open");
                    cancellation.Cancel();
                    AddResource(Resource("cancel_requested", 0, null, null));
                    await JoinAsync(scripts.WaitForReadCancellationAsync()).ConfigureAwait(false);
                    scripts.ReleaseGates();
                    await RawReadCancellation.ObserveAsync(
                        scripts.CreateRawReadCancellationOracle(pendingRead, cancellation.Token),
                        JoinTimeout).ConfigureAwait(false);
                }
                catch (Exception exception) { failure = exception; }
                finally
                {
                    scripts.ReleaseGates();
                    await RetainCleanupAsync(enumerator.DisposeAsync().AsTask(), exception => failure ??= exception).ConfigureAwait(false);
                    await RetainCleanupAsync(stream.DisposeAsync().AsTask(), exception => failure ??= exception).ConfigureAwait(false);
                    CurrentOperation = null;
                    scripts.CurrentOperation = null;
                }
                if (failure is not null) ExceptionDispatchInfo.Capture(failure).Throw();
                AddResource(Resource("stream_closed", 0, null, null));
                CaptureCheckpointIfDeclared(procedure, "after_cancel");
                CaptureCheckpointIfDeclared(procedure, "after_close");
                AddOperation(Operation(0, "stream", "cancelled", null, null, [], cancelRequested: true));
                }
                await InvokeAsync(client, WithoutStreaming(request), 1).ConfigureAwait(false);
                break;
            case "concurrent_reservation_recovery":
                using (var cancellation = new CancellationTokenSource())
                {
                    var pending = InvokeAsync(client, request, 0, cancellation.Token, observerRequestedCancellation: true);
                    await scripts.WaitForGateAsync().ConfigureAwait(false);
                    AddResource(Resource("pending_observed", 0, null, null));
                    await InvokeAsync(client, request, 1).ConfigureAwait(false);
                    cancellation.Cancel();
                    AddResource(Resource("cancel_requested", 0, null, null));
                    scripts.ReleaseGates();
                    await ObserveInvocationCancellationAsync(pending, 0, cancellation.Token).ConfigureAwait(false);
                    CaptureCheckpointIfDeclared(procedure, "after_cancel");
                }
                await InvokeAsync(client, request, 2).ConfigureAwait(false);
                break;
            case "cache_sequence":
                if (!_source.GetProperty("request").TryGetProperty("calls", out var calls))
                {
                    await InvokeAsync(client, request, 0).ConfigureAwait(false);
                    break;
                }
                var index = 0;
                foreach (var call in calls.EnumerateArray())
                {
                    var varied = new GenerationRequest(ReadMessages(call.GetProperty("messages")), request.Route, request.Sampling, request.Repair, request.Schema, request.SchemaMechanism, request.TimeoutS, request.MaxResponseBytes, request.Stream, request.Tools, request.ToolChoice, request.Cache);
                    await InvokeAsync(client, varied, index++).ConfigureAwait(false);
                }
                break;
            case "governor_body_gate":
                var first = InvokeAsync(client, request, 0);
                await JoinAsync(scripts.WaitForGateAsync()).ConfigureAwait(false);
                AddResource(Resource("pending_observed", 0, null, null));
                if (scripts.LatestGateName == "queue")
                {
                    await RunQueuedGovernorAsync(client, request, scripts, first).ConfigureAwait(false);
                    await InvokeAsync(client, request, 2).ConfigureAwait(false);
                }
                else
                {
                    await RunGatedTwoCallsAsync(client, request, request, scripts, first, firstAlreadyObserved: true).ConfigureAwait(false);
                }
                break;
            case "context_route":
                var routed = InvokeAsync(client, request, 0);
                if (scripts.HasDeclaredGate)
                {
                    await scripts.WaitForGateAsync().ConfigureAwait(false);
                    AddResource(Resource("pending_observed", 0, null, null));
                    scripts.ReleaseGates();
                }
                await JoinAsync(routed).ConfigureAwait(false);
                break;
            case "config_consumer":
                if (scripts.HasDeclaredGate)
                {
                    await RunGatedTwoCallsAsync(client, request, WithCache(request, ReadCallerCache()), scripts).ConfigureAwait(false);
                }
                else
                {
                    var operation = 0;
                    while (scripts.Remaining > 0)
                    {
                        var configured = operation == 0 ? request : WithCache(request, ReadCallerCache());
                        await InvokeAsync(client, configured, operation++).ConfigureAwait(false);
                    }
                }
                break;
            case "tool_stream" when HasCaptureModes(procedure):
                var captureOperation = 0;
                var streamingRequest = WithStreaming(request);
                foreach (var mode in procedure.GetProperty("capture_modes").EnumerateArray())
                {
                    switch (RequiredScalarString(mode, "capture_modes item"))
                    {
                        case "default":
                            await InvokeAsync(client, streamingRequest, captureOperation++).ConfigureAwait(false);
                            break;
                        case "explicit":
                            await InvokeWithExplicitPayloadsAsync(streamingRequest, captureOperation++, scripts).ConfigureAwait(false);
                            break;
                        default:
                            throw new FormatException("Unknown public manifest capture mode.");
                    }
                }
                break;
            case "tool_stream":
                await InvokeAsync(client, WithStreaming(request), 0).ConfigureAwait(false);
                break;
            default:
                await InvokeAsync(client, request, 0).ConfigureAwait(false);
                break;
        }
    }

    private async Task InvokeWithExplicitPayloadsAsync(GenerationRequest request, int operation, ScriptQueue scripts)
    {
        AsyncClient? explicitClient = null;
        Exception? failure = null;
        try
        {
            (explicitClient, _) = CreateClient(
                RequestPolicyProgram.RequiredString(_source, "kind"),
                _registry ?? throw new InvalidOperationException("Missing public registry."),
                scripts,
                _collector ?? throw new InvalidOperationException("Missing public observer."),
                _ledger,
                _capabilityComposition ?? throw new InvalidOperationException("Missing capability composition."),
                manifestPayloads: true);
            await InvokeAsync(explicitClient, request, operation).ConfigureAwait(false);
        }
        catch (Exception exception) { failure = exception; }
        finally
        {
            scripts.ReleaseGates();
            if (explicitClient is not null)
            {
                await RetainCleanupAsync(explicitClient.DisposeAsync().AsTask(), exception => failure ??= exception).ConfigureAwait(false);
            }
        }
        if (failure is not null) ExceptionDispatchInfo.Capture(failure).Throw();
    }

    private async Task RunGatedTwoCallsAsync(
        AsyncClient client,
        GenerationRequest firstRequest,
        GenerationRequest secondRequest,
        ScriptQueue scripts,
        Task? first = null,
        bool firstAlreadyObserved = false)
    {
        first ??= InvokeAsync(client, firstRequest, 0);
        Task? second = null;
        Exception? failure = null;
        try
        {
            if (!firstAlreadyObserved)
            {
                await JoinAsync(scripts.WaitForGateAsync()).ConfigureAwait(false);
                AddResource(Resource("pending_observed", 0, null, null));
            }
            RequireNoAdmissionBeforeRelease(1);
            second = InvokeAsync(client, secondRequest, 1);
            await JoinAsync(WaitForRequestStartedAsync(1)).ConfigureAwait(false);
            AddResource(Resource("pending_observed", 1, null, null));
            if (HasAdmission(1))
            {
                throw new InvalidOperationException("A later public invocation sent before the declared body gate released.");
            }
        }
        catch (Exception exception)
        {
            failure = exception;
        }
        finally
        {
            ReleaseGuardedGates(scripts);
            await RetainCleanupAsync(first, exception => failure ??= exception).ConfigureAwait(false);
            if (second is not null)
            {
                await RetainCleanupAsync(second, exception => failure ??= exception).ConfigureAwait(false);
            }
        }

        if (failure is not null) ExceptionDispatchInfo.Capture(failure).Throw();
    }

    private async Task RunQueuedGovernorAsync(AsyncClient client, GenerationRequest request, ScriptQueue scripts, Task first)
    {
        using var cancellation = new CancellationTokenSource();
        Task? queued = null;
        Exception? failure = null;
        try
        {
            RequireNoAdmissionBeforeRelease(1);
            queued = InvokeAsync(client, request, 1, cancellation.Token, observerRequestedCancellation: true);
            await JoinAsync(WaitForRequestStartedAsync(1)).ConfigureAwait(false);
            AddResource(Resource("pending_observed", 1, null, null));
            if (HasAdmission(1))
            {
                throw new InvalidOperationException("A queued public invocation sent before its declared cancellation.");
            }
            cancellation.Cancel();
            AddResource(Resource("cancel_requested", 1, null, null));
            await ObserveInvocationCancellationAsync(queued, 1, cancellation.Token).ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            failure = exception;
        }
        finally
        {
            ReleaseGuardedGates(scripts);
            if (queued is not null)
            {
                await RetainCleanupAsync(queued, exception => failure ??= exception).ConfigureAwait(false);
            }
            await RetainCleanupAsync(first, exception => failure ??= exception).ConfigureAwait(false);
        }

        if (failure is not null) ExceptionDispatchInfo.Capture(failure).Throw();
    }

    private async Task InvokeAsync(AsyncClient client, GenerationRequest request, int index, CancellationToken cancellationToken = default, bool observerRequestedCancellation = false)
    {
        try
        {
            CurrentOperation = index;
            _scripts!.CurrentOperation = index;
            if (request.Stream)
            {
                var stream = client.StreamAsync(request, cancellationToken);
                Exception? failure = null;
                try
                {
                    await foreach (var item in stream.WithCancellation(cancellationToken).ConfigureAwait(false)) RecordStreamEvent(item, index);
                }
                catch (Exception exception) { failure = exception; }
                finally
                {
                    await RetainCleanupAsync(stream.DisposeAsync().AsTask(), exception => failure ??= exception).ConfigureAwait(false);
                }
                if (failure is not null) ExceptionDispatchInfo.Capture(failure).Throw();
                return;
            }

            var result = await client.GenerateAsync(request, cancellationToken).ConfigureAwait(false);
            AddOperation(Operation(index, "generate", "ok", ResultValue(index, result), null, result.Attempts, cancelRequested: false));
        }
        catch (OperationCanceledException exception) when (observerRequestedCancellation && IsDeclaredCancellation(exception, cancellationToken))
        {
            AddOperation(Operation(index, request.Stream ? "stream" : "generate", "cancelled", null, null, [], cancelRequested: true));
        }
        catch (AnyInferException exception)
        {
            AddOperation(Operation(index, request.Stream ? "stream" : "generate", "error", null, ErrorValue(exception), exception is AllTargetsFailedException failed ? failed.Attempts : [], cancelRequested: false));
        }
        finally
        {
            CurrentOperation = null;
            _scripts!.CurrentOperation = null;
        }
    }

    private static bool IsDeclaredCancellation(OperationCanceledException exception, CancellationToken declaredToken) =>
        declaredToken.IsCancellationRequested && exception.CancellationToken == declaredToken;

    private async Task ObserveInvocationCancellationAsync(Task task, int operation, CancellationToken declaredToken)
    {
        await JoinAsync(task).ConfigureAwait(false);
        var cancelled = false;
        lock (_captureGate)
        {
            cancelled = _operations.Any(value =>
                value["index"]?.GetValue<int>() == operation &&
                value["outcome"]?.GetValue<string>() == "cancelled");
        }
        if (!declaredToken.IsCancellationRequested || !cancelled)
        {
            throw new InvalidOperationException("A declared observer invocation did not record its matching cancellation.");
        }
    }

    private static async Task RetainCleanupAsync(Task task, Action<Exception> retain)
    {
        try { await JoinAsync(task).ConfigureAwait(false); }
        catch (Exception exception) { retain(exception); }
    }

    private static async Task JoinAsync(Task task)
    {
        await task.WaitAsync(JoinTimeout).ConfigureAwait(false);
    }

    private void AddResource(JsonObject value)
    {
        lock (_captureGate) _resources.Add(value);
    }

    private void AddOperation(JsonObject value)
    {
        lock (_captureGate) _operations.Add(value);
    }

    private bool HasAdmission(int operation)
    {
        lock (_captureGate) return _admissionOrdinals.TryGetValue(operation, out var values) && values.Count != 0;
    }

    private void RequireNoAdmissionBeforeRelease(int operation)
    {
        lock (_captureGate)
        {
            _noAdmissionBeforeRelease = operation;
            _observerReleasedGate = false;
        }
    }

    private void ReleaseGuardedGates(ScriptQueue scripts)
    {
        lock (_captureGate) _observerReleasedGate = true;
        scripts.ReleaseGates();
    }

    private Task WaitForRequestStartedAsync(int operation)
    {
        lock (_captureGate)
        {
            return RequestStartedSource(operation).Task;
        }
    }

    private TaskCompletionSource RequestStartedSource(int operation)
    {
        if (!_requestStarted.TryGetValue(operation, out var source))
        {
            source = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            _requestStarted.Add(operation, source);
        }
        return source;
    }

    private ProviderRegistry BuildRegistry(ScriptQueue scripts, CapabilityComposition capabilities)
    {
        var builtin = ProviderRegistry.CreateDefault().Descriptors.Single(static descriptor => descriptor.Id == "openai-compat");
        var descriptors = new List<ProviderDescriptor>
        {
            capabilities.HasDescriptorFacts(builtin.Id)
                ? CloneDescriptor(builtin, capabilities.DefaultFor(builtin.Id), capabilities.StaticFor(builtin.Id))
                : builtin,
        };
        if (_source.TryGetProperty("descriptor", out var descriptor) && descriptor.ValueKind != JsonValueKind.Null)
        {
            var id = RequestPolicyProgram.RequiredString(descriptor, "id");
            var mechanism = descriptor.TryGetProperty("cache_mechanism", out var rawMechanism)
                ? Enum.Parse<CacheMechanism>(rawMechanism.GetString()!, ignoreCase: true)
                : (CacheMechanism?)null;
            descriptors.Add(new ProviderDescriptor(
                id, id, (config, _) => new ValueTask<IProviderAdapter>(new RecordingAdapter(scripts, _wires, config.ProviderId, id)),
                aliases: ["recording"], cacheMechanism: mechanism,
                cacheMaxMarks: descriptor.TryGetProperty("cache_max_marks", out var marks) ? marks.GetInt32() : 0,
                cacheMinTokens: descriptor.TryGetProperty("cache_min_tokens", out var floor) ? floor.GetInt64() : 0,
                defaultCapabilities: capabilities.DefaultFor(id),
                staticCapabilities: capabilities.StaticFor(id)));
        }
        capabilities.EnsureBound(descriptors);
        return new ProviderRegistry(descriptors);
    }

    private IReadOnlyList<ProviderSettings> Settings(ScriptQueue scripts)
    {
        var source = _source.TryGetProperty("instances", out var instances)
            ? instances
            : _source.GetProperty("config").GetProperty("providers");
        var settings = new List<ProviderSettings>();
        foreach (var item in source.EnumerateArray())
        {
            var id = RequestPolicyProgram.RequiredString(item, "id");
            var adapter = RequestPolicyProgram.RequiredString(item, "adapter");
            settings.Add(ProviderSettings.Of(
                adapter == "recording" ? RequestPolicyProgram.RequiredString(item, "descriptor") : "openai-compat",
                baseUrl: "https://policy.invalid/v1",
                apiKey: RequestPolicyProgram.RequiredString(item, "api_key"),
                transport: scripts.CreateHandler(id),
                alias: id,
                limits: item.TryGetProperty("limits", out var limits) ? ReadLimits(limits) : null));
        }
        return settings;
    }

    private GenerationRequest Request()
    {
        var raw = _source.TryGetProperty("request", out var request) ? request : _source.GetProperty("action");
        var route = raw.TryGetProperty("route", out var configured) ? ReadRoute(configured) : new Route([RequestPolicyProgram.RequiredString(raw, "target")]);
        var sampling = raw.TryGetProperty("max_output_tokens", out var output) ? new Sampling(maxOutputTokens: output.GetInt32()) : null;
        var repair = raw.TryGetProperty("repair", out var repairValue) ? new Repair(repairValue.GetProperty("max_attempts").GetInt32()) : null;
        var schema = raw.TryGetProperty("schema", out var schemaValue) ? SchemaSpec.FromJson(schemaValue.GetRawText()) : null;
        return new GenerationRequest(ReadMessages(raw.GetProperty("messages")), route, sampling, repair, schema, stream: raw.TryGetProperty("stream", out var stream) && stream.GetBoolean(), tools: ReadTools(raw), toolChoice: raw.TryGetProperty("tool_choice", out var choice) ? choice.GetString()! : "auto", cache: ReadCache(raw));
    }

    private static Route ReadRoute(JsonElement value)
    {
        var retry = value.GetProperty("retry");
        return new Route(value.GetProperty("targets").EnumerateArray().Select(static item => item.GetString()!), new Retry(retry.GetProperty("max_attempts").GetInt32(), retry.GetProperty("backoff_base_s").GetDouble(), retry.GetProperty("backoff_max_s").GetDouble()), value.GetProperty("health_gate").GetBoolean(), contextWindowTargets: value.TryGetProperty("context_window_targets", out var contexts) ? contexts.EnumerateArray().Select(static item => item.GetString()!) : null);
    }

    private static IReadOnlyList<Message> ReadMessages(JsonElement source)
    {
        var messages = new List<Message>();
        foreach (var item in source.EnumerateArray())
        {
            var parts = new List<ContentPart>();
            if (item.TryGetProperty("content", out var content) && content.ValueKind != JsonValueKind.Null) parts.Add(new Text(content.GetString()!));
            if (item.TryGetProperty("parts", out var rawParts))
            {
                foreach (var part in rawParts.EnumerateArray())
                {
                    switch (RequestPolicyProgram.RequiredString(part, "type"))
                    {
                        case "text": parts.Add(new Text(RequestPolicyProgram.RequiredString(part, "text"))); break;
                        case "tool_call":
                            var arguments = AnyInfer.Json.JsonReader.Read(part.GetProperty("arguments").GetRawText()) as AnyInfer.Json.JsonObject
                                ?? throw new FormatException("Tool arguments must be an object.");
                            parts.Add(new ToolCall(RequestPolicyProgram.RequiredString(part, "id"), RequestPolicyProgram.RequiredString(part, "name"), arguments));
                            break;
                        case "tool_result": parts.Add(new ToolResult(RequestPolicyProgram.RequiredString(part, "call_id"), RequestPolicyProgram.RequiredString(part, "content"), part.GetProperty("is_error").GetBoolean())); break;
                        default: throw new FormatException("Unknown content part.");
                    }
                }
            }
            messages.Add(new Message(RequestPolicyProgram.RequiredString(item, "role"), parts));
        }
        return messages;
    }

    private static IReadOnlyList<ToolSpec> ReadTools(JsonElement value)
    {
        if (!value.TryGetProperty("tools", out var tools)) return [];
        return tools.EnumerateArray().Select(static item => new ToolSpec(
            RequestPolicyProgram.RequiredString(item, "name"),
            RequestPolicyProgram.RequiredString(item, "description"),
            AnyInfer.Json.JsonReader.Read(item.GetProperty("parameters").GetRawText()) as AnyInfer.Json.JsonObject
                ?? throw new FormatException("Tool parameters must be an object."))).ToArray();
    }

    private static GenerationRequest WithoutStreaming(GenerationRequest source) => new(
        source.Messages, source.Route, source.Sampling, source.Repair, source.Schema,
        source.SchemaMechanism, source.TimeoutS, source.MaxResponseBytes, stream: false,
        source.Tools, source.ToolChoice, source.Cache);

    private static GenerationRequest WithStreaming(GenerationRequest source) => new(
        source.Messages, source.Route, source.Sampling, source.Repair, source.Schema,
        source.SchemaMechanism, source.TimeoutS, source.MaxResponseBytes, stream: true,
        source.Tools, source.ToolChoice, source.Cache);

    private static GenerationRequest WithCache(GenerationRequest source, CachePolicy? cache) => new(
        source.Messages, source.Route, source.Sampling, source.Repair, source.Schema,
        source.SchemaMechanism, source.TimeoutS, source.MaxResponseBytes, source.Stream,
        source.Tools, source.ToolChoice, cache);

    private CachePolicy? ReadCache(JsonElement request) => request.TryGetProperty("cache", out var cache) ? ReadCacheValue(cache) : null;

    private static CachePolicy ReadCacheValue(JsonElement cache)
    {
        return new CachePolicy(
            Enum.Parse<CacheMode>(RequestPolicyProgram.RequiredString(cache, "mode"), ignoreCase: true),
            cache.GetProperty("min_segment_tokens").GetInt64(),
            cache.GetProperty("max_marks").GetInt32());
    }

    private ITokenEstimator ReadEstimator()
    {
        ITokenEstimator inner = _source.TryGetProperty("estimator", out var estimator)
            ? new LiteralEstimator(estimator.GetProperty("tokens").GetInt64(), estimator.GetProperty("floor").GetInt64())
            : new HeuristicTokenEstimator();
        return new RecordingEstimator(inner, _estimatorInputs, _captureGate);
    }

    private SpendPolicy? ReadSpendPolicy()
    {
        if (!_source.TryGetProperty("spend_policy", out var policy)) return null;
        return new SpendPolicy(ReadDecimal(policy, "max_total_usd"), ReadDecimal(policy, "max_request_usd"), RequestPolicyProgram.RequiredString(policy, "on_unknown"));
    }

    private static EDecimal? ReadDecimal(JsonElement value, string name) =>
        value.TryGetProperty(name, out var raw) && raw.ValueKind != JsonValueKind.Null
            ? EDecimal.FromString(RequestPolicyProgram.RequiredString(value, name))
            : null;
    private static RateLimits ReadLimits(JsonElement value) => new(
        value.TryGetProperty("max_concurrent", out var concurrent) && concurrent.ValueKind != JsonValueKind.Null ? concurrent.GetInt32() : null,
        value.TryGetProperty("requests_per_minute", out var requests) && requests.ValueKind != JsonValueKind.Null ? requests.GetDouble() : null,
        value.TryGetProperty("min_interval_s", out var interval) ? interval.GetDouble() : 0,
        value.TryGetProperty("respect_headers", out var headers) ? headers.GetBoolean() : true,
        value.TryGetProperty("reserve_fraction", out var reserve) ? reserve.GetDouble() : 0);
    private bool ReadContextGate() => !_source.TryGetProperty("client", out var client) || !client.TryGetProperty("context_gate", out var gate) || gate.GetBoolean();
    private CachePolicy? ReadCachePolicy() => null;
    private CachePolicy? ReadCallerCache() => _source.TryGetProperty("action", out var action) && action.TryGetProperty("caller_cache", out var cache) ? ReadCacheValue(cache) : null;

    private CapabilityComposition BuildCapabilityComposition()
    {
        var composition = new CapabilityComposition(ReadDescriptorBindings());

        if (_source.TryGetProperty("capabilities", out var capabilities))
        {
            foreach (var value in capabilities.EnumerateArray())
            {
                var provenance = Enum.Parse<Provenance>(RequestPolicyProgram.RequiredString(value, "provenance"), ignoreCase: true);
                var context = value.TryGetProperty("context_window", out var window) && window.ValueKind != JsonValueKind.Null
                    ? new Sourced<int>(window.GetInt32(), provenance)
                    : null;
                Sourced<Feature>? features = null;
                if (value.TryGetProperty("features", out var declaredFeatures))
                {
                    var combined = Feature.None;
                    foreach (var declared in declaredFeatures.EnumerateArray())
                    {
                        var literal = RequiredScalarString(declared, "features item");
                        var member = Enum.GetNames<Feature>().SingleOrDefault(name =>
                            string.Equals(name, literal.Replace("_", string.Empty, StringComparison.Ordinal), StringComparison.OrdinalIgnoreCase))
                            ?? throw new FormatException($"Unknown capability feature '{literal}'.");
                        combined |= Enum.Parse<Feature>(member, ignoreCase: false);
                    }
                    features = new Sourced<Feature>(combined, provenance);
                }
                composition.Add(RequestPolicyProgram.RequiredString(value, "target"), provenance, new ModelCapabilities(contextWindow: context, features: features));
            }
        }
        if (_source.TryGetProperty("pricing", out var pricing))
        {
            foreach (var value in pricing.EnumerateArray())
            {
                var target = RequestPolicyProgram.RequiredString(value, "target");
                var provenance = Enum.Parse<Provenance>(RequestPolicyProgram.RequiredString(value, "provenance"), ignoreCase: true);
                var price = new Pricing(EDecimal.FromString(RequestPolicyProgram.RequiredString(value, "input_per_1m")), EDecimal.FromString(RequestPolicyProgram.RequiredString(value, "output_per_1m")));
                composition.Add(target, provenance, new ModelCapabilities(pricing: new Sourced<Pricing>(price, provenance)));
            }
        }
        return composition;
    }

    private void RecordStreamEvent(StreamEvent item, int operation)
    {
        lock (_captureGate)
        {
            if (item is ToolCallDelta tool) _streamEvents.Add(new JsonObject { ["type"] = "tool_call_delta", ["operation_index"] = operation, ["index"] = tool.Index, ["id"] = tool.CallId, ["name"] = tool.Name, ["arguments"] = tool.ArgumentsFragment is null ? null : Redaction.Redact(tool.ArgumentsFragment) });
            if (item is TimingMark timing && timing.Name is "first_token" or "last_token") _streamEvents.Add(new JsonObject { ["type"] = "timing_mark", ["operation_index"] = operation, ["name"] = timing.Name });
            if (item is StreamEnded ended) _operations.Add(Operation(operation, "stream", "ok", ResultValue(operation, ended.Result), null, ended.Result.Attempts, cancelRequested: false));
        }
    }

    private void ObserveTelemetry(TelemetryEvent telemetryEvent)
    {
        lock (_captureGate)
        {
            var operation = CaptureTelemetryOperation(telemetryEvent);
            _telemetry.Add(new CapturedTelemetry(telemetryEvent, operation));
            switch (telemetryEvent)
            {
                case RetryScheduled:
                    MarkNextAdmissionCheckpoint("after_retry_replacement", operation);
                    break;
                case FallbackTriggered:
                    MarkNextAdmissionCheckpoint("after_fallback_handoff", operation);
                    break;
                case RepairAttempted:
                    MarkNextAdmissionCheckpoint("after_repair", operation);
                    break;
            }
        }
    }

    private int? CaptureTelemetryOperation(TelemetryEvent telemetryEvent)
    {
        if (telemetryEvent is RequestStarted started)
        {
            var operation = CurrentOperation ?? throw new InvalidOperationException("RequestStarted was emitted outside a public operation.");
            _requestOperations.Add(started.RequestId, operation);
            if (!_operationRequests.TryGetValue(operation, out var requestIds))
            {
                requestIds = new HashSet<string>(StringComparer.Ordinal);
                _operationRequests.Add(operation, requestIds);
            }
            requestIds.Add(started.RequestId);
            RequestStartedSource(operation).TrySetResult();
            return operation;
        }

        if (telemetryEvent is AttemptStarted attempt)
        {
            var operation = RequestOperation(attempt.RequestId);
            _attemptStarts[(attempt.RequestId, attempt.Target.ToString())] = attempt.AttemptNumber;
            return operation;
        }

        return telemetryEvent switch
        {
            TargetResolved value => RequestOperation(value.RequestId),
            AttemptCompleted value => RequestOperation(value.RequestId),
            RetryScheduled value => RequestOperation(value.RequestId),
            FallbackTriggered value => RequestOperation(value.RequestId),
            RepairAttempted value => RequestOperation(value.RequestId),
            RequestCompleted value => RequestOperation(value.RequestId),
            RequestFailed value => RequestOperation(value.RequestId),
            CachePlanned value => RequestOperation(value.RequestId),
            ParameterDropped value => RequestOperation(value.RequestId),
            UsageEstimated value => RequestOperation(value.RequestId),
            _ => null,
        };
    }

    private int RequestOperation(string requestId) => _requestOperations.TryGetValue(requestId, out var operation)
        ? operation
        : throw new InvalidOperationException("A request-scoped public event was observed before RequestStarted.");

    private void ObserveAdmission(int? operation, int ordinal)
    {
        if (operation is null || ordinal <= 0)
        {
            throw new InvalidOperationException("A public handler or adapter entry was observed outside an operation.");
        }

        string[] checkpoints;
        lock (_captureGate)
        {
            if (_noAdmissionBeforeRelease == operation && !_observerReleasedGate)
            {
                throw new InvalidOperationException("A declared later operation reached the public handler before the observer released its gate.");
            }
            if (!_admissionOrdinals.TryGetValue(operation.Value, out var ordinals))
            {
                ordinals = [];
                _admissionOrdinals.Add(operation.Value, ordinals);
            }

            ordinals.Add(ordinal);
            if (!_pendingAdmissionCheckpoints.TryGetValue(operation.Value, out var pending))
            {
                checkpoints = [];
            }
            else
            {
                checkpoints = pending.ToArray();
                _pendingAdmissionCheckpoints.Remove(operation.Value);
            }
        }

        CaptureCheckpointIfDeclared(_procedure, "after_initial_reserve");
        foreach (var name in checkpoints) CaptureCheckpointIfDeclared(_procedure, name);
    }

    private void MarkNextAdmissionCheckpoint(string name, int? operation)
    {
        if (operation is not int operationIndex)
        {
            throw new InvalidOperationException($"{name} was emitted outside an active public operation.");
        }

        if (!_pendingAdmissionCheckpoints.TryGetValue(operationIndex, out var pending))
        {
            pending = new HashSet<string>(StringComparer.Ordinal);
            _pendingAdmissionCheckpoints.Add(operationIndex, pending);
        }

        pending.Add(name);
    }

    private void CaptureCheckpointIfDeclared(JsonElement procedure, string name)
    {
        var ledger = _ledger;
        if (ledger is null || !procedure.TryGetProperty("checkpoints", out var names) || !names.EnumerateArray().Any(value => value.GetString() == name)) return;
        var reserved = ledger.Reserved().ToString();
        var totals = ledger.Totals();
        lock (_captureGate)
        {
            if (!_capturedCheckpoints.Add(name)) return;
            _checkpoints.Add(new JsonObject
            {
                ["name"] = name,
                ["reserved"] = reserved,
                ["totals"] = new JsonObject
                {
                    ["cost"] = totals.Cost.ToString(), ["currency"] = totals.Currency,
                    ["requests"] = totals.Requests, ["unknown_requests"] = totals.UnknownRequests,
                    ["input_tokens"] = totals.InputTokens, ["output_tokens"] = totals.OutputTokens,
                    ["cache_read_tokens"] = totals.CacheReadTokens,
                },
                ["estimator_inputs"] = new JsonArray(_estimatorInputs.Select(static input => JsonValue.Create(input)).ToArray()),
            });
        }
    }

    private void EnsureDeclaredCheckpoints(JsonElement procedure)
    {
        lock (_captureGate)
        {
            if (_ledger is null || !procedure.TryGetProperty("checkpoints", out var names)) return;
            foreach (var name in names.EnumerateArray().Select(static value => value.GetString()))
            {
                if (name is null || !_capturedCheckpoints.Contains(name))
                {
                    throw new InvalidOperationException("A declared public checkpoint was not causally observed.");
                }
            }
        }
    }

    private void RecordObserverFailure(Exception exception)
    {
        lock (_captureGate) _observerFailure ??= exception;
    }

    private void ThrowObserverFailure()
    {
        Exception? failure;
        lock (_captureGate) failure = _observerFailure;
        if (failure is not null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private int? CurrentOperation
    {
        get => _currentOperation.Value;
        set => _currentOperation.Value = value;
    }

    private JsonArray OperationsValue()
    {
        (JsonObject Value, int Index)[] ordered;
        lock (_captureGate)
        {
            ordered = _operations
                .Select(value => (Value: value, Index: value["index"]?.GetValue<int>()
                    ?? throw new InvalidOperationException("A captured operation has no invocation index.")))
                .OrderBy(static value => value.Index)
                .ToArray();
        }
        if (ordered.Select(static value => value.Index).Distinct().Count() != ordered.Length)
        {
            throw new InvalidOperationException("A public invocation produced more than one captured operation.");
        }
        return new JsonArray(ordered.Select(static value => (JsonNode?)value.Value).ToArray());
    }

    private JsonArray TelemetryValue()
    {
        CapturedTelemetry[] telemetry;
        lock (_captureGate) telemetry = _telemetry.ToArray();
        return new JsonArray(telemetry.Select(ProjectTelemetry).Where(static item => item is not null).Cast<JsonNode?>().ToArray());
    }
    private JsonObject? ProjectTelemetry(CapturedTelemetry captured)
    {
        var item = captured.Value;
        var operation = captured.Operation;
        return item switch
        {
            RequestStarted started => RequestStartedValue(started, operation),
            TargetResolved resolved => new JsonObject { ["type"] = "TargetResolved", ["operation_index"] = operation, ["target"] = resolved.Target.ToString() },
            AttemptStarted started => AttemptStartedValue(started, operation),
            AttemptCompleted completed => AttemptCompletedValue(completed, operation),
            RetryScheduled retry => new JsonObject { ["type"] = "RetryScheduled", ["operation_index"] = operation, ["attempt"] = retry.AttemptNumber, ["error"] = ErrorInfoValue(retry.Error) },
            FallbackTriggered fallback => new JsonObject { ["type"] = "FallbackTriggered", ["operation_index"] = operation, ["source"] = fallback.FromTarget.ToString(), ["destination"] = fallback.ToTarget, ["error"] = fallback.Error is null ? null : ErrorInfoValue(fallback.Error) },
            RepairAttempted repair => new JsonObject { ["type"] = "RepairAttempted", ["operation_index"] = operation, ["count"] = repair.AttemptNumber, ["mechanism"] = repair.Mechanism },
            RequestCompleted completed => new JsonObject { ["type"] = "RequestCompleted", ["operation_index"] = operation, ["target"] = completed.Target.ToString(), ["usage"] = UsageValue(completed.Usage), ["repair_attempts"] = completed.RepairAttempts },
            RequestFailed failed => new JsonObject { ["type"] = "RequestFailed", ["operation_index"] = operation, ["error"] = ErrorInfoValue(failed.Error) },
            CachePlanned planned => new JsonObject { ["type"] = "CachePlanned", ["operation_index"] = operation, ["mechanism"] = planned.Mechanism, ["count"] = planned.MarkCount, ["estimated_tokens"] = planned.EstimatedCacheableTokens },
            ParameterDropped dropped => new JsonObject { ["type"] = "ParameterDropped", ["operation_index"] = operation, ["parameter"] = dropped.Parameter, ["reason"] = dropped.Reason },
            UsageEstimated estimated => new JsonObject { ["type"] = "UsageEstimated", ["operation_index"] = operation, ["field"] = estimated.FieldName, ["method"] = estimated.Method },
            ProviderDiagnostic diagnostic => new JsonObject { ["type"] = "ProviderDiagnostic", ["operation_index"] = operation, ["target"] = diagnostic.Target?.ToString(), ["code"] = diagnostic.Diagnostic.Code, ["severity"] = diagnostic.Diagnostic.Severity.ToString() },
            RateLimitObserved observed => new JsonObject { ["type"] = "RateLimitObserved", ["operation_index"] = null, ["provider"] = observed.ProviderId, ["remaining"] = observed.RequestsRemaining, ["reset"] = observed.ResetsInS?.ToString(System.Globalization.CultureInfo.InvariantCulture) },
            FirstToken or RateLimitWaited => null,
            _ => throw new InvalidOperationException($"Unsupported public telemetry event '{item.GetType().Name}'."),
        };
    }

    private JsonObject RequestStartedValue(RequestStarted value, int? operation)
    {
        return new JsonObject { ["type"] = "RequestStarted", ["operation_index"] = operation, ["targets"] = new JsonArray(value.Targets.Select(static target => JsonValue.Create(target)).ToArray()) };
    }
    private JsonObject AttemptStartedValue(AttemptStarted value, int? operation)
    {
        return new JsonObject { ["type"] = "AttemptStarted", ["operation_index"] = operation, ["attempt"] = value.AttemptNumber, ["target"] = value.Target.ToString() };
    }

    private JsonObject AttemptCompletedValue(AttemptCompleted value, int? operation)
    {
        lock (_captureGate)
        {
            if (!_attemptStarts.TryGetValue((value.RequestId, value.Target.ToString()), out _))
            {
                throw new InvalidOperationException("AttemptCompleted was observed without a preceding public AttemptStarted for the same request and target.");
            }
        }

        return new JsonObject { ["type"] = "AttemptCompleted", ["operation_index"] = operation, ["outcome"] = "ok" };
    }
    private static JsonObject ErrorInfoValue(ErrorInfo value) => new() { ["runtime_type"] = value.TypeName, ["provider"] = value.Provider, ["phase"] = value.Phase, ["retryable"] = value.Retryable, ["http_status"] = value.HttpStatus };
    private static JsonObject LedgerValue(SpendLedger ledger) => new() { ["reserved"] = ledger.Reserved().ToString(), ["totals"] = new JsonObject { ["cost"] = ledger.Totals().Cost.ToString(), ["currency"] = ledger.Totals().Currency, ["requests"] = ledger.Totals().Requests, ["unknown_requests"] = ledger.Totals().UnknownRequests, ["input_tokens"] = ledger.Totals().InputTokens, ["output_tokens"] = ledger.Totals().OutputTokens, ["cache_read_tokens"] = ledger.Totals().CacheReadTokens } };
    private JsonObject ResultValue(int operation, Generation value) => new() { ["target"] = value.Target?.ToString(), ["text"] = Redaction.Redact(value.Text), ["structured"] = PublicJson(value.Structured), ["finish_reason"] = value.FinishReason, ["usage"] = UsageValue(value.Usage), ["repair_attempts"] = value.RepairAttempts, ["warnings"] = new JsonArray(value.Warnings.Select(Redaction.Redact).Select(static warning => JsonValue.Create(warning)).ToArray()), ["tool_calls"] = new JsonArray(value.ToolCalls.Select(call => new JsonObject { ["id"] = call.Id, ["name"] = call.Name, ["arguments"] = PublicJson(call.Arguments)?.AsObject() ?? new JsonObject() }).Cast<JsonNode?>().ToArray()), ["manifest"] = ManifestValue(operation, value.Manifest) };
    private static JsonNode? PublicJson(AnyInfer.Json.JsonValue? value) => value is null ? null : RequestPolicyProgram.RedactJson(JsonNode.Parse(AnyInfer.Json.JsonWriter.Write(value)));
    private JsonObject? ManifestValue(int operation, AnyInfer.Manifest.RunManifest? value)
    {
        if (value is null) return null;
        bool sameOperation;
        lock (_captureGate) sameOperation = _operationRequests.TryGetValue(operation, out var requestIds) && requestIds.Contains(value.RequestId);
        return new JsonObject
        {
            ["format"] = value.Format,
            ["complete"] = value.Complete,
            ["request_id_relation"] = sameOperation ? "same_operation" : "absent",
            ["usage"] = UsageFacetValue(value.Usage),
            ["payload"] = value.Payloads is null ? null : new JsonObject
            {
                ["tool_arguments"] = new JsonArray(value.Payloads.ToolArguments.Select(static item => JsonValue.Create(item)).ToArray()),
                ["repair_texts"] = new JsonArray(value.Payloads.RepairTexts.Select(static item => JsonValue.Create(item)).ToArray()),
            },
        };
    }
    private static JsonObject? UsageValue(Usage? value) => value is null ? null : new JsonObject { ["input_tokens"] = value.InputTokens, ["output_tokens"] = value.OutputTokens, ["total_tokens"] = value.TotalTokens, ["cache_read_tokens"] = value.CacheReadTokens, ["cache_write_tokens"] = value.CacheWriteTokens, ["reasoning_tokens"] = value.ReasoningTokens, ["cost_usd"] = value.CostUsd?.ToString(), ["search_units"] = value.SearchUnits, ["server_tool_uses"] = new JsonObject() };
    private static JsonObject UsageFacetValue(AnyInfer.Manifest.UsageFacet value) => new()
    {
        ["input_tokens"] = value.InputTokens,
        ["output_tokens"] = value.OutputTokens,
        ["total_tokens"] = value.TotalTokens,
        ["cache_read_tokens"] = value.CacheReadTokens,
        ["cache_write_tokens"] = value.CacheWriteTokens,
        ["reasoning_tokens"] = value.ReasoningTokens,
        ["cost_usd"] = value.CostUsd,
        ["search_units"] = value.SearchUnits,
    };
    private static JsonObject ErrorValue(AnyInferException value) => new()
    {
        ["runtime_type"] = value.GetType().Name,
        ["provider"] = value.Provider,
        ["phase"] = value.Phase,
        ["retryable"] = value.Retryable,
        ["http_status"] = value.HttpStatus,
        ["retry_after_s"] = value.RetryAfterS,
        ["limit_usd"] = value is SpendLimitException spend ? spend.LimitUsd?.ToString() : null,
        ["spent_usd"] = value is SpendLimitException spent ? spent.SpentUsd?.ToString() : null,
        ["estimated_usd"] = value is SpendLimitException estimate ? estimate.EstimatedUsd?.ToString() : null,
    };
    private JsonObject Operation(int index, string entryPoint, string outcome, JsonObject? result, JsonObject? error, IEnumerable<AttemptRecord> attempts, bool cancelRequested)
    {
        int sendCount;
        bool hasRequestIds;
        lock (_captureGate)
        {
            sendCount = _http.Count(item => HasOperation(item, index)) + _wires.Count(item => HasOperation(item, index));
            hasRequestIds = _operationRequests.TryGetValue(index, out var observedRequestIds) && observedRequestIds.Count != 0;
        }
        return new JsonObject
        {
            ["index"] = index,
            ["entry_point"] = entryPoint,
            ["outcome"] = outcome,
            ["result"] = result,
            ["error"] = error,
            ["attempts"] = new JsonArray(attempts.Select(AttemptValue).Cast<JsonNode?>().ToArray()),
            ["relations"] = new JsonObject
            {
                ["request_id_relation"] = hasRequestIds ? "all_present_same" : "none_observed",
                ["send_count"] = sendCount,
                ["terminal_event"] = outcome == "ok" ? "completed" : outcome == "error" ? "failed" : "none",
                ["cleanup"] = "released",
                ["cancel_requested"] = cancelRequested,
                ["cancelled_before_terminal"] = cancelRequested,
            },
        };
    }
    private static bool HasOperation(JsonObject item, int index) => item["operation_index"] is JsonValue value && value.TryGetValue<int>(out var actual) && actual == index;
    private static JsonObject AttemptValue(AttemptRecord value) => new() { ["target"] = value.Target?.ToString(), ["outcome"] = value.Outcome, ["error"] = value.Error is null ? null : AttemptErrorValue(value.Error) };
    private static JsonObject AttemptErrorValue(AnyInferException value) => new() { ["runtime_type"] = value.GetType().Name, ["provider"] = value.Provider, ["phase"] = value.Phase, ["retryable"] = value.Retryable, ["http_status"] = value.HttpStatus };
    private static JsonObject Resource(string type, int? operation, string? script, string? instance) => new() { ["type"] = type, ["operation_index"] = operation, ["script_id"] = script, ["instance"] = instance };

    private sealed class EventCollector(Action<TelemetryEvent> observe, Action<Exception> recordFailure) : IObserver
    {
        public void OnEvent(TelemetryEvent telemetryEvent)
        {
            try
            {
                observe(telemetryEvent);
            }
            catch (Exception exception)
            {
                recordFailure(exception);
            }
        }
    }
    private sealed class LiteralEstimator(long tokens, long floor) : ITokenEstimator
    {
        public TokenEstimate Estimate(string text) => new(tokens, floor);
    }

    internal sealed class RecordingEstimator(ITokenEstimator inner, List<string> inputs, object? captureGate = null) : ITokenEstimator
    {
        public TokenEstimate Estimate(string text)
        {
            if (captureGate is null) inputs.Add(text);
            else lock (captureGate) inputs.Add(text);
            return inner.Estimate(text);
        }
    }

    private sealed class CapabilityComposition(IReadOnlyDictionary<string, string> bindings)
    {
        private readonly Dictionary<string, ModelCapabilities> _defaults = new(StringComparer.Ordinal);
        private readonly Dictionary<string, Dictionary<string, ModelCapabilities>> _statics = new(StringComparer.Ordinal);
        private readonly Dictionary<string, Dictionary<string, ModelCapabilities>> _overrides = new(StringComparer.Ordinal);
        private readonly HashSet<string> _boundDescriptors = new(StringComparer.Ordinal);

        internal IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>? Overrides => _overrides.Count == 0
            ? null
            : _overrides.ToDictionary(static pair => pair.Key, static pair => (IReadOnlyDictionary<string, ModelCapabilities>)pair.Value, StringComparer.Ordinal);

        internal void Add(string target, Provenance provenance, ModelCapabilities value)
        {
            var parts = target.Split(':', 2);
            if (parts.Length != 2 || string.IsNullOrWhiteSpace(parts[0]) || string.IsNullOrWhiteSpace(parts[1]))
            {
                throw new FormatException("A capability target must be provider:model.");
            }

            var provider = ProviderRegistry.NormalizeProviderId(parts[0]);
            if (!bindings.TryGetValue(provider, out var descriptorId))
            {
                throw new FormatException($"Capability target provider '{parts[0]}' is not a configured public instance.");
            }

            if (provenance == Provenance.Override)
            {
                AddModel(_overrides, provider, parts[1], value);
                return;
            }

            _boundDescriptors.Add(descriptorId);
            if (provenance == Provenance.Default)
            {
                _defaults[descriptorId] = _defaults.TryGetValue(descriptorId, out var existing)
                    ? existing.Overlay(value)
                    : value;
                return;
            }

            AddModel(_statics, descriptorId, parts[1], value);
        }

        internal ModelCapabilities? DefaultFor(string descriptorId) =>
            _defaults.TryGetValue(descriptorId, out var value) ? value : null;

        internal IReadOnlyDictionary<string, ModelCapabilities>? StaticFor(string descriptorId) =>
            _statics.TryGetValue(descriptorId, out var value) ? value : null;

        internal bool HasDescriptorFacts(string descriptorId) =>
            _defaults.ContainsKey(descriptorId) || _statics.ContainsKey(descriptorId);

        internal void EnsureBound(IEnumerable<ProviderDescriptor> descriptors)
        {
            var available = descriptors.Select(static descriptor => descriptor.Id).ToHashSet(StringComparer.Ordinal);
            if (_boundDescriptors.Any(descriptor => !available.Contains(descriptor)))
            {
                throw new FormatException("A declared non-override capability cannot be composed through a public descriptor.");
            }
        }

        private static void AddModel(Dictionary<string, Dictionary<string, ModelCapabilities>> layers, string provider, string model, ModelCapabilities value)
        {
            if (!layers.TryGetValue(provider, out var models))
            {
                layers.Add(provider, models = new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal));
            }

            models[model] = models.TryGetValue(model, out var existing) ? existing.Overlay(value) : value;
        }
    }

    private IReadOnlyDictionary<string, string> ReadDescriptorBindings()
    {
        var source = _source.TryGetProperty("instances", out var instances)
            ? instances
            : _source.TryGetProperty("config", out var config) && config.TryGetProperty("providers", out var providers)
                ? providers
                : throw new FormatException("Capability composition requires configured public instances.");
        var bindings = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var item in source.EnumerateArray())
        {
            var instanceId = ProviderRegistry.NormalizeProviderId(RequestPolicyProgram.RequiredString(item, "id"));
            var adapter = RequestPolicyProgram.RequiredString(item, "adapter");
            var descriptorId = adapter == "recording"
                ? RequestPolicyProgram.RequiredString(_source.GetProperty("descriptor"), "id")
                : "openai-compat";
            if (!bindings.TryAdd(instanceId, descriptorId))
            {
                throw new FormatException("Configured public instance IDs must be unique.");
            }
        }
        return bindings;
    }

    private static ProviderDescriptor CloneDescriptor(
        ProviderDescriptor source,
        ModelCapabilities? defaultCapabilities,
        IReadOnlyDictionary<string, ModelCapabilities>? staticCapabilities) =>
        new(
            source.Id,
            source.DisplayName,
            source.Factory,
            source.Aliases,
            source.Setup,
            source.DefaultBaseUrl,
            source.RequiresBaseUrl,
            source.StructuredOutputProfiles,
            source.MaxRepairAttempts,
            source.Locality,
            defaultCapabilities is null ? source.DefaultCapabilities : source.DefaultCapabilities.Overlay(defaultCapabilities),
            MergeStaticCapabilities(source.StaticCapabilities, staticCapabilities),
            source.Operations,
            source.StaticEmbeddingCapabilities,
            source.StaticRerankCapabilities,
            source.TokenCalibration,
            source.RateLimitHeaders,
            source.CacheMechanism,
            source.CacheMaxMarks,
            source.CacheMinTokens,
            source.GovernsOwnTransport);

    private static IReadOnlyDictionary<string, ModelCapabilities>? MergeStaticCapabilities(
        IReadOnlyDictionary<string, ModelCapabilities>? baseline,
        IReadOnlyDictionary<string, ModelCapabilities>? declared)
    {
        if (declared is null) return baseline;
        if (baseline is null) return declared;

        var merged = baseline.ToDictionary(static pair => pair.Key, static pair => pair.Value, StringComparer.Ordinal);
        foreach (var pair in declared)
        {
            merged[pair.Key] = merged.TryGetValue(pair.Key, out var existing)
                ? existing.Overlay(pair.Value)
                : pair.Value;
        }
        return merged;
    }
}
