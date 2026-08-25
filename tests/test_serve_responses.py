"""The Responses API endpoint: OpenAI's current-generation dialect, served.

A Responses-first SDK 404s against a chat-completions-only gateway, which is what this
route fixes. The interesting half is not the request decode — that lands in the same
`GenerationRequest` the chat route builds — but the *streaming* projection: this dialect
narrates a lifecycle (an item was added, a content part opened, text arrived, the part
closed) where chat completions repeats one chunk shape. A client written against it
depends on that narration, so a delta with no preceding `content_part.added` has nowhere
to land. Most of these tests are about the sequence being well-formed.

The other half is what is deliberately *refused*: Responses is a stateful API, and this
gateway keeps nothing.
"""

from __future__ import annotations

import json

import pytest

import anyinfer as ai
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

starlette = pytest.importorskip("starlette", reason="requires the [serve] extra")
from starlette.testclient import TestClient  # noqa: E402

from anyinfer.serve.app import create_app  # noqa: E402

TARGET = "openai-compat:fake-model-small"


def _client(server: FakeOpenAIServer) -> TestClient:
    async_client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ]
    )
    return TestClient(create_app(async_client))  # type: ignore[arg-type]


def _post(http: TestClient, **body: object) -> object:
    return http.post("/v1/responses", json={"model": TARGET, "input": "hi", **body})


# ---- the response object ------------------------------------------------------------


def test_a_response_is_shaped_the_way_the_dialect_says() -> None:
    http = _client(FakeOpenAIServer(FakeResponse(text="Hello from the frontend.")))
    body = _post(http).json()

    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["model"] == TARGET
    assert body["id"].startswith("resp_")

    message = body["output"][0]
    assert message["type"] == "message"
    assert message["role"] == "assistant"
    assert message["content"][0]["type"] == "output_text"
    assert message["content"][0]["text"] == "Hello from the frontend."


def test_usage_uses_this_dialects_names_not_the_chat_ones() -> None:
    """`input_tokens`, not `prompt_tokens`: a client reading the wrong one sees nothing."""
    http = _client(FakeOpenAIServer(FakeResponse(text="hi")))
    usage = _post(http).json()["usage"]

    assert usage["input_tokens"] == 11
    assert usage["output_tokens"] == 7
    assert usage["total_tokens"] == 18
    assert "prompt_tokens" not in usage


def test_a_tool_call_becomes_its_own_output_item() -> None:
    server = FakeOpenAIServer(
        FakeResponse(text="", tool_calls=(("call_1", "lookup", '{"q":"x"}'),), finish_reason="tool_calls")
    )
    body = _post(_client(server)).json()

    calls = [item for item in body["output"] if item["type"] == "function_call"]
    assert len(calls) == 1
    assert calls[0]["call_id"] == "call_1"
    assert calls[0]["name"] == "lookup"
    assert json.loads(calls[0]["arguments"]) == {"q": "x"}


def test_stopping_early_is_incomplete_with_a_reason() -> None:
    """This dialect has no per-choice finish reason; it says so on the response."""
    http = _client(FakeOpenAIServer(FakeResponse(text="cut", finish_reason="length")))
    body = _post(http).json()

    assert body["status"] == "incomplete"
    assert body["incomplete_details"] == {"reason": "max_output_tokens"}


def test_a_response_states_that_nothing_was_stored() -> None:
    """A client learns the gateway's retention posture without having to be refused."""
    assert _post(_client(FakeOpenAIServer(FakeResponse(text="hi")))).json()["store"] is False


# ---- what the request surface carries -------------------------------------------------


def test_instructions_become_a_system_turn() -> None:
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    _post(_client(server), instructions="Be terse.")

    sent = server.requests[0]["messages"]
    assert sent[0]["role"] == "system"
    assert sent[0]["content"] == "Be terse."


def test_a_bare_string_input_is_one_user_turn() -> None:
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    _post(_client(server))
    assert server.requests[0]["messages"][-1] == {"role": "user", "content": "hi"}


def test_typed_input_items_decode_into_message_parts() -> None:
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    _post(
        _client(server),
        input=[
            {"role": "user", "content": [{"type": "input_text", "text": "what is this?"}]},
            {"type": "function_call", "call_id": "c1", "name": "f", "arguments": '{"a":1}'},
            {"type": "function_call_output", "call_id": "c1", "output": "42"},
        ],
    )

    sent = server.requests[0]["messages"]
    assert sent[0]["content"] == "what is this?"
    assert sent[1]["tool_calls"][0]["function"]["name"] == "f"
    assert sent[2]["role"] == "tool" and sent[2]["content"] == "42"


