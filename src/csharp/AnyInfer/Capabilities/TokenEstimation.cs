using AnyInfer.Json;

namespace AnyInfer.Capabilities;

/// <summary>Provides pure request sizing over the currently representable request surface.</summary>
public static class TokenEstimation
{
    /// <summary>Gets UTF-8 bytes per planning token in the built-in heuristic.</summary>
    public const long EstimateBytesPerToken = 3;

    /// <summary>Gets UTF-8 bytes per lower-bound token in the built-in heuristic.</summary>
    public const long FloorBytesPerToken = 8;

    /// <summary>Gets planning-only chat-envelope tokens charged per message.</summary>
    public const long PerMessageOverheadTokens = 4;

    private static readonly ITokenEstimator DefaultEstimator = new HeuristicTokenEstimator();

    /// <summary>Estimates the current request's text messages and optional schema without validation or dispatch.</summary>
    public static RequestEstimate EstimateRequest(
        GenerationRequest request,
        ITokenEstimator? estimator = null,
        TokenCalibration? calibration = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        var counter = estimator ?? DefaultEstimator;
        var messages = new TokenEstimate(0, 0);
        long unpricedParts = 0;
        foreach (var message in request.Messages)
        {
            var text = string.Concat(message.Content.OfType<Text>().Select(static part => part.Value));
            var estimate = counter.Estimate(text) ?? throw new InvalidOperationException("Token estimator returned null.");
            messages += new TokenEstimate(checked(estimate.Tokens + PerMessageOverheadTokens), estimate.Floor);
            foreach (var part in message.Content)
            {
                if (part is not Text)
                {
                    unpricedParts = checked(unpricedParts + 1);
                }
            }
        }

        var tools = new TokenEstimate(0, 0);
        var schema = request.Schema is null
            ? new TokenEstimate(0, 0)
            : counter.Estimate(JsonWriter.WriteAccounting(request.Schema.JsonSchema, indent: null));
        if (schema is null)
        {
            throw new InvalidOperationException("Token estimator returned null.");
        }

        var content = messages + tools + schema;
        return new RequestEstimate(messages, tools, schema, Envelope(content, calibration), unpricedParts);
    }

    private static TokenEstimate Envelope(TokenEstimate content, TokenCalibration? calibration)
    {
        if (calibration is null || calibration.IsIdentity)
        {
            return new TokenEstimate(0, 0);
        }

        var scaled = checked((long)Math.Ceiling(content.Tokens * calibration.Multiplier));
        var added = checked(Math.Max(0, checked(scaled - content.Tokens)) + (long)calibration.OverheadTokens);
        return new TokenEstimate(added, 0);
    }
}
