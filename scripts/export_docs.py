"""Write static redirects, search metadata, and agent exports from rendered docs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ORIGIN = "https://anyinfer.dev"
SECTION_MAX_BYTES = 800_000
RETIRED = {
    "guides/when-to-use.md": "why-anyinfer.md",
    "guides/integration-paths.md": "guides/README.md",
    "guides/local-models.md": "guides/local-inference.md",
    "guides/credentials.md": "concepts/credentials.md",
    "guides/soc2-mapping.md": "guides/confidentiality-tiers.md#appendix-soc-2-control-mapping",
    "guides/sidecar-corpus-context.md": "serve/README.md#reducing-an-explicit-corpus",
    "examples/compare-targets.md": "guides/comparing-targets.md",
    "concepts/rate-limits.md": "concepts/routing.md#pacing-before-the-limit",
    "concepts/models.md": "concepts/catalog.md#acquiring-a-pick",
    "reference/run-manifest.md": "concepts/run-manifests.md",
    "providers/jina.md": "providers/retrieval.md",
    "providers/voyage.md": "providers/retrieval.md",
    "contributing/repository-setup.md": "contributing/releasing.md",
}


class Article(HTMLParser):
    """Extract article text and anchors, excluding navigation and controls."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.skip: str | None = None
        self.skip_depth = 0
        self.chunks: list[str] = []
        self.anchors: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track article nesting and skip non-content subtrees."""
        values = dict(attrs)
        if values.get("id"):
            self.anchors.add(str(values["id"]))
        if self.skip:
            if tag == self.skip:
                self.skip_depth += 1
            return
        if tag == "article":
            self.depth += 1
        elif self.depth:
            classes = values.get("class") or ""
            if tag in {"script", "style", "nav", "svg", "button", "form"} or any(
                name in classes for name in ("hash-link", "headerlink", "theme-edit")
            ):
                self.skip, self.skip_depth = tag, 1
            elif tag in {"p", "div", "li", "tr", "br", "pre", "h1", "h2", "h3", "h4", "h5", "h6"}:
                self.chunks.append("\n")
            elif tag in {"td", "th"}:
                # Keep table cells apart in exported text instead of running them together.
                self.chunks.append(" ")

    def handle_endtag(self, tag: str) -> None:
        """Retain paragraph boundaries without keeping page chrome."""
        if self.skip:
            if tag == self.skip:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skip = None
            return
        if tag == "article" and self.depth:
            self.depth -= 1
        elif self.depth and tag in {
            "p",
            "div",
            "li",
            "tr",
            "pre",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        """Keep visible article data."""
        if self.depth and not self.skip:
            self.chunks.append(data)

    def text(self) -> str:
        """Return text with stable paragraph boundaries."""
        return re.sub(
            r"\n{3,}",
            "\n\n",
            "\n".join(line.strip() for line in "".join(self.chunks).splitlines()),
        ).strip()


def page_file(site: Path, url: str) -> Path:
    """Resolve a same-site URL to its static HTML file."""
    path = urlsplit(url).path.lstrip("/")
    if ".." in Path(path).parts:
        raise ValueError(f"unsafe documentation URL: {url}")
    return site / (
        path if path.endswith(".html") else f"{path.rstrip('/')}/index.html".lstrip("/")
    )


def old_url(source: str) -> str:
    """Return the legacy directory URL for a Markdown source."""
    path = source.removesuffix(".md")
    if path.endswith(("/README", "/index")):
        path = path.rsplit("/", 1)[0]
    elif path in {"README", "index"}:
        path = ""
    return "/" + path.strip("/") + ("/" if path else "")


def redirects_for(manifest: dict) -> dict[str, str]:
    """Combine SDK moves with previously retired routes."""
    pages = {page["source"]: page["url"] for page in manifest["pages"]}
    redirects = dict(manifest.get("redirects", {}))
    for source, target in RETIRED.items():
        destination, _, anchor = target.partition("#")
        redirects[old_url(source)] = pages[destination] + (f"#{anchor}" if anchor else "")
    return {source: target for source, target in redirects.items() if source != target}


def _write(site: Path, name: str, text: str, *, bounded: bool = False) -> None:
    text = text.rstrip() + "\n"
    if re.search(r"\bADR-\d{3}\b", text):
        raise ValueError(f"{name} contains an internal decision identifier")
    if bounded and len(text.encode("utf-8")) > SECTION_MAX_BYTES:
        raise ValueError(f"{name} exceeds the {SECTION_MAX_BYTES}-byte section budget")
    destination = site / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def export_site(site: Path, manifest: dict) -> None:
    """Export current article content and preserve old links using static files."""
    sections: dict[str, list[tuple[dict, str]]] = {}
    bodies: dict[str, str] = {}
    versions = manifest["versions"]
    version_line = f"Python {versions['python']}; C# {versions['csharp']} (prerelease)."
    for page in sorted(manifest["pages"], key=lambda value: value["order"]):
        path = page_file(site, page["url"])
        html = path.read_text(encoding="utf-8")
        article = Article()
        article.feed(html)
        body = article.text()
        if not body:
            raise ValueError(f"no rendered article content for {page['source']}")
        bodies[page["url"]] = body
        sdk = page["sdk"]
        version = str(versions.get(sdk, "current"))
        scope = "shared" if sdk == "shared" else f"{sdk}:{version}"
        metadata = (
            f'<meta data-pagefind-filter="scope:{escape(scope, quote=True)}">'
            f'<meta data-pagefind-filter="sdk:{escape(sdk, quote=True)}">'
            f'<meta data-pagefind-filter="version:{escape(version, quote=True)}">'
            f'<meta data-pagefind-meta="sdk[content]" content="{escape(sdk)}">'
            f'<meta data-pagefind-meta="version[content]" content="{escape(version)}">'
        )
        html = html.replace("</head>", metadata + "</head>", 1)
        html = re.sub(r"<article(?=[\s>])", "<article data-pagefind-body", html, count=1)
        path.write_text(html, encoding="utf-8")
        sections.setdefault(page["section"], []).append((page, body))

    index = [
        "# AnyInfer",
        "",
        f"> {version_line}",
        "",
        f"Full current documentation: {ORIGIN}/llms-full.txt",
        "",
    ]
    full = [f"# AnyInfer — full documentation\n\n{version_line}\n"]
    for section, entries in sections.items():
        slug = re.sub(r"[^a-z0-9]+", "-", section.lower().replace("c#", "csharp")).strip("-")
        header = f"# AnyInfer — {section}\n\n{version_line}\n"
        chunks = [
            f"\n---\n\n# {page['title']}\n\nSource: {ORIGIN}{page['url']}\n\n{body}\n"
            for page, body in entries
        ]
        full.extend(chunks)
        index.extend([f"## {section}", "", f"Section text: {ORIGIN}/llms/{slug}.txt", ""])
        for page, body in entries:
            summary = " ".join(body.split())[:180]
            index.append(f"- [{page['title']}]({ORIGIN}{page['url']}): {summary}")
        index.append("")
        section_text = header + "".join(chunks)
        if len(section_text.encode("utf-8")) <= SECTION_MAX_BYTES:
            _write(site, f"llms/{slug}.txt", section_text, bounded=True)
        else:
            # Stable topic parts preserve the original section URL without raising its limit.
            links = [header, "This section is split into topic bundles:\n"]
            for number, ((page, _), chunk) in enumerate(zip(entries, chunks, strict=True), 1):
                name = f"llms/{slug}-{number}.txt"
                _write(site, name, header + chunk, bounded=True)
                links.append(f"- {page['title']}: {ORIGIN}/{name}\n")
            _write(site, f"llms/{slug}.txt", "\n".join(links), bounded=True)
    _write(site, "llms.txt", "\n".join(index))
    _write(site, "llms-full.txt", "\n".join(full))

    redirects = redirects_for(manifest)
    canonical = {page["url"] for page in manifest["pages"]}
    titles = {page["url"]: page["title"] for page in manifest["pages"]}
    for source, target in redirects.items():
        if source in canonical:
            raise ValueError(f"redirect overwrites canonical page: {source}")
        if urlsplit(target).path not in canonical:
            raise ValueError(f"redirect has no canonical target: {source} -> {target}")
        absolute = ORIGIN + target
        safe = escape(absolute, quote=True)
        target_path = urlsplit(target).path
        title = escape(f"{titles[target_path]} · AnyInfer", quote=True)
        description = escape(" ".join(bodies[target_path].split())[:240], quote=True)
        script_target = json.dumps(target).replace("<", "\\u003c")
        text = (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="robots" content="noindex"><title>{title}</title>'
            f'<meta name="description" content="{description}">'
            f'<link rel="canonical" href="{safe}">'
            f'<meta http-equiv="refresh" content="0;url={safe}">'
            f'<meta property="og:url" content="{safe}">'
            f'<meta property="og:title" content="{title}">'
            f'<meta property="og:description" content="{description}">'
            f'<meta property="og:image" content="{ORIGIN}/assets/anyinfer-social-card.png">'
            '<meta name="twitter:card" content="summary_large_image">'
            f'<meta name="twitter:title" content="{title}">'
            f'<meta name="twitter:description" content="{description}"></head><body>'
            f'<p>This page moved to <a href="{safe}">{safe}</a>.</p>'
            f"<script>const target={script_target};"
            'location.replace(target+(target.includes("#")?"":location.hash));</script>'
            "</body></html>"
        )
        output = page_file(site, source)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    manifest = {**manifest, "redirects": redirects}
    _write(site, "docs-manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    receipt = {
        page["url"]: hashlib.sha256(page_file(site, page["url"]).read_bytes()).hexdigest()
        for page in manifest["pages"]
    }
    _write(
        site,
        "docs-receipt.json",
        json.dumps({"versions": versions, "pages": receipt}, indent=2),
    )


def main() -> int:
    """Run the post-build exporter."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=Path("site"))
    parser.add_argument("--manifest", type=Path, default=Path("website/.generated/manifest.json"))
    args = parser.parse_args()
    export_site(args.site, json.loads(args.manifest.read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
