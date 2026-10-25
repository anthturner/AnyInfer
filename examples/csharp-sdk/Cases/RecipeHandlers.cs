using System.Net;
using System.Text;
using System.Text.Json;

namespace AnyInfer.Examples.Cases;

/// <summary>Answers OpenAI-compatible chat requests and records what each request carried.</summary>
/// <param name="reply">The assistant text every buffered response carries.</param>
/// <param name="inputTokens">The prompt token count each response reports, or <see langword="null"/> to report none.</param>
/// <param name="outputTokens">The completion token count each response reports.</param>
internal sealed class RecipeChatHandler(string reply = "hello", int? inputTokens = 10, int outputTokens = 5) : HttpMessageHandler
{
    private readonly List<JsonElement> _bodies = [];

    /// <summary>Gets how many requests the handler answered.</summary>
    public int Requests { get; private set; }

    /// <summary>Gets how many times the handler was disposed.</summary>
    public int Disposals { get; private set; }

    /// <summary>Gets the request URIs in order.</summary>
    public List<string> Uris { get; } = [];

    /// <summary>Gets the Authorization header of each request, in order.</summary>
    public List<string?> Authorizations { get; } = [];

    /// <summary>Gets each request body, in order.</summary>
    public IReadOnlyList<JsonElement> Bodies => _bodies;

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        Requests++;
        Uris.Add(request.RequestUri!.AbsoluteUri);
        Authorizations.Add(request.Headers.Authorization?.ToString());
        var body = request.Content is null ? "{}" : await request.Content.ReadAsStringAsync(cancellationToken);
        using (var document = JsonDocument.Parse(body))
        {
            _bodies.Add(document.RootElement.Clone());
        }

        var usage = inputTokens is null
            ? $"{{\"completion_tokens\":{outputTokens}}}"
            : $"{{\"prompt_tokens\":{inputTokens},\"completion_tokens\":{outputTokens},\"total_tokens\":{inputTokens + outputTokens}}}";
        var response = $"{{\"choices\":[{{\"message\":{{\"content\":{JsonSerializer.Serialize(reply)}}},\"finish_reason\":\"stop\"}}],\"usage\":{usage}}}";
        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(response, Encoding.UTF8, "application/json"),
        };
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            Disposals++;
        }

        base.Dispose(disposing);
    }
}

/// <summary>Answers native TEI embed and rerank requests of any size and records each batch.</summary>
/// <param name="failText">A text whose batch is answered with HTTP 413, as TEI does for an oversized batch, or <see langword="null"/>.</param>
/// <param name="info">The <c>GET /info</c> response body, or <see langword="null"/> to answer 404.</param>
internal sealed class RecipeTeiHandler(string? failText = null, string? info = null) : HttpMessageHandler
{
    private readonly object _gate = new();
    private int _requests;
    private int _disposals;

    /// <summary>Gets how many requests the handler received.</summary>
    public int Requests => Volatile.Read(ref _requests);

    /// <summary>Gets how many times the handler was disposed.</summary>
    public int Disposals => Volatile.Read(ref _disposals);

    /// <summary>Gets the texts each request carried, in arrival order.</summary>
    public List<string[]> Batches { get; } = [];

    /// <summary>Gets the request paths, in arrival order.</summary>
    public List<string> Paths { get; } = [];

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        Interlocked.Increment(ref _requests);
        if (request.Method == HttpMethod.Get)
        {
            lock (_gate)
            {
                Paths.Add(request.RequestUri!.AbsolutePath);
            }

            return info is not null && request.RequestUri!.AbsolutePath.EndsWith("/info", StringComparison.Ordinal)
                ? new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(info, Encoding.UTF8, "application/json") }
                : new HttpResponseMessage(HttpStatusCode.NotFound);
        }

        var body = request.Content is null ? "{}" : await request.Content.ReadAsStringAsync(cancellationToken);
        using var document = JsonDocument.Parse(body);
        var root = document.RootElement;
        var path = request.RequestUri!.AbsolutePath;
        var texts = (path.EndsWith("/rerank", StringComparison.Ordinal) ? root.GetProperty("texts") : root.GetProperty("inputs"))
            .EnumerateArray()
            .Select(static item => item.GetString()!)
            .ToArray();
        lock (_gate)
        {
            Batches.Add(texts);
            Paths.Add(path);
        }

        if (failText is not null && texts.Contains(failText, StringComparer.Ordinal))
        {
            return new HttpResponseMessage(HttpStatusCode.RequestEntityTooLarge)
            {
                Content = new StringContent("{\"error\":\"batch size exceeds the server limit\",\"error_type\":\"Validation\"}", Encoding.UTF8, "application/json"),
            };
        }

        string response;
        if (path.EndsWith("/rerank", StringComparison.Ordinal))
        {
            // Texts that mention water score highest; ties keep submission order.
            response = "[" + string.Join(",", texts.Select(static (text, index) =>
                $"{{\"index\":{index},\"score\":{(text.Contains("water", StringComparison.Ordinal) ? "0.9" : "0.1")}}}")) + "]";
        }
        else
        {
            // Each vector is [text length, last character code], so callers can check input order.
            response = "[" + string.Join(",", texts.Select(static text => $"[{text.Length},{(int)text[^1]}]")) + "]";
        }

        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(response, Encoding.UTF8, "application/json"),
        };
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            Interlocked.Increment(ref _disposals);
        }

        base.Dispose(disposing);
    }
}

/// <summary>Shared assertion helpers for the recipe cases.</summary>
internal static class RecipeSupport
{
    /// <summary>Runs a call and returns the exception it threw, or <see langword="null"/>.</summary>
    internal static async Task<Exception?> CaptureAsync(Func<Task> call)
    {
        try
        {
            await call();
            return null;
        }
        catch (Exception exception)
        {
            return exception;
        }
    }

    /// <summary>Runs a synchronous call and returns the exception it threw, or <see langword="null"/>.</summary>
    internal static Exception? Capture(Action call)
    {
        try
        {
            call();
            return null;
        }
        catch (Exception exception)
        {
            return exception;
        }
    }
}

/// <summary>Answers Voyage- or Jina-shaped embedding requests of any size and records each batch size.</summary>
internal sealed class RecipeHostedRetrievalHandler : HttpMessageHandler
{
    private readonly object _gate = new();

    /// <summary>Gets the number of inputs each embedding request carried, in arrival order.</summary>
    public List<int> BatchSizes { get; } = [];

    /// <summary>Gets how many requests the handler received.</summary>
    public int Requests
    {
        get
        {
            lock (_gate)
            {
                return BatchSizes.Count;
            }
        }
    }

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var body = request.Content is null ? "{}" : await request.Content.ReadAsStringAsync(cancellationToken);
        using var document = JsonDocument.Parse(body);
        var count = document.RootElement.TryGetProperty("input", out var input) ? input.GetArrayLength() : 0;
        lock (_gate)
        {
            BatchSizes.Add(count);
        }

        if (!request.RequestUri!.AbsolutePath.EndsWith("/embeddings", StringComparison.Ordinal))
        {
            throw new InvalidOperationException("Only embedding requests are scripted.");
        }

        var data = string.Join(",", Enumerable.Range(0, count).Select(static index => $"{{\"index\":{index},\"embedding\":[{index},1]}}"));
        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent($"{{\"data\":[{data}],\"usage\":{{\"total_tokens\":{count}}}}}", Encoding.UTF8, "application/json"),
        };
    }
}
