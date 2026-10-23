using System.Net;
using System.Net.Http.Headers;

namespace AnyInfer.Providers;

internal sealed class RedirectCookieJar
{
    private readonly CookieContainer _cookies = new(int.MaxValue, int.MaxValue, int.MaxValue);
    private readonly object _gate = new();

    internal void Apply(Uri destination, HttpRequestMessage request, bool isRedirect)
    {
        if (isRedirect) request.Headers.Remove("Cookie");
        if (!isRedirect && request.Headers.Contains("Cookie")) return;
        string value;
        lock (_gate) value = _cookies.GetCookieHeader(destination);
        if (value.Length != 0) request.Headers.TryAddWithoutValidation("Cookie", value);
    }

    internal void Observe(Uri responseUri, HttpResponseHeaders headers)
    {
        if (!headers.TryGetValues("Set-Cookie", out var values)) return;
        foreach (var value in values)
        {
            try { lock (_gate) _cookies.SetCookies(responseUri, value); }
            catch (CookieException) { }
        }
    }
}
