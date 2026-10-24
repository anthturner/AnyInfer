using System.Net;
using System.Text;
using System.Text.Json;
using AnyInfer.Config;

namespace AnyInfer.Examples;

/// <summary>Uses the default Cerebras generation registration without hosted traffic.</summary>
public static class CerebrasExample
{
    /// <summary>Creates settings for the registered Cerebras provider.</summary>
    public static ProviderSettings Settings(
        HttpMessageHandler transport,
        string apiKey = "env://CEREBRAS_API_KEY") =>
        ProviderSettings.Of("cerebras", apiKey: apiKey, transport: transport);

    /// <summary>Generates one response through the default provider registry.</summary>
    public static async Task<Generation> RunAsync(
        ProviderSettings settings,
        CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient([settings]);
        return await client.GenerateAsync(
            "Say hello from the Cerebras default registration.",
            target: "cerebras:gpt-oss-120b",
            cancellationToken: cancellationToken);
    }
}

/// <summary>Provides the offline transport assertion used by the executable Cerebras example.</summary>
public sealed class CerebrasScriptedHandler : HttpMessageHandler
{
    /// <summary>Gets the number of requests received by the handler.</summary>
    public int RequestCount { get; private set; }

    /// <summary>Gets the number of times the client disposed the handler.</summary>
    public int DisposeCount { get; private set; }

    /// <inheritdoc />
    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        RequestCount++;
        var body = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellationToken);
        using var document = JsonDocument.Parse(body);
        var root = document.RootElement;
        if (request.Method != HttpMethod.Post
            || request.RequestUri?.AbsolutePath != "/v1/chat/completions"
            || request.Headers.Authorization?.Scheme != "Bearer"
            || request.Headers.Authorization.Parameter != "offline-cerebras-key"
            || root.GetProperty("model").GetString() != "gpt-oss-120b"
            || root.GetProperty("messages")[0].GetProperty("content").GetString()
                != "Say hello from the Cerebras default registration.")
        {
            throw new InvalidOperationException("Cerebras example did not preserve the registered request shape.");
        }

        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(
                "{\"choices\":[{\"message\":{\"content\":\"hello from Cerebras\"},\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":1,\"total_tokens\":2}}",
                Encoding.UTF8,
                "application/json"),
        };
    }

    /// <inheritdoc />
    protected override void Dispose(bool disposing)
    {
        if (disposing) DisposeCount++;
        base.Dispose(disposing);
    }
}
