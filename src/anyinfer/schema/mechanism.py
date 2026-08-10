"""Structured-output mechanism selection.

The ladder is ``grammar > json_schema > json_mode > prompt``: always take the strongest
mechanism the model is *known* to support. Unknown capabilities fall to the weakest rung —
prompt injection works everywhere, so an unknown model degrades into something that still
produces a validated result rather than a hard failure.
"""

from __future__ import annotations

from ..types.capabilities import Feature, ModelCapabilities
from ..types.results import Mechanism

__all__ = [
    "MECHANISM_LADDER",
    "SCHEMA_PROMPT_TEMPLATE",
    "choose_mechanism",
    "system_prompt_for",
]

MECHANISM_LADDER: tuple[tuple[Feature, Mechanism], ...] = (
    (Feature.GRAMMAR, "grammar"),
    (Feature.JSON_SCHEMA, "json_schema"),
    (Feature.JSON_MODE, "json_mode"),
)
"""The native rungs, strongest first.

Public because explaining a choice needs the same table that made it: a run manifest
reports which rungs were rejected and why, and a second copy of this tuple would be a
second answer to drift away from the first. ``prompt`` is not a rung here — it is what is
left when every rung fails, and it is always available.
"""

SCHEMA_PROMPT_TEMPLATE = (
    "Respond with ONLY a JSON value matching this JSON Schema. No prose. Schema:\n{schema}"
)
"""Injected into the system prompt for the ``prompt`` and ``json_mode`` mechanisms."""


def choose_mechanism(caps: ModelCapabilities | None) -> Mechanism:
    """Pick the strongest structured-output mechanism the model supports.

    Args:
        caps: Assembled capabilities, or ``None`` when nothing is known.

    Returns:
        The chosen mechanism. ``"prompt"`` when no native mechanism is known to work.
    """
    features = caps.features.value if caps is not None else Feature(0)
    for feature, mechanism in MECHANISM_LADDER:
        if feature in features:
            return mechanism
    return "prompt"


def system_prompt_for(schema_json: str) -> str:
    """Build the schema instruction injected for prompt-based mechanisms."""
    return SCHEMA_PROMPT_TEMPLATE.format(schema=schema_json)
