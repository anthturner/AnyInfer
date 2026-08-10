"""Bounded multi-target arena execution, selection, and surface parity."""

from __future__ import annotations

import asyncio
import json
from dataclasses import fields
from decimal import Decimal

import httpx2
import pytest

import anyinfer as ai
from anyinfer.arena import Candidate, candidate_envelope, select_candidates
from anyinfer.registry import ProviderRegistry
from anyinfer.serve.openai_codec import request_from_openai, request_to_openai
from anyinfer.testing import ScriptedFailure, ScriptedModel, ScriptedProvider
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse


class _Events:
    def __init__(self) -> None:
        self.items: list[object] = []

    def on_event(self, event: object) -> None:
        self.items.append(event)


def _client(
    *models: ScriptedModel,
    arena: ai.ArenaPolicy | None = None,
    spend: ai.SpendPolicy | None = None,
) -> tuple[ai.AsyncClient, ScriptedProvider]:
    provider = ScriptedProvider("panel", models)
    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    provider.register(registry)
    return (
        ai.AsyncClient(
            [provider.settings()],
            registry=registry,
            use_default_catalog=False,
            arena=arena,
            spend=spend,
        ),
        provider,
    )


async def test_partial_failure_is_evidence_and_usage_is_not_authoritative() -> None:
    client, provider = _client(
        ScriptedModel("good", text="usable"),
        ScriptedModel("bad", failures=(ScriptedFailure(status=401, message="no access"),)),
    )
    async with client:
        result = await client.generate(
            "question",
            arena=ai.ArenaPolicy(("panel:good", "panel:bad")),
        )

    assert result.text == "usable"
    assert result.arena is not None
    assert result.arena.candidates[1].error is not None
    assert result.arena.usage_complete is False
    assert result.arena.usage == ai.Usage()
    assert provider.call_count() == 2


async def test_all_failures_preserve_every_attempt() -> None:
    client, _ = _client(
        ScriptedModel("a", failures=(ScriptedFailure(status=401),)),
        ScriptedModel("b", failures=(ScriptedFailure(status=401),)),
    )
    async with client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate("question", arena=ai.ArenaPolicy(("panel:a", "panel:b")))

    assert len(excinfo.value.attempts) == 2


async def test_cancelling_an_arena_stops_pending_candidates() -> None:
    rendered = FakeOpenAIServer(FakeResponse(text="done")).transport()
    slow_started = asyncio.Event()
    slow_cancelled = asyncio.Event()
    requested: list[str] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        model = str(json.loads(request.content)["model"])
        requested.append(model)
        if model == "slow":
            slow_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                slow_cancelled.set()
                raise
        return rendered.handler(request)

    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://arena.invalid/v1",
                transport=httpx2.MockTransport(handler),
            )
        ]
    )
    async with client:
        task = asyncio.create_task(
            client.generate(
                "question",
                arena=ai.ArenaPolicy(("openai-compat:fast", "openai-compat:slow")),
            )
        )
        await slow_started.wait()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert {"fast", "slow"} <= set(requested)
    assert slow_cancelled.is_set()


async def test_consensus_is_canonical_and_free_text_degrades() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    }
    client, _ = _client(
        ScriptedModel("one", structured={"a": 1, "b": 2}),
        ScriptedModel("two", structured={"b": 2, "a": 1}),
        ScriptedModel("three", structured={"a": 9, "b": 9}),
    )
    async with client:
        result = await client.generate(
            "question",
            schema=schema,
            arena=ai.ArenaPolicy(("panel:one", "panel:two", "panel:three"), strategy="consensus"),
        )

    assert result.arena is not None
    assert result.arena.agreement == 2
    assert result.structured == {"a": 1, "b": 2}

    other, _ = _client(ScriptedModel("one", text="a"), ScriptedModel("two", text="b"))
    degraded = _Events()
    other.subscribe(degraded)
    async with other:
        plain = await other.generate(
            "question",
            arena=ai.ArenaPolicy(("panel:one", "panel:two"), strategy="consensus"),
        )
    assert plain.arena is not None and plain.arena.strategy == "first_valid"
    assert any(isinstance(event, ai.ParameterDropped) for event in degraded.items)


async def test_judge_and_synthesis_spend_one_bounded_extra_call() -> None:
    client, _ = _client(
        ScriptedModel("a", text="A"),
        ScriptedModel("b", text="B"),
        ScriptedModel("judge", structured={"pick": 2, "why": "clearer"}),
    )
    async with client:
        result = await client.generate(
            "question",
            arena=ai.ArenaPolicy(
                ("panel:a", "panel:b"), strategy="judge", judge_target="panel:judge"
            ),
        )
    assert result.text == "B"
    assert result.arena is not None and result.arena.calls == 3
    assert len(result.arena.candidates) == 2


async def test_synthesis_promotes_the_extra_answer_without_discarding_candidates() -> None:
    client, _ = _client(
        ScriptedModel("a", text="A"),
        ScriptedModel("b", text="B"),
        ScriptedModel("judge", text="A and B together"),
    )
    async with client:
        result = await client.generate(
            "question",
            arena=ai.ArenaPolicy(
                ("panel:a", "panel:b"), strategy="synthesize", judge_target="panel:judge"
            ),
        )

    assert result.text == "A and B together"
    assert result.arena is not None
    assert result.arena.synthesized is not None
    assert [item.generation.text for item in result.arena.candidates if item.generation] == [
        "A",
        "B",
    ]


