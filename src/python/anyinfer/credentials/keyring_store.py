"""OS keyring credential resolver (``credential://backend/identifier``).

Requires the ``[keyring]`` extra. A missing extra is a `ConfigError`
with an install hint rather than an ``ImportError``, so the failure tells the user what to do.
"""

from __future__ import annotations

import re
from typing import Any

from ..errors import ConfigError, CredentialError

__all__ = ["KEYRING_SERVICE", "KeyringResolver"]

_SCHEME = "credential://"
KEYRING_SERVICE = "AnyInfer"
"""Service name under which secrets are stored in the OS vault."""

_SYSTEM_BACKEND = "system"
_IDENTIFIER = re.compile(r"^[a-z0-9](?:[a-z0-9._/-]*[a-z0-9])?$")


class KeyringResolver:
    """Resolves ``credential://system/<identifier>`` against the OS credential vault."""

    def handles(self, reference: str) -> bool:
        """Whether ``reference`` uses the ``credential://`` scheme."""
        return reference.startswith(_SCHEME)

    def resolve(self, reference: str) -> str:
        """Read the identified secret from the OS vault.

        Raises:
            ConfigError: If the ``[keyring]`` extra is not installed, or the reference is
                malformed.
            CredentialError: If the vault is unavailable, locked, or has no such entry.
        """
        backend_name, identifier = self._parse(reference)
        if backend_name != _SYSTEM_BACKEND:
            raise ConfigError(
                f"unknown credential backend {backend_name!r}",
                hint=f"the only built-in backend is '{_SYSTEM_BACKEND}'",
            )
        keyring = self._import_keyring()
        try:
            backend = keyring.get_keyring()
            if getattr(backend, "priority", 0) <= 0:
                raise CredentialError(
                    "no usable OS credential store is available on this system",
                    hint="configure a system keyring, or use 'env://VAR_NAME' instead",
                )
            secret = keyring.get_password(KEYRING_SERVICE, identifier)
        except CredentialError:
            raise
        except Exception as exc:
            raise CredentialError(
                f"cannot read credential {identifier!r} from the OS vault: {exc}",
                hint="unlock your keyring, or use 'env://VAR_NAME' instead",
            ) from exc
        if not secret:
            raise CredentialError(
                f"no credential stored under {identifier!r}",
                hint=f"store it with keyring under service {KEYRING_SERVICE!r}",
            )
        return str(secret)

    def _parse(self, reference: str) -> tuple[str, str]:
        remainder = reference[len(_SCHEME) :]
        backend, sep, identifier = remainder.partition("/")
        if not sep or not identifier:
            raise ConfigError(
                f"malformed credential reference {reference!r}",
                hint="write it as 'credential://system/openai-api-key'",
            )
        if not _IDENTIFIER.match(identifier):
            raise ConfigError(
                f"invalid credential identifier {identifier!r}",
                hint="use lowercase letters, digits, and . _ - / characters",
            )
        return backend, identifier

    @staticmethod
    def _import_keyring() -> Any:
        """Import the optional keyring module, or explain how to install it."""
        try:
            import keyring
        except ImportError as exc:
            raise ConfigError(
                "the 'credential://' scheme requires the keyring extra",
                hint="pip install 'anyinfer[keyring]'",
            ) from exc
        return keyring
