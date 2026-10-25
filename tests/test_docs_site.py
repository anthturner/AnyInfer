"""Artifact checks for the exported Docusaurus site."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[1] / "scripts" / "check_docs_site.py"
sys.path.insert(0, str(_SCRIPT.parent))
_SPEC = importlib.util.spec_from_file_location("check_docs_site", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
validate_site = _MODULE.validate_site


def _make_site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "python/api/client").mkdir(parents=True)
    (site / "assets").mkdir()
    (site / "llms").mkdir()
    (site / "assets/logo.svg").write_text("<svg/>", encoding="utf-8")
    (site / "CNAME").write_text("anyinfer.dev\n", encoding="utf-8")
    home = '<html><body><article><h1 id="home">Home</h1><a href="/python/api/client/#client">Client</a><img src="/assets/logo.svg"></article></body></html>'
    client = '<html><body><article><h1 id="client">Client</h1><p>anyinfer.Client</p></article></body></html>'
    (site / "index.html").write_text(home, encoding="utf-8")
    (site / "python/api/client/index.html").write_text(client, encoding="utf-8")
    manifest = {
        "pages": [
            {
                "source": "index.md",
                "sdk": "shared",
                "id": "home",
                "slug": "/",
                "url": "/",
                "title": "Home",
                "section": "Home",
                "order": 0,
            },
            {
                "source": "reference/api/client.md",
                "sdk": "python",
                "id": "reference/api/client",
                "slug": "/api/client/",
                "url": "/python/api/client/",
                "title": "Client",
                "section": "Reference",
                "order": 1,
            },
        ],
        "versions": {"python": "0.1.3", "csharp": "0.1.0-proof"},
        "redirects": {"/reference/api/client/": "/python/api/client/#client"},
    }
    (site / "reference/api/client").mkdir(parents=True)
    (site / "reference/api/client/index.html").write_text("redirect", encoding="utf-8")
    (site / "docs-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    receipt = "Python 0.1.3; C# 0.1.0-proof (prerelease).\n"
    (site / "llms.txt").write_text(receipt + "index", encoding="utf-8")
    (site / "llms-full.txt").write_text(receipt + "full", encoding="utf-8")
    (site / "llms/reference.txt").write_text(receipt + "reference", encoding="utf-8")
    return site


def test_validate_site_accepts_complete_minimal_fixture(tmp_path: Path) -> None:
    validate_site(_make_site(tmp_path), baseline=None, require_pagefind=False)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing_asset", "missing local target"),
        ("missing_fragment", "missing fragment"),
        ("empty_export", "empty documentation export"),
        ("oversize", "exceeds section budget"),
        ("redirect_collision", "collides with canonical"),
    ],
)
def test_validate_site_rejects_broken_artifacts(tmp_path: Path, mutation: str, match: str) -> None:
    site = _make_site(tmp_path)
    if mutation == "missing_asset":
        (site / "assets/logo.svg").unlink()
    elif mutation == "missing_fragment":
        (site / "index.html").write_text(
            '<html><body><article><a href="/python/api/client/#gone">Client</a></article></body></html>',
            encoding="utf-8",
        )
    elif mutation == "empty_export":
        (site / "llms-full.txt").write_text("", encoding="utf-8")
    elif mutation == "oversize":
        (site / "llms/reference.txt").write_text(
            "Python 0.1.3; C# 0.1.0-proof (prerelease).\n" + "x" * 800_001,
            encoding="utf-8",
        )
    else:
        manifest = json.loads((site / "docs-manifest.json").read_text(encoding="utf-8"))
        manifest["redirects"] = {"/": "/python/api/client/"}
        (site / "docs-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        validate_site(site, baseline=None, require_pagefind=False)


def test_validate_site_requires_local_pagefind_bundle(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Pagefind"):
        validate_site(_make_site(tmp_path), baseline=None)


def _add_generated_reference(site: Path, *, indexed: bool = True, exported: bool = True) -> None:
    manifest = json.loads((site / "docs-manifest.json").read_text(encoding="utf-8"))
    search = '<meta data-pagefind-filter="sdk:csharp">' if indexed else ""
    pages = {
        "/csharp/api/": '<a href="/csharp/api/n.alpha/">Alpha</a>',
        "/csharp/api/n.alpha/": '<h1 id="alpha">Alpha</h1><a id="member-0123456789abcdef"></a>',
    }
    for order, (url, body) in enumerate(pages.items(), 10):
        directory = site / url.strip("/")
        directory.mkdir(parents=True)
        (directory / "index.html").write_text(
            f"<html><head>{search}</head><body><article>{body}<p>{url}</p></article></body></html>",
            encoding="utf-8",
        )
        manifest["pages"].append(
            {
                "source": f"generated:csharp-api/{url}",
                "sdk": "csharp",
                "id": url,
                "slug": url,
                "url": url,
                "title": url,
                "section": "C# API Reference",
                "order": order,
                "generated": True,
            }
        )
    manifest["generated"] = {
        "csharp-api": {"sdk": "csharp", "namespaces": [{"label": "N", "items": []}]}
    }
    (site / "docs-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if exported:
        with (site / "llms-full.txt").open("a", encoding="utf-8") as handle:
            for url in pages:
                handle.write(f"\nSource: https://anyinfer.dev{url}\n\n{url}\n")


def test_validate_site_accepts_a_complete_generated_reference(tmp_path: Path) -> None:
    site = _make_site(tmp_path)
    _add_generated_reference(site)
    validate_site(site, baseline=None, require_pagefind=False, require_generated_reference=True)


@pytest.mark.parametrize(
    ("variant", "match"),
    [
        ("absent", "no generated C# API reference"),
        ("unindexed", "not indexed for C# search"),
        ("unexported", "missing from llms-full.txt"),
    ],
)
def test_validate_site_rejects_an_incomplete_generated_reference(
    tmp_path: Path, variant: str, match: str
) -> None:
    site = _make_site(tmp_path)
    if variant != "absent":
        _add_generated_reference(
            site, indexed=variant != "unindexed", exported=variant != "unexported"
        )
    with pytest.raises(ValueError, match=match):
        validate_site(
            site, baseline=None, require_pagefind=False, require_generated_reference=True
        )


def _add_archive(site: Path, *, indexed: bool) -> None:
    manifest = json.loads((site / "docs-manifest.json").read_text(encoding="utf-8"))
    manifest["archives"] = {
        "csharp": [
            {"version": "0.0.9-proof", "pages": [{"url": "/csharp/0.0.9-proof/", "title": "C#"}]}
        ]
    }
    (site / "docs-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    directory = site / "csharp" / "0.0.9-proof"
    directory.mkdir(parents=True)
    metadata = '<meta data-pagefind-filter="version:0.0.9-proof">' if indexed else ""
    body = " data-pagefind-body" if indexed else ""
    (directory / "index.html").write_text(
        f"<html><head>{metadata}</head><body><article{body}><h1>C#</h1>"
        '<a href="/python/api/client/#client">Client</a></article></body></html>',
        encoding="utf-8",
    )


def test_validate_site_accepts_searchable_archived_versions(tmp_path: Path) -> None:
    site = _make_site(tmp_path)
    _add_archive(site, indexed=True)
    validate_site(site, baseline=None, require_pagefind=False)


def test_validate_site_rejects_unsearchable_or_missing_archived_pages(tmp_path: Path) -> None:
    site = _make_site(tmp_path)
    _add_archive(site, indexed=False)
    with pytest.raises(ValueError, match=r"not searchable as csharp 0\.0\.9-proof"):
        validate_site(site, baseline=None, require_pagefind=False)
    (site / "csharp" / "0.0.9-proof" / "index.html").unlink()
    with pytest.raises(ValueError, match="archived page is missing"):
        validate_site(site, baseline=None, require_pagefind=False)
