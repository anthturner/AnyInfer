using System.Net;
using System.Net.Http.Headers;

namespace AnyInfer.Providers;

internal sealed record RedirectRequestContext(Uri Uri, HttpMethod Method, bool IncludeBody, bool IncludeOriginBoundHeaders, bool IsRedirect, bool OriginalConfiguredHostEligible = true);

internal sealed class RedirectExchange : IDisposable
{
    private HttpRequestMessage? _request;
    private HttpResponseMessage? _response;
    internal RedirectExchange(HttpRequestMessage request, HttpResponseMessage response) { _request = request; _response = response; }
    internal HttpRequestMessage Request => _request ?? throw new ObjectDisposedException(nameof(RedirectExchange));
    internal HttpResponseMessage Response => _response ?? throw new ObjectDisposedException(nameof(RedirectExchange));
    public void Dispose()
    {
        var response = Interlocked.Exchange(ref _response, null);
        var request = Interlocked.Exchange(ref _request, null);
        Exception? cleanup = null;
        try { response?.Dispose(); } catch (Exception exception) { cleanup = exception; }
        try { request?.Dispose(); } catch when (cleanup is not null) { }
        if (cleanup is not null) throw cleanup;
    }
}

internal sealed class ProviderHttpRedirects
{
    private const int MaximumFollowedRedirects = 20;
    private readonly HttpClient _client;
    private readonly RedirectCookieJar _cookies = new();
    internal ProviderHttpRedirects(HttpClient client) => _client = client;

    internal async ValueTask<RedirectExchange> SendAsync(Uri initialUri, HttpMethod initialMethod, Func<RedirectRequestContext, HttpRequestMessage> createRequest, string phase, CancellationToken cancellationToken)
    {
        var uri = initialUri; var method = initialMethod; var includeBody = true; var includeHeaders = true; var hostEligible = true;
        for (var followed = 0; ; followed++)
        {
            HttpRequestMessage? request = null; HttpResponseMessage? response = null;
            try
            {
                var redirect = followed != 0;
                request = createRequest(new RedirectRequestContext(uri, method, includeBody, includeHeaders, redirect, hostEligible));
                _cookies.Apply(uri, request, redirect);
                response = await _client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
                _cookies.Observe(uri, response.Headers);
                if (!IsRedirect(response.StatusCode) || !HasRawLocation(response.Headers)) return Transfer(request, response, ref request, ref response);
                if (followed == MaximumFollowedRedirects) throw new HttpRequestException("The provider redirect limit was exceeded.");
                if (!TryResolve(uri, response.Headers, out var next)) throw new HttpRequestException("The provider redirect target is invalid.");
                var nextMethod = Rewrite(method, response.StatusCode);
                var rewrote = nextMethod == HttpMethod.Get && method != HttpMethod.Get;
                var originChanged = !OriginCompatible(uri, next);
                var strictSameOrigin = SameOrigin(uri, next);
                try
                {
                    await DrainAsync(response, cancellationToken).ConfigureAwait(false);
                }
                catch (IOException exception)
                {
                    throw new HttpRequestException("The provider redirect response could not be drained.", exception);
                }
                DisposeBoth(ref response, ref request, primary: null);
                uri = next; method = nextMethod; includeBody = rewrote ? false : includeBody; includeHeaders &= !originChanged; hostEligible &= strictSameOrigin;
            }
            catch (Exception primary)
            {
                DisposeBoth(ref response, ref request, primary);
                throw;
            }
        }
    }

    private static RedirectExchange Transfer(HttpRequestMessage requestValue, HttpResponseMessage responseValue, ref HttpRequestMessage? request, ref HttpResponseMessage? response)
    { var exchange = new RedirectExchange(requestValue, responseValue); request = null; response = null; return exchange; }
    private static bool IsRedirect(HttpStatusCode value) => value is HttpStatusCode.Moved or HttpStatusCode.Redirect or HttpStatusCode.RedirectMethod or HttpStatusCode.TemporaryRedirect or HttpStatusCode.PermanentRedirect;
    private static bool HasRawLocation(HttpResponseHeaders headers) => headers.NonValidated.TryGetValues("Location", out var values) && values.Any();
    private static HttpMethod Rewrite(HttpMethod method, HttpStatusCode value) => (value is HttpStatusCode.Moved or HttpStatusCode.Redirect or HttpStatusCode.RedirectMethod) && method == HttpMethod.Post ? HttpMethod.Get : method;
    private static bool TryResolve(Uri current, HttpResponseHeaders headers, out Uri next)
    {
        next = null!;
        try
        {
            if (!headers.NonValidated.TryGetValues("Location", out var raw)) return false;
            var values = raw.ToArray();
            if (values.Length != 1) return false;
            var value = values[0];
            Uri resolved;
            if (TryHttpSchemeReference(value, out var scheme, out var remainder))
            {
                if (remainder.Length != 0 && remainder[0] is not ('/' or '?' or '#')) return false;
                if (HasNonEmptyAuthority(remainder))
                {
                    if (!Uri.TryCreate(current, value, out var absoluteTarget)) return false;
                    resolved = absoluteTarget;
                }
                else if (!TryRepairHostlessHttpReference(current, scheme, remainder, out resolved))
                {
                    return false;
                }
            }
            else if (!Uri.TryCreate(current, value, out var relativeTarget))
            {
                return false;
            }
            else
            {
                resolved = relativeTarget;
            }
            if (resolved.Fragment.Length <= 1 && current.Fragment.Length > 1)
            {
                var builder = new UriBuilder(resolved) { Fragment = current.Fragment };
                resolved = builder.Uri;
            }
            if (resolved.Scheme is not ("http" or "https") || string.IsNullOrEmpty(resolved.Host) || !string.IsNullOrEmpty(resolved.UserInfo)) return false;
            next = resolved; return true;
        }
        catch (UriFormatException) { return false; }
        catch (ArgumentException) { return false; }
    }

