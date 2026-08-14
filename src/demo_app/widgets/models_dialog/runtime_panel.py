"""The llama.cpp builds present, and the accelerator backends they can drive."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from anyinfer.local.hardware import HardwareProfile
from anyinfer.local.runtimes import InstallReport

from ...config import DemoConfig
from ...engine import Engine, RuntimeInstallProgress
from ..formatting import _bytes
from ..sdk_help import SdkHelpButton
from ._shared import _INSTALL_RUNTIME_KEY, _RUNTIMES_KEY, _llama_cpp_enabled, _LlamaSetupPrompt


def _default_runtime_kind(hardware: HardwareProfile | None) -> str:
    """Return the SDK's default backend spelling without duplicating its policy."""
    from anyinfer.local.runtimes import default_runtime_kind

    return default_runtime_kind(hardware)


def _runtime_backend_usable(kind: str, hardware: HardwareProfile | None) -> tuple[bool, str]:
    """Explain whether detected hardware can drive one llama.cpp runtime family."""
    if kind == "cpu":
        return True, "CPU runtimes work on every supported machine."
    if hardware is None:
        return False, "Hardware was not detected, so this accelerator cannot be confirmed."

    detected = {accelerator.kind for accelerator in hardware.accelerators}
    if kind == "cuda":
        usable = "cuda" in detected
        return usable, (
            "An NVIDIA CUDA device was detected."
            if usable
            else "No NVIDIA CUDA device was detected."
        )
    if kind == "metal":
        apple_silicon = (
            hardware.os_name.lower() in ("darwin", "macos")
            and hardware.arch.lower() in ("arm64", "aarch64")
            and "metal" in detected
        )
        return apple_silicon, (
            "Apple Silicon with Metal was detected."
            if apple_silicon
            else "Metal runtimes require detected Apple Silicon."
        )
    if kind == "rocm":
        usable = "rocm" in detected
        return usable, (
            "A ROCm-capable device was detected."
            if usable
            else "No ROCm-capable device was detected."
        )
    if kind == "vulkan":
        usable = hardware.has_accelerator
        return usable, (
            "A hardware accelerator was detected; Vulkan is the vendor-neutral fallback."
            if usable
            else "No GPU or other hardware accelerator was detected for Vulkan."
        )
    return False, f"{kind} is not a recognized llama.cpp runtime backend."


