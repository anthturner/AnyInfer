"""The shared provider conformance suite.

Every adapter — built-in or third-party — proves it satisfies the contract by running this
suite. The conformance matrix in the documentation is generated from its results, so a
provider page can never claim a capability the suite did not verify.

**Division of labor.** This suite proves *our code matches our claims*. The drift check
(``contracts/DRIFT-CHECK.md``) proves *our claims still match upstream*.

**Usage.** A third-party adapter certifies itself by pointing the suite at a factory:

```python
from anyinfer.testing import Capabilities, ConformanceHarness, run_conformance

harness = ConformanceHarness(
    provider_id="acme-llm",
    model="acme-model-1",
    build_client=my_client_factory,
    supports=Capabilities(tools=True, structured_output=False),
)
results = await run_conformance(harness)
assert all(r.passed or r.skipped for r in results)
```

Cases a provider genuinely cannot support are declared in `Capabilities` and reported
as ``skipped`` rather than failing — an honest ➖ in the matrix, not a silent pass.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..types.events import (
    AttemptFailed,
    ReasoningDelta,
    StreamEnded,
    TextDelta,
    TimingMark,
    ToolCallDelta,
    UsageUpdate,
)
from ..types.requests import ToolSpec

if TYPE_CHECKING:
    from .._client.async_client import AsyncClient

__all__ = [
    "CONFORMANCE_CASES",
    "PROBE_SCHEMA",
    "PROBE_TOOL",
    "Capabilities",
    "CaseResult",
    "ConformanceCase",
    "ConformanceHarness",
    "matrix_row",
    "results_to_json",
    "run_conformance",
]

PROBE_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
"""The schema every structured-output probe requests."""

PROBE_TOOL = ToolSpec(
    name="lookup",
    description="Look up a value by key.",
    parameters={
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "required": ["key"],
    },
)
"""The tool every tool-calling probe advertises."""


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What a provider claims to support, so unsupported cases skip honestly.

    Each flag gates at least one case of the conformance matrix. Setting a flag to
    ``False`` is a documented ➖, not a pass.

    Attributes:
        list_models: Model discovery returns the provider's models.
        health: The provider answers a health probe.
        non_streaming: Whole-response generation, including finish-reason normalization.
        streaming: Incremental generation with the event-ordering guarantees.
        ttft: Time to first token is measurable on streams.
        usage: Token usage is reported, including usage that trails the finish reason.
        tools: Tool calls surface completely, streaming and non-streaming.
        reasoning: Reasoning streams on its own channel, excluded from the answer text.
        structured_output: Schema-constrained generation yields a validated value.
        repair: An invalid structured value can be repaired within the attempt budget.
        retry_after: Rate limiting surfaces as a retryable, recorded attempt.
        error_mapping: Provider failures map to typed errors with a correct retry flag.
        byte_cap: An oversized response is rejected rather than silently truncated.
    """

    list_models: bool = True
    health: bool = True
    non_streaming: bool = True
    streaming: bool = True
    ttft: bool = True
    usage: bool = True
    tools: bool = True
    reasoning: bool = True
    structured_output: bool = True
    repair: bool = True
    retry_after: bool = True
    error_mapping: bool = True
    byte_cap: bool = True


@dataclass(frozen=True, slots=True)
class ConformanceHarness:
    """Everything the suite needs to exercise one adapter.

    Attributes:
        provider_id: The provider under test.
        model: Model id to send.
        build_client: Builds a client whose scripted responses match ``scenario``. The
            suite passes a scenario name so the harness can program its fake or select its
            cassette.
        supports: Declared capabilities; unsupported cases are skipped.
    """

    provider_id: str
    model: str
    build_client: Callable[[str], Awaitable[AsyncClient]]
    supports: Capabilities = Capabilities()

    @property
    def target(self) -> str:
        """The target string for this harness."""
        return f"{self.provider_id}:{self.model}"


@dataclass(frozen=True, slots=True)
class CaseResult:
    """The outcome of one conformance case.

    Attributes:
        name: The case's row name in the conformance matrix.
        passed: Whether the check succeeded. Also ``False`` for skipped cases; check
            ``skipped`` first.
        skipped: The harness declared the capability unsupported, so the case did not run.
        detail: Why the case failed (truncated), or why it was skipped; empty on a pass.
    """

    name: str
    passed: bool
    skipped: bool = False
    detail: str = ""

    @property
    def symbol(self) -> str:
        """Matrix symbol: ``✅`` pass, ``➖`` declared-unsupported, ``❌`` failure."""
        if self.skipped:
            return "➖"
        return "✅" if self.passed else "❌"


