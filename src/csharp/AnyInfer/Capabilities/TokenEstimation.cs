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
    /// <remarks>
    /// Messages count their text, tool-call names and arguments, and tool-result content, plus
    /// <see cref="PerMessageOverheadTokens"/> planning tokens each; other content parts, such as media, are
    /// counted in <see cref="RequestEstimate.UnpricedParts"/> instead of being guessed. Tool declarations and the
    /// schema are estimated from their JSON text. A calibration's envelope correction raises the planning count
    /// only, never the floor.
    /// </remarks>
    /// <param name="request">Request to estimate.</param>
    /// <param name="estimator">Token estimator, or <see langword="null"/> for the built-in <see cref="HeuristicTokenEstimator"/>.</param>
    /// <param name="calibration">Provider envelope calibration, or <see langword="null"/> for none.</param>
    /// <returns>The component estimate of the request's input size.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="request"/> is <see langword="null"/>.</exception>
    /// <exception cref="InvalidOperationException"><paramref name="estimator"/> returned <see langword="null"/>.</exception>
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
            var text = FlattenMessage(message, ref unpricedParts);
            var estimate = EstimateOrThrow(counter, text);
            messages += new TokenEstimate(checked(estimate.Tokens + PerMessageOverheadTokens), estimate.Floor);
        }

        var tools = new TokenEstimate(0, 0);
        foreach (var tool in request.Tools)
        {
            var declaration = new JsonObject(
            [
                new JsonProperty("name", new JsonString(tool.Name)),
                new JsonProperty("description", new JsonString(tool.Description)),
                new JsonProperty("parameters", tool.Parameters),
            ]);
            tools += EstimateOrThrow(counter, JsonWriter.WriteAccounting(declaration, indent: null));
        }

        var schema = request.Schema is null
            ? new TokenEstimate(0, 0)
            : EstimateOrThrow(counter, JsonWriter.WriteAccounting(request.Schema.JsonSchema, indent: null));

        var content = messages + tools + schema;
        return new RequestEstimate(messages, tools, schema, Envelope(content, calibration), unpricedParts);
    }

    private static string FlattenMessage(Message message, ref long unpricedParts)
    {
        var text = new System.Text.StringBuilder();
        foreach (var part in message.Content)
        {
            switch (part)
            {
                case Text value:
                    text.Append(value.Value);
                    break;
                case ToolCall call:
                    text.Append(call.Name);
                    text.Append(JsonWriter.WriteAccounting(call.Arguments, indent: null));
                    break;
                case ToolResult result:
                    text.Append(result.Content);
                    break;
                default:
                    unpricedParts = checked(unpricedParts + 1);
                    break;
            }
        }
        return text.ToString();
    }

    private static TokenEstimate EstimateOrThrow(ITokenEstimator counter, string text) =>
        counter.Estimate(text) ?? throw new InvalidOperationException("Token estimator returned null.");

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
