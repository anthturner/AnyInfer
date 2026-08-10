"""Truncated structured output reports received facts without inventing missing ones."""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.schema.partial import partial_object
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from support import make_client

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "year": {"type": "integer"},
        "cities": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["name", "year", "cities", "summary"],
}


@pytest.mark.parametrize(
    ("fragment", "partial", "missing"),
    [
        ('{"name":"Hansa","year":12', {"name": "Hansa"}, ("year", "cities", "summary")),
        (
            '{"name":"Hansa","year":1230,"cities":["Lübeck","Hamburg"],"summary":"tra',
            {"name": "Hansa", "year": 1230, "cities": ["Lübeck", "Hamburg"]},
            ("summary",),
        ),
        ('{"name":"unfinished', None, ("name", "year", "cities", "summary")),
        ("not json", None, ("name", "year", "cities", "summary")),
    ],
)
def test_partial_object_keeps_only_complete_members(
    fragment: str, partial: object, missing: tuple[str, ...]
) -> None:
    assert partial_object(fragment, SCHEMA) == (partial, missing)


async def test_schema_error_carries_partial_and_missing_fields() -> None:
    server = FakeOpenAIServer(FakeResponse(text='{"name":"Hansa","year":1230,"cities":['))
    async with make_client(server) as client:
        with pytest.raises(ai.SchemaViolationError) as excinfo:
            await client.generate(
                "describe",
                target="openai-compat:m",
                schema=SCHEMA,
                repair=ai.Repair(max_attempts=0),
            )

    assert excinfo.value.partial == {"name": "Hansa", "year": 1230}
    assert excinfo.value.missing_required == ("cities", "summary")


def test_schema_violation_type_exposes_partial_without_claiming_validity() -> None:
    error = ai.SchemaViolationError(
        "truncated",
        partial={"name": "Hansa"},
        missing_required=("summary",),
    )
    assert error.partial == {"name": "Hansa"}
    assert error.missing_required == ("summary",)
