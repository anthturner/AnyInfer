"""``python -m anyinfer_demo`` entry point.

Routed through the package-level `main()` so a missing PySide6 produces the same
one-line install hint as the ``anyinfer-demo`` console script.
"""

from __future__ import annotations

import sys

from . import main

if __name__ == "__main__":
    sys.exit(main())
