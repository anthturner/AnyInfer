"""The OpenAI-compatible ASGI application.

A thin HTTP shell around `anyinfer.serve.openai_codec` and a normal
`AsyncClient`. It contains **no** routing, retry, validation, credential,
or provider logic — all of that is the core's, reached through the same public API any SDK
caller uses. If a feature seems to belong here, it belongs in the core instead.

Security posture:

- binds loopback by default; a non-loopback bind requires ``allow_remote_exposure=True``
  *and* a bearer token, because an unauthenticated LLM gateway on a LAN is a credential
  laundering service;
- backend credentials never transit — the frontend authenticates *clients to itself*;
- no configuration-execution endpoints of any kind, which is a deliberate response to how
  comparable gateways have been compromised.
"""

from __future__ import annotations

import json
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from ..errors import AnyInferError, SchemaViolationError
from ..types.events import StreamEnded
from ..types.operations import RerankDocument
from .embeddings_codec import (
    embedding_request_from_openai,
    embeddings_response,
    rerank_request_from_body,
    rerank_response,
)
from .openai_codec import (
    chunk_from_event,
    completion_from_generation,
    final_chunk,
    manifest_chunk,
    request_from_openai,
    wants_manifest,
)

__all__ = ["create_app"]

_SSE_HEADERS = {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    "connection": "keep-alive",
    # Without this, reverse proxies buffer the whole response and streaming stops being
    # streaming — a failure that only shows up behind a proxy, never in local testing.
    "x-accel-buffering": "no",
}


