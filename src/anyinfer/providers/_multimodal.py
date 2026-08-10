"""Small wire-encoding helpers shared by provider adapters."""

from __future__ import annotations

import base64
from pathlib import PurePath

from ..errors import UnsupportedInputError
from ..types.messages import AudioPart, DocumentPart, ImagePart, Message

__all__ = [
    "base64_data",
    "data_url",
    "has_multimodal",
    "media_subtype",
    "neutral_filename",
    "unsupported",
]


def data_url(media_type: str, data: bytes) -> str:
    """Encode inline bytes only at the provider projection boundary."""
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def base64_data(data: bytes) -> str:
    """Encode inline bytes for dialects that carry MIME type separately."""
    return base64.b64encode(data).decode("ascii")


def media_subtype(media_type: str, *, jpeg: bool = False) -> str:
    """Return the subtype used by media blocks, normalizing common aliases."""
    subtype = media_type.partition("/")[2].lower()
    if subtype == "jpg" and jpeg:
        return "jpeg"
    if subtype == "mpeg":
        return "mp3"
    return subtype


def neutral_filename(filename: str | None, default: str) -> str:
    """Project only a basename and keep provider-visible names neutral."""
    name = PurePath(filename or default).name
    return "".join(ch if ch.isalnum() or ch in " -()[]" else "-" for ch in name) or default


def unsupported(provider: str, modality: str, detail: str = "") -> UnsupportedInputError:
    """Build the common explicit adapter-boundary refusal."""
    suffix = f" ({detail})" if detail else ""
    return UnsupportedInputError(
        f"{provider} cannot project {modality} input{suffix}",
        provider=provider,
        hint="choose a target that supports this input form or supply supported inline bytes",
    )


def has_multimodal(messages: tuple[Message, ...]) -> bool:
    """Whether a request contains any non-text input payload."""
    return any(
        isinstance(part, ImagePart | DocumentPart | AudioPart)
        for message in messages
        for part in message.content
    )
