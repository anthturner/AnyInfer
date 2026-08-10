"""Capability types with provenance tagging.

Every capability value records *where it came from* so consumers know how much to trust it.
An estimate is never presented as authoritative: a value assembled from a bundled catalog is
``"catalog"``, one read from a provider's model listing is ``"discovered"``, one measured by
an opt-in probe is ``"probed"``, and a descriptor-level fallback is ``"default"``. A value
the integrating application set deliberately is ``"override"`` — it outranks everything,
because a user's explicit correction must never lose to data the library merely collected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import Flag, auto
from typing import Generic, Literal, TypeVar

__all__ = [
    "DiscoveredModel",
    "Feature",
    "Health",
    "LocalModelInfo",
    "ModelCapabilities",
    "Pricing",
    "Provenance",
    "RateLimitHeaders",
    "Sourced",
    "TokenCalibration",
    "conjunction",
]

Provenance = Literal["catalog", "discovered", "probed", "default", "override"]
"""Where a capability value came from, weakest (``default``) to strongest (``override``)."""

_PROVENANCE_RANK: dict[Provenance, int] = {
    "default": 0,
    "catalog": 1,
    "discovered": 2,
    "probed": 3,
    "override": 4,
}


_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class Sourced(Generic[_T]):
    """A capability value paired with its provenance."""

    value: _T
    provenance: Provenance = "default"

    def outranks(self, other: Sourced[_T] | None) -> bool:
        """Whether this value's provenance is at least as strong as ``other``'s."""
        if other is None:
            return True
        return _PROVENANCE_RANK[self.provenance] >= _PROVENANCE_RANK[other.provenance]


@dataclass(frozen=True, slots=True)
class TokenCalibration:
    """How much a provider's own envelope inflates the prompt it is sent.

    Serialized request bytes are not what every provider counts. Some wrap the caller's
    messages in a transport of their own before the model ever sees them — a session API
    that prepends its harness, a tool scaffold, a service-side system preamble, and then
    bill (and window-check) the inflated total. Estimating such a provider from message
    bytes alone under-counts every request, and the under-count is systematic rather than
    noise, so budgets stay optimistic right up to the overflow.

    A provider therefore declares its own correction, and only the planning figure moves:

    - `multiplier` scales content that grows with the prompt.
    - `overhead_tokens` adds what the envelope costs regardless of prompt size.

    Neither touches the estimate's floor. The floor exists to *refuse* requests before
    dispatch, and a lower bound may only claim tokens the provider certainly charges —
    envelope overhead is a correction we believe, not one we can prove.

    Attributes:
        multiplier: Factor applied to the planning estimate of prompt-proportional
            content. ``1.0`` means the provider counts what was sent.
        overhead_tokens: Flat tokens the envelope adds per request, counted once.
    """

    multiplier: float = 1.0
    overhead_tokens: int = 0

    def __post_init__(self) -> None:
        """Reject calibrations that would corrupt every estimate downstream.

        Raises:
            ValueError: If the multiplier is not a positive finite number, or the
                overhead is negative.
        """
        if not math.isfinite(self.multiplier) or self.multiplier <= 0:
            raise ValueError("token calibration multiplier must be a positive finite number")
        if self.overhead_tokens < 0:
            raise ValueError("token calibration overhead must not be negative")

    @property
    def is_identity(self) -> bool:
        """Whether this calibration leaves an estimate unchanged."""
        return self.multiplier == 1.0 and self.overhead_tokens == 0


@dataclass(frozen=True, slots=True)
class RateLimitHeaders:
    """Which response headers a provider reports its rate-limit state in.

    Header names are wire facts and differ per provider, so they are declared on the
    descriptor and recorded in that provider's contract snapshot; never branched on by
    provider id in the core.

    A provider whose dialect cannot be verified from its documentation declares nothing.
    An empty dialect is not a failure: pacing falls back to whatever bounds the caller
    configured, which is a smaller promise honestly kept rather than a guessed header name
    that silently reads `None` forever.

    Attributes:
        requests_remaining: Requests left in the current window.
        requests_reset: When the request window resets. Read as seconds, or as a duration
            like ``"1m30s"`` for the providers that spell it that way.
        tokens_remaining: Tokens left in the current window.
        tokens_reset: When the token window resets, in the same two spellings.
        limit_requests: The window's full request allowance, when the provider states it.
            Only needed to turn ``reserve_fraction`` into an absolute floor.
        limit_tokens: The window's full token allowance, for the same reason.
    """

    requests_remaining: str = ""
    requests_reset: str = ""
    tokens_remaining: str = ""
    tokens_reset: str = ""
    limit_requests: str = ""
    limit_tokens: str = ""

    @property
    def declared(self) -> bool:
        """Whether this provider reports anything worth reading."""
        return bool(
            self.requests_remaining
            or self.requests_reset
            or self.tokens_remaining
            or self.tokens_reset
        )


class Feature(Flag):
    """Capabilities a model may support.

    Structured-output mechanism selection reads these in the order
    ``GRAMMAR > JSON_SCHEMA > JSON_MODE > prompt injection``.

    ``CACHE_USAGE`` and ``CACHE_PLACEMENT`` are deliberately separate facts: reporting what
    the prompt cache did is not the same as accepting instructions about where it should
    apply, and a provider may do either without the other.
    """

    STREAMING = auto()
    JSON_SCHEMA = auto()
    GRAMMAR = auto()
    JSON_MODE = auto()
    TOOLS = auto()
    REASONING = auto()
    SYSTEM_PROMPT = auto()
    CACHE_USAGE = auto()
    CACHE_PLACEMENT = auto()
    VISION = auto()
    DOCUMENT = auto()
    AUDIO_IN = auto()


@dataclass(frozen=True, slots=True)
class Pricing:
    """Per-million-token pricing used to compute `cost_usd`.

    Cache rates are optional and default to unknown rather than to the input rate. A
    provider that discounts cached prompt tokens but whose discount we have not recorded
    must not be billed as though the discount were zero *or* as though it were free — an
    unknown rate leaves cached tokens priced as ordinary input, which is the same answer
    this library gave before cache accounting existed, and is wrong in only one direction
    that a caller can reason about.

    Attributes:
        input_per_1m: Price per one million prompt tokens.
        output_per_1m: Price per one million generated tokens.
        cache_read_per_1m: Price per one million prompt tokens served from the provider's
            cache, or ``None`` when the rate is not recorded.
        cache_write_per_1m: Price per one million prompt tokens written into the cache, or
            ``None`` when the rate is not recorded. Several providers charge a *premium*
            for a write, so this is not assumed to be a discount.
        currency: Currency code the prices are quoted in.
    """

    input_per_1m: Decimal
    output_per_1m: Decimal
    cache_read_per_1m: Decimal | None = None
    cache_write_per_1m: Decimal | None = None
    currency: str = "USD"


@dataclass(frozen=True, slots=True)
class LocalModelInfo:
    """Facts about a local model artifact, used for tuning and recommendation.

    Attributes:
        artifact_size_bytes: On-disk size of the model weights.
        parameter_size: Parameter count as the runtime reports it (e.g. ``"7B"``).
        quantization: Quantization scheme of the artifact (e.g. ``"Q4_K_M"``).
        est_ram_bytes: Estimated system memory needed to run the model.
        est_vram_bytes: Estimated GPU memory needed to run the model.
        observed_vram_bytes: GPU memory actually measured in use while the model was
            loaded, when the runtime reports it.
    """

    artifact_size_bytes: int | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    est_ram_bytes: int | None = None
    est_vram_bytes: int | None = None
    observed_vram_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """What a model can do, as far as we know.

    Attributes:
        context_window: Maximum tokens of input context, with provenance; ``None`` when
            unknown.
        max_output_tokens: Maximum tokens one response may contain, with provenance;
            ``None`` when unknown.
        features: Which `Feature` flags the model supports, with provenance.
        pricing: Per-million-token pricing, when known.
        default_temperature: The temperature this provider applies when a request sends
            none, with provenance; ``None`` when the provider does not document one.
        default_top_p: The nucleus-sampling cutoff this provider applies when a request
            sends none, with provenance; ``None`` when undocumented.
        local: Facts about the local artifact, for locally-run models only.

    The two sampling defaults exist so an application can say *what* "provider default"
    means instead of only that it is one. They are populated from a provider's own
    documentation and nowhere else; never probed, never inferred from a sibling
    provider, never carried over from a model family. A provider whose documentation
    states no default keeps ``None`` indefinitely, and that is the correct final state for
    it rather than a gap waiting to be filled: an invented number presented beside a
    provenance tag is precisely the estimate-as-authority this type exists to prevent.
    """

    context_window: Sourced[int] | None = None
    max_output_tokens: Sourced[int] | None = None
    features: Sourced[Feature] = Sourced(Feature(0), "default")
    pricing: Sourced[Pricing] | None = None
    default_temperature: Sourced[float] | None = None
    default_top_p: Sourced[float] | None = None
    local: LocalModelInfo | None = None

    def overlay(self, other: ModelCapabilities) -> ModelCapabilities:
        """Layer ``other`` on top of this, field by field, stronger provenance winning.

        This is the assembly rule: later layers override earlier ones, but a
        weaker-provenance value never displaces a stronger one.
        """
        return ModelCapabilities(
            context_window=_stronger(self.context_window, other.context_window),
            max_output_tokens=_stronger(self.max_output_tokens, other.max_output_tokens),
            features=_stronger(self.features, other.features) or self.features,
            pricing=_stronger(self.pricing, other.pricing),
            default_temperature=_stronger(self.default_temperature, other.default_temperature),
            default_top_p=_stronger(self.default_top_p, other.default_top_p),
            local=other.local if other.local is not None else self.local,
        )


def _stronger(current: Sourced[_T] | None, incoming: Sourced[_T] | None) -> Sourced[_T] | None:
    if incoming is None:
        return current
    return incoming if incoming.outranks(current) else current


def conjunction(candidates: list[ModelCapabilities]) -> ModelCapabilities:
    """Tightest bound across candidate models — the ``auto``-sentinel rule.

    When a provider delegates model choice at request time (GitHub Copilot's ``"auto"``), the
    only safe capability claim is the conjunction: the minimum of each numeric bound and the
    intersection of feature flags. Provenance degrades to the weakest contributor.

    Sampling defaults are deliberately **not** reduced: they are omitted from the result.
    The minimum of two candidates' default temperatures is not a fact about anything — a
    delegating provider does not apply "the lowest default among the models it might
    pick", it applies whichever model's default it ends up using. Reporting a computed
    number there would be a guess wearing a provenance tag, which is the one thing this
    module refuses to produce.

    Args:
        candidates: Capabilities of every model the provider might pick.

    Returns:
        Capabilities guaranteed to hold whichever candidate is chosen. An empty candidate
        list yields fully-unknown capabilities.
    """
    if not candidates:
        return ModelCapabilities()

    context = _min_sourced([c.context_window for c in candidates])
    max_out = _min_sourced([c.max_output_tokens for c in candidates])

    features = candidates[0].features.value
    provenance = candidates[0].features.provenance
    for cap in candidates[1:]:
        features &= cap.features.value
        provenance = _weaker(provenance, cap.features.provenance)

    return ModelCapabilities(
        context_window=context,
        max_output_tokens=max_out,
        features=Sourced(features, provenance),
        pricing=None,
        default_temperature=None,
        default_top_p=None,
        local=None,
    )


def _min_sourced(values: list[Sourced[int] | None]) -> Sourced[int] | None:
    known = [v for v in values if v is not None]
    if not known or len(known) != len(values):
        # An unknown bound makes the conjunction unknown — we cannot promise a minimum.
        return None
    best = min(known, key=lambda s: s.value)
    provenance = best.provenance
    for other in known:
        provenance = _weaker(provenance, other.provenance)
    return Sourced(best.value, provenance)


def _weaker(a: Provenance, b: Provenance) -> Provenance:
    return a if _PROVENANCE_RANK[a] <= _PROVENANCE_RANK[b] else b


@dataclass(frozen=True, slots=True)
class Health:
    """Result of a provider's cheap readiness probe.

    Attributes:
        ok: Whether the provider answered its readiness probe successfully.
        detail: Short human-readable explanation, most useful when ``ok`` is false.
    """

    ok: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class DiscoveredModel:
    """A model reported by a provider's listing endpoint.

    ``capabilities`` carries only fields the provider actually reported; the capability
    assembler tags them ``"discovered"``.

    Attributes:
        id: The model identifier exactly as the provider lists it.
        capabilities: Capability fields the listing reported; ``None`` when the provider
            lists ids only.
    """

    id: str
    capabilities: ModelCapabilities | None = None
