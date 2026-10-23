"""Public redirect policy controls for provider HTTP traffic.

The shared JSON fixture supplies only request/response stimuli.  These controls assert the
Python public client behavior independently; it is not a cross-language oracle.
"""

from __future__ import annotations

import json
import sys
import types
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import anyio
import httpx2
import pytest

from anyinfer.errors import TransportError
from anyinfer.providers.anthropic import AnthropicAdapter
from anyinfer.providers.azure_foundry import AzureFoundryAdapter
from anyinfer.providers.base import ProviderConfig, WireRequest
from anyinfer.providers.bedrock import BedrockAdapter
from anyinfer.providers.cloud_auth import GoogleTokenSource
from anyinfer.providers.gemini import GeminiAdapter
from anyinfer.providers.http import build_client, map_transport_error
from anyinfer.providers.m365_copilot import M365CopilotAdapter
from anyinfer.providers.presets import COMPAT_PRESETS, PresetCompatAdapter
from anyinfer.providers.vertex import VertexAdapter

FIXTURE = Path(__file__).with_name("fixtures") / "provider_redirects.json"


def _fixture_ids() -> set[str]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    return {case["id"] for case in payload["cases"]}


def _stimulus(case_id: str) -> dict[str, object]:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    return next(case for case in cases if case["id"] == case_id)


def _client(
    handler: httpx2.AsyncBaseTransport, *, headers: dict[str, str] | None = None
) -> httpx2.AsyncClient:
    return build_client(
        base_url="https://first.example",
        headers=headers,
        transport=handler,
        origin_bound_header_names=(headers or {}).keys(),
    )


@pytest.mark.anyio
async def test_shared_stimuli_inventory_is_input_only_and_complete() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    assert _fixture_ids() == {
        "same-origin",
        "post-rewrite",
        "cross-origin-sticky",
        "safe-upgrade",
        "relative-query-fragment",
        "terminal-missing-location",
        "cookies",
        "unsupported-userinfo",
    }
    for case in cases:
        assert set(case) == {"id", "request", "responses"}
        assert "expected" not in json.dumps(case).lower()


