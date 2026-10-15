"""Shared JSON configuration for the Python API, CLI, demo, and sidecar."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .._client.providers import ProviderSettings
from ..context.settings import DEFAULT_TUNING, ContextTuning
from ..errors import AnyInferError, ConfigError
from ..mcp import MCPServer
from ..registry import ProviderRegistry, default_registry, normalize_provider_id
from ..routing import Route
from ..types.requests import (
    ARENA_MEMO_MODES,
    ARENA_STRATEGIES,
    CACHE_MODES,
    HISTORY_MODES,
    ArenaPolicy,
    CachePolicy,
    HistoryPolicy,
    RateLimits,
    Repair,
)

__all__ = [
    "BUILTIN_OBSERVERS",
    "COMMENT_KEY",
    "CONFIG_FORMAT_VERSION",
    "MAX_CONFIG_BYTES",
    "AnyInferConfig",
    "ObserverSpec",
    "build_observers",
    "dump_config",
    "dumps_config",
    "load_config",
    "loads_config",
]

CONFIG_FORMAT_VERSION = 1
"""The configuration format version written and understood by this release."""

MAX_CONFIG_BYTES = 1024 * 1024
"""Maximum accepted configuration size."""

COMMENT_KEY = "_comment"
"""Root key carrying a human-readable note, accepted and ignored by the loader.

The format is JSON, not JSONC, so a generated file cannot explain itself in `//` lines
without becoming something this loader would reject. A string under this key is the
version of that idea the format can actually carry: `dumps_config(..., comments=True)`
writes one, and reading it back changes nothing.
"""

_ROOT_KEYS = frozenset(
    {
        COMMENT_KEY,
        "format_version",
        "providers",
        "default_route",
        "operation_routes",
        "context",
        "history",
        "cache",
        "repair",
        "observers",
        "arena",
        "arenas",
        "mcp",
        # Settings owned by the bundled demo. They are accepted so one file can be
        # shared with the SDK, CLI, and sidecar; this loader intentionally ignores them.
        "targets",
        "system_prompt",
        "theme",
        "context_window_tokens",
        "ignore_runtime_hardware_constraints",
    }
)
_IDENTITY_KEYS = frozenset({"id", "adapter", "provider_id", "alias", "enabled"})
_SETTING_KEYS = frozenset(
    {
        "base_url",
        "api_key",
        "api_version",
        "headers",
        "options",
        "timeout_s",
        "values",
        "limits",
        "proxy",
        "verify",
        "client_cert",
    }
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
        mcp: Model Context Protocol servers described by the optional ``mcp`` block. These
            are inert descriptions: loading a file never spawns a process or opens a
            socket. Pass them to `anyinfer.mcp.MCPToolset.connect` when tools are wanted.
        observers: Telemetry sinks *described* by the optional ``observers`` block, as
            `ObserverSpec`s. Inert: loading a file never opens a log. Call
            `build_observers` to construct them, then pass the result to `Client` or
            `AsyncClient` as ``observers=``. This is how a sidecar deployment gets an
            access log at all — it has no constructor for a caller to reach, so a sink it
            cannot name is a sink it cannot have.
        repair: Bounded schema-repair budget from the optional ``repair`` block, or
            ``None`` when the file does not ask for one. Pass to `Client` or
            `AsyncClient` as ``repair=``. Without it, structured output validates and
            fails rather than repairing — which is why a sidecar deployment could not
            reach the repair loop at all before this block existed.
        operation_routes: Per-operation default routes from the optional
            ``operation_routes`` block, keyed ``"embedding"``/``"rerank"``. An
            embedding route can never be selected for generation or vice versa —
            generation's default stays ``default_route``. Pass to `Client` or
            `AsyncClient` as ``operation_routes=``.
    """

    providers: tuple[ProviderSettings, ...] = ()
    route: Route | None = None
    format_version: int = CONFIG_FORMAT_VERSION
    context: ContextTuning = DEFAULT_TUNING
    history: HistoryPolicy | None = None
    cache: CachePolicy | None = None
    repair: Repair | None = None
    observers: tuple[ObserverSpec, ...] = ()
    arena: ArenaPolicy | None = None
    arenas: Mapping[str, ArenaPolicy] = field(default_factory=dict)
    mcp: tuple[MCPServer, ...] = ()
    operation_routes: Mapping[str, Route] = field(default_factory=dict)


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
    operation_routes = _parse_operation_routes(data.get("operation_routes"), source)
    context = _parse_context(data.get("context"), source)
    history = _parse_history(data.get("history"), source)
    cache = _parse_cache(data.get("cache"), source)
    repair = _parse_repair(data.get("repair"), source)
    observers = _parse_observers(data.get("observers"), source)
    arena = _parse_arena(data.get("arena"), source, "'arena'")
    arenas = _parse_arenas(data.get("arenas"), source)
    mcp = _parse_mcp(data.get("mcp"), source)
    return AnyInferConfig(
        providers=tuple(providers),
        route=route,
        format_version=version,
        context=context,
        history=history,
        cache=cache,
        repair=repair,
        observers=observers,
        arena=arena,
        arenas=arenas,
        mcp=mcp,
        operation_routes=operation_routes,
    )


