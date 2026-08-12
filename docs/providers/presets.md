---
icon: material/format-list-group
---

# Hosted & local OpenAI-compatible presets

One implementation, many brandings. Every provider on this page speaks the
chat-completions dialect closely enough that AnyInfer's shared OpenAI-compatible adapter
covers it, so each ships as a **preset**: a first-class registered provider with the
endpoint, auth spelling, quirks, and capabilities filled in for you.

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

Everything the [core owns](README.md#what-is-the-same-everywhere) — routing, retries,
structured output, telemetry, cost accounting — works identically through a preset.
Provider-specific extras go through `provider_options`, passed to the provider verbatim.

## Hosted services

| Preset | Target prefix | Key (conventional env var) | Notes |
|---|---|---|---|
| Groq | `groq:` | `GROQ_API_KEY` | LPU-served open models |
| Cerebras | `cerebras:` | `CEREBRAS_API_KEY` | Reasoning effort supported |
| SambaNova | `sambanova:` | `SAMBANOVA_API_KEY` | Listing reports live pricing |
| Together AI | `together:` | `TOGETHER_API_KEY` | `org/model` ids; embeddings verified |
| Fireworks AI | `fireworks:` | `FIREWORKS_API_KEY` | `accounts/fireworks/models/…` ids; embeddings verified |
| DeepInfra | `deepinfra:` | `DEEPINFRA_API_KEY` | `service_tier` extension; embeddings verified |
| Novita AI | `novita:` | `NOVITA_API_KEY` | `max_tokens` required by the API |
| Hyperbolic | `hyperbolic:` | `HYPERBOLIC_API_KEY` | |
| Baseten | `baseten:` | `BASETEN_API_KEY` | Fixed shared catalog |
| Mistral | `mistral:` | `MISTRAL_API_KEY` | Reasoning effort incl. `minimal`; embeddings verified |
| Perplexity | `perplexity:` | `PERPLEXITY_API_KEY` | Built-in web search; no tool calls |
| Moonshot (Kimi) | `moonshot:` / `kimi:` | `MOONSHOT_API_KEY` | `max_completion_tokens` dialect |
| Z.ai (GLM) | `z-ai:` / `zai:` / `glm:` | `ZAI_API_KEY` | International Zhipu host; no model listing |
| Alibaba Model Studio (Qwen) | `dashscope:` / `qwen:` | `DASHSCOPE_API_KEY` | International endpoint; regional keys |
| MiniMax | `minimax:` | `MINIMAX_API_KEY` | No model listing |
| AI21 | `ai21:` | `AI21_API_KEY` | Jamba; `max_tokens` ≤ 4096 |
| Hugging Face | `huggingface:` / `hf:` | `HF_TOKEN` | Router across serving partners |
| NVIDIA NIM | `nvidia:` / `nim:` | `NVIDIA_API_KEY` | Same surface self-hosted |
| Vercel AI Gateway | `vercel-ai-gateway:` / `vercel:` | `AI_GATEWAY_API_KEY` | `creator/model` ids |
| Cloudflare Workers AI | `cloudflare-workers-ai:` | `CLOUDFLARE_API_TOKEN` | Base URL embeds your account id |
| LiteLLM Proxy | `litellm:` | virtual key | Self-hosted; base URL required |
| Portkey | `portkey:` | `PORTKEY_API_KEY` | Upstream chosen by `x-portkey-*` headers |
| Featherless AI | `featherless:` | `FEATHERLESS_API_KEY` | Very large HF catalog; concurrency-metered |
| Parasail | `parasail:` | `PARASAIL_API_KEY` | `parasail-` prefixed ids |
| Inference.net | `inference-net:` | `INFERENCE_API_KEY` | BYOK passthrough to upstream vendors |
| Nscale | `nscale:` | `NSCALE_API_KEY` | `tool_choice` supports only auto/none |
| Scaleway | `scaleway:` | `SCW_SECRET_KEY` | EU-sovereign; quantization suffixes on ids |
| Venice AI | `venice:` | `VENICE_API_KEY` | Privacy-focused; `max_completion_tokens` dialect |
| Upstage (Solar) | `upstage:` / `solar:` | `UPSTAGE_API_KEY` | Reasoning semantics differ per model |
| Reka AI | `reka:` | `REKA_API_KEY` | Multimodal; auth via `x-api-key` |
| Nous Research | `nous:` / `hermes:` | `NOUS_API_KEY` | `max_tokens` defaults to 100 — set it |
| Arcee AI | `arcee:` | `ARCEE_API_KEY` | Trinity models |
| DigitalOcean | `digitalocean:` | `MODEL_ACCESS_KEY` | Fixed host; `max_completion_tokens` dialect |
| OVHcloud | `ovhcloud:` / `ovh:` | `OVH_AI_ENDPOINTS_ACCESS_TOKEN` | Ids are irregular; never normalize |
| Snowflake Cortex | `snowflake-cortex:` / `cortex:` | `SNOWFLAKE_PAT` | Base URL embeds your account |
| Databricks | `databricks:` | `DATABRICKS_TOKEN` | Base URL is your workspace host |
| Oracle OCI | `oci-genai:` / `oci:` | `OCI_GENAI_API_KEY` | Region-templated base URL |
| Requesty | `requesty:` | `REQUESTY_API_KEY` | Reports `usage.cost` in USD; lowest effort is `min` |
| Martian | `martian:` | `MARTIAN_API_KEY` | `creator/model` ids |
| Helicone | `helicone:` | `HELICONE_API_KEY` | Provider suffix *follows* the model |
| Chutes | `chutes:` | `CHUTES_API_KEY` | Model field doubles as a routing directive |
| Avian | `avian:` | `AVIAN_API_KEY` | Keys carry a literal `avian-` prefix |
| BytePlus ModelArk | `volcengine:` / `doubao:` | `ARK_API_KEY` | International edition; Doubao models |
| Baidu Qianfan | `qianfan:` / `ernie:` | `QIANFAN_API_KEY` | v2 bearer key only; never the v1 AK/SK flow |
| Tencent Hunyuan | `hunyuan:` | `HUNYUAN_API_KEY` | `stop` halts *after* the match |
| iFlytek Spark | `spark:` / `iflytek:` | `SPARK_API_PASSWORD` | Console APIPassword, not the AppID triple |
| StepFun | `stepfun:` / `step:` | `STEP_API_KEY` | Reasoning effort supported |
| IBM watsonx.ai | `watsonx:` | `WATSONX_API_KEY` | Beta gateway; base URL is your region's |
| Poe | `poe:` | `POE_API_KEY` | Bot-name ids; no `json_schema`, `n` must be 1 |
| SiliconFlow | `siliconflow:` | `SILICONFLOW_API_KEY` | `.com` is international, `.cn` is mainland |
| PPIO | `ppio:` / `ppinfra:` | `PPIO_API_KEY` | Renamed from PPInfra; host moved to `api.ppio.com` |
| ModelScope | `modelscope:` | `MODELSCOPE_SDK_TOKEN` | Credential is an `ms-` SDK token |
| Zhipu BigModel | `bigmodel:` / `zhipu-cn:` | `ZHIPU_API_KEY` | Mainland GLM; `temperature` is the open interval (0,1) |
| Inception (Mercury) | `inception:` / `mercury:` | `INCEPTION_API_KEY` | Diffusion models; `diffusing` revises streamed text |
| Sarvam AI | `sarvam:` | `SARVAM_API_KEY` | Indic models; reasoning is on by default |
| Clarifai | `clarifai:` | `CLARIFAI_PAT` | PAT auth; catalog-path model ids |
| LightOn Paradigm | `lighton:` / `paradigm:` | `LIGHTON_API_KEY` | Base path is `/api/v2` |
| Ollama Cloud | `ollama-cloud:` | `OLLAMA_API_KEY` | Hosted catalog; ids drop the `-cloud` suffix |
| Runpod | `runpod:` | `RUNPOD_API_KEY` | Base URL embeds your endpoint id |
| Vast.ai | `vast-ai:` / `vast:` | `VAST_API_KEY` | The `model` field is ignored by the proxy |
| Cloudflare AI Gateway | `cloudflare-ai-gateway:` | `CF_AIG_TOKEN` | Multi-provider gateway; `provider/model` ids |
| Hyperstack | `hyperstack:` | `HYPERSTACK_API_KEY` | Base URL and ids come from your deployment |
| Nutanix Enterprise AI | `nutanix:` / `nai:` | `NUTANIX_API_KEY` | On-prem; base URL is your cluster |

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

## Local engines

No key, loopback by default, and a bare hostname expands with the engine's conventional
port (`ProviderSettings.of("vllm", base_url="gpu-box")` →
`http://gpu-box:8000`):

| Preset | Target prefix | Default endpoint | Notes |
|---|---|---|---|
| vLLM | `vllm:` | `http://127.0.0.1:8000/v1` | One model per server process |
| SGLang | `sglang:` | `http://127.0.0.1:30000/v1` | |
| KoboldCpp | `koboldcpp:` / `kobold:` | `http://127.0.0.1:5001/v1` | |
| Jan | `jan:` | `http://127.0.0.1:1337/v1` | Enable the server in Jan's settings |
| GPT4All | `gpt4all:` | `http://localhost:4891/v1` | No streaming or tools |
| text-generation-webui | `text-generation-webui:` / `oobabooga:` | `http://127.0.0.1:5000/v1` | Start with `--api` |
| TabbyAPI | `tabbyapi:` / `tabby:` | `http://127.0.0.1:5000/v1` | Auth via `x-api-key` |
| LocalAI | `localai:` | `http://127.0.0.1:8080/v1` | Serves many models at once |
| llamafile | `llamafile:` | `http://127.0.0.1:8080/v1` | Model id reports as `LLaMA_CPP` |
| Text Generation Inference | `tgi:` | `http://127.0.0.1:3000/v1` | Model id is the literal `tgi` |
| OpenLLM | `openllm:` | `http://127.0.0.1:3000/v1` | BentoML; `openllm serve model:version` |
| Aphrodite Engine | `aphrodite:` | `http://127.0.0.1:2242/v1` | Port 2242, not vLLM's 8000 |
| MLC-LLM | `mlc-llm:` / `mlc:` | `http://127.0.0.1:8000/v1` | Needs a compiled model library |
| NVIDIA Triton | `triton:` | `http://127.0.0.1:9000/v1` | Port 9000 — 8000 is Triton's own KServe API |
| Xinference | `xinference:` | `http://127.0.0.1:9997/v1` | Serves many models; ids are launched UIDs |
| RamaLama | `ramalama:` | `http://127.0.0.1:8080/v1` | Port drifts upward if 8080 is taken |
| GenieX | `geniex:` / `nexa:` | `http://127.0.0.1:18181/v1` | Formerly Nexa SDK; `geniex serve` |
| Llama Stack | `llama-stack:` | `http://127.0.0.1:8321/v1` | Older builds nest routes under `/v1/openai/v1` |
| Lemonade | `lemonade:` | `http://127.0.0.1:13305/v1` | AMD NPU backends; key is a `?api_key=` query param |
| Docker Model Runner | `docker-model-runner:` / `dmr:` | `http://127.0.0.1:12434/engines/v1` | Routes live under `/engines/v1`, not `/v1` |
| llama-swap | `llama-swap:` | `http://127.0.0.1:8080/v1` | Model id is a config profile; swapping reloads |
| KServe | `kserve:` | _you supply it_ | Routes sit behind an `/openai` prefix |
| Foundry Local | `foundry-local:` | _you supply it_ | Port is assigned at service start; never hardcode |

Ports are the easiest thing to get wrong here, and a wrong one fails only at request time,
so each is taken from the engine's own documentation and pinned by a test. Two cannot be
pinned at all: RamaLama starts at 8080 and walks upward when that is taken, and Foundry
Local picks its port when the service starts — read what `ramalama serve` printed, or
`foundry service status`, rather than trusting a default.

Three of these are addressed at a path that is not `/v1`, which is the likeliest reason a
correct key still 404s: Docker Model Runner serves `/engines/v1`, KServe prefixes its
routes with `/openai`, and older Llama Stack builds nest them under `/v1/openai/v1`.

For deeper local integration — model loading, residency, VRAM awareness — see the
dedicated [Ollama](ollama.md) and [llama.cpp](llama-cpp.md) adapters.

## Quirks that will bite you

Most preset differences are mechanical. These change *behavior*, so they are worth
knowing before you debug them:

- **Tencent Hunyuan stops after the stop sequence**, where OpenAI stops before it. Your
  `stop` strings will appear in the output. Code that uses a stop token as a delimiter
  and then splits on it will silently see an extra fragment.
- **Helicone inverts the routing syntax.** Most routers take `vendor/model`; Helicone
  takes `model/vendor` (`gpt-4o-mini/openai`), and a bare model id lets the gateway
  choose the upstream for you.
- **Inception's diffusion models revise text they already streamed.** With
  `provider_options={"inception": {"diffusing": True}}`, deltas carry noisy tokens that
  later deltas refine *in place* rather than appending to. Code that concatenates deltas
  will produce nonsense; the flag is off by default for exactly that reason.
- **Vast.ai ignores the `model` field entirely.** The served model is whatever the
  endpoint was configured with, so the routing lives in the base URL and any non-empty
  model string works. A typo there fails silently instead of erroring.
- **Sarvam reasons unless told not to.** `reasoning_effort` defaults to `low` rather than
  off, so requests you expect to be cheap will think first.

## What a preset does and does not change

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
  `ParameterDropped` telemetry instead (Perplexity ignores `tools`, for example).

Anything beyond that — thinking budgets, search filters, sampler extensions — is the
provider's own vocabulary and goes through the escape hatch:

```python
client.generate(
    prompt,
    target="dashscope:qwen-plus",
    provider_options={"dashscope": {"enable_thinking": True, "thinking_budget": 2048}},
)
```

## Embeddings

Chat compatibility does not imply embeddings compatibility — an OpenAI-shaped
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
preset specifically — every other verified preset reports it. Mistral's dimensionality
control is spelled `output_dimension`, not the shared dialect's `dimensions`, so a
`dimensions=` request on `mistral:` is silently ignored on the wire; use
`provider_options={"mistral": {"output_dimension": N}}` instead.

Every other preset on this page remains generation-only, including presets whose
underlying engine is known to serve OpenAI-compatible embeddings in general (self-hosted
engines like vLLM, for instance) — verifying that a *specific* deployment exposes it is
outside what a static preset table can promise, so it stays off unless independently
confirmed. See `contracts/openai-compat-presets.md` for verification dates and sources.

## Cost accounting

Presets participate in [cost computation](../concepts/budgeting.md) like every other
provider: models with entries in the bundled pricing table report `usage.cost_usd`
automatically, and unknown prices remain unknown rather than reading as zero.

## Anthropic-compatible endpoints

Several of these providers also expose an Anthropic-Messages-compatible endpoint
(Moonshot, Z.ai, MiniMax, SambaNova, Vercel's gateway, and others). The
[Anthropic adapter](anthropic.md) accepts a base-URL override, so those are reachable
without any extra machinery:

```python
ai.ProviderSettings.of(
    "anthropic",
    base_url="https://api.moonshot.ai/anthropic",
    api_key="env://MOONSHOT_API_KEY",
)
```

Use the OpenAI-compatible preset unless you specifically need Messages-dialect behavior.

## Verification

Endpoint, auth, and quirk data for every preset was verified against the provider's live
documentation; the per-provider details, dates, and sources live in the
[contract snapshot](https://github.com/anthturner/AnyInfer/blob/main/contracts/openai-compat-presets.md),
which the provider drift check re-audits.
