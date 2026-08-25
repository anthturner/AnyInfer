"""The help system's honesty checks.

The "How is this built?" chips are only worth having if what they say stays true. These
tests hold the registry to that: every API entry must resolve against the real package,
every claimed demo source file must exist, and the library map's arithmetic must add up.
When the SDK renames something, the failure lands here — in the demo's help — instead of
shipping a dialog that teaches an API that no longer exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anyinfer_demo.sdk_help import TOPICS, covered_symbols, resolve_api, uncovered_symbols

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_every_api_entry_resolves_against_the_real_package():
    """A help dialog naming a symbol that does not exist is worse than no help at all."""
    stale = []
    for topic in TOPICS.values():
        for entry in topic.api:
            try:
                resolve_api(entry)
            except Exception:
                stale.append(f"{topic.key}: anyinfer.{entry}")
    assert stale == []


def test_every_topic_points_at_a_real_demo_file():
    missing = [
        f"{topic.key}: {topic.demo_source}"
        for topic in TOPICS.values()
        if not (REPO_ROOT / topic.demo_source).is_file()
    ]
    assert missing == []


def test_every_topic_is_fully_written():
    """No placeholder topics: each needs prose, at least one API entry, and a snippet."""
    for topic in TOPICS.values():
        assert topic.title, topic.key
        assert len(topic.summary) > 80, topic.key
        assert topic.api, topic.key
        assert any(marker in topic.snippet for marker in ("client", "anyinfer", "ai.")), topic.key


def test_library_map_lists_uncovered():
    """Covered and uncovered must partition the public surface — nothing double-counted."""
    import anyinfer

    covered = covered_symbols()
    uncovered = set(uncovered_symbols())
    assert covered & uncovered == set()
    # Dunders (__version__) are neither a coverage goal nor worth listing as a gap.
    public = {name for name in anyinfer.__all__ if not name.startswith("__")}
    assert covered | uncovered == public
    # The demo genuinely exercises a majority of the public surface.
    assert len(covered) > len(uncovered)


def test_snippets_reference_the_apis_they_document():
    """Each snippet should actually use at least one of its topic's API names."""
    for topic in TOPICS.values():
        leaves = {entry.split(".")[-1] for entry in topic.api}
        assert any(leaf in topic.snippet for leaf in leaves), topic.key


class TestHelpWidgets:
    def test_help_button_rejects_an_unknown_topic(self, qapp: object):
        from anyinfer_demo.widgets.sdk_help import SdkHelpButton

        with pytest.raises(KeyError):
            SdkHelpButton("no-such-topic")

    def test_every_topic_renders_in_the_dialog(self, qapp: object):
        from anyinfer_demo.widgets.sdk_help import SdkHelpDialog

        for topic in TOPICS.values():
            dialog = SdkHelpDialog(topic)
            assert topic.title in dialog.windowTitle()
            assert dialog.minimumWidth() == 756
            assert dialog._snippet.toPlainText() == topic.snippet
            dialog.close()

    def test_library_map_shows_every_topic_and_the_gap_count(self, qapp: object):
        from anyinfer_demo.widgets.sdk_help import LibraryMapDialog

        dialog = LibraryMapDialog()
        try:
            top_level = [
                dialog._tree.topLevelItem(i).text(0)
                for i in range(dialog._tree.topLevelItemCount())
            ]
            for topic in TOPICS.values():
                assert topic.title in top_level
            assert top_level[-1] == f"Not demonstrated here ({len(uncovered_symbols())})"
        finally:
            dialog.close()

    def test_inspector_sections_carry_help_chips(self, qapp: object):
        from anyinfer_demo.config import default_config
        from anyinfer_demo.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            for key, section in window._inspector_sections.items():
                assert section.help_button is not None, key
        finally:
            window.close()
