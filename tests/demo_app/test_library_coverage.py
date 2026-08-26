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

**What the demo deliberately does not surface.** This list is hand-curated, which means a
missing feature is invisible here unless it is written down — so it is. Each of these is
reachable from the CLI and the sidecar, and absent from the demo *by decision*, not by
oversight:

- **Arena fan-out** (`client.arena`) — running one prompt against several targets at once
  needs a multi-result transcript view; the demo's transcript is deliberately a single
  conversation, and a second layout would double the window's complexity for a feature an
  integrator reads about rather than clicks.
- **Target comparison** (`client.compare`) — same reason, and `anyinfer compare` already
  demonstrates it in the surface where its tabular output belongs.
- **Run manifests** (`Generation.manifest`) — the telemetry view shows live events, which
  is the thing a GUI adds over reading a manifest after the fact.
- **MCP tool sources** — the tool loop is covered here with in-process tools; adding a
  server connection would make the demo spawn subprocesses, which its offline-by-default
  posture rules out.

Adding a demo surface for any of them is a fine change — delete the bullet in the same
commit. What is not fine is an omission nobody decided on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from anyinfer_demo.config import ProviderConfig, default_config
from anyinfer_demo.engine import Engine
from anyinfer_demo.fake_provider import DEMO_PROVIDER_ID, TOOL_MODEL


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
    """A field is rendered, and hinted — according to the kind its provider declared."""

    def test_a_directory_field_gets_a_picker_and_no_url_hint(self, qapp: object):
        """The bug these kinds exist to prevent: a model directory suggesting a URL."""
        from anyinfer.registry import default_registry
        from anyinfer_demo.widgets.settings_dialog import _PathField, _ProviderPanel

        descriptor = default_registry.get("llama-cpp")
        panel = _ProviderPanel(descriptor, ProviderConfig(provider_id="llama-cpp"))

        editor = panel._editors["model_dir"]
        assert isinstance(editor, _PathField)
        assert "://" not in editor._edit.placeholderText()

    def test_a_choice_field_offers_exactly_its_declared_choices(self, qapp: object):
        from PySide6.QtWidgets import QComboBox

        from anyinfer.registry import default_registry
        from anyinfer_demo.widgets.settings_dialog import _ProviderPanel

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

    def test_local_model_inventory_scope_is_declared_by_providers(self):
        from anyinfer.registry import default_registry

        assert default_registry.get("llama-cpp").model_inventory == "installed"
        assert default_registry.get("ollama").model_inventory == "installed"
        assert default_registry.get("vllm").model_inventory == "served"

    def test_a_choice_must_declare_choices(self):
        """Caught at import time, so it is an authoring error rather than a dead dropdown."""
        from anyinfer.errors import ConfigError
        from anyinfer.registry import SetupField

        with pytest.raises(ConfigError):
            SetupField(key="posture", label="Posture", kind="choice")
        with pytest.raises(ConfigError):
            SetupField(key="url", label="URL", kind="endpoint", choices=("a", "b"))


