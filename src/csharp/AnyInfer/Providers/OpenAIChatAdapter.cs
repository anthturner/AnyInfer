using AnyInfer.Json;
using System.Net;
using System.Net.Http.Headers;
using System.Numerics;
using System.Runtime.CompilerServices;
using System.Text;

namespace AnyInfer.Providers;

/// <summary>Translates the bounded OpenAI-compatible chat-completions dialect.</summary>
internal sealed class OpenAIChatAdapter : IProviderAdapter
{
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);
    private readonly HttpClient _client;
    private readonly Uri _endpoint;
    private readonly string _apiKey;
    private readonly IReadOnlyList<KeyValuePair<string, string>> _headers;
    private int _disposed;

    internal OpenAIChatAdapter(
        Uri baseUrl,
        string apiKey,
        IReadOnlyDictionary<string, string>? headers = null,
        HttpMessageHandler? handler = null)
    {
        ArgumentNullException.ThrowIfNull(baseUrl);
        if (!baseUrl.IsAbsoluteUri)
        {
            throw new ArgumentException("The OpenAI-compatible base URL must be absolute.", nameof(baseUrl));
        }

        ArgumentException.ThrowIfNullOrEmpty(apiKey);
        _endpoint = BuildEndpoint(baseUrl);
        _apiKey = apiKey;
        _headers = (headers ?? new Dictionary<string, string>())
            .Select(static header => new KeyValuePair<string, string>(header.Key, header.Value))
            .ToArray();
        var ownedHandler = handler ?? new HttpClientHandler
        {
            AllowAutoRedirect = false,
        };
        _client = new HttpClient(ownedHandler, disposeHandler: true)
        {
            Timeout = Timeout.InfiniteTimeSpan,
        };
    }

    public IAsyncEnumerable<AdapterEvent> GenerateAsync(
        WireRequest request,
        CancellationToken cancellationToken = default) =>
        GenerateIterator(request, cancellationToken);

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
            response = await SendAsync(message, cancellationToken).ConfigureAwait(false);
            responseStream = await OpenResponseStreamAsync(response.Content, cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                var errorBytes = await ReadResponseBytesAsync(
                    responseStream,
                    request.MaxResponseBytes,
                    "generate",
                    cancellationToken).ConfigureAwait(false);
                throw HttpFailure(response, errorBytes);
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
        var payload = JsonWriter.Write(CreatePayload(request));
        var content = new ByteArrayContent(Encoding.UTF8.GetBytes(payload));
        content.Headers.ContentType = new MediaTypeHeaderValue("application/json");

        var message = new HttpRequestMessage(HttpMethod.Post, _endpoint)
        {
            Content = content,
        };
        message.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);
        foreach (var header in _headers)
        {
            if (!message.Headers.TryAddWithoutValidation(header.Key, header.Value))
            {
                message.Dispose();
                throw new ArgumentException("The configured HTTP header is invalid.", nameof(_headers));
            }
        }

        return message;
    }

    private static JsonObject CreatePayload(WireRequest request)
    {
        var properties = new List<JsonProperty>
        {
            new("model", new JsonString(request.Model)),
            new("messages", new JsonArray(request.Messages.Select(CreateMessage))),
        };
        AddSampling(properties, request.Sampling);
        if (request.Stream)
        {
            properties.Add(new JsonProperty("stream", new JsonBoolean(true)));
            properties.Add(new JsonProperty("stream_options", new JsonObject([
                new JsonProperty("include_usage", new JsonBoolean(true)),
            ])));
        }

        return new JsonObject(properties);
    }

    private static JsonObject CreateMessage(Message message)
    {
        var content = new StringBuilder();
        foreach (var part in message.Content)
        {
            if (part is not TextPart textPart)
            {
                throw new ProviderException(
                    "The OpenAI-compatible chat adapter supports text message content only.",
                    "unsupported_input",
                    retryable: false,
                    phase: "generate");
            }

            content.Append(textPart.Text);
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

    private static IEnumerable<AdapterEvent> ReadBuffered(byte[] body)
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

    private static async IAsyncEnumerable<AdapterEvent> ReadSseAsync(
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

    private static async Task<byte[]> ReadResponseBytesAsync(
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

    private async Task<HttpResponseMessage> SendAsync(HttpRequestMessage message, CancellationToken cancellationToken)
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
            throw TransportFailure("The OpenAI-compatible request could not be sent.", "generate", exception);
        }
    }

    private static async Task<Stream> OpenResponseStreamAsync(HttpContent content, CancellationToken cancellationToken)
    {
        try
        {
            return await content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (HttpRequestException exception)
        {
            throw TransportFailure("The OpenAI-compatible response could not be opened.", "generate", exception);
        }
        catch (IOException exception)
        {
            throw TransportFailure("The OpenAI-compatible response could not be opened.", "generate", exception);
        }
    }

    private static async Task DisposeResponseStreamAsync(Stream stream, string phase)
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

    private static void DisposeResponse(HttpResponseMessage? response, string phase)
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

    private static async Task<int> ReadChunkAsync(
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

    private static ProviderException HttpFailure(HttpResponseMessage response, byte[] errorBytes)
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
        return new ProviderException(
            $"The OpenAI-compatible service returned HTTP {(int)response.StatusCode}.",
            category,
            retryable,
            phase: "generate",
            retryAfterS: RetryAfter(response.Headers.RetryAfter),
            httpStatus: (int)response.StatusCode,
            provider: "openai-compat");
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

    private static ProviderException TransportFailure(string message, string phase, Exception exception) =>
        new(message, "transport", retryable: true, phase, provider: "openai-compat", nativeInner: exception);

    private static ProviderException ProtocolFailure(string message) =>
        new(message, "stream_protocol", retryable: false, phase: "stream", provider: "openai-compat");

    private static JsonObject ReadObject(ReadOnlySpan<byte> bytes)
    {
        try
        {
            return JsonReader.Read(bytes) as JsonObject
                ?? throw ProtocolFailure("The OpenAI-compatible response is not a JSON object.");
        }
        catch (FormatException exception)
        {
            throw new ProviderException(
                "The OpenAI-compatible response contains invalid JSON.",
                "stream_protocol",
                retryable: false,
                phase: "stream",
                provider: "openai-compat",
                nativeInner: exception);
        }
    }

    private static JsonObject FirstChoice(JsonObject root)
    {
        if (!root.TryGetValue("choices", out var value) || value is not JsonArray { Items.Count: > 0 } choices ||
            choices.Items[0] is not JsonObject choice)
        {
            throw ProtocolFailure("The OpenAI-compatible response has no completion choice.");
        }

        return choice;
    }

    private static JsonObject? OptionalFirstChoice(JsonObject root)
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

    private static JsonObject RequiredObject(JsonObject source, string name) =>
        OptionalObject(source, name) ?? throw ProtocolFailure($"The OpenAI-compatible response is missing {name}.");

    private static JsonObject? OptionalObject(JsonObject source, string name)
    {
        if (!source.TryGetValue(name, out var value) || value is JsonNull)
        {
            return null;
        }

        return value as JsonObject
            ?? throw ProtocolFailure($"The OpenAI-compatible response has invalid {name}.");
    }

    private static string RequiredString(JsonObject source, string name) =>
        OptionalString(source, name) ?? throw ProtocolFailure($"The OpenAI-compatible response is missing {name}.");

    private static string? OptionalString(JsonObject source, string name)
    {
        if (!source.TryGetValue(name, out var value) || value is JsonNull)
        {
            return null;
        }

        return value is JsonString text
            ? text.Value
            : throw ProtocolFailure($"The OpenAI-compatible response has invalid {name}.");
    }

    private static Usage? OptionalUsage(JsonObject source)
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

    private static long? NestedLong(JsonObject source, string objectName, string propertyName)
    {
        var nested = OptionalObject(source, objectName);
        return nested is null ? null : OptionalLong(nested, propertyName);
    }

    private static long? OptionalLong(JsonObject source, string name)
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

    private static string DecodeLine(List<byte> line)
    {
        try
        {
            return StrictUtf8.GetString(line.ToArray());
        }
        catch (DecoderFallbackException exception)
        {
            throw new ProviderException(
                "The OpenAI-compatible event stream is not valid UTF-8.",
                "stream_protocol",
                retryable: false,
                phase: "stream",
                provider: "openai-compat",
                nativeInner: exception);
        }
    }

    private static Uri BuildEndpoint(Uri baseUrl)
    {
        var text = baseUrl.AbsoluteUri.TrimEnd('/');
        var suffix = baseUrl.AbsolutePath.TrimEnd('/').EndsWith("/v1", StringComparison.OrdinalIgnoreCase)
            ? "/chat/completions"
            : "/v1/chat/completions";
        return new Uri(text + suffix, UriKind.Absolute);
    }

    private void ThrowIfDisposed()
    {
        if (Volatile.Read(ref _disposed) != 0)
        {
            throw new ObjectDisposedException(nameof(OpenAIChatAdapter));
        }
    }
}
