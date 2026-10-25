using System.Net;
using System.Text;
using System.Text.Json;

namespace AnyInfer.Examples.Cases;

/// <summary>One HTTP request a cookbook case's scripted handler received.</summary>
/// <param name="Method">The HTTP method.</param>
/// <param name="Uri">The absolute request URI.</param>
/// <param name="Authorization">The rendered Authorization header, or <see langword="null"/>.</param>
/// <param name="Body">The request body text.</param>
internal sealed record CookbookRequest(HttpMethod Method, Uri Uri, string? Authorization, string Body)
{
    /// <summary>Parses the request body as JSON.</summary>
    internal JsonElement Json() => JsonDocument.Parse(Body).RootElement.Clone();
}

/// <summary>An offline HTTP handler that answers each request from an ordered script.</summary>
/// <remarks>
/// It records every request, fails when the client sends more requests than were scripted, and
/// counts disposals so cases can assert that the client released the transport it was given.
/// </remarks>
internal sealed class CookbookScriptedHandler(params Func<CookbookRequest, CancellationToken, Task<HttpResponseMessage>>[] script)
    : HttpMessageHandler
{
    private readonly Queue<Func<CookbookRequest, CancellationToken, Task<HttpResponseMessage>>> _script = new(script);

    internal List<CookbookRequest> Requests { get; } = [];

    internal int DisposeCount { get; private set; }

    internal int Remaining => _script.Count;

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var body = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellationToken);
        var recorded = new CookbookRequest(request.Method, request.RequestUri!, request.Headers.Authorization?.ToString(), body);
        Requests.Add(recorded);
        if (!_script.TryDequeue(out var next))
        {
            throw new InvalidOperationException($"Unscripted request to {request.RequestUri}.");
        }

        return await next(recorded, cancellationToken);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) DisposeCount++;
        base.Dispose(disposing);
    }
}

/// <summary>Scripted OpenAI-compatible, TEI, Voyage and Jina responses for cookbook cases.</summary>
internal static class CookbookReplies
{
    internal static Func<CookbookRequest, CancellationToken, Task<HttpResponseMessage>> Chat(
        string content, long promptTokens = 10, long completionTokens = 5) =>
        (_, _) => Task.FromResult(Json(ChatBody(content, promptTokens, completionTokens)));

    internal static Func<CookbookRequest, CancellationToken, Task<HttpResponseMessage>> Status(
        HttpStatusCode status, string error = "offline failure") =>
        (_, _) => Task.FromResult(new HttpResponseMessage(status)
        {
            Content = new StringContent(JsonSerializer.Serialize(new { error = new { message = error } }), Encoding.UTF8, "application/json"),
        });

    internal static Func<CookbookRequest, CancellationToken, Task<HttpResponseMessage>> ToolCalls(
        params (string Id, string Name, string Arguments)[] calls) =>
        (_, _) => Task.FromResult(Json(JsonSerializer.Serialize(new
        {
            choices = new[]
            {
                new
                {
                    message = new
                    {
                        tool_calls = calls.Select(static call => new
                        {
                            id = call.Id,
                            type = "function",
                            function = new { name = call.Name, arguments = call.Arguments },
                        }).ToArray(),
                    },
                    finish_reason = "tool_calls",
                },
            },
            usage = new { prompt_tokens = 20, completion_tokens = 8, total_tokens = 28 },
        })));

