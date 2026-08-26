# Observe Requests, and Bridge to OpenTelemetry

Every request emits typed [telemetry events](../concepts/telemetry.md) as it runs. This
page shows how to consume them in-process and how to export them to OpenTelemetry; the
[event stream](../concepts/events.md) page covers the per-request events a stream consumer
sees.

## In-Process Observers

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

Keep `on_event` fast: it runs inline on the request path, so queue anything slow. An
observer that raises is isolated and warned about once: a broken telemetry sink must never
fail a generation.

## Catch Silent Degradation

Two events exist specifically to make otherwise-invisible problems visible:

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
mode where `temperature=0` silently does nothing and looks exactly like success.

`RateLimitWaited` belongs to the same family. A request held back by
[client-side pacing](../concepts/routing.md#pacing-before-the-limit) is indistinguishable
from a slow provider unless something says so, which is why the wait also lands in
`result.timing.phases["queued_ms"]`.

## Payload Privacy

Prompt and response text are `None` unless an observer opts in, and stripping happens per
observer:

```python
client.subscribe(metrics)  # never sees text
client.subscribe(audit_trail, payloads=True)  # sees prompt and response
```

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
owner-restricted there, so put it somewhere whose ACL already excludes other accounts. `LoggingObserver` is the same idea aimed at a `logging.Logger`: the
event name is the message and the full mapping rides as an `anyinfer_event` record
attribute, so a JSON formatter renders it while a plain one still prints something
readable.

Neither sink needs code to configure. Both can be named from the
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

## OpenTelemetry

```python
from anyinfer import otel

otel.install(client)  # payload-free
otel.install(client, record_payloads=True)  # include prompt/response text
```

Needs the `[otel]` extra; nothing OTel-related is imported otherwise.

You get one span per request with attempts as span events, plus
`gen_ai.client.token.usage`, `gen_ai.client.operation.duration`, and
`gen_ai.server.time_to_first_token`, using GenAI semantic-convention attribute names so
standard tooling reads them.

Every event in the contract crosses the bridge. Events carrying a `request_id` become span
events on that request's span, while the three that belong to no single request
(`ContextReduced`, `ServerLifecycle`, `DownloadProgress`) become standalone spans, since
attaching them to an arbitrary in-flight request would misattribute the work. The full
mapping is in [the OpenTelemetry bridge](../concepts/telemetry.md#the-opentelemetry-bridge);
the bridge is a consumer of the event contract, so consuming events directly and exporting
to OTel are both first-class, and you can do both.

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

!!! tip "Key Takeaways"
    - Observers run inline on the request path: keep them fast, and know that one which
      raises is isolated rather than allowed to fail a generation.
    - `ParameterDropped`, `UsageEstimated`, and `RateLimitWaited` make degradation visible
      that would otherwise look exactly like success.
    - Payloads are opt-in per observer, and redaction runs before any event is delivered;
      a sink named from a configuration file is always payload-free.
    - `LoggingObserver` and `JsonlObserver` ship with the library and can be named from
      configuration, so an audit trail needs no code.
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

</div>
