"""xAI's Grok API (`contracts/xai.md`).

An ``openai-compat`` subclass. Three deltas justify the dedicated adapter:

- **``max_completion_tokens``**, not ``max_tokens`` — the latter is deprecated.
- **Reported cost is authoritative.** xAI returns ``cost_in_usd_ticks`` on every
  response: the amount actually billed, including server-side tool fees and tiered
  pricing, which no table of per-token rates can reproduce. It becomes the result's
  ``cost_usd``, outranking any computed estimate.
- **The model listing carries prices.** ``GET /v1/language-models`` reports per-model
  rates and context windows, so capabilities arrive with ``discovered`` provenance —
  the same strength OpenRouter's listing gives.

Server-side tools (web search, code execution) live on the Responses API rather than
chat completions, and are reachable through ``provider_options`` when xAI exposes them
on this surface; their fees are already reflected in the reported cost.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

import httpx2

from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import (
    DiscoveredModel,
    Feature,
    ModelCapabilities,
    Pricing,
    Sourced,
)
from ..types.requests import ReasoningEffort
from ..types.results import Usage
from .base import WireRequest
from .http import map_transport_error, read_error_detail
from .openai_compat import OpenAICompatAdapter

__all__ = ["XaiAdapter", "descriptor"]

_DEFAULT_BASE_URL = "https://api.x.ai/v1"

_USD_TICKS = Decimal(10_000_000_000)
"""Ticks per USD in the reported cost figure (1 USD = 10^10 ticks)."""

_CENTS_PER_100M_TOKENS = Decimal(100) * Decimal(100)
"""Listing prices are USD cents per 100M tokens; this converts them to USD per 1M."""

_XAI_EFFORTS: Mapping[ReasoningEffort, str] = {
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
}


class XaiAdapter(OpenAICompatAdapter):
    """Adapter for xAI's Grok models."""

    output_tokens_field: ClassVar[str] = "max_completion_tokens"
    """``max_tokens`` is deprecated on this API."""

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """List models from ``/language-models``, which reports prices and limits.

        Falls back to the plain ``/models`` listing when the richer endpoint is
        unavailable, so discovery degrades to ids rather than failing outright.
        """
        try:
            response = await self._client.get("/language-models")
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="discover") from exc
        if response.status_code >= 400:
            detail = read_error_detail(response.content)
            if response.status_code == 404:
                return await super().list_models()
            raise self._classify(response.status_code, detail, response.headers, phase="discover")

        payload = response.json()
        entries = payload.get("models") if isinstance(payload, Mapping) else payload
        if not isinstance(entries, list):
            return await super().list_models()
        return [_parse_language_model(e) for e in entries if isinstance(e, Mapping)]

    def build_payload(self, req: WireRequest) -> dict[str, Any]:
        """Add xAI's Live Search, which is a request-level block rather than a tool.

        Every other provider spells server-run search as an entry in the `tools` array.
        xAI spells it as `search_parameters` beside the messages, and reports what it used
        in `usage.num_sources_used` rather than as a content block — so the count comes
        from usage on the way back, not from a stream event.
        """
        payload = super().build_payload(req)
        if any(spec.kind == "web_search" for spec in req.server_tools):
            search: dict[str, Any] = {"mode": "on"}
            max_uses = next(
                (s.max_uses for s in req.server_tools if s.kind == "web_search"), None
            )
            if max_uses is not None:
                search["max_search_results"] = max_uses
            payload["search_parameters"] = search
        return payload

    def _parse_usage(self, usage: Mapping[str, Any]) -> Usage:
        """Read the standard block, then adopt xAI's exact billed cost.

        A provider-reported figure beats any computed one: it already accounts for
        tiered pricing, cached-token rates, and server-side tool fees.
        """
        parsed = super()._parse_usage(usage)
        sources = usage.get("num_sources_used")
        if isinstance(sources, int) and not isinstance(sources, bool) and sources > 0:
            parsed = replace(parsed, server_tool_uses={"web_search": sources})
        cost = _cost_from_ticks(usage.get("cost_in_usd_ticks"))
        if cost is None:
            return parsed
        return replace(parsed, cost_usd=cost)


def _cost_from_ticks(value: Any) -> Decimal | None:
    """Convert ``cost_in_usd_ticks`` into USD, ignoring absent or malformed values."""
    if not isinstance(value, int | str) or isinstance(value, bool):
        return None
    try:
        ticks = Decimal(str(value))
    except InvalidOperation:
        return None
    return ticks / _USD_TICKS if ticks >= 0 else None


def _parse_language_model(entry: Mapping[str, Any]) -> DiscoveredModel:
    """Read one ``/language-models`` entry: id, window, and per-token prices."""
    model_id = str(entry.get("id") or entry.get("name") or "")

    window = entry.get("max_prompt_length") or entry.get("context_window")
    context = (
        Sourced(int(window), "discovered")
        if isinstance(window, int) and not isinstance(window, bool) and window > 0
        else None
    )

    pricing = _parse_listing_pricing(entry)
    features = Feature.STREAMING | Feature.TOOLS | Feature.SYSTEM_PROMPT
    modalities = entry.get("input_modalities")
    if isinstance(modalities, list) and "text" in modalities:
        features |= Feature.JSON_MODE

    return DiscoveredModel(
        id=model_id,
        capabilities=ModelCapabilities(
            context_window=context,
            features=Sourced(features, "discovered"),
            pricing=Sourced(pricing, "discovered") if pricing is not None else None,
        ),
    )


def _parse_listing_pricing(entry: Mapping[str, Any]) -> Pricing | None:
    """Convert listing prices (USD cents per 100M tokens) into USD per 1M tokens."""

    def rate(key: str) -> Decimal | None:
        raw = entry.get(key)
        if not isinstance(raw, int | float | str) or isinstance(raw, bool):
            return None
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            return None
        return value / _CENTS_PER_100M_TOKENS if value >= 0 else None

    prompt = rate("prompt_text_token_price")
    completion = rate("completion_text_token_price")
    if prompt is None or completion is None:
        return None
    return Pricing(input_per_1m=prompt, output_per_1m=completion)


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Map normalized effort onto ``reasoning_effort``.

    ``minimal`` clamps to ``low`` rather than ``none``: only some Grok models accept
    ``none``, and silently disabling reasoning on a reasoning model would change the
    answer more than the caller asked for. An explicit ``none`` is passed straight
    through — the caller asked for exactly that, so a model that rejects it should say so
    rather than have the request quietly rewritten into more reasoning than was wanted.
    """
    if effort is None:
        return {}
    if effort == "none":
        return {"reasoning_effort": "none"}
    return {"reasoning_effort": _XAI_EFFORTS[effort]}


_XAI_FEATURES = (
    Feature.WEB_SEARCH
    | Feature.STREAMING
    | Feature.JSON_SCHEMA
    | Feature.JSON_MODE
    | Feature.TOOLS
    | Feature.REASONING
    | Feature.SYSTEM_PROMPT
    | Feature.CACHE_USAGE
)


descriptor = ProviderDescriptor(
    id="xai",
    display_name="xAI (Grok)",
    aliases=("grok",),
    factory=XaiAdapter,
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
                help_text=("Conventionally env://XAI_API_KEY. Accepts env:// and credential://."),
                placeholder="env://XAI_API_KEY or a literal key",
                env_var="XAI_API_KEY",
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
    server_tools=frozenset({"web_search"}),
    default_capabilities=ModelCapabilities(features=Sourced(_XAI_FEATURES, "default")),
)
"""Descriptor for the xAI provider."""
