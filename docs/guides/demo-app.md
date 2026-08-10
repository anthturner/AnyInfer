# The pack-in demo application

AnyInfer ships a PySide6 reference application in [`src/demo_app/`](https://github.com/anthturner/AnyInfer/blob/main/src/demo_app). It
is a *worked example of integration*, not part of the library's public API; nothing in
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
| `choice` | Combo box over the field's declared `choices` |
| `path` | Line edit with a file picker |
| `directory` | Line edit with a directory picker |
| `host-profile` | Line edit |
| `text` | Line edit |

`File → App settings…` holds preferences that are not properties of one provider. Its
local-inference override can expose accelerator runtime variants that hardware detection
normally disables; builds absent for the current OS/architecture remain unavailable.

The kind decides the *hint* as much as the widget. A field a provider declares as an
`endpoint` may reasonably be offered `https://…` in an empty editor; a model directory, a
resource posture, and a tenant id may not, and a UI has no way to tell them apart unless
the descriptor says so.

Install a third-party adapter that advertises itself through the `anyinfer.providers`
entry-point group and it appears in this dialog automatically, correctly rendered, with no
change to the demo.

The dialog also asks as little as it can. A provider marks the fields it already has a
standard value for, and those go behind an **Advanced** disclosure instead of into the
form, so adding OpenAI asks for a key rather than for a key, a base URL, and an API
version, and adding Ollama or vLLM asks for nothing at all. Collapsed fields still show
the value they will use, are still saved, and the disclosure opens by itself whenever a
stored setting overrides one of them: hiding a setting that is in force would trade one
confusion for a worse one.

### Conversations are tabs

Each conversation lives in its own tab, titled from the gist of its first message
("Build me a retro 486 that I can play Commander Keen on" becomes *Build Retro 486 Play
Commander Keen*; a deterministic heuristic, because asking the model to name the chat
would silently spend a request per conversation). Tabs close from a hover-revealed ×,
and their context menu carries New / Open Saved… / Rename / Save As ▸ / Delete / Close /
Close All. Completed conversations save automatically; **Open Saved…** brings one back as
a tab, while **Save As** writes a portable Markdown or JSON copy.

Tabs are not cosmetic: generations are **keyed by conversation**, so two tabs can stream
from two providers at the same time and every delta lands in the transcript that asked
for it. The composer's single action button follows the *active tab's* state; Send when
idle, Stop while that tab streams, and the right-hand inspector sidebar snaps shut when
dragged below a usable width.

### Streaming is the primitive

The transcript is written from `TextDelta` events as they arrive, never assembled at the
end. `ReasoningDelta` text goes to a separate collapsible region, because reasoning is
explicitly *not* part of the answer.

The metrics strip shows only what the core measured or the provider reported; a value
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
  quantization, e.g. `qwen3:8b; 8.2B · Q4_K_M`). The field stays editable, so a model the
  engine has not listed yet can be typed in. The ↻ button re-runs discovery.
- **Context window** shows the token budget with an auto-detect toggle (the wand button).
  While auto-detect is on, the disabled field shows the token count actually on file for
  the current engine/model; e.g. *Auto-Detected (32,768 tokens)*, and its tooltip names
  the value's provenance (`discovered`, `catalog`, or `default`), because capability data
  is provenance-tagged and an estimate is never presented as authoritative.
  Toggling auto-detect off frees the field for a manual override, which is remembered
  across sessions.

Under the hood the bar still just produces the `provider:model` string that
[`Route`](../concepts/routing.md) consumes; the demo adds no routing logic of its own.

### Routing, retry, and fallback

The **Fallback** dropdown adds an optional second target to the route, chosen
from everything discovery has reported. Four offline models make the behaviour
reproducible without a real outage:

| Model | Behaviour |
| --- | --- |
| `reliable` | Answers immediately. |
| `flaky` | Fails its first call with a retryable 503, then succeeds. |
| `slow` | Streams in smaller fragments. |
| `tools` | Answers a plain request with a tool call, and a request carrying a tool result with text; the whole shape of a tool loop, offline. |

Pick the `flaky` model with **Max attempts/target** at 1 and `demo-fake:reliable` as the
fallback to watch the router fall back, or set attempts to 2 to watch it retry and recover
in place. Failed attempts appear inline in the transcript and in the telemetry tree.

### Request options beyond sampling

The three-by-three **Request options** panel under the composer is collapsible and starts
closed, keeping the conversation area primary. It also carries:

- **Reasoning**: the normalized effort levels (`minimal` … `high`). The blank entry
  means the field is omitted entirely; a provider without the control drops it and
  reports the drop as telemetry rather than failing.
- **Reuse session**: threads turns through one `Session` handle per target. The status
  line reports what actually happened after each turn; `resumed`, `fresh`, or
  `unsupported`, because the provider decides, never the client. Against a local Ollama
  the effect is visible immediately: the second turn's time-to-first-token collapses once
  the provider resumes.
- **History**: opt-in conversation compaction via `HistoryPolicy`: trim only when the
  request would not fit, or proactively on every turn. Trimming is never silent; each
  reduction emits a `ContextReduced` telemetry event with the kept/omitted counts and
  the token arithmetic behind them.
- **Prompt cache**: opt-in placement via `CachePolicy`. No policy means cached exactly
  as before: not at all. With one, the plan (mechanism and mark placement) arrives as a
  `CachePlanned` telemetry event; a target with no cache mechanism reports a
  `ParameterDropped` instead of pretending.
- The token hint above the input comes from `Client.budget()` and appends a **cost range**
  when the pricing table has an entry for the target. Its preflight help button sits beside
  that readout, and an absent price renders as nothing because it is not a free request.

### The target inspector and the tool loop

