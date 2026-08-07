"""The bounded repair loop's prompt construction.

Repair re-prompts the *same resolved target* — not the whole route — with the validation
errors appended. Re-routing on a schema violation would confound "this model can't follow the
schema" with "this endpoint is down", and would spend the fallback budget on a problem
fallback cannot fix.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..types.messages import Message, assistant, user
from .validate import format_errors

__all__ = ["REPAIR_PROMPT", "build_repair_messages"]

REPAIR_PROMPT = (
    "Your previous response did not match the required JSON schema. Errors:\n"
    "{errors}\n"
    "Respond again with ONLY a corrected JSON value that satisfies the schema. No prose, "
    "no code fences."
)
"""Template appended as a user turn when a response fails validation."""


def build_repair_messages(
    original: Sequence[Message],
    response_text: str,
    errors: tuple[str, ...],
) -> tuple[Message, ...]:
    """Extend a conversation with the failed response and a correction request.

    Args:
        original: The messages that produced the invalid response.
        response_text: The model's raw invalid output, echoed back so it can see it.
        errors: Validation error messages to cite.

    Returns:
        The conversation to send for the repair attempt.
    """
    return (
        *original,
        assistant(response_text),
        user(REPAIR_PROMPT.format(errors=format_errors(errors))),
    )
