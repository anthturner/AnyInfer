"""The serve frontend end to end (§22, ADR-009).

An unmodified OpenAI-shaped client must work against this app — that is the whole promise.
These tests drive it through Starlette's test client rather than a socket, so they exercise
the real ASGI app without binding a port.
"""

from __future__ import annotations

import json

import pytest

import anyinfer as ai
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.types.capabilities import ModelCapabilities, Sourced

starlette = pytest.importorskip("starlette", reason="requires the [serve] extra")
from starlette.testclient import TestClient  # noqa: E402

from anyinfer.serve.app import create_app  # noqa: E402


def _client(server: FakeOpenAIServer, **app_kwargs: object) -> tuple[TestClient, object]:
    async_client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ]
    )
    app = create_app(async_client, **app_kwargs)  # type: ignore[arg-type]
    return TestClient(app), async_client


# ---- non-streaming -------------------------------------------------------------------


def test_chat_completion_returns_an_openai_shaped_body() -> None:
    server = FakeOpenAIServer(FakeResponse(text="Hello from the frontend."))
    http, _ = _client(server)

    response = http.post(
        "/v1/chat/completions",
        json={
            "model": "openai-compat:fake-model-small",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "Hello from the frontend."
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["completion_tokens"] == 7


def test_manifest_extension_is_opt_in_and_stock_body_is_unchanged() -> None:
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    http, _ = _client(server)
    base = {
        "model": "openai-compat:m",
        "messages": [{"role": "user", "content": "hi"}],
    }

    stock = http.post("/v1/chat/completions", json=base).json()
    extended = http.post("/v1/chat/completions", json={**base, "anyinfer_manifest": True}).json()

    assert "anyinfer_manifest" not in stock
    manifest = extended.pop("anyinfer_manifest")
    extended.pop("id", None)
    stock.pop("id", None)
    extended.pop("created", None)
    stock.pop("created", None)
    assert extended == stock
    assert manifest["route"]["resolved"] == "openai-compat:m"


def test_arena_extension_keeps_a_stock_chat_completion_and_all_candidates() -> None:
    server = FakeOpenAIServer(FakeResponse(text="candidate"))
    http, _ = _client(server)

    response = http.post(
        "/v1/chat/completions",
        json={
            "model": "ignored-when-arena-is-present",
            "messages": [{"role": "user", "content": "compare"}],
            "anyinfer_arena": {
                "targets": ["openai-compat:a", "openai-compat:b"],
                "strategy": "first_valid",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "candidate"
    arena = body["anyinfer_arena"]
    assert len(arena["candidates"]) == 2
    assert arena["winner"] == 0


def test_target_grammar_works_as_a_model_string() -> None:
    """Federation is free precisely because a Target *is* an OpenAI model string."""
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    http, _ = _client(server)

    response = http.post(
        "/v1/chat/completions",
        json={
            "model": "openai-compat:some:model",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200
    assert server.requests[0]["model"] == "some:model"


def test_sampling_and_tools_reach_the_provider() -> None:
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    http, _ = _client(server)

    http.post(
        "/v1/chat/completions",
        json={
            "model": "openai-compat:m",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.3,
            "max_tokens": 64,
            "stop": ["END"],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "Look up",
                        "parameters": {"type": "object"},
                    },
                }
            ],
        },
    )

    sent = server.requests[0]
    assert sent["temperature"] == 0.3
    assert sent["max_tokens"] == 64
    assert sent["stop"] == ["END"]
    assert sent["tools"][0]["function"]["name"] == "lookup"


def test_structured_output_is_validated_before_responding() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"n": 5})))
    http, _ = _client(server)

    response = http.post(
        "/v1/chat/completions",
        json={
            "model": "openai-compat:m",
            "messages": [{"role": "user", "content": "hi"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "Answer", "schema": schema},
            },
        },
    )

    assert response.status_code == 200
    assert json.loads(response.json()["choices"][0]["message"]["content"]) == {"n": 5}


