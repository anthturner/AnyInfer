"""A third-party provider that fails to load says so, instead of vanishing."""

from __future__ import annotations

from typing import Any

import pytest

from anyinfer.errors import ConfigError
from anyinfer.registry import (
    PluginLoadIssue,
    ProviderDescriptor,
    ProviderRegistry,
    normalize_provider_id,
)
from anyinfer.testing import ScriptedProvider


class _FakeEntryPoint:
    """An ``importlib.metadata`` entry point standing in for an installed package."""

    def __init__(self, name: str, loader: Any) -> None:
        self.name = name
        self._loader = loader

    def load(self) -> Any:
        return self._loader()


def _registry_with(monkeypatch: pytest.MonkeyPatch, *points: _FakeEntryPoint) -> ProviderRegistry:
    import anyinfer.registry as registry_module

    monkeypatch.setattr(registry_module, "entry_points", lambda group: list(points))
    return ProviderRegistry(load_builtins=True, load_entry_points=True)


def _descriptor(provider_id: str, *aliases: str) -> ProviderDescriptor:
    return ScriptedProvider(provider_id, aliases=aliases).descriptor()


def test_import_failure_is_recorded_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode() -> Any:
        raise ImportError("no module named 'acme_internals'")

    registry = _registry_with(monkeypatch, _FakeEntryPoint("acme", explode))

    issues = registry.plugin_issues()
    assert [i.reason for i in issues] == ["import-failed"]
    assert "acme_internals" in issues[0].detail
    # The rest of the registry is unharmed.
    assert registry.has("openai-compat")


def test_non_descriptor_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _registry_with(monkeypatch, _FakeEntryPoint("acme", lambda: ["not a descriptor"]))

    issues = registry.plugin_issues()
    assert [i.reason for i in issues] == ["not-a-descriptor"]
    assert "str" in issues[0].detail


def test_id_collision_with_a_builtin_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _registry_with(
        monkeypatch, _FakeEntryPoint("shadow", lambda: _descriptor("ollama"))
    )

    issues = registry.plugin_issues()
    assert [i.reason for i in issues] == ["id-taken"]
    assert "ollama" in issues[0].detail


def test_alias_collision_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _registry_with(
        monkeypatch, _FakeEntryPoint("shadow", lambda: _descriptor("acme-llm", "claude"))
    )

    issues = registry.plugin_issues()
    assert [i.reason for i in issues] == ["alias-taken"]
    assert "claude" in issues[0].detail


def test_a_working_plugin_loads_and_reports_no_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _registry_with(
        monkeypatch, _FakeEntryPoint("acme", lambda: _descriptor("acme-llm"))
    )

    assert registry.has("acme-llm")
    assert registry.plugin_issues() == ()


def test_unknown_provider_hint_names_the_failed_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point: the error explains why *their* provider is missing."""

    def explode() -> Any:
        raise ImportError("boom")

    registry = _registry_with(monkeypatch, _FakeEntryPoint("acme", explode))

    with pytest.raises(ConfigError) as caught:
        registry.resolve_alias("acme")

    hint = str(caught.value.hint or "")
    assert "failed to load" in hint
    assert "acme" in hint
    assert "import-failed" in hint


def test_unknown_provider_without_a_plugin_lists_known_providers() -> None:
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)

    with pytest.raises(ConfigError) as caught:
        registry.resolve_alias("nonesuch")

    assert "known providers" in str(caught.value.hint or "")


def test_issue_summary_is_one_line() -> None:
    issue = PluginLoadIssue(entry_point="acme", reason="id-taken", detail="provider id 'x'")
    assert issue.summary == "acme: id-taken (provider id 'x')"
    assert "\n" not in issue.summary


def test_normalize_provider_id_is_unchanged() -> None:
    assert normalize_provider_id(" Acme_LLM ") == "acme-llm"
