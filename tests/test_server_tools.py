"""Provider-run tools: web search and code execution, executed inside one request.

Distinct from `ToolSpec` in the one way that matters — nothing comes back for the caller
to run. The provider searches, or executes code, and folds the result into its own answer.
That makes this translate-only territory rather than agent-framework territory, which is
the line this library holds.

The rule these tests protect hardest is the **refusal**. Everywhere else in this library
an unhonored request parameter is reported dropped and the answer still arrives; here it
is refused before dispatch. The difference is what the caller gets back. A dropped
`temperature` still answers the question, slightly differently sampled. An answer produced
without the web search that was asked for is a *different* answer, built from stale
training data — and it arrives looking exactly like a good one.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import anyinfer as ai
from anyinfer.providers.base import ProviderConfig, WireRequest
from anyinfer.registry import default_registry
from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced
from anyinfer.types.events import ServerToolDelta
from anyinfer.types.requests import SERVER_TOOL_KINDS, ServerToolSpec
from anyinfer.types.results import ServerToolUse

SEARCH = ServerToolSpec(kind="web_search")
CODE = ServerToolSpec(kind="code_execution")


# ---- the spec ---------------------------------------------------------------------------


def test_an_unknown_kind_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="unknown server tool kind"):
        ServerToolSpec(kind="telepathy")  # type: ignore[arg-type]


def test_a_use_ceiling_must_be_positive() -> None:
    """The field exists to *bound* a per-invocation bill; zero would be a request for none."""
    with pytest.raises(ValueError, match="max_uses"):
        ServerToolSpec(kind="web_search", max_uses=0)


def test_the_kinds_are_deliberately_two() -> None:
    """Anything needing the caller to run code or hold state is a client tool, or an agent."""
    assert SERVER_TOOL_KINDS == ("web_search", "code_execution")


# ---- each dialect's spelling --------------------------------------------------------------


def _payload(provider_id: str, **overrides: Any) -> dict[str, Any]:
    adapter = default_registry.get(provider_id).factory(
        ProviderConfig(provider_id=provider_id, base_url="https://fake.invalid/v1", api_key="k")
    )
    request = WireRequest(model="m", messages=(ai.user("hi"),), **overrides)
    return adapter.build_payload(request)  # type: ignore[attr-defined]


def test_anthropic_uses_dated_tool_types() -> None:
    """The version is *in* the type here; a pin recorded in the contract, not a guess."""
    tools = _payload("anthropic", server_tools=(SEARCH, CODE))["tools"]
    assert tools[0]["type"] == "web_search_20250305"
    assert tools[1]["type"] == "code_execution_20250522"


def test_anthropic_is_the_one_dialect_that_can_bound_uses() -> None:
    tools = _payload("anthropic", server_tools=(ServerToolSpec(kind="web_search", max_uses=3),))[
        "tools"
    ]
    assert tools[0]["max_uses"] == 3


def test_the_responses_dialect_uses_bare_marker_objects() -> None:
    tools = _payload("openai", server_tools=(SEARCH, CODE))["tools"]
    assert tools[0] == {"type": "web_search"}
    assert tools[1]["type"] == "code_interpreter"


def test_gemini_puts_them_beside_function_declarations_not_inside() -> None:
    """They are siblings in the same array, which is why the list is assembled not replaced."""
    tools = _payload(
        "gemini",
        server_tools=(SEARCH,),
        tools=(ai.ToolSpec(name="f", description="", parameters={}),),
    )["tools"]

    assert tools[0] == {"googleSearch": {}}
    assert "functionDeclarations" in tools[1]


def test_server_tools_do_not_disturb_client_tools() -> None:
    payload = _payload(
        "anthropic",
        server_tools=(SEARCH,),
        tools=(ai.ToolSpec(name="lookup", description="d", parameters={"type": "object"}),),
    )
    names = [tool.get("name") for tool in payload["tools"]]
    assert names == ["web_search", "lookup"]


def test_nothing_is_sent_when_nothing_was_asked_for() -> None:
    for provider_id in ("anthropic", "openai", "gemini"):
        payload = _payload(provider_id)
        assert "search" not in repr(payload).lower(), provider_id


@pytest.mark.parametrize("provider_id", ["openai", "gemini"])
def test_a_ceiling_the_dialect_cannot_express_is_reported_dropped(provider_id: str) -> None:
    """Neither takes a per-tool ceiling, so a caller who set one is told rather than ignored."""
    from anyinfer._client.wire import dropped_parameters

    request = ai.GenerationRequest(
        messages=(ai.user("hi"),), server_tools=(ServerToolSpec(kind="web_search", max_uses=5),)
    )
    dropped = dict(dropped_parameters(request, default_registry.get(provider_id)))
    assert "server_tools.max_uses" in dropped


# ---- refusal, not silent omission ----------------------------------------------------------


def test_every_adapter_that_cannot_spell_one_declares_so() -> None:
    """The descriptor field is load-bearing: 95 adapters never read `server_tools`.

    Without a declaration the core could check, each of those would answer as though the
    tool had run. This asserts the set is exactly the adapters with projection code.
    """
    declaring = {
        default_registry.get(pid).id
        for pid in default_registry.known_ids()
        if default_registry.get(pid).server_tools
    }
    assert declaring == {"anthropic", "openai", "gemini"}


def test_vertex_deliberately_does_not_claim_them_despite_sharing_geminis_adapter() -> None:
    """It inherits the projection, so the omission has to be deliberate to stay honest.

    Vertex has published a different spelling for grounded search than the Gemini API at
    various points, and this repository has not verified the current one against Google's
    own documentation. Declaring the capability would send a tool block that may be
    rejected; withholding it refuses locally instead, which is the honest failure. Recorded
    on the vertex contract's watchlist.
    """
    assert default_registry.get("vertex").server_tools == frozenset()


async def test_a_provider_with_no_wire_form_refuses_rather_than_answering_without_it() -> None:
    from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

    server = FakeOpenAIServer(FakeResponse(text="a confident answer with no search"))
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat", base_url="https://fake.invalid/v1", transport=server.transport()
            )
        ],
        use_default_catalog=False,
    )
    try:
        with pytest.raises(ai.AnyInferError) as caught:
            await client.generate("hi", target="openai-compat:m", server_tools=(SEARCH,))
    finally:
        await client.aclose()

    assert "web_search" in str(caught.value)
    assert not server.requests, "the request must not reach the provider at all"


def test_a_model_trustedly_lacking_the_feature_is_refused_too() -> None:
    """Two different things can be missing; only the model half is ever a guess."""
    from anyinfer._client.async_client import AsyncClient

    request = ai.GenerationRequest(messages=(ai.user("hi"),), server_tools=(SEARCH,))
    target = ai.ResolvedTarget(provider_id="anthropic", model="m")
    client = AsyncClient([ai.ProviderSettings.of("anthropic", api_key="k")], use_default_catalog=False)

    guessed = ModelCapabilities(features=Sourced(Feature.STREAMING, "default"))
    client._check_server_tools(request, target, guessed)  # a guess is not grounds to refuse

    known = ModelCapabilities(features=Sourced(Feature.STREAMING, "catalog"))
    with pytest.raises(ai.UnsupportedInputError, match="web_search"):
        client._check_server_tools(request, target, known)

    supported = ModelCapabilities(
        features=Sourced(Feature.STREAMING | Feature.WEB_SEARCH, "catalog")
    )
    client._check_server_tools(request, target, supported)


# ---- what comes back -----------------------------------------------------------------------


def _events(provider_id: str, chunks: list[Any]) -> list[Any]:
    import importlib

    adapter = default_registry.get(provider_id).factory(
        ProviderConfig(provider_id=provider_id, base_url="https://fake.invalid/v1", api_key="k")
    )
    state = importlib.import_module(type(adapter).__module__)._StreamState()
    produced: list[Any] = []
    for chunk in chunks:
        produced.extend(adapter._events_from_chunk(chunk, state))
    produced.append(state.finalize())
    return produced


def test_anthropic_counts_invocations_and_narrates_their_lifecycle() -> None:
    produced = _events(
        "anthropic",
        [
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "server_tool_use", "name": "web_search"},
            },
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "web_search_tool_result", "content": []},
            },
        ],
    )
    deltas = [e for e in produced if isinstance(e, ServerToolDelta)]
    assert [(d.kind, d.status) for d in deltas] == [
        ("web_search", "started"),
        ("web_search", "completed"),
    ]
    assert produced[-1].server_tool_uses == (ServerToolUse(kind="web_search", uses=1),)


def test_a_failed_search_is_reported_as_failed() -> None:
    produced = _events(
        "anthropic",
        [
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "web_search_tool_result",
                    "content": {"type": "web_search_tool_result_error"},
                },
            }
        ],
    )
    assert [e.status for e in produced if isinstance(e, ServerToolDelta)] == ["failed"]


def test_the_responses_dialect_reports_its_typed_lifecycle_events() -> None:
    produced = _events(
        "openai",
        [
            {"type": "response.web_search_call.in_progress"},
            {"type": "response.web_search_call.completed"},
        ],
    )
    assert [(e.kind, e.status) for e in produced if isinstance(e, ServerToolDelta)] == [
        ("web_search", "started"),
        ("web_search", "completed"),
    ]
    assert produced[-1].server_tool_uses == (ServerToolUse(kind="web_search", uses=1),)


def test_gemini_counts_search_from_grounding_metadata() -> None:
    """Gemini reports search on the candidate, not as a part, so it is counted there."""
    produced = _events(
        "gemini",
        [
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "answer"}]},
                        "groundingMetadata": {"webSearchQueries": ["a", "b"]},
                    }
                ]
            }
        ],
    )
    assert produced[-1].server_tool_uses == (ServerToolUse(kind="web_search", uses=2),)


def test_gemini_counts_code_execution_from_its_parts() -> None:
    produced = _events(
        "gemini",
        [
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"executableCode": {"language": "PYTHON", "code": "1+1"}},
                                {"codeExecutionResult": {"outcome": "OUTCOME_OK"}},
                            ]
                        }
                    }
                ]
            }
        ],
    )
    statuses = [e.status for e in produced if isinstance(e, ServerToolDelta)]
    assert statuses == ["started", "completed"]
    assert produced[-1].server_tool_uses == (ServerToolUse(kind="code_execution", uses=1),)


def test_a_use_report_carries_a_count_and_nothing_else() -> None:
    """What a provider searched for is caller content; the bill is what the result owes."""
    use = ServerToolUse(kind="web_search", uses=3)
    assert set(vars(type(use))["__slots__"]) == {"kind", "uses"}


def test_a_server_tool_delta_does_not_start_the_first_token_clock() -> None:
    """A provider that searches before writing has not produced a token yet."""
    from anyinfer.types.events import is_content_event

    assert not is_content_event(ServerToolDelta(kind="web_search", status="started"))


# ---- the wire extension ----------------------------------------------------------------------


def test_the_chat_dialect_carries_them_as_an_extension() -> None:
    """Its `tools` array is client-executed functions; a provider-run one cannot go there."""
    from anyinfer.serve.openai_codec import (
        SERVER_TOOLS_FIELD,
        request_from_openai,
        request_to_openai,
    )

    body = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        SERVER_TOOLS_FIELD: [{"kind": "web_search", "max_uses": 2}],
    }
    _, request, _ = request_from_openai(body)
    assert request.server_tools == (ServerToolSpec(kind="web_search", max_uses=2),)
    assert request_to_openai("m", request)[SERVER_TOOLS_FIELD] == [
        {"kind": "web_search", "max_uses": 2}
    ]


def test_a_misspelled_kind_is_refused_rather_than_skipped() -> None:
    """Skipping it would answer confidently with no search at all."""
    from anyinfer.serve.openai_codec import SERVER_TOOLS_FIELD, request_from_openai

    with pytest.raises(ValueError, match="unknown server tool kind"):
        request_from_openai(
            {"model": "m", "messages": [], SERVER_TOOLS_FIELD: [{"kind": "web_serach"}]}
        )


def test_the_responses_dialect_understands_its_own_native_tool_entries() -> None:
    """A stock Responses client asking for `{"type": "web_search"}` is understood as written."""
    from anyinfer.serve.responses_codec import request_from_responses

    _, request, _ = request_from_responses(
        {"model": "m", "input": "hi", "tools": [{"type": "web_search"}]}
    )
    assert request.server_tools == (ServerToolSpec(kind="web_search"),)


def test_a_native_entry_takes_its_ceiling_from_the_extension() -> None:
    """The native form cannot express one, so the extension is the only source."""
    from anyinfer.serve.openai_codec import SERVER_TOOLS_FIELD
    from anyinfer.serve.responses_codec import request_from_responses

    _, request, _ = request_from_responses(
        {
            "model": "m",
            "input": "hi",
            "tools": [{"type": "web_search"}],
            SERVER_TOOLS_FIELD: [{"kind": "web_search", "max_uses": 4}],
        }
    )
    assert request.server_tools == (ServerToolSpec(kind="web_search", max_uses=4),)


def test_a_native_function_tool_is_not_mistaken_for_a_server_tool() -> None:
    from anyinfer.serve.responses_codec import request_from_responses

    _, request, _ = request_from_responses(
        {
            "model": "m",
            "input": "hi",
            "tools": [{"type": "function", "name": "lookup", "parameters": {}}],
        }
    )
    assert request.server_tools == ()
    assert [tool.name for tool in request.tools] == ["lookup"]


def test_the_counts_come_back_on_both_dialects() -> None:
    from anyinfer.serve.openai_codec import SERVER_TOOLS_FIELD, completion_from_generation
    from anyinfer.serve.responses_codec import encode_response

    result = ai.Generation(
        text="answer",
        structured=None,
        tool_calls=(),
        target=ai.ResolvedTarget(provider_id="anthropic", model="m"),
        finish_reason="stop",
        usage=ai.Usage(),
        timing=ai.Timing(started_at=0.0, total_ms=1.0),
        server_tool_uses=(ServerToolUse(kind="web_search", uses=2),),
    )
    expected = [{"kind": "web_search", "uses": 2}]
    assert completion_from_generation(result, model="m")[SERVER_TOOLS_FIELD] == expected
    assert encode_response(result, model="m")[SERVER_TOOLS_FIELD] == expected


def test_json_round_trips_the_request_extension() -> None:
    from anyinfer.serve.openai_codec import SERVER_TOOLS_FIELD, request_from_openai

    body = json.loads(
        json.dumps(
            {
                "model": "m",
                "messages": [],
                SERVER_TOOLS_FIELD: [{"kind": "code_execution"}],
            }
        )
    )
    _, request, _ = request_from_openai(body)
    assert request.server_tools == (ServerToolSpec(kind="code_execution"),)