def dumps_config(config: AnyInferConfig, *, comments: bool = False) -> str:
    """Render a configuration as the JSON text `loads_config` accepts.

    The other half of the shared format. Three frontends could read this file and none
    could write it, which left every example of the format as prose and left
    ``anyinfer init`` with no way to produce one but string templating.

    Round-tripping is the contract: ``loads_config(dumps_config(c)) == c`` for every
    configuration the loader accepts. What that costs is verbosity in one place — a
    provider instance carrying an opt-in policy emits that policy even when every field in
    it is standard, because an omitted block and a default-valued block mean different
    things to the loader and only one of them is what the caller had.

    Credential values are written exactly as configured. References such as ``env://`` and
    ``credential://`` remain references, while a literal credential remains literal. This
    function never resolves a reference, but callers must still review configurations that
    they constructed with literal secrets before writing or committing them. Discovery and
    `anyinfer init` produce references so their generated files contain no key material.

    Args:
        config: The configuration to render.
        comments: Write a leading `COMMENT_KEY` note explaining what the file is. Still
            JSON, and still accepted by the loader.

    Returns:
        UTF-8 JSON text, two-space indented, ending in a newline.

    Raises:
        ConfigError: If a provider's ``options`` or ``headers`` hold a value JSON cannot
            represent. Settings built in Python may carry anything; a file cannot.
    """
    document: dict[str, Any] = {}
    if comments:
        document[COMMENT_KEY] = (
            "AnyInfer configuration. Prefer credential references (env://VAR or "
            "credential://system/name); review literal credentials before committing."
        )
    document["format_version"] = CONFIG_FORMAT_VERSION

    providers = [_provider_json(settings) for settings in config.providers]
    if providers:
        document["providers"] = providers
    if config.route is not None:
        document["default_route"] = list(config.route.targets)
    if config.operation_routes:
        document["operation_routes"] = {
            operation: list(route.targets)
            for operation, route in config.operation_routes.items()
        }
    if config.context != DEFAULT_TUNING:
        document["context"] = _changed_fields(config.context, ContextTuning())
    if config.history is not None:
        document["history"] = _changed_fields(config.history, HistoryPolicy())
    if config.cache is not None:
        document["cache"] = _changed_fields(config.cache, CachePolicy())
    if config.repair is not None:
        document["repair"] = _changed_fields(config.repair, Repair())
    if config.observers:
        document["observers"] = [
            spec.name if not spec.options else {"name": spec.name, "options": dict(spec.options)}
            for spec in config.observers
        ]
    if config.arena is not None:
        document["arena"] = _arena_json(config.arena)
    if config.arenas:
        document["arenas"] = {name: _arena_json(policy) for name, policy in config.arenas.items()}
    if config.mcp:
        document["mcp"] = [_mcp_json(server) for server in config.mcp]

    try:
        return json.dumps(document, indent=2, sort_keys=False) + "\n"
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"this configuration cannot be written as JSON: {exc}",
            hint="provider options and headers must hold JSON values",
        ) from exc


