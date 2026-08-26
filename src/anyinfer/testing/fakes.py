"""In-process fake providers for tests, examples, and documentation builds.

Every code sample in the docs runs against these in CI, which is what stops examples from
rotting. They are also the fake-server mode of the conformance suite.

The fakes are httpx2 *transports*, not sockets: no ports, no cleanup races, and they work
identically on every platform.
"""

from __future__ import annotations

import binascii
import json
import struct
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import unquote

import httpx2

__all__ = [
    "CONFORMANCE_SCENARIOS",
    "FakeAnthropicServer",
    "FakeBedrockServer",
    "FakeGeminiServer",
    "FakeOllamaServer",
    "FakeOpenAIServer",
    "FakeResponse",
    "FakeResponsesBatchServer",
    "FakeResponsesServer",
    "FakeRetrievalServer",
    "chunk_text",
    "eventstream_frame",
    "ndjson_lines",
    "scenario_responses",
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
        logprobs: Report these per-token log-probabilities, as ``(token, logprob)``
            pairs, but **only when the request asked for them**. A fake that answered
            with log-probabilities nobody requested would let an adapter that never sends
            the field pass a test for sending it.
        top_logprobs: Alternatives to attach to each reported token, as ``(token,
            logprob)`` pairs. Sent only when the request asked for a positive count.
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
    logprobs: tuple[tuple[str, float], ...] = ()
    top_logprobs: tuple[tuple[str, float], ...] = ()


CONFORMANCE_SCENARIOS: tuple[str, ...] = (
    "default",
    "tools",
    "reasoning",
    "structured",
    "repair",
    "auth_error",
    "rate_limited",
    "oversized",
    "odd_finish",
)
"""Every scenario key `run_conformance` hands to a harness's client factory."""

_PROBE_ANSWER = json.dumps({"answer": "ok"})


def scenario_responses(
    scenario: str,
    *,
    text: str = "Hello from the fake provider.",
    reasoning: str = "Let me think.",
    probe_answer: str = _PROBE_ANSWER,
) -> list[FakeResponse]:
    """The canonical response programme for one conformance scenario.

    Every harness answers the same nine scenarios with the same *shapes*: a tool call for
    ``tools``, an invalid-then-valid pair for ``repair``, a 401 for ``auth_error``, and so
    on. Only the wire encoding differs per dialect, and the fake server classes already own
    that. Programming the scenarios here means a new adapter's harness declares its dialect
    and its capabilities — never a ninth copy of the same if/elif chain, which is exactly
    where a subtly weaker probe slips into one provider's column unnoticed.

    Args:
        scenario: A key from `CONFORMANCE_SCENARIOS`. An unrecognized key is treated as
            ``default``, so a harness never has to enumerate them.
        text: Assistant text for the scenarios that just need a successful answer.
        reasoning: Thinking text for the ``reasoning`` scenario. Dialects without a
            reasoning channel ignore it and declare ``reasoning=False`` instead.
        probe_answer: The JSON answer satisfying `PROBE_SCHEMA`.

    Returns:
        Responses to serve in order. The fake servers reuse the last one once exhausted,
        so a single-element list answers every request in the scenario.
    """
    if scenario == "tools":
        return [
            FakeResponse(
                text="",
                tool_calls=(("call_0", "lookup", json.dumps({"key": "alpha"})),),
                finish_reason="tool_calls",
            )
        ]
    if scenario == "reasoning":
        return [FakeResponse(text=text, reasoning=reasoning)]
    if scenario == "structured":
        return [FakeResponse(text=probe_answer)]
    if scenario == "repair":
        # The first answer validates against nothing; the repair loop must recover.
        return [FakeResponse(text=json.dumps({"wrong": True})), FakeResponse(text=probe_answer)]
    if scenario == "auth_error":
        return [FakeResponse(status=401, error_message="invalid token")]
    if scenario == "rate_limited":
        return [
            FakeResponse(status=429, error_message="busy", headers={"retry-after": "0"}),
            FakeResponse(text="recovered"),
        ]
    if scenario == "oversized":
        return [FakeResponse(text="x" * 20_000)]
    if scenario == "odd_finish":
        return [FakeResponse(text=text, finish_reason="model_decided")]
    return [FakeResponse(text=text)]


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
        reasoning_field: Name of the dialect's reasoning key (DeepSeek and xAI both
            send ``reasoning_content``). ``None`` — the plain OpenAI shape — omits
            reasoning entirely, so an adapter with no reasoning channel cannot
            accidentally pass the reasoning case.
        dimensions: Width of the vectors ``POST /embeddings`` returns.

    Attributes:
        requests: Every request body received, for assertions.
    """

    def __init__(
        self,
        responses: Sequence[FakeResponse] | FakeResponse | None = None,
        *,
        models: Sequence[str] = ("fake-model-small", "fake-model-large"),
        chunk_size: int = 4,
        reasoning_field: str | None = None,
        dimensions: int = 8,
    ) -> None:
        super().__init__(responses)
        self._models = list(models)
        self._chunk_size = chunk_size
        self._reasoning_field = reasoning_field
        self._dimensions = dimensions

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
        if path.endswith("/embeddings"):
            return self._handle_embeddings(request)
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

        asked_for_logprobs = bool(body.get("logprobs"))
        wants_alternatives = asked_for_logprobs and bool(body.get("top_logprobs"))
        wants_stream = bool(body.get("stream")) and not response.ignore_stream
        if wants_stream:
            return httpx2.Response(
                200,
                content=self._stream_body(
                    response, logprobs=asked_for_logprobs, alternatives=wants_alternatives
                ),
                headers={
                    "content-type": "text/event-stream",
                    **dict(response.headers),
                },
            )
        return httpx2.Response(
            200,
            json=self._completion_body(
                response, logprobs=asked_for_logprobs, alternatives=wants_alternatives
            ),
            headers=dict(response.headers),
        )

    def _handle_embeddings(self, request: httpx2.Request) -> httpx2.Response:
        """Serve ``POST /embeddings``, sharing the scenario script with generation.

        Failure scenarios must reach embeddings the same way they reach chat, or a
        provider's ``embedding_retry_after`` column would claim a retry path that was
        never exercised. Vectors are derived from the input text so duplicate inputs
        produce identical vectors and the positional-preservation case is meaningful.
        """
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

        raw = body.get("input", [])
        inputs = [raw] if isinstance(raw, str) else list(raw)
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "model": body.get("model", "fake-embedding-model"),
                "data": [
                    {
                        "object": "embedding",
                        "index": index,
                        "embedding": self._vector(str(text)),
                    }
                    for index, text in enumerate(inputs)
                ],
                "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
            },
            headers=dict(response.headers),
        )

    def _vector(self, text: str) -> list[float]:
        """A deterministic, unnormalized vector for ``text``.

        Deliberately not unit-length: the normalization probe must *measure* the answer,
        so a fake that always returned normalized vectors would hide an adapter that
        merely assumed it.
        """
        seed = sum(ord(c) for c in text) or 1
        return [round(((seed * (i + 1)) % 97) / 97 + 0.05, 6) for i in range(self._dimensions)]

    def _logprobs_block(
        self, response: FakeResponse, *, alternatives: bool
    ) -> dict[str, Any] | None:
        """The dialect's ``logprobs`` object, or ``None`` when the script has none."""
        if not response.logprobs:
            return None
        top = (
            [
                {"token": token, "logprob": logprob, "bytes": list(token.encode())}
                for token, logprob in response.top_logprobs
            ]
            if alternatives
            else []
        )
        return {
            "content": [
                {
                    "token": token,
                    "logprob": logprob,
                    "bytes": list(token.encode()),
                    "top_logprobs": top,
                }
                for token, logprob in response.logprobs
            ]
        }

    def _completion_body(
        self, response: FakeResponse, *, logprobs: bool = False, alternatives: bool = False
    ) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": response.text or None}
        if response.reasoning and self._reasoning_field:
            message[self._reasoning_field] = response.reasoning
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
        if logprobs:
            block = self._logprobs_block(response, alternatives=alternatives)
            if block is not None:
                body["choices"][0]["logprobs"] = block
        if response.usage is not None:
            body["usage"] = dict(response.usage)
        return body

    def _stream_body(
        self, response: FakeResponse, *, logprobs: bool = False, alternatives: bool = False
    ) -> bytes:
        if response.malformed_sse:
            return b"data: {not json at all\n\n"

        chunks: list[dict[str, Any]] = []
        if self._reasoning_field:
            for fragment in chunk_text(response.reasoning, self._chunk_size):
                if not fragment:
                    continue
                chunks.append(self._delta_chunk({self._reasoning_field: fragment}))
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
        if logprobs:
            block = self._logprobs_block(response, alternatives=alternatives)
            if block is not None:
                # One chunk carrying every token, which is the shape a provider produces
                # when its last delta closes the message. The adapter accumulates across
                # chunks, so a single-chunk script still exercises the accumulation path.
                final["choices"][0]["logprobs"] = block
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


