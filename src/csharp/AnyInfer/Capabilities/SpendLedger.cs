using System.Collections.ObjectModel;
using AnyInfer.Events;
using AnyInfer.Internal;
using PeterO.Numbers;

namespace AnyInfer.Capabilities;

/// <summary>Rolls completed request spend into caller-owned, in-process immutable snapshots.</summary>
public sealed class SpendLedger : IObserver
{
    private readonly object _gate = new();
    private readonly string _currency;
    private SpendTotals _overall;
    private readonly Dictionary<string, SpendTotals> _byTarget = new(StringComparer.Ordinal);
    private readonly Dictionary<string, Dictionary<string, SpendTotals>> _byLabel = new(StringComparer.Ordinal);
    private readonly Dictionary<string, IReadOnlyDictionary<string, string>> _metadata = new(StringComparer.Ordinal);
    private readonly Dictionary<string, EDecimal> _reservations = new(StringComparer.Ordinal);

    /// <summary>Creates an empty ledger for the supplied currency spelling.</summary>
    public SpendLedger(string currency = "USD")
    {
        _currency = currency ?? throw new ArgumentNullException(nameof(currency));
        _overall = new SpendTotals(currency: _currency);
    }

    /// <summary>Records telemetry without owning observer lifetime or performing I/O.</summary>
    public void OnEvent(TelemetryEvent telemetryEvent)
    {
        ArgumentNullException.ThrowIfNull(telemetryEvent);
        switch (telemetryEvent)
        {
            case RequestStarted started when started.Metadata.Count != 0:
                lock (_gate)
                {
                    _metadata[started.RequestId] = CopySnapshot(started.Metadata);
                }
                break;
            case RequestFailed failed:
                lock (_gate)
                {
                    _metadata.Remove(failed.RequestId);
                    _reservations.Remove(failed.RequestId);
                }
                break;
            case RequestCompleted completed:
                Record(completed.Target, completed.Usage, completed.RequestId);
                break;
        }
    }

    /// <summary>Folds one successful request into overall, target, and caller-label snapshots.</summary>
    public void Record(ResolvedTarget target, Usage usage, string? requestId = null)
    {
        ArgumentNullException.ThrowIfNull(target);
        ArgumentNullException.ThrowIfNull(usage);
        lock (_gate)
        {
            var metadata = requestId is not null && _metadata.Remove(requestId, out var found)
                ? found
                : EmptyMetadata;
            if (requestId is not null)
            {
                _reservations.Remove(requestId);
            }

            _overall = _overall.Plus(usage);
            var targetKey = target.ToString();
            _byTarget[targetKey] = Existing(_byTarget, targetKey).Plus(usage);
            foreach (var (label, value) in metadata)
            {
                if (!_byLabel.TryGetValue(label, out var values))
                {
                    values = new Dictionary<string, SpendTotals>(StringComparer.Ordinal);
                    _byLabel.Add(label, values);
                }

                values[value] = Existing(values, value).Plus(usage);
            }
        }
    }

    /// <summary>Replaces one request reservation if its total remains within the supplied ceiling.</summary>
    public (bool Accepted, EDecimal Spent, EDecimal Reserved) Reserve(string requestId, EDecimal estimate, EDecimal? ceiling)
    {
        ArgumentNullException.ThrowIfNull(requestId);
        ArgumentNullException.ThrowIfNull(estimate);
        lock (_gate)
        {
            var previous = _reservations.TryGetValue(requestId, out var current) ? current : EDecimal.Zero;
            var reserved = EDecimal.Zero;
            foreach (var value in _reservations.Values)
            {
                reserved = AccountingDecimal.Add(reserved, value);
            }

            reserved = AccountingDecimal.Subtract(reserved, previous);
            var spent = _overall.Cost;
            var projected = AccountingDecimal.Add(AccountingDecimal.Add(spent, reserved), estimate);
            if (ceiling is not null && AccountingDecimal.Compare(projected, ceiling) > 0)
            {
                return (false, spent, reserved);
            }

            _reservations[requestId] = estimate;
            return (true, spent, reserved);
        }
    }

    /// <summary>Releases a request reservation without changing completed spend.</summary>
    public void Release(string requestId)
    {
        ArgumentNullException.ThrowIfNull(requestId);
        lock (_gate)
        {
            _reservations.Remove(requestId);
        }
    }

    /// <summary>Removes request-local accounting state after an operation that did not complete.</summary>
    internal void Abandon(string requestId)
    {
        ArgumentNullException.ThrowIfNull(requestId);
        lock (_gate)
        {
            _metadata.Remove(requestId);
            _reservations.Remove(requestId);
        }
    }

    /// <summary>Gets the exact sum of current reservations.</summary>
    public EDecimal Reserved()
    {
        lock (_gate)
        {
            var total = EDecimal.Zero;
            foreach (var reservation in _reservations.Values)
            {
                total = AccountingDecimal.Add(total, reservation);
            }

            return total;
        }
    }

    /// <summary>Gets all completed spend observed by this ledger.</summary>
    public SpendTotals Totals()
    {
        lock (_gate)
        {
            return _overall;
        }
    }

    /// <summary>Gets completed spend by resolved target in first-seen order.</summary>
    public IReadOnlyDictionary<string, SpendTotals> ByTarget()
    {
        lock (_gate)
        {
            return CopySnapshot(_byTarget);
        }
    }

    /// <summary>Gets completed spend by one caller metadata label in first-seen order.</summary>
    public IReadOnlyDictionary<string, SpendTotals> ByLabel(string key)
    {
        ArgumentNullException.ThrowIfNull(key);
        lock (_gate)
        {
            return _byLabel.TryGetValue(key, out var values)
                ? CopySnapshot(values)
                : EmptyTotals;
        }
    }

    /// <summary>Clears all observed spend, metadata, and reservations.</summary>
    public void Reset()
    {
        lock (_gate)
        {
            _overall = new SpendTotals(currency: _currency);
            _byTarget.Clear();
            _byLabel.Clear();
            _metadata.Clear();
            _reservations.Clear();
        }
    }

    private SpendTotals Existing(IReadOnlyDictionary<string, SpendTotals> values, string key) =>
        values.TryGetValue(key, out var total) ? total : new SpendTotals(currency: _currency);

    private static readonly IReadOnlyDictionary<string, string> EmptyMetadata =
        new ReadOnlyDictionary<string, string>(new Dictionary<string, string>(StringComparer.Ordinal));
    private static readonly IReadOnlyDictionary<string, SpendTotals> EmptyTotals =
        new ReadOnlyDictionary<string, SpendTotals>(new Dictionary<string, SpendTotals>(StringComparer.Ordinal));

    private static IReadOnlyDictionary<string, T> CopySnapshot<T>(IReadOnlyDictionary<string, T> values) =>
        new ReadOnlyDictionary<string, T>(new Dictionary<string, T>(values, StringComparer.Ordinal));
}