def test_schema_violation_is_a_422() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    server = FakeOpenAIServer(FakeResponse(text="not json at all"))
    http, _ = _client(server)

    response = http.post(
        "/v1/chat/completions",
        json={
            "model": "openai-compat:m",
            "messages": [{"role": "user", "content": "hi"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "Answer", "schema": schema},
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "SchemaViolationError"


def test_provider_error_maps_to_a_status() -> None:
    server = FakeOpenAIServer(FakeResponse(status=401, error_message="bad key"))
    http, _ = _client(server)

    response = http.post(
        "/v1/chat/completions",
        json={"model": "openai-compat:m", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code >= 400
    assert "error" in response.json()


# ---- streaming -----------------------------------------------------------------------


def _parse_sse(text: str) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    for record in text.split("\n\n"):
        line = record.strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            continue
        chunks.append(json.loads(payload))
    return chunks


def test_streaming_produces_a_reconstructable_chunk_sequence() -> None:
    server = FakeOpenAIServer(FakeResponse(text="Streaming works."))
    http, _ = _client(server)

    with http.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "openai-compat:m",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        body = "".join(response.iter_text())

    chunks = _parse_sse(body)
    text = "".join(
        str(c["choices"][0]["delta"].get("content", ""))  # type: ignore[index,union-attr]
        for c in chunks
        if c.get("choices") and "content" in c["choices"][0]["delta"]  # type: ignore[index,operator]
    )
    assert text == "Streaming works."
    assert body.rstrip().endswith("data: [DONE]")

    finishes = [
        c
        for c in chunks
        if c.get("choices") and c["choices"][0].get("finish_reason")  # type: ignore[index,union-attr]
    ]
    assert len(finishes) == 1


def test_streaming_includes_a_terminal_usage_chunk() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    http, _ = _client(server)

    with http.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "openai-compat:m",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
    ) as response:
        chunks = _parse_sse("".join(response.iter_text()))

    usage_chunks = [c for c in chunks if "usage" in c]
    assert len(usage_chunks) == 1
    assert usage_chunks[0]["usage"]["completion_tokens"] == 7  # type: ignore[index]


def test_streaming_manifest_frame_precedes_done() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    http, _ = _client(server)

    with http.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "openai-compat:m",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "anyinfer_manifest": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert body.index('"anyinfer_manifest"') < body.index("data: [DONE]")
    frames = _parse_sse(body)
    manifest_frames = [frame for frame in frames if "anyinfer_manifest" in frame]
    assert len(manifest_frames) == 1
    assert manifest_frames[0]["anyinfer_manifest"]["complete"] is True  # type: ignore[index]


def test_usage_can_be_suppressed() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    http, _ = _client(server)

    with http.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "openai-compat:m",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": {"include_usage": False},
        },
    ) as response:
        chunks = _parse_sse("".join(response.iter_text()))

    assert not [c for c in chunks if "usage" in c]


# ---- models and health ---------------------------------------------------------------


def test_models_lists_catalog_aliases() -> None:
    server = FakeOpenAIServer()
    http, _ = _client(server)

    body = http.get("/v1/models").json()
    ids = {entry["id"] for entry in body["data"]}

    assert body["object"] == "list"
    assert {"small", "medium", "large"} <= ids


def test_models_includes_exposed_targets() -> None:
    server = FakeOpenAIServer()
    http, _ = _client(server, expose_targets=("openai-compat:fake-model-small",))

    ids = {entry["id"] for entry in http.get("/v1/models").json()["data"]}
    assert "openai-compat:fake-model-small" in ids


def test_namespaced_compare_projects_the_public_client_api() -> None:
    server = FakeOpenAIServer()
    http, _ = _client(server)
    response = http.post(
        "/v1/anyinfer/compare",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "targets": ["openai-compat:m", "missing:m"],
            "temperature": 0.2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "anyinfer.target_comparison.list"
    assert [item["resolvable"] for item in body["data"]] == [True, False]
    assert server.requests == []


def test_health_needs_no_authentication() -> None:
    server = FakeOpenAIServer()
    http, _ = _client(server, auth_token="secret-token-value")

    assert http.get("/health").json() == {"status": "ok"}


# ---- authentication ------------------------------------------------------------------


def test_bearer_token_is_enforced() -> None:
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    http, _ = _client(server, auth_token="secret-token-value")
    body = {"model": "openai-compat:m", "messages": [{"role": "user", "content": "hi"}]}

    assert http.post("/v1/chat/completions", json=body).status_code == 401
    assert (
        http.post(
            "/v1/chat/completions",
            json=body,
            headers={"authorization": "Bearer wrong-token-value"},
        ).status_code
        == 401
    )
    assert (
        http.post(
            "/v1/chat/completions",
            json=body,
            headers={"authorization": "Bearer secret-token-value"},
        ).status_code
        == 200
    )


def test_models_also_requires_the_token() -> None:
    server = FakeOpenAIServer()
    http, _ = _client(server, auth_token="secret-token-value")
    assert http.get("/v1/models").status_code == 401


# ---- unsupported surface -------------------------------------------------------------


@pytest.mark.parametrize("path", ["/v1/images/generations", "/v1/audio"])
def test_unmodelled_endpoints_return_a_clear_404(path: str) -> None:
    """AnyInfer models text generation, embeddings, and reranking; the rest says so plainly.

    ``/v1/embeddings`` moved out of this list once it became a real modeled endpoint
    (see test_serve_embeddings.py) — it now 200s rather than 404ing.
    """
    server = FakeOpenAIServer()
    http, _ = _client(server)

    response = http.post(path, json={})
    assert response.status_code == 404
    assert "text generation, embeddings, and reranking only" in response.json()["error"]["message"]


def test_missing_model_field_is_a_400() -> None:
    server = FakeOpenAIServer()
    http, _ = _client(server)

    response = http.post("/v1/chat/completions", json={"messages": []})
    assert response.status_code == 400
    assert "model" in response.json()["error"]["message"]


def test_malformed_body_is_a_400() -> None:
    server = FakeOpenAIServer()
    http, _ = _client(server)

    response = http.post(
        "/v1/chat/completions",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400


# ---- the config file's instance model ---------------------------------------------------


def _write_config(tmp_path, data: dict) -> object:
    path = tmp_path / "anyinfer.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_config_without_an_adapter_keeps_single_instance_behaviour(tmp_path) -> None:
    path = _write_config(
        tmp_path, {"providers": [{"id": "openai", "api_key": "env://OPENAI_API_KEY"}]}
    )
    config = ai.load_config(path)
    settings, route = config.providers, config.route

    assert [s.provider_id for s in settings] == ["openai"]
    assert [s.instance_id for s in settings] == ["openai"]
    assert settings[0].alias is None
    assert route is None


def test_config_adapter_key_names_the_engine_behind_an_instance(tmp_path) -> None:
    path = _write_config(
        tmp_path,
        {
            "providers": [
                {"id": "openai", "api_key": "env://OPENAI_API_KEY"},
                {
                    "id": "work-azure",
                    "adapter": "azure-foundry",
                    "base_url": "https://wumbo.openai.azure.com",
                    "api_key": "env://WUMBO_KEY",
                },
                {
                    "id": "ollama-local",
                    "adapter": "ollama",
                    "base_url": "http://127.0.0.1:11434",
                },
            ],
            "default_route": ["openai:gpt-5", "work-azure:gpt-4o"],
        },
    )
    config = ai.load_config(path)
    settings, route = config.providers, config.route

    assert [s.instance_id for s in settings] == ["openai", "work-azure", "ollama-local"]
    assert [s.provider_id for s in settings] == ["openai", "azure-foundry", "ollama"]
    assert settings[1].base_url == "https://wumbo.openai.azure.com"
    assert route.targets == ("openai:gpt-5", "work-azure:gpt-4o")


def test_two_instances_of_one_engine_coexist(tmp_path) -> None:
    path = _write_config(
        tmp_path,
        {
            "providers": [
                {"id": "tenant-a", "adapter": "azure-foundry", "base_url": "https://a"},
                {"id": "tenant-b", "adapter": "azure-foundry", "base_url": "https://b"},
            ]
        },
    )
    settings = ai.load_config(path).providers

    assert [s.instance_id for s in settings] == ["tenant-a", "tenant-b"]
    assert {s.provider_id for s in settings} == {"azure-foundry"}


def test_a_duplicate_id_fails_fast_with_a_hint(tmp_path) -> None:
    from anyinfer.errors import ConfigError

    path = _write_config(
        tmp_path,
        {
            "providers": [
                {"id": "openai", "api_key": "env://A"},
                {"id": "openai", "api_key": "env://B"},
            ]
        },
    )
    with pytest.raises(ConfigError) as caught:
        ai.load_config(path)
    assert "configured more than once" in str(caught.value)
    assert "unique 'id'" in (caught.value.hint or "")


def test_an_aliased_instance_routes_to_its_own_adapter() -> None:
    """`alias:model` must reach the instance the alias names, not the engine's default."""
    first, second = FakeOpenAIServer(), FakeOpenAIServer()
    async_client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                alias="site-a",
                base_url="https://a.invalid/v1",
                transport=first.transport(),
            ),
            ai.ProviderSettings.of(
                "openai-compat",
                alias="site-b",
                base_url="https://b.invalid/v1",
                transport=second.transport(),
            ),
        ]
    )
    http = TestClient(create_app(async_client))

    response = http.post(
        "/v1/chat/completions",
        json={"model": "site-b:fake-model-small", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200, response.text
    # Only the instance named in the target saw traffic.
    assert second.requests and not first.requests


def test_exposed_targets_may_be_written_in_instance_terms() -> None:
    server = FakeOpenAIServer()
    async_client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                alias="work-azure",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ]
    )
    http = TestClient(create_app(async_client, expose_targets=("work-azure:gpt-4o",)))

    ids = {entry["id"] for entry in http.get("/v1/models").json()["data"]}
    assert "work-azure:gpt-4o" in ids


# ---- conversation compaction, inherited from the client ------------------------------


def _compaction_client(
    server: FakeOpenAIServer, **client_kwargs: object
) -> tuple[TestClient, object]:
    """A gateway whose client has a small window and, optionally, a compaction policy."""
    async_client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ],
        capability_overrides={
            "openai-compat:fake-model-small": ModelCapabilities(
                context_window=Sourced(8_192, "catalog")
            )
        },
        **client_kwargs,  # type: ignore[arg-type]
    )
    return TestClient(create_app(async_client)), async_client


