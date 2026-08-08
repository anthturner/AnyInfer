"""Nebius Token Factory (`contracts/nebius.md`).

An ``openai-compat`` subclass whose one real delta is its **model listing**. Passing
``?verbose=true`` to ``GET /models`` returns per-model pricing, context length,
quantization, and rate limits — so capabilities arrive with ``discovered`` provenance
rather than as catalogued estimates, the same strength OpenRouter's listing gives.

That matters more here than for most hosts, because Nebius prices *flavors* separately:
appending ``-fast`` to a model id selects a low-latency variant with its own rate, and the
catalog turns over often enough that a bundled price table would be stale within weeks.
Reading prices from the listing means the numbers are always the provider's own.

Prices arrive as USD **per single token**, as decimal strings; they are scaled to the
per-million-token figures the capability layer works in, with ``Decimal`` throughout
because per-token prices are fractions of a cent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx2

from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import (
    DiscoveredModel,
    Feature,
    LocalModelInfo,
    ModelCapabilities,
    Pricing,
    Sourced,
)
from ..types.events import ReasoningDelta
from ..types.requests import ReasoningEffort
from .base import AdapterEvent, WireRequest
from .http import map_transport_error, read_error_detail
from .openai_compat import OpenAICompatAdapter, _StreamState

__all__ = ["NebiusAdapter", "descriptor"]

_DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1"

_TOKENS_PER_MILLION = Decimal(1_000_000)
"""Listing prices are per single token; capabilities are per million."""


class NebiusAdapter(OpenAICompatAdapter):
    """Adapter for Nebius Token Factory, with its verbose model listing."""

    def _events_from_chunk(
        self, chunk: Any, state: _StreamState
    ) -> Iterable[AdapterEvent]:
        """Surface Nebius reasoning fields separately from visible answer text."""
        if isinstance(chunk, Mapping):
            choices = chunk.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
                delta = choices[0].get("delta")
                if isinstance(delta, Mapping):
                    reasoning = _reasoning_text(delta)
                    if reasoning is not None:
                        yield ReasoningDelta(reasoning)
        yield from super()._events_from_chunk(chunk, state)

    def _events_from_completion(
        self, payload: Any, req: WireRequest
    ) -> Iterable[AdapterEvent]:
        """Apply the same reasoning-channel handling to buffered responses."""
        if isinstance(payload, Mapping):
            choices = payload.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
                message = choices[0].get("message")
                if isinstance(message, Mapping):
                    reasoning = _reasoning_text(message)
                    if reasoning is not None:
                        yield ReasoningDelta(reasoning)
        yield from super()._events_from_completion(payload, req)

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """List models with ``?verbose=true``, falling back to the plain listing.

        The verbose form is what makes this adapter worth having; a deployment that does
        not offer it degrades to ids alone rather than failing.
        """
        try:
            response = await self._client.get(self.models_path, params={"verbose": "true"})
        except httpx2.HTTPError as exc:
            raise map_transport_error(
                exc, provider=self.provider_id, phase="discover"
            ) from exc
        if response.status_code >= 400:
            if response.status_code in (400, 404, 422):
                return await super().list_models()
            raise self._classify(
                response.status_code,
                read_error_detail(response.content),
                response.headers,
                phase="discover",
            )

        payload = response.json()
        entries = payload.get("data") if isinstance(payload, Mapping) else payload
        if not isinstance(entries, list):
            return await super().list_models()
        return [self._parse_model(e) for e in entries if isinstance(e, Mapping)]

    def _parse_model(self, entry: Mapping[str, Any]) -> DiscoveredModel:
        """Read one verbose listing entry: window, pricing, features, quantization."""
        window = entry.get("context_length")
        context = (
            Sourced(int(window), "discovered")
            if isinstance(window, int) and not isinstance(window, bool) and window > 0
            else None
        )

        pricing = _parse_pricing(entry.get("pricing"))
        features = _features_from_entry(entry)
        quantization = entry.get("quantization")

        return DiscoveredModel(
            id=str(entry.get("id", "")),
            capabilities=ModelCapabilities(
                context_window=context,
                features=Sourced(features, "discovered"),
                pricing=Sourced(pricing, "discovered") if pricing is not None else None,
                local=(
                    LocalModelInfo(quantization=str(quantization))
                    if isinstance(quantization, str) and quantization
                    else None
                ),
            ),
        )


def _parse_pricing(payload: Any) -> Pricing | None:
    """Convert per-token price strings into per-million-token decimals.

    Parsed with ``Decimal`` rather than ``float``: a per-token price is on the order of
    1e-8, and float error accumulates fast when multiplied out across a long run.
    """
    if not isinstance(payload, Mapping):
        return None

    def per_million(key: str) -> Decimal | None:
        raw = payload.get(key)
        if not isinstance(raw, str | int | float) or isinstance(raw, bool):
            return None
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            return None
        return value * _TOKENS_PER_MILLION if value >= 0 else None

    prompt = per_million("prompt")
    completion = per_million("completion")
    if prompt is None or completion is None:
        return None
    return Pricing(input_per_1m=prompt, output_per_1m=completion)


def _reasoning_text(container: Mapping[str, Any]) -> str | None:
    """Read either reasoning field without emitting duplicate content."""
    for field in ("reasoning_content", "reasoning"):
        value = container.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _features_from_entry(entry: Mapping[str, Any]) -> Feature:
    """Derive capability flags from what the listing says a model supports.

    Absence is treated as unsupported when the listing enumerates features, because an
    enumeration that omits something is meaningful. With no enumeration at all, the
    conservative compat defaults stand instead.
    """
    supported = entry.get("supported_features")
    if not isinstance(supported, list):
        return Feature.STREAMING | Feature.TOOLS | Feature.SYSTEM_PROMPT

    names = {str(f).lower() for f in supported}
    features = Feature.SYSTEM_PROMPT
    if "streaming" in names or "stream" in names:
        features |= Feature.STREAMING
    if "tools" in names or "function_calling" in names or "tool_calling" in names:
        features |= Feature.TOOLS
    if "structured_output" in names or "json_schema" in names:
        features |= Feature.JSON_SCHEMA
    if "json_mode" in names or "response_format" in names:
        features |= Feature.JSON_MODE
    if "reasoning" in names or "thinking" in names:
        features |= Feature.REASONING
    if "prompt_caching" in names or "caching" in names:
        features |= Feature.CACHE_USAGE
    return features


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Pass normalized effort through as ``reasoning_effort``.

    All four normalized levels are accepted verbatim; Nebius additionally documents
    ``none``, ``xhigh``, and ``max``, which are reachable through ``provider_options``.
    """
    return {} if effort is None else {"reasoning_effort": effort}


_NEBIUS_FEATURES = (
    Feature.STREAMING
    | Feature.JSON_SCHEMA
    | Feature.JSON_MODE
    | Feature.TOOLS
    | Feature.REASONING
    | Feature.SYSTEM_PROMPT
    | Feature.CACHE_USAGE
)


descriptor = ProviderDescriptor(
    id="nebius",
    display_name="Nebius Token Factory",
    aliases=("nebius-token-factory", "token-factory"),
    factory=NebiusAdapter,
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
                placeholder="env://NEBIUS_API_KEY or a literal key",
                help_text=(
                    "Conventionally env://NEBIUS_API_KEY. Accepts env:// and "
                    "credential://."
                ),
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
    default_capabilities=ModelCapabilities(features=Sourced(_NEBIUS_FEATURES, "default")),
)
"""Descriptor for the Nebius Token Factory provider."""
