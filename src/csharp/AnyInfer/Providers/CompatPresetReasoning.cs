using AnyInfer.Json;

namespace AnyInfer.Providers;

/// <summary>Closed reasoning-wire translations retained from compatibility-preset source data.</summary>
internal enum CompatPresetReasoningStyle
{
    None,
    Effort,
    EffortMinLow,
    EffortThreeLevel,
    EffortMinNamed,
    ReasoningObject,
}

/// <summary>Translates normalized reasoning effort into a preset's private wire shape.</summary>
internal static class CompatPresetReasoning
{
    internal static JsonObject Translate(CompatPresetReasoningStyle style, string? effort)
    {
        if (!Enum.IsDefined(style))
        {
            throw new ArgumentOutOfRangeException(nameof(style));
        }

        if (effort is null || style == CompatPresetReasoningStyle.None)
        {
            return Empty();
        }

        return style switch
        {
            CompatPresetReasoningStyle.Effort => Scalar(effort),
            CompatPresetReasoningStyle.EffortMinLow or CompatPresetReasoningStyle.EffortThreeLevel =>
                effort == "none" ? Empty() : Scalar(effort == "minimal" ? "low" : effort),
            CompatPresetReasoningStyle.EffortMinNamed =>
                Scalar(effort is "none" or "minimal" ? "min" : effort),
            CompatPresetReasoningStyle.ReasoningObject => Object(effort),
            _ => throw new ArgumentOutOfRangeException(nameof(style)),
        };
    }

    private static JsonObject Empty() => new([]);

    private static JsonObject Scalar(string effort) => new([
        new JsonProperty("reasoning_effort", new JsonString(effort)),
    ]);

    private static JsonObject Object(string effort) => effort == "none"
        ? new JsonObject([
            new JsonProperty("reasoning", new JsonObject([
                new JsonProperty("enabled", new JsonBoolean(false)),
            ])),
        ])
        : new JsonObject([
            new JsonProperty("reasoning", new JsonObject([
                new JsonProperty("effort", new JsonString(effort)),
            ])),
        ]);
}
