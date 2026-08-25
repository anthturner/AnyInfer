"""Tier 4: model-weight provenance verification.

Tier 3 (`attestation.py`) proves *where* a prompt ran. It says nothing about *what* ran
inside it — whether the model weights are the exact, certified artifact a vendor shipped,
or something swapped or tampered with in place. This module extends the manifest
discipline `local/runtimes.py` already applies to *runtime* builds (`runtime.json` pins
architecture, backend, and build id) to the *model weights* themselves: a content hash and
signature check against a vendor-published manifest.

**This module verifies signatures. It never signs anything, and never handles a private
key.** Each vendor signs their own model manifests with their own keys — AnyInfer never
operates a shared signing service or takes custody of vendor key material, mirroring how
`runtimes.py`'s own manifests are already owned by whoever built the runtime, not by
AnyInfer. A vendor's own tooling (e.g. `cryptography`'s `Ed25519PrivateKey` directly, or
any signing process they already trust) produces the signature; this module only checks it.

**Only a Tier 4 claim when it runs inside Tier 3's attested boundary.** A hash-and-signature
check on an unattested host is a real, valid check, but a *weaker and different* claim —
verifying that the file on disk matches a signature, with no guarantee about who else
could have read or swapped it before or during the check. Marketing that as "Tier 4" would
misrepresent the guarantee DESIGN.md §30.5 defines; the field this
module populates (`ConfidentialExecutionStatus.model_verified`) is documented accordingly
— a caller must additionally check `end_to_end` before treating it as the full claim.

**Requires the `attest` extra** (``pip install anyinfer[attest]``) for the signature
verification dependency (`cryptography`) — never imported at module scope, so importing
`anyinfer.local` never pulls it in for callers who don't use Tier 4 at all.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import ConfidentialExecutionError, ConfigError
from .downloads import _read_and_hash

__all__ = [
    "ModelManifest",
    "VerifiedWeights",
    "WeightsProvenance",
    "hash_model_weights",
    "open_verified_weights",
    "verify_model_manifest",
]

_HASH_CHUNK_BYTES = 1024 * 1024

_ATTEST_EXTRA_HINT = (
    "install the 'attest' extra: pip install anyinfer[attest]"
)


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """A vendor-signed record of what one set of model weights should hash to.

    Attributes:
        model_id: The vendor's identifier for this model variant.
        weight_hash: SHA-256 of the weight file (or, for a multi-file snapshot, of the
            sorted ``relative_path:sha256`` listing — see `hash_model_weights`), as a hex
            string.
        vendor_key_id: Which vendor key this manifest was signed with, for a caller
            managing more than one registered vendor public key.
        signed_at: ISO-8601 signing timestamp, for audit trails.
        signature: The vendor's signature over this manifest's canonical payload.
    """

    model_id: str
    weight_hash: str
    vendor_key_id: str
    signed_at: str
    signature: bytes

    def _payload(self) -> bytes:
        """The exact bytes the signature covers — canonical, so signing and verifying
        never drift from a formatting difference.
        """  # noqa: D205
        payload = {
            "model_id": self.model_id,
            "weight_hash": self.weight_hash,
            "vendor_key_id": self.vendor_key_id,
            "signed_at": self.signed_at,
        }
        return json.dumps(payload, sort_keys=True).encode("utf-8")

    def to_dict(self) -> dict[str, Any]:
        """A JSON-safe mapping — the on-disk manifest format."""
        return {
            "model_id": self.model_id,
            "weight_hash": self.weight_hash,
            "vendor_key_id": self.vendor_key_id,
            "signed_at": self.signed_at,
            "signature": self.signature.hex(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelManifest:
        """Load a manifest previously written by `to_dict`."""
        try:
            return cls(
                model_id=str(data["model_id"]),
                weight_hash=str(data["weight_hash"]),
                vendor_key_id=str(data["vendor_key_id"]),
                signed_at=str(data["signed_at"]),
                signature=bytes.fromhex(data["signature"]),
            )
        except (KeyError, ValueError) as exc:
            raise ConfigError(f"malformed model manifest: {exc}") from exc


def hash_model_weights(path: Path) -> str:
    r"""Hash the weights at `path`, hex-encoded SHA-256.

    A single file (the GGUF case) is hashed directly. A directory (an `hf_repo` snapshot)
    is hashed as the SHA-256 of a sorted ``relative_path:sha256\n`` listing over every
    file it contains — deterministic regardless of filesystem enumeration order, and
    sensitive to every file's content, name, and presence.
    """
    if path.is_file():
        return _hash_file(path)
    if path.is_dir():
        lines = []
        for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
            rel = file_path.relative_to(path).as_posix()
            lines.append(f"{rel}:{_hash_file(file_path)}")
        return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    raise ConfigError(f"model weights not found at {path}")


def _hash_file(path: Path) -> str:
    return _read_and_hash(path, hashlib.sha256)


def verify_model_manifest(
    manifest: ModelManifest, *, weights_path: Path, vendor_public_key: bytes
) -> bool:
    """Verify a manifest's signature and that it matches the weights on disk.

    Args:
        manifest: The vendor-signed manifest to check.
        weights_path: Where the model weights actually are — re-hashed and compared
            against `manifest.weight_hash`; a manifest is never trusted for the hash
            alone, since that would make the signature pointless.
        vendor_public_key: The registered vendor's Ed25519 public key.

    Returns:
        `True` only when the signature verifies against `vendor_public_key` **and** the
        recomputed hash of `weights_path` matches `manifest.weight_hash` exactly.

    Raises:
        anyinfer.errors.ConfigError: The `attest` extra is not installed.

    Note:
        **This is a point-in-time answer, not a load-bound one.** It reports what was on
        disk when it was read, and says nothing about what a loader opens afterwards —
        the gap between the two is however long the caller makes it.

        For anything that is about to load the weights, use `open_verified_weights`, or
        pass a `WeightsProvenance` to `LocalServerSupervisor.acquire`, which verifies
        inside the start path and re-confirms file identity in the instant before the
        process is spawned. This function remains the right call for reporting on weights
        nobody is loading right now — which is exactly what
        `confidential_execution_status` does with it.
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise ConfigError(
            f"model manifest verification needs the 'cryptography' package: {_ATTEST_EXTRA_HINT}"
        ) from exc

    try:
        Ed25519PublicKey.from_public_bytes(vendor_public_key).verify(
            manifest.signature, manifest._payload()
        )
    except InvalidSignature:
        return False

    actual_hash = hash_model_weights(weights_path)
    return actual_hash == manifest.weight_hash


