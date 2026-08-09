"""Shared JSON configuration for the Python API, CLI, demo, and sidecar."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .._client.providers import ProviderSettings
from ..context.settings import DEFAULT_TUNING, ContextTuning
from ..errors import ConfigError
from ..registry import ProviderRegistry, default_registry, normalize_provider_id
from ..routing import Route
from ..types.requests import CACHE_MODES, HISTORY_MODES, CachePolicy, HistoryPolicy

__all__ = [
    "CONFIG_FORMAT_VERSION",
    "MAX_CONFIG_BYTES",
    "AnyInferConfig",
    "load_config",
    "loads_config",
]

CONFIG_FORMAT_VERSION = 1
"""The configuration format version written and understood by this release."""

MAX_CONFIG_BYTES = 1024 * 1024
"""Maximum accepted configuration size."""

_ROOT_KEYS = frozenset(
    {
        "format_version",
        "providers",
        "default_route",
        "context",
        "history",
        "cache",
        # Settings owned by the bundled demo. They are accepted so one file can be
        # shared with the SDK, CLI, and sidecar; this loader intentionally ignores them.
        "targets",
        "system_prompt",
        "theme",
        "context_window_tokens",
    }
)
_IDENTITY_KEYS = frozenset({"id", "adapter", "provider_id", "alias", "enabled"})
_SETTING_KEYS = frozenset(
    {"base_url", "api_key", "api_version", "headers", "options", "timeout_s", "values"}
)
_DIRECT_SETTING_KEYS = frozenset({"base_url", "api_key", "api_version"})


@dataclass(frozen=True, slots=True)
class AnyInferConfig:
    """Validated configuration shared by every AnyInfer integration surface.

    Pass `providers` and `route` directly to `Client` or `AsyncClient`. The same object is
    used by the command-line runner and OpenAI-compatible sidecar.

    Attributes:
        providers: Configured provider instances, in declaration order.
        route: Default fallback route, when one was configured.
        format_version: Parsed file-format version.
        context: Advanced context-reduction settings from the optional ``context`` block.
            Pass to `anyinfer.context.select` as ``tuning=``. Defaults reproduce the
            library's plain behaviour, so a file without the block behaves as before.
        history: Conversation-compaction policy from the optional ``history`` block, or
            ``None`` when the file does not ask for one. Pass to `Client` or `AsyncClient`
            as ``history=``; every frontend built on that client then behaves identically.
        cache: Prompt-cache placement from the optional ``cache`` block, or ``None`` when
            the file does not ask for one. Pass to `Client` or `AsyncClient` as ``cache=``.
            Absent means no placement — caching changes what a provider bills, so it is
            never turned on by a file that did not name it.
    """

    providers: tuple[ProviderSettings, ...] = ()
    route: Route | None = None
    format_version: int = CONFIG_FORMAT_VERSION
    context: ContextTuning = DEFAULT_TUNING
    history: HistoryPolicy | None = None
    cache: CachePolicy | None = None


def load_config(
    path: str | Path,
    *,
    registry: ProviderRegistry | None = None,
) -> AnyInferConfig:
    """Read and validate an AnyInfer JSON configuration file.

    Args:
        path: File to read.
        registry: Provider registry used to validate setup-field names. Defaults to the
            process-wide registry, including installed third-party providers.

    Raises:
        ConfigError: If the file cannot be read or does not match the shared format.
    """
    source = Path(path)
    try:
        size = source.stat().st_size
        if size > MAX_CONFIG_BYTES:
            raise _error(
                source,
                f"file is {size} bytes; the limit is {MAX_CONFIG_BYTES} bytes",
            )
        text = source.read_text(encoding="utf-8")
    except ConfigError:
        raise
    except OSError as exc:
        raise _error(source, f"cannot read file: {exc}") from exc
    except UnicodeError as exc:
        raise _error(source, "file is not valid UTF-8") from exc
    return loads_config(text, source=str(source), registry=registry)


def loads_config(
    text: str,
    *,
    source: str = "<string>",
    registry: ProviderRegistry | None = None,
) -> AnyInferConfig:
    """Parse and validate AnyInfer configuration from a JSON string.

    Args:
        text: UTF-8 JSON text.
        source: Human-readable source name included in validation errors.
        registry: Provider registry used to validate setup-field names.

    Raises:
        ConfigError: If the text is too large, invalid JSON, or has invalid fields.
    """
    try:
        encoded_size = len(text.encode("utf-8"))
    except UnicodeError as exc:
        raise _error(source, "content is not valid UTF-8") from exc
    if encoded_size > MAX_CONFIG_BYTES:
        raise _error(source, f"content exceeds the {MAX_CONFIG_BYTES}-byte limit")
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise _error(source, f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise _error(source, "the document must be a JSON object")

    unknown_root = set(data) - _ROOT_KEYS
    if unknown_root:
        raise _unknown_keys(source, "top level", unknown_root)

    version = data.get("format_version", CONFIG_FORMAT_VERSION)
    if type(version) is not int or version != CONFIG_FORMAT_VERSION:
        raise _error(
            source,
            f"unsupported format_version {version!r}; expected {CONFIG_FORMAT_VERSION}",
        )

    raw_providers = data.get("providers", [])
    if not isinstance(raw_providers, list):
        raise _error(source, "'providers' must be a list")

    active_registry = registry or default_registry
    providers: list[ProviderSettings] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_providers):
        location = f"providers[{index}]"
        if not isinstance(raw, dict):
            raise _error(source, f"{location} must be an object")
        setting = _parse_provider(raw, source, location, active_registry)
        if setting is None:
            continue
        if setting.instance_id in seen:
            raise _error(
                source,
                f"provider instance {setting.instance_id!r} is configured more than once",
                provider=setting.instance_id,
                hint="give every provider instance a unique 'id'",
            )
        seen.add(setting.instance_id)
        providers.append(setting)

    route = _parse_route(data.get("default_route"), source)
    context = _parse_context(data.get("context"), source)
    history = _parse_history(data.get("history"), source)
    cache = _parse_cache(data.get("cache"), source)
    return AnyInferConfig(tuple(providers), route, version, context, history, cache)


def _parse_provider(
    raw: Mapping[str, Any],
    source: str,
    location: str,
    registry: ProviderRegistry,
) -> ProviderSettings | None:
    """Validate and normalize one provider entry."""
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise _error(source, f"{location}.enabled must be true or false")
    if not enabled:
        return None

    instance_value = raw.get("id")
    if not isinstance(instance_value, str) or not instance_value.strip():
        raise _error(source, f"{location}.id must be a non-empty string")
    instance_id = normalize_provider_id(instance_value)

    adapter_value = raw.get("adapter")
    legacy_provider_value = raw.get("provider_id")
    if adapter_value and legacy_provider_value:
        if not isinstance(adapter_value, str) or not isinstance(legacy_provider_value, str):
            raise _error(source, f"{location}.adapter must be a non-empty string")
        if normalize_provider_id(adapter_value) != normalize_provider_id(legacy_provider_value):
            raise _error(
                source,
                f"{location}.adapter and legacy provider_id name different providers",
            )
    engine_value = adapter_value or legacy_provider_value or instance_value
    if not isinstance(engine_value, str) or not engine_value.strip():
        raise _error(source, f"{location}.adapter must be a non-empty string")
    engine_id = normalize_provider_id(engine_value)

    alias_value = raw.get("alias")
    if alias_value is not None:
        if not isinstance(alias_value, str) or not alias_value.strip():
            raise _error(source, f"{location}.alias must be a non-empty string")
        if normalize_provider_id(alias_value) != instance_id:
            raise _error(source, f"{location}.alias must match its 'id'")

    try:
        descriptor = registry.get(engine_id)
    except ConfigError as exc:
        raise _error(
            source,
            f"{location} names unknown provider {engine_id!r}",
            provider=engine_id,
            hint="run 'anyinfer providers' to list registered providers",
        ) from exc

    declared_keys = {field.key for field in descriptor.setup.fields}
    allowed_keys = _IDENTITY_KEYS | _SETTING_KEYS | declared_keys
    unknown = set(raw) - allowed_keys
    if unknown:
        raise _unknown_keys(source, location, unknown, provider=instance_id)

    values = raw.get("values", {})
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise _error(source, f"{location}.values must be an object")
    unknown_values = set(values) - (declared_keys | _DIRECT_SETTING_KEYS)
    if unknown_values:
        raise _unknown_keys(source, f"{location}.values", unknown_values, provider=instance_id)

    options = raw.get("options", {})
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise _error(source, f"{location}.options must be an object")
    merged_options = dict(options)

    direct: dict[str, Any] = {}
    for key in _DIRECT_SETTING_KEYS:
        value = raw.get(key, values.get(key))
        if value not in (None, ""):
            if not isinstance(value, str):
                raise _error(source, f"{location}.{key} must be a string")
            direct[key] = value

    for key in declared_keys - _DIRECT_SETTING_KEYS:
        value = raw.get(key, values.get(key))
        if value not in (None, "") and key not in merged_options:
            merged_options[key] = value

    headers = raw.get("headers", {})
    if headers is None:
        headers = {}
    if not isinstance(headers, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in headers.items()
    ):
        raise _error(source, f"{location}.headers must map strings to strings")

    timeout = raw.get("timeout_s", 120.0)
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0:
        raise _error(source, f"{location}.timeout_s must be a positive number")

    return ProviderSettings.of(
        engine_id,
        alias=instance_id if instance_id != engine_id else None,
        headers=headers,
        options=merged_options,
        timeout_s=float(timeout),
        **direct,
    )


def _parse_context(value: Any, source: str) -> ContextTuning:
    """Validate the optional advanced context-reduction block.

    The block names `anyinfer.context.ContextTuning` fields directly rather than
    inventing a second vocabulary, so a setting means the same thing in a config file, a
    ``--context-*`` flag, and a Python keyword argument.
    """
    if value is None:
        return DEFAULT_TUNING
    if not isinstance(value, dict):
        raise _error(source, "'context' must be an object")
    try:
        return ContextTuning.from_mapping(value)
    except ValueError as exc:
        raise _error(
            source,
            f"'context' is invalid: {exc}",
            hint="see the context reduction settings in the shared configuration guide",
        ) from exc


def _parse_history(value: Any, source: str) -> HistoryPolicy | None:
    """Validate the optional conversation-compaction block.

    Absent means no compaction, which is the shipped behaviour: a request that outgrows
    its window is rerouted or fails, and nothing is discarded without being asked for.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _error(source, "'history' must be an object")

    unknown = set(value) - {"enabled", "mode", "keep_recent", "keep_system"}
    if unknown:
        raise _unknown_keys(source, "'history'", unknown)

    fields: dict[str, Any] = {}
    for key in ("enabled", "keep_system"):
        if key in value:
            if not isinstance(value[key], bool):
                raise _error(source, f"history.{key} must be true or false")
            fields[key] = value[key]
    if "keep_recent" in value:
        raw = value["keep_recent"]
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise _error(source, "history.keep_recent must be an integer")
        fields["keep_recent"] = raw
    if "mode" in value:
        mode = value["mode"]
        if not isinstance(mode, str) or mode not in HISTORY_MODES:
            raise _error(
                source,
                f"history.mode must be one of {', '.join(HISTORY_MODES)}",
                hint="'last_resort' prefers a larger-window target; 'proactive' shrinks first",
            )
        fields["mode"] = mode

    try:
        return HistoryPolicy(**fields)
    except ValueError as exc:
        raise _error(source, f"'history' is invalid: {exc}") from exc


