"""Integration evidence for private schema-assessment capture."""

from __future__ import annotations

import asyncio
import json

import pytest

import anyinfer as ai
import anyinfer._client.generation as generation
import anyinfer.schema._capture as capture
from anyinfer.providers.openai_compat import OpenAICompatAdapter
from anyinfer.schema._capture import _ACTIVE, capture_enabled
from anyinfer.schema.repair import REPAIR_PROMPT
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from support import make_client

PERSON_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
    "required": ["name", "age"],
    "additionalProperties": False,
}


async def test_capture_links_invalid_assessment_to_repair_wire() -> None:
    """The evidence comes from the actual validation and repair transition."""
    invalid = json.dumps({"name": "Ada"})
    valid = json.dumps({"name": "Ada", "age": 36})
    server = FakeOpenAIServer([FakeResponse(text=invalid), FakeResponse(text=valid)])

    with capture_enabled() as operations:
        async with make_client(server) as client:
            result = await client.generate(
                "Describe Ada.",
                target="openai-compat:m",
                schema=PERSON_SCHEMA,
                repair=ai.Repair(max_attempts=1),
                sampling=ai.Sampling(temperature=0.25),
                timeout_s=17,
                max_response_bytes=321,
            )

    assert result.structured == {"name": "Ada", "age": 36}
    assert len(operations) == 1
    operation = operations[0]
    assert operation.evidence_available
    assert len(operation.assessments) == 2
    source = operation.assessments[0]
    assert source.source_entry_ordinal == 0
    assert source.issues is not None
    assert source.issues[0].rule == "required"
    assert source.issues[0].params["property"] == "age"

    assert len(operation.preparations) == 1
    preparation = operation.preparations[0]
    assert preparation.source_entry_ordinal == 0
    assert preparation.assessment_ref == source.assessment_id
    assert preparation.raw_text == invalid
    assert preparation.errors == source.native_messages
    assert preparation.original_messages[-1]["text"] == "Describe Ada."
    assert preparation.built_messages[-2] == {"role": "assistant", "text": invalid}
    assert preparation.built_messages[-1] == {
        "role": "user",
        "text": REPAIR_PROMPT.format(errors="\n".join(f"- {error}" for error in source.native_messages)),
    }

    assert [(entry.entry_ordinal, entry.role) for entry in operation.entries] == [
        (0, "original"),
        (1, "correction"),
    ]
    correction = operation.entries[1]
    assert correction.repair_assessment_ref == source.assessment_id
    assert correction.wire_snapshot is not None
    assert correction.wire_snapshot["timeout_s"] == 17
    assert correction.wire_snapshot["max_response_bytes"] == 321
    assert correction.wire_snapshot["sampling"]["temperature"] == 0.25
    wire_messages = correction.wire_snapshot["messages"]
    assert tuple(wire_messages[-len(preparation.built_messages) :]) == preparation.built_messages
    injected_messages = wire_messages[: -len(preparation.built_messages)]
    assert all(message["role"] == "system" for message in injected_messages)


async def test_capture_records_final_exhaustion_without_inventing_preparation() -> None:
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada"})))

    with capture_enabled() as operations:
        async with make_client(server) as client:
            with pytest.raises(ai.SchemaViolationError):
                await client.generate(
                    "Describe Ada.",
                    target="openai-compat:m",
                    schema=PERSON_SCHEMA,
                    repair=ai.Repair(max_attempts=1),
                )

    operation = operations[0]
    assert operation.evidence_available
    assert [entry.role for entry in operation.entries] == ["original", "correction"]
    assert len(operation.assessments) == 2
    assert len(operation.preparations) == 1
    assert operation.assessments[-1].source_entry_ordinal == 1


