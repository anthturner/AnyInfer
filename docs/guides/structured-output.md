# Enforce a JSON schema

```python
import anyinfer as ai

REVIEW = {
    "type": "object",
    "properties": {
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "themes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sentiment", "score", "themes"],
    "additionalProperties": False,
}

result = client.generate(
    "Analyze this review:\n" + review_text,
    target="medium",
    schema=REVIEW,
    repair=ai.Repair(max_attempts=1),
)

analysis = result.structured  # already validated against REVIEW
print(analysis["sentiment"], analysis["score"])
```

## Handling failure

```python
try:
    result = client.generate(prompt, target="medium", schema=REVIEW)
except ai.SchemaViolationError as error:
    log.warning("model produced: %s", error.raw_text)
    for message in error.errors:
        log.warning("  %s", message)
```

You get the bounded raw output, specific validation errors, and any delimiter-confirmed
complete top-level members in `error.partial`, so your application can inspect the
response or tighten the prompt.

## Pydantic models work

No pydantic dependency is added; the model is duck-typed through `model_json_schema()`:

```python
from pydantic import BaseModel


class Review(BaseModel):
    sentiment: str
    score: int


result = client.generate(prompt, target="medium", schema=Review)
parsed = Review.model_validate(result.structured)
```

## Knowing what happened

```python
result.structured_mechanism  # "grammar" | "json_schema" | "json_mode" | "prompt"
result.repair_attempts  # 0 if the model got it right first time
```

Both are worth logging in aggregate. A model that frequently needs repair is usually a
prompt problem; a target that unexpectedly reports `"prompt"` may not be the model you
thought you configured.

## Repair costs a request

`Repair(max_attempts=1)` allows one corrective round trip against the **same** model — never
a different provider ([why](../concepts/structured-output.md#repair)). Budget for it on
latency-sensitive paths.

## Writing schemas that work everywhere

Grammar-based engines (llama.cpp, Ollama) compile your schema into a decoding grammar, where
a few keywords are expensive:

- `minLength` / `maxLength` on strings are stripped **for the wire**.
- `minItems` / `maxItems` of 2000 or more are stripped **for the wire**.

Both are still enforced by client-side validation, so nothing you asked for is lost. But if
a local model keeps failing a length constraint, that is why, and clearer prompt wording
will help more than a tighter constraint.

Two things that improve results under every mechanism: prefer `enum` over free-form strings,
and keep nesting shallow.

See [structured output](../concepts/structured-output.md) for how the mechanism is chosen.