def dump_config(config: AnyInferConfig, path: str | Path, *, force: bool = False) -> None:
    """Write a configuration to a file, refusing to replace one that exists.

    Destructive-by-default is not acceptable for a file a user may have hand-tuned, and a
    configuration file is exactly that kind of file. Overwriting is available and has to be
    asked for.

    Args:
        config: The configuration to write.
        path: Where to write it. Parent directories must already exist.
        force: Replace an existing file instead of refusing.

    Raises:
        ConfigError: If the path exists and ``force`` is false, if the configuration
            cannot be rendered, or if the file cannot be written.
    """
    destination = Path(path)
    text = dumps_config(config, comments=True)
    if destination.exists() and not force:
        raise ConfigError(
            f"{destination} already exists",
            hint="pass force=True to replace it, or write to a different path",
        )
    try:
        destination.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            f"cannot write {destination}: {exc}",
            hint="check the directory exists and is writable",
        ) from exc


def _provider_json(settings: ProviderSettings) -> dict[str, Any]:
    """Render one provider instance.

    ``adapter`` appears only when the instance is named something other than its engine,
    which is the multi-instance case: one entry per Azure tenant, each with its own id and
    all naming the same adapter.
    """
    entry: dict[str, Any] = {"id": settings.instance_id}
    if settings.instance_id != normalize_provider_id(settings.provider_id):
        entry["adapter"] = normalize_provider_id(settings.provider_id)
    for key in ("base_url", "api_key", "api_version"):
        value = getattr(settings, key)
        if value:
            entry[key] = value
    if settings.headers:
        entry["headers"] = dict(settings.headers)
    if settings.options:
        entry["options"] = dict(settings.options)
    if settings.timeout_s != 120.0:
        entry["timeout_s"] = settings.timeout_s
    if settings.limits is not None:
        entry["limits"] = _changed_fields(settings.limits, RateLimits())
    if settings.proxy:
        entry["proxy"] = settings.proxy
    if settings.verify is not None:
        entry["verify"] = settings.verify
    if settings.client_cert is not None:
        entry["client_cert"] = (
            list(settings.client_cert)
            if isinstance(settings.client_cert, tuple)
            else settings.client_cert
        )
    return entry


def _mcp_json(server: MCPServer) -> dict[str, Any]:
    """Render one Model Context Protocol server description."""
    entry: dict[str, Any] = {"name": server.name}
    if server.command:
        entry["command"] = list(server.command)
    if server.url:
        entry["url"] = server.url
    if server.env:
        entry["env"] = dict(server.env)
    if server.headers:
        entry["headers"] = dict(server.headers)
    if server.cwd:
        entry["cwd"] = server.cwd
    if server.timeout_s != 30.0:
        entry["timeout_s"] = server.timeout_s
    for key in ("allow_tools", "deny_tools"):
        names = getattr(server, key)
        if names:
            entry[key] = list(names)
    return entry


def _changed_fields(value: Any, reference: Any) -> dict[str, Any]:
    """The dataclass fields of ``value`` that differ from ``reference``.

    An empty object is the correct rendering of a policy left entirely at its defaults:
    the block's *presence* is what asks for the policy, and its contents only say how it
    was tuned. Dropping the block instead would turn "pace this provider by whatever it
    reports" back into "do not pace it at all".
    """
    import dataclasses

    return {
        f.name: _json_scalar(getattr(value, f.name))
        for f in dataclasses.fields(value)
        if getattr(value, f.name) != getattr(reference, f.name)
    }


