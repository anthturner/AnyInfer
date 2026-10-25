namespace AnyInfer;

/// <summary>Configures standalone client-side request pacing for one provider instance.</summary>
/// <remarks>
/// Attach it with <see cref="ProviderSettings.Limits"/>, or pace calls yourself with a
/// <see cref="Routing.RateLimiter"/>. The default instance sets no local bound but still waits on
/// provider-reported allowance headers, so it is <see cref="Active"/>.
/// </remarks>
public sealed record RateLimits
{
    /// <summary>Creates immutable rate-limit settings.</summary>
    /// <param name="maxConcurrent">Maximum number of requests in flight at once, at least 1; <see langword="null"/> for no concurrency bound.</param>
    /// <param name="requestsPerMinute">Sustained request rate, greater than 0, enforced by a token bucket; <see langword="null"/> for no rate bound.</param>
    /// <param name="minIntervalS">Minimum time in seconds between consecutive dispatches; 0 (the default) for none. Must not be negative.</param>
    /// <param name="respectHeaders">Whether to wait for a provider-reported window reset when the reported remaining allowance is used up or within the reserve; <see langword="true"/> by default. It has an effect only when the provider declares rate-limit headers and its responses are visible to the limiter.</param>
    /// <param name="reserveFraction">Fraction of a provider-reported limit to keep unused, from 0 (inclusive, the default) to 1 (exclusive); waiting starts once the remaining count falls to that share of the reported limit.</param>
    /// <exception cref="ArgumentOutOfRangeException">A value is outside its documented range.</exception>
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
    /// <summary>Gets the configured token-bucket request rate in requests per minute, when configured.</summary>
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
