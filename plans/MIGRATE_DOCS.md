# Migrate documentation from MkDocs to Docusaurus

**Resume from the first unchecked box.** Read this entire file, `AGENTS.md`, and
`DESIGN.md` before executing. Each box has a test gate; tick it only after inspecting
the result. Record departures immediately below the affected box with a `> NOTE:`
and reconcile the checklist after every work wave.

Status: **plan only; implementation has not been authorized by this request.**
Prepared on 2026-10-25 against checkout `117a0d80ed4f48a6968250ad6956f1ca681429a4`
plus the existing working tree. The checkout has unrelated C# development changes,
including changes to `workspace.py`, CI, tests, and documentation. Re-read those files
before editing during execution; preserve that work. This plan does not authorize
branching, implementation, committing, or deployment now.

## Outcome and settled decisions

Replace the MkDocs/Material publisher with one Docusaurus site at
`https://anyinfer.dev/`, still built by GitHub Actions and hosted on GitHub Pages.
Ship generated Python **and** C# references, retain the useful current documentation,
and make a future SDK an additional content/generator registration rather than a
site rebuild.

The user explicitly selected:

- Independent SDK documentation versions; shared concepts remain together.
- Generated references for Python and C# in this migration.
- Local search, with its index built in CI and served by GitHub Pages.

Additional implementation decisions:

1. **Static deployment throughout.** No application server, database, paid search
   subscription, or hosted documentation platform. Preserve the existing Pages
   workflow, domain, release trigger, permissions, artifact naming, duplicate-artifact
   cleanup, and deployment concurrency behavior.
2. **One authored source per page.** Keep prose in `docs/`. Put Docusaurus configuration
   and UI in `website/`. Prepare generated inputs under `website/.generated/`, then
   publish the complete artifact to the existing root `site/` directory. Never make
   authors maintain a Markdown copy in both trees.
3. **Three docs instances initially:** `shared`, `python`, and `csharp`. Use `/` for
   shared conceptual/operator/contributor documentation, `/python/` for Python-specific
   guides and reference, and `/csharp/` for C#-specific guides and reference. Programming
   languages are SDK sections, not Docusaurus translation locales.
4. **Independent current versions, no invented history.** Read Python's version from
   `pyproject.toml` and each add-on's own distribution metadata; read C#'s evaluated
   package version from `src/csharp/AnyInfer/AnyInfer.csproj` and its imported props.
   Current observed values are Python `0.1.3` and C# `0.1.0-proof`, not constants to
   embed in the site. Keep Python's supported/published status and C#'s prerelease,
   local-package, bounded-capability status explicit. This is not a parity expansion.
5. **Generated API content uses language-native extraction.** Python: Griffe plus
   `griffe2md.render_object_docs`, grouped by the existing reference topics. C#:
   DocFX metadata for the single public `AnyInfer` library, initially using its
   Markdown output. No OpenAPI-to-SDK-reference substitution and no second DocFX site.
   The bounded C# fallback is described in MD2.C; do not silently change generators.
6. **Search uses Pagefind.** Generate the index from the final static HTML and provide
   a small Docusaurus `SearchBar` adapter. Its SDK/version filters use site metadata,
   avoiding reliance on a search plugin with only one preferred-version SDK setting.
   All search JavaScript, WebAssembly, and index files ship in the Pages artifact.
7. **Preserve URLs deliberately.** Retain current shared routes where practical;
   moved SDK pages get static redirects, existing retired routes remain supported,
   and referenced fragments receive explicit anchors or a documented fragment map.
   Never assume Pages can serve HTTP redirect rules.
8. **Preserve the brand, not Material's DOM.** Reuse existing SVG/PNG art, teal/amber
   palette, social card, typography intent, downloads entry, and light/dark behavior.
   Replace Material templates and selectors with Docusaurus components/styles.
9. **Preserve documentation guarantees.** Public-symbol/docstring coverage, runnable
   examples, generated indexes, strict links, agent exports, redaction requirements,
   and the absence of internal decision identifiers remain gates. New site tooling
   is build/dev tooling, never a mandatory dependency of an installed SDK.
10. **Keep the migration bounded.** Do not change runtime/config/provider semantics,
    add translations, redesign the brand, rewrite all prose, publish C# to NuGet,
    claim new SDK capability, or manufacture historical API references.

## Evidence and current integration points

These are discovery pointers; inspect current files again before implementation.

