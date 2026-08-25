---
icon: material/format-list-group
---

# Hosted & Local OpenAI-Compatible Presets

One implementation, many brandings. Every provider on this page speaks the
chat-completions dialect closely enough that AnyInfer's shared
[OpenAI-compatible adapter](openai-compat.md) covers it, so each ships as a **preset**: a
first-class registered provider with the endpoint, auth spelling, quirks, and
capabilities filled in ahead of time.

```python
import anyinfer as ai

client = ai.Client(
    [
        ai.ProviderSettings.of("groq", api_key="env://GROQ_API_KEY"),
        ai.ProviderSettings.of("together", api_key="env://TOGETHER_API_KEY"),
        ai.ProviderSettings.of("vllm"),  # local engines need no key
    ]
)

result = client.generate(prompt, target="groq:llama-3.3-70b-versatile")
result = client.generate(prompt, target="together:deepseek-ai/DeepSeek-V3")
result = client.generate(prompt, target="vllm:qwen3-8b")
```

Everything the [core owns](README.md#what-is-the-same-everywhere) (routing, retries,
structured output, telemetry, cost accounting) works identically through a preset.
Provider-specific extras go through
[`provider_options`](README.md#reaching-provider-specific-parameters), passed to the
provider verbatim.

The full preset roster (86 services and engines, with each one's target prefix,
conventional key variable or default endpoint, and one-line notes) is generated from the
registry in [the complete inventory](all.md), so it cannot drift from what the library
ships.

## What a Preset Does and Does Not Change

A preset only adjusts declarative knobs on the shared adapter:

- the endpoint and how the credential is spelled (`Authorization: Bearer` vs `x-api-key`);
- the output-token parameter name (`max_tokens` vs `max_completion_tokens`);
- whether `GET /models` exists (absent → discovery reports nothing, and the health
  probe answers optimistically since there is nothing cheap to probe);
- whether a base URL is yours rather than the vendor's, as with the account-scoped
  and region-scoped enterprise endpoints;
- how normalized [reasoning effort](../concepts/capabilities.md) is translated, where
  the provider documents a control;
- which parameters the provider accepts and silently discards, so they surface as
  `ParameterDropped` [telemetry](../concepts/telemetry.md) instead (Perplexity ignores
  `tools`, for example).

Anything beyond that (thinking budgets, search filters, sampler extensions) is the
provider's own vocabulary and goes through the escape hatch:

```python
client.generate(
    prompt,
    target="dashscope:qwen-plus",
    provider_options={"dashscope": {"enable_thinking": True, "thinking_budget": 2048}},
)
```

## Base URLs That Are Yours

Some presets need a base URL because it is yours, not theirs:

```python
ai.ProviderSettings.of(
    "cloudflare-workers-ai",
    base_url="https://api.cloudflare.com/client/v4/accounts/<account_id>/ai/v1",
    api_key="env://CLOUDFLARE_API_TOKEN",
)
ai.ProviderSettings.of("litellm", base_url="http://litellm.internal:4000", api_key="sk-…")
ai.ProviderSettings.of(
    "snowflake-cortex",
    base_url="https://<account>.snowflakecomputing.com/api/v2/cortex/v1",
    api_key="env://SNOWFLAKE_PAT",
)
ai.ProviderSettings.of(
    "databricks",
    base_url="https://<workspace-host>/serving-endpoints",
    api_key="env://DATABRICKS_TOKEN",
)
```

## Local Engines

Local-engine presets need no key, default to loopback, and a bare hostname expands with
the engine's conventional port (`ProviderSettings.of("vllm", base_url="gpu-box")` →
`http://gpu-box:8000`). The [complete inventory](all.md#local-engines-self-hosted-servers)
lists every engine with its default endpoint.

Ports are the easiest thing to get wrong here, and a wrong one fails only at request time,
so each is taken from the engine's own documentation and pinned by a test. Two cannot be
pinned at all: RamaLama starts at 8080 and walks upward when that is taken, and Foundry
Local picks its port when the service starts; read what `ramalama serve` printed, or
`foundry service status`, rather than trusting a default.

Three of these are addressed at a path that is not `/v1`, which is the likeliest reason a
correct key still 404s: Docker Model Runner serves `/engines/v1`, KServe prefixes its
routes with `/openai`, and older Llama Stack builds nest them under `/v1/openai/v1`.

For deeper local integration (model loading, residency, VRAM awareness), see the
dedicated [Ollama](ollama.md) and [llama.cpp](llama-cpp.md) adapters.

## Known Quirks

Most preset differences are mechanical. These change *behavior*, so they are worth
knowing before debugging them:

- **Tencent Hunyuan stops after the stop sequence**, where OpenAI stops before it. The
  `stop` strings will appear in the output. Code that uses a stop token as a delimiter
  and then splits on it will silently see an extra fragment.
- **Helicone inverts the routing syntax.** Most routers take `vendor/model`; Helicone
  takes `model/vendor` (`gpt-4o-mini/openai`), and a bare model id allows the gateway
  to choose the upstream.
- **Inception's diffusion models revise text they already streamed.** With
  `provider_options={"inception": {"diffusing": True}}`, deltas carry noisy tokens that
  later deltas refine *in place* rather than appending to. Code that concatenates deltas
  will produce nonsense; the flag is off by default for exactly that reason.
- **Vast.ai routes by base URL, not the `model` field.** The base URL ends in the
  endpoint name and carries no `/v1`, and the proxy ignores the `model` field; the
  served model is whatever the endpoint was configured with, so any non-empty model
  string works and a typo there fails silently instead of erroring.
- **Sarvam reasons unless told not to.** `reasoning_effort` defaults to `low` rather than
  off, so requests expected to be cheap will think first.

## Embeddings

Chat compatibility does not imply embeddings compatibility: an OpenAI-shaped
`/v1/chat/completions` says nothing about whether `/v1/embeddings` exists at all, so
every preset stays generation-only by default. Four have been verified live against
their own documentation and opt in: **Together AI**, **Fireworks AI**, **DeepInfra**,
and **Mistral**.

```python
result = client.embed(
    ["first text", "second text"],
    target="together:togethercomputer/m2-bert-80M-8k-retrieval",
)
```

Together's response carries no `usage` block, so `result.usage` stays unset for that
preset specifically; every other verified preset reports it. Mistral's dimensionality
control is spelled `output_dimension`, not the shared dialect's `dimensions`, so a
`dimensions=` request on `mistral:` is silently ignored on the wire; use
`provider_options={"mistral": {"output_dimension": N}}` instead.

Every other preset remains generation-only, including presets whose underlying engine is
known to serve OpenAI-compatible [embeddings](../concepts/embeddings.md) in general
(self-hosted engines like vLLM, for instance); verifying that a *specific* deployment
exposes it is outside what a static preset table can promise, so it stays off unless
independently confirmed. See `contracts/openai-compat-presets.md` for verification dates
and sources.

## Cost Accounting

Presets participate in [cost computation](../concepts/cost.md) like every other
provider: models with entries in the bundled pricing table report `usage.cost_usd`
automatically, and unknown prices remain unknown rather than reading as zero.

## Anthropic-Compatible Endpoints

Several of these providers (Moonshot, Z.ai, MiniMax, SambaNova, Vercel's gateway, and
others) also expose an Anthropic-Messages-compatible endpoint, reachable by
[pointing the Anthropic adapter at it](anthropic.md#pointing-this-adapter-elsewhere).
Use the OpenAI-compatible preset unless Messages-dialect behavior is specifically needed.

## Verification

Endpoint, auth, and quirk data for every preset was verified against the provider's live
documentation; the per-provider details, dates, and sources live in the
[contract snapshot](https://github.com/anthturner/AnyInfer/blob/main/contracts/openai-compat-presets.md),
which the provider drift check re-audits.
