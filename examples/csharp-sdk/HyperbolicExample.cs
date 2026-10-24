using System.Net;
using System.Text;
using System.Text.Json;
using AnyInfer.Config;

namespace AnyInfer.Examples;

/// <summary>Uses the default Hyperbolic generation registration without hosted traffic.</summary>
public static class HyperbolicExample
{
    /// <summary>Creates settings for the registered Hyperbolic provider.</summary>
    public static ProviderSettings Settings(
        HttpMessageHandler transport,
        string apiKey = "env://HYPERBOLIC_API_KEY") =>
        ProviderSettings.Of("hyperbolic", apiKey: apiKey, transport: transport);

    /// <summary>Generates one response through the default provider registry.</summary>
    public static async Task<Generation> RunAsync(
        ProviderSettings settings,
        CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient([settings]);
        return await client.GenerateAsync(
            "Say hello from the Hyperbolic default registration.",
            target: "hyperbolic:glm-5.3-flash",
            cancellationToken: cancellationToken);
    }
}

/// <summary>Provides the offline transport assertion used by the executable Hyperbolic example.</summary>
public sealed class HyperbolicScriptedHandler : HttpMessageHandler
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
            || request.RequestUri is not
            {
                Scheme: "https",
                Host: "api.hyperbolic.ai",
                AbsolutePath: "/inference/v1/chat/completions",
            }
            || request.Headers.Authorization?.Scheme != "Bearer"
            || request.Headers.Authorization.Parameter != "offline-hyperbolic-key"
            || root.GetProperty("model").GetString() != "glm-5.3-flash"
            || root.GetProperty("messages")[0].GetProperty("content").GetString()
                != "Say hello from the Hyperbolic default registration.")
        {
            throw new InvalidOperationException("Hyperbolic example did not preserve the registered request shape.");
        }

        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(
                "{\"choices\":[{\"message\":{\"content\":\"hello from Hyperbolic\"},\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":1,\"total_tokens\":2}}",
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
