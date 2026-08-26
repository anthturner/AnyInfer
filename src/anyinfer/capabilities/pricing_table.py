"""The bundled model-pricing table and its loaders.

A versioned data file (``pricing.json``, beside this module) records per-million-token
prices for hosted models, each entry carrying a ``last_verified`` date and the source it
was verified against — the same discipline as the ``contracts/`` protocol snapshots:
a date is never fabricated. The table feeds capability assembly as the ``catalog`` layer,
so every existing trust rule applies unchanged: ``discovered`` pricing (OpenRouter) beats
it, an application's ``override`` beats everything, and a model with no entry keeps
``pricing=None`` — cost stays honestly unknown rather than becoming a stale guess.

Freshness is opt-in and explicit. The library never fetches anything implicitly; a repo
workflow keeps the upstream file current, and `fetch_pricing()` lets an application
pull that file on its own schedule and hand it to a client.

An entry may optionally carry ``per_search_unit`` (a decimal string, same rule as the
token rates) for rerank providers billed per search rather than per token; embedding
and rerank cost computation is `anyinfer.capabilities.pricing.compute_operation_cost`,
which reads only the field relevant to its operation (input-token rate for embeddings,
``per_search_unit`` for rerank) — an entry missing the field it needs simply prices
that operation as unknown rather than guessing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from importlib import resources
from types import MappingProxyType
from typing import Any

from ..errors import ConfigError
from ..types.capabilities import Pricing, Sourced

__all__ = [
    "DEFAULT_PRICING_URL",
    "PricingEntry",
    "PricingTable",
    "fetch_pricing",
    "load_default_pricing",
]

DEFAULT_PRICING_URL = (
    "https://raw.githubusercontent.com/anthturner/AnyInfer/main/"
    "src/anyinfer/capabilities/pricing.json"
)
"""Where the repo publishes the continuously-maintained pricing file."""

_MODEL_ID_BOUNDARIES = ("-", ".", ":", "@")
"""Separators that may follow a prefix entry for it to match a longer model id."""


@dataclass(frozen=True, slots=True)
class PricingEntry:
    """One priced model (or model-id prefix) in the table.

    Attributes:
        model: Exact model id, or a prefix that matches dated/suffixed variants
            (``gpt-4.1`` matches ``gpt-4.1-2025-04-14``; longest prefix wins, so
            ``gpt-4.1-mini`` is never captured by ``gpt-4.1``).
        pricing: The per-million-token rates.
        last_verified: ISO date the rates were last checked against ``source``.
        source: URL the rates were verified against.
        openrouter_id: OpenRouter's id for the same model, used by the automated
            drift check to cross-verify; empty when OpenRouter does not list it.
    """

    model: str
    pricing: Pricing
    last_verified: str
    source: str
    openrouter_id: str = ""


class PricingTable:
    """Per-provider model pricing with prefix-aware lookup."""

    def __init__(self, entries: dict[str, tuple[PricingEntry, ...]]) -> None:
        self._entries = entries

    @property
    def providers(self) -> tuple[str, ...]:
        """Provider ids the table covers, sorted."""
        return tuple(sorted(self._entries))

    def entries_for(self, provider_id: str) -> tuple[PricingEntry, ...]:
        """Every entry for one provider, or an empty tuple."""
        return self._entries.get(provider_id, ())

    def lookup(self, provider_id: str, model: str) -> Sourced[Pricing] | None:
        """Find pricing for a model: exact match first, then longest boundary prefix.

        Returns:
            The pricing tagged ``catalog`` provenance, or ``None`` when the model has no
            entry; never a fallback price.
        """
        entries = self._entries.get(provider_id)
        if not entries:
            return None
        best: PricingEntry | None = None
        for entry in entries:
            if model == entry.model:
                best = entry
                break
            if any(model.startswith(entry.model + sep) for sep in _MODEL_ID_BOUNDARIES) and (
                best is None or len(entry.model) > len(best.model)
            ):
                best = entry
        if best is None:
            return None
        return Sourced(best.pricing, "catalog")

    @classmethod
    def from_mapping(cls, data: Any) -> PricingTable:
        """Build and validate a table from parsed JSON.

        Raises:
            ConfigError: On a malformed document — wrong format version, missing fields,
                or prices that do not parse as non-negative decimals.
        """
        if not isinstance(data, dict) or data.get("format_version") != 1:
            raise ConfigError(
                "pricing table has an unsupported format",
                hint="expected a JSON object with format_version: 1",
            )
        providers = data.get("providers")
        if not isinstance(providers, dict):
            raise ConfigError("pricing table is missing its 'providers' mapping")

        tool_rates = _parse_server_tools(data.get("server_tools"))
        entries: dict[str, tuple[PricingEntry, ...]] = {}
        for provider_id, raw_entries in providers.items():
            provider_tools = tool_rates.get(str(provider_id), {})
            parsed = tuple(
                _parse_entry(
                    provider_id, raw, _rates_for(provider_tools, str(raw.get("model", "")))
                )
                for raw in _require_list(provider_id, raw_entries)
            )
            entries[str(provider_id)] = parsed
        return cls(entries)


def _require_list(provider_id: str, value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigError(f"pricing entries for {provider_id!r} must be a list")
    return value


@dataclass(frozen=True, slots=True)
class _ToolRate:
    """One server tool's price, before a model is known.

    Attributes:
        flat: The rate however the tool is used, or ``Decimal(0)`` for a tool the provider
            folds into the token bill. ``None`` when the rate depends on the model.
        by_model: Rates keyed by model id or prefix, for a provider that charges by model
            class. Empty when a flat rate applies.
    """

    flat: Decimal | None = None
    by_model: Mapping[str, Decimal] = field(default_factory=dict)

    def resolve(self, model: str) -> Decimal | None:
        """The rate for one model, or ``None`` when this table cannot price it.

        Longest-prefix wins, matching how a model entry is looked up, so
        ``gemini-2.5-flash`` finds a ``gemini-2.5`` rate without a ``gemini-2`` rate
        stealing it. An unmatched model returns ``None`` and stays honestly unpriced.
        """
        if self.flat is not None:
            return self.flat
        best: str | None = None
        for candidate in self.by_model:
            matches = model == candidate or model.startswith(candidate)
            if matches and (best is None or len(candidate) > len(best)):
                best = candidate
        return self.by_model[best] if best is not None else None


def _parse_server_tools(raw: Any) -> dict[str, dict[str, _ToolRate]]:
    """Parse the provider-level server-tool rate block.

    Three shapes, because the providers genuinely have three. A tool billed at one flat
    rate however it is used carries `per_use`. A tool whose rate depends on the model
    carries `per_use_by_model`, keyed by model id or prefix — OpenAI charges reasoning and
    non-reasoning models differently for the same search, and Gemini charges by model
    generation. And a tool that adds no separate line item at all carries
    `billed_as: "tokens"`, which is a *known* cost of zero rather than a missing one.

    That last distinction is the reason this is not simply a number. An absent rate means
    unpriced, which makes the whole generation's cost unknown; zero means the provider
    folds this tool into the token bill and the token figure is already the whole answer.
    Collapsing them would either invent a charge or hide one.

    A model not matched by any `per_use_by_model` key stays unpriced. That is deliberate:
    where a provider bills by model class rather than by a name we can match, guessing
    which class an unlisted model falls into would produce a confident wrong number.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError("pricing table's 'server_tools' must be a mapping")
    parsed: dict[str, dict[str, _ToolRate]] = {}
    for provider_id, block in raw.items():
        # An underscore-prefixed key is prose for whoever edits this file next, at either
        # level, the same convention the document's top-level `_comment` uses.
        if provider_id.startswith("_"):
            continue
        if not isinstance(block, dict):
            raise ConfigError(f"server-tool rates for {provider_id!r} must be an object")
        rates: dict[str, _ToolRate] = {}
        for kind, entry in block.items():
            if kind.startswith("_"):
                continue
            if not isinstance(entry, dict):
                raise ConfigError(
                    f"server-tool rate {kind!r} for {provider_id!r} must be an object"
                )
            where = f"server-tool rate {kind!r} for {provider_id!r}"
            try:
                # Same discipline as a token rate: the date and source are mandatory, so
                # an unverified figure cannot be added without saying it is unverified.
                str(entry["last_verified"])
                str(entry["source"])
            except KeyError as missing:
                raise ConfigError(
                    f"{where} is missing field {missing.args[0]!r}"
                ) from None
            rates[str(kind)] = _parse_tool_rate(entry, where)
        parsed[str(provider_id)] = rates
    return parsed


