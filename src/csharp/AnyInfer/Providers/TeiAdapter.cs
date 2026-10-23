using AnyInfer.Capabilities;
using AnyInfer.Internal;
using AnyInfer.Json;
using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Numerics;
using System.Text;

namespace AnyInfer.Providers;

/// <summary>Translates Text Embeddings Inference's native retrieval endpoints.</summary>
internal sealed class TeiAdapter : IEmbedsText, IReranksText, IProviderLifecycle, IAsyncDisposable
{
    private const string DefaultBaseUrl = "http://127.0.0.1:8080";
    private readonly Uri _baseUrl;
    private readonly string? _apiKey;
    private readonly string _providerId;
    private readonly IReadOnlyList<KeyValuePair<string, string>> _headers;
    private readonly TeiHttpTransport _transport;
    private readonly double _timeoutS;
    private int _disposed;

    private TeiAdapter(ProviderConfig config, CancellationToken cancellationToken)
    {
        _baseUrl = ParseBaseUrl(config.BaseUrl ?? DefaultBaseUrl, config.ProviderId);
        _apiKey = config.ApiKey;
        _providerId = config.ProviderId;
        _headers = config.Headers.ToArray();
        ValidateHeaders(_headers);
        _timeoutS = config.TimeoutS;
        _transport = new TeiHttpTransport(config, cancellationToken);
    }

    internal static IAsyncDisposable Create(ProviderConfig config, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(config);
        try { return new TeiAdapter(config, cancellationToken); }
        catch (UriFormatException exception) { throw new ConfigException("The TEI provider configuration is invalid.", config.ProviderId, "The configured base URL is invalid.", nativeInner: exception); }
        catch (ArgumentException exception) { throw new ConfigException("The TEI provider configuration is invalid.", config.ProviderId, "The configured base URL or headers are invalid.", nativeInner: exception); }
    }

