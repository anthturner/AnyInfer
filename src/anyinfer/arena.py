"""Arena records, deterministic selection, and the versioned candidate envelope."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from typing import Any

from .types.requests import ArenaPolicy, ResolvedTarget
from .types.results import ErrorInfo, Generation, Usage

__all__ = [
    "ARENA_ENVELOPE_FORMAT",
    "ArenaResult",
    "Candidate",
    "arena_to_dict",
    "candidate_envelope",
    "canonical_json",
    "select_candidates",
]

ARENA_ENVELOPE_FORMAT = "1"
"""Candidate-envelope format version."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """One arena branch's final answer or bounded, redacted failure."""

    target: ResolvedTarget
    generation: Generation | None = None
    error: ErrorInfo | None = None
    valid: bool | None = None
    elapsed_ms: float = 0.0
    rounds: int | None = None
    tool_calls: int = 0


@dataclass(frozen=True, slots=True)
class ArenaResult:
    """Every candidate, terminal selection, and aggregate accounting for an arena."""

    candidates: tuple[Candidate, ...]
    winner: Candidate | None
    strategy: str
    agreement: int | None = None
    synthesized: Generation | None = None
    calls: int = 0
    memoized_tool_calls: int = 0
    usage: Usage = Usage()
    usage_complete: bool = True

    def summary(self) -> str:
        """Render one content-free status line."""
        successes = sum(candidate.generation is not None for candidate in self.candidates)
        agreement = f", agreement {self.agreement}" if self.agreement is not None else ""
        usage = "complete" if self.usage_complete else "unknown after failed attempts"
        return (
            f"arena {self.strategy}: {successes}/{len(self.candidates)} candidates, "
            f"{self.calls} calls{agreement}; usage {usage}"
        )


def canonical_json(value: Any) -> str:
    """Canonical JSON used by consensus and exact tool memoization."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def select_candidates(
    candidates: tuple[Candidate, ...], policy: ArenaPolicy, *, has_schema: bool
) -> tuple[Candidate | None, str, int | None, str | None]:
    """Apply a deterministic strategy, returning any announced degradation reason."""
    valid = [
        candidate
        for candidate in candidates
        if candidate.generation is not None and (not has_schema or candidate.valid is True)
    ]
    if not valid:
        return None, "first_valid", None, "no valid candidate was available"

    strategy = policy.strategy
    if strategy in ("judge", "synthesize"):
        strategy = "first_valid"
    if strategy == "first_valid":
        return valid[0], "first_valid", None, None
    if strategy == "fastest":
        return min(valid, key=lambda item: item.elapsed_ms), "fastest", None, None
    if strategy == "cheapest":
        priced = [
            (candidate, generation.usage.cost_usd)
            for candidate in valid
            if (generation := candidate.generation) is not None
            and generation.usage.cost_usd is not None
        ]
        if not priced:
            return (
                valid[0],
                "first_valid",
                None,
                ("arena.strategy cheapest degraded because every candidate cost is unknown"),
            )

        return min(priced, key=lambda item: item[1])[0], "cheapest", None, None
    if strategy == "consensus":
        if not has_schema:
            return (
                valid[0],
                "first_valid",
                None,
                ("arena.strategy consensus requires a structured-output schema"),
            )
        groups: dict[str, list[Candidate]] = {}
        for candidate in valid:
            generation = candidate.generation
            if generation is None:  # defensive: ``valid`` already excludes this
                continue
            key = canonical_json(generation.structured)
            groups.setdefault(key, []).append(candidate)
        largest = max(groups.values(), key=len)
        return largest[0], "consensus", len(largest), None
    return valid[0], "first_valid", None, f"arena.strategy {strategy} could not be applied"


def candidate_envelope(candidates: tuple[Candidate, ...], *, reveal_targets: bool) -> str:
    """Render candidates deterministically, anonymized unless explicitly requested."""
    blocks: list[str] = [f'<candidates format="{ARENA_ENVELOPE_FORMAT}">']
    for index, candidate in enumerate(candidates, start=1):
        target = (
            f' target="{html.escape(str(candidate.target), quote=True)}"' if reveal_targets else ""
        )
        text = candidate.generation.text if candidate.generation is not None else ""
        blocks.append(f'<candidate index="{index}"{target}>\n{html.escape(text)}\n</candidate>')
    blocks.append("</candidates>")
    return "\n".join(blocks)


def arena_to_dict(result: ArenaResult) -> dict[str, Any]:
    """Serialize an arena result for the sidecar response extension."""
    winner_index = next(
        (index for index, item in enumerate(result.candidates) if item is result.winner), None
    )
    return {
        "strategy": result.strategy,
        "winner": winner_index,
        "agreement": result.agreement,
        "calls": result.calls,
        "memoized_tool_calls": result.memoized_tool_calls,
        "usage_complete": result.usage_complete,
        "usage": _usage_dict(result.usage),
        "candidates": [_candidate_dict(candidate) for candidate in result.candidates],
        "synthesized": (
            _generation_dict(result.synthesized) if result.synthesized is not None else None
        ),
    }


def _candidate_dict(candidate: Candidate) -> dict[str, Any]:
    return {
        "target": str(candidate.target),
        "valid": candidate.valid,
        "elapsed_ms": candidate.elapsed_ms,
        "rounds": candidate.rounds,
        "tool_calls": candidate.tool_calls,
        "generation": (
            _generation_dict(candidate.generation) if candidate.generation is not None else None
        ),
        "error": (
            {
                "type": candidate.error.type_name,
                "provider": candidate.error.provider,
                "phase": candidate.error.phase,
                "retryable": candidate.error.retryable,
                "http_status": candidate.error.http_status,
                "detail": candidate.error.detail,
            }
            if candidate.error is not None
            else None
        ),
    }


def _generation_dict(generation: Generation) -> dict[str, Any]:
    return {
        "text": generation.text,
        "structured": generation.structured,
        "target": str(generation.target),
        "finish_reason": generation.finish_reason,
        "usage": _usage_dict(generation.usage),
        "timing": {
            "first_token_ms": generation.timing.first_token_ms,
            "total_ms": generation.timing.total_ms,
        },
        "structured_mechanism": generation.structured_mechanism,
        "repair_attempts": generation.repair_attempts,
    }


def _usage_dict(usage: Usage) -> dict[str, Any]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "cost_usd": str(usage.cost_usd) if usage.cost_usd is not None else None,
    }
