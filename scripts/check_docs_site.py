"""Validate the exported static documentation artifact before publication."""

from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

try:  # Package import for tests and build scripts run from the repository root.
    from .export_docs import SECTION_MAX_BYTES, Article, page_file
except ImportError:  # Direct ``python scripts/check_docs_site.py`` execution.
    from export_docs import SECTION_MAX_BYTES, Article, page_file


ROOT = Path(__file__).resolve().parents[1]
_EXTERNAL_SCHEMES = frozenset({"data", "javascript", "mailto", "tel"})
_API_MARKER = re.compile(
    r"^\s*:::\s+(?:anyinfer|anyinfer_store|anyinfer_shared|anyinfer_confidential)\b", re.MULTILINE
)
_SNIPPET_MARKER = re.compile(r"^\s*--8<--", re.MULTILINE)
_ADR = re.compile(r"\bADR-\d{3}\b")
_WORKSTATION_PATH = re.compile(r"(?:[A-Za-z]:[\\/](?:Users|home)[\\/]|/(?:Users|home)/[^/]+/)")


class _Links(HTMLParser):
    """Collect local link-like attributes from an HTML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record links and assets that static hosting must resolve."""
        for name, value in attrs:
            if name in {"href", "src"} and value:
                self.values.append(value)


def validate_site(
    site: Path,
    *,
    baseline: Path | None = None,
    require_pagefind: bool = True,
) -> None:
    """Validate a built and exported site directory.

    Args:
        site: Root of the static output.
        baseline: Optional legacy route/anchor inventory.  Omit for deliberately small
            test fixtures; production callers use the committed baseline by default.
        require_pagefind: Require the local Pagefind JavaScript and WebAssembly bundle.

    Raises:
        ValueError: If a published route, link, fragment, export, or safety invariant fails.
    """
    site = site.resolve()
    manifest_path = site / "docs-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("site has no docs-manifest.json; run the export step first")
    manifest = _read_json(manifest_path, "docs manifest")
    pages = manifest.get("pages")
    versions = manifest.get("versions")
    if not isinstance(pages, list) or not pages:
        raise ValueError("docs manifest has no pages")
    if not isinstance(versions, dict) or not all(
        isinstance(versions.get(name), str) for name in ("python", "csharp")
    ):
        raise ValueError("docs manifest must carry Python and C# versions")

    routes: dict[str, dict] = {}
    articles: dict[str, Article] = {}
    documents: dict[str, str] = {}
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("url"), str):
            raise ValueError("docs manifest has a page without a URL")
        url = page["url"]
        if url in routes:
            raise ValueError(f"docs manifest has duplicate canonical route {url}")
        routes[url] = page
        path = page_file(site, url)
        if not path.is_file():
            raise ValueError(f"canonical page is missing: {url}")
        html = path.read_text(encoding="utf-8")
        _reject_source_markers(url, html)
        article = Article()
        article.feed(html)
        if not article.text():
            raise ValueError(f"canonical page has no article body: {url}")
        _reject_public_text(url, article.text())
        articles[url] = article
        documents[url] = html

    for url, html in documents.items():
        _validate_links(site, url, html, articles)

    home = page_file(site, "/")
    if not home.is_file():
        raise ValueError("homepage is missing")
    home_article = Article()
    home_article.feed(home.read_text(encoding="utf-8"))
    if not home_article.text():
        raise ValueError("homepage has no article body")

    redirects = manifest.get("redirects", {})
    if not isinstance(redirects, dict):
        raise ValueError("docs manifest redirects must be an object")
    _validate_redirects(site, routes, articles, redirects)
    _validate_exports(site, versions)
    cname = site / "CNAME"
    if not cname.is_file() or cname.read_text(encoding="utf-8").strip() != "anyinfer.dev":
        raise ValueError("site CNAME must contain anyinfer.dev")
    if require_pagefind:
        _validate_pagefind(site)

    if baseline is not None:
        _validate_legacy(site, baseline, routes, articles, redirects)


