using AnyInfer.Internal;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;

namespace AnyInfer.Providers;

/// <summary>Owns the bounded HTTP mechanics used only by Voyage's retrieval dialect.</summary>
internal sealed class VoyageHttpTransport : IAsyncDisposable
{
    private const int ErrorLimit = 64 * 1024;
    private readonly HttpClient _client;
    private readonly ProviderHttpRedirects _redirects;
    private readonly TimeSpan _configurationTimeout;
    private int _disposed;

    internal VoyageHttpTransport(ProviderConfig config, CancellationToken cancellationToken)
        : this(
            config.Transport ?? ConnectionHandlerFactory.CreateOwned(config, cancellationToken),
            config.TimeoutS,
            config.Transport is not null && config.TransportOwnedByPool)
    {
    }

    internal VoyageHttpTransport(HttpMessageHandler? handler, double configurationTimeoutS, bool handlerOwnedByPool)
    {
        _configurationTimeout = TimeSpan.FromSeconds(configurationTimeoutS);
        var ownedHandler = handler ?? ConnectionHandlerFactory.CreateDefault(CancellationToken.None);
        _client = new HttpClient(ownedHandler, disposeHandler: handler is null || !handlerOwnedByPool)
        {
            Timeout = Timeout.InfiniteTimeSpan,
        };
        _redirects = new ProviderHttpRedirects(_client);
    }

    internal async ValueTask<T> SendAsync<T>(
        Uri initialUri,
        HttpMethod initialMethod,
        Func<RedirectRequestContext, HttpRequestMessage> createRequest,
        string phase,
        double? timeoutS,
        int successLimit,
        CancellationToken cancellationToken,
        Func<VoyageHttpResponse, T> convert,
        bool readBody = true)
    {
        ThrowIfDisposed();
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(timeoutS is null ? _configurationTimeout : TimeSpan.FromSeconds(timeoutS.Value));
        RedirectExchange? exchange = null;
        HttpResponseMessage? response = null;
        Stream? stream = null;
        Exception? primary = null;
        try
        {
            exchange = await _redirects.SendAsync(initialUri, initialMethod, createRequest, phase, timeout.Token).ConfigureAwait(false);
            response = exchange.Response;
            if (!readBody) return convert(new VoyageHttpResponse(response.StatusCode, response.Headers, []));
            stream = await response.Content.ReadAsStreamAsync(timeout.Token).ConfigureAwait(false);
            var isError = (int)response.StatusCode >= 400;
            var limit = isError ? ErrorLimit : successLimit;
            var body = await ReadBoundedAsync(stream, limit, isError, timeout.Token).ConfigureAwait(false);
            return convert(new VoyageHttpResponse(response.StatusCode, response.Headers, body));
        }
        catch (OperationCanceledException exception) when (cancellationToken.IsCancellationRequested)
        {
            var original = CancellationIdentityContext.Resolve(cancellationToken);
            primary = new OperationCanceledException(null, exception, original.IsCancellationRequested ? original : cancellationToken);
            throw primary;
        }
        catch (OperationCanceledException exception) when (timeout.IsCancellationRequested)
        {
            primary = ProviderException.Create("The Voyage request timed out.", "transport", true, phase, provider: null, nativeInner: exception);
            throw primary;
        }
        catch (HttpRequestException exception)
        {
            primary = IsConnectionFailure(exception)
                ? ProviderException.Create("Cannot connect to the Voyage service.", "provider_unavailable", true, phase, provider: null, hint: "check the base URL and network connection", nativeInner: exception)
                : ProviderException.Create("The Voyage request could not be completed.", "transport", true, phase, provider: null, nativeInner: exception);
            throw primary;
        }
        catch (IOException exception)
        {
            primary = ProviderException.Create("The Voyage response could not be read.", "transport", true, phase, provider: null, nativeInner: exception);
            throw primary;
        }
        catch (Exception exception)
        {
            primary = exception;
            throw;
        }
        finally
        {
            Exception? cleanup = null;
            try { if (stream is not null) await stream.DisposeAsync().ConfigureAwait(false); }
            catch (Exception exception) { if (primary is null) cleanup = exception; }
            try { exchange?.Dispose(); }
            catch (Exception exception) { if (primary is null && cleanup is null) cleanup = exception; }
            if (primary is null && cleanup is not null) throw cleanup;
        }
    }

    private static bool IsConnectionFailure(HttpRequestException exception)
    {
        if (exception.HttpRequestError is HttpRequestError.NameResolutionError or HttpRequestError.ConnectionError or HttpRequestError.SecureConnectionError) return true;
        for (Exception? current = exception; current is not null; current = current.InnerException)
        {
            if (current is SocketException) return true;
        }

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

    public ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) == 0) _client.Dispose();
        return ValueTask.CompletedTask;
    }

    private void ThrowIfDisposed()
    {
        if (Volatile.Read(ref _disposed) != 0) throw new ObjectDisposedException(nameof(VoyageHttpTransport));
    }
}

internal sealed record VoyageHttpResponse(HttpStatusCode StatusCode, HttpResponseHeaders Headers, byte[] Body);
