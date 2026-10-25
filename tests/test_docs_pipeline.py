"""Focused tests for the source-to-Docusaurus preparation boundary."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.docs_common import Page, build_pages, load_navigation
from scripts.prepare_docs import (
    _cached_reference_renderer,
    _prepare_markdown,
    _rewrite_generated_references,
    _symbol_urls,
    prepare,
)


def _root(tmp_path: Path) -> Path:
    (tmp_path / "docs" / "guides").mkdir(parents=True)
    (tmp_path / "docs" / "reference" / "api").mkdir(parents=True)
    (tmp_path / "docs" / "reference").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "assets").mkdir(parents=True)
    (tmp_path / "examples" / "csharp-sdk").mkdir(parents=True)
    (tmp_path / "website").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    props = tmp_path / "src" / "csharp" / "Directory.Build.props"
    props.parent.mkdir(parents=True)
    props.write_text(
        "<Project><PropertyGroup><Version>4.5.6-proof</Version></PropertyGroup></Project>",
        encoding="utf-8",
    )
    (tmp_path / "website" / "navigation.json").write_text(
        json.dumps(
            [
                {"Home": "index.md"},
                {
                    "Integrate": [
                        {"Python": "guides/python-sdk.md"},
                        {"C#": "guides/csharp-sdk.md"},
                    ]
                },
                {
                    "Reference": [
                        {
                            "API": [
                                "reference/api/README.md",
                                {"Client": "reference/api/client.md"},
                            ]
                        },
                        {"C# ref": "reference/csharp-sdk.md"},
                    ]
                },
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "docs" / "index.md").write_text(
        "# Home\n\n{{ extra.anyinfer_version }}\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "downloads.md").write_text("# Downloads\n", encoding="utf-8")
    (tmp_path / "docs" / "guides" / "python-sdk.md").write_text("# Python\n", encoding="utf-8")
    (tmp_path / "docs" / "guides" / "csharp-sdk.md").write_text(
        '# C#\n\n--8<-- "examples/csharp-sdk/Sample.cs"\n', encoding="utf-8"
    )
    (tmp_path / "docs" / "reference" / "csharp-sdk.md").write_text(
        "# C# reference\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "reference" / "api" / "README.md").write_text("# API\n", encoding="utf-8")
    (tmp_path / "docs" / "reference" / "api" / "client.md").write_text(
        "# Client\n\n[Python](../../guides/python-sdk.md#start)\n\n::: anyinfer.Client\n",
        encoding="utf-8",
    )
    (tmp_path / "examples" / "csharp-sdk" / "Sample.cs").write_text(
        "var value = 1;\n", encoding="utf-8"
    )
    binary = tmp_path / "examples" / "csharp-sdk" / "bin"
    binary.mkdir()
    (binary / "private.dll").write_bytes(b"not a documentation asset")
    return tmp_path


def test_page_metadata_keeps_source_paths_and_assigns_sdk_routes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    pages = build_pages(root / "docs", load_navigation(root / "website" / "navigation.json"))
    by_source = {page.source: page for page in pages}

    assert by_source["index.md"].id == "home"
    assert by_source["index.md"].url == "/"
    assert by_source["guides/python-sdk.md"].url == "/python/"
    assert by_source["guides/csharp-sdk.md"].url == "/csharp/"
    assert by_source["reference/api/client.md"].slug == "/api/client/"
    assert by_source["reference/api/README.md"].title == "API"
    assert by_source["reference/csharp-sdk.md"].url == "/csharp/reference/"
    assert by_source["downloads.md"].section == "Home"


def test_prepare_stages_original_paths_and_expands_stateful_markers(tmp_path: Path) -> None:
    root = _root(tmp_path)
    source = root / "docs" / "guides" / "python-sdk.md"
    source.write_text(
        '# Python\n\n!!! tip "Keep it"\n\n    Details\n\n??? note "More"\n\n    Expanded\n\n=== "Sync"\n\n    ```python\n    pass\n    ```\n\n=== "Async"\n\n    ```python\n    await run()\n    ```\n',
        encoding="utf-8",
    )
    manifest = prepare(root, renderer=lambda symbol: f"## {symbol}\n")
    generated = root / "website" / ".generated"
    staged_python = (generated / "python" / "guides" / "python-sdk.mdx").read_text(
        encoding="utf-8"
    )
    staged_client = (generated / "python" / "reference" / "api" / "client.md").read_text(
        encoding="utf-8"
    )
    staged_csharp = (generated / "csharp" / "guides" / "csharp-sdk.md").read_text(encoding="utf-8")

    assert "slug: /" in staged_python
    assert ":::tip Keep it" in staged_python and ":::" in staged_python
    assert "<details>" in staged_python and "<summary>More</summary>" in staged_python
    assert staged_python.count("<Tabs>") == 1 and staged_python.count("<TabItem") == 2
    assert "## anyinfer.Client" in staged_client and "::: anyinfer.Client" not in staged_client
    assert "(/python/#start)" in staged_client
    assert "```csharp\nvar value = 1;\n```" in staged_csharp
    assert "1.2.3" in (generated / "home.mdx").read_text(encoding="utf-8")
    assert (generated / "static" / "examples" / "csharp-sdk" / "Sample.cs").is_file()
    assert not (generated / "static" / "examples" / "csharp-sdk" / "bin" / "private.dll").exists()
    assert manifest["versions"] == {"python": "1.2.3", "csharp": "4.5.6-proof", "addons": {}}


@pytest.mark.parametrize(
    ("header", "hidden"),
    [
        ("hide:\n  - toc\n", True),
        ("hide_table_of_contents: true\n", True),
        ("hide:\n  - navigation\n", False),
        ("hide_table_of_contents: false\n", False),
    ],
)
def test_prepare_preserves_authored_toc_visibility(
    tmp_path: Path, header: str, hidden: bool
) -> None:
    root = _root(tmp_path)
    (root / "docs" / "downloads.md").write_text(
        f"---\n{header}---\n\n# Downloads\n\n## Options\n", encoding="utf-8"
    )
    prepare(root, renderer=lambda symbol: f"## {symbol}\n")
    staged = (root / "website" / ".generated" / "shared" / "downloads.md").read_text(
        encoding="utf-8"
    )
    assert ("hide_table_of_contents: true" in staged) is hidden
    assert "## Options" in staged


def test_prepare_rejects_missing_snippets_and_api_directive_leaks(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "docs" / "guides" / "python-sdk.md").write_text(
        '--8<-- "missing.cs"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="does not exist"):
        prepare(root, renderer=lambda symbol: symbol)

    (root / "docs" / "guides" / "python-sdk.md").write_text("# okay\n", encoding="utf-8")
    with pytest.raises(ValueError, match="left a directive"):
        prepare(root, renderer=lambda symbol: f"::: {symbol}\n")


def test_prepare_expands_a_snippet_inside_an_existing_fence_without_nesting(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    (root / "docs" / "guides" / "csharp-sdk.md").write_text(
        '```csharp\n--8<-- "examples/csharp-sdk/Sample.cs"\n```\n', encoding="utf-8"
    )
    prepare(root, renderer=lambda symbol: symbol)
    staged = (root / "website" / ".generated" / "csharp" / "guides" / "csharp-sdk.md").read_text(
        encoding="utf-8"
    )
    assert staged.count("```csharp") == 1
    assert "```csharp\nvar value = 1;\n```" in staged


def test_real_material_heading_and_downloads_syntax_becomes_safe_mdx() -> None:
    repository = Path(__file__).parents[1]
    page = Page(
        "reference/errors.md",
        "shared",
        "reference/errors",
        "/reference/errors/",
        "/reference/errors/",
        "Errors",
        "Reference",
        0,
    )
    errors = _prepare_markdown(
        (repository / "docs" / "reference" / "errors.md").read_text(encoding="utf-8"),
        page,
        {page.source: page},
        repository,
        lambda symbol: symbol,
    )
    downloads = _prepare_markdown(
        (repository / "docs" / "downloads.md").read_text(encoding="utf-8"),
        Page(
            "downloads.md",
            "shared",
            "downloads",
            "/downloads/",
            "/downloads/",
            "Downloads",
            "Home",
            0,
        ),
        {
            "serve/README.md": Page(
                "serve/README.md",
                "shared",
                "serve/README",
                "/serve/",
                "/serve/",
                "Sidecar",
                "Integrate",
                1,
            )
        },
        repository,
        lambda symbol: symbol,
    )

    assert ":material-" not in errors
    assert "⚠ (Not retryable; fix the configuration)" in errors
    assert '{ title="Not retryable' not in errors
    assert ":material-" not in downloads
    assert "{ .anyinfer-button" not in downloads
    assert 'className="anyinfer-card-grid anyinfer-download-grid"' in downloads
    assert downloads.count("releases/latest/download/") == 10
    assert (
        '<a className="anyinfer-button anyinfer-button-secondary" href="/serve/">Sidecar documentation →</a>'
        in downloads
    )


def test_mdx_escaping_preserves_code_but_escapes_prose_braces_and_pseudo_tags(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    page = Page(
        "guides/python-sdk.md",
        "python",
        "guides/python-sdk",
        "/",
        "/python/",
        "Python",
        "Integrate",
        0,
    )
    rendered = _prepare_markdown(
        'Outside {brace} and Type<T>.\n\n`{"literal": true}`\n',
        page,
        {page.source: page},
        root,
        lambda symbol: symbol,
    )

    assert "Outside \\{brace\\} and Type\\<T>." in rendered
    assert '`{"literal": true}`' in rendered


def test_default_renderer_cache_hits_and_source_change_invalidates(tmp_path: Path) -> None:
    root = tmp_path
    source = root / "src" / "python" / "anyinfer" / "public.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    renderer_source = root / "scripts" / "generate_python_reference.py"
    renderer_source.parent.mkdir()
    renderer_source.write_text("# renderer\n", encoding="utf-8")
    lock = root / "website" / "requirements.lock"
    lock.parent.mkdir()
    lock.write_text("renderer==1\n", encoding="utf-8")
    calls: list[tuple[str, dict[str, object] | None]] = []

    def render(qualified: str, options: dict[str, object] | None = None) -> str:
        calls.append((qualified, options))
        return f"# {qualified} {len(calls)}\n"

    cached = _cached_reference_renderer(root, render)
    assert cached("anyinfer.Client", {"members": ["generate"]}) == "# anyinfer.Client 1\n"
    assert cached("anyinfer.Client", {"members": ["generate"]}) == "# anyinfer.Client 1\n"
    assert calls == [("anyinfer.Client", {"members": ["generate"]})]

    source.write_text("VALUE = 2\n", encoding="utf-8")
    invalidated = _cached_reference_renderer(root, render)
    assert invalidated("anyinfer.Client", {"members": ["generate"]}) == "# anyinfer.Client 2\n"
    assert len(calls) == 2


def test_mdx_escaping_preserves_generated_html_anchors(tmp_path: Path) -> None:
    root = _root(tmp_path)
    page = Page(
        "guides/python-sdk.md",
        "python",
        "guides/python-sdk",
        "/",
        "/python/",
        "Python",
        "Integrate",
        0,
    )
    rendered = _prepare_markdown(
        '<a id="anyinfer.Client"></a>\n\nType<T>\n\n<https://anyinfer.dev/llms.txt>\n',
        page,
        {page.source: page},
        root,
        lambda symbol: symbol,
    )

    assert '<a id="anyinfer.Client"></a>' in rendered
    assert "Type\\<T>" in rendered
    assert "[https://anyinfer.dev/llms.txt](https://anyinfer.dev/llms.txt)" in rendered


def test_real_headings_keep_legacy_ids_and_tab_ids_attach_to_tab_items() -> None:
    repository = Path(__file__).parents[1]
    errors_page = Page(
        "reference/errors.md",
        "shared",
        "reference/errors",
        "/reference/errors/",
        "/reference/errors/",
        "Errors",
        "Reference",
        0,
    )
    errors = _prepare_markdown(
        (repository / "docs" / "reference" / "errors.md").read_text(encoding="utf-8"),
        errors_page,
        {errors_page.source: errors_page},
        repository,
        lambda symbol: symbol,
    )
    glossary_page = Page(
        "reference/glossary.md",
        "shared",
        "reference/glossary",
        "/reference/glossary/",
        "/reference/glossary/",
        "Glossary",
        "Reference",
        0,
    )
    glossary = _prepare_markdown(
        (repository / "docs" / "reference" / "glossary.md").read_text(encoding="utf-8"),
        glossary_page,
        {glossary_page.source: glossary_page},
        repository,
        lambda symbol: symbol,
    )
    tabbed = _prepare_markdown(
        '=== "One"\n\n    first\n\n=== "Two"\n\n    second\n',
        glossary_page,
        {glossary_page.source: glossary_page},
        repository,
        lambda symbol: symbol,
    )

    assert '<a id="confidentialexecutionerror"></a>' in errors
    assert '<a id="adapter"></a>\n\n#### Adapter' in glossary
    assert "{ #adapter }" not in glossary
    assert '<TabItem value="one" label="One">\n<a id="__tabbed_1_1"></a>' in tabbed
    assert '<TabItem value="two" label="Two">\n<a id="__tabbed_1_2"></a>' in tabbed


def test_generated_references_use_global_symbol_map_and_drop_unresolved_types() -> None:
    first = Page(
        "reference/api/one.md",
        "python",
        "reference/api/one",
        "/api/one/",
        "/python/api/one/",
        "One",
        "Reference",
        0,
    )
    second = Page(
        "reference/api/two.md",
        "python",
        "reference/api/two",
        "/api/two/",
        "/python/api/two/",
        "Two",
        "Reference",
        1,
    )
    symbols = _symbol_urls(
        [(first, '<a id="anyinfer.Sourced"></a>'), (second, '<a id="anyinfer.Client"></a>')]
    )
    rewritten = _rewrite_generated_references(
        "[Sourced](#anyinfer.types.capabilities.Sourced) [Client](#anyinfer.Client) "
        "[Exception](#Exception) [Callable](#Callable)",
        symbols,
    )

    assert "[Sourced](/python/api/one/#anyinfer.Sourced)" in rewritten
    assert "[Client](/python/api/two/#anyinfer.Client)" in rewritten
    assert rewritten.endswith(" Exception Callable")


def test_incremental_prepare_preserves_unchanged_files_updates_changes_and_removes_stale(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    asset = root / "docs" / "assets" / "logo.svg"
    asset.write_text("first", encoding="utf-8")
    prepare(root, renderer=lambda symbol: symbol)
    generated = root / "website" / ".generated"
    page = generated / "python" / "guides" / "python-sdk.md"
    copied_asset = generated / "static" / "assets" / "logo.svg"
    before_page_mtime = page.stat().st_mtime_ns
    before_asset_mtime = copied_asset.stat().st_mtime_ns

    time.sleep(0.02)
    prepare(root, renderer=lambda symbol: symbol, incremental=True)
    assert page.stat().st_mtime_ns == before_page_mtime
    assert copied_asset.stat().st_mtime_ns == before_asset_mtime

    stale = generated / "python" / "guides" / "python-sdk.mdx"
    stale.write_text("obsolete", encoding="utf-8")
    (root / "docs" / "guides" / "python-sdk.md").write_text("# Changed\n", encoding="utf-8")
    asset.write_text("second", encoding="utf-8")
    time.sleep(0.02)
    prepare(root, renderer=lambda symbol: symbol, incremental=True)

    assert "# Changed" in page.read_text(encoding="utf-8")
    assert copied_asset.read_text(encoding="utf-8") == "second"
    assert page.stat().st_mtime_ns != before_page_mtime
    assert copied_asset.stat().st_mtime_ns != before_asset_mtime
    assert not stale.exists()


def _generated_reference(*type_names: str) -> object:
    """Render a small generated C# reference with the real renderer's page shape."""
    from scripts.generate_csharp_reference import GeneratedPage, Reference

    pages = [
        GeneratedPage(
            uid="index",
            path="api/index.md",
            slug="/api/",
            url="/csharp/api/",
            title="C# API reference",
            label="Overview",
            namespace="",
            kind="index",
            origin=None,
            content="---\nslug: /api/\n---\n\n# C# API reference\n",
        )
    ]
    for name in type_names:
        slug = f"n.{name.lower()}"
        pages.append(
            GeneratedPage(
                uid=f"T:N.{name}",
                path=f"api/{slug}.md",
                slug=f"/api/{slug}/",
                url=f"/csharp/api/{slug}/",
                title=f"{name} class",
                label=name,
                namespace="N",
                kind="class",
                origin=f"src/csharp/AnyInfer/{name}.cs",
                content=f"---\nslug: /api/{slug}/\n---\n\n# {name} class\n",
            )
        )
    return Reference(
        tuple(pages),
        {f"T:N.{name}": f"/csharp/api/n.{name.lower()}/" for name in type_names},
        (("N", tuple(pages[1:])),),
    )


