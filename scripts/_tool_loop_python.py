"""Execution and admission primitives for the frozen Python tool-loop observer."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "python"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "tool-loop-v1"
PROFILE = "tool-loop-v1"
FROZEN_INPUT_SHA256 = "4693fca5c88e2c3ca129b7197b819c5c55bfbe11d2621135184bb7bfcfbad5a9"
EXPECTED_IDS = (
    "tools-final-no-calls",
    "tools-one-call",
    "tools-ordered-calls",
    "tools-repeated-id",
    "tools-duplicate-name",
    "tools-round-exhaustion",
    "tools-zero-rounds",
    "tools-negative-rounds",
    "tools-unknown-name",
    "tools-sync-path",
)

if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
import jsonschema  # noqa: E402

import anyinfer as ai  # noqa: E402
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse  # noqa: E402


def require_selected_source(root: Path = ROOT) -> None:
    """Reject imported SDK code outside the selected checkout's Python source tree."""
    expected = (root / "src" / "python").resolve()
    loaded = Path(ai.__file__ or "").resolve()
    if not loaded.is_relative_to(expected):
        raise RuntimeError(f"AnyInfer import escaped selected checkout: {loaded}")


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _schema_documents() -> tuple[dict[str, Any], dict[str, Any]]:
    input_schema = json.loads((FIXTURE_ROOT / "schema.json").read_text(encoding="utf-8"))
    observation_schema = json.loads(
        (FIXTURE_ROOT / "observations.schema.json").read_text(encoding="utf-8")
    )
    return input_schema, observation_schema


def admit_corpus(
    raw: bytes, *, expected_sha256: str = FROZEN_INPUT_SHA256
) -> tuple[dict[str, Any], str]:
    """Verify frozen bytes before strict decoding, then validate profile and references."""
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise ValueError("tool-loop input bytes do not match the frozen corpus SHA-256")
    if raw.startswith(bytes.fromhex("efbbbf")):
        raise ValueError("UTF-8 BOM is forbidden")
    corpus = json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=_pairs_without_duplicates,
        parse_constant=_reject_constant,
    )
    if not isinstance(corpus, dict) or corpus.get("profile") != PROFILE:
        raise ValueError(f"unexpected profile; expected {PROFILE!r}")
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise ValueError("tool-loop inputs must use LF and end with LF")
    schema, _ = _schema_documents()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(corpus)
    cases = corpus["cases"]
    scripts = corpus["scripts"]
    case_ids = [case["id"] for case in cases]
    script_ids = [script["id"] for script in scripts]
    if tuple(case_ids) != EXPECTED_IDS:
        raise ValueError("input case IDs or order do not match the closed profile")
    if len(set(case_ids)) != len(case_ids) or len(set(script_ids)) != len(script_ids):
        raise ValueError("case and script IDs must be unique")
    if [case["script_id"] for case in cases] != script_ids:
        raise ValueError("each case must reference its corresponding ordered script")
    return corpus, digest


def source_provenance(corpus_sha256: str, *, root: Path = ROOT) -> dict[str, Any]:
    """Read selected checkout HEAD/dirty state and validate the actual import location."""
    root = root.resolve()
    require_selected_source(root)
    top = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if Path(top).resolve() != root:
        raise RuntimeError(f"Git selected a different checkout: {top}")
    revision = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise RuntimeError(f"unexpected Git HEAD revision: {revision!r}")
    dirty = bool(
        subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    return {
        "profile": PROFILE,
        "runtime": "python",
        "source_revision": revision,
        "source_dirty": dirty,
        "corpus_sha256": corpus_sha256,
    }


def _messages(raw_messages: list[dict[str, Any]]) -> list[ai.Message]:
    return [
        ai.Message(
            role=message["role"],
            content=tuple(ai.Text(part["text"]) for part in message["content"]),
        )
        for message in raw_messages
    ]


def _make_tool(
    index: int, registration: dict[str, Any], invocations: list[dict[str, Any]]
) -> ai.Tool:
    spec = registration["spec"]
    declaration = registration["handler"]
    state = {"counter": declaration.get("start", 0)}
    argument = declaration.get("argument")

    def invoke(**kwargs: Any) -> Any:
        kind = declaration["kind"]
        if kind == "constant":
            returned = declaration["value"]
        elif kind == "echo":
            returned = kwargs.get(argument)
        else:
            state["counter"] += 1
            returned = state["counter"]
        invocations.append(
            {
                "registration_index": index,
                "name": spec["name"],
                "arguments": kwargs,
                "returned_data": returned,
            }
        )
        return returned

    if declaration["async"]:
        original = invoke

        async def async_invoke(**kwargs: Any) -> Any:
            return original(**kwargs)

        function = async_invoke
    else:
        function = invoke
    return ai.Tool(
        ai.ToolSpec(
            name=spec["name"],
            description=spec["description"],
            parameters=spec["parameters"],
        ),
        function,
    )


def build_tools(case: dict[str, Any], invocations: list[dict[str, Any]]) -> list[ai.Tool]:
    """Build actual SDK Tool/ToolSpec registrations with independent callback state."""
    return [
        _make_tool(index, registration, invocations)
        for index, registration in enumerate(case["registrations"])
    ]


def _script_server(script: dict[str, Any]) -> FakeOpenAIServer:
    responses = []
    for response in script["responses"]:
        calls = tuple(
            (
                call["id"],
                call["name"],
                json.dumps(call["arguments"], ensure_ascii=False, separators=(",", ":")),
            )
            for call in response["tool_calls"]
        )
        responses.append(
            FakeResponse(
                text=response["text"],
                tool_calls=calls,
                finish_reason=response["finish_reason"],
                usage=response.get("usage"),
            )
        )
    return FakeOpenAIServer(responses)


def _route(case: dict[str, Any], target: str) -> ai.Route:
    route = case["client"]["route"]
    return ai.Route(
        targets=(target,),
        retry=ai.Retry(max_attempts=route["retry"]["max_attempts"]),
        health_gate=route["health_gate"],
    )


def _error(error: ai.ToolLoopError) -> dict[str, Any]:
    return {
        "type": type(error).__name__,
        "message": str(error),
        "detail": error.detail,
        "hint": error.hint,
    }


def _result(result: ai.Generation) -> dict[str, Any]:
    usage = result.usage
    return {
        "text": result.text,
        "finish_reason": result.finish_reason,
        "target": {"provider_id": result.target.provider_id, "model": result.target.model},
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        },
    }