class _RuntimePanel(QWidget):
    """The llama.cpp builds present, and the accelerator backends they can drive.

    Runtimes are fetched rather than bundled — a wheel carrying every accelerator build of
    llama.cpp would be enormous and mostly wrong for any given machine, so "which build
    do I have" is a real question with a real answer, and this is where it is asked.
    """

    quick_llama_setup_requested = Signal()
    runtime_selected = Signal(str)

    def __init__(self, engine: Engine, config: DemoConfig) -> None:
        super().__init__()
        self._engine = engine
        self._config = config
        self._report: _RuntimeReport | None = None
        self._ignore_hardware_constraints = False
        self._llama_cpp_ready = False

        outer = QVBoxLayout(self)
        self._setup_prompt = _LlamaSetupPrompt("installing or inspecting its runtimes")
        self._setup_prompt.setup_requested.connect(self.quick_llama_setup_requested)
        outer.addWidget(self._setup_prompt)

        self._content = QWidget()
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(0, 0, 0, 0)
        caption = QLabel(
            "llama.cpp runtimes are downloaded on demand for the accelerator this machine "
            "actually has. Nothing is bundled into the package. vLLM and Ollama manage "
            "their own runtime environments, so they do not appear here."
        )
        caption.setWordWrap(True)
        layout.addWidget(caption)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Selected", "Backend", "Build", "Architecture", "Path"]
        )
        self._table.setAccessibleName("Installed runtimes")
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 1)

        self._backends = QLabel()
        self._backends.setWordWrap(True)
        self._backends.setObjectName("HintText")
        layout.addWidget(self._backends)

        selection = QHBoxLayout()
        selection.addWidget(QLabel("Runtime:"))
        self._runtime_choice = QComboBox()
        for kind in ("cuda", "vulkan", "metal", "rocm", "cpu"):
            self._runtime_choice.addItem(kind.upper(), kind)
        self._runtime_choice.setAccessibleName("llama.cpp runtime to install")
        self._runtime_choice.currentIndexChanged.connect(self._update_install_button)
        selection.addWidget(self._runtime_choice)
        self._install = QPushButton("Install Runtime")
        self._install.setToolTip(
            "Fetch the pinned llama.cpp build for this backend into the per-user runtime "
            "directory, then make it the default for llama.cpp."
        )
        self._install.clicked.connect(self._on_install)
        selection.addWidget(self._install)
        selection.addStretch(1)
        selection.addWidget(SdkHelpButton("runtimes"))
        layout.addLayout(selection)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setAccessibleName("Runtime installation progress")
        layout.addWidget(self._progress)
        outer.addWidget(self._content, 1)

        self.set_providers(config)

    def refresh(self) -> None:
        """Re-read installed runtimes and the backends this machine can drive."""
        self._engine.run_task(_RUNTIMES_KEY, _read_runtimes)

    def on_runtimes(self, report: _RuntimeReport) -> None:
        """Adopt a freshly read runtime inventory."""
        self._report = report
        self._configure_backend_choices()
        self._select_configured_or_recommended_runtime()
        self._render_runtime_table()

    def _render_runtime_table(self) -> None:
        """Render the installed variants and mark the backend llama.cpp will select."""
        report = self._report
        self._table.setRowCount(0)
        if report is None:
            return
        selected_kind = self._selected_runtime_kind()
        for manifest in report.installed:
            row = self._table.rowCount()
            self._table.insertRow(row)
            selected = QTableWidgetItem("✓" if manifest.backend == selected_kind else "")
            selected.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            selected.setToolTip(
                "Selected for llama.cpp"
                if manifest.backend == selected_kind
                else "Installed but not selected"
            )
            self._table.setItem(row, 0, selected)
            self._table.setItem(row, 1, QTableWidgetItem(manifest.backend))
            self._table.setItem(row, 2, QTableWidgetItem(manifest.build))
            self._table.setItem(row, 3, QTableWidgetItem(manifest.architecture))
            self._table.setItem(row, 4, QTableWidgetItem(str(manifest.executable)))
        available = ", ".join(f"{b.kind}" for b in report.backends) or "none detected"
        self._table.setToolTip("")
        self._backends.setText(
            f"Usable installed backends on this machine: {available}."
            if report.installed
            else f"No runtime installed yet. Usable installed backends: {available}."
        )

    def set_providers(self, config: DemoConfig) -> None:
        """Apply the llama.cpp prerequisite and runtime hardware preference."""
        self._config = config
        self._llama_cpp_ready = _llama_cpp_enabled(config)
        self._ignore_hardware_constraints = config.ignore_runtime_hardware_constraints
        self._setup_prompt.set_ready(self._llama_cpp_ready)
        self._content.setVisible(self._llama_cpp_ready)
        self._configure_backend_choices()
        self._select_configured_or_recommended_runtime()
        self._render_runtime_table()

    def _configured_runtime(self) -> str:
        """Return the first enabled llama.cpp instance's configured backend."""
        for provider in self._config.instances_of("llama-cpp"):
            if provider.enabled:
                return str(provider.options.get("runtime", "auto"))
        return "auto"

    def _selected_runtime_kind(self) -> str | None:
        """Resolve ``auto`` to the installed backend that this machine would use."""
        configured = self._configured_runtime()
        if configured != "auto":
            return configured
        if self._report is None:
            return None
        selected = next(
            (
                backend.kind
                for backend in self._report.backends
                if _runtime_backend_usable(backend.kind, self._report.hardware)[0]
            ),
            None,
        )
        if selected is not None:
            return str(selected)
        fallback = next(
            (
                manifest.backend
                for manifest in self._report.installed
                if _runtime_backend_usable(manifest.backend, self._report.hardware)[0]
            ),
            None,
        )
        return str(fallback) if fallback is not None else None

    def _select_configured_or_recommended_runtime(self) -> None:
        """Prefer an explicit setting, otherwise show the SDK's machine recommendation."""
        if self._report is None:
            return
        configured = self._configured_runtime()
        wanted = (
            configured if configured != "auto" else _default_runtime_kind(self._report.hardware)
        )
        index = self._runtime_choice.findData(wanted)
        model = self._runtime_choice.model()
        if isinstance(model, QStandardItemModel) and index >= 0 and model.item(index).isEnabled():
            self._runtime_choice.setCurrentIndex(index)

    def _configure_backend_choices(self) -> None:
        """Enable only published variants the detected machine can plausibly drive."""
        report = self._report
        model = self._runtime_choice.model()
        if not isinstance(model, QStandardItemModel):
            return

        if report is None:
            for index in range(self._runtime_choice.count()):
                model.item(index).setEnabled(False)
            self._install.setEnabled(False)
            return

        default_kind = _default_runtime_kind(report.hardware)
        published = set(report.installable)
        for index in range(self._runtime_choice.count()):
            value = self._runtime_choice.itemData(index)
            kind = str(value)
            available = kind in published
            usable, reason = _runtime_backend_usable(kind, report.hardware)
            enabled = available and (usable or self._ignore_hardware_constraints)
            item = model.item(index)
            item.setEnabled(enabled)
            if not available:
                tooltip = f"No pinned {kind} build is published for this platform."
            elif usable:
                tooltip = reason
            elif self._ignore_hardware_constraints:
                tooltip = f"Hardware constraint ignored: {reason}"
            else:
                tooltip = reason
            label = kind.upper()
            if kind == default_kind:
                label += " — recommended for this machine"
            self._runtime_choice.setItemText(index, label)
            self._runtime_choice.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)

        current = model.item(self._runtime_choice.currentIndex())
        if current is None or not current.isEnabled():
            first = next(
                (
                    index
                    for index in range(self._runtime_choice.count())
                    if model.item(index).isEnabled()
                ),
                -1,
            )
            self._runtime_choice.setCurrentIndex(first)
        self._update_install_button()

    def _update_install_button(self, *_args: object) -> None:
        model = self._runtime_choice.model()
        index = self._runtime_choice.currentIndex()
        choice_enabled = (
            isinstance(model, QStandardItemModel) and index >= 0 and model.item(index).isEnabled()
        )
        self._install.setEnabled(
            self._llama_cpp_ready and choice_enabled and not self._progress.isVisible()
        )

    def _on_install(self) -> None:
        kind = self._runtime_choice.currentData()
        wanted = kind if isinstance(kind, str) and kind else None
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._progress.setFormat("Preparing runtime download…")
        self._update_install_button()
        self._engine.install_runtime(
            _INSTALL_RUNTIME_KEY,
            wanted,
            force=self._ignore_hardware_constraints,
        )

    def on_install_progress(self, progress: object) -> None:
        """Render archive download progress emitted by the runtime installer."""
        if not isinstance(progress, RuntimeInstallProgress):
            return
        self._progress.setVisible(True)
        if progress.total_bytes:
            self._progress.setRange(0, 1000)
            fraction = min(1.0, progress.downloaded_bytes / progress.total_bytes)
            self._progress.setValue(round(fraction * 1000))
            self._progress.setFormat(
                f"{progress.artifact_id}: {_bytes(progress.downloaded_bytes)} of "
                f"{_bytes(progress.total_bytes)}"
            )
        else:
            self._progress.setRange(0, 0)
            self._progress.setFormat(
                f"{progress.artifact_id}: {_bytes(progress.downloaded_bytes)}"
            )

    def on_install_finished(self, report: InstallReport) -> None:
        """Restore controls and select the successfully installed backend."""
        self._progress.setVisible(False)
        self._update_install_button()
        self.runtime_selected.emit(report.backend)

    def on_install_failed(self) -> None:
        """Restore controls after a runtime install fails."""
        self._progress.setVisible(False)
        self._update_install_button()


class _RuntimeReport:
    """What one runtime inventory read found.

    A tiny value rather than a tuple, so the two lists cannot be swapped at the call site
    and so the worker returns one object through the engine's single ``task_done`` channel.
    """

    __slots__ = ("backends", "hardware", "installable", "installed")

    def __init__(
        self,
        installed: Sequence[Any],
        backends: Sequence[Any],
        hardware: HardwareProfile,
        installable: Sequence[str],
    ) -> None:
        self.installed = installed
        self.backends = backends
        self.hardware = hardware
        self.installable = tuple(installable)


def _read_runtimes() -> _RuntimeReport:
    """Read the runtime inventory. Runs on a worker thread — it touches the filesystem."""
    from anyinfer.local.backends import available_backends
    from anyinfer.local.hardware import detect
    from anyinfer.local.runtimes import installed_runtimes, load_runtime_table

    hardware = detect()
    installable = tuple(artifact.backend for artifact in load_runtime_table().for_platform())
    return _RuntimeReport(
        installed_runtimes(),
        available_backends(hardware=hardware),
        hardware,
        installable,
    )
