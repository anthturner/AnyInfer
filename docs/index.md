---
# No `title:` here on purpose. The theme renders a front-matter title as
# "<title> - AnyInfer", which on the site's own homepage reads "AnyInfer - AnyInfer" --
# in the browser tab and in every link unfurl (overrides/main.html).
template: home.html
hide:
  - navigation
  - toc
---

# AnyInfer { .anyinfer-visually-hidden }

<div class="anyinfer-code-teaser" markdown>

=== "Sync"

    ```python
    import anyinfer as ai

    client = ai.Client([ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")])
    result = client.generate(prompt, target="anthropic:claude-sonnet-4-5")
    print(result.text)
    ```

=== "Async"

    ```python
    import anyinfer as ai

    async with ai.AsyncClient(
        [ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")]
    ) as client:
        result = await client.generate(prompt, target="anthropic:claude-sonnet-4-5")
        print(result.text)
    ```

</div>

## Install

```bash
pip install anyinfer
```

The core depends on only `httpx2` and `jsonschema`. Provider SDKs, the sidecar, and the
demo app are optional extras. Local inference is part of the core. See
[installation and extras](guides/installation.md).

## What AnyInfer gives you

Applications that talk to more than one model provider accumulate the same layer every
time: per-provider request shaping, SSE parsing, retry logic, token accounting, and a
tangle of `if engine == ...` branches that leaks into config screens and error handling.
AnyInfer is that layer, extracted and made rigorous:

- **One primitive.** A `GenerationRequest` becomes a typed event stream. Non-streaming is
  the drained stream. It is *not* an OpenAI-API clone — the OpenAI dialect is one edge
  format among several.
- **Adapters only translate.** Retry, fallback, health gating, schema validation, repair,
  TTFT measurement, usage normalization, telemetry, and redaction live in the core, once.
- **Structured output is a contract.** A request carrying a schema always returns a
  client-side-validated result, using the strongest mechanism the provider offers
  (grammar → json_schema → json_mode → prompt), with an opt-in bounded repair loop.
- **Embeddings and reranking are inference primitives, not provider options.**
  `client.embed()`/`client.rerank()` are typed, routed, batched, and cost-tracked exactly
  like generation, with a fallback safety rule generation does not need: a target that
  cannot be proven to share the primary target's vector space is refused before dispatch.
- **Context engineering is connected to dispatch.** Preflight budgets, cost ranges,
  deterministic reduction, and hierarchical distillation all use the target's actual
  capability data and report uncertainty or omission instead of hiding it.
- **Capabilities carry provenance.** Every context window, price, and feature flag records
  whether it was catalogued, discovered, probed, or defaulted. Nothing is guessed silently.
- **Local inference is first-class.** Hardware detection, backend selection, llama-server
  supervision and tuning, verified GGUF downloads, and hardware→tier recommendation.

### One engine, four kinds of target

| Environment | Examples | What AnyInfer owns |
|---|---|---|
| Hosted provider | OpenAI, Anthropic, Gemini, Bedrock | Native protocol translation and capability discovery |
| Router or hub | OpenRouter, compatible gateways | Targeting, normalized events, and shared routing policy |
| Existing local service | Ollama, LM Studio, vLLM | Native or compatible client behavior; the service keeps process ownership |
| Managed local runtime | `llama.cpp` | Runtime and model acquisition, hardware fit, tuning, supervision, and loopback lifecycle |

**→ [See the compatibility inventory](providers/all.md)** — dedicated protocol adapters
and declarative presets, from frontier APIs to local engines.

See the [provider guides](providers/README.md) and the
[conformance matrix](reference/conformance-matrix.md) for exactly what each supports.

Embeddings and reranking are live today on OpenAI, Azure AI Foundry, Google Vertex AI,
AWS Bedrock, Cohere, Voyage AI, Jina AI, TEI, Ollama, LM Studio, and four
OpenAI-compatible presets — see [embeddings and reranking](concepts/embeddings.md) and
the [semantic-search example](examples/semantic-search.md).

## Next steps

<div class="grid cards" markdown>

- **Deciding whether you need this layer?**

    Start with [when to use AnyInfer](guides/when-to-use.md). It names the cases where a
    provider client, organization gateway, or dedicated local server is the better tool.

- **Integrating into an app?**

    The [Python SDK guide](guides/python-sdk.md) covers lifecycle, generation, streaming,
    and errors. The [Quickstart](guides/quickstart.md) is the five-minute route.

- **Want existing OpenAI clients to use the same route?**

    Run the [sidecar](serve/README.md) — an OpenAI-compatible loopback service, available
    as a Python extra or a standalone download.
    Anything that can point at an OpenAI base URL can use the providers, routes, and local
    models you configured.

- **Working from a shell?**

    [`anyinfer run`](guides/cli.md) sends one prompt through the same routing and
    structured-output path and streams the answer to stdout, then exits — no server to
    keep running, no Python to write.

- **Just want to see it?**

    The [pack-in demo app](guides/demo-app.md) runs fully offline against in-process
    fakes — streaming, retry and fallback, structured output, and live telemetry, no
    credentials required. Grab a standalone build from [Downloads](downloads.md).

- **Reading code first?**

    Start with the [examples](examples/README.md) — small, complete programs that run
    verbatim in CI — then the [SDK reference](reference/api/README.md).

- **Configuring more than one path?**

    Use one [shared configuration file](reference/configuration.md) for the Python SDK,
    command-line tool, and sidecar.

</div>

Pre-1.0 and under active development. Python 3.11+; Windows, macOS, and Linux are all
first-class. MIT licensed. Sources, design documents, and the issue tracker live at
[github.com/anthturner/AnyInfer](https://github.com/anthturner/AnyInfer).
