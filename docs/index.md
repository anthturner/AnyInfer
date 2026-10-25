# AnyInfer { .anyinfer-visually-hidden }

<div class="anyinfer-code-teaser" markdown>

=== "Python sync"

    ```python
    import anyinfer as ai

    prompt = "Summarize the Apollo program in one sentence."

    client = ai.Client([ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")])
    result = client.generate(prompt, target="anthropic:claude-sonnet-4-5")
    print(result.text)
    ```

=== "Python async"

    ```python
    import anyinfer as ai

    prompt = "Summarize the Apollo program in one sentence."

    async with ai.AsyncClient(
        [ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")]
    ) as client:
        result = await client.generate(prompt, target="anthropic:claude-sonnet-4-5")
        print(result.text)
    ```

=== "C# (prerelease)"

    ```csharp
    --8<-- "examples/csharp-sdk/GenerationExample.cs"
    ```

</div>

AnyInfer provides a shared inference foundation with independent Python and C# SDK
implementations. Python is the supported published SDK; its CLI and OpenAI-compatible
sidecar use the Python engine. The native .NET 8 C# SDK is an independent prerelease,
locally packaged as `0.1.0-proof`, with no runtime Python dependency. It is not published to
NuGet and does not claim full parity. See [the foundation](concepts/foundation.md) for the capability map.

Choose the [Python quickstart](guides/quickstart.md), [Python SDK guide](guides/python-sdk.md),
or [Python reference](reference/api/README.md) for the supported SDK. For the native prerelease,
start with the [C# installation](guides/csharp-installation.md) and
[C# quickstart](guides/csharp-quickstart.md), then the [C# SDK guide](guides/csharp-sdk.md),
[C# reference](reference/csharp-sdk.md), or [Python-to-C# migration map](guides/python-to-csharp.md).
The C# SDK is distinct from calling the Python sidecar over HTTP.

## Install the Python SDK {#install}

```bash
pip install anyinfer
```

The Python core depends on only `httpx2` and `jsonschema`. Python provider SDKs, the Python
sidecar, and the demo app are optional extras. Local inference is part of the Python core. See
[installation and extras](guides/installation.md).

## What Makes This Different

The capabilities below describe the supported Python runtime. The
[C# capability map](concepts/foundation.md#c-capability-map) covers the native prerelease.

Most libraries in this space solve *provider switching*: one function, many APIs, one
response shape. AnyInfer solves the problem that starts right after: being correct about
what you sent, what you got back, what it cost, and what quietly didn't happen.

- **Your fallback chain has a real test, with no credentials and no network.** The test
  kit ships with the library (script a 503, a malformed schema response, a rate limit)
  and allows you to assert on the recovery, not on a mock of your own wrapper.
  [→ Testing your app](guides/testing-your-app.md)
- **Every number says where it came from.** A context window, a price, a feature flag is
  tagged cataloged, discovered, probed, defaulted, or overridden by you, and an unknown
  cost is `None`, never `$0.00`. [→ Capabilities and provenance](concepts/capabilities.md)
- **Structured output is a contract.** A request carrying a schema always returns a
  client-side-validated result, using the strongest mechanism the provider offers, with
  an opt-in bounded repair loop.
  [→ Structured output](concepts/structured-output.md)
- **Portability is a test result, not a claim.** `compare()` reports exactly what a
  fixed request becomes on a different target before you spend anything, and the
  [conformance matrix](reference/conformance-matrix.md) is generated from executed
  tests. [→ Comparing targets](guides/comparing-targets.md)
- **A local model is a target, not a separate product.** Point the same call at
  `llama-cpp:qwen3-8b-q4-k-m` and AnyInfer acquires, verifies, and supervises the
  weights itself: same fallback chain, event stream, and structured-output contract,
  no separate daemon. [→ Run a model locally](guides/local-inference.md)
- **Context engineering is part of dispatch.** A provenance-aware budget estimates
  input, reserve, and cost before a call; deterministic reducers fit approved corpora
  to it and report exactly what they omitted.
  [→ Context reduction](concepts/context-reduction.md)

**→ [Read the full case, with runnable proof for every claim](why-anyinfer.md).**

### One Engine, Four Kinds of Target

| Environment | Examples | What AnyInfer owns |
|---|---|---|
| Hosted provider | OpenAI, Anthropic, Gemini, Bedrock | Native protocol translation and capability discovery |
| Router or hub | OpenRouter, compatible gateways | Targeting, normalized events, and shared routing policy |
| Existing local service | Ollama, LM Studio, vLLM | Native or compatible client behavior; the service keeps process ownership |
| Managed local runtime | `llama.cpp` | Runtime and model acquisition, hardware fit, tuning, supervision, and loopback lifecycle |

**→ [See the Python compatibility inventory](providers/all.md)**: dedicated protocol adapters
and declarative presets, from frontier APIs to local engines, with
[per-provider guides](providers/README.md). Embeddings and reranking are typed, routed
operations on the same client; see
[embeddings and reranking](concepts/embeddings.md).

## Next Steps

<div class="grid cards" markdown>

- **Deciding whether you need this layer?**

    Start with [why and when to use AnyInfer](why-anyinfer.md). It names the cases where
    a provider client, organization gateway, or dedicated local server is the better
    tool.

- **Integrating into an app?**

    The [Python quickstart](guides/quickstart.md) and the
    [C# quickstart](guides/csharp-quickstart.md) are the short routes from install to a
    result; [Integrate AnyInfer](guides/README.md) chooses between the Python SDK, the
    native C# prerelease, the CLI, and the sidecar.

- **Want existing OpenAI clients to use the same route?**

    Run the [sidecar](serve/README.md), an OpenAI-compatible loopback service.
    Anything that can point at an OpenAI base URL can use the providers, routes, and
    local models you configured.

- **Just want to see it?**

    The [pack-in demo app](guides/demo-app.md) runs fully offline against in-process
    fakes (no credentials required). Grab a standalone build from
    [Downloads](downloads.md).

</div>

Pre-1.0 and under active development. The Python SDK needs Python 3.11+ and the C#
prerelease needs .NET 8; Windows, macOS, and Linux are all first-class. MIT licensed. Sources, design documents, and the issue tracker live at
[github.com/anthturner/AnyInfer](https://github.com/anthturner/AnyInfer).
