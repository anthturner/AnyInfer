<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/anthturner/AnyInfer/main/docs/assets/anyinfer-horizontal-dark.svg">
    <img src="https://raw.githubusercontent.com/anthturner/AnyInfer/main/docs/assets/anyinfer-horizontal-light.svg" alt="AnyInfer" width="480" />
  </picture>
</p>

<p align="center">
  <a href="https://github.com/anthturner/AnyInfer/actions/workflows/ci.yml"><img src="https://github.com/anthturner/AnyInfer/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <a href="https://anyinfer.dev/"><img src="https://img.shields.io/badge/docs-anyinfer.dev-2C7A6F" alt="Documentation" /></a>
  <a href="https://github.com/anthturner/AnyInfer/releases/latest"><img src="https://img.shields.io/github/v/release/anthturner/AnyInfer?include_prereleases&label=release&color=E8963C" alt="Latest release" /></a>
  <a href="https://github.com/anthturner/AnyInfer/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-2C7A6F" alt="MIT license" /></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-0B3B3C" alt="Python 3.11+" />
</p>

**An application-owned hybrid inference runtime for Python.** Send one typed request to
hosted providers, routing hubs, existing local servers, or a supervised `llama.cpp`
process. The same core owns routing, structured output, context budgeting and reduction,
telemetry, and shared configuration.

```python
import anyinfer as ai

client = ai.Client(
    [
        ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY"),
        ai.ProviderSettings.of("ollama"),
    ]
)
result = client.generate(
    "Summarize this release note:\n" + text, target="anthropic:claude-sonnet-4-5"
)

print(result.text)
print(result.usage.output_tokens, "tokens in", result.timing.total_ms, "ms")
```

Point the same call at a local model by changing one string:

```python
result = client.generate(prompt, target="ollama:qwen3:8b")  # "medium" is a catalog alias
```

Embeddings and reranking are the same client, the same routing, and the same batching —
never a bolted-on provider option:

```python
vectors = client.embed(["first passage", "second passage"], target="ollama:nomic-embed-text")
ranked = client.rerank("which passage answers the question", passages, target="cohere:rerank-v3.5")
```

---

## Why this exists

