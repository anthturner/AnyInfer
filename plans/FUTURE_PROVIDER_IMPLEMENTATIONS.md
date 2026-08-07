# Future Provider Implementations

Prioritized checklist of engines, hosted providers, and routers worth adding to AnyInfer,
ordered by priority **descending** (commonality / user count / notoriety). Check items off
as adapters land. When an adapter lands, add its `contracts/<provider>.md` snapshot in the
same change set (see [AGENTS.md](../AGENTS.md)).

Provider details (URLs, endpoints, compat claims) were written against docs as of
**2026-08**; re-verify against live docs before implementing (the `/check-provider-drift`
skill workflow applies). Everything checked off below **was** re-verified against live
documentation on 2026-08-07, with sources recorded in the contract snapshots — except
**Groq**, whose documentation blocked automated access; its entry was built from the
official `groq-python` SDK reference and is flagged for the next drift check.

Legend:
- **OpenAI-compat**: whether the provider exposes an OpenAI Chat Completions–compatible
  endpoint that the existing `openai_compat` adapter could reach with just a base URL +
  key. "Yes, but…" means a thin config entry works for an MVP, but a dedicated adapter
  unlocks provider-specific features.
- Priority is about *breadth of users who would want it*, not implementation ease.

---

## How the landed items were implemented (2026-08-07)

Most Tier 2–4 items landed exactly as implementation note 1 anticipated: a **preset
registry** (`providers/presets.py`) of declarative descriptors over the shared
`openai_compat` adapter, verified against live provider documentation and recorded in
`contracts/openai-compat-presets.md`. Items needing real protocol translation got
dedicated adapters: **Gemini** (native `generateContent`), **DeepSeek**
(`reasoning_content` channel + split cache accounting), and **xAI**
(`max_completion_tokens`, reported cost, priced model listing).

