"""Run the shared conformance suite against the built-in adapters.

This is the M0 instantiation: openai-compat in fake-server mode. Later milestones add a row
per adapter, and cassette mode once real traffic has been recorded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import anyinfer as ai
from anyinfer.testing.conformance import (
    CONFORMANCE_CASES,
    Capabilities,
    ConformanceHarness,
    matrix_row,
    results_to_json,
    run_conformance,
)
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

PROBE_ANSWER = json.dumps({"answer": "ok"})


def _server_for(scenario: str) -> FakeOpenAIServer:
    """Program the fake server for one conformance scenario."""
    if scenario == "tools":
        return FakeOpenAIServer(
            FakeResponse(
                text="",
                tool_calls=(("call_0", "lookup", '{"key": "alpha"}'),),
                finish_reason="tool_calls",
            )
        )
    if scenario == "structured":
        return FakeOpenAIServer(FakeResponse(text=PROBE_ANSWER))
    if scenario == "repair":
        return FakeOpenAIServer(
            [FakeResponse(text='{"wrong": true}'), FakeResponse(text=PROBE_ANSWER)]
        )
    if scenario == "auth_error":
        return FakeOpenAIServer(FakeResponse(status=401, error_message="invalid key"))
    if scenario == "rate_limited":
        return FakeOpenAIServer(
            [
                FakeResponse(status=429, error_message="slow down", headers={"retry-after": "0"}),
                FakeResponse(text="recovered"),
            ]
        )
    if scenario == "oversized":
        return FakeOpenAIServer(FakeResponse(text="x" * 20_000))
    if scenario == "odd_finish":
        return FakeOpenAIServer(FakeResponse(text="hello", finish_reason="model_decided"))
    return FakeOpenAIServer(FakeResponse(text="Hello from the fake provider."))


async def _build_client(scenario: str) -> ai.AsyncClient:
    server = _server_for(scenario)
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ],
        route=ai.Route(
            targets=("openai-compat:fake-model-small",),
            retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
        ),
    )


HARNESS = ConformanceHarness(
    provider_id="openai-compat",
    model="fake-model-small",
    build_client=_build_client,
    supports=Capabilities(
        # The generic dialect has no reasoning channel of its own; providers that do
        # (openai, anthropic) enable this row in their own harness.
        reasoning=False,
        cancellation=True,
    ),
)


def test_the_published_case_table_lists_every_case() -> None:
    """The matrix's own legend must enumerate what the matrix actually ran.

    The table is hand-written prose beside a generated table, which is exactly the shape
    that drifts: seven cases had accumulated without an entry before this test existed,
    so a reader of the published matrix saw seven unexplained columns.
    """
    import re

    footer = (Path(__file__).resolve().parent.parent / "workspace.py").read_text(
        encoding="utf-8"
    )
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", footer, re.M))
    undocumented = [c.name for c in CONFORMANCE_CASES if c.name not in documented]
    assert undocumented == [], (
        f"add these to the matrix legend in workspace.py: {', '.join(undocumented)}"
    )


@pytest.mark.parametrize("case", CONFORMANCE_CASES, ids=lambda c: c.name)
async def test_openai_compat_conformance(case: object) -> None:
    """Each conformance case is its own test, so failures name the broken behavior."""
    name = case.name  # type: ignore[attr-defined]
    results = await run_conformance(HARNESS, only=[name])
    assert results, f"case {name} did not run"
    result = results[0]
    assert result.passed or result.skipped, f"{name} failed: {result.detail}"


async def test_full_suite_produces_a_matrix_row() -> None:
    """The matrix row published in the docs is generated from a real run."""
    results = await run_conformance(HARNESS)

    assert len(results) == len(CONFORMANCE_CASES)
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, f"conformance failures: {[(f.name, f.detail) for f in failures]}"

    row = matrix_row("openai-compat", results)
    assert row.startswith("| openai-compat |")
    assert "❌" not in row

    payload = json.loads(results_to_json("openai-compat", results))
    assert payload["provider"] == "openai-compat"
    assert {c["status"] for c in payload["cases"]} <= {"pass", "skipped"}
