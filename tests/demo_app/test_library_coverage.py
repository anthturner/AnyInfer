"""The demo's coverage of the library surfaces beyond generation.

Separate from ``test_demo_app.py`` because it asks a different question. That file checks
that the chat window behaves; this one checks that the parts of AnyInfer an integrator
would otherwise have to discover from the API reference — the model catalog, the store,
runtimes, capability probes, the tool loop — are actually reachable from the application,
and reachable *honestly*: a fit verdict carries its reasons, a probe says what it spent,
an absent price is not rendered as a free request.

Everything here runs headless and offline against the in-process fake provider, with one
deliberate exception noted at its call site: the catalog is real data read from the shipped
`catalog/models.json`, because a fake catalog would test the table
widget rather than the integration.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from demo_app.config import ProviderConfig, default_config
from demo_app.engine import Engine
from demo_app.fake_provider import DEMO_PROVIDER_ID, TOOL_MODEL


def _drain_task(engine: Engine, key: str, timeout_ms: int = 30_000) -> object:
    """Run the Qt event loop until one *keyed* background task settles.

    Keyed rather than paired with its caller, because the engine's local-work pool runs
    two tasks at once by design: a models-dialog refresh and a probe can both be in flight,
    and the first answer to arrive is not necessarily the one being awaited.
    """
    loop = QEventLoop()
    outcome: dict[str, object] = {}

    def on_done(done_key: str, result: object) -> None:
        if done_key == key:
            outcome["result"] = result
            loop.quit()

    def on_failed(failed_key: str, message: str, _error: object) -> None:
        if failed_key == key:
            outcome["error"] = message
            loop.quit()

    engine.task_done.connect(on_done)
    engine.task_failed.connect(on_failed)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()

    if "error" in outcome:
        raise AssertionError(f"task {key} failed: {outcome['error']}")
    if "result" not in outcome:
        raise AssertionError(f"task {key} timed out")
    return outcome["result"]


def _drain_generation(engine: Engine, timeout_ms: int = 15_000) -> object:
    """Run the Qt event loop until a generation finishes or fails."""
    loop = QEventLoop()
    outcome: dict[str, object] = {}

    def on_finished(result: object) -> None:
        outcome["result"] = result
        loop.quit()

    def on_failed(message: str, _error: object) -> None:
        outcome["error"] = message
        loop.quit()

    engine.finished.connect(on_finished)
    engine.failed.connect(on_failed)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    if "error" in outcome:
        raise AssertionError(f"generation failed: {outcome['error']}")
    return outcome.get("result")


@pytest.fixture
def engine(qapp: object) -> Engine:
    """An engine wired to the offline fake provider."""
    built = Engine(default_config())
    yield built
    built.close()


class TestSetupFieldRendering:
    """A field is rendered — and hinted — according to the kind its provider declared."""

    def test_a_directory_field_gets_a_picker_and_no_url_hint(self, qapp: object):
        """The bug these kinds exist to prevent: a model directory suggesting a URL."""
        from anyinfer.registry import default_registry
        from demo_app.widgets.settings_dialog import _PathField, _ProviderPanel

        descriptor = default_registry.get("llama-cpp")
        panel = _ProviderPanel(descriptor, ProviderConfig(provider_id="llama-cpp"))

        editor = panel._editors["model_dir"]
        assert isinstance(editor, _PathField)
        assert "://" not in editor._edit.placeholderText()

    def test_a_choice_field_offers_exactly_its_declared_choices(self, qapp: object):
        from PySide6.QtWidgets import QComboBox

        from anyinfer.registry import default_registry
        from demo_app.widgets.settings_dialog import _ProviderPanel

        descriptor = default_registry.get("llama-cpp")
        panel = _ProviderPanel(descriptor, ProviderConfig(provider_id="llama-cpp"))

        editor = panel._editors["posture"]
        assert isinstance(editor, QComboBox)
        offered = [editor.itemText(i) for i in range(editor.count())]
        # A leading blank is "use the provider's default"; then the declared set verbatim.
        assert offered == ["", "conservative", "balanced", "aggressive"]

    def test_every_endpoint_and_version_field_hints_something(self):
        """An empty editor with no example reads as "this field does not matter"."""
        from anyinfer.registry import default_registry

        hintless = [
            (descriptor.id, field.key)
            for descriptor in default_registry
            for field in descriptor.setup.fields
            if field.kind in ("endpoint", "api-version")
            and not (field.placeholder or field.default_value)
        ]
        assert hintless == []

    def test_a_choice_must_declare_choices(self):
        """Caught at import time, so it is an authoring error rather than a dead dropdown."""
        from anyinfer.errors import ConfigError
        from anyinfer.registry import SetupField

        with pytest.raises(ConfigError):
            SetupField(key="posture", label="Posture", kind="choice")
        with pytest.raises(ConfigError):
            SetupField(key="url", label="URL", kind="endpoint", choices=("a", "b"))


class TestModelsDialog:
    def test_catalog_lists_entries_carrying_their_fit_reasons(self, engine: Engine, qapp: object):
        """Real catalog data on purpose: a fake one would test the table, not the wiring."""
        from demo_app.widgets.models_dialog import _CATALOG_KEY, ModelsDialog

        dialog = ModelsDialog(engine, default_config())
        try:
            view = _drain_task(engine, _CATALOG_KEY)
            dialog._catalog.on_catalog(view)
            assert dialog._catalog._table.rowCount() > 0
            # The verdict stays checkable: its tooltip is the library's own reasons for it.
            fit_cell = dialog._catalog._table.item(0, 3)
            assert fit_cell is not None
            assert fit_cell.toolTip()
        finally:
            dialog.close()

    def test_installed_panel_starts_empty_and_says_so(self, engine: Engine, qapp: object):
        from demo_app.widgets.models_dialog import ModelsDialog

        dialog = ModelsDialog(engine, default_config())
        try:
            dialog._installed.on_installed([])
            assert dialog._installed._empty.isVisibleTo(dialog._installed)
            assert dialog._installed._remove.isEnabled() is False
        finally:
            dialog.close()

    def test_pull_offers_only_engines_that_manage_their_own_store(
        self, engine: Engine, qapp: object
    ):
        """Which engines can pull is the registry's answer, not a list kept in the UI."""
        from demo_app.widgets.models_dialog import ModelsDialog

        dialog = ModelsDialog(engine, default_config())
        try:
            # The offline fake declares no model puller, so it must not be offered.
            assert dialog._pull._instances.count() == 0
            assert dialog._pull._pull.isEnabled() is False
        finally:
            dialog.close()

    def test_unknown_download_size_reads_as_unknown_not_free(self):
        from demo_app.widgets.models_dialog import _bytes

        assert _bytes(None) == "—"
        assert _bytes(0) == "0 B"


