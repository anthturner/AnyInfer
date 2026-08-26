"""Message and content-part types.

The conversation model is deliberately small: a `Message` is a role plus an ordered
tuple of typed text, tool, image, document, audio, and video input parts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "AudioPart",
    "ContentPart",
    "DocumentPart",
    "ImagePart",
    "Message",
    "Role",
    "Text",
    "ToolCall",
    "ToolResult",
    "VideoPart",
    "assistant",
    "system",
    "user",
]

Role = Literal["system", "user", "assistant", "tool"]
"""Who authored a message."""


@dataclass(frozen=True, slots=True)
class Text:
    """A run of plain text within a message."""

    text: str


@dataclass(frozen=True, slots=True)
class ImagePart:
    """An image supplied inline or by remote URL for a multimodal model."""

    data: bytes | None = None
    url: str | None = None
    media_type: str = "image/png"
    detail: Literal["auto", "low", "high"] | None = None

    def __post_init__(self) -> None:
        """Require exactly one source and an image media type."""
        if (self.data is None) == (self.url is None):
            raise ValueError("ImagePart requires exactly one of data or url")
        if not self.media_type.startswith("image/"):
            raise ValueError("ImagePart media_type must start with 'image/'")
        if self.detail not in (None, "auto", "low", "high"):
            raise ValueError("ImagePart detail must be auto, low, or high")


@dataclass(frozen=True, slots=True)
class DocumentPart:
    """A document supplied inline or by remote URL for a capable model."""

    data: bytes | None = None
    url: str | None = None
    media_type: str = "application/pdf"
    filename: str | None = None

    def __post_init__(self) -> None:
        """Require exactly one source and a non-empty media type."""
        if (self.data is None) == (self.url is None):
            raise ValueError("DocumentPart requires exactly one of data or url")
        if not self.media_type:
            raise ValueError("DocumentPart media_type must not be empty")


@dataclass(frozen=True, slots=True)
class AudioPart:
    """Inline audio input for a multimodal model."""

    data: bytes
    media_type: str = "audio/wav"

    def __post_init__(self) -> None:
        """Require bytes and an audio media type."""
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("AudioPart data must be non-empty bytes")
        if not self.media_type.startswith("audio/"):
            raise ValueError("AudioPart media_type must start with 'audio/'")


@dataclass(frozen=True, slots=True)
class VideoPart:
    """A video supplied inline or by provider-hosted URI for a capable model.

    Unlike `AudioPart`, a URL form is not a convenience here — it is the normal path.
    Video is the one modality whose realistic payloads dwarf a request body: the providers
    that accept it publish an upload endpoint and expect a URI back, and one of them also
    accepts a public video URL directly. Inline bytes are supported for short clips and are
    bounded by the same per-part and per-request ceilings as every other inline payload
    (`GenerationRequest.max_input_part_bytes`), which is deliberately *not* raised for
    video: a ceiling quietly loosened for one modality is a ceiling that no longer means
    what its name says. A caller sending a large clip inline raises the request's own
    ceiling and thereby says so.

    Attributes:
        data: Inline video bytes, or ``None`` when the video is referenced by URI.
        url: Provider-hosted URI or public video URL, or ``None`` for inline bytes.
        media_type: IANA media type; must be a ``video/*`` subtype.
        start_offset_s: Where to begin reading the video, in seconds. ``None`` means the
            beginning. Clipping is a *request* parameter rather than something the caller
            does with a decoder, because the providers bill for the frames they sample and
            the clip bounds are what decide how many there are.
        end_offset_s: Where to stop reading, in seconds; ``None`` means the end.
        fps: Frames per second to sample at. ``None`` leaves the provider's own default,
            which is what almost every caller wants — the field exists because raising it
            for a fast-moving clip, or lowering it for a screen recording, changes both
            the answer and the bill.
    """

    data: bytes | None = None
    url: str | None = None
    media_type: str = "video/mp4"
    start_offset_s: float | None = None
    end_offset_s: float | None = None
    fps: float | None = None

    def __post_init__(self) -> None:
        """Require exactly one source, a video media type, and a sane clip window.

        Raises:
            ValueError: If both or neither source is given, the media type is not
                ``video/*``, an offset is negative, the window ends before it starts, or
                the frame rate is not positive.
        """
        if (self.data is None) == (self.url is None):
            raise ValueError("VideoPart requires exactly one of data or url")
        if not self.media_type.startswith("video/"):
            raise ValueError("VideoPart media_type must start with 'video/'")
        for name in ("start_offset_s", "end_offset_s"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"VideoPart {name} must not be negative")
        if (
            self.start_offset_s is not None
            and self.end_offset_s is not None
            and self.end_offset_s <= self.start_offset_s
        ):
            raise ValueError("VideoPart end_offset_s must be after start_offset_s")
        if self.fps is not None and self.fps <= 0:
            raise ValueError("VideoPart fps must be positive")


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A model's request to invoke a tool.

    Attributes:
        id: Provider-assigned call id. Adapters synthesize ``"call_0"``, ``"call_1"``… when
            the provider omits one, so downstream correlation always has a key.
        name: The tool being called.
        arguments: Parsed JSON arguments. An unparseable argument payload yields ``{}`` and
            a warning on the `Generation`.
    """

    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """The outcome of executing a tool call, fed back to the model.

    Attributes:
        call_id: Id of the `ToolCall` this result answers.
        content: The tool's output, rendered as text for the model to read.
        is_error: Whether the tool failed; the content then describes the failure.
    """

    call_id: str
    content: str
    is_error: bool = False


ContentPart = Text | ToolCall | ToolResult | ImagePart | DocumentPart | AudioPart | VideoPart
"""A single piece of message content."""


@dataclass(frozen=True, slots=True)
class Message:
    """One turn in a conversation.

    Attributes:
        role: Who authored the turn.
        content: Ordered parts making up the turn — text runs, tool calls, and tool
            results.
    """

    role: Role
    content: tuple[ContentPart, ...]

    @property
    def text(self) -> str:
        """Concatenation of this message's `Text` parts."""
        return "".join(p.text for p in self.content if isinstance(p, Text))


def user(text: str) -> Message:
    """Build a user message from plain text."""
    return Message(role="user", content=(Text(text),))


def system(text: str) -> Message:
    """Build a system message from plain text."""
    return Message(role="system", content=(Text(text),))


def assistant(text: str) -> Message:
    """Build an assistant message from plain text."""
    return Message(role="assistant", content=(Text(text),))
