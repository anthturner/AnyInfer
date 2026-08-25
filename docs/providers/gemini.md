---
provider: gemini
icon: material/google
---

# Google Gemini

The native `generateContent` protocol. Google's OpenAI-compatibility layer is documented
as beta and ignores parameters it does not implement, while thinking levels, response
schemas, safety settings, and context caching are native-only or better supported.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: reasoning</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: health</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery (context windows)</span>
</div>

## Setup

```python
import anyinfer as ai

client = ai.Client(
    [
        ai.ProviderSettings.of("gemini", api_key="env://GEMINI_API_KEY"),
    ]
)

result = client.generate(prompt, target="gemini:gemini-2.5-flash")
```

The key is sent as `x-goog-api-key`. `google:`, `google-gemini:`, and `ai-studio:` are
accepted as aliases of `gemini:`.

## Reasoning

Gemini names thinking *levels* rather than budgeting tokens, so the four normalized
effort levels map straight across:

```python
result = client.generate(prompt, target="gemini:gemini-2.5-pro", reasoning="high")

print(result.usage.reasoning_tokens)  # thoughts, reported separately
print(result.usage.output_tokens)  # answer + thoughts, because both bill as output
```

Gemini's own `candidatesTokenCount` excludes thoughts even though they bill at the
output rate, so AnyInfer reports `output_tokens` as the sum; cost stays right, and
`reasoning_tokens` keeps the breakdown visible.

Thinking text arrives as `ReasoningDelta` events and is excluded from `result.text`:

```python
with client.stream(prompt, target="gemini:gemini-2.5-flash", reasoning="medium") as stream:
    for event in stream:
        if isinstance(event, ai.ReasoningDelta):
            print("[thinking]", event.text, end="")
        elif isinstance(event, ai.TextDelta):
            print(event.text, end="")
```

Models that cannot disable thinking (2.5 Pro, and the Gemini 3 family) clamp a low
request upward server-side rather than failing.

## Structured Output

```python
SUMMARY = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "points": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "points"],
}

result = client.generate(article, target="gemini:gemini-2.5-flash", schema=SUMMARY)
print(result.structured["headline"])
```

Gemini's `responseSchema` accepts an OpenAPI subset, and rejects the *entire request* on
an unknown keyword. AnyInfer projects the schema down to the accepted subset before
sending (dropping things like `$schema`, `pattern`, and `unevaluatedProperties`), and
then [validates the response](../concepts/structured-output.md) against the original
schema. Some wire-level strictness is lost, never result correctness.

## Tool Calling

```python
result = client.generate(prompt, target="gemini:gemini-2.5-flash", tools=[lookup_spec])
for call in result.tool_calls:
    print(call.name, call.arguments)
```

Gemini emits complete function calls rather than streamed argument fragments, and
supports several calls in one turn. Tool results are sent back on a *user* turn as
`functionResponse` parts; the adapter handles that translation, so
[`run_tools()`](../guides/tool-loop.md) works the same as everywhere else.

## Embeddings

Gemini embeds through `batchEmbedContents`, so batches are native:

```python
result = client.embed(
    ["What is deep learning?"],
    target="gemini:gemini-embedding-2",
    dimensions=768,  # 128-3072; both models default to 3072
)
```

- The legacy `gemini-embedding-001` accepts task types, mapped from
  [`input_type`](../concepts/embeddings.md#input-intent) (`query` → `RETRIEVAL_QUERY` and
  so on). The current `gemini-embedding-2` documents no task types (prompt instructions
  replace them), so an `input_type` there is never sent and the result says so in a
  warning.
- No batch ceiling is documented, so requests above the library's
  [sanity ceiling](../concepts/embeddings.md#batching) are refused rather than split at a
  guessed size; set `BatchPolicy.max_items_override` after independently verifying a
  limit.
- There is no reranking endpoint on this API.

## Discovery

The model listing reports real limits, so context windows carry `discovered`
provenance:

```python
for model in client.models("gemini"):
    caps = model.capabilities
    if caps and caps.context_window:
        print(model.id, caps.context_window.value, caps.context_window.provenance)
```

## Reaching Native Features

Anything AnyInfer does not model (context caching, safety settings, grounded search,
numeric thinking budgets) passes straight through
[the escape hatch](README.md#reaching-provider-specific-parameters):

```python
client.generate(
    prompt,
    target="gemini:gemini-2.5-flash",
    provider_options={
        "gemini": {
            "cachedContent": "cachedContents/abc123",
            "safetySettings": [
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"}
            ],
        }
    },
)
```

## Content Filtering

A prompt Gemini blocks returns **no candidates at all**, with the reason on
`promptFeedback`. That surfaces as `finish_reason == "content_filter"` rather than an
empty successful answer, and a [`Route`](../concepts/routing.md) with
`content_policy_targets` can redirect it to a differently-governed provider.

## Multimodal Inputs

Images, documents, and audio use native `inlineData` blocks for bytes and `fileData` for
remote references. Support and limits remain model-specific.

## Wire Contract

For the exact request/response fields this adapter depends on, see
[contracts/gemini.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/gemini.md).

## See Also

<div class="anyinfer-see-also" markdown>

- [Capabilities and provenance](../concepts/capabilities.md): how discovered limits are
  ranked.
- [Routing and rate limits](../concepts/routing.md): including the content-policy
  fallback chain.
- [Google Vertex AI](vertex.md): the same models with GCP auth.

</div>
