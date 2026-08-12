# openai-compat presets — Protocol Contract

Status: **implemented** — `providers/presets.py`, branded descriptors over the shared
`openai-compat` adapter (see `contracts/openai-compat.md` for the base dialect this file
inherits; only per-provider deltas are recorded here).
Last verified: 2026-08-07 — live provider documentation, per the sources under each entry.
Exception: **groq** could not be re-verified this session (console.groq.com and groq.com
blocked automated access); its entry is built from the official groq-python SDK reference
plus search excerpts of the official compatibility page, and is flagged for the next
drift check.

Removed during verification: **Lambda Inference API** — lambda.ai carries an official
wind-down notice and docs.lambda.ai has removed the API documentation entirely, so no
preset was added.

Presets carry no wire logic of their own beyond four declarative knobs on the shared
adapter: auth header spelling (`Authorization: Bearer` vs `x-api-key`), the output-token
parameter name (`max_tokens` vs `max_completion_tokens`), whether `GET /models` exists
(absent → empty discovery + optimistic health), and reasoning-effort translation
(`reasoning_effort` string, minimal→low clamped variant, a three-level variant for
providers publishing only low/medium/high, or a `reasoning: {effort}` object). Everything
else in each entry is context for the drift check.

One further knob is declarative but *not* wire logic: `accepts_api_key` controls whether a
preset offers a credential field at all. It exists because two entries below authenticate
somewhere other than the header this adapter sends — **lemonade** documents an `?api_key=`
query parameter, and **docker-model-runner** ignores `Authorization` outright — so both are
declared `accepts_api_key=False`. Every other keyless local engine does accept a bearer
credential once its operator enables auth (see each entry's Auth line, which records the
flag or setting that turns it on), and offers the field as an optional one.

A second batch of twenty-three presets was added on 2026-08-07 (`featherless` through `triton`
below), each verified against live documentation the same way. Four candidates surveyed in
that pass were deliberately **not** added, because a preset would have been wrong rather
than merely incomplete: **Writer** exposes `POST /v1/chat`, not `/v1/chat/completions`, and
returns a `{"models": […]}` listing, so an OpenAI client cannot reach it at all;
**IBM watsonx.ai** requires an IAM token exchange plus `project_id`/`space_id` in the body
and a mandatory `version` query parameter; **PowerInfer**'s vendored server predates the
llama.cpp `/v1` routes and documents no chat-completions endpoint; and **Kong AI Gateway**
is configured server-side per route, so there is no client-supplied base URL to preset.
Each would need a dedicated adapter, and Writer and watsonx remain plausible candidates for
one.

## groq — Groq (GroqCloud)

- Base URL: `https://api.groq.com/openai/v1`
- Auth: Authorization: Bearer <key>
- `GET /models`: yes
- Compatibility notes:
  NOT DIRECTLY VERIFIED THIS SESSION: console.groq.com and api.groq.com returned 403/'Access
  denied. Please check your network settings.' to every fetch method tried (WebFetch and curl
  with browser UA); groq.com/pricing now 308-redirects to the groq.com homepage, so no pricing
  could be read from an official page. Facts below come from (a) the official groq-python SDK
  reference (raw.githubusercontent.com/groq/groq-python/main/api.md, loaded successfully —
  confirms endpoints: chat/completions, models list/retrieve/delete, batches, files, audio
  transcriptions/translations/speech, embeddings), and (b) a web-search excerpt of the official
  https://console.groq.com/docs/openai page: unsupported OpenAI fields that return 400 if
  supplied: logprobs, top_logprobs, logit_bias, messages[].name; n must equal 1 if supplied;
  temperature=0 is converted to 1e-8; audio transcription response_format values vtt and srt
  unsupported. A Responses API also exists (console.groq.com/docs/responses-api). Groq's known
  streaming-usage convention (usage delivered in the final SSE chunk under an x_groq field)
  could not be confirmed from official pages this session and should be re-verified before
  implementing.
- Reasoning:
  Could not be verified this session (docs blocked). Groq documents reasoning at
  console.groq.com/docs/reasoning (reasoning_format raw/parsed/hidden and reasoning_effort for
  supported models per prior contract snapshots) — treat as unverified until console.groq.com is
  reachable; re-run /check-provider-drift from a network Groq does not block.
- Sources (NOT fully verified this session):
  - https://raw.githubusercontent.com/groq/groq-python/main/api.md
  - https://console.groq.com/docs/openai
  - https://groq.com/pricing
  - https://groq.com/sitemap.xml

## cerebras — Cerebras Inference

