# Integrate AnyInfer

Choose the boundary that fits your application. All three production paths use the same
core behavior and [shared configuration file](../reference/configuration.md).

Not every application needs this layer. Read [when to use AnyInfer](when-to-use.md) first
if a provider-switching client, organization gateway, or dedicated local server may already
solve your whole problem.

| Path | Use it when | Start here |
|---|---|---|
| Python SDK | AnyInfer runs inside your Python process and you want the full typed API. | [Integrate the Python SDK](python-sdk.md) |
| Command-line tool | A person or shell script needs one result and no long-running service. | [Run a prompt from the shell](cli.md) |
| OpenAI-compatible sidecar | A non-Python application or existing OpenAI client needs AnyInfer over HTTP. | [Run the sidecar](../serve/README.md) |

If you are still deciding, read [choosing an integration path](integration-paths.md). The
[quickstart](quickstart.md) is the shortest SDK path from installation to a result.

## Python tasks

- [Stream typed events](streaming.md)
- [Enforce a JSON schema](structured-output.md)
- [Add a fallback chain](fallback.md)
- [Run the tool loop](tool-loop.md)
- [Fit a corpus to a budget](fitting-context.md)
- [Reduce an explicit corpus through the sidecar](sidecar-corpus-context.md)

## Operations

- [Choose and download a local model](local-models.md)
- [Run a local model end to end](local-inference.md)
- [Keep the sidecar running across reboots](../serve/running-as-a-service.md)
- [Observe requests and bridge to OpenTelemetry](observability.md)
- [Compare request portability across targets](comparing-targets.md)
- [Store credentials in the OS keyring](credentials.md)

## Letting a coding agent write the integration

- [Coding agents](coding-agents.md): `anyinfer agents-md`, `llms.txt`, and the
  integration procedure a skill can execute.

## Evaluate before integrating

The [demo app](demo-app.md) is a reference integration that runs offline against deterministic
fake providers. It demonstrates streaming, fallback, structured output, and telemetry without
requiring an account or credential.

These pages are for integrators. If you are changing AnyInfer itself, start with the
[contributor guide](../contributing/README.md); contributor architecture and release material
is kept in its own section so it does not interrupt the integration path.