def _read_json(path: Path, label: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a JSON object")
    return data


def _reject_source_markers(url: str, html: str) -> None:
    if _API_MARKER.search(html):
        raise ValueError(f"unexpanded API marker in {url}")
    if _SNIPPET_MARKER.search(html):
        raise ValueError(f"unexpanded snippet marker in {url}")


def _reject_public_text(url: str, text: str) -> None:
    if _ADR.search(text):
        raise ValueError(f"internal decision identifier in public article: {url}")
    # This authored service example deliberately uses a generic home placeholder.
    path_text = text.replace("/home/you/", "/example-home/")
    checkout_paths = (str(ROOT), ROOT.as_posix())
    if _WORKSTATION_PATH.search(path_text) or any(path in text for path in checkout_paths):
        raise ValueError(f"workstation path in public article: {url}")


def _validate_links(site: Path, page_url: str, html: str, articles: dict[str, Article]) -> None:
    links = _Links()
    links.feed(html)
    for value in links.values:
        parsed = urlsplit(value)
        if parsed.scheme in _EXTERNAL_SCHEMES or (
            parsed.scheme and parsed.netloc != "anyinfer.dev"
        ):
            continue
        if parsed.netloc and parsed.netloc != "anyinfer.dev":
            continue
        target = urlsplit(urljoin(f"https://anyinfer.dev{page_url}", value))
        path = unquote(target.path)
        if ".." in Path(path).parts:
            raise ValueError(f"unsafe local link in {page_url}: {value}")
        destination = _local_destination(site, path)
        if not destination.is_file():
            raise ValueError(f"missing local target in {page_url}: {value}")
        if target.fragment:
            route = path if path.endswith("/") else f"{path}/"
            article = articles.get(route)
            if article is None:
                article = Article()
                article.feed(destination.read_text(encoding="utf-8"))
            if unquote(target.fragment) not in article.anchors:
                raise ValueError(f"missing fragment in {page_url}: {value}")


def _local_destination(site: Path, path: str) -> Path:
    relative = path.lstrip("/")
    if Path(relative).suffix:
        return site / relative
    return page_file(site, path or "/")


def _validate_redirects(
    site: Path, routes: dict[str, dict], articles: dict[str, Article], redirects: dict,
) -> None:
    canonical = set(routes)
    for source, target in redirects.items():
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError("docs manifest redirects must map strings to strings")
        if source in canonical:
            raise ValueError(f"redirect collides with canonical route: {source}")
        if not page_file(site, source).is_file():
            raise ValueError(f"redirect page is missing: {source}")
        _resolve_redirect(source, redirects, canonical)
        target_parts = urlsplit(target)
        if target_parts.path not in canonical:
            raise ValueError(f"redirect has no canonical target: {source} -> {target}")
        if target_parts.fragment:
            target_article = articles[target_parts.path]
            if unquote(target_parts.fragment) not in target_article.anchors:
                raise ValueError(f"redirect fragment is missing: {source} -> {target}")


def _resolve_redirect(source: str, redirects: dict, canonical: set[str]) -> str:
    seen: set[str] = set()
    current = source
    while current not in canonical:
        if current in seen:
            raise ValueError(f"redirect cycle at {source}")
        seen.add(current)
        target = redirects.get(current)
        if not isinstance(target, str):
            raise ValueError(f"redirect has no canonical target: {source}")
        current = urlsplit(target).path
    return current


def _validate_exports(site: Path, versions: dict) -> None:
    expected = f"Python {versions['python']}; C# {versions['csharp']} (prerelease)."
    outputs = [site / "llms.txt", site / "llms-full.txt", *(site / "llms").glob("*.txt")]
    if not (site / "llms").is_dir() or len(outputs) < 3:
        raise ValueError("site has no section llms exports")
    for path in outputs:
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            raise ValueError(f"empty documentation export: {path.relative_to(site)}")
        text = path.read_text(encoding="utf-8")
        if expected not in text:
            raise ValueError(
                f"documentation export has no version receipt: {path.relative_to(site)}"
            )
        if path.parent.name == "llms" and len(text.encode("utf-8")) > SECTION_MAX_BYTES:
            raise ValueError(
                f"documentation export exceeds section budget: {path.relative_to(site)}"
            )
        _reject_public_text(path.relative_to(site).as_posix(), text)


def _validate_pagefind(site: Path) -> None:
    bundle = site / "pagefind"
    if (
        not bundle.is_dir()
        or not list(bundle.glob("pagefind*.js"))
        or not list(bundle.glob("wasm.*.pagefind"))
        or not (bundle / "pagefind-entry.json").is_file()
        or not (bundle / "pagefind-worker.js").is_file()
    ):
        raise ValueError("site has no complete local Pagefind bundle")


def _validate_legacy(
    site: Path,
    baseline: Path,
    routes: dict[str, dict],
    articles: dict[str, Article],
    redirects: dict,
) -> None:
    legacy = _read_json(baseline, "legacy baseline")
    pages = legacy.get("pages")
    if not isinstance(pages, list):
        raise ValueError("legacy baseline has no pages")
    anchor_map = legacy.get("anchor_redirects", {})
    if not isinstance(anchor_map, dict):
        raise ValueError("legacy baseline anchor_redirects must be an object")
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("file"), str):
            raise ValueError("legacy baseline has an invalid page")
        if page["file"] == "404.html":
            if not (site / "404.html").is_file():
                raise ValueError("static 404 page is missing")
            continue
        route = _legacy_route(page["file"])
        target = route if route in routes else redirects.get(route)
        if not isinstance(target, str):
            raise ValueError(f"legacy route no longer resolves: {route}")
        target_path = urlsplit(target).path
        if target_path not in routes:
            raise ValueError(f"legacy route has no canonical destination: {route}")
        for anchor in page.get("anchors", []):
            if not isinstance(anchor, str):
                raise ValueError(f"legacy anchor is invalid: {route}")
            mapped = anchor_map.get(f"{route}#{anchor}", f"{target_path}#{anchor}")
            mapped_parts = urlsplit(str(mapped))
            if (
                mapped_parts.path not in routes
                or not mapped_parts.fragment
                or unquote(mapped_parts.fragment) not in articles[mapped_parts.path].anchors
            ):
                raise ValueError(f"legacy anchor no longer resolves: {route}#{anchor}")


def _legacy_route(file: str) -> str:
    if file == "index.html":
        return "/"
    if not file.endswith("/index.html"):
        return f"/{file}"
    return f"/{file[: -len('index.html')]}"


def main() -> int:
    """Run the static artifact validation command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=Path("site"))
    parser.add_argument(
        "--baseline",
        type=Path,
        default=ROOT / "tests/fixtures/docs_migration/legacy.json",
    )
    parser.add_argument("--allow-no-pagefind", action="store_true")
    args = parser.parse_args()
    try:
        validate_site(
            args.site,
            baseline=args.baseline,
            require_pagefind=not args.allow_no_pagefind,
        )
    except ValueError as error:
        print(f"docs site validation failed: {error}")
        return 1
    print("docs site validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
