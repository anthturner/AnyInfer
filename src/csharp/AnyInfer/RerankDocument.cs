using AnyInfer.Internal;
using AnyInfer.Json;

namespace AnyInfer;

/// <summary>One immutable text document supplied to a reranking request.</summary>
public sealed record RerankDocument
{
    /// <summary>Creates a copied reranking document.</summary>
    /// <param name="id">
    /// The caller-owned identifier, reported back as <see cref="RankedItem.DocumentId"/>. Use a
    /// non-empty value: <see cref="RankedItem"/> rejects an empty identifier.
    /// </param>
    /// <param name="text">The document text sent to the provider.</param>
    /// <param name="metadata">Caller metadata kept with the document and not sent to the provider, or <see langword="null"/> for none. The map is copied.</param>
    /// <exception cref="ArgumentNullException"><paramref name="id"/> or <paramref name="text"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="metadata"/> contains a <see langword="null"/> value.</exception>
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