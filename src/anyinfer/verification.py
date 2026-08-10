"""The end-to-end verification probe: one bounded request that proves a target works.

A health probe answers "can I reach this endpoint". That is not the question an operator
is asking when they press *Test connection*, because everything a health probe touches can
be fine while the thing they actually want — an answer from a model — still fails:

- the credential is valid for the listing endpoint and not for inference,
- the model id is a typo, and only generation says so,
- the deployment exists but has no capacity,
- the provider answers, but never in the shape a schema asked for.

So this probe spends one real request, deliberately tiny, and reports what happened in
enough detail to act on: whether the provider answered at all, whether it answered
*correctly*, which model actually served it, how long it took, and anything the provider
wants to say about its own runtime.

**On the prompt.** The library does not write application prose (a stated non-goal), and
this does not change that: the text below is mechanical scaffolding for a library-owned
operation, the same category as the schema-repair re-prompt. Nothing here is reachable by
an application's own generation path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types.requests import ResolvedTarget
from .types.results import Diagnostic, Mechanism, Usage

__all__ = [
    "VERIFY_MAX_OUTPUT_TOKENS",
    "VERIFY_PROMPT",
    "VERIFY_REASONING_OUTPUT_TOKENS",
    "VERIFY_SCHEMA",
    "Verification",
    "excerpt",
    "judge_reply",
]

VERIFY_PROMPT = (
    "This is an automated connection test. Reply with the single word OK in the "
    '"reply" field, and nothing else.'
)
"""The probe prompt: short enough to cost nothing, explicit enough to grade."""

VERIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "connection_test",
    "properties": {"reply": {"type": "string"}},
    "required": ["reply"],
    "additionalProperties": False,
}
"""The probe schema.

Deliberately trivial, and deliberately *present*: carrying a schema exercises the
provider's structured-output mechanism, so a target that generates fine but cannot hold a
shape is distinguishable from one that works — see `Verification.reached`.
"""

VERIFY_MAX_OUTPUT_TOKENS = 64
"""Output ceiling for the probe. A target that needs more than this to say OK has failed."""

VERIFY_REASONING_OUTPUT_TOKENS = 256
"""Output ceiling for the probe when the target is known to be a reasoning model.

A thinking model spends its output budget on reasoning *before* it produces the answer, so
64 tokens buys a truncated thought and an empty reply, which the probe then reports as
"the provider answered with empty text", pointing an operator at a connection problem they
do not have.

This is a ceiling, not a spend: a model that answers in six tokens spends six whichever
value applies, and the larger cap costs more only for a model that would have been
truncated, which is to say, one that was going to fail the probe anyway. That is why it
is applied on a mere feature flag rather than on a trusted one, and why it is still not
applied to targets with no reasoning flag at all: an unbounded probe is not the goal.

Four times the ordinary ceiling, which is enough headroom for the short deliberation a
one-word connection test provokes. Raise it if a real reasoning target is found to
overrun it; do not raise it speculatively.
"""

_EXCERPT_CHARS = 160


@dataclass(frozen=True, slots=True)
class Verification:
    """What one end-to-end probe of a target found.

    Never raised, always returned: "this target is broken" is the answer to the question,
    not a failure to answer it. The two booleans are deliberately separate, because
    "unreachable" and "reachable but cannot hold a schema" call for completely different
    fixes.

    Attributes:
        target: What the target string resolved to, and — for a provider that picks the
            model itself, which model actually served the request.
        ok: The provider answered, in the shape asked for, with the expected content.
        reached: The provider answered *at all*. ``True`` with ``ok`` false means the
            connection and credential are fine and the model's output was not.
        latency_ms: Wall-clock time for the whole probe, including any retry the route
            performed. Indicative only — one request is not a benchmark.
        detail: What went wrong, or empty when nothing did.
        reply: A bounded excerpt of what came back, for a human to look at.
        mechanism: The structured-output mechanism actually used, when one was.
        usage: Tokens the probe spent, as the provider reported them.
        diagnostics: Anything the provider said about its own runtime while serving this.
    """

    target: ResolvedTarget | None
    ok: bool
    reached: bool = False
    latency_ms: float = 0.0
    detail: str = ""
    reply: str = ""
    mechanism: Mechanism | None = None
    usage: Usage = field(default_factory=Usage)
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def summary(self) -> str:
        """One line suitable for a status area or a CLI."""
        name = str(self.target) if self.target is not None else "target"
        if self.ok:
            return f"{name} answered in {self.latency_ms:.0f} ms"
        return f"{name} failed: {self.detail}" if self.detail else f"{name} failed"


def excerpt(text: str) -> str:
    """Collapse and truncate provider text for display."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= _EXCERPT_CHARS:
        return collapsed
    return f"{collapsed[:_EXCERPT_CHARS].rstrip()}…"


def judge_reply(structured: Any, text: str) -> tuple[bool, str, str]:
    """Grade what came back from the probe.

    Lenient about *packaging* and strict about *content*: a model that says "OK!" or
    "Ok, ready" has demonstrably understood and served the request, and failing it over
    punctuation would send an operator hunting for a problem that is not there. A model
    that says something else entirely has not.

    Args:
        structured: The validated structured answer, when the request produced one.
        text: The raw response text.

    Returns:
        Whether it passed, an explanation when it did not, and the excerpt to show.
    """
    reply = ""
    if isinstance(structured, dict):
        candidate = structured.get("reply")
        if isinstance(candidate, str):
            reply = candidate
    if not reply:
        reply = text

    shown = excerpt(reply)
    if not reply.strip():
        return False, "the provider answered with empty text", shown
    if not _says_ok(reply):
        return False, f'the provider answered without "OK": {shown}', shown
    return True, "", shown


def _says_ok(reply: str) -> bool:
    """Whether ``OK`` appears as a word, ignoring case and surrounding punctuation."""
    normalized = "".join(
        char if char.isalnum() or char.isspace() else " " for char in reply.casefold()
    )
    return "ok" in normalized.split()