def _fixture_transport(case_id: str, seen: list[httpx2.Request]) -> httpx2.MockTransport:
    """Replay one shared input sequence while retaining every physical request."""
    stimulus = _stimulus(case_id)
    responses = stimulus["responses"]
    assert isinstance(responses, list)
    scripted: Iterator[dict[str, object]] = iter(responses)

    def handler(wire_request: httpx2.Request) -> httpx2.Response:
        seen.append(wire_request)
        response = next(scripted)
        status = response["status"]
        location = response.get("location")
        cookies = response.get("set_cookie", [])
        assert isinstance(status, int)
        assert location is None or isinstance(location, str)
        assert isinstance(cookies, list)
        assert all(isinstance(cookie, str) for cookie in cookies)
        headers = [("Set-Cookie", cookie) for cookie in cookies]
        if location is not None:
            headers.append(("Location", location))
        return httpx2.Response(status, headers=headers, request=wire_request)

    return httpx2.MockTransport(handler)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("case_id", "expected_urls", "expected_methods", "terminal_status"),
    [
        (
            "same-origin",
            [
                "https://first.example/v1/chat/completions",
                "https://first.example/next",
            ],
            ["POST", "POST"],
            200,
        ),
        (
            "post-rewrite",
            [
                "https://first.example/v1/chat/completions",
                "https://first.example/next",
            ],
            ["POST", "GET"],
            200,
        ),
        (
            "cross-origin-sticky",
            [
                "https://first.example/v1/chat/completions",
                "https://second.example/next",
                "https://first.example/return",
            ],
            ["POST", "POST", "POST"],
            200,
        ),
        (
            "safe-upgrade",
            ["http://first.example/models", "https://first.example/models"],
            ["GET", "GET"],
            200,
        ),
        (
            "relative-query-fragment",
            [
                "https://first.example/catalog/base",
                "https://first.example/catalog/base?page=2#fragment",
            ],
            ["GET", "GET"],
            200,
        ),
        ("terminal-missing-location", ["https://first.example/models"], ["GET"], 302),
        (
            "cookies",
            ["https://first.example/cookie", "https://first.example/cookie-next"],
            ["GET", "GET"],
            200,
        ),
    ],
)
async def test_shared_stimulus_has_literal_complete_hop_evidence(
    case_id: str,
    expected_urls: list[str],
    expected_methods: list[str],
    terminal_status: int,
) -> None:
    """Each selected input has an independently asserted public wire trace."""
    stimulus = _stimulus(case_id)
    request = stimulus["request"]
    assert isinstance(request, dict)
    method, path, body = request["method"], request["path"], request["body"]
    assert isinstance(method, str) and isinstance(path, str) and isinstance(body, str)
    seen: list[httpx2.Request] = []
    headers = {
        "Authorization": "Bearer fixture-token",
        "X-Configured": "fixture-configured",
        "Content-Length": "999",
        "Cookie": "literal=initial",
    }
    base_url = "http://first.example" if case_id == "safe-upgrade" else "https://first.example"
    async with build_client(
        base_url=base_url,
        headers=headers,
        transport=_fixture_transport(case_id, seen),
        origin_bound_header_names=headers.keys(),
    ) as client:
        response = await client.request(
            method, path, content=b'{"fixture":true}' if body == "json" else None
        )

    assert response.status_code == terminal_status
    assert [str(item.url) for item in seen] == expected_urls
    assert [item.method for item in seen] == expected_methods
    assert [item.headers["host"] for item in seen] == [
        "first.example" if item.url.host == "first.example" else "second.example" for item in seen
    ]
    assert seen[0].headers["authorization"] == "Bearer fixture-token"
    assert seen[0].headers["x-configured"] == "fixture-configured"
    if case_id == "same-origin":
        assert seen[1].content == b'{"fixture":true}'
        assert seen[1].headers["authorization"] == "Bearer fixture-token"
        assert seen[1].headers["x-configured"] == "fixture-configured"
    elif case_id == "post-rewrite":
        assert seen[1].content == b""
        assert "content-length" not in seen[1].headers
        assert "transfer-encoding" not in seen[1].headers
    elif case_id == "cross-origin-sticky":
        for item in seen[1:]:
            assert item.content == b'{"fixture":true}'
            assert "authorization" not in item.headers
            assert "x-configured" not in item.headers
            assert "cookie" not in item.headers
            assert item.headers["content-length"] == str(len(item.content))
            assert "transfer-encoding" not in item.headers
    elif case_id == "safe-upgrade":
        assert seen[1].headers["authorization"] == "Bearer fixture-token"
        assert seen[1].headers["x-configured"] == "fixture-configured"
    elif case_id == "relative-query-fragment":
        assert seen[1].url.query == b"page=2"
        assert seen[1].url.fragment == "fragment"
    elif case_id == "cookies":
        assert "literal=initial" not in seen[1].headers.get("cookie", "")
        assert "one=1" in seen[1].headers.get("cookie", "")
        assert "two=2" in seen[1].headers.get("cookie", "")