    internal static Func<CookbookRequest, CancellationToken, Task<HttpResponseMessage>> Sse(params string[] records) =>
        (_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(string.Concat(records.Select(static record => $"data: {record}\n\n")), Encoding.UTF8, "text/event-stream"),
        });

    internal static string Delta(string text) =>
        JsonSerializer.Serialize(new { choices = new[] { new { delta = new { content = text } } } });

    internal static string Finish(long promptTokens = 10, long completionTokens = 5) =>
        JsonSerializer.Serialize(new
        {
            choices = new[] { new { delta = new { }, finish_reason = "stop" } },
            usage = new { prompt_tokens = promptTokens, completion_tokens = completionTokens, total_tokens = promptTokens + completionTokens },
        });

    internal static string ChatBody(string content, long promptTokens, long completionTokens) =>
        JsonSerializer.Serialize(new
        {
            choices = new[] { new { message = new { content }, finish_reason = "stop" } },
            usage = new { prompt_tokens = promptTokens, completion_tokens = completionTokens, total_tokens = promptTokens + completionTokens },
        });

    internal static HttpResponseMessage Json(string body) => new(HttpStatusCode.OK)
    {
        Content = new StringContent(body, Encoding.UTF8, "application/json"),
    };
}

/// <summary>A response body that is delivered in scripted steps: bytes, a read failure, or a stall.</summary>
/// <remarks>
/// A stall waits until the reader's cancellation token fires and records that it did, so a case can
/// assert that caller cancellation reached the provider call that was in progress.
/// </remarks>
internal sealed class CookbookBody : Stream
{
    private readonly Queue<object> _steps;
    private byte[] _pending = [];
    private int _offset;

    private CookbookBody(IEnumerable<object> steps) => _steps = new Queue<object>(steps);

    internal static object Stall { get; } = new();

    internal static object Break { get; } = new();

    internal bool StallCancelled { get; private set; }

    internal bool Disposed { get; private set; }

    /// <summary>Builds an SSE body whose string steps are <c>data:</c> records.</summary>
    internal static (CookbookBody Body, Func<CookbookRequest, CancellationToken, Task<HttpResponseMessage>> Reply) Sse(params object[] steps)
    {
        var body = new CookbookBody(steps.Select(static step => step is string record ? $"data: {record}\n\n" : step));
        return (body, (_, _) =>
        {
            var content = new StreamContent(body);
            content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("text/event-stream");
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = content });
        });
    }

    public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
    {
        while (_offset >= _pending.Length)
        {
            if (!_steps.TryDequeue(out var step)) return 0;
            if (ReferenceEquals(step, Stall))
            {
                try
                {
                    await Task.Delay(Timeout.Infinite, cancellationToken);
                }
                catch (OperationCanceledException)
                {
                    StallCancelled = true;
                    throw;
                }
            }
            else if (ReferenceEquals(step, Break))
            {
                throw new IOException("The offline connection was reset mid-body.");
            }
            else
            {
                _pending = Encoding.UTF8.GetBytes((string)step);
                _offset = 0;
            }
        }

        var count = Math.Min(buffer.Length, _pending.Length - _offset);
        _pending.AsMemory(_offset, count).CopyTo(buffer);
        _offset += count;
        return count;
    }

    public override int Read(byte[] buffer, int offset, int count) =>
        ReadAsync(buffer.AsMemory(offset, count)).AsTask().GetAwaiter().GetResult();

    public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken) =>
        ReadAsync(buffer.AsMemory(offset, count), cancellationToken).AsTask();

    protected override void Dispose(bool disposing)
    {
        Disposed = true;
        base.Dispose(disposing);
    }

    public override bool CanRead => true;
    public override bool CanSeek => false;
    public override bool CanWrite => false;
    public override long Length => throw new NotSupportedException();
    public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
    public override void Flush() { }
    public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
    public override void SetLength(long value) => throw new NotSupportedException();
    public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
}

/// <summary>Sets environment variables for one case and restores their previous values.</summary>
internal sealed class CookbookEnvironment : IDisposable
{
    private readonly Dictionary<string, string?> _previous = new(StringComparer.Ordinal);

    internal CookbookEnvironment(params (string Name, string? Value)[] values)
    {
        foreach (var (name, value) in values)
        {
            _previous[name] = Environment.GetEnvironmentVariable(name);
            Environment.SetEnvironmentVariable(name, value);
        }
    }

    public void Dispose()
    {
        foreach (var (name, value) in _previous)
        {
            Environment.SetEnvironmentVariable(name, value);
        }
    }
}
