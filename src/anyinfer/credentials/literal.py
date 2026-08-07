"""Literal credential resolver — the value *is* the secret."""

from __future__ import annotations

from . import env, keyring_store

__all__ = ["LiteralResolver"]

# The bare scheme names, not the full "scheme://" prefixes: declining on the name alone
# is what makes a malformed reference (a typo'd "env:/OPENAI_KEY") fail loudly instead of
# silently becoming a literal secret.
_KNOWN_SCHEMES = (env._SCHEME.removesuffix("//"), keyring_store._SCHEME.removesuffix("//"))


class LiteralResolver:
    """Treats the reference itself as the secret.

    Placed last in the chain: it declines anything that looks like a known scheme, so a
    typo'd ``env:/OPENAI_KEY`` fails loudly rather than silently becoming a literal.
    """

    def handles(self, reference: str) -> bool:
        """Whether ``reference`` is a bare secret rather than a scheme reference."""
        return not reference.startswith(_KNOWN_SCHEMES)

    def resolve(self, reference: str) -> str:
        """Return the reference verbatim."""
        return reference