def create_app(
    client: Any,
    *,
    auth_token: str | None = None,
    expose_targets: Sequence[str] = (),
) -> Any:
    """Build the ASGI application.

    Args:
        client: An `AsyncClient` to federate through.
        auth_token: Bearer token clients must present. ``None`` disables authentication,
            which is only appropriate on loopback.
        expose_targets: Concrete ``provider:model`` targets to advertise from
            ``/v1/models``, in addition to catalog aliases.

    Returns:
        A Starlette application.

    Raises:
        ConfigError: If the ``[serve]`` extra is not installed.
    """
    starlette = _import_starlette()

    async def chat_completions(request: Any) -> Any:
        """Serve ``POST /v1/chat/completions``."""
        guard = _check_auth(request, auth_token, starlette)
        if guard is not None:
            return guard

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — any malformed body is one error to the client
            return _error(starlette, 400, "request body must be valid JSON")
        if not isinstance(body, Mapping):
            return _error(starlette, 400, "request body must be a JSON object")

        try:
            target, generation_request, wants_stream = request_from_openai(body)
            include_manifest = wants_manifest(body)
        except ValueError as exc:
            # A malformed AnyInfer extension field is the client's mistake, and telling it
            # so beats silently applying the gateway's default instead of what it asked for.
            return _error(starlette, 400, str(exc))
        if not target:
            return _error(starlette, 400, "the 'model' field is required")

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())

        if wants_stream:
            return starlette.StreamingResponse(
                _stream_chunks(
                    client,
                    target,
                    generation_request,
                    body,
                    completion_id=completion_id,
                    created=created,
                    model=target,
                ),
                headers=_SSE_HEADERS,
            )

        try:
            result = await _generate(client, target, generation_request)
        except AnyInferError as exc:
            return _error(starlette, _status_for(exc), str(exc), type(exc).__name__)

        return starlette.JSONResponse(
            completion_from_generation(
                result,
                model=target,
                completion_id=completion_id,
                created=created,
                include_manifest=include_manifest,
            )
        )

    async def models(request: Any) -> Any:
        """Serve ``GET /v1/models``: catalog aliases plus any configured targets."""
        guard = _check_auth(request, auth_token, starlette)
        if guard is not None:
            return guard

        created = int(time.time())
        seen: set[str] = set()
        entries: list[dict[str, Any]] = []

        def add(model_id: str) -> None:
            """Advertise one id once, keeping catalog aliases ahead of concrete targets."""
            if model_id and model_id not in seen:
                seen.add(model_id)
                entry: dict[str, Any] = {
                    "id": model_id,
                    "object": "model",
                    "created": created,
                    "owned_by": "anyinfer",
                }
                # Additive extension: which operations the target is known to serve,
                # so a client can tell an embedding model from a chat model. OpenAI
                # clients ignore unknown keys; an unresolvable id is simply untagged.
                try:
                    operations = client.operations_for(model_id)
                except Exception:  # noqa: BLE001 — advisory metadata, never a 500
                    operations = frozenset()
                if operations:
                    entry["anyinfer"] = {"operations": sorted(operations)}
                entries.append(entry)

        catalog = getattr(client, "catalog", None)
        if catalog is not None:
            for alias in catalog.alias_names():
                add(alias)
        # `--expose` targets are already written in instance terms ("work-azure:gpt-4o"),
        # which is what makes an engine configured twice separately addressable here.
        for target in expose_targets:
            add(target)
        return starlette.JSONResponse({"object": "list", "data": entries})

    async def compare_targets(request: Any) -> Any:
        """Serve ``POST /v1/anyinfer/compare`` as a client-API projection."""
        guard = _check_auth(request, auth_token, starlette)
        if guard is not None:
            return guard
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _error(starlette, 400, "request body must be valid JSON")
        if not isinstance(body, Mapping):
            return _error(starlette, 400, "request body must be a JSON object")
        raw_targets = body.get("targets")
        if (
            not isinstance(raw_targets, list)
            or not raw_targets
            or not all(isinstance(item, str) and item.strip() for item in raw_targets)
        ):
            return _error(starlette, 400, "'targets' must be a non-empty array of strings")
        targets = tuple(str(item) for item in raw_targets)
        shaped = dict(body)
        shaped.pop("targets", None)
        shaped.setdefault("model", targets[0])
        try:
            _, generation_request, _ = request_from_openai(shaped)
            comparisons = await client.compare(generation_request, targets=targets)
        except (AnyInferError, ValueError) as exc:
            return _error(starlette, 400, str(exc), type(exc).__name__)
        return starlette.JSONResponse(
            {
                "object": "anyinfer.target_comparison.list",
                "data": [item.to_dict() for item in comparisons],
            }
        )

    async def embeddings(request: Any) -> Any:
        """Serve ``POST /v1/embeddings`` as an OpenAI-compatible codec over `AsyncClient.embed`."""
        guard = _check_auth(request, auth_token, starlette)
        if guard is not None:
            return guard
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — any malformed body is one error to the client
            return _error(starlette, 400, "request body must be valid JSON")
        if not isinstance(body, Mapping):
            return _error(starlette, 400, "request body must be a JSON object")

        try:
            target, inputs, kwargs = embedding_request_from_openai(body)
            include_manifest = wants_manifest(body)
        except ValueError as exc:
            return _error(starlette, 400, str(exc))

        try:
            result = await client.embed(inputs, target=target, **kwargs)
        except AnyInferError as exc:
            return _error(starlette, _status_for(exc), str(exc), type(exc).__name__)
        return starlette.JSONResponse(
            embeddings_response(result, model=target, include_manifest=include_manifest)
        )

    async def rerank(request: Any) -> Any:
        """Serve ``POST /v1/anyinfer/rerank`` as a codec over `AsyncClient.rerank`."""
        guard = _check_auth(request, auth_token, starlette)
        if guard is not None:
            return guard
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _error(starlette, 400, "request body must be valid JSON")
        if not isinstance(body, Mapping):
            return _error(starlette, 400, "request body must be a JSON object")

        try:
            target, query, documents, kwargs = rerank_request_from_body(body)
            include_manifest = wants_manifest(body)
        except ValueError as exc:
            return _error(starlette, 400, str(exc))

        rerank_documents = [RerankDocument(id=doc_id, text=text) for doc_id, text in documents]
        try:
            result = await client.rerank(query, rerank_documents, target=target, **kwargs)
        except AnyInferError as exc:
            return _error(starlette, _status_for(exc), str(exc), type(exc).__name__)
        return starlette.JSONResponse(
            rerank_response(result, model=target, include_manifest=include_manifest)
        )

    async def health(request: Any) -> Any:
        """Serve ``GET /health``: liveness only, requiring no authentication."""
        return starlette.JSONResponse({"status": "ok"})

    async def unsupported(request: Any) -> Any:
        """Answer endpoints AnyInfer does not model with a clear 404."""
        return _error(
            starlette,
            404,
            (
                f"{request.url.path} is not supported: AnyInfer models text generation, "
                "embeddings, and reranking only"
            ),
            "not_found",
        )

    routes = [
        starlette.Route("/health", health, methods=["GET"]),
        starlette.Route("/v1/chat/completions", chat_completions, methods=["POST"]),
        starlette.Route("/v1/embeddings", embeddings, methods=["POST"]),
        starlette.Route("/v1/anyinfer/rerank", rerank, methods=["POST"]),
        starlette.Route("/v1/models", models, methods=["GET"]),
        starlette.Route("/v1/anyinfer/compare", compare_targets, methods=["POST"]),
        starlette.Route("/v1/{rest:path}", unsupported, methods=["GET", "POST"]),
    ]
    return starlette.Starlette(routes=routes)


async def _generate(client: Any, target: str, request: Any) -> Any:
    """Run a non-streaming generation through the client's public API."""
    return await client.generate(
        request.messages,
        target=target,
        schema=request.schema,
        tools=request.tools,
        tool_choice=request.tool_choice,
        sampling=request.sampling,
        history=request.history,
        cache=request.cache,
        arena=request.arena,
        context=request.context,
        provider_options=request.provider_options,
        metadata=request.metadata,
    )


