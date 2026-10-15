"""Session reuse: letting a provider keep what it already knows.

Every request in this library is independent by default, which is the right default and
the wrong one for a conversation. Providers that can carry state between turns each do it
differently, and each saves something different:

- **GitHub Copilot** keeps the conversation server-side, so a resumed session does not
  re-send prior turns at all.
- **llama.cpp** keeps a supervised server and its KV cache resident, so a continued
  conversation does not pay a model load or re-prefill a prefix it already has.
- **Ollama** keeps the model resident via ``keep_alive``, which is the same saving minus
  the conversation.

What those share is not a protocol; it is a *shape*. The caller says "these requests belong
together", and a provider that can exploit that does. So a `Session` is an opaque handle
rather than a conversation object: the library never interprets what a provider stores in
it, and never pretends a provider kept something it did not.

Three properties keep the abstraction honest:

- **A session never changes an answer.** It is a performance and cost optimization. A
  provider that ignores it produces exactly the result it would have produced anyway, which
  is why passing one to a stateless provider is allowed and merely reported as unsupported.
- **A session is bound to one target.** Provider state is not portable, so a session used
  against another provider — after a fallback, say — silently does not apply to that turn
  rather than sending one provider's handle to another.
- **The provider decides.** `reuse` reports what actually happened on the last turn, not
  what was hoped for: a resumed session that the provider had already expired reports
  ``"fresh"``.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import Any, Literal

from .errors import ConfigError
from .types.requests import ResolvedTarget

__all__ = ["Session", "SessionReuse"]

SessionReuse = Literal["fresh", "resumed", "unsupported"]
"""What happened on the most recent turn.

``fresh`` — the provider started new state (the first turn, or one it had expired).
``resumed`` — the provider continued state it already held.
``unsupported`` — nothing was reused, because this provider cannot or this turn went
somewhere else.
"""


class Session:
    """A handle threading related requests through one provider's own state.

    Obtained from `session()`, passed to
    `generate()` or `stream()`, and threaded forward by the caller. Mutable by design —
    it is a handle, like a stream, not a domain value, and updated in place after each
    turn so a caller can keep passing the same object.

    ```python
    with client.session("copilot:auto") as chat:
        first = client.generate("Summarize this report.", session=chat)
        follow = client.generate("Now list the risks.", session=chat)
        chat.reuse      # 'resumed' — the provider kept the conversation
    ```

    Closing stops the handle being used; it does not reach out to the provider. Server-side
    state expires on the provider's own schedule, and a library that pretended otherwise
    would be making a promise it cannot keep.
    """

    def __init__(self, target: ResolvedTarget, *, supported: bool) -> None:
        self._target = target
        self._supported = supported
        self._state: Mapping[str, Any] = {}
        self._reuse: SessionReuse = "unsupported" if not supported else "fresh"
        self._turns = 0
        self._closed = False

    @property
    def target(self) -> ResolvedTarget:
        """The provider and model this session's state belongs to."""
        return self._target

    @property
    def supported(self) -> bool:
        """Whether this provider declares it can keep state between requests.

        ``False`` is not an error: the session is inert, every request behaves exactly as
        it would without one, and `reuse` says so on every turn.
        """
        return self._supported

    @property
    def reuse(self) -> SessionReuse:
        """What happened on the most recent turn."""
        return self._reuse

    @property
    def turns(self) -> int:
        """How many requests have been made with this session."""
        return self._turns

    @property
    def active(self) -> bool:
        """Whether the provider is currently holding state for this session."""
        return bool(self._state) and not self._closed

    @property
    def state(self) -> Mapping[str, Any]:
        """The provider's opaque continuation data.

        Exposed for diagnostics and persistence, never interpreted by the core. Its
        contents are the provider's business and may change between releases of *that*
        provider, so treat it as a token rather than a structure.
        """
        return dict(self._state)

    @property
    def closed(self) -> bool:
        """Whether this handle has been closed."""
        return self._closed

    def applies_to(self, target: ResolvedTarget) -> bool:
        """Whether this session's state may be sent to ``target``.

        Provider state is not portable: after a fallback to another provider, or a
        different model on the same one, the stored handle means nothing there.
        """
        return (
            self._supported
            and not self._closed
            and target.provider_id == self._target.provider_id
            and target.model == self._target.model
        )

    def close(self) -> None:
        """Stop using this handle. Idempotent."""
        self._closed = True

    def __enter__(self) -> Session:
        """Enter a context that closes the handle on exit."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the handle."""
        self.close()

    async def __aenter__(self) -> Session:
        """Enter an async context that closes the handle on exit."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the handle."""
        self.close()

    def __repr__(self) -> str:
        """Show the target, turn count, and last reuse outcome."""
        return (
            f"Session(target={self._target!s}, turns={self._turns}, "
            f"reuse={self._reuse!r}{', closed' if self._closed else ''})"
        )

    # ---- core-facing plumbing ---------------------------------------------------------

    def _ensure_usable(self) -> None:
        """Reject a closed handle before it reaches a provider.

        Raises:
            ConfigError: If the session has been closed.
        """
        if self._closed:
            raise ConfigError(
                "this session has been closed",
                hint="open a new one with client.session(target)",
            )

    def _record(self, state: Mapping[str, Any] | None, *, applied: bool) -> None:
        """Absorb what a turn reported, updating the reuse verdict.

        Args:
            state: Continuation data the adapter wants remembered, or ``None`` when it
                reported none.
            applied: Whether this session's state was actually offered to the provider —
                false when the turn went to a target the session does not cover.
        """
        self._turns += 1
        if not applied:
            self._reuse = "unsupported"
            return
        had_state = bool(self._state)
        if state is not None:
            self._state = dict(state)
        self._reuse = "resumed" if had_state and self._state else "fresh"