Note 2 also landed: the Anthropic adapter takes its base URL and provider id from
configuration, so every Anthropic-compatible Messages endpoint (Moonshot, Z.ai, DeepSeek,
xAI, MiniMax, SambaNova, Vercel's gateway) is reachable without new code.

**Dropped:** Lambda Inference API — lambda.ai carries an official wind-down notice and
its API documentation has been removed.

**Still open:** Replicate alone — its predictions API is asynchronous and per-model,
which fits a chat multiplexer poorly; see the per-item note below. Everything else in
this document has landed, across four waves; the registry now holds **one hundred and
three providers** — seventeen dedicated adapters and eighty-six OpenAI-compatible
presets. The complete list is published at `docs/providers/all.md`, generated from the
registry by `scripts/generate_provider_index.py` so it cannot drift.

## Second wave (2026-08-07) — twenty-four more, beyond the original list

The list above is complete, so a second pass sourced providers it never named. Twenty-four
landed as verified presets, taking the registry to fifty-two presets and sixty-eight
providers overall. All were verified against live documentation the same day, with the
details in `contracts/openai-compat-presets.md`.

- **Hosted:** Nebius Token Factory (since promoted to a dedicated adapter), Featherless AI, Parasail, Inference.net, Nscale,
  Scaleway Generative APIs, Venice AI, Upstage (Solar), Reka AI, Nous Research, Arcee AI
- **Cloud platforms:** DigitalOcean Inference, OVHcloud AI Endpoints, Snowflake Cortex,
  Databricks Model Serving, Oracle OCI Generative AI
- **Gateways:** Portkey
- **Local engines:** LocalAI, llamafile, Text Generation Inference, OpenLLM, Aphrodite
  Engine, MLC-LLM, NVIDIA Triton (OpenAI frontend)

Two premises the earlier document would have gotten wrong were corrected by verification:
Oracle now ships a first-party OpenAI-compatible endpoint that accepts a static key, so
request signing is no longer the only path, and Snowflake Cortex is explicitly
OpenAI-spec-compliant with static tokens. Both are therefore presets, not adapters.

**Surveyed and deliberately rejected** — each needs a dedicated adapter, so shipping a
preset would have been wrong rather than merely thin:

- **Writer (Palmyra)** — serves `POST /v1/chat`, not `/chat/completions`, and returns a
  `{"models": […]}` listing. An OpenAI client cannot reach it at all. Best candidate for
  the next dedicated adapter.
- **IBM watsonx.ai** — IAM token exchange, `project_id`/`space_id` in the body, and a
  mandatory `version` query parameter on every call. *Overturned in the third wave:* the
  `/openai/v1` gateway accepts a plain bearer, so a preset works provided the caller
  supplies an **exchanged IAM token** rather than a raw API key. The descriptor says so.
- **PowerInfer** — its vendored llama.cpp fork predates the native `/v1` routes and
  documents no chat-completions endpoint.
- **Kong AI Gateway** — upstream credentials are configured server-side per route, so
  there is no client-supplied base URL to preset.
- **Xinference** — plausible, but its documentation host rate-limited every attempt, and
  an unverified preset would violate the verification rule. *Overturned in the third wave:*
  the docs were reachable, port 9997 confirmed, and it landed as a preset.

New pricing landed for Venice (105 models), DigitalOcean (54), Reka, Upstage and Arcee.
The other nineteen publish no per-token USD rate this table could carry honestly — several
report live pricing through their own model listing, and the enterprise clouds bill in
DBUs, credits or per-character transactions. `pricing.json` records the reason per
provider rather than leaving the omissions unexplained.

## Third wave (2026-08-07) — routers, regional clouds, and local engines

A third pass targeted three groups the earlier waves under-covered: cost-reporting routers,
the Chinese regional clouds, and local engines that had shipped an OpenAI frontend since.
Fourteen landed as presets and one — Nebius — was promoted from preset to a dedicated
adapter. The registry now holds **seventeen dedicated adapters and sixty-five presets,
eighty-two providers overall**.

- **Routers and gateways:** Requesty, Martian, Helicone, Chutes, Avian
- **Regional clouds:** BytePlus ModelArk (Volcengine Ark), Baidu Qianfan, Tencent Hunyuan,
  iFlytek Spark, StepFun
- **Enterprise:** IBM watsonx.ai
- **Local engines:** Xinference, RamaLama, GenieX

**Promoted to a dedicated adapter:** Nebius. `GET /models?verbose=true` returns pricing,
context length and quantization per model, so capabilities arrive `discovered` rather than
catalogued — worth more here than elsewhere because Nebius prices `-fast` flavors as
separate ids and its catalog turns over faster than a bundled table could track.

Two entries record an upstream rebrand rather than a new service: GenieX is the former
Nexa SDK under Qualcomm with a renamed CLI, and BytePlus ModelArk is Volcengine Ark's
international edition.

Two behavioral traps are documented in the preset guide rather than a table cell, because
they change output rather than plumbing: **Hunyuan halts after the stop sequence** where
OpenAI halts before it, and **Helicone inverts routing to `model/vendor`**.

**Still rejected from this wave's survey:** Writer (Palmyra) remains the best candidate for
the next dedicated adapter — it serves `POST /v1/chat`, which no OpenAI client can reach.

### Re-verification pass (2026-08-07) — six corrections

The third wave was re-audited against live documentation immediately after landing, on the
principle that a preset nobody has run is a claim rather than a fact. Six entries were
wrong, every one of them in a way that fails only against the real service:

- **StepFun's host was wrong twice over.** Recorded as `https://api.stepfun.ai/step_plan/v1`;
  the documented endpoint is `https://api.stepfun.com/v1` — `.com`, not `.ai`, and
  `/step_plan/v1` is the *subscription* surface, billed separately. Both domains answer,
  which is precisely why this would have survived a smoke test. Its key env is `STEP_API_KEY`.
- **Three model listings were disabled that shouldn't have been.** Helicone, GenieX and
  Qianfan all document `GET /models`; Helicone's returns HTTP 200 unauthenticated on a live
  probe, and Qianfan's reports per-model pricing. Discovery silently returned nothing.
- **watsonx did not require a token exchange.** IBM's own OpenAI-SDK example passes the
  Cloud API key straight through, so demanding an exchanged IAM token was an invented
  obstacle. Its `max_completion_tokens` claim was also unverified — IBM's examples use
  `max_tokens` — and the gateway is beta, IBM Cloud only.
- **Requesty spells its lowest effort `min`, not `minimal`.** A near-homograph: the old
  mapping clamped to `low`, which was safe but quietly asked for more reasoning than the
  caller wanted. It now translates to the documented `min`.
- **Qianfan's thinking control was inverted.** Recorded as a model choice (ERNIE-X1); it is
  parameter-driven (`thinking` or `enable_thinking`, per model family), and ERNIE-X1 is
  stale naming.

Each correction is pinned by a regression test, since all six are invisible to unit tests
that never touch the network. Three pre-existing tests asserted the *old* values and were
themselves corrected — the tests encoded the bug rather than catching it.

New pricing from this pass: **Avian** (10 models) and **Chutes** (13), both read from the
providers' live `/v1/models` so the ids are the API's own rather than pricing-page display
names — Chutes' real ids carry a `-TEE` suffix the pricing page omits entirely. Hunyuan and
StepFun publish in CNY only and are deliberately absent rather than converted at an FX rate
this file cannot keep current.

## Fourth wave (2026-08-08) — past one hundred providers

A fourth pass targeted what the first three under-covered: subscription aggregators, the
remaining Chinese platforms, deployment-scoped serverless hosts, and local engines that
shipped an OpenAI frontend since. Twenty landed as presets, taking the registry to
**seventeen dedicated adapters and eighty-six presets, one hundred and three providers
overall**.

- **Aggregators and routers:** Poe (Quora), Cloudflare AI Gateway (the multi-provider
  `compat` surface, distinct from the Workers AI preset already present)
- **Regional and specialist clouds:** SiliconFlow, PPIO (formerly PPInfra), ModelScope,
  Zhipu BigModel (the mainland platform behind GLM), Sarvam AI, LightOn Paradigm,
  Inception (Mercury), Clarifai
- **Deployment-scoped serverless:** Runpod, Vast.ai, Hyperstack, Nutanix Enterprise AI
- **Hosted catalog of an existing local engine:** Ollama Cloud
- **Local engines:** Llama Stack, Lemonade (AMD Ryzen AI NPU), Docker Model Runner,
  llama-swap, KServe, Microsoft Foundry Local

The theme of this batch is **addressing** rather than dialect. Seven entries are account-
or deployment-scoped and carry no default base URL at all; five more serve the OpenAI
routes at a path that is not `/v1` — PPIO at `/openai`, Docker Model Runner at
`/engines/v1`, KServe behind an `/openai` prefix, LightOn at `/api/v2`, BigModel at
`/api/paas/v4`. A wrong prefix 404s only against the real service, so each is pinned by a
regression test.

Three entries record a fact that search results actively get wrong, which is the case for
verifying against first-party docs rather than aggregators:

- **PPIO** rebranded from PPInfra and moved host. Nearly every third-party write-up still
  gives `api.ppinfra.com/v3/openai`; the current docs give `api.ppio.com/openai`. The old
  brand survives as an alias.
- **Ollama Cloud's model ids drop the `-cloud` suffix.** That suffix is how a *local*
  Ollama names a cloud-proxied model; calling ollama.com directly wants the bare id.
- **Foundry Local's port is assigned at service start.** Microsoft's own reference says
  never to hardcode it and shows two different values in its own examples, so the preset
  requires a base URL despite being a loopback service.

**Surveyed and rejected**, each for a reason that would have made the preset wrong rather
than merely thin:

- **kluster.ai** — wound down; the site now redirects to an unrelated product.
- **Meta Llama API** — OpenAI-compatible and well documented, but with a published
  retirement date of 2026-07-06. Adding it would ship a known expiry.
- **Lepton AI** — acquired by NVIDIA; the serverless token-billed API is sunset.
- **Anyscale Endpoints** — sunset in late 2024.
- **Aleph Alpha** — its native client is not OpenAI-shaped, and PhariaAI *consumes*
  OpenAI-compatible APIs rather than exposing one.
- **Crusoe, TensorWave, Civo, Genesis Cloud, Koyeb, Salad** — GPU infrastructure, not
  token APIs; the `vllm` and `tgi` presets already cover what you deploy on them.
- **Bifrost, TrueFoundry, AISIX, Higress** — self-hosted gateways configured server-side,
  the same reason Kong was rejected in the second wave.

Test coverage changed shape alongside the registry. Preset conformance had run against
six hand-picked "representatives"; it now runs the full suite against **every** preset,
since the harness is provider-agnostic and the quirk axes are not as orthogonal as the
sampling assumed. A new whole-registry invariant class in `tests/test_registry_and_catalog.py`
asserts properties of all one hundred and three descriptors — every one instantiable,
no local engine defaulting off-box, no plaintext credential to a non-loopback host,
every reasoning translator accepting all four normalized levels, no display-name
collisions — so a future provider has to satisfy them without anyone remembering to
write a test for it.

## Already implemented

- [x] **OpenAI** (ChatGPT models — GPT-4.1/4o/5 series, o-series) — `providers/openai.py`, `contracts/openai.md`
- [x] **Anthropic** (Claude) — `providers/anthropic.py`, `contracts/anthropic.md`
- [x] **OpenRouter** (router) — `providers/openrouter.py`, `contracts/openrouter.md`
- [x] **Ollama** (local engine) — `providers/ollama.py`, `contracts/ollama.md`
- [x] **llama.cpp** (`llama-server`, local engine) — `providers/llama_cpp.py`, `contracts/llama-cpp.md`
- [x] **GitHub Copilot** — `providers/copilot.py`, `contracts/copilot.md`
- [x] **Microsoft 365 Copilot** — `providers/m365_copilot.py`, `contracts/m365-copilot.md`
- [x] **Azure AI Foundry** (incl. Azure OpenAI) — `providers/azure_foundry.py`, `contracts/azure-foundry.md`
- [x] **Generic OpenAI-compatible** (catch-all) — `providers/openai_compat.py`, `contracts/openai-compat.md`

---

## Tier 1 — Frontier / mass-market (do these first)

- [x] **Google Gemini** (aka Google AI Studio, Generative Language API) — **landed as a dedicated adapter** (`providers/gemini.py`, `contracts/gemini.md`)
  - URL: https://ai.google.dev · API docs: https://ai.google.dev/api
  - Base: `https://generativelanguage.googleapis.com/v1beta` — native `generateContent`
    / `streamGenerateContent` protocol, API-key auth (`x-goog-api-key`).
  - OpenAI-compat: **Yes, but incomplete** — `https://generativelanguage.googleapis.com/v1beta/openai/`
    exists; it lags the native API. **Use the native API**: thinking budgets, safety
    settings, context caching, Files API, grounding/search tools, and code execution are
    native-only or better-supported there.
  - Biggest gap in the current lineup — arguably the #1 missing provider by user count.

- [x] **Google Vertex AI** (enterprise Gemini; also hosts Claude, Llama, Mistral) — **landed as a dedicated adapter** (`providers/vertex.py`, `contracts/vertex.md`), a
  `gemini` subclass that changes only addressing and auth. Claude-on-Vertex
  (`rawPredict`) is still uncovered; reachable via the anthropic adapter's base URL.
  - URL: https://cloud.google.com/vertex-ai · API docs: https://cloud.google.com/vertex-ai/generative-ai/docs
  - Base: `https://{region}-aiplatform.googleapis.com/v1/projects/{project}/locations/{region}/publishers/...`
    — same `generateContent` wire shape as Gemini API but **GCP OAuth/ADC auth**, not API key.
  - OpenAI-compat: partial (`.../endpoints/openapi/chat/completions`); native is more complete.
  - Claude-on-Vertex uses the Anthropic Messages shape via `rawPredict`/`streamRawPredict`
    — potentially reuse the Anthropic adapter with a Vertex transport (mirrors how the
    Anthropic SDK does it). Consider sharing a protocol core with the Gemini adapter.

- [x] **AWS Bedrock** (hosts Claude, Amazon Nova, Llama, Mistral, DeepSeek, …) — **landed as a dedicated adapter** (`providers/bedrock.py`, `contracts/bedrock.md`)
  speaking Converse/ConverseStream, including a first-party decoder for AWS's binary
  `vnd.amazon.eventstream` framing.
  - URL: https://aws.amazon.com/bedrock · API docs: https://docs.aws.amazon.com/bedrock/latest/APIReference/
  - Native: **Converse / ConverseStream** unified API (recommended over per-model
    `InvokeModel`). Auth is AWS SigV4 (or Bedrock API keys, added 2025) — the main
    implementation cost; consider optional `boto3`/`aws4` dependency or hand-rolled SigV4.
  - OpenAI-compat: limited endpoint added 2025 (`/openai/v1/chat/completions`) for select
    models — fine for MVP, but Converse is the real interface (doc blocks, guardrails,
    caching points).
  - Claude-on-Bedrock also speaks the Anthropic Messages shape via `InvokeModel` —
    same transport-reuse idea as Vertex.

- [x] **xAI Grok** — **landed as a dedicated adapter** (`providers/xai.py`, `contracts/xai.md`)
  - URL: https://x.ai · API docs: https://docs.x.ai
  - Base: `https://api.x.ai/v1` — API-key auth.
  - OpenAI-compat: **Yes** (chat completions), and also exposes an **Anthropic-compatible**
    Messages endpoint. Native extras: Live Search / server-side web+X search parameters,
    deferred completions. MVP via `openai_compat` config; dedicated adapter for search
    params and reasoning-effort mapping.

- [x] **DeepSeek** — **landed as a dedicated adapter** (`providers/deepseek.py`, `contracts/deepseek.md`)
  - URL: https://www.deepseek.com · API docs: https://api-docs.deepseek.com
  - Base: `https://api.deepseek.com` (also `/v1` alias) — API-key auth.
  - OpenAI-compat: **Yes** (also an Anthropic-compatible endpoint). Quirks worth a
    dedicated adapter: `reasoning_content` field on R1/reasoner models (streamed
    separately from `content`), automatic context-caching with distinct cache-hit/miss
    pricing (`prompt_cache_hit_tokens`), `deepseek-chat` vs `deepseek-reasoner` model
    split. Very high notoriety since R1.

- [x] **Mistral AI** (La Plateforme) — **landed as a preset** (`providers/presets.py`)
  - URL: https://mistral.ai · API docs: https://docs.mistral.ai/api/
  - Base: `https://api.mistral.ai/v1` — API-key auth.
  - OpenAI-compat: **Mostly** — chat completions shape is near-identical; MVP via config
    entry. Native extras deserving an adapter: FIM endpoint (`/v1/fim/completions` for
    Codestral), OCR/Document AI, Agents API, `safe_prompt`, structured outputs.

## Tier 2 — Major hosted inference & aggregators

- [x] **Groq** (LPU fast inference; not Grok) — **landed as a preset** (`providers/presets.py`)
  - URL: https://groq.com · API docs: https://console.groq.com/docs
  - Base: `https://api.groq.com/openai/v1` — API-key auth.
  - OpenAI-compat: **Yes, explicitly** (documented deviations: some sampling params
    ignored/rejected, e.g. `logprobs`/`frequency_penalty` historically). Config entry is
    likely enough; huge developer mindshare for fast open-model serving.

- [x] **Together AI** — **landed as a preset** (`providers/presets.py`)
  - URL: https://www.together.ai · API docs: https://docs.together.ai/reference
  - Base: `https://api.together.xyz/v1` — API-key auth.
  - OpenAI-compat: **Yes**. Big open-model catalog (Llama, Qwen, DeepSeek …). Config
    entry first; adapter only if their extras (dedicated endpoints, rerank) matter.

- [x] **Fireworks AI** — **landed as a preset** (`providers/presets.py`)
  - URL: https://fireworks.ai · API docs: https://docs.fireworks.ai
  - Base: `https://api.fireworks.ai/inference/v1` — API-key auth.
  - OpenAI-compat: **Yes**. Model ids look like `accounts/fireworks/models/…`. Config
    entry first.

- [x] **Perplexity** (Sonar API) — **landed as a preset** (`providers/presets.py`)
  - URL: https://www.perplexity.ai · API docs: https://docs.perplexity.ai
  - Base: `https://api.perplexity.ai` — API-key auth.
  - OpenAI-compat: **Yes for request shape**, but responses carry search extras
    (`search_results`/citations) and requests take search-domain/recency filters — a
    dedicated adapter is needed to surface grounded-search results properly.

- [x] **Alibaba Qwen** (DashScope / Model Studio) — **landed as a preset** (`providers/presets.py`)
  - URL: https://www.alibabacloud.com/en/product/modelstudio · API docs: https://www.alibabacloud.com/help/en/model-studio/
  - Base (intl): `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` — API-key auth.
  - OpenAI-compat: **Yes** (compatible-mode); native DashScope protocol also exists with
    extras (`enable_thinking`, partial mode). Qwen models are extremely popular; config
    entry first, adapter for thinking controls.

- [x] **Moonshot AI (Kimi)** — **landed as a preset** (`providers/presets.py`)
  - URL: https://www.moonshot.ai · API docs: https://platform.moonshot.ai/docs
  - Base: `https://api.moonshot.ai/v1` — API-key auth.
  - OpenAI-compat: **Yes**; also an **Anthropic-compatible** endpoint
    (`https://api.moonshot.ai/anthropic`) popular for Claude Code–style tooling.
    Kimi K2 raised its profile substantially. Config entry first. (Note: existing
    `plans/KIMI_*.md` docs suggest in-house interest.)

- [x] **Z.ai (Zhipu, GLM models)** — **landed as a preset** (`providers/presets.py`)
  - URL: https://z.ai · API docs: https://docs.z.ai
  - Base: `https://api.z.ai/api/paas/v4` — API-key auth.
  - OpenAI-compat: **Mostly** (chat completions shape); also an Anthropic-compatible
    endpoint used by GLM coding plans. GLM-4.x models are widely used; config entry first.

- [x] **Cohere** — **landed as a dedicated adapter** (`providers/cohere.py`,
  `contracts/cohere.md`) on the native v2 Chat API. Grounded generation and citations
  are reachable through `provider_options` but not yet normalized.
  - URL: https://cohere.com · API docs: https://docs.cohere.com/reference/chat
  - Base: `https://api.cohere.com/v2` — API-key auth.
  - OpenAI-compat: **Compatibility API exists** (`https://api.cohere.ai/compatibility/v1`)
    but the native v2 Chat API is the complete interface (documents/RAG citations,
    rerank, embed). Enterprise/RAG notoriety; needs a native adapter to be worthwhile.

- [x] **Cerebras Inference** — **landed as a preset** (`providers/presets.py`)
  - URL: https://cerebras.ai · API docs: https://inference-docs.cerebras.ai
  - Base: `https://api.cerebras.ai/v1` — API-key auth.
  - OpenAI-compat: **Yes** (documented unsupported params). Known for extreme
    tokens/sec; config entry is probably sufficient.

- [x] **Hugging Face Inference Providers** (router) — **landed as a preset** (`providers/presets.py`)
  - URL: https://huggingface.co/inference · API docs: https://huggingface.co/docs/inference-providers
  - Base: `https://router.huggingface.co/v1` — HF token auth.
  - OpenAI-compat: **Yes** (chat completions router across Together/Fireworks/etc.).
    Config entry first; `:provider` suffix routing in model ids.

- [x] **Mistral-hosted / NVIDIA NIM** (build.nvidia.com) — **landed as a preset** (`providers/presets.py`)
  - URL: https://build.nvidia.com · API docs: https://docs.nvidia.com/nim/
  - Base: `https://integrate.api.nvidia.com/v1` — API-key auth.
  - OpenAI-compat: **Yes**. Also relevant for self-hosted NIM containers (same
    OpenAI-compat surface on localhost). Config entry.

## Tier 3 — Local engines & self-hosted servers (high fit for a multiplexing library)

- [x] **LM Studio** — **landed as a dedicated adapter** (`providers/lm_studio.py`,
  `contracts/lm-studio.md`): generation on the OpenAI-compatible endpoint, discovery on
  the native API (context length, quantization, residency). Model *management*
  (load/unload/download) is read-only for now.
  - URL: https://lmstudio.ai · API docs: https://lmstudio.ai/docs/app/api
  - Base: `http://localhost:1234/v1` (OpenAI-compat) **plus** a more complete native REST
    API (`/api/v0/…`, and newer `/api/v1`) with model load/unload, TTL, and stats.
  - OpenAI-compat: **Yes**; prefer a dedicated adapter to expose model management +
    loaded-model discovery, mirroring what the Ollama adapter does.

- [x] **vLLM** (self-hosted serving engine) — **landed as a preset** (`providers/presets.py`)
  - URL: https://vllm.ai · API docs: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html
  - Base: user-hosted, `http://host:8000/v1` — optional key.
  - OpenAI-compat: **Yes** (the de-facto OSS serving standard). Extras via `extra_body`
    (guided decoding, beam search). Config entry / documented preset over the
    `openai_compat` adapter is likely enough.

- [x] **SGLang** (self-hosted serving engine) — **landed as a preset** (`providers/presets.py`)
  - URL: https://docs.sglang.ai · OpenAI-compat server like vLLM; config preset.

- [x] **KoboldCpp** — **landed as a preset** (`providers/presets.py`)
  - URL: https://github.com/LostRuins/koboldcpp · OpenAI-compat endpoint plus native
    Kobold API (`/api/v1/generate`). Niche but loyal local-LLM user base; config entry.

- [x] **Jan** (local app, OpenAI-compat server on `http://localhost:1337/v1`) — config entry. — **landed as a preset** (`providers/presets.py`).
- [x] **GPT4All** (local app, OpenAI-compat server on `http://localhost:4891/v1`) — config entry. — **landed as a preset** (`providers/presets.py`).
- [x] **text-generation-webui (oobabooga)** — OpenAI-compat extension, `http://localhost:5000/v1`; config entry. — **landed as a preset** (`providers/presets.py`).
- [x] **TabbyAPI / ExLlamaV2** — OpenAI-compat, exllama-focused; config entry. — **landed as a preset** (`providers/presets.py`).

## Tier 4 — Routers, gateways & secondary hosts

- [x] **Vercel AI Gateway** (router) — **landed as a preset** (`providers/presets.py`)
  - URL: https://vercel.com/ai-gateway · API docs: https://vercel.com/docs/ai-gateway
  - Base: `https://ai-gateway.vercel.sh/v1` — API-key (or Vercel OIDC) auth.
  - OpenAI-compat: **Yes**; also Anthropic-compatible endpoint. `creator/model-name`
    ids, provider-routing options similar to OpenRouter. Config entry first.

- [x] **Cloudflare Workers AI / AI Gateway** — **landed as a preset** (`providers/presets.py`)
  - URL: https://developers.cloudflare.com/workers-ai/ · AI Gateway: https://developers.cloudflare.com/ai-gateway/
  - Base: `https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1` (OpenAI-compat)
    — API-token auth. AI Gateway additionally proxies *other* providers (incl. OpenAI,
    Anthropic) with caching/analytics — worth supporting as a base-URL override pattern
    on existing adapters, not just a new adapter.

- [x] **LiteLLM Proxy** (self-hosted router) — **landed as a preset** (`providers/presets.py`)
  - URL: https://docs.litellm.ai · OpenAI-compat proxy in front of 100+ providers.
    Support = documented config preset for `openai_compat` (base URL + virtual key).

- [x] **DeepInfra** — https://deepinfra.com · Base `https://api.deepinfra.com/v1/openai`; OpenAI-compat: yes. Config entry. — **landed as a preset** (`providers/presets.py`).
- [x] **SambaNova Cloud** — https://cloud.sambanova.ai · Base `https://api.sambanova.ai/v1`; OpenAI-compat: yes. Config entry. — **landed as a preset** (`providers/presets.py`).
- [ ] **Replicate** — https://replicate.com · API docs: https://replicate.com/docs/reference/http
  - **The one item still open, and deliberately so.** Not OpenAI-compatible in general:
    a native predictions API (async, polling or SSE) with per-model schemas. Big
    notoriety, but models-as-predictions fits a chat multiplexer poorly — there is no
    stable request shape to normalize across models, which is the premise the whole
    adapter contract rests on. Revisit if demand appears.
  - **Re-checked 2026-08-07 against the authoritative source** rather than search
    results: `https://api.replicate.com/openapi.json` declares 26 paths, none of which
    is a chat-completions route (`/predictions`, `/models/{owner}/{name}/predictions`,
    `/trainings`, `/files`, `/search`, …). There is still no OpenAI-compatible surface to
    preset, so the original deferral stands on current evidence rather than on the
    reasoning that first produced it. A dedicated async adapter remains the only option.
- [x] **Baseten** — https://baseten.co · Model APIs expose OpenAI-compat endpoints; config entry. — **landed as a preset** (`providers/presets.py`).
- [x] **Novita AI** — https://novita.ai · OpenAI-compat (`https://api.novita.ai/v3/openai`); config entry. — **landed as a preset** (`providers/presets.py`).
- [x] **Hyperbolic** — https://hyperbolic.xyz · OpenAI-compat (`https://api.hyperbolic.xyz/v1`); config entry. — **landed as a preset** (`providers/presets.py`).
- [x] **MiniMax** — https://www.minimax.io · API docs: https://platform.minimax.io/docs — **landed as a preset** (`providers/presets.py`).
  - OpenAI-compat-ish chat endpoint + native API; rising notoriety (MiniMax-M/abab, audio/video). Config entry first.
- [x] **AI21 Labs (Jamba)** — https://www.ai21.com · Base `https://api.ai21.com/studio/v1`; OpenAI-compat-ish chat. Config entry. — **landed as a preset** (`providers/presets.py`).
- [x] **Lambda Inference API** — **dropped, not implemented.** lambda.ai carries an
  official wind-down notice for the Inference API and docs.lambda.ai has removed its
  documentation entirely (verified 2026-08-07). No preset was added.
- [x] **Amazon Nova (direct)** — **covered by the Bedrock adapter**; no separate
  adapter needed, as anticipated. Nova pricing is in the bundled table under `bedrock`.

---

## Implementation notes (cross-cutting)

1. **Config-entry vs. dedicated adapter.** Many Tier 2–4 items are pure OpenAI-compat
   hosts. The cheapest path to broad coverage is a curated **provider preset registry**
   (name → base URL, auth header, known quirks/param blocklist, pricing) layered on
   `providers/openai_compat.py`, reserving dedicated adapters for providers with real
   protocol deltas (Gemini, Vertex, Bedrock, Cohere, Perplexity, LM Studio, Replicate).
2. **Anthropic-compatible endpoints are a pattern now** (xAI, DeepSeek, Moonshot, Z.ai,
   Vercel Gateway, MiniMax). Consider making the Anthropic adapter base-URL/auth
   configurable the same way `openai_compat` is, to get these nearly free.
3. **Cloud-auth transports** (SigV4 for Bedrock, OAuth/ADC for Vertex) are the main new
   infrastructure. **Decided and landed 2026-08-07: hand-rolled, behind reserved
   extras.** Both flows live in `providers/cloud_auth.py` against the standard library
   and `httpx2`, so the slim core is untouched and `pip install anyinfer` still pulls
   two dependencies. Credentials resolve in precedence order — an explicit token or
   key, then the official SDK when the application happens to have it installed (it
   knows about SSO caches, instance metadata, and profile chains), then the in-house
   flow. `anyinfer[bedrock]` is reserved and empty; `anyinfer[vertex]` carries only
   `cryptography`, needed to sign a service-account JWT — and only when neither a
   pre-acquired token nor `google-auth` is available.
4. **Pricing/capabilities**: each new provider needs `capabilities/pricing.json` entries
   and conformance coverage per `testing/conformance.py`; reasoning-token and
   cache-pricing fields differ per provider (DeepSeek cache-hit pricing, Gemini thinking
   tokens) and should be captured in the contract snapshots.
