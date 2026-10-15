"""The direct-URL resolver: fetch exactly what the caller named.

The escape hatch for weights that live outside any registry — an internal artifact server,
a release asset, a signed link. There is no listing API to consult, so sizes come from a
``HEAD`` and digests come from the caller or not at all.

"Or not at all" is the interesting case, and it is refused by default: an unverifiable
download is a file we cannot distinguish from a truncated or substituted one. A caller who
genuinely has no digest opts in explicitly, and the resulting store entry is marked
unverified so `ModelStore.locate` can keep saying so.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

import httpx2

from ...errors import LocalRuntimeError
from . import RemoteFile, ResolvedArtifact, SourceRef, register_resolver, safe_relative_path

__all__ = ["DirectUrlResolver", "filename_from_url"]


def filename_from_url(url: str) -> str:
    """Derive a destination file name from a URL path.

    Query strings and percent-encoding are stripped, then the name goes through the same
    containment rule every remote-supplied name does — a URL is no more trustworthy than a
    repository listing.
    """
    path = urlsplit(url).path
    name = unquote(path.rsplit("/", 1)[-1]).strip()
    if not name:
        raise LocalRuntimeError(
            f"could not derive a file name from {url!r}",
            hint="supply filenames explicitly with SourceRef(files=(...))",
        )
    return safe_relative_path(name)


class DirectUrlResolver:
    """Resolves caller-supplied URLs, sizing them with a ``HEAD`` request."""

    scheme = "url"

    def __init__(
        self, *, client: httpx2.AsyncClient | None = None, allow_unverified: bool = False
    ) -> None:
        self._client = client
        self._allow_unverified = allow_unverified

    async def resolve(
        self,
        ref: SourceRef,
        *,
        token: str | None = None,
        client: httpx2.AsyncClient | None = None,
    ) -> ResolvedArtifact:
        """Turn a URL list into a file list.

        Args:
            ref: The reference; ``urls`` is required, ``files`` optionally renames them,
                and ``digests`` optionally pins them by destination name.
            token: Sent as a bearer token when supplied. Unlike the Hugging Face resolver
                this does not follow redirects itself, so a caller pointing a token at a
                redirecting URL should point it at the final one instead.
            client: An ``httpx2.AsyncClient`` to reuse.

        Returns:
            The resolved file list.

        Raises:
            LocalRuntimeError: If no URLs were given, if the name list length disagrees, or
                if a file has no digest and unverified downloads were not allowed.
        """
        if not ref.urls:
            raise LocalRuntimeError(
                "a direct-URL source reference needs at least one url",
                hint="pass SourceRef(resolver='url', urls=(...))",
            )
        if ref.files and len(ref.files) != len(ref.urls):
            raise LocalRuntimeError(
                "the direct-URL reference lists a different number of names and urls",
                hint="supply one name per url, or none at all",
            )

        names = (
            [safe_relative_path(name) for name in ref.files]
            if ref.files
            else [filename_from_url(url) for url in ref.urls]
        )

        http = client or self._client
        owns_client = http is None
        if http is None:
            http = httpx2.AsyncClient(timeout=httpx2.Timeout(60.0))
        files: list[RemoteFile] = []
        warnings: list[str] = []
        try:
            for name, url in zip(names, ref.urls, strict=True):
                digest = ref.digests.get(name) or ref.digests.get(url) or ""
                if not digest and not self._allow_unverified:
                    raise LocalRuntimeError(
                        f"{name} has no expected sha256, so the download cannot be verified",
                        hint=(
                            "pin a digest in the source reference, or pass "
                            "allow_unverified=True to accept an unverifiable file"
                        ),
                    )
                if not digest:
                    warnings.append(f"{name} will be stored without verification")
                files.append(
                    RemoteFile(
                        path=name,
                        url=url,
                        size_bytes=ref.sizes.get(name) or await self._head_size(http, url, token),
                        digest=digest.lower(),
                        digest_kind="sha256" if digest else "none",
                    )
                )
        finally:
            if owns_client:
                await http.aclose()

        return ResolvedArtifact(
            resolver=self.scheme,
            files=tuple(files),
            revision=ref.revision,
            warnings=tuple(warnings),
        )

    async def _head_size(
        self, client: httpx2.AsyncClient, url: str, token: str | None
    ) -> int | None:
        """Ask for a size, tolerating a server that will not say.

        An unknown size is reported as unknown rather than guessed: it makes progress
        percentages honest about being estimates, which is the whole point of tracking it.
        """
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            response = await client.request("HEAD", url, headers=headers, follow_redirects=True)
        except httpx2.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        length = response.headers.get("content-length")
        return int(length) if length and length.isdigit() else None


register_resolver(DirectUrlResolver())
