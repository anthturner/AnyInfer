using AnyInfer;
using AnyInfer.Providers;
using System.Net;
using System.Runtime.ExceptionServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

internal sealed class ScriptQueue : IDisposable
{
    private readonly Queue<JsonElement> _scripts;
    private readonly List<JsonObject> _resources;
    private readonly List<JsonObject> _http;
    private readonly List<BodyGate> _gates = [];
    private readonly List<ScriptedHandler> _handlers = [];
    private readonly Action<int?, int> _onAdmission;
    private readonly object _scriptGate = new();
    private readonly object _captureGate;
    private readonly AsyncLocal<int?> _currentOperation = new();
    private int _ordinal;

    private ScriptQueue(
        IEnumerable<JsonElement> scripts,
        List<JsonObject> resources,
        List<JsonObject> http,
        Action<int?, int> onAdmission,
        object? captureGate)
    {
        _scripts = new Queue<JsonElement>(scripts);
        _resources = resources;
        _http = http;
        _onAdmission = onAdmission;
        _captureGate = captureGate ?? new object();
        HasDeclaredGate = _scripts.Any(static script => script.TryGetProperty("gate", out _));
    }

    internal HttpMessageHandler CreateHandler(string instanceId)
    {
        lock (_scriptGate)
        {
            var handler = new ScriptedHandler(this, instanceId);
            _handlers.Add(handler);
            return handler;
        }
    }
    internal int Remaining { get { lock (_scriptGate) return _scripts.Count; } }
    internal bool HasDeclaredGate { get; }
    internal int? CurrentOperation { get => _currentOperation.Value; set => _currentOperation.Value = value; }
    internal string? LatestGateName { get { lock (_scriptGate) return _gates.LastOrDefault()?.Name; } }

    internal static ScriptQueue Create(
        JsonElement scripts,
        List<JsonObject> resources,
        List<JsonObject> http,
        Action<int?, int> onAdmission,
        object? captureGate = null) =>
        new(scripts.EnumerateArray().ToArray(), resources, http, onAdmission, captureGate);

    internal ScriptClaim Take(string expectedTransport)
    {
        lock (_scriptGate)
        {
            if (!_scripts.TryDequeue(out var script)) throw new InvalidOperationException("A fixture script was not available.");
            if (RequestPolicyProgram.RequiredString(script, "transport") != expectedTransport) throw new InvalidOperationException("The fixture transport did not match the public adapter.");
            return new ScriptClaim(
                script,
                RequestPolicyProgram.RequiredString(script, "id"),
                RequestPolicyProgram.RequiredString(script, "instance"));
        }
    }

    internal void ObserveAdmission() => _onAdmission(CurrentOperation, Interlocked.Increment(ref _ordinal));

    internal void RequireConsumed()
    {
        lock (_scriptGate)
        {
            if (_scripts.Count != 0) throw new InvalidOperationException("The public operation did not consume every declared fixture script.");
        }
    }

    internal Task WaitForGateAsync()
    {
        lock (_scriptGate)
        {
            var gate = _gates.LastOrDefault() ?? throw new InvalidOperationException("The procedure waited for an undeclared response-body gate.");
            return gate.Ready;
        }
    }

    internal Task WaitForReadCancellationAsync()
    {
        lock (_scriptGate)
        {
            var gate = _gates.LastOrDefault() ?? throw new InvalidOperationException("The procedure waited for cancellation without a declared response-body gate.");
            return gate.CancellationObserved;
        }
    }

    internal RawReadCancellationOracle CreateRawReadCancellationOracle(Task pending, CancellationToken declaredCallerToken)
    {
        lock (_scriptGate)
        {
            var gate = _gates.LastOrDefault() ?? throw new InvalidOperationException("The procedure observed cancellation without a declared response-body gate.");
            return new RawReadCancellationOracle(
                pending,
                declaredCallerToken,
                gate.ObservedReadToken,
                gate.CancellationObserved.IsCompleted);
        }
    }

    internal void ReleaseGates()
    {
        BodyGate[] gates;
        lock (_scriptGate)
        {
            gates = _gates.ToArray();
        }
        foreach (var gate in gates)
        {
            gate.Release();
        }
    }

    internal void AddHttp(JsonObject value)
    {
        lock (_captureGate) _http.Add(value);
    }

    internal void AddResource(JsonObject value)
    {
        lock (_captureGate) _resources.Add(value);
    }

    internal void AddWire(List<JsonObject> wires, JsonObject value)
    {
        lock (_captureGate) wires.Add(value);
    }

