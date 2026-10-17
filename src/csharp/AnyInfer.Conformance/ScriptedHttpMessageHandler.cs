using System.Collections.Concurrent;
using System.Net;
using System.Net.Http.Headers;
using System.Runtime.CompilerServices;
using AnyInfer.Json;
using AnyInfer.Providers;

namespace AnyInfer.Conformance;

/// <summary>Provides one input-only HTTP response script and records actual native exchange facts.</summary>
internal sealed class ScriptedHttpMessageHandler : HttpMessageHandler
{
    private readonly IReadOnlyList<ResponseScript> _responses;
    private readonly HashSet<string> _semanticHeaders;
    private readonly ConcurrentQueue<WireRequest> _pendingWires = new();
    private readonly object _exchangeGate = new();
    private readonly List<RecordedHttpExchange> _exchanges = [];
    private int _nextResponse;
    private int _actualRequestCount;
    private int _disposed;

    internal ScriptedHttpMessageHandler(JsonArray responses, IEnumerable<string>? configuredHeaderNames = null)
    {
        ArgumentNullException.ThrowIfNull(responses);
        _responses = responses.Items.Select(ReadResponse).ToArray();
        _semanticHeaders = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "content-type",
            "authorization",
        };
        if (configuredHeaderNames is not null)
        {
            foreach (var name in configuredHeaderNames)
            {
                if (string.IsNullOrWhiteSpace(name))
                {
                    throw new ArgumentException("Configured header names cannot be empty.", nameof(configuredHeaderNames));
                }

                _semanticHeaders.Add(name.ToLowerInvariant());
            }
        }
    }

    internal int ActualRequestCount => Volatile.Read(ref _actualRequestCount);

    internal int RemainingResponses => Math.Max(0, _responses.Count - Volatile.Read(ref _nextResponse));

    internal IReadOnlyList<RecordedHttpExchange> Exchanges
    {
        get
        {
            lock (_exchangeGate)
            {
                return _exchanges.ToArray();
            }
        }
    }

    internal bool IsDisposed => Volatile.Read(ref _disposed) != 0;

    internal void BindPendingWire(WireRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        ThrowIfDisposed();
        _pendingWires.Enqueue(request);
    }

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        ThrowIfDisposed();
        cancellationToken.ThrowIfCancellationRequested();
        _ = Interlocked.Increment(ref _actualRequestCount);
        if (!_pendingWires.TryDequeue(out var wireRequest))
        {
            throw new TransportHarnessException("The HTTP request has no bound native wire request.");
        }

        if (!TryClaimResponse(out var ordinal))
        {
            throw new TransportHarnessException("The scripted HTTP response sequence is exhausted.");
        }

        var semanticHeaders = CaptureSemanticHeaders(request, _semanticHeaders);
        var body = await CaptureBodyAsync(request, cancellationToken).ConfigureAwait(false);
        var stream = ReadStreamMode(body);
        var script = _responses[ordinal];
        var exchange = new RecordedHttpExchange(
            ordinal,
            wireRequest,
            request.Method.Method,
            request.RequestUri?.PathAndQuery ?? throw new TransportHarnessException("The HTTP request has no URI."),
            semanticHeaders,
            body,
            stream,
            script.Status,
            script.Headers,
            script.Chunks);
        lock (_exchangeGate)
        {
            _exchanges.Add(exchange);
        }

        var response = new TrackingHttpResponseMessage(exchange, script.Status)
        {
            Content = new ChunkedHttpContent(exchange),
        };
        try
        {
            ApplyHeaders(response, script.Headers);
        }
        catch (TransportHarnessException)
        {
            response.Dispose();
            throw;
        }

        return response;
    }

    private bool TryClaimResponse(out int ordinal)
    {
        while (true)
        {
            var next = Volatile.Read(ref _nextResponse);
            if (next >= _responses.Count)
            {
                ordinal = -1;
                return false;
            }

            if (Interlocked.CompareExchange(ref _nextResponse, next + 1, next) == next)
            {
                ordinal = next;
                return true;
            }
        }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            Interlocked.Exchange(ref _disposed, 1);
        }

        base.Dispose(disposing);
    }

    private static ResponseScript ReadResponse(JsonValue value)
    {
        if (value is not JsonObject response)
        {
            throw new ArgumentException("HTTP response scripts must be objects.", nameof(value));
        }

        RequireOnly(response, "status", "headers", "byte_chunks");
        if (!response.TryGetValue("status", out var statusValue) || statusValue is not JsonInteger statusInteger ||
            statusInteger.Value < 100 || statusInteger.Value > 599 ||
            !response.TryGetValue("headers", out var headersValue) || headersValue is not JsonObject headers ||
            !response.TryGetValue("byte_chunks", out var chunksValue) || chunksValue is not JsonArray chunks)
        {
            throw new ArgumentException("HTTP response script has invalid fields.", nameof(value));
        }

        var copiedHeaders = ReadHeaders(headers);
        var copiedChunks = new List<ReadOnlyMemory<byte>>();
        foreach (var chunkValue in chunks.Items)
        {
            if (chunkValue is not JsonObject chunk)
            {
                throw new ArgumentException("HTTP response chunks must be objects.", nameof(value));
            }

            RequireOnly(chunk, "bytes");
            if (!chunk.TryGetValue("bytes", out var encodedValue) || encodedValue is not JsonString encoded)
            {
                throw new ArgumentException("HTTP response chunks require base64 bytes.", nameof(value));
            }

            try
            {
                copiedChunks.Add(Convert.FromBase64String(encoded.Value));
            }
            catch (FormatException exception)
            {
                throw new ArgumentException("HTTP response chunks require base64 bytes.", nameof(value), exception);
            }
        }

        return new ResponseScript((int)statusInteger.Value, copiedHeaders, copiedChunks);
    }

    private static void RequireOnly(JsonObject value, params string[] names)
    {
        var allowed = new HashSet<string>(names, StringComparer.Ordinal);
        if (value.Properties.Any(property => !allowed.Contains(property.Name)))
        {
            throw new ArgumentException("HTTP response script contains an unrecognized member.", nameof(value));
        }
    }

    private static JsonObject ReadHeaders(JsonObject value)
    {
        var properties = new List<JsonProperty>();
        foreach (var property in value.Properties)
        {
            if (property.Value is not JsonString text || string.IsNullOrWhiteSpace(property.Name))
            {
                throw new ArgumentException("HTTP response headers must be strings.", nameof(value));
            }

            properties.Add(new JsonProperty(property.Name.ToLowerInvariant(), new JsonString(text.Value)));
        }

        return new JsonObject(properties);
    }

    private static async Task<JsonObject> CaptureBodyAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        if (request.Content is null)
        {
            throw new TransportHarnessException("The HTTP request has no JSON body.");
        }

        var bytes = await request.Content.ReadAsByteArrayAsync(cancellationToken).ConfigureAwait(false);
        return JsonReader.Read(bytes) as JsonObject
            ?? throw new TransportHarnessException("The HTTP request body is not a JSON object.");
    }

    private static bool ReadStreamMode(JsonObject body) =>
        body.TryGetValue("stream", out var stream) && stream is JsonBoolean { Value: true };

    private static JsonObject CaptureSemanticHeaders(HttpRequestMessage request, ISet<string> allowed)
    {
        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        CaptureHeaders(request.Headers, allowed, values);
        if (request.Content is not null)
        {
            CaptureHeaders(request.Content.Headers, allowed, values);
        }

        return new JsonObject(values
            .OrderBy(static item => item.Key, StringComparer.Ordinal)
            .Select(static item => new JsonProperty(item.Key, new JsonString(item.Value))));
    }

    private static void CaptureHeaders(HttpHeaders headers, ISet<string> allowed, IDictionary<string, string> values)
    {
        foreach (var header in headers)
        {
            var name = header.Key.ToLowerInvariant();
            if (allowed.Contains(name))
            {
                values[name] = string.Join(",", header.Value);
            }
        }
    }

    private static void ApplyHeaders(HttpResponseMessage response, JsonObject headers)
    {
        foreach (var property in headers.Properties)
        {
            var value = ((JsonString)property.Value).Value;
            if (string.Equals(property.Name, "content-type", StringComparison.OrdinalIgnoreCase))
            {
                try
                {
                    response.Content.Headers.ContentType = MediaTypeHeaderValue.Parse(value);
                }
                catch (FormatException)
                {
                    throw new TransportHarnessException("The scripted content-type header is invalid.");
                }
            }
            else if (!response.Headers.TryAddWithoutValidation(property.Name, value) &&
                !response.Content.Headers.TryAddWithoutValidation(property.Name, value))
            {
                throw new TransportHarnessException("The scripted response header cannot be placed on a response.");
            }
        }
    }

    private void ThrowIfDisposed()
    {
        if (IsDisposed)
        {
            throw new ObjectDisposedException(nameof(ScriptedHttpMessageHandler));
        }
    }

    private sealed record ResponseScript(int Status, JsonObject Headers, IReadOnlyList<ReadOnlyMemory<byte>> Chunks);
}