# ---- verification bound to the bytes that get loaded ------------------------------------


@dataclass(frozen=True, slots=True)
class WeightsProvenance:
    """A signed manifest plus the key that checks it, carried to the point of load.

    Exists so a caller can hand the *whole* provenance requirement to whatever starts the
    server, instead of verifying somewhere else and hoping the two agree. Passing this to
    `LocalServerSupervisor.acquire` is what makes verification and load one operation.

    Attributes:
        manifest: The vendor-signed manifest describing the expected weights.
        vendor_public_key: The vendor's Ed25519 public key.
    """

    manifest: ModelManifest
    vendor_public_key: bytes


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    """Which file on which device, as the kernel saw it when we read it."""

    path: Path
    dev: int
    ino: int
    size: int


class VerifiedWeights:
    """Weights that have been verified, with the descriptors still open.

    Holding the descriptors matters for a reason that is easy to miss: inode numbers are
    recycled. If verification only recorded ``(dev, ino)`` and closed the file, an
    attacker could delete it and create a replacement that happens to be assigned the
    same inode number, and an identity check would pass. An open descriptor keeps that
    inode alive, so its number cannot be handed to anything else while this object lives.

    Instances come from `open_verified_weights` and are not constructed directly.
    """

    def __init__(self, digest: str, identities: tuple[_FileIdentity, ...], fds: tuple[int, ...]):
        self._digest = digest
        self._identities = identities
        self._fds = fds

    @property
    def digest(self) -> str:
        """The hex SHA-256 that was verified, read from the open descriptors."""
        return self._digest

    def assert_unchanged(self) -> None:
        """Re-resolve every path and confirm it still names the bytes we verified.

        Call immediately before handing the path to a loader. Catches the whole
        swap-at-the-path class — rename over, delete and recreate, repointed symlink —
        because a replacement is a different inode no matter how identical it looks.

        Raises:
            ConfidentialExecutionError: A path now resolves somewhere else, or has gone
                missing. Fails closed: the caller must not load.
        """
        for identity in self._identities:
            try:
                current = identity.path.stat()
            except OSError as exc:
                raise ConfidentialExecutionError(
                    f"verified weights are no longer readable at {identity.path}: {exc}",
                    hint="the file changed between verification and load; do not load it",
                ) from exc
            if (current.st_dev, current.st_ino) != (identity.dev, identity.ino):
                raise ConfidentialExecutionError(
                    f"{identity.path} was replaced after verification "
                    "(it now resolves to a different file)",
                    hint=(
                        "something with write access to the model directory swapped the "
                        "file; treat the host as untrusted rather than retrying"
                    ),
                )
            if current.st_size != identity.size:
                raise ConfidentialExecutionError(
                    f"{identity.path} changed size after verification "
                    f"({identity.size} -> {current.st_size} bytes)",
                    hint="the file was written to after it was verified; do not load it",
                )

    def close(self) -> None:
        """Release the descriptors. The identity guarantee ends here."""
        for fd in self._fds:
            with contextlib.suppress(OSError):  # already closed, or never valid
                os.close(fd)


def _hash_fd(fd: int) -> str:
    """SHA-256 of a descriptor's full contents, read from offset zero.

    Reads through the descriptor rather than reopening the path, so the bytes hashed are
    the bytes of *this* file and not of whatever the path happens to name by then.
    """
    digest = hashlib.sha256()
    offset = 0
    while True:
        block = _read_at(fd, _HASH_CHUNK_BYTES, offset)
        if not block:
            break
        offset += len(block)
        digest.update(block)
    return digest.hexdigest()