@pytest.mark.anyio
async def test_shared_unsupported_userinfo_stops_before_the_followed_send() -> None:
    """The userinfo stimulus is a defined transport failure, never a hidden success."""
    stimulus = _stimulus("unsupported-userinfo")
    request = stimulus["request"]
    assert isinstance(request, dict)
    seen: list[httpx2.Request] = []
    async with _client(_fixture_transport("unsupported-userinfo", seen)) as client:
        with pytest.raises(httpx2.LocalProtocolError):
            await client.request(str(request["method"]), str(request["path"]), content=b"{}")
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert str(seen[0].url) == "https://first.example/v1/chat/completions"
    assert seen[0].content == b"{}"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("name", "make_adapter", "credential_header"),
    [
        (
            "preset-x-api-key",
            lambda transport: PresetCompatAdapter(
                ProviderConfig(
                    provider_id="tabbyapi",
                    base_url="https://first.example",
                    api_key="preset-key",
                    headers={"accept": "application/custom"},
                    transport=transport,
                ),
                preset=next(item for item in COMPAT_PRESETS if item.id == "tabbyapi"),
            ),
            "x-api-key",
        ),
        (
            "anthropic-x-api-key",
            lambda transport: AnthropicAdapter(
                ProviderConfig(
                    provider_id="anthropic",
                    base_url="https://first.example",
                    api_key="anthropic-key",
                    headers={"accept": "application/custom"},
                    transport=transport,
                )
            ),
            "x-api-key",
        ),
        (
            "azure-api-key",
            lambda transport: AzureFoundryAdapter(
                ProviderConfig(
                    provider_id="azure-foundry",
                    base_url="https://first.example/openai/v1",
                    api_key="azure-key",
                    headers={"accept": "application/custom"},
                    transport=transport,
                )
            ),
            "api-key",
        ),
        (
            "gemini-x-goog-api-key",
            lambda transport: GeminiAdapter(
                ProviderConfig(
                    provider_id="gemini",
                    base_url="https://first.example",
                    api_key="gemini-key",
                    headers={"accept": "application/custom"},
                    transport=transport,
                )
            ),
            "x-goog-api-key",
        ),
        (
            "m365-bearer",
            lambda transport: M365CopilotAdapter(
                ProviderConfig(
                    provider_id="m365-copilot",
                    base_url="https://first.example",
                    api_key="m365-token",
                    headers={"accept": "application/custom"},
                    transport=transport,
                )
            ),
            "authorization",
        ),
    ],
    ids=lambda item: item if isinstance(item, str) else None,
)
async def test_builtin_constructor_client_dispatch_strips_declared_credential_without_default_fallback(
    name: str,
    make_adapter: Callable[[httpx2.AsyncBaseTransport], object],
    credential_header: str,
) -> None:
    """Actual builtin construction declares nonstandard credential provenance."""
    del name
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx2.Response(
                307,
                headers={"Location": "https://second.example/next"},
                request=request,
            )
        return httpx2.Response(200, request=request)

    adapter = make_adapter(httpx2.MockTransport(handler))
    try:
        # The adapter's own client is the construction seam shared by real operations;
        # this sends through it rather than manufacturing a generic client/header set.
        await adapter._client.post("/redirect-control", content=b"{}")
    finally:
        await adapter.aclose()

    assert len(seen) == 2
    assert credential_header in seen[0].headers
    assert seen[0].headers["accept"] == "application/custom"
    assert credential_header not in seen[1].headers
    assert "accept" not in seen[1].headers
    assert seen[1].headers["host"] == "second.example"


def _unsafe_follow_transport(
    seen: list[httpx2.Request], *, final_json: object | None = None
) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx2.Response(
                307,
                headers={"Location": "https://second.example/next"},
                request=request,
            )
        return (
            httpx2.Response(200, json=final_json, request=request)
            if final_json is not None
            else httpx2.Response(200, request=request)
        )

    return httpx2.MockTransport(handler)


@pytest.mark.anyio
async def test_azure_entra_auth_flow_marks_late_bearer_for_actual_unsafe_follow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch only the external Entra acquisition seam; HTTPX owns the auth flow."""
    from anyinfer.providers.azure_foundry import _EntraAuth

    monkeypatch.setattr(_EntraAuth, "_acquire", lambda self: ("entra-token", 4_102_444_800.0))
    seen: list[httpx2.Request] = []
    adapter = AzureFoundryAdapter(
        ProviderConfig(
            provider_id="azure-foundry",
            base_url="https://first.example/openai/v1",
            transport=_unsafe_follow_transport(seen),
        )
    )
    try:
        await adapter._client.post("/redirect-control", content=b"{}")
    finally:
        await adapter.aclose()

    assert seen[0].headers["authorization"] == "Bearer entra-token"
    assert "authorization" not in seen[1].headers


@pytest.mark.anyio
async def test_vertex_token_source_marks_late_bearer_for_actual_unsafe_follow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vertex obtains the token at its existing source seam, then sends normally."""
    monkeypatch.setattr(
        GoogleTokenSource, "_acquire", lambda self: ("vertex-token", 4_102_444_800.0)
    )
    seen: list[httpx2.Request] = []
    adapter = VertexAdapter(
        ProviderConfig(
            provider_id="vertex",
            base_url="https://first.example",
            options={"project": "fixture-project", "location": "global"},
            transport=_unsafe_follow_transport(seen),
        )
    )
    try:
        await adapter._client.post(
            adapter._model_path("gemini-2.5-flash", "generateContent"),
            content=b"{}",
            headers=adapter._request_headers(),
        )
    finally:
        await adapter.aclose()

    assert seen[0].headers["authorization"] == "Bearer vertex-token"
    assert "authorization" not in seen[1].headers


