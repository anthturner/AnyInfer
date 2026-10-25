using System.Collections.ObjectModel;
using AnyInfer.Events;
using AnyInfer.Internal;
using PeterO.Numbers;

namespace AnyInfer.Capabilities;

/// <summary>Rolls completed request spend into caller-owned, in-process immutable snapshots.</summary>
/// <remarks>
/// <para>
/// The ledger is accounting for the clients it is given to, in this process only; there is no process-wide
/// ledger, and nothing is persisted unless the caller uses <see cref="SpendStore"/>. A client constructed with
/// a ledger subscribes it to its telemetry, and two clients share a total only when given the same ledger.
/// </para>
/// <para>
/// Costs come from each request's reported <see cref="Usage.CostUsd"/>. A request whose cost is unknown is
/// counted in <see cref="SpendTotals.UnknownRequests"/> and never treated as free. All members are safe to
/// call concurrently.
/// </para>
/// </remarks>
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
    /// <param name="currency">Currency code recorded on every snapshot; costs are summed without conversion.</param>
    /// <exception cref="ArgumentNullException"><paramref name="currency"/> is <see langword="null"/>.</exception>
    public SpendLedger(string currency = "USD")
    {
        _currency = currency ?? throw new ArgumentNullException(nameof(currency));
        _overall = new SpendTotals(currency: _currency);
    }

    /// <summary>Records telemetry without owning observer lifetime or performing I/O.</summary>
    /// <remarks>
    /// <see cref="RequestStarted"/> metadata is held as labels until the request ends, <see cref="RequestCompleted"/>
    /// is folded in with <see cref="Record"/>, and <see cref="RequestFailed"/> discards the request's labels and
    /// reservation. Other events are ignored.
    /// </remarks>
    /// <param name="telemetryEvent">Event emitted by a client.</param>
    /// <exception cref="ArgumentNullException"><paramref name="telemetryEvent"/> is <see langword="null"/>.</exception>
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
    /// <param name="target">Target that served the request; its <c>provider:model</c> text keys <see cref="ByTarget"/>.</param>
    /// <param name="usage">Reported usage; a <see langword="null"/> cost counts the request as unknown-cost.</param>
    /// <param name="requestId">
    /// Request correlation identifier whose held labels and reservation are consumed, or <see langword="null"/>
    /// to record without labels.
    /// </param>
    /// <exception cref="ArgumentNullException"><paramref name="target"/> or <paramref name="usage"/> is <see langword="null"/>.</exception>
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
    /// <remarks>
    /// The check and the reservation happen atomically under the ledger's lock. A refused reservation leaves any
    /// earlier reservation for <paramref name="requestId"/> in place.
    /// </remarks>
    /// <param name="requestId">Request correlation identifier the reservation belongs to.</param>
    /// <param name="estimate">Estimated cost to reserve; replaces this request's previous reservation.</param>
    /// <param name="ceiling">Total-spend ceiling, or <see langword="null"/> to reserve without a limit.</param>
    /// <returns>
    /// Whether the reservation was accepted, the known completed spend, and the sum of other requests'
    /// reservations; it is refused when spend plus those reservations plus <paramref name="estimate"/> exceeds
    /// <paramref name="ceiling"/>.
    /// </returns>
    /// <exception cref="ArgumentNullException"><paramref name="requestId"/> or <paramref name="estimate"/> is <see langword="null"/>.</exception>
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
    /// <param name="requestId">Request correlation identifier; releasing an unknown identifier does nothing.</param>
    /// <exception cref="ArgumentNullException"><paramref name="requestId"/> is <see langword="null"/>.</exception>
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
    /// <returns>The sum of outstanding reserved estimates; zero when none are held.</returns>
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
    /// <returns>
    /// An immutable snapshot. Read <see cref="SpendTotals.Cost"/> together with
    /// <see cref="SpendTotals.UnknownRequests"/>: the cost omits requests that could not be priced.
    /// </returns>
    public SpendTotals Totals()
    {
        lock (_gate)
        {
            return _overall;
        }
    }

    /// <summary>Gets completed spend by resolved target in first-seen order.</summary>
    /// <returns>A new immutable snapshot keyed by <c>provider:model</c> target text.</returns>
    public IReadOnlyDictionary<string, SpendTotals> ByTarget()
    {
        lock (_gate)
        {
            return CopySnapshot(_byTarget);
        }
    }

    /// <summary>Gets completed spend by one caller metadata label in first-seen order.</summary>
    /// <remarks>Labels are the request metadata the caller supplied; the ledger never interprets them.</remarks>
    /// <param name="key">Metadata key, such as a tenant or feature label.</param>
    /// <returns>A new immutable snapshot keyed by that label's values; empty when the key was never seen.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="key"/> is <see langword="null"/>.</exception>
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
