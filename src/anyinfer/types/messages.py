"""Message and content-part types.

The conversation model is deliberately small: a `Message` is a role plus an ordered
tuple of content parts. Multimodal parts are reserved for a future version; v1 models text,
tool calls, and tool results only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "ContentPart",
    "Message",
    "Role",
    "Text",
    "ToolCall",
    "ToolResult",
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


ContentPart = Text | ToolCall | ToolResult
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