async def test_correction_transport_retry_starts_a_fresh_repair_chain() -> None:
    invalid = json.dumps({"name": "Ada"})
    server = FakeOpenAIServer(
        [
            FakeResponse(text=invalid),
            FakeResponse(status=503, error_message="temporary"),
            FakeResponse(text=invalid),
            FakeResponse(text=json.dumps({"name": "Ada", "age": 36})),
        ]
    )

    with capture_enabled() as operations:
        async with make_client(server) as client:
            result = await client.generate(
                "Describe Ada.",
                target="openai-compat:m",
                schema=PERSON_SCHEMA,
                repair=ai.Repair(max_attempts=1),
            )

    operation = operations[0]
    assert result.structured == {"name": "Ada", "age": 36}
    assert [entry.role for entry in operation.entries] == [
        "original",
        "correction",
        "original",
        "correction",
    ]
    first_assessment, second_assessment = operation.assessments[:2]
    assert operation.entries[0].repair_assessment_ref is None
    assert operation.entries[1].repair_assessment_ref == first_assessment.assessment_id
    assert operation.entries[2].repair_assessment_ref is None
    assert operation.entries[3].repair_assessment_ref == second_assessment.assessment_id
    assert first_assessment.assessment_id != second_assessment.assessment_id


async def test_user_repair_template_text_does_not_create_a_correction_entry() -> None:
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada", "age": 36})))
    literal = "Your previous response did not match the required JSON schema. Errors:"

    with capture_enabled() as operations:
        async with make_client(server) as client:
            await client.generate(
                literal,
                target="openai-compat:m",
                schema=PERSON_SCHEMA,
            )

    operation = operations[0]
    assert [(entry.entry_ordinal, entry.role, entry.repair_assessment_ref) for entry in operation.entries] == [
        (0, "original", None)
    ]
    assert operation.preparations == []


async def test_capture_keeps_concurrent_operations_separate() -> None:
    """A shared enabled scope records one independent operation per client call."""
    first = FakeOpenAIServer(
        [FakeResponse(text=json.dumps({"name": "Ada"})), FakeResponse(text=json.dumps({"name": "Ada", "age": 1}))]
    )
    second = FakeOpenAIServer(
        [FakeResponse(text=json.dumps({"name": "Lin"})), FakeResponse(text=json.dumps({"name": "Lin", "age": 2}))]
    )

    with capture_enabled() as operations:
        async with make_client(first) as left, make_client(second) as right:
            results = await asyncio.gather(
                left.generate("left", target="openai-compat:m", schema=PERSON_SCHEMA, repair=ai.Repair(max_attempts=1)),
                right.generate("right", target="openai-compat:m", schema=PERSON_SCHEMA, repair=ai.Repair(max_attempts=1)),
            )

    assert {result.structured["name"] for result in results if result.structured is not None} == {
        "Ada",
        "Lin",
    }
    assert len(operations) == 2
    assert len({operation.operation_id for operation in operations}) == 2
    assert all([entry.role for entry in operation.entries] == ["original", "correction"] for operation in operations)
    assert {operation.preparations[0].raw_text for operation in operations} == {
        json.dumps({"name": "Ada"}),
        json.dumps({"name": "Lin"}),
    }


async def test_stream_capture_does_not_leak_active_context_across_tasks() -> None:
    """Cross-task advancement and close leave no active capture context."""
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada", "age": 1})))
    with capture_enabled() as operations:
        async with make_client(server) as client:
            stream = client.stream("who?", target="openai-compat:m", schema=PERSON_SCHEMA)
            assert _ACTIVE.get() is None
            events = []
            while True:
                try:
                    events.append(await asyncio.create_task(stream.__anext__()))
                except StopAsyncIteration:
                    break
                assert _ACTIVE.get() is None
            await asyncio.create_task(stream.aclose())
            assert _ACTIVE.get() is None

    assert len(operations) == 1
    assert events
    assert [(entry.entry_ordinal, entry.role) for entry in operations[0].entries] == [
        (0, "original")
    ]
    assert operations[0].assessments


async def test_capture_snapshot_fault_never_changes_the_native_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Private observation failure makes evidence unavailable without changing inference."""
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada", "age": 1})))

    def broken_freeze(_: object) -> object:
        raise RuntimeError("capture test fault")

    monkeypatch.setattr(capture, "_freeze", broken_freeze)
    with capture_enabled() as operations:
        async with make_client(server) as client:
            result = await client.generate("who?", target="openai-compat:m", schema=PERSON_SCHEMA)

    assert result.structured == {"name": "Ada", "age": 1}
    assert len(operations) == 1
    assert not operations[0].evidence_available


async def test_capture_projection_fault_preserves_terminal_schema_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capture projection failures cannot replace the production schema outcome."""
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada"})))

    def broken_freeze(_: object) -> object:
        raise RuntimeError("capture projection test fault")

    monkeypatch.setattr(capture, "_freeze", broken_freeze)
    with capture_enabled() as operations:
        async with make_client(server) as client:
            with pytest.raises(ai.SchemaViolationError) as excinfo:
                await client.generate("who?", target="openai-compat:m", schema=PERSON_SCHEMA)

    assert excinfo.value.raw_text == json.dumps({"name": "Ada"})
    assert excinfo.value.errors
    assert len(operations) == 1
    assert not operations[0].evidence_available