    public async ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default)
    {
        var info = await InfoAsync(cancellationToken).ConfigureAwait(false);
        if (!info.TryGetValue("model_id", out var idValue) || idValue is not JsonString id || id.Value.Length == 0) return Array.Empty<DiscoveredModel>();
        ModelCapabilities? capabilities = null;
        if (info.TryGetValue("model_type", out var type))
        {
            var operation = ModelType(type);
            if (operation is not null) capabilities = new ModelCapabilities(operations: new Sourced<IReadOnlySet<InferenceOperation>>(operation, Provenance.Discovered));
        }
        return [new DiscoveredModel(id.Value, capabilities)];
    }

    public async ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var info = await InfoAsync(cancellationToken).ConfigureAwait(false);
            return info.TryGetValue("model_id", out var id) && id is JsonString model && model.Value.Length > 0 ? new Health(true, "serving " + model.Value) : new Health(true);
        }
        catch (ProviderException exception) { return new Health(false, Bound(exception.Detail ?? exception.Message, 200)); }
    }

    public async ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        var properties = new List<JsonProperty> { new("inputs", new JsonArray(request.Inputs.Select(static input => new JsonString(input)))) };
        if (request.Dimensions is { } dimensions) properties.Add(new JsonProperty("dimensions", new JsonInteger(dimensions)));
        Overlay(properties, request.ExtraOptions);
        var payload = new JsonObject(properties);
        return await SendAsync(HttpMethod.Post, "embed", payload, "generate", request.TimeoutS, request.MaxResponseBytes, cancellationToken, response => ParseEmbedding(response, request, payload)).ConfigureAwait(false);
    }

    private EmbeddingWireResult ParseEmbedding(TeiHttpResponse response, EmbeddingWireRequest request, JsonObject payload)
    {
        ThrowForStatus(response, "generate");
        var raw = ReadJson(response.Body, "embed response is not valid JSON.");
        if (raw is not JsonArray rows) throw Validation("The TEI embed response is not an array of vectors.");
        if (rows.Items.Count != request.Inputs.Count) throw Validation($"The TEI embed response returned {rows.Items.Count} vectors for {request.Inputs.Count} inputs.");
        var vectors = rows.Items.Select(row => row is JsonArray array ? array.Items.Select(Float).ToArray() : throw Validation("The TEI embed response contains a non-array vector.")).ToArray();
        bool? normalized = payload.TryGetValue("normalize", out var normalize) ? normalize is JsonBoolean value ? value.Value : null : true;
        return new EmbeddingWireResult(vectors, dimensions: vectors.Length == 0 ? null : vectors[0].Length, normalized: normalized, usage: null, raw: raw);
    }

    public async ValueTask<RerankWireResult> RerankAsync(RerankWireRequest request, CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        var properties = new List<JsonProperty> { new("query", new JsonString(request.Query)), new("texts", new JsonArray(request.Documents.Select(static document => new JsonString(document.Text)))), new("return_text", new JsonBoolean(false)) };
        Overlay(properties, request.ExtraOptions);
        return await SendAsync(HttpMethod.Post, "rerank", new JsonObject(properties), "generate", request.TimeoutS, request.MaxResponseBytes, cancellationToken, response => ParseRerank(response, request)).ConfigureAwait(false);
    }

    private RerankWireResult ParseRerank(TeiHttpResponse response, RerankWireRequest request)
    {
        ThrowForStatus(response, "generate");
        var raw = ReadJson(response.Body, "rerank response is not valid JSON.");
        if (raw is not JsonArray entries) throw Validation("The TEI rerank response is not an array of ranks.");
        var items = new List<WireRankedItem>();
        foreach (var entry in entries.Items)
        {
            if (entry is not JsonObject item || !item.TryGetValue("index", out var indexValue) || indexValue is not JsonInteger position || position.Value < 0 || position.Value > int.MaxValue || !item.TryGetValue("score", out var scoreValue)) throw Validation("The TEI rerank response contains an invalid rank.");
            var positionInt = (int)position.Value;
            if (positionInt >= request.Documents.Count) throw Validation("The TEI rerank response index is outside the submitted documents.");
            var score = scoreValue switch { JsonInteger integer => (double)integer.Value, JsonNumber number => number.Value, _ => throw Validation("The TEI rerank rank is missing a numeric score.") };
            items.Add(new WireRankedItem(request.Documents[positionInt].Index, score));
        }
        var ranked = items.OrderByDescending(static item => item.Score).ToList();
        if (request.TopN is { } topN) ranked = ranked.Take(topN).ToList();
        return new RerankWireResult(ranked, usage: null, raw: raw);
    }

    private async ValueTask<JsonObject> InfoAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        return await SendAsync(HttpMethod.Get, "info", null, "discover", null, 1024 * 1024, cancellationToken, ParseInfo).ConfigureAwait(false);
    }

    private JsonObject ParseInfo(TeiHttpResponse response)
    {
        ThrowForStatus(response, "discover");
        return ReadJson(response.Body, "TEI info response is not valid JSON.") as JsonObject ?? throw Validation("The TEI info response is not an object.", "discover");
    }

    private async ValueTask<T> SendAsync<T>(HttpMethod method, string path, JsonObject? payload, string phase, double? timeoutS, int cap, CancellationToken cancellationToken, Func<TeiHttpResponse, T> convert)
    {
        using var message = new HttpRequestMessage(method, Endpoint(path));
        if (payload is not null) { var content = new ByteArrayContent(Encoding.UTF8.GetBytes(JsonWriter.WriteModern(payload))); content.Headers.ContentType = new MediaTypeHeaderValue("application/json"); message.Content = content; }
        else { message.Content = new ByteArrayContent([]); message.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json"); }
        message.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        ApplyHeaders(message, message.Content, _headers);
        if (!string.IsNullOrEmpty(_apiKey) && !message.Headers.Contains("Authorization")) message.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);
        try { return await _transport.SendAsync(message, phase, timeoutS, cap, cancellationToken, convert).ConfigureAwait(false); }
        catch (ProviderException exception) when (exception.Provider is null) { throw ProviderException.Create(exception.Message, exception.Category, exception.Retryable, exception.Phase, exception.RetryAfterS, exception.HttpStatus, _providerId, exception.Detail, exception.Hint, exception.NativeInner); }
    }

    private void ThrowForStatus(TeiHttpResponse response, string phase)
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
        throw ProviderException.Create($"The TEI service returned HTTP {status}.", category, retryable, phase, RetryAfter(response.Headers), status, _providerId, detail, hint);
    }

    private static Uri ParseBaseUrl(string value, string providerId)
    {
        var uri = new Uri(value, UriKind.Absolute);
        if (uri.Scheme is not ("http" or "https") || !string.IsNullOrEmpty(uri.UserInfo) || !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment)) throw new ArgumentException("The TEI base URL must be an absolute HTTP(S) URL without userinfo, query, or fragment.", nameof(value));
        return uri;
    }
    private Uri Endpoint(string suffix) => new(_baseUrl.AbsoluteUri.TrimEnd('/') + "/" + suffix.TrimStart('/'), UriKind.Absolute);
    private static void Overlay(List<JsonProperty> properties, IReadOnlyDictionary<string, JsonValue> options) { foreach (var pair in options) properties.Add(new JsonProperty(pair.Key, pair.Value)); }
    private static void ValidateHeaders(IEnumerable<KeyValuePair<string, string>> headers) { using var message = new HttpRequestMessage(); using var content = new ByteArrayContent([]); ApplyHeaders(message, content, headers); }
    private static void ApplyHeaders(HttpRequestMessage message, HttpContent? content, IEnumerable<KeyValuePair<string, string>> headers) { foreach (var header in headers) { if (string.Equals(header.Key, "Authorization", StringComparison.OrdinalIgnoreCase)) message.Headers.Remove("Authorization"); if (content is not null && string.Equals(header.Key, "Content-Type", StringComparison.OrdinalIgnoreCase)) content.Headers.Remove("Content-Type"); if (!message.Headers.TryAddWithoutValidation(header.Key, header.Value) && (content is null || !content.Headers.TryAddWithoutValidation(header.Key, header.Value))) throw new ArgumentException("The configured HTTP header is invalid.", nameof(headers)); } }
    private static JsonValue ReadJson(byte[] body, string message) { try { return JsonReader.Read(body); } catch (FormatException exception) { throw Validation(message, native: exception); } }
    private static double Float(JsonValue value) => value switch { JsonInteger integer => (double)integer.Value, JsonNumber number => number.Value, JsonBoolean boolean => boolean.Value ? 1d : 0d, JsonString text => double.Parse(text.Value, NumberStyles.Float, CultureInfo.InvariantCulture), _ => throw Validation("The TEI embedding vector contains a non-numeric component.") };
    private static ProviderException Validation(string message, string phase = "validate", Exception? native = null) => ProviderException.Create(message, "provider", false, phase, nativeInner: native);
    private static IReadOnlySet<InferenceOperation>? ModelType(JsonValue value) { var kind = value switch { JsonString text => text.Value, JsonObject obj when obj.Properties.Count == 1 => obj.Properties[0].Name, _ => null }; return kind switch { "embedding" => new HashSet<InferenceOperation> { InferenceOperation.Embedding }, "reranker" => new HashSet<InferenceOperation> { InferenceOperation.Rerank }, null => null, _ => new HashSet<InferenceOperation>() }; }
    private static string ErrorDetail(byte[] body) { var text = Encoding.UTF8.GetString(body); try { if (JsonReader.Read(body) is JsonObject obj && obj.TryGetValue("error", out var error) && error is JsonString message) text = message.Value; } catch (FormatException) { } return Bound(text, 300); }
    private static string Bound(string text, int count) => string.Concat(text.EnumerateRunes().Take(count).Select(static rune => rune.ToString()));
    private static bool ContextOverflow(string detail) { var lower = detail.ToLowerInvariant(); return lower.Contains("context length") || lower.Contains("context_length") || lower.Contains("too many tokens") || lower.Contains("maximum context"); }
    private static double? RetryAfter(HttpResponseHeaders headers)
    {
        if (!headers.TryGetValues("Retry-After", out var values)) return null;
        var raw = values.FirstOrDefault();
        return raw is not null && double.TryParse(raw.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out var value) && double.IsFinite(value) && value >= 0d ? value : null;
    }
    private void ThrowIfDisposed() { if (Volatile.Read(ref _disposed) != 0) throw new ObjectDisposedException(nameof(TeiAdapter)); }
    public async ValueTask DisposeAsync() { if (Interlocked.Exchange(ref _disposed, 1) == 0) await _transport.DisposeAsync().ConfigureAwait(false); }
}
