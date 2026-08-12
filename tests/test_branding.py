"""Brand assets stay consistent across the documentation and bundled demo."""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC_ASSETS = ROOT / "docs" / "assets"
DEMO_ASSETS = ROOT / "src" / "demo_app" / "assets"

RUNTIME_ASSETS = (
    "anyinfer-icon-512.svg",
    "anyinfer-icon-512.png",
    "anyinfer-horizontal-light.svg",
    "anyinfer-horizontal-dark.svg",
)


def test_demo_brand_assets_are_exact_canonical_mirrors() -> None:
    for name in RUNTIME_ASSETS:
        demo, docs = DEMO_ASSETS / name, DOC_ASSETS / name
        if demo.suffix == ".svg":
            assert (
                demo.read_text(encoding="utf-8").splitlines()
                == docs.read_text(encoding="utf-8").splitlines()
            ), name
        else:
            assert demo.read_bytes() == docs.read_bytes(), name


def test_brand_constants_match_the_canonical_palette() -> None:
    palette = (DOC_ASSETS / "anyinfer-palette.css").read_text(encoding="utf-8")
    theme = (ROOT / "src" / "demo_app" / "theme.py").read_text(encoding="utf-8")
    expected = {
        "_TEAL": "#2C7A6F",
        "_TEAL_DEEP": "#0B3B3C",
        "_TEAL_BRIGHT": "#4FBFA8",
        "_AMBER": "#E8963C",
        "_GOLD": "#F0C86A",
    }
    for constant, color in expected.items():
        assert color.lower() in palette.lower()
        assert re.search(rf'^{constant} = "{color}"$', theme, re.MULTILINE)


def test_social_card_is_current_with_the_wordmark() -> None:
    # The card is composed from the canonical dark wordmark, so a wordmark edit that is not
    # followed by `python scripts/render_social_card.py` would leave every link unfurl
    # showing the old art. The PNG cannot be re-rendered here (it needs Qt), but it is
    # written in the same run as the SVG, so pinning the SVG pins both.
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_social_card import render_card_svg  # type: ignore[import-not-found]

    committed = (DOC_ASSETS / "anyinfer-social-card.svg").read_text(encoding="utf-8")
    assert committed.splitlines() == render_card_svg().splitlines(), (
        "docs/assets/anyinfer-social-card.svg is stale - run "
        "`python scripts/render_social_card.py`"
    )


def test_social_card_png_has_the_dimensions_unfurlers_expect() -> None:
    # 1200x630 is the size Slack, X, LinkedIn and Facebook all render uncropped; anything
    # else gets centre-cropped differently by each of them.
    header = (DOC_ASSETS / "anyinfer-social-card.png").read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", header[16:24]) == (1200, 630)


def test_social_card_is_documentation_only() -> None:
    # The demo bundle mirrors the runtime assets; the link-preview card is a website
    # concern and has no business adding weight to the wheel.
    assert not (DEMO_ASSETS / "anyinfer-social-card.png").exists()


def test_site_head_template_wires_up_the_brand_marks() -> None:
    head = (ROOT / "overrides" / "main.html").read_text(encoding="utf-8")
    for expected in (
        'property="og:image"',
        'name="twitter:card" content="summary_large_image"',
        "anyinfer-social-card.png",
        "anyinfer-icon-512.svg",
        'rel="apple-touch-icon"',
    ):
        assert expected in head, expected


def test_deprecated_promotional_media_is_not_part_of_the_brand_kit() -> None:
    assert not (DOC_ASSETS / "flow.png").exists()
    assert not (DOC_ASSETS / "flow_video.mp4").exists()
