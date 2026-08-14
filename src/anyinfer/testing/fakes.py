"""In-process fake providers for tests, examples, and documentation builds.

Every code sample in the docs runs against these in CI, which is what stops examples from
rotting. They are also the fake-server mode of the conformance suite.

The fakes are httpx2 *transports*, not sockets: no ports, no cleanup races, and they work
identically on every platform.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx2

__all__ = [
    "FakeGeminiServer",
    "FakeOllamaServer",
    "FakeOpenAIServer",
    "FakeResponse",
    "chunk_text",
    "ndjson_lines",
    "sse_lines",
]


def chunk_text(text: str, size: int = 4) -> list[str]:
    """Split text into fixed-size fragments, mimicking token-level streaming."""
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def sse_lines(payloads: Iterable[Any], *, done: bool = True) -> bytes:
    """Encode payloads as an SSE body."""
    parts = [f"data: {json.dumps(p)}\n\n" for p in payloads]
    if done:
        parts.append("data: [DONE]\n\n")
    return "".join(parts).encode()


def ndjson_lines(payloads: Iterable[Any]) -> bytes:
    """Encode payloads as an NDJSON body (Ollama's framing)."""
    return "".join(f"{json.dumps(p)}\n" for p in payloads).encode()


@dataclass(frozen=True, slots=True)
class FakeResponse:
    """A scripted response the fake server should produce.

    Attributes:
        text: Assistant text to emit, chunked across deltas when streaming.
        reasoning: Thinking text to emit before the answer. Only dialects with a
            reasoning channel surface it (Ollama's ``thinking`` field, Gemini's
            ``thought``-flagged parts).
        tool_calls: Tool calls to emit, as ``(id, name, arguments_json)`` triples.
        finish_reason: Finish reason to report.
        usage: Usage block to report, or ``None`` to omit it entirely.
        status: HTTP status; ``>= 400`` produces an error body instead of a completion.
        error_message: Message for error responses.
        headers: Extra response headers (e.g. ``retry-after``).
        malformed_sse: Emit an unparseable SSE data field, to exercise error handling.
        ignore_stream: Answer a streaming request with a buffered JSON body.
        omit_usage_chunk: Stream without a terminal usage chunk.
    """

    text: str = "Hello from the fake provider."
    reasoning: str = ""
    tool_calls: tuple[tuple[str, str, str], ...] = ()
    finish_reason: str = "stop"
    usage: Mapping[str, Any] | None = field(
        default_factory=lambda: {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        }
    )
    status: int = 200
    error_message: str = "fake provider error"
    headers: Mapping[str, str] = field(default_factory=dict)
    malformed_sse: bool = False
    ignore_stream: bool = False
    omit_usage_chunk: bool = False


class _FakeServerBase:
    """Shared response-list bookkeeping and transport wiring for fake provider servers.

    Each dialect-specific subclass normalizes its constructor's ``responses`` argument
    through this base, then adds its own wire-shape-specific request handling in
    ``_handle``.
    """

    def __init__(self, responses: Sequence[FakeResponse] | FakeResponse | None) -> None:
        if responses is None:
            responses = [FakeResponse()]
        elif isinstance(responses, FakeResponse):
            responses = [responses]
        self._responses = list(responses)
        self._call_index = 0
        self.requests: list[dict[str, Any]] = []

    @property
    def call_count(self) -> int:
        """How many generation requests have been served."""
        return self._call_index

    def transport(self) -> httpx2.MockTransport:
        """Build an httpx2 transport that routes to this fake."""
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        raise NotImplementedError


class FakeOpenAIServer(_FakeServerBase):
    """A configurable in-process OpenAI-compatible endpoint.

    Args:
        responses: Responses to serve, one per request, in order. The last is reused once
            exhausted, so a single-element list serves every request.
        models: Model ids reported by ``GET /models``.
        chunk_size: Characters per streamed text delta.

    Attributes:
        requests: Every request body received, for assertions.
    """

    def __init__(
        self,
        responses: Sequence[FakeResponse] | FakeResponse | None = None,
        *,
        models: Sequence[str] = ("fake-model-small", "fake-model-large"),
        chunk_size: int = 4,
    ) -> None:
        super().__init__(responses)
        self._models = list(models)
        self._chunk_size = chunk_size

    def next_response(self) -> FakeResponse:
        """The response for the next generation call."""
        index = min(self._call_index, len(self._responses) - 1)
        return self._responses[index]

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/models"):
            return self._handle_models()
        if path.endswith("/chat/completions"):
            return self._handle_chat(request)
        return httpx2.Response(404, json={"error": {"message": f"no such path: {path}"}})

    def _handle_models(self) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [{"id": m, "object": "model"} for m in self._models],
            },
        )

    def _handle_chat(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append(body)
        response = self.next_response()
        self._call_index += 1

        if response.status >= 400:
            return httpx2.Response(
                response.status,
                json={"error": {"message": response.error_message, "type": "fake_error"}},
                headers=dict(response.headers),
            )

        wants_stream = bool(body.get("stream")) and not response.ignore_stream
        if wants_stream:
            return httpx2.Response(
                200,
                content=self._stream_body(response),
                headers={
                    "content-type": "text/event-stream",
                    **dict(response.headers),
                },
            )
        return httpx2.Response(
            200,
            json=self._completion_body(response),
            headers=dict(response.headers),
        )

    def _completion_body(self, response: FakeResponse) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": response.text or None}
        if response.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                }
                for call_id, name, args in response.tool_calls
            ]
        body: dict[str, Any] = {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "model": "fake-model-small",
            "choices": [{"index": 0, "message": message, "finish_reason": response.finish_reason}],
        }
        if response.usage is not None:
            body["usage"] = dict(response.usage)
        return body

    def _stream_body(self, response: FakeResponse) -> bytes:
        if response.malformed_sse:
            return b"data: {not json at all\n\n"

        chunks: list[dict[str, Any]] = []
        for fragment in chunk_text(response.text, self._chunk_size):
            if not fragment:
                continue
            chunks.append(self._delta_chunk({"content": fragment}))

        for index, (call_id, name, args) in enumerate(response.tool_calls):
            chunks.append(
                self._delta_chunk(
                    {
                        "tool_calls": [
                            {
                                "index": index,
                                "id": call_id,
                                "type": "function",
                                "function": {"name": name, "arguments": ""},
                            }
                        ]
                    }
                )
            )
            for fragment in chunk_text(args, self._chunk_size):
                chunks.append(
                    self._delta_chunk(
                        {"tool_calls": [{"index": index, "function": {"arguments": fragment}}]}
                    )
                )

        final = self._delta_chunk({})
        final["choices"][0]["finish_reason"] = response.finish_reason
        chunks.append(final)

        if response.usage is not None and not response.omit_usage_chunk:
            chunks.append(
                {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion.chunk",
                    "model": "fake-model-small",
                    "choices": [],
                    "usage": dict(response.usage),
                }
            )
        return sse_lines(chunks)

    def _delta_chunk(self, delta: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": "chatcmpl-fake",
            "object": "chat.completion.chunk",
            "model": "fake-model-small",
            "choices": [{"index": 0, "delta": dict(delta), "finish_reason": None}],
        }