def _oversized_body(**extra: object) -> dict:
    filler = "x" * 10_000
    messages = [{"role": "system", "content": "Be brief."}]
    for index in range(5):
        messages.append({"role": "user", "content": f"Q{index}. {filler}"})
        messages.append({"role": "assistant", "content": f"A{index}. {filler}"})
    messages.append({"role": "user", "content": "And finally?"})
    return {"model": "openai-compat:fake-model-small", "messages": messages, **extra}


def test_the_gateway_inherits_the_clients_compaction_policy() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    client, _ = _compaction_client(
        server, history=ai.HistoryPolicy(mode="proactive", keep_recent=1)
    )
    response = client.post("/v1/chat/completions", json=_oversized_body())

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hi"
    assert server.requests, "the gateway dispatched rather than failing on overflow"


def test_without_a_policy_the_gateway_still_reports_the_overflow() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    client, _ = _compaction_client(server)
    response = client.post("/v1/chat/completions", json=_oversized_body())

    assert response.status_code >= 400
    assert not server.requests


def test_a_request_can_ask_for_compaction_the_gateway_did_not_configure() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    client, _ = _compaction_client(server)
    response = client.post(
        "/v1/chat/completions",
        json=_oversized_body(anyinfer_history={"mode": "proactive", "keep_recent": 1}),
    )

    assert response.status_code == 200
    assert server.requests


