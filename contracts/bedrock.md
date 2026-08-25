# bedrock — Protocol Contract

Status: **implemented** — `providers/bedrock.py`, the Converse API for generation; Titan
Text Embeddings V2 and Cohere Embed v3 via `InvokeModel` for embeddings; `amazon.rerank-v1:0`
and `cohere.rerank-v3-5:0` via the separate `bedrock-agent-runtime` Rerank action.
Last verified: 2026-08-14 — generation section against 2026-08-07 live documentation;
Titan embeddings section fetched live 2026-08-12; Cohere embeddings and Rerank sections
fetched live 2026-08-14 and cross-checked against botocore's own installed
`bedrock-agent-runtime` service model.

## Upstream sources
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseStream.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ContentBlockDelta.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ReasoningContentBlockDelta.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ContentBlock.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModelWithResponseStream.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions-mantle.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic-claude-messages.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic-claude-messages-request-response.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/inference-reasoning.html
- https://aws.amazon.com/bedrock/pricing/
- https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/us-east-1/index.json
- https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html
  (embeddings, fetched live 2026-08-12)
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html
  (embeddings request/response shape, fetched live 2026-08-12)
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html
  (InvokeModel URI/headers, fetched live 2026-08-12)
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-embed-v3.html
  (Cohere Embed v3 request/response shape and limits, fetched live 2026-08-14)
- https://docs.aws.amazon.com/bedrock/latest/userguide/rerank-supported.html
  (Rerank model IDs and Region support, fetched live 2026-08-14)
- https://docs.aws.amazon.com/bedrock/latest/userguide/rerank-use.html
  (Rerank request/response fields and a verbatim boto3 code example, fetched live 2026-08-14)
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Rerank.html
  (Rerank API reference, fetched live 2026-08-14)
- botocore's installed `bedrock-agent-runtime` `2023-07-26` service model
  (`service-2.json`, inspected locally 2026-08-14) — the authoritative source for exact
  shapes, enum values, and the SigV4 `signingName`

## Why Converse, not InvokeModel

Converse is the *unified* interface: one request shape across Claude, Nova, Llama,
Mistral, and DeepSeek, where `InvokeModel` demands a different body per model family.
That normalization is what AnyInfer wants, and it is where tool use, document blocks,
guardrails, and cache points live. `InvokeModel` is not used.

## Wire contract

### Endpoints
- `POST {base}/model/{modelId}/converse` — unary generation
- `POST {base}/model/{modelId}/converse-stream` — streaming
- `GET https://bedrock.{region}.amazonaws.com/foundation-models` — discovery, on the
  **control plane** (a different host than the runtime, signed separately)

Default base is `https://bedrock-runtime.{region}.amazonaws.com`, region default
`us-east-1`. `modelId` may be a base model id, an inference-profile id, or an ARN, and is
percent-encoded into the path because ARNs contain colons and slashes.

### Auth
Two schemes, in precedence order:

1. **Bedrock API key** — `Authorization: Bearer <key>`, used verbatim when `api_key` is
   set. Conventionally `env://AWS_BEARER_TOKEN_BEDROCK`.
2. **SigV4** — every request signed with service name `bedrock` from resolved AWS
   credentials (explicit options, then boto3's chain when installed, then the
   environment). Signed headers are `content-type`, `host`, `x-amz-content-sha256`,
   `x-amz-date`, plus `x-amz-security-token` for temporary credentials.

Explicit credentials are supplied as the `aws_access_key_id`, `aws_secret_access_key`,
`aws_session_token`, and `profile` setup fields. The two that are genuinely secret are
declared `kind="secret"` so they resolve `env://` and `credential://` references and are
registered for redaction; an access key id and a profile name are identifiers, not
secrets, so they are passed through verbatim. Leaving every credential field empty is the
supported way to use the ambient chain.

### Version pins
- None. The Converse shape is versioned by the endpoint path.

### Request fields sent
- `messages[]`: role plus a list of typed content blocks. Blocks emitted: `text`,
  `toolUse` (`toolUseId`, `name`, `input`), `toolResult` (`toolUseId`, `content`,
  `status`), `image`, `document`, and `audio`. Multimodal blocks were verified 2026-08-10
  against the ContentBlock reference and Converse guide. Inline sources carry base64 in
  `bytes`; remote sources must be `s3://` and project to `s3Location`. **Tool results ride
  on a `user` turn**, as in the Anthropic dialect.
- `system[]`: a top-level list of text blocks, not a message.
- `inferenceConfig`: `maxTokens`, `temperature`, `topP`, `stopSequences` — and nothing
  else. Converse defines no `seed`, penalty, or log-probability field (re-checked
  2026-08-25); model-specific equivalents exist only under
  `additionalModelRequestFields`, which is per-model rather than protocol-level, so the
  descriptor declares all four in `ignored_parameters`. Unset sampling
  fields are omitted entirely.
