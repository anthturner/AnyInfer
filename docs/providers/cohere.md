---
provider: cohere
icon: material/hexagon-multiple
---

# Cohere

The native v2 Chat API, chosen over the OpenAI compatibility layer because v2 is where
the things worth choosing Cohere for live: grounded generation with document citations, a
separate thinking channel, and usage that distinguishes what was processed from what was
billed.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: reasoning</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery (context lengths)</span>
</div>

## Setup

```python
import anyinfer as ai

client = ai.Client(
    [
        ai.ProviderSettings.of("cohere", api_key="env://CO_API_KEY"),
    ]
)

result = client.generate(prompt, target="cohere:command-a-03-2025")
```

## Dialect differences

Cohere's API diverges from the OpenAI shape in ways the adapter normalizes, but which
show up if you reach past it with `provider_options`:

| AnyInfer | Cohere |
|---|---|
| `finish_reason == "stop"` | `COMPLETE` (uppercase enum) |
| `tool_choice="required"` | `"REQUIRED"`; there is no way to name one tool |
| `Sampling(top_p=...)` | `p`, not `top_p` |
| optional streaming | `stream` is **required** on every request |

Unknown finish reasons normalize to `"other"` rather than propagating.

## Reasoning

Cohere budgets thinking in tokens, so normalized effort maps to a budget: `minimal`
disables thinking, and `low`/`medium`/`high` map to increasing token budgets. Thinking
blocks arrive as `ReasoningDelta` events on the
[event stream](../concepts/events.md) and stay out of `result.text`.

```python
result = client.generate(prompt, target="cohere:command-a-03-2025", reasoning="high")
```

## Usage accounting

Cohere reports both `billed_units` and `tokens`. AnyInfer's counts follow `tokens` —
what the model actually processed, which is what a context window measures:

```python
result = client.generate(prompt, target="cohere:command-a-03-2025")
print(result.usage.input_tokens)  # processed
```

If you need billed units for cost reconciliation, build the client with `retain_raw=True`
and read them off `result.raw`.

## Grounded generation

```python
client.generate(
    question,
    target="cohere:command-a-03-2025",
    provider_options={
        "cohere": {
            "documents": [{"id": "doc1", "data": {"text": "..."}}],
            "citation_options": {"mode": "ACCURATE"},
        }
    },
)
```

Document grounding and citations are reachable through the
[escape hatch](README.md#reaching-provider-specific-parameters). Citations are not yet
surfaced as typed results; read them from `result.raw` until they are modeled.

## Embeddings and reranking

Cohere serves both operations natively (`POST /v2/embed`, `POST /v2/rerank`), and is the
first provider here with native [input intents](../concepts/embeddings.md#input-intent)
and native rerank scores:

```python
docs = client.embed(
    ["the cat sat on the mat", "stock markets rallied"],
    target="cohere:embed-v4.0",
    input_type="document",
)
ranked = client.rerank(
    "where did the cat sit",
    ["stock markets rallied", "the cat sat on the mat"],
    target="cohere:rerank-v3.5",
    top_n=1,
)
```

Three things worth knowing:

- **`input_type` is required.** Cohere's embed API demands an intent and documents no
  default, so an intent-less `embed()` is refused with a hint rather than guessed —
  query and document embeddings are not comparable unless produced with matching
  intents.
- **Batching engages at 96 inputs.** The endpoint accepts at most 96 texts per call;
  larger requests are [split by the core](../concepts/embeddings.md#batching) and
  re-assembled in input order, invisibly. Requested `dimensions` are forwarded as
  `output_dimension` (embed-v4 models only).
- **Rerank usage is search units, not tokens.** Live rerank responses report only
  `billed_units.search_units`, which AnyInfer never encodes as fake token counts — so
  `result.usage` is typically empty for rerank. The billed units are on
  `result.raw["meta"]["billed_units"]` for cost reconciliation.

## Discovery

The model listing reports real context lengths, so windows carry
[`discovered` provenance](../concepts/capabilities.md#the-five-provenances):

```python
for model in client.models("cohere"):
    caps = model.capabilities
    if caps and caps.context_window:
        print(model.id, caps.context_window.value, caps.context_window.provenance)
```

Every model is listed — embedding and rerank models included — with its operations
derived from the listing's `endpoints` field, so `client.models("cohere",
operation="embedding")` answers from discovery rather than a guess.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/cohere.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/cohere.md).

## See also

<div class="anyinfer-see-also" markdown>

- [Structured output](../concepts/structured-output.md): how the schema mechanism is chosen.

</div>
