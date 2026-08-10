"""Token estimation for preflight budgeting.

No tokenizer dependency ships in the core: the default estimator is a byte-count
heuristic, and anything more accurate — tiktoken, a provider's count-tokens endpoint,
llama-server's ``/tokenize`` — plugs in through the `TokenEstimator` protocol.

Every estimate is two numbers, not one. `TokenEstimate.tokens` is a deliberately
*high* planning figure (callers deciding how much context still fits should err small), and
`TokenEstimate.floor` is a lower bound the true count is not realistically below.
The pre-dispatch gate (`anyinfer.capabilities.gating`) acts only on the floor, because
refusing a request that would actually have fit is worse than paying one failed round trip
— the two consumers of an estimate need opposite biases, so both are carried.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Protocol

from ..types.capabilities import TokenCalibration
from ..types.messages import (
    AudioPart,
    DocumentPart,
    ImagePart,
    Message,
    Text,
    ToolCall,
    ToolResult,
)
from ..types.requests import GenerationRequest

__all__ = [
    "ESTIMATE_BYTES_PER_TOKEN",
    "FLOOR_BYTES_PER_TOKEN",
    "PER_MESSAGE_OVERHEAD_TOKENS",
    "HeuristicTokenEstimator",
    "RequestEstimate",
    "TokenEstimate",
    "TokenEstimator",
    "estimate_request",
]

ESTIMATE_BYTES_PER_TOKEN = 3
"""UTF-8 bytes per token for the planning estimate.

Real text averages nearer 4, so dividing by 3 overestimates — the right direction for a
number used to decide how much more context fits.
"""

FLOOR_BYTES_PER_TOKEN = 8
"""UTF-8 bytes per token for the lower bound.

Even whitespace-heavy code and multi-space runs, which tokenizers pack aggressively,
average well under 8 bytes per token, so dividing by 8 underestimates — the right
direction for a number used to *refuse* a request before dispatch.
"""

PER_MESSAGE_OVERHEAD_TOKENS = 4
"""Wire-framing tokens charged per message (role markers, separators) on chat endpoints.