@dataclass(frozen=True, slots=True)
class ConformanceCase:
    """One named check.

    Attributes:
        name: Matrix row name.
        scenario: Scenario key handed to the harness's client factory.
        requires: Capability flag gating this case.
        run: The check itself; raises ``AssertionError`` on failure.
    """

    name: str
    scenario: str
    requires: str
    run: Callable[[AsyncClient, ConformanceHarness], Awaitable[None]]


# ---- the cases -----------------------------------------------------------------------


async def _case_list_models(client: AsyncClient, h: ConformanceHarness) -> None:
    models = await client.models(h.provider_id)
    assert isinstance(models, Sequence), "list_models must return a sequence"
    assert all(m.id for m in models), "every discovered model needs a non-empty id"


async def _case_health(client: AsyncClient, h: ConformanceHarness) -> None:
    health = await client.health(h.provider_id)
    assert isinstance(health.ok, bool), "health must report a boolean"


async def _case_non_streaming(client: AsyncClient, h: ConformanceHarness) -> None:
    result = await client.generate("Say hello.", target=h.target)
    assert result.text, "a non-streaming generation must produce text"
    assert result.target.provider_id == h.provider_id
    assert result.finish_reason in {
        "stop", "length", "tool_calls", "content_filter", "other"
    }


async def _case_streaming(client: AsyncClient, h: ConformanceHarness) -> None:
    stream = client.stream("Say hello.", target=h.target)
    deltas: list[str] = []
    async for event in stream:
        if isinstance(event, TextDelta):
            deltas.append(event.text)
    assert deltas, "a streaming generation must emit text deltas"
    assert "".join(deltas) == stream.result.text, (
        "concatenated deltas must equal the final text (ordering guarantee 4)"
    )


async def _case_event_ordering(client: AsyncClient, h: ConformanceHarness) -> None:
    stream = client.stream("Say hello.", target=h.target)
    events = [event async for event in stream]

    ends = [e for e in events if isinstance(e, StreamEnded)]
    assert len(ends) == 1, "exactly one StreamEnded (guarantee 3)"
    assert isinstance(events[-1], StreamEnded), "StreamEnded must be last (guarantee 3)"

    marks = [e for e in events if isinstance(e, TimingMark)]
    assert marks and marks[0].name == "attempt_start", (
        "attempt_start must be the first mark (guarantee 2)"
    )

    content_types = (TextDelta, ReasoningDelta, ToolCallDelta)
    first_content = next(
        (i for i, e in enumerate(events) if isinstance(e, content_types)), None
    )
    if first_content is not None:
        first_tokens = [
            i for i, e in enumerate(events)
            if isinstance(e, TimingMark) and e.name == "first_token"
        ]
        assert len(first_tokens) == 1, "exactly one first_token mark (guarantee 2)"
        assert first_tokens[0] < first_content, (
            "first_token must immediately precede the first content event (guarantee 2)"
        )

    failures = [i for i, e in enumerate(events) if isinstance(e, AttemptFailed)]
    if failures and first_content is not None:
        assert max(failures) < first_content, (
            "AttemptFailed events precede content (guarantee 1)"
        )


async def _case_ttft(client: AsyncClient, h: ConformanceHarness) -> None:
    stream = client.stream("Say hello.", target=h.target)
    marks: list[TimingMark] = []
    async for event in stream:
        if isinstance(event, TimingMark):
            marks.append(event)
    result = stream.result
    assert any(m.name == "first_token" for m in marks), "TTFT must be measurable"
    assert result.timing.first_token_ms is not None
    assert result.timing.first_token_ms >= 0
    assert result.timing.total_ms >= result.timing.first_token_ms


async def _case_usage(client: AsyncClient, h: ConformanceHarness) -> None:
    result = await client.generate("Say hello.", target=h.target)
    usage = result.usage
    assert usage.output_tokens is not None, "usage must report output tokens"
    if usage.input_tokens is not None and usage.output_tokens is not None:
        assert usage.total_tokens == usage.input_tokens + usage.output_tokens, (
            "total_tokens must agree with its parts"
        )


