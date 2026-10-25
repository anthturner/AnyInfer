"""Render selected public Python symbols into Docusaurus-safe Markdown.

The documentation sources retain their ``::: qualified.symbol`` markers.  The staging
pipeline resolves those markers through :func:`render_symbol`, keeping the authored topic
grouping separate from the generated API text.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
"""Repository root, used to find every documented Python distribution."""

_SOURCE_ROOTS = (
    ROOT / "src" / "python",
    ROOT / "src" / "python" / "anyinfer-store" / "src",
    ROOT / "src" / "python" / "anyinfer-shared" / "src",
    ROOT / "src" / "python" / "anyinfer-confidential" / "src",
)

_LOADER_OPTIONS = frozenset({"docstring_style", "docstring_options", "search_paths"})
_HEADING = re.compile(r"^(#{1,6}\s+`([^`]+)`.*)$", re.MULTILINE)
_ADR_IDENTIFIER = re.compile(r"\bADR-\d{3}\b")

_DEFAULT_OPTIONS: dict[str, Any] = {
    "show_root_heading": True,
    "show_root_full_path": True,
    "show_root_members_full_path": True,
    "show_object_full_path": True,
    "show_source": False,
    "show_signature": True,
    "show_signature_annotations": True,
    "separate_signature": True,
    "merge_init_into_class": True,
    "members_order": "source",
    "inherited_members": False,
    "show_submodules": False,
    "filters": ["!^_(?!_)", "!^annotations$", "!^TYPE_CHECKING$"],
}


def render_symbol(qualified: str, options: dict[str, Any] | None = None) -> str:
    """Render one public symbol with stable, explicit anchors.

    Args:
        qualified: Import path recorded in an authored API marker, such as
            ``anyinfer.Client``.
        options: Optional griffe2md render options captured from that marker.  Options
            that select the parser or search path are ignored so every reference page
            uses the repository's Google-style source documentation.

    Returns:
        Ordinary Markdown suitable for inclusion in a Docusaurus ``.md`` document.

    Raises:
        ValueError: If ``qualified`` is empty, private, or cannot be resolved from the
            documented source distributions.
        RuntimeError: If the build-only Griffe renderer is unavailable.
    """
    _validate_qualified(qualified)
    try:
        import griffe
        from griffe2md import render_object_docs
    except ImportError as error:  # pragma: no cover - exercised by docs-environment setup
        raise RuntimeError(
            "Python API rendering requires website/requirements.lock; "
            "install it before building docs"
        ) from error

    render_options = dict(_DEFAULT_OPTIONS)
    if options:
        render_options.update(
            {key: value for key, value in options.items() if key not in _LOADER_OPTIONS}
        )
    # Source APIs are rendered as public surfaces even if an obsolete marker supplied a
    # permissive filter.  A reference shell must never turn private implementation names
    # into published documentation.
    render_options["filters"] = _public_filters(render_options.get("filters"))
    if isinstance(render_options.get("members"), (list, tuple)):
        render_options["members"] = [
            name
            for name in render_options["members"]
            if isinstance(name, str) and not _is_single_underscore_private(name)
        ]

    loader = _loader(griffe)
    try:
        obj = loader.modules_collection[qualified]
    except (KeyError, ModuleNotFoundError, ValueError):
        try:
            obj = loader.load(qualified)
        except (KeyError, ModuleNotFoundError, ValueError) as load_error:
            raise ValueError(
                f"documented Python symbol {qualified!r} could not be resolved"
            ) from load_error
    _resolve_aliases_for_root(loader, qualified)
    _restrict_module_members_to_exports(obj, render_options)

    rendered = render_object_docs(obj, render_options, format_md=False).strip()
    if not rendered:
        raise ValueError(f"documented Python symbol {qualified!r} rendered no Markdown")
    rendered = _explicit_anchors(rendered)
    _reject_forbidden_public_text(qualified, rendered)
    return rendered + "\n"


@lru_cache(maxsize=1)
def _loader(griffe: Any) -> Any:
    """Build one source loader for the complete marker-expansion pass."""
    return griffe.GriffeLoader(
        search_paths=[str(path) for path in _SOURCE_ROOTS if path.is_dir()],
        docstring_parser="google",
        allow_inspection=False,
    )


@lru_cache(maxsize=1)
def _resolved_roots() -> set[str]:
    """Retain distributions whose aliases are resolved by the cached loader."""
    return set()


def _resolve_aliases_for_root(loader: Any, qualified: str) -> None:
    """Resolve aliases when the cached loader first adds a distribution root."""
    root = qualified.partition(".")[0]
    resolved = _resolved_roots()
    if root not in resolved:
        loader.resolve_aliases(external=False)
        resolved.add(root)


def _validate_qualified(qualified: str) -> None:
    """Reject malformed and private API markers before asking Griffe to load them."""
    if not qualified or qualified.startswith("."):
        raise ValueError("a documented Python symbol must be an absolute import path")
    if any(
        not part or _is_single_underscore_private(part) for part in qualified.split(".")
    ):
        raise ValueError(f"documented Python symbol {qualified!r} is private or malformed")


def _is_single_underscore_private(name: str) -> bool:
    """Return whether a name is an implementation member rather than a magic method."""
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _public_filters(value: Any) -> list[str]:
    """Keep the configured public-member filter while removing private-member opt-ins."""
    values = list(value) if isinstance(value, (list, tuple)) else []
    return [
        item
        for item in values
        if isinstance(item, str) and not item.startswith("!^_")
    ] + ["!^_(?!_)", "!^annotations$", "!^TYPE_CHECKING$"]


def _restrict_module_members_to_exports(obj: Any, options: dict[str, Any]) -> None:
    """Render only a module's declared public API, not its implementation imports.

    Griffe's source-order traversal touches every imported alias before applying the
    normal public filter.  A standard-library alias such as ``math`` therefore attempts
    resolution even though it is neither documented nor exported.  A module's
    ``__all__`` is the repository's public boundary, so make it the renderer's member
    list unless an authored marker selected members explicitly.
    """
    if options.get("members") is not None or getattr(
        getattr(obj, "kind", None), "value", None
    ) != "module":
        return
    exports = getattr(obj, "exports", None)
    if isinstance(exports, (list, tuple)):
        options["members"] = [
            name
            for name in exports
            if isinstance(name, str) and not _is_single_underscore_private(name)
        ]


def _reject_forbidden_public_text(qualified: str, markdown: str) -> None:
    """Refuse internal identifiers before they can enter generated public pages."""
    match = _ADR_IDENTIFIER.search(markdown)
    if match:
        raise ValueError(
            f"documented Python symbol {qualified!r} contains forbidden public text "
            f"{match.group(0)!r}"
        )


def _explicit_anchors(markdown: str) -> str:
    """Put stable IDs before every rendered symbol heading.

    griffe2md uses the fully-qualified symbol inside every heading, so its source-order
    output gives us both root and member anchors without a separate reflection pass.
    Raw ``<a>`` elements are supported in ordinary Docusaurus Markdown and avoid its
    generated-slug normalization changing the legacy mixed-case Python IDs.
    """
    seen: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        heading, symbol = match.groups()
        if symbol in seen:
            return heading
        seen.add(symbol)
        return f'<a id="{symbol}"></a>\n\n{heading}'

    return _HEADING.sub(replace, markdown)
