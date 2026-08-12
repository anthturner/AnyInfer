"""Conversation persistence: one JSON file per conversation, no secrets or raw payloads.

A `Conversation` stores the messages that make up the transcript plus a *summary* of
each generation result — target, timing, usage, finish reason; never the provider's raw
response body. That keeps the on-disk format small, diffable, and safe to share.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anyinfer.types.messages import (
    AudioPart,
    ContentPart,
    DocumentPart,
    ImagePart,
    Message,
    Role,
    Text,
    ToolCall,
    ToolResult,
)
from anyinfer.types.results import Generation

__all__ = ["Conversation", "GenerationSummary", "conversations_dir", "gist_title"]

_SCHEMA_VERSION = 1
_TITLE_MAX_CHARS = 40


def conversations_dir(config_dir: Path) -> Path:
    """Where per-conversation JSON files live, given the demo's config directory."""
    return config_dir / "conversations"


@dataclass(frozen=True, slots=True)
class GenerationSummary:
    """A redacted, summary-only record of one completed generation."""

    target: str
    finish_reason: str
    total_ms: float
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: str | None
    attempts: int

    @classmethod
    def from_result(cls, result: Generation) -> GenerationSummary:
        """Summarize a `Generation`, dropping raw payloads."""
        return cls(
            target=str(result.target),
            finish_reason=result.finish_reason,
            total_ms=result.timing.total_ms,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cost_usd=str(result.usage.cost_usd) if result.usage.cost_usd is not None else None,
            attempts=len(result.attempts),
        )

    def to_json(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible mapping."""
        return {
            "target": self.target,
            "finish_reason": self.finish_reason,
            "total_ms": self.total_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "attempts": self.attempts,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> GenerationSummary:
        """Rebuild from a persisted mapping."""
        return cls(
            target=str(data.get("target", "")),
            finish_reason=str(data.get("finish_reason", "other")),
            total_ms=float(data.get("total_ms", 0.0)),
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
            cost_usd=data.get("cost_usd"),
            attempts=int(data.get("attempts", 0)),
        )


@dataclass(frozen=True, slots=True)
class Conversation:
    """One saved chat: its messages, plus summaries of each generation result."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: tuple[Message, ...] = ()
    results: tuple[GenerationSummary, ...] = ()

    @classmethod
    def new(cls) -> Conversation:
        """A fresh, untitled conversation."""
        now = datetime.now(UTC)
        return cls(id=str(uuid.uuid4()), title="New chat", created_at=now, updated_at=now)

    def with_messages(self, messages: Sequence[Message]) -> Conversation:
        """Return a copy with the transcript replaced and the title re-derived."""
        now = datetime.now(UTC)
        return replace(
            self,
            messages=tuple(messages),
            title=_derive_title(messages) if self.title == "New chat" else self.title,
            updated_at=now,
        )

    def with_result(self, result: Generation) -> Conversation:
        """Append one generation's summary."""
        return replace(
            self,
            results=(*self.results, GenerationSummary.from_result(result)),
            updated_at=datetime.now(UTC),
        )

    def renamed(self, title: str) -> Conversation:
        """Return a copy with an explicit, user-chosen title."""
        return replace(self, title=title, updated_at=datetime.now(UTC))

    # ---- serialization -----------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible mapping."""
        return {
            "schema_version": _SCHEMA_VERSION,
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "messages": [_message_to_json(m) for m in self.messages],
            "results": [r.to_json() for r in self.results],
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Conversation:
        """Rebuild from a persisted mapping, migrating older schema versions if needed."""
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            title=str(data.get("title", "New chat")),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
            messages=tuple(
                _message_from_json(m) for m in data.get("messages", []) if isinstance(m, Mapping)
            ),
            results=tuple(
                GenerationSummary.from_json(r)
                for r in data.get("results", [])
                if isinstance(r, Mapping)
            ),
        )

    def save(self, directory: Path) -> Path:
        """Write this conversation to ``directory / '{id}.json'``."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.id}.json"
        path.write_text(json.dumps(self.to_json(), indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> Conversation | None:
        """Read one conversation file, or ``None`` if it is missing or corrupt."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, Mapping):
            return None
        return cls.from_json(data)

    @classmethod
    def load_all(cls, directory: Path) -> list[Conversation]:
        """Every conversation in ``directory``, newest first; corrupt files are skipped."""
        if not directory.is_dir():
            return []
        loaded = [cls.load(p) for p in directory.glob("*.json")]
        conversations = [c for c in loaded if c is not None]
        conversations.sort(key=lambda c: c.updated_at, reverse=True)
        return conversations

    def delete(self, directory: Path) -> None:
        """Remove this conversation's file, if present."""
        path = directory / f"{self.id}.json"
        path.unlink(missing_ok=True)

    def to_markdown(self) -> str:
        """A simple Markdown transcript, for human-readable export."""
        lines = [f"# {self.title}", ""]
        for message in self.messages:
            speaker = {"user": "You", "assistant": "Assistant", "system": "System"}.get(
                message.role, message.role
            )
            lines.append(f"**{speaker}:**")
            lines.append("")
            lines.append(message.text or "*(no text content)*")
            lines.append("")
        return "\n".join(lines)


def _word_set(words: str) -> frozenset[str]:
    return frozenset(words.split())


_FLUFF_WORDS = _word_set(
    "please can could would you kindly hey hi hello i we want need like to me my "
    "help just maybe some"
)
"""Leading filler that carries no topic. 'Build' and 'Spec' survive; 'please can you'
does not."""

_STOP_WORDS = _word_set(
    "a an the that this those these i we you it is are was be been being of in on at "
    "for with and or so then them they my your our me can could should would will "
    "do does did have has had there here what which who how why when"
)
"""Grammar words dropped from the middle of a gist."""

_GIST_MAX_WORDS = 6


def gist_title(text: str, *, max_chars: int = 40) -> str:
    """Condense a first message into a short tab title.

    Deliberately a deterministic heuristic, not a model call: naming a chat by asking
    the model would silently spend a request per conversation, and against the offline
    fake every title would be the same canned sentence. The rules are simple — first
    line only, leading filler dropped, grammar words removed, the first few content
    words kept: "Build me a retro 486 that I can play Commander Keen on" becomes
    "Build Retro 486 Play Commander Keen".
    """
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    words = [w.strip(".,!?;:\"'()") for w in first_line.split()]
    words = [w for w in words if w]
    while words and words[0].lower() in _FLUFF_WORDS:
        words.pop(0)
    content = [w for w in words if w.lower() not in _STOP_WORDS]
    if not content:
        content = words
    picked = content[:_GIST_MAX_WORDS]
    # Title-case plain lowercase words; leave anything with its own casing (486, JSON,
    # McCarthy) alone.
    shaped = [w if w != w.lower() or not w.isalpha() else w.capitalize() for w in picked]
    title = " ".join(shaped) or "New chat"
    return title if len(title) <= max_chars else title[: max_chars - 1] + "…"


def _derive_title(messages: Sequence[Message]) -> str:
    for message in messages:
        if message.role == "user" and message.text.strip():
            text = message.text.strip().replace("\n", " ")
            return text if len(text) <= _TITLE_MAX_CHARS else text[: _TITLE_MAX_CHARS - 1] + "…"
    return "New chat"


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(UTC)


def _message_to_json(message: Message) -> dict[str, Any]:
    return {"role": message.role, "content": [_part_to_json(p) for p in message.content]}


def _part_to_json(part: ContentPart) -> dict[str, Any]:
    if isinstance(part, Text):
        return {"kind": "text", "text": part.text}
    if isinstance(part, ToolCall):
        return {
            "kind": "tool_call",
            "id": part.id,
            "name": part.name,
            "arguments": dict(part.arguments),
        }
    if isinstance(part, ImagePart | DocumentPart | AudioPart):
        # The demo's transcript store is intentionally payload-free. A future attachment
        # picker can own a separate asset store; silently embedding binary request data in
        # conversation JSON would violate the existing persistence contract.
        return {"kind": "attachment_omitted", "media_type": part.media_type}
    if isinstance(part, ToolResult):
        return {
            "kind": "tool_result",
            "call_id": part.call_id,
            "content": part.content,
            "is_error": part.is_error,
        }
    raise TypeError(f"unsupported conversation content part: {type(part).__name__}")


def _message_from_json(data: Mapping[str, Any]) -> Message:
    raw_role = data.get("role")
    role: Role = raw_role if raw_role in ("system", "user", "assistant", "tool") else "user"
    parts = tuple(_part_from_json(p) for p in data.get("content", []) if isinstance(p, Mapping))
    return Message(role=role, content=parts)


def _part_from_json(data: Mapping[str, Any]) -> ContentPart:
    kind = data.get("kind")
    if kind == "tool_call":
        return ToolCall(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            arguments=dict(data.get("arguments", {})),
        )
    if kind == "tool_result":
        return ToolResult(
            call_id=str(data.get("call_id", "")),
            content=str(data.get("content", "")),
            is_error=bool(data.get("is_error", False)),
        )
    if kind == "attachment_omitted":
        return Text(f"[attachment omitted: {data.get('media_type', 'unknown')}]")
    return Text(str(data.get("text", "")))
