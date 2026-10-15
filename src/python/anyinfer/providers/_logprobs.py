"""Parsing for the one log-probability wire shape the hosted dialects share.

OpenAI's chat-completions and Responses APIs, and every preset built on the former,
report log-probabilities as the same entry object — ``token``, ``logprob``, optional
``bytes``, optional ``top_logprobs`` — differing only in where the list of entries hangs.
So the entry parser lives here once rather than in each adapter that reads one.

Every function is defensive by construction: a provider that reports a malformed entry
degrades to fewer entries, never to an exception. Log-probabilities are advisory output —
losing one must not fail a generation that otherwise succeeded.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..types.results import TokenLogprob

__all__ = ["parse_logprob_entries", "parse_openai_logprobs"]


def parse_openai_logprobs(container: Any) -> tuple[TokenLogprob, ...]:
    """Read a chat-completions ``logprobs`` object.

    Args:
        container: The choice's ``logprobs`` value, whatever the provider sent.

    Returns:
        The parsed tokens in generation order; empty when the shape is not the expected
        ``{"content": [...]}``.
    """
    if not isinstance(container, Mapping):
        return ()
    return parse_logprob_entries(container.get("content"))


def parse_logprob_entries(entries: Any) -> tuple[TokenLogprob, ...]:
    """Read a bare list of log-probability entries.

    Args:
        entries: The list as the provider sent it. Anything else yields no tokens.

    Returns:
        The parsed tokens in list order, skipping any entry without both a string token
        and a numeric log-probability.
    """
    if not isinstance(entries, list):
        return ()
    return tuple(_iter_entries(entries))


def _iter_entries(entries: Iterable[Any]) -> Iterable[TokenLogprob]:
    """Yield one `TokenLogprob` per well-formed entry, skipping the rest."""
    for entry in entries:
        parsed = _parse_entry(entry, with_top=True)
        if parsed is not None:
            yield parsed


def _parse_entry(entry: Any, *, with_top: bool) -> TokenLogprob | None:
    """Parse one entry, or ``None`` when it lacks the two required fields.

    ``with_top`` is False for the alternatives themselves: providers do not nest
    ``top_logprobs`` inside ``top_logprobs``, and refusing to recurse means a provider
    that someday does cannot turn one response into unbounded parsing work.
    """
    if not isinstance(entry, Mapping):
        return None
    token = entry.get("token")
    logprob = entry.get("logprob")
    if not isinstance(token, str) or not isinstance(logprob, int | float):
        return None
    if isinstance(logprob, bool):  # bool is an int subclass; a boolean is not a logprob
        return None
    top: tuple[TokenLogprob, ...] = ()
    if with_top:
        raw_top = entry.get("top_logprobs")
        if isinstance(raw_top, list):
            top = tuple(
                parsed
                for parsed in (_parse_entry(item, with_top=False) for item in raw_top)
                if parsed is not None
            )
    return TokenLogprob(
        token=token,
        logprob=float(logprob),
        top=top,
        bytes=_parse_bytes(entry.get("bytes")),
    )


def _parse_bytes(raw: Any) -> tuple[int, ...] | None:
    """Read a token's byte list, or ``None`` when the provider omitted a usable one."""
    if not isinstance(raw, list):
        return None
    values = tuple(
        b for b in raw if isinstance(b, int) and not isinstance(b, bool) and 0 <= b < 256
    )
    return values if len(values) == len(raw) else None
