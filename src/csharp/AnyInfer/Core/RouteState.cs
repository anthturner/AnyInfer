namespace AnyInfer.Core;

internal sealed class RouteState
{
    private readonly IOperationClock _clock;
    private readonly object _gate = new();
    private readonly Dictionary<Target, double> _failedAt = [];

    internal RouteState(IOperationClock clock)
    {
        _clock = clock ?? throw new ArgumentNullException(nameof(clock));
    }

    internal bool IsUnhealthy(Target target, double healthTtlS)
    {
        ArgumentNullException.ThrowIfNull(target);
        lock (_gate)
        {
            if (!_failedAt.TryGetValue(target, out var failedAt))
            {
                return false;
            }

            if (_clock.NowSeconds - failedAt >= healthTtlS)
            {
                _failedAt.Remove(target);
                return false;
            }

            return true;
        }
    }

    internal void MarkFailed(Target target)
    {
        ArgumentNullException.ThrowIfNull(target);
        lock (_gate)
        {
            _failedAt[target] = _clock.NowSeconds;
        }
    }

    internal void Clear(Target target)
    {
        ArgumentNullException.ThrowIfNull(target);
        lock (_gate)
        {
            _failedAt.Remove(target);
        }
    }

    internal void SeedFailure(Target target, double failedAtSeconds)
    {
        ArgumentNullException.ThrowIfNull(target);
        lock (_gate)
        {
            _failedAt[target] = failedAtSeconds;
        }
    }

    internal static double BackoffSeconds(RetryPolicy policy, int attemptNumber, double? retryAfterS)
    {
        ArgumentNullException.ThrowIfNull(policy);
        if (attemptNumber < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(attemptNumber));
        }

        var exponential = policy.BackoffBaseS * Math.Pow(2, attemptNumber - 1);
        var floor = Math.Max(exponential, retryAfterS ?? 0);
        return Math.Clamp(floor, 0, policy.BackoffMaxS);
    }
}