There are already good libraries for switching between cloud providers, good gateways for
centralizing model traffic, and good local-model servers. If one of those is your whole
problem, you may not need AnyInfer. See
[when AnyInfer is the right layer](https://anyinfer.dev/guides/when-to-use/).

AnyInfer is for applications that need those environments to behave as one runtime. It
keeps provider translation, local process ownership, context preparation, routing, and
result validation inside one testable boundary:

- **One primitive.** A `GenerationRequest` becomes a typed event stream. Non-streaming is
  the drained stream. It is *not* an OpenAI-API clone. The OpenAI dialect is one edge
  format among several.
- **Adapters only translate.** Retry, fallback, health gating, schema validation, repair,
  TTFT measurement, usage normalization, telemetry, and redaction live in the core, once.
- **Structured output is a contract.** A request carrying a schema always returns a
  client-side-validated result, using the strongest mechanism the provider offers
  (grammar → json_schema → json_mode → prompt), with an opt-in bounded repair loop.
- **Embeddings and reranking are inference primitives, not provider options.**
  `client.embed()`/`client.rerank()` are typed, routed, batched, and cost-tracked exactly
  like generation — with a safety rule generation does not need: a fallback that cannot
  be proven to share the primary target's vector space is refused before dispatch, not
  silently served as a wrong-but-plausible vector.
- **Context engineering is part of dispatch.** A provenance-aware budget estimates input,
  output reserve, headroom, and cost before a call. Deterministic reducers fit approved
  corpora to that budget and report exactly what they omitted; hierarchical distillation
  handles material that cannot fit at any fidelity.
- **Capabilities carry provenance.** Every context window, price, and feature flag records
  whether it was catalogued, discovered, probed, or defaulted. Nothing is guessed silently.
- **Local inference is first-class.** Hardware detection, backend selection, llama-server
  supervision and tuning, verified GGUF downloads, and hardware→tier recommendation.
- **Portability is verified behavior, not a provider count.** Contract snapshots and a
  shared conformance suite document what each adapter actually supports and surface dropped
  parameters or degraded mechanisms instead of hiding them.
- **Your integration is testable.** A scripted provider and pytest fixtures ship with the
  library, so your fallback chain, repair budget, and reduction settings have offline tests
  that run in CI with no credentials, including the failures you cannot provoke on demand:
  rate limits, truncated streams, malformed structured answers, refusals, timeouts.
- **A confidentiality story nobody else in this market ships.** Encrypted-at-rest prompt
  templates, a zero-retention orchestration relay, and a portable capability check that
  tells your application whether a box can back local inference with a real
  hardware-attested guarantee — see [confidentiality
  tiers](https://anyinfer.dev/guides/confidentiality-tiers/).
- **Slim by construction.** Mandatory dependencies are `httpx2` and `jsonschema`. Everything
  else is an extra.

## When it is the right layer

Use AnyInfer when your application needs to own a hybrid route, such as a hosted model
with a managed local fallback, or when context fit, structured results, attempt
history, and telemetry must retain the same meaning after the target changes.

Use a simpler provider client when you only need cloud API switching. Use a gateway when
you need organization-wide keys, quotas, spend controls, or an admin plane. Use Ollama,
LM Studio, or LocalAI directly when a dedicated local-model service is the product boundary.

**[Why AnyInfer →](https://anyinfer.dev/why-anyinfer/)** goes through the five capabilities
that are genuinely unusual here, with a dated comparison by category and the commands that
check each claim. The [decision guide](https://anyinfer.dev/guides/when-to-use/) argues the
other side and names the tools that are a better fit when they are.

## Install

```bash
pip install anyinfer                 # core + local lifecycle; runtimes fetched separately
pip install "anyinfer[copilot]"      # GitHub Copilot
pip install "anyinfer[azure]"        # Azure AI Foundry (Entra auth)
pip install "anyinfer[vertex]"       # Vertex service-account authentication
pip install "anyinfer[keyring]"      # credential:// references via the OS vault
pip install "anyinfer[otel]"         # OpenTelemetry bridge
pip install "anyinfer[serve]"        # the OpenAI-compatible HTTP frontend
pip install "anyinfer[demo]"         # the PySide6 pack-in demo app
pip install "anyinfer[all]"
```

Python 3.11+. Windows, macOS, and Linux are all first-class.

### Two commands to a working call

```bash
anyinfer init      # detect what is usable here, write anyinfer.json and starter.py
python starter.py  # run it
```

`init` reports only what it observed: a loopback engine that answered or a credential
variable that is actually set. It writes detected keys as `env://` references rather
than values, so the file it generates is safe to commit. It installs nothing and never
replaces a configuration you already have.

### Try it without credentials

```bash
pip install "anyinfer[demo]"
anyinfer-demo
```

The [pack-in demo app](https://anyinfer.dev/guides/demo-app/) runs offline against
in-process fakes and shows streaming, routing with retry and fallback, structured output,
and the telemetry event stream. Standalone builds for Windows, macOS, and Linux require no Python and are
attached to [every release](https://github.com/anthturner/AnyInfer/releases/latest); see the
[downloads page](https://anyinfer.dev/downloads/).

### Working on AnyInfer

```bash
python workspace.py setup    # install the project and dev extras
python workspace.py check    # every gate CI runs
python workspace.py demo     # launch the demo app
```

`python workspace.py` with no arguments lists every verb. See
[Contributing](https://anyinfer.dev/contributing/).

## Compatibility surface

Provider breadth is compatibility inventory, not the product thesis. AnyInfer ships 17
dedicated adapters plus 86 declarative OpenAI-compatible presets.
**[See the complete inventory →](https://anyinfer.dev/providers/all/)**

The dedicated adapters, each handling provider-specific protocol or discovery behavior:

| Provider | Target prefix | Notes |
|---|---|---|
| OpenAI-compatible | `openai-compat:` | Any server speaking `/chat/completions` |
| OpenAI | `openai:` | Responses API |
| Anthropic | `anthropic:` (alias `claude:`) | Messages API |
| Google Gemini | `gemini:` (alias `google:`) | Native generateContent, thinking levels |
| DeepSeek | `deepseek:` | Reasoning channel, split cache accounting |
| xAI | `xai:` (alias `grok:`) | Provider-reported cost, discovered pricing |
| Google Vertex AI | `vertex:` | Gemini with GCP OAuth/ADC auth |
| AWS Bedrock | `bedrock:` | Converse API, SigV4 or Bedrock API key |
| Cohere | `cohere:` | Native v2 chat API |
| LM Studio | `lm-studio:` | Native model discovery and residency |
| Azure AI Foundry | `azure-foundry:` | Entra or API key |
| GitHub Copilot | `copilot:` | Includes the `auto` sentinel |
| Microsoft 365 Copilot | `m365-copilot:` | Interactive auth only |
| OpenRouter | `openrouter:` | Rich discovered pricing/context metadata |
| Nebius Token Factory | `nebius:` | Live pricing, context, and quantization discovery |
| Ollama | `ollama:` | Native API, grammar-enforced schemas |
| llama.cpp | `llama-cpp:` | Supervised `llama-server`, loopback-only |
| 86 more, preconfigured | `groq:` `together:` `mistral:` `vllm:` … | [OpenAI-compatible presets](https://anyinfer.dev/providers/presets/) |

See the [complete provider list](https://anyinfer.dev/providers/all/),
the [provider guides](https://anyinfer.dev/providers/) and the
[conformance matrix](https://anyinfer.dev/reference/conformance-matrix/) for exactly what each supports.

Embeddings and/or reranking are live today on OpenAI, Azure AI Foundry, Google Vertex AI,
AWS Bedrock (Titan), Cohere, Voyage AI, Jina AI, TEI, Ollama, LM Studio, and four
OpenAI-compatible presets (Together AI, Fireworks AI, DeepInfra, Mistral) — see
[Embeddings and reranking](https://anyinfer.dev/concepts/embeddings/) and the
[semantic-search example](https://anyinfer.dev/examples/semantic-search/).

## Integration paths

| Path | Best for | Entry point |
|---|---|---|
| Python SDK | Python applications that want typed results and the full event stream | `Client` / `AsyncClient` |
| Command-line tool | Shell scripts and one-off prompts | `anyinfer run` |
| OpenAI-compatible sidecar | Non-Python applications and existing OpenAI clients | `anyinfer serve` (pip) or the standalone `anyinfer-serve` bundle |

All three use the same engine and the same versioned JSON configuration format:

```json
{
  "format_version": 1,
  "providers": [{"id": "ollama"}],
  "default_route": ["ollama:qwen3:8b"]
}
```

Load it with `ai.load_config("anyinfer.json")`, pass it to `anyinfer run --config`, or use
it unchanged with the sidecar. See [choosing an integration path](https://anyinfer.dev/guides/integration-paths/)
and [shared configuration](https://anyinfer.dev/reference/configuration/).

## Documentation

**[anyinfer.dev](https://anyinfer.dev/)** is the published
site, including the generated [SDK reference](https://anyinfer.dev/reference/api/)
and [runnable examples](https://anyinfer.dev/examples/). The same pages are
browsable in-repo from the **[documentation index](https://github.com/anthturner/AnyInfer/blob/main/docs/README.md)**.

Quick links by role:

- **Integrating the Python SDK?** → [Python SDK guide](https://anyinfer.dev/guides/python-sdk/) ·
  [Quickstart](https://anyinfer.dev/guides/quickstart/) · [SDK reference](https://anyinfer.dev/reference/api/)
- **Running the HTTP service?** → [OpenAI-compatible sidecar](https://anyinfer.dev/serve/)
- **Working from a shell?** → [Run a prompt from the shell](https://anyinfer.dev/guides/cli/)
- **Sharing provider and route settings?** → [Configuration](https://anyinfer.dev/reference/configuration/)
- **Letting a coding agent write the integration?** → [Coding agents](https://anyinfer.dev/guides/coding-agents/) ·
  [`llms.txt`](https://anyinfer.dev/llms.txt) · run `anyinfer agents-md >> AGENTS.md`
- **Contributing or writing an adapter?** →
  [Contributor guide](https://github.com/anthturner/AnyInfer/blob/main/CONTRIBUTING.md) ·
  [Provider contracts](https://github.com/anthturner/AnyInfer/blob/main/contracts/README.md)
- **Reporting a vulnerability?** → [Security policy](https://github.com/anthturner/AnyInfer/security/policy)

## Project status

Pre-1.0 and under active development: the public API is settled in shape but may still
move before 1.0. Releases are published to
[PyPI](https://pypi.org/project/anyinfer/) and
[GitHub](https://github.com/anthturner/AnyInfer/releases); the
[release strategy](https://anyinfer.dev/contributing/releasing/) has the
details. The architecture is settled and documented:

- [DESIGN.md](https://github.com/anthturner/AnyInfer/blob/main/DESIGN.md): architecture, module responsibilities, decision rationale, open questions, and risks
- [AGENTS.md](https://github.com/anthturner/AnyInfer/blob/main/AGENTS.md): canonical repository automation instructions

## License

[MIT](https://github.com/anthturner/AnyInfer/blob/main/LICENSE).
