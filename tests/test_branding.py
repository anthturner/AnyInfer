"""Brand assets stay consistent across the documentation and bundled demo."""

from __future__ import annotations

import re
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
            assert demo.read_text(encoding="utf-8").splitlines() == docs.read_text(
                encoding="utf-8"
            ).splitlines(), name
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


def test_deprecated_promotional_media_is_not_part_of_the_brand_kit() -> None:
    assert not (DOC_ASSETS / "flow.png").exists()
    assert not (DOC_ASSETS / "flow_video.mp4").exists()