- Base URL: `https://api.cerebras.ai/v1`
- Auth: Authorization: Bearer <key>
- `GET /models`: yes
- Compatibility notes:
  GET https://api.cerebras.ai/v1/models documented and works (returns object=list with model
  ids). Combining tools + response_format is model-dependent: gpt-oss-120b rejects requests
  containing both fields; other models may accept the combination but prioritize tool calling
  (docs say don't rely on response_format then). frequency_penalty, presence_penalty, logit_bias
  are listed but 'parameter support can differ depending on the model used'.
  stream_options.include_usage is NOT documented anywhere in the chat-completions spec or
  streaming guide (usage-in-stream behavior undocumented). max_completion_tokens includes
  reasoning tokens. usage object: prompt_tokens, completion_tokens, total_tokens, image_tokens
  (vision), prompt_tokens_details.cached_tokens, completion_tokens_details. Prompt caching is
  automatic (128-token prefix blocks, org-scoped, 5min-1hr TTL) with NO price discount: 'Input
  tokens, whether served from the cache or processed fresh, are billed at the standard input
  token rate'. Cerebras-specific params: reasoning_effort, reasoning_format, clear_thinking,
  prompt_cache_key (requires enablement), prediction, service_tier (Private Preview:
  priority/default/auto/flex). Free tier context 65k vs 131k paid. Model catalog is small: gpt-
  oss-120b (production), gemma-4-31b (preview), zai-glm-4.7 (preview, deprecation Aug 17 2026).
- Reasoning:
  Controlled per model via reasoning_effort: gpt-oss-120b accepts low/medium/high (default
  medium); zai-glm-4.7 accepts 'none' to disable (legacy disable_reasoning boolean deprecated
  after Jul 21 2026); gemma-4-31b default 'none' (disabled), low/medium/high enable. Output
  shape controlled by reasoning_format: 'parsed' = reasoning in separate `reasoning` field
  (logprobs split into reasoning_logprobs); 'raw' = reasoning prepended to content (GLM wraps in
  <think>...</think>); 'hidden' = generated but stripped from response; 'none' = model default.
  Billing: reasoning tokens count toward completion_tokens and are billed as output even when
  hidden/stripped; max_completion_tokens includes reasoning. Reasoning does not carry across
  turns automatically — prior reasoning must be re-included manually in the model's native
  format; clear_thinking param controls including thinking from previous turns.
- Sources (verified 2026-08-07):
  - https://inference-docs.cerebras.ai/llms.txt
  - https://inference-docs.cerebras.ai/resources/openai.md
  - https://inference-docs.cerebras.ai/api-reference/chat-completions.md
  - https://inference-docs.cerebras.ai/api-reference/models/list-models.md
  - https://inference-docs.cerebras.ai/capabilities/reasoning.md
  - https://inference-docs.cerebras.ai/capabilities/streaming.md

## sambanova — SambaNova Cloud (SambaCloud)

- Base URL: `https://api.sambanova.ai/v1`
- Auth: Authorization: Bearer <key> (Anthropic-compat /v1/messages endpoint also accepts x-api-key: <key>; same key works for both)
- `GET /models`: yes
- Anthropic-compatible endpoint: `https://api.sambanova.ai/v1`
- Compatibility notes:
  GET /v1/models documented and notably returns per-model pricing metadata (prompt/completion
  token price in USD), context_length, max_completion_tokens, owned_by, sn_metadata — adapters
  can fetch live prices. presence_penalty and frequency_penalty are documented as IGNORED
  (accepted, no effect). n supported with values 1-8, but n>1 combined with tools/function
  calling returns 400. seed unavailable on multimodal or continuous-batching models; logit_bias
  unavailable on multimodal or high-throughput models. No system_fingerprint in responses. top_k
  is a SambaNova extension param. Both max_tokens and max_completion_tokens accepted. Streaming:
  SSE; chunks may contain MULTIPLE tokens per chunk (count all tokens in each chunk for
  metrics); stream_options.include_usage supported — usage arrives in final chunk marked
  is_last_response: true. usage object includes cached tokens plus performance metrics (time-to-
  first-token, tokens/sec, total latency) and completion_tokens_details.reasoning_tokens. Prompt
  caching (Automatic Prefix Caching) currently MiniMax-M2.7 only, on by default, requires
  >=4096-token prefix; usage reports prompt_tokens_details.cached_tokens (billed at lower cached
  rate) and cache_creation_tokens (informational, no charge); cost = (prompt_tokens -
  cached_tokens) x input_rate + cached_tokens x cached_rate + completion_tokens x output_rate.
  An OpenAI Responses API (POST /v1/responses) is also available.
- Reasoning:
  reasoning_effort request param (enum low/medium/high) controls reasoning-token budget on
  compatible models (e.g. gpt-oss-120b); chat_template_kwargs: {enable_thinking: bool} toggles
  DeepSeek-style thinking (DeepSeek-V3.2 thinking mode is optional and disabled by default).
  Reasoning output appears inline in message content inside <think>...</think> tags (no separate
  reasoning_content field documented); usage reports completion_tokens_details.reasoning_tokens.
  Docs note reasoning raises token usage/latency (billed within completion tokens; no separate
  reasoning rate published). On the Anthropic-compatible Messages API, thinking:
  {type:'enabled'} returns 400 — only type:'disabled' works.
- Sources (verified 2026-08-07):
  - https://sambanova-systems.mintlify.site/docs/llms.txt
  - https://sambanova-systems.mintlify.dev/docs/en/get-started/api-keys-urls.md
  - https://sambanova-systems.mintlify.dev/docs/en/get-started/quickstart.md
  - https://sambanova-systems.mintlify.dev/docs/en/features/openai-compatibility.md
  - https://sambanova-systems.mintlify.dev/docs/en/features/messages.md
  - https://sambanova-systems.mintlify.dev/docs/en/features/prompt-caching.md

## together — Together AI

- Base URL: `https://api.together.ai/v1`
- Auth: Authorization: Bearer <TOGETHER_API_KEY>
- `GET /models`: yes
- Compatibility notes:
  Docs canonicalize base URL as https://api.together.ai/v1 (legacy host api.together.xyz still
  referenced elsewhere; alt v2 listing at https://api-inference.together.ai/v2/models). Model
  ids use <org>/<model> format (e.g. deepseek-ai/DeepSeek-V4-Pro). service_tier, store,
  metadata, and prediction are accepted but ignored. seed is best-effort (determinism not
  guaranteed across replicas). n works on most models but may be rejected (loop client-side).
  logit_bias unsupported on most models. Vision 'detail' field accepted but ignored. No
  Assistants/Threads/Runs, no OpenAI-shaped Batch or Files APIs, no Moderations endpoint (use
  Llama Guard). Errors are OpenAI-shaped but with proprietary type/code values — match on HTTP
  status. Usage reporting varies by model: reasoning models nest cached/reasoning token details
  under usage.prompt_tokens_details while others return cached_tokens flat at usage level;
  clients must check both. GET /v1/models returns per-model context_length and a pricing object
  (base/input/output/cached_input/finetune/hourly).
- Reasoning:
  reasoning_effort request parameter is supported. Reasoning output is returned in a 'reasoning'
  field on assistant messages (not OpenAI's nested structure). For reasoning models,
  cached/reasoning token counts are nested under usage.prompt_tokens_details (location differs
  from non-reasoning models). Docs pages loaded did not state a separate billing rate for
  reasoning tokens (they are counted in token usage; no separate reasoning price published on
  the pricing page).
- Embeddings (verified live 2026-08-12, docs.together.ai/reference/embeddings):
  `POST /v1/embeddings`, `model`/`input` request, `data[].embedding`/`model`/`object`
  response. **No `usage` block documented** — `embed()` results carry no usage for this
  preset. Listed models: WhereIsAI/UAE-Large-V1, BAAI/bge-large-en-v1.5,
  BAAI/bge-base-en-v1.5, togethercomputer/m2-bert-80M-8k-retrieval. Declared in
  `presets.py` as `embeddings=True`; wire mapping is otherwise the unmodified shared
  `openai_compat_embeddings.py` dialect.
- Sources (verified 2026-08-07):
  - https://docs.together.ai/docs/openai-api-compatibility
  - https://www.together.ai/pricing
  - https://docs.together.ai/reference/models-1
  - https://docs.together.ai/docs/serverless-models
  - https://docs.together.ai/reference/embeddings (embeddings, verified 2026-08-12)

## fireworks — Fireworks AI

- Base URL: `https://api.fireworks.ai/inference/v1`
- Auth: Authorization: Bearer <FIREWORKS_API_KEY>
- `GET /models`: yes
- Anthropic-compatible endpoint: `https://api.fireworks.ai/inference`
- Compatibility notes:
  Model ids are globally unique names of form accounts/<ACCOUNT_ID>/models/<MODEL_ID>
  (serverless: accounts/fireworks/models/<slug>; dot in version becomes 'p', e.g. glm-5p2,
  qwen3p7-plus, kimi-k2p6). max_tokens is silently adjusted DOWN if prompt+max_tokens exceeds
  context window instead of erroring; control via context_length_exceeded_behavior = 'truncate'
  (default) | 'error'. Usage is returned for BOTH streaming and non-streaming by default: final
  SSE chunk (the one with finish_reason set) carries usage totals; set include_usage=false to
  opt out (inverse of OpenAI's opt-in stream_options.include_usage). Extension params: top_k,
  min_p, typical_p, repetition_penalty, mirostat_target/mirostat_lr, prompt_truncate_len,
  raw_output, return_token_ids, prompt_token_ids, safe_tokenization, echo_last, prompt_cache_key
  / prompt_cache_isolation_key (cache session affinity), perf_metrics_in_response,
  stream_options buffering (buffer_tokens/buffer_ms/buffer_mode). Perf metrics always in
  response headers (fireworks-prompt-tokens, fireworks-server-time-to-first-token); in streaming
  they appear under perf_metrics in the final chunk. finish_reason values: stop, length,
  function_call (legacy), tool_calls. Validation errors return FastAPI-style 422
  HTTPValidationError {detail:[{loc,msg,type,input,ctx}]} rather than OpenAI error shape.
  OpenAI-style GET /v1/models exists under the inference base (documented via Python client
  ListModelsResponse); full-metadata management listing at GET
  https://api.fireworks.ai/v1/accounts/{account_id}/models (page_size max 200, AIP-160 filter).
- Reasoning:
  reasoning_effort accepts strings ('low','medium','high','xhigh','max','none','adaptive'),
  booleans (Fireworks extension), or positive integers (hard token limit on reasoning output);
  defaults vary per model (e.g. MiniMax M2 always on defaulting 'medium', DeepSeek V3.1 binary
  default off, DeepSeek V3.2 default on). Alternative Anthropic-style 'thinking' param: {type:
  'enabled'|'disabled'|'adaptive', budget_tokens >= 1024}; specifying both thinking and
  reasoning_effort raises a validation error. Reasoning output is returned in reasoning_content
  (separate from content); when streaming, accumulate delta.reasoning_content. reasoning_history
  = 'disabled'|'interleaved'|'preserved' controls how prior reasoning is included in the prompt;
  interleaved thinking triggers when the last message has role 'tool'; 'preserved' feeds full
  reasoning context across turns. On the Anthropic-compatible endpoint, thinking is exposed as
  content blocks with block.type == 'thinking'. Reasoning tokens are part of normal output token
  usage; no separate reasoning price published on the serverless pricing page.
- Embeddings (verified live 2026-08-12, docs.fireworks.ai): `POST /v1/embeddings` under
  the same `/inference/v1` root as chat; `model`/`input` request, response carries
  `data`/`model`/`usage` — fully OpenAI-shaped, unlike Together's usage-less response.
  Documented model: `nomic-ai/nomic-embed-text-v1.5` (8,192 tokens, configurable output
  dimensions — but the shared dialect only forwards `dimensions`, not any
  Fireworks-specific dimension parameter name, since none was found in the fetched
  content; verify before relying on dimension truncation). Declared `embeddings=True`.
- Sources (verified 2026-08-07):
  - https://docs.fireworks.ai/tools-sdks/openai-compatibility
  - https://docs.fireworks.ai/serverless/pricing
  - https://fireworks.ai/pricing
  - https://docs.fireworks.ai/guides/querying-text-models
  - https://docs.fireworks.ai/api-reference/post-chatcompletions
  - https://docs.fireworks.ai/api-reference/anthropic-messages
  - https://docs.fireworks.ai/api-reference/creates-an-embedding-vector-representing-the-input-text
    (embeddings, verified 2026-08-12)

## deepinfra — DeepInfra

- Base URL: `https://api.deepinfra.com/v1/openai`
- Auth: Authorization: Bearer <DEEPINFRA_TOKEN>
- `GET /models`: yes
- Anthropic-compatible endpoint: `https://api.deepinfra.com/anthropic`
- Compatibility notes:
  Docs moved to docs.deepinfra.com (deepinfra.com/docs/* returns 308 redirects). Docs warn 'We
  may not be 100% compatible with all OpenAI parameters.' Documented params: model, messages,
  max_tokens, stream, temperature, top_p, stop, n, presence_penalty, frequency_penalty,
  response_format, tools/tool_choice, plus extensions service_tier ('priority' = 50% surcharge /
  1.5x, 'flex' = 20% discount / 0.8x, standard 1x), fail_fast (capacity-aware rejection),
  reasoning_effort. Streaming: standard OpenAI SSE ending with data: [DONE]; the final chunk
  before [DONE] contains usage (prompt_tokens/completion_tokens) with no stream_options opt-in
  required; docs do not mention an estimated_cost field in the stream. Response continuation
  supported when output limit is exceeded. Model listing: native Models List endpoint documented
  at docs.deepinfra.com/api-reference/models/models-list (returns model_name, type, pricing
  incl. per-token table, max_tokens, deprecated/replaced_by, quantization, etc.); the OpenAI-
  convention GET {base}/models route is not explicitly documented on the pages loaded. Also has
  native inference API at /v1/inference/{model_name}. Model ids are HF-style org/name (e.g.
  deepseek-ai/DeepSeek-V4-Pro, anthropic/claude-sonnet-5 — DeepInfra now hosts Anthropic Claude
  models).
- Reasoning:
  reasoning_effort: 'none'|'low'|'medium'|'high' ('higher effort means deeper thinking but more
  output tokens and higher latency'). Alternative fine-grained 'reasoning' object: {effort:
  <same values>, enabled: bool}; enabled:false == reasoning_effort:'none'. Reasoning models
  produce a reasoning trace alongside the response by default; model API docs show it on
  assistant messages as reasoning_content (OpenAI-compatible format). Billing: 'Reasoning tokens
  count toward output token billing.' Params are no-ops on non-reasoning models.
- Embeddings (verified live 2026-08-12, docs.deepinfra.com/apis/embeddings):
  `POST https://api.deepinfra.com/v1/openai/embeddings` — under the preset's existing
  base URL, so the shared dialect's default `{base}/embeddings` path resolves correctly
  with no override needed. `model`/`input`/`encoding_format` ("float" only) request;
  `data[].embedding`/`model`/`usage.prompt_tokens` response. Models: Qwen3 Embedding
  family, BAAI/bge, sentence-transformers, and more (browse the models page). Declared
  `embeddings=True`.
- Sources (verified 2026-08-07):
  - https://docs.deepinfra.com/chat/overview
  - https://docs.deepinfra.com/chat/streaming
  - https://docs.deepinfra.com/chat/reasoning
  - https://docs.deepinfra.com/integrations/anthropic
  - https://docs.deepinfra.com/api-reference/models/models-list
  - https://deepinfra.com/pricing
  - https://docs.deepinfra.com/apis/embeddings (embeddings, verified 2026-08-12)

## novita — Novita AI

- Base URL: `https://api.novita.ai/openai`
- Auth: Authorization: Bearer <API key>
- `GET /models`: yes
- Compatibility notes:
  Current documented OpenAI-compat base is https://api.novita.ai/openai with endpoints
  /v1/chat/completions, /v1/completions (legacy), GET /v1/models and GET /v1/models/{model}
  (older references and some cached docs still show https://api.novita.ai/v3/openai — support
  both when routing). Chat completions: `max_tokens` is documented as REQUIRED.
  stream_options.include_usage supported (usage appended before [DONE]). Extensions beyond
  OpenAI: video content and audio input/output modalities, model-specific params like
  `separate_reasoning` (DeepSeek) and `enable_thinking`, plus top_k/min_p sampling. GET
  /v1/models returns per-model metadata including input_token_price_per_m /
  output_token_price_per_m and context_size — note these price fields are in credit units
  (appear to be USD*10000) and can lag the pricing page. Model ids are author/model (e.g. meta-
  llama/llama-3.3-70b-instruct, deepseek/deepseek-r1).
- Reasoning:
  Reasoning models (DeepSeek R1 family etc.) return thinking in a dedicated reasoning_content
  field: response.choices[0].message.reasoning_content non-streaming,
  chunk.choices[0].delta.reasoning_content when streaming; active by default on reasoning
  models. `separate_reasoning`/`enable_thinking` params control splitting. Reasoning tokens
  billed as normal output tokens (billing 'based on the number of tokens for both input and
  output').
- Sources (verified 2026-08-07):
  - https://novita.ai/docs/guides/llm-api
  - https://novita.ai/docs/guides/llm-models
  - https://novita.ai/docs/api-reference/model-apis-llm-create-chat-completion
  - https://novita.ai/docs/guides/llm-reasoning
  - https://novita.ai/docs/llms.txt
  - https://novita.ai/pricing

## hyperbolic — Hyperbolic

- Base URL: `https://api.hyperbolic.xyz/v1`
- Auth: Authorization: Bearer <API key> (keys from app.hyperbolic.ai)
- `GET /models`: yes
- Compatibility notes:
  Docs have migrated: docs.hyperbolic.xyz now 301s through docs.hyperbolic.ai to
  hyperbolic.ai/docs (inference docs at hyperbolic.ai/docs/inference/overview) — but the API
  host remains api.hyperbolic.xyz/v1. Drop-in OpenAI replacement: POST /v1/chat/completions with
  streaming, tool calling (18+ models), and structured JSON output; also a legacy OpenAI text-
  completions endpoint for base-model prompting (notably Llama-3.1-405B-Base in BF16 and FP8).
  Docs state the model list is available via the API but do not spell out the /v1/models path on
  the overview page. ~25+ open-source models (Llama 3.1/3.2 Vision, Qwen 2.5/Qwen2-VL, DeepSeek
  V3/R1, Hermes 3, Mistral). No Anthropic-compatible endpoint documented.
- Reasoning:
  Serves chain-of-thought models (e.g. DeepSeek R1); no dedicated reasoning field or reasoning-
  token controls are documented — expect inline <think>-style content on reasoning models.
  Reasoning tokens are not documented as billed separately from output tokens.
- Sources (verified 2026-08-07):
  - https://www.hyperbolic.ai/docs/inference/overview
  - https://hyperbolic.ai/docs/

## baseten — Baseten (Model APIs)

- Base URL: `https://inference.baseten.co/v1`
- Auth: Authorization: Bearer <BASETEN_API_KEY>
- `GET /models`: yes
- Anthropic-compatible endpoint: `https://inference.baseten.co/v1/messages (Anthropic Messages format, beta; requires overriding the Anthropic SDK default_headers to send Authorization: Bearer instead of x-api-key)`
- Compatibility notes:
  Fixed shared-infrastructure catalog (~12 slugs), not arbitrary models. GET /v1/models returns
  the live catalog with metadata including pricing, context windows, and supported features —
  served context/output limits can differ from a model's advertised native maximum. Slugs are
  author/Model case-sensitive (deepseek-ai/DeepSeek-V4-Pro, deepseek-ai/DeepSeek-V4-Flash-0731,
  zai-org/GLM-4.7, zai-org/GLM-5.2, zai-org/GLM-5.2-Fast, thinkingmachines/inkling,
  thinkingmachines/inkling-small, moonshotai/Kimi-K2.6, moonshotai/Kimi-K2.7-Code,
  moonshotai/Kimi-K3, nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B, openai/gpt-oss-120b). 'Fast'
  tier variants are separate slugs with their own pricing/rate limits on dedicated capacity.
  Tool calling, structured outputs, JSON mode on all models; vision on Inkling and Kimi; audio
  on Inkling only. KV-cache prompt caching is automatic on every request with cached input
  tokens billed at a discounted rate.
- Reasoning:
  Reasoning enabled by default for DeepSeek V4 Pro/Flash, Inkling/Inkling-Small, Kimi K3, gpt-
  oss-120b; opt-in for GLM 4.7/5.2, Kimi K2.6/K2.7, Nemotron Ultra via chat_template_args (e.g.
  enable_thinking) and a reasoning_effort param (values vary per model, e.g.
  none/low/medium/high/max), passed via extra_body in OpenAI SDKs. Reasoning output returned in
  a separate message.reasoning_content field (streamed too); reasoning tokens are included in
  completion_tokens and billed as output.
- Sources (verified 2026-08-07):
  - https://docs.baseten.co/development/model-apis/overview
  - https://docs.baseten.co/inference/model-apis/overview
  - https://docs.baseten.co/inference/model-apis/reasoning
  - https://www.baseten.co/pricing

## mistral — Mistral La Plateforme

- Base URL: `https://api.mistral.ai/v1`
- Auth: Authorization: Bearer <MISTRAL_API_KEY>
- `GET /models`: yes
- Compatibility notes:
  POST /v1/chat/completions is OpenAI-shaped with documented deviations: uses random_seed
  instead of seed; no logit_bias and no user param documented; safe_prompt (bool, default false)
  injects a safety system prompt; tool_choice accepts "any" in addition to auto/none/required
  (plus object form); response_format supports text | json_object | json_schema; temperature
  guidance is 0.0-0.7. presence_penalty, frequency_penalty, n, stop, max_tokens ARE supported.
  Mistral-specific extras: prompt_mode ("reasoning"), reasoning_effort
  (none|minimal|low|medium|high|xhigh), prompt_cache_key (opt-in prompt caching, cached tokens
  billed at 10% of input price), prediction (predicted outputs), parallel_tool_calls (default
  true), guardrails, metadata. GET /v1/models works for listing. Streaming is data-only SSE;
  usage-in-stream behavior is not explicitly documented (stream_options.include_usage not
  documented). Batch API gives 50% discount. Docs pricing-page FAQ still shows a stale "$2/$6
  Mistral Large" example that conflicts with the current mistral-large-2512 model card
  ($0.50/$1.50) — model cards are the authoritative per-model prices.
- Reasoning:
  Reasoning is controlled per-request via reasoning_effort (none|minimal|low|medium|high|xhigh)
  and/or prompt_mode:"reasoning" on chat completions. Changelog states Mistral Medium 3.5 has
  adjustable reasoning via reasoning_effort; Mistral Small 4 is a hybrid instruct+reasoning
  model. No separate reasoning-token billing or separate reasoning delta field is documented —
  no reasoning_content-style channel appears in the chat completions reference, so assume
  reasoning is billed as normal output tokens until docs say otherwise.
- Embeddings (verified live 2026-08-12, docs.mistral.ai/api/endpoint/embeddings):
  `POST /v1/embeddings`, model `mistral-embed`. `model`/`input` request as usual, plus
  Mistral-specific extras beyond the shared dialect: `output_dimension` (int, **not**
  the shared dialect's `dimensions` field name — a `dimensions=` request through
  `client.embed()` is therefore silently ignored on the wire for this preset; use
  `provider_options={"mistral": {"output_dimension": N}}`), `output_dtype`
  (float/int8/uint8/binary/ubinary), `encoding_format` (float/base64), `metadata`.
  Response: `data[].{embedding,index,object}`, `model`, `usage`. Max inputs per request
  and default dimensionality were not stated in the fetched content — not assumed.
  Declared `embeddings=True` despite the field-name mismatch, since the base wire shape
  (model/input in, data[].embedding out) still works; only native dimension truncation
  needs the escape hatch.
- Sources (verified 2026-08-07):
  - https://docs.mistral.ai/api/
  - https://mistral.ai/pricing/
  - https://docs.mistral.ai/getting-started/models/models_overview/
  - https://docs.mistral.ai/models/model-cards/mistral-medium-3-5-26-04
  - https://docs.mistral.ai/models/model-cards/mistral-large-3-25-12
  - https://docs.mistral.ai/models/model-cards/codestral-25-08
  - https://docs.mistral.ai/api/endpoint/embeddings (embeddings, verified 2026-08-12)

## perplexity — Perplexity Sonar

- Base URL: `https://api.perplexity.ai`
- Auth: Authorization: Bearer <PERPLEXITY_API_KEY>
- `GET /models`: yes
- Compatibility notes:
  Sonar API canonical endpoint is now POST /v1/sonar, with POST /chat/completions kept as an
  OpenAI-SDK-compatible alias (base_url https://api.perplexity.ai). Unsupported/ignored OpenAI
  params per official compatibility page: logit_bias, n, functions, tools, presence_penalty,
  frequency_penalty. Supported: model, messages, max_tokens (up to 128k), temperature (0-2),
  top_p, stream, response_format (text | json_schema). Streaming: SSE;
  stream_options.include_usage:true yields a final usage chunk before data: [DONE]; stream_mode
  full|concise controls whether reasoning events are suppressed or emitted separately.
  Perplexity-specific request fields (send via extra_body with OpenAI SDKs): search_mode
  (web|academic|sec), search_domain_filter, search_recency_filter (hour|day|week|month|year),
  disable_search, enable_search_classifier, return_images, return_related_questions,
  web_search_options {search_context_size: low|medium|high, search_type: fast|pro|auto,
  user_location, image relevance filtering}, reasoning_effort (minimal|low|medium|high),
  language_preference (ISO 639-1). Extra response fields: search_results (title/url/date array),
  citations (URL array), images; usage adds num_search_queries, citation_tokens,
  reasoning_tokens and a cost breakdown. GET /v1/models exists (no auth, OpenAI list format) but
  lists Agent API models (third-party provider ids like anthropic/*, openai/*), not the sonar
  family — there is no documented sonar model-listing endpoint. Docs note Sonar chat completions
  is being migrated toward the Agent API (POST /v1/agent, alias POST /v1/responses, base
  https://api.perplexity.ai/v2 in examples); a separate Gateway API lives at
  https://api.perplexity.ai/router/v1.
- Reasoning:
  reasoning_effort request param (minimal|low|medium|high) on the Sonar endpoint. Reasoning
  token usage is reported in usage.reasoning_tokens; for sonar-deep-research reasoning tokens
  are billed separately at $3.00/1M. stream_mode:'concise' emits reasoning events as separate
  stream events; 'full' suppresses them. Sonar answers are additionally billed per-request
  search fees tiered by web_search_options.search_context_size (low/medium/high).
- Sources (verified 2026-08-07):
  - https://docs.perplexity.ai/getting-started/overview
  - https://docs.perplexity.ai/getting-started/pricing
  - https://docs.perplexity.ai/api-reference/chat-completions-post
  - https://docs.perplexity.ai/docs/sonar/openai-compatibility
  - https://docs.perplexity.ai/api-reference/models-get

## moonshot — Moonshot AI (Kimi)

- Base URL: `https://api.moonshot.ai/v1`
- Auth: Authorization: Bearer <key> (Anthropic-compat endpoint uses the same Kimi key via ANTHROPIC_AUTH_TOKEN, not ANTHROPIC_API_KEY)
- `GET /models`: yes
- Anthropic-compatible endpoint: `https://api.moonshot.ai/anthropic`
- Compatibility notes:
  Docs portal moved from platform.moonshot.ai to platform.kimi.ai (301 redirect); API host
  unchanged. Full OpenAI Chat Completions compatibility with Kimi-specific extensions:
  thinking={type,keep} must be passed via extra_body in official OpenAI SDKs; 'partial' mode is
  a field on the final assistant message ({"partial": true}), not a top-level param; max_tokens
  is deprecated in favor of max_completion_tokens; prompt_cache_key supported. Usage object
  reports cached_tokens for cache hits; with stream_options:{include_usage:true} the final chunk
  before [DONE] carries usage (intermediate chunks usage:null). Finish reasons:
  stop/length/tool_calls only. Context caching is automatic (no cache management API); a request
  only hits the prefix cache when the previous request's prompt exceeded 256 tokens.
  reasoning_content is a non-standard message/delta field (check via hasattr in the OpenAI SDK).
  moonshot-v1 series sunsets 2026-08-31; original kimi-k2 series was discontinued 2026-05-25.
- Reasoning:
  kimi-k3: reasoning always enabled, controlled by top-level reasoning_effort
  ('low'/'high'/'max', default 'max'). kimi-k2.7-code: thinking always on — requests that
  disable it get 400 'invalid thinking'. kimi-k2.6/k2.5: thinking={type:'enabled'|'disabled'}
  via extra_body; thinking.keep='all' preserves reasoning across turns (k2.7-code preserves
  automatically; k2.5 lacks Preserved Thinking). CoT returned in reasoning_content; in streaming
  it always arrives before content. Reasoning tokens count against max_tokens and are billed as
  output tokens.
- Sources (verified 2026-08-07):
  - https://platform.kimi.ai/docs/api/overview.md
  - https://platform.kimi.ai/docs/api/chat.md
  - https://platform.kimi.ai/docs/pricing/chat
  - https://platform.kimi.ai/docs/pricing/chat-k3.md
  - https://platform.kimi.ai/docs/pricing/chat-k27-code.md
  - https://platform.kimi.ai/docs/pricing/chat-k26.md

## z-ai — Z.ai (Zhipu GLM)

- Base URL: `https://api.z.ai/api/paas/v4`
- Auth: Authorization: Bearer <key> (JWT tokens also accepted as an alternative; Anthropic endpoint uses the Z.ai key via ANTHROPIC_AUTH_TOKEN)
- `GET /models`: not documented
- Anthropic-compatible endpoint: `https://api.z.ai/api/anthropic`
- Compatibility notes:
  Works with the OpenAI SDK against https://api.z.ai/api/paas/v4/ but docs admit 'in some
  scenarios there are still differences'. No GET /models endpoint is documented
  (models_endpoint=false on that basis). temperature range is [0.0, 1.0] (not OpenAI's 0-2;
  temperature=0 / do_sample=False semantics don't apply to OpenAI-style calls); top_p range
  [0.01, 1.0]; max_tokens caps at 131,072. thinking={type} must go through extra_body in the
  OpenAI SDK; streaming adds delta.reasoning_content chunks. Usage reports cache hits as
  prompt_tokens_details.cached_tokens. Extra finish reasons beyond stop/length/tool_calls:
  sensitive, model_context_window_exceeded, network_error. tools array accepts non-OpenAI types
  retrieval and web_search in addition to function.
- Reasoning:
  thinking={type:'enabled'|'disabled'}, default enabled (model auto-decides), except GLM-4.7 and
  GLM-4.5V which force thinking; clear_thinking boolean also available. reasoning_effort
  supported from GLM-5.2 onward: max/xhigh/high/medium/low/minimal/none ('max' recommended for
  deep reasoning). CoT is returned in reasoning_content separate from content and streams before
  the answer. Docs say the thinking process 'will consume extra tokens' billed within standard
  token counts (no separate reasoning-token usage field documented). Deep Thinking supported on
  GLM-5.2/5.1/5/5-Turbo/5V-Turbo/4.7/4.6/4.5 series.
- Sources (verified 2026-08-07):
  - https://docs.z.ai/guides/overview/pricing
  - https://docs.z.ai/guides/develop/http/introduction
  - https://docs.z.ai/guides/develop/openai/python.md
  - https://docs.z.ai/api-reference/llm/chat-completion.md
  - https://docs.z.ai/guides/capabilities/thinking.md
  - https://docs.z.ai/guides/llm/glm-5

## dashscope — Alibaba Qwen (Model Studio / DashScope International)

- Base URL: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
- Auth: Authorization: Bearer <DASHSCOPE_API_KEY> (Anthropic-compat endpoint also accepts x-api-key: <DASHSCOPE_API_KEY>)
- `GET /models`: not documented
- Anthropic-compatible endpoint: `https://dashscope-intl.aliyuncs.com/apps/anthropic`
- Compatibility notes:
  Singapore/international OpenAI-compatible base is https://dashscope-
  intl.aliyuncs.com/compatible-mode/v1 (POST /chat/completions); newer workspace-scoped domains
  https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1 and a US endpoint
  https://dashscope-us.aliyuncs.com/compatible-mode/v1 also exist, and API keys are region-
  specific. GET /models is not documented for compatible-mode, and the Anthropic-compat endpoint
  explicitly returns 404 for /v1/models (Messages API only) — clients must hardcode model ids.
  Streaming usage requires stream_options={'include_usage': true}. Non-standard params
  enable_thinking/thinking_budget must be sent via extra_body with the OpenAI SDK. Compat doc
  notes tool restrictions: n forces to 1 when tools are set, and one doc note states tools
  cannot be combined with stream=true (verify per model). Cached tokens are reported in
  usage.prompt_tokens_details.cached_tokens (Anthropic-compat reports
  usage.cache_read_input_tokens, counted separately from input rather than included). Pricing is
  tiered by total input tokens per request: the whole request bills at the tier its input-token
  count lands in.
- Reasoning:
  Hybrid-thinking models toggle reasoning per request with enable_thinking (bool, extra_body in
  OpenAI SDK); thinking_budget caps reasoning tokens (model stops reasoning and answers when
  hit). Defaults vary: qwen3.7-max/qwen3.5 series default thinking ON; qwen3-max and qwen-plus
  default OFF; qwq-plus/deepseek-r1 are thinking-only. Reasoning text is returned in a separate
  reasoning_content field (streaming and non-streaming), final answer in content. On the
  Anthropic-compat endpoint use thinking:{type:'enabled', budget_tokens:N} (reasoning_effort is
  NOT supported); reasoning returns as thinking-type content blocks. Billing: thinking content
  is billed per output token; docs state some models price thinking vs non-thinking output
  differently (per-model thinking rates were not shown on the pricing page fetched, so treat
  differing thinking output rates as model-specific and verify per model). Context cache
  billing: implicit cache hits = 20% of input price; explicit cache creation = 125%; explicit
  cache hits = 10%.
- Sources (verified 2026-08-07):
  - https://www.alibabacloud.com/help/en/model-studio/model-pricing
  - https://www.alibabacloud.com/help/en/model-studio/models
  - https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope
  - https://www.alibabacloud.com/help/en/model-studio/deep-thinking
  - https://www.alibabacloud.com/help/en/model-studio/anthropic-api-messages
  - https://www.alibabacloud.com/help/en/model-studio/context-cache

## minimax — MiniMax (platform.minimax.io international)

- Base URL: `https://api.minimax.io/v1`
- Auth: Authorization: Bearer <MINIMAX_API_KEY> (JWT-format key from Account Management > API Keys)
- `GET /models`: not documented
- Anthropic-compatible endpoint: `https://api.minimax.io/anthropic`
- Compatibility notes:
  OpenAI-compatible endpoint POST https://api.minimax.io/v1/chat/completions (a legacy native
  path /v1/text/chatcompletion_v2 also exists). GET /models is not documented. Ignored params:
  presence_penalty, frequency_penalty, logit_bias; deprecated function_call unsupported (use
  tools); n must be 1; temperature strictly validated to (0,2] — out-of-range errors rather than
  clamps. Uses max_completion_tokens (M3: recommended 131K, max 512K; M2.x: recommended 64K, max
  200K). stream_options.include_usage supported; usage = {total_tokens, prompt_tokens,
  completion_tokens, prompt_tokens_details.cached_tokens}. By default reasoning is embedded in
  content inside <think>...</think> tags which MUST be preserved in multi-turn history; set
  reasoning_split=true to get separate reasoning_content + reasoning_details fields instead.
  Extra response fields: input_sensitive/output_sensitive content-policy flags and a base_resp
  {status_code, status_msg} error envelope (0=success, 1002=rate limit, 1004=auth failed,
  1008=insufficient balance, 1039=token limit, 2013=parameter error) — errors can arrive with
  HTTP 200 and nonzero base_resp.status_code. service_tier: 'standard' | 'priority' (priority
  billed at 1.5x). M3 accepts image/video content parts natively; M2.x is text+tool-calls only.
- Reasoning:
  Controlled by a thinking object: {type: 'disabled' | 'adaptive'}. M2.x-series models cannot
  disable thinking; for MiniMax-M3 the Anthropic-compat doc says thinking defaults off and is
  enabled with {type:'adaptive'}, while the OpenAI-compat reference describes 'adaptive' as the
  default — treat the default as model/endpoint-dependent and set it explicitly. Reasoning is
  emitted in-band as <think> tags in content (counted as completion output tokens) unless
  reasoning_split=true, which yields reasoning_content plus a structured reasoning_details array
  [{type:'reasoning.text', id, format:'MiniMax-response-v1', index, text}]. On the Anthropic-
  compat endpoint thinking arrives as Anthropic-style thinking content blocks that must be
  passed back in multi-turn tool-use conversations. No separate thinking token price is
  documented; priority tier multiplies all rates 1.5x.
- Sources (verified 2026-08-07):
  - https://platform.minimax.io/docs/guides/pricing-paygo
  - https://platform.minimax.io/docs/pricing/overview
  - https://platform.minimax.io/docs/api-reference/text-chat-openai
  - https://platform.minimax.io/docs/api-reference/text-chat
  - https://platform.minimax.io/docs/api-reference/text-anthropic-api
  - https://platform.minimax.io/docs/api-reference/text-openai-api

## ai21 — AI21 Labs (AI21 Studio)

- Base URL: `https://api.ai21.com/studio/v1`
- Auth: Authorization: Bearer <AI21_API_KEY>
- `GET /models`: not documented
- Compatibility notes:
  OpenAI-style shape (POST /chat/completions with messages/choices/streaming deltas, terminating
  with data: [DONE], usage in the final SSE chunk) but NOT a drop-in OpenAI base URL — path is
  /studio/v1/chat/completions and no GET /models listing endpoint is documented. Deviations:
  max_tokens capped at 4096; temperature default 0.4 (range 0.0-2.0); top_p default 1.0; n
  supports 1-16 but n>1 is incompatible with temperature=0; stream requires n=1 and is
  incompatible with tools (tools require non-streaming); response_format {'type':'json_object'}
  for JSON mode; extra non-OpenAI 'documents' parameter (content + metadata key-value pairs) for
  RAG-style grounding; ~256K-token cap on the messages list. AnyInfer surfaces the two stated
  defaults (temperature 0.4, top_p 1.0) as `ModelCapabilities.default_temperature` /
  `default_top_p` at `catalog` provenance — a documented fact, not a probe; re-check them on
  the next drift run for this preset. Model aliases float: docs advise
  dated versions — jamba-large currently -> jamba-large-1.7-2025-07 and jamba-mini -> jamba-
  mini-2-2026-01. No Anthropic-compatible endpoint documented.
- Reasoning:
  No thinking/reasoning-mode parameters are documented for the hosted Jamba chat API (no
  reasoning_content field, no thinking budget); reasoning is not separately exposed or billed.
  AI21's Jamba Reasoning 3B is an open-weights (Apache 2.0) model intended for self-deployment
  (vLLM/llama.cpp/LM Studio) and has no published hosted per-token price on the AI21 pricing
  page.
- Sources (verified 2026-08-07):
  - https://docs.ai21.com/reference/jamba-1-6-api-ref
  - https://docs.ai21.com/docs/usage-cost
  - https://www.ai21.com/pricing
  - https://docs.ai21.com/reference/introduction
  - https://docs.ai21.com/docs/vllm

## huggingface — Hugging Face Inference Providers

- Base URL: `https://router.huggingface.co/v1`
- Auth: Authorization: Bearer <HF_TOKEN> (fine-grained token with 'Make calls to Inference Providers' permission)
- `GET /models`: yes
- Compatibility notes:
  Drop-in replacement for OpenAI chat completions only — no /completions, /embeddings, /audio
  etc. on the router's OpenAI surface. Exact HTTP behavior can vary by selected upstream
  provider since the router proxies to providers with their own API requirements. Model naming
  deviates from OpenAI (HF repo ids + :provider/:policy suffixes). Docs do not publish a router-
  level list of rejected params; upstream provider capabilities govern. Billing: no HF markup —
  provider rates passed through; monthly included credits: free accounts $0.10 (subject to
  change), PRO $2.00, Team/Enterprise $2.00 per seat (pooled); pay-as-you-go past credits
  requires purchasing credits. Custom provider keys (set in HF settings) route the same code
  path but bill directly on the provider account and get no HF credits. hf-inference provider
  bills compute-time x hardware price rather than per token.
- Reasoning:
  No router-level reasoning controls are documented; reasoning behavior/billing is that of the
  underlying model and provider (e.g. deepseek-ai/DeepSeek-R1 served by novita etc.). Thinking
  token pricing follows the upstream provider's per-token rates passed through without markup.
- Sources (verified 2026-08-07):
  - https://huggingface.co/docs/inference-providers/index
  - https://huggingface.co/docs/inference-providers/pricing

## nvidia — NVIDIA NIM (build.nvidia.com / self-hosted)

- Base URL: `https://integrate.api.nvidia.com/v1`
- Auth: Authorization: Bearer <nvapi-...> (NVIDIA_API_KEY from build.nvidia.com Settings > API keys; distinct from NGC personal keys). Self-hosted NIM containers require no auth header by default.
- `GET /models`: yes
- Compatibility notes:
  API follows the OpenAI spec as implemented by vLLM's OpenAI-compatible server — NVIDIA's API
  reference defers to vLLM docs for full request/response schemas, so vLLM-specific parameter
  support/limits apply rather than exact OpenAI parity. No documented deviations list on the
  pages loaded; usage reporting and stream framing follow vLLM/OpenAI conventions. Hosted
  catalog is credit-metered rather than token-priced: NVIDIA API Trial ToS says trial credits
  are deducted per usage/API access instance; free credits at signup, and production use
  requires an NVIDIA AI Enterprise subscription (90-day free license available) or serving via a
  partner — NVIDIA publishes NO per-token USD prices for integrate.api.nvidia.com, hence the
  empty pricing list. Developer Program members also get free downloadable NIMs for up to two
  nodes/16 GPUs (self-hosted = you pay infra, not tokens).
- Reasoning:
  No unified reasoning parameter is documented for the NIM surface on the pages loaded;
  reasoning exposure is model-specific (vLLM backend), and there is no separate reasoning
  billing since hosted usage is credit-based and self-hosted usage is unmetered.
- Sources (verified 2026-08-07):
  - https://docs.api.nvidia.com/nim/reference/llm-apis
  - https://docs.nvidia.com/nim/large-language-models/1.12.0/api-reference.html
  - https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html
  - https://docs.nvidia.com/nim/large-language-models/2.0.6/reference/architecture.html
  - https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf
  - https://developer.nvidia.com/blog/access-to-nvidia-nim-now-available-free-to-developer-program-members/

## vercel-ai-gateway — Vercel AI Gateway

- Base URL: `https://ai-gateway.vercel.sh/v1`
- Auth: Authorization: Bearer <AI Gateway API key or Vercel OIDC token> (API key takes precedence over OIDC even if invalid). Anthropic Messages surface additionally accepts x-api-key: <key>. Claude Code conf
- `GET /models`: yes
- Anthropic-compatible endpoint: `https://ai-gateway.vercel.sh`
- Compatibility notes:
  Model ids are creator/model-name (e.g. anthropic/claude-opus-5, openai/gpt-5.6-sol,
  openai/gpt-oss-120b). GET /models and GET /models/{model} return OpenAI-shaped lists; POST
  /embeddings supported; OpenAI Responses API surface also available. Nonstandard extensions:
  top-level `reasoning` object on chat completions ({enabled, effort:
  none|minimal|low|medium|high|xhigh, max_tokens, exclude}; effort and max_tokens mutually
  exclusive); responses add message.reasoning plus a structured reasoning_details array (types
  reasoning.text/reasoning.encrypted/reasoning.summary with format 'openai-
  responses-v1'|'anthropic-claude-v1'); streaming adds delta.reasoning and
  delta.reasoning_details. Provider routing via top-level providerOptions.gateway {order, only,
  sort: 'cost'|'ttft'|'tps', caching: 'auto', byok: {provider: [{apiKey}]}}. Generation id is
  the response `id` field and is injected into the first content chunk of streams; also GET
  /v1/credits and GET /v1/generation on the REST API for spend/usage lookup. Errors are OpenAI-
  shaped on /v1 and Anthropic-shaped ({type:'error',...}) on the Messages surface. Anthropic
  surface: POST /v1/messages and /v1/messages/count_tokens; cache_control passed through to
  Anthropic/Vertex/Bedrock Anthropic models. Known gap: for Claude Opus 4.7+/Claude 5 on the
  Chat Completions surface, reasoning.effort yields no reasoning tokens and reasoning.max_tokens
  is rejected with 400 (adaptive thinking uses Anthropic output_config which chat-completions
  cannot reach) — use the Anthropic Messages surface for those models.
- Reasoning:
  Controlled by the gateway-normalized `reasoning` object (any provider), mapped to each
  provider's native config (OpenAI reasoningEffort/reasoningSummary, Anthropic thinking budget,
  Google thinkingConfig, Groq/xAI equivalents). Reasoning text returned in message.reasoning +
  reasoning_details; streamed via delta.reasoning;
  usage.completion_tokens_details.reasoning_tokens reported. For models without native reasoning
  output the gateway extracts <think> tags automatically. On the Anthropic surface, `thinking`
  (and usage cache_creation_input_tokens/cache_read_input_tokens) pass through unchanged.
  Billing: tokens billed at the underlying provider's own prices with zero markup (pass-
  through), including BYOK.
- Sources (verified 2026-08-07):
  - https://vercel.com/docs/ai-gateway
  - https://vercel.com/docs/ai-gateway/sdks-and-apis/openai-chat-completions
  - https://vercel.com/docs/ai-gateway/sdks-and-apis/openai-chat-completions/reasoning
  - https://vercel.com/docs/ai-gateway/sdks-and-apis/anthropic-messages-api
  - https://vercel.com/docs/ai-gateway/models-and-providers/provider-options
  - https://vercel.com/docs/ai-gateway/observability-and-spend/usage

## cloudflare-workers-ai — Cloudflare Workers AI

- Base URL: `https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1`
- Auth: Authorization: Bearer <Cloudflare API token>. For the AI Gateway REST API the token needs Account > Workers AI > Read permission (tokens with only AI Gateway permission get 401); Workers AI requests t
- `GET /models`: not documented
- Anthropic-compatible endpoint: `https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/messages (AI Gateway REST API; third-party author/model ids only — @cf/ Workers AI models do NOT support the Anthropic schema)`
- Compatibility notes:
  Workers AI OpenAI-compat surface documents only POST /v1/chat/completions and POST
  /v1/embeddings (no GET /models documented). Model ids are @cf/author/model (e.g.
  @cf/meta/llama-3.1-8b-instruct, @cf/openai/gpt-oss-120b, @cf/baai/bge-large-en-v1.5).
  Streaming via "stream": true. The newer AI Gateway REST API at .../accounts/{account_id}/ai/*
  adds POST /ai/run (universal), /ai/v1/chat/completions (OpenAI), /ai/v1/responses (OpenAI
  Responses; only for Workers AI models that support it, e.g. GPT-OSS), /ai/v1/messages
  (Anthropic) — third-party models use author/model ids and Unified Billing prepaid credits,
  Workers AI models keep @cf/ ids and Workers AI billing. Per-request behavior via cf-aig-*
  headers (cf-aig-skip-cache, cf-aig-cache-ttl, cf-aig-max-attempts). Separate AI Gateway
  provider-proxy pattern:
  https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/{provider} preserves each
  upstream provider's native schema (OpenAI, Anthropic, Google AI Studio, Workers AI, Bedrock,
  Azure OpenAI); a Workers binding env.AI.gateway("name").getUrl("openai") returns that URL.
- Reasoning:
  No documented reasoning-token controls or separate reasoning deltas on the Workers AI OpenAI-
  compat surface. GPT-OSS models are exposed through the Responses API endpoint
  (/ai/v1/responses) on the AI Gateway REST API. Billing is per-token as published but metered
  in 'neurons' on the backend ($0.011 per 1,000 neurons after 10,000 free neurons/day).
- Sources (verified 2026-08-07):
  - https://developers.cloudflare.com/workers-ai/
  - https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/
  - https://developers.cloudflare.com/workers-ai/platform/pricing/
  - https://developers.cloudflare.com/ai-gateway/usage/rest-api/
  - https://developers.cloudflare.com/workers-ai/llms.txt

## litellm — LiteLLM Proxy

- Base URL: `http://<your-proxy-host>:4000 (self-hosted; default 0.0.0.0:4000, fully configurable)`
- Auth: Authorization: Bearer sk-<virtual key> (proxy-issued virtual keys; master key for admin endpoints). The /v1/messages surface uses x-api-key: <key>.
- `GET /models`: yes
- Anthropic-compatible endpoint: `http://<your-proxy-host>:4000/v1/messages (Anthropic Messages format; auth via x-api-key header plus anthropic-version: 2023-06-01; works across all LiteLLM-supported providers including OpenAI, Bedrock, Vertex, Gemini, Azure)`
- Compatibility notes:
  Self-hosted OpenAI-compatible gateway, no hosted pricing (costs are whatever the upstream
  providers charge; the proxy tracks spend per key). Endpoints: /chat/completions, /completions,
  /embeddings, /image/generations, /moderations, /audio/transcriptions, /audio/speech,
  /assistants, /batches, /fine_tuning, plus Azure-format and Vertex passthrough and Anthropic
  /v1/messages. Input/output/exceptions are normalized to OpenAI format for all providers.
  Quirks: unsupported provider params can be silently stripped with --drop_params; extra
  metadata/tags passed via extra_body={"metadata": {..., "tags": [...]}}; comma-separated model
  field ("llama3,gpt-3.5-turbo") fans one request out to multiple models and returns a list.
  Model listing: GET /model/info (master key) returns the full model list with provider mappings
  and token costs (API keys masked); the OpenAI-style listing surface is in the proxy Swagger.
- Reasoning:
  On /v1/messages, Anthropic-style `thinking` config is supported (thinking budget minimum 1024
  tokens; temperature restricted to 0<t<1 on that surface; max request text 5,000,000
  characters); responses mirror Anthropic content blocks including thinking blocks and cache
  usage metrics. Reasoning billing is entirely the upstream provider's — LiteLLM only
  meters/attributes it to virtual keys.
- Sources (verified 2026-08-07):
  - https://docs.litellm.ai/docs/proxy/user_keys
  - https://docs.litellm.ai/docs/anthropic_unified
  - https://docs.litellm.ai/docs/proxy/model_management

## vllm — vLLM (OpenAI-compatible server)

- Base URL: `http://localhost:8000/v1`
- Auth: Authorization: Bearer <key> — only enforced if server started with --api-key (multiple keys accepted for rotation) or VLLM_API_KEY env var. Caveat: auth is enforced only on /v1-prefixed (and /v2, /inf
- `GET /models`: yes
- Compatibility notes:
  Start: `vllm serve <model>`; defaults host localhost, port 8000 (--host/--port; note
  VLLM_PORT/VLLM_HOST_IP are internal-use and do NOT set the API port). Serves one model at a
  time. Endpoints: /v1/models, /v1/completions, /v1/chat/completions,
  /v1/chat/completions/batch, /v1/embeddings, /v1/responses and /v1/responses/{response_id},
  /v1/audio/transcriptions, /v1/audio/translations, /tokenize, /detokenize, /health, /metrics
  (Prometheus). Documented deviations: Completions API `suffix` parameter is not supported; Chat
  API `user` parameter is ignored; `parallel_tool_calls` controls single vs multiple tool calls
  (default true). Chat models need a chat template (override with --chat-template
  ./template.jinja, --chat-template-content-format string|openai). Extra params go via
  extra_body: sampling extras and structured outputs. Structured outputs:
  guided_json/guided_regex/guided_choice/guided_grammar were DEPRECATED in v0.12.0 in favor of
  extra_body={"structured_outputs": {"json"|"regex"|"choice"|"grammar"|"structural_tag": ...}};
  response_format {type:"json_schema"} is also supported and structured outputs are on by
  default in the server. Config file support (YAML) with CLI > config > defaults precedence.
  VLLM_SERVER_DEV_MODE=1 adds dev endpoints (not for production).
- Reasoning:
  Local — no billing. Enable with --reasoning-parser <name> (e.g. deepseek_r1, qwen3; parsers
  exist for DeepSeek R1, Qwen3, GLM-4.5, Granite 3.2, Command A Reasoning, etc.). Reasoning is
  exposed as choices[0].message.reasoning (non-streaming) and choices[0].delta.reasoning
  (streaming); the older field name reasoning_content is deprecated. Tool calls are parsed only
  from content, never from reasoning. Reasoning can coexist with structured outputs for
  compatible parsers.
- Sources (verified 2026-08-07):
  - https://docs.vllm.ai/en/latest/serving/online_serving/
  - https://docs.vllm.ai/en/latest/features/structured_outputs.html
  - https://docs.vllm.ai/en/latest/features/reasoning_outputs.html
  - https://docs.vllm.ai/en/stable/getting_started/quickstart/
  - https://docs.vllm.ai/en/stable/cli/serve/
  - https://docs.vllm.ai/en/stable/usage/security/

## sglang — SGLang

- Base URL: `http://localhost:30000/v1`
- Auth: Authorization: Bearer <key> — only if server launched with --api-key; without it, clients pass any placeholder (docs show api_key="None"). Anthropic-compat endpoint likewise accepts a dummy ANTHROPIC_
- `GET /models`: yes
- Anthropic-compatible endpoint: `http://localhost:30000`
- Compatibility notes:
  Launch: `sglang serve --model-path <model>` (recommended entrypoint; `python -m
  sglang.launch_server` still supported); conventional default port 30000 (--port), YAML config
  via --config with CLI overriding. OpenAI-compat endpoints: /v1/chat/completions,
  /v1/completions, /v1/embeddings, /v1/models (vision supported on chat). Extra parameters
  beyond OpenAI passed via extra_body: top_k, min_p, min_tokens, regex, ebnf, json_schema,
  separate_reasoning, stream_reasoning, lora_path. Swagger UI at /docs, ReDoc at /redoc, spec at
  /openapi.json. Anthropic-compatible /v1/messages is served on every server (documented Claude
  Code integration via ANTHROPIC_BASE_URL=http://127.0.0.1:30000); the model field is NOT
  validated server-side (any name accepted), and a "[1m]" model-name suffix is a client-side
  hint for Claude Code's 1M-context beta. Server flags --reasoning-parser and --tool-call-parser
  select parsing for reasoning/tool-call output (e.g. --reasoning-parser glm45 --tool-call-
  parser glm47).
- Reasoning:
  Local — no billing. Server-side: --reasoning-parser <name> parses model thinking output.
  Request-side extras via extra_body: separate_reasoning (split reasoning from content) and
  stream_reasoning (stream reasoning deltas).
- Sources (verified 2026-08-07):
  - https://docs.sglang.io/basic_usage/openai_api.html
  - https://docs.sglang.io/docs/basic_usage/openai_api
  - https://docs.sglang.io/docs/basic_usage/native_api
  - https://docs.sglang.ai/advanced_features/server_arguments.html
  - https://docs.sglang.io/advanced_features/router.html
  - https://docs.sglang.io/cookbook/autoregressive/GLM/GLM-5.2

## koboldcpp — KoboldCpp

- Base URL: `http://localhost:5001/v1`
- Auth: Authorization: Bearer <password> — only if launched with --password; otherwise no auth (any API key string accepted / not validated).
- `GET /models`: yes
- Compatibility notes:
  Default port 5001 (--port to change); on startup it exposes the native Kobold API at /api/ and
  the OpenAI-compatible API at /v1/ on the SAME port. OpenAI-compat endpoints:
  /v1/chat/completions, /v1/completions, /v1/models, /v1/embeddings (Nomic Embed/BGE/GTE/E5
  GGUF), /v1/audio/transcriptions (Whisper). Accepts non-OpenAI sampler extensions in the
  request body: min_p, top_a, dry_multiplier, xtc_probability, xtc_threshold, logit_bias and
  other KoboldCpp samplers. Also serves Ollama-compatible endpoints (can be run on port 11434
  for Ollama-tool compatibility) and Stable Diffusion image-generation endpoints on the same
  port.
- Reasoning:
  Local — no billing. No dedicated reasoning/thinking API surface documented in the official
  wiki.
- Sources (verified 2026-08-07):
  - https://github.com/LostRuins/koboldcpp/wiki

## jan — Jan

- Base URL: `http://127.0.0.1:1337/v1`
- Auth: Authorization: Bearer <key> for OpenAI-compat endpoints; x-api-key: <key> for the Anthropic-compat /v1/messages endpoint. The key is an optional user-set secret (Settings > Local API Server); leaving 
- `GET /models`: yes
- Anthropic-compatible endpoint: `http://127.0.0.1:1337`
- Compatibility notes:
  Desktop app server (Settings > Local API Server > Start Server) listens at
  http://127.0.0.1:1337 with /v1 as the default API prefix; host binding 127.0.0.1 by default
  (0.0.0.0 for LAN) plus a trusted-hosts allowlist and a configurable response timeout.
  Endpoints: GET /v1/models; POST /v1/chat/completions (streaming, tool calling, multi-turn);
  POST /v1/messages (Anthropic-compatible — Jan auto-translates requests to its internal
  format). OpenAI Responses API (/v1/responses) is documented as "coming soon" (not yet
  available). Backend is llama.cpp. Separately, the Jan CLI can serve a model at
  http://localhost:6767/v1 (auto-detects LlamaCPP or MLX).
- Reasoning:
  Local — no billing. No dedicated reasoning/thinking controls documented for the local API
  server.
- Sources (verified 2026-08-07):
  - https://www.jan.ai/docs/desktop/api-server
  - https://www.jan.ai/docs/desktop/api-preference
  - https://www.jan.ai/docs/desktop/cli

## gpt4all — GPT4All

- Base URL: `http://localhost:4891/v1`
- Auth: None documented (no authentication mechanism in the official API server docs).
- `GET /models`: yes
- Compatibility notes:
  Enable via GPT4All desktop app: Settings > Application > Advanced > "Enable Local API Server";
  port defaults to 4891, configurable via the "API Server Port" setting. HTTP only (no HTTPS)
  and listens on IPv4 localhost only (not IPv6 ::1). Endpoints: GET /v1/models, GET
  /v1/models/<name>, POST /v1/completions, POST /v1/chat/completions — a minimal surface (no
  embeddings endpoint, streaming not documented). Documented params in examples: model,
  messages, max_tokens, temperature. LocalDocs integration: when a LocalDocs collection is
  active (configured in the UI only), retrieved references are injected and returned as
  response["choices"][0]["references"] with text, author, date, page (PDFs only), and title
  fields — a non-OpenAI response extension adapters must tolerate.
- Reasoning:
  Local — no billing. No reasoning/thinking API surface documented.
- Sources (verified 2026-08-07):
  - https://docs.gpt4all.io/gpt4all_api_server/home.html

## text-generation-webui — text-generation-webui (oobabooga)

- Base URL: `http://localhost:5000/v1`
- Auth: Authorization: Bearer <key> — only if launched with --api-key yourkey; otherwise no auth. Optional SSL via --ssl-keyfile/--ssl-certfile; --public-api creates a public Cloudflare tunnel URL (incompatib
- `GET /models`: yes
- Compatibility notes:
  Enable with --api; default port 5000 (--api-port to change). Endpoints: POST
  /v1/chat/completions (SSE streaming with "stream": true; tool/function calling returns
  finish_reason "tool_calls" with structured name/arguments), POST /v1/completions, GET
  /v1/models (lists the LOADED model only), GET /v1/models/{id}, POST /v1/embeddings
  (SentenceTransformer-backed), /v1/images/generations (b64_json only), /v1/audio/* endpoints.
  Accepts many non-OpenAI extensions in request bodies: extra samplers (top_k, min_p, mirostat,
  etc.), plus UI-specific fields mode ("chat"/"instruct"/"chat-instruct"), character,
  instruction_template, instruction_template_str. Fully offline; no logging.
- Reasoning:
  Local — no billing. No dedicated reasoning/thinking API surface documented in the wiki.
- Sources (verified 2026-08-07):
  - https://github.com/oobabooga/text-generation-webui/wiki/12-%E2%80%90-OpenAI-API

## tabbyapi — TabbyAPI

- Base URL: `http://127.0.0.1:5000/v1`
- Auth: x-api-key: <key> for inference/list endpoints; x-admin-key: <key> for admin endpoints (model load/unload); Authorization: Bearer is also supported. Keys are auto-generated into api_tokens.yml; network
- `GET /models`: yes
- Compatibility notes:
  Defaults confirmed in official config_sample.yml: network.host 127.0.0.1, network.port 5000;
  api_servers defaults to ["OAI"] with optional "Kobold" (KoboldAI-compatible API on the same
  server). OpenAI-compat endpoints: /v1/chat/completions, /v1/completions, /v1/embeddings,
  /v1/models. Quirks: /v1/models can return fake entries when model.use_dummy_models is on
  (dummy_model_names defaults to ["gpt-3.5-turbo"] for clients that expect OpenAI names);
  model.inline_model_loading allows loading a model directly from a completion request (strict
  name matching); accepts extended generation params beyond OpenAI (min_p, repetition_penalty,
  plus load-time params like cache_mode, tensor_parallel, draft-model settings). Streaming
  responses emit SSE keep-alive comment pings every sse_ping_interval seconds (default 15, 0
  disables) — adapters must ignore SSE comments. Backend is ExLlamaV3; per-model options include
  max_seq_len, cache_size (default 4096, multiple of 256), cache_mode (FP16 / quantized k,v
  bits).
- Reasoning:
  Local — no billing. No dedicated reasoning/thinking API surface documented in the wiki.
- Sources (verified 2026-08-07):
  - https://github.com/theroyallab/tabbyAPI/wiki/02.-Server-options
  - https://github.com/theroyallab/tabbyAPI/wiki/03.-Usage
  - https://raw.githubusercontent.com/theroyallab/tabbyAPI/main/config_sample.yml

## featherless — Featherless AI

- Base URL: `https://api.featherless.ai/v1`
- Auth: Authorization: Bearer <key>
- `GET /models`: yes
- Compatibility notes:
  Serverless hosting over a very large catalog (tens of thousands of Hugging Face models);
  model ids are HF repo paths and are CASE-SENSITIVE (meta-llama/Meta-Llama-3.1-8B-Instruct).
  Docs claim OpenAI compatibility ("any client program that works with OpenAI as an inference
  provider can be reconfigured with little effort") but publish NO supported/unsupported
  parameter matrix — the weakest parameter documentation of the providers added in this pass;
  treat unlisted parameters as untested rather than supported. Endpoints documented:
  /v1/chat/completions, /v1/completions, GET /v1/models, plus non-OpenAI /v1/plan,
  /v1/tokenize and /account/concurrency/stream. max_tokens is the output cap
  (max_completion_tokens not mentioned). Billing is subscription tiers metered by CONCURRENCY
  rather than tokens, so no per-token rate card exists and the bundled pricing table
  deliberately has no featherless section. FEATHERLESS_API_KEY appears only as a literal
  placeholder in sample code, not as a documented env-var convention.
- Reasoning:
  No documented control — neither reasoning_effort nor a reasoning object appears in the
  docs loaded. Reasoning behavior is whatever the selected open-weights model does natively.
- Sources (verified 2026-08-07):
  - https://featherless.ai/docs/quickstart-guide
  - https://featherless.ai/docs/api-examples-and-snippets
  - https://featherless.ai/

## parasail — Parasail

- Base URL: `https://api.parasail.io/v1`
- Auth: Authorization: Bearer <PARASAIL_API_KEY>
- `GET /models`: yes
- Compatibility notes:
  Host is api.parasail.io (.io, not .ai — some cookbook pages show .ai, a docs
  inconsistency; the API reference and serverless pages agree on .io). THREE distinct
  gateways: serverless/dedicated inference on api.parasail.io/v1, batch on
  api.saas.parasail.io/v1, and the Responses API only on api-webflux.saas.parasail.io/v1
  (where `store` must be false on every request or the gateway errors); a dedicated control
  plane lives at api.parasail.io/api/v1. Model ids carry a `parasail-` prefix (e.g.
  parasail-deepseek-r1). Both max_tokens and max_completion_tokens appear across examples —
  the parameter table documents max_tokens, so the preset sends that. top_k is a non-OpenAI
  extension requiring extra_body, where top_k=-1 means the setting is ignored. Batch is 50%
  off serverless. The published pricing page names models by DISPLAY name and does not
  publish the display-name-to-id mapping, so no parasail section was added to the bundled
  pricing table; resolve rates through GET /v1/models instead.
- Reasoning:
  No single top-level control: reasoning is model-specific and travels in extra_body
  (provider_options here). DeepSeek V3.1 uses chat_template_kwargs.thinking (boolean);
  Qwen3.5 uses chat_template_kwargs.enable_thinking (boolean); GPT-OSS accepts
  thinking_budget (int) plus reasoning_effort restricted to low/medium/high — notably NO
  `minimal`, which is why the preset clamps minimal onto low rather than passing it through.
  Documented presets: fast = budget 10/low, balanced = 25/medium, deep = 40+/high.
- Sources (verified 2026-08-07):
  - https://docs.parasail.io/parasail-docs/api-reference/chat-completions
  - https://docs.parasail.io/parasail-docs/api-reference/parameters.md
  - https://docs.parasail.io/parasail-docs/products/overview/model-specific-notes.md
  - https://docs.parasail.io/parasail-docs/billing/pricing.md
  - https://www.parasail.io/pricing

## inference-net — Inference.net

- Base URL: `https://api.inference.net/v1`
- Auth: Authorization: Bearer <INFERENCE_API_KEY>
- `GET /models`: yes
- Anthropic-compatible endpoint: `https://api.inference.net`
- Compatibility notes:
  Two model-id shapes coexist: bare serverless ids (glm-5.2, claude-haiku-4-5) and custom
  deployments spelled team/model; older docs also show a quantization-suffixed form
  (google/gemma-3-27b-instruct/bf-16). max_tokens is the documented output cap. Docs state
  the API "supports the standard OpenAI chat completions parameters" and mark nothing as
  ignored. A BYOK passthrough ("Catalyst") routes to upstream vendors through the same base
  URL using headers x-inference-provider-api-key and x-inference-provider. Batch/async
  inference and a gateway product also exist. Per-model rates are exposed only through the
  authenticated CLI (inf models list --json -> costInputPerMToken / costOutputPerMToken keyed
  by routeId such as openai:gpt-5.2-2025-12-11), not on a public pricing page, so the bundled
  table has no inference-net section.
- Reasoning:
  No documented request-side control — no reasoning_effort, no reasoning object. Docs note
  reasoning models "spend part of the token budget on reasoning before producing text, so set
  max_tokens high enough for both": the budget is implicit and governed only by max_tokens.
  On the Anthropic-compatible surface the SDK's apiKey must be set to null and the credential
  passed as authToken/auth_token, so the request carries Authorization: Bearer rather than
  x-api-key; that surface also requires max_tokens.
- Sources (verified 2026-08-07):
  - https://docs.inference.net/api/api-quickstart
  - https://docs.inference.net/api/anthropic-sdk.md
  - https://docs.inference.net/cli/models.md
  - https://inference.net/pricing

## nscale — Nscale

- Base URL: `https://inference.api.nscale.com/v1`
- Auth: Authorization: Bearer <service token> (the OpenAPI describes an "IdentityAuthorization" scheme accepting Unikorn Identity JWTs; the credential is a service token rather than a classic API key)
- `GET /models`: yes
- Compatibility notes:
  Model ids are HF-style org/model (deepseek-ai/DeepSeek-R1-Distill-Qwen-32B). Both
  max_completion_tokens and max_tokens are in the documented schema. tool_choice supports
  only 'auto' and 'none' — docs state explicitly that "'required' tool_choice option requires
  vllm>=0.8.3 and is not currently supported", so a forced-tool request cannot be expressed.
  Unlike several peers, n, frequency_penalty, logit_bias, logprobs and top_logprobs ARE in
  the schema. Docs state Nscale "doesn't enforce rate limits for serverless inference".
  Prepaid credit model, $5 minimum. GET /v1/models returns per-model pricing{input, output}
  and context_length — live rates, so no nscale section is in the bundled table; note that
  for image models pricing.output is per million PIXELS, not tokens. stream_options.
  include_usage is supported. The human-readable model catalogue page is access-code gated
  and www.nscale.com/pricing returned 404, so no example prices could be read. The env var
  NSCALE_API_KEY comes from Nscale's blog rather than the API docs — a convention, not a spec.
- Reasoning:
  A top-level reasoning_effort string IS present in the documented request schema, but the
  docs specify NO allowed value set and there is no separate reasoning object. Whether
  `minimal` is accepted could not be confirmed; the preset passes the normalized level
  through unchanged and this is flagged for the next drift check.
- Sources (verified 2026-08-07):
  - https://docs.nscale.com/api-reference/inference/create-chat-completion.md
  - https://docs.nscale.com/api-reference/models/list-models.md
  - https://docs.nscale.com/docs/ai-services/models.md
  - https://docs.nscale.com/docs/getting-started/quickstart.md
  - https://docs.nscale.com/docs/faqs/rate-limits.md

## scaleway — Scaleway Generative APIs

- Base URL: `https://api.scaleway.ai/v1`
- Auth: Authorization: Bearer <SCW_SECRET_KEY> (Scaleway's account-wide secret key, not a service-specific key)
- `GET /models`: yes
- Compatibility notes:
  The best-documented rejection list of this batch. EXPLICITLY UNSUPPORTED on chat
  completions: frequency_penalty, n, top_logprobs, logit_bias, user — note that
  presence_penalty IS supported while frequency_penalty is NOT, an easy adapter bug, and the
  reason those four are declared as ignored_parameters on the preset. Supported: messages,
  model, max_tokens, temperature (default 0.7, not OpenAI's 1), top_p, presence_penalty,
  response_format, logprobs, stop, seed, stream, tools, tool_choice. max_completion_tokens is
  NOT in the supported list. Model ids carry explicit quantization suffixes (:fp8, :int4,
  :bf16, :fp4, :awq, :nvfp4 — e.g. gpt-oss-120b:fp4) and are variously bare (glm-5.2) or
  vendor-prefixed (mistral/…, qwen/…). Models follow a formal lifecycle with Deprecation and
  EOL dates; several are EOL on serverless while remaining on Dedicated. Managed Inference is
  deployment-scoped at https://<Deployment UUID>.ifr.fr-par.scaleway.com/v1. The Responses API
  is beta. Embeddings additionally reject encoding_format and dimensions. No per-model token
  rate card is published (the pricing docs path 404s and the cost estimator is an interactive
  console tool), and billing is EUR, so no scaleway section is in the bundled table.
- Reasoning:
  No documented control: reasoning_effort appears in NEITHER the supported nor the
  unsupported list — a genuine documentation gap rather than an explicit rejection. Docs
  point to the beta Responses API for "more agentic tasks and reasoning" but specify no
  reasoning parameters for chat completions.
- Sources (verified 2026-08-07):
  - https://www.scaleway.com/en/docs/generative-apis/
  - https://github.com/scaleway/docs-content/blob/main/pages/generative-apis/api-cli/openai-compatibility.mdx
  - https://raw.githubusercontent.com/scaleway/docs-content/main/pages/generative-apis/api-cli/using-chat-api.mdx
  - https://raw.githubusercontent.com/scaleway/docs-content/main/pages/generative-apis/reference-content/supported-models.mdx
  - https://raw.githubusercontent.com/scaleway/docs-content/main/pages/generative-apis/reference-content/cost-estimator.mdx

## venice — Venice AI

- Base URL: `https://api.venice.ai/api/v1` (note the doubled /api/v1 segment)
- Auth: Authorization: Bearer <VENICE_API_KEY>
- `GET /models`: yes (auth optional; supports a ?type= filter — text, code, image, embedding, tts, asr, music, video, upscale, inpaint, all)
- Compatibility notes:
  Privacy-focused provider; documentation quality is the best of this batch. max_tokens is
  explicitly DEPRECATED in favour of max_completion_tokens ("now deprecated in favor of
  max_completion_tokens"), which is why the preset renames the field; values <= 0 are ignored.
  Explicitly ignored-for-compatibility parameters, verbatim: `user` — "This field is discarded
  on the request but is supported in the Venice API for compatibility with OpenAI clients";
  `store` — "accepted for OpenAI compatibility but is not used by Venice". Docs warn that
  "request fields not listed in this documentation may be passed through but are not validated
  or guaranteed to work". Non-OpenAI extension object venice_parameters carries character_slug,
  strip_thinking_response, disable_thinking, enable_web_search (off/on/auto),
  enable_web_scraping, enable_x_search, enable_web_citations, include_search_results_in_stream,
  return_search_results_as_documents and include_venice_system_prompt; min_temp/max_temp give
  dynamic temperature scaling. Model ids accept suffixes of the form model_id:parameter=value,
  and an `e2ee-` prefix marks end-to-end-encrypted variants. Legacy reasoning models emit
  inline <think></think> blocks in content. Billing is credit-based (100 credits = $1). No
  Anthropic-compatible endpoint: the Claude Code guide routes through the third-party
  claude-code-router proxy pointed at /api/v1/chat/completions. Several models are tiered by
  context length under the SAME id (grok-4-5 doubles above 200K; openai-gpt-55 above 272K) —
  the bundled table records the standard tier only, per its stated policy.
- Reasoning:
  Top-level reasoning_effort string, enum documented as none, minimal, low, medium, high,
  xhigh, max — `minimal` IS accepted, so all four normalized levels pass through unchanged.
- Sources (verified 2026-08-07):
  - https://docs.venice.ai/api-reference/api-spec
  - https://docs.venice.ai/api-reference/endpoint/chat/completions
  - https://docs.venice.ai/api-reference/endpoint/models/list
  - https://docs.venice.ai/overview/pricing
  - https://docs.venice.ai/overview/getting-started

## upstage — Upstage (Solar)

- Base URL: `https://api.upstage.ai/v1`
- Auth: Authorization: Bearer <key> (keys carry an `up_` prefix)
- `GET /models`: not documented
- Compatibility notes:
  The reference supplies static model alias tables rather than a listing endpoint, hence
  models_endpoint=false. /v1 is current; the legacy /v1/solar path appears in older material
  and the Agent API uses a /v2 base. max_tokens is the output cap. message.reasoning holds
  chain-of-thought and completion_tokens_details.reasoning_tokens counts within
  completion_tokens. Prompt caching is supported via a cache-key parameter and is priced
  separately (cached input is a tenth of fresh input on Pro 2/Pro 3). response_format has
  historically been restricted to certain models. Model aliases: solar-pro3, solar-pro2,
  solar-mini, syn-pro, plus versioned ids (solar-pro3-260323, solar-pro2-251215) and
  embedding-query / embedding-passage. Published prices EXCLUDE 10% VAT. The pricing page
  names models by display name ("Solar Pro 4"); the mapping to a solar-pro4 API alias is an
  inference and the alias table loaded did not include a Pro 4 entry — flagged for the next
  drift check, as is a promotional free period for Pro 4 that conflicts with its list price.
- Reasoning:
  Top-level reasoning_effort string documented as none, minimal, low, medium, high, xhigh,
  max, with the explicit warning that "not every model accepts every value" — and the
  per-model semantics genuinely differ, which is unusual enough to record in full:
  solar-pro3 omitted = off, minimal/low disable, medium/high enable with visible reasoning;
  solar-pro2 and solar-pro2-nightly behave the same but emit no visible reasoning text;
  solar-open2 reasons BY DEFAULT (omitted = on) and is disabled with none/minimal;
  solar-mini and solar-mini-nightly do not accept the parameter at all and require it to be
  omitted entirely. The preset therefore passes the level through and leaves per-model
  suitability to the caller.
- Sources (verified 2026-08-07):
  - https://console.upstage.ai/api/docs/for-agents/raw
  - https://www.upstage.ai/pricing/api

## reka — Reka AI

- Base URL: `https://api.reka.ai/v1`
- Auth: X-Api-Key: <REKA_API_KEY> for /v1/chat/completions and /v1/models (the Research endpoint documents Authorization: Bearer instead — the two surfaces disagree)
- `GET /models`: yes
- Compatibility notes:
  The auth spelling is the headline quirk and the reason this preset sets auth_header to
  x-api-key: the HTTP reference specifies X-Api-Key on chat and models, while the quickstart
  drives the same base URL with the OpenAI SDK, which necessarily sends Authorization:
  Bearer. Whether Reka accepts BOTH could not be confirmed from the documentation and is
  flagged for the next drift check; a caller needing bearer auth can override via configured
  headers. Non-standard defaults: temperature 0.4, top_p 0.95, top_k 1024. tool_choice spells
  the forced case 'tool' rather than OpenAI's 'required' (values auto/tool/none). Multimodal
  input (image, video, audio) via data URLs. max_tokens is the output cap. The legacy
  v0.docs.reka.ai API is superseded. The pricing page lists reka-core while the models page
  lists only reka-flash, reka-edge and reka-edge-2603 and notes "other models may be
  available" — the models page is likely the fresher source, so reka-core's continued
  availability is unconfirmed even though its published price is recorded.
- Reasoning:
  No reasoning_effort on chat completions. Reka Research instead exposes a nested research
  object with parallel_thinking.mode taking none/low/high — a different surface with its own
  vocabulary, and priced per 1k requests ($25 base, $35 low, $60 high) rather than per token.
  Chat models therefore declare no reasoning control.
- Sources (verified 2026-08-07):
  - https://docs.reka.ai/chat/api-reference/create.md
  - https://docs.reka.ai/chat/models.md
  - https://docs.reka.ai/chat/overview
  - https://docs.reka.ai/pricing.md
  - https://docs.reka.ai/research/api-reference/create-chat-completion.md

## nous — Nous Research (Portal)

- Base URL: `https://inference-api.nousresearch.com/v1`
- Auth: Authorization: Bearer <key> (x402 Solana USDC micropayments are also supported in beta, requiring no account or key)
- `GET /models`: not documented
- Compatibility notes:
  The official OpenAPI spec lists only /chat/completions and /completions — no models
  listing, hence models_endpoint=false. Model ids are CAPITALIZED and case-sensitive:
  Hermes-4.3-36B, Hermes-4-70B, Hermes-4-405B, all 128K context. The most dangerous default
  in this batch: max_tokens has range 1–32000 and DEFAULTS TO 100, so omitting it truncates
  output at 100 tokens rather than running to the model maximum. temperature range 0.0–2.0
  (default 1). Community reports indicate /chat/completions additionally requires a `tags`
  array containing a user= entry (e.g. "tags": ["user=myapp"]) or returns HTTP 400; this is
  ABSENT from the official OpenAPI spec, could not be verified against official docs, and is
  flagged for the next drift check — if real, it is supplied through provider_options.
  Portal's broader 300+ model catalogue is a separate OAuth-based proxy over OpenRouter,
  distinct from this first-party Hermes endpoint. No pricing appears in the OpenAPI spec and
  portal.nousresearch.com/api-docs returned HTTP 429 throughout verification, so no nous
  section was added to the bundled table rather than importing third-party aggregator figures.
- Reasoning:
  No documented control — neither reasoning_effort nor a reasoning object appears in the
  OpenAPI spec.
- Sources (verified 2026-08-07):
  - https://portal.nousresearch.com/api/openapi
  - https://hermes-agent.nousresearch.com/docs/integrations/providers

## arcee — Arcee AI

- Base URL: `https://api.arcee.ai/api/v1`
- Auth: Authorization: Bearer <key> (the chat-completion reference documents an `rcai-` key prefix; the quick-start shows a generic `api-` placeholder)
- `GET /models`: yes — but documented as returning results "according to OpenRouter provider spec", so the response shape follows OpenRouter's rather than OpenAI's
- Compatibility notes:
  Arcee publishes THREE base URLs across products and picking the wrong one is the main
  risk: the Arcee Platform at api.arcee.ai/api/v1 (used in the official first-API-call
  examples and adopted here), the Conductor auto-router at models.arcee.ai/v1 which accepts
  model="auto", and a further conductor.arcee.ai/v1 reference. Documented parameters: model
  (required), messages, timeout, temperature, top_p, n, stream, stop, max_tokens,
  presence_penalty, frequency_penalty, logit_bias, user, seed, tools, tool_choice
  (auto/none/required), logprobs, top_logprobs, plus deprecated functions/function_call.
  Model ids: trinity-large-thinking (the only model in every official example and the only
  one with a published price) and trinity-mini; the models-overview page states Trinity Mini
  and Trinity Large (Preview) are "not hosted" on the Platform. Conductor additionally
  accepts SLM names (blitz, coder, maestro, virtuoso-small, caller, spotlight) and
  third-party passthrough. Free-plan users without a payment method can invoke only Arcee
  SLMs. Conductor's own pricing table is rendered as an image and so was not machine-readable;
  only the Platform's published text rate is recorded in the bundled table.
- Reasoning:
  No documented request-side control — no reasoning_effort, no reasoning object. Responses
  DO expose choices[0].message.reasoning, so reasoning text is returned without being
  requestable.
- Sources (verified 2026-08-07):
  - https://docs.arcee.ai/api-reference/your-first-api-call
  - https://docs.arcee.ai/api-reference/chat-completion.md
  - https://docs.arcee.ai/api-reference/models.md
  - https://docs.arcee.ai/get-started/pricing.md
  - https://docs.arcee.ai/get-started/models-overview.md
  - https://docs.arcee.ai/arcee-conductor/features-and-functionality/api

## digitalocean — DigitalOcean Inference

- Base URL: `https://inference.do-ai.run/v1`
- Auth: Authorization: Bearer <MODEL_ACCESS_KEY> (keys are `sk-do-…`; a Personal Access Token is also accepted, but model-access keys are preferred because they scope per model and can be bound to a VPC)
- `GET /models`: yes
- Anthropic-compatible endpoint: `https://inference.do-ai.run/v1/messages`
- Compatibility notes:
  Naming: the live docs are under /products/inference/; the older "Gradient AI Platform" API
  path 404s, so the preset is named for the current product. Unusually for a cloud provider,
  the base URL is a FIXED global host with no account or region id embedded — the cleanest
  fit of the enterprise clouds surveyed. max_completion_tokens is the documented output cap
  on chat completions (/v1/responses uses max_output_tokens); whether legacy max_tokens is
  still accepted is unverified, so the preset sends max_completion_tokens. Model ids apply
  vendor prefixes INCONSISTENTLY — anthropic-claude-opus-5 and openai-gpt-5 are prefixed
  while llama3.3-70b-instruct, glm-5.2 and kimi-k3 are not — so ids must be read from the
  listing rather than derived. Access is tier-gated: Tier 1–2 accounts reach open-weight
  models only. A VPC-bound key used from outside that VPC returns 403. Prepaid billing;
  batch up to 50% off. Docs conflict on Anthropic extended thinking (the limits page says
  unavailable, the models page lists adaptive thinking as supported) — flagged for the next
  drift check.
- Reasoning:
  Top-level reasoning_effort accepting none, low, medium, high and `max` — an extension
  beyond OpenAI's set — or a reasoning object {effort, max_tokens}. `minimal` is NOT among
  the documented values, so the preset clamps it onto low. Reasoning output is returned in
  reasoning_content.
- Sources (verified 2026-08-07):
  - https://docs.digitalocean.com/products/inference/details/pricing/
  - https://docs.digitalocean.com/products/inference/details/models/
  - https://docs.digitalocean.com/products/inference/

## ovhcloud — OVHcloud AI Endpoints

- Base URL: `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1`
- Auth: Authorization: Bearer <OVH_AI_ENDPOINTS_ACCESS_TOKEN> (long-lived; expiry is optional and chosen by the user). Anonymous access works at a documented 2 requests/minute
- `GET /models`: yes in practice, but essentially undocumented — absent from the prose guides
- Compatibility notes:
  The unified gateway above is current and multiplexes every model; legacy per-model
  hostnames still resolve but are redundant, and OVH's /en/ and /en-gb/ locales disagree
  about which is canonical (docs mid-migration). Model ids are LOAD-BEARING and irregularly
  punctuated — Meta-Llama-3_3-70B-Instruct uses an underscore where the version dot belongs,
  while Mistral-Small-3.2-24B-Instruct-2506 keeps its dots — so ids must never be normalized.
  A virtual-model DSL is supported: mistral@latest, gpt-oss@cheapest, and constraint forms
  such as mistral@latest?context_size>100000. max_tokens is the documented output cap
  (max_completion_tokens is not documented, though the listing reports a field of that name).
  Rate limit 400 req/min authenticated; request body capped at 2 MB (10 MB for visual models).
  GET /v1/models returns non-standard pricing, context_length and max_completion_tokens
  extensions. Pricing is published in EUR on the catalogue pages but returned in USD by the
  live API and the two are not a clean FX conversion, so no ovhcloud section was added to the
  bundled table; the human-readable pricing page is JS-rendered and could not be verified.
- Reasoning:
  reasoning_effort accepting low/medium/high (the virtual-models guide adds none), so
  `minimal` is clamped onto low. Reasoning output is returned in reasoning_content. Two
  documentation defects to be aware of: a sample nests reasoning_effort INSIDE the message
  object rather than at top level, and DeepSeek-R1 is still referenced although it is no
  longer in the live catalogue.
- Sources (verified 2026-08-07):
  - https://help.ovhcloud.com/csm/en-public-cloud-ai-endpoints-getting-started
  - https://endpoints.ai.cloud.ovh.net/
  - https://help.ovhcloud.com/csm/en-public-cloud-ai-endpoints-models

## snowflake-cortex — Snowflake Cortex

- Base URL: `https://<account-identifier>.snowflakecomputing.com/api/v2/cortex/v1` (account-scoped; the user must supply it)
- Auth: Authorization: Bearer <token>. A Programmatic Access Token works as a static credential (default 15-day, maximum 365-day expiry). An optional X-Snowflake-Authorization-Token-Type header selects KEYPAIR_JWT, OAUTH, PROGRAMMATIC_ACCESS_TOKEN or WORKLOAD_IDENTITY_FEDERATION; key-pair JWTs expire hourly but are opt-in
- `GET /models`: not on the compatible base — the listing is GET /api/2.0/cortex/models, which is outside the /v1 path an OpenAI client would use, so discovery is disabled
- Anthropic-compatible endpoint: `https://<account-identifier>.snowflakecomputing.com/api/v2/cortex/v1/messages`
- Compatibility notes:
  Genuinely OpenAI-compatible — the docs state "the Chat Completions API follows the OpenAI
  specification" — and reachable with a static token, which is why it lands as a preset
  rather than a dedicated adapter. (The older proprietary /inference:complete endpoint is a
  separate surface.) max_completion_tokens is the documented cap and max_tokens is
  DEPRECATED; default 4096, maximum 131072. IGNORED parameters: n, presence_penalty,
  logprobs, stop and logit_bias — declared as ignored_parameters on the preset. Tool calling
  and image input ERROR on models outside the OpenAI and Claude families. Model ids are
  proprietary (claude-sonnet-4-5, openai-gpt-5.2, llama3.1-70b). Many models require
  cross-region inference to be enabled on the account, and callers need the
  snowflake.cortex_user role plus a permitting network policy, so model availability is
  account-dependent. Billing is in Snowflake credits published only in a Service Consumption
  Table PDF whose columns could not be extracted reliably, so no snowflake-cortex section was
  added to the bundled table; the table also carries a footnote that prices rise 50% on
  2026-09-01.
- Reasoning:
  Two spellings by model family: Claude models take a reasoning object {effort, max_tokens},
  while OpenAI models take reasoning_effort with none/minimal/low/medium/high — `minimal` is
  accepted, so the preset passes levels through. reasoning_effort is IGNORED on Claude models.
- Sources (verified 2026-08-07):
  - https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql/rest-api
  - https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql/chat-completions
  - https://docs.snowflake.com/en/user-guide/programmatic-access-tokens

## databricks — Databricks Model Serving

- Base URL: `https://<workspace-host>/serving-endpoints` (workspace-scoped; the user must supply it). A newer AI Gateway surface at https://<workspace-host>/ai-gateway/mlflow/v1 is in beta
- Auth: Authorization: Bearer <token>. A static Personal Access Token works — the docs themselves pass one as an OpenAI-client api_key — while OAuth M2M is recommended for production but not required
- `GET /models`: no OpenAI-style listing; only the native GET /api/2.0/serving-endpoints, which returns a different shape, so discovery is disabled
- Compatibility notes:
  Docs are mid-migration between the legacy serving-endpoints surface and the beta AI Gateway
  one, and the model-id format is tied to whichever is chosen: databricks-claude-sonnet-4-5
  on the former, system.ai.claude-sonnet-4-5 on the latter. Note that
  /serving-endpoints/{name}/invocations is the NATIVE REST path, not the OpenAI base URL.
  max_tokens is the documented cap (max_completion_tokens is absent from the chat spec).
  REJECTED with HTTP 400: background, store and conversation; additionally Claude Sonnet 5
  rejects temperature, top_p and top_k outright. n is available only on provisioned
  throughput, and service_tier accepts only default/priority. A notable streaming deviation:
  usage is returned in EVERY stream chunk rather than only the final one. Billing is in DBUs
  with no published USD conversion on the pricing page (e.g. GPT OSS 120B at 2.143/8.571 DBU
  per million input/output tokens), so no databricks section was added to the bundled table.
- Reasoning:
  reasoning_effort accepting minimal/low/medium/high on models such as gpt-oss, so all four
  normalized levels pass through unchanged; Claude and Gemini models instead take an
  Anthropic-style thinking object {"type": "enabled", "budget_tokens": N} supplied through
  provider_options.
- Sources (verified 2026-08-07):
  - https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/api-reference
  - https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/
  - https://www.databricks.com/product/pricing/foundation-model-serving

## oci-genai — Oracle OCI Generative AI

- Base URL: `https://inference.generativeai.<region>.oci.oraclecloud.com/openai/v1` (region-templated; the user must supply it)
- Auth: Authorization: Bearer <sk-…>. OCI Generative AI API keys are service-specific opaque secrets, explicitly distinct from IAM key-pairs; IAM request signing remains the production-recommended path and is mandatory for the native API
- `GET /models`: not verified on the compatible surface — the control-plane listing GET /20231130/models lives on a different host and requires a compartmentId, so discovery is disabled
- Compatibility notes:
  Oracle now ships a first-party OpenAI-compatible endpoint accepting a static key, which is
  what makes a preset viable; request signing is no longer the only path, and the proprietary
  /20231130/actions/chat endpoint continues in parallel. A second template
  (.../20231130/actions/v1) appears on the API-keys page and whether the two are true aliases
  is UNVERIFIED. Model ids are friendly strings rather than OCIDs
  (meta.llama-3.3-70b-instruct, openai.gpt-oss-120b); compartmentId and servingMode are
  needed only on the proprietary API. Both max_tokens and max_completion_tokens (and their
  camelCase spellings) exist as distinct fields. The compatible surface covers only a SUBSET
  of the catalogue — Gemini, gpt-oss and Grok — with Cohere and Meta models absent. On-demand
  serving caps a run at 4,000 tokens and Meta models are unsupported on the Responses API. A
  `project` OCID appears in the Responses sample but not in the chat-completions sample;
  whether chat requires it is the biggest open risk here and is flagged for the next drift
  check. Billing is per CHARACTER ("one transaction equals to one character") priced per
  10,000 transactions against coarse tiers rather than per model, so no oci-genai section was
  added to the bundled table; the pricing pages themselves returned 403.
- Reasoning:
  reasoning_effort accepting NONE, MINIMAL, LOW, MEDIUM, HIGH (documented in upper case),
  alongside a verbosity parameter taking LOW/MEDIUM/HIGH. `minimal` is documented, so
  normalized levels pass through unchanged.
- Sources (verified 2026-08-07):
  - https://docs.oracle.com/en-us/iaas/Content/generative-ai/use-playground-chat.htm
  - https://docs.oracle.com/en-us/iaas/api/#/en/generative-ai-inference/20231130/
  - https://docs.oracle.com/en-us/iaas/Content/generative-ai/api-keys.htm

## portkey — Portkey AI Gateway

- Base URL: `https://api.portkey.ai/v1` (hosted); self-hosted deployments of the open-source gateway supply their own
- Auth: x-portkey-api-key: <PORTKEY_API_KEY> selects and authenticates the gateway, with the upstream provider's own credential supplied either as Authorization: Bearer <token> for direct passthrough or held server-side behind a saved provider slug
- `GET /models`: not documented on the inference surface
- Compatibility notes:
  A gateway rather than a model host: it adds routing, retries, caching, fallbacks and
  observability over many upstream providers, and the OpenAI SDK reaches it purely by
  base-URL override. Selecting the upstream is done with headers rather than request-body
  fields, which is why this preset registers no default model listing and expects header
  configuration: x-portkey-provider names the provider slug (prefixed @ for a saved,
  managed provider), x-portkey-config attaches a routing config, x-portkey-custom-host
  targets a bespoke endpoint, and x-portkey-trace-id groups related requests (auto-generated
  when omitted). x-portkey-virtual-key is LEGACY, superseded by x-portkey-provider with an
  @slug. Because four documented header combinations are valid, auth is a strategy rather
  than a fixed pair, and AnyInfer passes these through as configured headers rather than
  modelling each. Pricing is the upstream provider's; Portkey meters and attributes it, so
  there is no portkey section in the bundled table.
- Reasoning:
  No gateway-level reasoning parameter is documented on the inference API; reasoning controls
  are those of the selected upstream provider and pass through in the request body.
- Sources (verified 2026-08-07):
  - https://portkey.ai/docs/api-reference/inference-api/introduction
  - https://portkey.ai/docs/api-reference/inference-api/headers

## localai — LocalAI

- Base URL: `http://127.0.0.1:8080/v1`
- Auth: none by default; optional, set through LOCALAI_API_KEY. Notably accepts THREE header spellings — Authorization: Bearer, x-api-key, and xi-api-key
- `GET /models`: yes
- Compatibility notes:
  Local — no billing. A genuine OpenAI chat-completions drop-in that serves MANY models from
  one process on a single port (8080 serves both the API and the WebUI). Model ids are the
  gallery name or the GGUF filename, e.g. llama-3.2-1b-instruct:q4_k_m or
  phi-2.Q4_K_M.gguf. Models can be installed at runtime through POST /models/apply. LocalAI
  additionally emulates the Anthropic and ElevenLabs APIs on the same server. Legacy API keys
  grant full administrative access with no role separation, so a key shared with an untrusted
  client is a privilege risk. Documentation note: the localai.io/basics/* paths are stale
  redirects; the live tree is localai.io/docs/*.
- Reasoning:
  Local — no billing. No reasoning or thinking API surface is documented; reasoning behavior
  is whatever the loaded model does natively.
- Sources (verified 2026-08-07):
  - https://localai.io/docs/getting-started/models/
  - https://localai.io/docs/features/authentication/

## llamafile — llamafile

- Base URL: `http://127.0.0.1:8080/v1`
- Auth: none; examples pass the placeholder `sk-no-key-required` / Authorization: Bearer no-key
- `GET /models`: yes (inherited from the llama.cpp server surface)
- Compatibility notes:
  Local — no billing. A single self-contained executable bundling weights and runtime, from
  the mozilla-ai project (the repository moved from Mozilla-Ocho; older paths 404). Serves
  ONE model, selected with -m at launch, and official examples report the model id as the
  literal string "LLaMA_CPP" rather than a real model name — a client that echoes the id back
  will see that constant. Recent versions default to a combined mode running the server
  alongside a terminal chat. Exposes the Anthropic Messages API in addition to OpenAI chat
  completions. Port 8080 is heavily contested by other local tools, so the host shorthand
  matters here. As with the rest of the llama.cpp family, the project makes no strong claim
  of strict OpenAI spec compliance — assume silent parameter ignoring rather than errors.
- Reasoning:
  Local — no billing. No reasoning or thinking API surface documented.
- Sources (verified 2026-08-07):
  - https://docs.mozilla.ai/llamafile/getting-started/quickstart
  - https://github.com/mozilla-ai/llamafile

## tgi — Text Generation Inference

- Base URL: `http://127.0.0.1:3000/v1`
- Auth: none by default; examples pass the placeholder api_key="-"
- `GET /models`: not documented in the Messages API reference — do not assume it exists
- Compatibility notes:
  Local — no billing. Hugging Face's production serving engine. The default port is 3000,
  NOT the 8080 a reader might assume from other engines. Serves ONE model per process, and
  every official example addresses it by the literal id "tgi" rather than the real model
  name, so the model string is effectively a constant. The Messages API — the
  OpenAI-compatible surface — requires TGI 1.4.0 or newer; a separate non-OpenAI native API
  also exists on the same server. max_tokens is the output cap. Docs claim the endpoint is
  "fully compatible with the OpenAI Chat Completion API" but publish no list of rejected
  parameters. Because the listing endpoint is undocumented, this preset disables discovery
  and reports health optimistically rather than probing a route that may not exist.
- Reasoning:
  Local — no billing. No reasoning or thinking API surface documented.
- Sources (verified 2026-08-07):
  - https://huggingface.co/docs/text-generation-inference/en/messages_api
  - https://huggingface.co/docs/text-generation-inference/en/reference/api_reference

## aphrodite — Aphrodite Engine

- Base URL: `http://127.0.0.1:2242/v1`
- Auth: none by default; a --api-key flag exists (Docker examples pass "sk-empty")
- `GET /models`: yes — lists models and LoRA adapters
- Compatibility notes:
  Local — no billing. A vLLM fork carrying substantially more sampler options, serving one
  model at a time via `aphrodite run <model>` or `aphrodite serve <model>
  --served-model-name <alias>`. The default port is 2242, deliberately differing from
  upstream vLLM's 8000 — confirmed independently by the repository README and the docs site,
  and pinned by test because it is the kind of value that silently fails. Claims "near-perfect
  feature parity" with the OpenAI protocol and additionally exposes Anthropic, pooling,
  scoring, reranking and transcription APIs; an optional KoboldAI endpoint can be launched on
  the same port with --launch-kobold-api. Extended samplers travel through provider_options.
  Caveat for the next drift check: the project appears to be undergoing an organisation
  rename, its README links out to a differently-branded docs host, and several
  aphrodite.pygmalion.chat paths 404 — treat its documentation as in flux.
- Reasoning:
  Local — no billing. No reasoning or thinking API surface documented.
- Sources (verified 2026-08-07):
  - https://github.com/aphrodite-engine/aphrodite-engine/blob/main/README.md

## mlc-llm — MLC-LLM

- Base URL: `http://127.0.0.1:8000/v1`
- Auth: none documented
- `GET /models`: yes — explicitly documented ("Get a list of models available for MLC-LLM")
- Compatibility notes:
  Local — no billing. Machine-learning-compilation serving, launched as `mlc_llm serve MODEL
  [--model-lib PATH]`; it requires a COMPILED model library, which distinguishes it from
  engines that load GGUF or safetensors directly. Documented defaults: host 127.0.0.1, port
  8000. Only two endpoints are documented — /v1/models and /v1/chat/completions — so the
  surface is narrower than most: no embeddings or completions route is promised. Documented
  request parameters: temperature, top_p, max_tokens, stream, frequency_penalty,
  presence_penalty, logprobs, seed, stop and tools. max_tokens is the output cap;
  max_completion_tokens is not mentioned.
- Reasoning:
  Local — no billing. No reasoning or thinking API surface documented.
- Sources (verified 2026-08-07):
  - https://llm.mlc.ai/docs/deploy/rest.html

## openllm — OpenLLM

- Base URL: `http://127.0.0.1:3000/v1`
- Auth: optional; a dummy value such as 'na' works locally
- `GET /models`: yes
- Compatibility notes:
  Local — no billing. BentoML's model server, launched as `openllm serve llama3.2:1b` using
  a model:version tag format. The default port is 3000 (BentoML's convention), not 8000 or
  8080. Serves one model per server process and additionally hosts a chat UI at /chat.
  OpenAI-compatible chat completions are reachable with the standard client by base-URL
  override.
- Reasoning:
  Local — no billing. No reasoning or thinking API surface documented.
- Sources (verified 2026-08-07):
  - https://github.com/bentoml/OpenLLM/blob/main/README.md

## triton — NVIDIA Triton (OpenAI frontend)

- Base URL: `http://127.0.0.1:9000/v1`
- Auth: none; examples pass api_key="EMPTY". An --openai-restricted-api flag enables custom auth headers
- `GET /models`: yes, plus non-standard POST /v1/models/{name}/load and /unload
- Compatibility notes:
  Local — no billing. The OpenAI frontend is a SEPARATE process from Triton's main server
  and listens on port 9000 — port 8000 is Triton's own KServe HTTP endpoint, so defaulting to
  8000 reaches the wrong protocol entirely. It is not enabled by a daemon flag: it is
  launched as `python3 openai_frontend/main.py --model-repository … --tokenizer … --backend
  tensorrtllm`, and an explicit --tokenizer is required. Endpoints: /v1/chat/completions,
  /v1/completions, /v1/embeddings and /v1/models. A LoRA adapter is selected by appending a
  separator and adapter name to the model string when --lora-separator is set. Streaming
  tool-call parsing is bounded by --max-tool-call-parse-bytes (default 128 KiB).
- Reasoning:
  Local — no billing. No reasoning or thinking API surface documented.
- Sources (verified 2026-08-07):
  - https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/client_guide/openai_readme.html

## Batch added 2026-08-07 (routers, regional clouds, and local engines)

Verified against live provider documentation on 2026-08-07. Two entries record an upstream
rebrand rather than a new service: GenieX is the former Nexa SDK, now published by Qualcomm with
a renamed CLI, and BytePlus ModelArk is Volcengine Ark's international edition.

### requesty — Requesty

- Base URL: `https://router.requesty.ai/v1`
- Auth: Authorization: Bearer <REQUESTY_API_KEY> (the /v1/messages Anthropic-compatible path uses x-api-key instead)
- `GET /models`: yes
- Anthropic-compatible endpoint: `https://router.requesty.ai`
- Reasoning:
reasoning_effort (string). Provider-neutral values "low"/"medium"/"high", OpenAI-specific
"xhigh", plus Requesty extensions "max"/"min"/"none"; numeric token budgets are also accepted
and are translated to Anthropic/Gemini thinking budgets. Reasoning text comes back on
message.reasoning_content for DeepSeek and Anthropic models; OpenAI models do not return
reasoning tokens.
- Compatibility notes:
Strong OpenAI compatibility. Notable deltas: (1) provider-reported cost — every non-streaming
chat completion returns usage.cost in USD (example value 0.0000935) with no opt-in param; for
streaming you must pass stream_options={"include_usage": true} to get usage/cost in the final
chunk. (2) usage is NOT returned on streaming requests by default. (3) Model ids are namespaced
provider/model (e.g. openai/gpt-4o, anthropic/claude-sonnet-4-5), and "policy/..." ids select a
routing policy rather than a concrete model. (4) Response headers x-requesty-provider,
x-requesty-cache, x-requesty-latency-ms, x-requesty-request-id expose routing decisions. (5)
Optional HTTP-Referer and X-Title headers for analytics attribution. (6) Requesty-specific
metadata is passed via extra_body under a "requesty" key. (7) Separate EU residency host
https://router.eu.requesty.ai/v1. (8) Management API lives on a different host
(https://api-v2.requesty.ai) — key/group/org endpoints under /v1/manage/*, not on the inference
host.
- Sources (verified 2026-08-07):
  - https://docs.requesty.ai/quickstart
  - https://docs.requesty.ai/api-reference/overview
  - https://docs.requesty.ai/api-reference/openapi.json
  - https://docs.requesty.ai/features/reasoning
  - https://docs.requesty.ai/features/cost-tracking
  - https://docs.requesty.ai/llms-full.txt

### martian — Martian Gateway (withmartian)

- Base URL: `https://api.withmartian.com/v1`
- Auth: Authorization: Bearer <MARTIAN_API_KEY>
- `GET /models`: yes
- Anthropic-compatible endpoint: `https://api.withmartian.com`
- Reasoning:
none documented — the Gateway docs do not specify a reasoning/thinking parameter spelling;
presumably passthrough of the upstream provider's field, but unconfirmed on official pages.
- Compatibility notes:
OpenAI-shaped POST /v1/chat/completions with namespaced model ids (documented example:
openai/gpt-4.1-nano). Docs state compatibility with both the OpenAI and Anthropic SDKs, implying
an Anthropic-compatible messages path alongside the OpenAI one, though the exact Anthropic path
is not spelled out on the public pages. Model catalog covers 200+ models and the docs note
"Prices are fetched directly from the Martian Gateway API and updated every 5 minutes",
indicating the models listing carries live per-model pricing. IMPORTANT status note: the
original per-prompt "Model Router" product (route.withmartian.com, model="router") is no longer
the supported offering — that host failed to load (TLS handshake failure) and the legacy docs at
docs.withmartian.com/martian-api describe 2023-era router positioning. The current supported
product is the Gateway.
- Sources (verified 2026-08-07):
  - https://docs.withmartian.com/gateway
  - https://gateway-docs.withmartian.com/
  - https://docs.withmartian.com/api-reference
  - https://docs.withmartian.com/api-reference/models

### helicone — Helicone AI Gateway

- Base URL: `https://ai-gateway.helicone.ai`
- Auth: Authorization: Bearer <HELICONE_API_KEY> (single Helicone key covers all upstream providers when using credits; BYOK provider keys can be stored instead)
- `GET /models`: yes
- Correction (2026-08-07 re-verification): recorded as undocumented, but the REST reference
  lists a Get Models endpoint and an unauthenticated probe of
  `https://ai-gateway.helicone.ai/v1/models` returns HTTP 200 with an OpenAI-shaped list.
  Returned ids are BARE (`claude-opus-4-1`, owned_by `anthropic`), consistent with this
  gateway's suffix-style routing rather than a vendor prefix. One further behavioral fork
  worth knowing: under credit billing the accepted request schema is narrower than OpenAI's
  (restricted to fields stable across every provider mapping), while BYOK restores the full
  schema.
  Source: https://docs.helicone.ai/llms.txt plus a live probe on 2026-08-07
- Reasoning:
none documented — passthrough to the upstream provider's own parameter.
- Compatibility notes:
OpenAI-compatible chat completions and the newer Responses API are supported; the legacy
/v1/completions API is explicitly not supported. Model routing syntax is the significant quirk
and is INVERTED relative to OpenRouter/Requesty — the provider suffix follows the model rather
than prefixing it: bare `gpt-4o-mini` lets the gateway pick any provider, `gpt-4o-mini/openai`
pins one provider, `gpt-4o-mini/azure/clm1a2b3c` targets a specific custom deployment id,
`gpt-4o-mini/azure,gpt-4o-mini/openai,gpt-4o-mini` declares an ordered fallback chain, and
`!openai,gpt-4o-mini` excludes providers. (Some Helicone examples also show OpenRouter-style
provider/model such as openai/gpt-4o-mini against the /ai path, so the accepted forms differ by
endpoint — verify against the model registry before hardcoding.) Two URL shapes: the default
unified endpoint at the root / `/ai` suffix, and named routers at /router/<router-name> which
attach a saved routing policy (latency-based P2C+PeakEWMA, weighted distribution, cost
optimization, rate limits, Redis/S3 caching). Self-hosted binary via `npx @helicone/ai-gateway`
on localhost:8080 with the same /ai and /router/<name> paths. Anthropic requests are normalized
through the OpenAI interface rather than exposed as a native /v1/messages passthrough. Gateway
credits are advertised as 0% markup / provider pass-through pricing (contrasted with
OpenRouter's 5.5%) but the credits page is a waitlist, so availability is gated; the
observability platform tiers are Hobby free (10k requests, 1GB storage), Pro $79/mo, Team
$799/mo, Enterprise custom.
- Sources (verified 2026-08-07):
  - https://docs.helicone.ai/gateway/overview
  - https://docs.helicone.ai/gateway/provider-routing
  - https://github.com/Helicone/ai-gateway
  - https://www.helicone.ai/pricing
  - https://www.helicone.ai/credits

### chutes — Chutes

- Base URL: `https://llm.chutes.ai/v1`
- Auth: Authorization: Bearer <cpk_...>
- `GET /models`: yes
- Reasoning:
No documented top-level reasoning_effort param. /v1/models advertises a "reasoning" flag in
supported_features per model; reasoning models emit thinking inline. Sampling params are
enumerated per-model in supported_sampling_parameters (temperature, top_p, top_k,
repetition_penalty, frequency_penalty, presence_penalty, stop, seed).
- Compatibility notes:
OpenAI-compatible chat/completions + embeddings. Notable deltas: (1) GET /v1/models is
UNAUTHENTICATED and returns an unusually rich catalog — dual pricing objects
(price.{input,output,input_cache_read}.{usd,tao} and
pricing.{prompt,completion,input_cache_read}, with the displayed USD numbers flat per 1M),
context_length/max_model_len,
max_output_length, input/output modalities, supported_features, supported_sampling_parameters,
quantization, chute_id, confidential_compute (TEE) flag, and root (the underlying non-TEE repo).
(2) Inline failover routing: the model field accepts "default" (saved failover pool) or a comma-
list with a metric selector, e.g. "modelA,modelB,modelC:latency". (3) X-API-Key is NOT accepted
for inference — Bearer only; unauthenticated requests fall to an anonymous rate-limit path
returning HTTP 429. (4) Prices are denominated in both USD and TAO (Bittensor). (5) Capacity
comes from community-donated compute, so sustained 429s indicate no available GPUs rather than
misconfiguration. (6) api.chutes.ai is the management plane (billing, keys, quotas) and is a
DIFFERENT host from the llm.chutes.ai inference plane. (7) Self-deployed chutes get per-
deployment subdomains: https://{slug}.chutes.ai/v1.
- Sources (protocol verified 2026-08-07; public model/pricing schema re-verified 2026-08-10):
  - https://chutes.ai/llms.txt
  - https://chutes.ai/pricing
  - https://llm.chutes.ai/v1/models
  - https://chutes.ai/docs/api-reference/pricing

### avian — Avian.io

- Base URL: `https://api.avian.io/v1`
- Auth: Authorization: Bearer avian-<API_KEY> (keys carry a literal "avian-" prefix)
- `GET /models`: yes
- Reasoning:
None documented as a request parameter. /v1/models exposes a per-model boolean "reasoning"
capability flag, but no documented reasoning_effort / thinking-budget knob.
- Compatibility notes:
Straightforward OpenAI Chat Completions clone: same schema, same client libraries, streaming via
stream:true, tool/function calling via the tools parameter. GET /v1/models is UNAUTHENTICATED
and returns a modestly enriched object: id, owned_by, display_name, context_length, max_output,
a boolean reasoning flag, and pricing.{input_per_million, output_per_million,
cache_read_per_million} in flat USD per 1M tokens (note the non-standard *_per_million field
naming rather than OpenRouter's per-token strings). Small curated catalog — 11 text models at
the 2026-08-10 live check, all open-weight Chinese-lab frontier models (DeepSeek, GLM, Kimi,
MiniMax); no OpenAI/Anthropic
proxying. Vision, web search, web reader and native tool calling are advertised across all
models. Prepaid credits that never expire; no rate limits beyond balance. Dedicated H200/H100
capacity is sales-contact only.
- Sources (protocol verified 2026-08-07; public model/pricing schema re-verified 2026-08-10):
  - https://avian.io/docs/
  - https://avian.io/pricing/
  - https://api.avian.io/v1/models
  - https://avian.io/

### volcengine — ByteDance Volcengine Ark / BytePlus ModelArk (Doubao / Seed)

- Base URL: `https://ark.ap-southeast.bytepluses.com/api/v3`
- Auth: Authorization: Bearer $ARK_API_KEY
- `GET /models`: not documented
- Reasoning:
`thinking` object passed via OpenAI SDK `extra_body` (e.g. extra_body={"thinking": {...}}) to
toggle deep reasoning; not a top-level OpenAI param
- Compatibility notes:
International edition is branded BytePlus ModelArk; mainland edition is ark.cn-
beijing.volces.com/api/v3 (separate accounts/pricing/currency). OpenAI SDK 1.0+ and Python 3.7+
required. No model-discovery endpoint documented - catalog is static. Non-OpenAI fields
(thinking, encryption) go through extra_body. Optional headers X-Client-Request-Id for request
tracing and x-is-encrypted:true for application-layer encryption. Classic Doubao deployments
require the endpoint id (ep-...) in the `model` field rather than a model family name, though
current docs publish direct model ids. Requested id and returned id can differ: requesting
seed-1-8-251228 can return "model":"doubao-seed-1-8-251228". Tool-call schemas reject JSON-
Schema keywords minLength/maxLength/minItems/maxItems/minContains/maxContains. Region
availability varies (all listed models in ap-southeast-1; seed-2-0 and seedream-5-0-lite also
eu-west-1). Separate Responses API at /responses and Batch API at
/api/v3/batch/chat/completions. Streaming usage via stream_options.include_usage is supported.
- Sources (verified 2026-08-07):
  - https://docs.byteplus.com/api/docs/ModelArk/1330626
  - https://docs.byteplus.com/en/docs/ModelArk/1330310
  - https://docs.byteplus.com/en/docs/ModelArk/1494384
  - https://docs.byteplus.com/en/docs/ModelArk/1544106
  - https://docs.byteplus.com/en/docs/ModelArk/2123228
  - https://docs.byteplus.com/en/docs/ModelArk/1399008

### qianfan — Baidu Qianfan / ERNIE (Baidu AI Cloud)

- Base URL: `https://qianfan.baidubce.com/v2`
- Auth: Authorization: Bearer <API Key>  (key format bce-v3/ALTAK-xxxx/xxxx; the literal 'Bearer ' prefix is required or IAM auth fails. The embedded slashes are part of the key — never split on them)
- `GET /models`: yes
- Correction (2026-08-07 re-verification): the listing was previously recorded as
  undocumented. `GET https://qianfan.baidubce.com/v2/models` IS documented, takes the same
  bearer key, and returns 50+ models with context length, modalities and per-model pricing —
  a live pricing source. Deep thinking was also recorded as a model choice (ERNIE-X1); it is
  in fact parameter-driven and spelled per model family, `thinking: {type: enabled}` for the
  DeepSeek/Kimi/GLM lines and `enable_thinking` (boolean) for Qwen and the ERNIE 4.5/5.0
  thinking previews. ERNIE-X1 is stale naming; the current thinking model is
  `ernie-5.0-thinking-preview`. Both `max_tokens` and `max_completion_tokens` are documented,
  the latter covering answer plus reasoning chain.
  Source: https://cloud.baidu.com/doc/qianfan-api/s/Dmba8k71y and
  https://cloud.baidu.com/doc/qianfan-docs/s/Wm95lyynv
- Anthropic-compatible endpoint: `https://qianfan.baidubce.com/anthropic/coding`
- Reasoning:
No OpenAI-style reasoning_effort documented on the v2 chat surface; deep-thinking is exposed as
separate model ids (ERNIE-X1 / X1.1 series) rather than a request parameter
- Compatibility notes:
v2 endpoint uses a single permanent Bearer API key; the legacy v1 flow (aip.baidubce.com with an
OAuth access_token minted from AK/SK) is deprecated and must not be mixed with v2 keys - this is
the single most common integration failure. Optional custom header `appid` (a V2 application id)
can be sent via default_headers to attribute call volume and billing; not required. API keys are
scoped at creation to either all application identities or specific appids. Docs do not
enumerate which OpenAI endpoints beyond /chat/completions are supported and do not publish a
model-listing endpoint; the model catalog is a docs page. Separate surfaces exist on the same
host with their own paths: AI search at /v2/ai_search/chat/completions, image generation at
/v2/images/generations, and a Coding Plan at /v2/coding (OpenAI protocol) and /anthropic/coding
(Anthropic protocol). Coding Plan issues a dedicated API key usable ONLY on those coding paths.
Some legacy models (ERNIE-3.5-8K, ERNIE-Speed-8K) are free with QPS caps. Offline batch
inference is priced at 40% of online rates.
- Sources (verified 2026-08-07):
  - https://cloud.baidu.com/doc/qianfan/s/Hmh4suq26
  - https://cloud.baidu.com/doc/qianfan-docs/s/qm8qxemze
  - https://cloud.baidu.com/doc/qianfan/s/wmh4sv6ya
  - https://cloud.baidu.com/doc/qianfan-api/s/ym9chdsy5
  - https://cloud.baidu.com/doc/qianfan/s/imlg0beiu

### hunyuan — Tencent Hunyuan (Tencent Cloud)

- Base URL: `https://api.hunyuan.cloud.tencent.com/v1`
- Auth: Authorization: Bearer $HUNYUAN_API_KEY
- `GET /models`: not documented
- Reasoning:
No reasoning_effort parameter documented on the OpenAI-compatible surface; reasoning is selected
by model id (hunyuan-t1-* family)
- Compatibility notes:
REAL SEMANTIC DEVIATION: the `stop` parameter halts generation AFTER the matched string, whereas
OpenAI stops BEFORE it - output will contain the stop sequence, which silently breaks callers
that use stop tokens as delimiters. Hunyuan-specific fields passed via extra_body:
enable_enhancement (search/enhancement toggle), force_search_enhancement, citation (search
citation marks), enable_multimedia, enable_recommended_questions, search_info. Streaming usage
is returned in the final chunk when stream=true and stream_options.include_usage=true.
Embeddings are heavily restricted: only `input` and `model` accepted, dimensions fixed at 1024,
model must be hunyuan-embedding. GET /v1/models is not documented. Some third-party integrations
report capitalized non-OpenAI params (e.g. TopP) on adjacent native APIs. Not every hunyuan-* id
is a chat model - the 3D API is an async submit/poll job API with a different shape. MIGRATION
RISK: the billing docs carry a notice that Hunyuan features are gradually migrating to
'TokenHub' (product 1823), where models are relabeled (Hy3, Hy-MT2-Pro, Hy-Role-Latest) and the
legacy pricing page no longer lists the main text models.
- Sources (verified 2026-08-07):
  - https://cloud.tencent.com/document/product/1729/111007
  - https://cloud.tencent.com/document/product/1729/97731
  - https://cloud.tencent.com/document/product/1823/130055
  - https://cloud.tencent.com/document/product/1759/106152

### spark — iFlytek Spark (讯飞星火)

- Base URL: `https://spark-api-open.xf-yun.com/v1/`
- Auth: Authorization: Bearer <APIPassword>  (the console 'APIPassword', a single token - distinct from the legacy AppID/APIKey/APISecret triple)
- `GET /models`: not documented
- Reasoning:
None documented on the OpenAI-compatible v1 path; the generic /v1/chat/completions surface does
not expose reasoning_content, so the X1/X2 deep-reasoning chain is not surfaced there. Reasoning
models are selected by model id.
- Compatibility notes:
Docs explicitly state '兼容openAI SDK' (compatible with the OpenAI SDK) with base_url
https://spark-api-open.xf-yun.com/v1/. Two entirely different auth schemes coexist and are a
common failure source: the HTTP/OpenAI-compatible path takes a single Bearer APIPassword, while
the LEGACY WebSocket path (wss://spark-api.xf-yun.com/v3.5/chat) requires an AppID + APIKey +
APISecret triple with request signing - AnyInfer should target only the HTTP path. Each model
version has its own distinct APIPassword. A separate MaaS host also exposes an OpenAI-compatible
path at https://maas-api.cn-huabei-1.xf-yun.com/v1/chat/completions with sk- prefixed keys.
Model ids are non-obvious marketing-derived strings, not a uniform family (see pricing/notes).
Only Spark Pro, Max and 4.0Ultra support the built-in plugins (search, weather, date); only
4.0Ultra and Max support system messages and Function Call, and Function Call is HTTP-protocol
only. A non-OpenAI `web_search` param accepts deep/normal search strategies with differing token
consumption. Token accounting is roughly 1 token ~ 1.5 Chinese characters or 0.8 English words.
No /models endpoint documented.
- Sources (verified 2026-08-07):
  - https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html
  - https://xinghuo.xfyun.cn/sparkapi?scr=price

### stepfun — StepFun (阶跃星辰)

- Base URL: `https://api.stepfun.com/v1`
- Auth: Authorization: Bearer $STEP_API_KEY
- `GET /models`: yes
- Correction (2026-08-07 re-verification): this entry previously recorded
  `https://api.stepfun.ai/step_plan/v1`, which was wrong twice over — the documented host
  is `api.stepfun.com` (.com, not .ai), and `/step_plan/v1` is the Step Plan *subscription*
  surface rather than the general API, billed differently. Both paths live on the same host,
  so point `base_url` at `/step_plan/v1` deliberately for plan traffic. `GET /v1/models` and
  a single-model retrieve endpoint are documented, so the listing is enabled.
  Source: https://platform.stepfun.com/docs/zh/quickstart/overview.md and
  https://platform.stepfun.com/docs/zh/api-reference/models/list.md
- Anthropic-compatible endpoint: `https://api.stepfun.com/step_plan` (no /v1 — the Anthropic SDK appends it)
- Reasoning:
OpenAI protocol: `reasoning_effort` with values low|medium|high. Anthropic protocol:
`output_config.effort` with values low|medium|high.
- Compatibility notes:
Fully OpenAI Chat Completions compatible, and additionally serves a native Anthropic Messages
API. CRITICAL base-URL trap, documented explicitly: the OpenAI-compatible base URL INCLUDES /v1
(https://api.stepfun.ai/step_plan/v1) while the Anthropic-compatible base URL OMITS it
(https://api.stepfun.ai/step_plan), because the Anthropic SDK appends /v1/messages itself. Two
domains mirror each other: api.stepfun.ai is international, api.stepfun.com is China - docs are
published under both platform.stepfun.ai (en) and platform.stepfun.com (zh). Two product
surfaces: the plain open-platform path (POST https://api.stepfun.com/v1/messages, SDK base_url
https://api.stepfun.com) and the Step Plan path (POST .../step_plan/v1/messages). Rate limits
are tiered V0-V5 purely by cumulative top-up amount, from 5 concurrent / 10 RPM / 5M TPM at V0
up to 10,000 concurrent / 200,000 RPM / 100M TPM at V5 ($1,500+); higher limits require emailing
platform@stepfun.com with ~2 business days lead time. Prompt caching is priced as a separate
cheaper cache-hit input rate. A machine-readable docs index is published at /docs/llms.txt.
- Sources (verified 2026-08-07):
  - https://platform.stepfun.ai/docs/en/guides/pricing/details
  - https://platform.stepfun.ai/docs/en/step-plan/integrations/reasoning-api
  - https://platform.stepfun.ai/docs/en/step-plan/integrations/claude-code
  - https://platform.stepfun.com/docs/zh/api-reference/chat/messages-create
  - https://platform.stepfun.ai/docs/en/step-plan/integrations/openclaw

### watsonx — IBM watsonx.ai

- Base URL: `https://<region>.ml.cloud.ibm.com/ml/gateway/v1 (OpenAI-compatible model gateway); native chat is https://<region>.ml.cloud.ibm.com/ml/v1/text/chat?version=YYYY-MM-DD`
- Auth: Native /ml/v1 API: Authorization: Bearer <IAM access token>, exchanged from an IBM Cloud API key at IBM Cloud IAM, plus a required version=YYYY-MM-DD query parameter on every call. Model gateway (/ml/gateway/v1): IBM's own OpenAI-SDK example passes the IBM Cloud API key STRAIGHT THROUGH as api_key; an exchanged IAM bearer token is also accepted, but then it expires and a long-lived client must refresh and rebuild. Earlier revisions of this entry said the gateway required the exchanged token — that was wrong, and the preset no longer implies it (key_env is WATSONX_API_KEY).
- Correction (2026-08-07 re-verification): the gateway is explicitly labelled BETA and is IBM Cloud only (no Cloud Pak parity). Project scoping does not vanish so much as move — providers are registered per project ahead of time rather than named in the request body. The output-token field was previously recorded as max_completion_tokens; the only IBM-sourced example observed uses max_tokens, so the preset no longer renames it. Models are addressed provider-namespaced (openai/gpt-4o). Source: https://ibm.github.io/watsonx-ai-python-sdk/v1.4.11/model_gateway.html (www.ibm.com/docs returned HTTP 403 to automated access).
- `GET /models`: yes
- Reasoning:
Not documented as a distinct reasoning/thinking wire parameter on the pages loaded; generation
controls sit either at the body root (temperature, max_completion_tokens) or, in older examples,
nested under a parameters object (max_new_tokens, time_limit).
- Compatibility notes:
Two distinct surfaces. (1) Native POST /ml/v1/text/chat with mandatory version query param (e.g.
?version=2024-05-31, newer examples ?version=2025-10-25); body carries model_id (not model),
messages, and a required project_id (or space_id when working in a deployment space); streaming
is a separate path POST /ml/v1/text/chat_stream rather than a stream:true flag. Newer params
such as max_completion_tokens and temperature sit at the body root while older examples nest
generation settings under parameters. Not all foundation models support the chat API — the
supported subset is discoverable via GET
/ml/v1/foundation_model_specs?version=2024-10-10&filters=function_text_chat. Deployment-scoped
calls use /ml/v1/deployments/<deployment-id>/text/chat_stream?version=... and omit model_id and
project_id. (2) The model gateway at /ml/gateway/v1 maintains compatibility with the OpenAI API
so OpenAI SDKs work directly, exposing /chat/completions, /completions, /embeddings, /models and
/providers, using model rather than model_id and requiring no project_id or version param;
caveat is that a configured backend provider may not support a given endpoint service, producing
errors, and the gateway is still marked preview in some deployments. Model ids are namespaced
vendor/model strings, e.g. ibm/granite-3-8b-instruct, ibm/granite-3-2-8b-instruct, ibm/granite-
vision-3-2-2b, meta-llama/llama-3-2-3b-instruct, meta-llama/llama-3-2-11b-vision-instruct.
- Sources (verified 2026-08-07):
  - https://cloud.ibm.com/apidocs/watsonx-ai
  - https://www.ibm.com/docs/en/watsonx/saas?topic=generation-inferencing-gateway-models
  - https://dataplatform.cloud.ibm.com/docs/content/wsj/analyze-data/fm-model-gateway-use.html?context=wx
  - https://www.ibm.com/docs/en/watsonx/saas?topic=hub-chat-model-tutorial
  - https://www.ibm.com/docs/SSLSRPV_latest/wsj/analyze-data/fm-api-generation.html

### xinference — Xinference (Xorbits Inference)

- Base URL: `http://127.0.0.1:9997/v1`
- Auth: None documented for the default local launch (`xinference-local`)
- `GET /models`: yes
- Reasoning:
none documented
- Compatibility notes:
Default port 9997. Docs describe an "OpenAI compatible RESTful API" and give the OpenAI python
client base_url as "http://127.0.0.1:9997/v1" so it functions as a local replacement for OpenAI
endpoints. Web UI at http://127.0.0.1:9997 and interactive API docs at
http://127.0.0.1:9997/docs. Distributed/cluster mode (supervisor + workers) exists alongside the
single-node local launcher. Note: readthedocs was intermittently rate-limiting (HTTP 429) this
session, so the port and base URL were confirmed from the docs source in the official GitHub
repo instead.
- Sources (verified 2026-08-07):
  - https://github.com/xorbitsai/inference/blob/main/doc/source/getting_started/using_xinference.rst
  - https://github.com/xorbitsai/inference

### ramalama — RamaLama

- Base URL: `http://127.0.0.1:8080/v1`
- Auth: Optional Bearer token — chat_providers/base.py: `return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}`. No auth by default.
- `GET /models`: yes
- Reasoning:
none documented
- Compatibility notes:
Container-based runner (Podman/Docker) that serves models via a pluggable backend. `ramalama
serve llama3` defaults to port 8080; if taken it picks a free port — the man page says "If not
specified, a free port in the 8080-8180 range is selected, starting with 8080" (the README
summarizes 8081-8090), so the port is NOT reliably fixed and should be user-overridable.
`ramalama chat` defaults --url to http://127.0.0.1:8080. The client appends default_path
"/chat/completions" (OpenAICompletionsChatProvider) or "/responses"
(OpenAIResponsesChatProvider) via build_url(), which does NO automatic '/v1' insertion — the
'/v1' therefore comes from the user-supplied base URL and the backend. Backends are llama.cpp,
vLLM ("OpenAI compatible server") and MLX LM, so the exact param surface follows whichever
runtime is selected via --runtime. Web UI on by default at 127.0.0.1:<port>, disable with
--webui off.
- Sources (verified 2026-08-07):
  - https://github.com/containers/ramalama
  - https://github.com/containers/ramalama/blob/main/docs/ramalama-serve.1.md
  - https://github.com/containers/ramalama/blob/main/docs/ramalama-chat.1.md
  - https://github.com/containers/ramalama/blob/main/ramalama/chat_providers/openai.py
  - https://github.com/containers/ramalama/blob/main/ramalama/chat_providers/base.py

### geniex — Nexa SDK / GenieX (Qualcomm)

- Base URL: `http://127.0.0.1:18181/v1`
- Auth: None enforced, but the credential must be NON-EMPTY — the official example passes
  `api_key="geniex"` with the note that the server does not check it. An empty string or
  `None` breaks the OpenAI client before the request is sent.
- `GET /models`: yes
- Correction (2026-08-07 re-verification): recorded as undocumented. The official local-server
  page documents `POST /v1/chat/completions`, `GET /v1/models` AND `GET /v1/models/{model}`,
  so discovery is enabled. Also documented: only one tool call per assistant turn is parsed —
  parallel tool calls in a single response are unsupported — and Qwen3's default
  `<think>` prefix is suppressed with `extra_body={"enable_think": false}`.
  Source: https://geniex.aihub.qualcomm.com/en/run/cli/local-server.md
- Reasoning:
none documented
- Compatibility notes:
IMPORTANT — the project has been rebranded: the NexaAI/nexa-sdk repo is now the Qualcomm-
published GenieX project, and the CLI is `geniex serve`, not `nexa serve`. README: "geniex serve
# serves http://127.0.0.1:18181/v1" and "Point any OpenAI client at http://127.0.0.1:18181/v1 —
no code changes." Confirmed POST /v1/chat/completions with model/messages/max_tokens. Targets
GPU/NPU/CPU across PC, mobile and Arm64/x86 Docker. Caution: older third-party write-ups (and
search snippets) still cite `nexa serve --host 127.0.0.1:8080` — that port and command are
STALE; 18181 is what the current official README documents. GET /v1/models is not documented in
the README, and third-party integrations have historically had to proxy in a /v1/models endpoint
for Open WebUI compatibility, so treat model listing as absent.
- Sources (verified 2026-08-07):
  - https://github.com/NexaAI/nexa-sdk
  - https://raw.githubusercontent.com/NexaAI/nexa-sdk/main/README.md

## Batch added 2026-08-08 (aggregators, regional clouds, and more local engines)

Twenty presets verified against live documentation on 2026-08-08, taking the registry past
one hundred providers. The recurring theme in this batch is *addressing*: seven entries are
account- or deployment-scoped and therefore carry no default base URL, and five more
document a path prefix that is not `/v1` (`/openai`, `/engines/v1`, `/api/v2`,
`/openai/v1`, `/api/paas/v4`). A wrong prefix 404s at runtime and is invisible to unit
tests, so each is pinned by a regression test.

**Surveyed and rejected this pass:**

- **kluster.ai** - the company has wound down; kluster.ai now serves a notice that the team
  has joined MITO and redirects to an unrelated video product. No API remains to preset.
- **Meta Llama API** (`api.llama.com/compat/v1`) - OpenAI-compatible and well documented,
  but Meta has published a retirement date of 2026-07-06, after which requests return a
  sunset response. Adding it would ship a preset with a known expiry.
- **Lepton AI** - acquired by NVIDIA and relaunched as DGX Cloud Lepton, a GPU marketplace;
  the serverless token-billed inference API it had is sunset.
- **Crusoe, TensorWave, Civo, Genesis Cloud, Koyeb, Salad** - GPU infrastructure, not token
  APIs. The OpenAI surface comes from whatever you deploy (vLLM, TGI), which the `vllm` and
  `tgi` presets already cover at your own base URL.
- **Anyscale Endpoints** - sunset in late 2024; LLM serving now lives inside Ray Serve
  deployments with no hosted drop-in base URL.
- **Aleph Alpha** - its native client is not OpenAI-shaped; PhariaAI consumes external
  OpenAI-compatible APIs rather than exposing one, so the compatibility runs the other way.
- **Bifrost, TrueFoundry, AISIX, Higress** - self-hosted gateways whose upstream credentials
  are configured server-side, the same reason Kong was rejected in the second wave.
  Reachable today via the `openai-compat` adapter with a user-supplied base URL.

### poe - Poe (Quora)

- Base URL: `https://api.poe.com/v1`
- Auth: Authorization: Bearer $POE_API_KEY (keys from poe.com/api/keys; an active Poe
  subscription is required - the API spends subscription points)
- `GET /models`: yes
- Reasoning:
No reasoning_effort on the chat-completions surface. The Responses API at /v1/responses is
the documented route for reasoning and built-in tools such as web_search_preview.
- Compatibility notes:
Model ids are Poe bot names and are CASE-SENSITIVE and capitalized (Claude-Sonnet-4.6,
GPT-5.4, Gemini-3.1-Pro), unlike every other preset in this file. Documented limitations:
`n` must equal 1; `parallel_tool_calls` is unsupported; audio input is ignored;
`response_format` with type "json_schema" is NOT supported - which matters to this library
specifically, because structured output must fall back to json_mode or prompt-level coercion
rather than schema enforcement. Private bots, App-Creator and Script-Bot-Creator bots are
unreachable through this endpoint. Image/video/audio bots should be called with stream=False.
Rate limit is 500 requests/minute, request-based only (no token-based limiting), and
Retry-After is honoured on 429/503. Custom bot parameters go through extra_body.
- Sources (verified 2026-08-08):
  - https://creator.poe.com/docs/external-applications/openai-compatible-api
  - https://creator.poe.com/docs/external-applications/interface-configuration
  - https://creator.poe.com/api-reference

### siliconflow - SiliconFlow

- Base URL: `https://api.siliconflow.com/v1`
- Auth: Authorization: Bearer <key>
- `GET /models`: yes
- Reasoning:
Parameter-driven, not effort-based: `enable_thinking` (boolean, DEFAULTS TO TRUE) and
`thinking_budget` (integer, 128-32768, default 4096) on Qwen3 and DeepSeek-V3.1/3.2 families.
DeepSeek-R1 returns the chain separately as reasoning_content on the delta. Notably
DeepSeek-V3.1 requires enable_thinking=false for function calling to work.
- Compatibility notes:
TWO HOSTS, TWO ACCOUNTS: api.siliconflow.com is the international platform and
api.siliconflow.cn is the mainland one; keys are not interchangeable, and both appear in
official documentation, which is why the preset pins .com and says so. Model ids are HF-style
org/model paths (Qwen/Qwen3-8B). The docs advise reserving ~10k tokens of headroom rather
than requesting the full advertised context window.
- Sources (verified 2026-08-08):
  - https://docs.siliconflow.com/en/api-reference/chat-completions/chat-completions
  - https://docs.siliconflow.cn/en/faqs/stream-mode

### ppio - PPIO (formerly PPInfra)

- Base URL: `https://api.ppio.com/openai`
- Auth: Authorization: Bearer ${API_KEY}
- `GET /models`: not documented - the docs direct readers to the web catalog at
  ppio.com/model-api/product/llm-api instead of an API listing.
- Reasoning:
No reasoning/thinking parameter documented. The documented generation controls are
temperature, top_p, top_k, presence/frequency penalties, max_tokens and stream.
- Compatibility notes:
REBRAND WITH A HOST CHANGE, and this is the trap: nearly every third-party write-up and search
result still gives `https://api.ppinfra.com/v3/openai`, while ppinfra.com now 301-redirects to
ppio.com and the current first-party docs give `https://api.ppio.com/openai` (note: no /v3,
and no /v1 either - the OpenAI client appends the endpoint path). The preset records the
current host and keeps `ppinfra` as an alias so anyone who knows the old brand still resolves.
Model ids are vendor-namespaced (deepseek/deepseek-r1); a trailing /community marks the free
trial tier of the same weights, which the docs say is identical in quality but requires
topping up for sustained use.
- Sources (verified 2026-08-08):
  - https://ppio.com/docs/model/llm.md
  - https://ppio.com/docs/third-party/chatbox-use?from=ppinfra
  - https://ppio.com/docs/llms.txt

### modelscope - ModelScope API-Inference

- Base URL: `https://api-inference.modelscope.cn/v1`
- Auth: Authorization: Bearer <SDK token>. The credential is a ModelScope SDK access token
  shaped `ms-<uuid>`, issued from modelscope.cn/my/myaccesstoken - not a console API key,
  which is the usual mix-up.
- `GET /models`: yes
- Reasoning:
Depends on the served model rather than the platform; reasoning families stream
reasoning_content in the delta as elsewhere.
- Compatibility notes:
Alibaba's model community, distinct from Model Studio/DashScope (the `dashscope` preset) -
different host, different credential, free tier. Model ids are HF-style org/model repo paths.
Free quota is documented as roughly 2,000 requests/day overall with 500/day per model, and
phone verification is required at signup. A reported gotcha: the bare base URL returns
"404 page not found", which is correct - only the sub-paths route - so a 404 on the root is
not evidence of a wrong host. Also exposes an Anthropic-shaped /v1/messages using x-api-key
with the same ms- token.
- Sources (verified 2026-08-08):
  - https://modelscope.cn/docs/model-service/API-Inference/intro
  - https://modelscope.cn/my/myaccesstoken

### bigmodel - Zhipu AI BigModel (GLM, mainland)

- Base URL: `https://open.bigmodel.cn/api/paas/v4`
- Auth: Authorization: Bearer <key>
- `GET /models`: not documented on the compatibility page.
- Reasoning:
`thinking: {"type": "enabled"}` passed through extra_body / provider_options, documented for
GLM-5.2 with streaming.
- Compatibility notes:
This is Zhipu's MAINLAND platform and a separate account from the international z.ai host that
the `z-ai` preset covers: keys do not cross between them. One genuine wire difference rather
than a spelling one - the temperature range is the OPEN interval (0,1), so 0 and 1 are both
rejected where OpenAI accepts them, and temperature=0 with do_sample=False has no equivalent
here. Zhipu-specific features (web search tool, code interpreter, character models) need
their native SDK. A separate coding-plan surface exists at api.z.ai/api/coding/paas/v4.
- Sources (verified 2026-08-08):
  - https://docs.bigmodel.cn/cn/guide/develop/openai/introduction
  - https://docs.bigmodel.cn/cn/guide/platform/model-migration

### inception - Inception Labs (Mercury)

- Base URL: `https://api.inceptionlabs.ai/v1`
- Auth: Authorization: Bearer [INCEPTION_API_KEY]
- `GET /models`: not documented in the launch announcement.
- Reasoning:
reasoning_effort with low/medium/high; Mercury 2 is documented as a diffusion-based reasoning
model and the migration guidance is to start at "low".
- Compatibility notes:
DIFFUSION, NOT AUTOREGRESSIVE - the one entry in this file whose streaming semantics differ in
kind rather than degree. With `diffusing: True`, the model streams blocks of NOISY tokens that
are steadily refined into the final output, so a delta can REVISE text it already emitted
rather than only appending to it. Any consumer that concatenates deltas will produce garbage
under that flag; it is off by default and reachable only through provider_options. Those noisy
tokens are explicitly not billed. Also serves /fim/completions (fill-in-the-middle) beside
chat/completions.
- Sources (verified 2026-08-08):
  - https://www.inceptionlabs.ai/blog/introducing-inception-api
  - https://www.inceptionlabs.ai/blog/mercury-azure-foundry

### sarvam - Sarvam AI

- Base URL: `https://api.sarvam.ai/v1`
- Auth: its own header is `api-subscription-key`, but the docs state that
  `Authorization: Bearer <key>` is accepted on every endpoint for OpenAI-compatible tooling.
  The preset sends the bearer form.
- `GET /models`: not documented.
- Reasoning:
reasoning_effort with low/medium/high, and - unusually - reasoning is ON BY DEFAULT at "low".
It is disabled by passing an explicit null (reasoning_effort=None in Python), not by omitting
the parameter. sarvam-30b and sarvam-105b support think and non-think modes.
- Compatibility notes:
Indian-language (Indic) models. TWO PATHS, DIFFERENT CATALOGS: Sarvam's own chat models,
including sarvam-105b-conversations, are on /v1, while open-weight models (glm5.2, gemma4)
are served from /v2/chat/completions - so the version segment selects a catalog, not just an
API revision. Structured output works via response_format with a json_schema and
strict: true, returning a JSON string in message.content. The Python SDK requires
response_format to be passed through request_options rather than as a direct parameter.
- Sources (verified 2026-08-08):
  - https://docs.sarvam.ai/api-reference-docs/api-guides-tutorials/chat-completion/overview
  - https://docs.sarvam.ai/api/getting-started/models

### clarifai - Clarifai

- Base URL: `https://api.clarifai.com/v2/ext/openai/v1`
- Auth: Authorization: Bearer $CLARIFAI_PAT - a Personal Access Token, not a per-app key.
- `GET /models`: not documented on the OpenAI compatibility page.
- Reasoning:
Not documented as a distinct parameter; depends on the served model.
- Compatibility notes:
Note the doubly-nested path (/v2/ext/openai/v1) - the platform's own v2 API, an extension
namespace, then the OpenAI v1 surface. Model ids are catalog paths
(openai/chat-completion/models/gpt-oss-120b) and the full https://clarifai.com/... URL form is
also accepted. Supports the `developer` and `tool` message roles. Responses, Images Generate
and Embeddings are served from the same base.
- Sources (verified 2026-08-08):
  - https://docs.clarifai.com/compute/inference/open-ai/

### lighton - LightOn Paradigm

- Base URL: `https://paradigm.lighton.ai/api/v2`
- Auth: Paradigm API key as a bearer token.
- `GET /models`: yes - the Models endpoint is listed among the OpenAI-SDK-compatible routes.
- Reasoning:
Not documented.
- Compatibility notes:
French/EU document-intelligence platform. The base path is `/api/v2` - neither /v1 nor a bare
host. Chat Completions, Completions, Embeddings, Models and Files are the documented
compatible endpoints. The docs warn that model names are platform-specific, some advanced
parameters are unsupported, and rate limits differ from OpenAI's.
- Sources (verified 2026-08-08):
  - https://docs.lighton.ai/en/developer-resources/api-fundamentals/openai-compatibility

### ollama-cloud - Ollama Cloud

- Base URL: `https://ollama.com/v1`
- Auth: Authorization: Bearer $OLLAMA_API_KEY - required here, unlike a local Ollama where
  the key is required-but-ignored.
- `GET /models`: yes
- Reasoning:
Model-dependent; Ollama exposes thinking on its native API surface rather than through an
OpenAI effort parameter.
- Compatibility notes:
Distinct from the dedicated `ollama` adapter, which is the LOCAL daemon on 11434 - this is the
hosted catalog and needs a real credential. MODEL ID TRAP: the `-cloud` suffix
(gpt-oss:120b-cloud) is how a LOCAL Ollama names a cloud-proxied model; calling ollama.com
directly wants the bare id (gpt-oss:120b). Ollama's own docs note that the /v1 OpenAI path is
lossier than the native /api surface for tool calling - models can emit raw tool-call JSON as
text - so the native adapter remains preferable where it applies.
- Sources (verified 2026-08-08):
  - https://docs.ollama.com/cloud
  - https://docs.ollama.com/api/openai-compatibility

### runpod - Runpod Serverless

- Base URL: `https://api.runpod.ai/v2/<endpoint_id>/openai/v1` - no default; the endpoint id
  is yours.
- Auth: Authorization: Bearer $RUNPOD_API_KEY ("Use your Runpod API key, not an OpenAI key").
- `GET /models`: yes - documented via client.models.list().
- Reasoning:
Whatever the deployed vLLM worker's model supports; no gateway-level parameter.
- Compatibility notes:
The OpenAI surface is the vLLM worker's, so vLLM extras (best_of, top_k, beam_search, guided
decoding) are available through provider_options. Documented divergences: token counting
differs from OpenAI's (different tokenizers), rate limits are Runpod's, and tool/vision
support depends on the underlying model. Set RAW_OPENAI_OUTPUT=1 on the worker if streaming
responses arrive in an unexpected shape. A native queue-based route also exists at
/v2/<id>/runsync wrapping openai_route/openai_input, which this preset does not use.
- Sources (verified 2026-08-08):
  - https://docs.runpod.io/serverless/vllm/openai-compatibility

### vast-ai - Vast.ai Serverless

- Base URL: `https://openai.vast.ai/<endpoint_name>` - no default, and note it carries NO /v1
  segment; the proxy mounts the OpenAI routes at the endpoint root.
- Auth: Authorization: Bearer <VAST_API_KEY>
- `GET /models`: not documented for the proxy.
- Reasoning:
Model-dependent (vLLM backend).
- Compatibility notes:
THE MODEL FIELD IS IGNORED. The docs are explicit: it is required by the OpenAI protocol but
discarded by the proxy, and the served model is decided entirely by the MODEL_NAME environment
variable on your serverless endpoint - so any non-empty string works and the routing lives in
the base URL. Other documented divergences: tokenization differs, streaming chunk boundaries
vary and empty strings can appear with chunked prefill, tool calling differs from OpenAI's,
vLLM returns extra response fields, user/suffix/image_url.detail are accepted and ignored,
and no content moderation layer is applied.
- Sources (verified 2026-08-08):
  - https://docs.vast.ai/guides/serverless/openai-compatible-api

### cloudflare-ai-gateway - Cloudflare AI Gateway (unified / compat)

- Base URL: `https://gateway.ai.cloudflare.com/v1/<account_id>/<gateway_id>/compat` - no
  default; both ids are yours.
- Auth: `cf-aig-authorization: Bearer <CF_AIG_TOKEN>` for gateway-authenticated ("credits")
  use, optionally combined with the upstream provider's own token in the standard
  Authorization header (dual authentication).
- `GET /models`: not documented - the supported-provider list is static in the docs.
- Reasoning:
Passthrough to the upstream provider's own parameter.
- Compatibility notes:
DISTINCT FROM `cloudflare-workers-ai`, which serves only Cloudflare's own @cf/ models from
api.cloudflare.com. This entry is the multi-provider gateway: models are addressed
{provider}/{model} (openai/gpt-5.2, anthropic/claude-4-5-sonnet,
workers-ai/@cf/meta/llama-3.3-70b-instruct-fp8-fast), with dynamic routes as dynamic/{route}.
Documented upstreams include Anthropic, OpenAI, Groq, Mistral, Cohere, Perplexity, Workers AI,
Google AI Studio, Vertex AI, xAI, DeepSeek, Cerebras and Baseten. Because Cloudflare's own
credential belongs in cf-aig-authorization rather than Authorization, pass it as a configured
header when the upstream also needs a key.
- Sources (verified 2026-08-08):
  - https://developers.cloudflare.com/ai-gateway/usage/chat-completion/
  - https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/

### hyperstack - Hyperstack AI Studio

- Base URL: no fixed default - the console's AI Studio Playground exposes the Base URL and
  Model ID per deployment (https://console.hyperstack.cloud/ai/api/v1 shape).
- Auth: Hyperstack API key as a bearer token.
- `GET /models`: not documented; the playground's API panel is the documented discovery path.
- Reasoning:
Not documented at the platform level.
- Compatibility notes:
On-demand GPU cloud whose AI Studio exports fine-tuned and catalog models as OpenAI-compatible
endpoints. Because both the base URL and the model id follow your own deployment rather than a
shared catalog, this preset requires a base URL rather than guessing one.
- Sources (verified 2026-08-08):
  - https://www.hyperstack.cloud/ai-studio
  - https://www.hyperstack.cloud/technical-resources/tutorials/how-to-integrate-hyperstack-llm-api-with-opencode-for-smarter-ai-applications

### nutanix - Nutanix Enterprise AI (GPT-in-a-Box)

- Base URL: no default - your own NAI endpoint host, https://<host>/api/v1.
- Auth: an NAI-issued API key as a bearer token.
- `GET /models`: deployment-dependent.
- Reasoning:
Model-dependent.
- Compatibility notes:
On-premises/private-cloud serving; Nutanix documents accessing NAI endpoints with
OpenAI-compatible clients, so the wire surface is the standard one and everything specific to
a site is the base URL. Ships as part of the Nutanix Cloud Platform's agentic AI stack.
- Sources (verified 2026-08-08):
  - https://portal.nutanix.com/docs/Nutanix-Enterprise-AI-v2_5:top-nai-access-open-ai-clients-t.html
  - https://www.nutanix.com/blog/unleashing-the-power-of-ai-with-nutanix-gpt-in-a-box-and-red-hat-openshift-ai

### llama-stack - Llama Stack (Meta)

- Base URL: `http://127.0.0.1:8321/v1`
- Auth: none enforced locally; examples pass a placeholder ("fake").
- `GET /models`: yes
- Reasoning:
Delegated to the configured backend provider.
- Compatibility notes:
A composable server fronting vLLM, Ollama, TGI or hosted providers behind one endpoint.
PATH MOVED BETWEEN VERSIONS: current builds serve the OpenAI routes at `/v1`
(/v1/chat/completions, /v1/completions, /v1/embeddings, plus /v1/vector_stores, /v1/files,
/v1/batches), while older documentation nests them under `/v1/openai/v1` - so a 404 on an
otherwise correct setup usually means the other layout. Also speaks the Anthropic Messages
shape at /v1/messages and a Google GenAI surface at /v1alpha/interactions. Default port 8321
is confirmed by the server's own startup log.
- Sources (verified 2026-08-08):
  - https://pypi.org/project/llama-stack/
  - https://llamastack.github.io/
  - https://github.com/llamastack/llama-stack

### kserve - KServe

- Base URL: no default - a cluster service host, http://<service-host>/openai/v1.
- Auth: none by default; gateway-dependent (Kuadrant/Gateway API deployments add keys).
- `GET /models`: yes, under the same prefix.
- Reasoning:
Backend-dependent (vLLM or TGI serving runtimes).
- Compatibility notes:
THE /openai PREFIX IS THE WHOLE TRAP: KServe mounts the OpenAI routes at
/openai/v1/chat/completions, not /v1/chat/completions, and a base URL ending in /v1 alone
404s. The prefix is configurable through KSERVE_OPENAI_ROUTE_PREFIX, and some downstream
distributions strip it, so the preset requires an explicit base URL rather than guessing which
layout a cluster uses. The predictor container itself listens on 8080; external access is via
ingress with a Host header.
- Sources (verified 2026-08-08):
  - https://kserve.github.io/website/docs/model-serving/generative-inference/tasks/text-generation
  - https://kserve.github.io/website/docs/getting-started/genai-first-isvc
  - https://kserve.github.io/website/docs/model-serving/generative-inference/overview

### lemonade - Lemonade Server (AMD)

- Base URL: `http://localhost:13305/v1`
- Auth: OPTIONAL AND NOT A BEARER TOKEN - when LEMONADE_API_KEY is set, the documented form
  is an `?api_key=KEY` QUERY PARAMETER, not an Authorization header. Unset, no auth applies.
- `GET /models`: yes, plus GET /v1/models/{model_id}.
- Reasoning:
Model-dependent; the catalog labels reasoning-capable models (Qwen3 and similar).
- Compatibility notes:
AMD-sponsored local server, notable as the open-source OpenAI-compatible server with Ryzen AI
NPU acceleration (flm / ryzenai backends). Port 13305 is current; older material and some
third-party integrations still say 8000. Both /api/v1/* and /v1/* prefixes are served.
Documented parameter gaps: logprobs is unavailable for chat completions; image generation
supports only n=1 and b64_json. It also serves the Ollama API and the Anthropic Messages API
(/v1/messages) on the same port, and can route to remote providers whose models then appear
dot-namespaced in the same /v1/models listing.
- Sources (verified 2026-08-08):
  - https://lemonade-server.ai/docs/api/openai/
  - https://lemonade-server.ai/docs/guide/concepts/
  - https://lemonade-server.ai/docs/guide/configuration/

### docker-model-runner - Docker Model Runner

- Base URL: `http://localhost:12434/engines/v1` (from inside a container:
  http://model-runner.docker.internal/engines/v1)
- Auth: none. "DMR ignores the Authorization header" - pass anything or nothing.
- `GET /models`: yes, at /engines/v1/models.
- Reasoning:
Model-dependent.
- Compatibility notes:
Built into Docker Desktop, so it is the local engine most likely to be already installed. The
OpenAI routes live under `/engines/v1`, NOT `/v1` - the single most likely misconfiguration
for this provider. Also serves /engines/v1/completions and /engines/v1/embeddings.
- Sources (verified 2026-08-08):
  - https://docs.docker.com/ai/model-runner/api-reference/
  - https://docs.docker.com/ai/model-runner/

### llama-swap - llama-swap

- Base URL: `http://127.0.0.1:8080/v1`
- Auth: optional - "API Key support: define keys to restrict access to API endpoints".
- `GET /models`: yes
- Reasoning:
Whatever the swapped-to upstream supports.
- Compatibility notes:
A model-swapping proxy rather than an engine: it reads the `model` field from each request,
loads the matching upstream configuration (llama-server, vLLM, TabbyAPI ...) and replaces the
running process if a different one is needed. Consequences worth knowing: model ids are
CONFIG PROFILE NAMES from config.yaml, not file paths or HF repos; only one model is resident
by default (use groups for more); and the first request after a switch pays the load cost, so
it is slow rather than failed. Serves v1/completions, v1/chat/completions, v1/models,
v1/embeddings, plus audio and image routes. Docker images listen on 8080 internally.
- Sources (verified 2026-08-08):
  - https://github.com/mostlygeek/llama-swap/blob/main/README.md
  - https://github.com/mostlygeek/llama-swap/blob/main/docs/configuration.md

### foundry-local - Microsoft Foundry Local

- Base URL: no default - http://127.0.0.1:<PORT>/v1, where PORT is ASSIGNED DYNAMICALLY when
  the service starts.
- Auth: none documented for the local service.
- `GET /models`: the OpenAI-shaped listing is at `/openai/models` and returns a BARE ARRAY of
  model-name strings, not an OpenAI {object: "list", data: [...]} envelope; a richer catalog
  is at /foundry/list. Because it is neither at /v1/models nor OpenAI-shaped, the preset
  declares no listing rather than pointing discovery at a route that would misparse.
- Reasoning:
max_completion_tokens is documented as covering visible output plus reasoning tokens, but no
reasoning_effort parameter is exposed.
- Compatibility notes:
THE PORT MUST BE DISCOVERED, NOT ASSUMED. Microsoft's own reference says to read it from
`foundry service status` or GET /openai/status and explicitly warns "never hardcode the
port"; their examples show both 5273 and 5272, and `foundry service set --port` can change it.
That is why this preset requires a base URL despite being a loopback service. Requests need
the FULL model id (Phi-4-mini-instruct-generic-cpu), not the CLI alias. Models unload after
ten idle minutes by default unless loaded with an explicit ttl. Non-standard extras on the
chat body: `ep` (ONNX execution provider: dml/cuda/qnn/cpu/webgpu) and `ttl`. The API is in
preview and documented as subject to breaking changes without notice.
- Sources (verified 2026-08-08):
  - https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-rest
  - https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-local/concepts/foundry-local-architecture