async def test_unusable_judge_degrades_to_first_valid_instead_of_failing() -> None:
    client, _ = _client(
        ScriptedModel("a", text="A"),
        ScriptedModel("b", text="B"),
        ScriptedModel("judge", structured={"pick": 99, "why": "outside"}),
    )
    events = _Events()
    client.subscribe(events)
    async with client:
        result = await client.generate(
            "question",
            arena=ai.ArenaPolicy(
                ("panel:a", "panel:b"), strategy="judge", judge_target="panel:judge"
            ),
        )
    assert result.text == "A"
    assert result.arena is not None and result.arena.strategy == "first_valid"
    assert any(isinstance(event, ai.ParameterDropped) for event in events.items)


def test_candidate_envelope_is_stable_and_anonymous_by_default() -> None:
    generation = ai.Generation(
        text="A < B",
        structured=None,
        tool_calls=(),
        target=ai.ResolvedTarget("secret-provider", "secret-model"),
        finish_reason="stop",
        usage=ai.Usage(),
        timing=ai.Timing(1.0),
    )
    candidates = (Candidate(generation.target, generation=generation),)
    assert candidate_envelope(candidates, reveal_targets=False) == (
        '<candidates format="1">\n<candidate index="1">\nA &lt; B\n</candidate>\n</candidates>'
    )
    revealed = candidate_envelope(candidates, reveal_targets=True)
    assert "secret-provider:secret-model" in revealed


def test_cheapest_excludes_unknown_cost_without_treating_it_as_zero() -> None:
    unknown_generation = ai.Generation(
        "unknown", None, (), ai.ResolvedTarget("p", "unknown"), "stop", ai.Usage(), ai.Timing(1)
    )
    known_generation = ai.Generation(
        "known",
        None,
        (),
        ai.ResolvedTarget("p", "known"),
        "stop",
        ai.Usage(cost_usd=Decimal("2")),
        ai.Timing(2),
    )
    candidates = (
        Candidate(unknown_generation.target, generation=unknown_generation),
        Candidate(known_generation.target, generation=known_generation),
    )
    winner, strategy, _, _ = select_candidates(
        candidates,
        ai.ArenaPolicy(("p:unknown", "p:known"), strategy="cheapest"),
        has_schema=False,
    )
    assert winner is candidates[1]
    assert strategy == "cheapest"


async def test_summed_spend_guard_refuses_before_any_candidate_dispatch() -> None:
    capabilities = ai.ModelCapabilities(
        context_window=ai.Sourced(32_768, "catalog"),
        max_output_tokens=ai.Sourced(1, "catalog"),
        pricing=ai.Sourced(ai.Pricing(Decimal("0.001"), Decimal("1")), "catalog"),
    )
    client, provider = _client(
        ScriptedModel("a", capabilities=capabilities),
        ScriptedModel("b", capabilities=capabilities),
        spend=ai.SpendPolicy(max_request_usd=Decimal("0.0000015")),
    )
    async with client:
        with pytest.raises(ai.SpendLimitError, match="summed estimate"):
            await client.generate("q", arena=ai.ArenaPolicy(("panel:a", "panel:b")))
    assert provider.call_count() == 0


async def test_tool_loops_are_independent_and_exact_calls_are_single_flight() -> None:
    client, _ = _client(
        ScriptedModel(
            "a",
            tool_calls=(("a1", "lookup", '{"x":1}'),),
            finish_reason="tool_calls",
            answer_after_tools="A",
        ),
        ScriptedModel(
            "b",
            tool_calls=(("b1", "lookup", '{"x":1}'),),
            finish_reason="tool_calls",
            answer_after_tools="B",
        ),
    )
    dispatches = 0

    async def lookup(x: int) -> int:
        nonlocal dispatches
        dispatches += 1
        await asyncio.sleep(0)
        return x

    async with client:
        result = await client.run_tools(
            "question",
            tools=[lookup],
            arena=ai.ArenaPolicy(("panel:a", "panel:b"), memoize_tools="all"),
        )

    assert result.arena is not None
    assert [item.rounds for item in result.arena.candidates] == [2, 2]
    assert result.arena.calls == 4
    assert result.arena.memoized_tool_calls == 1
    assert dispatches == 1


async def test_tool_candidates_finish_independently_without_cross_candidate_results() -> None:
    client, provider = _client(
        ScriptedModel("a", text="A"),
        ScriptedModel(
            "b",
            tool_calls=(("b1", "lookup", '{"x":2}'),),
            finish_reason="tool_calls",
            answer_after_tools="B",
        ),
    )

    async def lookup(x: int) -> int:
        return x

    async with client:
        result = await client.run_tools(
            "question",
            tools=[lookup],
            arena=ai.ArenaPolicy(("panel:a", "panel:b")),
        )

    assert result.arena is not None
    assert [item.rounds for item in result.arena.candidates] == [1, 2]
    a_requests = [body for body in provider.requests if body["model"] == "a"]
    b_requests = [body for body in provider.requests if body["model"] == "b"]
    assert not any(message["role"] == "tool" for message in a_requests[0]["messages"])
    assert any(message["role"] == "tool" for message in b_requests[-1]["messages"])


def test_config_and_sidecar_round_trip_every_arena_field() -> None:
    policy = ai.ArenaPolicy(
        ("panel:a", "panel:b"),
        strategy="judge",
        judge_target="panel:judge",
        instructions="pick",
        concurrency=2,
        min_candidates=2,
        reveal_targets=True,
        memoize_tools="off",
    )
    config = ai.AnyInferConfig(arena=policy, arenas={"panel": policy})
    assert ai.loads_config(ai.dumps_config(config)) == config

    body = request_to_openai("panel", ai.GenerationRequest((ai.user("hi"),), arena=policy))
    _, decoded, _ = request_from_openai(body)
    assert decoded.arena == policy
    assert {item.name for item in fields(ai.ArenaPolicy)} == {
        "targets",
        "strategy",
        "judge_target",
        "instructions",
        "concurrency",
        "min_candidates",
        "reveal_targets",
        "memoize_tools",
    }
