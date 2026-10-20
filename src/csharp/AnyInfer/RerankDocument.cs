using AnyInfer.Internal;
using AnyInfer.Json;

namespace AnyInfer;

/// <summary>One immutable text document supplied to a reranking request.</summary>
public sealed record RerankDocument
{
    /// <summary>Creates a copied reranking document.</summary>
    public RerankDocument(string id, string text, IReadOnlyDictionary<string, string>? metadata = null)
    {
        Id = id ?? throw new ArgumentNullException(nameof(id));
        Text = text ?? throw new ArgumentNullException(nameof(text));
        Metadata = ImmutableValues.Map(metadata, nameof(metadata));
    }

    /// <summary>Gets the caller-owned document identifier.</summary>
    public string Id { get; }
    /// <summary>Gets the document text.</summary>
    public string Text { get; }
    /// <summary>Gets copied caller metadata.</summary>
    public IReadOnlyDictionary<string, string> Metadata { get; }
}