"""The Hugging Face resolver: two JSON endpoints and one download URL shape.

AnyInfer speaks the Hugging Face HTTP API directly rather than depending on
``huggingface_hub``. That is the direct cost of the slim-core rule, and it is bounded
deliberately: two endpoints, one URL template, no cache-layout emulation, no upload, no
inference API. If that scope ever grows, the decision to skip the official client deserves
re-litigating explicitly rather than by accretion.

What is spoken here is recorded in ``contracts/huggingface.md`` and audited by the provider
drift check, because it is a third-party protocol we now depend on — the same discipline
every inference provider gets.

Two things this module is careful about, both of which are security properties rather than
conveniences:

- **A branch is always resolved to an immutable commit before anything is downloaded**, so
  a repository that moves under us is a detectable event rather than a silent swap.
- **The bearer token is dropped on any cross-origin redirect.** ``resolve`` URLs redirect to
  a CDN, and forwarding a token to whatever host a redirect names is a credential leak, so
  redirects are followed by hand rather than by ``follow_redirects=True``.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

import httpx2

from ...credentials import default_resolver
from ...errors import LocalRuntimeError
from ...redaction import register_secret
from . import (
    DigestKind,
    RemoteFile,
    ResolvedArtifact,
    SourceRef,
    register_resolver,
    safe_relative_path,
)

__all__ = [
    "DEFAULT_EXCLUDE",
    "DEFAULT_SNAPSHOT_INCLUDE",
    "HF_ENDPOINT",
    "PICKLE_PATTERNS",
    "HuggingFaceResolver",
    "download_url",
    "resolve_token",
    "trusted_redirect",
]

HF_ENDPOINT = "https://huggingface.co"
"""The API root. Overridable with ``HF_ENDPOINT`` for an enterprise deployment."""

_TOKEN_ENV = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")
_MAX_REDIRECTS = 5

DEFAULT_SNAPSHOT_INCLUDE: tuple[str, ...] = (
    "*.safetensors",
    "*.safetensors.index.json",
    "config.json",
    "generation_config.json",
    "tokenizer*",
    "*.model",
    "preprocessor_config.json",
    "chat_template.*",
    "special_tokens_map.json",
)
"""What a vLLM-shaped repository snapshot needs, and nothing more."""

PICKLE_PATTERNS: tuple[str, ...] = ("*.bin", "*.pt", "*.pth", "*.ckpt")
"""Weight formats that execute arbitrary code on load. Never fetched by default."""

DEFAULT_EXCLUDE: tuple[str, ...] = (
    *PICKLE_PATTERNS,
    "*.msgpack",
    "*.h5",
    "*.onnx",
    "*.gguf",
    "original/*",
    "original/**",
)
"""Excluded from snapshots: unsafe formats, other frameworks, and the other channel's files.

``*.gguf`` is here because a GGUF inside a repository snapshot belongs to the llama.cpp
channel, which fetches named shard sets rather than whole directories.
"""


def resolve_token(explicit: str | None = None) -> str | None:
    """Resolve a Hugging Face token and register it for redaction.

    An explicit value first — resolved through the credential chain, so
    ``"env://HF_TOKEN"`` works the same way it does for every provider key — then the
    ``HF_TOKEN`` and ``HUGGING_FACE_HUB_TOKEN`` environment variables. Whatever is found is
    registered as a secret, so it can never appear in an error, an event, an index entry,
    or a log line.
    """
    value: str | None = None
    if explicit:
        value = default_resolver().resolve(explicit)
    else:
        for name in _TOKEN_ENV:
            candidate = os.environ.get(name)
            if candidate:
                value = candidate
                break
    if value:
        register_secret(value)
    return value


def download_url(repo: str, revision: str, path: str, *, endpoint: str | None = None) -> str:
    """The URL that serves one file's bytes at a pinned revision."""
    root = (endpoint or os.environ.get("HF_ENDPOINT") or HF_ENDPOINT).rstrip("/")
    return f"{root}/{repo}/resolve/{revision}/{path}"


def trusted_redirect(origin: str, destination: str) -> bool:
    """Whether the ``Authorization`` header may survive a redirect from one URL to another.

    Only a same-origin hop keeps it. Hugging Face redirects file downloads to a CDN on a
    different host, and that host has no business receiving a user's token.
    """
    source = urlsplit(origin)
    target = urlsplit(destination)
    return (source.scheme, source.hostname, source.port) == (
        target.scheme,
        target.hostname,
        target.port,
    )


