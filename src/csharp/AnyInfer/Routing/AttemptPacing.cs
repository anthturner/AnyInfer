using AnyInfer.Events;

namespace AnyInfer.Routing;

internal sealed class AttemptPacing : IDisposable
{
    private static readonly AsyncLocal<AttemptPacing?> CurrentValue = new();
    private readonly AttemptPacing? _previous;
    private int _detached;

    internal AttemptPacing(string requestId, ResolvedTarget? target = null)
    {
        RequestId = requestId ?? throw new ArgumentNullException(nameof(requestId));
        Target = target;
        _previous = CurrentValue.Value;
        CurrentValue.Value = this;
    }

    internal string RequestId { get; }
    internal ResolvedTarget? Target { get; }
    internal double WaitedS { get; private set; }
    internal IReadOnlyList<string> Reasons => _reasons;
    internal bool Waited => WaitedS > 0;
    internal double WaitedMs => WaitedS * 1000;
    internal static AttemptPacing? Current => CurrentValue.Value;
    private readonly List<string> _reasons = [];

    internal void Record(double waitedS, string reason)
    {
        WaitedS += waitedS;
        _reasons.Add(reason);
    }

    internal void Detach()
    {
        if (Interlocked.Exchange(ref _detached, 1) == 0 && ReferenceEquals(CurrentValue.Value, this))
        {
            CurrentValue.Value = _previous;
        }
    }

    public void Dispose() => Detach();
}
