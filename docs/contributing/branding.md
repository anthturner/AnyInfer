# Branding and visual assets

The canonical logo files and palette live in `docs/assets/`:

- `anyinfer-icon-512.svg` and `anyinfer-icon-512.png` for square marks and favicons;
- `anyinfer-horizontal-light.svg` and `anyinfer-horizontal-dark.svg` for wordmarks;
- `anyinfer-palette.css` for the deep-teal, amber, gold, and slate color tokens.

Use the supplied assets. Do not redraw the mark, substitute a provider logo, recolor a
wordmark, or add generated approximations. The icon art is background-independent; only the
wordmark text changes between light and dark variants.

The demo needs package-local copies under `src/demo_app/assets/` because those files ship in
the wheel and standalone application. They are content-identical mirrors, not a second
source of truth; SVG line endings may follow the checkout platform. Tests fail if they drift
from `docs/assets/`. `src/demo_app/theme.py` translates the canonical palette into Qt tokens,
and the same tests pin its brand constants.

When changing the brand kit:

1. Edit the canonical files in `docs/assets/`.
2. Copy the four runtime assets exactly into `src/demo_app/assets/`.
3. Update the Qt tokens only if `anyinfer-palette.css` changed.
4. Run `python workspace.py check` and `python workspace.py build docs`.

Keep screenshots and promotional media out of the canonical asset set. They become stale
independently of the logo and should be linked or generated as release collateral instead of
being treated as product identity.