def _parse_cache(value: Any, source: str) -> CachePolicy | None:
    """Validate the optional prompt-cache block.

    Absent means no placement, which is the shipped behaviour: caching changes what a
    provider bills and how long it keeps a copy of the prompt, so a file that does not ask
    for it does not get it.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _error(source, "'cache' must be an object")

    known = {"mode", "min_segment_tokens", "max_marks", "include_tools", "include_system"}
    unknown = set(value) - known
    if unknown:
        raise _unknown_keys(source, "'cache'", unknown)

    fields: dict[str, Any] = {}
    for key in ("include_tools", "include_system"):
        if key in value:
            if not isinstance(value[key], bool):
                raise _error(source, f"cache.{key} must be true or false")
            fields[key] = value[key]
    for key in ("min_segment_tokens", "max_marks"):
        if key in value:
            raw = value[key]
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise _error(source, f"cache.{key} must be an integer")
            fields[key] = raw
    if "mode" in value:
        mode = value["mode"]
        if not isinstance(mode, str) or mode not in CACHE_MODES:
            raise _error(
                source,
                f"cache.mode must be one of {', '.join(CACHE_MODES)}",
                hint="'auto' uses the strongest mechanism the target offers",
            )
        fields["mode"] = mode

    try:
        return CachePolicy(**fields)
    except ValueError as exc:
        raise _error(source, f"'cache' is invalid: {exc}") from exc


def _parse_route(value: Any, source: str) -> Route | None:
    """Validate the optional default route."""
    if value is None or value == []:
        return None
    if not isinstance(value, list):
        raise _error(source, "'default_route' must be a list of target strings")
    if not all(isinstance(target, str) and target.strip() for target in value):
        raise _error(source, "every 'default_route' entry must be a non-empty string")
    return Route(targets=tuple(value))


def _unknown_keys(
    source: str | Path,
    location: str,
    keys: set[str],
    *,
    provider: str | None = None,
) -> ConfigError:
    """Build a consistent unknown-key error."""
    names = ", ".join(repr(key) for key in sorted(keys))
    return _error(
        source,
        f"{location} has unknown key(s): {names}",
        provider=provider,
        hint="remove misspelled keys or place adapter-specific values under 'options'",
    )


def _error(
    source: str | Path,
    detail: str,
    *,
    provider: str | None = None,
    hint: str | None = None,
) -> ConfigError:
    """Attach source context to a configuration error."""
    return ConfigError(
        f"configuration {source}: {detail}",
        provider=provider,
        hint=hint or "see the shared configuration guide for the supported format",
    )
