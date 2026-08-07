---
provider: gemini
icon: material/google
---

# Google Gemini

The **native** `generateContent` protocol, not Google's OpenAI-compatibility layer. That
layer is documented as beta and silently ignores parameters it does not implement, while
thinking levels, response schemas, safety settings, and context caching are native-only
or better supported.

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

client = ai.Client([
    ai.ProviderSettings.of("gemini", api_key="env://GEMINI_API_KEY"),
])

result = client.generate(prompt, target="gemini:gemini-2.5-flash")
```

The key is sent as `x-goog-api-key`. `google:`, `google-gemini:`, and `ai-studio:` are
accepted as aliases of `gemini:`.

## Thinking

Gemini names thinking *levels* rather than budgeting tokens, so the four normalized
effort levels map straight across:

```python
result = client.generate(prompt, target="gemini:gemini-2.5-pro", reasoning="high")

print(result.usage.reasoning_tokens)   # thoughts, reported separately
print(result.usage.output_tokens)      # answer + thoughts, because both bill as output
```

Thinking text arrives as `ReasoningDelta` events and is excluded from `result.text`:

```python
with client.stream(prompt, target="gemini:gemini-2.5-flash", reasoning="medium") as stream:
    for event in stream:
        if isinstance(event, ai.ReasoningDelta):
            print("[thinking]", event.text, end="")
        elif isinstance(event, ai.TextDelta):
            print(event.text, end="")
```

!!! note "Why output tokens include thoughts"

    Gemini's `candidatesTokenCount` **excludes** thinking tokens, but thinking bills at
    the output rate. AnyInfer reports `output_tokens` as the sum, so cost is right;
    `reasoning_tokens` keeps the breakdown visible.

Models that cannot disable thinking (2.5 Pro, and the Gemini 3 family) clamp a low
request upward server-side rather than failing.

## Structured output

```python
SUMMARY = {
    "type": "object",
    "properties": {"headline": {"type": "string"}, "points": {
        "type": "array", "items": {"type": "string"}}},
    "required": ["headline", "points"],
}

result = client.generate(article, target="gemini:gemini-2.5-flash", schema=SUMMARY)
print(result.structured["headline"])
```

Gemini's `responseSchema` accepts an OpenAPI subset, and rejects the *entire request* on
an unknown keyword. AnyInfer projects your schema down to the accepted subset before
sending — dropping things like `$schema`, `pattern`, and `unevaluatedProperties` — and
then validates the response against your **original** schema. You lose some
wire-level strictness, never result correctness.

## Tool calling

```python
result = client.generate(prompt, target="gemini:gemini-2.5-flash", tools=[lookup_spec])
for call in result.tool_calls:
    print(call.name, call.arguments)
```

Gemini emits complete function calls rather than streamed argument fragments, and
supports several calls in one turn. Tool results are sent back on a *user* turn as
`functionResponse` parts — the adapter handles that translation, so
[`run_tools()`](../guides/tool-loop.md) works the same as everywhere else.

## Discovery

The model listing reports real limits, so context windows carry `discovered`
provenance:

```python
for model in client.models("gemini"):
    caps = model.capabilities
    if caps and caps.context_window:
        print(model.id, caps.context_window.value, caps.context_window.provenance)
```

## Reaching native features

Anything AnyInfer does not model — context caching, safety settings, grounded search,
numeric thinking budgets — passes straight through:

```python
client.generate(
    prompt,
    target="gemini:gemini-2.5-flash",
    provider_options={"gemini": {
        "cachedContent": "cachedContents/abc123",
        "safetySettings": [
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"}
        ],
    }},
)
```

## Content filtering

A prompt Gemini blocks returns **no candidates at all**, with the reason on
`promptFeedback`. That surfaces as `finish_reason == "content_filter"` rather than an
empty successful answer — and a [`Route`](../concepts/routing.md) with
`content_policy_targets` can redirect it to a differently-governed provider.

## See also

<div class="anyinfer-see-also" markdown>

- [Contract snapshot](https://github.com/anthturner/anyinfer/blob/main/contracts/gemini.md)
  — the exact wire details this adapter depends on.
- [Capabilities and provenance](../concepts/capabilities.md) — how discovered limits are
  ranked.
- [Routing](../concepts/routing.md) — including the content-policy fallback chain.

</div>
