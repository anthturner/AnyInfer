using System.Net;
using System.Net.Http.Headers;
using System.Runtime.ExceptionServices;
using AnyInfer.Internal;

namespace AnyInfer.Routing;

/// <summary>Applies one instance limiter to HTTP exchanges without exposing it to adapters.</summary>
internal sealed class GovernedHttpMessageHandler : HttpMessageHandler
{
    private readonly HttpMessageHandler _inner;
    private readonly HttpMessageInvoker _invoker;
    private readonly RateLimiter _limiter;
    private readonly bool _ownsInner;
    private int _disposed;

    internal GovernedHttpMessageHandler(HttpMessageHandler inner, RateLimiter limiter, bool ownsInner)
    {
        _inner = inner ?? throw new ArgumentNullException(nameof(inner));
        _limiter = limiter ?? throw new ArgumentNullException(nameof(limiter));
        _ownsInner = ownsInner;
        _invoker = new HttpMessageInvoker(inner, disposeHandler: false);
    }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        RateLimitLease? lease = null;
        HttpResponseMessage? response = null;
        try
        {
            var callerIdentity = CancellationIdentityContext.Resolve(cancellationToken);
            lease = await _limiter.AcquireAsync(
                cancellationToken,
                () => callerIdentity.IsCancellationRequested ? callerIdentity : null).ConfigureAwait(false);
            response = await _invoker.SendAsync(request, cancellationToken).ConfigureAwait(false);
            _limiter.Observe(MergeHeaders(response));

            var content = response.Content;
            response.Content = new LeaseContent(content, lease);
            lease = null;
            return response;
        }
        catch (Exception exception)
        {
            try
            {
                response?.Dispose();
            }
            catch
            {
            }

            try
            {
                lease?.Dispose();
            }
            catch
            {
            }

            ExceptionDispatchInfo.Capture(exception).Throw();
            throw;
        }
    }

    protected override void Dispose(bool disposing)
    {
        if (!disposing || Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            base.Dispose(disposing);
            return;
        }

        Exception? failure = null;
        try
        {
            _invoker.Dispose();
        }
        catch (Exception exception)
        {
            failure = exception;
        }

        if (_ownsInner)
        {
            try
            {
                _inner.Dispose();
            }
            catch (Exception exception)
            {
                failure ??= exception;
            }
        }

        try
        {
            base.Dispose(disposing);
        }
        catch (Exception exception)
        {
            failure ??= exception;
        }

        if (failure is not null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private static IReadOnlyDictionary<string, string> MergeHeaders(HttpResponseMessage response)
    {
        var merged = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        AddHeaders(merged, response.Headers);
        AddHeaders(merged, response.Content.Headers);
        return merged;
    }

    private static void AddHeaders(Dictionary<string, string> destination, HttpHeaders headers)
    {
        foreach (var header in headers)
        {
            var value = string.Join(", ", header.Value);
            if (destination.TryGetValue(header.Key, out var existing))
            {
                destination[header.Key] = string.Concat(existing, ", ", value);
            }
            else
            {
                destination.Add(header.Key, value);
            }
        }
    }

    private sealed class LeaseContent : HttpContent
    {
        private readonly HttpContent _inner;
        private RateLimitLease? _lease;
        private int _disposed;

        internal LeaseContent(HttpContent inner, RateLimitLease lease)
        {
            _inner = inner ?? throw new ArgumentNullException(nameof(inner));
            _lease = lease ?? throw new ArgumentNullException(nameof(lease));
            foreach (var header in inner.Headers)
            {
                Headers.TryAddWithoutValidation(header.Key, header.Value);
            }
        }

        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) =>
            _inner.CopyToAsync(stream, context);

        protected override Task SerializeToStreamAsync(
            Stream stream,
            TransportContext? context,
            CancellationToken cancellationToken) =>
            _inner.CopyToAsync(stream, context, cancellationToken);

        protected override bool TryComputeLength(out long length)
        {
            length = _inner.Headers.ContentLength ?? 0;
            return _inner.Headers.ContentLength is not null;
        }

        protected override Task<Stream> CreateContentReadStreamAsync() => _inner.ReadAsStreamAsync();

        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) =>
            _inner.ReadAsStreamAsync(cancellationToken);

        protected override void Dispose(bool disposing)
        {
            if (!disposing || Interlocked.Exchange(ref _disposed, 1) != 0)
            {
                base.Dispose(disposing);
                return;
            }

            Exception? failure = null;
            try
            {
                _inner.Dispose();
            }
            catch (Exception exception)
            {
                failure = exception;
            }

            try
            {
                base.Dispose(disposing);
            }
            catch (Exception exception)
            {
                failure ??= exception;
            }

            try
            {
                Interlocked.Exchange(ref _lease, null)?.Dispose();
            }
            catch (Exception exception)
            {
                failure ??= exception;
            }

            if (failure is not null)
            {
                ExceptionDispatchInfo.Capture(failure).Throw();
            }
        }
    }
}