def test_a_request_can_refuse_the_gateways_policy() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    client, _ = _compaction_client(
        server, history=ai.HistoryPolicy(mode="proactive", keep_recent=1)
    )
    response = client.post("/v1/chat/completions", json=_oversized_body(anyinfer_history=False))

    assert response.status_code >= 400, "the caller chose the error over a shortened history"
    assert not server.requests


def test_a_malformed_history_extension_is_a_400() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    client, _ = _compaction_client(server)
    response = client.post(
        "/v1/chat/completions",
        json=_oversized_body(anyinfer_history={"mode": "whenever"}),
    )

    assert response.status_code == 400
    assert "anyinfer_history" in response.text


# ---- disconnect mid-stream releases the provider connection --------------------------


class _FakeUnderlyingStream:
    """Stands in for `AsyncStream`: yields scripted events, tracks whether it was closed."""

    def __init__(self, events: list[object]) -> None:
        self._events = iter(events)
        self.closed = False

    def __aiter__(self) -> _FakeUnderlyingStream:
        return self

    async def __anext__(self) -> object:
        try:
            return next(self._events)
        except StopIteration:
            raise StopAsyncIteration from None

    async def aclose(self) -> None:
        self.closed = True


class _FakeStreamingClient:
    """Stands in for `AsyncClient`: `.stream(...)` returns one scripted fake stream."""

    def __init__(self, events: list[object]) -> None:
        self.underlying = _FakeUnderlyingStream(events)

    def stream(self, *args: object, **kwargs: object) -> _FakeUnderlyingStream:
        return self.underlying


