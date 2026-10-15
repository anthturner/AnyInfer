"""Entry-point discovery for the extension points that are not provider adapters.

Entry-point discovery is a headline capability of the provider registry, and for a long
time `anyinfer.providers` was the only group using it. That gap is invisible from Python —
an application can always pass an observer or a resolver to the constructor — but it is
decisive for the standalone sidecar, which has no constructor to reach: `anyinfer serve`
can only use what a configuration file can *name*, and a name is resolvable only if
something published it.

Two groups are defined here, deliberately narrow:

``anyinfer.observers``
    Telemetry sinks a config file can name. Each entry point resolves to an `Observer`,
    or to a callable returning one — the callable form is what lets a sink take options
    (`{"name": "jsonl", "options": {"path": "..."}}`).

``anyinfer.credential_stores``
    `CredentialResolver` implementations that add a reference scheme, so an organization's
    own vault becomes usable from the same config file every frontend reads, without a
    fork of the resolver chain.

Reducers and token estimators stay constructor-injection only. Both take an application's
own judgement as arguments and neither is meaningfully expressible as a config-file name,
so a group for them would be surface without a use.

**Failures are recorded, never raised.** A broken third-party package must not stop a
client from starting; the same discipline `ProviderRegistry` applies, reusing its
`PluginLoadIssue` vocabulary so a caller inspects one shape regardless of what failed.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from .registry import PluginLoadIssue

__all__ = [
    "CREDENTIAL_STORE_GROUP",
    "OBSERVER_GROUP",
    "load_credential_stores",
    "load_observers",
]

OBSERVER_GROUP = "anyinfer.observers"
"""Entry-point group for config-nameable telemetry sinks."""

CREDENTIAL_STORE_GROUP = "anyinfer.credential_stores"
"""Entry-point group for credential resolvers adding a reference scheme."""

_RESERVED_SCHEMES = ("env://", "credential://")
"""Schemes the built-in resolvers own; a plugin claiming one is refused."""


def _load_group(group: str) -> tuple[dict[str, Any], list[PluginLoadIssue]]:
    """Load every entry point in `group`, collecting failures instead of raising.

    Returns the loaded objects keyed by entry-point name, plus one `PluginLoadIssue` per
    entry point that could not be loaded. The objects are returned *unvalidated*: what
    counts as usable differs per group, so each caller checks its own shape and records
    its own issue.
    """
    issues: list[PluginLoadIssue] = []
    loaded: dict[str, Any] = {}
    try:
        points = entry_points(group=group)
    except Exception:  # noqa: BLE001 — metadata backends vary across environments
        return loaded, issues
    for point in points:
        try:
            loaded[point.name] = point.load()
        except Exception as exc:  # noqa: BLE001 — a broken plugin must not break us
            issues.append(
                PluginLoadIssue(
                    entry_point=point.name,
                    reason="import-failed",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
    return loaded, issues


def load_observers() -> tuple[dict[str, Any], list[PluginLoadIssue]]:
    """Discover telemetry sinks published under `OBSERVER_GROUP`.

    Returns:
        A ``(factories, issues)`` pair. Each factory is either an `Observer` instance or
        a callable that builds one from keyword options; the caller decides which by
        whether it has options to pass.

    Note:
        Nothing is instantiated here. A sink that opens a file should not do so merely
        because a package that provides it happens to be installed.
    """
    return _load_group(OBSERVER_GROUP)


def load_credential_stores() -> tuple[dict[str, Any], list[PluginLoadIssue]]:
    """Discover credential resolvers published under `CREDENTIAL_STORE_GROUP`.

    Discovered resolvers are placed ahead of the built-ins in `default_resolver`, so
    first refusal is exactly what makes a custom scheme work — and exactly what would let
    an installed distribution interpose on the built-in ones. Any resolver claiming to
    handle ``env://`` or ``credential://`` is therefore dropped with a ``scheme-reserved``
    issue, mirroring the id/alias-collision refusal the `anyinfer.providers` group has
    enforced since it shipped. A plugin is trusted to add a scheme, never to redefine one.

    That guard bounds interposition, not code execution: an installed package already runs
    arbitrary code at interpreter startup by other means, and this group's entry points are
    imported and instantiated like any other. What it removes is the specific case where a
    compromised transitive dependency silently becomes the resolver for every credential
    in the process without the operator having named it anywhere.

    Returns:
        A ``(resolvers, issues)`` pair. Entries that are callable are called with no
        arguments to build the resolver; anything failing the `CredentialResolver`
        protocol, or claiming a built-in scheme, is dropped with an issue rather than
        reaching the chain.
    """
    from .credentials.resolver import CredentialResolver

    loaded, issues = _load_group(CREDENTIAL_STORE_GROUP)
    resolvers: dict[str, Any] = {}
    for name, obj in loaded.items():
        try:
            candidate = obj() if callable(obj) and not isinstance(obj, type) else obj
            if isinstance(candidate, type):
                candidate = candidate()
        except Exception as exc:  # noqa: BLE001
            issues.append(
                PluginLoadIssue(
                    entry_point=name,
                    reason="import-failed",
                    detail=f"constructing failed: {type(exc).__name__}: {exc}",
                )
            )
            continue
        if not isinstance(candidate, CredentialResolver):
            issues.append(
                PluginLoadIssue(
                    entry_point=name,
                    reason="not-a-descriptor",
                    detail=(
                        f"{type(candidate).__name__} does not implement "
                        "CredentialResolver (needs handles() and resolve())"
                    ),
                )
            )
            continue
        reserved = _reserved_scheme_claimed_by(candidate)
        if reserved is not None:
            issues.append(
                PluginLoadIssue(
                    entry_point=name,
                    reason="scheme-reserved",
                    detail=(
                        f"{type(candidate).__name__} claims the built-in scheme "
                        f"{reserved!r}, which plugins may not resolve"
                    ),
                )
            )
            continue
        resolvers[name] = candidate
    return resolvers, issues


def _reserved_scheme_claimed_by(resolver: Any) -> str | None:
    """Return the first built-in scheme `resolver` claims, or None.

    Probed by asking rather than by inspecting, because `handles` is the only thing the
    `CredentialResolver` protocol defines — a resolver matching on a prefix, a regex, or a
    parsed URL all answer the same question the same way. A probe that raises is treated
    as a claim: a resolver that cannot answer whether it handles ``env://`` is not one to
    put ahead of the resolver that definitely does.
    """
    for scheme in _RESERVED_SCHEMES:
        try:
            if resolver.handles(f"{scheme}anyinfer-reserved-probe"):
                return scheme
        except Exception:  # noqa: BLE001 — an unanswerable probe counts against the plugin
            return scheme
    return None
