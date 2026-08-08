"""OpenRouter (`contracts/openrouter.md`).

An ``openai-compat`` subclass whose real value is its model listing: OpenRouter reports
per-model context length *and* per-token pricing, making it the one provider that feeds the
capability layer ``discovered``-provenance pricing rather than catalogued estimates.

Its SSE stream also carries ``: OPENROUTER PROCESSING`` keep-alive comments, which the
shared parser already ignores (comments are dropped by the SSE framing rules).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from ..errors import AuthError, Phase, ProviderError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import (
    DiscoveredModel,
    Feature,
    ModelCapabilities,
    Pricing,
    Sourced,
)
from ..types.requests import ReasoningEffort
from .base import ProviderConfig
from .openai_compat import OpenAICompatAdapter

__all__ = ["OpenRouterAdapter", "descriptor"]

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

_TOKENS_PER_MILLION = Decimal(1_000_000)


class OpenRouterAdapter(OpenAICompatAdapter):
    """Adapter for OpenRouter's aggregation API."""


    def _build_headers(self, config: ProviderConfig) -> dict[str, str]:
        """Add OpenRouter's optional attribution headers."""
        headers = super()._build_headers(config)
        options = config.options
        referer = options.get("http_referer") or options.get("referer")
        title = options.get("x_title") or options.get("title")
        if isinstance(referer, str) and referer:
            headers["http-referer"] = referer
        if isinstance(title, str) and title:
            headers["x-title"] = title
        return headers

    def _parse_model(self, entry: Mapping[str, Any]) -> DiscoveredModel:
        """Read OpenRouter's rich listing: context length, pricing, and features.

        This is the strongest ``discovered`` layer any provider gives us — real pricing
        rather than a catalogued estimate, which is what makes cost reporting for
        OpenRouter targets authoritative instead of approximate.
        """
        model_id = str(entry.get("id", ""))

        context = entry.get("context_length")
        context_window = (
            Sourced(int(context), "discovered")
            if isinstance(context, int) and context > 0
            else None
        )

        max_output = None
        top_provider = entry.get("top_provider")
        if isinstance(top_provider, Mapping):
            completion_limit = top_provider.get("max_completion_tokens")
            if isinstance(completion_limit, int) and completion_limit > 0:
                max_output = Sourced(completion_limit, "discovered")

        pricing = _parse_pricing(entry.get("pricing"))
        features = _features_from_parameters(entry.get("supported_parameters"))

        return DiscoveredModel(
            id=model_id,
            capabilities=ModelCapabilities(
                context_window=context_window,
                max_output_tokens=max_output,
                features=Sourced(features, "discovered"),
                pricing=Sourced(pricing, "discovered") if pricing is not None else None,
            ),
        )

    def _classify(self, status: int, detail: str, headers: Mapping[str, str],
                  phase: Phase = "generate") -> ProviderError:
        """Map OpenRouter's billing-specific 402 alongside the standard statuses."""
        if status == 402:
            return AuthError(
                detail or "insufficient OpenRouter credits",
                provider=self.provider_id,
                http_status=status,
                phase=phase,
                hint="add credits to your OpenRouter account, or use a free-tier model",
            )
        return super()._classify(status, detail, headers, phase)


def _parse_pricing(payload: Any) -> Pricing | None:
    """Convert OpenRouter's per-token price strings into per-million-token decimals.

    Prices arrive as strings to preserve precision, so they are parsed with ``Decimal``:
    float arithmetic on fractions-of-a-cent accumulates error across a long run.
    """
    if not isinstance(payload, Mapping):
        return None

    def per_million(key: str) -> Decimal | None:
        raw = payload.get(key)
        if not isinstance(raw, str | int | float):
            return None
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return None
        return value * _TOKENS_PER_MILLION if value >= 0 else None

    prompt = per_million("prompt")
    completion = per_million("completion")
    if prompt is None or completion is None:
        return None
    return Pricing(input_per_1m=prompt, output_per_1m=completion)


def _features_from_parameters(parameters: Any) -> Feature:
    """Derive capability flags from the parameters a model advertises.

    Absence is treated as unsupported rather than unknown: OpenRouter enumerates what each
    model accepts, so a missing entry is meaningful, and claiming more would send requests
    that the upstream provider silently drops.
    """
    features = Feature.STREAMING | Feature.SYSTEM_PROMPT
    if not isinstance(parameters, list):
        return features | Feature.TOOLS

    names = {str(p) for p in parameters}
    if "tools" in names or "tool_choice" in names:
        features |= Feature.TOOLS
    if "response_format" in names:
        features |= Feature.JSON_MODE
    if "structured_outputs" in names:
        features |= Feature.JSON_SCHEMA
    if "reasoning" in names or "include_reasoning" in names:
        features |= Feature.REASONING
    return features


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """OpenRouter accepts a unified ``reasoning`` object across upstream providers."""
    return {} if effort is None else {"reasoning": {"effort": effort}}


_OPENROUTER_FEATURES = (
    Feature.STREAMING | Feature.TOOLS | Feature.JSON_MODE | Feature.SYSTEM_PROMPT
)
"""Conservative defaults; the model listing upgrades these per model."""


descriptor = ProviderDescriptor(
    id="openrouter",
    display_name="OpenRouter",
    factory=OpenRouterAdapter,
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
                help_text="Accepts a literal, env://VAR, or credential://system/name.",
                placeholder="env://OPENROUTER_API_KEY or a literal key",
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
    default_capabilities=ModelCapabilities(
        features=Sourced(_OPENROUTER_FEATURES, "default")
    ),
)
"""Descriptor for the OpenRouter provider."""
