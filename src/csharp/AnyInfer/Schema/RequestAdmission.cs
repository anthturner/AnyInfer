namespace AnyInfer.Schema;

/// <summary>Performs construction and profile admission before an adapter entry exists.</summary>
public static class RequestAdmission
{
    /// <summary>Validates construction constraints and the frozen request profile.</summary>
    public static void Validate(GenerationRequest request) => Validate(request, allowTargetAliases: false);

    internal static void Validate(GenerationRequest request, bool allowTargetAliases, SchemaExecutionProfile profile = SchemaExecutionProfile.FrozenV0)
    {
        ArgumentNullException.ThrowIfNull(request);
        ValidateConstruction(request.Sampling);

        foreach (var message in request.Messages)
        {
            if (message.Role is not ("system" or "user" or "assistant"))
            {
                ThrowUnsupported("The message role is outside the v0 profile.");
            }

            if (message.Content.Any(static part => part is not Text))
            {
                ThrowUnsupported("Non-text message content is outside the v0 profile.");
            }
        }

        foreach (var target in request.Route.Targets)
        {
            if (!allowTargetAliases && !string.IsNullOrWhiteSpace(target) && !target.Contains(':'))
            {
                ThrowUnsupported("Target aliases are outside the v0 profile.");
            }
        }

        if (profile == SchemaExecutionProfile.FrozenV0)
        {
            SchemaAdmission.Validate(request.Schema);
        }
    }

    private static void ValidateConstruction(Sampling? sampling)
    {
        if (sampling is null)
        {
            return;
        }

        if (sampling.Seed is < 0 ||
            sampling.PresencePenalty is { } presence && !double.IsFinite(presence) ||
            sampling.FrequencyPenalty is { } frequency && !double.IsFinite(frequency))
        {
            throw new ProviderException(
                "The request has an invalid sampling value.",
                "invalid_request",
                retryable: false,
                phase: null,
                detail: "Sampling seed and penalties are outside the v0 construction domain.",
                hint: "Use a non-negative seed and finite penalties.");
        }
    }

    private static void ThrowUnsupported(string detail) =>
        throw new ProviderException(
            "The request uses input outside the core-generation v0 profile.",
            "unsupported_input",
            retryable: false,
            phase: "generate",
            detail: detail,
            hint: "Use the admitted core-generation v0 request surface.");
}
