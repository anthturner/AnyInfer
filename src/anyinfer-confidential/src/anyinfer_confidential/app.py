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

import math
import secrets
import warnings
from collections.abc import Mapping
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route as StarletteRoute

from .admission import RelayThrottledError
from .relay import Relay, RelayBadRequestError, RelayError

__all__ = ["RELAY_RATE_LIMIT_HEADERS", "build_app"]

_RATE_LIMIT_LIMIT = "ratelimit-limit"
_RATE_LIMIT_REMAINING = "ratelimit-remaining"
_RATE_LIMIT_RESET = "ratelimit-reset"


def _relay_rate_limit_headers() -> Any:
    """The header dialect this app emits, as a core `RateLimitHeaders`.

    Built lazily so importing this module does not import core's capability types. The
    payoff for using the IETF draft names rather than bespoke ``X-Relay-*`` ones: an
    AnyInfer client pointed at a Relay paces itself against these with no new client code,
    by passing this constant as its provider dialect.

    A rename in a future revision of that draft is then a deliberate, versioned change to
    *both* halves at once — and the round-trip test between them is what makes a
    half-finished rename fail loudly instead of silently reading `None` forever.
    """
    from anyinfer.types.capabilities import RateLimitHeaders

    return RateLimitHeaders(
        requests_remaining=_RATE_LIMIT_REMAINING,
        requests_reset=_RATE_LIMIT_RESET,
        limit_requests=_RATE_LIMIT_LIMIT,
    )


RELAY_RATE_LIMIT_HEADERS = _relay_rate_limit_headers
"""Call to get the `RateLimitHeaders` describing what this app emits.

A callable rather than a value so `import anyinfer_confidential.app` stays free of a core
import at module scope, matching how the rest of this package defers its core imports.
"""

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": 'Bearer realm="anyinfer-relay"'}


def _authenticate(request: Request, tokens: Mapping[str, str]) -> str | None:
    """Return the tenant the presented bearer token belongs to, or None.

    Compared with `secrets.compare_digest` against every configured token rather than
    looked up in a dict: a dict lookup's timing varies with how much of the token
    matched, which leaks a prefix to a client that can measure it. The scan is over a
    handful of tenants, so the cost is irrelevant next to the property.

    Both sides are encoded to bytes before comparison. `compare_digest` raises
    `TypeError` on a str holding any character above U+007F, and Starlette decodes
    header values as latin-1 -- so a single byte >= 0x80 in the Authorization value
    would turn a clean 401 into an unhandled 500 that any unauthenticated client could
    mint. Encoding is a bijection on str, so equality is preserved exactly.
    """
    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        return None

    presented_bytes = presented.encode("utf-8", "surrogateescape")
    matched: str | None = None
    for token, tenant_id in tokens.items():
        if secrets.compare_digest(token.encode("utf-8", "surrogateescape"), presented_bytes):
            matched = tenant_id
    return matched


DEFAULT_MAX_REQUEST_BYTES = 256 * 1024
"""Cap on a relay request body. Slot-fill requests are tiny; this is generous for them."""


def _throttled_response(exc: RelayThrottledError) -> JSONResponse:
    """Render a refusal as a 429 a client can act on without parsing prose.

    ``Retry-After`` is emitted as **bare integer seconds**, never the HTTP-date spelling
    the RFC also permits: this project's own `parse_retry_after` deliberately refuses
    dates, so a date here would be silently dropped by our own client. Rounded up, because
    rounding a backoff down is how a client retries into the same wall.
    """
    info = exc.info
    headers = {"Retry-After": str(max(1, math.ceil(info.retry_after_s)))}
    if info.remaining is not None:
        headers[_RATE_LIMIT_REMAINING] = str(info.remaining)
        headers[_RATE_LIMIT_RESET] = str(max(1, math.ceil(info.retry_after_s)))
    return JSONResponse(
        {"error": str(exc), "reason": info.reason, "retry_after_s": info.retry_after_s},
        status_code=429,
        headers=headers,
    )


def _apply_budget_headers(response: JSONResponse, relay: Relay, tenant_id: str) -> None:
    """Tell a successful caller how much of its own budget is left.

    This is the half that lets a client slow down *before* the wall rather than after it,
    which is the more useful half — a 429 arrives too late to avoid the round trip it
    refused.

    Every value derives from the requesting tenant's own state, never the process's. A
    remaining count computed from global load would let a tenant poll in a loop and read
    another tenant's traffic volume straight off its own response headers, which is the
    enumeration the registry's uniform error message exists to prevent.

    Nothing is emitted when the tenant has no configured limits: an empty dialect honestly
    declared beats a guessed one, which is the same call `RateLimitHeaders` makes.
    """
    admission = relay.admission()
    limits = admission.limits_for(tenant_id)
    if limits.max_in_flight is None:
        return
    response.headers[_RATE_LIMIT_LIMIT] = str(limits.max_in_flight)
    remaining = admission.remaining(tenant_id)
    if remaining is not None:
        response.headers[_RATE_LIMIT_REMAINING] = str(remaining)


def build_app(
    relay: Relay,
    *,
    tokens: Mapping[str, str],
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
) -> Any:
    """Build a Starlette app exposing `relay` at ``POST /v1/relay/assemble``.

    A vendor's own script constructs the bound `Relay` (its `TemplateVault` and
    `RelayRegistry` are deployment-specific) and serves the result with any standard ASGI
    server, e.g. ``uvicorn.run(build_app(my_relay, tokens=my_tokens), ...)`` — there is no
    bundled zero-configuration entry point, since the route registry always needs real
    provisioning first.

    Args:
        relay: The bound `Relay` to serve.
        max_request_bytes: Refuse a request body larger than this with 413. Enforced
            while reading rather than from ``content-length``, which is absent on a
            chunked request and forgeable on any other. Pass ``0`` to disable. The
            default is deliberately small: this endpoint takes a routing key and a slot
            mapping, so a body approaching it is already anomalous. Exposure is post-auth
            only, but one misbehaving tenant must not be able to exhaust the process that
            is assembling other tenants' prompts.
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
        except RelayThrottledError as exc:
            return _throttled_response(exc)
        except RelayBadRequestError as exc:
            # Split from the catch-all below: every validation failure used to answer 404,
            # which sends a caller looking for a provisioning problem that does not exist.
            return JSONResponse({"error": str(exc)}, status_code=400)
        except RelayError as exc:
            # Route resolution only. The message stays deliberately uniform across "no such
            # route" and "another tenant's route" — see `RelayRegistry.resolve`.
            return JSONResponse({"error": str(exc)}, status_code=404)

        response = JSONResponse(
            {
                "assembled_prompt": result.assembled_prompt,
                "generation_text": result.generation_text,
                "target": result.target,
                "latency_ms": result.latency_ms,
            }
        )
        _apply_budget_headers(response, relay, tenant_id)
        return response

    if len({*tokens.values()}) >= 2 and not relay.admission().configured_tenants:
        warnings.warn(
            "this relay serves more than one tenant with no admission limits configured: "
            "one tenant's fan-out can consume the whole process. Set TenantLimits via "
            "Relay.admission().set_limits(), or provision them in the registry file.",
            stacklevel=2,
        )

    app = Starlette(routes=[StarletteRoute("/v1/relay/assemble", handle, methods=["POST"])])
    if max_request_bytes > 0:
        # Shared with the sidecar rather than reimplemented: it is dependency-free ASGI,
        # and a second copy would be a second place to fix the next edge case found in it.
        from anyinfer.serve.app import _with_body_limit

        return _with_body_limit(app, max_request_bytes)
    return app
