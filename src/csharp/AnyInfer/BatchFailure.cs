namespace AnyInfer;

/// <summary>One internal batch outcome retained on an exhausted retrieval route.</summary>
public sealed record BatchFailure
{
    /// <summary>Creates one immutable batch failure snapshot.</summary>
    /// <param name="batchIndex">The batch position within the logical request.</param>
    /// <param name="itemCount">The number of request items carried by the batch.</param>
    /// <param name="succeeded">Whether the batch completed successfully.</param>
    /// <param name="error">The bounded provider error detail, when present.</param>
    public BatchFailure(int batchIndex, int itemCount, bool succeeded, string? error = null)
    {
        BatchIndex = batchIndex;
        ItemCount = itemCount;
        Succeeded = succeeded;
        Error = error;
    }

    /// <summary>Gets the batch position within the logical request.</summary>
    public int BatchIndex { get; }

    /// <summary>Gets the number of items carried by the batch.</summary>
    public int ItemCount { get; }

    /// <summary>Gets whether the batch completed successfully.</summary>
    public bool Succeeded { get; }

    /// <summary>Gets the bounded provider error detail, when present.</summary>
    public string? Error { get; }
}