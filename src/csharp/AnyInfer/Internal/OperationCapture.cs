using AnyInfer.Core;
using AnyInfer.Providers;
using AnyInfer.Schema;

namespace AnyInfer.Internal;

internal sealed class OperationCapture
{
    private readonly object _gate = new();
    private readonly int _capacity;
    private readonly List<EntryContext> _entries = [];
    private readonly List<NativeAssessment> _assessments = [];
    private readonly List<LifecycleObservation> _lifecycle = [];
    private readonly List<string> _unavailableReasons = [];
    private readonly List<TelemetryObservation> _telemetry = [];
    private readonly List<RepairPreparation> _repairs = [];
    private Guid? _operationId;
    private long _nextSequence;
    private int _recordCount;
    private bool _writesFrozen;

    internal OperationCapture(int capacity = 4096)
    {
        if (capacity < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(capacity));
        }

        _capacity = capacity;
    }

    internal bool IsAvailable
    {
        get
        {
            lock (_gate)
            {
                return _unavailableReasons.Count == 0;
            }
        }
    }

    internal IReadOnlyList<string> UnavailableReasons
    {
        get
        {
            lock (_gate)
            {
                return Array.AsReadOnly(_unavailableReasons.ToArray());
            }
        }
    }

    internal IReadOnlyList<EntryContext> Entries
    {
        get
        {
            lock (_gate)
            {
                return Array.AsReadOnly(_entries.ToArray());
            }
        }
    }

    internal IReadOnlyList<NativeAssessment> Assessments
    {
        get
        {
            lock (_gate)
            {
                return Array.AsReadOnly(_assessments.ToArray());
            }
        }
    }

    internal IReadOnlyList<LifecycleObservation> Lifecycle
    {
        get
        {
            lock (_gate)
            {
                return Array.AsReadOnly(_lifecycle.ToArray());
            }
        }
    }

    internal IReadOnlyList<TelemetryObservation> Telemetry
    {
        get
        {
            lock (_gate)
            {
                return Array.AsReadOnly(_telemetry.ToArray());
            }
        }
    }

    internal IReadOnlyList<RepairPreparation> Repairs
    {
        get
        {
            lock (_gate)
            {
                return Array.AsReadOnly(_repairs.ToArray());
            }
        }
    }

    internal void RecordTelemetry(Guid operationId, TelemetryObservation observation)
    {
        ArgumentNullException.ThrowIfNull(observation);
        lock (_gate)
        {
            if (!CanWrite(operationId) || !Reserve())
            {
                return;
            }

            _telemetry.Add(observation);
        }
    }

    internal void RecordRepair(Guid operationId, RepairPreparation preparation)
    {
        ArgumentNullException.ThrowIfNull(preparation);
        lock (_gate)
        {
            if (!CanWrite(operationId) || !Reserve())
            {
                return;
            }

            _repairs.Add(preparation);
        }
    }
    internal void BindOperation(Guid operationId)
    {
        lock (_gate)
        {
            if (_operationId is null)
            {
                _operationId = operationId;
                return;
            }

            if (_operationId != operationId)
            {
                MarkUnavailableLocked("capture was reused by a different operation");
                _writesFrozen = true;
            }
        }
    }

    internal void RecordEntry(EntryContext entry)
    {
        lock (_gate)
        {
            if (!CanWrite(entry.OperationId) || !Reserve())
            {
                return;
            }

            _entries.Add(entry);
        }
    }

    internal void RecordAssessment(NativeAssessment assessment)
    {
        lock (_gate)
        {
            if (!CanWrite(assessment.OperationId) || !Reserve())
            {
                return;
            }

            _assessments.Add(assessment);
        }
    }

    internal void RecordLifecycle(Guid operationId, int entryOrdinal, string name)
    {
        lock (_gate)
        {
            if (!CanWrite(operationId) || !Reserve())
            {
                return;
            }

            _lifecycle.Add(new LifecycleObservation(_nextSequence++, entryOrdinal, name));
        }
    }

    internal void MarkUnavailable(string reason)
    {
        lock (_gate)
        {
            MarkUnavailableLocked(reason);
        }
    }

    internal void RecordAdapterEvent(EntryContext entry, AdapterEvent adapterEvent)
    {
        lock (_gate)
        {
            if (!CanWrite(entry.OperationId) || !Reserve())
            {
                return;
            }

            entry.RetainAdapterEvent(adapterEvent);
        }
    }

    private bool Reserve()
    {
        if (_recordCount >= _capacity)
        {
            MarkUnavailableLocked("capture capacity exhausted");
            _writesFrozen = true;
            return false;
        }

        _recordCount++;
        return true;
    }

    private bool CanWrite(Guid operationId)
    {
        if (_writesFrozen || _operationId != operationId)
        {
            return false;
        }

        return true;
    }

    private void MarkUnavailableLocked(string reason)
    {
        if (!_unavailableReasons.Contains(reason, StringComparer.Ordinal))
        {
            _unavailableReasons.Add(reason);
        }
    }
}

internal sealed record LifecycleObservation(long Sequence, int EntryOrdinal, string Name);
internal sealed record TelemetryObservation(string Name, string? Parameter = null, string? Reason = null, int? AttemptNumber = null);

internal sealed class EntryContext
{
    private readonly object _gate = new();
    private readonly List<AdapterEvent> _adapterEvents = [];

    internal EntryContext(
        Guid operationId,
        int ordinal,
        EntryRole role,
        WireRequest request,
        NativeAssessment? repairAssessment,
        OperationCapture? capture)
    {
        OperationId = operationId;
        Ordinal = ordinal;
        Role = role;
        Request = request;
        RepairAssessment = repairAssessment;
        Capture = capture;
    }

    internal Guid OperationId { get; }
    internal int Ordinal { get; }
    internal EntryRole Role { get; }
    internal WireRequest Request { get; }
    internal NativeAssessment? RepairAssessment { get; }
    internal EntryTimeoutScope Timeout { get; set; } = null!;
    internal Exception? NativeFailure { get; private set; }
    internal Exception? TerminalFailure { get; private set; }
    internal Exception? PriorNativeFailure { get; private set; }
    internal Exception? PriorTerminalFailure { get; private set; }

    internal IReadOnlyList<AdapterEvent> AdapterEvents
    {
        get
        {
            lock (_gate)
            {
                return Array.AsReadOnly(_adapterEvents.ToArray());
            }
        }
    }

    internal OperationCapture? Capture { get; }

    internal void RecordAdapterEvent(AdapterEvent adapterEvent)
    {
        Capture?.RecordAdapterEvent(this, adapterEvent);
    }

    internal void RetainAdapterEvent(AdapterEvent adapterEvent)
    {
        lock (_gate)
        {
            _adapterEvents.Add(adapterEvent);
        }
    }

    internal void RecordFailure(Exception nativeFailure, Exception terminalFailure)
    {
        lock (_gate)
        {
            if (TerminalFailure is not null)
            {
                PriorNativeFailure ??= NativeFailure;
                PriorTerminalFailure ??= TerminalFailure;
            }

            NativeFailure = nativeFailure;
            TerminalFailure = terminalFailure;
        }
    }
}
