using AnyInfer.Json;

namespace AnyInfer.Providers;

public sealed record WireRequest
{
    public WireRequest(
        string model,
        IEnumerable<Message> messages,
        Sampling sampling,
        JsonValue? schema = null,
        string? mechanism = null,
        bool stream = false,
        double timeoutS = 120,
        int maxResponseBytes = 1_048_576)
    {
        Model = model ?? throw new ArgumentNullException(nameof(model));
        ArgumentNullException.ThrowIfNull(messages);
        Messages = Array.AsReadOnly(messages.Select(static message => message ?? throw new ArgumentException("Wire messages cannot contain null references.")).ToArray());
        Sampling = sampling ?? throw new ArgumentNullException(nameof(sampling));
        Schema = schema;
        Mechanism = mechanism;
        Stream = stream;
        TimeoutS = timeoutS;
        MaxResponseBytes = maxResponseBytes;
    }

    public string Model { get; }

    public IReadOnlyList<Message> Messages { get; }

    public Sampling Sampling { get; }

    public JsonValue? Schema { get; }

    public string? Mechanism { get; }

    public bool Stream { get; }

    public double TimeoutS { get; }

    public int MaxResponseBytes { get; }
}
