---
icon: material/format-list-bulleted
---

# Every provider

This is AnyInfer's compatibility inventory, not its primary value proposition:
**103 providers** comprising 17 dedicated adapters with provider-specific
behavior and 86 presets over the shared OpenAI-compatible adapter. Each is a
first-class target prefix: `groq:`, `vllm:`, `bedrock:`.

!!! note "This page is generated"

    It is rendered from the provider registry by
    `scripts/generate_provider_index.py` and verified by a test, so it cannot drift
    from what the library actually ships. Counts and columns come from the code.

```python
import anyinfer as ai

# Any row below works the same way — pick the id from the "Target" column.
client = ai.Client([ai.ProviderSettings.of("groq", api_key="env://GROQ_API_KEY")])
result = client.generate(prompt, target="groq:llama-3.3-70b-versatile")
```

New to these? Start with [choosing a provider](README.md); the per-provider quirks for
the preset table are in [hosted & local presets](presets.md).

## Dedicated adapters

These need more than declarative endpoint and auth settings: a native request shape,
special auth flow, richer discovery, or provider-specific stream handling. Each has its
own adapter and guide.

| Provider | Target | Kind | What it adds |
|---|---|---|---|
| [Anthropic](anthropic.md) | `anthropic:` / `claude:` | Hosted | Messages API, extended thinking deltas; any Anthropic-shaped endpoint |
| [Azure AI Foundry](azure-foundry.md) | `azure-foundry:` / `azure:` / `foundry:` | Hosted | Deployment-addressed, `api-version` pinning |
| [AWS Bedrock](bedrock.md) | `bedrock:` / `aws-bedrock:` / `amazon-bedrock:` | Hosted | Converse API, SigV4 or API key, binary event-stream framing |
| [Cohere](cohere.md) | `cohere:` | Hosted | Native v2 chat, grounded generation, thinking channel |
| [GitHub Copilot](copilot.md) | `copilot:` / `github-copilot:` | Hosted | GitHub Copilot subscription; auth delegated to the Copilot CLI |
| [DeepSeek](deepseek.md) | `deepseek:` | Hosted | Separate reasoning channel, split cache accounting |
| [Google Gemini](gemini.md) | `gemini:` / `google:` / `google-gemini:` / `ai-studio:` | Hosted | Native `generateContent`, thinking levels, discovered windows |
| [llama.cpp (supervised llama-server)](llama-cpp.md) | `llama-cpp:` / `llamacpp:` / `llama:` | Local | Supervised `llama-server`, loopback only |
| [LM Studio](lm-studio.md) | `lm-studio:` / `lmstudio:` | Local | Native discovery: context, quantization, residency |
| [Microsoft 365 Copilot](m365-copilot.md) | `m365-copilot:` / `m365:` | Hosted | Microsoft 365 Copilot Chat, Entra auth |
| [Nebius Token Factory](nebius.md) | `nebius:` / `nebius-token-factory:` / `token-factory:` | Hosted | Verbose listing: discovered pricing, context and quantization |
| [Ollama](ollama.md) | `ollama:` | Local | Native API, grammar schemas, phase timings |
| [OpenAI](openai.md) | `openai:` | Hosted | Responses API, reasoning-token accounting |
| [OpenAI-compatible endpoint](openai-compat.md) | `openai-compat:` / `openai-compatible:` / `oai-compat:` | Hosted | Any `/chat/completions` endpoint by URL |
| [OpenRouter](openrouter.md) | `openrouter:` | Hosted | Router across upstreams, discovered per-model pricing |
| [Google Vertex AI](vertex.md) | `vertex:` / `vertex-ai:` / `google-vertex:` | Hosted | Gemini with GCP auth; project-scoped addressing |
| [xAI (Grok)](xai.md) | `xai:` / `grok:` | Hosted | Provider-reported cost, discovered pricing |

## Presets

These speak the OpenAI chat-completions dialect closely enough that one shared adapter
covers them; what differs is declarative — endpoint, auth spelling, token-field name,
model listing, reasoning translation. See [presets](presets.md) for the quirk notes.

