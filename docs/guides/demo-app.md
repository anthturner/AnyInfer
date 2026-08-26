# The Pack-In Demo Application

AnyInfer ships a PySide6 reference application in
[`src/anyinfer_demo/`](https://github.com/anthturner/AnyInfer/blob/main/src/anyinfer_demo).
It is a worked example of integration, not part of the library's public API; nothing in
`anyinfer` imports it, and nothing in it is importable from `anyinfer`. It runs with no
credentials and no network: the default configuration talks to an in-process fake
provider built on [`anyinfer.testing.fakes`](../contributing/testing.md), so every
subsystem it exercises is demonstrable offline.

## Running It

```bash
pip install -e ".[demo]"
anyinfer-demo
```

Or, from a checkout, via the [task runner](../contributing/README.md#the-task-runner) or
the module directly:

```bash
python workspace.py demo
python -m anyinfer_demo
```

| Flag | Effect |
| --- | --- |
| `--config PATH` | Use a specific settings file instead of the per-user default. |
| `--reset` | Ignore saved settings and start from the offline defaults. |

## The Integration Pattern Worth Copying

Qt owns the main thread; the `Client` owns a background loop thread.
[`anyinfer_demo/engine.py`](https://github.com/anthturner/AnyInfer/blob/main/src/anyinfer_demo/engine.py)
keeps them apart:

- Every call runs on a `QThreadPool` worker; never on the GUI thread.
- Results cross back as Qt signals, which Qt marshals to the GUI thread.
- No widget touches AnyInfer directly, and the engine touches no widget.

Calling `client.generate()` from a button handler instead would freeze the UI for the length
of the request.

Equally important is what the demo *does not* contain: no retry loop, no fallback logic, no
schema validation, and no timing measurement. Those belong to the library, and the demo's
job is to show how little an application needs to add on top of it.

## What It Demonstrates

Each surface is a small, inspectable use of one public subsystem:

- **Provider setup** renders one panel per registered provider from its declared
  `ProviderSetupSpec`, with no per-provider code; third-party adapters registered through
  the `anyinfer.providers` entry-point group appear automatically. See
  [configuration](../reference/configuration.md) and [providers](../providers/README.md).
- **Streaming** writes the transcript from `TextDelta` events as they arrive, with
  `ReasoningDelta` text in a separate collapsible region; two tabs can stream from two
  providers at once. See [stream to a terminal](streaming.md).
- **Telemetry** re-emits each typed event as a Qt signal through a plain observer
  registered without `payloads=True`, so prompt and response text are labeled "withheld"
  rather than shown empty. See [telemetry and observers](../concepts/telemetry.md).
- **Structured output** sends a JSON Schema and reports which mechanism the core selected
  and how many repair rounds it took. See
  [structured output](../concepts/structured-output.md).
- **Routing and fallback** are reproducible without a real outage through four offline
  fake models (`reliable`, `flaky`, `slow`, `tools`). See
  [routing and rate limits](../concepts/routing.md) and
  [add a fallback chain](fallback.md).
- **The target inspector** runs `resolve()`, verify, probe, and a paired warm/cold
  benchmark against the selected target, with price tags on the buttons that spend real
  tokens. See [proving a target works](../concepts/capabilities.md#proving-a-target-works).
- **The tool loop** hands two `@tool` functions to `Client.run_tools()` and lists the
  functions that executed. See [run the tool loop](tool-loop.md).
- **Local inference** (Tools → Local Inference…) turns hardware detection, the model
  catalog, benchmarking, and runtime installs into one dialog. See
  [the local subsystem](../concepts/local.md) and
  [the model catalog](../concepts/catalog.md).

Every major surface carries a `</>` chip that opens the SDK story behind it: the public
calls involved, a copyable plain-Python snippet, and where in the demo source it is
wired. A test resolves every named symbol against the real package, so the help cannot
drift from the API.

## Tests

The demo is covered by
[`tests/demo_app/`](https://github.com/anthturner/AnyInfer/blob/main/tests/demo_app),
which runs headless (`QT_QPA_PLATFORM=offscreen`) and drives real generations
(streaming, retry, fallback, structured output) through the offline provider:

```bash
pytest tests/demo_app             # or the full suite: python workspace.py check --only=test
```

!!! tip "Key Takeaways"
    - The demo runs offline against fake providers, with no credentials and no network.
    - Copy the threading pattern in `anyinfer_demo/engine.py`: AnyInfer calls on worker
      threads, results back to the GUI thread as Qt signals, no widget touching the SDK.
    - The demo contains no retry, fallback, validation, or timing logic of its own;
      those belong to the library.
    - Its tests run headless and drive real generations through the offline provider.

## See Also

<div class="anyinfer-see-also" markdown>

- [Integrate AnyInfer](README.md)
- [Stream to a terminal](streaming.md): the same event stream, without Qt.
- [Observe requests](observability.md)
- [Add a fallback chain](fallback.md)

</div>