async def test_capture_assessment_append_fault_preserves_terminal_schema_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An owned capture sink failure cannot replace a real schema violation."""
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada"})))
    original_append = capture._OperationCapture.append

    def broken_assessment_append(
        self: capture._OperationCapture,
        target: list[object],
        record: object,
        *,
        assessment: bool = False,
    ) -> None:
        if assessment:
            raise RuntimeError("capture append test fault")
        original_append(self, target, record, assessment=assessment)

    monkeypatch.setattr(capture._OperationCapture, "append", broken_assessment_append)
    with capture_enabled() as operations:
        async with make_client(server) as client:
            with pytest.raises(ai.SchemaViolationError) as excinfo:
                await client.generate("who?", target="openai-compat:m", schema=PERSON_SCHEMA)

    assert excinfo.value.raw_text == json.dumps({"name": "Ada"})
    assert excinfo.value.errors
    assert len(operations) == 1
    assert not operations[0].evidence_available


@pytest.mark.parametrize("fault", ["append", "freeze"])
async def test_preparation_fault_does_not_link_a_correction_to_missing_evidence(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    """A native repair remains a correction, but has no unavailable preparation ref."""
    invalid = json.dumps({"name": "Ada"})
    server = FakeOpenAIServer(
        [FakeResponse(text=invalid), FakeResponse(text=json.dumps({"name": "Ada", "age": 1}))]
    )
    if fault == "append":
        original_append = capture._OperationCapture.append

        def broken_preparation_append(
            self: capture._OperationCapture,
            target: list[object],
            record: object,
            *,
            assessment: bool = False,
        ) -> bool:
            if target is self.preparations:
                raise RuntimeError("preparation append test fault")
            return original_append(self, target, record, assessment=assessment)

        monkeypatch.setattr(capture._OperationCapture, "append", broken_preparation_append)
    else:
        original_freeze = capture._freeze
        operations: list[capture._OperationCapture] = []
        tripped = False

        def broken_preparation_freeze(value: object) -> object:
            nonlocal tripped
            if (
                operations
                and operations[0].assessments
                and not tripped
                and isinstance(value, dict)
                and set(value) == {"role", "text"}
            ):
                tripped = True
                raise RuntimeError("preparation freeze test fault")
            return original_freeze(value)

        monkeypatch.setattr(capture, "_freeze", broken_preparation_freeze)

    with capture_enabled() as operations:
        async with make_client(server) as client:
            result = await client.generate(
                "who?", target="openai-compat:m", schema=PERSON_SCHEMA, repair=ai.Repair(max_attempts=1)
            )

    captured = operations[0]
    assert result.structured == {"name": "Ada", "age": 1}
    assert not captured.evidence_available
    assert captured.preparations == []
    assert [(entry.role, entry.repair_assessment_ref) for entry in captured.entries] == [
        ("original", None),
        ("correction", None),
    ]


async def test_entry_allocation_fault_does_not_change_native_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed evidence ordinal does not prevent the adapter invocation."""
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada", "age": 1})))

    def broken_allocate(operation: capture._OperationCapture | None) -> None:
        if operation is not None:
            operation.evidence_available = False
        return None

    monkeypatch.setattr(generation, "allocate_entry", broken_allocate)
    with capture_enabled() as operations:
        async with make_client(server) as client:
            result = await client.generate("who?", target="openai-compat:m", schema=PERSON_SCHEMA)

    assert result.structured == {"name": "Ada", "age": 1}
    assert not operations[0].evidence_available
    assert operations[0].entries == []