def _json_scalar(value: Any) -> Any:
    """Render one settings value in its JSON form, tuples becoming lists."""
    if isinstance(value, tuple):
        return list(value)
    return value


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

    if "api_key" in direct:
        _check_credential_reference(direct["api_key"], source, location, instance_id)

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

    connection: dict[str, Any] = {}
    proxy = raw.get("proxy")
    if proxy is not None:
        if not isinstance(proxy, str) or not proxy.strip():
            raise _error(source, f"{location}.proxy must be a non-empty URL string")
        connection["proxy"] = proxy.strip()
    if "verify" in raw:
        verify = raw["verify"]
        if isinstance(verify, bool):
            if verify:
                # `true` is the default; storing it would only make the file noisier.
                pass
            else:
                connection["verify"] = False
        elif isinstance(verify, str) and verify.strip():
            connection["verify"] = verify.strip()
        else:
            raise _error(
                source,
                f"{location}.verify must be false or a path to a CA bundle",
                hint="true is the default; omit the key instead",
            )
    client_cert = raw.get("client_cert")
    if client_cert is not None:
        if isinstance(client_cert, str) and client_cert.strip():
            connection["client_cert"] = client_cert.strip()
        elif (
            isinstance(client_cert, list)
            and len(client_cert) in (2, 3)
            and all(isinstance(part, str) and part for part in client_cert)
        ):
            connection["client_cert"] = tuple(client_cert)
        else:
            raise _error(
                source,
                f"{location}.client_cert must be a path, or [cert, key], or "
                "[cert, key, password]",
            )

    if connection and not descriptor.honors_connection_settings:
        # Rejected rather than accepted-and-ignored, the same rule that makes a redundant
        # `verify: true` an error: a key the runtime silently drops is worse than one it
        # refuses, because the operator believes their CA bundle is in effect.
        raise _error(
            source,
            f"{location} sets {', '.join(sorted(connection))}, which the "
            f"{engine_id!r} adapter cannot honor",
            provider=instance_id,
            hint=(
                "this adapter delegates transport to a vendor SDK it does not configure; "
                "use the process environment (HTTPS_PROXY, SSL_CERT_FILE) instead"
            ),
        )

    return ProviderSettings.of(
        engine_id,
        alias=instance_id if instance_id != engine_id else None,
        headers=headers,
        options=merged_options,
        timeout_s=float(timeout),
        limits=_parse_limits(raw.get("limits"), source, location),
        **connection,
        **direct,
    )


def _bool_field(source: str | Path, location: str, raw: Mapping[str, Any], key: str) -> bool:
    """Validate ``raw[key]`` as a boolean, or raise a `ConfigError` naming the field.

    Assumes ``key in raw``; callers guard the optional-field check themselves so a field
    left out of the mapping is silently skipped rather than reported as invalid.
    """
    value = raw[key]
    if not isinstance(value, bool):
        raise _error(source, f"{location}.{key} must be true or false")
    return value


