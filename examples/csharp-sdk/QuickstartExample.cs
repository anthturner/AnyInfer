using AnyInfer;

namespace AnyInfer.Examples;

/// <summary>
/// The C# quickstart: settings for an OpenAI-compatible endpoint, one buffered call, a caller-owned
/// deadline, and the asynchronous and synchronous client lifetimes.
/// </summary>
public static class QuickstartExample
{
    // --8<-- [start:settings]
    /// <summary>Creates settings for an OpenAI-compatible server on loopback, such as Ollama or LM Studio.</summary>
    /// <param name="baseUrl">The server's OpenAI-compatible base URL, including its <c>/v1</c> path.</param>
    /// <returns>Settings without an API key, so requests carry no <c>Authorization</c> header.</returns>
    public static ProviderSettings LocalServer(string baseUrl = "http://127.0.0.1:11434/v1") =>
        ProviderSettings.Of("openai-compat", baseUrl: baseUrl);

    /// <summary>Creates settings for a hosted OpenAI-compatible endpoint that needs an API key.</summary>
    /// <param name="baseUrl">The endpoint's base URL, such as <c>https://api.example.com/v1</c>.</param>
    /// <param name="apiKey">
    /// A credential reference such as <c>env://EXAMPLE_API_KEY</c>; it is resolved when the first call
    /// needs it, not when the settings or the client are created.
    /// </param>
    /// <returns>Settings that send the resolved key as a bearer token.</returns>
    public static ProviderSettings Hosted(string baseUrl, string apiKey) =>
        ProviderSettings.Of("openai-compat", baseUrl: baseUrl, apiKey: apiKey);
    // --8<-- [end:settings]

    // --8<-- [start:first-call]
    /// <summary>Sends one prompt and returns the buffered result.</summary>
    /// <param name="settings">The provider instance to call.</param>
    /// <param name="target">A <c>provider:model</c> target, such as <c>openai-compat:qwen3:8b</c>.</param>
    /// <param name="cancellationToken">Stops the call, including any retries, when cancelled.</param>
    /// <returns>The generation: its text, target, finish reason, usage, timing, and attempts.</returns>
    public static async Task<Generation> FirstCallAsync(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient([settings]);
        return await client.GenerateAsync(
            "Name one planet in the solar system.",
            target: target,
            cancellationToken: cancellationToken);
    }

    /// <summary>Formats a result's text with the token counts its provider reported.</summary>
    /// <param name="result">A completed generation.</param>
    /// <returns>The text followed by the reported input and output token counts.</returns>
    public static string Describe(Generation result) =>
        result.Usage is { } usage
            ? $"{result.Text} ({usage.InputTokens} input + {usage.OutputTokens} output tokens)"
            : $"{result.Text} (no usage reported)";
    // --8<-- [end:first-call]

    // --8<-- [start:deadline]
    /// <summary>Gives the whole call, retries included, a deadline that the caller owns.</summary>
    /// <param name="settings">The provider instance to call.</param>
    /// <param name="target">A <c>provider:model</c> target.</param>
    /// <param name="deadline">How long the call may take before it is cancelled.</param>
    /// <returns>The generation, or <see langword="null"/> when the deadline passed first.</returns>
    public static async Task<Generation?> FirstCallWithDeadlineAsync(
        ProviderSettings settings,
        string target,
        TimeSpan deadline)
    {
        using var timeout = new CancellationTokenSource(deadline);
        try
        {
            return await FirstCallAsync(settings, target, timeout.Token);
        }
        catch (OperationCanceledException) when (timeout.IsCancellationRequested)
        {
            return null;
        }
    }
    // --8<-- [end:deadline]

    // --8<-- [start:sync]
    /// <summary>Makes the same call through the synchronous facade, blocking until it completes.</summary>
    /// <param name="settings">The provider instance to call.</param>
    /// <param name="target">A <c>provider:model</c> target.</param>
    /// <param name="cancellationToken">Stops the call, including any retries, when cancelled.</param>
    /// <returns>The generation.</returns>
    public static Generation FirstCall(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        using var client = new Client([settings]);
        return client.Generate(
            "Name one planet in the solar system.",
            target: target,
            cancellationToken: cancellationToken);
    }
    // --8<-- [end:sync]
}