class FakeResponsesBatchServer(_FakeServerBase):
    """The OpenAI Batch API's three-step lifecycle, in process.

    Deliberately models all three steps rather than collapsing them: a JSONL file is
    uploaded to ``/files``, the batch references it by id, and results come back as *two*
    more files — successes in ``output_file_id`` and rejections in ``error_file_id``. An
    adapter that read only the first would silently drop every failure and return a batch
    that looks smaller than it was, which is a fake's job to catch.

    Args:
        responses: Scenario script. Only ``text`` and ``status`` apply here.
        polls_before_done: Status polls the batch reports in progress for before it ends.
            At least one, so a caller must always poll — a fake that finished immediately
            could not exercise the poll-then-fetch shape a deferred API exists for.
        failures: How many lines land in the error file rather than the output file.
        dialect: Which body shape answered lines carry. ``responses`` is OpenAI's own;
            ``chat`` is what every provider that copied the Batch API onto chat
            completions returns (Groq). The lifecycle is byte-identical between them —
            only the line bodies differ — which is exactly why one fake covers both.

    Attributes:
        requests: Every request body received, for assertions.
        uploaded: The JSONL text of each uploaded input file, in order.
    """

    def __init__(
        self,
        responses: Sequence[FakeResponse] | FakeResponse | None = None,
        *,
        polls_before_done: int = 1,
        failures: int = 0,
        dialect: Literal["responses", "chat"] = "responses",
    ) -> None:
        super().__init__(responses)
        self.polls_before_done = max(1, polls_before_done)
        self.failures = failures
        self.dialect = dialect
        self.uploaded: list[str] = []
        self._lines: list[str] = []
        self._polls = 0
        self._cancelled = False

    def next_response(self) -> FakeResponse:
        """The response every line's body is built from."""
        return self._responses[min(self._call_index, len(self._responses) - 1)]

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/files") and request.method == "POST":
            return self._handle_upload(request)
        if "/files/" in path and path.endswith("/content"):
            return self._handle_download(path)
        if path.endswith("/batches") and request.method == "POST":
            return self._handle_submit(request)
        if path.endswith("/cancel"):
            self._cancelled = True
            return httpx2.Response(200, json=self._batch_object())
        if "/batches/" in path:
            self._polls += 1
            return httpx2.Response(200, json=self._batch_object())
        return httpx2.Response(404, json={"error": {"message": f"no such path: {path}"}})

    def _handle_upload(self, request: httpx2.Request) -> httpx2.Response:
        """Accept the multipart upload and remember its JSONL, for assertions."""
        body = request.content.decode("utf-8", "replace")
        # Pull the file part out of the multipart envelope without a parser: every line
        # that looks like one of our own JSONL records is one.
        self.uploaded.append(
            "\n".join(line for line in body.splitlines() if line.startswith('{"custom_id"'))
        )
        self._lines = [
            json.loads(line)["custom_id"]
            for line in self.uploaded[-1].splitlines()
            if line.strip()
        ]
        return httpx2.Response(200, json={"id": "file-input", "object": "file"})

    def _handle_submit(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append(body)
        self._polls = 0
        self._cancelled = False
        return httpx2.Response(200, json=self._batch_object())

    def _batch_object(self) -> dict[str, Any]:
        done = self._cancelled or self._polls >= self.polls_before_done
        failures = min(self.failures, len(self._lines))
        status = "cancelled" if self._cancelled else ("completed" if done else "in_progress")
        body: dict[str, Any] = {
            "id": "batch_fake",
            "object": "batch",
            "status": status,
            "request_counts": {
                "total": len(self._lines),
                "completed": len(self._lines) - failures if done else 0,
                "failed": failures if done else 0,
            },
        }
        if done:
            body["output_file_id"] = "file-output"
            if failures:
                body["error_file_id"] = "file-errors"
        return body

    def _handle_download(self, path: str) -> httpx2.Response:
        failures = min(self.failures, len(self._lines))
        succeeded = self._lines[failures:]
        rejected = self._lines[:failures]
        if path.endswith("file-errors/content"):
            return httpx2.Response(200, text=self._error_manifest(rejected))
        return httpx2.Response(200, text=self._output_manifest(succeeded))

    def _output_manifest(self, custom_ids: Sequence[str]) -> str:
        """Successful lines, in *completion* order — which is not submission order."""
        response = self.next_response()
        entries = [
            {
                "id": f"batch_req_{custom_id}",
                "custom_id": custom_id,
                "response": {
                    "status_code": 200,
                    "body": self._line_body(custom_id, f"{response.text} #{custom_id}"),
                },
                "error": None,
            }
            for custom_id in custom_ids
        ]
        return "\n".join(json.dumps(entry) for entry in reversed(entries))

    def _line_body(self, custom_id: str, text: str) -> dict[str, Any]:
        """One answered line's body, in whichever dialect this fake serves."""
        if self.dialect == "chat":
            return {
                "id": f"chatcmpl_{custom_id}",
                "object": "chat.completion",
                "model": "fake-chat",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            }
        return {
            "id": f"resp_{custom_id}",
            "object": "response",
            "status": "completed",
            "model": "fake-gpt",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
            "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
        }

    def _error_manifest(self, custom_ids: Sequence[str]) -> str:
        """Rejected lines, which live in their own file rather than beside the successes."""
        return "\n".join(
            json.dumps(
                {
                    "id": f"batch_req_{custom_id}",
                    "custom_id": custom_id,
                    "response": None,
                    "error": {"code": "invalid_request", "message": "line rejected"},
                }
            )
            for custom_id in custom_ids
        )


class FakeRetrievalServer(_FakeServerBase):
    """An in-process endpoint for retrieval-only providers (Voyage, Jina).

    These providers speak a narrow dialect: ``POST /embeddings`` in the OpenAI shape, a
    ``POST /rerank`` that differs only in which key holds the ranking, and no listing
    route at all. Sharing one fake keeps their conformance rows honest about the same
    scenarios every other adapter answers.

    Args:
        responses: Scenario script, as for the other fakes. Only ``status``, ``headers``,
            and ``error_message`` apply — there is no text to generate.
        dimensions: Width of the vectors ``POST /embeddings`` returns.
        rerank_key: Key holding the ranking. Voyage uses ``data``; Jina uses ``results``.
        top_n_key: Request key carrying the truncation count. Voyage spells it
            ``top_k``; Jina sends a plain ``top_n``. A fake that accepted either
            would let an adapter send the wrong one and still pass.
        models_status: Status for ``GET /models``. These providers document no listing
            route, so the honest default is a 404 that still proves reachability.

    Attributes:
        requests: Every request body received, for assertions.
    """

    def __init__(
        self,
        responses: Sequence[FakeResponse] | FakeResponse | None = None,
        *,
        dimensions: int = 8,
        rerank_key: str = "data",
        top_n_key: str = "top_n",
        models_status: int = 404,
    ) -> None:
        super().__init__(responses)
        self._dimensions = dimensions
        self._rerank_key = rerank_key
        self._top_n_key = top_n_key
        self._models_status = models_status

    def next_response(self) -> FakeResponse:
        """The response for the next retrieval call."""
        index = min(self._call_index, len(self._responses) - 1)
        return self._responses[index]

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/models"):
            return httpx2.Response(
                self._models_status, json={"detail": "no listing API on this provider"}
            )
        if path.endswith("/embeddings"):
            return self._retrieval(request, self._embedding_body)
        if path.endswith("/rerank"):
            return self._retrieval(request, self._rerank_body)
        return httpx2.Response(404, json={"detail": f"no such path: {path}"})

    def _retrieval(
        self,
        request: httpx2.Request,
        build: Callable[[Mapping[str, Any]], dict[str, Any]],
    ) -> httpx2.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append(body)
        response = self.next_response()
        self._call_index += 1
        if response.status >= 400:
            return httpx2.Response(
                response.status,
                json={"detail": response.error_message},
                headers=dict(response.headers),
            )
        return httpx2.Response(200, json=build(body), headers=dict(response.headers))

    def _embedding_body(self, body: Mapping[str, Any]) -> dict[str, Any]:
        raw = body.get("input", [])
        inputs = [raw] if isinstance(raw, str) else list(raw)
        return {
            "object": "list",
            "model": body.get("model", "fake-embedding-model"),
            # Deliberately reversed: entries carry their index, and an adapter that
            # trusts arrival order instead must fail this.
            "data": [
                {"object": "embedding", "index": index, "embedding": self._vector(str(text))}
                for index, text in reversed(list(enumerate(inputs)))
            ],
            "usage": {"total_tokens": len(inputs)},
        }

    def _rerank_body(self, body: Mapping[str, Any]) -> dict[str, Any]:
        documents = list(body.get("documents", []))
        top_n = body.get(self._top_n_key)
        # Descending by construction; the caller's order is the tie-break.
        ranked = [
            {"index": index, "relevance_score": round(1.0 - index * 0.1, 4)}
            for index in range(len(documents))
        ]
        if isinstance(top_n, int):
            ranked = ranked[:top_n]
        return {self._rerank_key: ranked, "model": body.get("model", "fake-rerank-model")}

    def _vector(self, text: str) -> list[float]:
        """A deterministic, unnormalized vector for ``text``."""
        seed = sum(ord(c) for c in text) or 1
        return [round(((seed * (i + 1)) % 97) / 97 + 0.05, 6) for i in range(self._dimensions)]


class FakeResponsesServer(_FakeServerBase):
    """A configurable in-process OpenAI **Responses API** endpoint.

    Not the same dialect as `FakeOpenAIServer`, which speaks ``/chat/completions``. The
    Responses protocol is *typed events* — ``response.output_text.delta``,
    ``response.output_item.added``, ``response.completed`` — rather than choice deltas, and
    a finish reason is derived from the terminal response object's ``status`` and
    ``incomplete_details`` rather than sent as a field. Modelling that difference is the
    point: an adapter that quietly treated one as the other would pass a chat-shaped fake.

    Args:
        responses: Responses to serve, one per request, in order. The last is reused once
            exhausted, so a single-element list serves every request.
        models: Model ids reported by ``GET /models``.
        chunk_size: Characters per streamed text delta.
        dimensions: Width of the vectors ``POST /embeddings`` returns.

    Attributes:
        requests: Every request body received, for assertions.
    """

    def __init__(
        self,
        responses: Sequence[FakeResponse] | FakeResponse | None = None,
        *,
        models: Sequence[str] = ("gpt-5", "gpt-5-mini"),
        chunk_size: int = 4,
        dimensions: int = 8,
    ) -> None:
        super().__init__(responses)
        self._models = list(models)
        self._chunk_size = chunk_size
        self._dimensions = dimensions

    def next_response(self) -> FakeResponse:
        """The response for the next generation call."""
        index = min(self._call_index, len(self._responses) - 1)
        return self._responses[index]

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/models"):
            return httpx2.Response(
                200,
                json={
                    "object": "list",
                    "data": [{"id": m, "object": "model"} for m in self._models],
                },
            )
        if path.endswith("/responses"):
            return self._handle_responses(request)
        if path.endswith("/embeddings"):
            return self._handle_embeddings(request)
        return httpx2.Response(404, json={"error": {"message": f"no such path: {path}"}})

    def _consume(self, request: httpx2.Request) -> tuple[dict[str, Any], FakeResponse]:
        body = json.loads(request.content or b"{}")
        self.requests.append(body)
        response = self.next_response()
        self._call_index += 1
        return body, response

    def _handle_responses(self, request: httpx2.Request) -> httpx2.Response:
        _body, response = self._consume(request)
        if response.status >= 400:
            return httpx2.Response(
                response.status,
                json={"error": {"message": response.error_message, "type": "fake_error"}},
                headers=dict(response.headers),
            )
        return httpx2.Response(
            200,
            content=self._stream_body(response),
            headers={"content-type": "text/event-stream", **dict(response.headers)},
        )

    def _handle_embeddings(self, request: httpx2.Request) -> httpx2.Response:
        body, response = self._consume(request)
        if response.status >= 400:
            return httpx2.Response(
                response.status,
                json={"error": {"message": response.error_message, "type": "fake_error"}},
                headers=dict(response.headers),
            )
        raw = body.get("input", [])
        inputs = [raw] if isinstance(raw, str) else list(raw)
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "model": body.get("model", "text-embedding-3-small"),
                "data": [
                    {"object": "embedding", "index": i, "embedding": self._vector(str(text))}
                    for i, text in enumerate(inputs)
                ],
                "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
            },
            headers=dict(response.headers),
        )

    def _vector(self, text: str) -> list[float]:
        """A deterministic, unnormalized vector for ``text``."""
        seed = sum(ord(c) for c in text) or 1
        return [round(((seed * (i + 1)) % 97) / 97 + 0.05, 6) for i in range(self._dimensions)]

    def _stream_body(self, response: FakeResponse) -> bytes:
        if response.malformed_sse:
            return b"data: {not json at all\n\n"

        events: list[dict[str, Any]] = []
        for fragment in chunk_text(response.reasoning, self._chunk_size):
            if fragment:
                events.append({"type": "response.reasoning_text.delta", "delta": fragment})
        for fragment in chunk_text(response.text, self._chunk_size):
            if fragment:
                events.append({"type": "response.output_text.delta", "delta": fragment})

        for index, (call_id, name, args) in enumerate(response.tool_calls):
            events.append(
                {
                    "type": "response.output_item.added",
                    "output_index": index,
                    "item": {"type": "function_call", "call_id": call_id, "name": name},
                }
            )
            events.extend(
                {
                    "type": "response.function_call_arguments.delta",
                    "output_index": index,
                    "delta": fragment,
                }
                for fragment in chunk_text(args, self._chunk_size)
                if fragment
            )

        terminal: dict[str, Any] = {"status": "completed"}
        if response.usage is not None:
            terminal["usage"] = {
                "input_tokens": response.usage.get("prompt_tokens", 11),
                "output_tokens": response.usage.get("completion_tokens", 7),
                "total_tokens": response.usage.get("total_tokens", 18),
            }
        kind = "response.completed"
        if response.finish_reason not in ("stop", "tool_calls"):
            # Responses reports an early stop as `incomplete` with a reason, not as a
            # finish-reason string; an unrecognized reason must still normalize.
            kind = "response.incomplete"
            terminal["status"] = "incomplete"
            terminal["incomplete_details"] = {"reason": response.finish_reason}
        events.append({"type": kind, "response": terminal})
        return sse_lines(events, done=False)