    internal sealed record ScriptClaim(JsonElement Value, string Id, string Instance);

    internal HttpResponseMessage Send(HttpRequestMessage request, string expectedInstance)
    {
        var operation = CurrentOperation;
        var claim = Take("http");
        var script = claim.Value;
        var scriptId = claim.Id;
        var instance = claim.Instance;
        if (!string.Equals(instance, expectedInstance, StringComparison.Ordinal))
        {
            throw new InvalidOperationException("The consumed HTTP fixture script did not match the configured handler instance.");
        }
        var body = script.GetProperty("body");
        var status = script.GetProperty("status").GetInt32();
        var requestJson = request.Content is null
            ? new JsonObject()
            : RequestPolicyProgram.RedactJson(JsonNode.Parse(request.Content.ReadAsStringAsync().GetAwaiter().GetResult()))?.AsObject() ?? new JsonObject();
        var requestHeaderEntries = request.Headers.ToList();
        if (request.Content is not null)
        {
            requestHeaderEntries.AddRange(request.Content.Headers);
        }

        var requestHeaders = requestHeaderEntries
            .ToDictionary(
                static header => header.Key.ToLowerInvariant(),
                static header => string.Join(", ", header.Value),
                StringComparer.Ordinal);
        var headersValue = new JsonObject();
        foreach (var (name, value) in requestHeaders)
        {
            headersValue[name] = Redaction.Redact(value);
        }
        AddHttp(new JsonObject
        {
            ["operation_index"] = operation,
            ["script_id"] = scriptId,
            ["instance"] = instance,
            ["method"] = request.Method.Method,
            ["path"] = request.RequestUri?.AbsolutePath ?? string.Empty,
            ["query"] = request.RequestUri?.Query.TrimStart('?') ?? string.Empty,
            ["headers"] = headersValue,
            ["request_json"] = requestJson,
            ["status"] = status,
        });
        ObserveAdmission();
        AddResource(Resource("handler_entry", operation, scriptId, instance));
        var bytes = body.GetProperty("kind").GetString() switch
        {
            "json" => Encoding.UTF8.GetBytes(body.GetProperty("value").GetRawText()),
            "raw_utf8" or "sse" => Encoding.UTF8.GetBytes(string.Concat(body.GetProperty("chunks").EnumerateArray().Select(static value => value.GetString()))),
            _ => throw new FormatException("Unknown fixture body kind."),
        };
        BodyGate? gate = null;
        if (script.TryGetProperty("gate", out var declaredGate))
        {
            var gateName = RequestPolicyProgram.RequiredString(declaredGate, "name");
            gate = new BodyGate(
                gateName,
                RequestPolicyProgram.RequiredString(declaredGate, "readiness"),
                () => AddResource(Resource("body_ready", operation, scriptId, instance)),
                () => AddResource(Resource("body_released", operation, scriptId, instance)));
            lock (_scriptGate) _gates.Add(gate);
        }

        var content = new TrackedContent(bytes, gate, () => AddResource(Resource("body_closed", operation, scriptId, instance)));
        var contentType = body.TryGetProperty("content_type", out var declared) ? declared.GetString()! : "application/json";
        content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(contentType);
        foreach (var header in script.GetProperty("headers").EnumerateArray()) content.Headers.TryAddWithoutValidation(RequestPolicyProgram.RequiredString(header, "name"), RequestPolicyProgram.RequiredString(header, "value"));
        return new HttpResponseMessage((HttpStatusCode)status) { Content = content, RequestMessage = request };
    }

    public void Dispose()
    {
        ScriptedHandler[] handlers;
        lock (_scriptGate) handlers = _handlers.ToArray();
        foreach (var handler in handlers) handler.Dispose();
    }

    private static JsonObject Resource(string type, int? operation, string? scriptId, string? instance) => new()
    {
        ["type"] = type,
        ["operation_index"] = operation,
        ["script_id"] = scriptId,
        ["instance"] = instance,
    };

    private void RecordHandlerClosed(string instanceId) => AddResource(new JsonObject
    {
        ["type"] = "handler_closed",
        ["operation_index"] = null,
        ["script_id"] = null,
        ["instance"] = instanceId,
    });

    private sealed class ScriptedHandler(ScriptQueue owner, string instanceId) : HttpMessageHandler
    {
        private int _closed;

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            Task.FromResult(owner.Send(request, instanceId));

