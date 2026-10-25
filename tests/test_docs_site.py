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
            {"source": "index.md", "sdk": "shared", "id": "home", "slug": "/", "url": "/", "title": "Home", "section": "Home", "order": 0},
            {"source": "reference/api/client.md", "sdk": "python", "id": "reference/api/client", "slug": "/api/client/", "url": "/python/api/client/", "title": "Client", "section": "Reference", "order": 1},
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