def _read_at(fd: int, size: int, offset: int) -> bytes:
    """Read from a descriptor at an absolute offset, leaving its file position alone.

    `os.pread` is POSIX-only; Windows has no equivalent, so there the offset is set and
    restored around a plain `os.read`. What must survive that substitution is the property
    the caller depends on: the bytes come from *this descriptor*, never from reopening a
    path that may name a different file by now. Seeking does not weaken it — the
    descriptor is still the only handle involved.

    The file position is restored because the caller holds these descriptors open past
    verification and hands them to the loader; leaving the offset at EOF would silently
    give the loader an empty file.

    Note:
        Unlike `pread`, the fallback is not atomic against another thread reading the same
        descriptor concurrently. Nothing here shares a descriptor across threads —
        verification runs to completion before the fd is handed on — so the two behave
        identically in this use.
    """
    if hasattr(os, "pread"):
        return os.pread(fd, size, offset)
    saved = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        os.lseek(fd, offset, os.SEEK_SET)
        return os.read(fd, size)
    finally:
        os.lseek(fd, saved, os.SEEK_SET)


def _weight_files(weights_path: Path) -> list[Path]:
    """Every file the digest covers, in the order `hash_model_weights` uses."""
    if weights_path.is_file():
        return [weights_path]
    if weights_path.is_dir():
        return sorted(p for p in weights_path.rglob("*") if p.is_file())
    raise ConfigError(f"model weights not found at {weights_path}")


@contextlib.contextmanager
def open_verified_weights(
    provenance: WeightsProvenance, weights_path: Path
) -> Iterator[VerifiedWeights]:
    """Verify weights and keep them pinned for the length of the block.

    The difference from `verify_model_manifest` is *when* and *from what*. This opens
    every file first and hashes through those descriptors, so the digest describes the
    bytes of specific inodes rather than of whatever the path named at the time. The
    descriptors stay open for the block, and `VerifiedWeights.assert_unchanged` re-checks
    the paths still resolve to them — so a caller can verify, do its remaining setup, and
    re-confirm identity in the instant before it starts a loader.

    Args:
        provenance: The manifest and the key to check it with.
        weights_path: A GGUF file, or a snapshot directory.

    Yields:
        A `VerifiedWeights` whose descriptors are open for the duration.

    Raises:
        ConfidentialExecutionError: The signature does not verify, or the weights do not
            match the manifest. Fails closed — nothing should be loaded.
        anyinfer.errors.ConfigError: The `attest` extra is missing, or the path is absent.

    Note:
        This closes the swap-at-the-path window, not every window. `llama-server` opens
        the path itself, so the microseconds between `assert_unchanged` and that open are
        not covered, and because llama.cpp maps weights lazily, a writer with access to
        the *same inode* can still alter pages that have not been faulted in yet. Both
        residuals need the bytes to be immutable during load — a read-only mount, or a
        directory only root can write — which is a property of the deployment, not of
        this function. See `verify_model_manifest` for the wider note.
    """
    files = _weight_files(weights_path)
    fds: list[int] = []
    identities: list[_FileIdentity] = []
    try:
        for file_path in files:
            fd = os.open(file_path, os.O_RDONLY)
            fds.append(fd)
            stat = os.fstat(fd)
            identities.append(
                _FileIdentity(
                    path=file_path, dev=stat.st_dev, ino=stat.st_ino, size=stat.st_size
                )
            )

        # Byte-for-byte the digest `hash_model_weights` produces, so manifests signed
        # before this path existed keep verifying.
        if weights_path.is_file():
            digest = _hash_fd(fds[0])
        else:
            lines = [
                f"{path.relative_to(weights_path).as_posix()}:{_hash_fd(fd)}"
                for path, fd in zip(files, fds, strict=True)
            ]
            digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()

        if not _signature_ok(provenance.manifest, provenance.vendor_public_key):
            raise ConfidentialExecutionError(
                f"model manifest for {provenance.manifest.model_id!r} is not signed by "
                "the expected vendor key",
                hint="check the manifest came from the vendor whose key you registered",
            )
        if digest != provenance.manifest.weight_hash:
            raise ConfidentialExecutionError(
                f"weights at {weights_path} do not match the signed manifest "
                f"(expected {provenance.manifest.weight_hash[:16]}…, got {digest[:16]}…)",
                hint="the weights are not the artifact the vendor signed; do not load them",
            )

        verified = VerifiedWeights(digest, tuple(identities), tuple(fds))
        fds = []  # ownership passes to `verified`
        try:
            yield verified
        finally:
            verified.close()
    finally:
        for fd in fds:
            with contextlib.suppress(OSError):  # pragma: no cover
                os.close(fd)


def _signature_ok(manifest: ModelManifest, vendor_public_key: bytes) -> bool:
    """Whether the manifest's signature verifies against the vendor key."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise ConfigError(
            f"model manifest verification needs the 'cryptography' package: {_ATTEST_EXTRA_HINT}"
        ) from exc
    try:
        Ed25519PublicKey.from_public_bytes(vendor_public_key).verify(
            manifest.signature, manifest._payload()
        )
    except InvalidSignature:
        return False
    return True