/// <summary>Wraps an adapter to retain actual entry and HTTP request identities without altering execution.</summary>
internal sealed class RecordingHttpAdapter : IProviderAdapter
{
    private readonly IProviderAdapter _inner;
    private readonly ScriptedHttpMessageHandler _handler;
    private readonly object _wireGate = new();
    private readonly List<WireRequest> _wireRequests = [];
    private int _callCount;
    private int _disposed;

    internal RecordingHttpAdapter(IProviderAdapter inner, ScriptedHttpMessageHandler handler)
    {
        _inner = inner ?? throw new ArgumentNullException(nameof(inner));
        _handler = handler ?? throw new ArgumentNullException(nameof(handler));
    }

    internal int CallCount => Volatile.Read(ref _callCount);

    internal int RemainingEntries => _handler.RemainingResponses;

    internal IReadOnlyList<WireRequest> WireRequests
    {
        get
        {
            lock (_wireGate)
            {
                return _wireRequests.ToArray();
            }
        }
    }

    public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        ThrowIfDisposed();
        return GenerateCoreAsync(request, cancellationToken);
    }

    public ValueTask DisposeAsync()
    {
        return Interlocked.Exchange(ref _disposed, 1) == 0
            ? _inner.DisposeAsync()
            : ValueTask.CompletedTask;
    }

    private async IAsyncEnumerable<AdapterEvent> GenerateCoreAsync(
        WireRequest request,
        [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        Interlocked.Increment(ref _callCount);
        lock (_wireGate)
        {
            _wireRequests.Add(request);
        }

        _handler.BindPendingWire(request);
        await using var iterator = _inner.GenerateAsync(request, cancellationToken).GetAsyncEnumerator(cancellationToken);
        while (await iterator.MoveNextAsync().ConfigureAwait(false))
        {
            yield return iterator.Current;
        }
    }

    private void ThrowIfDisposed()
    {
        if (Volatile.Read(ref _disposed) != 0)
        {
            throw new ObjectDisposedException(nameof(RecordingHttpAdapter));
        }
    }
}

