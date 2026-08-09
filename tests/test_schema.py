"""Structured-output subsystem: coercion, mechanism ladder, projection, extraction, repair."""

from __future__ import annotations

import json

import pytest

import anyinfer as ai
from anyinfer.schema.mechanism import choose_mechanism
from anyinfer.schema.project import identity_projection, repetition_safe_projection
from anyinfer.schema.repair import REPAIR_PROMPT, build_repair_messages
from anyinfer.schema.validate import extract_json, format_errors, validate
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse, sse_lines
from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced
from support import make_client, make_multi_client

PERSON_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
    "required": ["name", "age"],
    "additionalProperties": False,
}


# ---- SchemaSpec coercion ------------------------------------------------------------


def test_coerce_accepts_a_plain_mapping() -> None:
    spec = ai.SchemaSpec.coerce(PERSON_SCHEMA)
    assert spec.json_schema == PERSON_SCHEMA
    assert spec.name == "response"


def test_coerce_reads_a_title_as_the_schema_name() -> None:
    spec = ai.SchemaSpec.coerce({**PERSON_SCHEMA, "title": "Person"})
    assert spec.name == "Person"


def test_coerce_accepts_a_pydantic_style_model() -> None:
    class Person:
        """A duck-typed stand-in for a pydantic model."""

        @staticmethod
        def model_json_schema() -> dict[str, object]:
            return PERSON_SCHEMA

    spec = ai.SchemaSpec.coerce(Person)
    assert spec.json_schema == PERSON_SCHEMA
    assert spec.name == "Person"


def test_coerce_rejects_unsupported_input() -> None:
    with pytest.raises(TypeError, match="model_json_schema"):
        ai.SchemaSpec.coerce(42)  # type: ignore[arg-type]


# ---- mechanism ladder ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("features", "expected"),
    [
        (Feature.GRAMMAR | Feature.JSON_SCHEMA | Feature.JSON_MODE, "grammar"),
        (Feature.JSON_SCHEMA | Feature.JSON_MODE, "json_schema"),
        (Feature.JSON_MODE, "json_mode"),
        (Feature.STREAMING, "prompt"),
        (Feature(0), "prompt"),
    ],
)
def test_mechanism_ladder(features: Feature, expected: str) -> None:
    caps = ModelCapabilities(features=Sourced(features, "catalog"))
    assert choose_mechanism(caps) == expected


def test_unknown_capabilities_fall_to_the_weakest_mechanism() -> None:
    assert choose_mechanism(None) == "prompt"


# ---- projection ----------------------------------------------------------------------


def test_identity_projection_preserves_the_schema() -> None:
    assert identity_projection(PERSON_SCHEMA) == PERSON_SCHEMA


def test_repetition_safe_projection_strips_grammar_hostile_keywords() -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 100},
            "tags": {"type": "array", "minItems": 1, "maxItems": 5000},
            "few": {"type": "array", "minItems": 2, "maxItems": 10},
        },
    }
    projected = repetition_safe_projection(schema)

    name = projected["properties"]["name"]  # type: ignore[index]
    assert "minLength" not in name and "maxLength" not in name

    tags = projected["properties"]["tags"]  # type: ignore[index]
    assert "maxItems" not in tags, "huge array bounds are dropped"
    assert tags["minItems"] == 1, "small bounds survive"

    few = projected["properties"]["few"]  # type: ignore[index]
    assert few["maxItems"] == 10, "reasonable bounds survive"


def test_projection_does_not_mutate_the_original() -> None:
    schema = {"type": "string", "minLength": 3}
    repetition_safe_projection(schema)
    assert schema["minLength"] == 3


# ---- extraction ----------------------------------------------------------------------


def test_extract_plain_json() -> None:
    value, error = extract_json('{"name": "Ada", "age": 36}')
    assert error is None
    assert value == {"name": "Ada", "age": 36}


def test_extract_json_from_a_code_fence() -> None:
    text = 'Here you go:\n```json\n{"name": "Ada", "age": 36}\n```\nHope that helps!'
    value, error = extract_json(text)
    assert error is None
    assert value == {"name": "Ada", "age": 36}


def test_extract_json_array() -> None:
    value, error = extract_json("Sure! [1, 2, 3] done")
    assert error is None
    assert value == [1, 2, 3]


def test_extract_ignores_braces_inside_strings() -> None:
    value, error = extract_json('prose {"text": "a } brace", "n": 1} more prose')
    assert error is None
    assert value == {"text": "a } brace", "n": 1}


def test_extract_reports_non_json() -> None:
    value, error = extract_json("I'm afraid I can't do that.")
    assert value is None
    assert error is not None and "not JSON" in error