- `toolConfig`: `tools[].toolSpec` (`name`, `description`, `inputSchema.json`) plus
  `toolChoice`, which is `auto`, `any`, or a named `tool`.
- `additionalModelRequestFields`: model-specific parameters Converse does not model.
  Reasoning effort travels here as Claude-style `thinking`, since Converse has no
  reasoning field of its own.

### Structured output
Converse has no response-format field, so a schema is emulated as a **single forced tool
call** — the same emulation the Anthropic adapter uses, and for the same reason: the API
genuinely constrains tool input. The core recovers the answer from the tool call's
arguments.

### Response fields read
- `output.message.content[]` — `text`, `reasoningContent` (surfaced as reasoning, kept out
  of the answer), `toolUse`.
- `stopReason` — `end_turn`/`stop_sequence` to stop, `max_tokens` to length, `tool_use` to
  tool_calls, `guardrail_intervened`/`content_filtered` to content_filter,
  `model_context_window_exceeded` to length, `malformed_model_output`/`malformed_tool_use`
  to other.
- `usage` — `inputTokens`, `outputTokens`, `totalTokens`, `cacheReadInputTokens`,
  `cacheWriteInputTokens`.
- `metrics.latencyMs` becomes the result's `provider_latency` phase timing.

### Streaming
**Binary `application/vnd.amazon.eventstream` framing, with no SSE or JSON alternative** —
decoded by `anyinfer.providers.eventstream`, which verifies both the prelude and message
CRC32s. Events read: `messageStart`, `contentBlockStart` (tool-use blocks),
`contentBlockDelta` (text, `toolUse.input` fragments, `reasoningContent`),
`contentBlockStop`, `messageStop` (stop reason), `metadata`.

**Usage arrives only in the terminal `metadata` event.** A stream closed on `messageStop`
reports no tokens at all.

### Errors
- In-stream exception frames (`:message-type: exception`) mapped to the shared status
  classification: `throttlingException` and `modelNotReadyException` to 429,
  `serviceUnavailableException` to 503, `internalServerException` to 500,
  `modelStreamErrorException` to 424, `modelTimeoutException` to 408, others to 400.
- HTTP errors: `ValidationException` 400, `AccessDeniedException` 403,
  `ResourceNotFoundException` 404, `ModelTimeoutException` 408, `ModelErrorException` 424,
  `ThrottlingException` 429, `InternalServerException` 500, `ServiceUnavailableException`
  503.

### Health
Deliberately not a network call: every runtime endpoint costs a generation, and the
control plane may be denied by policy even when inference works. Health reports whether
credentials are present.

## Embeddings (verified live 2026-08-12)

Bedrock has **no embeddings surface on Converse at all** — every embedding model goes
through the older, per-model `InvokeModel` action, so `BedrockAdapter.embed()` is
entirely separate machinery, reusing only the SigV4/bearer-key auth headers and the
`_quote_model` path helper.

### Endpoint
`POST {base}/model/{modelId}/invoke`, `content-type: application/json`,
`accept: application/json` — same base host and auth as generation, just a different
action name and no `/converse` suffix.

### Titan Text Embeddings V2 (`amazon.titan-embed-text-v2:0`) — scoped and implemented
Request:
```json
{"inputText": "string", "dimensions": 1024, "normalize": true, "embeddingTypes": ["float"]}
```
`inputText` required; `dimensions` accepts `1024` (default), `512`, or `256`; `normalize`
defaults `true`; `embeddingTypes` defaults `["float"]`. **Exactly one `inputText` per
call — there is no batch field**, confirmed by the request schema having no array
variant. The adapter declares `max_batch_inputs=1` and issues one `InvokeModel` call per
input, summing `inputTextTokenCount` across calls into `Usage.input_tokens`.

Response:
```json
{"embedding": [0.1, ...], "inputTextTokenCount": 12, "embeddingsByType": {"float": [...]}}
```
`embedding` is read directly; `embeddingsByType` is not consumed (the adapter never sets
`embeddingTypes`, so the response always carries `float` in both fields identically).

Limits: 8,192 max input tokens, 50,000 max input characters (whichever binds first — only
the token ceiling is representable in `EmbeddingCapabilities`). No `task_type`/intent
concept in the request schema — `input_intents=()`.

### Cohere Embed v3 (`cohere.embed-english-v3`, `cohere.embed-multilingual-v3`) — verified live 2026-08-14, implemented

Same `POST {base}/model/{modelId}/invoke` action and host as Titan, a completely
different body — verified live against
docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-embed-v3.html (the
`model-parameters-cohere-embed.html` URL the earlier session tried no longer resolves;
AWS has since restructured this page under `model-parameters-embed-v3.html`).

