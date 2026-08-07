# The pack-in demo application

AnyInfer ships a PySide6 reference application in [`src/demo_app/`](https://github.com/anthturner/anyinfer/blob/main/src/demo_app). It
is a *worked example of integration*, not part of the library's public API — nothing in
`anyinfer` imports it, and nothing in it is importable from `anyinfer`.

It runs with **no credentials and no network**: the default configuration talks to an
in-process fake provider built on [`anyinfer.testing.fakes`](../contributing/testing.md).

## Running it

```bash
pip install -e ".[demo]"
anyinfer-demo
```

Or, from a checkout, via the [task runner](../contributing/README.md#the-task-runner) or the
module directly:

```bash
python workspace.py demo
python -m demo_app
```

Useful flags:

| Flag | Effect |
| --- | --- |
| `--config PATH` | Use a specific settings file instead of the per-user default. |
| `--reset` | Ignore saved settings and start from the offline defaults. |

## What it demonstrates

### Provider setup is generic

`File → Provider settings…` renders one panel per registered provider, and **contains no
per-provider code**. Each widget is chosen from the declared `SetupField.kind` on that
provider's `ProviderSetupSpec` (see [Configuration](../reference/configuration.md) and
[Providers](../providers/README.md)):

| Field kind | Rendered as |
| --- | --- |
| `endpoint` | Line edit, hinting the provider's host shorthand |
| `secret` | Password-masked edit that prefers `env://` references |
| `api-version` | Line edit |
| `model-list` | Editable combo box |
| `reasoning-efforts` | Combo box over the normalized effort levels |
| `host-profile` | Line edit |

Install a third-party adapter that advertises itself through the `anyinfer.providers`
entry-point group and it appears in this dialog automatically, correctly rendered, with no
change to the demo.

### Streaming is the primitive

The transcript is written from `TextDelta` events as they arrive, never assembled at the
end. `ReasoningDelta` text goes to a separate collapsible region, because reasoning is
explicitly *not* part of the answer.

The metrics strip shows only what the core measured or the provider reported — a value
AnyInfer was not given reads `—`, never `0`.

### Telemetry is a typed contract

The **Telemetry** tab is fed by a plain observer that re-emits each
[`TelemetryEvent`](../concepts/telemetry.md) as a Qt signal. Events are grouped under the
request that produced them, so a retry-then-fallback sequence reads as one tree.

The observer registers **without** `payloads=True`, so `prompt_text` and `response_text`
arrive as `None`. The inspector labels them "withheld" rather than showing them as empty —
payload privacy is visible, not implicit.

### Structured output and bounded repair

The **Structured output** tab sends a JSON Schema with the request and reports which
*mechanism* the core selected (`grammar`, `json_schema`, `json_mode`, or `prompt`) together
with the number of repair rounds it took. Validation is always against the canonical schema
regardless of the mechanism used on the wire.

### Picking an engine and model (no target strings)

The bar at the top of the window replaces hand-typed `provider:model` target strings:

- **Engine** lists every provider enabled under *File → Provider settings…*, by display
  name. It is populated from the registry, so third-party providers appear automatically.
- **Model** lists what the selected engine's `list_models()` discovery reported, decorated
  with the model's size when the engine says (Ollama reports parameter count and
  quantization, e.g. `qwen3:8b — 8.2B · Q4_K_M`). The field stays editable, so a model the
  engine has not listed yet can be typed in. The ↻ button re-runs discovery.
- **Context window** shows the token budget with an auto-detect toggle (the wand button).
  While auto-detect is on, the disabled field shows the token count actually on file for
  the current engine/model — e.g. *Auto-detected — 32,768 tokens* — and its tooltip names
  the value's provenance (`discovered`, `catalog`, or `default`), because capability data
  is provenance-tagged and an estimate is never presented as authoritative.
  Toggling auto-detect off frees the field for a manual override, which is remembered
  across sessions.

Under the hood the bar still just produces the `provider:model` string that
[`Route`](../concepts/routing.md) consumes — the demo adds no routing logic of its own.

### Routing, retry, and fallback

The **If it fails, try:** dropdown adds an optional second target to the route, chosen
from everything discovery has reported. Three offline models make the behaviour
reproducible without a real outage:

| Model | Behaviour |
| --- | --- |
| `reliable` | Answers immediately. |
| `flaky` | Fails its first call with a retryable 503, then succeeds. |
| `slow` | Streams in smaller fragments. |

Pick the `flaky` model with **Max attempts/target** at 1 and `demo-fake:reliable` as the
fallback to watch the router fall back, or set attempts to 2 to watch it retry and recover
in place. Failed attempts appear inline in the transcript and in the telemetry tree.

### Appearance

The demo follows the OS light/dark appearance by default and repaints live when it
changes; *View → Theme* overrides it explicitly. The palette is the project's own
deep-teal-and-amber brand palette (`docs/assets/anyinfer-palette.css`), rendered as a Qt
stylesheet in [`demo_app/theme.py`](https://github.com/anthturner/anyinfer/blob/main/src/demo_app/theme.py). The choice is persisted with the rest of the
demo's settings.

## The integration pattern worth copying

Qt owns the main thread; the `Client` owns a background loop thread.
[`demo_app/engine.py`](https://github.com/anthturner/anyinfer/blob/main/src/demo_app/engine.py) keeps them
apart:

- Every call runs on a `QThreadPool` worker — never on the GUI thread.
- Results cross back as Qt signals, which Qt marshals to the GUI thread.
- No widget touches AnyInfer directly, and the engine touches no widget.

Calling `client.generate()` from a button handler instead would freeze the UI for the length
of the request.

Equally important is what the demo *does not* contain: no retry loop, no fallback logic, no
schema validation, and no timing measurement. Those belong to the library, and duplicating
any of them in an application is the mistake this demo exists to prevent.

## Tests

The demo is covered by [`tests/demo_app/`](https://github.com/anthturner/anyinfer/blob/main/tests/demo_app), which runs headless
(`QT_QPA_PLATFORM=offscreen`) and drives real generations — streaming, retry, fallback, and
structured output — through the offline provider:

```bash
pytest tests/demo_app             # or the full suite: python workspace.py check --only=test
```

## See also

- [Choosing an integration path](integration-paths.md)
- [Stream to a terminal](streaming.md) — the same event stream, without Qt.
- [Observe requests](observability.md)
- [Add a fallback chain](fallback.md)
