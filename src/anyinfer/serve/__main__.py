"""Run the OpenAI-compatible sidecar with ``python -m anyinfer.serve``."""

from __future__ import annotations

import sys

from ..cli import main

if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main(["serve", *sys.argv[1:]]))
