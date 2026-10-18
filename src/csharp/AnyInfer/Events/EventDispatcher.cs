using System.Diagnostics;

namespace AnyInfer.Events;

/// <summary>Synchronously fans out events to caller-owned observers.</summary>
internal sealed class EventDispatcher
{
    private sealed class Subscription(IObserver observer, bool payloads)
    {
        internal IObserver Observer { get; } = observer;
        internal bool Payloads { get; } = payloads;
        internal bool Warned { get; set; }
    }

    private readonly object _gate = new();
    private readonly List<Subscription> _subscriptions = [];
    private readonly Action<string>? _warningSink;
    private static readonly TraceSource Trace = new("AnyInfer.Events");

    internal EventDispatcher(IEnumerable<IObserver>? observers = null, Action<string>? warningSink = null)
    {
        _warningSink = warningSink;
        foreach (var observer in observers ?? [])
        {
            Subscribe(observer);
        }
    }

    internal bool HasObservers { get { lock (_gate) return _subscriptions.Count != 0; } }
    internal bool WantsPayloads { get { lock (_gate) return _subscriptions.Any(static item => item.Payloads); } }

    internal void Subscribe(IObserver observer, bool payloads = false)
    {
        ArgumentNullException.ThrowIfNull(observer);
        lock (_gate) _subscriptions.Add(new Subscription(observer, payloads));
    }

    internal void Unsubscribe(IObserver observer)
    {
        ArgumentNullException.ThrowIfNull(observer);
        lock (_gate) _subscriptions.RemoveAll(item => ReferenceEquals(item.Observer, observer));
    }

    internal void Emit(TelemetryEvent telemetryEvent)
    {
        ArgumentNullException.ThrowIfNull(telemetryEvent);
        Subscription[] snapshot;
        lock (_gate) snapshot = _subscriptions.ToArray();
        TelemetryEvent? stripped = null;
        foreach (var subscription in snapshot)
        {
            try { subscription.Observer.OnEvent(subscription.Payloads ? telemetryEvent : stripped ??= TelemetrySerialization.StripPayloads(telemetryEvent)); }
            catch (Exception exception)
            {
                var warn = false;
                lock (_gate) { if (!subscription.Warned) { subscription.Warned = true; warn = true; } }
                if (warn) Warn(subscription.Observer, exception);
            }
        }
    }

    private void Warn(IObserver observer, Exception exception)
    {
        var message = Redaction.Redact($"observer {observer.GetType().Name} raised {exception.GetType().Name}: {exception.Message}; further errors suppressed");
        if (message.Length > 512) message = message[..512];
        try { if (_warningSink is not null) _warningSink(message); else Trace.TraceEvent(TraceEventType.Warning, 0, message); } catch { }
    }
}