@pytest.mark.anyio
async def test_m365_interactive_acquisition_marks_late_bearer_for_actual_generate_follow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the interactive credential implementation is substituted for this control."""
    azure = types.ModuleType("azure")
    identity = types.ModuleType("azure.identity")

    class InteractiveBrowserCredential:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def get_token(self, *scopes: str) -> object:
            assert scopes == ("https://graph.microsoft.com/.default",)
            return types.SimpleNamespace(token="m365-late-token")

    identity.InteractiveBrowserCredential = InteractiveBrowserCredential
    azure.identity = identity
    monkeypatch.setitem(sys.modules, "azure", azure)
    monkeypatch.setitem(sys.modules, "azure.identity", identity)
    seen: list[httpx2.Request] = []
    adapter = M365CopilotAdapter(
        ProviderConfig(
            provider_id="m365-copilot",
            base_url="https://first.example",
            transport=_unsafe_follow_transport(
                seen,
                final_json={
                    "text": "answer",
                    "usage": {"promptTokens": 11, "completionTokens": 7},
                },
            ),
        )
    )
    try:
        async for _ in adapter.generate(WireRequest(model="m365-copilot", messages=())):
            pass
    finally:
        await adapter.aclose()

    assert seen[0].headers["authorization"] == "Bearer m365-late-token"
    assert "authorization" not in seen[1].headers


@pytest.mark.anyio
async def test_bedrock_sigv4_header_set_is_declared_and_removed_after_unsafe_follow() -> None:
    """Session-token signing metadata is observable before the shared redirect policy acts."""
    seen: list[httpx2.Request] = []
    adapter = BedrockAdapter(
        ProviderConfig(
            provider_id="bedrock",
            base_url="https://first.example",
            options={
                "region": "us-east-1",
                "aws_access_key_id": "AKIDFIXTURE",
                "aws_secret_access_key": "fixture-secret",
                "aws_session_token": "fixture-session-token",
            },
            transport=_unsafe_follow_transport(seen),
        )
    )
    body = b'{"messages":[]}'
    try:
        await adapter._client.post(
            "/model/fixture/converse",
            content=body,
            headers=adapter._auth_headers(
                method="POST", path="/model/fixture/converse", body=body
            ),
        )
    finally:
        await adapter.aclose()

    for name in ("authorization", "x-amz-date", "x-amz-content-sha256", "x-amz-security-token"):
        assert name in seen[0].headers
        assert name not in seen[1].headers
    assert seen[0].headers["x-amz-security-token"] == "fixture-session-token"


@pytest.mark.anyio
async def test_concurrent_redirect_chains_on_one_client_keep_origin_state_independent() -> None:
    """Two chains sharing a client cannot inherit one another's sticky stripping state."""
    seen: list[httpx2.Request] = []
    both_started = anyio.Event()
    release = anyio.Event()
    unsafe_hop_entered = anyio.Event()
    first_hops = 0

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal first_hops
        seen.append(request)
        if request.url.path in {"/one", "/two"}:
            first_hops += 1
            if first_hops == 2:
                both_started.set()
            with anyio.fail_after(15):
                await release.wait()
            if request.url.path == "/one":
                return httpx2.Response(
                    307, headers={"Location": "https://second.example/unsafe"}, request=request
                )
            with anyio.fail_after(15):
                await unsafe_hop_entered.wait()
            return httpx2.Response(307, headers={"Location": "/same"}, request=request)
        if request.url.host == "second.example":
            unsafe_hop_entered.set()
        return httpx2.Response(200, request=request)

    async with _client(
        httpx2.MockTransport(handler),
        headers={"Authorization": "Bearer independent", "X-Configured": "independent"},
    ) as client:
        async with anyio.create_task_group() as group:
            group.start_soon(client.get, "/one")
            group.start_soon(client.get, "/two")
            with anyio.fail_after(15):
                await both_started.wait()
            release.set()

    assert sorted(request.url.path for request in seen) == ["/one", "/same", "/two", "/unsafe"]
    unsafe = next(request for request in seen if request.url.path == "/unsafe")
    safe = next(request for request in seen if request.url.path == "/same")
    assert "authorization" not in unsafe.headers
    assert "x-configured" not in unsafe.headers
    assert safe.headers["authorization"] == "Bearer independent"
    assert safe.headers["x-configured"] == "independent"


