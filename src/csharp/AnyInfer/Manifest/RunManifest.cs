using AnyInfer.Internal;

namespace AnyInfer.Manifest;

/// <summary>One immutable format-1 account of a single inference call.</summary>
public sealed partial record RunManifest
{
    /// <summary>Renders this manifest as an immutable JSON object.</summary>
    public Json.JsonObject ToDictionary() => ManifestSerialization.Encode(this);

    /// <summary>Rebuilds a manifest from an immutable JSON object.</summary>
    public static RunManifest FromDictionary(Json.JsonObject data) => ManifestSerialization.Decode(data);

    /// <summary>Serializes this manifest using the format-one JSON writer.</summary>
    public string ToJson(int? indent = 2) => Json.JsonWriter.WriteManifest(ToDictionary(), indent);

    /// <summary>Rebuilds a manifest from format-one JSON text.</summary>
    public static RunManifest FromJson(string json)
    {
        if (Json.JsonReader.ReadModern(json) is not Json.JsonObject data)
        {
            throw new FormatException("Manifest JSON must be an object.");
        }

        return FromDictionary(data);
    }

    /// <summary>Initializes a content-free manifest with Python format-1 defaults.</summary>
    public RunManifest(
        string format = "1",
        string anyinferVersion = "",
        string requestId = "",
        bool complete = false,
        RequestFacet? request = null,
        RouteFacet? route = null,
        CapabilityFacet? capability = null,
        IReadOnlyList<AttemptFacet>? attempts = null,
        SchemaFacet? structured = null,
        CacheFacet? cache = null,
        ContextFacet? context = null,
        IReadOnlyList<DroppedParameter>? dropped = null,
        UsageFacet? usage = null,
        TimingFacet? timing = null,
        IReadOnlyList<string>? notes = null,
        PayloadFacet? payloads = null,
        string operation = "generation",
        EmbeddingSpace? embeddingSpace = null)
    {
        Format = format ?? throw new ArgumentNullException(nameof(format));
        AnyinferVersion = anyinferVersion ?? throw new ArgumentNullException(nameof(anyinferVersion));
        RequestId = requestId ?? throw new ArgumentNullException(nameof(requestId));
        Complete = complete;
        Request = request ?? new RequestFacet();
        Route = route ?? new RouteFacet();
        Capability = capability ?? new CapabilityFacet();
        Attempts = ImmutableValues.List(attempts, nameof(attempts));
        Structured = structured ?? new SchemaFacet();
        Cache = cache ?? new CacheFacet();
        Context = context ?? new ContextFacet();
        Dropped = ImmutableValues.List(dropped, nameof(dropped));
        Usage = usage ?? new UsageFacet();
        Timing = timing ?? new TimingFacet();
        Notes = ImmutableValues.List(notes, nameof(notes));
        Payloads = payloads;
        Operation = operation ?? throw new ArgumentNullException(nameof(operation));
        EmbeddingSpace = embeddingSpace;
    }

    /// <summary>Gets the manifest format version.</summary>
    public string Format { get; }

    /// <summary>Gets the producing AnyInfer version.</summary>
    public string AnyinferVersion { get; }

    /// <summary>Gets the event correlation identifier.</summary>
    public string RequestId { get; }

    /// <summary>Gets whether a terminal result exists.</summary>
    public bool Complete { get; }

    /// <summary>Gets request facts.</summary>
    public RequestFacet Request { get; }

    /// <summary>Gets route facts.</summary>
    public RouteFacet Route { get; }

    /// <summary>Gets capability facts.</summary>
    public CapabilityFacet Capability { get; }

    /// <summary>Gets attempt trail.</summary>
    public IReadOnlyList<AttemptFacet> Attempts { get; }

    /// <summary>Gets structured-output facts.</summary>
    public SchemaFacet Structured { get; }

    /// <summary>Gets cache facts.</summary>
    public CacheFacet Cache { get; }

    /// <summary>Gets context facts.</summary>
    public ContextFacet Context { get; }

    /// <summary>Gets dropped parameters.</summary>
    public IReadOnlyList<DroppedParameter> Dropped { get; }

    /// <summary>Gets usage facts.</summary>
    public UsageFacet Usage { get; }

    /// <summary>Gets timing facts.</summary>
    public TimingFacet Timing { get; }

    /// <summary>Gets ordered notes.</summary>
    public IReadOnlyList<string> Notes { get; }

    /// <summary>Gets optional redacted payload facts.</summary>
    public PayloadFacet? Payloads { get; }

    /// <summary>Gets operation spelling.</summary>
    public string Operation { get; }

    /// <summary>Gets embedding-space identity for embedding operations.</summary>
    public EmbeddingSpace? EmbeddingSpace { get; }
}
