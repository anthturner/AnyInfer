using System.Net;
using System.Text.Json;
using AnyInfer.Events;
using AnyInfer.Manifest;

namespace AnyInfer.Examples.Cases;

/// <summary>Runs the ticket-triage audit trail offline: typed events, the JSONL sink and manifests.</summary>
internal static class CookbookObservabilityCases
{
    private const string Ticket = "My parcel never arrived.";

    private static readonly Route TriageRoute = new(["primary:triage", "backup:triage"], retry: new Retry(MaxAttempts: 1));

    private static readonly string[] FallbackSequence =
    [
        "RequestStarted", "TargetResolved", "AttemptStarted", "UsageEstimated", "FallbackTriggered",
        "TargetResolved", "AttemptStarted", "UsageEstimated", "FirstToken", "AttemptCompleted", "RequestCompleted",
    ];

    [ExampleCase("cookbook.observability.audit-trail")]
    internal static async Task AuditTrail()
    {
        var (primary, backup) = Handlers();
        using var directory = new TemporaryDirectory();
        var log = Path.Combine(directory.Path, "audit", "events.jsonl");

        var trail = await CookbookObservabilityExample.TriageAsync(Providers(primary, backup), TriageRoute, "T-42", Ticket, log);

        // Typed events: one request ID, payload text removed, the fallback's cause kept as a safe summary.
        var events = trail.Events;
        var requestId = trail.Terminal.RequestId;
        ExampleSupport.Require(events.Select(static item => item.GetType().Name).SequenceEqual(FallbackSequence)
            && events.All(item => item.ToDictionary().TryGetValue("request_id", out var id) && id is Json.JsonString { Value: var value } && value == requestId)
            && events[0] is RequestStarted { PromptText: null } started && started.Metadata["ticket"] == "T-42"
            && events[4] is FallbackTriggered { ToTarget: "backup:triage", Error: { TypeName: "ProviderUnavailableException", HttpStatus: 503 } }
            && events[^1] is RequestCompleted { ResponseText: null, Usage.TotalTokens: 46 } completed
            && completed.Target.ToString() == "backup:triage",
            "The audit observer did not receive the payload-free typed event sequence of the fallback.");

        // Manifests: incomplete before the stream is consumed, committed after, and the same request.
        var terminal = trail.Terminal;
        ExampleSupport.Require(trail.Partial is { Complete: false, Attempts.Count: 0, Route.Resolved: null }
            && trail.Partial.RequestId == requestId
            && ReferenceEquals(terminal, trail.Generation.Manifest)
            && terminal is { Complete: true, Payloads: null, Route.Resolved: "backup:triage" }
            && terminal.Route.Considered.Select(static step => step.Outcome).SequenceEqual(["abandoned", "ok"])
            && terminal.Attempts.Select(static attempt => (attempt.Target, attempt.Outcome)).SequenceEqual([("primary:triage", "failed"), ("backup:triage", "ok")])
            && terminal.Attempts[0].Error is { TypeName: "ProviderUnavailableException", HttpStatus: 503 }
            && terminal.Request.MetadataKeys.SequenceEqual(["ticket"])
            && terminal.Request is { SchemaPresent: true, SchemaName: "triage" }
            && terminal.Request.SchemaDigest == trail.SchemaDigest
            && trail.SchemaDigest.StartsWith("sha256:", StringComparison.Ordinal)
            && terminal.Structured is { Used: "prompt", Validated: true }
            && terminal.Usage is { InputTokens: 40, OutputTokens: 6, CostUsd: null },
            "The terminal manifest did not record the route, attempts, schema digest and usage of the run.");

        // Archive and render: the JSON round-trips, the rendering is for people, and neither holds the ticket text.
        ExampleSupport.Require(RunManifest.FromJson(trail.ArchivedJson).ToJson() == trail.ArchivedJson
            && !trail.ArchivedJson.Contains(Ticket, StringComparison.Ordinal)
            && trail.Rendered.StartsWith($"run {requestId} - complete", StringComparison.Ordinal)
            && !trail.Rendered.Contains(Ticket, StringComparison.Ordinal)
            && trail.Rendered.Contains("cost        unknown (no trusted pricing)", StringComparison.Ordinal)
            && trail.Generation.Structured is Json.JsonObject structured
            && structured.TryGetValue("queue", out var queue) && queue is Json.JsonString { Value: "shipping" },
            "The archived manifest did not round-trip, or a rendering or archive leaked the ticket text.");

        // The JSONL sink saw the same sequence; the client never disposed it, and the program's using did.
        var lines = File.ReadAllLines(log);
        ExampleSupport.Require(lines.Select(static line => JsonDocument.Parse(line).RootElement.GetProperty("event").GetString()).SequenceEqual(FallbackSequence)
            && !File.ReadAllText(log).Contains(Ticket, StringComparison.Ordinal)
            && IsClosed(log)
            && primary.DisposeCount == 1
            && backup.DisposeCount == 1,
            "The JSONL sink did not record the payload-free sequence or was left open.");
    }