class FakeGeminiServer(_FakeServerBase):
    """A configurable in-process Gemini endpoint speaking the native protocol.

    Args:
        responses: Responses to serve, one per request, in order. The last is reused once
            exhausted.
        models: Model ids reported by ``GET /models``.
        chunk_size: Characters per streamed text part.

    Attributes:
        requests: Every request body received, for assertions.
    """

    def __init__(
        self,
        responses: Sequence[FakeResponse] | FakeResponse | None = None,
        *,
        models: Sequence[str] = ("gemini-2.5-flash", "gemini-2.5-pro"),
        chunk_size: int = 4,
    ) -> None:
        super().__init__(responses)
        self._models = list(models)
        self._chunk_size = chunk_size

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/models"):
            return httpx2.Response(
                200,
                json={
                    "models": [
                        {
                            "name": f"models/{name}",
                            "inputTokenLimit": 1_048_576,
                            "outputTokenLimit": 65_536,
                            "supportedGenerationMethods": [
                                "generateContent",
                                "streamGenerateContent",
                            ],
                            "thinking": True,
                        }
                        for name in self._models
                    ]
                },
            )
        if ":streamGenerateContent" in path or ":generateContent" in path:
            return self._handle_generate(request, streaming=":stream" in path)
        return httpx2.Response(
            404, json={"error": {"code": 404, "message": f"no such path: {path}"}}
        )

    def _handle_generate(self, request: httpx2.Request, *, streaming: bool) -> httpx2.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append(body)
        index = min(self._call_index, len(self._responses) - 1)
        response = self._responses[index]
        self._call_index += 1

        if response.status >= 400:
            return httpx2.Response(
                response.status,
                json={
                    "error": {
                        "code": response.status,
                        "message": response.error_message,
                        "status": "RESOURCE_EXHAUSTED"
                        if response.status == 429
                        else "INVALID_ARGUMENT",
                    }
                },
                headers=dict(response.headers),
            )

        if not streaming:
            return httpx2.Response(200, json=self._body(response, parts=self._all_parts(response)))

        chunks = [
            self._body(response, parts=[part], usage=False) for part in self._all_parts(response)
        ] or [self._body(response, parts=[{"text": ""}], usage=False)]
        chunks[-1]["candidates"][0]["finishReason"] = _GEMINI_FINISH.get(
            response.finish_reason, response.finish_reason.upper()
        )
        if response.usage is not None and not response.omit_usage_chunk:
            chunks.append(self._body(response, parts=[], usage=True))
        return httpx2.Response(
            200,
            content=sse_lines(chunks, done=False),
            headers={"content-type": "text/event-stream", **dict(response.headers)},
        )

    def _all_parts(self, response: FakeResponse) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = [
            {"text": fragment, "thought": True}
            for fragment in chunk_text(response.reasoning, self._chunk_size)
            if fragment
        ]
        parts.extend(
            {"text": fragment}
            for fragment in chunk_text(response.text, self._chunk_size)
            if fragment
        )
        parts.extend(
            {"functionCall": {"id": call_id, "name": name, "args": json.loads(args)}}
            for call_id, name, args in response.tool_calls
        )
        return parts

    def _body(
        self,
        response: FakeResponse,
        *,
        parts: list[dict[str, Any]],
        usage: bool = True,
    ) -> dict[str, Any]:
        candidate: dict[str, Any] = {
            "content": {"role": "model", "parts": parts},
            "index": 0,
        }
        if usage:
            candidate["finishReason"] = _GEMINI_FINISH.get(
                response.finish_reason, response.finish_reason.upper()
            )
        body: dict[str, Any] = {
            "candidates": [candidate],
            "modelVersion": "fake-gemini",
        }
        if usage and response.usage is not None:
            body["usageMetadata"] = {
                "promptTokenCount": response.usage.get("prompt_tokens", 11),
                "candidatesTokenCount": response.usage.get("completion_tokens", 7),
                "totalTokenCount": response.usage.get("total_tokens", 18),
            }
        return body


