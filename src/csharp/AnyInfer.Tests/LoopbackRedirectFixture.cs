using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Text;

namespace AnyInfer.Tests;

/// <summary>Finite owned HTTP loopback retaining every request and joining all handlers.</summary>
internal sealed class LoopbackRedirectFixture : IAsyncDisposable
{
    private readonly TcpListener _listener = new(IPAddress.Loopback, 0);
    private readonly CancellationTokenSource _stopping = new();
    private readonly ConcurrentQueue<LoopbackRedirectResponse> _responses;
    private readonly ConcurrentBag<Task> _handlers = [];
    private readonly ConcurrentQueue<Exception> _failures = [];
    private readonly Task _accepting;

    private LoopbackRedirectFixture(IEnumerable<LoopbackRedirectResponse> responses)
    {
        _responses = new ConcurrentQueue<LoopbackRedirectResponse>(responses);
        _listener.Start();
        OriginUri = new Uri($"http://127.0.0.1:{((IPEndPoint)_listener.LocalEndpoint).Port}/");
        _accepting = AcceptAsync();
    }

    internal Uri OriginUri { get; }
    internal ConcurrentQueue<LoopbackRedirectRequest> Requests { get; } = [];
    internal static LoopbackRedirectFixture Start(params LoopbackRedirectResponse[] responses) => new(responses);

    internal void ReplaceFirstLocation(string location)
    {
        var responses = _responses.ToArray();
        if (responses.Length == 0) throw new InvalidOperationException("No scripted response exists.");
        while (_responses.TryDequeue(out _)) { }
        _responses.Enqueue(responses[0] with { Location = location });
        foreach (var response in responses.Skip(1)) _responses.Enqueue(response);
    }

    private async Task AcceptAsync()
    {
        try
        {
            while (!_stopping.IsCancellationRequested)
            {
                var client = await _listener.AcceptTcpClientAsync(_stopping.Token).ConfigureAwait(false);
                _handlers.Add(HandleAsync(client));
            }
        }
        catch (OperationCanceledException) when (_stopping.IsCancellationRequested) { }
        catch (ObjectDisposedException) when (_stopping.IsCancellationRequested) { }
        catch (Exception exception) { _failures.Enqueue(exception); }
    }

    private async Task HandleAsync(TcpClient client)
    {
        try
        {
            using (client)
            await using (var stream = client.GetStream())
            {
                var head = await ReadHeadersAsync(stream, _stopping.Token).ConfigureAwait(false);
                if (head is null) return;
                var contentLength = head.Headers.TryGetValue("Content-Length", out var rawLength) && int.TryParse(rawLength, out var parsed)
                    ? parsed : 0;
                var body = await ReadExactlyAsync(stream, contentLength, _stopping.Token).ConfigureAwait(false);
                Requests.Enqueue(new LoopbackRedirectRequest(head.RequestLine, head.Headers, body));
                var response = _responses.TryDequeue(out var scripted) ? scripted : new LoopbackRedirectResponse(200, "{}");
                await WriteResponseAsync(stream, response, _stopping.Token).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) when (_stopping.IsCancellationRequested) { }
        catch (Exception exception) { _failures.Enqueue(exception); }
    }

    private static async Task<ParsedHead?> ReadHeadersAsync(NetworkStream stream, CancellationToken token)
    {
        using var bytes = new MemoryStream();
        var single = new byte[1];
        while (bytes.Length <= 64 * 1024)
        {
            if (await stream.ReadAsync(single, token).ConfigureAwait(false) == 0) return null;
            bytes.WriteByte(single[0]);
            if (bytes.Length >= 4 && bytes.GetBuffer().AsSpan((int)bytes.Length - 4, 4).SequenceEqual("\r\n\r\n"u8)) break;
        }
        var text = Encoding.ASCII.GetString(bytes.GetBuffer(), 0, (int)bytes.Length - 4);
        var lines = text.Split("\r\n", StringSplitOptions.None);
        if (lines.Length == 0 || lines[0].Length == 0) return null;
        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var line in lines.Skip(1))
        {
            var separator = line.IndexOf(':');
            if (separator > 0) headers[line[..separator]] = line[(separator + 1)..].Trim();
        }
        return new ParsedHead(lines[0], headers);
    }

    private static async Task<byte[]> ReadExactlyAsync(NetworkStream stream, int count, CancellationToken token)
    {
        if (count == 0) return [];
        var bytes = new byte[count];
        var copied = 0;
        while (copied < count)
        {
            var read = await stream.ReadAsync(bytes.AsMemory(copied, count - copied), token).ConfigureAwait(false);
            if (read == 0) throw new IOException("Loopback request body ended early.");
            copied += read;
        }
        return bytes;
    }

    private static async Task WriteResponseAsync(NetworkStream stream, LoopbackRedirectResponse response, CancellationToken token)
    {
        var body = Encoding.UTF8.GetBytes(response.Body);
        var status = $"HTTP/1.1 {response.StatusCode} {(response.StatusCode == 200 ? "OK" : "Redirect")}";
        var location = response.Location is null ? "" : $"Location: {response.Location}\r\n";
        var cookies = string.Concat((response.SetCookies ?? []).Select(static cookie => $"Set-Cookie: {cookie}\r\n"));
        var responseHeaders = response.Headers ?? new Dictionary<string, string>();
        var headers = string.Concat(responseHeaders.Select(static pair => $"{pair.Key}: {pair.Value}\r\n"));
        var head = $"{status}\r\nConnection: close\r\n{location}{cookies}{headers}Content-Type: {response.ContentType}\r\nContent-Length: {body.Length}\r\n\r\n";
        await stream.WriteAsync(Encoding.ASCII.GetBytes(head), token).ConfigureAwait(false);
        await stream.WriteAsync(body, token).ConfigureAwait(false);
    }

    public async ValueTask DisposeAsync()
    {
        _stopping.Cancel();
        _listener.Stop();
        try { await _accepting.WaitAsync(TimeSpan.FromSeconds(15)).ConfigureAwait(false); } catch (OperationCanceledException) { }
        await Task.WhenAll(_handlers.ToArray()).WaitAsync(TimeSpan.FromSeconds(15)).ConfigureAwait(false);
        _stopping.Dispose();
        if (_failures.TryDequeue(out var failure)) System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
    }

    private sealed record ParsedHead(string RequestLine, Dictionary<string, string> Headers);
}

internal sealed record LoopbackRedirectResponse(
    int StatusCode,
    string Body,
    string? Location = null,
    IReadOnlyList<string>? SetCookies = null,
    IReadOnlyDictionary<string, string>? Headers = null,
    string ContentType = "application/json");
internal sealed record LoopbackRedirectRequest(string RequestLine, IReadOnlyDictionary<string, string> Headers, byte[] Body);