Two right-hand sections go a level deeper than the Providers panel:

- **Target inspector**: four library calls against the selected `provider:model`, with
  their price tags on the buttons: **Capabilities** (`resolve()`, free, provenance-tagged
  values), **Verify** (one request), **Probe** (one request per feature), and
  **Benchmark ×2** (two identical deterministic requests, back to back). These are the
  demo's only buttons that spend real tokens, and they say so.

    The benchmark runs as a *pair* on purpose. Whether a local engine (Ollama,
    llama.cpp, vLLM) already had the model in memory is not knowable from outside, so
    the demo controls the protocol instead of guessing: run 2 is warm by construction —
    it starts the moment run 1 finishes, and the report compares the two. Matching
    numbers mean the engine was already warm; a large first-run gap is the load cost
    run 1 absorbed.
- **Tool loop**: two ordinary Python functions declared with `@tool`, handed to
  `Client.run_tools()`. The panel lists the functions that *actually executed*, because a
  model claiming it called something is not evidence that it did. Pick
  `demo-fake:tools` to watch the full round trip offline.

### Local Inference (Tools → Local Inference…)

The first **System** tab turns the same detected hardware profile used by the catalog into
CPU, RAM, accelerator, VRAM, model-storage, backend, and driver cards. Branded text badges
identify familiar CPU/GPU vendors without shipping trademarked logo artwork. Storage shows
capacity and current free space; it does not claim a speed without performing a separate,
intrusive disk workload.

**Benchmark** has its own tab. Its target list is built from installed AnyInfer weights and
the installed/served inventories of configured local engines. It runs a deterministic cold
and immediately-following warm request, plots estimated decode throughput and best-effort
CPU/GPU/RAM/VRAM utilization live, then replaces estimates with the provider's terminal
timings. The System tab summarizes that measured profile instead of collapsing a
model/runtime/workload-specific result into a misleading universal score.

**Catalog** is the unified model manager. It overlays `installed_models()` and the inventories
reported by enabled local services onto the `local_catalog()` view, with a distinct
**Installed For** column preserving ownership. A provider-reported model that is not in the
shipped catalog still gets its own row. The Engines and Installed For columns use the Ollama
and llama.cpp marks with accessible name tooltips; other engines retain text labels. Only
AnyInfer-owned rows offer removal.

The tab's **Add…** dialog searches the verified catalog by enabled engine: llama.cpp
artifacts are pinned Hugging Face GGUFs and Ollama choices use catalog tags handed to
`pull_model()`. An exact provider-owned model id outside the shipped catalog can be entered
there too. Models are ranked by catalog hardware fit, estimated free disk is called out,
and deliberately unreasonable choices remain visible as warnings. The former Installed and
Engine pull tabs are therefore no longer separate surfaces.

**Runtimes** is llama.cpp-specific: its contents stay hidden until that provider is enabled,
and its one selector suggests the SDK's machine recommendation while disabling choices the
detected hardware cannot drive. Every choice keeps the same **Install Runtime** action. A
successful install also makes that backend the demo-wide llama.cpp default, and the installed
runtime table marks the selected backend with a check. vLLM and Ollama manage different
runtime environments and are therefore not presented as llama.cpp runtime variants.

### How is this built? The `</>` chips

Every major surface carries a small `</>` chip. Clicking one opens the SDK story for that
surface: what it shows, the public `anyinfer` calls that implement it, a copyable
plain-Python snippet doing the same thing, and where in the demo source it is wired. The
prose lives in one registry (`demo_app/sdk_help.py`), and a test resolves every named
symbol against the real package, so the help cannot silently drift from the API.

**Help → Library map…** shows the wider picture: which public `anyinfer` symbols this
demo exercises, surface by surface, plus the list it does not. The Help menu
also links the documentation and SDK reference, lists the demo's third-party licenses
(PySide6/Qt, Tabler Icons, Python-Markdown), and carries the About box.

### Appearance

The demo follows the OS light/dark appearance by default and repaints live when it
changes; *View → Theme* overrides it explicitly. *View → Sidebar* contains the one
whole-sidebar switch followed by checkboxes for each inspector section. The palette is the
project's own
deep-teal-and-amber brand palette (`docs/assets/anyinfer-palette.css`), rendered as a Qt
stylesheet in [`demo_app/theme.py`](https://github.com/anthturner/AnyInfer/blob/main/src/demo_app/theme.py). The choice is persisted with the rest of the
demo's settings.

## The integration pattern worth copying

Qt owns the main thread; the `Client` owns a background loop thread.
[`demo_app/engine.py`](https://github.com/anthturner/AnyInfer/blob/main/src/demo_app/engine.py) keeps them
apart:

- Every call runs on a `QThreadPool` worker; never on the GUI thread.
- Results cross back as Qt signals, which Qt marshals to the GUI thread.
- No widget touches AnyInfer directly, and the engine touches no widget.

Calling `client.generate()` from a button handler instead would freeze the UI for the length
of the request.

Equally important is what the demo *does not* contain: no retry loop, no fallback logic, no
schema validation, and no timing measurement. Those belong to the library, and duplicating
any of them in an application is the mistake this demo exists to prevent.

## Tests

The demo is covered by [`tests/demo_app/`](https://github.com/anthturner/AnyInfer/blob/main/tests/demo_app), which runs headless
(`QT_QPA_PLATFORM=offscreen`) and drives real generations; streaming, retry, fallback, and
structured output; through the offline provider:

```bash
pytest tests/demo_app             # or the full suite: python workspace.py check --only=test
```

## See also

- [Choosing an integration path](integration-paths.md)
- [Stream to a terminal](streaming.md): the same event stream, without Qt.
- [Observe requests](observability.md)
- [Add a fallback chain](fallback.md)