def test_the_flattened_tool_shape_is_what_this_dialect_uses() -> None:
    """Responses puts name and parameters on the tool; chat nests them under `function`."""
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    _post(
        _client(server),
        tools=[{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
    )
    assert server.requests[0]["tools"][0]["function"]["name"] == "lookup"


def test_text_format_carries_the_schema_flattened() -> None:
    """This dialect puts schema and name on the format object; chat nests them a level down.

    Asserted on the enforced result rather than on the wire, as the chat tests do: which
    mechanism a schema reaches a provider through is a capability decision, and the
    contract here is that the schema was understood at all.
    """
    server = FakeOpenAIServer(FakeResponse(text='{"n": 1}'))
    response = _post(
        _client(server),
        text={
            "format": {
                "type": "json_schema",
                "name": "Counted",
                "schema": {
                    "type": "object",
                    "properties": {"n": {"type": "integer"}},
                    "required": ["n"],
                },
            }
        },
    )
    assert response.status_code == 200
    assert json.loads(response.json()["output"][0]["content"][0]["text"]) == {"n": 1}


def test_a_schema_violation_is_a_422_here_too() -> None:
    server = FakeOpenAIServer(FakeResponse(text="not json at all"))
    response = _post(
        _client(server),
        text={
            "format": {
                "type": "json_schema",
                "name": "Counted",
                "schema": {
                    "type": "object",
                    "properties": {"n": {"type": "integer"}},
                    "required": ["n"],
                },
            }
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "SchemaViolationError"


def test_reasoning_effort_is_read_from_its_nested_object() -> None:
    """Decoded into the normalized level, so it reaches every provider's own spelling.

    Asserted on the decode rather than on a wire body: `openai-compat` publishes no
    reasoning field, so its translator emits nothing — which is correct, and would make a
    wire assertion here a test of the wrong provider.
    """
    from anyinfer.serve.responses_codec import request_from_responses

    _, request, _ = request_from_responses(
        {"model": TARGET, "input": "hi", "reasoning": {"effort": "high"}}
    )
    assert request.reasoning == "high"


def test_top_logprobs_reaches_the_provider() -> None:
    """End to end, because the codec decoding it was never the part that could break."""
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    _post(_client(server), top_logprobs=3)
    assert server.requests[0]["logprobs"] is True
    assert server.requests[0]["top_logprobs"] == 3


# ---- what is refused rather than emulated ---------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [("previous_response_id", "resp_abc"), ("store", True)],
)
def test_server_side_state_is_refused_with_an_explanation(field: str, value: object) -> None:
    """Silently dropping these produces an answer with no history — a bad model, not a gap."""
    response = _post(_client(FakeOpenAIServer(FakeResponse(text="ok"))), **{field: value})

    assert response.status_code == 400
    assert field in response.json()["error"]["message"]


def test_store_false_is_accepted_because_it_describes_what_happens() -> None:
    assert _post(_client(FakeOpenAIServer(FakeResponse(text="ok"))), store=False).status_code == 200


def test_a_missing_model_is_a_400() -> None:
    http = _client(FakeOpenAIServer(FakeResponse(text="ok")))
    assert http.post("/v1/responses", json={"input": "hi"}).status_code == 400


def test_a_malformed_input_item_is_a_400() -> None:
    response = _post(
        _client(FakeOpenAIServer(FakeResponse(text="ok"))),
        input=[{"type": "web_search_call", "id": "ws_1"}],
    )
    assert response.status_code == 400
    assert "web_search_call" in response.json()["error"]["message"]


# ---- the streamed lifecycle -----------------------------------------------------------


def _events(http: TestClient, **body: object) -> list[tuple[str, dict]]:
    """Drive a streaming request and return its ``(event name, payload)`` pairs."""
    with http.stream(
        "POST", "/v1/responses", json={"model": TARGET, "input": "hi", "stream": True, **body}
    ) as response:
        assert response.status_code == 200
        raw = b"".join(response.iter_bytes()).decode()

    pairs: list[tuple[str, dict]] = []
    for record in raw.split("\n\n"):
        if not record.strip():
            continue
        name = ""
        payload = "{}"
        for line in record.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                payload = line.removeprefix("data: ")
        pairs.append((name, json.loads(payload)))
    return pairs


def test_every_record_names_its_event_type_on_the_event_line() -> None:
    """This dialect's clients dispatch on the event name, not on the payload's shape."""
    pairs = _events(_client(FakeOpenAIServer(FakeResponse(text="Hello there"))))
    assert all(name and name == payload["type"] for name, payload in pairs)


def test_the_lifecycle_is_well_formed_for_a_text_answer() -> None:
    """A delta with no preceding `content_part.added` has nowhere to land in a client."""
    names = [name for name, _ in _events(_client(FakeOpenAIServer(FakeResponse(text="Hello there"))))]

    assert names[0] == "response.created"
    assert names[1] == "response.in_progress"
    assert names.index("response.output_item.added") < names.index("response.content_part.added")
    assert names.index("response.content_part.added") < names.index("response.output_text.delta")
    assert names.index("response.output_text.done") < names.index("response.content_part.done")
    assert names.index("response.content_part.done") < names.index("response.output_item.done")
    assert names[-1] == "response.completed"


def test_sequence_numbers_are_monotonic() -> None:
    payloads = [payload for _, payload in _events(_client(FakeOpenAIServer(FakeResponse(text="abcd"))))]
    numbers = [p["sequence_number"] for p in payloads]
    assert numbers == sorted(numbers) == list(range(1, len(numbers) + 1))


def test_the_deltas_concatenate_to_the_finished_text() -> None:
    pairs = _events(_client(FakeOpenAIServer(FakeResponse(text="Hello there, world"))))

    deltas = "".join(p["delta"] for n, p in pairs if n == "response.output_text.delta")
    done = next(p["text"] for n, p in pairs if n == "response.output_text.done")
    final = next(p["response"] for n, p in pairs if n == "response.completed")

    assert deltas == done == "Hello there, world"
    assert final["output"][0]["content"][0]["text"] == deltas


def test_a_tool_call_streams_as_its_own_item_and_closes_with_its_arguments() -> None:
    server = FakeOpenAIServer(
        FakeResponse(text="", tool_calls=(("call_1", "lookup", '{"q":"x"}'),), finish_reason="tool_calls")
    )
    pairs = _events(_client(server))
    names = [n for n, _ in pairs]

    assert "response.function_call_arguments.delta" in names
    done = next(p for n, p in pairs if n == "response.function_call_arguments.done")
    assert json.loads(done["arguments"]) == {"q": "x"}

    closed = [p["item"] for n, p in pairs if n == "response.output_item.done"]
    assert any(item["type"] == "function_call" and item["name"] == "lookup" for item in closed)


def test_reasoning_streams_under_its_own_item_rather_than_being_dropped() -> None:
    """Folding it into the answer would corrupt the answer; dropping it loses what was paid for.

    Driven against the codec's state machine directly. Reaching a `ReasoningDelta` through
    the app would mean picking a provider whose adapter surfaces one, which tests that
    adapter rather than this projection.
    """
    from anyinfer.serve.responses_codec import response_stream_events

    events = response_stream_events(model=TARGET, response_id="resp_x", created=0)
    records = [
        *events.created(),
        *events.reasoning_delta("thinking"),
        *events.text_delta("answer"),
    ]
    names = [record["type"] for record in records]

    assert "response.reasoning_summary_text.delta" in names
    opened = [r["item"] for r in records if r["type"] == "response.output_item.added"]
    assert [item["type"] for item in opened] == ["reasoning", "message"]

    answer = "".join(
        r["delta"] for r in records if r["type"] == "response.output_text.delta"
    )
    assert answer == "answer", "reasoning must not leak into the answer text"

    # The reasoning item closes before the message opens, so the sequence stays well-formed.
    assert names.index("response.output_item.done") < names.index(
        "response.content_part.added"
    )


def test_a_failure_after_the_headers_arrives_as_a_terminal_event() -> None:
    """The status line is long gone, so this is the only way left to tell the client."""
    server = FakeOpenAIServer(FakeResponse(status=401, error_message="nope"))
    pairs = _events(_client(server))

    name, payload = pairs[-1]
    assert name == "response.failed"
    assert payload["response"]["status"] == "failed"
    assert payload["response"]["error"]["message"]


def test_a_stock_stream_carries_no_anyinfer_extension() -> None:
    """Absence of the request field means absence of the response form, as elsewhere."""
    pairs = _events(_client(FakeOpenAIServer(FakeResponse(text="hi"))))
    final = next(p["response"] for n, p in pairs if n == "response.completed")
    assert "anyinfer_manifest" not in final
