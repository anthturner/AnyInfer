"""Tier 2: the `AnyInfer Relay` — zero-retention remote prompt assembly.

**What this protects:** the orchestration pipeline — which templates fire in what order,
routing/scoring logic, few-shot example selection — the part of a vendor's IP that isn't
prompt *text* at all, and that a single captured request on the wire would not reveal.
**What it costs:** the vendor is back in the customer's data path for that call, which
trades directly against the BYOK privacy posture Tier 0 already provides (see
DESIGN.md §30.0, §30.3). A vendor deploying this must document exactly
what the Relay sees (the assembled request, transiently) and what it persists (nothing,
by design and by construction — this module never writes a request or response body to
any durable store; nothing here opens a file or a database connection).

This module is deployment-agnostic on purpose: nothing here assumes who operates it.
Self-hosting by the vendor and any hosted offering run the identical `Relay` class; the
only difference is who runs the process and how `RelayRegistry` is provisioned. See §3's
"Decided" note on both being offered as equal options.

**Multi-tenant isolation.** `RelayRegistry` scopes every route by `tenant_id`: a request
that supplies `tenant_id="acme"` can only ever resolve routes provisioned under
`"acme"`, structurally — there is no code path that looks across tenants. A hosted
deployment serving several vendors' traffic relies on this scoping directly.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from .sealed_template import EncryptedTemplate, TemplateVault

if TYPE_CHECKING:
    import anyinfer as ai

__all__ = [
    "Relay",
    "RelayError",
    "RelayRegistry",
    "RelayResult",
    "RelayRoute",
    "load_registry",
]


class RelayError(Exception):
    """Base class for Relay-specific errors (unknown route, wrong tenant, etc.)."""


@dataclass(frozen=True, slots=True)
class RelayRoute:
    """One vendor-configured orchestration route.

    Attributes:
        routing_key: What a client request selects this route by.
        template: The sealed template this route renders.
        target: The `anyinfer` target string (``provider:model``) a ``"forward"`` mode
            request dispatches to.
    """

    routing_key: str
    template: EncryptedTemplate
    target: str


@dataclass(frozen=True, slots=True)
class RelayResult:
    """What one Relay call returns — held in memory only, never written to disk here.

    Attributes:
        assembled_prompt: The rendered prompt text, present for both modes (a caller in
            ``"forward"`` mode may still want it for its own transient display).
        generation_text: The provider's response text, only in ``"forward"`` mode.
        target: The target the request was (or would be) dispatched to.
        latency_ms: Time spent inside `Relay.handle`, for metadata-only telemetry — never
            the prompt or response content.
    """

    assembled_prompt: str
    generation_text: str | None
    target: str
    latency_ms: float


class RelayRegistry:
    """Tenant-scoped route storage — the structural boundary multi-tenant isolation rests on."""

    def __init__(self) -> None:
        self._routes: dict[str, dict[str, RelayRoute]] = {}

    def register(self, tenant_id: str, route: RelayRoute) -> None:
        """Provision one route under one tenant."""
        self._routes.setdefault(tenant_id, {})[route.routing_key] = route

    def resolve(self, tenant_id: str, routing_key: str) -> RelayRoute:
        """Look up a route, scoped strictly to `tenant_id`.

        Raises:
            RelayError: No route named `routing_key` is provisioned for `tenant_id` —
                deliberately the same error whether the route does not exist at all or
                exists only under a *different* tenant, so a probing client cannot use
                the error to enumerate other tenants' routing keys.
        """
        route = self._routes.get(tenant_id, {}).get(routing_key)
        if route is None:
            raise RelayError(f"no route {routing_key!r} provisioned for this tenant")
        return route


def load_registry(path: str | Path) -> RelayRegistry:
    """Build a `RelayRegistry` from a JSON provisioning file.

    The registry is in-memory and has no persistence of its own, which left every
    deployment hand-writing the same registration loop. This is that loop, so a
    self-hosted relay can be provisioned from a file under configuration management
    rather than from a bespoke script.

    The file holds *sealed* templates — ciphertext — so it is not itself secret material
    and can live in a config repository. Decryption still requires the deployment's
    `TemplateVault`, its key ring, and a valid license.

    Expected shape::

        {
          "tenants": {
            "acme": [
              {
                "routing_key": "summarize",
                "target": "anthropic:claude-sonnet-4-5",
                "template": { ... EncryptedTemplate.to_json() payload ... }
              }
            ]
          }
        }

    Args:
        path: The JSON provisioning file.

    Returns:
        A registry with every listed route provisioned under its tenant.

    Raises:
        RelayError: The file is malformed, or a route entry is missing a required field.
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        tenants = document["tenants"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RelayError(f"cannot load relay registry from {path}: {exc}") from exc

    registry = RelayRegistry()
    for tenant_id, routes in tenants.items():
        for entry in routes:
            try:
                template = EncryptedTemplate.from_json(json.dumps(entry["template"]))
                route = RelayRoute(
                    routing_key=str(entry["routing_key"]),
                    template=template,
                    target=str(entry["target"]),
                )
            except (KeyError, ValueError, TypeError) as exc:
                raise RelayError(
                    f"malformed route for tenant {tenant_id!r} in {path}: {exc}"
                ) from exc
            registry.register(str(tenant_id), route)
    return registry


class Relay:
    """Assembles (and optionally forwards) one request per call, retaining nothing.

    Every `handle()` call is independent: no cache, no session, no store of prior
    requests. The zero-retention contract is structural, not a policy applied on top —
    there is simply nowhere in this class that a request or response body could persist
    past the `return`.
    """

    def __init__(self, *, vault: TemplateVault, registry: RelayRegistry) -> None:
        self._vault = vault
        self._registry = registry

    async def handle(
        self,
        *,
        tenant_id: str,
        routing_key: str,
        slots: dict[str, object],
        mode: Literal["assemble", "forward"] = "assemble",
        provider_settings: ai.ProviderSettings | None = None,
    ) -> RelayResult:
        """Assemble a request, and optionally forward it.

        Args:
            tenant_id: Which vendor's route namespace to resolve `routing_key` against.
            routing_key: Selects the `RelayRoute` to assemble.
            slots: Non-proprietary slot-fill values the client supplies; these are the
                only caller-controlled content that reaches the template render.
            mode: ``"assemble"`` returns the rendered prompt for the client to send
                itself — no provider credential touches this process at all. ``"forward"``
                additionally dispatches the request server-side using
                `provider_settings`, a short-lived, non-persisted credential the caller
                supplies fresh on every call (mirroring `anyinfer.credentials`'
                resolver pattern — nothing here stores it).
            provider_settings: Required when `mode` is ``"forward"``; ignored otherwise.

        Raises:
            RelayError: `mode="forward"` was requested without `provider_settings`, or
                the routing key does not resolve for this tenant.
        """
        start = time.monotonic()
        route = self._registry.resolve(tenant_id, routing_key)
        prompt = self._vault.render(route.template, **slots)

        generation_text: str | None = None
        if mode == "forward":
            if provider_settings is None:
                raise RelayError("mode='forward' requires provider_settings")
            generation_text = await self._forward(prompt, route.target, provider_settings)

        return RelayResult(
            assembled_prompt=prompt,
            generation_text=generation_text,
            target=route.target,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    async def _forward(
        self, prompt: str, target: str, provider_settings: ai.ProviderSettings
    ) -> str:
        import anyinfer as ai
        from anyinfer.redaction import register_secret

        api_key = getattr(provider_settings, "api_key", None)
        if isinstance(api_key, str):
            register_secret(api_key)  # never persisted; registered only for redaction

        client = ai.AsyncClient([provider_settings])
        try:
            result = await client.generate(prompt, target=target)
            return result.text
        finally:
            await client.aclose()