def test_prepare_stages_generated_csharp_pages_into_the_csharp_plugin_and_manifest(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    manifest = prepare(
        root,
        renderer=lambda symbol: symbol,
        csharp_reference=lambda _root: _generated_reference("Alpha"),
    )
    generated = root / "website" / ".generated" / "csharp" / "api"
    assert (generated / "index.md").is_file() and (generated / "n.alpha.md").is_file()
    entries = {page["url"]: page for page in manifest["pages"]}
    alpha = entries["/csharp/api/n.alpha/"]
    assert alpha["sdk"] == "csharp" and alpha["generated"] is True
    assert alpha["origin"] == "src/csharp/AnyInfer/Alpha.cs"
    assert alpha["order"] > max(
        page["order"] for page in manifest["pages"] if not page.get("generated")
    )
    section = manifest["generated"]["csharp-api"]
    assert section["sdk"] == "csharp" and section["index"] == "api/index"
    assert section["namespaces"] == [
        {"label": "N", "items": [{"id": "api/n.alpha", "label": "Alpha"}]}
    ]
    # Generated pages never become legacy redirects; authored routes are unchanged.
    assert all("/api/n." not in target for target in manifest["redirects"].values())


def test_incremental_prepare_removes_generated_pages_for_removed_types(tmp_path: Path) -> None:
    root = _root(tmp_path)
    prepare(
        root,
        renderer=lambda symbol: symbol,
        csharp_reference=lambda _root: _generated_reference("Alpha", "Beta"),
    )
    generated = root / "website" / ".generated" / "csharp" / "api"
    assert (generated / "n.beta.md").is_file()
    prepare(
        root,
        renderer=lambda symbol: symbol,
        incremental=True,
        csharp_reference=lambda _root: _generated_reference("Alpha"),
    )
    assert (generated / "n.alpha.md").is_file()
    assert not (generated / "n.beta.md").exists()


def test_docs_only_roots_without_docfx_configuration_skip_the_native_reference(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    manifest = prepare(root, renderer=lambda symbol: symbol)
    assert manifest["generated"] == {}
    assert not any(page.get("generated") for page in manifest["pages"])