def test_extract_reports_empty() -> None:
    value, error = extract_json("   ")
    assert value is None
    assert error is not None and "empty" in error


# ---- validation ----------------------------------------------------------------------


def test_validation_passes_for_a_conforming_value() -> None:
    assert validate({"name": "Ada", "age": 36}, PERSON_SCHEMA) == ()


def test_validation_reports_missing_fields() -> None:
    errors = validate({"name": "Ada"}, PERSON_SCHEMA)
    assert errors
    assert any("age" in e for e in errors)


def test_validation_reports_an_invalid_schema_rather_than_crashing() -> None:
    errors = validate({}, {"type": "not-a-real-type"})
    assert errors
    assert "invalid" in errors[0]


def test_error_formatting_is_a_bulleted_list() -> None:
    assert format_errors(("a: bad", "b: worse")) == "- a: bad\n- b: worse"


# ---- repair --------------------------------------------------------------------------


def test_repair_messages_extend_the_conversation() -> None:
    original = (ai.user("Describe Ada."),)
    messages = build_repair_messages(original, '{"name": "Ada"}', ("age: required",))

    assert len(messages) == 3
    assert messages[0] is original[0]
    assert messages[1].role == "assistant"
    assert messages[1].text == '{"name": "Ada"}'
    assert messages[2].role == "user"
    assert "age: required" in messages[2].text
    assert REPAIR_PROMPT.split("{")[0] in messages[2].text


# ---- end-to-end ----------------------------------------------------------------------


async def test_structured_output_is_validated_client_side() -> None:
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada", "age": 36})))
    async with make_client(server) as client:
        result = await client.generate("who?", target="openai-compat:m", schema=PERSON_SCHEMA)

    assert result.structured == {"name": "Ada", "age": 36}
    assert result.structured_mechanism == "prompt"
    assert result.repair_attempts == 0


async def test_schema_violation_raises_without_a_repair_budget() -> None:
    """A schema violation is not a routing failure, so it surfaces directly.

    Falling back to another provider would be the wrong response: the request reached the
    model and the model answered — it just answered the wrong shape.
    """
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada"})))
    async with make_client(server) as client:
        with pytest.raises(ai.SchemaViolationError) as excinfo:
            await client.generate("who?", target="openai-compat:m", schema=PERSON_SCHEMA)

    error = excinfo.value
    assert error.raw_text == json.dumps({"name": "Ada"})
    assert any("age" in e for e in error.errors)
    assert error.hint is not None
    assert server.call_count == 1, "no fallback on a schema violation"


async def test_repair_loop_recovers_a_violation() -> None:
    server = FakeOpenAIServer(
        [
            FakeResponse(text=json.dumps({"name": "Ada"})),
            FakeResponse(text=json.dumps({"name": "Ada", "age": 36})),
        ]
    )
    async with make_client(server) as client:
        result = await client.generate(
            "who?",
            target="openai-compat:m",
            schema=PERSON_SCHEMA,
            repair=ai.Repair(max_attempts=1),
        )

    assert result.structured == {"name": "Ada", "age": 36}
    assert result.repair_attempts == 1
    assert server.call_count == 2

    repair_request = server.requests[1]
    last_message = repair_request["messages"][-1]
    assert "did not match the required JSON schema" in last_message["content"]


async def test_repair_budget_is_bounded() -> None:
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada"})))
    async with make_client(server) as client:
        with pytest.raises(ai.SchemaViolationError):
            await client.generate(
                "who?",
                target="openai-compat:m",
                schema=PERSON_SCHEMA,
                repair=ai.Repair(max_attempts=2),
            )

    assert server.call_count == 3, "the original attempt plus two repairs"


class _Recorder:
    """Collects telemetry events for assertions."""

    def __init__(self) -> None:
        self.events: list[ai.TelemetryEvent] = []

    def on_event(self, event: ai.TelemetryEvent) -> None:
        self.events.append(event)


def _capped_registry(ceiling: int | None) -> ai.ProviderRegistry:
    """An openai-compat registration that caps how often it may be asked to self-repair."""
    from anyinfer.providers.openai_compat import OpenAICompatAdapter

    registry = ai.ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(
        ai.ProviderDescriptor(
            id="capped",
            display_name="Fake capped",
            factory=OpenAICompatAdapter,
            requires_base_url=True,
            max_repair_attempts=ceiling,
        )
    )
    return registry


async def test_provider_repair_ceiling_clamps_the_caller_budget() -> None:
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada"})))
    async with make_multi_client(
        [("capped", server)], registry=_capped_registry(1)
    ) as client:
        with pytest.raises(ai.SchemaViolationError):
            await client.generate(
                "who?",
                target="capped:m",
                schema=PERSON_SCHEMA,
                repair=ai.Repair(max_attempts=3),
            )

    assert server.call_count == 2, "the original attempt plus the one repair allowed"


