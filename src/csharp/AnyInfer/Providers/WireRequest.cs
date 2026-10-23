using AnyInfer.Json;

namespace AnyInfer.Providers;

/// <summary>Immutable normalized request passed to a provider adapter.</summary>
public sealed record WireRequest
{
    /// <summary>Creates a public wire request using the frozen serialization profile.</summary>
    public WireRequest(
        string model,
        IEnumerable<Message> messages,
        Sampling sampling,
        JsonValue? schema = null,
        string? mechanism = null,
        bool stream = false,
        double timeoutS = 120,
        int maxResponseBytes = 1_048_576,
        string schemaName = "response",
        IEnumerable<ToolSpec>? tools = null,
        string toolChoice = "auto",
        IEnumerable<int>? cacheMarks = null,
        JsonObject? reasoningWire = null,
        IEnumerable<ServerToolSpec>? serverTools = null,
        bool citeDocuments = false,
        int? logprobs = null,
        JsonObject? extraOptions = null,
        JsonObject? sessionState = null)
        : this(model, messages, sampling, schema, mechanism, stream, timeoutS, maxResponseBytes, schemaName, modernSchema: false, tools, toolChoice, cacheMarks, reasoningWire, serverTools, citeDocuments, logprobs, extraOptions, sessionState)
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
        string? schemaName,
        bool modernSchema,
        IEnumerable<ToolSpec>? tools = null,
        string toolChoice = "auto",
        IEnumerable<int>? cacheMarks = null,
        JsonObject? reasoningWire = null,
        IEnumerable<ServerToolSpec>? serverTools = null,
        bool citeDocuments = false,
        int? logprobs = null,
        JsonObject? extraOptions = null,
        JsonObject? sessionState = null)
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
        SchemaName = schemaName;
        Tools = Array.AsReadOnly((tools ?? []).Select(static tool => tool ?? throw new ArgumentException("Wire tools cannot contain null references.")).ToArray());
        ToolChoice = toolChoice ?? throw new ArgumentNullException(nameof(toolChoice));
        CacheMarks = Array.AsReadOnly((cacheMarks ?? []).ToArray());
        ReasoningWire = reasoningWire is null ? new JsonObject([]) : RichGenerationSnapshots.Object(reasoningWire);
        ServerTools = RichGenerationSnapshots.List(serverTools, nameof(serverTools));
        CiteDocuments = citeDocuments;
        Logprobs = logprobs;
        ExtraOptions = extraOptions is null ? new JsonObject([]) : RichGenerationSnapshots.Object(extraOptions);
        SessionState = sessionState is null ? null : RichGenerationSnapshots.Object(sessionState);
        if (!modernSchema && Tools.Count == 0 && !string.Equals(ToolChoice, "auto", StringComparison.Ordinal))
        {
            throw new ArgumentException("A non-auto tool choice requires at least one tool.", nameof(toolChoice));
        }
        UsesModernSchema = modernSchema;
    }

    /// <summary>Gets the selected model.</summary>
    public string Model { get; }
    /// <summary>Gets copied request messages.</summary>
    public IReadOnlyList<Message> Messages { get; }
    /// <summary>Gets sampling controls.</summary>
    public Sampling Sampling { get; }
    /// <summary>Gets the optional structured-output schema.</summary>
    public JsonValue? Schema { get; }
    /// <summary>Gets the selected structured-output mechanism.</summary>
    public string? Mechanism { get; }
    /// <summary>Gets whether the provider should stream events.</summary>
    public bool Stream { get; }
    /// <summary>Gets the provider timeout in seconds.</summary>
    public double TimeoutS { get; }
    /// <summary>Gets the maximum response size in bytes.</summary>
    public int MaxResponseBytes { get; }
    /// <summary>Gets the schema name used by compatible provider projections.</summary>
    public string? SchemaName { get; }
    /// <summary>Gets copied tool declarations.</summary>
    public IReadOnlyList<ToolSpec> Tools { get; }
    /// <summary>Gets the raw provider tool-choice spelling.</summary>
    public string ToolChoice { get; }
    /// <summary>Gets copied cache segment marks selected by the core.</summary>
    public IReadOnlyList<int> CacheMarks { get; }
    /// <summary>Gets copied provider-specific reasoning fields.</summary>
    public JsonObject ReasoningWire { get; }
    /// <summary>Gets copied provider-run tool declarations.</summary>
    public IReadOnlyList<ServerToolSpec> ServerTools { get; }
    /// <summary>Gets whether citations were requested for supplied documents.</summary>
    public bool CiteDocuments { get; }
    /// <summary>Gets the requested alternative log-probability count, or <see langword="null"/>.</summary>
    public int? Logprobs { get; }
    /// <summary>Gets copied provider-specific wire options.</summary>
    public JsonObject ExtraOptions { get; }
    /// <summary>Gets opaque copied continuation state, or <see langword="null"/> when no session is open.</summary>
    public JsonObject? SessionState { get; }
    internal bool UsesModernSchema { get; }
}
