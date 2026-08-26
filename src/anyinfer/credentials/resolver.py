"""Credential resolution.

A credential *reference* is a string a user can safely put in a config file. Three forms ship
in v1:

===========================  ==============================================================
``"sk-abc123…"``             a literal secret (discouraged in files, supported in code)
``"env://OPENAI_API_KEY"``   read from an environment variable
``"credential://system/x"``  read from the OS keyring (requires the ``[keyring]`` extra)
===========================  ==============================================================

Applications register additional resolvers for their own vaults. Every successfully resolved
secret is registered for redaction before it is returned, so it can never appear in a log
line, error detail, or telemetry event afterwards.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ..errors import CredentialError
from ..redaction import register_secret
from ..registry import PluginLoadIssue

__all__ = [
    "CredentialResolver",
    "ResolverChain",
    "default_resolver",
]


@runtime_checkable
class CredentialResolver(Protocol):
    """Resolves credential references of one scheme."""

    def handles(self, reference: str) -> bool:
        """Whether this resolver recognizes ``reference``."""
        ...

    def resolve(self, reference: str) -> str:
        """Resolve ``reference`` to a secret.

        Raises:
            CredentialError: If the reference is recognized but cannot be resolved.
        """
        ...


class ResolverChain:
    """Tries each resolver in order, returning the first match's result.

    The chain; not the individual resolvers — is responsible for registering resolved
    secrets for redaction, so a third-party resolver cannot forget to.
    """

    def __init__(
        self,
        resolvers: list[CredentialResolver],
        *,
        plugin_issues: Sequence[PluginLoadIssue] = (),
    ) -> None:
        self._resolvers = list(resolvers)
        self._plugin_issues = tuple(plugin_issues)

    def plugin_issues(self) -> tuple[PluginLoadIssue, ...]:
        """Entry points under `anyinfer.credential_stores` that did not become resolvers.

        Mirrors `ProviderRegistry.plugin_issues` deliberately, and for the same reason: a
        skipped plugin is invisible at the point it matters, where the only symptom is
        that a reference nothing installed can resolve fails with a scheme error. The
        chain records rather than raises, so the failure of one vault plugin cannot stop a
        process whose other credentials resolve fine — but the record has to be reachable.
        """
        return self._plugin_issues

    def add(self, resolver: CredentialResolver, *, first: bool = True) -> None:
        """Register an additional resolver, by default ahead of the built-ins."""
        if first:
            self._resolvers.insert(0, resolver)
        else:
            self._resolvers.append(resolver)

    def resolve(self, reference: str | None) -> str | None:
        """Resolve a credential reference.

        Args:
            reference: The reference string, or ``None`` for "no credential configured".

        Returns:
            The resolved secret, or ``None`` when ``reference`` is ``None`` or empty.

        Raises:
            CredentialError: If no resolver handles the reference, or resolution fails.
        """
        if reference is None or not reference.strip():
            return None
        ref = reference.strip()
        for resolver in self._resolvers:
            if resolver.handles(ref):
                secret = resolver.resolve(ref)
                register_secret(secret)
                return secret
        raise CredentialError(
            f"no credential resolver handles reference scheme in {_scheme_of(ref)!r}",
            hint=self._unhandled_hint(),
        )

    def _unhandled_hint(self) -> str:
        """Explain an unhandled scheme, naming a failed plugin when one could be the cause."""
        base = "use a literal value, 'env://VAR_NAME', or 'credential://system/name'"
        if not self._plugin_issues:
            return f"{base}; a custom scheme needs a plugin under 'anyinfer.credential_stores'"
        skipped = "; ".join(issue.summary for issue in self._plugin_issues)
        return f"{base} — note that a credential-store plugin was skipped: {skipped}"


def _scheme_of(reference: str) -> str:
    head, sep, _ = reference.partition("://")
    return f"{head}://" if sep else reference[:12]


def default_resolver() -> ResolverChain:
    """Build the standard resolver chain: plugins, keyring, env, then literal.

    Literal is last because it accepts anything; the scheme-specific resolvers must get first
    refusal.

    Resolvers published under the ``anyinfer.credential_stores`` entry-point group are
    placed *ahead* of the built-ins, so an organization's own vault scheme can be used
    from a plain config file — the sidecar has no other way to reach one. A plugin that
    claims a built-in scheme is dropped before it gets there, so being first in line
    cannot become a way to interpose on ``env://`` or ``credential://``; see
    `anyinfer.plugins.load_credential_stores`.

    A plugin that fails to load is skipped rather than raising: an unavailable vault must
    not stop a process whose other credentials resolve fine. Each skip is warned once
    here and kept on the chain's `ResolverChain.plugin_issues`, because a silently
    skipped resolver is indistinguishable from a mistyped scheme at the point it fails.
    """
    from ..plugins import load_credential_stores
    from .env import EnvResolver
    from .keyring_store import KeyringResolver
    from .literal import LiteralResolver

    discovered, issues = load_credential_stores()
    for issue in issues:
        warnings.warn(
            f"credential-store plugin skipped — {issue.summary}",
            RuntimeWarning,
            stacklevel=2,
        )
    plugins = [discovered[name] for name in sorted(discovered)]
    return ResolverChain(
        [*plugins, KeyringResolver(), EnvResolver(), LiteralResolver()],
        plugin_issues=issues,
    )
