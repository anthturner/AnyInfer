---
provider: bedrock
icon: material/aws
---

# AWS Bedrock

The **Converse** API — Bedrock's unified interface, where one request shape serves Claude,
Nova, Llama, Mistral, and DeepSeek alike. That normalization is exactly what AnyInfer
wants, so `InvokeModel` and its per-model request bodies are never used.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: reasoning</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: cache accounting</span>
</div>

## Setup

Two ways to authenticate. A **Bedrock API key** is the simplest:

```python
import anyinfer as ai

client = ai.Client([
    ai.ProviderSettings.of(
        "bedrock",
        api_key="env://AWS_BEARER_TOKEN_BEDROCK",
        options={"region": "us-east-1"},
    ),
])

result = client.generate(prompt, target="bedrock:us.anthropic.claude-sonnet-4-5")
```

Or **AWS credentials**, which are SigV4-signed per request:

```python
ai.ProviderSettings.of("bedrock", options={"region": "us-west-2"})
```

With no explicit key, credentials are resolved in order: explicit `aws_access_key_id` /
`aws_secret_access_key` options, then `boto3`'s chain if you have it installed (it knows
about SSO caches, instance metadata, and profiles), then `AWS_ACCESS_KEY_ID` and friends
from the environment. Neither `boto3` nor any other SDK is a dependency — signing is
implemented against the standard library.

`aws-bedrock:` and `amazon-bedrock:` are accepted aliases.

## Model ids

Bedrock accepts base model ids, inference-profile ids, and full ARNs. Cross-region
inference profiles carry a region prefix:

```python
client.generate(prompt, target="bedrock:us.anthropic.claude-sonnet-4-5")
client.generate(prompt, target="bedrock:amazon.nova-pro-v1:0")
```

Model ids containing colons work as targets — the target grammar splits on the *first*
colon only, so everything after `bedrock:` is the model.

## Streaming is binary

`ConverseStream` answers with AWS's `vnd.amazon.eventstream` framing and offers no SSE or
JSON alternative. AnyInfer decodes it — including verifying both frame checksums — so
from your side it is an ordinary stream:

```python
with client.stream(prompt, target="bedrock:us.anthropic.claude-sonnet-4-5") as stream:
    for event in stream:
        if isinstance(event, ai.TextDelta):
            print(event.text, end="", flush=True)
    print(stream.result.usage.input_tokens)
```

!!! note "Why usage only appears at the end"

    Bedrock sends token counts **only** in the terminal `metadata` event, after
    `messageStop`. A client that stopped at the stop reason would report zero tokens for
    every request; AnyInfer reads through to the metadata frame.

## Structured output

Converse has no response-format field, so a schema is emulated as a single **forced tool
call** — the same approach the Anthropic adapter takes, because the API genuinely
constrains tool input:

```python
result = client.generate(article, target="bedrock:amazon.nova-pro-v1:0", schema=SUMMARY)
print(result.structured["headline"])
print(result.structured_mechanism)   # "json_schema"
```

## Reasoning

Converse has no reasoning parameter of its own; extended thinking is a model-specific
field, so normalized effort travels in `additionalModelRequestFields`:

```python
result = client.generate(prompt, target="bedrock:us.anthropic.claude-sonnet-4-5",
                         reasoning="high")
```

Thinking text arrives as `ReasoningDelta` events and stays out of `result.text`. Models
without extended thinking ignore the field.

## Reaching model-specific parameters

Anything Converse does not model — Claude's `top_k`, guardrail configuration, a service
tier — passes through:

```python
client.generate(
    prompt,
    target="bedrock:us.anthropic.claude-sonnet-4-5",
    provider_options={"bedrock": {
        "additionalModelRequestFields": {"top_k": 40},
        "guardrailConfig": {"guardrailIdentifier": "gr-123", "guardrailVersion": "1"},
    }},
)
```

## Discovery and health

Discovery reads the Bedrock **control plane**, a different host than the runtime. An
account without `bedrock:ListFoundationModels` gets an empty list rather than an error — a
permission gap should not make the provider look broken.

Health deliberately makes no network call at all: every runtime endpoint costs a
generation, and the control plane may be denied by policy even when inference works
perfectly. It reports whether credentials are present.

## Pricing

Bedrock prices per model and per region, and inference profiles differ from base models.
The bundled table carries the common `us-east-1` on-demand rates for the Nova family and
Claude; use `capability_overrides` where your account's rates differ.

## See also

<div class="anyinfer-see-also" markdown>

- [Contract snapshot](https://github.com/anthturner/anyinfer/blob/main/contracts/bedrock.md)
- [Anthropic](anthropic.md) — Claude direct, without the Bedrock layer.
- [Routing](../concepts/routing.md) — retries and fallback across regions or providers.

</div>
