# Branding and visual assets

The canonical logo files and palette live in `docs/assets/`:

- `anyinfer-icon-512.svg` and `anyinfer-icon-512.png` for square marks and favicons;
- `anyinfer-horizontal-light.svg` and `anyinfer-horizontal-dark.svg` for wordmarks;
- `anyinfer-palette.css` for the deep-teal, amber, gold, and slate color tokens;
- `anyinfer-social-card.svg` and `anyinfer-social-card.png` for link previews. Generated,
  not hand-drawn — see below.

Use the supplied assets. Do not redraw the mark, substitute a provider logo, recolor a
wordmark, or add generated approximations. The icon art is background-independent; only the
wordmark text changes between light and dark variants.

The demo needs package-local copies under `src/demo_app/assets/` because those files ship in
the wheel and standalone application. They are content-identical mirrors, not a second
source of truth; SVG line endings may follow the checkout platform. Tests fail if they drift
from `docs/assets/`. `src/demo_app/theme.py` translates the canonical palette into Qt tokens,
and the same tests pin its brand constants.

## How the published site uses the marks

`mkdocs.yml` points the header logo and favicon at the icon. `overrides/main.html` adds the
rest of the head: an SVG favicon, an Apple touch icon, and the Open Graph and Twitter card
tags that decide how an AnyInfer link renders when it is pasted into Slack, Discord, X,
LinkedIn, or iMessage. Each page unfurls with its own title and description over the shared
1200×630 card, which is the size every one of those services renders without re-cropping.

The card is not a hand-drawn file. `scripts/render_social_card.py` composes it from the
canonical dark wordmark on the deep-teal surface and rasterizes it with Qt's SVG renderer,
writing both `anyinfer-social-card.svg` and `anyinfer-social-card.png`. A wordmark edit that
skips this step fails `tests/test_branding.py`. The card is a website asset only — it is not
mirrored into the demo package.

GitHub's own repository preview image is a repository setting, not a file: upload the same
`anyinfer-social-card.png` under **Settings → General → Social preview**.

When changing the brand kit:

1. Edit the canonical files in `docs/assets/`.
2. Copy the four runtime assets exactly into `src/demo_app/assets/`.
3. Update the Qt tokens only if `anyinfer-palette.css` changed.
4. Run `python scripts/render_social_card.py` if a wordmark or the surface color changed.
5. Run `python workspace.py check` and `python workspace.py build docs`.

Keep screenshots and promotional media out of the canonical asset set. They become stale
independently of the logo and should be linked or generated as release collateral instead of
being treated as product identity.