### Hosted services

| Provider | Target | Key (conventional env var) | Notes |
|---|---|---|---|
| AI21 Labs | `ai21:` | `AI21_API_KEY` | Jamba model family; max_tokens caps at 4096 |
| Arcee AI | `arcee:` | `ARCEE_API_KEY` | Trinity models; the Conductor router (models.arcee.ai/v1) accepts model='auto' as a base-URL override |
| Avian | `avian:` | `AVIAN_API_KEY` | Keys carry a literal avian- prefix, which is part of the key rather than something to strip |
| Baseten Model APIs | `baseten:` | `BASETEN_API_KEY` | Fixed shared catalog; model listing reports pricing and context metadata |
| Zhipu BigModel (GLM, mainland) | `bigmodel:` / `zhipu-cn:` | `ZHIPU_API_KEY` | The mainland platform behind GLM, and a separate account from z-ai: keys do not cross between them |
| Cerebras Inference | `cerebras:` | `CEREBRAS_API_KEY` | Wafer-scale speed; combining tools with response_format is model-dependent |
| Chutes | `chutes:` | `CHUTES_API_KEY` | Decentralized open-model serving |
| Clarifai | `clarifai:` | `CLARIFAI_PAT` | The credential is a personal access token, not a per-app key |
| Cloudflare AI Gateway (unified) | `cloudflare-ai-gateway:` / `cf-ai-gateway:` | `CF_AIG_TOKEN` | The multi-provider gateway, not Workers AI: it fronts OpenAI, Anthropic, Groq and others behind provider/model ids |
| Cloudflare Workers AI | `cloudflare-workers-ai:` / `workers-ai:` / `cloudflare:` | `CLOUDFLARE_API_TOKEN` | @cf/author/model ids; the base URL embeds your account id |
| Alibaba Model Studio (Qwen) | `dashscope:` / `qwen:` / `alibaba-qwen:` / `model-studio:` | `DASHSCOPE_API_KEY` | International endpoint; keys are region-specific |
| Databricks Model Serving | `databricks:` / `mosaic:` | `DATABRICKS_TOKEN` | Base URL is your workspace host; a personal access token authenticates |
| DeepInfra | `deepinfra:` | `DEEPINFRA_API_KEY` | Pay-per-token open models; service_tier extension for priority/flex |
| DigitalOcean Inference | `digitalocean:` / `do-inference:` / `digitalocean-inference:` | `MODEL_ACCESS_KEY` | Serverless catalog on a fixed host; model-access keys are scopable per-model |
| Featherless AI | `featherless:` | `FEATHERLESS_API_KEY` | Very large HF-repo-id catalog, case-sensitive; subscription plans are concurrency-limited rather than token-metered |
| Fireworks AI | `fireworks:` / `fireworks-ai:` | `FIREWORKS_API_KEY` | Model ids look like accounts/fireworks/models/…; over-long max_tokens is silently truncated unless context_length_exceeded_behavior='error' |
| Groq | `groq:` | `GROQ_API_KEY` | LPU-served open models; rejects logprobs/logit_bias-style parameters |
| Helicone AI Gateway | `helicone:` / `helicone-gateway:` | `HELICONE_API_KEY` | Routing with observability |
| Hugging Face Inference Providers | `huggingface:` / `hf:` / `huggingface-router:` | `HF_TOKEN` | Routes HF-hub model ids across serving partners; append :provider to pin one (e.g |
| Tencent Hunyuan | `hunyuan:` / `tencent:` | `HUNYUAN_API_KEY` | Reasoning is mostly a model choice (the hunyuan-t1-* line), though hunyuan-a13b instead toggles it in-prompt with a /no_think prefix |
| Hyperbolic | `hyperbolic:` | `HYPERBOLIC_API_KEY` | Open-model serving; reasoning models emit inline <think> content |
| Hyperstack AI Studio | `hyperstack:` | `HYPERSTACK_API_KEY` | Base URL and model id are both read off the AI Studio playground's API panel, since they follow your deployment rather than a fixed catalog |
| Inception (Mercury) | `inception:` / `mercury:` | `INCEPTION_API_KEY` | Diffusion LLMs rather than autoregressive ones, which shows up in the stream: with provider_options {'diffusing': True} the model emits blocks of noisy tokens that are refined in place, so deltas revise earlier text instead of only appending |
| Inference.net | `inference-net:` / `inference:` | `INFERENCE_API_KEY` | Serverless ids plus team/model deployments; BYOK passthrough via provider headers |
| LightOn Paradigm | `lighton:` / `paradigm:` | `LIGHTON_API_KEY` | EU document-intelligence platform |
| LiteLLM Proxy | `litellm:` / `litellm-proxy:` | — | Self-hosted gateway over 100+ providers; authenticate with a proxy-issued virtual key |
| Martian Gateway | `martian:` | `MARTIAN_API_KEY` | creator/model ids; routes across upstream providers |
| MiniMax | `minimax:` | `MINIMAX_API_KEY` | M-series models; thinking controls via provider_options ({'thinking': {'type': …}}) |
| Mistral AI (La Plateforme) | `mistral:` / `mistral-ai:` | `MISTRAL_API_KEY` | Uses random_seed instead of seed; safe_prompt via provider_options |
| ModelScope (API-Inference) | `modelscope:` / `ms-inference:` | `MODELSCOPE_SDK_TOKEN` | Alibaba's model community |
| Moonshot AI (Kimi) | `moonshot:` / `kimi:` | `MOONSHOT_API_KEY` | Kimi model family; thinking controls via provider_options ({'thinking': …}) |
| Nous Research (Portal) | `nous:` / `nousresearch:` / `hermes:` | `NOUS_API_KEY` | Hermes models, capitalized ids (Hermes-4-405B) |
| Novita AI | `novita:` / `novita-ai:` | `NOVITA_API_KEY` | max_tokens is required by the API; reasoning models stream reasoning_content |
| Nscale | `nscale:` | `NSCALE_API_KEY` | No enforced rate limits; model listing reports pricing and context length |
| Nutanix Enterprise AI | `nutanix:` / `nai:` | `NUTANIX_API_KEY` | On-prem GPT-in-a-Box deployments; the host is your own cluster endpoint |
| NVIDIA NIM (build.nvidia.com) | `nvidia:` / `nim:` / `nvidia-nim:` | `NVIDIA_API_KEY` | Hosted NIM catalog; self-hosted NIM containers expose the same surface on your own base URL |
| Oracle OCI Generative AI | `oci-genai:` / `oci:` / `oracle:` | `OCI_GENAI_API_KEY` | Base URL is region-templated |
| Ollama Cloud | `ollama-cloud:` / `ollama-turbo:` | `OLLAMA_API_KEY` | Ollama's hosted catalog, distinct from the local ollama: adapter and needing a real key |
| OVHcloud AI Endpoints | `ovhcloud:` / `ovh:` | `OVH_AI_ENDPOINTS_ACCESS_TOKEN` | EU-hosted unified gateway |
| Parasail | `parasail:` | `PARASAIL_API_KEY` | parasail- prefixed model ids; per-model thinking controls (chat_template_kwargs, thinking_budget) via provider_options |
| Perplexity Sonar | `perplexity:` | `PERPLEXITY_API_KEY` | Grounded web search built in; search_results ride on the raw payload (retain_raw=True), search filters via provider_options |
| Poe (Quora) | `poe:` | `POE_API_KEY` | Hundreds of models and community bots behind one subscription |
| Portkey AI Gateway | `portkey:` | `PORTKEY_API_KEY` | Routing, caching and fallbacks over many providers |
| PPIO | `ppio:` / `ppinfra:` | `PPIO_API_KEY` | Formerly PPInfra: the host moved to api.ppio.com/openai, and the widely copied api.ppinfra.com/v3/openai is the legacy spelling |
| Baidu Qianfan (ERNIE) | `qianfan:` / `baidu:` / `ernie:` | `QIANFAN_API_KEY` | v2 takes a single permanent bearer key shaped bce-v3/ALTAK-<id>/<secret> — pass it whole, since the embedded slashes are part of the key |
| Reka AI | `reka:` | `REKA_API_KEY` | Multimodal (image/video/audio) |
| Requesty Router | `requesty:` | `REQUESTY_API_KEY` | vendor/model ids across many upstreams |
| Runpod Serverless | `runpod:` | `RUNPOD_API_KEY` | The base URL embeds your serverless endpoint id |
| SambaNova Cloud | `sambanova:` | `SAMBANOVA_API_KEY` | Model listing reports live per-model pricing and context metadata |
| Sarvam AI | `sarvam:` | `SARVAM_API_KEY` | Indic-language models |
| Scaleway Generative APIs | `scaleway:` | `SCW_SECRET_KEY` | EU-sovereign; ids carry quantization suffixes (:fp8, :int4) |
| SiliconFlow | `siliconflow:` / `silicon-flow:` | `SILICONFLOW_API_KEY` | The .com host serves the international account; api.siliconflow.cn is the mainland one and keys are not interchangeable |
| Snowflake Cortex | `snowflake-cortex:` / `cortex:` / `snowflake:` | `SNOWFLAKE_PAT` | Base URL embeds your account identifier; authenticate with a programmatic access token |
| iFlytek Spark | `spark:` / `iflytek:` | `SPARK_API_PASSWORD` | The HTTP surface takes a single bearer APIPassword from the console — not the legacy AppID/APIKey/APISecret triple, which belongs to the WebSocket path and does not work here |
| StepFun | `stepfun:` / `step:` | `STEP_API_KEY` | Step models |
| Together AI | `together:` / `together-ai:` | `TOGETHER_API_KEY` | Large open-model catalog; org/model ids (e.g |
| Upstage (Solar) | `upstage:` / `solar:` | `UPSTAGE_API_KEY` | Solar family; reasoning_effort semantics differ per model — solar-mini rejects the parameter entirely, solar-open2 reasons unless disabled |
| Vast.ai Serverless | `vast-ai:` / `vast:` | `VAST_API_KEY` | The base URL ends in your endpoint name and carries no /v1 |
| Venice AI | `venice:` | `VENICE_API_KEY` | Privacy-focused; max_tokens is deprecated in favour of max_completion_tokens |
| Vercel AI Gateway | `vercel-ai-gateway:` / `vercel:` / `ai-gateway:` | `AI_GATEWAY_API_KEY` | creator/model ids across upstream providers; gateway-normalized reasoning object |
| BytePlus ModelArk (Volcengine Ark) | `volcengine:` / `ark:` / `doubao:` / `bytedance:` | `ARK_API_KEY` | International (BytePlus) endpoint; the mainland edition is a separate account and host (ark.cn-beijing.volces.com/api/v3) |
| IBM watsonx.ai (model gateway) | `watsonx:` / `ibm-watsonx:` | `WATSONX_API_KEY` | The OpenAI-compatible model gateway (beta, IBM Cloud only), which sidesteps the native API's request-body project scoping and version pinning — providers are registered per project ahead of time instead |
| Z.ai (Zhipu GLM) | `z-ai:` / `zai:` / `glm:` | `ZAI_API_KEY` | GLM model family; temperature range is 0-1, thinking controls via provider_options ({'thinking': {'type': …}}) |

### Local engines & self-hosted servers

Local engines need no API key and default to loopback. Where the address is yours — a
cluster host, a dynamically assigned port — the preset requires a base URL instead.

| Provider | Target | Default endpoint | Notes |
|---|---|---|---|
| Aphrodite Engine | `aphrodite:` | `http://127.0.0.1:2242/v1` | vLLM fork with extra samplers, on port 2242 rather than vLLM's 8000; sampler extensions via provider_options |
| Docker Model Runner | `docker-model-runner:` / `dmr:` | `http://127.0.0.1:12434/engines/v1` | Built into Docker Desktop |
| Microsoft Foundry Local | `foundry-local:` / `foundry-local-service:` | _you supply it_ | On-device ONNX serving |
| GenieX (formerly Nexa SDK) | `geniex:` / `nexa:` | `http://127.0.0.1:18181/v1` | On-device Snapdragon inference, now published by Qualcomm as GenieX — the CLI is `geniex serve`, not the older `nexa serve` |
| GPT4All | `gpt4all:` | `http://localhost:4891/v1` | Minimal local server (enable in settings); no streaming or tool calling documented |
| Jan | `jan:` | `http://127.0.0.1:1337/v1` | Desktop app's local API server (enable it in Jan's settings) |
| KoboldCpp | `koboldcpp:` / `kobold:` | `http://127.0.0.1:5001/v1` | OpenAI-compatible surface beside the native Kobold API on one port; sampler extensions via provider_options |
| KServe | `kserve:` | _you supply it_ | Kubernetes model serving |
| Lemonade Server | `lemonade:` | `http://127.0.0.1:13305/v1` | AMD-sponsored server with Ryzen AI NPU backends |
| Llama Stack | `llama-stack:` / `llamastack:` | `http://127.0.0.1:8321/v1` | Meta's server, fronting vLLM/Ollama/hosted backends |
| llama-swap | `llama-swap:` | `http://127.0.0.1:8080/v1` | A proxy that swaps the upstream llama-server/vLLM process to match each request's model field, so the model id is a config profile name rather than a file |
| llamafile | `llamafile:` | `http://127.0.0.1:8080/v1` | Single self-contained executable serving one model; examples report the model id as the literal string LLaMA_CPP |
| LocalAI | `localai:` / `local-ai:` | `http://127.0.0.1:8080/v1` | Serves many models at once; ids are gallery names or GGUF filenames |
| MLC-LLM | `mlc-llm:` / `mlc:` | `http://127.0.0.1:8000/v1` | Compiled-model serving (mlc_llm serve); documents /v1/models and /v1/chat/completions only |
| OpenLLM | `openllm:` | `http://127.0.0.1:3000/v1` | BentoML's server on port 3000; one model per process, launched as 'openllm serve model:version' |
| RamaLama | `ramalama:` | `http://127.0.0.1:8080/v1` | Container-based runner |
| SGLang | `sglang:` | `http://127.0.0.1:30000/v1` | Engine extras (separate_reasoning, top_k, min_p) via provider_options |
| TabbyAPI | `tabbyapi:` / `tabby:` | `http://127.0.0.1:5000/v1` | ExLlama-family serving; inference calls use the x-api-key header |
| text-generation-webui | `text-generation-webui:` / `oobabooga:` / `textgen-webui:` | `http://127.0.0.1:5000/v1` | Start with --api; the model listing reports only the loaded model |
| Text Generation Inference | `tgi:` / `text-generation-inference:` | `http://127.0.0.1:3000/v1` | Hugging Face's server, default port 3000 |
| NVIDIA Triton (OpenAI frontend) | `triton:` / `triton-openai:` | `http://127.0.0.1:9000/v1` | The OpenAI frontend listens on 9000 — port 8000 is Triton's own KServe HTTP endpoint, not this one |
| vLLM | `vllm:` | `http://127.0.0.1:8000/v1` | Serves one model per process; engine extras (guided decoding, top_k) via provider_options |
| Xinference | `xinference:` / `xorbits:` | `http://127.0.0.1:9997/v1` | Serves many models at once; ids are the model UIDs you launched |

## Not yet covered

- **Replicate** — its predictions API is asynchronous and per-model, with no
  chat-completions route to normalize; `api.replicate.com/openapi.json` declares 26
  paths and none of them is one. A dedicated async adapter remains the only option.
- **Writer (Palmyra)** — serves `POST /v1/chat`, not `/chat/completions`, so no OpenAI
  client can reach it. The best candidate for the next dedicated adapter.

Anything else with an OpenAI-compatible endpoint already works today without waiting for
a preset — point the [generic adapter](openai-compat.md) at it:

```python
ai.ProviderSettings.of("openai-compat", base_url="https://your-host/v1", api_key="…")
```
