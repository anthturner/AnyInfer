"""Observe the frozen tool-loop corpus through AnyInfer's public Python clients."""

from __future__ import annotations

import argparse
from pathlib import Path

from _tool_loop_python import observe


def main() -> None:
    """Parse command-line arguments and run the observer."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observe", nargs=2, metavar=("INPUTS", "OUTPUT"), required=True)
    inputs, output = parser.parse_args().observe
    observe(Path(inputs), Path(output))


if __name__ == "__main__":
    main()