@pytest.mark.anyio
async def test_cancel_during_entered_redirect_hop_preserves_cancellation_and_sends_no_third_hop() -> (
    None
):
    """Cancellation is coordinated at an entered second hop, without a timing sleep."""
    entered_followed_hop = anyio.Event()
    sends = 0
    cancelled: list[BaseException] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        if sends == 1:
            return httpx2.Response(307, headers={"Location": "/entered"}, request=request)
        entered_followed_hop.set()
        with anyio.fail_after(15):
            await anyio.Event().wait()
        raise AssertionError("unreachable")

    async with _client(httpx2.MockTransport(handler)) as client:

        async def request() -> None:
            try:
                await client.post("/start", content=b"body")
            except BaseException as exc:
                cancelled.append(exc)
                raise

        with anyio.CancelScope() as scope:
            async with anyio.create_task_group() as group:
                group.start_soon(request)
                with anyio.fail_after(15):
                    await entered_followed_hop.wait()
                scope.cancel()

    assert sends == 2
    assert len(cancelled) == 1
    assert isinstance(cancelled[0], anyio.get_cancelled_exc_class())


@pytest.mark.anyio
async def test_same_origin_retains_protected_values_and_replays_a_fresh_buffered_body() -> None:
    seen: list[httpx2.Request] = []
    stimulus = _stimulus("same-origin")
    responses = stimulus["responses"]
    assert isinstance(responses, list)

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        response = responses[len(seen) - 1]
        assert isinstance(response, dict)
        status = response["status"]
        location = response.get("location")
        assert isinstance(status, int)
        assert location is None or isinstance(location, str)
        return httpx2.Response(
            status,
            headers={"Location": location} if location is not None else {},
            request=request,
        )

    async with _client(
        httpx2.MockTransport(handler),
        headers={"Authorization": "Bearer key", "X-Configured": "value", "Content-Length": "999"},
    ) as client:
        response = await client.post("/v1/chat/completions", content=b'{"prompt":"one"}')

    assert response.status_code == 200
    assert len(seen) == 2
    assert seen[1].headers["authorization"] == "Bearer key"
    assert seen[1].headers["x-configured"] == "value"
    assert seen[0] is not seen[1]
    assert seen[1].content == b'{"prompt":"one"}'
    assert seen[1].headers["content-length"] == "999"


@pytest.mark.anyio
@pytest.mark.parametrize("status", [301, 302, 303])
async def test_post_rewrite_drops_body_and_stale_custom_framing(status: int) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return (
            httpx2.Response(status, headers={"Location": "/rewritten"}, request=request)
            if len(seen) == 1
            else httpx2.Response(200, request=request)
        )

    async with _client(httpx2.MockTransport(handler), headers={"Content-Length": "77"}) as client:
        await client.post("/source", content=b"body")

    assert seen[1].method == "GET"
    assert seen[1].content == b""
    assert seen[1].headers.get("content-length") != "77"
    assert "transfer-encoding" not in seen[1].headers


@pytest.mark.anyio
@pytest.mark.parametrize("status", [307, 308])
async def test_post_preserving_redirect_replays_body_without_reusing_the_request(
    status: int,
) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return (
            httpx2.Response(status, headers={"Location": "/preserved"}, request=request)
            if len(seen) == 1
            else httpx2.Response(200, request=request)
        )

    async with _client(httpx2.MockTransport(handler)) as client:
        await client.post("/source", content=b"body")

    assert seen[1].method == "POST"
    assert seen[1].content == b"body"
    assert seen[0] is not seen[1]


