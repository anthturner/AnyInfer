# Multimodal inputs

AnyInfer generation requests may contain images, documents, and audio alongside text.
The output is still text and tool calls — this does not add image generation, speech
output, transcription, or another inference API.

```python
from pathlib import Path

import anyinfer as ai

message = ai.Message(
    role="user",
    content=(
        ai.Text("Explain this diagram and summarize the report."),
        ai.ImagePart(data=Path("diagram.png").read_bytes(), media_type="image/png"),
        ai.DocumentPart(
            data=Path("report.pdf").read_bytes(),
            media_type="application/pdf",
            filename="report.pdf",
        ),
    ),
)
result = client.generate(message, target="openai:gpt-5.6")
```

`ImagePart` and `DocumentPart` accept either inline `bytes` or a remote `url`, never
both. `AudioPart` accepts inline bytes. Bytes stay unencoded in the domain model; each
adapter base64-encodes them only when its wire protocol requires it.

The default ceilings are 20 MiB for one inline part and 50 MiB for the whole request.
`generate()` and `stream()` accept `max_input_part_bytes` and `max_input_bytes` for a
tighter bound. A violation is rejected before a provider call.

## Capabilities and conservative budgets

The [capability flags](capabilities.md) are `VISION`, `DOCUMENT`, and `AUDIO_IN`. A
trusted capability record that lacks a required flag refuses the request before
dispatch. Unknown or defaulted capability data does not pretend to be an authoritative
"no"; the adapter still either projects the part or raises an explicit
unsupported-input error.

Image and document token costs depend on provider formulas, resolution, page count, and
model. When no catalog formula is available, `budget.estimate.unpriced_parts` reports
the gap and both `budget.fits` and `budget.estimated_cost` are `None` — the
[context gate](budgeting.md#the-pre-dispatch-gate) lets the request through instead of
inventing a token count.

## Frontends

The [CLI](../guides/cli.md) reads attachments in the frontend and passes bytes to the
same typed request:

```console
anyinfer run "What is important here?" --image diagram.png --document report.pdf
```

The [sidecar](../serve/README.md) preserves OpenAI message content arrays containing
`image_url`, `input_audio`, and `file` parts, subject to the same request caps. No
attachment content appears in [telemetry](telemetry.md), manifests, or error messages.

## Which providers accept what

Support varies by part type, provider, and model. The
[conformance matrix](../reference/conformance-matrix.md) records per-provider multimodal
support from actual test runs, and each provider page states its own quirks — for
example, [Ollama](../providers/ollama.md) takes inline images only, and the supervised
[llama.cpp](../providers/llama-cpp.md) path needs a catalog artifact with a pinned
projector companion. Provider contract snapshots record the wire spellings and their
verification sources.

!!! tip "Key takeaways"
    - Parts are typed (`ImagePart`, `DocumentPart`, `AudioPart`) and size-capped before
      any provider call; adapters handle wire encoding.
    - A trusted capability record gates multimodal requests before dispatch; an unknown
      one defers to the adapter's explicit accept-or-raise.
    - Unpriceable parts make the budget honest — `fits` and `estimated_cost` go `None`
      instead of guessing.
    - Per-provider support lives in the conformance matrix, not in a hand-maintained
      list here.

## See also

<div class="anyinfer-see-also" markdown>

- [Conformance matrix](../reference/conformance-matrix.md): per-provider multimodal
  support, from test runs.
- [Capabilities and provenance](capabilities.md): the flags that gate dispatch.
- [Token estimation and context budgets](budgeting.md): how unpriceable parts are
  reported.

</div>