Counted in the planning estimate only, never in the floor: the exact framing cost varies
by dialect, and the floor must not claim tokens a provider might not charge.
"""


@dataclass(frozen=True, slots=True)
class TokenEstimate:
    """A token count carried as a planning estimate and a defensible lower bound.

    Attributes:
        tokens: The planning figure, deliberately conservative-high.
        floor: A lower bound the true count is not realistically below. An exact
            tokenizer sets ``floor == tokens``.
    """

    tokens: int
    floor: int

    def __add__(self, other: TokenEstimate) -> TokenEstimate:
        """Sum two estimates component-wise."""
        return TokenEstimate(self.tokens + other.tokens, self.floor + other.floor)


class TokenEstimator(Protocol):
    """Pluggable token counting.

    Implementations may be heuristic (the shipped default) or exact (tiktoken, a
    provider's tokenize endpoint). Exact implementations should return
    ``TokenEstimate(n, n)`` so the gate can act on their counts with full force.
    """

    def estimate(self, text: str) -> TokenEstimate:
        """Estimate the token count of ``text``."""
        ...


@dataclass(frozen=True, slots=True)
class HeuristicTokenEstimator:
    """The dependency-free default: token counts from UTF-8 byte counts.

    Attributes:
        multiplier: Calibration factor applied to the planning estimate, for providers
            whose transport envelope inflates reported prompt tokens beyond the
            serialized bytes. The floor is never inflated — envelope overhead is not
            something a lower bound may claim.
    """

    multiplier: float = 1.0

    def __post_init__(self) -> None:
        """Reject non-finite or non-positive calibration factors."""
        if not math.isfinite(self.multiplier) or self.multiplier <= 0:
            raise ValueError("estimator multiplier must be a positive finite number")

    def estimate(self, text: str) -> TokenEstimate:
        """Estimate tokens as ``ceil(bytes/3)``, with a ``bytes//8`` floor."""
        byte_count = len(text.encode("utf-8"))
        tokens = math.ceil(math.ceil(byte_count / ESTIMATE_BYTES_PER_TOKEN) * self.multiplier)
        return TokenEstimate(tokens, min(byte_count // FLOOR_BYTES_PER_TOKEN, tokens))


_DEFAULT_ESTIMATOR = HeuristicTokenEstimator()


@dataclass(frozen=True, slots=True)
class RequestEstimate:
    """Content-free size accounting for one request, by component.

    The breakdown follows the typed request itself: what the caller said, what tools were
    offered, and what schema was attached — the three things that occupy input tokens on
    any provider.

    Attributes:
        messages: The conversation, including per-message wire-framing overhead.
        tools: Serialized tool specifications, when any were offered.
        schema: The structured-output schema, when one was requested. Counted whether the
            wire carries it natively or the core injects it into the prompt — either way
            it occupies input tokens.
        envelope: What the provider's own transport adds around all of the above, from its
            declared `TokenCalibration`. Zero for
            every provider that counts what it was sent, and floor-free always: an
            envelope correction is believed, not proven.
    """

    messages: TokenEstimate
    tools: TokenEstimate
    schema: TokenEstimate
    envelope: TokenEstimate = TokenEstimate(0, 0)
    unpriced_parts: int = 0

    @property
    def tokens(self) -> int:
        """Total planning estimate across all components."""
        return self.messages.tokens + self.tools.tokens + self.schema.tokens + self.envelope.tokens

    @property
    def floor(self) -> int:
        """Total lower bound across all components."""
        return self.messages.floor + self.tools.floor + self.schema.floor + self.envelope.floor


def estimate_request(
    request: GenerationRequest,
    *,
    estimator: TokenEstimator | None = None,
    calibration: TokenCalibration | None = None,
) -> RequestEstimate:
    """Estimate the input tokens a request will occupy.

    Derived from the typed request rather than hand-fed strings: messages (every content
    part, plus per-message framing overhead), offered tools, and the schema.

    Args:
        request: The request to size.
        estimator: Token counting strategy; defaults to the byte heuristic.
        calibration: The target provider's declared envelope correction. Applied to the
            planning figure only, and reported as its own component so the breakdown still
            adds up. ``None`` means the identity.

    Returns:
        The per-component estimate.
    """
    counter = estimator or _DEFAULT_ESTIMATOR

    messages = TokenEstimate(0, 0)
    unpriced_parts = 0
    for message in request.messages:
        estimate = counter.estimate(_message_text(message))
        messages += TokenEstimate(estimate.tokens + PER_MESSAGE_OVERHEAD_TOKENS, estimate.floor)
        unpriced_parts += sum(
            isinstance(part, ImagePart | DocumentPart | AudioPart) for part in message.content
        )

    tools = TokenEstimate(0, 0)
    for tool in request.tools:
        serialized = json.dumps(
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
            },
            default=str,
        )
        tools += counter.estimate(serialized)

    schema = TokenEstimate(0, 0)
    if request.schema is not None:
        schema = counter.estimate(json.dumps(dict(request.schema.json_schema), default=str))

    return RequestEstimate(
        messages=messages,
        tools=tools,
        schema=schema,
        envelope=_envelope(messages + tools + schema, calibration),
        unpriced_parts=unpriced_parts,
    )


def _envelope(content: TokenEstimate, calibration: TokenCalibration | None) -> TokenEstimate:
    """Size a provider's transport envelope around already-counted content.

    Reported as a separate component rather than folded into the others so the breakdown
    stays readable: an app looking at a budget can see that eleven hundred of its tokens
    belong to the provider's harness and not to anything it sent. The floor is always
    zero — see `TokenCalibration`.
    """
    if calibration is None or calibration.is_identity:
        return TokenEstimate(0, 0)
    scaled = math.ceil(content.tokens * calibration.multiplier) - content.tokens
    return TokenEstimate(max(0, scaled) + calibration.overhead_tokens, 0)


def _message_text(message: Message) -> str:
    """Flatten one message's content parts into the text a provider will be sent."""
    parts: list[str] = []
    for part in message.content:
        if isinstance(part, Text):
            parts.append(part.text)
        elif isinstance(part, ToolCall):
            parts.append(part.name)
            parts.append(json.dumps(dict(part.arguments), default=str))
        elif isinstance(part, ToolResult):
            parts.append(part.content)
    return "".join(parts)
