# Providers

This section is the compatibility inventory: dedicated adapters for protocols that require
real translation, plus declarative presets for OpenAI-compatible services and engines.
Breadth is useful, but it is not AnyInfer's product boundary; start with
[why and when to use AnyInfer](../why-anyinfer.md) if you are choosing an integration layer.

The generated [complete inventory](all.md) is the full accessible rendering — all 106
providers (20 dedicated adapters, 86 presets), each with its target prefixes, key
variable or default endpoint, and notes.

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

- :material-vector-triangle: **[Voyage AI](retrieval.md)** `voyage:`
  <br>Specialist embeddings and reranking; query/document intents.
  <br>`Hosted`

- :material-vector-triangle: **[Jina AI](retrieval.md)** `jina:`
  <br>Specialist embeddings and reranking; full task vocabulary.
  <br>`Hosted`

- :material-vector-triangle: **[Text Embeddings Inference](tei.md)** `tei:`
  <br>Local embeddings and reranking; retrieval-only, one model per server.
  <br>`Local`

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
behaviors each one supports, generated from test results rather than asserted.

## What is the same everywhere

Since the core owns orchestration, [routing and retries](../concepts/routing.md),
[structured-output validation](../concepts/structured-output.md),
[cost accounting](../concepts/cost.md), timing, [telemetry](../concepts/telemetry.md),
and the [event stream](../concepts/events.md) behave identically no matter which
provider served a request. The [concepts section](../concepts/README.md) documents each.

## What differs, and how you find out

Real differences are surfaced, never hidden:

- **Capability flags** say what a model supports, with
  [provenance](../concepts/capabilities.md).
- **`structured_mechanism`** on each result says how a schema was actually enforced.
- **`ParameterDropped` events** fire when a provider accepts a parameter and discards it.
- **Provider pages** document the rest.

## Reaching provider-specific parameters

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