class TestTargetInspector:
    def test_resolve_reports_provider_and_model_without_a_request(
        self, engine: Engine, qapp: object
    ):
        from demo_app.widgets.target_inspector import RESOLVE_KEY, TargetInspector

        inspector = TargetInspector(engine)
        inspector.set_target(f"{DEMO_PROVIDER_ID}:reliable")
        inspector._on_resolve()

        resolved = _drain_task(engine, RESOLVE_KEY)
        inspector._on_task_done(RESOLVE_KEY, resolved)
        text = inspector._output.toPlainText()
        assert DEMO_PROVIDER_ID in text
        assert "reliable" in text

    def test_probe_reports_per_feature_outcomes_and_what_it_spent(
        self, engine: Engine, qapp: object
    ):
        """A probe costs one request per feature, and the panel says how many it spent."""
        from demo_app.widgets.target_inspector import PROBE_KEY, TargetInspector

        inspector = TargetInspector(engine)
        inspector.set_target(f"{DEMO_PROVIDER_ID}:reliable")
        inspector._on_probe()

        report = _drain_task(engine, PROBE_KEY)
        inspector._on_task_done(PROBE_KEY, report)
        text = inspector._output.toPlainText()
        assert "Requests issued:" in text
        assert "STREAMING" in text

    def test_capabilities_are_rendered_with_their_provenance(self):
        """A measured window and a guessed one must not read the same."""
        from anyinfer import Feature, ModelCapabilities, Sourced
        from demo_app.widgets.target_inspector import _capabilities_lines

        lines = _capabilities_lines(
            ModelCapabilities(
                context_window=Sourced(32_768, "catalog"),
                features=Sourced(Feature.STREAMING, "default"),
            )
        )
        assert any("32,768" in line and "catalog" in line for line in lines)
        assert any("STREAMING" in line and "default" in line for line in lines)

    def test_buttons_stay_disabled_without_a_target(self, engine: Engine, qapp: object):
        from demo_app.widgets.target_inspector import TargetInspector

        inspector = TargetInspector(engine)
        inspector.set_target("")
        assert inspector._resolve.isEnabled() is False
        assert inspector._probe_button.isEnabled() is False


class TestToolLoop:
    def test_the_offline_model_drives_a_real_tool_round_trip(self, engine: Engine, qapp: object):
        """The function actually runs — the answer text alone would not prove it did."""
        from demo_app.widgets import tools_panel
        from demo_app.widgets.tools_panel import TOOLS_KEY, ToolsPanel

        panel = ToolsPanel(engine)
        panel.set_target(f"{DEMO_PROVIDER_ID}:{TOOL_MODEL}")
        panel._prompt.setText("What time is it in UTC?")
        panel._on_run()

        result = _drain_task(engine, TOOLS_KEY)
        panel._on_task_done(TOOLS_KEY, result)

        assert tools_panel._CALLS == ["current_time(timezone='UTC')"]
        assert "current_time" in panel._output.toPlainText()

    def test_run_needs_a_target(self, engine: Engine, qapp: object):
        from demo_app.widgets.tools_panel import ToolsPanel

        panel = ToolsPanel(engine)
        panel.set_target("")
        assert panel._run.isEnabled() is False