def eventstream_frame(event_type: str, payload: Any) -> bytes:
    """Encode one ``application/vnd.amazon.eventstream`` frame.

    AWS frames its Converse stream in a binary envelope with two CRC32s rather than in
    SSE, so a fake that returned JSON lines would exercise a decoder the adapter does not
    have. The checksums are computed, not stubbed: an adapter that skips validating them
    should not be able to pass by being handed frames that were never valid.
    """
    body = json.dumps(payload).encode("utf-8")
    headers = b""
    for name, value in ((":event-type", event_type), (":message-type", "event")):
        encoded = value.encode("utf-8")
        headers += bytes([len(name)]) + name.encode("ascii")
        headers += bytes([7]) + struct.pack(">H", len(encoded)) + encoded
    total = 12 + len(headers) + len(body) + 4
    prelude = struct.pack(">II", total, len(headers))
    prelude += struct.pack(">I", binascii.crc32(prelude) & 0xFFFFFFFF)
    frame = prelude + headers + body
    return frame + struct.pack(">I", binascii.crc32(frame) & 0xFFFFFFFF)


class FakeBedrockServer(_FakeServerBase):
    """A configurable in-process Bedrock endpoint spanning its four actions.

    Bedrock is not one API. Generation is ``/model/{id}/converse`` buffered or
    ``/model/{id}/converse-stream`` in AWS's binary event framing; Titan embeddings are
    ``/model/{id}/invoke`` on the same runtime host; rerank is a *different service*
    (``bedrock-agent-runtime``'s ``POST /rerank``); and discovery is a *different host*
    again (the control plane's ``/foundation-models``). Routing all four through one fake
    is what lets the shared suite treat Bedrock as one provider the way a caller does.

    Two Converse details the fake models deliberately. Usage arrives **only** in the
    terminal ``metadata`` event, so a stream that ends at ``messageStop`` reports no
    tokens — an adapter reading usage from the wrong event silently loses it. And a
    schema is emulated as a forced tool call, so the structured answer arrives as a
    ``toolUse`` block rather than as text.

    Args:
        responses: Responses to serve, one per request, in order. The last is reused once
            exhausted, so a single-element list serves every request.
        models: Model ids reported by the control plane's ``/foundation-models``.
        chunk_size: Characters per streamed text delta.
        dimensions: Width of the vectors ``/invoke`` returns.
        batch_polls_before_done: Status polls a submitted job reports in progress for
            before it finishes. At least one, so a caller must always poll.
        batch_failures: How many records come back carrying an ``error`` rather than a
            ``modelOutput``. Bedrock puts both in the same object, unlike OpenAI's two
            files, and an adapter that assumed one or the other would drop them.

    Attributes:
        requests: Every request body received, for assertions.
        objects: Every S3 object written, keyed by URL — a batch is staged in the
            caller's own bucket rather than uploaded over the API, so the fake has to
            stand in for S3 as well as for Bedrock.
    """

    def __init__(
        self,
        responses: Sequence[FakeResponse] | FakeResponse | None = None,
        *,
        models: Sequence[str] = (
            "anthropic.claude-sonnet-4-5-v1:0",
            "amazon.titan-embed-text-v2:0",
        ),
        chunk_size: int = 4,
        dimensions: int = 8,
        batch_polls_before_done: int = 1,
        batch_failures: int = 0,
    ) -> None:
        super().__init__(responses)
        self._models = list(models)
        self._chunk_size = chunk_size
        self._dimensions = dimensions
        self.objects: dict[str, bytes] = {}
        self.batch_polls_before_done = max(1, batch_polls_before_done)
        self.batch_failures = batch_failures
        self._batch_polls = 0
        self._batch_stopped = False
        self._batch_records: list[str] = []

    def next_response(self) -> FakeResponse:
        """The response for the next call."""
        index = min(self._call_index, len(self._responses) - 1)
        return self._responses[index]

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if ".s3." in request.url.host:
            return self._handle_s3(request)
        if "/model-invocation-job" in path:
            return self._handle_batch(request)
        if path.endswith("/foundation-models"):
            return httpx2.Response(
                200,
                json={
                    "modelSummaries": [
                        {"modelId": model, "providerName": "fake"} for model in self._models
                    ]
                },
            )
        if path.endswith("/converse-stream"):
            return self._streaming(request)
        if path.endswith("/converse"):
            return self._buffered(request)
        if path.endswith("/invoke"):
            return self._embed(request)
        if path.endswith("/rerank"):
            return self._rerank(request)
        return httpx2.Response(404, json={"message": f"no such path: {path}"})

    # ---- deferred batches, and the bucket they are staged in ---------------------------

    def _handle_s3(self, request: httpx2.Request) -> httpx2.Response:
        """Stand in for the caller's own S3 bucket.

        Bedrock's batch tier never carries the job over the API: the input is an object
        the client writes and the output is an object it reads. Modeling that here rather
        than pretending the API takes the lines is the point — an adapter that skipped the
        staging step would pass a fake that skipped it too.
        """
        key = str(request.url)
        if request.method == "PUT":
            self.objects[key] = request.content
            self._batch_records = [
                json.loads(line)["recordId"]
                for line in request.content.decode("utf-8").splitlines()
                if line.strip()
            ]
            return httpx2.Response(200)
        if key in self.objects:
            return httpx2.Response(200, content=self.objects[key])
        if key.endswith(".jsonl.out"):
            return httpx2.Response(200, text=self._batch_manifest())
        return httpx2.Response(404, text="<Error><Code>NoSuchKey</Code></Error>")

    def _handle_batch(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/model-invocation-job"):
            self.requests.append(json.loads(request.content or b"{}"))
            self._batch_polls = 0
            self._batch_stopped = False
            return httpx2.Response(
                200,
                json={"jobArn": "arn:aws:bedrock:us-east-1:1234:model-invocation-job/fake"},
            )
        if path.endswith("/stop"):
            self._batch_stopped = True
            return httpx2.Response(200, json={})
        self._batch_polls += 1
        return httpx2.Response(200, json={"status": self._batch_status()})

    def _batch_status(self) -> str:
        if self._batch_stopped:
            return "Stopped"
        return (
            "Completed"
            if self._batch_polls >= self.batch_polls_before_done
            else "InProgress"
        )

    def _batch_manifest(self) -> str:
        """Answered records, in completion order — which is not submission order."""
        response = self.next_response()
        failures = min(self.batch_failures, len(self._batch_records))
        entries: list[dict[str, Any]] = []
        for index, record_id in enumerate(self._batch_records):
            if index < failures:
                entries.append(
                    {
                        "recordId": record_id,
                        "error": {
                            "errorCode": "ValidationException",
                            "errorMessage": "record rejected",
                        },
                    }
                )
                continue
            entries.append(
                {
                    "recordId": record_id,
                    "modelOutput": {
                        "output": {
                            "message": {
                                "role": "assistant",
                                "content": [{"text": f"{response.text} #{record_id}"}],
                            }
                        },
                        "stopReason": "end_turn",
                        "usage": {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18},
                    },
                }
            )
        return "\n".join(json.dumps(entry) for entry in reversed(entries))

    def _consume(self, request: httpx2.Request) -> tuple[dict[str, Any], FakeResponse]:
        body = json.loads(request.content or b"{}")
        self.requests.append(body)
        response = self.next_response()
        self._call_index += 1
        return body, response

    @staticmethod
    def _error(response: FakeResponse) -> httpx2.Response:
        return httpx2.Response(
            response.status,
            json={"message": response.error_message, "__type": "FakeException"},
            headers=dict(response.headers),
        )

    @staticmethod
    def _forced_tool_name(body: Mapping[str, Any]) -> str | None:
        """The schema's tool name, when this request emulates a schema."""
        config = body.get("toolConfig")
        choice = config.get("toolChoice") if isinstance(config, Mapping) else None
        tool = choice.get("tool") if isinstance(choice, Mapping) else None
        if isinstance(tool, Mapping):
            name = tool.get("name")
            if isinstance(name, str):
                return name
        return None

    def _content_blocks(
        self, response: FakeResponse, body: Mapping[str, Any]
    ) -> tuple[list[dict[str, Any]], str]:
        """The Converse content blocks for one response, plus its stop reason."""
        forced = self._forced_tool_name(body)
        if forced is not None:
            return (
                [
                    {
                        "toolUse": {
                            "toolUseId": "tooluse_schema",
                            "name": forced,
                            "input": json.loads(response.text or "{}"),
                        }
                    }
                ],
                "tool_use",
            )

        blocks: list[dict[str, Any]] = []
        if response.reasoning:
            blocks.append({"reasoningContent": {"reasoningText": {"text": response.reasoning}}})
        if response.text:
            blocks.append({"text": response.text})
        stop = response.finish_reason
        for call_id, name, args in response.tool_calls:
            blocks.append(
                {"toolUse": {"toolUseId": call_id, "name": name, "input": json.loads(args)}}
            )
            stop = "tool_use"
        return blocks, stop

    def _buffered(self, request: httpx2.Request) -> httpx2.Response:
        body, response = self._consume(request)
        if response.status >= 400:
            return self._error(response)
        blocks, stop = self._content_blocks(response, body)
        payload: dict[str, Any] = {
            "output": {"message": {"role": "assistant", "content": blocks}},
            "stopReason": stop,
        }
        if response.usage is not None:
            payload["usage"] = {
                "inputTokens": response.usage.get("prompt_tokens", 11),
                "outputTokens": response.usage.get("completion_tokens", 7),
                "totalTokens": response.usage.get("total_tokens", 18),
            }
        return httpx2.Response(200, json=payload, headers=dict(response.headers))

    def _streaming(self, request: httpx2.Request) -> httpx2.Response:
        body, response = self._consume(request)
        if response.status >= 400:
            return self._error(response)

        frames: list[bytes] = [eventstream_frame("messageStart", {"role": "assistant"})]
        forced = self._forced_tool_name(body)
        stop = response.finish_reason

        if forced is not None:
            frames.extend(self._tool_frames(0, "tooluse_schema", forced, response.text))
            stop = "tool_use"
        else:
            for fragment in chunk_text(response.reasoning, self._chunk_size):
                if fragment:
                    frames.append(
                        eventstream_frame(
                            "contentBlockDelta",
                            {
                                "contentBlockIndex": 0,
                                "delta": {"reasoningContent": {"text": fragment}},
                            },
                        )
                    )
            for fragment in chunk_text(response.text, self._chunk_size):
                if fragment:
                    frames.append(
                        eventstream_frame(
                            "contentBlockDelta",
                            {"contentBlockIndex": 0, "delta": {"text": fragment}},
                        )
                    )
            for offset, (call_id, name, args) in enumerate(response.tool_calls):
                frames.extend(self._tool_frames(offset + 1, call_id, name, args))
                stop = "tool_use"

        frames.append(eventstream_frame("messageStop", {"stopReason": stop}))
        if response.usage is not None:
            # Usage lives here and nowhere else.
            frames.append(
                eventstream_frame(
                    "metadata",
                    {
                        "usage": {
                            "inputTokens": response.usage.get("prompt_tokens", 11),
                            "outputTokens": response.usage.get("completion_tokens", 7),
                            "totalTokens": response.usage.get("total_tokens", 18),
                        }
                    },
                )
            )
        return httpx2.Response(
            200,
            content=b"".join(frames),
            headers={
                "content-type": "application/vnd.amazon.eventstream",
                **dict(response.headers),
            },
        )

    def _tool_frames(self, index: int, call_id: str, name: str, arguments: str) -> list[bytes]:
        """One tool call, opened then filled with ``toolUse.input`` fragments."""
        frames = [
            eventstream_frame(
                "contentBlockStart",
                {
                    "contentBlockIndex": index,
                    "start": {"toolUse": {"toolUseId": call_id, "name": name}},
                },
            )
        ]
        frames.extend(
            eventstream_frame(
                "contentBlockDelta",
                {"contentBlockIndex": index, "delta": {"toolUse": {"input": fragment}}},
            )
            for fragment in chunk_text(arguments, self._chunk_size)
            if fragment
        )
        return frames

    def _embed(self, request: httpx2.Request) -> httpx2.Response:
        body, response = self._consume(request)
        if response.status >= 400:
            return self._error(response)
        # Titan takes one input per call; the core's batching is what fans them out.
        text = str(body.get("inputText", ""))
        return httpx2.Response(
            200,
            json={"embedding": self._vector(text), "inputTextTokenCount": 3},
            headers=dict(response.headers),
        )

    def _rerank(self, request: httpx2.Request) -> httpx2.Response:
        body, response = self._consume(request)
        if response.status >= 400:
            return self._error(response)
        sources = body.get("sources", [])
        top_n = body.get("rerankingConfiguration", {}).get(
            "bedrockRerankingConfiguration", {}
        ).get("numberOfResults")
        # `document` echoes the input. The adapter documents that it never reads the
        # field, so including it proves exactly that: an adapter that started depending
        # on it would be depending on something the contract says is optional.
        ranked = [
            {
                "index": index,
                "relevanceScore": round(1.0 - index * 0.1, 4),
                "document": dict(source) if isinstance(source, Mapping) else {},
            }
            for index, source in enumerate(sources)
        ]
        if isinstance(top_n, int):
            ranked = ranked[:top_n]
        return httpx2.Response(200, json={"results": ranked}, headers=dict(response.headers))

    def _vector(self, text: str) -> list[float]:
        """A deterministic, unnormalized vector for ``text``."""
        seed = sum(ord(c) for c in text) or 1
        return [round(((seed * (i + 1)) % 97) / 97 + 0.05, 6) for i in range(self._dimensions)]


class FakeAnthropicServer(_FakeServerBase):
    """A configurable in-process Messages API endpoint.

    Two properties of the real API shape this fake. It **always streams** — the adapter
    sends ``stream: true`` unconditionally, so there is no buffered branch to model — and
    it has **no response-format field**, so a schema is emulated as a single forced tool
    call and the structured answer arrives as a ``tool_use`` block rather than as text.

    That second point is why this fake reads the request before answering. A scenario says
    "return this JSON"; whether that JSON belongs in a ``text_delta`` or in the ``input`` of
    a ``tool_use`` block is a property of what was asked, not of the scenario. The tool name
    is echoed from the request's own ``tool_choice`` rather than hardcoded, so the fake
    cannot drift from whatever the core decides to call the schema.

    Args:
        responses: Responses to serve, one per request, in order. The last is reused once
            exhausted, so a single-element list serves every request.
        models: Model ids reported by ``GET /v1/models``.
        chunk_size: Characters per streamed text delta.
        batch_polls_before_done: How many status polls a submitted batch reports
            ``in_progress`` for before it ends. At least one, so a caller must always poll
            at least once — a fake that ended immediately could never exercise the
            poll-then-fetch shape that is the whole point of a deferred API.
        batch_failures: How many of a batch's lines come back as per-line errors. A batch
            is not all-or-nothing, and a result type that could not carry a partial failure
            would force the whole job to be discarded over one bad request.
        page_size: Model ids per listing page. The listing is cursor-paginated, and an
            adapter that ignores ``has_more`` silently reports only the first page --
            which looks like a working discovery call.

    Attributes:
        requests: Every request body received, for assertions.
    """

    def __init__(
        self,
        responses: Sequence[FakeResponse] | FakeResponse | None = None,
        *,
        models: Sequence[str] = ("claude-sonnet-4-5", "claude-opus-4-1"),
        chunk_size: int = 4,
        page_size: int = 1,
        batch_polls_before_done: int = 1,
        batch_failures: int = 0,
    ) -> None:
        super().__init__(responses)
        self._models = list(models)
        self._chunk_size = chunk_size
        self._page_size = max(1, page_size)
        self.batch_polls_before_done = max(1, batch_polls_before_done)
        self.batch_failures = batch_failures
        self._batch_lines: list[str] = []
        self._batch_polls = 0
        self._batch_cancelled = False

    def next_response(self) -> FakeResponse:
        """The response for the next generation call."""
        index = min(self._call_index, len(self._responses) - 1)
        return self._responses[index]

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/v1/models"):
            return self._handle_models(request)
        if path.endswith("/v1/messages"):
            return self._handle_messages(request)
        if "/v1/messages/batches" in path or path.endswith("/batch-results"):
            return self._handle_batch(request)
        return httpx2.Response(
            404, json={"type": "error", "error": {"type": "not_found", "message": path}}
        )

    # ---- batches ---------------------------------------------------------------------
    #
    # A whole deferred job in one in-process fake: submit, poll, cancel, and download. The
    # state machine is deliberately real — a batch reports `in_progress` until it is polled
    # `batch_polls_before_done` times — because the property worth testing is that a caller
    # polls to a terminal status and only then fetches, which a fake that answered
    # `ended` immediately could never exercise.

    def _handle_batch(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/batch-results"):
            return httpx2.Response(200, text=self._batch_manifest())
        if request.method == "POST" and path.endswith("/v1/messages/batches"):
            body = json.loads(request.content or b"{}")
            self.requests.append(body)
            self._batch_lines = [str(entry.get("custom_id", "")) for entry in body["requests"]]
            self._batch_polls = 0
            self._batch_cancelled = False
            return httpx2.Response(200, json=self._batch_object())
        if path.endswith("/cancel"):
            self._batch_cancelled = True
            return httpx2.Response(200, json=self._batch_object())
        self._batch_polls += 1
        return httpx2.Response(200, json=self._batch_object())

    def _batch_object(self) -> dict[str, Any]:
        """The batch as the API reports it right now."""
        done = self._batch_cancelled or self._batch_polls >= self.batch_polls_before_done
        failures = min(self.batch_failures, len(self._batch_lines))
        body: dict[str, Any] = {
            "id": "msgbatch_fake",
            "type": "message_batch",
            "processing_status": "ended" if done else "in_progress",
            "request_counts": {
                "succeeded": len(self._batch_lines) - failures if done else 0,
                "errored": failures if done else 0,
                "expired": 0,
                "processing": 0 if done else len(self._batch_lines),
            },
        }
        if self._batch_cancelled:
            body["cancel_initiated_at"] = "2026-08-25T00:00:00Z"
        if done:
            body["results_url"] = "https://fake.invalid/batch-results"
        return body

    def _batch_manifest(self) -> str:
        """The JSONL manifest, in *completion* order — which is not submission order.

        Reversed on purpose. Providers return whatever finished first, and a caller zipping
        results against their own inputs must not have to sort; that ordering is the core's
        job and this is what proves it does it.
        """
        response = self.next_response()
        failures = min(self.batch_failures, len(self._batch_lines))
        entries: list[dict[str, Any]] = []
        for position, custom_id in enumerate(self._batch_lines):
            if position < failures:
                entries.append(
                    {
                        "custom_id": custom_id,
                        "result": {
                            "type": "errored",
                            "error": {"type": "invalid_request", "message": "line rejected"},
                        },
                    }
                )
                continue
            entries.append(
                {
                    "custom_id": custom_id,
                    "result": {
                        "type": "succeeded",
                        "message": {
                            "id": f"msg_{custom_id}",
                            "type": "message",
                            "role": "assistant",
                            "model": "fake-claude",
                            "content": [{"type": "text", "text": f"{response.text} #{custom_id}"}],
                            "stop_reason": "end_turn",
                            "usage": {"input_tokens": 11, "output_tokens": 7},
                        },
                    },
                }
            )
        return "\n".join(json.dumps(entry) for entry in reversed(entries))

    def _handle_models(self, request: httpx2.Request) -> httpx2.Response:
        after = request.url.params.get("after_id")
        start = 0
        if after is not None:
            start = self._models.index(after) + 1 if after in self._models else len(self._models)
        page = self._models[start : start + self._page_size]
        has_more = start + self._page_size < len(self._models)
        return httpx2.Response(
            200,
            json={
                "data": [{"id": model, "type": "model"} for model in page],
                "has_more": has_more,
                "last_id": page[-1] if page else None,
            },
        )

    def _handle_messages(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append(body)
        response = self.next_response()
        self._call_index += 1

        if response.status >= 400:
            return httpx2.Response(
                response.status,
                json={
                    "type": "error",
                    "error": {"type": "fake_error", "message": response.error_message},
                },
                headers=dict(response.headers),
            )
        return httpx2.Response(
            200,
            content=self._stream_body(response, body),
            headers={"content-type": "text/event-stream", **dict(response.headers)},
        )

    @staticmethod
    def _forced_tool_name(body: Mapping[str, Any]) -> str | None:
        """The schema's tool name, when this request emulates a schema."""
        choice = body.get("tool_choice")
        if isinstance(choice, Mapping) and choice.get("type") == "tool":
            name = choice.get("name")
            if isinstance(name, str):
                return name
        return None

    def _stream_body(self, response: FakeResponse, body: Mapping[str, Any]) -> bytes:
        if response.malformed_sse:
            return b"data: {not json at all\n\n"

        events: list[dict[str, Any]] = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 12}}}
        ]
        forced = self._forced_tool_name(body)
        stop_reason = response.finish_reason

        if forced is not None:
            # A schema request: the answer is the tool call's input, not text.
            events.extend(self._tool_use_events(0, "toolu_schema", forced, response.text))
            stop_reason = "tool_use"
        else:
            events.append(
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}
            )
            for fragment in chunk_text(response.reasoning, self._chunk_size):
                if fragment:
                    events.append(
                        {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "thinking_delta", "thinking": fragment},
                        }
                    )
            for fragment in chunk_text(response.text, self._chunk_size):
                if fragment:
                    events.append(
                        {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": fragment},
                        }
                    )
            events.append({"type": "content_block_stop", "index": 0})

            for offset, (call_id, name, args) in enumerate(response.tool_calls):
                events.extend(self._tool_use_events(offset + 1, call_id, name, args))
                stop_reason = "tool_use"

        if response.usage is not None:
            events.append(
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason},
                    "usage": {"output_tokens": response.usage.get("completion_tokens", 7)},
                }
            )
        else:
            events.append({"type": "message_delta", "delta": {"stop_reason": stop_reason}})
        events.append({"type": "message_stop"})
        return sse_lines(events, done=False)

    def _tool_use_events(
        self, index: int, call_id: str, name: str, arguments: str
    ) -> list[dict[str, Any]]:
        """One tool call, opened then filled with ``input_json_delta`` fragments."""
        events: list[dict[str, Any]] = [
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "tool_use", "id": call_id, "name": name},
            }
        ]
        events.extend(
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "input_json_delta", "partial_json": fragment},
            }
            for fragment in chunk_text(arguments, self._chunk_size)
            if fragment
        )
        events.append({"type": "content_block_stop", "index": index})
        return events


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
        batch_polls_before_done: int = 1,
        batch_failures: int = 0,
    ) -> None:
        super().__init__(responses)
        self._models = list(models)
        self._chunk_size = chunk_size
        self.objects: dict[str, bytes] = {}
        self.batch_polls_before_done = max(1, batch_polls_before_done)
        self.batch_failures = batch_failures
        self._batch_polls = 0
        self._batch_cancelled = False
        self._batch_lines: list[dict[str, Any]] = []

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if request.url.host == "storage.googleapis.com":
            return self._handle_gcs(request)
        if "batchPredictionJobs" in path:
            return self._handle_batch(request)
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
        if ":predict" in path:
            # Vertex embedding models document `:predict`, not Gemini's
            # `batchEmbedContents`, and the response nests under `embeddings.values`.
            return self._handle_predict(request)
        return httpx2.Response(
            404, json={"error": {"code": 404, "message": f"no such path: {path}"}}
        )

    # ---- deferred batches, and the bucket they are staged in ---------------------------

    def _handle_gcs(self, request: httpx2.Request) -> httpx2.Response:
        """Stand in for the caller's own GCS bucket.

        Vertex's batch tier never carries the job over the API: the input is an object
        the client writes and the predictions are an object it reads. Modeling the
        staging step rather than pretending the API takes the lines is the point.
        """
        if request.method == "POST":
            name = request.url.params.get("name", "")
            self.objects[name] = request.content
            self._batch_lines = [
                json.loads(line)
                for line in request.content.decode("utf-8").splitlines()
                if line.strip()
            ]
            return httpx2.Response(200, json={"name": name})
        key = unquote(request.url.path.rsplit("/o/", 1)[-1])
        if key.endswith("predictions.jsonl"):
            return httpx2.Response(200, text=self._predictions())
        if key in self.objects:
            return httpx2.Response(200, content=self.objects[key])
        return httpx2.Response(404, json={"error": {"message": f"no such object: {key}"}})

    def _handle_batch(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith(":cancel"):
            self._batch_cancelled = True
            return httpx2.Response(200, json={})
        if request.method == "POST":
            self.requests.append(json.loads(request.content or b"{}"))
            self._batch_polls = 0
            self._batch_cancelled = False
            return httpx2.Response(
                200,
                json={
                    "name": "projects/p/locations/us-central1/batchPredictionJobs/9",
                    "state": "JOB_STATE_PENDING",
                },
            )
        self._batch_polls += 1
        return httpx2.Response(200, json=self._job_object())

    def _job_object(self) -> dict[str, Any]:
        if self._batch_cancelled:
            return {"state": "JOB_STATE_CANCELLED"}
        if self._batch_polls < self.batch_polls_before_done:
            return {"state": "JOB_STATE_RUNNING"}
        failures = min(self.batch_failures, len(self._batch_lines))
        return {
            "state": "JOB_STATE_SUCCEEDED",
            "completionStats": {
                "successfulCount": len(self._batch_lines) - failures,
                "failedCount": failures,
            },
            # A timestamped directory of the API's own naming, under the requested
            # prefix — the reason the output path cannot simply be predicted.
            "outputInfo": {
                "gcsOutputDirectory": f"{self._batch_prefix()}/prediction-2026-08-25T00:00:00Z"
            },
        }

    def _batch_prefix(self) -> str:
        submitted = self.requests[-1] if self.requests else {}
        output = submitted.get("outputConfig", {}) if isinstance(submitted, dict) else {}
        destination = output.get("gcsDestination", {}) if isinstance(output, dict) else {}
        return str(destination.get("outputUriPrefix", "gs://fake/out"))

    def _predictions(self) -> str:
        """Answered predictions, in an order the API does not promise."""
        response = self._responses[min(self._call_index, len(self._responses) - 1)]
        failures = min(self.batch_failures, len(self._batch_lines))
        entries: list[dict[str, Any]] = []
        for index, line in enumerate(self._batch_lines):
            request_body = line.get("request", {})
            line_id = request_body.get("labels", {}).get("anyinfer_line_id", "")
            if index < failures:
                entries.append({"request": request_body, "status": "line rejected"})
                continue
            entries.append(
                {
                    "request": request_body,
                    "response": {
                        "candidates": [
                            {
                                "content": {
                                    "role": "model",
                                    "parts": [{"text": f"{response.text} #{line_id}"}],
                                },
                                "finishReason": "STOP",
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 11,
                            "candidatesTokenCount": 7,
                            "totalTokenCount": 18,
                        },
                    },
                }
            )
        return "\n".join(json.dumps(entry) for entry in reversed(entries))

    def _handle_predict(self, request: httpx2.Request) -> httpx2.Response:
        """Serve ``:predict``, sharing the scenario script with generation.

        One prediction per instance, in the order they were sent: `:predict` carries no
        index, so position *is* the identity and an adapter that reorders has no way to
        recover. Vectors are derived from the input text, so duplicate inputs produce
        identical vectors and the positional-preservation case stays meaningful.
        """
        body = json.loads(request.content or b"{}")
        self.requests.append(body)
        index = min(self._call_index, len(self._responses) - 1)
        response = self._responses[index]
        self._call_index += 1

        if response.status >= 400:
            return httpx2.Response(
                response.status,
                json={"error": {"code": response.status, "message": response.error_message}},
                headers=dict(response.headers),
            )

        instances = body.get("instances", [])
        return httpx2.Response(
            200,
            json={
                "predictions": [
                    {
                        "embeddings": {
                            "values": self._vector(str(instance.get("content", ""))),
                            "statistics": {"token_count": 3},
                        }
                    }
                    for instance in instances
                ]
            },
            headers=dict(response.headers),
        )

    def _vector(self, text: str) -> list[float]:
        """A deterministic, unnormalized vector for ``text``."""
        seed = sum(ord(c) for c in text) or 1
        return [round(((seed * (i + 1)) % 97) / 97 + 0.05, 6) for i in range(8)]

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
