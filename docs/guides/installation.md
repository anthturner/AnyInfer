# Installation and extras

```bash
pip install anyinfer
```

The core depends on `httpx2` and `jsonschema` and nothing else. That constraint is a
security argument as much as an aesthetic one: a small mandatory dependency surface is a
small supply-chain attack surface.

## Extras

| Extra | Adds | Needed for |
|---|---|---|
| `copilot` | `github-copilot-sdk` | The `copilot` provider |
| `azure` | `azure-identity` | Entra auth for `azure-foundry`, and `m365-copilot` |
| `vertex` | `cryptography` | Signing a Vertex service-account assertion |
| `attest` | `cryptography` | Tier 4 model-manifest signature verification (`anyinfer.local.provenance`) |
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

## Optional add-on packages

Some features ship as separate, independently-versioned distributions rather than as
`anyinfer` extras — never imported by core, never a dependency of it:

| Package | Adds | Needed for |
|---|---|---|
| `anyinfer-confidential` | `SealedTemplate`, `TemplateVault`, the `AnyInfer Relay` | [Confidentiality tiers](confidentiality-tiers.md) 1-2 |
| `anyinfer-shared` | `ConfidentialityReport` | Composing confidentiality facts from both `anyinfer-confidential` and `anyinfer` core in one type |
| `anyinfer-store` | `VectorStore`, `query_and_rerank` | Small-scale [embedded vector storage](vector-store.md) over `embed()`/`rerank()` results |

```bash
pip install -e src/anyinfer-confidential   # from a repository checkout, until a first
pip install -e src/anyinfer-shared         # PyPI release ships
pip install -e src/anyinfer-store
```

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
