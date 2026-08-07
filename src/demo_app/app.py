"""Application bootstrap: argument parsing, Qt setup, and window construction."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import CONFIG_PATH, DemoConfig, default_config

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Kept free of Qt imports so ``--help`` works even where no display is available.
    """
    parser = argparse.ArgumentParser(
        prog="anyinfer-demo",
        description=(
            "A PySide6 demonstration of the AnyInfer library: generic provider setup, "
            "streaming, telemetry, structured output, and routing."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help=f"configuration file to use (default: {CONFIG_PATH})",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="ignore saved settings and start from the offline defaults",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the demo application.

    Args:
        argv: Command-line arguments; defaults to `sys.argv`.

    Returns:
        The Qt exit code.
    """
    args = build_parser().parse_args(argv)

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .assets import asset_path
    from .main_window import MainWindow
    from .theme import apply_theme

    config = default_config() if args.reset else DemoConfig.load(args.config)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("AnyInfer Demo")
    app.setApplicationVersion(_library_version())
    app.setWindowIcon(QIcon(str(asset_path("anyinfer-icon-512.png"))))
    apply_theme(app, config.theme)

    # The window saves back to the same file the session was started from.
    window = MainWindow(config, config_path=args.config)
    window.show()
    return int(app.exec())


def _library_version() -> str:
    """The AnyInfer version the demo is running against."""
    import anyinfer

    return str(anyinfer.__version__)
