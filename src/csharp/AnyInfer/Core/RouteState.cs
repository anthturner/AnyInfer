namespace AnyInfer.Core;

internal sealed class RouteState
{
    private readonly IOperationClock _clock;
    private readonly object _gate = new();
    private readonly Dictionary<(string ProviderId, string Model), double> _failedAt = [];

    internal RouteState(IOperationClock clock)
    {
        _clock = clock ?? throw new ArgumentNullException(nameof(clock));
    }

    internal bool IsUnhealthy(ResolvedTarget target, double healthTtlS)
    {
        ArgumentNullException.ThrowIfNull(target);
        lock (_gate)
        {
            var key = Key(target);
            if (!_failedAt.TryGetValue(key, out var failedAt))
            {
                return false;
            }

            if (_clock.NowSeconds - failedAt >= healthTtlS)
            {
                _failedAt.Remove(key);
                return false;
            }

            return true;
        }
    }

    internal void MarkFailed(ResolvedTarget target)
    {
        ArgumentNullException.ThrowIfNull(target);
        lock (_gate)
        {
            _failedAt[Key(target)] = _clock.NowSeconds;
        }
    }

    internal void Clear(ResolvedTarget target)
    {
        ArgumentNullException.ThrowIfNull(target);
        lock (_gate)
        {
            _failedAt.Remove(Key(target));
        }
    }

    internal void SeedFailure(ResolvedTarget target, double failedAtSeconds)
    {
        ArgumentNullException.ThrowIfNull(target);
        lock (_gate)
        {
            _failedAt[Key(target)] = failedAtSeconds;
        }
    }

    internal static double BackoffSeconds(Retry policy, int attemptNumber, double? retryAfterS)
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

    private static (string ProviderId, string Model) Key(ResolvedTarget target) =>
        (target.ProviderId, target.Model);
}
