"""Offline tests for multi-source pricing drift maintenance tooling."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "tests" / "fixtures" / "pricing"
sys.path.insert(0, str(SCRIPTS))

import check_pricing_drift as cli  # noqa: E402
from pricing_check import (  # noqa: E402
    AVIAN_URL,
    CHUTES_URL,
    OPENROUTER_URL,
    BundledRate,
    RateObservation,
    compare_rates,
    load_bundled,
    parse_avian,
    parse_chutes,
    parse_openrouter,
    render_json,
    render_text,
    selected_rates,
    validate_policies,
)
from pricing_fetch import fetch_json  # noqa: E402
from validate_pricing import validate  # noqa: E402


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"), parse_float=Decimal)


def _pricing() -> dict[str, Any]:
    path = ROOT / "src" / "anyinfer" / "capabilities" / "pricing.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _rate(input_rate: str = "1", output_rate: str = "2") -> BundledRate:
    return BundledRate(
        "provider",
        "Model/Exact",
        Decimal(input_rate),
        Decimal(output_rate),
        "2026-08-01",
        "https://provider.example/pricing",
        "upstream/exact",
    )


def _observation(input_rate: str = "1", output_rate: str = "2") -> RateObservation:
    return RateObservation(
        "checker",
        "direct",
        "upstream/exact",
        Decimal(input_rate),
        Decimal(output_rate),
        "USD",
        "standard",
        "https://provider.example/models",
    )


def test_source_parsers_preserve_exact_units_and_ignore_other_dimensions() -> None:
    openrouter = parse_openrouter(_fixture("openrouter.json"))
    assert openrouter["openai/gpt-5"].input_per_1m == Decimal("1.25")

    chutes = parse_chutes(_fixture("chutes.json"))
    assert chutes["Qwen/Qwen3-32B-TEE"].input_per_1m == Decimal("0.104")
    assert chutes["Qwen/Qwen3-32B-TEE"].output_per_1m == Decimal("0.416")

    avian = parse_avian(_fixture("avian.json"))
    assert avian["deepseek/deepseek-v4-flash"].input_per_1m == Decimal("0.0805")
    assert avian["xiaomi/mimo-v2.5"].output_per_1m == Decimal("0.4")


def test_parsers_reject_float_values_and_schema_renames() -> None:
    assert (
        parse_openrouter({"data": [{"id": "x", "pricing": {"prompt": 0.1, "completion": 1}}]})
        == {}
    )
    assert parse_chutes({"data": [{"id": "x", "pricing": {"input": "1", "output": "2"}}]}) == {}
    assert (
        parse_avian({"data": [{"id": "x", "pricing": {"prompt": "1", "completion": "2"}}]}) == {}
    )
    with pytest.raises(ValueError, match="data array"):
        parse_avian({"models": []})


@pytest.mark.parametrize(
    ("input_rate", "output_rate", "status", "reason"),
    [
        ("1", "2", "match", "rates match"),
        ("1.1", "2", "price-drift", "input rate"),
        ("1", "2.1", "price-drift", "output rate"),
        ("1.1", "2.1", "price-drift", "input and output"),
    ],
)
def test_comparator_classifies_exact_sides(
    input_rate: str, output_rate: str, status: str, reason: str
) -> None:
    observation = _observation(input_rate, output_rate)
    finding = compare_rates(
        [_rate()], {"upstream/exact": observation}, checker="openrouter-models"
    )[0]
    assert finding.status == status
    assert reason in finding.reason


def test_comparator_uses_exact_case_sensitive_identity() -> None:
    finding = compare_rates(
        [_rate()], {"Upstream/Exact": _observation()}, checker="openrouter-models"
    )[0]
    assert finding.status == "upstream-missing"


def test_not_comparable_dimensions_are_reported() -> None:
    observation = RateObservation(
        "checker",
        "direct",
        "upstream/exact",
        Decimal(1),
        Decimal(2),
        "EUR",
        "regional",
        "https://example.com",
    )
    finding = compare_rates(
        [_rate()], {"upstream/exact": observation}, checker="openrouter-models"
    )[0]
    assert finding.status == "not-comparable"


class _Response:
    def __init__(self, body: bytes, *, length: str | None = None) -> None:
        self.body = body
        self.headers = {} if length is None else {"Content-Length": length}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self.body[:size]


class _Opener:
    def __init__(self, result: _Response | Exception) -> None:
        self.result = result

    def open(self, _request: object, *, timeout: int) -> _Response:
        assert timeout == 30
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_bounded_fetch_success_uses_decimal() -> None:
    payload = fetch_json(
        "https://example.com/models", opener=_Opener(_Response(b'{"data":[0.1]}'))
    )
    assert payload["data"] == [Decimal("0.1")]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_Response(b"{}", length="100"), "exceeds"),
        (_Response(b"12345"), "exceeds"),
        (_Response(b"{"), "malformed"),
        (_Response(b"[]"), "root"),
    ],
)
def test_bounded_fetch_failures(response: _Response, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        fetch_json("https://example.com/models", opener=_Opener(response), max_bytes=4)


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("slow"),
        urllib.error.URLError("offline"),
        urllib.error.HTTPError("https://example.com", 503, "no", {}, io.BytesIO()),
    ],
)
def test_bounded_fetch_network_failures(error: Exception) -> None:
    with pytest.raises(RuntimeError, match="request failed"):
        fetch_json("https://example.com/models", opener=_Opener(error))


def test_coverage_policy_is_exhaustive_and_meets_non_regression_gate() -> None:
    rates = load_bundled(_pricing())
    assert validate_policies(rates) == []
    assert len(rates) == 294
    assert len(selected_rates(rates, "openrouter-models")) == 10
    assert len(selected_rates(rates, "chutes-models")) == 13
    assert len(selected_rates(rates, "avian-models")) == 10


def test_unknown_provider_requires_policy() -> None:
    rates = [
        *load_bundled(_pricing()),
        BundledRate(
            "new-provider", "m", Decimal(1), Decimal(2), "2026-01-01", "https://example.com"
        ),
    ]
    assert "no pricing coverage policy" in " ".join(validate_policies(rates))


def _fetch_fixture(url: str) -> dict[str, Any]:
    return {
        OPENROUTER_URL: _fixture("openrouter.json"),
        CHUTES_URL: _fixture("chutes.json"),
        AVIAN_URL: _fixture("avian.json"),
    }[url]


def test_full_fixture_run_matches_33_entries_and_is_stable() -> None:
    report, status = cli.run_check(
        source_names=["openrouter-models", "chutes-models", "avian-models"],
        fetcher=_fetch_fixture,
        checked_at="2026-08-10T12:00:00Z",
    )
    assert status == 0
    assert report["summary"] == {
        "bundled_entries": 294,
        "checked_entries": 33,
        "direct_entries": 23,
        "secondary_entries": 10,
        "drift": 0,
        "source_failures": 0,
    }
    assert render_json(report) == render_json(report)
    assert "33/294" in render_text(report)
    serialized = render_json(report)
    assert "cache_read" not in serialized
    assert "headers" not in serialized


def test_source_outage_outranks_drift_and_keeps_partial_report() -> None:
    def fetch(url: str) -> dict[str, Any]:
        if url == CHUTES_URL:
            raise TimeoutError("offline")
        payload = _fetch_fixture(url)
        if url == OPENROUTER_URL:
            payload = json.loads(json.dumps(payload), parse_float=Decimal)
            payload["data"][0]["pricing"]["prompt"] = "9"
        return payload

    report, status = cli.run_check(
        source_names=["openrouter-models", "chutes-models", "avian-models"],
        fetcher=fetch,
        checked_at="2026-08-10T12:00:00Z",
    )
    assert status == 2
    assert report["summary"]["drift"] == 1
    assert report["summary"]["source_failures"] == 1
    assert any(row["status"] == "source-failed" for row in report["findings"])
    assert not any(
        row["provider"] == "chutes" and row["status"] == "upstream-missing"
        for row in report["findings"]
    )


def test_missing_exact_model_is_drift_not_source_failure() -> None:
    payload = _fixture("avian.json")
    payload["data"] = [
        row for row in payload["data"] if row.get("id") != "deepseek/deepseek-v4-flash"
    ]
    report, status = cli.run_check(
        source_names=["avian-models"],
        fetcher=lambda _url: payload,
        checked_at="2026-08-10T12:00:00Z",
    )
    assert status == 1
    assert report["summary"]["drift"] == 1


def test_github_output_true_only_for_exit_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    cli._write_github_output(False)
    cli._write_github_output(True)
    assert output.read_text(encoding="utf-8") == "drift=false\ndrift=true\n"


def test_pricing_validator_checks_generated_and_policy(tmp_path: Path) -> None:
    data = _pricing()
    data["generated"] = "2999-01-01"
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert "generated 2999-01-01 is in the future" in validate(path)


def test_workflow_hands_off_report_with_scoped_permissions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pricing-refresh.yml").read_text(encoding="utf-8")
    assert "upload-artifact" in workflow
    assert "download-artifact" in workflow
    assert "pricing-drift-report.json" in workflow
    assert "concurrency:" in workflow
    assert "contents: read" in workflow
    assert "pull-requests: write" in workflow
    assert "Run `python scripts/check_pricing_drift.py`" not in workflow
