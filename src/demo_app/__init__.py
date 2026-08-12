"""AnyInfer Demo — a PySide6 pack-in application showcasing the library.

This is a *reference integration*, not part of the library's public surface. It exists to
demonstrate, in a form a person can click through, the things AnyInfer claims to provide:

- **Generic provider configuration** driven entirely by
  `ProviderSetupSpec` — every provider describes its own setup fields, so the settings
  dialog contains no per-provider ``if/elif`` branch and picks up third-party adapters
  automatically.
- **Streaming as the primitive** — the chat view renders
  `StreamEvent` values as they arrive, including the
  centrally-measured first-token mark.
- **The typed telemetry contract** — a live event inspector fed by a plain
  `Observer`.
- **Structured output with bounded repair** — a schema panel that shows the mechanism the
  core selected and how many repair rounds it took.
- **Routing and fallback** — an editable target chain whose attempts are visible per request.

It runs with no credentials and no network by default, against the in-process fakes from
`anyinfer.testing.fakes`.

Run it with ``anyinfer-demo`` or ``python -m demo_app``.
"""

__all__ = ["main"]

# ASCII only: this prints on consoles whose code page cannot encode typographic dashes.
_PYSIDE_HINT = (
    "The AnyInfer demo needs PySide6, which the base install leaves out; "
    'run: pip install "anyinfer[demo]"'
)


def main() -> int:
    """Console-script entry point. Imported lazily so ``--help`` needs no Qt."""
    from .app import main as _main

    try:
        return _main()
    except ModuleNotFoundError as error:
        # A bare `pip install anyinfer` has no Qt; die with one actionable line
        # instead of a traceback.
        if error.name and error.name.partition(".")[0] == "PySide6":
            import sys

            print(_PYSIDE_HINT, file=sys.stderr)
            return 1
        raise
