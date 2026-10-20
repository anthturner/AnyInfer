namespace AnyInfer;

/// <summary>One validated public reranking item.</summary>
public sealed record RankedItem
{
    /// <summary>Creates a ranked item with a source document identity.</summary>
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