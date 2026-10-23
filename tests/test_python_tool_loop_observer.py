from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import _tool_loop_python as observer  # noqa: E402

INPUTS = ROOT / "tests" / "fixtures" / "tool-loop-v1" / "inputs.json"
EXPECTED_IDS = list(observer.EXPECTED_IDS)


def test_admission_checks_frozen_hash_before_decode_and_rejects_invalid_json() -> None:
    with pytest.raises(ValueError, match="frozen corpus SHA-256"):
        observer.admit_corpus(b"not valid UTF-8 or JSON")
    raw = INPUTS.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == observer.FROZEN_INPUT_SHA256
    corpus, actual_digest = observer.admit_corpus(raw)
    assert corpus["profile"] == observer.PROFILE
    assert actual_digest == digest

    for invalid in (
        b"\xef\xbb\xbf" + raw,
        raw.replace(b"\n", b"\r\n"),
        raw[:-1] + b"\xff",
        (raw[:-1] + b" "),
    ):
        with pytest.raises(ValueError):
            observer.admit_corpus(invalid, expected_sha256=hashlib.sha256(invalid).hexdigest())
    duplicate_key = b'{"profile":"tool-loop-v1","profile":"tool-loop-v1"}\n'
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        observer.admit_corpus(
            duplicate_key, expected_sha256=hashlib.sha256(duplicate_key).hexdigest()
        )
    nonfinite = b'{"profile":"tool-loop-v1","x":NaN}\n'
    with pytest.raises(ValueError, match="non-finite"):
        observer.admit_corpus(nonfinite, expected_sha256=hashlib.sha256(nonfinite).hexdigest())
    wrong_profile = b'{"profile":"wrong"}\n'
    with pytest.raises(ValueError, match="unexpected profile"):
        observer.admit_corpus(
            wrong_profile, expected_sha256=hashlib.sha256(wrong_profile).hexdigest()
        )


def test_selected_source_guard_rejects_another_checkout(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="escaped selected checkout"):
        observer.require_selected_source(tmp_path)


def test_actual_full_ten_case_aggregate_validates_and_mutations_fail() -> None:
    corpus, digest = observer.admit_corpus(INPUTS.read_bytes())
    output = observer.execute_all(corpus, digest)
    observer.validate_aggregate(corpus, output)
    assert [record["id"] for record in output["observations"]] == EXPECTED_IDS
    assert output["source_revision"] == observer.source_provenance(digest)["source_revision"]
    assert output["source_dirty"] is observer.source_provenance(digest)["source_dirty"]
    assert len(output["observations"]) == 10
    for case, record in zip(corpus["cases"], output["observations"], strict=True):
        if not record["requests"]:
            continue
        expected_messages = [
            {
                "role": message["role"],
                "content": "".join(part["text"] for part in message["content"]),
            }
            for message in case["request"]["messages"]
        ]
        actual_messages = record["requests"][0]["messages"][: len(expected_messages)]
        assert actual_messages == expected_messages

    _, schema = observer._schema_documents()
    jsonschema.Draft202012Validator.check_schema(schema)
    for edit in (
        lambda records: records.clear(),
        lambda records: records.pop(),
        lambda records: records.__setitem__(1, copy.deepcopy(records[0])),
        lambda records: records[0].__setitem__("id", "unknown-id"),
        lambda records: records.reverse(),
    ):
        changed = copy.deepcopy(output)
        edit(changed["observations"])
        with pytest.raises(ValueError, match="exactly once and in order"):
            observer.validate_aggregate(corpus, changed)


@pytest.mark.asyncio
async def test_each_counter_registration_owns_its_state() -> None:
    corpus, _ = observer.admit_corpus(INPUTS.read_bytes())
    case = next(
        case
        for case in corpus["cases"]
        if any(r["handler"]["kind"] == "counter" for r in case["registrations"])
    )
    registration = next(r for r in case["registrations"] if r["handler"]["kind"] == "counter")
    calls: list[dict[str, object]] = []
    tools = observer.build_tools(
        {"registrations": [registration, copy.deepcopy(registration)]}, calls
    )
    argument = registration["spec"]["parameters"]["required"][0]
    start = registration["handler"]["start"]
    assert await tools[0].call({argument: "first"}) == start + 1
    assert await tools[1].call({argument: "second"}) == start + 1
    assert await tools[0].call({argument: "third"}) == start + 2
