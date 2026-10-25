using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Manifest;
using AnyInfer.Schema;

namespace AnyInfer.Examples;

/// <summary>
/// A ticket triage call with an audit trail: an application observer keeps typed telemetry, a JSONL
/// sink appends it to a file the caller owns, and the run manifest is checked, archived and rendered.
/// </summary>
public static class CookbookObservabilityExample
{
    private static readonly SchemaSpec TriageSchema = SchemaSpec.FromJson("""
        {"$schema":"https://json-schema.org/draft/2020-12/schema","title":"triage","type":"object",
         "required":["queue"],"properties":{"queue":{"enum":["billing","shipping","account"]}}}
        """);

    /// <summary>Triages one ticket and returns its telemetry, manifests and archived manifest JSON.</summary>
    /// <param name="providers">The provider instances the route's targets name.</param>
    /// <param name="route">The ordered targets with their retry policy.</param>
    /// <param name="ticketId">The application's ticket ID, attached as request metadata.</param>
    /// <param name="ticket">The ticket text.</param>
    /// <param name="eventLogPath">The JSONL file the telemetry sink appends to; the caller owns it.</param>
    /// <param name="includePayloads">Whether the audit observer also receives prompt and response text.</param>
    /// <param name="cancellationToken">Cancels the request.</param>
    /// <returns>What the audit trail captured.</returns>
    public static async Task<CookbookAuditTrail> TriageAsync(
        IEnumerable<ProviderSettings> providers,
        Route route,
        string ticketId,
        string ticket,
        string eventLogPath,
        bool includePayloads = false,
        CancellationToken cancellationToken = default)
    {
        var audit = new CookbookAuditObserver();
        using var eventLog = new JsonlObserver(eventLogPath);
        await using var client = new AsyncClient(
            providers,
            route: route,
            observers: [eventLog],
            manifests: true,
            manifestPayloads: false);
        client.Subscribe(audit, payloads: includePayloads);

        await using var stream = client.StreamAsync(
            "Route this support ticket to a queue.\n\n" + ticket,
            schema: TriageSchema,
            metadata: new Dictionary<string, string> { ["ticket"] = ticketId },
            cancellationToken: cancellationToken);
        var partial = stream.Manifest
            ?? throw new InvalidOperationException("Manifest capture is enabled, so a stream always has a manifest.");
        var generation = await stream.CollectAsync(cancellationToken).ConfigureAwait(false);
        var terminal = generation.Manifest
            ?? throw new InvalidOperationException("A completed generation carries its terminal manifest.");

        // Check the manifest against the schema embedded in the SDK before archiving it.
        var check = await SchemaValidator.ValidateAsync(
            terminal.ToDictionary(),
            new SchemaSpec(ManifestUtilities.JsonSchema()),
            cancellationToken: cancellationToken).ConfigureAwait(false);
        if (!check.IsValid)
        {
            throw new InvalidOperationException("The manifest does not match the embedded manifest schema: " + string.Join("; ", check.Messages));
        }

        return new CookbookAuditTrail(
            generation,
            partial,
            terminal,
            terminal.ToJson(),
            ManifestUtilities.Render(terminal),
            ManifestUtilities.SchemaDigest((JsonObject)TriageSchema.JsonSchema),
            audit.Snapshot());
    }
}

/// <summary>An application observer that keeps each telemetry event it receives, in order.</summary>
/// <remarks>
/// The client calls it synchronously on the request path, possibly from several requests at once, so it
/// only appends under a lock. It never throws; an exception from an observer would be suppressed.
/// </remarks>
public sealed class CookbookAuditObserver : IObserver
{
    private readonly object _gate = new();
    private readonly List<TelemetryEvent> _events = [];

    /// <inheritdoc />
    public void OnEvent(TelemetryEvent telemetryEvent)
    {
        lock (_gate)
        {
            _events.Add(telemetryEvent);
        }
    }

    /// <summary>Returns the events received so far.</summary>
    /// <returns>An immutable copy, in delivery order.</returns>
    public IReadOnlyList<TelemetryEvent> Snapshot()
    {
        lock (_gate)
        {
            return _events.ToArray();
        }
    }
}

/// <summary>Everything the triage audit trail captured for one ticket.</summary>
/// <param name="Generation">The terminal generation.</param>
/// <param name="Partial">The manifest read before the stream was consumed.</param>
/// <param name="Terminal">The committed manifest of the completed stream.</param>
/// <param name="ArchivedJson">The terminal manifest as archived JSON.</param>
/// <param name="Rendered">The terminal manifest rendered for a human.</param>
/// <param name="SchemaDigest">The digest of the triage schema, as the manifest records it.</param>
/// <param name="Events">The typed telemetry events the audit observer received.</param>
public sealed record CookbookAuditTrail(
    Generation Generation,
    RunManifest Partial,
    RunManifest Terminal,
    string ArchivedJson,
    string Rendered,
    string SchemaDigest,
    IReadOnlyList<TelemetryEvent> Events);