| Area | Current authority / behavior | Migration obligation |
|---|---|---|
| Site configuration | `mkdocs.yml`: explicit nav, Material overrides, Python Markdown extensions, Python-only mkdocstrings handler | Replace configuration and convert supported syntax; preserve curated navigation |
| Python reference | `docs/reference/api/*.md`: prose plus `::: qualified.symbol` directives | Preserve topic grouping, aliases, annotations, constants, add-ons, and coverage |
| Python coverage | `workspace.py`: `_PUBLIC_SURFACES`, `_PUBLIC_EXTRA_SYMBOLS`, `_scan_public_boundaries`, `_reference_directives`, `_referenced_object_ids`, `_check_docstrings` | Replace directive discovery without weakening any public-boundary check |
| C# reference | `docs/reference/csharp-sdk.md` is authored prose; `src/csharp/AnyInfer/AnyInfer.csproj` does not currently request XML documentation | Retain authored semantic guidance and add generated public API documentation |
| Native toolchain | `src/csharp/global.json`: SDK `8.0.425`, `latestPatch`; `Directory.Build.props`: `net8.0`, warnings as errors, package version | Use the pinned native toolchain; do not retarget the SDK or scan probe/test projects |
| Hook behavior | `scripts/mkdocs_hooks.py`: `on_config`, `on_page_markdown`, `on_nav`, `on_post_page`, `on_post_build` | Port release metadata, provider count, redirects, rendered-body extraction, and exports |
| Agent exports | `llms.txt`, `llms-full.txt`, and `llms/<section>.txt`; `LLMS_SECTION_MAX_BYTES = 800_000` | Preserve filenames and version/source attribution; rendered API bodies must be included |
| Existing redirects | `scripts/mkdocs_hooks.py::REDIRECTS` and `_write_redirects` | Preserve every mapping, anchor, fallback link, canonical URL, and social metadata |
| Site styling | `overrides/{main,home,404}.html`, `overrides/partials/header.html`, `docs/stylesheets/`, `docs/assets/` | Replace templates; retain artwork and public asset URLs |
| Generated content | `scripts/generate_provider_index.py`, `workspace.py matrix`, registry-derived provider data | Preserve generators/freshness checks; do not author duplicate counts |
| Developer entry points | `workspace.py::_build_docs_site`, `_gate_phases`, `cmd_build`, `cmd_docs`, `cmd_setup`, tool diagnostics | Keep one build implementation for the docs-build gate and publication |
| Deployment | `.github/workflows/docs-site.yml` builds through `workspace.py`, uploads `site/`, then deploys Pages | Add build toolchains, retain hosting and deployment safeguards |
| CI | `.github/workflows/ci.yml`: docs-only classifier, `docs-check`, `docs-build`, Python test matrix, later native tool setup | Install Node/.NET before the docs build; keep executable build tooling classified as code |
| Existing tests | `tests/test_workspace.py`, `tests/test_docs_examples.py`, `tests/test_agent_instructions.py` | Adapt renderer/command assumptions; retain behavior and canonical-procedure tests |
| Packaging | `pyproject.toml` dev dependencies and sdist include list | Remove obsolete docs tools at the end; never put Node modules or generated sites in distributions |

Official sources checked during planning:

