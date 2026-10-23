"""Controls for privacy/provenance mechanics used by the rich Python observer."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import httpx2
import pytest

from anyinfer.errors import ErrorInfo
from anyinfer.events import RetryScheduled, UsageEstimated
from anyinfer.providers.base import WireRequest
from anyinfer.types.requests import ResolvedTarget

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import observe_python_rich_generation as observer  # noqa: E402
from _rich_observation_python import (  # noqa: E402
    ObservationPrivacyError,
    require_python_source,
    serialization_evidence,
)
from _rich_python_adapters import ScriptLedger  # noqa: E402
from _rich_python_execution import (  # noqa: E402
    ObservedMockTransport,
    _error_projection,
    _session_state,
    _wire_request,
    execute_async,
    telemetry_projection,
)
from observe_python_rich_generation import _request  # noqa: E402


def test_observer_source_guard_selects_checkout_source() -> None:
    assert require_python_source(Path(__file__).parents[1]).name == "python"


@pytest.mark.parametrize("value", ["prefix-answer-marker", "raw-marker-suffix"])
def test_serializer_evidence_rejects_marker_substrings(value: str) -> None:
    with pytest.raises(ObservationPrivacyError):
        serialization_evidence({"payload": value}, scope="telemetry")


def test_request_started_metadata_is_the_only_allowed_metadata_marker() -> None:
    evidence = serialization_evidence(
        {"metadata": {"fixture": "metadata-marker"}},
        scope="telemetry",
        event_type="RequestStarted",
    )
    assert evidence["string_leaves"]
    with pytest.raises(ObservationPrivacyError):
        serialization_evidence({"metadata": {"fixture": "metadata-marker"}}, scope="manifest")
    with pytest.raises(ObservationPrivacyError):
        serialization_evidence(
            {"metadata": {"fixture": "metadata-marker"}},
            scope="telemetry",
            event_type="RequestCompleted",
        )
    with pytest.raises(ObservationPrivacyError):
        serialization_evidence(
            {"detail": "metadata-marker"}, scope="telemetry", event_type="RequestStarted"
        )


def test_evidence_uses_sorted_rfc6901_pointers() -> None:
    evidence = serialization_evidence({"z/a": ["x"], "a~b": "y"}, scope="telemetry")
    assert evidence["field_paths"] == ["/a~0b", "/z~1a", "/z~1a/0"]
    assert [leaf["path"] for leaf in evidence["string_leaves"]] == ["/a~0b", "/z~1a/0"]


def test_wire_session_state_preserves_absent_null_and_value() -> None:
    default_request = WireRequest(model="model", messages=())
    value_request = WireRequest(model="model", messages=(), session_state={"cursor": "next"})

    assert _wire_request(default_request)["session_state"] == {"state": "null"}
    value = _wire_request(value_request)["session_state"]
    assert value["state"] == "value"
    assert value["value"]["canonical_json"] == '{"cursor":"next"}'
    assert _session_state(object()) == {"state": "absent"}


def test_admission_rejects_tampered_bytes_before_decode_or_case_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "tampered.json"
    output_path = tmp_path / "observed.json"
    input_path.write_bytes(b"not-json\xff")
    constructed = False

    def fail_if_constructed(_request: object) -> None:
        nonlocal constructed
        constructed = True
        raise AssertionError("case construction must not run before corpus admission")

    monkeypatch.setattr(observer, "_request", fail_if_constructed)
    with pytest.raises(ValueError, match="not the frozen corpus"):
        observer.observe(input_path, output_path)
    assert not constructed
    assert not output_path.exists()


def test_admission_rejects_wrong_profile_before_case_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "wrong-profile.json"
    output_path = tmp_path / "observed.json"
    raw = json.dumps({"profile": "other-profile", "cases": [{"id": "must-not-run"}]}).encode()
    input_path.write_bytes(raw)
    constructed = False

    def fail_if_constructed(_request: object) -> None:
        nonlocal constructed
        constructed = True
        raise AssertionError("case construction must not run before profile admission")

    monkeypatch.setattr(observer, "_request", fail_if_constructed)
    with pytest.raises(ValueError, match="Unexpected rich-generation profile"):
        observer.observe(input_path, output_path, expected_sha256=hashlib.sha256(raw).hexdigest())
    assert not constructed
    assert not output_path.exists()


def test_additional_telemetry_projection_uses_actual_default_event_serialization() -> None:
    target = ResolvedTarget("fixture", "model")
    failure = ErrorInfo(
        type_name="ProviderError",
        provider="fixture",
        phase="generate",
        retryable=True,
        http_status=None,
        detail="temporary",
    )
    projected = telemetry_projection(
        [
            UsageEstimated("request-1", target, "input_tokens", "tokenizer"),
            RetryScheduled("request-1", target, 1, 0.5, failure),
        ]
    )
    assert [item["stable"]["event"] for item in projected] == [
        "UsageEstimated",
        "RetryScheduled",
    ]
    assert projected[0]["stable"]["method"] == "tokenizer"
    assert projected[1]["stable"]["delay_s"] == 0.5
    assert "/delay_s" in projected[1]["serialized"]["field_paths"]
    assert "/error/detail" in projected[1]["serialized"]["field_paths"]
    assert projected[1]["stable"]["error"]["type_name"] == "ProviderError"


def test_missing_sdk_detail_stays_null() -> None:
    assert _error_projection(ValueError())["detail"] == ""
    assert _error_projection(asyncio.CancelledError())["detail"] is None
    error_info = ErrorInfo(
        type_name="UnsupportedInputException",
        provider="fixture",
        phase="generate",
        retryable=False,
        http_status=None,
        detail=None,
    )
    projected = _error_projection(error_info)
    assert projected["type_name"] == "UnsupportedInputException"
    assert projected["detail"] is None
    assert projected["hint"] is None


def test_http_transport_close_is_recorded_at_actual_aclose() -> None:
    async def check() -> None:
        ledger = ScriptLedger({}, ())

        def respond(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, content=b"ok", request=request)

        transport = ObservedMockTransport(respond, ledger, "fixture")
        response = await transport.handle_async_request(
            httpx2.Request("GET", "https://fixture.invalid/")
        )
        assert response.status_code == 200
        assert ledger.cleanup == []
        await transport.aclose()
        assert ledger.cleanup == ["server:fixture"]

    asyncio.run(check())


def test_stream_cancellation_and_close_effects_are_separate() -> None:
    corpus = json.loads(
        (Path(__file__).parents[1] / "tests/fixtures/rich-generation-v1/inputs.json").read_text()
    )

    async def observe(case_id: str):
        case = next(item for item in corpus["cases"] if item["id"] == case_id)
        ledger = ScriptLedger.from_case(case)
        return await execute_async(case, _request(case["request"]), ledger)

    _, cancel_result, cancel_error, cancel_cleanup, _ = asyncio.run(
        observe("caller-cancellation-cleanup")
    )
    assert cancel_result is None
    assert isinstance(cancel_error, asyncio.CancelledError)
    assert cancel_cleanup

    _, close_result, close_error, close_cleanup, _ = asyncio.run(observe("early-close-cleanup"))
    assert close_result is None
    assert close_error is None
    assert {item["kind"] for item in close_cleanup} >= {
        "reader_cancelled",
    }