/// <summary>Signals a malformed, exhausted, or surplus transport fixture script without projecting a provider failure.</summary>
internal sealed class TransportHarnessException : InvalidOperationException
{
    internal TransportHarnessException(string message)
        : base(message)
    {
    }
}

/// <summary>One actual HTTP exchange with owned response-script and native resource observations.</summary>
internal sealed class RecordedHttpExchange
{
    private readonly object _gate = new();
    private readonly List<int> _readByteCounts = [];
    private int _responseDisposed;
    private int _contentDisposed;
    private int _createdStreamCount;
    private int _disposedStreamCount;
    private int _automaticSerializationRequested;

    internal RecordedHttpExchange(
        int ordinal,
        WireRequest boundWireRequest,
        string method,
        string path,
        JsonObject semanticHeaders,
        JsonObject body,
        bool stream,
        int responseStatus,
        JsonObject responseHeaders,
        IReadOnlyList<ReadOnlyMemory<byte>> configuredRawChunks)
    {
        Ordinal = ordinal;
        BoundWireRequest = boundWireRequest ?? throw new ArgumentNullException(nameof(boundWireRequest));
        Method = method ?? throw new ArgumentNullException(nameof(method));
        Path = path ?? throw new ArgumentNullException(nameof(path));
        SemanticHeaders = semanticHeaders ?? throw new ArgumentNullException(nameof(semanticHeaders));
        Body = body ?? throw new ArgumentNullException(nameof(body));
        Stream = stream;
        ResponseStatus = responseStatus;
        ResponseHeaders = responseHeaders ?? throw new ArgumentNullException(nameof(responseHeaders));
        ConfiguredRawChunks = configuredRawChunks ?? throw new ArgumentNullException(nameof(configuredRawChunks));
    }

    internal int Ordinal { get; }
    internal WireRequest BoundWireRequest { get; }
    internal string Method { get; }
    internal string Path { get; }
    internal JsonObject SemanticHeaders { get; }
    internal JsonObject Body { get; }
    internal bool Stream { get; }
    internal int ResponseStatus { get; }
    internal JsonObject ResponseHeaders { get; }
    internal IReadOnlyList<ReadOnlyMemory<byte>> ConfiguredRawChunks { get; }
    internal bool ResponseCreated => true;
    internal bool ContentCreated => true;
    internal bool ResponseDisposed => Volatile.Read(ref _responseDisposed) != 0;
    internal bool ContentDisposed => Volatile.Read(ref _contentDisposed) != 0;
    internal int CreatedStreamCount => Volatile.Read(ref _createdStreamCount);
    internal int DisposedStreamCount => Volatile.Read(ref _disposedStreamCount);
    internal bool AutomaticSerializationRequested => Volatile.Read(ref _automaticSerializationRequested) != 0;

    internal IReadOnlyList<int> ActualReadByteCounts
    {
        get
        {
            lock (_gate)
            {
                return _readByteCounts.ToArray();
            }
        }
    }

