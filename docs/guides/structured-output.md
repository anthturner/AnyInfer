# Enforce a JSON Schema

Pass a schema and `result.structured` comes back already validated against it, whichever
[mechanism](../concepts/structured-output.md) the target supports:

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

`repair=ai.Repair(max_attempts=1)` allows one corrective round trip against the same
model before the call fails; see [repair](../concepts/structured-output.md#repair) for
what that costs and why it never falls back to another provider.

## Handling Failure

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
response or tighten the prompt. [Fallback](fallback.md) never fires here: the model
answered, just in the wrong shape.

## Pydantic Models Work

No pydantic dependency is added; the model is duck-typed through `model_json_schema()`:

```python
from pydantic import BaseModel


class Review(BaseModel):
    sentiment: str
    score: int


result = client.generate(prompt, target="medium", schema=Review)
parsed = Review.model_validate(result.structured)
```

## Knowing What Happened

```python
result.structured_mechanism  # "grammar" | "json_schema" | "json_mode" | "prompt"
result.repair_attempts  # 0 if the model got it right first time
```

Both are worth logging in aggregate. A model that frequently needs repair is usually a
prompt problem; a target that unexpectedly reports `"prompt"` may not be the model you
thought you configured.

!!! tip "Key Takeaways"
    - `result.structured` is validated client-side against your original schema, whatever
      mechanism the provider used to produce it.
    - A `SchemaViolationError` carries the raw text, the specific validation errors, and
      any recoverable partial members (enough to debug the prompt, not just the failure).
    - Repair is opt-in and costs an extra request per attempt; budget for it on
      latency-sensitive paths.
    - Pydantic models are accepted directly, with no pydantic dependency in the library.

## See Also

<div class="anyinfer-see-also" markdown>

- [Structured output](../concepts/structured-output.md): how the mechanism is chosen, and
  how to write schemas that work on grammar-based engines.
- [Test your application offline](testing-your-app.md): proving a repair budget converges
  with a scripted provider.

</div>
