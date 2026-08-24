# Conformance matrix

**Generated from a real conformance run — do not edit by hand.**
Regenerate with `python workspace.py matrix`.

Legend: ✅ verified · ➖ declared unsupported · ❌ failing

Each cell is one parametrized test case executed against that adapter in fake-server mode.
A ➖ is an honest, declared limitation; it is not a pass.


Last generated: 2026-08-24.

| Provider | list_models | health | non_streaming | streaming | event_ordering | ttft | usage | usage_survives_streaming | tool_calls | streaming_tool_calls | reasoning | structured_output | schema_repair | error_mapping | retry_after | byte_cap | cancellation | unknown_finish_reason | embedding | embedding_duplicates | rerank | rerank_top_n | rerank_duplicate_text | embedding_normalization_probe | embedding_byte_cap | rerank_byte_cap | embedding_retry_after | rerank_retry_after |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| anthropic | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ |
| azure-foundry | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ✅ | ✅ | ➖ | ✅ | ➖ |
| bedrock | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| cohere | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| deepseek | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ |
| gemini | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ |
| groq | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ |
| jina | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| lm-studio | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ |
| m365-copilot | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ✅ | ✅ | ➖ | ➖ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ |
| moonshot | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ |
| nebius | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ |
| ollama | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ✅ | ✅ | ➖ | ✅ | ➖ |
| openai | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ✅ | ✅ | ➖ | ✅ | ➖ |
| openai-compat | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ |
| openrouter | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ |
| reka | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ |
| tei | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| venice | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ |
| vertex | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ✅ | ✅ | ➖ | ✅ | ➖ |
| voyage | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| xai | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ |

Adapters without a harness yet (`copilot`, `llama-cpp`) are covered by their own dialect tests; the public matrix reports only shared-harness results. Expanding cassette-backed coverage is tracked as release follow-up work. The `groq`, `moonshot`, `reka` and `venice` rows exercise the shared adapter's quirk axes — bearer auth, the renamed output-token field, `x-api-key` auth, and the `max_completion_tokens` dialect. Every entry in the [preset registry](../providers/presets.md) is separately instantiated and checked for registry invariants; these rows do not claim a live upstream verification.

## What the cases check

| Case | Verifies |
|---|---|
| `list_models` | Discovery returns models with non-empty ids. |
| `health` | The readiness probe answers with a boolean. |
| `non_streaming` | A buffered generation produces text and a valid finish reason. |
| `streaming` | Deltas arrive and concatenate to the final text (ordering guarantee 4). |
| `event_ordering` | All four ordering guarantees hold. |
| `ttft` | First-token timing is measured and consistent with total duration. |
| `usage` | Token counts are reported and internally consistent. |
| `usage_survives_streaming` | A trailing usage chunk reaches the result and the event stream. |
| `tool_calls` | Tool calls carry an id, a name, and parsed arguments. |
| `streaming_tool_calls` | Argument fragments reassemble by index. |
| `reasoning` | Reasoning streams as its own channel, excluded from the answer text. |
| `structured_output` | A schema request yields a validated value and records its mechanism. |
| `schema_repair` | The repair loop recovers an initially-invalid response. |
| `error_mapping` | Failures are typed, carry an attempt trail, and mark retryability. |
| `retry_after` | A rate-limited attempt is retried and recorded. |
| `byte_cap` | An oversized response is rejected rather than silently truncated. |
| `cancellation` | Abandoning a stream releases its connection and leaves the client usable. |
| `unknown_finish_reason` | An unrecognized finish reason normalizes instead of crashing. |
| `embedding` | One vector per input, uniform non-zero dimensions, a space identity. |
| `embedding_duplicates` | Duplicate inputs come back positionally, never deduplicated. |
| `rerank` | Rankings descend, and caller document identity survives the round trip. |
| `rerank_top_n` | `top_n` truncates the ranking to the requested size. |
| `rerank_duplicate_text` | Identical document text keeps its distinct caller-owned ids. |
| `embedding_normalization_probe` | A probe measures normalization instead of assuming it. |
| `embedding_byte_cap` | An oversized embedding response is refused, not parsed. |
| `rerank_byte_cap` | An oversized rerank response is refused, not parsed. |
| `embedding_retry_after` | A rate-limited embedding call is retried and recorded. |
| `rerank_retry_after` | A rate-limited rerank call is retried and recorded. |

## Modes

- **fake-server** — in-process transports asserting we handle each protocol *shape*. Runs on
  every commit.
- **cassette** — recorded real traffic, asserting we handle what providers *actually send*.
- **live** — opt-in, requires credentials. `m365-copilot` is exempt: its authentication is
  interactive-only and cannot run headless.

## See also

- [Provider pages](../providers/README.md) for the human-readable version.
- [Contract snapshots](https://github.com/anthturner/AnyInfer/blob/main/contracts/README.md) for the wire details each adapter depends on.
