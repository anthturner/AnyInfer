# Branding and Visual Assets

The canonical logo files and palette live in
[`docs/assets/`](https://github.com/anthturner/AnyInfer/tree/main/docs/assets):

- `anyinfer-icon-512.svg` and `anyinfer-icon-512.png` for square marks and favicons;
- `anyinfer-horizontal-light.svg` and `anyinfer-horizontal-dark.svg` for wordmarks;
- `anyinfer-palette.css` for the deep-teal, amber, gold, and slate color tokens;
- `anyinfer-social-card.svg` and `anyinfer-social-card.png` for link previews. Generated,
  not hand-drawn; see below.

Use the supplied assets: do not redraw the mark, substitute a provider logo, recolor a
wordmark, or add generated approximations. The icon art is background-independent; only the
wordmark text changes between light and dark variants.

The demo needs package-local copies under
[`src/anyinfer_demo/assets/`](https://github.com/anthturner/AnyInfer/tree/main/src/anyinfer_demo/assets)
because those files ship in the wheel and standalone application. They are
content-identical mirrors, not a second source of truth; SVG line endings may follow the
checkout platform.
[`tests/test_branding.py`](https://github.com/anthturner/AnyInfer/blob/main/tests/test_branding.py)
fails if they drift from `docs/assets/`.
[`src/anyinfer_demo/theme.py`](https://github.com/anthturner/AnyInfer/blob/main/src/anyinfer_demo/theme.py)
translates the canonical palette into Qt tokens, and the same tests pin its brand
constants.

## How the Published Site Uses the Marks

[`mkdocs.yml`](https://github.com/anthturner/AnyInfer/blob/main/mkdocs.yml) points the
header logo and favicon at the icon, and
[`overrides/main.html`](https://github.com/anthturner/AnyInfer/blob/main/overrides/main.html)
adds the SVG favicon, the Apple touch icon, and the Open Graph and Twitter card tags that
decide how an AnyInfer link renders when pasted elsewhere. Every page unfurls with its own
title and description over the shared 1200×630 card, a size Slack, Discord, X, LinkedIn,
and iMessage all render without re-cropping.

The card is not a hand-drawn file.
[`scripts/render_social_card.py`](https://github.com/anthturner/AnyInfer/blob/main/scripts/render_social_card.py)
composes it from the canonical dark wordmark on the deep-teal surface and rasterizes it
with Qt's SVG renderer, writing both `anyinfer-social-card.svg` and
`anyinfer-social-card.png`. A wordmark edit that skips this step fails
`tests/test_branding.py`. The card is a website asset only; it is not mirrored into the
demo package.

GitHub's own repository preview image is a repository setting, not a file: upload the same
`anyinfer-social-card.png` under **Settings → General → Social preview**.

When changing the brand kit:

1. Edit the canonical files in `docs/assets/`.
2. Copy the four runtime assets exactly into `src/anyinfer_demo/assets/`.
3. Update the Qt tokens only if `anyinfer-palette.css` changed.
4. Run `python scripts/render_social_card.py` if a wordmark or the surface color changed.
5. Run `python workspace.py check` and `python workspace.py build docs`.

Keep screenshots and promotional media out of the canonical asset set. They become stale
independently of the logo and should be linked or generated as release collateral instead of
being treated as product identity.
