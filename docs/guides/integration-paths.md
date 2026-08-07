# Choosing an integration path

Three supported production paths. They share the same core behavior and
[configuration format](../reference/configuration.md); only the process boundary changes.

## You're building…

<div class="anyinfer-card-grid" markdown>

- **A Python app**

    Embed the SDK directly. Typed results, the full event stream, and in-process
    telemetry. See [the Python SDK guide](python-sdk.md).

- **An existing OpenAI-compatible tool**

    Run the [sidecar](../serve/README.md). Anything that already speaks the OpenAI API can
    use the providers, routes, and local models in your shared configuration.

- **A shell script or a one-off question**

    Use [`anyinfer run`](cli.md). One prompt through the same routing and
    structured-output path, streamed to stdout, then exit — no server, no script.

- **A desktop demo**

    Run the [pack-in demo app](demo-app.md) — no credentials, no network, streaming and
    fallback and structured output all visible in a GUI.

</div>

## 1. Embed the SDK

```python
import anyinfer as ai
client = ai.Client([ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")])
```

**Choose this when** you are writing Python, want typed results, need the event stream for
timing or progress, or want in-process telemetry.

**You get:** typed `Generation` results, the full event stream, observers, the local
subsystem, the tool loop, capability metadata with provenance.

**Costs:** AnyInfer is in your dependency tree and your process.

## 2. Run the sidecar

```bash
pip install "anyinfer[serve]"
anyinfer serve --config anyinfer.json
```

Then point any OpenAI-compatible client at it:

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="unused")
client.chat.completions.create(model="ollama:qwen3:8b", messages=[...])
```

**Choose this when** your application is not Python, when you want one process to hold
provider credentials for several clients, or when you want existing OpenAI-speaking tools
(IDE plugins, third-party apps) to use one configured hybrid route.

**You get:** configured providers, aliases, routes, and supervised local models through an
interface your tools already speak.

**Costs:** an HTTP hop; and the OpenAI wire format cannot carry AnyInfer-native
observability — timing marks and attempt records have no chunk representation, so you lose
that detail (usage and finish reasons survive).

Install the `[serve]` extra when you already manage Python, or use a self-contained build
from [Downloads](../downloads.md). Both read the same `anyinfer.json` file.

## 3. Run one prompt from the shell

```bash
anyinfer run "Explain TCP slow start." --config anyinfer.json --target ollama:qwen3:8b
cat notes.txt | anyinfer run "Summarize this:" --config anyinfer.json
```

**Choose this when** you want an answer in a terminal or a shell script, without writing
Python or leaving a server running. It reads the same config file as the SDK and sidecar.

**You get:** streaming to stdout, routing and fallback, schema-validated output, tool
declarations, and `--json` for machine-readable results — the same core path the SDK uses.

**Costs:** process startup per call, and no persistent state between calls. It declares
tools but never executes them; an automated call-and-respond cycle needs the
[tool loop](tool-loop.md) in a script.

Full flag reference: [run a prompt from the shell](cli.md).

## Side by side

| | Python SDK | Sidecar | CLI `run` |
|---|---|---|---|
| Language | Python | Any | Any (a shell) |
| Typed results | Yes | OpenAI JSON | Text or JSON |
| Event stream | Full | Text and tool-call deltas | Text to stdout |
| TTFT / attempt trail | Yes | Not on the wire | `--stats` / `--json` (timing and usage; no attempt trail) |
| Local models | Yes | Yes | Yes |
| Credentials | In-process | Held by the server | Read per call |
| Deployment | A library | A process | A command |

## They compose

Nothing stops you embedding the SDK *and* exposing the frontend from the same process:

```python
from anyinfer.serve import create_app
app = create_app(async_client, auth_token=token)
```

`create_app` returns a plain ASGI app, mountable inside an existing Starlette or FastAPI
application.

See the [sidecar documentation](../serve/README.md).
