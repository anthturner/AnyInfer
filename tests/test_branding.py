"""Brand assets stay consistent across the documentation, the website, and the bundled demo."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC_ASSETS = ROOT / "docs" / "assets"
DEMO_ASSETS = ROOT / "src" / "python" / "anyinfer_demo" / "assets"
WEBSITE = ROOT / "website"

RUNTIME_ASSETS = (
    "anyinfer-icon-512.svg",
    "anyinfer-icon-512.png",
    "anyinfer-horizontal-light.svg",
    "anyinfer-horizontal-dark.svg",
    "favicon-16.png",
    "favicon-24.png",
)

# The social card is finished art supplied with the brand kit, not composed in this
# repository. Replacing it means committing the kit's new SVG and PNG and updating these.
SOCIAL_CARD_SHA256 = {
    "anyinfer-social-card.svg": "58f2b315f39b93192c34b10381d8b523ab9a5041bc4e49742d0fc43349941e6e",
    "anyinfer-social-card.png": "255732739497cfd45667284383db95af6136c833adc6aebda11b42e77e76a1f6",
}

# Tokens renamed away in brand kit v2 (`--anyinfer-*` became `--ai-*`).
RETIRED_TOKENS = re.compile(
    r"--anyinfer-(?:teal|teal-deep|teal-bright|amber|gold|slate|knockout|bg|surface|border|"
    r"text|text-muted|muted|accent|accent-text|accent-strong|accent-bg|accent-border|"
    r"on-accent|link|link-hover|focus|card-bg|card-border|ok|danger)\b"
)


def _palette() -> str:
    return (DOC_ASSETS / "anyinfer-palette.css").read_text(encoding="utf-8")


def _block(css: str, selector_start: str) -> dict[str, str]:
    """The `--ai-*` declarations of the first rule whose selector starts as given."""
    start = css.index(selector_start)
    body = css[css.index("{", start) + 1 : css.index("}", start)]
    return {
        name: value.upper()
        for name, value in re.findall(r"--ai-([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\s*;", body)
    }


def _light_tokens() -> dict[str, str]:
    return _block(_palette(), ":root {")


def _dark_tokens() -> dict[str, str]:
    # The explicit-theme rule, which is what Docusaurus's data-theme attribute selects.
    return _block(_palette(), '[data-color-mode="dark"],')


def _luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _demo_theme_tables() -> dict[str, dict[str, str]]:
    """`_LIGHT`/`_DARK` from the demo theme, read without importing PySide6."""
    source = (ROOT / "src" / "python" / "anyinfer_demo" / "theme.py").read_text(encoding="utf-8")
    constants: dict[str, str] = {}
    tables: dict[str, dict[str, str]] = {}
    for node in ast.parse(source).body:
        target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
        value = getattr(node, "value", None)
        if not isinstance(target, ast.Name) or value is None:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            constants[target.id] = value.value
        elif isinstance(value, ast.Dict) and target.id in {"_LIGHT", "_DARK"}:
            table = {}
            for key, item in zip(value.keys, value.values, strict=True):
                assert isinstance(key, ast.Constant)
                if isinstance(item, ast.Name):
                    table[str(key.value)] = constants[item.id]
                else:
                    assert isinstance(item, ast.Constant)
                    table[str(key.value)] = str(item.value)
            tables[target.id] = {k: v.upper() for k, v in table.items()}
    return tables


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
    bundled = {path.name for path in DEMO_ASSETS.iterdir() if path.suffix in {".svg", ".png"}}
    assert bundled == set(RUNTIME_ASSETS)


def test_brand_constants_match_the_canonical_palette() -> None:
    palette = _palette()
    theme = (ROOT / "src" / "python" / "anyinfer_demo" / "theme.py").read_text(encoding="utf-8")
    expected = {
        "_AMBER": "amber",
        "_AMBER_BRIGHT": "amber-bright",
        "_TEAL": "teal",
        "_TEAL_BRIGHT": "teal-bright",
        "_INK": "ink",
        "_MIST": "mist",
    }
    for constant, token in expected.items():
        canonical = re.search(rf"--ai-brand-{token}:\s*(#[0-9A-Fa-f]{{6}});", palette)
        assert canonical is not None, token
        assert re.search(rf'^{constant} = "{canonical[1]}"$', theme, re.MULTILINE), constant


def test_demo_theme_tokens_are_the_palette_tokens() -> None:
    mapping = {
        "bg": "bg",
        "surface": "surface",
        "border": "border",
        "text": "text",
        "muted": "text-muted",
        "accent": "accent",
        "accent_bg": "accent-bg",
        "on_accent": "on-accent",
        "link": "link",
        "amber": "signal",
        "warn": "signal-text",
        "ok": "success",
        "danger": "danger",
    }
    tables = _demo_theme_tables()
    for table, tokens in (("_LIGHT", _light_tokens()), ("_DARK", _dark_tokens())):
        for key, token in mapping.items():
            assert tables[table][key] == tokens[token], (table, key)


def test_palette_text_tokens_meet_wcag_aa_in_both_themes() -> None:
    ink = _light_tokens()["brand-ink"]  # text on an amber fill is ink in both themes
    for tokens in (_light_tokens(), _dark_tokens()):
        for text in ("text", "text-muted", "link", "signal-text", "success", "danger"):
            for ground in ("bg", "surface"):
                assert _contrast(tokens[text], tokens[ground]) >= 4.5, (text, ground)
        assert _contrast(tokens["on-accent"], tokens["accent"]) >= 4.5
        assert _contrast(tokens["link"], tokens["accent-bg"]) >= 4.5
        assert _contrast(tokens["signal-text"], tokens["signal-bg"]) >= 4.5
        assert _contrast(ink, tokens["signal"]) >= 4.5


def test_code_theme_uses_palette_colors_with_aa_contrast() -> None:
    config = (WEBSITE / "docusaurus.config.ts").read_text(encoding="utf-8")
    themes = re.findall(r"\{text: '(#[0-9A-F]{6})', surface: '(#[0-9A-F]{6})'(.*?)\}", config)
    assert len(themes) == 2
    palette_values = set(_light_tokens().values()) | set(_dark_tokens().values())
    for text, surface, rest in themes:
        colors = [text, *re.findall(r"'(#[0-9A-F]{6})'", rest)]
        assert surface in palette_values
        for color in colors:
            assert color in palette_values, color
            assert _contrast(color, surface) >= 4.5, color


def test_social_card_is_the_brand_kit_art() -> None:
    for name, digest in SOCIAL_CARD_SHA256.items():
        # A Windows checkout may rewrite text line endings; the art itself must not change.
        content = (DOC_ASSETS / name).read_bytes()
        if name.endswith(".svg"):
            content = content.replace(b"\r\n", b"\n")
        assert hashlib.sha256(content).hexdigest() == digest, name
    svg = (DOC_ASSETS / "anyinfer-social-card.svg").read_text(encoding="utf-8")
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630"')
    # Outlined art: nothing a link unfurler would have to fetch or a font to render.
    for forbidden in ("<text", "<image", "href=", "url(", "@import", "<script"):
        assert forbidden not in svg, forbidden


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


def test_docusaurus_configuration_wires_up_the_brand_marks() -> None:
    config = (WEBSITE / "docusaurus.config.ts").read_text(encoding="utf-8")
    for expected in (
        "property: 'og:image'",
        "name: 'twitter:card', content: 'summary_large_image'",
        "name: 'twitter:image'",
        "anyinfer-social-card.png",
        "src: 'assets/anyinfer-horizontal-light.svg'",
        "srcDark: 'assets/anyinfer-horizontal-dark.svg'",
        "favicon: 'assets/favicon.ico'",
        "href: '/assets/favicon-16.png'",
        "href: '/assets/favicon-32.png'",
        "rel: 'apple-touch-icon'",
    ):
        assert expected in config, expected
    # The navbar lockup is at least the kit's 24 px minimum height.
    logo = re.search(r"navbar: \{\s*logo: \{.*?height: (\d+),", config, re.DOTALL)
    assert logo is not None and int(logo[1]) >= 24
    sources = (config, *(path.read_text(encoding="utf-8") for path in _website_sources()))
    for text in sources:
        for name in re.findall(r"assets/([A-Za-z0-9@._-]+\.(?:svg|png|ico))", text):
            assert (DOC_ASSETS / name).is_file(), name


def _website_sources() -> list[Path]:
    return sorted(
        path for pattern in ("*.css", "*.tsx", "*.ts") for path in (WEBSITE / "src").rglob(pattern)
    )


def test_website_builds_on_the_canonical_palette() -> None:
    stylesheet = (WEBSITE / "src" / "css" / "custom.css").read_text(encoding="utf-8")
    imported = re.search(r"@import '([^']+anyinfer-palette\.css)';", stylesheet)
    assert imported is not None
    assert (WEBSITE / "src" / "css" / imported[1]).resolve() == DOC_ASSETS / "anyinfer-palette.css"
    for path in _website_sources():
        text = path.read_text(encoding="utf-8")
        # The palette is the only place a token gets its value.
        assert not re.search(r"--ai-[a-z0-9-]+\s*:", text), path
        assert not RETIRED_TOKENS.search(text), path


def test_retired_palette_tokens_are_gone_from_published_styles() -> None:
    for path in DOC_ASSETS.glob("*.css"):
        assert not RETIRED_TOKENS.search(path.read_text(encoding="utf-8")), path
    assert not (ROOT / "docs" / "stylesheets").exists()


def test_site_fonts_are_self_hosted_and_pinned() -> None:
    package = json.loads((WEBSITE / "package.json").read_text(encoding="utf-8"))
    families = ("@fontsource/space-grotesk", "@fontsource/inter", "@fontsource/jetbrains-mono")
    for family in families:
        assert re.fullmatch(r"\d+\.\d+\.\d+", package["dependencies"][family]), family
    fonts = (WEBSITE / "src" / "fonts.ts").read_text(encoding="utf-8")
    for family in families:
        assert f"import '{family}/" in fonts, family
    config = (WEBSITE / "docusaurus.config.ts").read_text(encoding="utf-8")
    assert "clientModules: ['./src/fonts.ts']" in config
    for text in (config, *(path.read_text(encoding="utf-8") for path in _website_sources())):
        assert "fonts.googleapis.com" not in text and "fonts.gstatic.com" not in text


def test_deprecated_promotional_media_is_not_part_of_the_brand_kit() -> None:
    assert not (DOC_ASSETS / "flow.png").exists()
    assert not (DOC_ASSETS / "flow_video.mp4").exists()
    assert not (ROOT / "scripts" / "render_social_card.py").exists()