Request:
```json
{"texts": ["string"], "input_type": "search_document|search_query|classification|clustering|image", "truncate": "NONE|START|END", "embedding_types": ["float"]}
```
`texts` required (mutually exclusive with `images`, not sent by this adapter);
`input_type` required, **no default** — Bedrock's Cohere v3 refuses a request without one,
same as hosted Cohere, so `BedrockAdapter._embed_cohere` raises `ConfigError` before
sending rather than guessing an intent. `embedding_types` is always sent explicitly as
`["float"]` by this adapter so the response shape stays the deterministic dict-keyed form
below, rather than the flat-array form the docs show for the (unused, by this adapter)
no-`embedding_types` default. Batch limits: **96 texts per call, 2,048 characters per
text** (stated in characters on this page, not tokens — converted to `max_input_tokens=512`
using the same page's own "1 token is about 4 characters" rule, to stay consistent with
every other provider's token-denominated `EmbeddingCapabilities` field here).

Response:
```json
{"id": "string", "response_type": "embeddings_floats", "embeddings": {"float": [[0.1, ...]]}, "texts": ["string"]}
```
`embeddings` is a dict keyed by requested type (confirmed by the docs' own boto3 code
sample, which indexes it as `embeddings[embedding_type]`) — the same shape and the same
parse `providers/cohere.py` already uses for hosted Cohere, reused verbatim here.
**No token-usage or search-unit field anywhere in this response** — `Usage` is always
`None`, unlike Titan's `inputTextTokenCount`. No `dimensions` override field exists on
this action; output is always 1,024 dimensions for both v3 models.

### Rerank (`amazon.rerank-v1:0`, `cohere.rerank-v3-5:0`) — verified 2026-08-14, implemented

A **third action, a different host and a different service surface** from both
`InvokeModel` and `Converse`: `bedrock-agent-runtime.{region}.amazonaws.com`'s
`POST /rerank`, confirmed against the live AWS docs page
(`docs.aws.amazon.com/bedrock/latest/userguide/rerank-use.html`, including a verbatim
boto3 code example) and cross-checked against botocore's own installed
`bedrock-agent-runtime` `2023-07-26` service model (`service-2.json`) for the exact shape
and SigV4 `signingName` — which is `"bedrock"`, the **same** signing service name
`InvokeModel`/`Converse` use, despite the different host and endpoint prefix. This
adapter reuses `_SIGNING_SERVICE` unchanged.

Genuinely model-agnostic at the wire level — one request/response shape for both
`amazon.rerank-v1:0` and `cohere.rerank-v3-5:0`, selected only by `modelArn`:

Request:
```json
{
  "queries": [{"type": "TEXT", "textQuery": {"text": "string"}}],
  "sources": [{"type": "INLINE", "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": "string"}}}],
  "rerankingConfiguration": {
    "type": "BEDROCK_RERANKING_MODEL",
    "bedrockRerankingConfiguration": {
      "modelConfiguration": {"modelArn": "arn:aws:bedrock:{region}::foundation-model/{modelId}"},
      "numberOfResults": 10
    }
  }
}
```
`queries` is fixed at exactly 1 item (`RerankQueriesList` max is 1 in the service model —
Bedrock's Rerank action takes one query per call, not a batch of queries). `sources`
allows 1-1,000 documents (`RerankSourcesList`). `numberOfResults` (this adapter's
`top_n`) allows 1-1,000 when set; omitted when the caller doesn't request truncation, so
every document is ranked. The `modelArn` format
(`arn:aws:bedrock:{region}::foundation-model/{modelId}`, no account id between the two
colons) is the literal string from AWS's own boto3 example, not inferred.

Response:
```json
{"results": [{"index": 0, "relevanceScore": 0.9, "document": {...}}], "nextToken": "string"}
```
`index` is positional within the `sources` array this call sent, mapped back onto the
caller-supplied `RerankWireDocument.index` — same rule every other adapter's rerank
parsing follows. `document` (an echo of the input) is never requested or read.
**No usage or search-unit field anywhere in this response.** `nextToken`-based pagination
exists in the shape but is not implemented — every call the core issues fits its full
document set in one `Rerank` call today (bounded by `RerankCapabilities.max_documents`),
so pagination has never been reachable; revisit if that assumption changes.

## Watchlist
- **The OpenAI-compat endpoints.** `bedrock-mantle.{region}.api.aws/v1` (recommended,
  API-key auth) and `bedrock-runtime.{region}.amazonaws.com/v1` exist for select models.
  If coverage broadens, a preset entry may become worthwhile alongside this adapter.
- `serviceTier` (priority/default/flex/reserved) and `performanceConfig` — not currently
  sent; reachable through `provider_options`.
- Claude Sonnet 4.5 and Haiku 4.5 accept `temperature` **or** `top_p`, not both; sending
  both is a model-level rejection this adapter does not pre-empt.
- Long read timeouts (60 minutes or more) are recommended for Claude models on Bedrock.
- `cacheDetails[]` per-TTL cache accounting — read only in aggregate today.
