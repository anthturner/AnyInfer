namespace AnyInfer.Providers;

/// <summary>Private wire-spelling choices for an OpenAI-compatible adapter instance.</summary>
internal sealed record OpenAICompatDialectOptions
{
    internal OpenAICompatDialectOptions(
        string authHeader = "bearer",
        bool modelsListing = true,
        string outputTokensField = "max_tokens")
    {
        if (authHeader is not ("bearer" or "x-api-key"))
        {
            throw new ArgumentException("The OpenAI-compatible authentication header is invalid.", nameof(authHeader));
        }

        if (outputTokensField is not ("max_tokens" or "max_completion_tokens"))
        {
            throw new ArgumentException("The OpenAI-compatible output-token field is invalid.", nameof(outputTokensField));
        }

        AuthHeader = authHeader;
        ModelsListing = modelsListing;
        OutputTokensField = outputTokensField;
    }

    internal string AuthHeader { get; }

    internal bool ModelsListing { get; }

    internal string OutputTokensField { get; }
}
