# Enforce a JSON Schema

Pass a schema and `result.structured` comes back already validated against it, whichever
[mechanism](../concepts/structured-output.md) the target supports:

=== "Python"

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

=== "C# SDK (prerelease)"

    ```csharp
    --8<-- "examples/csharp-sdk/StructuredOutputExample.cs"
    ```

The C# source passes a [`SchemaSpec`](/csharp/api/anyinfer.schemaspec/) and deserializes the
validated result into its `AnswerResult` record. The C# recipes below are executed offline by
the example runner; the schema dialects and native numeric and regular-expression limits are
under [native C# schema limits](#native-c-schema-limits).

`repair=ai.Repair(max_attempts=1)` in Python, or `new Repair(MaxAttempts: 1)` in C#, allows one
corrective round trip against the same model before the call fails; see
[repair](../concepts/structured-output.md#repair) for what that costs and why it never falls
back to another provider. Either SDK also accepts a client-wide default repair budget, and
a provider can declare a lower ceiling.

## Deserialize into a Record {#deserialize-into-a-record}

In C#, `Generation.Structured` holds the validated value as an `AnyInfer.Json.JsonValue`.
`DeserializeStructured<T>()` turns it into your own type with `System.Text.Json`, and an
overload that takes a `JsonTypeInfo<T>` serves source-generated serialization:

```csharp
--8<-- "examples/csharp-sdk/StructuredRecordExample.cs:record"
```

Validation runs against the schema, not against your record, so keep the two in agreement.
`DeserializeStructured<T>` applies ordinary `System.Text.Json` rules: a member the JSON lacks
receives its default value rather than failing, unless the record marks it `[JsonRequired]`.
On a generation requested without a schema, `DeserializeStructured<T>` throws
`InvalidOperationException`.

## Handling Failure

=== "Python"

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

=== "C#"

    ```csharp
    --8<-- "examples/csharp-sdk/StructuredRecordExample.cs:failure"
    ```

    `SchemaViolationException.Issues` names up to five failing rules, such as `maximum` or
    `required`. The C# exception does not carry the model's raw text or recovered partial
    members. An [observer](csharp-sdk.md#observe-telemetry-and-manifests) subscribed with
    `payloads: true` receives each answer that triggered a repair round trip as the
    `RawText` of a `RepairAttempted` event.

[Fallback](fallback.md) never fires here: the model answered, just in the wrong shape. Once
the repair budget is spent, the call fails on that target even when its route lists others.

## Pydantic Models Work in Python {#pydantic-models-work}

The Python SDK accepts a Pydantic model as the schema. No pydantic dependency is added; the
model is duck-typed through `model_json_schema()`:

```python
from pydantic import BaseModel


class Review(BaseModel):
    sentiment: str
    score: int


result = client.generate(prompt, target="medium", schema=Review)
parsed = Review.model_validate(result.structured)
```

Pydantic input is Python-only. In C#, write the JSON Schema as a `SchemaSpec` and deserialize
the validated value into a record, as in [Deserialize into a Record](#deserialize-into-a-record).

## Knowing What Happened

=== "Python"

    ```python
    result.structured_mechanism  # "grammar" | "json_schema" | "json_mode" | "prompt"
    result.repair_attempts  # 0 if the model got it right first time
    ```

=== "C#"

    ```csharp
    --8<-- "examples/csharp-sdk/StructuredRecordExample.cs:mechanism"
    ```

    `Generation.StructuredMechanism` uses the same names, and `Generation.RepairAttempts` is 0
    when the first answer was valid. The generic OpenAI-compatible descriptor declares no
    native schema mechanism, so its targets report `prompt`.

Both are worth logging in aggregate. A model that frequently needs repair is usually a
prompt problem; a target that unexpectedly reports `"prompt"` may not be the model you
thought you configured.

## Native C# Schema Limits {#native-c-schema-limits}

The C# SDK validates with its own native evaluator. It accepts Draft 6, Draft 7, Draft 2019-09,
and Draft 2020-12 schemas, and a schema without `$schema` is evaluated as Draft 2020-12; Draft 3
and Draft 4 are not supported. Regular expressions are .NET regular expressions with a bounded
timeout per match, and `format` is an annotation, not an assertion. Schema input and generated
values keep arbitrary-size integers, but numeric `const`, `enum`, and `uniqueItems` comparisons
use .NET `decimal`, so a value outside that range, such as `1e70`, raises a controlled
`SchemaEvaluationException`. Registered resources and external retrieval are explicit through
`SchemaValidationOptions`. The [C# reference](../reference/csharp-sdk.md) keeps the complete
list of native limits.

!!! tip "Key Takeaways"
    - The structured result is validated client-side against your original schema, whatever
      mechanism the provider used to produce it.
    - A schema violation carries the specific validation failures (enough to debug the prompt,
      not just the failure); Python's `SchemaViolationError` also carries the raw text and
      recoverable partial members.
    - Repair is opt-in and costs an extra request per attempt; budget for it on
      latency-sensitive paths.
    - Python accepts Pydantic models directly, with no pydantic dependency in the library; C#
      deserializes the validated value into your record.

## See Also

<div class="anyinfer-see-also" markdown>

- [Structured output](../concepts/structured-output.md): how the mechanism is chosen, and
  how to write schemas that work on grammar-based engines.
- [Test your application offline](testing-your-app.md): proving a repair budget converges
  with a scripted provider.

</div>
