# Observe Requests, and Bridge to OpenTelemetry

Every request emits typed [telemetry events](../concepts/telemetry.md) as it runs. This
page shows how to consume them in-process and how to export them to OpenTelemetry; the
[event stream](../concepts/events.md) page covers the per-request events a stream consumer
sees. The Python SDK and the C# SDK (prerelease) share the observer model and the event
records; the ready-made sinks differ, and the OpenTelemetry bridge and configuration-named sinks
are Python-only. Each section shows the C# form where one exists.

## In-Process Observers

=== "Python"

    ```python
    import anyinfer as ai


    class Metrics:
        def on_event(self, event: ai.TelemetryEvent) -> None:
            match event:
                case ai.FirstToken(at_ms=ms, target=target):
                    histogram("ttft_ms", ms, provider=target.provider_id)
                case ai.AttemptCompleted(usage=usage, target=target):
                    counter("tokens_out", usage.output_tokens or 0, provider=target.provider_id)
                case ai.RetryScheduled(error=error):
                    counter("retries", 1, error=error.type_name)
                case ai.RequestFailed(error=error):
                    counter("failures", 1, error=error.type_name)


    client = ai.Client(providers, observers=[Metrics()])
    ```

=== "C# SDK (prerelease)"

    ```csharp
    --8<-- "examples/csharp-sdk/TelemetryExample.cs"
    ```

    A C# observer implements `IObserver.OnEvent` and receives typed records such as
    `FirstToken`, `AttemptCompleted`, `RetryScheduled`, and `RequestFailed`; match on them with
    a `switch` over the record type. Observers passed to the client constructor, or subscribed
    with `client.Subscribe(observer)`, stay owned by the application. See the
    [C# telemetry recipe](csharp-sdk.md#observe-telemetry-and-manifests).

Keep the handler (`on_event` in Python, `OnEvent` in C#) fast: it runs inline on the request
path, so queue anything slow. An observer that raises is isolated and warned about once: a
broken telemetry sink must never fail a generation.

## Catch Silent Degradation

Two events exist specifically to make otherwise-invisible problems visible. A Python observer
that watches for both:

```python
class DegradationWatch:
    def on_event(self, event):
        match event:
            case ai.ParameterDropped(parameter=p, target=t, reason=why):
                log.warning("%s ignored %s: %s", t, p, why)
            case ai.UsageEstimated(field_name=field, method=how):
                log.info("usage.%s was estimated via %s", field, how)
```

`ParameterDropped` fires when a provider accepts a parameter and discards it: the failure
mode where `temperature=0` silently does nothing and looks exactly like success. The C# SDK
emits the same `ParameterDropped` and `UsageEstimated` records; an `OnEvent` handler matches them
by type.

`RateLimitWaited` belongs to the same family. A request held back by
[client-side pacing](../concepts/routing.md#pacing-before-the-limit) is indistinguishable
from a slow provider unless something says so, which is why the wait also lands in
`result.timing.phases["queued_ms"]`.

## Payload Privacy

Prompt and response text are `None` (`null` in C#) unless an observer opts in, and stripping
happens per observer:

=== "Python"

    ```python
    client.subscribe(metrics)  # never sees text
    client.subscribe(audit_trail, payloads=True)  # sees prompt and response
    ```

=== "C# SDK (prerelease)"

    ```csharp
    --8<-- "examples/csharp-sdk/TelemetrySinksExample.cs:observe"
    ```

    Observers passed to the C# client constructor are always payload-free;
    `Subscribe(observer, payloads: true)` is the only opt-in.

Everything still passes redaction first, so a resolved credential cannot appear even in a
payload-carrying event.

## A JSONL Trail

An audit trail ships with the library — `JsonlObserver` appends one redacted JSON object
per line to a file it opens once and holds:

```python
import anyinfer as ai

with ai.JsonlObserver("telemetry.jsonl") as trail:
    client.subscribe(trail)
```

On POSIX the file is created at mode `0600`, since even payload-free telemetry names
targets, models, and spend. Windows has no equivalent through `chmod` — the file is not
owner-restricted there, so put it somewhere whose ACL already excludes other accounts.

`LoggingObserver` is the same idea aimed at a `logging.Logger`: the event name is the
message and the full mapping rides as an `anyinfer_event` record attribute, so a JSON
formatter renders it while a plain one still prints something readable.

In Python, neither sink needs code to configure. Both can be named from the
[shared configuration file](../reference/configuration.md#the-observers-block), which is
the only way to reach them from the [sidecar](../serve/README.md):

```json
{
  "observers": [
    "logging",
    {"name": "jsonl", "options": {"path": "/var/log/anyinfer/telemetry.jsonl"}}
  ]
}
```

Sinks are described, not built: loading a configuration file never opens a log file.
`anyinfer.config.build_observers` constructs them when a frontend decides to observe. A
config-named sink is always payload-free — the opt-in above is a *code* decision, and a
file that could be edited into leaking prompt text would be the wrong default. See
[the ready-made sinks](../reference/api/telemetry.md#ready-made-sinks) for the full
signatures.

**Writing your own** is still first-class and unchanged: an observer is any object with an
`on_event` method, and `anyinfer.events.sinks.event_to_dict` is public precisely so a
third sink can reuse the redacting serializer rather than reinvent it.

### Trace and JSONL Sinks in C#

The C# SDK has its own `LoggingObserver` and `JsonlObserver`, and both are created in code: its
version 1 configuration reader rejects an `observers` block. `LoggingObserver` writes each event
as one compact, redacted JSON line through a `System.Diagnostics.TraceSource`, not a
`logging.Logger`. Created without a source, it makes an `AnyInfer.Telemetry` source whose switch
is off, so it records nothing unless that source is configured from outside the observer. The
direct path is to pass a source whose switch level and listeners the application sets:

```csharp
--8<-- "examples/csharp-sdk/TelemetrySinksExample.cs:trace"
```

`JsonlObserver` appends one redacted JSON line per event to a path the application chooses,
creating missing directories; on platforms other than Windows the file is restricted to owner
read and write, as in Python. It holds the file open until it is disposed, so dispose it after
the client, as the payload example above does. Both sinks are payload-free when passed to the
constructor. `TelemetryEvent.ToDictionary()` exposes the same redacted projection for a sink of
your own. The once-per-subscription warning for an observer that throws goes to the
`AnyInfer.Events` trace source, whose switch is also off by default.

The C# event vocabulary also declares records for features the C# SDK does not have:
`ArenaCompleted`, `ContextReduced`, `ServerLifecycle`, `DownloadProgress`, `BatchSubmitted`,
`BatchCompleted`, and `CredentialRotated` are never emitted by the C# core. The prompt-cache prefix
`ProviderDiagnostic` currently carries a `null` `RequestId`, so correlate it by target. The
[C# sink recipe](csharp-sdk.md#write-telemetry-to-a-trace-source-or-file) lists what its offline
cases check.

## OpenTelemetry

```python
from anyinfer import otel

otel.install(client)  # payload-free
otel.install(client, record_payloads=True)  # include prompt/response text
```

Needs the `[otel]` extra; nothing OTel-related is imported otherwise. The bridge is
Python-only: the C# SDK has no OpenTelemetry integration, and its telemetry reaches only the
observers you subscribe.

You get one span per request with attempts as span events, plus
`gen_ai.client.token.usage`, `gen_ai.client.operation.duration`, and
`gen_ai.server.time_to_first_token`, using GenAI semantic-convention attribute names so
standard tooling reads them.

Every event type in the contract crosses the bridge. Events about one request become span
events on that request's span. Events that belong to no single request become standalone spans,
since attaching them to an arbitrary in-flight request would misattribute the work:
`ArenaCompleted`, `RateLimitObserved`, `BatchSubmitted`, `BatchCompleted`, `CredentialRotated`,
`ContextReduced`, `ServerLifecycle`, and the final `DownloadProgress` of a download (earlier
progress events are not exported). A `ProviderDiagnostic` or `RateLimitWaited` with no matching
request span, such as a wait during a model listing, becomes a standalone span too. The bridge is
[a consumer of the event contract](../concepts/telemetry.md#the-opentelemetry-bridge), so
consuming events directly and exporting to OTel are both first-class, and you can do both.

## Cost

```python
if result.usage.cost_usd is not None:
    ledger.record(result.usage.cost_usd)
else:
    ledger.record_unknown(result.target)  # do NOT record this as zero
```

`None` means unknown, not free. Treating the two the same turns a reporting gap into a
silent financial error. See
[cost is tri-state](../concepts/cost.md#cost-is-tri-state).

In C#, `Usage.CostUsd` is `null` when the cost is unknown. A caller-owned `SpendLedger` given to
the client records completed requests itself, counts unpriced ones in `UnknownRequests` rather
than adding zero, and reports `SpendTotals.Complete` as false while any are present; see
[share a ledger and persist spend](csharp-sdk.md#share-a-ledger-and-persist-spend).

!!! tip "Key Takeaways"
    - Observers run inline on the request path: keep them fast, and know that one which
      raises is isolated rather than allowed to fail a generation.
    - `ParameterDropped`, `UsageEstimated`, and `RateLimitWaited` make degradation visible
      that would otherwise look exactly like success.
    - Payloads are opt-in per observer, and redaction runs before any event is delivered;
      a sink named from a configuration file is always payload-free.
    - `LoggingObserver` and `JsonlObserver` ship with the library and, in Python, can be named
      from configuration, so an audit trail needs no code.
    - In C#, sinks are created in code, `LoggingObserver` writes nothing until its trace source
      switch is enabled, and there is no OpenTelemetry bridge.
    - The OTel bridge consumes the same event contract as your observers, so the two
      paths never disagree and can run side by side.
    - Never record an unknown cost as zero; `cost_usd` is `None` when the price is not
      trusted.

## See Also

<div class="anyinfer-see-also" markdown>

- [Telemetry and observers](../concepts/telemetry.md): the full event contract and the
  OTel mapping.
- [The event stream](../concepts/events.md): per-request events and their ordering
  guarantees.
- [Cost and spending](../concepts/cost.md): the ledger and spend ceilings behind
  `cost_usd`.
- [C# SDK guide](csharp-sdk.md#observe-requests): the native observer, sink, and manifest
  recipes.

</div>
