# Multimodal Inputs

AnyInfer generation requests may contain images, documents, audio, and video alongside
text. The output is still text and tool calls; this does not add image generation, speech
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

`ImagePart`, `DocumentPart`, and `VideoPart` accept either inline `bytes` or a remote
`url`, never both. `AudioPart` accepts inline bytes. Bytes stay unencoded in the domain
model; each adapter base64-encodes them only when its wire protocol requires it.

For video the URL form is the normal path rather than a convenience: the providers that
accept video publish an upload endpoint and expect a URI back, and one of them also takes
a public video URL directly.

```python
message = ai.Message(
    role="user",
    content=(
        ai.Text("What happens at the end?"),
        ai.VideoPart(url=uploaded_file_uri, start_offset_s=30, fps=1),
    ),
)
```

`start_offset_s`, `end_offset_s`, and `fps` are request parameters rather than something
a caller does with a decoder beforehand, because providers bill for the frames they
sample and these are what decide how many there are. Leave them unset for the provider's
own defaults.

The default ceilings are 20 MiB for one inline part and 50 MiB for the whole request, and
they are **not** loosened for video — a ceiling quietly raised for one modality is a
ceiling that no longer means what its name says. `generate()` and `stream()` accept
`max_input_part_bytes` and `max_input_bytes`, so a caller sending a large clip inline
raises them deliberately. A violation is rejected before a provider call.

## Capabilities and Conservative Budgets

The [capability flags](capabilities.md) are `VISION`, `DOCUMENT`, `AUDIO_IN`, and
`VIDEO_IN`. A trusted capability record that lacks a required flag refuses the request
before dispatch. Unknown or defaulted capability data does not pretend to be an authoritative
"no"; the adapter still either projects the part or raises an explicit
unsupported-input error.

Image and document token costs depend on provider formulas, resolution, page count, and
model. When no catalog formula is available, `budget.estimate.unpriced_parts` reports
the gap and both `budget.fits` and `budget.estimated_cost` are `None`; the
[context gate](budgeting.md#the-pre-dispatch-gate) lets the request through instead of
inventing a token count.

## Frontends

The [CLI](../guides/cli.md) reads attachments in the frontend and passes bytes to the
same typed request:

```console
anyinfer run "What is important here?" --image diagram.png --document report.pdf
```

The [sidecar](../serve/README.md) preserves OpenAI message content arrays containing
`image_url`, `input_audio`, and `file` parts, subject to the same request caps. Video has
no chat-completions content type, so it travels as an
[`anyinfer_video` content item](../serve/README.md#sending-video). No attachment content
appears in [telemetry](telemetry.md), manifests, or error messages.

## Which Providers Accept What

Support varies by part type, provider, and model. The
[conformance matrix](../reference/conformance-matrix.md) records per-provider multimodal
support from actual test runs, and each provider page states its own quirks: for
example, [Ollama](../providers/ollama.md) takes inline images only, and the supervised
[llama.cpp](../providers/llama-cpp.md) path needs a catalog artifact with a pinned
projector companion. Provider contract snapshots record the wire spellings and their
verification sources.

!!! tip "Key Takeaways"
    - Parts are typed (`ImagePart`, `DocumentPart`, `AudioPart`, `VideoPart`) and
      size-capped before any provider call; adapters handle wire encoding.
    - A trusted capability record gates multimodal requests before dispatch; an unknown
      one defers to the adapter's explicit accept-or-raise.
    - Unpriceable parts make the budget honest: `fits` and `estimated_cost` go `None`
      instead of guessing.
    - Per-provider support lives in the conformance matrix, not in a hand-maintained
      list here.

## See Also

<div class="anyinfer-see-also" markdown>

- [Conformance matrix](../reference/conformance-matrix.md): per-provider multimodal
  support, from test runs.
- [Capabilities and provenance](capabilities.md): the flags that gate dispatch.
- [Token estimation and context budgets](budgeting.md): how unpriceable parts are
  reported.

</div>
