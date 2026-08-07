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


def test_target_grammar_works_as_a_model_string() -> None:
    """Federation is free precisely because a Target *is* an OpenAI model string."""
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    http, _ = _client(server)

    response = http.post(
        "/v1/chat/completions",
        json={"model": "openai-compat:some:model", "messages": [{"role": "user",
                                                                 "content": "hi"}]},
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
        c for c in chunks
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
    assert http.post(
        "/v1/chat/completions",
        json=body,
        headers={"authorization": "Bearer wrong-token-value"},
    ).status_code == 401
    assert http.post(
        "/v1/chat/completions",
        json=body,
        headers={"authorization": "Bearer secret-token-value"},
    ).status_code == 200


def test_models_also_requires_the_token() -> None:
    server = FakeOpenAIServer()
    http, _ = _client(server, auth_token="secret-token-value")
    assert http.get("/v1/models").status_code == 401


# ---- unsupported surface -------------------------------------------------------------


@pytest.mark.parametrize("path", ["/v1/embeddings", "/v1/images/generations", "/v1/audio"])
def test_unmodelled_endpoints_return_a_clear_404(path: str) -> None:
    """AnyInfer models text generation only; the rest must say so plainly (§22)."""
    server = FakeOpenAIServer()
    http, _ = _client(server)

    response = http.post(path, json={})
    assert response.status_code == 404
    assert "text generation only" in response.json()["error"]["message"]


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
