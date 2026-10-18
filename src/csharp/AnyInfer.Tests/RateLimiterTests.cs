using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Routing;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Independent deterministic controls for standalone rate-limit pacing.</summary>
public sealed class RateLimiterTests
{
    private static readonly RateLimitHeaders Dialect = new(
        requestsRemaining: "x-remaining",
        requestsReset: "x-reset",
        tokensRemaining: "x-token-remaining",
        tokensReset: "x-token-reset",
        limitRequests: "x-limit");

    [Fact]
    public void Rate_limit_configuration_distinguishes_omitted_bare_inert_and_source_comparison_edges()
    {
        Assert.False(new RateLimits(respectHeaders: false).Active);
        Assert.True(new RateLimits().Active);
        Assert.True(new RateLimits(requestsPerMinute: double.NaN, minIntervalS: double.NaN).Active);
        Assert.True(new RateLimits(requestsPerMinute: double.PositiveInfinity).Active);
        Assert.Throws<ArgumentOutOfRangeException>(() => new RateLimits(maxConcurrent: 0));
        Assert.Throws<ArgumentOutOfRangeException>(() => new RateLimits(requestsPerMinute: 0));
        Assert.Throws<ArgumentOutOfRangeException>(() => new RateLimits(minIntervalS: -0.01));
        Assert.Throws<ArgumentOutOfRangeException>(() => new RateLimits(reserveFraction: double.NaN));
        Assert.Throws<ArgumentOutOfRangeException>(() => new RateLimits(reserveFraction: 1));
    }

    [Fact]
    public async Task Semaphore_leases_hold_until_exactly_one_sync_or_async_release_and_queued_cancellation_unwinds()
    {
        var clock = new VirtualTimeProvider();
        var limiter = new RateLimiter(new RateLimits(maxConcurrent: 1, respectHeaders: false), timeProvider: clock);
        var first = await limiter.AcquireAsync();
        var blocked = limiter.AcquireAsync().AsTask();
        Assert.False(blocked.IsCompleted);

        using var cancelled = new CancellationTokenSource();
        var queued = limiter.AcquireAsync(cancelled.Token).AsTask();
        cancelled.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => queued);

