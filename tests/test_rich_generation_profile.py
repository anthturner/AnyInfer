"""Static controls for the input-only rich generation compatibility profile."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

ROOT = Path(__file__).parent / "fixtures" / "rich-generation-v1"
FROZEN_FILE_SHA256 = {
    "inputs.json": ("9cff7a50fbfd553ebcfed25186173579fff582796721d0e83cc656e116cc1777"),
    "schema.json": ("5c02e14c8ebf96432755e19b63a4a065b3a7696a8c7f6eb0c300c880c9080cae"),
    "observations.schema.json": (
        "da4ab3ac0c084bd2cfc6ca762dfeabfbe7eb67998b08e01d6ae94c0de21f6951"
    ),
    "README.md": ("dd5037a5fe159fe1ecba2c1c16d25762d0717f2013f791b654c668692c23404e"),
}
EXPECTED_IDS = frozenset(
    {
        "media-image-inline-order",
        "media-image-url-detail",
        "media-document-inline-filename",
        "media-document-url",
        "media-audio-inline",
        "media-video-inline-window",
        "media-video-url-window",
        "media-invalid-image-two-sources",
        "media-invalid-video-window",
        "media-invalid-audio-empty",
        "bytes-part-at-limit",
        "bytes-part-over-limit",
        "bytes-total-at-limit",
        "bytes-total-over-limit",
        "bytes-remote-reference-not-counted",
        "media-known-unsupported-refusal",
        "media-default-unknown-dispatch",
        "server-tool-known-unsupported-refusal",
        "server-tool-default-unknown-dispatch",
        "server-tool-missing-wire-support-refusal",
        "reasoning-trusted-absence-dropped",
        "logprobs-trusted-absence-dropped",
        "citations-trusted-absence-dropped",
        "options-wildcard-instance-overlay",
        "openai-image-document-audio-wire",
        "openai-video-refusal",
        "tool-history-fragments-wire",
        "logprobs-request-terminal-raw",
        "reasoning-first-content",
        "empty-reasoning-first-content",
        "empty-text-first-content",
        "empty-tool-fragment-first-content",
        "citation-before-content",
        "server-tool-before-content",
        "rich-terminal-fields",
        "tool-fragments-assembly",
        "repair-rich-fields-isolated",
        "fallback-rich-fields-isolated",
        "raw-retained-versus-private-telemetry",
        "sync-public-path",
        "early-close-cleanup",
        "caller-cancellation-cleanup",
        "openai-document-url-refusal",
    }
)


def _read(name: str) -> dict[str, Any]:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def _walk(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [*value, *[item for child in value.values() for item in _walk(child)]]
    if isinstance(value, list):
        return [item for child in value for item in _walk(child)]
    return []


def test_rich_generation_input_corpus_is_strict_and_complete() -> None:
    for name, expected_digest in FROZEN_FILE_SHA256.items():
        raw = (ROOT / name).read_bytes()
        assert b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf")
        assert hashlib.sha256(raw).hexdigest() == expected_digest
    schema = _read("schema.json")
    corpus = _read("inputs.json")
    jsonschema.Draft202012Validator(schema).validate(corpus)

    identifiers = [case["id"] for case in corpus["cases"]]
    assert len(identifiers) == len(EXPECTED_IDS) == 43
    assert set(identifiers) == EXPECTED_IDS
    assert len(identifiers) == len(set(identifiers))
    assert "expect_request" not in _walk(corpus)


def test_rich_generation_input_corpus_has_no_result_oracle() -> None:
    corpus = _read("inputs.json")
    forbidden = {"expected", "expectation", "observation", "result", "telemetry", "wire_request"}
    assert not forbidden.intersection(_walk(corpus))


def test_rich_generation_observation_schema_has_the_shared_envelope() -> None:
    schema = _read("observations.schema.json")
    required = schema["required"]
    assert required == [
        "profile",
        "runtime",
        "source_revision",
        "source_dirty",
        "corpus_sha256",
        "observations",
    ]
    record = schema["$defs"]["observation"]
    assert record["required"] == ["id", "kind", "public", "wire", "cleanup", "telemetry"]


def test_rich_generation_corpus_references_and_validation_inputs_are_literal() -> None:
    corpus = _read("inputs.json")
    for case in corpus["cases"]:
        descriptors = {(item["id"], item["model"]) for item in case["descriptors"]}
        scripts = {item["id"]: item for item in case["scripts"]}
        assert set(case["procedure"]["script_ids"]) == set(scripts)
        for script in scripts.values():
            assert (script["provider"], script["model"]) in descriptors
        route = case["request"]["route"]
        if route is not None:
            for target in route["targets"]:
                provider, model = target.split(":", 1)
                assert (provider, model) in descriptors
        if case["kind"] == "validation":
            parts = case["request"]["messages"][0]["content"]
            assert any(part["type"] != "text" for part in parts)


@pytest.mark.parametrize(
    ("value", "allowed"),
    [
        (
            {
                "start_index": None,
                "end_index": None,
                "quoted_text": "q",
                "document_index": None,
                "title": "t",
                "uri": "u",
            },
            {"start_index", "end_index", "quoted_text", "document_index", "title", "uri"},
        ),
        ({"url": "u", "title": "t"}, {"url", "title"}),
        (
            {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "cache_read_tokens": None,
                "cache_write_tokens": None,
                "reasoning_tokens": None,
                "search_units": None,
                "cost_usd": None,
                "server_tool_uses": {},
            },
            {
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
                "reasoning_tokens",
                "search_units",
                "cost_usd",
                "server_tool_uses",
            },
        ),
        (
            {
                "kind": "provider",
                "provider": None,
                "phase": None,
                "retryable": True,
                "retry_after_s": None,
                "http_status": None,
                "detail": "d",
                "hint": None,
            },
            {
                "kind",
                "provider",
                "phase",
                "retryable",
                "retry_after_s",
                "http_status",
                "detail",
                "hint",
            },
        ),
        (
            {"token": "x", "logprob": -0.1, "top": [], "bytes": None},
            {"token", "logprob", "top", "bytes"},
        ),
        ({"kind": "web_search", "uses": 1}, {"kind", "uses"}),
    ],
)
def test_rich_generation_semantic_payloads_are_closed(
    value: dict[str, Any], allowed: set[str]
) -> None:
    assert set(value) == allowed
    mutated = {**value, "unknown": "must-fail"}
    assert not set(mutated).issubset(allowed)


@pytest.mark.parametrize("field", ["citation", "sources", "failure", "raw", "logprobs"])
def test_rich_generation_actions_have_no_implicit_observer_switch(field: str) -> None:
    corpus = _read("inputs.json")
    for case in corpus["cases"]:
        for script in case["scripts"]:
            for action in script["actions"]:
                assert "expected" not in action
                assert "procedure" not in action
    assert field in {"citation", "sources", "failure", "raw", "logprobs"}