class TestRequestOptions:
    def test_reasoning_effort_defaults_to_sending_nothing(self, qapp: object):
        """Blank means "omit the field", not "minimal" — each provider decides."""
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            assert window._reasoning.currentData() == ""
            window._reasoning.setCurrentText("medium")
            assert window._reasoning.currentData() == "medium"
        finally:
            window.close()

    def test_session_reuse_is_reported_rather_than_assumed(self, qapp: object):
        """Report the reuse verdict rather than implying the conversation was resumed.

        The fake provider keeps no session, so the honest answer is ``unsupported``.
        """
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window._reuse_session.setChecked(True)
            window._composer.set_text("hello")
            window._on_send()
            _drain_generation(window._engine)
            assert window._engine.session_reuse == "unsupported"
            assert "session unsupported" in window.statusBar().currentMessage()
        finally:
            window.close()

    def test_cost_is_absent_rather_than_zero_without_pricing(self):
        """No pricing on file must not render as a free request."""
        from decimal import Decimal

        from anyinfer import CostEstimate
        from demo_app.main_window import _cost_hint

        assert _cost_hint(None) == ""
        estimate = CostEstimate(low=Decimal("0.0012"), high=Decimal("0.0034"), currency="USD")
        assert _cost_hint(estimate) == "~0.0012-0.0034 USD"


class TestHistoryAndCachePolicies:
    def test_default_selections_send_no_policy_at_all(self, qapp: object):
        """Both dropdowns default to 'off': no policy object, not a disabled one."""
        from demo_app.config import default_config
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            assert window._history_policy() is None
            assert window._cache_policy() is None
        finally:
            window.close()

    def test_selections_map_to_the_library_policies(self, qapp: object):
        from anyinfer import CachePolicy, HistoryPolicy

        from demo_app.config import default_config
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window._history.setCurrentIndex(window._history.findData("proactive"))
            window._cache.setCurrentIndex(window._cache.findData("auto"))
            assert window._history_policy() == HistoryPolicy(mode="proactive")
            assert window._cache_policy() == CachePolicy(mode="auto")
        finally:
            window.close()

    def test_policies_travel_on_the_generation_spec(self, qapp: object):
        """What the dropdowns say is what the engine is handed — nothing in between."""
        from demo_app.config import default_config
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window._history.setCurrentIndex(window._history.findData("last_resort"))
            window._cache.setCurrentIndex(window._cache.findData("explicit"))
            captured = {}
            window._engine.generate = lambda spec: captured.setdefault("spec", spec)
            window._composer.set_text("hello")
            window._on_send()
            spec = captured["spec"]
            assert spec.history is not None and spec.history.mode == "last_resort"
            assert spec.cache is not None and spec.cache.mode == "explicit"
        finally:
            window.close()

    def test_cache_plan_appears_in_telemetry_when_requested(self, engine: Engine, qapp: object):
        """An auto cache policy produces either a CachePlanned event or an explicit
        ParameterDropped saying why not — never silence."""
        from anyinfer import Retry, Route, Sampling, user
        from anyinfer.events.telemetry import CachePlanned, ParameterDropped

        from demo_app.engine import GenerationSpec
        from anyinfer import CachePolicy

        events = []
        engine.telemetry.connect(events.append)
        spec = GenerationSpec(
            messages=(user("x " * 2000),),
            route=Route(targets=("demo-fake:reliable",), retry=Retry(max_attempts=1)),
            sampling=Sampling(),
            cache=CachePolicy(mode="auto"),
        )
        engine.generate(spec)
        _drain_generation(engine)
        assert any(isinstance(e, (CachePlanned, ParameterDropped)) for e in events)


class TestBenchmarkPair:
    def test_pair_runs_two_and_reports_the_warmth_protocol(self, engine: Engine, qapp: object):
        from demo_app.widgets.target_inspector import BENCHMARK_KEY, TargetInspector

        inspector = TargetInspector(engine)
        inspector.set_target(f"{DEMO_PROVIDER_ID}:reliable")
        inspector._on_benchmark()

        result = _drain_task(engine, BENCHMARK_KEY)
        assert isinstance(result, tuple) and len(result) == 2
        inspector._on_task_done(BENCHMARK_KEY, result)
        text = inspector._output.toPlainText()
        assert "Run 1" in text and "Run 2" in text
        assert "warm by construction" in text
        # The verdict line is present either way the numbers land.
        assert "Warm-up visible" in text or "No warm-up visible" in text


class TestTelemetryRendering:
    def test_context_reduced_and_cache_planned_render_structurally(self, qapp: object):
        from anyinfer.events.telemetry import CachePlanned, ContextReduced

        from demo_app.widgets.telemetry_view import _details_of

        reduced = _details_of(
            ContextReduced(
                strategy="history", representation="messages",
                candidate_count=12, selected_count=7, omitted_count=5,
                estimated_tokens=900, max_tokens=1024,
            )
        )
        assert "kept 7 of 12" in reduced and "omitted 5" in reduced

        planned = _details_of(
            CachePlanned(
                "req", None, mechanism="implicit", mark_count=0,
                estimated_cacheable_tokens=1800,
            )
        )
        assert "implicit" in planned and "1,800" in planned
