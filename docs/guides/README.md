# Integrate AnyInfer

The Python SDK, CLI, and sidecar share the Python engine and
[configuration file](../reference/configuration.md); only the process boundary changes.
The native .NET 8 C# SDK is a separate implementation, packaged locally as the
`0.1.0-proof` prerelease. Python remains the supported published SDK. C# has no runtime
Python dependency, is not published to NuGet, and does not claim full parity. See the
[foundation](../concepts/foundation.md) for the capability map.
Not every application needs this layer at all; if a provider-switching client, an
organization gateway, or a dedicated local server already solves your whole problem,
[why and when to use AnyInfer](../why-anyinfer.md) names the better-shaped tool.

The [Python quickstart](quickstart.md) is the shortest path from Python installation to a result.
For .NET, the [C# installation](csharp-installation.md) and [C# quickstart](csharp-quickstart.md)
pages are the equivalent path through the native prerelease.

## Choose a Path

**Embed the [Python SDK](python-sdk.md)** when you are writing Python and want typed
results, the event stream, and in-process telemetry. The cost: AnyInfer is in your
dependency tree and your process.

**Embed the native [C# SDK](csharp-sdk.md)** when you are writing .NET 8 and want its async core or
synchronous facade over typed events. Its bounded prerelease supports configured generation and
retrieval; it does not manage a local runtime. Follow the [application
setup](csharp-sdk.md#use-in-a-net-application), [reference](../reference/csharp-sdk.md), or
[migration map](python-to-csharp.md). This is native .NET code, not a client for the Python sidecar.

**Run the [OpenAI-compatible sidecar](../serve/README.md)** when an application in any
language needs the Python runtime over HTTP, when one process should hold provider credentials
for several clients, or when existing OpenAI-speaking tools should use your configured hybrid
route:

```bash
pip install "anyinfer[serve]"
anyinfer serve --config anyinfer.json
```

The cost: an HTTP hop, and the OpenAI wire format cannot carry AnyInfer-native
observability (timing marks and attempt records have no chunk representation, though
usage and finish reasons survive).

**Use [`anyinfer run`](cli.md)** when a person or a shell script needs one answer with
no server left running. The cost: process startup per call and no state between calls;
it declares tools but never executes them (that is the [tool loop](tool-loop.md)).

| | Python SDK | Native C# SDK (prerelease) | Python sidecar | CLI `run` |
|---|---|---|---|---|
| Language | Python | .NET 8 | Any | Any (a shell) |
| Typed results | Yes | Generation and retrieval results | OpenAI JSON | Text or JSON |
| Event stream | Full | Native typed events | Text and tool-call deltas | Text to stdout |
| TTFT / attempt trail | Yes | Timing and attempt records | Not on the wire | `--stats` / `--json` (timing and usage; no attempt trail) |
| Configured generation / retrieval | Yes | Bounded subset | Via the Python engine | Generation only |
| Local runtime management | Yes | No | Yes | Yes |
| Credentials | In-process | In-process | Held by the server | Read per call |
| Deployment | A library | A library (project reference or local package) | A process | A command |

The paths compose: `anyinfer.serve.create_app(async_client, auth_token=token)` returns
a plain ASGI app, mountable inside an existing Starlette or FastAPI application, so one
process can embed the SDK and expose the frontend.

In order to evaluate everything offline first, the [reference application](demo-app.md)
runs against in-process fakes with no credentials.

## Tasks {#python-tasks}

The first four guides give Python and native C# recipes side by side. The rest are Python
guides, with a note on the native C# equivalent where one exists.

- [Stream typed events](streaming.md)
- [Enforce a JSON schema](structured-output.md)
- [Add a fallback chain](fallback.md)
- [Run the tool loop](tool-loop.md)
- [Fit a corpus to a budget](fitting-context.md)
- [Test your application offline](testing-your-app.md)
- [Compare targets without spending](comparing-targets.md)
- [Add your own provider](custom-providers.md)
- [Embed, store, and query a small corpus](vector-store.md)

## Native C# SDK (Prerelease) {#c-sdk-development}

Start with [installation](csharp-installation.md), the [quickstart](csharp-quickstart.md),
and the [C# reference](../reference/csharp-sdk.md). The [foundation](../concepts/foundation.md)
keeps the capability map and current exclusions together.

- [Install the C# SDK](csharp-installation.md) and make a first call with the
  [C# quickstart](csharp-quickstart.md)
- [Generate text](csharp-sdk.md#generate-text) with the async core or
  [sync facade](csharp-sdk.md#use-the-synchronous-facade)
- [Stream typed events](streaming.md), [validate structured output](structured-output.md), and
  [route fallback](fallback.md) with the native recipes in each guide
- [Run registered .NET tool handlers](tool-loop.md#c-sdk-proof)
- [Embed and rerank text](csharp-sdk.md#embed-and-rerank-text)
- [Move from Python to C#](python-to-csharp.md)

## Operations

- [Run a model locally](local-inference.md) (Python)
- [Keep the sidecar running across reboots](../serve/running-as-a-service.md) (Python sidecar)
- [Observe requests](observability.md) in either SDK and
  [bridge to OpenTelemetry](observability.md#opentelemetry) (Python)
- [Credentials and redaction](../concepts/credentials.md)

## Confidentiality

- [Confidentiality tiers](confidentiality-tiers.md): protecting prompt IP shipped to
  customer machines, including the SOC 2 control mapping.

## Coding Agents

- [Coding agents](coding-agents.md): `anyinfer agents-md`, `llms.txt`, and the
  [integration procedure](../agents/INTEGRATION.md) a skill can execute.
