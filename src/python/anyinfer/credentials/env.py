"""Environment-variable credential resolver (``env://NAME``)."""

from __future__ import annotations

import os

from ..errors import CredentialError

__all__ = ["EnvResolver"]

_SCHEME = "env://"


class EnvResolver:
    """Resolves ``env://VAR_NAME`` against the process environment."""

    def handles(self, reference: str) -> bool:
        """Whether ``reference`` uses the ``env://`` scheme."""
        return reference.startswith(_SCHEME)

    def resolve(self, reference: str) -> str:
        """Read the named environment variable.

        Raises:
            CredentialError: If the variable is unset or empty.
        """
        name = reference[len(_SCHEME) :].strip()
        if not name:
            raise CredentialError(
                "env:// reference is missing a variable name",
                hint="write it as 'env://OPENAI_API_KEY'",
            )
        value = os.environ.get(name)
        if not value:
            raise CredentialError(
                f"environment variable {name} is not set",
                hint=f"export {name}=<your key> and retry",
            )
        return value