        protected override void Dispose(bool disposing)
        {
            try { base.Dispose(disposing); }
            finally
            {
                if (disposing && Interlocked.Exchange(ref _closed, 1) == 0) owner.RecordHandlerClosed(instanceId);
            }
        }
    }

    private sealed class BodyGate(string name, string readiness, Action ready, Action released)
    {
        private readonly TaskCompletionSource _ready = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly TaskCompletionSource _cancellationObserved = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private CancellationToken? _observedReadToken;
        private readonly TaskCompletionSource _release = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private int _started;
        private int _released;

        internal Task Ready => _ready.Task;
        internal Task CancellationObserved => _cancellationObserved.Task;
        internal CancellationToken? ObservedReadToken => _observedReadToken;
        internal string Name => name;

        internal async Task WaitAsync(int readNumber, CancellationToken cancellationToken)
        {
            if (readiness == "second_read_started" && readNumber < 2)
            {
                return;
            }

            if (Interlocked.Exchange(ref _started, 1) == 0)
            {
                ready();
                _ready.TrySetResult();
            }

            try
            {
                await _release.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException exception) when (cancellationToken.IsCancellationRequested)
            {
                _observedReadToken = cancellationToken;
                _cancellationObserved.TrySetResult();
                await _release.Task.ConfigureAwait(false);
                ExceptionDispatchInfo.Capture(exception).Throw();
                throw;
            }
        }

        internal void Release()
        {
            if (Interlocked.Exchange(ref _released, 1) == 0)
            {
                if (Volatile.Read(ref _started) != 0)
                {
                    released();
                }

                _release.TrySetResult();
            }
        }
    }

    private sealed class TrackedContent(byte[] bytes, BodyGate? gate, Action closed) : HttpContent
    {
        private int _closed;

        protected override bool TryComputeLength(out long length)
        {
            length = bytes.Length;
            return true;
        }

        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) =>
            SerializeCoreAsync(stream, CancellationToken.None);

        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context, CancellationToken cancellationToken) =>
            SerializeCoreAsync(stream, cancellationToken);

        private async Task SerializeCoreAsync(Stream stream, CancellationToken cancellationToken)
        {
            if (gate is not null)
            {
                await gate.WaitAsync(readNumber: 1, cancellationToken).ConfigureAwait(false);
            }

            await stream.WriteAsync(bytes, cancellationToken).ConfigureAwait(false);
        }

        protected override Task<Stream> CreateContentReadStreamAsync() =>
            Task.FromResult<Stream>(new GateReadStream(bytes, gate, CancellationToken.None));

        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) =>
            Task.FromResult<Stream>(new GateReadStream(bytes, gate, cancellationToken));

        protected override void Dispose(bool disposing)
        {
            try { base.Dispose(disposing); }
            finally
            {
                if (disposing && Interlocked.Exchange(ref _closed, 1) == 0) closed();
            }
        }
    }

    private sealed class GateReadStream : Stream
    {
        private readonly MemoryStream _inner;
        private readonly BodyGate? _gate;
        private readonly CancellationToken _cancellationToken;
        private int _reads;

        internal GateReadStream(byte[] bytes, BodyGate? gate, CancellationToken cancellationToken)
        {
            _inner = new MemoryStream(bytes, writable: false);
            _gate = gate;
            _cancellationToken = cancellationToken;
        }

        public override bool CanRead => _inner.CanRead;
        public override bool CanSeek => _inner.CanSeek;
        public override bool CanWrite => false;
        public override long Length => _inner.Length;
        public override long Position { get => _inner.Position; set => _inner.Position = value; }
        public override void Flush() => _inner.Flush();
        public override Task FlushAsync(CancellationToken cancellationToken) => _inner.FlushAsync(cancellationToken);

        public override int Read(byte[] buffer, int offset, int count)
        {
            WaitForReadAsync(CancellationToken.None).GetAwaiter().GetResult();
            return _inner.Read(buffer, offset, count);
        }

        public override int Read(Span<byte> buffer)
        {
            WaitForReadAsync(CancellationToken.None).GetAwaiter().GetResult();
            return _inner.Read(buffer);
        }

        public override async Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken)
        {
            await WaitForReadAsync(cancellationToken).ConfigureAwait(false);
            return await _inner.ReadAsync(buffer, offset, count, cancellationToken).ConfigureAwait(false);
        }

        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            await WaitForReadAsync(cancellationToken).ConfigureAwait(false);
            return await _inner.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
        }

        public override long Seek(long offset, SeekOrigin origin) => _inner.Seek(offset, origin);
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

        private async Task WaitForReadAsync(CancellationToken cancellationToken)
        {
            if (_gate is null)
            {
                return;
            }

            var effective = cancellationToken.CanBeCanceled ? cancellationToken : _cancellationToken;
            await _gate.WaitAsync(Interlocked.Increment(ref _reads), effective).ConfigureAwait(false);
        }

        protected override void Dispose(bool disposing)
        {
            try { base.Dispose(disposing); }
            finally
            {
                if (disposing) _inner.Dispose();
            }
        }
    }
}