class HuggingFaceResolver:
    """Expands a repository reference into a concrete, digest-carrying file list."""

    scheme = "huggingface"

    def __init__(
        self,
        *,
        client: httpx2.AsyncClient | None = None,
        endpoint: str | None = None,
    ) -> None:
        self._client = client
        self._endpoint = (endpoint or os.environ.get("HF_ENDPOINT") or HF_ENDPOINT).rstrip("/")

    async def resolve(
        self,
        ref: SourceRef,
        *,
        token: str | None = None,
        client: httpx2.AsyncClient | None = None,
    ) -> ResolvedArtifact:
        """Resolve a repository reference at an immutable commit.

        Args:
            ref: The reference, naming a repo and optionally a revision and file list.
            token: A Hugging Face token for gated or private repositories.
            client: An ``httpx2.AsyncClient`` to reuse.

        Returns:
            Every selected file with its URL, size, and digest.

        Raises:
            LocalRuntimeError: If the repository is missing, gated, or unreadable, or if a
                named file does not exist at the resolved commit.
        """
        if not ref.repo:
            raise LocalRuntimeError(
                "a Hugging Face source reference needs a 'repo'",
                hint="write it as 'publisher/name'",
            )

        http = client or self._client
        owns_client = http is None
        if http is None:
            http = httpx2.AsyncClient(timeout=httpx2.Timeout(60.0))
        try:
            revision = await self._resolve_revision(http, ref, token)
            tree = await self._fetch_tree(http, ref.repo, revision, token)
        finally:
            if owns_client:
                await http.aclose()

        files, warnings = self._select(ref, revision, tree)
        return ResolvedArtifact(
            resolver=self.scheme,
            files=files,
            repo=ref.repo,
            revision=revision,
            warnings=warnings,
        )

    # ---- endpoints -------------------------------------------------------------------

    async def _resolve_revision(
        self, client: httpx2.AsyncClient, ref: SourceRef, token: str | None
    ) -> str:
        """Turn a branch, tag, or commit into a commit sha."""
        repo = ref.repo or ""
        revision = ref.revision or "main"
        if _looks_like_commit(revision):
            return revision
        url = f"{self._endpoint}/api/models/{repo}/revision/{revision}"
        payload = await self._get_json(client, url, token, repo=repo)
        sha = payload.get("sha") if isinstance(payload, Mapping) else None
        if not isinstance(sha, str) or not _looks_like_commit(sha):
            raise LocalRuntimeError(
                f"Hugging Face did not report a commit for {repo}@{revision}",
                hint="check the repository and revision names",
            )
        return sha

    async def _fetch_tree(
        self, client: httpx2.AsyncClient, repo: str, revision: str, token: str | None
    ) -> list[Mapping[str, Any]]:
        """List every file at a commit, following the API's pagination."""
        entries: list[Mapping[str, Any]] = []
        cursor: str | None = f"{self._endpoint}/api/models/{repo}/tree/{revision}?recursive=1"
        seen = 0
        while cursor and seen < 100:
            response = await self._request(client, "GET", cursor, token, repo=repo)
            payload = response.json()
            if not isinstance(payload, list):
                break
            entries.extend(e for e in payload if isinstance(e, Mapping))
            cursor = _next_link(response.headers.get("link", ""))
            seen += 1
        if not entries:
            raise LocalRuntimeError(
                f"Hugging Face listed no files for {repo}@{revision[:12]}",
                hint="the repository may be empty, or the revision may not exist",
            )
        return entries

    # ---- selection --------------------------------------------------------------------

    def _select(
        self, ref: SourceRef, revision: str, tree: Sequence[Mapping[str, Any]]
    ) -> tuple[tuple[RemoteFile, ...], tuple[str, ...]]:
        """Choose the files this reference names, safely."""
        assert ref.repo is not None
        by_path = {str(e.get("path", "")): e for e in tree if e.get("type") == "file"}
        warnings: list[str] = []

        if ref.files:
            selected = []
            for name in ref.files:
                entry = by_path.get(name)
                if entry is None:
                    raise LocalRuntimeError(
                        f"{name!r} is not present in {ref.repo}@{revision[:12]}",
                        hint=(
                            "the catalog may be stale; re-run scripts/pin_catalog.py or "
                            "check the repository"
                        ),
                    )
                selected.append(entry)
        else:
            include = ref.include or DEFAULT_SNAPSHOT_INCLUDE
            exclude = ref.exclude or DEFAULT_EXCLUDE
            selected = []
            for path, entry in sorted(by_path.items()):
                name = path.rsplit("/", 1)[-1]
                if not any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(path, p) for p in include):
                    continue
                if any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(path, p) for p in exclude):
                    continue
                selected.append(entry)

            # Scanned across the whole listing rather than only the included files: a
            # pickle weight never matches the include list in the first place, and the
            # point of the warning is to say we *saw* one and chose not to fetch it.
            skipped_pickles = any(
                fnmatch.fnmatch(path.rsplit("/", 1)[-1], pattern)
                for path in by_path
                for pattern in PICKLE_PATTERNS
            )
            if skipped_pickles:
                warnings.append(
                    "pickle-format weights were excluded; loading them executes arbitrary "
                    "code, and safetensors carry the same weights"
                )
            if not selected:
                raise LocalRuntimeError(
                    f"{ref.repo}@{revision[:12]} has no safetensors weights to fetch",
                    hint=(
                        "this repository may publish only pickle weights; set "
                        "allow_pickle_weights=True only if you trust its publisher"
                    ),
                )

        files: list[RemoteFile] = []
        for entry in selected:
            path = safe_relative_path(str(entry.get("path", "")))
            digest, kind = _digest_of(entry)
            if kind == "none":
                warnings.append(f"{path} carries no digest and cannot be verified")
            files.append(
                RemoteFile(
                    path=path,
                    url=download_url(ref.repo, revision, path, endpoint=self._endpoint),
                    size_bytes=_size_of(entry),
                    digest=digest,
                    digest_kind=kind,
                )
            )
        return tuple(files), tuple(warnings)

    # ---- HTTP -----------------------------------------------------------------------

    async def _get_json(
        self, client: httpx2.AsyncClient, url: str, token: str | None, *, repo: str
    ) -> Mapping[str, Any]:
        response = await self._request(client, "GET", url, token, repo=repo)
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise LocalRuntimeError(
                f"Hugging Face returned an unexpected response for {repo}",
                hint="the API may have changed; see contracts/huggingface.md",
            )
        return payload

    async def _request(
        self,
        client: httpx2.AsyncClient,
        method: str,
        url: str,
        token: str | None,
        *,
        repo: str,
    ) -> httpx2.Response:
        """Issue a request, following redirects by hand so the token cannot leak."""
        current = url
        for _ in range(_MAX_REDIRECTS):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            try:
                response = await client.request(
                    method, current, headers=headers, follow_redirects=False
                )
            except httpx2.HTTPError as exc:
                raise LocalRuntimeError(
                    f"could not reach Hugging Face for {repo}: {exc}",
                    hint="check your network connection and retry",
                ) from exc

            if response.is_redirect:
                destination = str(response.headers.get("location", ""))
                if not destination:
                    break
                destination = str(response.url.join(destination))
                if not trusted_redirect(current, destination):
                    # The token stops here: the next hop is a different origin.
                    token = None
                current = destination
                continue

            if response.status_code in (401, 403):
                raise _gated_error(repo, response.status_code, bool(token))
            if response.status_code == 404:
                raise LocalRuntimeError(
                    f"Hugging Face has no repository or revision matching {repo}",
                    hint=(
                        f"check the id at {HF_ENDPOINT}/{repo}; if it was renamed, the "
                        "catalog entry needs re-pinning"
                    ),
                )
            if response.status_code >= 400:
                raise LocalRuntimeError(
                    f"Hugging Face returned HTTP {response.status_code} for {repo}",
                    hint="retry; if it persists, the API contract may have drifted",
                )
            return response

        raise LocalRuntimeError(
            f"too many redirects fetching {repo} from Hugging Face",
            hint="retry later; the CDN may be misconfigured",
        )