def _parse_tool_rate(entry: Mapping[str, Any], where: str) -> _ToolRate:
    """Read one tool's rate in whichever of the three shapes it was written."""
    if entry.get("billed_as") == "tokens":
        return _ToolRate(flat=Decimal(0))
    if "per_use" in entry:
        return _ToolRate(flat=_parse_rate(entry["per_use"]))
    by_model = entry.get("per_use_by_model")
    if isinstance(by_model, dict) and by_model:
        return _ToolRate(
            by_model={str(model): _parse_rate(rate) for model, rate in by_model.items()}
        )
    raise ConfigError(
        f"{where} needs one of 'per_use', 'per_use_by_model', or 'billed_as'"
    )

def _rates_for(rates: Mapping[str, _ToolRate], model: str) -> dict[str, Decimal]:
    """Resolve every tool's rate for one model, dropping the ones it cannot price."""
    resolved: dict[str, Decimal] = {}
    for kind, rate in rates.items():
        value = rate.resolve(model)
        if value is not None:
            resolved[kind] = value
    return resolved


def _parse_entry(
    provider_id: str, raw: Any, server_tools: Mapping[str, Decimal] = MappingProxyType({})
) -> PricingEntry:
    if not isinstance(raw, dict):
        raise ConfigError(f"pricing entry for {provider_id!r} must be an object")
    try:
        model = str(raw["model"])
        input_rate = _parse_rate(raw["input_per_1m"])
        output_rate = _parse_rate(raw["output_per_1m"])
        last_verified = str(raw["last_verified"])
        source = str(raw["source"])
    except KeyError as missing:
        raise ConfigError(
            f"pricing entry for {provider_id!r} is missing field {missing.args[0]!r}"
        ) from None
    per_search_unit_raw = raw.get("per_search_unit")
    per_search_unit = (
        _parse_rate(per_search_unit_raw) if per_search_unit_raw is not None else None
    )
    return PricingEntry(
        model=model,
        pricing=Pricing(
            input_per_1m=input_rate,
            output_per_1m=output_rate,
            currency=str(raw.get("currency", "USD")),
            per_search_unit=per_search_unit,
            per_server_tool_use=dict(server_tools),
        ),
        last_verified=last_verified,
        source=source,
        openrouter_id=str(raw.get("openrouter_id", "")),
    )


