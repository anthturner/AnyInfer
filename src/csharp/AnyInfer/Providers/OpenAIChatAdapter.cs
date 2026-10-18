using AnyInfer.Capabilities;
using AnyInfer.Internal;
using AnyInfer.Json;
using System.Net;
using System.Net.Http.Headers;
using System.Numerics;
using System.Runtime.CompilerServices;
using System.Text;

namespace AnyInfer.Providers;

/// <summary>Translates the bounded OpenAI-compatible chat-completions dialect.</summary>
internal sealed class OpenAIChatAdapter : IProviderAdapter, IProviderLifecycle
{
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);
    private readonly HttpClient _client;
    private readonly Uri _endpoint;
    private readonly Uri _modelsEndpoint;
    private readonly string? _apiKey;
    private readonly string _providerId;
    private readonly IReadOnlyList<KeyValuePair<string, string>> _headers;
    private readonly TimeSpan _timeout;
    private int _disposed;

    internal OpenAIChatAdapter(
        Uri baseUrl,
        string? apiKey,
        IReadOnlyDictionary<string, string>? headers = null,
        HttpMessageHandler? handler = null,
        string providerId = "openai-compat",
        double timeoutS = 120)
    {
        ArgumentNullException.ThrowIfNull(baseUrl);
        if (!baseUrl.IsAbsoluteUri ||
            baseUrl.Scheme is not ("http" or "https") ||
            !string.IsNullOrEmpty(baseUrl.UserInfo) ||
            !string.IsNullOrEmpty(baseUrl.Query) ||
            !string.IsNullOrEmpty(baseUrl.Fragment))
        {
            throw new ArgumentException("The OpenAI-compatible base URL must be an absolute HTTP(S) URL without userinfo, query, or fragment.", nameof(baseUrl));
        }

        _endpoint = BuildEndpoint(baseUrl, "chat/completions");
        _modelsEndpoint = BuildEndpoint(baseUrl, "models");
        _apiKey = apiKey;
        _providerId = ProviderSettings.NormalizeId(providerId, nameof(providerId));
        _headers = (headers ?? new Dictionary<string, string>())
            .Select(static header => new KeyValuePair<string, string>(header.Key, header.Value))
            .ToArray();
        _timeout = TimeSpan.FromSeconds(timeoutS);
        var ownedHandler = handler ?? new HttpClientHandler
        {
            AllowAutoRedirect = false,
        };
        _client = new HttpClient(ownedHandler, disposeHandler: true)
        {
            Timeout = Timeout.InfiniteTimeSpan,
        };
    }

    internal static IProviderAdapter Create(ProviderConfig config, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(config);
        if (config.ApiVersion is not null || config.Options is { Properties.Count: > 0 })
        {
            throw new ConfigException(
                "The OpenAI-compatible provider configuration is invalid.",
                provider: config.ProviderId,
                detail: "API versions and provider options are not supported by the OpenAI-compatible builtin.");
        }

        var baseUrl = config.BaseUrl ?? throw new ConfigException(
            "The OpenAI-compatible provider configuration is incomplete.",
            provider: config.ProviderId,
            detail: "A base URL is required.");
        try
        {
            ValidateHeaders(config.Headers);
            return new OpenAIChatAdapter(new Uri(baseUrl, UriKind.Absolute), config.ApiKey, config.Headers, config.Transport, config.ProviderId, config.TimeoutS);
        }
        catch (UriFormatException exception)
        {
            throw new ConfigException(
                "The OpenAI-compatible provider configuration is invalid.",
                config.ProviderId,
                "The configured base URL is invalid.",
                nativeInner: exception);
        }
        catch (ArgumentException exception)
        {
            throw new ConfigException(
                "The OpenAI-compatible provider configuration is invalid.",
                config.ProviderId,
                "The configured base URL or headers are invalid.",
                nativeInner: exception);
        }
    }

    public IAsyncEnumerable<AdapterEvent> GenerateAsync(
        WireRequest request,
        CancellationToken cancellationToken = default) =>
        GenerateIterator(request, cancellationToken);

    public async ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(
        CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        using var timeout = CreateLifecycleTimeout(cancellationToken);
        using var message = CreateModelsRequest();
        HttpResponseMessage? response = null;
        Stream? responseStream = null;
        try
        {
            response = await SendAsync(message, "discover", timeout.Token).ConfigureAwait(false);
            responseStream = await OpenResponseStreamAsync(response.Content, "discover", timeout.Token).ConfigureAwait(false);
            var body = await ReadLifecycleResponseBytesAsync(responseStream, "discover", timeout.Token).ConfigureAwait(false);
            if ((int)response.StatusCode >= 400)
            {
                throw HttpFailure(response, body, "discover");
            }

            return ParseDiscoveredModels(body);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            var callerIdentity = CancellationIdentityContext.Resolve(cancellationToken);
            throw new OperationCanceledException(
                callerIdentity.IsCancellationRequested ? callerIdentity : cancellationToken);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested && timeout.IsCancellationRequested)
        {
            throw LifecycleTimeout();
        }
        finally
        {
            try
            {
                if (responseStream is not null)
                {
                    await DisposeResponseStreamAsync(responseStream, "discover").ConfigureAwait(false);
                }
            }
            finally
            {
                DisposeResponse(response, "discover");
            }
        }
    }

    public async ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        using var timeout = CreateLifecycleTimeout(cancellationToken);
        using var message = CreateModelsRequest();
        HttpResponseMessage? response = null;
        Stream? responseStream = null;
        try
        {
            response = await SendAsync(message, "discover", timeout.Token).ConfigureAwait(false);
            responseStream = await OpenResponseStreamAsync(response.Content, "discover", timeout.Token).ConfigureAwait(false);
            await ReadLifecycleResponseBytesAsync(responseStream, "discover", timeout.Token).ConfigureAwait(false);
            return (int)response.StatusCode < 400
                ? new Health(true)
                : new Health(false, $"HTTP {(int)response.StatusCode}");
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            var callerIdentity = CancellationIdentityContext.Resolve(cancellationToken);
            throw new OperationCanceledException(
                callerIdentity.IsCancellationRequested ? callerIdentity : cancellationToken);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested && timeout.IsCancellationRequested)
        {
            return new Health(false, "The provider request timed out.");
        }
        catch (TransportException exception)
        {
            return new Health(false, BoundHealthDetail(exception.Detail ?? exception.Message));
        }
        finally
        {
            try
            {
                if (responseStream is not null)
                {
                    await DisposeResponseStreamAsync(responseStream, "discover").ConfigureAwait(false);
                }
            }
            finally
            {
                DisposeResponse(response, "discover");
            }
        }
    }

    public ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) == 0)
        {
            _client.Dispose();
        }

        return ValueTask.CompletedTask;
    }

    private async IAsyncEnumerable<AdapterEvent> GenerateIterator(
        WireRequest request,
        [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        ThrowIfDisposed();

        using var message = CreateRequest(request);
        HttpResponseMessage? response = null;
        Stream? responseStream = null;
        try
        {
            response = await SendAsync(message, "generate", cancellationToken).ConfigureAwait(false);
            responseStream = await OpenResponseStreamAsync(response.Content, "generate", cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                var errorBytes = await ReadResponseBytesAsync(
                    responseStream,
                    request.MaxResponseBytes,
                    "generate",
                    cancellationToken).ConfigureAwait(false);
                throw HttpFailure(response, errorBytes, "generate");
            }

            if (request.Stream)
            {
                await foreach (var adapterEvent in ReadSseAsync(
                    responseStream,
                    request.MaxResponseBytes,
                    cancellationToken).ConfigureAwait(false))
                {
                    yield return adapterEvent;
                }

                yield break;
            }

            var body = await ReadResponseBytesAsync(
                responseStream,
                request.MaxResponseBytes,
                "generate",
                cancellationToken).ConfigureAwait(false);
            foreach (var adapterEvent in ReadBuffered(body))
            {
                yield return adapterEvent;
            }
        }
        finally
        {
            try
            {
                if (responseStream is not null)
                {
                    await DisposeResponseStreamAsync(
                        responseStream,
                        request.Stream ? "stream" : "generate").ConfigureAwait(false);
                }
            }
            finally
            {
                DisposeResponse(response, request.Stream ? "stream" : "generate");
            }
        }
    }

    private HttpRequestMessage CreateRequest(WireRequest request)
    {
        var payload = request.UsesModernSchema ? JsonWriter.WriteModern(CreatePayload(request)) : JsonWriter.Write(CreatePayload(request));
        var content = new ByteArrayContent(Encoding.UTF8.GetBytes(payload));
        content.Headers.ContentType = new MediaTypeHeaderValue("application/json");

        var message = new HttpRequestMessage(HttpMethod.Post, _endpoint)
        {
            Content = content,
        };
        ApplyHeaders(message, content, _headers);

        if (!string.IsNullOrEmpty(_apiKey) && !message.Headers.Contains("Authorization"))
        {
            message.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);
        }

        return message;
    }

    private HttpRequestMessage CreateModelsRequest()
    {
        var content = new ByteArrayContent([]);
        content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
        var message = new HttpRequestMessage(HttpMethod.Get, _modelsEndpoint)
        {
            Content = content,
        };
        ApplyHeaders(message, content, _headers);
        if (!string.IsNullOrEmpty(_apiKey) && !message.Headers.Contains("Authorization"))
        {
            message.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);
        }

        return message;
    }

    private static void ValidateHeaders(IReadOnlyDictionary<string, string> headers)
    {
        using var message = new HttpRequestMessage();
        using var content = new ByteArrayContent([]);
        ApplyHeaders(
            message,
            content,
            headers.Select(static header => new KeyValuePair<string, string>(header.Key, header.Value)));
    }

    private static void ApplyHeaders(
        HttpRequestMessage message,
        HttpContent content,
        IEnumerable<KeyValuePair<string, string>> headers)
    {
        foreach (var header in headers)
        {
            if (string.Equals(header.Key, "Authorization", StringComparison.OrdinalIgnoreCase))
            {
                message.Headers.Remove("Authorization");
            }

            if (string.Equals(header.Key, "Content-Type", StringComparison.OrdinalIgnoreCase))
            {
                content.Headers.Remove("Content-Type");
            }

            if (!message.Headers.TryAddWithoutValidation(header.Key, header.Value) &&
                !content.Headers.TryAddWithoutValidation(header.Key, header.Value))
            {
                throw new ArgumentException("The configured HTTP header is invalid.", nameof(headers));
            }
        }
    }

    private JsonObject CreatePayload(WireRequest request)
    {
        var properties = new List<JsonProperty>
        {
            new("model", new JsonString(request.Model)),
            new("messages", new JsonArray(request.Messages.Select(CreateMessage))),
        };
        AddSampling(properties, request.Sampling);
        if (request.UsesModernSchema)
        {
            if (request.Mechanism == "json_schema" && request.Schema is not null)
            {
                properties.Add(new JsonProperty("response_format", new JsonObject([
                    new JsonProperty("type", new JsonString("json_schema")),
                    new JsonProperty("json_schema", new JsonObject([
                        new JsonProperty("name", new JsonString(request.SchemaName)),
                        new JsonProperty("schema", request.Schema),
                        new JsonProperty("strict", new JsonBoolean(false)),
                    ])),
                ])));
            }
            else if (request.Mechanism == "json_mode")
            {
                properties.Add(new JsonProperty("response_format", new JsonObject([
                    new JsonProperty("type", new JsonString("json_object")),
                ])));
            }
        }
        if (request.Stream)
        {
            properties.Add(new JsonProperty("stream", new JsonBoolean(true)));
            properties.Add(new JsonProperty("stream_options", new JsonObject([
                new JsonProperty("include_usage", new JsonBoolean(true)),
            ])));
        }

        return new JsonObject(properties);
    }

    private JsonObject CreateMessage(Message message)
    {
        var content = new StringBuilder();
        foreach (var part in message.Content)
        {
            if (part is not Text textPart)
            {
            throw ProviderException.Create(
                "The OpenAI-compatible chat adapter supports text message content only.",
                "unsupported_input",
                retryable: false,
                phase: "generate",
                provider: _providerId);
            }

            content.Append(textPart.Value);
        }

        return new JsonObject([
            new JsonProperty("role", new JsonString(message.Role)),
            new JsonProperty("content", new JsonString(content.ToString())),
        ]);
    }

    private static void AddSampling(List<JsonProperty> properties, Sampling sampling)
    {
        if (sampling.Temperature is { } temperature)
        {
            properties.Add(new JsonProperty("temperature", new JsonNumber(temperature)));
        }

        if (sampling.TopP is { } topP)
        {
            properties.Add(new JsonProperty("top_p", new JsonNumber(topP)));
        }

        if (sampling.MaxOutputTokens is { } maxTokens)
        {
            properties.Add(new JsonProperty("max_tokens", new JsonInteger(new BigInteger(maxTokens))));
        }

        if (sampling.Stop is { Count: > 0 } stop)
        {
            properties.Add(new JsonProperty("stop", new JsonArray(stop.Select(static value => (JsonValue)new JsonString(value)))));
        }

        if (sampling.Seed is { } seed)
        {
            properties.Add(new JsonProperty("seed", new JsonInteger(new BigInteger(seed))));
        }

        if (sampling.PresencePenalty is { } presencePenalty)
        {
            properties.Add(new JsonProperty("presence_penalty", new JsonNumber(presencePenalty)));
        }

        if (sampling.FrequencyPenalty is { } frequencyPenalty)
        {
            properties.Add(new JsonProperty("frequency_penalty", new JsonNumber(frequencyPenalty)));
        }
    }

    private IEnumerable<AdapterEvent> ReadBuffered(byte[] body)
    {
        var root = ReadObject(body);
        var choice = FirstChoice(root);
        var content = OptionalString(RequiredObject(choice, "message"), "content") ?? string.Empty;
        var finishReason = OptionalString(choice, "finish_reason") ?? "stop";
        var usage = OptionalUsage(root);

        if (content.Length > 0)
        {
            yield return new AdapterTextDelta(content);
        }

        if (usage is not null)
        {
            yield return new AdapterUsage(usage);
        }

        yield return new AdapterFinal(finishReason, usage);
    }

    private async IAsyncEnumerable<AdapterEvent> ReadSseAsync(
        Stream stream,
        int maxResponseBytes,
        [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        var buffer = new byte[4096];
        var line = new List<byte>();
        var dataLines = new List<string>();
        long bytesRead = 0;
        Usage? finalUsage = null;
        string? finishReason = null;

        while (true)
        {
            var count = await ReadChunkAsync(stream, buffer, "stream", cancellationToken).ConfigureAwait(false);
            if (count == 0)
            {
                break;
            }

            bytesRead += count;
            if (bytesRead > maxResponseBytes)
            {
                throw ProtocolFailure("The OpenAI-compatible response exceeded its byte limit.");
            }

            for (var index = 0; index < count; index++)
            {
                var value = buffer[index];
                if (value != (byte)'\n')
                {
                    line.Add(value);
                    continue;
                }

                if (line.Count > 0 && line[^1] == (byte)'\r')
                {
                    line.RemoveAt(line.Count - 1);
                }

                var text = DecodeLine(line);
                line.Clear();
                if (text.Length != 0)
                {
                    if (text.StartsWith("data:", StringComparison.Ordinal))
                    {
                        var data = text[5..];
                        dataLines.Add(data.StartsWith(' ') ? data[1..] : data);
                    }

                    continue;
                }

                if (dataLines.Count == 0)
                {
                    continue;
                }

                var frame = string.Join("\n", dataLines);
                dataLines.Clear();
                if (frame == "[DONE]")
                {
                    yield return new AdapterFinal(finishReason ?? "stop", finalUsage);
                    yield break;
                }

                var chunk = ReadObject(StrictUtf8.GetBytes(frame));
                var choice = OptionalFirstChoice(chunk);
                if (choice is not null)
                {
                    var delta = OptionalObject(choice, "delta");
                    var content = delta is null ? null : OptionalString(delta, "content");
                    if (content is { Length: > 0 })
                    {
                        yield return new AdapterTextDelta(content);
                    }

                    finishReason ??= OptionalString(choice, "finish_reason");
                }

                var usage = OptionalUsage(chunk);
                if (usage is not null)
                {
                    finalUsage = usage;
                    yield return new AdapterUsage(usage);
                }
            }
        }

        throw ProtocolFailure("The OpenAI-compatible event stream ended without a DONE sentinel.");
    }

    private async Task<byte[]> ReadResponseBytesAsync(
        Stream stream,
        int maxResponseBytes,
        string phase,
        CancellationToken cancellationToken)
    {
        var buffer = new byte[4096];
        var body = new MemoryStream();
        long total = 0;
        while (true)
        {
            var read = await ReadChunkAsync(stream, buffer, phase, cancellationToken).ConfigureAwait(false);
            if (read == 0)
            {
                return body.ToArray();
            }

            total += read;
            if (total > maxResponseBytes)
            {
                throw ProtocolFailure("The OpenAI-compatible response exceeded its byte limit.");
            }

            await body.WriteAsync(buffer.AsMemory(0, read), cancellationToken).ConfigureAwait(false);
        }
    }

    private async Task<byte[]> ReadLifecycleResponseBytesAsync(
        Stream stream,
        string phase,
        CancellationToken cancellationToken)
    {
        var buffer = new byte[4096];
        using var body = new MemoryStream();
        while (true)
        {
            var read = await ReadChunkAsync(stream, buffer, phase, cancellationToken).ConfigureAwait(false);
            if (read == 0)
            {
                return body.ToArray();
            }

            await body.WriteAsync(buffer.AsMemory(0, read), cancellationToken).ConfigureAwait(false);
        }
    }

    private async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage message,
        string phase,
        CancellationToken cancellationToken)
    {
        try
        {
            return await _client.SendAsync(
                message,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken).ConfigureAwait(false);
        }
        catch (HttpRequestException exception)
        {
            throw TransportFailure("The OpenAI-compatible request could not be sent.", phase, exception);
        }
    }

    private async Task<Stream> OpenResponseStreamAsync(
        HttpContent content,
        string phase,
        CancellationToken cancellationToken)
    {
        try
        {
            return await content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (HttpRequestException exception)
        {
            throw TransportFailure("The OpenAI-compatible response could not be opened.", phase, exception);
        }
        catch (IOException exception)
        {
            throw TransportFailure("The OpenAI-compatible response could not be opened.", phase, exception);
        }
    }

    private async Task DisposeResponseStreamAsync(Stream stream, string phase)
    {
        try
        {
            await stream.DisposeAsync().ConfigureAwait(false);
        }
        catch (IOException exception)
        {
            throw TransportFailure("The OpenAI-compatible response could not be closed.", phase, exception);
        }
        catch (HttpRequestException exception)
        {
            throw TransportFailure("The OpenAI-compatible response could not be closed.", phase, exception);
        }
    }

    private void DisposeResponse(HttpResponseMessage? response, string phase)
    {
        if (response is null)
        {
            return;
        }

        try
        {
            response.Dispose();
        }
        catch (IOException exception)
        {
            throw TransportFailure("The OpenAI-compatible response could not be closed.", phase, exception);
        }
        catch (HttpRequestException exception)
        {
            throw TransportFailure("The OpenAI-compatible response could not be closed.", phase, exception);
        }
    }

    private async Task<int> ReadChunkAsync(
        Stream stream,
        byte[] buffer,
        string phase,
        CancellationToken cancellationToken)
    {
        try
        {
            return await stream.ReadAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false);
        }
        catch (IOException exception)
        {
            throw TransportFailure("The OpenAI-compatible response could not be read.", phase, exception);
        }
        catch (HttpRequestException exception)
        {
            throw TransportFailure("The OpenAI-compatible response could not be read.", phase, exception);
        }
    }

    private ProviderException HttpFailure(HttpResponseMessage response, byte[] errorBytes, string phase)
    {
        var (category, retryable) = response.StatusCode switch
        {
            HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden => ("auth", false),
            HttpStatusCode.NotFound => ("model_not_found", false),
            (HttpStatusCode)429 => ("rate_limit", true),
            (HttpStatusCode)408 or (HttpStatusCode)409 or (HttpStatusCode)425 => ("transport", true),
            _ when (int)response.StatusCode >= 500 => ("provider_unavailable", true),
            _ => ("invalid_request", false),
        };
        _ = errorBytes;
        return ProviderException.Create(
            $"The OpenAI-compatible service returned HTTP {(int)response.StatusCode}.",
            category,
            retryable,
            phase,
            retryAfterS: RetryAfter(response.Headers.RetryAfter),
            httpStatus: (int)response.StatusCode,
            provider: _providerId);
    }

    private static double? RetryAfter(RetryConditionHeaderValue? retryAfter)
    {
        if (retryAfter?.Delta is { } delta)
        {
            return Math.Max(0, delta.TotalSeconds);
        }

        if (retryAfter?.Date is { } date)
        {
            return Math.Max(0, (date - DateTimeOffset.UtcNow).TotalSeconds);
        }

        return null;
    }

    private ProviderException TransportFailure(string message, string phase, Exception exception) =>
        ProviderException.Create(message, "transport", retryable: true, phase, provider: _providerId, nativeInner: exception);

    private ProviderException LifecycleTimeout() =>
        ProviderException.Create(
            "The provider request timed out.",
            "transport",
            retryable: true,
            phase: "discover",
            provider: _providerId);

    private ProviderException ProtocolFailure(string message) =>
        ProviderException.Create(message, "stream_protocol", retryable: false, phase: "stream", provider: _providerId);

    private CancellationTokenSource CreateLifecycleTimeout(CancellationToken cancellationToken)
    {
        var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(_timeout);
        return timeout;
    }

    private IReadOnlyList<DiscoveredModel> ParseDiscoveredModels(byte[] body)
    {
        var payload = JsonReader.Read(body);
        var entries = payload is JsonObject root && root.TryGetValue("data", out var data)
            ? data
            : payload;
        if (entries is not JsonArray array)
        {
            return Array.Empty<DiscoveredModel>();
        }

        return Array.AsReadOnly(array.Items
            .OfType<JsonObject>()
            .Select(static entry => new DiscoveredModel(PythonModelId(entry)))
            .ToArray());
    }

    private static string PythonModelId(JsonObject entry)
    {
        if (!entry.TryGetValue("id", out var value))
        {
            return string.Empty;
        }

        return value switch
        {
            JsonString text => text.Value,
            JsonNull => "None",
            JsonBoolean boolean => boolean.Value ? "True" : "False",
            JsonInteger integer => integer.Value.ToString(System.Globalization.CultureInfo.InvariantCulture),
            JsonNumber number => number.Value.ToString("R", System.Globalization.CultureInfo.InvariantCulture),
            JsonArray or JsonObject => JsonWriter.Write(value),
            _ => throw new InvalidOperationException("The JSON value is not supported."),
        };
    }

    private static string BoundHealthDetail(string detail)
    {
        var redacted = Redaction.Redact(detail);
        var runes = redacted.EnumerateRunes().Take(200).Select(static rune => rune.ToString());
        return string.Concat(runes);
    }

    private JsonObject ReadObject(ReadOnlySpan<byte> bytes)
    {
        try
        {
            return JsonReader.Read(bytes) as JsonObject
                ?? throw ProtocolFailure("The OpenAI-compatible response is not a JSON object.");
        }
        catch (FormatException exception)
        {
            throw ProviderException.Create(
                "The OpenAI-compatible response contains invalid JSON.",
                "stream_protocol",
                retryable: false,
                phase: "stream",
                provider: _providerId,
                nativeInner: exception);
        }
    }

    private JsonObject FirstChoice(JsonObject root)
    {
        if (!root.TryGetValue("choices", out var value) || value is not JsonArray { Items.Count: > 0 } choices ||
            choices.Items[0] is not JsonObject choice)
        {
            throw ProtocolFailure("The OpenAI-compatible response has no completion choice.");
        }

        return choice;
    }

    private JsonObject? OptionalFirstChoice(JsonObject root)
    {
        if (!root.TryGetValue("choices", out var value))
        {
            return null;
        }

        if (value is not JsonArray choices)
        {
            throw ProtocolFailure("The OpenAI-compatible event has invalid choices.");
        }

        if (choices.Items.Count == 0)
        {
            return null;
        }

        return choices.Items[0] as JsonObject
            ?? throw ProtocolFailure("The OpenAI-compatible event choice is invalid.");
    }

    private JsonObject RequiredObject(JsonObject source, string name) =>
        OptionalObject(source, name) ?? throw ProtocolFailure($"The OpenAI-compatible response is missing {name}.");

    private JsonObject? OptionalObject(JsonObject source, string name)
    {
        if (!source.TryGetValue(name, out var value) || value is JsonNull)
        {
            return null;
        }

        return value as JsonObject
            ?? throw ProtocolFailure($"The OpenAI-compatible response has invalid {name}.");
    }

    private string RequiredString(JsonObject source, string name) =>
        OptionalString(source, name) ?? throw ProtocolFailure($"The OpenAI-compatible response is missing {name}.");

    private string? OptionalString(JsonObject source, string name)
    {
        if (!source.TryGetValue(name, out var value) || value is JsonNull)
        {
            return null;
        }

        return value is JsonString text
            ? text.Value
            : throw ProtocolFailure($"The OpenAI-compatible response has invalid {name}.");
    }

    private Usage? OptionalUsage(JsonObject source)
    {
        if (!source.TryGetValue("usage", out var value) || value is JsonNull)
        {
            return null;
        }

        if (value is not JsonObject usage)
        {
            throw ProtocolFailure("The OpenAI-compatible response has invalid usage.");
        }

        return new Usage(
            InputTokens: OptionalLong(usage, "prompt_tokens"),
            OutputTokens: OptionalLong(usage, "completion_tokens"),
            TotalTokens: OptionalLong(usage, "total_tokens"),
            CacheReadTokens: NestedLong(usage, "prompt_tokens_details", "cached_tokens"),
            ReasoningTokens: NestedLong(usage, "completion_tokens_details", "reasoning_tokens"));
    }

    private long? NestedLong(JsonObject source, string objectName, string propertyName)
    {
        var nested = OptionalObject(source, objectName);
        return nested is null ? null : OptionalLong(nested, propertyName);
    }

    private long? OptionalLong(JsonObject source, string name)
    {
        if (!source.TryGetValue(name, out var value) || value is JsonNull)
        {
            return null;
        }

        if (value is JsonInteger { Value: var integer } && integer >= long.MinValue && integer <= long.MaxValue)
        {
            return (long)integer;
        }

        throw ProtocolFailure($"The OpenAI-compatible response has invalid {name}.");
    }

    private string DecodeLine(List<byte> line)
    {
        try
        {
            return StrictUtf8.GetString(line.ToArray());
        }
        catch (DecoderFallbackException exception)
        {
            throw ProviderException.Create(
                "The OpenAI-compatible event stream is not valid UTF-8.",
                "stream_protocol",
                retryable: false,
                phase: "stream",
                provider: _providerId,
                nativeInner: exception);
        }
    }

    private static Uri BuildEndpoint(Uri baseUrl, string suffix)
    {
        var text = baseUrl.AbsoluteUri.TrimEnd('/');
        return new Uri(text + "/" + suffix, UriKind.Absolute);
    }

    private void ThrowIfDisposed()
    {
        if (Volatile.Read(ref _disposed) != 0)
        {
            throw new ObjectDisposedException(nameof(OpenAIChatAdapter));
        }
    }
}
