# bedrock — Protocol Contract

Status: **implemented** — `providers/bedrock.py`, the Converse API.
Last verified: 2026-08-07 — against live AWS documentation (sources below).

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
- `inferenceConfig`: `maxTokens`, `temperature`, `topP`, `stopSequences`. Unset sampling
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
