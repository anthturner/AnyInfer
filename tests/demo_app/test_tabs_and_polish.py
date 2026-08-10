"""Round-two UI behaviours: tabs, snapping, morphing controls, and the help polish.

The heart of this file is the tab suite — several conversations at once, each stream
landing in the transcript that started it — because that is the claim the tabbed UI
makes and the one worth proving.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from demo_app.config import default_config
from demo_app.conversation import gist_title


@pytest.fixture
def window(qapp: object):
    from demo_app.main_window import MainWindow

    built = MainWindow(default_config())
    yield built
    built.close()


def _drain_keys(window, keys: set[str], timeout_ms: int = 20_000) -> dict[str, object]:
    """Run the event loop until every key in ``keys`` finishes (or fails)."""
    loop = QEventLoop()
    outcomes: dict[str, object] = {}

    def settle(key: str, payload: object) -> None:
        if key in keys:
            outcomes[key] = payload
            if keys <= set(outcomes):
                loop.quit()

    window._engine.gen_finished.connect(settle)
    window._engine.gen_failed.connect(lambda k, m, _e: settle(k, m))
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return outcomes


class TestGistTitles:
    def test_condenses_a_request_to_its_topic(self):
        assert (
            gist_title("Build me a retro 486 that I can play Commander Keen on")
            == "Build Retro 486 Play Commander Keen"
        )

    def test_drops_leading_politeness(self):
        assert gist_title("Please can you summarize this document")[:9] == "Summarize"

    def test_preserves_existing_casing(self):
        assert "JSON" in gist_title("Explain the JSON schema")

    def test_empty_input_stays_new_chat(self):
        assert gist_title("   ") == "New chat"

    def test_long_titles_are_elided(self):
        title = gist_title("supercalifragilisticexpialidocious " * 5)
        assert len(title) <= 40
        assert title.endswith("…")


class TestTabs:
    def test_send_titles_the_tab_from_the_first_message(self, window):
        window._composer.set_text("Build me a retro 486 that I can play Commander Keen on")
        window._on_send()
        page = window._tabs.current_page()
        assert window._tabs.tabText(0).startswith("Build Retro 486")
        _drain_keys(window, {page.key})

    def test_two_tabs_stream_concurrently_without_mixing(self, window):
        """The whole point of the tabs: parallel streams, separate transcripts."""
        window._composer.set_text("First conversation about apples")
        window._on_send()
        first = window._tabs.current_page()

        window._on_new_chat()
        window._composer.set_text("Second conversation about oranges")
        window._on_send()
        second = window._tabs.current_page()

        assert first.key != second.key
        outcomes = _drain_keys(window, {first.key, second.key})
        assert set(outcomes) == {first.key, second.key}
        assert "apples" in first.view.transcript_text()
        assert "oranges" not in first.view.transcript_text()
        assert "oranges" in second.view.transcript_text()

    def test_close_keeps_the_conversation_on_disk(self, window):
        window._composer.set_text("Keep me around")
        window._on_send()
        page = window._tabs.current_page()
        _drain_keys(window, {page.key})
        saved_id = page.conversation.id

        window._on_tab_close(window._tabs.indexOf(page))
        assert window._tabs.index_of_key(saved_id) == -1
        assert (window._conversations_dir / f"{saved_id}.json").exists()

    def test_delete_removes_tab_and_file(self, window):
        window._composer.set_text("Delete me")
        window._on_send()
        page = window._tabs.current_page()
        _drain_keys(window, {page.key})
        saved_id = page.conversation.id
        assert (window._conversations_dir / f"{saved_id}.json").exists()

        window._on_delete_conversation(saved_id)
        assert window._tabs.index_of_key(saved_id) == -1
        assert not (window._conversations_dir / f"{saved_id}.json").exists()
        assert window._tabs.count() >= 1  # never zero tabs

    def test_close_all_leaves_one_fresh_tab(self, window):
        window._on_new_chat()
        window._on_new_chat()
        assert window._tabs.count() == 3
        window._on_tab_close_all()
        assert window._tabs.count() == 1
        assert window._tabs.current_page().messages == []

    def test_selecting_a_saved_conversation_reopens_it_in_a_tab(self, window):
        window._composer.set_text("Remember this thread")
        window._on_send()
        page = window._tabs.current_page()
        _drain_keys(window, {page.key})
        saved_id = page.conversation.id
        window._on_tab_close(window._tabs.indexOf(page))

        window._on_conversation_selected(saved_id)
        assert window._tabs.current_page().conversation.id == saved_id
        assert "Remember this thread" in window._chat.transcript_text()


class TestSidebarSnap:
    """The snap handlers, fed sub-threshold widths directly.

    ``setSizes`` cannot produce those widths in a test — Qt clamps to the children's
    minimum sizes — so the reported sizes are shadowed for the call, exactly as a
    mid-drag ``splitterMoved`` would report them.
    """

    def test_left_sidebar_snaps_shut_below_the_threshold(self, window):
        window.show()
        splitter = window._outer_splitter
        splitter.sizes = lambda: [80, 1000]  # what a drag past the threshold reports
        try:
            window._on_outer_splitter_moved(0, 1)
        finally:
            del splitter.sizes
        assert splitter.sizes()[0] == 0
        assert window._left_sidebar_action.isChecked() is False

    def test_right_sidebar_snaps_shut_below_the_threshold(self, window):
        window.show()
        splitter = window._main_splitter
        splitter.sizes = lambda: [1000, 100]
        try:
            window._on_main_splitter_moved(0, 1)
        finally:
            del splitter.sizes
        assert splitter.sizes()[1] == 0
        assert window._right_sidebar_action.isChecked() is False

    def test_wide_drags_do_not_snap(self, window):
        window.show()
        before = window._outer_splitter.sizes()
        window._on_outer_splitter_moved(0, 1)  # real (wide) sizes: nothing to snap
        assert window._outer_splitter.sizes() == before
        assert window._left_sidebar_action.isChecked() is True


class TestBubblePolish:
    def test_assistant_header_reveals_target_on_hover(self, qapp: object):
        from demo_app.widgets.chat_view import MessageBubble

        bubble = MessageBubble("assistant", "ollama:gpt-oss:20b")
        assert "ollama" not in bubble._header_label.text()
        bubble._render_header(hovered=True)
        assert "ollama:gpt-oss:20b" in bubble._header_label.text()
        bubble._render_header(hovered=False)
        assert "ollama" not in bubble._header_label.text()


class TestDefaultsSurfaced:
    def test_max_tokens_shows_the_capability_value_when_known(self, window):
        from anyinfer.types.capabilities import (
            DiscoveredModel,
            ModelCapabilities,
            Sourced,
        )

        window._engine_bar.on_models_listed(
            "demo-fake",
            [
                DiscoveredModel(
                    "reliable",
                    ModelCapabilities(max_output_tokens=Sourced(8_192, "discovered")),
                )
            ],
        )
        window._engine_bar.set_target("demo-fake:reliable")
        window._refresh_default_hints()
        assert window._max_output_tokens.specialValueText() == "provider default (8,192)"
        assert "8,192" in window._max_output_tokens.toolTip()

    def test_sampling_defaults_say_they_are_not_reported(self, window):
        assert "not reported" in window._temperature.toolTip()
        assert "not reported" in window._reasoning.toolTip()

    def test_a_documented_sampling_default_is_shown_with_its_provenance(self, window):
        """A provider whose own reference states a default gets to show the number."""
        from anyinfer.types.capabilities import (
            DiscoveredModel,
            ModelCapabilities,
            Sourced,
        )

        window._engine_bar.on_models_listed(
            "demo-fake",
            [
                DiscoveredModel(
                    "documented",
                    ModelCapabilities(
                        default_temperature=Sourced(0.4, "catalog"),
                        default_top_p=Sourced(1.0, "catalog"),
                    ),
                )
            ],
        )
        window._engine_bar.set_target("demo-fake:documented")
        window._refresh_default_hints()

        assert window._temperature.specialValueText() == "provider default (0.4)"
        assert "catalog" in window._temperature.toolTip()
        assert window._top_p.specialValueText() == "provider default (1)"

    def test_an_undocumented_sampling_default_keeps_the_unreported_note(self, window):
        """Most providers state nothing, and saying so is the point of the note."""
        from anyinfer.types.capabilities import DiscoveredModel, ModelCapabilities

        window._engine_bar.on_models_listed(
            "demo-fake", [DiscoveredModel("plain", ModelCapabilities())]
        )
        window._engine_bar.set_target("demo-fake:plain")
        window._refresh_default_hints()

        assert window._temperature.specialValueText() == "provider default"
        assert "not reported" in window._temperature.toolTip()


class TestSectionMenuIcons:
    def test_hidden_sections_wear_their_icon_in_the_menu(self, window):
        action = window._section_actions["telemetry"]
        assert action.icon().isNull()  # visible → checkmark only
        action.setChecked(False)
        assert not action.icon().isNull()  # hidden → the section's icon
        action.setChecked(True)
        assert action.icon().isNull()


class TestHelpDialogPolish:
    def test_code_view_copy_excludes_line_numbers(self, qapp: object):
        from PySide6.QtWidgets import QApplication

        from demo_app.sdk_help import TOPICS
        from demo_app.widgets.sdk_help import SdkHelpDialog

        dialog = SdkHelpDialog(TOPICS["streaming"])
        try:
            dialog._snippet._copy()
            assert QApplication.clipboard().text() == TOPICS["streaming"].snippet
            assert "1" not in QApplication.clipboard().text().splitlines()[0][:2] or (
                QApplication.clipboard().text() == TOPICS["streaming"].snippet
            )
        finally:
            dialog.close()

    def test_licenses_dialog_lists_the_shipped_components(self, qapp: object):
        from demo_app.widgets.help_dialogs import THIRD_PARTY_COMPONENTS, LicensesDialog

        names = [c.name for c in THIRD_PARTY_COMPONENTS]
        assert any("Tabler" in n for n in names)
        assert any("PySide6" in n for n in names)

        dialog = LicensesDialog()
        try:
            assert dialog._list.count() == len(THIRD_PARTY_COMPONENTS)
            assert dialog._text.toPlainText()  # first entry auto-selected
        finally:
            dialog.close()

    def test_about_dialog_reports_the_sdk_version(self, qapp: object):
        import anyinfer

        from demo_app.widgets.help_dialogs import AboutDialog

        dialog = AboutDialog()
        try:
            from PySide6.QtWidgets import QLabel

            texts = [w.text() for w in dialog.findChildren(QLabel)]
            assert any(anyinfer.__version__ in t for t in texts)
            assert any("Demonstration Application" in t for t in texts)
        finally:
            dialog.close()


class TestConcurrentFakeShapes:
    """The offline fake answers each request in the shape that request asked for.

    A single mutable "json mode" on the backend used to decide this, which meant the
    last tab to start a generation chose the answer shape for every tab still running.
    """

    def test_structured_and_plain_tabs_do_not_reshape_each_other(self, window):
        import json

        from demo_app.widgets.schema_panel import EXAMPLE_SCHEMA

        # Tab 1: structured. Enable the schema before sending.
        window._schema.set_enabled(True)
        window._schema._editor.setPlainText(json.dumps(EXAMPLE_SCHEMA))
        window._composer.set_text("Analyze this review: great value")
        window._on_send()
        structured_page = window._tabs.current_page()

        # Tab 2: plain prose, started while the first is still settling, and with the
        # schema switched off — the state the old global flag would have leaked.
        window._on_new_chat()
        window._schema.set_enabled(False)
        window._composer.set_text("Just answer in prose")
        window._on_send()
        prose_page = window._tabs.current_page()

        _drain_keys(window, {structured_page.key, prose_page.key})

        structured_text = structured_page.view.transcript_text()
        prose_text = prose_page.view.transcript_text()
        assert "sentiment" in structured_text  # got the JSON object
        assert "sentiment" not in prose_text  # and the prose tab did not
        assert "fake provider" in prose_text

    def test_a_plain_request_alone_still_gets_prose(self, window):
        window._composer.set_text("hello")
        window._on_send()
        page = window._tabs.current_page()
        _drain_keys(window, {page.key})
        assert "fake provider" in page.view.transcript_text()
