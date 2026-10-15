"""Writing a file only its owner can read — and being honest where that is not possible.

POSIX expresses "owner only" as mode 0600, and `Path.chmod` sets it. Windows has no
equivalent through that call: `chmod` there toggles a read-only attribute and leaves the
file's ACL untouched, so a file "protected" this way stays readable by every other local
account. Nothing raises, and `stat().st_mode` reports 0o666 afterwards.

That gap is easy to paper over and expensive to get wrong, so this module keeps the two
halves separate: `restrict_to_owner` does what the platform can actually do and *reports*
whether the restriction is real, and callers holding genuine secrets decide what to say
when it is not. `anyinfer.serve.service` already set that precedent for the sidecar's
bearer token — it declines to write a token file on Windows at all, on the grounds that a
weakly-protected secret which looks protected is worse than telling the operator to put
the value where the OS already guards it.

No Windows ACL manipulation is attempted here. Doing it properly means `icacls` or the
Win32 security APIs, and shipping security-critical code that no maintainer can exercise
would trade a known gap for an unverified one.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["OWNER_ONLY_IS_ENFORCED", "owner_only_warning", "restrict_to_owner"]

OWNER_ONLY_IS_ENFORCED = os.name != "nt"
"""Whether `restrict_to_owner` can actually restrict a file on this platform."""

_WINDOWS_HINT = (
    "Windows does not honour POSIX file modes; store the file on a volume or in a "
    "user-profile directory whose ACL already excludes other accounts, or keep the "
    "value in the OS environment instead"
)


def restrict_to_owner(path: str | Path) -> bool:
    """Restrict `path` to its owner where the platform supports it.

    Args:
        path: An existing file.

    Returns:
        ``True`` when the restriction was applied and is meaningful, ``False`` on a
        platform that cannot express it. A `False` return is not an error — it is the
        answer to "is this file actually protected?", which the caller must not assume.
    """
    if not OWNER_ONLY_IS_ENFORCED:
        return False
    Path(path).chmod(0o600)
    return True


def owner_only_warning(path: str | Path, *, what: str) -> str:
    """The sentence to show when `restrict_to_owner` could not protect secret material."""
    return f"{what} was written to {path} without owner-only permissions: {_WINDOWS_HINT}"
