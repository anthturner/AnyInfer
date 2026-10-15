"""Raw observations made by the portable native execution driver."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from anyinfer.providers.base import WireRequest
from anyinfer.schema._capture import _OperationCapture
from anyinfer.types.events import StreamEvent
from anyinfer.types.messages import Message
from anyinfer.types.results import Generation

from .adapter import CleanupRecord

__all__ = ["NativeRun"]


@dataclass(frozen=True, slots=True)
class NativeRun:
    """Facts observed from one native execution; never an expected fixture outcome."""

    case_id: str
    events: tuple[StreamEvent, ...] = ()
    result: Generation | None = None
    error: BaseException | None = None
    error_stage: Literal["construction", "operation", "harness"] | None = None
    telemetry: tuple[Any, ...] = ()
    operations: tuple[_OperationCapture, ...] = ()
    requests: tuple[WireRequest, ...] = ()
    clock_advances_ms: tuple[int | float, ...] = ()
    cleanup_records: tuple[CleanupRecord, ...] = ()
    mirror: NativeRun | None = None
    construction_origin: Literal["messages", "repair", "route", "sampling"] | None = None
    input_messages: tuple[Message, ...] | None = None
    input_schema: Any = None
    consumption_mode: Literal["buffered", "stream"] | None = None
