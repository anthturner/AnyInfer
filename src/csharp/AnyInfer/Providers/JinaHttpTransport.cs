using AnyInfer.Internal;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;

namespace AnyInfer.Providers;

/// <summary>Owns the bounded HTTP mechanics used only by Jina's retrieval dialect.</summary>
internal sealed class JinaHttpTransport : IAsyncDisposable
{
    private const int ErrorLimit = 64 * 1024;
    private readonly HttpClient _client;
    private readonly TimeSpan _configurationTimeout;
    private int _disposed;

    internal JinaHttpTransport(HttpMessageHandler? handler, double configurationTimeoutS, bool handlerOwnedByPool)
    {
        _configurationTimeout = TimeSpan.FromSeconds(configurationTimeoutS);
        var ownedHandler = handler ?? new HttpClientHandler { AllowAutoRedirect = false };
        _client = new HttpClient(ownedHandler, disposeHandler: handler is null || !handlerOwnedByPool) { Timeout = Timeout.InfiniteTimeSpan };
    }

    internal async ValueTask<T> SendAsync<T>(HttpRequestMessage message, string phase, double? timeoutS, int successLimit, CancellationToken cancellationToken, Func<JinaHttpResponse, T> convert, bool readBody = true)
    {
        ThrowIfDisposed();
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(timeoutS is null ? _configurationTimeout : TimeSpan.FromSeconds(timeoutS.Value));
        HttpResponseMessage? response = null;
        Stream? stream = null;
        Exception? primary = null;
        try
        {
            response = await _client.SendAsync(message, HttpCompletionOption.ResponseHeadersRead, timeout.Token).ConfigureAwait(false);
            if (!readBody) return convert(new JinaHttpResponse(response.StatusCode, response.Headers, []));
            stream = await response.Content.ReadAsStreamAsync(timeout.Token).ConfigureAwait(false);
            var isError = (int)response.StatusCode >= 400;
            var body = await ReadBoundedAsync(stream, isError ? ErrorLimit : successLimit, isError, timeout.Token).ConfigureAwait(false);
            return convert(new JinaHttpResponse(response.StatusCode, response.Headers, body));
        }
        catch (OperationCanceledException exception) when (cancellationToken.IsCancellationRequested)
        {
            var original = CancellationIdentityContext.Resolve(cancellationToken);
            primary = new OperationCanceledException(null, exception, original.IsCancellationRequested ? original : cancellationToken);
            throw primary;
        }
        catch (OperationCanceledException exception) when (timeout.IsCancellationRequested)
        {
            primary = ProviderException.Create("The Jina request timed out.", "transport", true, phase, provider: null, nativeInner: exception);
            throw primary;
        }
        catch (HttpRequestException exception)
        {
            primary = IsConnectionFailure(exception)
                ? ProviderException.Create("Cannot connect to the Jina service.", "provider_unavailable", true, phase, provider: null, hint: "check the base URL and network connection", nativeInner: exception)
                : ProviderException.Create("The Jina request could not be completed.", "transport", true, phase, provider: null, nativeInner: exception);
            throw primary;
        }
        catch (IOException exception)
        {
            primary = ProviderException.Create("The Jina response could not be read.", "transport", true, phase, provider: null, nativeInner: exception);
            throw primary;
        }
        catch (Exception exception) { primary = exception; throw; }
        finally
        {
            Exception? cleanup = null;
            try { if (stream is not null) await stream.DisposeAsync().ConfigureAwait(false); }
            catch (Exception exception) { if (primary is null) cleanup = exception; }
            try { response?.Dispose(); }
            catch (Exception exception) { if (primary is null && cleanup is null) cleanup = exception; }
            if (primary is null && cleanup is not null) throw cleanup;
        }
    }

    private static bool IsConnectionFailure(HttpRequestException exception)
    {
        if (exception.HttpRequestError is HttpRequestError.NameResolutionError or HttpRequestError.ConnectionError or HttpRequestError.SecureConnectionError) return true;
        for (Exception? current = exception; current is not null; current = current.InnerException) if (current is SocketException) return true;
        return false;
    }

    private static async ValueTask<byte[]> ReadBoundedAsync(Stream stream, int limit, bool truncateAtLimit, CancellationToken cancellationToken)
    {
        var buffer = new byte[4096];
        using var body = new MemoryStream();
        while (true)
        {
            var count = await stream.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
            if (count == 0) return body.ToArray();
            if (body.Length + count > limit)
            {
                if (!truncateAtLimit) throw ProviderException.Create("The provider response exceeded the configured size limit.", "provider", false, "validate");
                var remaining = checked((int)(limit - body.Length));
                if (remaining > 0) body.Write(buffer, 0, remaining);
                return body.ToArray();
            }
            body.Write(buffer, 0, count);
        }
    }

    public ValueTask DisposeAsync() { if (Interlocked.Exchange(ref _disposed, 1) == 0) _client.Dispose(); return ValueTask.CompletedTask; }
    private void ThrowIfDisposed() { if (Volatile.Read(ref _disposed) != 0) throw new ObjectDisposedException(nameof(JinaHttpTransport)); }
}

internal sealed record JinaHttpResponse(HttpStatusCode StatusCode, HttpResponseHeaders Headers, byte[] Body);