def _project(
    case: dict[str, Any],
    result: ai.Generation | None,
    error: ai.ToolLoopError | None,
    invocations: list[dict[str, Any]],
    server: FakeOpenAIServer,
) -> dict[str, Any]:
    public = {
        "entry_point": case["request"]["entry_point"],
        "result": None if result is None else _result(result),
        "error": None if error is None else _error(error),
    }
    request_fields = ("model", "messages", "tools", "tool_choice")
    requests = [{field: body[field] for field in request_fields} for body in server.requests]
    return {"id": case["id"], "public": public, "requests": requests, "handler_calls": invocations}


def validate_aggregate(corpus: dict[str, Any], output: dict[str, Any]) -> None:
    """Validate the complete trace and exact input-order identity without outcome oracles."""
    expected_ids = [case["id"] for case in corpus["cases"]]
    observations = output.get("observations")
    actual_ids = (
        [record.get("id") for record in observations] if isinstance(observations, list) else None
    )
    if actual_ids != expected_ids:
        raise ValueError("observation IDs must match all input cases exactly once and in order")
    _, schema = _schema_documents()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(output)


async def _execute_async(
    case: dict[str, Any], script: dict[str, Any]
) -> tuple[ai.Generation | None, ai.ToolLoopError | None, list[dict[str, Any]], FakeOpenAIServer]:
    server = _script_server(script)
    invocations: list[dict[str, Any]] = []
    target = case["request"]["target"]
    async with ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat", base_url="https://fake.invalid/v1", transport=server.transport()
            )
        ],
        context_gate=case["client"]["context_gate"],
        use_default_catalog=case["client"]["use_default_catalog"],
    ) as client:
        try:
            result = await client.run_tools(
                _messages(case["request"]["messages"]),
                tools=build_tools(case, invocations),
                target=target,
                route=_route(case, target),
                max_rounds=case["request"]["max_rounds"],
                tool_choice=case["request"]["tool_choice"],
            )
            error = None
        except ai.ToolLoopError as caught:
            result = None
            error = caught
    if server.call_count != len(script["responses"]) or len(server.requests) != len(
        script["responses"]
    ):
        raise RuntimeError(
            f"response script consumption mismatch for {case['id']}: "
            f"{server.call_count} calls for {len(script['responses'])} scripted responses"
        )
    return result, error, invocations, server


def _execute_sync(
    case: dict[str, Any], script: dict[str, Any]
) -> tuple[ai.Generation | None, ai.ToolLoopError | None, list[dict[str, Any]], FakeOpenAIServer]:
    server = _script_server(script)
    invocations: list[dict[str, Any]] = []
    target = case["request"]["target"]
    with ai.Client(
        [
            ai.ProviderSettings.of(
                "openai-compat", base_url="https://fake.invalid/v1", transport=server.transport()
            )
        ],
        context_gate=case["client"]["context_gate"],
        use_default_catalog=case["client"]["use_default_catalog"],
    ) as client:
        try:
            result = client.run_tools(
                _messages(case["request"]["messages"]),
                tools=build_tools(case, invocations),
                target=target,
                route=_route(case, target),
                max_rounds=case["request"]["max_rounds"],
                tool_choice=case["request"]["tool_choice"],
            )
            error = None
        except ai.ToolLoopError as caught:
            result = None
            error = caught
    if server.call_count != len(script["responses"]) or len(server.requests) != len(
        script["responses"]
    ):
        raise RuntimeError(
            f"response script consumption mismatch for {case['id']}: "
            f"{server.call_count} calls for {len(script['responses'])} scripted responses"
        )
    return result, error, invocations, server


def execute_all(corpus: dict[str, Any], corpus_sha256: str) -> dict[str, Any]:
    """Run the complete corpus through the corresponding public Client API for each case."""
    scripts = {script["id"]: script for script in corpus["scripts"]}
    provenance = source_provenance(corpus_sha256)
    observations: list[dict[str, Any]] = []
    for case in corpus["cases"]:
        script = scripts[case["script_id"]]
        if case["request"]["entry_point"] == "async_run_tools":
            result, error, invocations, server = asyncio.run(_execute_async(case, script))
        elif case["request"]["entry_point"] == "sync_run_tools":
            result, error, invocations, server = _execute_sync(case, script)
        else:
            raise ValueError(f"unsupported public entry point: {case['request']['entry_point']!r}")
        observations.append(_project(case, result, error, invocations, server))
    output = {**provenance, "observations": observations}
    validate_aggregate(corpus, output)
    return output


def observe(input_path: Path, output_path: Path) -> dict[str, Any]:
    """Admit frozen bytes, run all public cases, validate, and write the output document."""
    corpus, digest = admit_corpus(input_path.read_bytes())
    output = execute_all(corpus, digest)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return output
