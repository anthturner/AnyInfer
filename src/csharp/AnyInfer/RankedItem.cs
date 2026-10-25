namespace AnyInfer;

/// <summary>One validated public reranking item.</summary>
public sealed record RankedItem
{
    /// <summary>Creates a ranked item with a source document identity.</summary>
    /// <param name="index">The zero-based index of the document in <see cref="RerankRequest.Documents"/>.</param>
    /// <param name="documentId">The document's non-empty <see cref="RerankDocument.Id"/>.</param>
    /// <param name="score">The finite provider relevance score; its scale is provider-defined.</param>
    /// <param name="text">The document text when <see cref="RerankRequest.ReturnDocuments"/> was set, or <see langword="null"/>.</param>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="index"/> is negative.</exception>
    /// <exception cref="ArgumentNullException"><paramref name="documentId"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="documentId"/> is empty or <paramref name="score"/> is not finite.</exception>
    public RankedItem(int index, string documentId, double score, string? text = null)
    {
        if (index < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(index));
        }

        DocumentId = documentId ?? throw new ArgumentNullException(nameof(documentId));
        if (DocumentId.Length == 0)
        {
            throw new ArgumentException("Document identifiers must not be empty.", nameof(documentId));
        }

        if (!double.IsFinite(score))
        {
            throw new ArgumentException("Ranked item scores must be finite.", nameof(score));
        }

        Index = index;
        Score = score;
        Text = text;
    }

    /// <summary>Gets the original request document index.</summary>
    public int Index { get; }
    /// <summary>Gets the caller-owned document identifier.</summary>
    public string DocumentId { get; }
    /// <summary>Gets the finite provider score.</summary>
    public double Score { get; }
    /// <summary>Gets echoed document text when requested.</summary>
    public string? Text { get; }
}