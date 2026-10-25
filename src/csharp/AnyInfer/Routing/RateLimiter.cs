using AnyInfer.Capabilities;
using AnyInfer.Events;

namespace AnyInfer.Routing;

/// <summary>Paces standalone dispatches and learns provider allowance headers.</summary>
/// <remarks>
/// <para>
/// <see cref="AcquireAsync(CancellationToken)"/> first waits for a concurrency slot when
/// <see cref="RateLimits.MaxConcurrent"/> is set. It then waits until every other configured bound
/// allows a dispatch: the token bucket for <see cref="RateLimits.RequestsPerMinute"/> (it starts full
/// and holds one second of requests, never less than one), the minimum interval since the previous
/// dispatch, and, when <see cref="ReadsHeaders"/> is <see langword="true"/>, a provider-reported window
/// reset once the observed remaining count is at or below the reserve. A single header wait is capped
/// at 60 seconds, and an acquisition stops honoring header waits after 60 seconds of them.
/// </para>
/// <para>
/// All members are thread-safe. Telemetry callbacks run synchronously on the calling thread, and an
/// exception they throw propagates to the caller.
/// </para>
/// </remarks>
public sealed class RateLimiter
{
    private const double MaximumHeaderWaitS = 60;
    private const double MaximumDelayMilliseconds = uint.MaxValue - 1;
    private readonly object _gate = new();
    private readonly RateLimitHeaders _dialect;
    private readonly string _providerId;
    private readonly Action<TelemetryEvent>? _events;
    private readonly bool _seesResponses;
    private readonly TimeProvider _timeProvider;
    private readonly SemaphoreSlim? _semaphore;
    private readonly long _timestampOrigin;
    private readonly Window _requests = new();
    private readonly Window _tokensWindow = new();
    private readonly double _capacity;
    private readonly double _refillPerS;
    private double _tokens;
    private double _refilledAt;
    private double? _lastDispatch;

    /// <summary>Creates a standalone limiter.</summary>
    /// <param name="limits">Pacing configuration.</param>
    /// <param name="dialect">Names of the provider's rate-limit response headers; <see langword="null"/> declares none, so <see cref="Observe"/> learns nothing.</param>
    /// <param name="providerId">Provider instance identifier reported in telemetry events; empty by default.</param>
    /// <param name="events">Callback that receives <see cref="RateLimitObserved"/> and <see cref="RateLimitWaited"/> events, or <see langword="null"/> for none.</param>
    /// <param name="seesResponses">Whether the caller will pass provider response headers to <see cref="Observe"/>; <see langword="false"/> disables header-based waiting and is explained by <see cref="UnsupportedHeadersReason"/>.</param>
    /// <param name="timeProvider">Clock and timer source for pacing, or <see langword="null"/> for <see cref="TimeProvider.System"/>.</param>
    /// <exception cref="ArgumentNullException"><paramref name="limits"/> or <paramref name="providerId"/> is <see langword="null"/>.</exception>
    public RateLimiter(
        RateLimits limits,
        RateLimitHeaders? dialect = null,
        string providerId = "",
        Action<TelemetryEvent>? events = null,
        bool seesResponses = true,
        TimeProvider? timeProvider = null)
    {
        Limits = limits ?? throw new ArgumentNullException(nameof(limits));
        _dialect = dialect ?? new RateLimitHeaders();
        _providerId = providerId ?? throw new ArgumentNullException(nameof(providerId));
        _events = events;
        _seesResponses = seesResponses;
        _timeProvider = timeProvider ?? TimeProvider.System;
        _timestampOrigin = _timeProvider.GetTimestamp();
        _refilledAt = NowS();
        _semaphore = limits.MaxConcurrent is { } concurrent ? new SemaphoreSlim(concurrent, concurrent) : null;
        if (limits.RequestsPerMinute is { } rate)
        {
            _capacity = rate / 60 > 1 ? rate / 60 : 1;
            _refillPerS = rate / 60;
            _tokens = _capacity;
        }
    }

