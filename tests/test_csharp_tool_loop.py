"""Focused controls for the strict tool-loop observation checker."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
SCRIPT = ROOT / "scripts" / "check_csharp_tool_loop.py"
SPEC = importlib.util.spec_from_file_location("check_csharp_tool_loop", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def _input() -> tuple[dict[str, object], tuple[str, ...]]:
    return CHECKER.read_cases(CHECKER.DEFAULT_INPUT)


def _record(identifier: str, entry_point: str = "async_run_tools") -> dict[str, object]:
    return {
        "id": identifier,
        "public": {
            "entry_point": entry_point,
            "result": {
                "text": "done",
                "finish_reason": "stop",
                "target": {"provider_id": "openai-compat", "model": "tool-loop-model"},
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            },
            "error": None,
        },
        "requests": [
            {
                "model": "tool-loop-model",
                "messages": [{"role": "user", "content": "input"}],
                "tools": [],
                "tool_choice": "auto",
            }
        ],
        "handler_calls": [],
    }


def _envelope(
    *, runtime: str = "python", revision: str = "a" * 40, dirty: bool = False
) -> dict[str, object]:
    _, identifiers = _input()
    return {
        "profile": CHECKER.PROFILE,
        "runtime": runtime,
        "source_revision": revision,
        "source_dirty": dirty,
        "corpus_sha256": CHECKER.FROZEN_CORPUS_SHA256,
        "observations": [
            _record(
                identifier,
                "sync_run_tools" if identifier == "tools-sync-path" else "async_run_tools",
            )
            for identifier in identifiers
        ],
    }


def test_valid_closed_envelope_and_portable_loop_error_mapping(tmp_path: Path) -> None:
    _, identifiers = _input()
    python, native = _envelope(), _envelope(runtime="csharp")
    python["observations"][5]["public"] = {
        "entry_point": "async_run_tools",
        "result": None,
        "error": {
            "type": "ToolLoopError",
            "message": "python wording",
            "detail": "detail",
            "hint": "hint",
        },
    }
    native["observations"][5]["public"] = {
        "entry_point": "async_run_tools",
        "result": None,
        "error": {
            "type": "ToolLoopException",
            "message": "native wording",
            "detail": "other",
            "hint": "other",
        },
    }
    python_path, native_path = tmp_path / "python.json", tmp_path / "native.json"
    python_path.write_text(json.dumps(python), encoding="utf-8")
    native_path.write_text(json.dumps(native), encoding="utf-8")
    left = CHECKER._validate_envelope(
        python_path, runtime="python", identifiers=identifiers, digest=CHECKER.FROZEN_CORPUS_SHA256
    )
    right = CHECKER._validate_envelope(
        native_path, runtime="csharp", identifiers=identifiers, digest=CHECKER.FROZEN_CORPUS_SHA256
    )
    assert (
        CHECKER.compare_case(identifiers[5], left["observations"][5], right["observations"][5])
        is None
    )


def test_loop_error_diagnostic_nulls_are_portable_only_at_public_error_paths() -> None:
    _, identifiers = _input()
    python, native = _envelope(), _envelope(runtime="csharp")
    python["observations"][5]["public"] = {
        "entry_point": "async_run_tools",
        "result": None,
        "error": {
            "type": "ToolLoopError",
            "message": "python wording",
            "detail": "python detail",
            "hint": "python hint",
        },
    }
    native["observations"][5]["public"] = {
        "entry_point": "async_run_tools",
        "result": None,
        "error": {
            "type": "ToolLoopException",
            "message": "native wording",
            "detail": None,
            "hint": None,
        },
    }
    assert (
        CHECKER.compare_case(identifiers[5], python["observations"][5], native["observations"][5])
        is None
    )
    assert CHECKER._equal(
        {"raw": {"detail": "python detail", "hint": "python hint"}},
        {"raw": {"detail": None, "hint": None}},
    )


def test_loop_error_class_mapping_is_directional() -> None:
    _, identifiers = _input()
    python, native = _envelope(), _envelope(runtime="csharp")
    error = {"message": "diagnostic"}
    python["observations"][5]["public"] = {
        "entry_point": "async_run_tools",
        "result": None,
        "error": {"type": "ToolLoopException", **error},
    }
    native["observations"][5]["public"] = {
        "entry_point": "async_run_tools",
        "result": None,
        "error": {"type": "ToolLoopError", **error},
    }
    with pytest.raises(CHECKER.observation.ObservationError, match="Python"):
        CHECKER.compare_case(identifiers[5], python["observations"][5], native["observations"][5])
    python["observations"][5]["public"]["error"]["type"] = "ToolLoopError"
    with pytest.raises(CHECKER.observation.ObservationError, match="C#"):
        CHECKER.compare_case(identifiers[5], python["observations"][5], native["observations"][5])


@pytest.mark.parametrize("mutation", ["missing", "unknown", "duplicate", "reordered"])
def test_envelope_requires_exact_input_order_and_ids(tmp_path: Path, mutation: str) -> None:
    _, identifiers = _input()
    value = _envelope()
    records = value["observations"]
    if mutation == "missing":
        records.pop()
    elif mutation == "unknown":
        records[-1]["id"] = "unknown"
    elif mutation == "duplicate":
        records[-1]["id"] = records[0]["id"]
    else:
        records[0], records[1] = records[1], records[0]
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(CHECKER.observation.ObservationError):
        CHECKER._validate_envelope(
            path, runtime="python", identifiers=identifiers, digest=CHECKER.FROZEN_CORPUS_SHA256
        )


def test_comparison_is_strict_for_handler_wire_result_and_raw_lookalikes() -> None:
    _, identifiers = _input()
    left, right = _envelope(), _envelope(runtime="csharp")
    for location, replacement in (
        ("handler", "changed"),
        ("wire", "other-model"),
        ("result", "changed"),
    ):
        changed = copy.deepcopy(right["observations"][0])
        if location == "handler":
            changed["handler_calls"] = [
                {
                    "registration_index": 0,
                    "name": "echo",
                    "arguments": {},
                    "returned_data": replacement,
                }
            ]
        elif location == "wire":
            changed["requests"][0]["model"] = replacement
        else:
            changed["public"]["result"]["text"] = replacement
        assert CHECKER.compare_case(identifiers[0], left["observations"][0], changed)
    raw_left = {"payload": {"error": {"type": "ToolLoopError", "message": "one"}}}
    raw_right = {"payload": {"error": {"type": "ToolLoopException", "message": "one"}}}
    assert CHECKER._equal(raw_left, raw_right)


def test_rejects_bad_provenance_and_unapproved_error_class(tmp_path: Path) -> None:
    _, identifiers = _input()
    value = _envelope()
    path = tmp_path / "evidence.json"
    for field, value_to_set in (("corpus_sha256", "0" * 64), ("source_dirty", "false")):
        broken = copy.deepcopy(value)
        broken[field] = value_to_set
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(CHECKER.observation.ObservationError):
            CHECKER._validate_envelope(
                path,
                runtime="python",
                identifiers=identifiers,
                digest=CHECKER.FROZEN_CORPUS_SHA256,
            )
    native = copy.deepcopy(value["observations"][0])
    native["public"] = {
        "entry_point": "async_run_tools",
        "result": None,
        "error": {"type": "ValueError", "message": "wrong"},
    }
    with pytest.raises(CHECKER.observation.ObservationError, match="C#"):
        CHECKER.compare_case(identifiers[0], value["observations"][0], native)


def test_handshake_rejects_stale_source_and_dirty_state() -> None:
    python, native = _envelope(), _envelope(runtime="csharp")
    native["source_revision"] = "b" * 40
    with pytest.raises(CHECKER.observation.ObservationError, match="revision"):
        CHECKER.validate_handshake(python, native, identity=None)
    native = _envelope(runtime="csharp")
    native["source_dirty"] = True
    with pytest.raises(CHECKER.observation.ObservationError, match="dirty"):
        CHECKER.validate_handshake(python, native, identity=None)