class TestModelsDialog:
    def test_store_count_shares_a_centred_footer_row_with_close(
        self, engine: Engine, qapp: object
    ):
        from PySide6.QtWidgets import QDialogButtonBox

        from anyinfer_demo.widgets.models_dialog import ModelsDialog

        dialog = ModelsDialog(engine, default_config())
        try:
            dialog._status.setText("2 model(s) in the store.")
            dialog.show()
            qapp.processEvents()

            close = dialog._buttons.button(QDialogButtonBox.StandardButton.Close)
            assert close is not None
            status_center = dialog._status.mapTo(dialog, dialog._status.rect().center()).y()
            close_center = close.mapTo(dialog, close.rect().center()).y()
            assert abs(status_center - close_center) <= 1
        finally:
            dialog.close()

    def test_runtimes_share_the_llama_setup_gate_and_limit_backends(
        self, engine: Engine, qapp: object, monkeypatch: pytest.MonkeyPatch
    ):
        import platform
        from dataclasses import replace

        from PySide6.QtCore import Qt

        from anyinfer.local.hardware import HardwareProfile
        from anyinfer_demo.widgets.models_dialog import _RuntimePanel, _RuntimeReport

        # default_runtime_kind() deliberately asks the real host, not the HardwareProfile
        # passed in below (it decides what to install on *this* machine) — pin the host so
        # the "plain Linux, no accelerator" scenario this test builds is what it sees too,
        # regardless of which OS actually runs the test.
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        monkeypatch.setattr(platform, "machine", lambda: "x86_64")

        missing = _RuntimePanel(engine, default_config())
        requested: list[bool] = []
        missing.quick_llama_setup_requested.connect(lambda: requested.append(True))
        try:
            assert missing._content.isHidden() is True
            assert missing._setup_prompt.isHidden() is False
            missing._setup_prompt.button.click()
            assert requested == [True]
        finally:
            missing.close()

        configured = default_config().with_provider(
            ProviderConfig(provider_id="llama-cpp", enabled=True)
        )
        panel = _RuntimePanel(engine, configured)
        hardware = HardwareProfile(os_name="linux", arch="x86_64")
        try:
            panel.on_runtimes(
                _RuntimeReport([], [], hardware, ("cuda", "vulkan", "metal", "rocm", "cpu"))
            )
            model = panel._runtime_choice.model()
            assert model.item(panel._runtime_choice.findData("cuda")).isEnabled() is False
            assert model.item(panel._runtime_choice.findData("metal")).isEnabled() is False
            assert model.item(panel._runtime_choice.findData("cpu")).isEnabled() is True
            assert panel._runtime_choice.currentData() == "cpu"
            assert "recommended" in panel._runtime_choice.currentText()
            assert panel._install.text() == "Install Runtime"
            assert not hasattr(panel, "_runtime_instance")

            panel.set_providers(replace(configured, ignore_runtime_hardware_constraints=True))
            assert model.item(panel._runtime_choice.findData("cuda")).isEnabled() is True
            assert "Hardware constraint ignored" in panel._runtime_choice.itemData(
                panel._runtime_choice.findData("cuda"), Qt.ItemDataRole.ToolTipRole
            )
        finally:
            panel.close()

    def test_runtime_install_progress_gets_its_own_progress_bar(
        self, engine: Engine, qapp: object
    ):
        from anyinfer.local.runtimes import InstallReport
        from anyinfer_demo.engine import RuntimeInstallProgress
        from anyinfer_demo.widgets.models_dialog import _RuntimePanel

        configured = default_config().with_provider(
            ProviderConfig(provider_id="llama-cpp", enabled=True)
        )
        panel = _RuntimePanel(engine, configured)
        try:
            panel.on_install_progress(RuntimeInstallProgress("runtime-cpu", 50, 100))
            assert panel._progress.isHidden() is False
            assert panel._progress.value() == 500
            assert "50 B of 100 B" in panel._progress.format()
            panel.on_install_finished(
                InstallReport("cpu", "b-test", Path("/tmp"), Path("/tmp/llama-server"))
            )
            assert panel._progress.isHidden() is True
        finally:
            panel.close()

    def test_runtime_panel_can_select_an_installed_backend(self, engine: Engine, qapp: object):
        from anyinfer.local.hardware import HardwareProfile
        from anyinfer.local.runtimes import InstallReport, RuntimeManifest
        from anyinfer_demo.widgets.models_dialog import _RuntimePanel, _RuntimeReport

        configured = default_config().with_provider(
            ProviderConfig(provider_id="llama-cpp", enabled=True)
        )
        panel = _RuntimePanel(engine, configured)
        selected: list[str] = []
        panel.runtime_selected.connect(selected.append)
        manifest = RuntimeManifest(
            backend="cpu",
            build="b-test",
            architecture="amd64",
            executable=Path("/tmp/llama-server"),
            directory=Path("/tmp"),
        )
        try:
            panel.on_runtimes(
                _RuntimeReport([manifest], [], HardwareProfile("linux", "x86_64"), ("cpu",))
            )
            panel.on_install_finished(
                InstallReport("cpu", "b-test", Path("/tmp"), Path("/tmp/llama-server"))
            )
            assert selected == ["cpu"]
            assert panel._table.item(0, 0).text() == "✓"
        finally:
            panel.close()

    def test_installed_llama_model_populates_the_benchmark_target(
        self, engine: Engine, qapp: object
    ):
        from anyinfer.local.store import StoreEntry
        from anyinfer_demo.widgets.models_dialog import _BenchmarkPanel

        configured = default_config().with_provider(
            ProviderConfig(provider_id="llama-cpp", enabled=True)
        )
        panel = _BenchmarkPanel(engine, configured)
        try:
            panel.on_installed(
                [
                    StoreEntry(
                        id="entry",
                        model_id="tiny-model",
                        variant_id="tiny-model-q4",
                        engine="llama.cpp",
                    )
                ]
            )
            assert panel._benchmark_target.currentText() == "llama-cpp:tiny-model-q4"
            assert panel._benchmark_button.isEnabled()
        finally:
            panel.close()

    def test_system_content_scrolls_instead_of_clipping_on_a_short_screen(
        self, engine: Engine, qapp: object
    ):
        from PySide6.QtWidgets import QApplication

        from anyinfer_demo.widgets.models_dialog import _scrollable, _SystemPanel

        panel = _SystemPanel(engine)
        scroll = _scrollable(panel)
        try:
            scroll.resize(700, 240)
            scroll.show()
            QApplication.processEvents()

            assert scroll.widgetResizable()
            assert scroll.verticalScrollBar().maximum() > 0
        finally:
            scroll.close()

    def test_add_model_search_uses_catalog_channels_and_provider_ownership(self, qapp: object):
        from anyinfer import load_default_catalog
        from anyinfer._client.models import build_catalog_view
        from anyinfer.local.hardware import HardwareProfile
        from anyinfer.registry import default_registry
        from anyinfer_demo.config import DemoConfig
        from anyinfer_demo.widgets.add_model_dialog import AddModelDialog, _acquisition_engine

        view = build_catalog_view(
            load_default_catalog(),
            hardware=HardwareProfile(os_name="linux", arch="x86_64", total_ram_bytes=32 * 1024**3),
            detect_backend=False,
        )
        config = DemoConfig(
            providers=(
                ProviderConfig("llama-cpp", enabled=True),
                ProviderConfig("ollama", enabled=True),
                ProviderConfig("vllm", enabled=True),
            )
        )
        dialog = AddModelDialog(view, config, default_registry)
        try:
            ollama_index = dialog._engine.findData("ollama")
            dialog._engine.setCurrentIndex(ollama_index)
            assert dialog._table.rowCount() > 0
            assert "Ollama" in dialog._table.item(0, 1).text()
            assert dialog._add.text() == "Pull"

            llama_index = dialog._engine.findData("llama-cpp")
            dialog._engine.setCurrentIndex(llama_index)
            assert "Hugging Face" in dialog._table.item(0, 1).text()
            assert dialog._add.text() == "Download"

            first_llama = next(entry for entry in view.entries if "llama-cpp" in entry.channels)
            assert _acquisition_engine(first_llama, "llama-cpp") == "llama.cpp"
            assert any(
                "Do not use" in dialog._table.item(row, 3).text()
                for row in range(dialog._table.rowCount())
            )

            vllm_index = dialog._engine.findData("vllm")
            dialog._engine.setCurrentIndex(vllm_index)
            assert dialog._table.rowCount() == 0
            assert "no vLLM artifacts" in dialog._empty.text()
        finally:
            dialog.close()

    def test_catalog_buttons_dispatch_qwen_through_the_selected_engine_operation(
        self, engine: Engine, qapp: object
    ):
        from PySide6.QtCore import Qt

        from anyinfer import load_default_catalog
        from anyinfer._client.models import build_catalog_view
        from anyinfer.local.hardware import HardwareProfile
        from anyinfer_demo.config import DemoConfig
        from anyinfer_demo.widgets.add_model_dialog import AddModelChoice
        from anyinfer_demo.widgets.models_dialog import _CatalogPanel

        config = DemoConfig(
            providers=(
                ProviderConfig("llama-cpp", enabled=True),
                ProviderConfig("ollama", enabled=True),
            )
        )
        panel = _CatalogPanel(engine, config)
        requested: list[tuple[AddModelChoice, bool]] = []
        panel.action_requested.connect(lambda choice, dry_run: requested.append((choice, dry_run)))

        def select_qwen() -> None:
            row = next(
                row
                for row in range(panel._table.rowCount())
                if panel._table.item(row, 0).data(Qt.ItemDataRole.UserRole) == "qwen3-4b"
            )
            panel._table.selectRow(row)

        try:
            panel.on_catalog(
                build_catalog_view(
                    load_default_catalog(),
                    hardware=HardwareProfile("linux", "x86_64"),
                    detect_backend=False,
                )
            )

            panel._engine_filter.setCurrentIndex(panel._engine_filter.findData("ollama"))
            select_qwen()
            assert panel._download.text() == "Pull"
            assert panel._download.isEnabled()
            assert not panel._plan.isEnabled()
            panel._download.click()
            ollama_choice, dry_run = requested.pop()
            assert not dry_run
            assert ollama_choice.operation == "pull"
            assert ollama_choice.instance_id == "ollama"
            assert ollama_choice.model_ref == "qwen3:4b"

            panel._engine_filter.setCurrentIndex(panel._engine_filter.findData("llama-cpp"))
            select_qwen()
            assert panel._download.text() == "Download"
            assert panel._download.isEnabled()
            assert panel._plan.isEnabled()
            panel._plan.click()
            llama_choice, dry_run = requested.pop()
            assert dry_run
            assert llama_choice.operation == "acquire"
            assert llama_choice.model_id == "qwen3-4b"
            assert llama_choice.acquisition_engine == "llama.cpp"
        finally:
            panel.close()

    def test_catalog_keeps_non_catalog_provider_models_and_branded_ownership(
        self, engine: Engine, qapp: object
    ):
        from PySide6.QtWidgets import QLabel

        from anyinfer import (
            DiscoveredModel,
            LocalModelInfo,
            ModelCapabilities,
            load_default_catalog,
        )
        from anyinfer._client.models import build_catalog_view
        from anyinfer.local.hardware import HardwareProfile
        from anyinfer_demo.widgets.models_dialog import _CatalogPanel

        panel = _CatalogPanel(
            engine,
            default_config().with_provider(ProviderConfig("ollama", enabled=True)),
        )
        try:
            panel.on_catalog(
                build_catalog_view(
                    load_default_catalog(),
                    hardware=HardwareProfile("linux", "x86_64"),
                    detect_backend=False,
                )
            )
            panel.set_provider_instances({"ollama": "ollama"})
            panel.on_provider_models(
                "ollama",
                [
                    DiscoveredModel(
                        "not-in-the-shipped-catalog:latest",
                        capabilities=ModelCapabilities(
                            local=LocalModelInfo(
                                artifact_size_bytes=5 * 1024**3,
                                quantization="Q4_K_M",
                            )
                        ),
                    )
                ],
            )
            row = next(
                row
                for row in range(panel._table.rowCount())
                if panel._table.item(row, 0).text() == "not-in-the-shipped-catalog:latest"
            )
            assert panel._table.item(row, 1).text() == "Other"
            assert panel._table.item(row, 2).text() == "5.0 GiB"
            engines = panel._table.cellWidget(row, 5)
            installed_for = panel._table.cellWidget(row, 6)
            assert engines.findChild(QLabel).accessibleName() == "ollama"
            assert installed_for.findChild(QLabel).toolTip() == "ollama"
            panel._table.selectRow(row)
            assert panel._remove.isEnabled() is False
        finally:
            panel.close()

    def test_system_is_first_and_renders_hardware_fit_guidance(self, engine: Engine, qapp: object):
        from anyinfer import CatalogView
        from anyinfer.local.hardware import Accelerator, HardwareProfile
        from anyinfer_demo.widgets.models_dialog import _CATALOG_KEY, ModelsDialog

        dialog = ModelsDialog(engine, default_config())
        try:
            assert dialog.windowTitle() == "Local Inference"
            assert dialog._tabs.tabText(0) == "System"
            assert dialog._tabs.tabText(1) == "Benchmark"
            assert dialog._benchmark._benchmark_target.currentText() == ""
            assert dialog._benchmark._benchmark_button.isEnabled() is False

            original = _drain_task(engine, _CATALOG_KEY)
            assert isinstance(original, CatalogView)
            view = CatalogView(
                entries=original.entries,
                hardware=HardwareProfile(
                    os_name="linux",
                    arch="x86_64",
                    total_ram_bytes=64 * 1024**3,
                    available_ram_bytes=48 * 1024**3,
                    cpu_name="AMD Ryzen 9 7950X",
                    physical_cores=16,
                    logical_cores=32,
                    accelerators=(
                        Accelerator(
                            kind="cuda",
                            name="NVIDIA GeForce RTX 4090",
                            total_vram_bytes=24 * 1024**3,
                            free_vram_bytes=20 * 1024**3,
                            compute_capability="8.9",
                            driver_version="580.65",
                        ),
                    ),
                ),
                hardware_source="detected",
                backend=original.backend,
                notes=original.notes,
            )
            dialog._system.on_catalog(view)

            assert dialog._system._cpu._mark.text() == "AMD RYZEN"
            assert "Ryzen 9 7950X" in dialog._system._cpu._name.text()
            assert dialog._system._gpu._mark.text() == "NVIDIA"
            assert "RTX 4090" in dialog._system._gpu._name.text()
            assert "24.0 GiB VRAM" in dialog._system._gpu._details.text()
            assert "catalog models are reasonable" in dialog._system._recommendations.text()
        finally:
            dialog.close()

    def test_system_benchmark_results_compare_first_and_warm_runs(
        self, engine: Engine, qapp: object
    ):
        from anyinfer import Measurement, MeasurementIdentity
        from anyinfer_demo.widgets.models_dialog import ModelsDialog

        dialog = ModelsDialog(engine, default_config())
        identity = MeasurementIdentity(provider_id="ollama", model="qwen3:8b")
        try:
            dialog._benchmark.on_benchmark(
                Measurement(
                    identity=identity,
                    ttft_ms=850,
                    total_ms=4_000,
                    prefill_tokens_per_s=200,
                    decode_tokens_per_s=18,
                ),
                Measurement(
                    identity=identity,
                    ttft_ms=110,
                    total_ms=3_100,
                    prefill_tokens_per_s=310,
                    decode_tokens_per_s=25,
                ),
            )

            assert dialog._benchmark._result_values[(1, 1)].text() == "850 ms"
            assert dialog._benchmark._result_values[(1, 2)].text() == "110 ms"
            assert dialog._benchmark._result_values[(3, 2)].text() == "25.0 tok/s"
            assert "Measured ollama:qwen3:8b" in dialog._benchmark._benchmark_note.text()
        finally:
            dialog.close()

    def test_catalog_requires_a_configured_llama_cpp_provider(self, engine: Engine, qapp: object):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTableWidgetItem

        from anyinfer import load_default_catalog
        from anyinfer._client.models import build_catalog_view
        from anyinfer.local.hardware import HardwareProfile
        from anyinfer_demo.widgets.models_dialog import _CatalogPanel

        panel = _CatalogPanel(engine, default_config())
        requested: list[bool] = []
        panel.quick_llama_setup_requested.connect(lambda: requested.append(True))
        try:
            assert panel._provider_notice.isHidden() is False
            panel._table.setRowCount(1)
            model = QTableWidgetItem("Test model")
            model.setData(Qt.ItemDataRole.UserRole, "test-model")
            panel._table.setItem(0, 0, model)
            panel._table.selectRow(0)
            assert panel._download.isEnabled() is False

            panel._quick_setup.click()
            assert requested == [True]

            configured = default_config().with_provider(
                ProviderConfig(provider_id="llama-cpp", enabled=True)
            )
            panel.set_providers(configured)
            assert panel._provider_notice.isHidden() is True
            panel.on_catalog(
                build_catalog_view(
                    load_default_catalog(),
                    hardware=HardwareProfile("linux", "x86_64"),
                    detect_backend=False,
                )
            )
            panel._table.selectRow(0)
            assert panel._download.isEnabled() is True
        finally:
            panel.close()

    def test_catalog_lists_entries_carrying_their_fit_reasons(
        self, engine: Engine, qapp: object, monkeypatch: pytest.MonkeyPatch
    ):
        """Real catalog data on purpose: a fake one would test the table, not the wiring."""
        from PySide6.QtCore import Qt

        from anyinfer import load_default_catalog
        from anyinfer._client.models import build_catalog_view
        from anyinfer.local.hardware import HardwareProfile
        from anyinfer_demo.widgets.models_dialog import ModelsDialog
        from anyinfer_demo.widgets.tab_widget import BorderedTabWidget

        monkeypatch.setattr(engine, "local_catalog", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(engine, "installed_models", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(engine, "run_task", lambda *_args, **_kwargs: None)
        dialog = ModelsDialog(engine, default_config())
        try:
            assert isinstance(dialog._tabs, BorderedTabWidget)
            view = build_catalog_view(
                load_default_catalog(),
                hardware=HardwareProfile("linux", "x86_64"),
                detect_backend=False,
            )
            dialog._catalog.on_catalog(view)
            assert dialog._catalog._table.rowCount() > 0
            assert dialog._catalog._table.horizontalHeaderItem(1).text() == "Family"
            family_by_id = {
                dialog._catalog._table.item(row, 0).data(
                    Qt.ItemDataRole.UserRole
                ): dialog._catalog._table.item(row, 1).text()
                for row in range(dialog._catalog._table.rowCount())
            }
            assert family_by_id["qwen3-4b"] == "Qwen"
            assert family_by_id["deepseek-r1-distill-qwen-1.5b"] == "DeepSeek"
            assert family_by_id["llama-3.2-1b-instruct"] == "Llama"
            assert family_by_id["phi-4"] == "Phi"
            assert family_by_id["mistral-small-3.2"] == "Mistral"

            dialog._catalog._table.sortItems(1, Qt.SortOrder.DescendingOrder)
            families = [
                dialog._catalog._table.item(row, 1).text()
                for row in range(dialog._catalog._table.rowCount())
            ]
            assert families == sorted(families, reverse=True)
            # The verdict stays checkable: its tooltip is the library's own reasons for it.
            fit_cell = dialog._catalog._table.item(0, 4)
            assert fit_cell is not None
            assert fit_cell.toolTip()
        finally:
            dialog.close()

    def test_catalog_replaces_installed_and_engine_pull_tabs(
        self, engine: Engine, qapp: object, monkeypatch: pytest.MonkeyPatch
    ):
        from anyinfer_demo.widgets.models_dialog import ModelsDialog

        monkeypatch.setattr(engine, "local_catalog", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(engine, "installed_models", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(engine, "run_task", lambda *_args, **_kwargs: None)
        dialog = ModelsDialog(engine, default_config())
        try:
            labels = [dialog._tabs.tabText(index) for index in range(dialog._tabs.count())]
            assert labels == ["System", "Benchmark", "Catalog", "Runtimes"]
            assert dialog._catalog._remove.isEnabled() is False
        finally:
            dialog.close()

    def test_catalog_add_accepts_an_exact_engine_owned_model_id(
        self, engine: Engine, qapp: object
    ):
        from anyinfer import load_default_catalog
        from anyinfer._client.models import build_catalog_view
        from anyinfer.local.hardware import HardwareProfile
        from anyinfer_demo.widgets.add_model_dialog import AddModelDialog

        view = build_catalog_view(
            load_default_catalog(),
            hardware=HardwareProfile("linux", "x86_64"),
            detect_backend=False,
        )
        config = default_config().with_provider(ProviderConfig("ollama", enabled=True))
        dialog = AddModelDialog(view, config, engine.registry)
        try:
            dialog._engine.setCurrentIndex(dialog._engine.findData("ollama"))
            dialog._search.setText("private-model:latest")
            assert dialog._table.rowCount() == 0
            assert dialog._add.text() == "Pull"
            assert dialog._add.isEnabled()
            dialog._accept()
            assert dialog.choice() is not None
            assert dialog.choice().model_ref == "private-model:latest"
        finally:
            dialog.close()

    def test_unknown_download_size_reads_as_unknown_not_free(self):
        from anyinfer_demo.widgets.models_dialog import _bytes

        assert _bytes(None) == "—"
        assert _bytes(0) == "0 B"


class TestTargetInspector:
    def test_resolve_reports_provider_and_model_without_a_request(
        self, engine: Engine, qapp: object
    ):
        from anyinfer_demo.widgets.target_inspector import RESOLVE_KEY, TargetInspector

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
        from anyinfer_demo.widgets.target_inspector import PROBE_KEY, TargetInspector

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
        from anyinfer_demo.widgets.target_inspector import _capabilities_lines

        lines = _capabilities_lines(
            ModelCapabilities(
                context_window=Sourced(32_768, "catalog"),
                features=Sourced(Feature.STREAMING, "default"),
            )
        )
        assert any("32,768" in line and "catalog" in line for line in lines)
        assert any("STREAMING" in line and "default" in line for line in lines)

    def test_buttons_stay_disabled_without_a_target(self, engine: Engine, qapp: object):
        from anyinfer_demo.widgets.target_inspector import TargetInspector

        inspector = TargetInspector(engine)
        inspector.set_target("")
        assert inspector._resolve.isEnabled() is False
        assert inspector._probe_button.isEnabled() is False


class TestToolLoop:
    def test_the_offline_model_drives_a_real_tool_round_trip(self, engine: Engine, qapp: object):
        """The function actually runs — the answer text alone would not prove it did."""
        from anyinfer_demo.widgets import tools_panel
        from anyinfer_demo.widgets.tools_panel import TOOLS_KEY, ToolsPanel

        panel = ToolsPanel(engine)
        panel.set_target(f"{DEMO_PROVIDER_ID}:{TOOL_MODEL}")
        panel._prompt.setText("What time is it in UTC?")
        panel._on_run()

        result = _drain_task(engine, TOOLS_KEY)
        panel._on_task_done(TOOLS_KEY, result)

        assert tools_panel._CALLS == ["current_time(timezone='UTC')"]
        assert "current_time" in panel._output.toPlainText()

    def test_run_needs_a_target(self, engine: Engine, qapp: object):
        from anyinfer_demo.widgets.tools_panel import ToolsPanel

        panel = ToolsPanel(engine)
        panel.set_target("")
        assert panel._run.isEnabled() is False


class TestRequestOptions:
    def test_reasoning_effort_defaults_to_sending_nothing(self, qapp: object):
        """Blank means "omit the field", not "minimal" — each provider decides."""
        from anyinfer_demo.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            assert window._reasoning.currentData() == ""
            window._reasoning.setCurrentText("medium")
            assert window._reasoning.currentData() == "medium"
        finally:
            window.close()

    def test_session_reuse_is_reported_rather_than_assumed(self, qapp: object, wait_for_models):
        """Report the reuse verdict rather than implying the conversation was resumed.

        The fake provider keeps no session, so the honest answer is ``unsupported``.
        """
        from anyinfer_demo.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            if not window._engine_bar.target():
                wait_for_models(window._engine, DEMO_PROVIDER_ID)
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
        from anyinfer_demo.main_window import _cost_hint

        assert _cost_hint(None) == ""
        estimate = CostEstimate(low=Decimal("0.0012"), high=Decimal("0.0034"), currency="USD")
        assert _cost_hint(estimate) == "~0.0012-0.0034 USD"


class TestHistoryAndCachePolicies:
    def test_default_selections_send_no_policy_at_all(self, qapp: object):
        """Both dropdowns default to 'off': no policy object, not a disabled one."""
        from anyinfer_demo.config import default_config
        from anyinfer_demo.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            assert window._history_policy() is None
            assert window._cache_policy() is None
        finally:
            window.close()

    def test_selections_map_to_the_library_policies(self, qapp: object):
        from anyinfer import CachePolicy, HistoryPolicy
        from anyinfer_demo.config import default_config
        from anyinfer_demo.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window._history.setCurrentIndex(window._history.findData("proactive"))
            window._cache.setCurrentIndex(window._cache.findData("auto"))
            assert window._history_policy() == HistoryPolicy(mode="proactive")
            assert window._cache_policy() == CachePolicy(mode="auto")
        finally:
            window.close()

    def test_policies_travel_on_the_generation_spec(self, qapp: object, wait_for_models):
        """What the dropdowns say is what the engine is handed — nothing in between."""
        from anyinfer_demo.config import default_config
        from anyinfer_demo.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            if not window._engine_bar.target():
                wait_for_models(window._engine, DEMO_PROVIDER_ID)
            window._history.setCurrentIndex(window._history.findData("last_resort"))
            window._cache.setCurrentIndex(window._cache.findData("explicit"))
            captured = {}
            window._engine.generate = lambda spec, key="": captured.setdefault("spec", spec)
            window._composer.set_text("hello")
            window._on_send()
            spec = captured["spec"]
            assert spec.history is not None and spec.history.mode == "last_resort"
            assert spec.cache is not None and spec.cache.mode == "explicit"
        finally:
            window.close()

    def test_cache_plan_appears_in_telemetry_when_requested(self, engine: Engine, qapp: object):
        """An auto cache policy always reports its outcome.

        It produces either a CachePlanned event or an explicit ParameterDropped event.
        """
        from anyinfer import CachePolicy, Retry, Route, Sampling, user
        from anyinfer.events.telemetry import CachePlanned, ParameterDropped
        from anyinfer_demo.engine import GenerationSpec

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
        from anyinfer_demo.widgets.target_inspector import BENCHMARK_KEY, TargetInspector

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
        from anyinfer_demo.widgets.telemetry_view import _details_of

        reduced = _details_of(
            ContextReduced(
                strategy="history",
                representation="messages",
                candidate_count=12,
                selected_count=7,
                omitted_count=5,
                estimated_tokens=900,
                max_tokens=1024,
            )
        )
        assert "kept 7 of 12" in reduced and "omitted 5" in reduced

        planned = _details_of(
            CachePlanned(
                "req",
                None,
                mechanism="implicit",
                mark_count=0,
                estimated_cacheable_tokens=1800,
            )
        )
        assert "implicit" in planned and "1,800" in planned