    /// <summary>Gets the immutable pacing configuration.</summary>
    public RateLimits Limits { get; }
    /// <summary>Gets whether usable provider allowance headers are read.</summary>
    /// <remarks><see langword="true"/> only when <see cref="RateLimits.RespectHeaders"/> is set, responses are visible, and the dialect names both a remaining-count header and a reset header for requests or for tokens.</remarks>
    public bool ReadsHeaders => Limits.RespectHeaders && _seesResponses &&
        ((!string.IsNullOrEmpty(_dialect.RequestsRemaining) && !string.IsNullOrEmpty(_dialect.RequestsReset)) ||
         (!string.IsNullOrEmpty(_dialect.TokensRemaining) && !string.IsNullOrEmpty(_dialect.TokensReset)));
    /// <summary>Gets why provider allowance headers cannot be read, when requested; <see langword="null"/> when headers are not requested or are readable.</summary>
    public string? UnsupportedHeadersReason => !Limits.RespectHeaders || ReadsHeaders ? null :
        !_seesResponses ? "this provider builds its own transport, so its response headers are never seen; pacing here is by configured bounds only" :
        !_dialect.Declared ? "this provider publishes no rate-limit headers" :
        "this provider reports a remaining count but no window reset";

    /// <summary>Gets the current provider-reported wait without consuming limiter state.</summary>
    /// <returns>
    /// The longer of the request-window and token-window waits, in seconds and at most 60, based on
    /// the headers observed so far; 0 when neither observed window is at or below its reserve. The
    /// concurrency bound, token bucket, and minimum interval are not included.
    /// </returns>
    public double ObservedWaitS()
    {
        lock (_gate)
        {
            var now = NowS();
            return OrderedMax(_requests.WaitS(now, Limits.ReserveFraction), _tokensWindow.WaitS(now, Limits.ReserveFraction));
        }
    }

    /// <summary>Acquires a permit after configured and observed pacing has completed.</summary>
    /// <remarks>Each nonzero wait is reported as a <see cref="RateLimitWaited"/> event whose reason is <c>concurrency</c>, <c>interval</c>, or <c>provider-headers</c>.</remarks>
    /// <param name="cancellationToken">Cancels the wait. A concurrency slot already taken by this call is released before the cancellation propagates.</param>
    /// <returns>A lease that holds the concurrency slot, when <see cref="RateLimits.MaxConcurrent"/> is set, until it is disposed. Dispose every lease once its request finishes; disposal is idempotent.</returns>
    /// <exception cref="OperationCanceledException"><paramref name="cancellationToken"/> is canceled while waiting.</exception>
    public ValueTask<RateLimitLease> AcquireAsync(CancellationToken cancellationToken = default) =>
        AcquireAsync(cancellationToken, null);