def _gated_error(repo: str, status: int, had_token: bool) -> LocalRuntimeError:
    """Map an authorization failure to advice that names the actual remedy."""
    if had_token:
        hint = (
            f"accept this model's terms at {HF_ENDPOINT}/{repo} with the account that owns "
            "your token, then retry"
        )
    else:
        hint = (
            f"this is a gated repository: accept its terms at {HF_ENDPOINT}/{repo}, then set "
            "HF_TOKEN to a token from that account"
        )
    return LocalRuntimeError(
        f"Hugging Face refused access to {repo} (HTTP {status})",
        hint=hint,
        http_status=status,
    )


def _digest_of(entry: Mapping[str, Any]) -> tuple[str, DigestKind]:
    """Extract a file's digest and how to compute it.

    LFS objects carry a sha256 in ``lfs.oid``; small files carry a git blob sha1 in ``oid``.
    Both are trust-on-first-use — we trust the API for *what the bytes should be*, then
    verify the bytes against it — which is a real improvement over trusting the transfer.
    """
    lfs = entry.get("lfs")
    if isinstance(lfs, Mapping):
        oid = lfs.get("oid")
        if isinstance(oid, str) and len(oid) == 64:
            return oid.lower(), "sha256"
    oid = entry.get("oid")
    if isinstance(oid, str) and len(oid) == 40:
        return oid.lower(), "git-sha1"
    return "", "none"


def _size_of(entry: Mapping[str, Any]) -> int | None:
    """A file's size, preferring the LFS-reported one."""
    lfs = entry.get("lfs")
    if isinstance(lfs, Mapping) and isinstance(lfs.get("size"), int):
        return int(lfs["size"])
    size = entry.get("size")
    return int(size) if isinstance(size, int) else None


def _looks_like_commit(revision: str) -> bool:
    """Whether a revision string is already a full commit sha."""
    return len(revision) == 40 and all(c in "0123456789abcdef" for c in revision.lower())


def _next_link(header: str) -> str | None:
    """Extract a ``rel="next"`` URL from a Link header."""
    for part in header.split(","):
        section, _, rel = part.partition(";")
        if 'rel="next"' in rel and "<" in section:
            return section.strip().strip("<>")
    return None


register_resolver(HuggingFaceResolver())
