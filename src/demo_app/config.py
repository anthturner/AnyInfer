"""Demo configuration: what providers are enabled and how they are set up.

Deliberately generic. A provider's configuration is a plain ``{field key: value}`` mapping
whose keys come from that provider's `ProviderSetupSpec`, so
adding a provider to AnyInfer, or installing a third-party one via the entry-point group —
requires no change here and no change in the settings dialog.

Secrets are stored as credential *references* (``env://OPENAI_API_KEY``) whenever the user
supplies one, so the demo's config file on disk holds no key material. Literal keys typed
into the dialog are kept in memory only.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from anyinfer.config import CONFIG_FORMAT_VERSION

__all__ = ["CONFIG_PATH", "DemoConfig", "ProviderConfig", "default_config"]


def _config_dir() -> Path:
    """Per-user config directory, following each platform's convention."""
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "AnyInferDemo"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "anyinfer-demo"
    return Path.home() / ".config" / "anyinfer-demo"


CONFIG_PATH = _config_dir() / "demo.json"
"""Where the demo persists its settings."""


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """One configured provider *instance*, keyed by its engine's setup-spec field keys.

    An engine may be configured more than once — two Azure tenants, a local and a remote
    Ollama, so ``provider_id`` names the engine while `instance_id` names this
    particular configuration of it.
    """

    provider_id: str
    alias: str | None = None
    enabled: bool = False
    values: Mapping[str, str] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)

    @property
    def instance_id(self) -> str:
        """This instance's identity: the alias when set, else the provider id."""
        return self.alias or self.provider_id

    @property
    def base_url(self) -> str:
        """The configured endpoint, if this provider has an ``endpoint`` field."""
        return self.values.get("base_url", "")

    @property
    def api_key(self) -> str:
        """The configured credential reference or literal key."""
        return self.values.get("api_key", "")

    @property
    def api_version(self) -> str:
        """The configured API version, for providers that pin one."""
        return self.values.get("api_version", "")

    def extra_values(self) -> dict[str, str]:
        """Setup-spec values that are not one of `ProviderSettings`' own fields.

        `ProviderSettings` spells three settings at the top level; every *other* field a
        provider declares — Anthropic's OAuth token, Vertex's project and region — is
        carried in ``options``. Filtering by what the top level already covers, rather
        than by a list of known extras, is what keeps a provider that adds a field
        working here without an edit.
        """
        return {
            key: value
            for key, value in self.values.items()
            if key not in _SERVE_SETTING_KEYS and value
        }


_THEME_PREFERENCES = (
    "system",
    "light",
    "dark",
    "slate",
    "rose",
    "forest",
    "ocean",
    "sunset",
)

_SERVE_SETTING_KEYS = ("base_url", "api_key", "api_version")
"""`ProviderSettings` fields a serve config spells at the top level of an entry.

The demo nests these under ``values`` (they are setup-spec field keys); the serve file
writes them flat. Reading both is what makes one file work for both tools.
"""


def _provider_from_entry(entry: Mapping[str, Any]) -> ProviderConfig | None:
    """Parse one provider entry in either the demo's or the serve file's spelling."""
    engine = entry.get("provider_id") or entry.get("adapter") or entry.get("id")
    if not engine:
        return None
    instance = entry.get("alias") or entry.get("id") or engine
    # `adapter` present means `id` is the instance; `adapter` absent means they are the
    # same thing, and an alias equal to the engine is stored as no alias at all.
    alias = str(instance) if str(instance) != str(engine) else None

    values = {str(k): str(v) for k, v in (entry.get("values") or {}).items()}
    for key in _SERVE_SETTING_KEYS:
        if key not in values and entry.get(key) is not None:
            values[key] = str(entry[key])

    return ProviderConfig(
        provider_id=str(engine),
        alias=alias,
        # A serve entry has no notion of "disabled" — listing a provider is enabling it.
        enabled=bool(entry.get("enabled", "enabled" not in entry)),
        values=values,
        options=dict(entry.get("options") or {}),
    )