- [Docusaurus multi-instance docs](https://docusaurus.io/docs/docs-multi-instance):
  separate docs plugins support independent SDK release histories.
- [Docusaurus deployment](https://docusaurus.io/docs/deployment): static output and
  GitHub Pages are supported; `url` and `baseUrl` determine deployment paths.
- [Docusaurus Markdown configuration](https://docusaurus.io/docs/api/docusaurus-config#markdown):
  `markdown.format: 'detect'` distinguishes `.md` from `.mdx`; broken-link/image hooks
  can fail the build. CommonMark mode requires the representative-format gate below.
- [Docusaurus versions](https://docusaurus.io/versions): initial Docusaurus package
  candidate `3.10.2`; keep all first-party Docusaurus packages on the same exact version.
- [Node release schedule](https://nodejs.org/en/about/previous-releases): Node 24 is an
  LTS release. Use Node 24 for docs tooling; this does not change Python support.
- [griffe2md API](https://mkdocstrings.github.io/griffe2md/reference/api/): selective
  rendering uses `render_object_docs`; configure docstring parsing on the Griffe loader
  and resolve aliases before rendering. The [PyPI page](https://pypi.org/project/griffe2md/)
  retrieved during planning exposed `1.5.0`; verify the installable version/API in MD1.
- [DocFX configuration](https://dotnet.github.io/docfx/reference/docfx-json-reference.html#outputformat)
  documents `mref`, `apiPage`, and `markdown` metadata output modes. The
  [NuGet package page](https://www.nuget.org/packages/docfx) exposes `2.81.0` targeting
  .NET 8; use a local tool manifest, not a global install.
- [Pagefind](https://pagefind.app/docs/) exposes `1.5.2` during planning and generates a
  static search bundle. Its [HTML filters](https://pagefind.app/docs/filtering/) can
  carry SDK and version context. Prove the browser query behavior in MD5.

These are candidate tool pins, not claims that AnyInfer has already built with them.
Resolve transitive dependencies into committed lockfiles during MD1. A changed direct
pin requires a primary-source compatibility check and an in-place `> NOTE:`.

## Target files, data flow, and ownership boundaries

Use this layout; omit a helper only if its responsibility stays explicit elsewhere.

```text
docs/                              # existing shared prose, assets, task guides
  python/                          # authored Python-specific pages and API shells
    api/
  csharp/                          # authored C# guide, migration notes, semantics
website/
  package.json
  package-lock.json
  .nvmrc                           # 24
  .config/dotnet-tools.json         # local docfx pin
  requirements.in                  # build-only Python extraction dependencies
  requirements.lock               # reproducible resolved extraction environment
  docusaurus.config.ts
  tsconfig.json
  sdks.json                        # source dirs, IDs, labels, status/version sources
  navigation.json                  # one curated sidebar/export-order authority
  redirects.json                  # explicit static route/fragment compatibility
  docfx.json                      # metadata generation only; single AnyInfer library
  plugins/site-manifest.ts         # actual built routes, docs metadata, version context
  src/pages/index.tsx              # branded landing page, composed from source content
  src/theme/SearchBar/index.tsx    # browser-only local search adapter
  src/components/                 # landing/content helpers; minimal theme wrapping
  src/css/custom.css
  static/CNAME                     # anyinfer.dev
  static/.nojekyll
  .generated/                      # ignored prepared docs, API maps, metadata, copied assets
    home.mdx                       # prepared docs/index.md content imported by root TSX page
  shared_versioned_docs/          # only if shared docs are versioned in the future
  python_versioned_docs/          # actual snapshots only when Python is versioned
  csharp_versioned_docs/          # actual snapshots only when C# is versioned
  python_versions.json            # created with the first real Python snapshot
  csharp_versions.json            # created with the first real C# snapshot
  python_versioned_sidebars/       # corresponding generated snapshot navigation
  csharp_versioned_sidebars/
scripts/
  build_docs.py                    # one pipeline entry point
  docs_common.py                   # metadata, navigation, route/symbol-map utilities
  prepare_docs.py                  # source staging, marker expansion, links/snippets
  generate_python_reference.py
  generate_csharp_reference.py
  export_docs.py                   # static redirects, body metadata, llms outputs
  check_docs_site.py               # final artifact invariants, routes, fragments, coverage
tests/
  test_docs_pipeline.py
  test_python_reference.py
  test_csharp_reference.py
  test_docs_site.py
  fixtures/docs_migration/         # small legacy route/anchor/symbol compatibility fixtures
website/tests/                    # production-artifact browser checks
```

Shared docs are unversioned initially, so do not create an empty shared version archive
just to match the illustrative layout. Use `shared` as the **explicit** plugin ID;
therefore any future shared version files must use the `shared_` prefix, not default
instance filenames. Python/C# version JSON and sidebars use their plugin ID prefixes.

Build order is fixed:

```text
source metadata + navigation + prose + native/Python source documentation
  -> Python reference and C# reference (one at a time for native build resources)
  -> prepared shared/Python/C# docs + API symbol maps
  -> Docusaurus static HTML and actual-route manifest
  -> redirects + article-only metadata + agent exports
  -> Pagefind index of canonical pages
  -> final artifact checks
  -> site/ uploaded to GitHub Pages
```

The route manifest is derived from Docusaurus's loaded content and final routes, not
from a hand-maintained duplicate of every public URL. It records SDK, version, status,
canonical route, authored source path, section/order, and API symbol destinations.
Never publish workstation paths or credentials. `navigation.json` supplies curated
ordering; the build rejects missing/duplicate source pages and contradictory metadata.

### Command contract to implement

All commands below run from the repository root unless their working directory is
explicitly `website/`. Use one Python orchestration entry point, not a shell chain.

| Command | Required behavior |
|---|---|
| `python scripts/build_docs.py build` | Complete strict production pipeline, including final artifact/browser gates |
| `python scripts/build_docs.py prepare` | Extract current API references and stage content/metadata without publishing |
| `python scripts/build_docs.py preview` | Prepare inputs, then start the local Docusaurus preview on `127.0.0.1`; forward supported preview arguments |
| `python scripts/build_docs.py snapshot --sdk python --version <outgoing-version>` | Validate the actual outgoing Python version, snapshot its prepared content/API maps through its docs plugin, and validate archived links |
| `python scripts/build_docs.py snapshot --sdk csharp --version <outgoing-version>` | Same operation for C#, without changing Python's history |
| `python scripts/check_docs_site.py --site site` | Validate the final artifact; no rebuild or dependency downloads |
| `npm run site:build` with cwd `website/` | Intermediate Docusaurus command: `docusaurus build --out-dir ../site` |
| `npm run search:index` with cwd `website/` | Intermediate Pagefind command: `pagefind --site ../site` |

Use installed local executables through npm scripts; never allow an unpinned `npx`
download during a build. Add a `website` browser-test npm script with pinned test
dependencies. Test Chromium installation is an explicit setup/CI step. Browser tests
serve the already-built files on loopback; they must not recursively invoke the full
build from their web-server fixture.

## Content and versioning rules

### Initial source moves and canonical destinations

Move files only during execution, preserving their content before targeted conversion.
Update repository-relative Markdown links, generated page templates, and source references
in the same phase. Keep shared task guides such as streaming and structured output in
`docs/guides/`; their supported-language examples remain on one task page.

| Existing source | New source | New canonical route |
|---|---|---|
| `docs/guides/python-sdk.md` | `docs/python/index.md` | `/python/` |
| `docs/guides/quickstart.md` | `docs/python/quickstart.md` | `/python/quickstart/` |
| `docs/guides/installation.md` | `docs/python/installation.md` | `/python/installation/` |
| `docs/reference/api/README.md` | `docs/python/api/README.md` | `/python/api/` |
| Other `docs/reference/api/*.md` | Same basename under `docs/python/api/` | `/python/api/<basename>/` |
| `docs/guides/csharp-sdk.md` | `docs/csharp/index.md` | `/csharp/` |
| `docs/guides/python-to-csharp.md` | `docs/csharp/migrating-from-python.md` | `/csharp/migrating-from-python/` |
| `docs/reference/csharp-sdk.md` | `docs/csharp/reference.md` | `/csharp/reference/` |
| Generated C# public types | Generated input only, no authored duplicate | `/csharp/api/<type-slug>/` |

Derive all old URLs from the MD0 build rather than assuming how MkDocs treated
`README.md`, index pages, or trailing slashes. Shared section indexes get explicit
slugs and `docs/README.md` stays the repository's GitHub-only table of contents.
`docs/index.md` remains the landing-page content source and is excluded from the shared
docs plugin to prevent a duplicate `/` route. `docs/downloads.md` remains a shared
published page at `/downloads/`, reachable from the header even if absent from a sidebar.

### SDK versions and future languages

- Configure each SDK's `current` docs at an empty version subpath, resulting in
  `/python/...` and `/csharp/...`. Labels come from the corresponding package metadata.
- Historical snapshots use their SDK's version subpath, e.g.
  `/python/<actual-version>/...`; do not create examples of historical versions in the
  production tree. Keep version identifiers in the SDK's own namespace.
- At a real release transition, snapshot the outgoing SDK's prepared prose **and
  generated API Markdown**, including its version/source receipt and symbol map.
  Archives must not re-render their reference from current source. A snapshot workflow
  is explicit release work, not a side effect of every docs build.
- Snapshot preparation must rewrite current-route links through that snapshot's route
  map, not retain absolute links back to the moving current SDK reference. Preserve
  symbols and source attribution in a checked-in per-snapshot receipt. Rebuilds may
  resolve those stored destinations but may not replace their content with HEAD.
- Prefer same-version links inside an SDK snapshot. Links to shared docs deliberately
  target the current shared section and are described as such in contributor guidance.
  Shared pages must qualify Python-only behavior and native implementation differences.
- Expose SDK selection and clearly identified independent version controls. Switching
  SDKs must not imply that the same package version exists in both. Keep C# prerelease
  status visible on its guide/reference and search results.
- Future SDK registration requires an ID, source directory, version/status source,
  navigation entries, generator adapter/symbol map, and the same artifact tests.
  Do not create empty third-language sections or guess which language comes next.

## Execution checklist

### MD0 — Freeze the behavior being replaced

- [ ] **MD0.A — Capture a real legacy baseline.** Before removing MkDocs, run its
  existing strict build through `python workspace.py build docs`. Record the commit
  and dirty-source status, canonical routes, current redirect targets, referenced
  fragments/API anchors, public Python symbol inventory, snippets, top-level nav order,
  agent-export filenames, and representative page metadata. Store compact generated
  expectations under `tests/fixtures/docs_migration/`; do not commit the whole rendered
  site. Include home, downloads, section indexes, client/context/error/add-on references,
  C# guidance, Mermaid, tabs, admonitions, and source snippets. If the current tree fails
  the baseline build, identify the existing failure explicitly before treating it as a
  migration regression. **Test gate:** inspect the strict-build exit status and validate
  every baseline route/fragment against the actual generated HTML.

- [ ] **MD0.B — Establish route and navigation authority.** Create `website/sdks.json`,
  `website/navigation.json`, and `website/redirects.json` from the source moves above,
  current nav, and every existing `REDIRECTS` entry. Use explicit shared/Python/C# IDs;
  include non-sidebar public pages such as downloads in the route inventory. Preserve
  shared/legacy agent section filenames, including `llms/reference.txt`, while adding
  SDK-specific sections where required. Add schema/uniqueness checks in
  `tests/test_docs_pipeline.py`. Do not hard-code current provider/export/page counts.
  **Test gate:** `python -m pytest tests/test_docs_pipeline.py -q`, proving complete
  source classification, unique routes, and coverage of every legacy redirect.

### MD1 — Prove and pin the static toolchain

- [ ] **MD1.A — Scaffold the build-only toolchain.** Add the `website/` package/config
  files, `.nvmrc` containing `24`, and a committed npm lockfile. Pin Docusaurus core,
  classic preset/theme, docs plugin, and Mermaid theme to `3.10.2`; use `pagefind` `1.5.2`.
  Resolve compatible React/TypeScript/browser-test peers from published manifests and
  pin them in the lockfile rather than inventing versions. Start Python extraction
  with `griffe2md==1.5.0` in `website/requirements.in`; resolve Griffe and its dependencies
  into `requirements.lock`, then verify the documented API against those installed
  versions. Pin `docfx` `2.81.0` in `website/.config/dotnet-tools.json`. Retain the native
  SDK selected by `src/csharp/global.json`. Add generated/cache/module exclusions to
  `.gitignore`; do not alter wheel dependencies. **Test gate:** clean `npm --prefix website
  ci`, locked Python requirements installation, `dotnet tool restore --tool-manifest
  website/.config/dotnet-tools.json`, and recorded successful version/API checks.

- [ ] **MD1.B — Build a representative static site before converting the corpus.**
  Configure `url: 'https://anyinfer.dev'`, `baseUrl: '/'`, `trailingSlash: true`,
  `markdown: {format: 'detect', mermaid: true}`, `onBrokenLinks: 'throw'`, and Markdown
  link/image hooks that throw. Disable the blog, avoid a duplicate default docs plugin,
  configure all three explicit docs instances, and build to root `site/`. Add
  `static/CNAME` containing `anyinfer.dev` and an empty `.nojekyll`. Prove `.md` and `.mdx`
  handling using angle brackets, braces, raw HTML, generic signatures, code fences,
  tabs, details/admonitions, tables, and Mermaid. Accept CommonMark mode only after
  these cases render correctly; any parser adjustment must retain this gate.
  **Test gate:** the locked Docusaurus build succeeds and a plain static file server
  serves direct nested URLs and the representative content without a Node server.

### MD2 — Replace both API-reference renderers

MD2.P and MD2.C may run concurrently after MD1 if file ownership is disjoint. They
must not both edit manifests, dependencies, `workspace.py`, or this checklist at once.

- [ ] **MD2.P — Generate the complete Python reference.** Own
  `scripts/generate_python_reference.py` and `tests/test_python_reference.py`. Replace
  each legacy symbol directive in its authored API shell with
  `<!-- anyinfer-api: qualified.symbol -->`; these markers are the topic/grouping
  authority, not another manually enumerated export list. Retain any per-directive
  member options in structured marker metadata, with fixtures for the observed cases.
  Load documented roots with Griffe, configure Google docstrings on the loader,
  resolve aliases, and render selected objects with `griffe2md.render_object_docs`.
  Match source ordering, signatures/annotations, constructor merging, root headings,
  no source listing, and the current inherited-member policy. Include all
  `_PUBLIC_SURFACES`, `_PUBLIC_EXTRA_SYMBOLS`, and documented add-on modules such as
  `anyinfer_store`, `anyinfer_shared`, and `anyinfer_confidential` where currently
  exposed. Preserve constant/type-alias documentation and re-export identities.
  Emit a deterministic qualified-symbol -> route/anchor map, retaining old Python
  anchors where possible. Fail on missing/ambiguous symbols, unresolved internal
  references, duplicate anchors, or forbidden public text. **Test gate:**
  `python -m pytest tests/test_python_reference.py -q`, comparing the legacy symbol
  baseline and current public exports, plus a rendered client/add-on reference smoke.

- [ ] **MD2.C — Generate the public C# reference.** Own
  `scripts/generate_csharp_reference.py`, `website/docfx.json`, and
  `tests/test_csharp_reference.py`. Enable XML documentation specifically for
  `src/csharp/AnyInfer/AnyInfer.csproj`, preferably through documentation-build
  properties first; do not enable warnings/errors across unrelated proof projects.
  Preserve warnings-as-errors and explicitly handle missing public XML documentation;
  do not silence it with a blanket `NoWarn=1591`. Restore/build the library in Release
  with documentation emission, then run the local DocFX metadata command on its
  project or DLL/XML inputs. Read version/assembly identities from evaluated build
  metadata. Start with `outputFormat: 'markdown'`, normalize links/front matter, and
  produce one page per public type, with namespace navigation. Exclude internal
  members and test/probe/conformance assemblies. Preserve summaries, parameters,
  returns, exceptions, enum values, properties, overloads, generic signatures,
  inheritance/inheritdoc, and XML `see`/`seealso` references.

  Type slug rule: lowercase the full type UID, replace runs of non-ASCII-alphanumeric
  characters with `-`, and trim boundary `-`; reject collisions. Member anchor rule:
  `cs-` plus the first 16 lowercase hex digits of SHA-256 over the full UTF-8 DocFX UID;
  reject collisions. Keep full UIDs and readable signatures in the symbol map.

  If Markdown output cannot preserve the required structure/links, record the failing
  examples and use the **same pinned DocFX extractor** with `mref` output plus a bounded
  deterministic YAML-to-Markdown renderer. Add only a build-time YAML dependency if
  that fallback is needed. Do not broaden this into a general documentation framework.
  If neither path passes, leave this box open; do not ship a partial C# reference as
  success. Restore NuGet/tool dependencies explicitly before extraction; this gate
  requires local generation without provider calls, not a network-free clean restore.
  **Test gate:** `python -m pytest tests/test_csharp_reference.py -q` and a real local
  native extraction after dependency restoration, covering
  `AsyncClient.GenerateAsync` overloads,
  `Client.Generate`, `Task<IReadOnlyList<DiscoveredModel>>`, `ValueTask DisposeAsync`,
  `IAsyncEnumerable<StreamEvent>`, records/enums, and resolved internal XML links.

### MD3 — Migrate source content, navigation, and appearance

- [ ] **MD3.A — Implement deterministic preparation and move SDK prose.** Own
  `scripts/prepare_docs.py`, `scripts/docs_common.py`, authored `docs/` moves, and
  shared pipeline tests. Apply the source-move table and update relative links across
  the repository, including README, canonical procedures, generated templates, and
  executable example references. Convert Material tabs to Docusaurus Tabs/TabItem MDX
  only where interaction is required; convert admonitions/details and attribute-list
  formatting to supported syntax. Preserve fenced examples and explicit legacy IDs.
  Expand source snippets from their existing files, never by pasting duplicate C#
  examples; missing snippets/regions are errors. Replace version placeholders from
  generated metadata. Stage into `website/.generated/{shared,python,csharp}/` with
  explicit IDs/slugs/edit URLs pointing to authored files, not the staging directory.
  Emit converted homepage prose separately as `website/.generated/home.mdx`; it is
  imported by `website/src/pages/index.tsx`, not registered as a shared docs page.
  Resolve source-relative links through the page/symbol maps, respecting same-version
  SDK links and shared-current links. Do not rewrite prose/code using global regexes
  that also alter fenced examples. **Test gate:**
  `python -m pytest tests/test_docs_pipeline.py tests/test_docs_examples.py -q`, source
  link checks, and a full candidate site build with no unexpanded directives, snippets,
  version placeholders, missing pages, duplicate routes, or broken internal links.

- [ ] **MD3.B — Port the branded UI and actual-route manifest.** Own Docusaurus
  config, `website/plugins/site-manifest.ts`, landing components, and CSS. Use
  `navigation.json` for sidebars and export ordering. Expose shared docs, SDK entry
  points, supported task guides, SDK version controls, and downloads. Compose the
  homepage by importing the generated `website/.generated/home.mdx` component into
  `website/src/pages/index.tsx`, alongside the branded UI components; do not retain
  a second prose copy in TSX. Reuse artwork from `docs/assets/` through generated
  static inputs and retain its `/assets/...` URLs. Map brand constants to Docusaurus theme variables, preserve
  code readability, and self-host any web fonts used by the site. Port the header's
  release/download metadata, accessible mobile navigation, SVG favicon, 404 page,
  canonical URLs, per-page titles/descriptions, and Open Graph/Twitter social cards.
  Generate the route manifest from actual plugin content/routes, including the
  homepage/downloads and versioned SDK pages. **Test gate:** production-artifact
  browser checks at desktop and mobile widths in light/dark mode; direct-link refresh,
  keyboard navigation, copy buttons, tabs, Mermaid, and page metadata all pass. A
  fixture edit to `docs/index.md` changes rendered `/` content without creating a
  second shared-plugin root route.

### MD4 — Preserve redirects, agent exports, and artifact integrity

- [ ] **MD4.A — Port hooks as explicit post-build operations.** Own
  `scripts/export_docs.py` and export/redirect tests. Replace the hook lifecycle with
  deterministic inputs: metadata, navigation, actual routes, and final rendered
  article content. Generate `llms.txt`, `llms-full.txt`, and section bundles, including
  complete rendered Python/C# API signatures and descriptions. Preserve existing
  bundle paths; add SDK bundles and split oversized reference sections into linked
  children rather than raising the 800,000-byte per-bundle limit. Keep
  `llms/reference.txt` as the shared-reference bundle with links to the Python/C#
  reference bundles if the former aggregate no longer fits. Attribute shared/Python/C#
  versions separately (shared prose is current/unversioned and attributed to its
  source revision), include add-on versions where applicable, and include source
  revision plus dirty status without embedding a wall-clock timestamp. Root exports
  contain current documentation once; historical SDK snapshots get their own scoped
  exports and are not mixed into the current full-text bundle. Exclude sidebar/search
  chrome, redirects, and script/style content. Fail on missing/empty expected bodies
  and internal decision identifiers.

  Generate static redirect HTML with canonical/social tags, meta refresh, and a usable
  fallback link; add a same-origin script for retaining incoming fragments where
  appropriate. Preserve explicit fragment remaps from old redirects and resolve
  redirect chains to one final canonical destination. Fail on source/canonical route
  collisions, cycles, nonexistent targets, or missing target anchors. Exclude redirects
  from search, sitemap, and text corpora. **Test gate:**
  `python -m pytest tests/test_docs_site.py -q`, proving every baseline route still
  works or redirects correctly, exported API text is substantive, version attribution
  is accurate, and 800,000-byte limits hold for all individual section bundles.

- [ ] **MD4.B — Add a final static-artifact validator.** Own
  `scripts/check_docs_site.py` and the relevant site tests. Walk final HTML, route
  metadata, assets, redirects, and text exports. Verify local links, decoded fragments,
  unique generated anchors, all current public-symbol destinations, metadata/canonical
  URLs, CNAME, 404, downloads, expected social assets, export completeness, and absence
  of leaked workstation paths or unsupported SDK claims. Compare legacy anchor
  fixtures; preserve incoming fragments by explicit compatibility anchors when needed.
  Use built HTML as fragment authority rather than assuming Markdown slug algorithms
  are identical. Test failure propagation by deliberately removing one symbol target,
  one snippet, and one asset in isolated fixture builds. **Test gate:**
  `python scripts/check_docs_site.py --site site` succeeds on the candidate artifact,
  and each deliberately damaged fixture fails with an actionable diagnostic.

### MD5 — Add local search and prove independent versions

- [ ] **MD5.A — Index final canonical HTML and add local search.** Own the Pagefind
  build/configuration and `website/src/theme/SearchBar/index.tsx`. Mark only readable
  article bodies for indexing; include the landing/downloads pages intentionally.
  Stamp metadata from the actual-route manifest, not from guesses about URL segments.
  Index SDK, SDK version, support status, title, and canonical destination. Use a
  composite `scope` filter, with values `shared`, `python:<version>`, and
  `csharp:<version>`. From an SDK page, search shared docs plus that SDK's selected
  version by default; let the reader select all current SDKs or archived content.
  Validate Pagefind's OR-filter behavior for these composite scopes rather than
  combining separate SDK/version filters that accidentally exclude shared pages.
  Load `/pagefind/` only in the browser, with SSR-safe initialization and cleanup on
  client navigation. Provide labelled search controls, keyboard open/close, focus
  restoration, loading/empty/error states, and useful SDK/version labels on results.
  Search is tested on a **production** build, not assumed to work in the dev server.
  **Test gate:** browser searches find a shared concept, a Python symbol, and a C#
  overload; SDK/version filters work; network interception proves search makes no
  third-party requests and all requested index/WASM files exist in `site/`.

- [ ] **MD5.B — Prove independent snapshot behavior without publishing fake history.**
  In an isolated test copy, snapshot one SDK's prepared docs/reference at a fixture
  version, change a current-only API description, and rebuild. Assert the archive
  retains its original text, anchors, symbol map, and version attribution; the other
  SDK's routes and selected version do not change. Prove version navigation,
  same-version API links, search filtering, and scoped agent exports on both direct
  loads and client navigation. Store only small fixtures/tests, not fictitious
  production release archives. Document exact per-instance snapshot commands and
  their ordering around an actual SDK release. **Test gate:** the independent-version
  browser/integration tests pass for both SDKs, and the normal artifact contains only
  actual current or deliberately retained real versions.

### MD6 — Integrate workspace commands, CI, and packaging

- [ ] **MD6.A — Make workspace commands use one complete pipeline.** Own
  `scripts/build_docs.py`, coordinated edits to `workspace.py`, and
  `tests/test_workspace.py`. Preserve `python workspace.py build docs`,
  `python workspace.py docs`, `python workspace.py check --only=docs-check`, and
  `--only=docs-build`. `_build_docs_site` must invoke the complete extraction ->
  preparation -> Docusaurus -> export -> Pagefind -> validation pipeline and propagate
  failures from every stage. The preview command must prepare content and explain
  that final search validation requires a production build. Replace directive
  discovery with marker/symbol-map discovery while retaining public export, alias,
  member-docstring, constant-docstring, and public-text checks. Keep docs-check useful
  before Node/native compilation; validate final rendered coverage in docs-build.
  Update setup/tool diagnostics and help text for locked Node/Python/DocFX prerequisites;
  do not silently install/download tools on every build. Resolve `npm.cmd` correctly on
  Windows, use subprocess argument arrays, retain current-interpreter Python behavior,
  and invoke native commands from the directory governed by `src/csharp/global.json`.
  **Test gate:** `python -m pytest tests/test_workspace.py tests/test_docs_pipeline.py -q`;
  `workspace build docs` and the `docs-build` check phase invoke the same complete
  strict production pipeline, including negative tests for missing tools and failing
  post-build stages. Separately prove `workspace docs` prepares content and invokes
  `docusaurus start` on loopback, without claiming production-search validation.

- [ ] **MD6.B — Install build prerequisites in the correct CI jobs.** Coordinate
  `.github/workflows/ci.yml` and `.github/workflows/docs-site.yml`. Add SHA-pinned
  setup-node with the checked-in Node version/lockfile, and move or add the existing
  SHA-pinned setup-dotnet step **before** docs-build wherever C# extraction runs.
  Use `src/csharp/global.json`; restore the local DocFX tool and locked Python/npm
  dependencies explicitly. Avoid adding Node/.NET tooling to Python-only test matrix
  jobs that do not build documentation. Preserve editable shard installation where
  coverage/examples require it; do not delete extras merely because extraction is
  static. Cache dependencies against their actual lockfiles and native project inputs.
  Keep source changes under `scripts/`, `website/` executable/configuration files,
  lockfiles, native docs-build settings, and CI classified as code for the full gates;
  prose-only `docs/` edits may retain the existing fast classification. Preserve
  `ci-ok` and current workflow triggers/deployment safeguards. Upload root `site/` with
  the existing SHA-pinned Pages actions, not a parallel deployment system.
  **Test gate:** inspect the effective job step order and classification tests; a clean
  Linux build produces the same checked artifact through the workspace command used
  locally, and a Windows smoke proves command/path handling without concurrent heavy suites.

- [ ] **MD6.C — Keep distributions and developer setup coherent.** Update
  `pyproject.toml` build/dev/sdist configuration and related package tests. The Python
  wheel must not gain documentation tooling. Keep the sdist's documented scope as a
  Python source distribution; include authored docs and necessary source snippets,
  but do not silently turn it into a complete .NET checkout. Document that the full
  multi-SDK site build requires a repository checkout and the docs toolchains; provide
  an actionable failure if invoked from an incomplete sdist tree. Exclude
  `node_modules`, `.generated`, `.docusaurus`, `site`, native binaries, and caches from
  packages. Retain `markdown` wherever the demo/runtime still uses it. Remove
  MkDocs/Material/mkdocstrings dependencies only after the replacement gates pass.
  **Test gate:** inspect built wheel/sdist contents with the existing packaging checks,
  verify the declared sdist limitation, and confirm importing/installing the SDK has
  no Node, DocFX, Griffe, or documentation-server requirement.

### MD7 — Update contributor guidance and retire MkDocs

- [ ] **MD7.A — Reconcile every documentation/instruction surface.** Update
  `docs/contributing/{README,releasing,branding,testing}.md`, `docs/guides/coding-agents.md`,
  `docs/agents/INTEGRATION.md`, root contributor/setup guidance, `AGENTS.md`, and
  relevant `DESIGN.md` docs/build descriptions. Update canonical provider procedures,
  especially `contracts/NEW-PROVIDER.md`, to name the new navigation authority instead
  of `mkdocs.yml`; entry-point shims continue to defer to their canonical procedures.
  Adapt `tests/test_agent_instructions.py` to those paths rather than dropping the
  procedure assertions. Explain source editing, API markers/generation, adding a
  future SDK, version snapshots, static local search, required tools, preview versus
  production build, and Pages publication. Preserve canonical integration source
  authority and regenerated outward instruction/version guarantees. Keep docs free of
  links to this ephemeral plan. **Test gate:**
  `python -m pytest tests/test_agent_instructions.py tests/test_docs_examples.py -q`,
  `python workspace.py check --only=docs-check`, and a repository search proving no
  current contributor command/procedure still points to removed MkDocs inputs.

- [ ] **MD7.B — Remove the old publisher after parity gates.** Delete `mkdocs.yml`,
  `scripts/mkdocs_hooks.py`, and obsolete Material `overrides/` only after MD0-MD7.A
  pass. Retain useful brand art and re-home any still-needed styles. Remove obsolete
  dependency entries, sdist inclusions, comments, and tests that specifically assume
  MkDocs; keep meaningful legacy compatibility fixtures. Do not remove canonical
  Python Markdown/runtime dependencies by association. Keep historical changelog
  mentions and migration fixtures clearly historical rather than rewriting history.
  **Test gate:** the replacement production build, route/anchor baseline checks,
  API-coverage checks, search/version browser tests, and package-content checks all
  pass with MkDocs tooling absent from a clean documentation environment.

### MD8 — Final acceptance, cutover, and recovery

- [ ] **MD8.A — Run the final gate and review the exact artifact.** Re-read this plan
  and reconcile every preceding box with the work. Run `python workspace.py check`
  once as the final repository gate, including native/package checks; do not run heavy
  suites concurrently. Ensure the browser acceptance suite and final static-artifact
  validator are invoked by the docs-build pipeline, so Pages cannot publish an artifact
  those checks did not cover. Review home, downloads, shared/task/provider docs,
  Python/C# guides, both generated references, legacy deep links, search, independent
  versions, exports, social metadata, and mobile/light/dark behavior. Record the tested
  source revision and artifact receipt. **Test gate:** the complete workspace gate
  passes and the exact `site/` artifact intended for Pages passes browser and artifact checks.

- [ ] **MD8.B — Cut over through the existing branch/release process.** Once execution
  and publication are authorized, use the repository's feature -> develop -> main
  process and the existing Pages workflow. Preserve the already-working domain/DNS
  configuration; no new service or billing setup is part of this migration. After
  deployment, perform bounded public smoke checks of the homepage, one shared page,
  one reference page per SDK, an old redirect with a fragment, local search, downloads,
  `llms.txt`, and a section bundle. Retain the prior working Pages artifact/deployment
  receipt for recovery. Roll back by redeploying that artifact or by a reviewed revert
  of the migration and a normal Pages rebuild; never rewrite Git history or reset
  unrelated SDK work. **Test gate:** the public static smoke passes at `anyinfer.dev`
  and the tested recovery procedure identifies a concrete prior artifact/revision.

## Delegation and execution notes

- Coordinator owns decisions, shared metadata/navigation, dependency manifests,
  workspace/CI integration, final gates, Git, and the checklist reconciliation.
- Safe parallel work after MD1: Python API generator/tests (MD2.P) and C# generator/tests
  (MD2.C). A UI worker may separately own the components/styles in MD3.B once the
  content/route contract is fixed. Shared manifest/config edits remain serialized.
- Every worker receives the full relevant box, exact owned files, constraints, test
  command, and expected report. Workers are not alone in the tree, must preserve others'
  changes, and never modify Git state. Coordinate plan updates to avoid shared-file races.
- Expensive native/build/browser gates run one at a time. Prefer narrow parser/route/API
  tests while iterating and the complete repository gate once at final acceptance.
- When pausing execution, append the exact first unchecked box, last completed/tested
  commit or dirty-source receipt, and any outstanding failure. Do not mark partial work
  complete. Retire this plan after the migration is accepted and durable guidance lives
  in contributor documentation.

> NOTE: Planning produced this file only. No candidate generator or Docusaurus build
> was installed or run, no source content was moved, and no deployment was changed.
> Initial resume point: **MD0.A**; planning baseline checkout is
> `117a0d80ed4f48a6968250ad6956f1ca681429a4` with pre-existing working-tree changes.
