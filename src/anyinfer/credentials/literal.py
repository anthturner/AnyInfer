"""Literal credential resolver — the value *is* the secret."""

from __future__ import annotations

import re

from . import env, keyring_store

__all__ = ["LiteralResolver"]

# The bare scheme names, not the full "scheme://" prefixes: declining on the name alone
# is what makes a malformed reference (a typo'd "env:/OPENAI_KEY") fail loudly instead of
# silently becoming a literal secret.
_KNOWN_SCHEMES = (env._SCHEME.removesuffix("//"), keyring_store._SCHEME.removesuffix("//"))

# Anything shaped like a URI scheme is declined as well, whether or not this build knows
# the scheme. The `anyinfer.credential_stores` entry-point group means the set of valid
# schemes is open — `vault://prod/openai` is a legitimate reference when its plugin is
# installed. If that plugin is missing or failed to import, matching on the known names
# alone would let the reference fall all the way through the chain and be accepted *as
# the secret*, sending an internal vault path to a provider as a bearer token. Declining
# the whole shape turns that into the loud `CredentialError` the chain already raises.
_SCHEME_SHAPED = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")


class LiteralResolver:
    """Treats the reference itself as the secret.

    Placed last in the chain: it declines anything that looks like a scheme reference, so
    both a typo'd ``env:/OPENAI_KEY`` and an unresolvable ``vault://prod/openai`` fail
    loudly rather than silently becoming a literal.
    """

    def handles(self, reference: str) -> bool:
        """Whether ``reference`` is a bare secret rather than a scheme reference."""
        if _SCHEME_SHAPED.match(reference):
            return False
        return not reference.startswith(_KNOWN_SCHEMES)

    def resolve(self, reference: str) -> str:
        """Return the reference verbatim."""
        return reference
