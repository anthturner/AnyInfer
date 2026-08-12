"""A minimal ASGI wrapper around `Relay` — requires the `relay` extra (starlette, uvicorn).

Not imported by `anyinfer_confidential/__init__.py`, so installing the base package never
pulls in an ASGI framework — the same "no daemon unless you asked for one" posture
`anyinfer[serve]` already takes for the sidecar.

Zero-retention is enforced structurally here too: this module never configures request
logging middleware, never writes to a file, and the only thing returned to the caller is
`RelayResult`'s fields — nothing is cached in the app or module state between requests.
"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route as StarletteRoute

from .relay import Relay, RelayError

__all__ = ["build_app"]


def build_app(relay: Relay) -> Starlette:
    """Build a Starlette app exposing `relay` at ``POST /v1/relay/assemble``.

    A vendor's own script constructs the bound `Relay` (its `TemplateVault` and
    `RelayRegistry` are deployment-specific) and serves the result with any standard ASGI
    server, e.g. ``uvicorn.run(build_app(my_relay), ...)`` — there is no bundled
    zero-configuration entry point, since the route registry always needs real
    provisioning first.
    """

    async def handle(request: Request) -> JSONResponse:
        try:
            body: dict[str, Any] = await request.json()
            tenant_id = str(body["tenant_id"])
            routing_key = str(body["routing_key"])
            slots = dict(body.get("slots", {}))
            mode = body.get("mode", "assemble")
        except (KeyError, ValueError, TypeError) as exc:
            return JSONResponse({"error": f"malformed request: {exc}"}, status_code=400)

        try:
            result = await relay.handle(
                tenant_id=tenant_id, routing_key=routing_key, slots=slots, mode=mode
            )
        except RelayError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

        return JSONResponse(
            {
                "assembled_prompt": result.assembled_prompt,
                "generation_text": result.generation_text,
                "target": result.target,
                "latency_ms": result.latency_ms,
            }
        )

    return Starlette(routes=[StarletteRoute("/v1/relay/assemble", handle, methods=["POST"])])
