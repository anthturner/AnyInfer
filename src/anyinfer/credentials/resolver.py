"""Credential resolution (D8).

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

from typing import Protocol, runtime_checkable

from ..errors import CredentialError
from ..redaction import register_secret

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

    The chain — not the individual resolvers — is responsible for registering resolved
    secrets for redaction, so a third-party resolver cannot forget to.
    """

    def __init__(self, resolvers: list[CredentialResolver]) -> None:
        self._resolvers = list(resolvers)

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
            hint="use a literal value, 'env://VAR_NAME', or 'credential://system/name'",
        )


def _scheme_of(reference: str) -> str:
    head, sep, _ = reference.partition("://")
    return f"{head}://" if sep else reference[:12]


def default_resolver() -> ResolverChain:
    """Build the standard resolver chain: keyring, env, then literal.

    Literal is last because it accepts anything; the scheme-specific resolvers must get first
    refusal.
    """
    from .env import EnvResolver
    from .keyring_store import KeyringResolver
    from .literal import LiteralResolver

    return ResolverChain([KeyringResolver(), EnvResolver(), LiteralResolver()])
