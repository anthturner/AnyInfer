using AnyInfer.Capabilities;
using AnyInfer.Internal;
using AnyInfer.Json;
using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Text;

namespace AnyInfer.Providers;

/// <summary>Translates Voyage's embeddings and reranking retrieval endpoints.</summary>
internal sealed class VoyageAdapter : IEmbedsText, IReranksText, IProviderLifecycle, IAsyncDisposable
{
    private const string DefaultBaseUrl = "https://api.voyageai.com/v1";
    private readonly Uri _baseUrl;
    private readonly string? _apiKey;
    private readonly string _providerId;
    private readonly IReadOnlyList<KeyValuePair<string, string>> _headers;
    private readonly VoyageHttpTransport _transport;
    private readonly double _timeoutS;
    private int _disposed;

    private VoyageAdapter(ProviderConfig config)
    {
        _baseUrl = ParseBaseUrl(config.BaseUrl ?? DefaultBaseUrl);
        _apiKey = config.ApiKey;
        _providerId = config.ProviderId;
        _headers = config.Headers.ToArray();
        ValidateHeaders(_headers);
        _timeoutS = config.TimeoutS;
        _transport = new VoyageHttpTransport(config.Transport, config.TimeoutS, config.TransportOwnedByPool);
    }

    internal static IAsyncDisposable Create(ProviderConfig config, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(config);
        try { return new VoyageAdapter(config); }
        catch (UriFormatException exception) { throw new ConfigException("The Voyage provider configuration is invalid.", config.ProviderId, "The configured base URL is invalid.", nativeInner: exception); }
        catch (ArgumentException exception) { throw new ConfigException("The Voyage provider configuration is invalid.", config.ProviderId, "The configured base URL or headers are invalid.", nativeInner: exception); }
    }

