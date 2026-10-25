# Branding and Visual Assets

AnyInfer's identity is a small kit: one mark, one logo, a palette of named color tokens,
and three typefaces. The canonical files live in
[`docs/assets/`](https://github.com/anthturner/AnyInfer/tree/main/docs/assets); the
documentation site and the README use them from there, and the demo application keeps mirrored
copies.

## The Mark

The mark is an **A** that fans out: one call goes in at the top and reaches many
providers.

- **The amber block** is AnyInfer itself, the layer that normalizes behavior. Its base
  forms the crossbar of the A.
- **The teal legs** are AnyInfer's adapters.
- **The slate ports** are the providers. Their three different shapes stand for providers
  that behave differently; all three fit the same 9.5 × 9.5 box.

Use the full mark at 32 px and up. Below 32 px, use the simple mark, which drops the ports
that would blur at that size. The favicon's 16 and 24 px images already do.

## The Name

- **In text**, write **AnyInfer**: "Why AnyInfer", "AnyInfer normalizes…".
- **In the logo**, the name is set lowercase as **anyinfer**. It matches what developers
  type (`pip install anyinfer`, `import anyinfer`), and only a lowercase `i` can carry the
  amber triangle.
- **The amber triangle on the `i`** appears only in the logo files. Never reproduce it in
  headings or body text.
- The logo is outlined Space Grotesk SemiBold, tracked −0.045em, with a narrowed `y`, so it
  needs no font to display. Use the files; don't retype the name.

## Using the Logo

- **Clear space:** leave at least the height of the amber block clear on every side.
- **Minimum size:** the logo with the name is at least 24 px tall on screen. The site's
  navigation bar shows it at 32 px and switches to the 32 px full mark on narrow screens.
- **Variants:** use the `on-light` art on light backgrounds and the `on-dark` art on dark
  ones. The site's footer is the dark ink ground in both themes, so it always uses the
  on-dark logo.
- **Don't** recolor, rotate, or outline the mark, add effects to it, or place it on teal
  or amber fills.

## Color

[`anyinfer-palette.css`](https://github.com/anthturner/AnyInfer/blob/main/docs/assets/anyinfer-palette.css) defines every color as an
`--ai-*` custom property. The light theme is the default. The dark theme applies through
`prefers-color-scheme`, or explicitly through `[data-theme="dark"]` (Docusaurus),
`[data-color-mode="dark"]` (GitHub Primer), `[data-md-color-scheme="slate"]` (MkDocs
Material), or a `.dark` class. Use the tokens by role rather than copying their values:

| Token | Role |
|---|---|
| `--ai-bg`, `--ai-surface`, `--ai-surface-2` | Page; panels and code; hover and selected states |
| `--ai-border` | Decorative rules and dividers |
| `--ai-text`, `--ai-text-muted` | Body text; secondary text |
| `--ai-accent`, `--ai-on-accent` | Primary actions; text on an accent fill |
| `--ai-focus` | Keyboard focus outlines |
| `--ai-link`, `--ai-link-hover` | Links and teal text |
| `--ai-accent-bg` | Note callouts and active navigation |
| `--ai-signal`, `--ai-signal-text`, `--ai-signal-bg` | Amber fill; amber text; prerelease and warning callouts |
| `--ai-port` | Provider ports and quiet decoration |
| `--ai-success`, `--ai-danger` | Pass and fail |
| `--ai-brand-*` | The mark's constant colors, identical in both themes |

Rules:

- **Amber (`--ai-signal`) is a fill only.** Amber text uses `--ai-signal-text`, and text
  on an amber fill is the brand ink.
- **Every text token passes WCAG AA** (4.5:1) against `--ai-bg` and `--ai-surface` in both
  themes. Text on `--ai-accent-bg` uses `--ai-link`, not `--ai-accent`, which falls just
  short there in the light theme.
- **Interactive boundaries** such as inputs and outlined buttons use the slate brand
  constant, which keeps 3:1 against the page in both themes. `--ai-border` is too faint
  for anything a reader has to find.

## Type

| Role | Family | Notes |
|---|---|---|
| Display and headings | Space Grotesk 500–600 | Tight tracking, −0.02 to −0.035em |
| Body and interface | Inter 400–600 | 16 px, line height 1.6 in documentation |
| Code and tokens | JetBrains Mono 400–500 | Code, provenance badges, labels |

The site serves these itself. The exact-pinned `@fontsource` packages in
[`website/package.json`](../../website/package.json) are imported by
[`website/src/fonts.ts`](../../website/src/fonts.ts), which loads only the Latin subset
of the weights above. The published site and its offline browser tests never contact a
font service.

## Where the Assets Live

| File in `docs/assets/` | Use |
|---|---|
| `anyinfer-icon-512.svg`, `anyinfer-icon-512.png` | Full mark for light backgrounds |
| `anyinfer-mark-on-dark.svg` | Full mark for dark backgrounds |
| `anyinfer-mark-simple-on-light.svg`, `anyinfer-mark-simple-on-dark.svg` | Simple mark, below 32 px |
| `anyinfer-horizontal-light.svg`, `anyinfer-horizontal-dark.svg` | Logo (mark and name) for light and dark backgrounds |
| `anyinfer-wordmark-on-light.svg`, `anyinfer-wordmark-on-dark.svg` | Name only, beside a separate full mark |
| `favicon.ico`, `favicon-16.png` … `favicon-64.png` | Favicon set; 16 and 24 px use the simple mark |
| `anyinfer-app-icon-light-180.png` | Touch icon for home screens |
| `anyinfer-palette.css` | Color tokens |
| `anyinfer-social-card.svg`, `anyinfer-social-card.png` | Link preview, 1200×630 |

The `anyinfer-icon-512.*` and `anyinfer-horizontal-*.svg` names predate the current kit,
whose own names for that art are `anyinfer-mark-on-light` and `anyinfer-logo-on-*`. The
old names stay because the README, which PyPI also shows, and outside links point at
them.

## How the Published Site Uses the Marks

[`website/docusaurus.config.ts`](../../website/docusaurus.config.ts) sets the navigation
bar and footer logos, the favicon set, and the Open Graph and Twitter card tags that
decide how an AnyInfer link renders when pasted elsewhere. Every page unfurls with its own
title and description over the shared 1200×630 card, a size Slack, Discord, X, LinkedIn,
and iMessage all render without re-cropping. The same file holds the code colors:
keywords in the amber text tone, literals in the link teal, comments muted.

[`website/src/css/custom.css`](../../website/src/css/custom.css) imports the palette and
maps Docusaurus's own variables onto it, so it never assigns a token a value of its own.
It also defines the kit's components for page authors:

- Buttons: `anyinfer-button` with `anyinfer-button-primary`, `anyinfer-button-secondary`,
  or `anyinfer-button-text`.
- Provenance badges, weakest to strongest: `anyinfer-badge` with `anyinfer-badge--default`,
  `--catalog`, `--discovered`, `--probed`, or `--override`.
- SDK status badges: `anyinfer-sdk-badge` with `anyinfer-sdk-badge--python` or
  `anyinfer-sdk-badge--csharp`. The navigation bar's version selector and each SDK page's
  version badge use them.
- Callouts: `note`, `info`, and `tip` render as the teal Note callout; `caution`,
  `warning`, and `danger` render as the amber callout.

The social card is finished art from the brand kit, not something this repository
generates. [`tests/test_branding.py`](../../tests/test_branding.py) pins both files'
digests, so replacing the card is a deliberate edit to that test as well. The card is a
website asset only; the demo package does not carry it. GitHub's own repository preview
image is a repository setting, not a file: upload the same `anyinfer-social-card.png`
under **Settings → General → Social preview**.

## How the Demo Mirrors Them

The demo application needs package-local copies under
[`src/python/anyinfer_demo/assets/`](https://github.com/anthturner/AnyInfer/tree/main/src/python/anyinfer_demo/assets)
because those files ship in the wheel and the standalone application: the full mark, both
logos, and the 16 and 24 px favicon images it uses for small window icons. They are
content-identical mirrors, not a second source of truth, and `tests/test_branding.py`
fails if they drift from `docs/assets/` or if the demo package carries any other
image.
[`src/python/anyinfer_demo/theme.py`](../../src/python/anyinfer_demo/theme.py) translates
the palette into Qt tokens, and the same tests check its brand constants and its light and
dark tokens against the palette.

## Updating the Brand Kit

1. Replace the files in `docs/assets/` with the kit's new versions, keeping the published
   file names listed above.
2. Copy the demo's runtime assets exactly into `src/python/anyinfer_demo/assets/`.
3. If the palette changed, update the Qt tokens in `theme.py` and the code colors in
   `website/docusaurus.config.ts`. The tests check that both use palette values and that
   every code color keeps 4.5:1 on the code surface.
4. If the social card changed, update its digests in `tests/test_branding.py`.
5. Run `python workspace.py check` and `python workspace.py build docs`, then read a few
   pages of the built site in both themes.

Keep screenshots and promotional media out of the canonical asset set. They become stale
independently of the logo and should be linked or generated as release collateral instead of
being treated as product identity.
