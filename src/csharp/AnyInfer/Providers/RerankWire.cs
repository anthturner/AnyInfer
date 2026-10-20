using AnyInfer.Internal;
using AnyInfer.Json;

namespace AnyInfer.Providers;

/// <summary>One document in a resolved provider reranking batch.</summary>
public sealed record RerankWireDocument
{
    /// <summary>Creates a wire document with its original request index.</summary>
    public RerankWireDocument(int index, string text)
    {
        Index = index;
        Text = text ?? throw new ArgumentNullException(nameof(text));
    }

    /// <summary>Gets the original caller document index.</summary>
    public int Index { get; }
    /// <summary>Gets the document text.</summary>
    public string Text { get; }
}

/// <summary>One resolved provider reranking batch.</summary>
public sealed record RerankWireRequest
{
    /// <summary>Creates a copied provider reranking request.</summary>
    public RerankWireRequest(
        string model,
        string query,
        IEnumerable<RerankWireDocument> documents,
        int? topN = null,
        double timeoutS = 120d,
        int maxResponseBytes = 1 * 1024 * 1024,
        IReadOnlyDictionary<string, JsonValue>? extraOptions = null)
    {
        Model = model ?? throw new ArgumentNullException(nameof(model));
        Query = query ?? throw new ArgumentNullException(nameof(query));
        Documents = ImmutableValues.List(documents, nameof(documents));
        TopN = topN;
        TimeoutS = timeoutS;
        MaxResponseBytes = maxResponseBytes;
        ExtraOptions = ImmutableValues.Map(extraOptions, nameof(extraOptions));
    }

    /// <summary>Gets the concrete provider model.</summary>
    public string Model { get; }
    /// <summary>Gets the query text.</summary>
    public string Query { get; }
    /// <summary>Gets copied documents in provider batch order.</summary>
    public IReadOnlyList<RerankWireDocument> Documents { get; }
    /// <summary>Gets the requested top-N limit, when present.</summary>
    public int? TopN { get; }
    /// <summary>Gets the provider timeout in seconds.</summary>
    public double TimeoutS { get; }
    /// <summary>Gets the provider response-body cap in bytes.</summary>
    public int MaxResponseBytes { get; }
    /// <summary>Gets copied provider-specific options.</summary>
    public IReadOnlyDictionary<string, JsonValue> ExtraOptions { get; }
}

/// <summary>One provider-reported reranking item before core validation.</summary>
public sealed record WireRankedItem
{
    /// <summary>Creates an unchecked provider-reported index and score.</summary>
    public WireRankedItem(int index, double score)
    {
        Index = index;
        Score = score;
    }

    /// <summary>Gets the provider-reported document index.</summary>
    public int Index { get; }
    /// <summary>Gets the provider-reported score.</summary>
    public double Score { get; }
}

/// <summary>One buffered reranking response before core validation.</summary>
public sealed record RerankWireResult
{
    /// <summary>Creates a copied, deliberately permissive provider reranking response.</summary>
    public RerankWireResult(
        IEnumerable<WireRankedItem> items,
        string? model = null,
        Usage? usage = null,
        JsonValue? raw = null)
    {
        Items = ImmutableValues.List(items, nameof(items));
        Model = model;
        Usage = usage;
        Raw = raw;
    }

    /// <summary>Gets copied provider items in provider result order.</summary>
    public IReadOnlyList<WireRankedItem> Items { get; }
    /// <summary>Gets the provider-reported model, when present.</summary>
    public string? Model { get; }
    /// <summary>Gets provider-reported usage, when present.</summary>
    public Usage? Usage { get; }
    /// <summary>Gets the immutable raw provider payload, when present.</summary>
    public JsonValue? Raw { get; }
}