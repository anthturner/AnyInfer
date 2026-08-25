"""A minimal ASGI wrapper around `Relay` — requires the `relay` extra (starlette, uvicorn).

Not imported by `anyinfer_confidential/__init__.py`, so installing the base package never
pulls in an ASGI framework — the same "no daemon unless you asked for one" posture
`anyinfer[serve]` already takes for the sidecar.

Zero-retention is enforced structurally here too: this module never configures request
logging middleware, never writes to a file, and the only thing returned to the caller is
`RelayResult`'s fields — nothing is cached in the app or module state between requests.

**Authentication is mandatory.** The response body carries the decrypted, assembled
prompt: the exact IP Tier 2 exists to protect. `RelayRegistry`'s per-tenant scoping is
only an isolation boundary if the tenant identity is *authenticated* — a caller that
declares its own `tenant_id` reduces isolation to "does not know the other tenant's id",
which is not access control. `build_app` therefore takes a token-to-tenant mapping as a
required argument and derives the tenant from the presented bearer token, never from the
request body. There is no unauthenticated mode to fall into by omission.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route as StarletteRoute

from .relay import Relay, RelayError

__all__ = ["build_app"]

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": 'Bearer realm="anyinfer-relay"'}


def _authenticate(request: Request, tokens: Mapping[str, str]) -> str | None:
    """Return the tenant the presented bearer token belongs to, or None.

    Compared with `secrets.compare_digest` against every configured token rather than
    looked up in a dict: a dict lookup's timing varies with how much of the token
    matched, which leaks a prefix to a client that can measure it. The scan is over a
    handful of tenants, so the cost is irrelevant next to the property.
    """
    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        return None

    matched: str | None = None
    for token, tenant_id in tokens.items():
        if secrets.compare_digest(token, presented):
            matched = tenant_id
    return matched


def build_app(relay: Relay, *, tokens: Mapping[str, str]) -> Starlette:
    """Build a Starlette app exposing `relay` at ``POST /v1/relay/assemble``.

    A vendor's own script constructs the bound `Relay` (its `TemplateVault` and
    `RelayRegistry` are deployment-specific) and serves the result with any standard ASGI
    server, e.g. ``uvicorn.run(build_app(my_relay, tokens=my_tokens), ...)`` — there is no
    bundled zero-configuration entry point, since the route registry always needs real
    provisioning first.

    Args:
        relay: The bound `Relay` to serve.
        tokens: Maps bearer token to the `tenant_id` it authenticates. Required, and
            required non-empty: an empty mapping would serve decrypted prompt IP to
            anyone who can reach the port. Issue one long, random token per tenant
            (``secrets.token_urlsafe(32)``) and rotate by replacing the mapping and
            rebuilding the app. Terminate TLS in front of this app — a bearer token on a
            plaintext connection is readable by anything on the path.

    Raises:
        ValueError: `tokens` is empty.

    Note:
        ``mode="forward"`` is not reachable over HTTP. Forwarding needs short-lived
        provider credentials that this endpoint deliberately does not accept on the wire;
        a forward-mode request is answered with 400. Call `Relay.handle` in-process for
        that mode.
    """
    if not tokens:
        raise ValueError(
            "build_app requires at least one bearer token: the response body carries "
            "decrypted prompt IP, so an unauthenticated relay has no isolation boundary"
        )
    # Copied so a later mutation of the caller's mapping cannot silently widen access
    # for an app that is already serving.
    tokens = dict(tokens)

    async def handle(request: Request) -> JSONResponse:
        tenant_id = _authenticate(request, tokens)
        if tenant_id is None:
            return JSONResponse(
                {"error": "a valid bearer token is required"},
                status_code=401,
                headers=_UNAUTHORIZED_HEADERS,
            )

        try:
            body: dict[str, Any] = await request.json()
            routing_key = str(body["routing_key"])
            slots = dict(body.get("slots", {}))
            mode = body.get("mode", "assemble")
        except (KeyError, ValueError, TypeError) as exc:
            return JSONResponse({"error": f"malformed request: {exc}"}, status_code=400)

        # A body tenant_id is not authoritative and never was; disagreeing with the
        # authenticated principal is a client bug or an attempt, and both deserve a
        # loud answer rather than being quietly ignored.
        claimed = body.get("tenant_id")
        if claimed is not None and str(claimed) != tenant_id:
            return JSONResponse(
                {"error": "tenant_id does not match the authenticated token"},
                status_code=403,
            )

        if mode != "assemble":
            return JSONResponse(
                {
                    "error": (
                        f"mode {mode!r} is not available over HTTP: this endpoint "
                        "assembles only. Forwarding needs short-lived provider "
                        "credentials, which are not accepted on the wire."
                    )
                },
                status_code=400,
            )

        try:
            result = await relay.handle(
                tenant_id=tenant_id, routing_key=routing_key, slots=slots, mode="assemble"
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