    [ExampleCase("cookbook.observability.payload-opt-in")]
    internal static async Task PayloadOptIn()
    {
        var (primary, backup) = Handlers();
        using var directory = new TemporaryDirectory();
        var log = Path.Combine(directory.Path, "events.jsonl");

        var trail = await CookbookObservabilityExample.TriageAsync(
            Providers(primary, backup), TriageRoute, "T-43", Ticket, log, includePayloads: true);

        // Payloads reach only the observer that opted in; the sink and the manifest stay payload-free.
        ExampleSupport.Require(trail.Events[0] is RequestStarted { PromptText: { } prompt } && prompt.EndsWith(Ticket, StringComparison.Ordinal)
            && trail.Events[^1] is RequestCompleted { ResponseText: """{"queue":"shipping"}""" }
            && trail.Terminal.Payloads is null
            && File.ReadAllLines(log).All(static line => !line.Contains(Ticket, StringComparison.Ordinal)),
            "Payload delivery was not limited to the observer that opted in.");
    }

    [ExampleCase("cookbook.observability.failed-request-logged")]
    internal static async Task FailedRequestLogged()
    {
        var primary = new CookbookScriptedHandler(CookbookReplies.Status(HttpStatusCode.ServiceUnavailable));
        var backup = new CookbookScriptedHandler(CookbookReplies.Status(HttpStatusCode.BadGateway));
        using var directory = new TemporaryDirectory();
        var log = Path.Combine(directory.Path, "events.jsonl");

        AllTargetsFailedException? failure = null;
        try
        {
            await CookbookObservabilityExample.TriageAsync(Providers(primary, backup), TriageRoute, "T-44", Ticket, log);
        }
        catch (AllTargetsFailedException exception)
        {
            failure = exception;
        }

        // The durable sink keeps the failed request's trail even though the program returned nothing.
        var events = File.ReadAllLines(log).Select(static line => JsonDocument.Parse(line).RootElement).ToArray();
        ExampleSupport.Require(failure is { Attempts.Count: 2 }
            && events[0].GetProperty("event").GetString() == "RequestStarted"
            && events[^1].GetProperty("event").GetString() == "RequestFailed"
            && events[^1].GetProperty("error").GetProperty("type_name").GetString() == "AllTargetsFailedException"
            && events.Count(static item => item.GetProperty("event").GetString() == "FallbackTriggered") == 1
            && IsClosed(log),
            "A failed request's events were not kept by the caller-owned sink.");
    }

    private static (CookbookScriptedHandler Primary, CookbookScriptedHandler Backup) Handlers() =>
    (
        new CookbookScriptedHandler(CookbookReplies.Status(HttpStatusCode.ServiceUnavailable)),
        new CookbookScriptedHandler(CookbookReplies.Sse(
            CookbookReplies.Delta("""{"queue":"""), CookbookReplies.Delta("\"shipping\"}"), CookbookReplies.Finish(40, 6), "[DONE]"))
    );

    private static ProviderSettings[] Providers(HttpMessageHandler primary, HttpMessageHandler backup) =>
    [
        ProviderSettings.Of("openai-compat", "https://primary.offline/v1", transport: primary, alias: "primary"),
        ProviderSettings.Of("openai-compat", "https://backup.offline/v1", transport: backup, alias: "backup"),
    ];

    private static bool IsClosed(string path)
    {
        using var exclusive = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None);
        return exclusive.Length > 0;
    }

    private sealed class TemporaryDirectory : IDisposable
    {
        internal string Path { get; } = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"anyinfer-cookbook-{Guid.NewGuid():N}");

        public void Dispose()
        {
            if (Directory.Exists(Path)) Directory.Delete(Path, recursive: true);
        }
    }
}
