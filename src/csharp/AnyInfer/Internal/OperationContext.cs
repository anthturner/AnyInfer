using AnyInfer.Providers;
using AnyInfer.Schema;

namespace AnyInfer.Internal;

internal enum EntryRole
{
    Original,
    Correction,
}

internal sealed class OperationContext
{
    private readonly object _gate = new();
    private int _nextOrdinal;

    internal OperationContext(OperationCapture? capture = null, TimeProvider? entryTimeProvider = null)
    {
        OperationId = Guid.NewGuid();
        Capture = capture;
        EntryTimeProvider = entryTimeProvider;
        Capture?.BindOperation(OperationId);
    }

    internal Guid OperationId { get; }
    internal OperationCapture? Capture { get; }
    internal TimeProvider? EntryTimeProvider { get; }
    internal EntryContext? LastEntry { get; private set; }
    internal NativeAssessment? LastAssessment { get; private set; }
    internal bool IsClosed { get; private set; }

    internal EntryContext BeginEntry(
        WireRequest request,
        EntryRole role,
        NativeAssessment? repairAssessment)
    {
        ArgumentNullException.ThrowIfNull(request);
        lock (_gate)
        {
            if (IsClosed)
            {
                throw new InvalidOperationException("The operation context is already complete.");
            }

            ValidateRepairAssessment(role, repairAssessment);

            var entry = new EntryContext(
                OperationId,
                checked(++_nextOrdinal),
                role,
                request,
                repairAssessment,
                Capture);
            LastEntry = entry;
            return entry;
        }
    }

    internal void RecordAssessment(NativeAssessment assessment)
    {
        ArgumentNullException.ThrowIfNull(assessment);
        lock (_gate)
        {
            if (IsClosed)
            {
                throw new InvalidOperationException("The operation context is already complete.");
            }

        ValidateCurrentAssessment(assessment, nameof(assessment));
            LastAssessment = assessment;
            Capture?.RecordAssessment(assessment);
        }
    }

    internal void Complete()
    {
        lock (_gate)
        {
            IsClosed = true;
        }
    }

    private void ValidateRepairAssessment(EntryRole role, NativeAssessment? repairAssessment)
    {
        if (role == EntryRole.Original && repairAssessment is not null)
        {
            throw new ArgumentException("Original entries cannot carry a repair assessment.", nameof(repairAssessment));
        }

        if (role == EntryRole.Correction && repairAssessment is null)
        {
            throw new ArgumentNullException(nameof(repairAssessment), "Correction entries require the latest assessment.");
        }

        if (repairAssessment is null)
        {
            return;
        }

        if (!ReferenceEquals(LastAssessment, repairAssessment))
        {
            throw new ArgumentException("Correction must use the latest recorded assessment instance.", nameof(repairAssessment));
        }

        ValidateCurrentAssessment(repairAssessment, nameof(repairAssessment));
    }

    private void ValidateCurrentAssessment(NativeAssessment assessment, string parameterName)
    {
        if (assessment.OperationId != OperationId)
        {
            throw new ArgumentException("Assessment belongs to another operation.", parameterName);
        }

        if (LastEntry is null || assessment.SourceEntryOrdinal != LastEntry.Ordinal)
        {
            throw new ArgumentException("Assessment must belong to the latest observed entry.", parameterName);
        }
    }
}