def _int_field(
    source: str | Path,
    location: str,
    raw: Mapping[str, Any],
    key: str,
    *,
    allow_float: bool = False,
) -> int | float:
    """Validate ``raw[key]`` as a number, or raise a `ConfigError` naming the field.

    ``allow_float`` widens the check to accept a float too, returned coerced to ``float``
    — for a field whose dataclass declares it ``float`` rather than ``int``. Booleans are
    always rejected even though ``bool`` is an ``int`` subtype.
    """
    value = raw[key]
    if allow_float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise _error(source, f"{location}.{key} must be a number")
        return float(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(source, f"{location}.{key} must be an integer")
    return value


def _enum_field(
    source: str | Path,
    location: str,
    raw: Mapping[str, Any],
    key: str,
    choices: tuple[str, ...],
    *,
    hint: str | None = None,
) -> str:
    """Validate ``raw[key]`` as a member of ``choices``, or raise a `ConfigError`."""
    value = raw[key]
    if not isinstance(value, str) or value not in choices:
        raise _error(source, f"{location}.{key} must be one of {', '.join(choices)}", hint=hint)
    return value


def _parse_limits(value: Any, source: str, location: str) -> RateLimits | None:
    """Validate a provider entry's optional ``limits`` block.

    Nested inside the provider rather than declared at the root, because a rate limit is a
    property of an account at a provider: two instances of the same engine on two keys have
    two independent allowances, and a single top-level number could not say which it meant.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _error(source, f"{location}.limits must be an object")

    known = {
        "max_concurrent",
        "requests_per_minute",
        "min_interval_s",
        "respect_headers",
        "reserve_fraction",
    }
    unknown = set(value) - known
    if unknown:
        raise _unknown_keys(source, f"{location}.limits", unknown)

    limits_location = f"{location}.limits"
    fields: dict[str, Any] = {}
    if "max_concurrent" in value:
        fields["max_concurrent"] = _int_field(source, limits_location, value, "max_concurrent")
    for key in ("requests_per_minute", "min_interval_s", "reserve_fraction"):
        if key in value:
            fields[key] = _int_field(source, limits_location, value, key, allow_float=True)
    if "respect_headers" in value:
        fields["respect_headers"] = _bool_field(source, limits_location, value, "respect_headers")

    try:
        return RateLimits(**fields)
    except ValueError as exc:
        raise _error(
            source,
            f"{location}.limits is invalid: {exc}",
            hint="pacing is opt-in; omit the block entirely to dispatch without it",
        ) from exc


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
            fields[key] = _bool_field(source, "history", value, key)
    if "keep_recent" in value:
        fields["keep_recent"] = _int_field(source, "history", value, "keep_recent")
    if "mode" in value:
        fields["mode"] = _enum_field(
            source,
            "history",
            value,
            "mode",
            HISTORY_MODES,
            hint="'last_resort' prefers a larger-window target; 'proactive' shrinks first",
        )

    try:
        return HistoryPolicy(**fields)
    except ValueError as exc:
        raise _error(source, f"'history' is invalid: {exc}") from exc


def _parse_arena(value: Any, source: str, location: str = "'arena'") -> ArenaPolicy | None:
    """Validate one default or named arena policy."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _error(source, f"{location} must be an object")
    known = {
        "targets",
        "strategy",
        "judge_target",
        "instructions",
        "concurrency",
        "min_candidates",
        "reveal_targets",
        "memoize_tools",
    }
    unknown = set(value) - known
    if unknown:
        raise _unknown_keys(source, location, unknown)
    raw_targets = value.get("targets")
    if (
        not isinstance(raw_targets, list)
        or not raw_targets
        or not all(isinstance(item, str) and item for item in raw_targets)
    ):
        raise _error(source, f"{location}.targets must be a non-empty list of strings")
    fields: dict[str, Any] = {"targets": tuple(raw_targets)}
    for key in ("strategy", "judge_target", "instructions", "memoize_tools"):
        if key in value:
            raw = value[key]
            if raw is not None and not isinstance(raw, str):
                raise _error(source, f"{location}.{key} must be a string")
            fields[key] = raw
    if fields.get("strategy", "first_valid") not in ARENA_STRATEGIES:
        raise _error(source, f"{location}.strategy must be one of {', '.join(ARENA_STRATEGIES)}")
    if fields.get("memoize_tools", "read_only") not in ARENA_MEMO_MODES:
        raise _error(
            source,
            f"{location}.memoize_tools must be one of {', '.join(ARENA_MEMO_MODES)}",
        )
    for key in ("concurrency", "min_candidates"):
        if key in value:
            fields[key] = _int_field(source, location, value, key)
    if "reveal_targets" in value:
        fields["reveal_targets"] = _bool_field(source, location, value, "reveal_targets")
    try:
        return ArenaPolicy(**fields)
    except ValueError as exc:
        raise _error(source, f"{location} is invalid: {exc}") from exc


def _parse_arenas(value: Any, source: str) -> Mapping[str, ArenaPolicy]:
    """Validate named arena policies addressable from a sidecar model string."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _error(source, "'arenas' must be an object keyed by arena name")
    result: dict[str, ArenaPolicy] = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not name:
            raise _error(source, "arena names must be non-empty strings")
        policy = _parse_arena(raw, source, f"arenas.{name}")
        if policy is None:
            raise _error(source, f"arenas.{name} must be an object")
        result[name] = policy
    return result


def _arena_json(policy: ArenaPolicy) -> dict[str, Any]:
    """Render every arena field so config parity cannot hide an implicit default."""
    return {
        "targets": list(policy.targets),
        "strategy": policy.strategy,
        "judge_target": policy.judge_target,
        "instructions": policy.instructions,
        "concurrency": policy.concurrency,
        "min_candidates": policy.min_candidates,
        "reveal_targets": policy.reveal_targets,
        "memoize_tools": policy.memoize_tools,
    }


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
            fields[key] = _bool_field(source, "cache", value, key)
    for key in ("min_segment_tokens", "max_marks"):
        if key in value:
            fields[key] = _int_field(source, "cache", value, key)
    if "mode" in value:
        fields["mode"] = _enum_field(
            source,
            "cache",
            value,
            "mode",
            CACHE_MODES,
            hint="'auto' uses the strongest mechanism the target offers",
        )

    try:
        return CachePolicy(**fields)
    except ValueError as exc:
        raise _error(source, f"'cache' is invalid: {exc}") from exc


BUILTIN_OBSERVERS = ("logging", "jsonl")
"""Sink names that need no plugin installed."""


@dataclass(frozen=True, slots=True)
class ObserverSpec:
    """A telemetry sink named in configuration, not yet built.

    Inert by design, exactly as `MCPServer` is: reading a configuration file must not
    open a log file any more than it should spawn a subprocess. `build_observers` turns
    these into live sinks when a frontend actually wants them.

    Attributes:
        name: ``"logging"``, ``"jsonl"``, or a name published under the
            ``anyinfer.observers`` entry-point group.
        options: Keyword arguments for the sink's constructor.
    """

    name: str
    options: Mapping[str, Any] = field(default_factory=dict)


def _parse_observers(value: Any, source: str) -> tuple[ObserverSpec, ...]:
    """Validate the optional telemetry-sink block into inert specs.

    Each entry is ``{"name": ..., "options": {...}}``, or a bare string when a sink needs
    no options. Names are checked against the built-ins and the entry-point group here,
    so a typo fails at load rather than at the first event.

    **Validating a non-builtin name imports the package that provides it**, because
    `entry_points` metadata carries only the name and the target string — confirming a
    name resolves to something real means calling `EntryPoint.load()`. Accepted rather
    than avoided: the alternative is a name that parses cleanly and fails at
    `build_observers`, which is the failure this validation exists to move earlier, and a
    configuration naming a third-party sink has already decided to run that package. The
    import happens only when a name is *not* a built-in, so the ordinary file pays
    nothing. Recorded here as the deliberate choice it is.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        raise _error(source, "'observers' must be an array")

    discovered: dict[str, Any] | None = None
    specs: list[ObserverSpec] = []
    for index, entry in enumerate(value):
        if isinstance(entry, str):
            name, options = entry.strip(), {}
        elif isinstance(entry, dict):
            unknown = set(entry) - {"name", "options"}
            if unknown:
                raise _unknown_keys(source, f"'observers[{index}]'", unknown)
            raw_name = entry.get("name")
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise _error(source, f"'observers[{index}]' needs a non-empty 'name'")
            raw_options = entry.get("options", {})
            if not isinstance(raw_options, dict):
                raise _error(source, f"'observers[{index}].options' must be an object")
            name, options = raw_name.strip(), dict(raw_options)
        else:
            raise _error(
                source, f"'observers[{index}]' must be a string or an object with 'name'"
            )

        if name not in BUILTIN_OBSERVERS:
            if discovered is None:
                from ..plugins import load_observers

                discovered, _issues = load_observers()
            if name not in discovered:
                known = ", ".join([*BUILTIN_OBSERVERS, *sorted(discovered)])
                raise _error(
                    source,
                    f"unknown observer {name!r}",
                    hint=f"install a package providing it, or use one of: {known}",
                )
        specs.append(ObserverSpec(name=name, options=options))
    return tuple(specs)


def build_observers(specs: Sequence[ObserverSpec]) -> tuple[Any, ...]:
    """Construct live telemetry sinks from configured specs.

    Separate from loading so that reading a file has no side effects — a `jsonl` sink
    opens and holds a file, and that should happen when a frontend decides to observe,
    not when a config file is parsed.

    Args:
        specs: Usually `AnyInferConfig.observers`.

    Returns:
        The constructed sinks, ready to pass as ``observers=``.

    Raises:
        anyinfer.errors.ConfigError: A sink rejected its options, could not open its
            file, or its plugin failed to build.
    """
    from ..events.sinks import JsonlObserver, LoggingObserver

    discovered: dict[str, Any] | None = None
    built: list[Any] = []
    for spec in specs:
        options = dict(spec.options)
        try:
            if spec.name == "jsonl":
                built.append(JsonlObserver(**options))
            elif spec.name == "logging":
                built.append(LoggingObserver(**options))
            else:
                if discovered is None:
                    from ..plugins import load_observers

                    discovered, _issues = load_observers()
                factory = discovered.get(spec.name)
                if factory is None:
                    raise ConfigError(
                        f"observer {spec.name!r} is no longer installed",
                        hint="install the package that provides it, or remove it",
                    )
                built.append(factory(**options) if callable(factory) else factory)
        except ConfigError:
            raise
        except (TypeError, OSError, ValueError) as exc:
            raise ConfigError(
                f"observer {spec.name!r} could not be built: {exc}",
                hint="check its 'options' against the sink's constructor",
            ) from exc
    return tuple(built)


def _parse_repair(value: Any, source: str) -> Repair | None:
    """Validate the optional bounded schema-repair budget.

    Absent means no repair: a schema violation is surfaced as an error rather than
    retried. That stays the default because a repair round-trip costs another call the
    caller did not ask for, so a file that did not name it never spends one.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _error(source, "'repair' must be an object")

    known = {"max_attempts"}
    unknown = set(value) - known
    if unknown:
        raise _unknown_keys(source, "'repair'", unknown)

    fields: dict[str, Any] = {}
    if "max_attempts" in value:
        fields["max_attempts"] = _int_field(source, "repair", value, "max_attempts")

    try:
        return Repair(**fields)
    except ValueError as exc:
        raise _error(source, f"'repair' is invalid: {exc}") from exc


def _parse_mcp(value: Any, source: str) -> tuple[MCPServer, ...]:
    """Validate the optional Model Context Protocol server list.

    Absent means no tool sources, which is the shipped behaviour. Servers are *described*
    here, never connected: loading a configuration file must not spawn a process or open a
    socket, so the descriptions are inert until an application asks for them.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        raise _error(source, "'mcp' must be a list of server objects")

    known = {
        "name",
        "command",
        "url",
        "env",
        "headers",
        "cwd",
        "timeout_s",
        "allow_tools",
        "deny_tools",
    }
    servers: list[MCPServer] = []
    for index, raw in enumerate(value):
        location = f"mcp[{index}]"
        if not isinstance(raw, dict):
            raise _error(source, f"{location} must be an object")
        unknown = set(raw) - known
        if unknown:
            raise _unknown_keys(source, f"'{location}'", unknown)

        fields: dict[str, Any] = {"name": raw.get("name", "")}
        if "command" in raw:
            command = raw["command"]
            if not isinstance(command, list) or not all(isinstance(p, str) for p in command):
                raise _error(source, f"{location}.command must be a list of strings")
            fields["command"] = tuple(command)
        for key in ("url", "cwd"):
            if key in raw:
                if not isinstance(raw[key], str):
                    raise _error(source, f"{location}.{key} must be a string")
                fields[key] = raw[key]
        for key in ("env", "headers"):
            if key in raw:
                mapping = raw[key]
                if not isinstance(mapping, dict) or not all(
                    isinstance(k, str) and k and isinstance(v, str)
                    for k, v in mapping.items()
                ):
                    raise _error(
                        source,
                        f"{location}.{key} must map non-empty strings to strings",
                    )
                fields[key] = dict(mapping)
        if "timeout_s" in raw:
            fields["timeout_s"] = _int_field(source, location, raw, "timeout_s", allow_float=True)
        for key in ("allow_tools", "deny_tools"):
            if key in raw:
                names = raw[key]
                if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                    raise _error(source, f"{location}.{key} must be a list of strings")
                fields[key] = tuple(names)

        try:
            servers.append(MCPServer(**fields))
        except AnyInferError as exc:
            raise _error(source, f"{location} is invalid: {exc.detail}") from exc

    return tuple(servers)


def _parse_route(value: Any, source: str) -> Route | None:
    """Validate the optional default route."""
    if value is None or value == []:
        return None
    if not isinstance(value, list):
        raise _error(source, "'default_route' must be a list of target strings")
    if not all(isinstance(target, str) and target.strip() for target in value):
        raise _error(source, "every 'default_route' entry must be a non-empty string")
    return Route(targets=tuple(value))


_OPERATION_ROUTE_KEYS = frozenset({"embedding", "rerank"})
"""Operations that may carry their own default route.

Generation deliberately has no entry here: its default stays ``default_route``, so an
embedding route can never be selected for a generation request by key confusion —
the two vocabularies do not overlap.
"""


def _parse_operation_routes(value: Any, source: str) -> Mapping[str, Route]:
    """Validate the optional per-operation default routes."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _error(source, "'operation_routes' must be an object keyed by operation")
    routes: dict[str, Route] = {}
    for operation, targets in value.items():
        if operation not in _OPERATION_ROUTE_KEYS:
            raise _error(
                source,
                f"'operation_routes' has unknown operation {operation!r}",
                hint=(
                    "valid keys are 'embedding' and 'rerank'; the generation default "
                    "belongs in 'default_route'"
                ),
            )
        if not isinstance(targets, list) or not targets:
            raise _error(
                source, f"'operation_routes.{operation}' must be a non-empty list of targets"
            )
        if not all(isinstance(target, str) and target.strip() for target in targets):
            raise _error(
                source,
                f"every 'operation_routes.{operation}' entry must be a non-empty string",
            )
        routes[operation] = Route(targets=tuple(targets))
    return routes


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


_BUILTIN_CREDENTIAL_SCHEMES = ("env://", "credential://")
_SCHEME_SHAPED = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")


def _check_credential_reference(
    reference: str, source: str | Path, location: str, provider: str
) -> None:
    """Reject an `api_key` naming a scheme nothing installed can resolve.

    Observer names are validated at load, and a credential reference deserves the same
    treatment for a sharper reason: an unresolvable one used to be *accepted as the
    secret itself* and put on the wire as a bearer token. `LiteralResolver` now declines
    the whole scheme shape, so the failure is loud either way — but at load time it names
    the config location and the missing plugin instead of surfacing later as a misleading
    401 from the provider.

    Only a scheme-shaped, non-built-in reference reaches plugin discovery, so the common
    cases (a literal, ``env://``, ``credential://``) still parse without importing any
    third-party code. Discovery here is the same trade the observers block already makes,
    narrowed to the configurations that opted into it.
    """
    ref = reference.strip()
    if not _SCHEME_SHAPED.match(ref) or ref.startswith(_BUILTIN_CREDENTIAL_SCHEMES):
        return

    from ..plugins import CREDENTIAL_STORE_GROUP, load_credential_stores

    discovered, issues = load_credential_stores()
    for resolver in discovered.values():
        try:
            if resolver.handles(ref):
                return
        except Exception:  # noqa: BLE001 — a resolver that cannot answer does not handle it
            continue

    scheme = ref.partition("://")[0]
    hint = (
        f"install a package publishing it under '{CREDENTIAL_STORE_GROUP}', "
        "or use 'env://VAR_NAME', 'credential://system/name', or a literal value"
    )
    if issues:
        skipped = "; ".join(issue.summary for issue in issues)
        hint = f"{hint} — a credential-store plugin was skipped: {skipped}"
    raise _error(
        source,
        f"{location}.api_key uses scheme {scheme + '://'!r}, which no credential "
        "resolver handles",
        provider=provider,
        hint=hint,
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
