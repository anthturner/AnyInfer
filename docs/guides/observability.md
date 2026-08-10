# Observe requests, and bridge to OpenTelemetry

## In-process observers

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

Keep `on_event` fast — it runs inline on the request path, so queue anything slow. An
observer that raises is isolated and warned about once: a broken telemetry sink must never
fail a generation.

## Catch silent degradation

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

`ParameterDropped` fires when a provider accepts a parameter and discards it — the failure
mode where `temperature=0` silently does nothing and looks exactly like success.

`RateLimitWaited` belongs to the same family. A request held back by
[client-side pacing](../concepts/rate-limits.md) is indistinguishable from a slow provider
unless something says so, which is why the wait also lands in
`result.timing.phases["queued_ms"]`.

## Payload privacy

Prompt and response text are `None` unless an observer opts in, and stripping happens per
observer:

```python
client.subscribe(metrics)  # never sees text
client.subscribe(audit_trail, payloads=True)  # sees prompt and response
```

Everything still passes redaction first, so a resolved credential cannot appear even in a
payload-carrying event.

## A JSONL trail

```python
import json
from dataclasses import asdict


class JsonlTrail:
    def __init__(self, path):
        self._file = open(path, "a", encoding="utf-8")

    def on_event(self, event):
        record = {"event": type(event).__name__, **asdict(event)}
        self._file.write(json.dumps(record, default=str) + "\n")
        self._file.flush()
```

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

Every event in the contract crosses the bridge — nothing is dropped. Events carrying a
`request_id` become span events on that request's span (`target.resolved`,
`attempt.started`, `first_token`, `retry.scheduled`, `fallback.triggered`,
`schema.repair`, `parameter.dropped`, `usage.estimated`). The three events that belong to
no single request — `ContextReduced`, `ServerLifecycle`, `DownloadProgress` — become
standalone spans (`context.reduced`, `server.lifecycle`, `download.completed`), because
attaching them to an arbitrary in-flight request would misattribute work that happens
outside it. A crashed server sets an error status on its span, and only the terminal
download event becomes a span — per-chunk progress would flood the exporter.

The bridge is a *consumer* of the event contract rather than the contract itself, so
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
[capabilities](../concepts/capabilities.md#cost-is-tri-state).
