"""Focused coverage for the Python-to-Docusaurus API renderer."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[1] / "scripts" / "generate_python_reference.py"
_SPEC = importlib.util.spec_from_file_location("generate_python_reference", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
render_symbol = _MODULE.render_symbol


def test_render_client_preserves_alias_signature_docstring_and_member_anchors() -> None:
    rendered = render_symbol("anyinfer.Client")

    assert '<a id="anyinfer.Client"></a>' in rendered
    assert '<a id="anyinfer.Client.generate"></a>' in rendered
    assert "## `anyinfer.Client`" in rendered
    assert "Client(providers: Sequence[ProviderSettings]" in rendered
    assert "The synchronous inference client." in rendered


def test_render_reuses_loaded_distribution_members_without_losing_alias_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    import griffe

    _MODULE._loader.cache_clear()
    _MODULE._resolved_roots.cache_clear()
    calls: list[str] = []
    original_load = griffe.GriffeLoader.load

    def tracked_load(self: object, objspec: str, /, **kwargs: object) -> object:
        calls.append(objspec)
        return original_load(self, objspec, **kwargs)

    monkeypatch.setattr(griffe.GriffeLoader, "load", tracked_load)
    try:
        client = render_symbol("anyinfer.Client")
        async_client = render_symbol("anyinfer.AsyncClient")
    finally:
        _MODULE._loader.cache_clear()
        _MODULE._resolved_roots.cache_clear()

    assert calls.count("anyinfer.Client") == 1
    assert "anyinfer.AsyncClient" not in calls
    assert '<a id="anyinfer.Client"></a>' in client
    assert '<a id="anyinfer.AsyncClient"></a>' in async_client


@pytest.mark.parametrize(
    ("qualified", "member"),
    [
        ("anyinfer.Client", "__enter__"),
        ("anyinfer.AsyncStream", "__aenter__"),
        ("anyinfer.HeuristicTokenEstimator", "__post_init__"),
    ],
)
def test_render_preserves_documented_magic_method_anchors(qualified: str, member: str) -> None:
    rendered = render_symbol(qualified)

    assert f'<a id="{qualified}.{member}"></a>' in rendered


def test_render_addon_preserves_public_constants_and_source_order() -> None:
    rendered = render_symbol("anyinfer_store")

    assert '<a id="anyinfer_store"></a>' in rendered
    assert '<a id="anyinfer_store.VectorStore"></a>' in rendered
    assert "SIZE_WARNING_THRESHOLD" in rendered
    assert rendered.index("VectorStore") < rendered.index("VectorStoreError")


@pytest.mark.parametrize(
    "qualified",
    ["anyinfer_confidential.TemplateVault", "anyinfer_shared.ConfidentialityReport"],
)
def test_render_other_documented_addon_symbols(qualified: str) -> None:
    rendered = render_symbol(qualified)

    assert f'<a id="{qualified}"></a>' in rendered
    assert f"`{qualified}`" in rendered


def test_render_options_retain_requested_member_selection_without_private_members() -> None:
    rendered = render_symbol("anyinfer.Client", {"members": ["generate", "_loop"]})

    assert "anyinfer.Client.generate" in rendered
    assert "anyinfer.Client._loop" not in rendered


def test_render_module_ignores_external_implementation_imports() -> None:
    rendered = render_symbol("anyinfer.context.select")

    assert '<a id="anyinfer.context.select"></a>' in rendered
    assert '<a id="anyinfer.context.select.select"></a>' in rendered
    assert "math" not in rendered


def test_private_or_missing_symbols_fail_with_actionable_error() -> None:
    with pytest.raises(ValueError, match="private or malformed"):
        render_symbol("anyinfer._client.Client")
    with pytest.raises(ValueError, match="private or malformed"):
        render_symbol("anyinfer.Client._loop")
    with pytest.raises(ValueError, match="could not be resolved"):
        render_symbol("anyinfer.NoSuchPublicSymbol")


def test_forbidden_public_text_fails_with_symbol_context() -> None:
    with pytest.raises(ValueError, match=r"anyinfer.Client.*ADR-001"):
        _MODULE._reject_forbidden_public_text("anyinfer.Client", "Internal ADR-001 note")


def test_aliases_resolve_once_for_each_loaded_distribution_root() -> None:
    class Loader:
        calls = 0

        def resolve_aliases(self, *, external: bool) -> None:
            assert not external
            self.calls += 1

    loader = Loader()
    _MODULE._resolved_roots.cache_clear()
    try:
        _MODULE._resolve_aliases_for_root(loader, "anyinfer.Client")
        _MODULE._resolve_aliases_for_root(loader, "anyinfer.AsyncClient")
        _MODULE._resolve_aliases_for_root(loader, "anyinfer_store.VectorStore")
    finally:
        _MODULE._resolved_roots.cache_clear()

    assert loader.calls == 2
