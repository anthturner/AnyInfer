# Integrate AnyInfer

Three supported production paths share the same core behavior and
[configuration file](../reference/configuration.md); only the process boundary changes.
Not every application needs this layer at all — if a provider-switching client, an
organization gateway, or a dedicated local server already solves your whole problem,
[why and when to use AnyInfer](../why-anyinfer.md) names the better-shaped tool.

The [quickstart](quickstart.md) is the shortest path from installation to a result.

## Choose a path

**Embed the [Python SDK](python-sdk.md)** when you are writing Python and want typed
results, the event stream, and in-process telemetry. The cost: AnyInfer is in your
dependency tree and your process.

**Run the [OpenAI-compatible sidecar](../serve/README.md)** when your application is not
Python, when one process should hold provider credentials for several clients, or when
existing OpenAI-speaking tools should use your configured hybrid route:

```bash
pip install "anyinfer[serve]"
anyinfer serve --config anyinfer.json
```

The cost: an HTTP hop, and the OpenAI wire format cannot carry AnyInfer-native
observability — timing marks and attempt records have no chunk representation, though
usage and finish reasons survive.

**Use [`anyinfer run`](cli.md)** when a person or a shell script needs one answer with
no server left running. The cost: process startup per call and no state between calls;
it declares tools but never executes them (that is the [tool loop](tool-loop.md)).

| | Python SDK | Sidecar | CLI `run` |
|---|---|---|---|
| Language | Python | Any | Any (a shell) |
| Typed results | Yes | OpenAI JSON | Text or JSON |
| Event stream | Full | Text and tool-call deltas | Text to stdout |
| TTFT / attempt trail | Yes | Not on the wire | `--stats` / `--json` (timing and usage; no attempt trail) |
| Local models | Yes | Yes | Yes |
| Credentials | In-process | Held by the server | Read per call |
| Deployment | A library | A process | A command |

The paths compose: `anyinfer.serve.create_app(async_client, auth_token=token)` returns
a plain ASGI app, mountable inside an existing Starlette or FastAPI application, so one
process can embed the SDK and expose the frontend.

To evaluate everything offline first, the [reference application](demo-app.md) runs
against in-process fakes with no credentials.

## Python tasks

- [Stream typed events](streaming.md)
- [Enforce a JSON schema](structured-output.md)
- [Add a fallback chain](fallback.md)
- [Run the tool loop](tool-loop.md)
- [Fit a corpus to a budget](fitting-context.md)
- [Test your application offline](testing-your-app.md)
- [Compare targets without spending](comparing-targets.md)
- [Add your own provider](custom-providers.md)
- [Embed, store, and query a small corpus](vector-store.md)

## Operations

- [Run a model locally](local-inference.md)
- [Keep the sidecar running across reboots](../serve/running-as-a-service.md)
- [Observe requests and bridge to OpenTelemetry](observability.md)
- [Credentials and redaction](../concepts/credentials.md)

## Confidentiality

- [Confidentiality tiers](confidentiality-tiers.md): protecting prompt IP shipped to
  customer machines, including the SOC 2 control mapping.

## Coding agents

- [Coding agents](coding-agents.md): `anyinfer agents-md`, `llms.txt`, and the
  [integration procedure](../agents/INTEGRATION.md) a skill can execute.