async def test_provider_repair_ceiling_is_reported_not_silent() -> None:
    recorder = _Recorder()
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada"})))
    async with make_multi_client(
        [("capped", server)], registry=_capped_registry(1), observers=[recorder]
    ) as client:
        with pytest.raises(ai.SchemaViolationError):
            await client.generate(
                "who?",
                target="capped:m",
                schema=PERSON_SCHEMA,
                repair=ai.Repair(max_attempts=3),
            )

    clamps = [
        e
        for e in recorder.events
        if isinstance(e, ai.ParameterDropped) and e.parameter == "repair.max_attempts"
    ]
    assert len(clamps) == 1
    assert "at most 1" in clamps[0].reason
    assert "3 requested" in clamps[0].reason


async def test_repair_budget_under_the_ceiling_is_left_alone() -> None:
    recorder = _Recorder()
    server = FakeOpenAIServer(
        [
            FakeResponse(text=json.dumps({"name": "Ada"})),
            FakeResponse(text=json.dumps({"name": "Ada", "age": 36})),
        ]
    )
    async with make_multi_client(
        [("capped", server)], registry=_capped_registry(2), observers=[recorder]
    ) as client:
        result = await client.generate(
            "who?", target="capped:m", schema=PERSON_SCHEMA, repair=ai.Repair(max_attempts=1)
        )

    assert result.repair_attempts == 1
    assert not [
        e
        for e in recorder.events
        if isinstance(e, ai.ParameterDropped) and e.parameter == "repair.max_attempts"
    ], "a budget the provider can honor is not a degradation"


async def test_no_ceiling_means_the_caller_decides() -> None:
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada"})))
    async with make_multi_client(
        [("capped", server)], registry=_capped_registry(None)
    ) as client:
        with pytest.raises(ai.SchemaViolationError):
            await client.generate(
                "who?",
                target="capped:m",
                schema=PERSON_SCHEMA,
                repair=ai.Repair(max_attempts=2),
            )

    assert server.call_count == 3


async def test_prompt_mechanism_injects_the_schema_into_a_system_message() -> None:
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada", "age": 1})))
    async with make_client(server) as client:
        await client.generate(
            [ai.system("Be terse."), ai.user("who?")],
            target="openai-compat:m",
            schema=PERSON_SCHEMA,
        )

    messages = server.requests[0]["messages"]
    system_message = messages[0]
    assert system_message["role"] == "system"
    assert "Be terse." in system_message["content"]
    assert "Respond with ONLY a JSON value" in system_message["content"]


async def test_prompt_mechanism_prepends_a_system_message_when_none_exists() -> None:
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada", "age": 1})))
    async with make_client(server) as client:
        await client.generate("who?", target="openai-compat:m", schema=PERSON_SCHEMA)

    messages = server.requests[0]["messages"]
    assert messages[0]["role"] == "system"
    assert "Respond with ONLY a JSON value" in messages[0]["content"]


# ---- forced-tool emulation -----------------------------------------------------------


async def test_a_schema_answered_as_a_forced_tool_call_is_recovered() -> None:
    """Providers with no response-format field emulate a schema as a forced tool.

    A well-behaved model then answers with a *tool call* rather than text. Reading only
    the text would report an empty response for a request the provider satisfied.
    """
    import httpx2

    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 3}}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "tu_1", "name": "response"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"n": 7}'},
        },
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=sse_lines(events, done=False),
            headers={"content-type": "text/event-stream"},
        )

    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "anthropic", api_key="sk-test", transport=httpx2.MockTransport(handler)
            )
        ]
    )
    async with client:
        result = await client.generate(
            "answer", target="anthropic:claude-sonnet-4-5", schema=schema
        )

    assert result.structured == {"n": 7}


async def test_a_callers_own_tool_call_is_not_mistaken_for_the_answer() -> None:
    """With caller tools present, a tool call is a tool call — not schema output."""
    import httpx2

    from anyinfer.types.requests import ToolSpec

    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 3}}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "tu_1", "name": "response"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"n": 7}'},
        },
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=sse_lines(events, done=False),
            headers={"content-type": "text/event-stream"},
        )

    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "anthropic", api_key="sk-test", transport=httpx2.MockTransport(handler)
            )
        ]
    )
    tool = ToolSpec(name="lookup", description="d", parameters={"type": "object"})
    async with client:
        with pytest.raises(ai.SchemaViolationError):
            await client.generate(
                "answer",
                target="anthropic:claude-sonnet-4-5",
                schema=schema,
                tools=[tool],
            )