_GEMINI_FINISH: Mapping[str, str] = {
    "stop": "STOP",
    "length": "MAX_TOKENS",
    "tool_calls": "STOP",
    "content_filter": "SAFETY",
}
"""Normalized finish reasons spelled the way Gemini reports them."""


class FakeOllamaServer(_FakeServerBase):
    """A configurable in-process Ollama server speaking the native NDJSON dialect.

    Args:
        responses: Responses to serve, one per request, in order. The last is reused once
            exhausted.
        models: Models reported by ``/api/tags``.
        loaded: ``model -> size_vram`` entries reported by ``/api/ps``, for GPU-spill tests.
        chunk_size: Characters per streamed text delta.

    Attributes:
        requests: Every request body received, for assertions.
    """

    def __init__(
        self,
        responses: Sequence[FakeResponse] | FakeResponse | None = None,
        *,
        models: Sequence[str] = ("qwen3:8b", "qwen2.5:3b"),
        loaded: Mapping[str, int] | None = None,
        chunk_size: int = 4,
        embed_scenario: str | None = None,
    ) -> None:
        super().__init__(responses)
        self._models = list(models)
        self._loaded = dict(loaded or {})
        self._chunk_size = chunk_size
        self._embed_scenario = embed_scenario
        self._embed_calls = 0
        self.pulled: list[str] = []
        self.pull_lines: list[dict[str, Any]] | None = None

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/api/embed"):
            body = json.loads(request.content or b"{}")
            raw_input = body.get("input", [])
            inputs = raw_input if isinstance(raw_input, list) else [raw_input]
            if self._embed_scenario == "rate_limited" and self._embed_calls == 0:
                self._embed_calls += 1
                return httpx2.Response(
                    429,
                    json={"error": "busy"},
                    headers={"retry-after": "0"},
                )
            self._embed_calls += 1
            if self._embed_scenario == "oversized":
                return httpx2.Response(
                    200,
                    json={
                        "model": body.get("model", ""),
                        "embeddings": [[0.1] * 20_000 for _ in inputs],
                        "prompt_eval_count": len(inputs),
                    },
                )
            return httpx2.Response(
                200,
                json={
                    "model": body.get("model", ""),
                    "embeddings": [[0.1, 0.2, 0.3, 0.4] for _ in inputs],
                    "prompt_eval_count": len(inputs),
                },
            )
        if path.endswith("/api/tags"):
            return httpx2.Response(
                200,
                json={
                    "models": [
                        {
                            "name": name,
                            "size": 4_400_000_000,
                            "details": {
                                "parameter_size": "8B",
                                "quantization_level": "Q4_K_M",
                            },
                        }
                        for name in self._models
                    ]
                },
            )
        if path.endswith("/api/ps"):
            return httpx2.Response(
                200,
                json={
                    "models": [
                        {"name": name, "size": 4_400_000_000, "size_vram": vram}
                        for name, vram in self._loaded.items()
                    ]
                },
            )
        if path.endswith("/api/pull"):
            return self._handle_pull(request)
        if path.endswith("/api/chat"):
            return self._handle_chat(request)
        return httpx2.Response(404, json={"error": f"no such path: {path}"})

    def _handle_pull(self, request: httpx2.Request) -> httpx2.Response:
        """Serve the NDJSON progress stream ``POST /api/pull`` produces."""
        body = json.loads(request.content or b"{}")
        self.pulled.append(str(body.get("model") or body.get("name") or ""))
        if self.pull_lines is not None:
            lines = self.pull_lines
        else:
            digest = "sha256:layer-one"
            lines = [
                {"status": "pulling manifest"},
                {
                    "status": "pulling " + digest,
                    "digest": digest,
                    "total": 8_000_000,
                    "completed": 4_000_000,
                },
                {
                    "status": "pulling " + digest,
                    "digest": digest,
                    "total": 8_000_000,
                    "completed": 8_000_000,
                },
                {"status": "verifying sha256 digest"},
                {"status": "success"},
            ]
        payload = "".join(json.dumps(line) + chr(10) for line in lines)
        return httpx2.Response(200, content=payload.encode("utf-8"))

    def _handle_chat(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append(body)
        index = min(self._call_index, len(self._responses) - 1)
        response = self._responses[index]
        self._call_index += 1

        if response.status >= 400:
            return httpx2.Response(
                response.status,
                json={"error": response.error_message},
                headers=dict(response.headers),
            )

        messages: list[dict[str, Any]] = []
        for fragment in chunk_text(response.reasoning, self._chunk_size):
            if fragment:
                messages.append(
                    {
                        "model": body.get("model", "fake"),
                        "message": {"role": "assistant", "thinking": fragment},
                        "done": False,
                    }
                )
        for fragment in chunk_text(response.text, self._chunk_size):
            if fragment:
                messages.append(
                    {
                        "model": body.get("model", "fake"),
                        "message": {"role": "assistant", "content": fragment},
                        "done": False,
                    }
                )

        for _, name, args in response.tool_calls:
            messages.append(
                {
                    "model": body.get("model", "fake"),
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": name, "arguments": json.loads(args)}}
                        ],
                    },
                    "done": False,
                }
            )

        terminal: dict[str, Any] = {
            "model": body.get("model", "fake"),
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop" if response.finish_reason == "stop" else response.finish_reason,
            "total_duration": 1_500_000_000,
            "load_duration": 300_000_000,
            "prompt_eval_duration": 200_000_000,
            "eval_duration": 1_000_000_000,
        }
        if response.usage is not None:
            terminal["prompt_eval_count"] = response.usage.get("prompt_tokens", 11)
            terminal["eval_count"] = response.usage.get("completion_tokens", 7)
        messages.append(terminal)

        return httpx2.Response(
            200,
            content=ndjson_lines(messages),
            headers={"content-type": "application/x-ndjson", **dict(response.headers)},
        )
