namespace AnyInfer;

/// <summary>Controls whether and how a request asks the core to plan prompt-cache placement.</summary>
public enum CacheMode
{
    /// <summary>Disables cache placement.</summary>
    Off,
    /// <summary>Uses the strongest cache mechanism the selected target declares.</summary>
    Auto,
    /// <summary>Requests explicit placement where the target supports it.</summary>
    Explicit,
}

/// <summary>Immutable caller policy for pure prompt-cache planning.</summary>
public sealed record CachePolicy
{
    /// <summary>Creates an immutable cache policy.</summary>
    /// <param name="mode">Whether cache placement is disabled, automatic, or explicitly requested.</param>
    /// <param name="minSegmentTokens">Smallest candidate segment worth marking.</param>
    /// <param name="maxMarks">Maximum number of explicit cache marks.</param>
    /// <param name="includeTools">Whether stable tool declarations may be cache candidates.</param>
    /// <param name="includeSystem">Whether the stable system block may be a cache candidate.</param>
    public CachePolicy(
        CacheMode mode = CacheMode.Auto,
        long minSegmentTokens = 1024,
        int maxMarks = 4,
        bool includeTools = true,
        bool includeSystem = true)
    {
        if (!Enum.IsDefined(mode))
        {
            throw new ArgumentOutOfRangeException(nameof(mode));
        }

        if (minSegmentTokens < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(minSegmentTokens));
        }

        if (maxMarks < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(maxMarks));
        }

        Mode = mode;
        MinSegmentTokens = minSegmentTokens;
        MaxMarks = maxMarks;
        IncludeTools = includeTools;
        IncludeSystem = includeSystem;
    }

    /// <summary>Gets whether cache placement is disabled, automatic, or explicitly requested.</summary>
    public CacheMode Mode { get; }

    /// <summary>Gets the smallest candidate segment worth marking.</summary>
    public long MinSegmentTokens { get; }

    /// <summary>Gets the maximum number of explicit cache marks.</summary>
    public int MaxMarks { get; }

    /// <summary>Gets whether stable tool declarations may be cache candidates.</summary>
    public bool IncludeTools { get; }

    /// <summary>Gets whether the stable system block may be a cache candidate.</summary>
    public bool IncludeSystem { get; }

    /// <summary>Gets whether this policy asks the planner to engage caching.</summary>
    public bool Active => Mode != CacheMode.Off;
}
