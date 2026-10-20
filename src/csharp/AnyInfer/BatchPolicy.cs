namespace AnyInfer;

/// <summary>Controls core-managed splitting for one embedding or reranking request.</summary>
public sealed record BatchPolicy
{
    /// <summary>Creates an immutable batching policy.</summary>
    /// <param name="maxConcurrency">Maximum batches the core may dispatch concurrently.</param>
    /// <param name="maxItemsOverride">Optional caller ceiling for items in one provider batch.</param>
    /// <param name="allowSplit">Whether the core may split a request across batches.</param>
    /// <param name="rerankCrossBatch">Whether reranking may cross provider batch boundaries.</param>
    public BatchPolicy(
        int maxConcurrency = 4,
        int? maxItemsOverride = null,
        bool allowSplit = true,
        bool rerankCrossBatch = false)
    {
        if (maxConcurrency <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maxConcurrency));
        }

        if (maxItemsOverride is <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maxItemsOverride));
        }

        MaxConcurrency = maxConcurrency;
        MaxItemsOverride = maxItemsOverride;
        AllowSplit = allowSplit;
        RerankCrossBatch = rerankCrossBatch;
    }

    /// <summary>Gets the maximum concurrent provider batches.</summary>
    public int MaxConcurrency { get; }

    /// <summary>Gets the caller-supplied item ceiling, or <see langword="null"/> when unset.</summary>
    public int? MaxItemsOverride { get; }

    /// <summary>Gets whether request splitting is permitted.</summary>
    public bool AllowSplit { get; }

    /// <summary>Gets whether reranking may be split across provider batches.</summary>
    public bool RerankCrossBatch { get; }
}