@pytest.mark.anyio
async def test_unsafe_crossing_strips_configured_and_adapter_credentials_stickily() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        locations = ["https://second.example/next", "https://first.example/return"]
        return (
            httpx2.Response(307, headers={"Location": locations[len(seen) - 1]}, request=request)
            if len(seen) < 3
            else httpx2.Response(200, request=request)
        )

    headers = {
        "Authorization": "Bearer key",
        "X-Api-Key": "key",
        "X-Goog-Api-Key": "gemini-key",
        "X-Amz-Date": "date",
        "X-Amz-Content-Sha256": "hash",
        "X-Amz-Security-Token": "session",
        "X-Ms-Authorization-Auxiliary": "late-auth",
        "Accept": "application/custom",
        "Content-Type": "custom/json",
        "X-Version": "v9",
    }
    async with _client(httpx2.MockTransport(handler), headers=headers) as client:
        await client.post("/source", content=b"{}")

    for request in seen[1:]:
        for name in headers:
            assert name.lower() not in request.headers
    assert seen[2].url.host == "first.example"
    assert seen[2].headers["host"] == "first.example"


@pytest.mark.anyio
async def test_only_default_port_same_host_http_to_https_keeps_protected_values() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return (
            httpx2.Response(
                308, headers={"Location": "https://first.example/secure"}, request=request
            )
            if len(seen) == 1
            else httpx2.Response(200, request=request)
        )

    async with build_client(
        base_url="http://first.example",
        headers={"Authorization": "Bearer key", "X-Configured": "value"},
        transport=httpx2.MockTransport(handler),
        origin_bound_header_names=("X-Configured",),
    ) as client:
        await client.get("/models")

    assert seen[1].headers["authorization"] == "Bearer key"
    assert seen[1].headers["x-configured"] == "value"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "location",
    [
        "https://first.example:444/secure",
        "http://first.example/again",
        "https://second.example/secure",
    ],
)
async def test_nondefault_upgrade_downgrade_and_host_change_strip_protected_names(
    location: str,
) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return (
            httpx2.Response(307, headers={"Location": location}, request=request)
            if len(seen) == 1
            else httpx2.Response(200, request=request)
        )

    async with build_client(
        base_url="https://first.example",
        headers={"Authorization": "Bearer key", "X-Configured": "value"},
        transport=httpx2.MockTransport(handler),
        origin_bound_header_names=("X-Configured",),
    ) as client:
        await client.get("/models")

    assert "authorization" not in seen[1].headers
    assert "x-configured" not in seen[1].headers


@pytest.mark.anyio
async def test_cookie_is_recalculated_on_redirect_and_final_cookie_reaches_next_operation() -> (
    None
):
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx2.Response(
                302,
                headers=[("Location", "/next"), ("Set-Cookie", "jar=one; Path=/")],
                request=request,
            )
        if len(seen) == 2:
            return httpx2.Response(
                200, headers=[("Set-Cookie", "final=two; Path=/")], request=request
            )
        return httpx2.Response(200, request=request)

    async with _client(httpx2.MockTransport(handler)) as client:
        await client.get("/start", headers={"Cookie": "literal=initial"})
        await client.get("/later")

    assert seen[0].headers["cookie"] == "literal=initial"
    assert "literal=initial" not in seen[1].headers.get("cookie", "")
    assert "jar=one" in seen[1].headers.get("cookie", "")
    assert "final=two" in seen[2].headers.get("cookie", "")


@pytest.mark.anyio
async def test_unsafe_origin_redirect_uses_destination_jar_cookie_not_configured_literal_cookie() -> (
    None
):
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return (
            httpx2.Response(
                307,
                headers={"Location": "https://second.example/next"},
                request=request,
            )
            if len(seen) == 1
            else httpx2.Response(200, request=request)
        )

    async with _client(
        httpx2.MockTransport(handler),
        headers={"Cookie": "literal=initial", "Authorization": "Bearer key"},
    ) as client:
        client.cookies.set("destination", "jar", domain="second.example", path="/")
        await client.get("/start")

    cookie = seen[1].headers.get("cookie", "")
    assert "literal=initial" not in cookie
    assert "destination=jar" in cookie
    assert "authorization" not in seen[1].headers


