using AnyInfer.Core;

namespace AnyInfer.Conformance;

/// <summary>Supplies deterministic route-health and retry time for development fixture runs.</summary>
internal sealed class VirtualClock : IOperationClock
{
    private readonly List<double> _delaysSeconds = [];

    internal VirtualClock(double startSeconds)
    {
        if (!double.IsFinite(startSeconds))
        {
            throw new ArgumentOutOfRangeException(nameof(startSeconds));
        }

        NowSeconds = startSeconds;
    }

    internal double NowSeconds { get; private set; }

    internal IReadOnlyList<double> DelaysSeconds => _delaysSeconds.AsReadOnly();

    double IOperationClock.NowSeconds => NowSeconds;

    public ValueTask DelayAsync(double seconds, CancellationToken cancellationToken = default)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(seconds);
        cancellationToken.ThrowIfCancellationRequested();
        if (seconds > 0)
        {
            _delaysSeconds.Add(seconds);
            NowSeconds += seconds;
        }

        return ValueTask.CompletedTask;
    }
}