async def test_entered_wire_snapshot_fault_does_not_change_native_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An entered wire remains recorded when its private snapshot cannot be made."""
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada", "age": 1})))
    original_freeze = capture._freeze

    def broken_wire_freeze(value: object) -> object:
        if isinstance(value, dict) and "model" in value:
            raise RuntimeError("wire snapshot test fault")
        return original_freeze(value)

    monkeypatch.setattr(capture, "_freeze", broken_wire_freeze)
    with capture_enabled() as operations:
        async with make_client(server) as client:
            result = await client.generate("who?", target="openai-compat:m", schema=PERSON_SCHEMA)

    assert result.structured == {"name": "Ada", "age": 1}
    assert not operations[0].evidence_available
    assert [(entry.role, entry.wire_snapshot) for entry in operations[0].entries] == [("original", None)]


async def test_entered_wire_append_fault_does_not_change_native_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An entry-sink failure cannot prevent a real adapter invocation."""
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada", "age": 1})))
    original_append = capture._OperationCapture.append

    def broken_entry_append(
        self: capture._OperationCapture,
        target: list[object],
        record: object,
        *,
        assessment: bool = False,
    ) -> bool:
        if target is self.entries:
            raise RuntimeError("entered wire append test fault")
        return original_append(self, target, record, assessment=assessment)

    monkeypatch.setattr(capture._OperationCapture, "append", broken_entry_append)
    with capture_enabled() as operations:
        async with make_client(server) as client:
            result = await client.generate("who?", target="openai-compat:m", schema=PERSON_SCHEMA)

    assert result.structured == {"name": "Ada", "age": 1}
    assert server.requests
    assert operations[0].entries == []
    assert not operations[0].evidence_available
    assert _ACTIVE.get() is None


@pytest.mark.parametrize(
    ("limit", "value", "response", "expect_error"),
    [
        ("_MAX_ASSESSMENTS", 0, json.dumps({"name": "Ada"}), True),
        ("_MAX_SNAPSHOT_BYTES", 1, json.dumps({"name": "Ada", "age": 1}), False),
    ],
)
async def test_capture_limits_do_not_change_native_outcomes(
    monkeypatch: pytest.MonkeyPatch, limit: str, value: int, response: str, expect_error: bool
) -> None:
    """Evidence count and byte caps only make observation unavailable."""
    monkeypatch.setattr(capture, limit, value)
    server = FakeOpenAIServer(FakeResponse(text=response))

    with capture_enabled() as operations:
        async with make_client(server) as client:
            if expect_error:
                with pytest.raises(ai.SchemaViolationError) as excinfo:
                    await client.generate("who?", target="openai-compat:m", schema=PERSON_SCHEMA)
            else:
                result = await client.generate("who?", target="openai-compat:m", schema=PERSON_SCHEMA)

    assert not operations[0].evidence_available
    if expect_error:
        assert excinfo.value.raw_text == response
        assert excinfo.value.errors
    else:
        assert result.structured == {"name": "Ada", "age": 1}


@pytest.mark.parametrize("capture_on", [False, True])
async def test_genuine_cancellation_preserves_sdk_cancellation(
    monkeypatch: pytest.MonkeyPatch, capture_on: bool
) -> None:
    """Cancel a task after its real adapter invocation has entered its async wait."""
    entered = asyncio.Event()
    release = asyncio.Event()
    original_generate = OpenAICompatAdapter.generate

    async def gated_generate(self: OpenAICompatAdapter, wire: object):  # type: ignore[no-untyped-def]
        entered.set()
        await release.wait()
        async for event in original_generate(self, wire):  # type: ignore[arg-type]
            yield event

    monkeypatch.setattr(OpenAICompatAdapter, "generate", gated_generate)
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"name": "Ada", "age": 1})))

    async def cancel_running_generation() -> None:
        async with make_client(server) as client:
            task = asyncio.create_task(
                client.generate("who?", target="openai-compat:m", schema=PERSON_SCHEMA)
            )
            await asyncio.wait_for(entered.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()

    operations: list[capture._OperationCapture] = []
    if capture_on:
        with capture_enabled() as operations:
            await cancel_running_generation()
    else:
        await cancel_running_generation()

    if capture_on:
        assert len(operations) == 1
        assert [(entry.entry_ordinal, entry.role) for entry in operations[0].entries] == [
            (0, "original")
        ]
        assert _ACTIVE.get() is None
