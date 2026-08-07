# Providers

This section is the compatibility inventory: dedicated adapters for protocols that require
real translation, plus declarative presets for OpenAI-compatible services and engines.
Breadth is useful, but it is not AnyInfer's product boundary; start with
[when to use AnyInfer](../guides/when-to-use.md) if you are choosing an integration layer.

The generated [complete inventory](all.md) records the current counts and target prefixes.

<div class="anyinfer-card-grid" markdown>

- :material-cloud-outline: **[OpenAI](openai.md)** `openai:`
  <br>Responses API, reasoning-token accounting.
  <br>`Hosted`

- :material-cloud-outline: **[Anthropic](anthropic.md)** `anthropic:` / `claude:`
  <br>Messages API, extended thinking deltas.
  <br>`Hosted`

- :material-google: **[Google Gemini](gemini.md)** `gemini:` / `google:`
  <br>Native generateContent, thinking levels, discovered windows.
  <br>`Hosted`

- :material-atom-variant: **[DeepSeek](deepseek.md)** `deepseek:`
  <br>Separate reasoning channel, split cache accounting.
  <br>`Hosted`

- :material-alpha-x-box-outline: **[xAI (Grok)](xai.md)** `xai:` / `grok:`
  <br>Provider-reported cost, discovered pricing.
  <br>`Hosted`

- :material-google-cloud: **[Google Vertex AI](vertex.md)** `vertex:`
  <br>Gemini with GCP auth; project-scoped addressing.
  <br>`Enterprise`

- :material-aws: **[AWS Bedrock](bedrock.md)** `bedrock:`
  <br>Converse API, SigV4 or API key, binary streaming.
  <br>`Enterprise`

- :material-hexagon-multiple: **[Cohere](cohere.md)** `cohere:`
  <br>Native v2 chat, grounded generation, thinking channel.
  <br>`Hosted`

- :material-laptop: **[LM Studio](lm-studio.md)** `lm-studio:`
  <br>Native discovery: context, quantization, residency.
  <br>`Local`

- :material-desktop-tower: **[Ollama](ollama.md)** `ollama:`
  <br>Native API, grammar schemas, phase timings.
  <br>`Local`

- :material-desktop-tower: **[llama.cpp](llama-cpp.md)** `llama-cpp:`
  <br>Supervised llama-server, loopback only.
  <br>`Local`

- :material-swap-horizontal: **[OpenAI-compatible](openai-compat.md)** `openai-compat:`
  <br>Any `/chat/completions` endpoint by URL.
  <br>`Local` `Hosted`

- :material-format-list-group: **[Hosted & local presets](presets.md)** `groq:` `together:` `mistral:` `vllm:` …
  <br>Eighty-six OpenAI-compatible services and engines, preconfigured.
  <br>`Local` `Hosted`

- :material-router-network: **[OpenRouter](openrouter.md)** `openrouter:`
  <br>Rich discovered pricing and context data.
  <br>`Hosted`

- :material-cloud-search-outline: **[Nebius Token Factory](nebius.md)** `nebius:`
  <br>Live pricing, context, quantization, and reasoning channels.
  <br>`Hosted`

- :material-domain: **[Azure AI Foundry](azure-foundry.md)** `azure-foundry:` / `azure:`
  <br>`max_completion_tokens`, API key or Entra auth.
  <br>`Enterprise`

- :material-microsoft: **[GitHub Copilot](copilot.md)** `copilot:`
  <br>`auto` sentinel, CLI-delegated auth.
  <br>`Hosted`

- :material-microsoft-office: **[Microsoft 365 Copilot](m365-copilot.md)** `m365-copilot:` / `m365:`
  <br>Interactive auth only, the most constrained provider.
  <br>`Enterprise`

</div>

See the [conformance matrix](../reference/conformance-matrix.md) for exactly which
behaviors each one supports, generated from test results rather than asserted, and the
table below as an accessible alternative to the cards.

| Provider | Target prefix | Extra needed | Notes |
|---|---|---|---|
| [openai](openai.md) | `openai:` | — | Responses API |
| [anthropic](anthropic.md) | `anthropic:` / `claude:` | — | Messages API, thinking deltas |
| [gemini](gemini.md) | `gemini:` / `google:` | — | Native generateContent, thinking levels |
| [deepseek](deepseek.md) | `deepseek:` | — | reasoning_content channel, cache split |
| [xai](xai.md) | `xai:` / `grok:` | — | Reported cost, discovered pricing |
| [vertex](vertex.md) | `vertex:` | `[vertex]` for service-account signing | Gemini via GCP OAuth; project-scoped |
| [bedrock](bedrock.md) | `bedrock:` | — | Converse API; SigV4 or Bedrock API key |
| [cohere](cohere.md) | `cohere:` | — | Native v2 chat, uppercase enums |
| [lm-studio](lm-studio.md) | `lm-studio:` | — | Native discovery and residency |
| [ollama](ollama.md) | `ollama:` | — | Native API, grammar schemas, phase timings |
| [llama-cpp](llama-cpp.md) | `llama-cpp:` | — | Supervised llama-server, loopback only |
| [openai-compat](openai-compat.md) | `openai-compat:` | — | Any `/chat/completions` endpoint |
| [openrouter](openrouter.md) | `openrouter:` | — | Rich discovered pricing and context data |
| [nebius](nebius.md) | `nebius:` | — | Live pricing, context, quantization, reasoning |
| [azure-foundry](azure-foundry.md) | `azure-foundry:` / `azure:` | `[azure]` for Entra | `max_completion_tokens` |
| [copilot](copilot.md) | `copilot:` | `[copilot]` | `auto` sentinel, CLI-delegated auth |
| [m365-copilot](m365-copilot.md) | `m365-copilot:` / `m365:` | `[azure]` | Interactive auth only |

## What is the same everywhere

Because the core owns orchestration, these behave identically no matter which provider
served a request:

- retries, fallback, and health gating;
- structured-output validation and repair;
- TTFT, duration, and throughput measurement;
- usage normalization and cost computation;
- telemetry events and secret redaction;
- the event stream and its ordering guarantees.

## What differs, and how you find out

Real differences are surfaced, never hidden:

- **Capability flags** say what a model supports, with
  [provenance](../concepts/capabilities.md).
- **`structured_mechanism`** on each result says how a schema was actually enforced.
- **`ParameterDropped` events** fire when a provider accepts a parameter and discards it.
- **Provider pages** document the rest.

## The escape hatch

Anything a provider supports that AnyInfer does not model is reachable verbatim:

```python
client.generate(
    prompt,
    target="ollama:qwen3:8b",
    provider_options={"ollama": {"keep_alive": "10m", "num_gpu": 99}},
)
```

Options are namespaced by provider id and passed straight through to the matching adapter —
the core never inspects them. You should never have to fork the library to reach a
provider-specific feature.

## Adding your own

Third-party adapters register through the `anyinfer.providers` entry-point group and prove
themselves with the same conformance suite the built-ins run. See
[writing an adapter](../contributing/writing-an-adapter.md).
