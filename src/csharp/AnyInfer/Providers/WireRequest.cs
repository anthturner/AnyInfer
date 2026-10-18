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
        int maxResponseBytes = 1_048_576,
        string schemaName = "response")
        : this(model, messages, sampling, schema, mechanism, stream, timeoutS, maxResponseBytes, schemaName, modernSchema: false)
    {
    }

    internal WireRequest(
        string model,
        IEnumerable<Message> messages,
        Sampling sampling,
        JsonValue? schema,
        string? mechanism,
        bool stream,
        double timeoutS,
        int maxResponseBytes,
        string schemaName,
        bool modernSchema)
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
        SchemaName = schemaName ?? throw new ArgumentNullException(nameof(schemaName));
        UsesModernSchema = modernSchema;
    }

    public string Model { get; }
    public IReadOnlyList<Message> Messages { get; }
    public Sampling Sampling { get; }
    public JsonValue? Schema { get; }
    public string? Mechanism { get; }
    public bool Stream { get; }
    public double TimeoutS { get; }
    public int MaxResponseBytes { get; }
    public string SchemaName { get; }
    internal bool UsesModernSchema { get; }
}
