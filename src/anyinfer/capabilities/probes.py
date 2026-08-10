"""Active capability probes: the third assembly layer, paid for in requests.

The catalog says what a model *should* support and discovery says what a provider *claims*.
Neither is a measurement, and for the compatibility surface the difference matters most —
eighty-six preset endpoints and every self-hosted OpenAI-compatible server inherit a
descriptor's default feature set, which is a reasonable guess and nothing more. A server
that accepts ``response_format`` and quietly ignores it looks identical to one that honors
it, right up until a schema silently stops being enforced.

A probe settles it by trying. Each one sends a deliberately trivial request with exactly
one mechanism forced, and reads the answer:

- the provider **rejected** it — the feature is unsupported, and that is a fact,
- the provider **honored** it — supported, also a fact,
- the provider accepted it and answered something else — **inconclusive**, because a weak
  model and an ignored parameter are indistinguishable from one reply, and guessing between
  them is exactly what the provenance model exists to prevent.

Only the first two are recorded. An inconclusive probe leaves the prior layer alone.

Probes are opt-in and priced in round trips: the default set costs four. Results are
recorded at ``probed`` provenance, which outranks catalog data and live discovery but still
loses to an application's deliberate override.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..types.capabilities import Feature, ModelCapabilities, Sourced
from ..types.requests import ResolvedTarget, ToolSpec
from ..types.results import Mechanism, Usage

__all__ = [
    "DEFAULT_PROBE_FEATURES",
    "PROBEABLE_FEATURES",
    "PROBE_MAX_OUTPUT_TOKENS",
    "PROBE_SCHEMA",
    "PROBE_TOOL",
    "FeatureProbe",
    "ProbeOutcome",
    "ProbeReport",
    "mechanism_for",
    "probe_prompt",
    "probed_features",
]

PROBEABLE_FEATURES: tuple[Feature, ...] = (
    Feature.JSON_SCHEMA,
    Feature.JSON_MODE,
    Feature.GRAMMAR,
    Feature.TOOLS,
    Feature.STREAMING,
)
"""Every feature a probe can settle.

Absent by design: ``REASONING`` (providers overwhelmingly accept the field and ignore it,
so a probe would return inconclusive nearly always), ``SYSTEM_PROMPT`` and ``CACHE_USAGE``
(no single reply distinguishes honored from ignored), and the numeric bounds — finding a
context window by bisection would cost dozens of requests to learn what one catalog entry
already says.
"""

DEFAULT_PROBE_FEATURES: tuple[Feature, ...] = (
    Feature.JSON_SCHEMA,
    Feature.JSON_MODE,
    Feature.TOOLS,
    Feature.STREAMING,
)
"""What `probe()` tests when the caller names nothing: the four an OpenAI-compatible
endpoint most often misreports. Four requests. ``GRAMMAR`` is excluded because the engines
that have it declare it accurately, so paying a request to confirm buys nothing."""

PROBE_MAX_OUTPUT_TOKENS = 64
"""Output ceiling for every probe. None of them needs a long answer to be readable."""

PROBE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "capability_probe",
    "properties": {"colour": {"type": "string"}},
    "required": ["colour"],
    "additionalProperties": False,
}
"""The probe schema: one required string, so a conforming answer is unmistakable."""

PROBE_TOOL = ToolSpec(
    name="record_colour",
    description="Record a colour the user mentioned.",
    parameters={
        "type": "object",
        "properties": {"colour": {"type": "string"}},
        "required": ["colour"],
    },
)
"""The probe tool. Trivial on purpose — a model that cannot call this cannot call anything."""

ProbeOutcome = Literal["supported", "unsupported", "inconclusive"]
"""What one probe established, if anything."""


@dataclass(frozen=True, slots=True)
class FeatureProbe:
    """The result of testing one feature against one target.

    Attributes:
        feature: The feature that was tested.
        outcome: What the attempt established.
        detail: One sentence explaining the outcome — the provider's rejection, or what
            came back instead of what was asked for.
    """

    feature: Feature
    outcome: ProbeOutcome
    detail: str = ""

    @property
    def conclusive(self) -> bool:
        """Whether this probe settled anything worth recording."""
        return self.outcome in ("supported", "unsupported")


@dataclass(frozen=True, slots=True)
class ProbeReport:
    """Everything one probing run learned, and what it cost.

    Attributes:
        target: The target that was probed.
        probes: One result per feature tested, in the order tested.
        capabilities: What to record at ``probed`` provenance, or ``None`` when nothing
            was settled. Already merged with what was known, since a feature flag is one
            value and a probe that clears a bit must not clear the others with it.
        requests: Round trips spent.
        usage: Tokens spent, summed across the probes.
    """

    target: ResolvedTarget
    probes: tuple[FeatureProbe, ...] = ()
    capabilities: ModelCapabilities | None = None
    requests: int = 0
    usage: Usage = field(default_factory=Usage)

    def outcome_for(self, feature: Feature) -> ProbeOutcome | None:
        """What was established for one feature, or ``None`` if it was not tested."""
        for probe in self.probes:
            if probe.feature is feature:
                return probe.outcome
        return None

    @property
    def summary(self) -> str:
        """One line naming what was settled."""
        supported = [p.feature.name for p in self.probes if p.outcome == "supported"]
        unsupported = [p.feature.name for p in self.probes if p.outcome == "unsupported"]
        parts = []
        if supported:
            parts.append(f"supports {', '.join(n for n in supported if n)}")
        if unsupported:
            parts.append(f"does not support {', '.join(n for n in unsupported if n)}")
        return f"{self.target}: {'; '.join(parts) or 'nothing conclusive'}"


def mechanism_for(feature: Feature) -> Mechanism | None:
    """The structured-output mechanism a feature probe must force, if any.

    Returned rather than inferred from capabilities, because the whole point of the probe
    is to test one mechanism the ladder would not otherwise choose.
    """
    mechanisms: dict[Feature, Mechanism] = {
        Feature.JSON_SCHEMA: "json_schema",
        Feature.JSON_MODE: "json_mode",
        Feature.GRAMMAR: "grammar",
    }
    return mechanisms.get(feature)


def probe_prompt(feature: Feature) -> str:
    """The request text for one probe.

    Mechanical scaffolding for a library-owned operation, like the verification probe and
    the repair re-prompt; never application prose.
    """
    if feature is Feature.TOOLS:
        return "The user mentioned the colour blue. Record it with the tool provided."
    if feature is Feature.STREAMING:
        return "Count from one to twenty in words, separated by commas. No other text."
    return 'Reply with a JSON object whose "colour" field is the string "blue".'


def probed_features(
    known: Sourced[Feature] | None, probes: tuple[FeatureProbe, ...]
) -> Sourced[Feature] | None:
    """Fold conclusive probe results into a complete feature flag.

    A probe settles one bit, but `ModelCapabilities.features` is a single value that
    overlays wholesale — recording a bare ``Feature.TOOLS`` would silently erase every
    other flag the catalog knew about. So the known set is the starting point, each
    conclusive probe sets or clears its own bit, and the result is recorded as one value.

    Args:
        known: The currently-assembled feature flag, if any.
        probes: Results from this run.

    Returns:
        The flag to record at ``probed`` provenance, or ``None`` when no probe settled
        anything and there is consequently nothing to record.
    """
    conclusive = [p for p in probes if p.conclusive]
    if not conclusive:
        return None
    value = known.value if known is not None else Feature(0)
    for probe in conclusive:
        if probe.outcome == "supported":
            value |= probe.feature
        else:
            value &= ~probe.feature
    return Sourced(value, "probed")