    internal async ValueTask<RateLimitLease> AcquireAsync(
        CancellationToken effectiveToken,
        Func<CancellationToken?>? cancelledParentToken)
    {
        var acquiredSemaphore = false;
        try
        {
            if (_semaphore is not null)
            {
                var started = NowS();
                try
                {
                    await _semaphore.WaitAsync(effectiveToken).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (TryGetCancelledParent(effectiveToken, cancelledParentToken, out var parent))
                {
                    throw new OperationCanceledException(parent);
                }
                acquiredSemaphore = true;
                var waited = NowS() - started;
                if (waited > 0)
                {
                    ReportWait(waited, "concurrency");
                }
            }

            await WaitForTurnAsync(effectiveToken, cancelledParentToken).ConfigureAwait(false);
            return new RateLimitLease(() => _semaphore?.Release());
        }
        catch
        {
            if (acquiredSemaphore)
            {
                _semaphore!.Release();
            }

            throw;
        }
    }

    /// <summary>Updates the observed provider allowance state from one response.</summary>
    /// <remarks>
    /// Header names from the dialect are matched exactly first and then case-insensitively. Reset
    /// values may be a number of seconds, a duration such as <c>1m30s</c> or <c>250ms</c>, or an ISO 8601
    /// instant with a UTC offset; unparsable values are ignored. A <see cref="RateLimitObserved"/> event
    /// is reported when a remaining count was read. Nothing happens when the dialect declares no headers.
    /// </remarks>
    /// <param name="headers">Response headers of one provider response, keyed by header name.</param>
    /// <exception cref="ArgumentNullException"><paramref name="headers"/> is <see langword="null"/>.</exception>
    /// <exception cref="OverflowException">A declared count header holds a number outside the <see cref="long"/> range.</exception>
    public void Observe(IReadOnlyDictionary<string, string> headers)
    {
        ArgumentNullException.ThrowIfNull(headers);
        if (!_dialect.Declared)
        {
            return;
        }

        var now = NowS();
        var requestsReset = RateLimitParsing.ParseResetSeconds(Header(headers, _dialect.RequestsReset), _timeProvider);
        var tokensReset = RateLimitParsing.ParseResetSeconds(Header(headers, _dialect.TokensReset), _timeProvider);
        var requestsRemaining = RateLimitParsing.ReadCount(headers, _dialect.RequestsRemaining);
        var tokensRemaining = RateLimitParsing.ReadCount(headers, _dialect.TokensRemaining);
        lock (_gate)
        {
            _requests.Apply(requestsRemaining, RateLimitParsing.ReadCount(headers, _dialect.LimitRequests), requestsReset, now);
            _tokensWindow.Apply(tokensRemaining, RateLimitParsing.ReadCount(headers, _dialect.LimitTokens), tokensReset, now);
        }

        if (requestsRemaining is not null || tokensRemaining is not null)
        {
            _events?.Invoke(new RateLimitObserved(
                _providerId,
                requestsRemaining,
                tokensRemaining,
                requestsReset ?? tokensReset));
        }
    }

    private async Task WaitForTurnAsync(
        CancellationToken cancellationToken,
        Func<CancellationToken?>? cancelledParentToken)
    {
        var headerWaited = 0d;
        while (true)
        {
            double delay;
            string? reason;
            lock (_gate)
            {
                (delay, reason) = NextDelay(NowS(), headerWaited >= MaximumHeaderWaitS);
                if (delay <= 0)
                {
                    Consume(NowS());
                    return;
                }
            }

            try
            {
                await DelayAsync(delay, cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (TryGetCancelledParent(cancellationToken, cancelledParentToken, out var parent))
            {
                throw new OperationCanceledException(parent);
            }
            if (reason == "provider-headers")
            {
                headerWaited += delay;
            }

            ReportWait(delay, reason!);
        }
    }

    private (double Delay, string? Reason) NextDelay(double now, bool headersSpent)
    {
        var delay = 0d;
        string? reason = null;
        if (_refillPerS > 0)
        {
            Refill(now);
            if (_tokens < 1)
            {
                Consider((1 - _tokens) / _refillPerS, "interval", ref delay, ref reason);
            }
        }

        if (Limits.MinIntervalS > 0 && _lastDispatch is { } last)
        {
            var elapsed = now - last;
            if (elapsed < Limits.MinIntervalS)
            {
                Consider(Limits.MinIntervalS - elapsed, "interval", ref delay, ref reason);
            }
        }

        if (ReadsHeaders && !headersSpent)
        {
            Consider(_requests.WaitS(now, Limits.ReserveFraction), "provider-headers", ref delay, ref reason);
            Consider(_tokensWindow.WaitS(now, Limits.ReserveFraction), "provider-headers", ref delay, ref reason);
        }

        return (delay, reason);
    }

    private void Refill(double now)
    {
        var elapsed = now - _refilledAt;
        if (elapsed < 0)
        {
            elapsed = 0;
        }

        _refilledAt = now;
        var candidate = _tokens + elapsed * _refillPerS;
        _tokens = candidate < _capacity ? candidate : _capacity;
    }

    private void Consume(double now)
    {
        if (_refillPerS > 0)
        {
            _tokens = _tokens - 1 > 0 ? _tokens - 1 : 0;
        }

        _lastDispatch = now;
        _requests.Consume();
        _tokensWindow.Consume();
    }

    private async Task DelayAsync(double seconds, CancellationToken cancellationToken)
    {
        if (double.IsPositiveInfinity(seconds))
        {
            await Task.Delay(Timeout.InfiniteTimeSpan, _timeProvider, cancellationToken).ConfigureAwait(false);
            return;
        }

        var remainingMilliseconds = seconds * 1000;
        while (remainingMilliseconds > 0)
        {
            var milliseconds = remainingMilliseconds > MaximumDelayMilliseconds ? MaximumDelayMilliseconds : remainingMilliseconds;
            await Task.Delay(TimeSpan.FromMilliseconds(milliseconds), _timeProvider, cancellationToken).ConfigureAwait(false);
            remainingMilliseconds -= milliseconds;
        }
    }

    private void ReportWait(double waitedS, string reason)
    {
        if (waitedS <= 0)
        {
            return;
        }

        var pacing = AttemptPacing.Current;
        pacing?.Record(waitedS, reason);
        _events?.Invoke(new RateLimitWaited(pacing?.RequestId ?? string.Empty, _providerId, waitedS, reason, pacing?.Target));
    }

    private double NowS() => _timeProvider.GetElapsedTime(_timestampOrigin, _timeProvider.GetTimestamp()).TotalSeconds;

    private static void Consider(double candidate, string candidateReason, ref double delay, ref string? reason)
    {
        if (candidate > delay ||
            candidate == delay && reason is not null && string.CompareOrdinal(candidateReason, reason) > 0)
        {
            delay = candidate;
            reason = candidateReason;
        }
    }

    private static double OrderedMax(double left, double right) => right > left ? right : left;

    private static bool TryGetCancelledParent(
        CancellationToken effectiveToken,
        Func<CancellationToken?>? cancelledParentToken,
        out CancellationToken parent)
    {
        var suppliedParent = cancelledParentToken?.Invoke();
        parent = suppliedParent ?? default;
        return effectiveToken.IsCancellationRequested && suppliedParent is not null;
    }

    private static string? Header(IReadOnlyDictionary<string, string> headers, string name)
    {
        return string.IsNullOrEmpty(name) ? null :
            headers.TryGetValue(name, out var direct) ? direct :
            headers.FirstOrDefault(header => string.Equals(header.Key, name, StringComparison.OrdinalIgnoreCase)).Value;
    }

    private sealed class Window
    {
        private long? _remaining;
        private long? _limit;
        private double? _resetsAt;

        internal double WaitS(double now, double reserveFraction)
        {
            if (_remaining is null || _resetsAt is null || _remaining > Floor(reserveFraction))
            {
                return 0;
            }

            var remaining = _resetsAt.Value - now;
            var capped = remaining < MaximumHeaderWaitS ? remaining : MaximumHeaderWaitS;
            return capped > 0 ? capped : 0;
        }

        internal void Apply(long? remaining, long? limit, double? resetS, double now)
        {
            if (remaining is not null)
            {
                _remaining = remaining;
            }

            if (limit is not null)
            {
                _limit = limit;
            }

            if (resetS is not null)
            {
                _resetsAt = now + resetS.Value;
            }
        }

        internal void Consume()
        {
            if (_remaining is not null)
            {
                _remaining = _remaining > 0 ? _remaining - 1 : 0;
            }
        }

        private double Floor(double reserveFraction) => reserveFraction == 0 || _limit is null ? 0 : _limit.Value * reserveFraction;
    }
}
