using System.Net;
using System.Text;
using System.Text.Json;

/// <summary>Records actual outgoing HTTP bodies and returns frozen offline responses.</summary>
internal sealed class ScriptedHttpHandler : HttpMessageHandler
{
    private readonly JsonElement? _script;
    private readonly string _provider;
    private int _used;
    private int _disposed;
    private readonly Action<string, JsonElement> _onRequest;
    private readonly Action<string, string> _onCleanup;

    internal ScriptedHttpHandler(string provider, JsonElement? script, Action<string, JsonElement> onRequest, Action<string, string> onCleanup)
    {
        _provider = provider;
        _script = script;
        _onRequest = onRequest;
        _onCleanup = onCleanup;
    }

    internal int Consumed => Volatile.Read(ref _used);

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        if (_script is null) throw new InvalidOperationException("No HTTP script exists for this dispatch.");
        var script = _script.Value;
        if (Interlocked.Exchange(ref _used, 1) != 0) throw new InvalidOperationException("HTTP script consumed more than once.");
        var body = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
        using (var parsed = JsonDocument.Parse(body)) _onRequest(script.GetProperty("id").GetString()!, parsed.RootElement.Clone());
        var action = script.GetProperty("actions")[0];
        var response = new HttpResponseMessage((HttpStatusCode)action.GetProperty("status").GetInt32())
        {
            Content = new StringContent(action.GetProperty("body").GetString()!, Encoding.UTF8),
        };
        foreach (var header in action.GetProperty("headers").EnumerateObject())
        {
            response.Content.Headers.Remove(header.Name);
            response.Content.Headers.TryAddWithoutValidation(header.Name, header.Value.GetString());
        }
        return response;
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing && Interlocked.Exchange(ref _disposed, 1) == 0) _onCleanup("server_close", _provider);
        base.Dispose(disposing);
    }
}