async def test_client_disconnect_mid_stream_closes_the_provider_connection() -> None:
    """ASGI closes the SSE generator on disconnect; the provider stream must follow.

    Without an explicit close, the only thing that would eventually release the
    upstream connection is garbage collection — not deterministic, and not something a
    gateway serving real traffic can rely on. This drives `_stream_chunks` directly as
    an async generator (the same object `StreamingResponse` iterates), consumes one
    event, then closes it early exactly as Starlette does when a client disconnects.
    """
    from anyinfer.serve.app import _stream_chunks
    from anyinfer.types.events import TextDelta

    fake_client = _FakeStreamingClient([TextDelta("partial")])
    request = ai.GenerationRequest(messages=(ai.user("hi"),))

    generator = _stream_chunks(
        fake_client,
        "openai-compat:m",
        request,
        {},
        completion_id="chatcmpl-test",
        created=0,
        model="openai-compat:m",
    )
    first = await generator.__anext__()
    assert b"partial" in first

    await generator.aclose()

    assert fake_client.underlying.closed is True


# ---- request body size limit ---------------------------------------------------------


def test_an_oversized_body_is_refused_with_413() -> None:
    """An unbounded request body is an unbounded allocation.

    Every handler buffers its whole body to parse JSON, so this is the thing that matters
    once the gateway leaves loopback.
    """
    server = FakeOpenAIServer(FakeResponse(text="never reached"))
    http, _ = _client(server, max_request_bytes=1024)

    response = http.post(
        "/v1/chat/completions",
        json={
            "model": "openai-compat:m",
            "messages": [{"role": "user", "content": "x" * 4096}],
        },
    )

    assert response.status_code == 413
    assert "limit" in response.json()["error"]["message"]


def test_a_body_under_the_limit_passes_through_untouched() -> None:
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    http, _ = _client(server, max_request_bytes=1024 * 1024)

    response = http.post(
        "/v1/chat/completions",
        json={"model": "openai-compat:m", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ok"


async def test_the_limit_is_enforced_while_reading_not_from_content_length() -> None:
    """`content-length` is advisory: absent on a chunked request, forgeable on any other.

    Driven at the raw ASGI layer because an HTTP client will always recompute the header
    honestly, which would let this pass on the declared-length check and prove nothing
    about the read-side one. Here the request declares no length at all and streams past
    the cap in chunks; it must be refused without the wrapped app ever being entered.
    """
    from anyinfer.serve.app import _with_body_limit

    reached = False

    async def inner(scope: object, receive: object, send: object) -> None:
        nonlocal reached
        reached = True

    app = _with_body_limit(inner, 1024)

    messages = [{"type": "http.request", "body": b"x" * 512, "more_body": True}] * 5
    messages.append({"type": "http.request", "body": b"", "more_body": False})
    pending = iter(messages)
    sent: list[dict] = []

    async def receive() -> dict:
        return next(pending)

    async def send(message: dict) -> None:
        sent.append(message)

    await app({"type": "http", "headers": []}, receive, send)

    assert sent[0]["status"] == 413
    assert not reached, "the oversized body must never reach the wrapped app"


async def test_a_chunked_body_under_the_limit_is_reassembled_for_the_app() -> None:
    """The wrapper replays what it buffered, so a chunked request is not truncated."""
    from anyinfer.serve.app import _with_body_limit

    received = b""

    async def inner(scope: object, receive: object, send: object) -> None:
        nonlocal received
        message = await receive()  # type: ignore[operator]
        received = message["body"]

    app = _with_body_limit(inner, 1024)

    messages = [
        {"type": "http.request", "body": b"y" * 100, "more_body": True},
        {"type": "http.request", "body": b"z" * 50, "more_body": False},
    ]
    pending = iter(messages)

    async def receive() -> dict:
        return next(pending)

    async def send(message: dict) -> None:
        pass

    await app({"type": "http", "headers": []}, receive, send)

    assert received == b"y" * 100 + b"z" * 50


def test_the_limit_can_be_disabled() -> None:
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    http, _ = _client(server, max_request_bytes=0)

    response = http.post(
        "/v1/chat/completions",
        json={
            "model": "openai-compat:m",
            "messages": [{"role": "user", "content": "x" * 100_000}],
        },
    )

    assert response.status_code == 200
