"""Message coercion and the shared spend-precheck flag.

A leaf module so the mixins split out of `async_client.py` can use these without
importing the client back — `async_client` imports them, never the reverse.

`MessagesInput` is part of the public surface and is re-exported from `async_client`,
so callers see no change from the move.
"""

from __future__ import annotations

import contextvars
from collections.abc import Sequence

from ..types.messages import Message, user

__all__ = ["MessagesInput"]


MessagesInput = str | Message | Sequence[Message]
"""What callers may pass as ``messages``: a bare prompt, one message, or a sequence."""

_spend_prechecked: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "anyinfer_spend_prechecked", default=False
)

def _coerce_messages(value: MessagesInput) -> tuple[Message, ...]:
    """Normalize the accepted message spellings into a tuple."""
    if isinstance(value, str):
        return (user(value),)
    if isinstance(value, Message):
        return (value,)
    return tuple(value)
