# Multimodal inputs

AnyInfer generation requests may contain images, documents, and audio alongside text. The
output is still text and tool calls; this does not add image generation, speech output,
transcription, or another inference API.

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

`ImagePart` and `DocumentPart` accept either inline `bytes` or a remote `url`, never both.
`AudioPart` accepts inline bytes. Bytes stay unencoded in the domain model; each adapter
base64-encodes them only when its wire protocol requires that.

The default ceilings are 20 MiB for one inline part and 50 MiB for the whole request.
`generate()` and `stream()` accept `max_input_part_bytes` and `max_input_bytes` when an
application needs a tighter bound. A violation is rejected before a provider call.

## Capabilities and conservative budgets

The capability flags are `VISION`, `DOCUMENT`, and `AUDIO_IN`. A trusted capability record
that lacks a required flag refuses the request before dispatch. Unknown or defaulted
capability data does not pretend to be an authoritative “no”; the adapter still either
projects the part or raises an explicit unsupported-input error.

Image and document token costs depend on provider formulas, resolution, page count, and
model. When no catalog formula is available, `budget.estimate.unpriced_parts` reports the
gap and both `budget.fits` and `budget.estimated_cost` are `None`. The context gate lets the
request through instead of inventing a token count.

## Frontends

The CLI reads attachments in the frontend and passes bytes to the same typed request:

```console
anyinfer run "What is important here?" --image diagram.png --document report.pdf
```

The sidecar preserves OpenAI message content arrays containing `image_url`, `input_audio`,
and `file` parts. Inline data must be valid base64 and is subject to the same request caps.
No attachment content appears in telemetry, manifests, or error messages.

## Current projection coverage

- OpenAI Responses: images, files, and model-dependent audio input.
- OpenAI-compatible Chat Completions: standard image, file, and audio content shapes;
  actual support remains service- and model-specific.
- Anthropic Messages: images and PDF documents; audio is refused.
- Gemini/Vertex generateContent: inline and file-referenced images, documents, and audio.
- Bedrock Converse: inline or S3-referenced image/document blocks and audio blocks, subject
  to the selected model's supported features.
- Ollama native chat: inline base64 images; documents, audio, and remote image URLs are
  refused.
- Supervised llama.cpp: images work when the catalog artifact includes a pinned projector
  companion. The bundled Qwen2.5-VL artifact includes its verified projector; custom vision
  entries must pin both files. Documents and audio are refused.
- Cohere, Copilot, and Microsoft 365 Copilot: multimodal inputs are explicitly unavailable
  until their exact runtime path is represented and verified.

Provider contract snapshots record the wire spellings and their verification sources.