def _parse_rate(value: Any) -> Decimal:
    """Parse a price that must be a string (JSON floats would corrupt Decimal math)."""
    if not isinstance(value, str):
        raise ConfigError(
            f"price {value!r} must be a JSON string, not a number",
            hint='floats lose precision; write prices as strings like "1.25"',
        )
    try:
        rate = Decimal(value)
    except InvalidOperation:
        raise ConfigError(f"price {value!r} does not parse as a decimal") from None
    if rate < 0:
        raise ConfigError(f"price {value!r} must not be negative")
    return rate


@lru_cache(maxsize=1)
def load_default_pricing() -> PricingTable:
    """Load the pricing table bundled with this release."""
    text = resources.files("anyinfer.capabilities").joinpath("pricing.json").read_text("utf-8")
    return PricingTable.from_mapping(json.loads(text))


def fetch_pricing(
    url: str = DEFAULT_PRICING_URL,
    *,
    timeout_s: float = 30.0,
    transport: Any | None = None,
) -> PricingTable:
    """Fetch a maintained pricing table over HTTPS — the explicit freshness opt-in.

    Nothing in the library calls this implicitly. An application that wants prices newer
    than its installed release calls it on its own schedule and passes the result to the
    client's ``pricing_table``.

    Args:
        url: Where to fetch from; defaults to the repo's continuously-updated file.
        timeout_s: Request timeout.
        transport: Test seam — an ``httpx2`` transport.

    Returns:
        The fetched, validated table.

    Raises:
        ConfigError: If the fetch fails or the response is not a valid pricing document.
    """
    import httpx2

    try:
        with httpx2.Client(transport=transport, timeout=timeout_s) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
    except httpx2.HTTPError as exc:
        raise ConfigError(
            f"could not fetch the pricing table from {url}: {exc}",
            hint="check connectivity, or keep using the bundled load_default_pricing()",
        ) from exc
    except ValueError as exc:
        raise ConfigError(
            f"the pricing table at {url} is not valid JSON: {exc}",
        ) from exc
    return PricingTable.from_mapping(payload)