async def _case_usage_survives_streaming(client: AsyncClient, h: ConformanceHarness) -> None:
    """Usage often arrives after the finish reason, in a trailing chunk.

    Closing the stream on ``finish_reason`` instead of the terminal sentinel silently
    undercounts tokens — a failure mode with real precedent across gateways.
    """
    stream = client.stream("Say hello.", target=h.target)
    saw_usage_event = False
    async for event in stream:
        if isinstance(event, UsageUpdate):
            saw_usage_event = True
    assert stream.result.usage.output_tokens is not None, (
        "a trailing usage chunk must reach the final result"
    )
    assert saw_usage_event, "usage must also surface as a stream event"


async def _case_tool_calls(client: AsyncClient, h: ConformanceHarness) -> None:
    result = await client.generate(
        "Look up the key 'alpha'.", target=h.target, tools=[PROBE_TOOL]
    )
    assert result.tool_calls, "the provider must surface tool calls"
    call = result.tool_calls[0]
    assert call.id, "every tool call needs an id (synthesized if the provider omits one)"
    assert call.name, "every tool call needs a name"
    assert isinstance(call.arguments, dict), "arguments must parse to a mapping"
    assert result.finish_reason == "tool_calls"


async def _case_streaming_tool_calls(client: AsyncClient, h: ConformanceHarness) -> None:
    """Tool-call arguments stream as fragments and must merge by index, not by arrival."""
    stream = client.stream("Look up the key 'alpha'.", target=h.target, tools=[PROBE_TOOL])
    fragments = 0
    async for event in stream:
        if isinstance(event, ToolCallDelta):
            fragments += 1
    result = stream.result
    assert fragments, "tool calls must stream as ToolCallDelta events"
    assert result.tool_calls, "fragments must reassemble into complete calls"
    assert isinstance(result.tool_calls[0].arguments, dict)


async def _case_reasoning(client: AsyncClient, h: ConformanceHarness) -> None:
    """Reasoning streams as its own channel and stays out of the answer text."""
    from ..types.events import ReasoningDelta as _ReasoningDelta

    stream = client.stream("Think it through.", target=h.target, reasoning="low")
    fragments: list[str] = []
    async for event in stream:
        if isinstance(event, _ReasoningDelta):
            fragments.append(event.text)
    result = stream.result
    thinking = "".join(fragments)
    assert thinking, "a reasoning-capable provider must emit ReasoningDelta events"
    assert thinking not in result.text, "reasoning must be excluded from the answer text"


async def _case_structured_output(client: AsyncClient, h: ConformanceHarness) -> None:
    result = await client.generate(
        "Answer with the word 'ok'.", target=h.target, schema=PROBE_SCHEMA
    )
    assert result.structured is not None, "a schema request must yield a structured value"
    assert isinstance(result.structured, dict)
    assert "answer" in result.structured, "the result must satisfy the original schema"
    assert result.structured_mechanism is not None, "the mechanism used must be recorded"


async def _case_repair(client: AsyncClient, h: ConformanceHarness) -> None:
    from ..types.requests import Repair

    result = await client.generate(
        "Answer with the word 'ok'.",
        target=h.target,
        schema=PROBE_SCHEMA,
        repair=Repair(max_attempts=1),
    )
    assert result.structured is not None, "repair must recover a valid value"
    assert result.repair_attempts >= 1, "the repair must be recorded on the result"


async def _case_error_mapping(client: AsyncClient, h: ConformanceHarness) -> None:
    from ..errors import AllTargetsFailedError

    try:
        await client.generate("Say hello.", target=h.target)
    except AllTargetsFailedError as exc:
        assert exc.attempts, "a failure must carry its attempt trail"
        error = exc.attempts[-1].error
        assert error is not None, "the failed attempt must record an error"
        assert error.type_name, "the error must be typed"
        assert error.retryable is False, "an auth failure must not be marked retryable"
        return
    raise AssertionError("expected the scripted error to surface")


async def _case_retry_after(client: AsyncClient, h: ConformanceHarness) -> None:
    result = await client.generate("Say hello.", target=h.target)
    assert result.attempts, "the attempt trail must be populated"
    retried = [a for a in result.attempts if a.outcome == "retried"]
    assert retried, "a rate-limited attempt must be recorded as retried"
    assert retried[0].error is not None
    assert retried[0].error.retryable is True


