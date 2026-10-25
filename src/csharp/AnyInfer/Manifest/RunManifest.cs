using AnyInfer.Internal;

namespace AnyInfer.Manifest;

/// <summary>One immutable format-1 account of a single inference call.</summary>
/// <remarks>
/// <para>
/// Manifests are content-free by default. Generation manifests record counts, names, digests,
/// routing, attempts, usage and timing, but no prompt, response, schema or tool-argument text:
/// <see cref="Payloads"/> stays <see langword="null"/> unless the client was created with
/// payload capture enabled (<c>manifestPayloads: true</c>), and captured payload text passes
/// through <see cref="AnyInfer.Redaction"/>. Embedding and rerank manifests never carry payloads.
/// A client can also omit the manifest altogether when manifests are disabled.
/// </para>
/// <para>
/// Facets that do not apply are empty rather than <see langword="null"/>. The C# SDK performs no
/// context reduction, so <see cref="Context"/> is empty in manifests it produces, and
/// <see cref="EmbeddingSpace"/> is set only for embedding operations.
/// </para>
/// </remarks>
public sealed partial record RunManifest
{
    /// <summary>Renders this manifest as an immutable JSON object.</summary>
    /// <returns>
    /// A new object holding every format-1 field under its snake_case name, with absent optional
    /// values written as JSON <c>null</c>.
    /// </returns>
    public Json.JsonObject ToDictionary() => ManifestSerialization.Encode(this);

    /// <summary>Rebuilds a manifest from an immutable JSON object.</summary>
    /// <remarks>
    /// Missing fields take the constructor defaults and unknown fields are ignored. The
    /// <c>format</c> value is read as is and is not checked against
    /// <see cref="ManifestUtilities.Format"/>.
    /// </remarks>
    /// <param name="data">The format-1 object, as produced by <see cref="ToDictionary"/>.</param>
    /// <returns>The rebuilt manifest.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="data"/> is <see langword="null"/>.</exception>
    /// <exception cref="FormatException">
    /// A present field has the wrong JSON type or an out-of-range integer, a required nested field
    /// is missing, or a non-nullable facet is JSON <c>null</c>.
    /// </exception>
    public static RunManifest FromDictionary(Json.JsonObject data) => ManifestSerialization.Decode(data);

    /// <summary>Serializes this manifest using the format-one JSON writer.</summary>
    /// <remarks>
    /// Object keys are sorted by Unicode code point and non-ASCII characters are escaped, so the
    /// output is ASCII.
    /// </remarks>
    /// <param name="indent">
    /// Spaces per nesting level; defaults to 2. <see langword="null"/> writes a single line with
    /// <c>", "</c> and <c>": "</c> separators, and 0 writes one value per line without
    /// indentation.
    /// </param>
    /// <returns>The manifest JSON text, without a trailing newline.</returns>
    /// <exception cref="ArgumentException">A manifest string contains an unpaired UTF-16 surrogate.</exception>
    public string ToJson(int? indent = 2) => Json.JsonWriter.WriteManifest(ToDictionary(), indent);

    /// <summary>Rebuilds a manifest from format-one JSON text.</summary>
    /// <remarks>Field handling is the same as for <see cref="FromDictionary(Json.JsonObject)"/>.</remarks>
    /// <param name="json">The manifest JSON text, as produced by <see cref="ToJson(int?)"/>.</param>
    /// <returns>The rebuilt manifest.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="json"/> is <see langword="null"/>.</exception>
    /// <exception cref="FormatException">
    /// <paramref name="json"/> is not strict JSON, is not an object, or has an invalid field.
    /// </exception>
    public static RunManifest FromJson(string json)
    {
        if (Json.JsonReader.ReadModern(json) is not Json.JsonObject data)
        {
            throw new FormatException("Manifest JSON must be an object.");
        }

        return FromDictionary(data);
    }

    /// <summary>Initializes a content-free manifest with format-1 defaults.</summary>
    /// <remarks>Every argument is optional; an omitted facet becomes its empty default and an omitted list becomes empty.</remarks>
    /// <param name="format">The manifest format version; defaults to <c>1</c>, the value of <see cref="ManifestUtilities.Format"/>.</param>
    /// <param name="anyinferVersion">The producing AnyInfer version, or empty when unknown.</param>
    /// <param name="requestId">The request identifier shared with telemetry events, or empty when unknown.</param>
    /// <param name="complete">Whether the call reached a terminal result; a partial stream manifest is incomplete.</param>
    /// <param name="request">Request shape facts, or <see langword="null"/> for an empty facet.</param>
    /// <param name="route">Route facts, or <see langword="null"/> for an empty facet.</param>
    /// <param name="capability">Capability facts consumed by the answering target, or <see langword="null"/> for an empty facet.</param>
    /// <param name="attempts">Attempts in order, or <see langword="null"/> for none. The list is copied.</param>
    /// <param name="structured">Structured-output facts, or <see langword="null"/> for an empty facet.</param>
    /// <param name="cache">Cache plan and cache usage facts, or <see langword="null"/> for an empty facet.</param>
    /// <param name="context">Context reduction facts, or <see langword="null"/> for an empty facet.</param>
    /// <param name="dropped">Parameters dropped for a target, or <see langword="null"/> for none. The list is copied.</param>
    /// <param name="usage">Usage facts, or <see langword="null"/> for an empty facet.</param>
    /// <param name="timing">Timing facts, or <see langword="null"/> for an empty facet.</param>
    /// <param name="notes">Ordered warnings and diagnostic notes, or <see langword="null"/> for none. The list is copied.</param>
    /// <param name="payloads">Redacted payload content, or <see langword="null"/> (the default) for a content-free manifest.</param>
    /// <param name="operation">The operation spelling: <c>generation</c> (the default), <c>embedding</c> or <c>rerank</c> for manifests the SDK produces.</param>
    /// <param name="embeddingSpace">The embedding space for an embedding operation, or <see langword="null"/>.</param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="format"/>, <paramref name="anyinferVersion"/>, <paramref name="requestId"/>
    /// or <paramref name="operation"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="ArgumentException">A supplied list contains <see langword="null"/>.</exception>
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