        first.Dispose();
        await first.DisposeAsync();
        await using var second = await blocked;
        var third = limiter.AcquireAsync().AsTask();
        Assert.False(third.IsCompleted);
        await second.DisposeAsync();
        await using var released = await third;
    }

    [Fact]
    public async Task Rpm_and_minimum_interval_compete_under_virtual_time_with_interval_winning_ties()
    {
        var clock = new VirtualTimeProvider();
        var waits = new List<RateLimitWaited>();
        var limiter = new RateLimiter(
            new RateLimits(requestsPerMinute: 60, minIntervalS: 1, respectHeaders: false),
            events: evt => { if (evt is RateLimitWaited waited) waits.Add(waited); },
            timeProvider: clock);

        await using (await limiter.AcquireAsync()) { }
        var pending = limiter.AcquireAsync().AsTask();
        clock.Advance(TimeSpan.FromSeconds(1));
        await using (await pending) { }

        Assert.Equal([1d], clock.Delays);
        Assert.Single(waits);
        Assert.Equal("interval", waits[0].Reason);
    }

    [Fact]
    public async Task Header_windows_preserve_partial_facts_are_read_only_and_cap_each_cumulative_wait_at_sixty_seconds()
    {
        var clock = new VirtualTimeProvider();
        var observed = new List<RateLimitObserved>();
        var limiter = new RateLimiter(
            new RateLimits(reserveFraction: .1), Dialect, "provider",
            evt => { if (evt is RateLimitObserved item) observed.Add(item); },
            timeProvider: clock);

        limiter.Observe(new Dictionary<string, string>
        {
            ["X-Remaining"] = "100",
            ["x-limit"] = "1000",
            ["x-reset"] = "2h",
        });
        Assert.Equal(60d, limiter.ObservedWaitS());
        Assert.Equal(60d, limiter.ObservedWaitS());
        Assert.Single(observed);
        Assert.Equal(100L, observed[0].RequestsRemaining);
        Assert.Null(observed[0].TokensRemaining);

        var pending = limiter.AcquireAsync().AsTask();
        clock.Advance(TimeSpan.FromSeconds(60));
        await using (await pending) { }
        Assert.Equal([60d], clock.Delays);
    }

    [Fact]
    public async Task Missing_limit_does_not_invent_reserve_and_missing_reset_or_unknown_dialect_remains_nonblocking()
    {
        var clock = new VirtualTimeProvider();
        var missingLimit = new RateLimiter(new RateLimits(reserveFraction: .5), Dialect, timeProvider: clock);
        missingLimit.Observe(new Dictionary<string, string> { ["x-remaining"] = "5", ["x-reset"] = "30s" });
        await using (await missingLimit.AcquireAsync()) { }
        Assert.Empty(clock.Delays);

        var partial = new RateLimiter(new RateLimits(), new RateLimitHeaders(requestsRemaining: "x-remaining"), timeProvider: clock);
        Assert.False(partial.ReadsHeaders);
        Assert.Contains("no window reset", partial.UnsupportedHeadersReason);

        var unknown = new RateLimiter(new RateLimits(), timeProvider: clock);
        unknown.Observe(new Dictionary<string, string> { ["x-remaining"] = "0", ["x-reset"] = "30s" });
        await using (await unknown.AcquireAsync()) { }
        Assert.Empty(clock.Delays);
    }

    [Fact]
    public async Task Interval_and_header_wait_choose_the_larger_delay_then_report_the_paid_request_context()
    {
        var clock = new VirtualTimeProvider();
        var events = new List<TelemetryEvent>();
        var limiter = new RateLimiter(
            new RateLimits(minIntervalS: 3), Dialect, "p", events.Add, timeProvider: clock);
        await using (await limiter.AcquireAsync()) { }
        limiter.Observe(new Dictionary<string, string> { ["x-remaining"] = "0", ["x-reset"] = "5s" });

        using var pacing = new AttemptPacing("request-42", new ResolvedTarget("p", "m"));
        var pending = limiter.AcquireAsync().AsTask();
        clock.Advance(TimeSpan.FromSeconds(5));
        await using (await pending) { }

        Assert.Equal(5d, pacing.WaitedS);
        Assert.Equal(["provider-headers"], pacing.Reasons);
        Assert.Collection(events,
            item =>
            {
                var observed = Assert.IsType<RateLimitObserved>(item);
                Assert.Equal("p", observed.ProviderId);
                Assert.Equal(0L, observed.RequestsRemaining);
                Assert.Equal(5d, observed.ResetsInS);
            },
            item => Assert.IsType<RateLimitWaited>(item));
        var waited = Assert.IsType<RateLimitWaited>(events[1]);
        Assert.Equal("request-42", waited.RequestId);
        Assert.Equal("provider-headers", waited.Reason);
        Assert.Equal(new ResolvedTarget("p", "m"), waited.Target);
    }

    [Fact]
    public async Task Equal_interval_and_provider_header_delays_choose_the_provider_header_reason()
    {
        var clock = new VirtualTimeProvider();
        var waited = new List<RateLimitWaited>();
        var limiter = new RateLimiter(
            new RateLimits(minIntervalS: 5), Dialect, "p",
            evt => { if (evt is RateLimitWaited item) waited.Add(item); }, timeProvider: clock);
        await using (await limiter.AcquireAsync()) { }
        limiter.Observe(new Dictionary<string, string> { ["x-remaining"] = "0", ["x-reset"] = "5s" });

        var pending = limiter.AcquireAsync().AsTask();
        clock.Advance(TimeSpan.FromSeconds(5));
        await using (await pending) { }

        Assert.Equal("provider-headers", Assert.Single(waited).Reason);
    }

    [Fact]
    public async Task Waiting_callback_failure_precedes_dispatch_and_releases_the_concurrency_permit()
    {
        var clock = new VirtualTimeProvider();
        var sentinel = new InvalidOperationException("wait callback");
        var limiter = new RateLimiter(
            new RateLimits(maxConcurrent: 1, requestsPerMinute: 60, respectHeaders: false),
            events: evt => { if (evt is RateLimitWaited) throw sentinel; }, timeProvider: clock);
        await using (await limiter.AcquireAsync()) { }

        var failed = limiter.AcquireAsync().AsTask();
        clock.Advance(TimeSpan.FromSeconds(1));
        var exception = await Assert.ThrowsAsync<InvalidOperationException>(() => failed);
        Assert.Same(sentinel, exception);

        var recovered = limiter.AcquireAsync().AsTask();
        clock.Advance(TimeSpan.FromSeconds(1));
        await using var lease = await recovered;
    }

    [Theory]
    [InlineData("garbage", null)]
    [InlineData("NaN", null)]
    public void Header_parser_keeps_malformed_and_nan_distinct_from_the_int64_boundary(string raw, long? expected)
    {
        var headers = new Dictionary<string, string> { ["x"] = raw };
        Assert.Equal(expected, RateLimitParsing.ReadCount(headers, "x"));
    }

    [Fact]
    public void Header_parser_rejects_out_of_range_values_and_reset_parser_handles_native_forms()
    {
        Assert.Throws<OverflowException>(() => RateLimitParsing.ReadCount(
            new Dictionary<string, string> { ["x"] = "9223372036854775808" }, "x"));
        Assert.Throws<OverflowException>(() => RateLimitParsing.ReadCount(
            new Dictionary<string, string> { ["x"] = "9223372036854775807.9" }, "x"));
        Assert.Throws<OverflowException>(() => RateLimitParsing.ReadCount(
            new Dictionary<string, string> { ["x"] = "Infinity" }, "x"));
        Assert.Throws<OverflowException>(() => RateLimitParsing.ReadCount(
            new Dictionary<string, string> { ["x"] = "-Infinity" }, "x"));
        var clock = new VirtualTimeProvider();
        Assert.Equal(5400d, RateLimitParsing.ParseResetSeconds("1h30m", clock));
        Assert.Null(RateLimitParsing.ParseResetSeconds("-5", clock));
        Assert.Equal(0d, RateLimitParsing.ParseResetSeconds("0", clock));
    }

    [Theory]
    [InlineData("2026-01-01T00:00:30Z", 30d)]
    [InlineData("20260101T000030Z", 30d)]
    [InlineData("2026-W01-4T00:00:30Z", 30d)]
    [InlineData("2026-01-01\n00:00:30Z", 30d)]
    [InlineData("2026-01-01😀00:00:30Z", 30d)]
    [InlineData("2026-01-01T01:00:30+01:00", 30d)]
    [InlineData("2026-01-01T00:00:31.123456789Z", 31.123456d)]
    [InlineData("2026-01-01T00:00:31+00:00:00.5000001", 30.5d)]
    public void Reset_parser_accepts_aware_iso_forms_with_one_unicode_scalar_separator(string text, double expected)
    {
        var actual = Assert.IsType<double>(RateLimitParsing.ParseResetSeconds(text, new VirtualTimeProvider()));
        Assert.Equal(expected, actual, precision: 6);
    }

    [Theory]
    [InlineData("2026-01-01T00:00:30")]
    [InlineData("01/01/2026T00:00:30Z")]
    [InlineData("2026-01-01TT00:00:30Z")]
    public void Reset_parser_rejects_naive_non_iso_and_two_scalar_separator_forms(string text)
    {
        Assert.Null(RateLimitParsing.ParseResetSeconds(text, new VirtualTimeProvider()));
    }

    private sealed class VirtualTimeProvider : TimeProvider
    {
        private readonly object _gate = new();
        private readonly List<VirtualTimer> _timers = [];
        private DateTimeOffset _utc = new(2026, 1, 1, 0, 0, 0, TimeSpan.Zero);
        private long _timestamp;

        internal List<double> Delays { get; } = [];
        public override DateTimeOffset GetUtcNow() => _utc;
        public override long GetTimestamp() => _timestamp;
        public override TimeZoneInfo LocalTimeZone => TimeZoneInfo.Utc;
        public override ITimer CreateTimer(TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period)
        {
            var timer = new VirtualTimer(this, callback, state, dueTime, period);
            lock (_gate)
            {
                _timers.Add(timer);
            }

            return timer;
        }

        internal void Advance(TimeSpan amount)
        {
            if (amount < TimeSpan.Zero)
            {
                throw new ArgumentOutOfRangeException(nameof(amount));
            }

            var target = _utc + amount;
            while (true)
            {
                VirtualTimer? next;
                lock (_gate)
                {
                    next = _timers.Where(timer => timer.IsDueAtOrBefore(target)).OrderBy(timer => timer.Due).FirstOrDefault();
                    if (next is null)
                    {
                        var remaining = target - _utc;
                        _utc = target;
                        _timestamp += remaining.Ticks;
                        return;
                    }

                    var elapsed = next.Due - _utc;
                    _utc = next.Due;
                    _timestamp += elapsed.Ticks;
                    next.Fire();
                }
            }
        }

        private sealed class VirtualTimer : ITimer
        {
            private readonly VirtualTimeProvider _owner;
            private readonly TimerCallback _callback;
            private readonly object? _state;
            private TimeSpan _period;
            private bool _disposed;

            internal VirtualTimer(VirtualTimeProvider owner, TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period)
            {
                _owner = owner;
                _callback = callback;
                _state = state;
                _period = period;
                Due = owner._utc + dueTime;
                owner.Delays.Add(dueTime.TotalSeconds);
            }

            internal DateTimeOffset Due { get; private set; }
            internal bool IsDueAtOrBefore(DateTimeOffset value) => !_disposed && Due <= value;

            public bool Change(TimeSpan dueTime, TimeSpan period)
            {
                if (_disposed)
                {
                    return false;
                }

                _period = period;
                Due = _owner._utc + dueTime;
                _owner.Delays.Add(dueTime.TotalSeconds);
                return true;
            }

            public void Dispose() => _disposed = true;
            public ValueTask DisposeAsync()
            {
                Dispose();
                return ValueTask.CompletedTask;
            }

            internal void Fire()
            {
                if (_disposed)
                {
                    return;
                }

                if (_period <= TimeSpan.Zero || _period == Timeout.InfiniteTimeSpan)
                {
                    _disposed = true;
                }
                else
                {
                    Due = _owner._utc + _period;
                }

                _callback(_state);
            }
        }
    }
}
