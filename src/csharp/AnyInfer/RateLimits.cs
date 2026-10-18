namespace AnyInfer;

/// <summary>Configures standalone client-side request pacing for one provider instance.</summary>
public sealed record RateLimits
{
    /// <summary>Creates immutable rate-limit settings.</summary>
    public RateLimits(
        int? maxConcurrent = null,
        double? requestsPerMinute = null,
        double minIntervalS = 0,
        bool respectHeaders = true,
        double reserveFraction = 0)
    {
        if (maxConcurrent is < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(maxConcurrent));
        }

        if (requestsPerMinute is <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(requestsPerMinute));
        }

        if (minIntervalS < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(minIntervalS));
        }

        if (!(reserveFraction >= 0 && reserveFraction < 1))
        {
            throw new ArgumentOutOfRangeException(nameof(reserveFraction));
        }

        MaxConcurrent = maxConcurrent;
        RequestsPerMinute = requestsPerMinute;
        MinIntervalS = minIntervalS;
        RespectHeaders = respectHeaders;
        ReserveFraction = reserveFraction;
    }

    /// <summary>Gets the maximum in-flight request count, when configured.</summary>
    public int? MaxConcurrent { get; }
    /// <summary>Gets the configured token-bucket request rate, when configured.</summary>
    public double? RequestsPerMinute { get; }
    /// <summary>Gets the minimum gap between dispatches in seconds.</summary>
    public double MinIntervalS { get; }
    /// <summary>Gets whether provider-reported allowance headers are honored.</summary>
    public bool RespectHeaders { get; }
    /// <summary>Gets the fraction of a reported allowance retained as reserve.</summary>
    public double ReserveFraction { get; }
    /// <summary>Gets whether this configuration requests any pacing behavior.</summary>
    public bool Active => MaxConcurrent is not null || RequestsPerMinute is not null || MinIntervalS > 0 || RespectHeaders;
}