@dataclass(frozen=True, slots=True)
class DemoConfig:
    """The demo's whole persisted state."""

    providers: tuple[ProviderConfig, ...] = ()
    targets: tuple[str, ...] = ("demo-fake:reliable",)
    system_prompt: str = ""
    theme: str = "system"
    """OS-following, light/dark, or named custom appearance preference."""
    context_window_tokens: int | None = None
    """Manual context-window override in tokens; ``None`` means auto-detect."""
    ignore_runtime_hardware_constraints: bool = False
    """Allow runtime variants even when detected hardware cannot use them."""

    def enabled_providers(self) -> Iterator[ProviderConfig]:
        """Every provider instance the user turned on."""
        return (p for p in self.providers if p.enabled)

    def for_provider(self, instance_id: str) -> ProviderConfig:
        """One instance's configuration, defaulted when it has none yet.

        Matches on instance id, so an aliased instance is found by the alias the user
        gave it rather than by the engine it happens to be built from.
        """
        for provider in self.providers:
            if provider.instance_id == instance_id:
                return provider
        return ProviderConfig(provider_id=instance_id)

    def instances_of(self, provider_id: str) -> Iterator[ProviderConfig]:
        """Every configured instance of one engine, in configuration order."""
        return (p for p in self.providers if p.provider_id == provider_id)

    def instance_ids(self) -> tuple[str, ...]:
        """Every configured instance id, in configuration order."""
        return tuple(p.instance_id for p in self.providers)

    def with_provider(self, updated: ProviderConfig) -> DemoConfig:
        """Return a copy with one instance's configuration replaced."""
        others = [p for p in self.providers if p.instance_id != updated.instance_id]
        return replace(self, providers=(*others, updated))

    def with_providers(self, providers: Sequence[ProviderConfig]) -> DemoConfig:
        """Return a copy whose configured instances are exactly ``providers``.

        Distinct from `with_provider()`: the settings dialog can *remove* instances, and
        a merge-only update could never express a deletion.
        """
        return replace(self, providers=tuple(providers))

    def with_targets(self, targets: Sequence[str]) -> DemoConfig:
        """Return a copy with a new default routing chain."""
        return replace(self, targets=tuple(t for t in targets if t.strip()))

    # ---- persistence -----------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible mapping.

        Provider identity uses the shared ``id``/``adapter`` spelling. ``adapter`` appears
        only when the instance differs from its engine, so the common single-instance
        case stays tidy and the saved file works unchanged with the SDK, CLI, and sidecar.
        """
        return {
            "format_version": CONFIG_FORMAT_VERSION,
            "providers": [
                {
                    "id": p.instance_id,
                    **({"adapter": p.provider_id} if p.alias and p.alias != p.provider_id else {}),
                    "enabled": p.enabled,
                    "values": dict(p.values),
                    "options": dict(p.options),
                }
                for p in self.providers
            ],
            "targets": list(self.targets),
            # The same routing chain under the shared config format's key, so a file
            # saved here starts `anyinfer serve --config` on the same route.
            "default_route": list(self.targets),
            "system_prompt": self.system_prompt,
            "theme": self.theme,
            "context_window_tokens": self.context_window_tokens,
            "ignore_runtime_hardware_constraints": self.ignore_runtime_hardware_constraints,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> DemoConfig:
        """Rebuild from a persisted mapping, ignoring anything malformed.

        The shared ``id``/``adapter`` spelling is preferred. The former
        ``provider_id``/``alias`` spelling remains readable so existing demo configs
        migrate the next time they are saved.
        """
        version = data.get("format_version", CONFIG_FORMAT_VERSION)
        if type(version) is not int or version != CONFIG_FORMAT_VERSION:
            return default_config()

        providers: list[ProviderConfig] = []
        for entry in data.get("providers", []):
            if not isinstance(entry, Mapping):
                continue
            parsed = _provider_from_entry(entry)
            if parsed is not None:
                providers.append(parsed)
        # `default_route` is the shared config file's spelling of the same chain; reading
        # it lets a hand-written serve file open in the demo on its intended route.
        raw_targets = data.get("targets") or data.get("default_route") or ()
        targets = tuple(str(t) for t in raw_targets if str(t).strip())
        theme = str(data.get("theme", "system"))
        raw_tokens = data.get("context_window_tokens")
        tokens = raw_tokens if isinstance(raw_tokens, int) and raw_tokens > 0 else None
        raw_ignore_runtime_constraints = data.get("ignore_runtime_hardware_constraints", False)
        return cls(
            providers=tuple(providers),
            targets=targets or ("demo-fake:reliable",),
            system_prompt=str(data.get("system_prompt", "")),
            theme=theme if theme in _THEME_PREFERENCES else "system",
            context_window_tokens=tokens,
            ignore_runtime_hardware_constraints=(
                raw_ignore_runtime_constraints
                if isinstance(raw_ignore_runtime_constraints, bool)
                else False
            ),
        )

    def save(self, path: Path | None = None) -> None:
        """Write the configuration to disk, creating its directory if needed."""
        destination = path or CONFIG_PATH
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(self.to_json(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | None = None) -> DemoConfig:
        """Read the configuration, falling back to defaults when absent or corrupt."""
        source = path or CONFIG_PATH
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default_config()
        if not isinstance(data, Mapping):
            return default_config()
        return cls.from_json(data)


def default_config() -> DemoConfig:
    """The out-of-the-box configuration: offline fakes on, nothing else touched."""
    return DemoConfig(
        providers=(ProviderConfig(provider_id="demo-fake", enabled=True),),
        targets=("demo-fake:reliable",),
        system_prompt="You are a concise assistant demonstrating the AnyInfer library.",
    )
