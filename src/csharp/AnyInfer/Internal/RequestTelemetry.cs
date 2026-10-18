using AnyInfer.Core;
using AnyInfer.Events;
using AnyInfer.Manifest;

namespace AnyInfer.Internal;

/// <summary>Prepared terminal facts that are published only by the owning stream.</summary>
internal readonly record struct PreparedCompletion(RunManifest? Manifest, RequestCompleted Event);

/// <summary>Owns one request's telemetry folding without owning stream publication.</summary>
internal sealed class RequestTelemetry
{
    private readonly NormalizedRequest _request;
    private readonly Route _route;
    private readonly EventDispatcher? _dispatcher;
    private readonly ManifestBuilder? _builder;
    private readonly string _requestId;
    private int _started;

    internal RequestTelemetry(NormalizedRequest request, Route route, EventDispatcher? dispatcher, ManifestBuilder? builder, string requestId)
    {
        _request = request ?? throw new ArgumentNullException(nameof(request));
        _route = route ?? throw new ArgumentNullException(nameof(route));
        _dispatcher = dispatcher;
        _builder = builder;
        _requestId = requestId ?? throw new ArgumentNullException(nameof(requestId));
    }

    internal string RequestId => _requestId;
    internal bool WantsPayloads => _dispatcher?.WantsPayloads == true;
    internal RunManifest? Partial => _builder?.BuildPartial();

    internal void Start()
    {
        if (Interlocked.Exchange(ref _started, 1) != 0)
        {
            return;
        }

        Emit(new RequestStarted(_requestId, _route.Targets, promptText: WantsPayloads ? Prompt() : null));
    }

    internal void NoteCapabilities(TargetMetadata metadata) => _builder?.NoteCapabilities(metadata);
    internal void NoteRepairText(string text) => _builder?.NoteRepairText(text);

    internal void Emit(TelemetryEvent telemetryEvent)
    {
        ArgumentNullException.ThrowIfNull(telemetryEvent);
        _builder?.Fold(telemetryEvent);
        _dispatcher?.Emit(RedactObserverPayload(telemetryEvent));
    }

    internal PreparedCompletion PrepareCompletion(Generation result)
    {
        ArgumentNullException.ThrowIfNull(result);
        if (result.Target is null)
        {
            throw new InvalidOperationException("A completed generation must have a resolved target.");
        }

        var usage = result.Usage ?? new Usage();
        var timing = result.Timing ?? new Timing();
        return new PreparedCompletion(
            _builder?.Build(result),
            new RequestCompleted(
                _requestId,
                result.Target,
                usage,
                timing,
                result.RepairAttempts,
                WantsPayloads && !string.IsNullOrEmpty(result.Text) ? Redaction.Redact(result.Text) : null));
    }

    /// <summary>Publishes the already folded terminal event after stream ownership commits it.</summary>
    internal void Complete(PreparedCompletion prepared) => _dispatcher?.Emit(prepared.Event);
    internal void Fail(AnyInferException failure) => Emit(new RequestFailed(_requestId, failure.Snapshot()));

    private string Prompt() => Redaction.Redact(string.Join("\n\n", _request.Messages
        .Select(static message => string.Concat(message.Content.OfType<Text>().Select(static text => text.Value)))
        .Where(static text => !string.IsNullOrEmpty(text))));

    private static TelemetryEvent RedactObserverPayload(TelemetryEvent telemetryEvent) => telemetryEvent switch
    {
        RepairAttempted repair => new RepairAttempted(
            repair.RequestId,
            repair.Target,
            repair.AttemptNumber,
            repair.Mechanism,
            repair.Errors.Select(Redaction.Redact),
            repair.RawText is null ? null : Redaction.Redact(repair.RawText)),
        _ => telemetryEvent,
    };
}