internal sealed class RecordingAdapter : IProviderAdapter
{
    private readonly ScriptQueue _scripts;
    private readonly List<JsonObject> _wires;
    private readonly string _providerId;
    private readonly string _descriptorId;
    private int _closed;

    internal RecordingAdapter(ScriptQueue scripts, List<JsonObject> wires, string providerId, string descriptorId)
    {
        _scripts = scripts;
        _wires = wires;
        _providerId = providerId;
        _descriptorId = descriptorId;
    }

    public async IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var claim = _scripts.Take("recording");
        var script = claim.Value;
        if (!string.Equals(claim.Instance, _providerId, StringComparison.Ordinal))
        {
            throw new InvalidOperationException("The consumed recording fixture script did not match the configured adapter instance.");
        }
        var operation = _scripts.CurrentOperation;
        _scripts.AddWire(_wires, new JsonObject
        {
            ["operation_index"] = operation,
            ["script_id"] = claim.Id,
            ["instance"] = claim.Instance,
            ["target"] = $"{_providerId}:{request.Model}",
            ["descriptor"] = _descriptorId,
            ["messages"] = new JsonArray(request.Messages.Select(MessageValue).Cast<JsonNode?>().ToArray()),
            ["tools"] = new JsonArray(request.Tools.Select(ToolValue).Cast<JsonNode?>().ToArray()),
            ["tool_choice"] = request.ToolChoice,
            ["cache_marks"] = new JsonArray(request.CacheMarks.Select(static mark => JsonValue.Create(mark)).ToArray()),
        });
        _scripts.ObserveAdmission();
        foreach (var item in script.GetProperty("events").EnumerateArray())
        {
            cancellationToken.ThrowIfCancellationRequested();
            switch (RequestPolicyProgram.RequiredString(item, "type"))
            {
                case "text_delta": yield return new AdapterTextDelta(RequestPolicyProgram.RequiredString(item, "text")); break;
                case "tool_call_delta": yield return new AdapterToolCallDelta(item.GetProperty("index").GetInt32(), item.GetProperty("call_id").ValueKind == JsonValueKind.Null ? null : item.GetProperty("call_id").GetString(), item.GetProperty("name").ValueKind == JsonValueKind.Null ? null : item.GetProperty("name").GetString(), RequestPolicyProgram.RequiredStringAllowEmpty(item, "arguments_fragment")); break;
                case "final": yield return new AdapterFinal(RequestPolicyProgram.RequiredString(item, "finish_reason"), ReadUsage(item.GetProperty("usage"))); break;
                default: throw new FormatException("Unknown recording event.");
            }
            await Task.Yield();
        }
    }

    public ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _closed, 1) == 0)
        {
            _scripts.AddResource(new JsonObject { ["type"] = "adapter_closed", ["operation_index"] = null, ["script_id"] = null, ["instance"] = _providerId });
        }
        return ValueTask.CompletedTask;
    }

    private static Usage ReadUsage(JsonElement raw) => new(raw.GetProperty("input_tokens").ValueKind == JsonValueKind.Null ? null : raw.GetProperty("input_tokens").GetInt64(), raw.GetProperty("output_tokens").ValueKind == JsonValueKind.Null ? null : raw.GetProperty("output_tokens").GetInt64(), raw.TryGetProperty("total_tokens", out var total) && total.ValueKind != JsonValueKind.Null ? total.GetInt64() : null);

    private static JsonObject MessageValue(Message message) => new()
    {
        ["role"] = message.Role,
        ["content"] = Redaction.Redact(message.Content.OfType<ToolResult>().FirstOrDefault()?.Content ?? message.Content.OfType<Text>().FirstOrDefault()?.Value),
    };

    private static JsonObject ToolValue(ToolSpec tool) => new()
    {
        ["name"] = tool.Name,
        ["description"] = tool.Description,
        ["parameters"] = RequestPolicyProgram.RedactJson(JsonNode.Parse(AnyInfer.Json.JsonWriter.Write(tool.Parameters)))?.AsObject() ?? new JsonObject(),
    };
}
