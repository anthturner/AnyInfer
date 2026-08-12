"""DeepSeek's chat API (`contracts/deepseek.md`).

An ``openai-compat`` subclass with three real deltas, each of which would otherwise cost
the caller silently:

- **Reasoning is a separate channel.** Chain-of-thought streams as ``reasoning_content``
  beside ``content``, so it is surfaced as reasoning rather than concatenated into the
  answer text — the same separation Anthropic's thinking deltas and Gemini's thought
  parts get.
- **Thinking is on by default**, controlled by a ``thinking`` object plus
  ``reasoning_effort``, not by a token budget.
- **Cache accounting is automatic and split.** ``prompt_cache_hit_tokens`` and
  ``prompt_cache_miss_tokens`` partition the prompt, and hits are billed at a much lower
  rate; ignoring them overstates cost on every repeated prefix.

Sampling controls are declared as ignored because DeepSeek silently discards
``temperature``, ``top_p``, and the penalties while thinking is enabled, which is the
default, so a caller setting them deserves a `ParameterDropped` event rather than the
illusion that they took effect.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import Feature, ModelCapabilities, Sourced
from ..types.events import ReasoningDelta
from ..types.requests import ReasoningEffort
from ..types.results import Usage
from .base import AdapterEvent, WireRequest
from .openai_compat import OpenAICompatAdapter, _StreamState

__all__ = ["DeepSeekAdapter", "descriptor"]

_DEFAULT_BASE_URL = "https://api.deepseek.com"

_DEEPSEEK_EFFORTS: Mapping[ReasoningEffort, str] = {
    # DeepSeek accepts low/high/max; medium and xhigh are mapped to high upstream, so
    # they are mapped here too rather than sending a value the API rewrites.
    "minimal": "low",
    "low": "low",
    "medium": "high",
    "high": "high",
}


class DeepSeekAdapter(OpenAICompatAdapter):
    """Adapter for DeepSeek's OpenAI-compatible chat API."""

    def _events_from_chunk(self, chunk: Any, state: _StreamState) -> Iterable[AdapterEvent]:
        """Surface ``reasoning_content`` as reasoning before delegating the rest."""
        if isinstance(chunk, Mapping):
            yield from _reasoning_events(chunk)
        yield from super()._events_from_chunk(chunk, state)

    def _events_from_completion(self, payload: Any, req: WireRequest) -> Iterable[AdapterEvent]:
        """Surface a buffered response's ``reasoning_content`` the same way."""
        if isinstance(payload, Mapping):
            choices = payload.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
                message = choices[0].get("message")
                if isinstance(message, Mapping):
                    text = message.get("reasoning_content")
                    if isinstance(text, str) and text:
                        yield ReasoningDelta(text)
        yield from super()._events_from_completion(payload, req)

    def _parse_usage(self, usage: Mapping[str, Any]) -> Usage:
        """Read DeepSeek's split cache accounting on top of the standard block.

        ``prompt_tokens`` already equals hits plus misses, so only the hit count is
        additional information, and it is the one that changes the bill.
        """
        parsed = super()._parse_usage(usage)
        hits = usage.get("prompt_cache_hit_tokens")
        if isinstance(hits, int) and not isinstance(hits, bool):
            parsed = Usage(
                input_tokens=parsed.input_tokens,
                output_tokens=parsed.output_tokens,
                total_tokens=parsed.total_tokens,
                cache_read_tokens=hits,
                cache_write_tokens=parsed.cache_write_tokens,
                reasoning_tokens=parsed.reasoning_tokens,
                cost_usd=parsed.cost_usd,
            )
        return parsed


def _reasoning_events(chunk: Mapping[str, Any]) -> Iterable[ReasoningDelta]:
    """Pull ``delta.reasoning_content`` out of a streaming chunk."""
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return
    choice = choices[0]
    if not isinstance(choice, Mapping):
        return
    delta = choice.get("delta")
    if not isinstance(delta, Mapping):
        return
    text = delta.get("reasoning_content")
    if isinstance(text, str) and text:
        yield ReasoningDelta(text)


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Map normalized effort onto DeepSeek's thinking controls.

    Thinking is on by default, so ``minimal`` is a request to think *less*, not to stop:
    disabling it outright would change the model's behavior more than the caller asked
    for. Pass ``provider_options={"deepseek": {"thinking": {"type": "disabled"}}}`` to
    turn it off deliberately.
    """
    if effort is None:
        return {}
    return {
        "thinking": {"type": "enabled"},
        "reasoning_effort": _DEEPSEEK_EFFORTS[effort],
    }


_DEEPSEEK_FEATURES = (
    Feature.STREAMING
    | Feature.JSON_MODE
    | Feature.TOOLS
    | Feature.REASONING
    | Feature.SYSTEM_PROMPT
    | Feature.CACHE_USAGE
)
"""Notably excludes JSON_SCHEMA: DeepSeek documents ``json_object`` mode, not schemas."""


descriptor = ProviderDescriptor(
    id="deepseek",
    display_name="DeepSeek",
    factory=DeepSeekAdapter,
    locality="hosted",
    default_base_url=_DEFAULT_BASE_URL,
    requires_base_url=False,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="api_key",
                label="API key",
                kind="secret",
                required=True,
                help_text=(
                    "Conventionally env://DEEPSEEK_API_KEY. Accepts env:// and credential://."
                ),
                placeholder="env://DEEPSEEK_API_KEY or a literal key",
                env_var="DEEPSEEK_API_KEY",
            ),
            SetupField(
                key="base_url",
                label="Base URL",
                kind="endpoint",
                required=False,
                advanced=True,
                default_value=_DEFAULT_BASE_URL,
                help_text=f"Defaults to {_DEFAULT_BASE_URL}.",
            ),
        ),
        model_selection="discover-or-manual",
    ),
    reasoning_translator=_translate_reasoning,
    default_capabilities=ModelCapabilities(features=Sourced(_DEEPSEEK_FEATURES, "default")),
    # Context caching happens on the provider's side against a stable prefix, and its hits
    # and misses are billed separately. Recorded in contracts/deepseek.md.
    cache_mechanism="implicit",
    ignored_parameters=("temperature", "top_p"),
)
"""Descriptor for the DeepSeek provider.

DeepSeek adds one finish reason beyond the standard set,
``insufficient_system_resource``; the shared normalization already maps unrecognized
values to ``other``, so it needs no special case.
"""