async def _case_byte_cap(client: AsyncClient, h: ConformanceHarness) -> None:
    from ..errors import AllTargetsFailedError, StreamProtocolError

    try:
        await client.generate("Say hello.", target=h.target, max_response_bytes=64)
    except (AllTargetsFailedError, StreamProtocolError):
        return
    raise AssertionError("an oversized response must be rejected, not truncated silently")


async def _case_unknown_finish_reason(client: AsyncClient, h: ConformanceHarness) -> None:
    """``finish_reason`` is an open enum; an unrecognized value must not break reassembly."""
    result = await client.generate("Say hello.", target=h.target)
    assert result.finish_reason in {
        "stop", "length", "tool_calls", "content_filter", "other"
    }, "unknown finish reasons must normalize, not propagate"


CONFORMANCE_CASES: tuple[ConformanceCase, ...] = (
    ConformanceCase("list_models", "default", "list_models", _case_list_models),
    ConformanceCase("health", "default", "health", _case_health),
    ConformanceCase("non_streaming", "default", "non_streaming", _case_non_streaming),
    ConformanceCase("streaming", "default", "streaming", _case_streaming),
    ConformanceCase("event_ordering", "default", "streaming", _case_event_ordering),
    ConformanceCase("ttft", "default", "ttft", _case_ttft),
    ConformanceCase("usage", "default", "usage", _case_usage),
    ConformanceCase(
        "usage_survives_streaming", "default", "usage", _case_usage_survives_streaming
    ),
    ConformanceCase("tool_calls", "tools", "tools", _case_tool_calls),
    ConformanceCase("streaming_tool_calls", "tools", "tools", _case_streaming_tool_calls),
    ConformanceCase("reasoning", "reasoning", "reasoning", _case_reasoning),
    ConformanceCase(
        "structured_output", "structured", "structured_output", _case_structured_output
    ),
    ConformanceCase("schema_repair", "repair", "repair", _case_repair),
    ConformanceCase("error_mapping", "auth_error", "error_mapping", _case_error_mapping),
    ConformanceCase("retry_after", "rate_limited", "retry_after", _case_retry_after),
    ConformanceCase("byte_cap", "oversized", "byte_cap", _case_byte_cap),
    ConformanceCase(
        "unknown_finish_reason", "odd_finish", "non_streaming", _case_unknown_finish_reason
    ),
)
"""Every conformance case, in matrix order."""


async def run_conformance(
    harness: ConformanceHarness,
    *,
    only: Sequence[str] | None = None,
) -> list[CaseResult]:
    """Run the suite against one adapter.

    Args:
        harness: The adapter under test.
        only: Restrict the run to these case names.

    Returns:
        One `CaseResult` per case, in matrix order.
    """
    results: list[CaseResult] = []
    for case in CONFORMANCE_CASES:
        if only is not None and case.name not in only:
            continue
        if not getattr(harness.supports, case.requires, True):
            results.append(
                CaseResult(case.name, passed=False, skipped=True, detail="declared unsupported")
            )
            continue

        client = await harness.build_client(case.scenario)
        try:
            await case.run(client, harness)
            results.append(CaseResult(case.name, passed=True))
        except AssertionError as exc:
            results.append(CaseResult(case.name, passed=False, detail=str(exc)[:300]))
        except Exception as exc:  # noqa: BLE001 — any failure is a conformance failure
            results.append(
                CaseResult(
                    case.name,
                    passed=False,
                    detail=f"{type(exc).__name__}: {exc}"[:300],
                )
            )
        finally:
            await client.aclose()
    return results


def matrix_row(provider_id: str, results: Sequence[CaseResult]) -> str:
    """Render results as one Markdown conformance-matrix row.

    Provider documentation pages embed this so a page cannot overstate what the suite
    actually verified.
    """
    cells = " | ".join(r.symbol for r in results)
    return f"| {provider_id} | {cells} |"


def results_to_json(provider_id: str, results: Sequence[CaseResult]) -> str:
    """Serialize results for the docs build."""
    return json.dumps(
        {
            "provider": provider_id,
            "cases": [
                {
                    "name": r.name,
                    "status": "skipped" if r.skipped else ("pass" if r.passed else "fail"),
                    "detail": r.detail,
                }
                for r in results
            ],
        },
        indent=2,
    )
