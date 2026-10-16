using System.Diagnostics;

namespace AnyInfer.Core;

internal interface IOperationClock
{
    double NowSeconds { get; }

    ValueTask DelayAsync(double seconds, CancellationToken cancellationToken = default);
}

internal sealed class SystemOperationClock : IOperationClock
{
    private static readonly double Frequency = Stopwatch.Frequency;

    public double NowSeconds => Stopwatch.GetTimestamp() / Frequency;

    public ValueTask DelayAsync(double seconds, CancellationToken cancellationToken = default)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(seconds);
        return new ValueTask(Task.Delay(TimeSpan.FromSeconds(seconds), cancellationToken));
    }
}
