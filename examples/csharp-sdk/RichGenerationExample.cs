namespace AnyInfer.Examples;

/// <summary>Runs a typed rich-input request through the configured OpenAI-compatible adapter.</summary>
public static class RichGenerationExample
{
    /// <summary>Generates from inline image, document, and audio parts with token log-probabilities requested.</summary>
    public static async Task<RichGenerationObservation> RunAsync(
        ProviderSettings settings,
        string target,
        IEnumerable<byte> imageData,
        IEnumerable<byte> documentData,
        IEnumerable<byte> audioData,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentException.ThrowIfNullOrWhiteSpace(target);
        ArgumentNullException.ThrowIfNull(imageData);
        ArgumentNullException.ThrowIfNull(documentData);
        ArgumentNullException.ThrowIfNull(audioData);
        var message = new Message("user",
        [
            new Text("Describe the supplied inputs."),
            new ImagePart(imageData, mediaType: "image/png", detail: "low"),
            new DocumentPart(documentData, mediaType: "application/pdf", filename: "brief.pdf"),
            new AudioPart(audioData, mediaType: "audio/wav"),
        ]);
        var request = new GenerationRequest([message], new Route([target]), logprobs: 2);
        await using var client = new AsyncClient([settings]);
        var generation = await client.GenerateAsync(request, cancellationToken);
        return new RichGenerationObservation(message, generation);
    }
}

/// <summary>Contains the typed request and terminal generation from the rich-input example.</summary>
public sealed record RichGenerationObservation(Message Request, Generation Generation);
