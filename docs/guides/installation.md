# Installation and extras

```bash
pip install anyinfer
```

The core depends on **`httpx2` and `jsonschema`** and nothing else. That is a deliberate
constraint, and it is a security argument as much as an aesthetic one: a small
mandatory dependency surface is a small supply-chain attack surface.

## Extras

| Extra | Adds | Needed for |
|---|---|---|
| `copilot` | `github-copilot-sdk` | The `copilot` provider |
| `azure` | `azure-identity` | Entra auth for `azure-foundry`, and `m365-copilot` |
| `vertex` | `cryptography` | Signing a Vertex service-account assertion |
| `keyring` | `keyring` | `credential://` references |
| `otel` | `opentelemetry-api` | The OpenTelemetry bridge |
| `serve` | `starlette`, `uvicorn` | The OpenAI-compatible sidecar |
| `demo` | `PySide6`, `markdown` | The [pack-in demo app](demo-app.md) (`anyinfer-demo`) |
| `all` | everything above | |

```bash
pip install "anyinfer[serve,otel]"
```

Optional packages are imported only when their feature is used. A missing package produces
an actionable `ConfigError` or `CredentialError` with the install command, never a raw
`ImportError` traceback.

## Which providers need nothing extra

`openai`, `anthropic`, `openai-compat`, `openrouter`, `ollama`, and `llama-cpp` are pure
`httpx2` and work with a bare install. The local subsystem, including hardware detection and
the llama-server supervisor, is core.

## Requirements

- **Python 3.11+**
- **Windows, macOS, and Linux** are all first-class and all tested in CI.

`llama-server` runtimes are installed explicitly with `anyinfer runtime install`; catalog
models are acquired on demand or with `anyinfer models add`. Neither is bundled in the
wheel, and both paths verify the downloaded artifacts.

For non-Python deployments, release builds of the demo and sidecar are listed on
the [Downloads](../downloads.md) page. The 0.1 beta native bundles are checksummed but not
code-signed; verify `SHA256SUMS` from the GitHub Release before running them.

## Verify the install

```bash
anyinfer providers   # every registered provider and what it needs
anyinfer doctor      # detected hardware and the recommended local tier
```
