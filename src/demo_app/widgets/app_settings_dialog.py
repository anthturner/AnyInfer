"""Application-wide preferences that do not belong to a provider instance."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..config import DemoConfig

__all__ = ["AppSettingsDialog"]


class AppSettingsDialog(QDialog):
    """Edit demo-wide preferences, separate from provider configuration."""

    def __init__(self, config: DemoConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("App settings")
        self.setMinimumWidth(560)
        self._config = config

        outer = QVBoxLayout(self)
        intro = QLabel(
            "Preferences here apply to the demo as a whole. Provider endpoints and "
            "credentials remain under Provider settings."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        local = QGroupBox("Local inference")
        local_layout = QVBoxLayout(local)
        self._ignore_runtime_hardware = QCheckBox(
            "Ignore hardware constraints when installing llama.cpp runtimes"
        )
        self._ignore_runtime_hardware.setChecked(config.ignore_runtime_hardware_constraints)
        self._ignore_runtime_hardware.setToolTip(
            "Offer runtime variants even when hardware detection says this machine cannot "
            "use them. Platform-incompatible or unpublished builds remain unavailable."
        )
        local_layout.addWidget(self._ignore_runtime_hardware)
        warning = QLabel(
            "Use this only when detection is wrong or the runtime will be copied to a "
            "different compatible machine. An unusable backend can install successfully "
            "and still fail when llama-server starts."
        )
        warning.setWordWrap(True)
        warning.setObjectName("HintText")
        local_layout.addWidget(warning)
        outer.addWidget(local)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def result_config(self) -> DemoConfig:
        """Return the original configuration with the edited preferences replaced."""
        return replace(
            self._config,
            ignore_runtime_hardware_constraints=self._ignore_runtime_hardware.isChecked(),
        )
