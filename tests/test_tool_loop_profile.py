from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import jsonschema
import pytest

import anyinfer as ai
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

ROOT = Path(__file__).parent / "fixtures" / "tool-loop-v1"
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


def _decode(raw: bytes) -> dict[str, Any]:
    if raw.startswith(bytes.fromhex("efbbbf")):
        raise ValueError("UTF-8 BOM is forbidden")
    text = raw.decode("utf-8", errors="strict")
    if b"\r" in raw or not text.endswith("\n"):
        raise ValueError("fixture must use LF and end with LF")
    return json.loads(text)


def _schemas() -> tuple[dict[str, Any], dict[str, Any]]:
    input_schema = json.loads((ROOT / "schema.json").read_text(encoding="utf-8"))
    observation_schema = json.loads(
        (ROOT / "observations.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator.check_schema(input_schema)
    jsonschema.Draft202012Validator.check_schema(observation_schema)
    return input_schema, observation_schema


def load_profile(raw: bytes | None = None) -> tuple[dict[str, Any], str]:
    raw = (ROOT / "inputs.json").read_bytes() if raw is None else raw
    corpus = _decode(raw)
    input_schema, _ = _schemas()
    jsonschema.Draft202012Validator(input_schema).validate(corpus)
    case_ids = [case["id"] for case in corpus["cases"]]
    script_ids = [script["id"] for script in corpus["scripts"]]
    if len(set(case_ids)) != len(case_ids) or len(set(script_ids)) != len(script_ids):
        raise ValueError("case and script IDs must be unique")
    if any(case["script_id"] not in set(script_ids) for case in corpus["cases"]):
        raise ValueError("case references an unknown script")
    if (
        tuple(case_ids) != EXPECTED_IDS
        or [case["script_id"] for case in corpus["cases"]] != script_ids
    ):
        raise ValueError("profile case or script order is invalid")
    return corpus, hashlib.sha256(raw).hexdigest()


def validate_aggregate(corpus: dict[str, Any], output: dict[str, Any]) -> None:
    expected_ids = [case["id"] for case in corpus["cases"]]
    actual_ids = [record.get("id") for record in output.get("observations", [])]
    if actual_ids != expected_ids:
        raise ValueError("observation IDs must match all input cases exactly once and in order")
    _, observation_schema = _schemas()
    jsonschema.Draft202012Validator(observation_schema).validate(output)


def _provenance(corpus_sha256: str) -> dict[str, Any]:
    repo_root = ROOT.parents[2].resolve()
    expected_source = (repo_root / "src" / "python").resolve()
    loaded_source = Path(ai.__file__).resolve()
    if not loaded_source.is_relative_to(expected_source):
        raise RuntimeError(f"AnyInfer import escaped selected checkout: {loaded_source}")
    top = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if Path(top).resolve() != repo_root:
        raise RuntimeError(f"selected checkout mismatch: {top}")
    revision = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
        raise RuntimeError(f"unexpected Git revision: {revision!r}")
    dirty = bool(
        subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    return {
        "profile": "tool-loop-v1",
        "runtime": "python",
        "source_revision": revision,
        "source_dirty": dirty,
        "corpus_sha256": corpus_sha256,
    }


def _messages(case: dict[str, Any]) -> list[ai.Message]:
    return [
        ai.Message(
            role=message["role"],
            content=tuple(ai.Text(part["text"]) for part in message["content"]),
        )
        for message in case["request"]["messages"]
    ]


def _make_tool(index: int, registration: dict[str, Any], calls: list[dict[str, Any]]) -> ai.Tool:
    spec = registration["spec"]
    handler = registration["handler"]
    state = {"counter": handler.get("start", 0)}
    argument = handler.get("argument")

    def invoke(**kwargs: Any) -> Any:
        if handler["kind"] == "constant":
            returned = handler["value"]
        elif handler["kind"] == "echo":
            returned = kwargs.get(argument)
        else:
            state["counter"] += 1
            returned = state["counter"]
        calls.append(
            {
                "registration_index": index,
                "name": spec["name"],
                "arguments": copy.deepcopy(kwargs),
                "returned_data": copy.deepcopy(returned),
            }
        )
        return returned

    if handler["async"]:
        original = invoke

        async def async_invoke(**kwargs: Any) -> Any:
            return original(**kwargs)

        func = async_invoke
    else:
        func = invoke
    return ai.Tool(
        ai.ToolSpec(
            name=spec["name"], description=spec["description"], parameters=spec["parameters"]
        ),
        func,
    )


def _tools(case: dict[str, Any], calls: list[dict[str, Any]]) -> list[ai.Tool]:
    return [
        _make_tool(index, registration, calls)
        for index, registration in enumerate(case["registrations"])
    ]


def _server(script: dict[str, Any]) -> FakeOpenAIServer:
    responses = []
    for response in script["responses"]:
        calls = tuple(
            (call["id"], call["name"], json.dumps(call["arguments"], separators=(",", ":")))
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
    options = case["client"]["route"]
    return ai.Route(
        targets=(target,),
        retry=ai.Retry(max_attempts=options["retry"]["max_attempts"]),
        health_gate=options["health_gate"],
    )


async def _execute_async(
    case: dict[str, Any], script: dict[str, Any]
) -> tuple[Any, BaseException | None, list[dict[str, Any]], FakeOpenAIServer]:
    server = _server(script)
    calls: list[dict[str, Any]] = []
    target = case["request"]["target"]
    async with ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat", base_url="https://fake.invalid/v1", transport=server.transport()
            )
        ],
        context_gate=case["client"]["context_gate"],
        use_default_catalog=case["client"]["use_default_catalog"],
        manifests=False,
    ) as client:
        try:
            result = await client.run_tools(
                _messages(case),
                tools=_tools(case, calls),
                target=target,
                route=_route(case, target),
                max_rounds=case["request"]["max_rounds"],
                tool_choice=case["request"]["tool_choice"],
            )
            return result, None, calls, server
        except ai.ToolLoopError as error:
            return None, error, calls, server


def _execute_sync(
    case: dict[str, Any], script: dict[str, Any]
) -> tuple[Any, BaseException | None, list[dict[str, Any]], FakeOpenAIServer]:
    server = _server(script)
    calls: list[dict[str, Any]] = []
    target = case["request"]["target"]
    with ai.Client(
        [
            ai.ProviderSettings.of(
                "openai-compat", base_url="https://fake.invalid/v1", transport=server.transport()
            )
        ],
        context_gate=case["client"]["context_gate"],
        use_default_catalog=case["client"]["use_default_catalog"],
        manifests=False,
    ) as client:
        try:
            result = client.run_tools(
                _messages(case),
                tools=_tools(case, calls),
                target=target,
                route=_route(case, target),
                max_rounds=case["request"]["max_rounds"],
                tool_choice=case["request"]["tool_choice"],
            )
            return result, None, calls, server
        except ai.ToolLoopError as error:
            return None, error, calls, server


def _project(
    case: dict[str, Any],
    provenance: dict[str, Any],
    result: Any,
    error: BaseException | None,
    calls: list[dict[str, Any]],
    server: FakeOpenAIServer,
) -> dict[str, Any]:
    entry = case["request"]["entry_point"]
    if error is None:
        usage = result.usage
        public = {
            "entry_point": entry,
            "result": {
                "text": result.text,
                "finish_reason": result.finish_reason,
                "target": {"provider_id": result.target.provider_id, "model": result.target.model},
                "usage": {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                },
            },
            "error": None,
        }
    else:
        public = {
            "entry_point": entry,
            "result": None,
            "error": {
                "type": type(error).__name__,
                "message": str(error),
                "detail": getattr(error, "detail", None),
                "hint": getattr(error, "hint", None),
            },
        }
    requests = [
        {key: body[key] for key in ("model", "messages", "tools", "tool_choice")}
        for body in server.requests
    ]
    return {
        **provenance,
        "observations": [
            {"id": case["id"], "public": public, "requests": requests, "handler_calls": calls}
        ],
    }


def test_profile_controls_and_schema_mutations() -> None:
    for path in ROOT.iterdir():
        if path.is_file():
            raw_file = path.read_bytes()
            assert not raw_file.startswith(bytes.fromhex("efbbbf")), path.name
            assert b"\r" not in raw_file and raw_file.endswith(b"\n"), path.name
            raw_file.decode("utf-8", errors="strict")
    raw = (ROOT / "inputs.json").read_bytes()
    corpus, digest = load_profile(raw)
    assert digest == hashlib.sha256(raw).hexdigest()
    input_schema, _ = _schemas()
    input_validator = jsonschema.Draft202012Validator(input_schema)
    for bad in (bytes.fromhex("efbbbf") + raw, raw.replace(b"\n", b"\r\n"), raw[:-1] + b"\xff"):
        with pytest.raises((ValueError, UnicodeDecodeError)):
            load_profile(bad)
    duplicate = copy.deepcopy(corpus)
    duplicate["cases"][1]["id"] = duplicate["cases"][0]["id"]
    with pytest.raises(ValueError, match="unique"):
        load_profile((json.dumps(duplicate) + "\n").encode())
    dangling = copy.deepcopy(corpus)
    dangling["cases"][0]["script_id"] = "unresolved"
    with pytest.raises(ValueError, match="unknown script"):
        load_profile((json.dumps(dangling) + "\n").encode())
    for mutate in (
        lambda d: d["cases"][0]["request"].pop("tool_choice"),
        lambda d: d["cases"][0]["request"].__setitem__("tool_choice", 3),
        lambda d: d["cases"][0]["registrations"][0]["handler"].__setitem__("async", "false"),
        lambda d: d["scripts"][0]["responses"][0].__setitem__("text", 7),
    ):
        changed = copy.deepcopy(corpus)
        mutate(changed)
        with pytest.raises(jsonschema.ValidationError):
            input_validator.validate(changed)
    unknown = copy.deepcopy(corpus)
    unknown["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        input_validator.validate(unknown)


@pytest.mark.asyncio
async def test_all_cases_execute_and_complete_actual_shaped_trace_validates() -> None:
    corpus, digest = load_profile()
    scripts = {script["id"]: script for script in corpus["scripts"]}
    provenance = _provenance(digest)
    aggregate = {**provenance, "observations": []}
    for case in corpus["cases"]:
        script = scripts[case["script_id"]]
        if case["request"]["entry_point"] == "sync_run_tools":
            result, error, calls, server = _execute_sync(case, script)
        else:
            result, error, calls, server = await _execute_async(case, script)
        assert error is None or isinstance(error, ai.ToolLoopError)
        assert (result is None) == (error is not None)
        case_record = _project(case, provenance, result, error, calls, server)
        aggregate["observations"].extend(case_record["observations"])
        for request in case_record["observations"][0]["requests"]:
            assert set(request) == {"model", "messages", "tools", "tool_choice"}
            assert request["tool_choice"] == case["request"]["tool_choice"]
        assert all("registration_index" in item and "returned_data" in item for item in calls)
    validate_aggregate(corpus, aggregate)

    # A multi-message/multi-part literal must survive conversion into public Message/Text values.
    multi = next(case for case in corpus["cases"] if len(case["request"]["messages"]) > 1)
    multi_index = next(
        i for i, record in enumerate(aggregate["observations"]) if record["id"] == multi["id"]
    )
    initial = aggregate["observations"][multi_index]["requests"][0]["messages"]
    expected = [
        {"role": message["role"], "content": "".join(part["text"] for part in message["content"])}
        for message in multi["request"]["messages"]
    ]
    assert initial == expected

    # The pure aggregate gate rejects cardinality and membership drift independently of outcomes.
    for mutation in (
        lambda records: records.clear(),
        lambda records: records.pop(),
        lambda records: records.__setitem__(1, copy.deepcopy(records[0])),
        lambda records: records[0].__setitem__("id", "unrecognized-case"),
        lambda records: records.reverse(),
    ):
        broken = copy.deepcopy(aggregate)
        mutation(broken["observations"])
        with pytest.raises(ValueError, match="observation IDs"):
            validate_aggregate(corpus, broken)
    for field, value in (("runtime", "ruby"), ("source_revision", "synthetic-placeholder")):
        broken = copy.deepcopy(aggregate)
        broken[field] = value
        with pytest.raises(jsonschema.ValidationError):
            validate_aggregate(corpus, broken)

    history = next(
        record
        for record in aggregate["observations"]
        if any(
            message["role"] == "tool"
            for request in record["requests"]
            for message in request["messages"]
        )
    )
    record_index = aggregate["observations"].index(history)
    for mutation in (
        lambda value: value["observations"][record_index]["requests"][0].pop("model"),
        lambda value: value["observations"][record_index]["requests"][0].pop("tools"),
        lambda value: value["observations"][record_index]["requests"][0].pop("tool_choice"),
        lambda value: value["observations"][record_index]["requests"][-1]["messages"][1].pop(
            "tool_calls"
        ),
        lambda value: value["observations"][record_index]["requests"][-1]["messages"][2].pop(
            "tool_call_id"
        ),
        lambda value: value["observations"][record_index]["requests"][-1]["messages"][
            2
        ].__setitem__("role", "unknown"),
    ):
        broken = copy.deepcopy(aggregate)
        mutation(broken)
        with pytest.raises(jsonschema.ValidationError):
            validate_aggregate(corpus, broken)


def test_counter_handler_state_isolated_per_registration() -> None:
    declaration = {
        "spec": {
            "name": "count",
            "description": "counter",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        },
        "handler": {"kind": "counter", "async": False, "start": 0},
    }
    calls: list[dict[str, Any]] = []
    first = _make_tool(0, declaration, calls)
    second = _make_tool(1, declaration, calls)
    assert first.call({"value": "x"}) == 1
    assert second.call({"value": "y"}) == 1
    assert first.call({"value": "z"}) == 2
