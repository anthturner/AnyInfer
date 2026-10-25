# Build an Audit Trail from Telemetry and Manifests

A support-ticket triage call in native C# that leaves an audit trail. An application observer keeps
the typed telemetry events of the call, a JSONL sink appends the same events to a file the
application owns, and the call's run manifest is read before and after the stream, checked against
the manifest schema embedded in the SDK, archived as JSON, and rendered for a person. By default
none of it contains the ticket text.

## Before You Start

- The .NET 8 SDK and a reference to the local C# prerelease, as described in
  [Install the C# SDK](../guides/csharp-installation.md), and the first call from the
  [C# quickstart](../guides/csharp-quickstart.md). The C# SDK is a locally packaged
  `0.1.0-proof` prerelease, not a NuGet package.
- Nothing else to run it offline. Against a real endpoint, pass `ProviderSettings` and a route
  for it; the audit trail does not depend on the provider.

## The Program

```csharp
--8<-- "examples/csharp-sdk/CookbookObservabilityExample.cs"
```

## How It Works

- **Observers are synchronous and caller-owned.** The client calls `IObserver.OnEvent` on the
  thread that produced the event, possibly from concurrent requests, so `CookbookAuditObserver`
  only appends under a lock. An exception thrown by an observer is suppressed rather than failing
  the request. The client never disposes an observer or sink: the program's `using` closes the
  `JsonlObserver` file, after the client has been disposed.
- **Payloads are opt-in per subscription.** Observers passed to the constructor, like the JSONL
  sink, always receive events with prompt and response text removed. `Subscribe` with
  `payloads: true` opts in one observer; the others, and the manifest, stay payload-free.
  Manifest payload capture is a separate client setting, `manifestPayloads`.
- **One request, one ID.** Every event of the call carries the same request ID as its manifest.
  For a primary that fails and a backup that answers, the observer sees `RequestStarted`, then
  `TargetResolved`, `AttemptStarted`, and `UsageEstimated` for the primary, `FallbackTriggered`
  with a credential-safe `ErrorInfo`, the same three events for the backup, then `FirstToken`,
  `AttemptCompleted`, and `RequestCompleted`. `UsageEstimated` is the context gate's pre-dispatch
  input estimate, which runs by default; the usage in `RequestCompleted` is what the provider
  reported.
- **Partial, then terminal.** With manifest capture on, `stream.Manifest` is available before the
  stream is consumed and is marked incomplete, with no attempts and no resolved target. After
  completion, `Generation.Manifest` holds the committed manifest: requested and resolved route, each
  attempt with its error summary, the structured-output ladder and mechanism used, usage, timing,
  and the request's metadata keys without their values.
- **The schema digest identifies the contract, not the content.** The manifest records the
  `sha256:` digest of the request's schema, computed as `ManifestUtilities.SchemaDigest` computes
  it, so archived runs can be grouped by output contract without storing the schema body.
- **Archive and render.** `ManifestUtilities.JsonSchema()` returns the embedded manifest schema;
  validating against it with `SchemaValidator` before archiving catches a manifest your tooling
  cannot read. `ToJson` and `RunManifest.FromJson` round-trip the archived text, and
  `ManifestUtilities.Render` produces the human-readable tree.

## Offline Run

The example runner sends the triage call through a primary that answers HTTP 503 and a backup that
streams the triage object, then asserts the trail. The cases are in
`examples/csharp-sdk/Cases/CookbookObservabilityCases.cs`; from `src/csharp`, run:

```bash
dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj --configuration Release
```

The `cookbook.observability.*` cases check that:

- the observer receives the eleven-event fallback sequence above, all with the manifest's request
  ID, with `PromptText` and `ResponseText` absent and the ticket label present as metadata;
- the partial manifest is incomplete, the terminal manifest is the generation's, records the
  abandoned primary and the successful backup, the schema name and digest, prompt-based
  enforcement, and reported usage with unknown cost;
- the archived JSON round-trips, the rendering starts with the run line, and neither contains the
  ticket text;
- the JSONL file holds the same event sequence without the ticket text and is closed when the
  program returns;
- an observer subscribed with payloads receives the prompt and response text while the JSONL sink
  and the manifest do not;
- when both targets fail, the program throws `AllTargetsFailedException` and the JSONL file still
  ends with `RequestFailed`.

## What Is Not Native

C# has no OpenTelemetry bridge: there is no equivalent of Python's `anyinfer.otel` installer,
span mapping, or GenAI metric instruments. To feed another telemetry system, write an `IObserver`
that forwards the typed events you need, or ship the JSONL file. Keep the observer fast, because
it runs on the request path.

## Before Production

- Put the JSONL file where your log shipping expects it and rotate it outside the process; the
  sink appends and never truncates.
- Keep payload capture off unless a specific observer needs text, and review where that observer
  writes.
- Archive manifests from completed generations; a partial manifest describes a stream that has
  not finished.
- Use one client per process, subscribe long-lived observers once, and unsubscribe with
  `Unsubscribe` when a subscriber goes away.

## See Also

<div class="anyinfer-see-also" markdown>

- [Telemetry](../concepts/telemetry.md) and [run manifests](../concepts/run-manifests.md).
- [Observability guide](../guides/observability.md), whose OpenTelemetry bridge is Python-only.
- [Regression-test fallback and repair](golden-manifest.md), the Python golden-manifest pattern.
- API: [`IObserver`](/csharp/api/anyinfer.events.iobserver/),
  [`TelemetryEvent`](/csharp/api/anyinfer.events.telemetryevent/),
  [`JsonlObserver`](/csharp/api/anyinfer.events.jsonlobserver/),
  [`FallbackTriggered`](/csharp/api/anyinfer.events.fallbacktriggered/),
  [`UsageEstimated`](/csharp/api/anyinfer.events.usageestimated/),
  [`RunManifest`](/csharp/api/anyinfer.manifest.runmanifest/),
  [`ManifestUtilities`](/csharp/api/anyinfer.manifest.manifestutilities/),
  [`SchemaValidator`](/csharp/api/anyinfer.schema.schemavalidator/).

</div>
