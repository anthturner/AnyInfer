"""Evaluation surfaces: multi-target arenas, capability comparison, portability diffs.

Three modules that answer questions *about* targets rather than sending work to one.
`arena` picks between candidate generations, `compare` reports what each target can do and
what it would cost before anything is spent, and `compare_diff` snapshots that report so
two runs can be diffed — the portability check behind ``anyinfer compare --diff``.

They are grouped because they share an audience, not an implementation: someone choosing a
target, or proving a choice still holds. Each stays importable on its own; nothing here
re-exports, because the public names already reach callers through `anyinfer`'s top level
and a second spelling would be a second thing to keep in step.
"""

from __future__ import annotations

# Deliberately empty: the three modules are imported directly, and their public names
# already reach callers through `anyinfer`'s top level. Re-exporting here would create a
# second spelling for every name and a second place to keep in step.
__all__ = []