    public ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        cancellationToken.ThrowIfCancellationRequested();
        return ValueTask.FromResult<IReadOnlyList<DiscoveredModel>>(Array.Empty<DiscoveredModel>());
    }

    public async ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        try
        {
            var status = await SendAsync(HttpMethod.Get, "models", null, "discover", null, 1024 * 1024, cancellationToken, static response => response.StatusCode, readBody: false).ConfigureAwait(false);
            return new Health(true, $"endpoint reachable (HTTP {(int)status}; reachability only)");
        }
        catch (ProviderException exception)
        {
            return new Health(false, Bound(exception.Detail ?? exception.Message, 200));
        }
    }

    public async ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        ArgumentNullException.ThrowIfNull(request);
        var properties = new List<JsonProperty>
        {
            new("model", new JsonString(request.Model)),
            new("input", new JsonArray(request.Inputs.Select(static input => new JsonString(input)))),
        };
        if (request.InputType is EmbeddingInputIntent.Query) properties.Add(new JsonProperty("input_type", new JsonString("query")));
        if (request.InputType is EmbeddingInputIntent.Document) properties.Add(new JsonProperty("input_type", new JsonString("document")));
        if (request.Dimensions is { } dimensions) properties.Add(new JsonProperty("output_dimension", new JsonInteger(dimensions)));
        Overlay(properties, request.ExtraOptions);
        var payload = new JsonObject(properties);
        return await SendAsync(HttpMethod.Post, "embeddings", payload, "generate", request.TimeoutS, request.MaxResponseBytes, cancellationToken, response => ParseEmbedding(response, request)).ConfigureAwait(false);
    }

    public async ValueTask<RerankWireResult> RerankAsync(RerankWireRequest request, CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        ArgumentNullException.ThrowIfNull(request);
        var properties = new List<JsonProperty>
        {
            new("model", new JsonString(request.Model)),
            new("query", new JsonString(request.Query)),
            new("documents", new JsonArray(request.Documents.Select(static document => new JsonString(document.Text)))),
        };
        if (request.TopN is { } topN) properties.Add(new JsonProperty("top_k", new JsonInteger(topN)));
        Overlay(properties, request.ExtraOptions);
        return await SendAsync(HttpMethod.Post, "rerank", new JsonObject(properties), "generate", request.TimeoutS, request.MaxResponseBytes, cancellationToken, response => ParseRerank(response, request)).ConfigureAwait(false);
    }

    private EmbeddingWireResult ParseEmbedding(VoyageHttpResponse response, EmbeddingWireRequest request)
    {
        ThrowForStatus(response, "generate");
        var raw = ReadJson(response.Body, "Voyage embeddings response is not valid JSON.");
        if (raw is not JsonObject payload || !payload.TryGetValue("data", out var dataValue) || dataValue is not JsonArray data) throw Validation("Voyage embeddings response is missing a data array.");
        if (data.Items.Count != request.Inputs.Count) throw Validation($"Voyage embeddings response returned {data.Items.Count} vectors for {request.Inputs.Count} inputs.");
        var vectors = new double[request.Inputs.Count][];
        var seen = new bool[request.Inputs.Count];
        foreach (var entry in data.Items)
        {
            if (entry is not JsonObject item || !item.TryGetValue("index", out var indexValue) || indexValue is not JsonInteger index || index.Value < 0 || index.Value >= request.Inputs.Count || !item.TryGetValue("embedding", out var embeddingValue) || embeddingValue is not JsonArray embedding) throw Validation("Voyage embeddings response contains an invalid indexed vector.");
            var position = checked((int)index.Value);
            if (seen[position]) throw Validation("Voyage embeddings response contains a duplicate vector index.");
            seen[position] = true;
            vectors[position] = embedding.Items.Select(Float).ToArray();
        }

        if (seen.Any(static present => !present)) throw Validation("Voyage embeddings response is missing an input vector.");
        return new EmbeddingWireResult(vectors, Model(payload), vectors.Length == 0 ? null : vectors[0].Length, usage: Usage(payload), raw: raw);
    }

    private RerankWireResult ParseRerank(VoyageHttpResponse response, RerankWireRequest request)
    {
        ThrowForStatus(response, "generate");
        var raw = ReadJson(response.Body, "Voyage rerank response is not valid JSON.");
        if (raw is not JsonObject payload || !payload.TryGetValue("data", out var dataValue) || dataValue is not JsonArray data) throw Validation("Voyage rerank response is missing a data array.");
        var seen = new HashSet<int>();
        var items = new List<WireRankedItem>();
        foreach (var entry in data.Items)
        {
            if (entry is not JsonObject item || !item.TryGetValue("index", out var indexValue) || indexValue is not JsonInteger index || index.Value < 0 || index.Value >= request.Documents.Count || !item.TryGetValue("relevance_score", out var scoreValue)) throw Validation("Voyage rerank response contains an invalid rank.");
            var position = checked((int)index.Value);
            if (!seen.Add(position)) throw Validation("Voyage rerank response contains a duplicate document index.");
            items.Add(new WireRankedItem(request.Documents[position].Index, RerankScore(scoreValue)));
        }

        return new RerankWireResult(items, Model(payload), Usage(payload), raw);
    }

    private async ValueTask<T> SendAsync<T>(HttpMethod method, string path, JsonObject? payload, string phase, double? timeoutS, int cap, CancellationToken cancellationToken, Func<VoyageHttpResponse, T> convert, bool readBody = true)
    {
        using var message = new HttpRequestMessage(method, Endpoint(path));
        if (payload is not null)
        {
            var content = new ByteArrayContent(Encoding.UTF8.GetBytes(JsonWriter.WriteModern(payload)));
            content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
            message.Content = content;
        }
        else
        {
            message.Content = new ByteArrayContent([]);
            message.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
        }
        message.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        ApplyHeaders(message, message.Content, _headers);
        if (!string.IsNullOrEmpty(_apiKey) && !message.Headers.Contains("Authorization")) message.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);
        try { return await _transport.SendAsync(message, phase, timeoutS ?? _timeoutS, cap, cancellationToken, convert, readBody).ConfigureAwait(false); }
        catch (ProviderException exception) when (exception.Provider is null) { throw ProviderException.Create(exception.Message, exception.Category, exception.Retryable, exception.Phase, exception.RetryAfterS, exception.HttpStatus, _providerId, exception.Detail, exception.Hint, exception.NativeInner); }
    }

    private void ThrowForStatus(VoyageHttpResponse response, string phase)
    {
        if ((int)response.StatusCode < 400) return;
        var detail = ErrorDetail(response.Body);
        var status = (int)response.StatusCode;
        var (category, retryable, hint) = response.StatusCode switch
        {
            HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden => ("auth", false, "check the configured API key or credential reference"),
            HttpStatusCode.NotFound => ("model_not_found", false, "verify the model id, or list available models with client.models()"),
            (HttpStatusCode)429 => ("rate_limit", true, (string?)null),
            (HttpStatusCode)413 or (HttpStatusCode)422 when ContextOverflow(detail) => ("context_length", false, "shorten the prompt or choose a model with a larger context window"),
            _ when status >= 500 => ("provider_unavailable", true, (string?)null),
            (HttpStatusCode)408 or (HttpStatusCode)409 or (HttpStatusCode)425 => ("provider", true, (string?)null),
            _ => ("provider", false, (string?)null),
        };
        throw ProviderException.Create($"The Voyage service returned HTTP {status}.", category, retryable, phase, RetryAfter(response.Headers), status, _providerId, detail, hint);
    }

    private static Uri ParseBaseUrl(string value)
    {
        var uri = new Uri(value, UriKind.Absolute);
        if (uri.Scheme is not ("http" or "https") || !string.IsNullOrEmpty(uri.UserInfo) || !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment)) throw new ArgumentException("The Voyage base URL must be an absolute HTTP(S) URL without userinfo, query, or fragment.", nameof(value));
        return uri;
    }

    private Uri Endpoint(string suffix) => new(_baseUrl.AbsoluteUri.TrimEnd('/') + "/" + suffix.TrimStart('/'), UriKind.Absolute);
    private static void Overlay(List<JsonProperty> properties, IReadOnlyDictionary<string, JsonValue> options) { foreach (var pair in options) properties.Add(new JsonProperty(pair.Key, pair.Value)); }
    private static void ValidateHeaders(IEnumerable<KeyValuePair<string, string>> headers) { using var message = new HttpRequestMessage(); using var content = new ByteArrayContent([]); ApplyHeaders(message, content, headers); }
    private static void ApplyHeaders(HttpRequestMessage message, HttpContent? content, IEnumerable<KeyValuePair<string, string>> headers) { foreach (var header in headers) { if (string.Equals(header.Key, "Authorization", StringComparison.OrdinalIgnoreCase)) message.Headers.Remove("Authorization"); if (content is not null && string.Equals(header.Key, "Content-Type", StringComparison.OrdinalIgnoreCase)) content.Headers.Remove("Content-Type"); if (!message.Headers.TryAddWithoutValidation(header.Key, header.Value) && (content is null || !content.Headers.TryAddWithoutValidation(header.Key, header.Value))) throw new ArgumentException("The configured HTTP header is invalid.", nameof(headers)); } }
    private static JsonValue ReadJson(byte[] body, string message) { try { return JsonReader.Read(body); } catch (FormatException exception) { throw Validation(message, native: exception); } }
    private static double Float(JsonValue value)
    {
        if (value is JsonInteger integer) return (double)integer.Value;
        if (value is JsonNumber number) return number.Value;
        if (value is JsonBoolean boolean) return boolean.Value ? 1d : 0d;
        if (value is JsonString text)
        {
            try { return double.Parse(text.Value, NumberStyles.Float, CultureInfo.InvariantCulture); }
            catch (FormatException exception) { throw Validation("Voyage response contains a non-numeric component.", native: exception); }
            catch (OverflowException exception) { throw Validation("Voyage response contains a non-numeric component.", native: exception); }
        }

        throw Validation("Voyage response contains a non-numeric component.");
    }
    private static double RerankScore(JsonValue value) => value switch
    {
        JsonInteger integer => (double)integer.Value,
        JsonNumber number => number.Value,
        _ => throw Validation("Voyage rerank response contains a non-numeric relevance score."),
    };
    private static string? Model(JsonObject payload) => payload.TryGetValue("model", out var value) && value is JsonString model ? model.Value : null;
    private static Usage? Usage(JsonObject payload)
    {
        if (!payload.TryGetValue("usage", out var usageValue) || usageValue is not JsonObject usage || !usage.TryGetValue("total_tokens", out var totalValue) || totalValue is not JsonInteger total) return null;
        if (total.Value < long.MinValue || total.Value > long.MaxValue) throw Validation("Voyage total_tokens exceeds the native usage counter range.");
        return new Usage(TotalTokens: (long)total.Value);
    }
    private static ProviderException Validation(string message, string phase = "validate", Exception? native = null) => ProviderException.Create(message, "provider", false, phase, nativeInner: native);
    private static string ErrorDetail(byte[] body)
    {
        var text = Encoding.UTF8.GetString(body);
        try
        {
            if (JsonReader.Read(body) is not JsonObject payload) return Bound(text, 400);
            if (payload.TryGetValue("error", out var error))
            {
                if (error is JsonString errorText) return Bound(errorText.Value, 400);
                if (error is JsonObject errorObject) return ErrorMessage(errorObject) ?? Bound(text, 400);
            }

            return ErrorMessage(payload) ?? Bound(text, 400);
        }
        catch (FormatException)
        {
            return Bound(text, 400);
        }
    }
    private static string? ErrorMessage(JsonObject payload)
    {
        foreach (var name in new[] { "message", "detail", "type" })
        {
            if (payload.TryGetValue(name, out var value) && value is JsonString text) return Bound(text.Value, 400);
        }

        return null;
    }
    private static string Bound(string text, int count) => string.Concat(text.EnumerateRunes().Take(count).Select(static rune => rune.ToString()));
    private static bool ContextOverflow(string detail) { var lower = detail.ToLowerInvariant(); return lower.Contains("context length") || lower.Contains("context_length") || lower.Contains("too many tokens") || lower.Contains("maximum context"); }
    private static double? RetryAfter(HttpResponseHeaders headers) { if (!headers.TryGetValues("Retry-After", out var values)) return null; var raw = values.FirstOrDefault(); return raw is not null && double.TryParse(raw.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out var value) && double.IsFinite(value) && value >= 0d ? value : null; }
    private void ThrowIfDisposed() { if (Volatile.Read(ref _disposed) != 0) throw new ObjectDisposedException(nameof(VoyageAdapter)); }
    public async ValueTask DisposeAsync() { if (Interlocked.Exchange(ref _disposed, 1) == 0) await _transport.DisposeAsync().ConfigureAwait(false); }
}
