namespace AnyInfer.Examples;

/// <summary>Creates immutable settings for an OpenAI-compatible provider instance.</summary>
public static class SettingsExample
{
    /// <summary>Creates settings whose credential may be a literal or a resolver reference.</summary>
    public static ProviderSettings Create(string apiBase, string? credentialReference = null) =>
        ProviderSettings.Of("openai-compat", baseUrl: apiBase, apiKey: credentialReference);
}
