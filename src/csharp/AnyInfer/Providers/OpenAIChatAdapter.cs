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
    private readonly OpenAICompatDialectOptions _dialect;
    private int _disposed;

    internal OpenAIChatAdapter(
        Uri baseUrl,
        string? apiKey,
        IReadOnlyDictionary<string, string>? headers = null,
        HttpMessageHandler? handler = null,
        string providerId = "openai-compat",
        double timeoutS = 120,
        bool handlerOwnedByPool = false,
        OpenAICompatDialectOptions? dialect = null)
    {
        ArgumentNullException.ThrowIfNull(baseUrl);
        ValidateBaseUrl(baseUrl, nameof(baseUrl));

        _endpoint = BuildEndpoint(baseUrl, "chat/completions");
        _modelsEndpoint = BuildEndpoint(baseUrl, "models");
        _apiKey = apiKey;
        _providerId = ProviderSettings.NormalizeId(providerId, nameof(providerId));
        _headers = (headers ?? new Dictionary<string, string>())
            .Select(static header => new KeyValuePair<string, string>(header.Key, header.Value))
            .ToArray();
        _timeout = TimeSpan.FromSeconds(timeoutS);
        _dialect = dialect ?? new OpenAICompatDialectOptions();
        var ownedHandler = handler ?? ConnectionHandlerFactory.CreateDefault(CancellationToken.None);
        _client = new HttpClient(ownedHandler, disposeHandler: handler is null || !handlerOwnedByPool)
        {
            Timeout = Timeout.InfiniteTimeSpan,
        };
    }

    internal static IProviderAdapter Create(ProviderConfig config, CancellationToken cancellationToken) =>
        Create(config, new OpenAICompatDialectOptions(), cancellationToken);

    internal static IProviderAdapter Create(
        ProviderConfig config,
        OpenAICompatDialectOptions dialect,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(config);
        ArgumentNullException.ThrowIfNull(dialect);
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
            var parsedBaseUrl = new Uri(baseUrl, UriKind.Absolute);
            ValidateBaseUrl(parsedBaseUrl, nameof(baseUrl));
            ValidateHeaders(config.Headers);
            var handler = config.Transport ?? ConnectionHandlerFactory.CreateOwned(config, cancellationToken);
            try
            {
                return new OpenAIChatAdapter(
                    parsedBaseUrl,
                    config.ApiKey,
                    config.Headers,
                    handler,
                    config.ProviderId,
                    config.TimeoutS,
                    config.Transport is not null && config.TransportOwnedByPool,
                    dialect);
            }
            catch
            {
                if (config.Transport is null)
                {
                    handler.Dispose();
                }

                throw;
            }
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

    private static void ValidateBaseUrl(Uri baseUrl, string parameterName)
    {
        if (!baseUrl.IsAbsoluteUri ||
            baseUrl.Scheme is not ("http" or "https") ||
            !string.IsNullOrEmpty(baseUrl.UserInfo) ||
            !string.IsNullOrEmpty(baseUrl.Query) ||
            !string.IsNullOrEmpty(baseUrl.Fragment))
        {
            throw new ArgumentException("The OpenAI-compatible base URL must be an absolute HTTP(S) URL without userinfo, query, or fragment.", parameterName);
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
        if (!_dialect.ModelsListing)
        {
            ThrowIfNoListingCancellation(cancellationToken);
            return Array.Empty<DiscoveredModel>();
        }

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
        if (!_dialect.ModelsListing)
        {
            ThrowIfNoListingCancellation(cancellationToken);
            return new Health(true, "no cheap readiness probe; failures surface on use");
        }

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
        if (request.UsesModernSchema && string.Equals(request.Mechanism, "grammar", StringComparison.Ordinal))
        {
            throw new UnsupportedInputException(
                "The OpenAI-compatible adapter does not support grammar structured output.",
                provider: _providerId,
                phase: "generate");
        }

        using var message = CreateRequest(request);
        HttpResponseMessage? response = null;
        Stream? responseStream = null;
        try
        {
            response = await SendAsync(
                message,
                "generate",
                cancellationToken,
                request.UsesModernSchema).ConfigureAwait(false);
            responseStream = await OpenResponseStreamAsync(
                response.Content,
                "generate",
                cancellationToken,
                request.UsesModernSchema).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                var errorBytes = await ReadResponseBytesAsync(
                    responseStream,
                    request.MaxResponseBytes,
                    "generate",
                    cancellationToken,
                    request.UsesModernSchema).ConfigureAwait(false);
                throw HttpFailure(response, errorBytes, "generate", request.UsesModernSchema);
            }

            if (request.Stream &&
                (!request.UsesModernSchema ||
                 string.Equals(
                     response.Content.Headers.ContentType?.MediaType,
                     "text/event-stream",
                     StringComparison.OrdinalIgnoreCase)))
            {
                await foreach (var adapterEvent in ReadSseAsync(
                    responseStream,
                    request.MaxResponseBytes,
                    request.UsesModernSchema || request.Tools.Count > 0,
                    cancellationToken,
                    request.UsesModernSchema).ConfigureAwait(false))
                {
                    yield return adapterEvent;
                }

                yield break;
            }

            var body = await ReadResponseBytesAsync(
                responseStream,
                request.MaxResponseBytes,
                request.Stream ? "stream" : "generate",
                cancellationToken,
                request.UsesModernSchema).ConfigureAwait(false);
            foreach (var adapterEvent in ReadBuffered(
                body,
                request.UsesModernSchema || request.Tools.Count > 0))
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
        var payload = request.UsesModernSchema || request.Tools.Count > 0
            ? JsonWriter.WriteModern(CreatePayload(request))
            : JsonWriter.Write(CreatePayload(request));
        var content = new ByteArrayContent(Encoding.UTF8.GetBytes(payload));
        content.Headers.ContentType = new MediaTypeHeaderValue("application/json");

        var message = new HttpRequestMessage(HttpMethod.Post, _endpoint)
        {
            Content = content,
        };
        ApplyHeaders(message, content, _headers);

        if (request.UsesModernSchema && request.Stream)
        {
            message.Headers.Remove("Accept");
            message.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));
        }

        ApplyAuthentication(message);

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
        ApplyAuthentication(message);

        return message;
    }

    private void ApplyAuthentication(HttpRequestMessage message)
    {
        if (string.IsNullOrEmpty(_apiKey))
        {
            return;
        }

        if (_dialect.AuthHeader == "bearer")
        {
            if (!message.Headers.Contains("Authorization"))
            {
                message.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);
            }

            return;
        }

        if (!message.Headers.Contains("x-api-key"))
        {
            message.Headers.TryAddWithoutValidation("x-api-key", _apiKey);
        }
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
                        new JsonProperty("name", new JsonString(request.SchemaName ?? "response")),
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
        if (request.Tools.Count > 0)
        {
            properties.Add(new JsonProperty("tools", new JsonArray(request.Tools.Select(CreateTool))));
            properties.Add(new JsonProperty("tool_choice", CreateToolChoice(request.ToolChoice)));
        }
        if (request.Stream)
        {
            properties.Add(new JsonProperty("stream", new JsonBoolean(true)));
            properties.Add(new JsonProperty("stream_options", new JsonObject([
                new JsonProperty("include_usage", new JsonBoolean(true)),
            ])));
        }

        if (request.Logprobs is not null)
        {
            properties.Add(new JsonProperty("logprobs", new JsonBoolean(true)));
            if (request.Logprobs > 0)
            {
                properties.Add(new JsonProperty("top_logprobs", new JsonInteger(new BigInteger(request.Logprobs.Value))));
            }
        }

        // The core translates generic reasoning controls before the adapter sees a request.
        // Raw extra options deliberately remain the final overlay, matching Python.
        properties.AddRange(request.ReasoningWire.Properties);
        properties.AddRange(request.ExtraOptions.Properties);

        // Buffered generation must not inherit a caller-supplied stream override. This
        // happens after the extra-options overlay for the same precedence as Python.
        if (!request.Stream)
        {
            properties.RemoveAll(static property => property.Name is "stream" or "stream_options");
        }

        var payload = new JsonObject(properties);
        return _dialect.OutputTokensField == "max_completion_tokens" &&
               payload.TryGetValue("max_tokens", out var maxTokens)
            ? RenameOutputTokens(payload, maxTokens)
            : payload;
    }

    private static JsonObject RenameOutputTokens(JsonObject payload, JsonValue maxTokens)
    {
        var properties = payload.Properties
            .Where(static property => property.Name != "max_tokens")
            .ToList();
        properties.Add(new JsonProperty("max_completion_tokens", maxTokens));
        return new JsonObject(properties);
    }

    private static JsonObject CreateTool(ToolSpec tool) =>
        new([
            new JsonProperty("type", new JsonString("function")),
            new JsonProperty("function", new JsonObject([
                new JsonProperty("name", new JsonString(tool.Name)),
                new JsonProperty("description", new JsonString(tool.Description)),
                new JsonProperty("parameters", tool.Parameters),
            ])),
        ]);

    private static JsonValue CreateToolChoice(string choice) =>
        choice is "auto" or "none" or "required"
            ? new JsonString(choice)
            : new JsonObject([
                new JsonProperty("type", new JsonString("function")),
                new JsonProperty("function", new JsonObject([
                    new JsonProperty("name", new JsonString(choice)),
                ])),
            ]);

    private JsonObject CreateMessage(Message message)
    {
        if (message.Content.OfType<ToolResult>().FirstOrDefault() is { } result)
        {
            return new JsonObject([
                new JsonProperty("role", new JsonString("tool")),
                new JsonProperty("tool_call_id", new JsonString(result.CallId)),
                new JsonProperty("content", new JsonString(result.Content)),
            ]);
        }

        var text = new StringBuilder();
        var calls = new List<ToolCall>();
        var multimodal = message.Content.Any(static part => part is ImagePart or DocumentPart or AudioPart or VideoPart);
        var items = new List<JsonValue>();
        foreach (var part in message.Content)
        {
            if (part is Text textPart)
            {
                text.Append(textPart.Value);
                if (multimodal)
                {
                    items.Add(new JsonObject([
                        new JsonProperty("type", new JsonString("text")),
                        new JsonProperty("text", new JsonString(textPart.Value)),
                    ]));
                }
                continue;
            }

            if (part is ToolCall call)
            {
                calls.Add(call);
                continue;
            }

            if (part is ImagePart image)
            {
                var imageProperties = new List<JsonProperty>
                {
                    new("url", new JsonString(image.Url ?? DataUrl(image.MediaType, image.Data!))),
                };
                if (image.Detail is not null)
                {
                    imageProperties.Add(new JsonProperty("detail", new JsonString(image.Detail)));
                }
                items.Add(new JsonObject([
                    new JsonProperty("type", new JsonString("image_url")),
                    new JsonProperty("image_url", new JsonObject(imageProperties)),
                ]));
                continue;
            }

            if (part is DocumentPart document)
            {
                if (document.Url is not null)
                {
                    throw UnsupportedPart("document URL");
                }
                var fileProperties = new List<JsonProperty>
                {
                    new("file_data", new JsonString(DataUrl(document.MediaType, document.Data!))),
                };
                if (document.Filename is not null)
                {
                    fileProperties.Add(new JsonProperty("filename", new JsonString(document.Filename)));
                }
                items.Add(new JsonObject([
                    new JsonProperty("type", new JsonString("file")),
                    new JsonProperty("file", new JsonObject(fileProperties)),
                ]));
                continue;
            }

            if (part is AudioPart audio)
            {
                items.Add(new JsonObject([
                    new JsonProperty("type", new JsonString("input_audio")),
                    new JsonProperty("input_audio", new JsonObject([
                        new JsonProperty("data", new JsonString(Convert.ToBase64String(audio.Data.ToArray()))),
                        new JsonProperty("format", new JsonString(MediaSubtype(audio.MediaType))),
                    ])),
                ]));
                continue;
            }

            if (part is VideoPart)
            {
                throw UnsupportedPart("video");
            }

            throw UnsupportedPart("content");
        }

        var properties = new List<JsonProperty>
        {
            new JsonProperty("role", new JsonString(message.Role)),
            new JsonProperty(
                "content",
                calls.Count > 0 && text.Length == 0 && !multimodal
                    ? JsonNull.Instance
                    : multimodal ? new JsonArray(items) : new JsonString(text.ToString())),
        };
        if (calls.Count > 0)
        {
            properties.Add(new JsonProperty("tool_calls", new JsonArray(calls.Select(CreateToolCall))));
        }

        return new JsonObject(properties);
    }

    private UnsupportedInputException UnsupportedPart(string modality) => new(
        $"{_providerId} cannot project {modality} input",
        provider: _providerId,
        phase: "generate");

    private static string DataUrl(string mediaType, IReadOnlyList<byte> data) =>
        $"data:{mediaType};base64,{Convert.ToBase64String(data.ToArray())}";

    private static string MediaSubtype(string mediaType)
    {
        var separator = mediaType.IndexOf('/');
        var subtype = separator < 0 ? mediaType : mediaType[(separator + 1)..];
        return string.Equals(subtype, "mpeg", StringComparison.OrdinalIgnoreCase) ? "mp3" : subtype.ToLowerInvariant();
    }

    private static JsonObject CreateToolCall(ToolCall call) => new([
        new JsonProperty("id", new JsonString(call.Id)),
        new JsonProperty("type", new JsonString("function")),
        new JsonProperty("function", new JsonObject([
            new JsonProperty("name", new JsonString(call.Name)),
            new JsonProperty("arguments", new JsonString(JsonWriter.WriteAccounting(call.Arguments, indent: null))),
        ])),
    ]);

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

    private IEnumerable<AdapterEvent> ReadBuffered(
        byte[] body,
        bool toolsEnabled)
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

        if (toolsEnabled)
        {
            foreach (var toolDelta in ReadToolDeltas(RequiredObject(choice, "message")))
            {
                yield return toolDelta;
            }
        }

        if (usage is not null)
        {
            yield return new AdapterUsage(usage);
        }

        yield return new AdapterFinal(
            finishReason,
            usage,
            root,
            logprobs: ReadLogprobs(choice));
    }

    private async IAsyncEnumerable<AdapterEvent> ReadSseAsync(
        Stream stream,
        int maxResponseBytes,
        bool toolsEnabled,
        [EnumeratorCancellation] CancellationToken cancellationToken,
        bool mapModernCancellation)
    {
        var buffer = new byte[4096];
        var line = new List<byte>();
        var dataLines = new List<string>();
        long bytesRead = 0;
        Usage? finalUsage = null;
        string? finishReason = null;
        var logprobs = new List<TokenLogprob>();

        while (true)
        {
            var count = await ReadChunkAsync(
                stream,
                buffer,
                "stream",
                cancellationToken,
                mapModernCancellation).ConfigureAwait(false);
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
                    yield return new AdapterFinal(finishReason ?? "stop", finalUsage, logprobs: logprobs);
                    yield break;
                }

                var chunk = ReadObject(StrictUtf8.GetBytes(frame));
                var choice = OptionalFirstChoice(chunk);
                if (choice is not null)
                {
                    logprobs.AddRange(ReadLogprobs(choice));
                    var delta = OptionalObject(choice, "delta");
                    var content = delta is null ? null : OptionalString(delta, "content");
                    if (content is { Length: > 0 })
                    {
                        yield return new AdapterTextDelta(content);
                    }

                    if (toolsEnabled && delta is not null)
                    {
                        foreach (var toolDelta in ReadToolDeltas(delta))
                        {
                            yield return toolDelta;
                        }
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

    private IEnumerable<AdapterToolCallDelta> ReadToolDeltas(JsonObject container)
    {
        if (!container.TryGetValue("tool_calls", out var value) || value is not JsonArray calls)
        {
            yield break;
        }

        for (var position = 0; position < calls.Items.Count; position++)
        {
            if (calls.Items[position] is not JsonObject call)
            {
                continue;
            }

            var index = position;
            if (call.TryGetValue("index", out var rawIndex))
            {
                if (rawIndex is JsonBoolean boolean)
                {
                    index = boolean.Value ? 1 : 0;
                }
                else if (rawIndex is JsonInteger { Value: var candidate })
                {
                    if (candidate < int.MinValue || candidate > int.MaxValue)
                    {
                        throw new StreamProtocolException(
                            "The OpenAI-compatible response has an unsupported tool-call index.",
                            provider: _providerId,
                            phase: "stream",
                            detail: "The tool-call index is outside the native signed 32-bit range.");
                    }

                    index = (int)candidate;
                }
            }

            string? name = null;
            var arguments = string.Empty;
            if (call.TryGetValue("function", out var rawFunction) && rawFunction is JsonObject function)
            {
                name = OptionalToolString(function, "name");
                arguments = OptionalToolString(function, "arguments") ?? string.Empty;
            }

            yield return new AdapterToolCallDelta(index, OptionalToolString(call, "id"), name, arguments);
        }
    }

    private static string? OptionalToolString(JsonObject source, string name) =>
        source.TryGetValue(name, out var value) && value is JsonString text ? text.Value : null;

    private static IReadOnlyList<TokenLogprob> ReadLogprobs(JsonObject choice)
    {
        if (!choice.TryGetValue("logprobs", out var raw) || raw is not JsonObject container ||
            !container.TryGetValue("content", out var entries) || entries is not JsonArray array)
        {
            return [];
        }

        return Array.AsReadOnly(array.Items
            .Select(static entry => ParseLogprob(entry, withTop: true))
            .Where(static entry => entry is not null)
            .Cast<TokenLogprob>()
            .ToArray());
    }

    private static TokenLogprob? ParseLogprob(JsonValue entry, bool withTop)
    {
        if (entry is not JsonObject item ||
            !item.TryGetValue("token", out var rawToken) || rawToken is not JsonString token ||
            !item.TryGetValue("logprob", out var rawLogprob))
        {
            return null;
        }

        var logprob = rawLogprob switch
        {
            JsonNumber number => number.Value,
            JsonInteger integer => (double)integer.Value,
            _ => double.NaN,
        };
        if (double.IsNaN(logprob))
        {
            return null;
        }

        IEnumerable<TokenLogprob>? top = null;
        if (withTop && item.TryGetValue("top_logprobs", out var rawTop) && rawTop is JsonArray topArray)
        {
            top = topArray.Items
                .Select(static alternative => ParseLogprob(alternative, withTop: false))
                .Where(static alternative => alternative is not null)
                .Cast<TokenLogprob>()
                .ToArray();
        }

        IReadOnlyList<byte>? bytes = null;
        if (item.TryGetValue("bytes", out var rawBytes))
        {
            if (rawBytes is not JsonArray byteArray)
            {
                return new TokenLogprob(token.Value, logprob, top, bytes);
            }
            var parsed = new List<byte>();
            foreach (var value in byteArray.Items)
            {
                if (value is not JsonInteger { Value: var integer } || integer < byte.MinValue || integer > byte.MaxValue)
                {
                    return new TokenLogprob(token.Value, logprob, top, bytes);
                }
                parsed.Add((byte)integer);
            }
            bytes = parsed;
        }

        return new TokenLogprob(token.Value, logprob, top, bytes);
    }

    private async Task<byte[]> ReadResponseBytesAsync(
        Stream stream,
        int maxResponseBytes,
        string phase,
        CancellationToken cancellationToken,
        bool mapModernCancellation = false)
    {
        var buffer = new byte[4096];
        var body = new MemoryStream();
        long total = 0;
        while (true)
        {
            var read = await ReadChunkAsync(
                stream,
                buffer,
                phase,
                cancellationToken,
                mapModernCancellation).ConfigureAwait(false);
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
        CancellationToken cancellationToken,
        bool mapModernCancellation = false)
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
        catch (OperationCanceledException) when (mapModernCancellation && cancellationToken.IsCancellationRequested)
        {
            throw CancellationFor(cancellationToken);
        }
    }

    private async Task<Stream> OpenResponseStreamAsync(
        HttpContent content,
        string phase,
        CancellationToken cancellationToken,
        bool mapModernCancellation = false)
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
        catch (OperationCanceledException) when (mapModernCancellation && cancellationToken.IsCancellationRequested)
        {
            throw CancellationFor(cancellationToken);
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
        CancellationToken cancellationToken,
        bool mapModernCancellation = false)
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
        catch (OperationCanceledException) when (mapModernCancellation && cancellationToken.IsCancellationRequested)
        {
            throw CancellationFor(cancellationToken);
        }
    }

    private static OperationCanceledException CancellationFor(CancellationToken effectiveToken)
    {
        var original = CancellationIdentityContext.Resolve(effectiveToken);
        return new OperationCanceledException(
            original.IsCancellationRequested ? original : effectiveToken);
    }

    private static void ThrowIfNoListingCancellation(CancellationToken cancellationToken)
    {
        if (!cancellationToken.IsCancellationRequested)
        {
            return;
        }

        var callerIdentity = CancellationIdentityContext.Resolve(cancellationToken);
        throw new OperationCanceledException(
            callerIdentity.IsCancellationRequested ? callerIdentity : cancellationToken);
    }

    private ProviderException HttpFailure(
        HttpResponseMessage response,
        byte[] errorBytes,
        string phase,
        bool modernGeneration = false)
    {
        if (modernGeneration &&
            response.StatusCode is (HttpStatusCode)413 or (HttpStatusCode)422)
        {
            var detail = ReadErrorDetail(errorBytes);
            if (LooksLikeContextOverflow(detail))
            {
                return new ContextLengthException(
                    detail,
                    provider: _providerId,
                    phase: phase,
                    retryable: false,
                    httpStatus: (int)response.StatusCode,
                    detail: detail,
                    hint: "shorten the prompt or choose a model with a larger context window");
            }
        }

        var (category, retryable) = response.StatusCode switch
        {
            HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden => ("auth", false),
            HttpStatusCode.NotFound => ("model_not_found", false),
            (HttpStatusCode)429 => ("rate_limit", true),
            (HttpStatusCode)408 or (HttpStatusCode)409 or (HttpStatusCode)425 => ("transport", true),
            _ when (int)response.StatusCode >= 500 => ("provider_unavailable", true),
            _ => ("invalid_request", false),
        };
        return ProviderException.Create(
            $"The OpenAI-compatible service returned HTTP {(int)response.StatusCode}.",
            category,
            retryable,
            phase,
            retryAfterS: RetryAfter(response.Headers.RetryAfter),
            httpStatus: (int)response.StatusCode,
            provider: _providerId);
    }

    private static string ReadErrorDetail(byte[] errorBytes)
    {
        var text = Encoding.UTF8.GetString(errorBytes).Trim();
        if (text.Length == 0)
        {
            return string.Empty;
        }

        try
        {
            if (JsonReader.Read(errorBytes) is JsonObject root)
            {
                var error = root.TryGetValue("error", out var suppliedError) ? suppliedError : root;
                if (error is JsonObject errorObject)
                {
                    var selected = FirstTruthyErrorValue(errorObject);
                    return selected is JsonString selectedText
                        ? BoundErrorDetail(selectedText.Value)
                        : BoundErrorDetail(text);
                }

                if (error is JsonString errorText)
                {
                    return BoundErrorDetail(errorText.Value);
                }
            }
        }
        catch (FormatException)
        {
            // A malformed error body follows the same bounded raw-text fallback as Python.
        }

        return BoundErrorDetail(text);
    }

    private static JsonValue? FirstTruthyErrorValue(JsonObject error)
    {
        foreach (var name in new[] { "message", "detail", "type" })
        {
            if (error.TryGetValue(name, out var value) && IsJsonTruthy(value))
            {
                return value;
            }
        }

        return null;
    }

    private static bool IsJsonTruthy(JsonValue value) => value switch
    {
        JsonNull => false,
        JsonBoolean boolean => boolean.Value,
        JsonInteger integer => !integer.Value.IsZero,
        JsonNumber number => number.Value != 0d,
        JsonString text => text.Value.Length != 0,
        JsonArray array => array.Items.Count != 0,
        JsonObject obj => obj.Properties.Count != 0,
        _ => false,
    };

    private static string BoundErrorDetail(string detail) =>
        string.Concat(detail.EnumerateRunes().Take(400).Select(static rune => rune.ToString()));

    private static bool LooksLikeContextOverflow(string detail)
    {
        var lowered = detail.ToLowerInvariant();
        return lowered.Contains("context length", StringComparison.Ordinal) ||
               lowered.Contains("context_length", StringComparison.Ordinal) ||
               lowered.Contains("too many tokens", StringComparison.Ordinal) ||
               lowered.Contains("maximum context", StringComparison.Ordinal);
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