@pytest.mark.anyio
async def test_unknown_stream_with_unsafe_custom_framing_fails_before_follow_or_body_read() -> (
    None
):
    """An unsafe redirect cannot repair an unread protected framing length."""
    sends = 0
    stream_iterated = False

    class GuardedStream(httpx2.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            nonlocal stream_iterated
            stream_iterated = True
            raise AssertionError("redirect hook must not read an unknown request body")
            yield b""

        async def aclose(self) -> None:
            return None

    class ScriptedRedirectTransport(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
            nonlocal sends
            sends += 1
            return httpx2.Response(
                307,
                headers={"Location": "https://second.example/next"},
                request=request,
            )

    async with _client(ScriptedRedirectTransport(), headers={"Content-Length": "7"}) as client:
        request = client.build_request("POST", "/stream", content=GuardedStream())
        with pytest.raises(httpx2.LocalProtocolError):
            await client.send(request)

    assert sends == 1
    assert not stream_iterated


@pytest.mark.anyio
async def test_missing_location_is_terminal_and_userinfo_target_is_safe_transport_failure() -> (
    None
):
    terminal = httpx2.MockTransport(lambda request: httpx2.Response(302, request=request))
    async with _client(terminal) as client:
        response = await client.get("/models")
    assert response.status_code == 302

    unsafe = httpx2.MockTransport(
        lambda request: httpx2.Response(
            307, headers={"Location": "https://u:p@second.example/"}, request=request
        )
    )
    async with _client(unsafe) as client:
        with pytest.raises(httpx2.LocalProtocolError) as captured:
            await client.get("/models")
    error = map_transport_error(captured.value, provider="fixture")
    assert isinstance(error, TransportError)
    assert "u:p" not in str(error)


@pytest.mark.anyio
async def test_limit_is_exactly_twenty_followed_redirects_and_safe_failure_omits_planted_values() -> (
    None
):
    sends = 0
    planted = "x" * 80

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        return httpx2.Response(
            307, headers={"Location": f"/next?token={planted}"}, request=request
        )

    async with _client(httpx2.MockTransport(handler), headers={"X-Configured": planted}) as client:
        with pytest.raises(httpx2.TooManyRedirects) as captured:
            await client.get("/start")

    assert sends == 21
    mapped = map_transport_error(captured.value, provider="fixture")
    assert planted not in str(mapped)


@pytest.mark.anyio
async def test_redirect_read_failure_surfaces_owned_close_failure_with_causal_identity() -> None:
    """The retained public redirect engine exposes close failure after an entered read fault."""
    original = httpx2.ReadError("redirect-read-marker")
    cleanup = RuntimeError("redirect-close-marker")
    cleanup_attempted = anyio.Event()
    sends = 0

    class DualFaultStream(httpx2.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            raise original
            yield b""

        async def aclose(self) -> None:
            cleanup_attempted.set()
            raise cleanup

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        return httpx2.Response(
            307,
            headers={"Location": "/must-not-follow"},
            stream=DualFaultStream(),
            request=request,
        )

    client = _client(httpx2.MockTransport(handler))
    try:
        with pytest.raises(RuntimeError) as captured:
            await client.get("/start")
    finally:
        await client.aclose()

    assert captured.value is cleanup
    with anyio.fail_after(1):
        await cleanup_attempted.wait()
    assert sends == 1
    assert client.is_closed
    chain: list[BaseException] = []
    current: BaseException | None = captured.value
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__context__ or current.__cause__
    assert original in chain


@pytest.mark.anyio
async def test_response_close_failure_is_observable_without_a_prior_read_failure() -> None:
    """An independently failing response close remains observable through the public client."""
    cleanup = RuntimeError("standalone-close-marker")
    cleanup_attempted = anyio.Event()

    class CloseFaultStream(httpx2.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            if False:
                yield b""

        async def aclose(self) -> None:
            cleanup_attempted.set()
            raise cleanup

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, stream=CloseFaultStream(), request=request)

    async with _client(httpx2.MockTransport(handler)) as client:
        response = await client.send(client.build_request("GET", "/close"), stream=True)
        with pytest.raises(RuntimeError) as captured:
            await response.aclose()

    assert captured.value is cleanup
    with anyio.fail_after(1):
        await cleanup_attempted.wait()
