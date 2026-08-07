"""Target resolution.

Three spellings, one resolution path::

    "anthropic:claude-sonnet-5"   explicit provider and model
    "ollama:qwen3:8b"             model ids may contain colons — split on the FIRST only
    "medium"                      a catalog alias, resolved against configured providers

Resolution is deterministic and total: it either produces a `ResolvedTarget` or raises
a `ConfigError` naming what to do instead. It never silently falls
back to a different model than the caller asked for.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib.resources import files

from ..errors import ConfigError
from ..registry import ProviderRegistry, normalize_provider_id
from ..types.requests import ResolvedTarget, Target
from .model import Catalog

__all__ = ["load_default_catalog", "resolve_target"]


def resolve_target(
    target: Target,
    *,
    registry: ProviderRegistry,
    catalog: Catalog | None = None,
    configured_providers: Sequence[str] = (),
) -> ResolvedTarget:
    """Resolve a target string to a concrete provider and model.

    Args:
        target: An alias, or a ``provider:model`` pair.
        registry: Registry used to resolve provider aliases (``claude`` → ``anthropic``).
        catalog: Alias catalog, when alias resolution should be attempted.
        configured_providers: Providers configured on this client, in preference order.
            Alias resolution picks the first candidate present here, which makes the choice
            deterministic and controlled by the application's own ordering.

    Returns:
        The resolved target.

    Raises:
        ConfigError: On an empty target, an unknown provider, an unknown alias, or an alias
            with no candidate among the configured providers.
    """
    text = target.strip()
    if not text:
        raise ConfigError(
            "target is empty",
            hint="use 'provider:model' (e.g. 'ollama:qwen3:8b') or a catalog alias",
        )

    if ":" in text:
        provider_raw, model = text.split(":", 1)
        model = model.strip()
        if not model:
            raise ConfigError(
                f"target {target!r} names a provider but no model",
                hint="write it as 'provider:model'",
            )
        provider_id = registry.resolve_alias(normalize_provider_id(provider_raw))
        return ResolvedTarget(provider_id=provider_id, model=model, via_alias=None)

    if catalog is not None and catalog.has_alias(text):
        return _resolve_alias(text, catalog, configured_providers)

    known = ", ".join(catalog.alias_names()) if catalog else ""
    hint = "use 'provider:model' (e.g. 'anthropic:claude-sonnet-5')"
    if known:
        hint += f", or one of these aliases: {known}"
    raise ConfigError(f"unknown target {target!r}", hint=hint)


def _resolve_alias(
    alias: str,
    catalog: Catalog,
    configured_providers: Sequence[str],
) -> ResolvedTarget:
    """Pick the first configured provider that realizes this alias."""
    candidates = catalog.targets_for_alias(alias)
    if not candidates:
        raise ConfigError(
            f"catalog alias {alias!r} has no provider targets",
            hint="add a target for at least one provider to this alias",
        )

    order = [normalize_provider_id(p) for p in configured_providers]
    normalized = {normalize_provider_id(p): p for p in candidates}

    for provider_id in order:
        original = normalized.get(provider_id)
        if original is not None:
            target_entry = candidates[original]
            return ResolvedTarget(
                provider_id=provider_id,
                model=target_entry.model_ref,
                via_alias=alias,
            )

    available = ", ".join(sorted(normalized)) or "(none)"
    configured = ", ".join(order) or "(none)"
    raise ConfigError(
        f"alias {alias!r} has no target among the configured providers",
        hint=(
            f"alias {alias!r} supports: {available}; this client is configured for: "
            f"{configured}. Configure one of them, or use an explicit 'provider:model'."
        ),
    )


def load_default_catalog() -> Catalog:
    """Load the catalog bundled with this AnyInfer build.

    Two documents, overlaid: ``default.json`` carries the hand-edited alias policy, and
    ``models.json`` carries the machine-maintained logical model table with its own refresh
    cadence — the same split the bundled pricing table uses.
    """
    merged = Catalog.from_mapping(_bundled("default.json"))
    return merged.overlay(Catalog.from_mapping(_bundled("models.json")))


def _bundled(name: str) -> dict[str, object]:
    """Read one bundled catalog document."""
    resource = files("anyinfer.catalog").joinpath(name)
    with resource.open("r", encoding="utf-8") as handle:
        data: dict[str, object] = json.load(handle)
    return data