    internal void RecordRead(int byteCount)
    {
        lock (_gate)
        {
            _readByteCounts.Add(byteCount);
        }
    }

    internal void RecordResponseDisposed() => Interlocked.Exchange(ref _responseDisposed, 1);

    internal void RecordContentDisposed() => Interlocked.Exchange(ref _contentDisposed, 1);

    internal void RecordStreamCreated() => Interlocked.Increment(ref _createdStreamCount);

    internal void RecordStreamDisposed() => Interlocked.Increment(ref _disposedStreamCount);

    internal void RecordAutomaticSerializationRequested() => Interlocked.Exchange(ref _automaticSerializationRequested, 1);
}

internal sealed class TrackingHttpResponseMessage : HttpResponseMessage
{
    private readonly RecordedHttpExchange _exchange;

    internal TrackingHttpResponseMessage(RecordedHttpExchange exchange, int statusCode)
        : base((HttpStatusCode)statusCode)
    {
        _exchange = exchange;
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _exchange.RecordResponseDisposed();
        }

        base.Dispose(disposing);
    }
}

internal sealed class ChunkedHttpContent : HttpContent
{
    private readonly RecordedHttpExchange _exchange;
    private readonly object _streamGate = new();
    private readonly List<ChunkedReadStream> _streams = [];

    internal ChunkedHttpContent(RecordedHttpExchange exchange)
    {
        _exchange = exchange ?? throw new ArgumentNullException(nameof(exchange));
    }

    protected override bool TryComputeLength(out long length)
    {
        length = 0;
        return false;
    }

    protected override async Task SerializeToStreamAsync(Stream stream, TransportContext? context)
    {
        ArgumentNullException.ThrowIfNull(stream);
        _exchange.RecordAutomaticSerializationRequested();
        foreach (var chunk in _exchange.ConfiguredRawChunks)
        {
            await stream.WriteAsync(chunk).ConfigureAwait(false);
        }
    }

    protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(CreateStream());

    protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.FromResult<Stream>(CreateStream());
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _exchange.RecordContentDisposed();
            ChunkedReadStream[] streams;
            lock (_streamGate)
            {
                streams = _streams.ToArray();
            }

            foreach (var stream in streams)
            {
                stream.Dispose();
            }
        }

        base.Dispose(disposing);
    }

    private ChunkedReadStream CreateStream()
    {
        var stream = new ChunkedReadStream(_exchange);
        lock (_streamGate)
        {
            _streams.Add(stream);
        }

        _exchange.RecordStreamCreated();
        return stream;
    }
}

internal sealed class ChunkedReadStream : Stream
{
    private readonly RecordedHttpExchange _exchange;
    private int _chunkIndex;
    private int _offset;
    private int _disposed;

    internal ChunkedReadStream(RecordedHttpExchange exchange)
    {
        _exchange = exchange ?? throw new ArgumentNullException(nameof(exchange));
    }

    public override bool CanRead => Volatile.Read(ref _disposed) == 0;
    public override bool CanSeek => false;
    public override bool CanWrite => false;
    public override long Length => throw new NotSupportedException();
    public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }

    public override void Flush() { }
    public override Task FlushAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.CompletedTask;
    }

    public override int Read(byte[] buffer, int offset, int count) => ReadCore(buffer.AsSpan(offset, count), CancellationToken.None);

    public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken) =>
        Task.FromResult(ReadCore(buffer.AsSpan(offset, count), cancellationToken));

    public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default) =>
        ValueTask.FromResult(ReadCore(buffer.Span, cancellationToken));

    public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
    public override void SetLength(long value) => throw new NotSupportedException();
    public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

    protected override void Dispose(bool disposing)
    {
        if (disposing && Interlocked.Exchange(ref _disposed, 1) == 0)
        {
            _exchange.RecordStreamDisposed();
        }

        base.Dispose(disposing);
    }

    private int ReadCore(Span<byte> destination, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (Volatile.Read(ref _disposed) != 0)
        {
            throw new ObjectDisposedException(nameof(ChunkedReadStream));
        }

        if (destination.IsEmpty || _chunkIndex >= _exchange.ConfiguredRawChunks.Count)
        {
            _exchange.RecordRead(0);
            return 0;
        }

        var chunk = _exchange.ConfiguredRawChunks[_chunkIndex].Span;
        var count = Math.Min(destination.Length, chunk.Length - _offset);
        chunk.Slice(_offset, count).CopyTo(destination);
        _offset += count;
        if (_offset == chunk.Length)
        {
            _chunkIndex++;
            _offset = 0;
        }

        _exchange.RecordRead(count);
        return count;
    }
}