async def _stream_chunks(
    client: Any,
    target: str,
    request: Any,
    body: Mapping[str, Any],
    *,
    completion_id: str,
    created: int,
    model: str,
) -> AsyncIterator[bytes]:
    """Project the event stream onto ``chat.completion.chunk`` SSE records.

    Errors that arrive after streaming has begun are emitted as a terminal SSE error
    record: the status line is long gone, so there is no other way to tell the client.
    """
    stream = client.stream(
        request.messages,
        target=target,
        schema=request.schema,
        tools=request.tools,
        tool_choice=request.tool_choice,
        sampling=request.sampling,
        history=request.history,
        cache=request.cache,
        arena=request.arena,
        context=request.context,
        provider_options=request.provider_options,
        metadata=request.metadata,
    )
    include_usage = _wants_usage(body)
    include_manifest = _wants_manifest_quietly(body)

    try:
        try:
            async for event in stream:
                chunk = chunk_from_event(
                    event, model=model, completion_id=completion_id, created=created
                )
                if chunk is not None:
                    yield _sse(chunk)
                if isinstance(event, StreamEnded):
                    for terminal in final_chunk(
                        event.result,
                        model=model,
                        completion_id=completion_id,
                        created=created,
                        include_usage=include_usage,
                    ):
                        yield _sse(terminal)
                    if include_manifest:
                        frame = manifest_chunk(
                            event.result,
                            model=model,
                            completion_id=completion_id,
                            created=created,
                        )
                        if frame is not None:
                            yield _sse(frame)
        except AnyInferError as exc:
            yield _sse(
                {
                    "error": {
                        "message": str(exc),
                        "type": type(exc).__name__,
                        "code": getattr(exc, "http_status", None),
                    }
                }
            )
    finally:
        # ASGI closes this generator (raising GeneratorExit here) the moment a client
        # disconnects mid-stream, without waiting for the loop above to finish on its
        # own. Without this, the underlying provider request — and, on a route with a
        # fallback chain, any AsyncStream still holding a live connection — would only
        # ever be released by garbage collection, not deterministically at disconnect
        # time. `aclose()` is idempotent, so this costs nothing on the normal
        # ran-to-completion path.
        await stream.aclose()
    yield b"data: [DONE]\n\n"


def _wants_manifest_quietly(body: Mapping[str, Any]) -> bool:
    """Whether the stream should end with a manifest frame.

    A malformed value was already rejected with a 400 before the response started; by the
    time the generator runs there is no status line left to change, so it re-reads the
    field rather than raising into a half-sent stream.
    """
    try:
        return wants_manifest(body)
    except ValueError:
        return False


def _wants_usage(body: Mapping[str, Any]) -> bool:
    """Whether the client asked for the trailing usage chunk."""
    options = body.get("stream_options")
    if isinstance(options, Mapping):
        return bool(options.get("include_usage", True))
    return True


def _sse(payload: Mapping[str, Any]) -> bytes:
    """Encode one SSE data record."""
    return f"data: {json.dumps(payload)}\n\n".encode()


def _check_auth(request: Any, auth_token: str | None, starlette: Any) -> Any:
    """Verify the bearer token, if one is configured."""
    if auth_token is None:
        return None
    header = request.headers.get("authorization", "")
    presented = header[7:] if header.lower().startswith("bearer ") else ""
    if not secrets.compare_digest(presented, auth_token):
        return _error(starlette, 401, "invalid or missing bearer token", "invalid_api_key")
    return None


def _status_for(exc: AnyInferError) -> int:
    """Map an AnyInfer error onto an HTTP status for the client."""
    if isinstance(exc, SchemaViolationError):
        return 422
    status = getattr(exc, "http_status", None)
    if isinstance(status, int) and 400 <= status < 600:
        return status
    return 502


def _error(starlette: Any, status: int, message: str, kind: str = "invalid_request_error") -> Any:
    """Build an OpenAI-shaped error response."""
    return starlette.JSONResponse(
        {"error": {"message": message, "type": kind, "code": None}}, status_code=status
    )


def _import_starlette() -> Any:
    """Import the optional ASGI dependencies, or explain how to install them."""
    try:
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse, StreamingResponse
        from starlette.routing import Route
    except ImportError as exc:
        from ..errors import ConfigError

        raise ConfigError(
            "the serve frontend requires the serve extra",
            hint="pip install 'anyinfer[serve]'",
        ) from exc

    from types import SimpleNamespace

    return SimpleNamespace(
        Starlette=Starlette,
        JSONResponse=JSONResponse,
        StreamingResponse=StreamingResponse,
        Route=Route,
    )