    private static bool TryHttpSchemeReference(string value, out string scheme, out string remainder)
    {
        scheme = string.Empty;
        remainder = string.Empty;
        var separator = value.IndexOf(':');
        if (separator <= 0) return false;
        var candidate = value[..separator];
        if (!candidate.Equals("http", StringComparison.OrdinalIgnoreCase) &&
            !candidate.Equals("https", StringComparison.OrdinalIgnoreCase)) return false;
        scheme = candidate;
        remainder = value[(separator + 1)..];
        return true;
    }

    private static bool TryRepairHostlessHttpReference(Uri current, string scheme, string remainder, out Uri resolved)
    {
        resolved = null!;
        var fragmentIndex = remainder.IndexOf('#');
        var withoutFragment = fragmentIndex < 0 ? remainder : remainder[..fragmentIndex];
        var fragment = fragmentIndex < 0 ? string.Empty : remainder[(fragmentIndex + 1)..];
        var queryIndex = withoutFragment.IndexOf('?');
        var path = queryIndex < 0 ? withoutFragment : withoutFragment[..queryIndex];
        var query = queryIndex < 0 ? string.Empty : withoutFragment[(queryIndex + 1)..];
        if (path.StartsWith("//", StringComparison.Ordinal)) path = path[2..];
        path = path.Length == 0 ? "/" : path[0] == '/' ? path : "/" + path;

        try
        {
            var builder = new UriBuilder(scheme, current.Host)
            {
                Path = path,
                Query = queryIndex < 0 ? string.Empty : "?" + query,
                Fragment = fragmentIndex < 0 ? string.Empty : "#" + fragment,
            };
            resolved = builder.Uri;
            return true;
        }
        catch (UriFormatException) { return false; }
        catch (ArgumentException) { return false; }
    }

    private static bool HasNonEmptyAuthority(string remainder) =>
        remainder.StartsWith("//", StringComparison.Ordinal) && remainder.Length > 2 && remainder[2] is not ('/' or '?' or '#');
    private static bool OriginCompatible(Uri current, Uri next) => string.Equals(current.Scheme, next.Scheme, StringComparison.OrdinalIgnoreCase) && string.Equals(current.Host, next.Host, StringComparison.OrdinalIgnoreCase) && current.Port == next.Port || string.Equals(current.Host, next.Host, StringComparison.OrdinalIgnoreCase) && current.Scheme.Equals("http", StringComparison.OrdinalIgnoreCase) && current.Port == 80 && next.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase) && next.Port == 443;
    private static bool SameOrigin(Uri current, Uri next) => string.Equals(current.Scheme, next.Scheme, StringComparison.OrdinalIgnoreCase) && string.Equals(current.Host, next.Host, StringComparison.OrdinalIgnoreCase) && current.Port == next.Port;
    private static async ValueTask DrainAsync(HttpResponseMessage response, CancellationToken token)
    { var stream = await response.Content.ReadAsStreamAsync(token).ConfigureAwait(false); var buffer = new byte[4096]; while (await stream.ReadAsync(buffer.AsMemory(), token).ConfigureAwait(false) != 0) { } }
    private static void DisposeBoth(ref HttpResponseMessage? response, ref HttpRequestMessage? request, Exception? primary)
    {
        var ownedResponse = response; response = null; var ownedRequest = request; request = null; Exception? cleanup = null;
        try { ownedResponse?.Dispose(); } catch (Exception exception) { cleanup = exception; }
        try { ownedRequest?.Dispose(); } catch when (cleanup is not null || primary is not null) { }
        if (primary is null && cleanup is not null) throw cleanup;
    }
}
