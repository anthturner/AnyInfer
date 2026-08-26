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

import asyncio
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from .admission import AdmissionController, RelayThrottledError, TenantLimits, ThrottleInfo
from .pacing import DEFAULT_RESERVE_FRACTION, PacingPool
from .sealed_template import EncryptedTemplate, TemplateVault

if TYPE_CHECKING:
    import anyinfer as ai
    from anyinfer.routing.limits import RateLimiter
    from anyinfer.types.capabilities import RateLimitHeaders

__all__ = [
    "Relay",
    "RelayBadRequestError",
    "RelayError",
    "RelayRegistry",
    "RelayResult",
    "RelayRoute",
    "load_registry",
]


class RelayError(Exception):
    """Base class for Relay-specific errors (unknown route, wrong tenant, etc.)."""


class RelayBadRequestError(RelayError):
    """The caller asked for something malformed, rather than something absent.

    Split out from the base class because the two answer different questions and, at the
    HTTP layer, deserve different status codes: a missing route is a 404, while a request
    that omitted a required field is a 400. Every such case was previously indistinguishable
    from "no such route", which told a caller to go looking for a provisioning problem
    that did not exist.
    """


_COLD_START_ESTIMATE_S = 1.0
"""Advertised wait before any service-time sample exists.

Never zero: telling a client to retry immediately at the exact moment the process is at
its cap is how a refusal becomes a hot loop."""

MIN_RETRY_AFTER_S = 0.5
"""Floor on any advertised wait, after jitter."""

MAX_RETRY_AFTER_S = 60.0
"""Ceiling on any advertised wait.

The same shape as core's `MAX_HEADER_WAIT_S`, and for the same reason: a client should
never be told to disappear for longer than it would take to simply ask again."""


def _jittered(estimate: float) -> float:
    """Spread an advertised wait over ``[0.5x, 1x]`` and clamp it.

    Full jitter over the lower half rather than a symmetric spread: the estimate is
    already biased high, so jittering downward keeps the average honest while still
    breaking synchronization. Two hundred clients told an identical "3s" retry in the same
    millisecond, which is a thundering herd the refusal was supposed to prevent.
    """
    # Not cryptographic randomness: this spreads retries, it does not protect anything.
    spread = random.uniform(0.5, 1.0) * estimate
    return min(MAX_RETRY_AFTER_S, max(MIN_RETRY_AFTER_S, spread))


def _dialect_for(provider_id: str) -> RateLimitHeaders:
    """The rate-limit header dialect a provider declares, or an empty one.

    Read from core's own registry rather than restated here: the header names are wire
    facts recorded in each provider's contract snapshot, and a second copy in this package
    is a second thing to drift. An unregistered provider gets the empty dialect, which
    means "pace by configured bounds only" — the honest fallback core already defines.
    """
    from anyinfer.registry import default_registry
    from anyinfer.types.capabilities import RateLimitHeaders

    try:
        return default_registry.get(provider_id).rate_limit_headers
    except Exception:  # noqa: BLE001 — an unknown provider is a missing dialect, not a failure
        return RateLimitHeaders()


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
        self._limits: dict[str, TenantLimits] = {}

    def set_limits(self, tenant_id: str, limits: TenantLimits) -> None:
        """Record one tenant's admission bounds alongside its routes.

        Held here rather than only on the controller because this file is the provisioning
        path: a deployment that describes its tenants in one document should describe
        their capacity there too, not in a second script that has to be kept in step.
        """
        self._limits[tenant_id] = limits

    def limits(self) -> dict[str, TenantLimits]:
        """Every provisioned tenant's bounds, for a `Relay` to install."""
        return dict(self._limits)

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
            "acme": {
              "limits": {"max_in_flight": 8, "max_waiting": 32},
              "routes": [
                {
                  "routing_key": "summarize",
                  "target": "anthropic:claude-sonnet-4-5",
                  "template": { ... EncryptedTemplate.to_json() payload ... }
                }
              ]
            }
          }
        }

    A tenant may also map directly to a bare list of routes, which is the original shape
    and means routes-only. Both are supported permanently: this file is a provisioning
    input under configuration management, and silently requiring a rewrite of every
    deployment's file to add an optional block would be a poor trade for the tidier
    grammar.

    Args:
        path: The JSON provisioning file.

    Returns:
        A registry with every listed route provisioned under its tenant, and every stated
        limit recorded on it.

    Raises:
        RelayError: The file is malformed, or a route entry is missing a required field.
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        tenants = document["tenants"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RelayError(f"cannot load relay registry from {path}: {exc}") from exc

    registry = RelayRegistry()
    for tenant_id, block in tenants.items():
        routes = block if isinstance(block, list) else block.get("routes", [])
        if not isinstance(block, list):
            raw_limits = block.get("limits")
            if raw_limits is not None:
                try:
                    registry.set_limits(str(tenant_id), TenantLimits(**dict(raw_limits)))
                except (TypeError, ValueError) as exc:
                    # Same failure path as a malformed route: a provisioning file that
                    # cannot be honored must not start a relay that silently ignores half
                    # of it.
                    raise RelayError(
                        f"malformed limits for tenant {tenant_id!r} in {path}: {exc}"
                    ) from exc
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

    def __init__(
        self,
        *,
        vault: TemplateVault,
        registry: RelayRegistry,
        pacing: PacingPool | None = None,
        admission: AdmissionController | None = None,
    ) -> None:
        """Bind a relay to its vault and routes.

        Args:
            vault: Decrypts and renders this deployment's sealed templates.
            registry: Tenant-scoped routes.
            pacing: Optional pacing state shared across calls. ``None`` — the default —
                is bit-for-bit today's behaviour: no pooled limiter, no bookkeeping, no
                extra await. Supply one to make provider pacing work at all in forward
                mode, where a per-call client otherwise paces every request against an
                empty bucket. Holds timing metadata only; see `PacingPool`.
            admission: Optional per-tenant concurrency bounds. ``None`` and an
                all-defaults `TenantLimits` are both inert.
        """
        self._vault = vault
        self._registry = registry
        self._pacing = pacing
        self._admission = admission or AdmissionController()
        for tenant_id, limits in registry.limits().items():
            self._admission.set_limits(tenant_id, limits)

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
        # Validation first: a request that can never succeed costs nothing to refuse, and
        # taking an admission slot for it would let malformed traffic consume a tenant's
        # capacity. Then admission, before the route resolves — a tenant at its cap should
        # hear back in milliseconds, and resolving a route it will not be allowed to use
        # is work done for a request that is already rejected.
        if mode == "forward" and provider_settings is None:
            raise RelayBadRequestError("mode='forward' requires provider_settings")

        async with self._admission.admit(tenant_id, estimate=self._estimate_wait(tenant_id)):
            route = self._registry.resolve(tenant_id, routing_key)
            prompt = await self._render(route.template, slots)

            generation_text: str | None = None
            if provider_settings is not None and mode == "forward":
                generation_text = await self._forward(
                    prompt, route.target, provider_settings, tenant_id=tenant_id
                )

            return RelayResult(
                assembled_prompt=prompt,
                generation_text=generation_text,
                target=route.target,
                latency_ms=(time.monotonic() - start) * 1000,
            )

    def admission(self) -> AdmissionController:
        """This relay's admission controller, for provisioning and for reading budgets."""
        return self._admission

    def _estimate_wait(self, tenant_id: str) -> float:
        """How long to tell a refused caller to wait, in seconds.

        Queue position times service time over the concurrency cap — the classic queueing
        estimate — computed **entirely from this tenant's own state**. A figure derived
        from process-wide load would be a metadata side channel: a tenant polling in a loop
        could read another tenant's traffic volume off its own backoff hint, which is
        exactly the enumeration `RelayRegistry.resolve` refuses to allow.

        Three deliberate choices:

        - **Jitter is mandatory**, not a refinement. An exact "3s" told to two hundred
          waiters is a synchronized retry storm with extra steps.
        - **Cold start floors rather than zeroes.** With no samples yet the estimate is a
          fixed second, jittered; telling a client to retry immediately is worse than
          telling it to wait too long.
        - **Clamped at both ends**, so neither a pathological sample nor an empty one
          produces a number a client cannot act on.
        """
        limits = self._admission.limits_for(tenant_id)
        service_s = _COLD_START_ESTIMATE_S
        if self._pacing is not None:
            sampled = self._pacing.service_quantile(tenant_id)
            if sampled is not None:
                service_s = sampled
        cap = limits.max_in_flight or 1
        depth = self._admission.waiting(tenant_id) + 1
        estimate = depth * service_s / cap
        return _jittered(estimate)

    async def _render(self, template: EncryptedTemplate, slots: dict[str, object]) -> str:
        """Render a template, offloading only when the render can block on the network.

        `TemplateVault.render` is synchronous, and the measured crypto path — Ed25519
        verification, AES-GCM decryption, formatting — is well under a millisecond for a
        realistic template, which an event loop tolerates and which a thread hop would
        roughly halve the throughput of for no benefit.

        A *network-backed* revocation checker is the one case where that reasoning
        inverts: a synchronous HTTP round trip inside the coroutine stalls every other
        in-flight request in the process, however fast the crypto is. So the offload is
        scoped to exactly that case, asked of the vault as a capability rather than
        inferred from its internals.
        """
        if self._vault.renders_may_block:
            return await asyncio.to_thread(self._vault.render, template, **slots)
        return self._vault.render(template, **slots)

    async def _forward(
        self,
        prompt: str,
        target: str,
        provider_settings: ai.ProviderSettings,
        *,
        tenant_id: str = "",
    ) -> str:
        """Dispatch one assembled prompt, pacing it against pooled state when configured.

        The client stays per-call. Its cost is small once pacing survives it, and a pooled
        `httpx2` client would hold the BYOK credential in its auth state past the request
        that carried it — which is the one thing this tier's zero-retention claim cannot
        allow. Only the *limiter* is pooled, and a limiter holds nothing but timing.
        """
        import anyinfer as ai
        from anyinfer.redaction import register_secret

        api_key = getattr(provider_settings, "api_key", None)
        if isinstance(api_key, str):
            register_secret(api_key)  # never persisted; registered only for redaction

        limiters = self._limiters_for(provider_settings)
        if limiters is not None:
            self._refuse_if_the_provider_says_wait(limiters, tenant_id)
        client = ai.AsyncClient([provider_settings], limiters=limiters)
        started = time.monotonic()
        try:
            result = await client.generate(prompt, target=target)
        finally:
            await client.aclose()
        if self._pacing is not None:
            # Only a call that actually completed is evidence about service time; see
            # `PacingPool.record_latency` for why a throttled one must never be recorded.
            self._pacing.record_latency(tenant_id, target, time.monotonic() - started)
        return result.text

    def _refuse_if_the_provider_says_wait(
        self, limiters: dict[str, RateLimiter], tenant_id: str
    ) -> None:
        """Refuse now, with the provider's own number, rather than hold a slot asleep.

        Core's limiter would ordinarily *wait* out an exhausted window, which is right for
        a client that owns its own process. It is wrong at a fronting layer: the wait
        happens while this tenant's admission slot is held, so one provider window can
        idle a tenant's whole capacity for its duration. Refusing instead returns that
        capacity immediately and tells the caller exactly when to come back.

        Only when the wait exceeds what the tenant was willing to queue for anyway —
        below that, waiting is cheaper than a round trip, and refusing would be worse than
        the behaviour it replaced.

        The number needs no jitter and no clamping beyond the limiter's own: it is the
        provider's stated reset for the caller's own BYOK key, passed through. That leaks
        nothing — it is the caller's own quota — and inventing a spread around a stated
        fact would make it less true.

        Raises:
            RelayThrottledError: The provider's reported window says to wait longer than
                this tenant's queueing budget.
        """
        budget = self._admission.limits_for(tenant_id).max_wait_s
        for limiter in limiters.values():
            wait_s = limiter.observed_wait_s()
            if wait_s > budget:
                raise RelayThrottledError(
                    ThrottleInfo("provider-window", wait_s, remaining=0)
                )

    def _limiters_for(
        self, provider_settings: ai.ProviderSettings
    ) -> dict[str, RateLimiter] | None:
        """The pooled limiter mapping for one call, or ``None`` when pacing is off."""
        if self._pacing is None:
            return None
        import anyinfer as ai

        key = self._pacing.key_for(provider_settings)
        limits = getattr(provider_settings, "limits", None) or ai.RateLimits(
            reserve_fraction=DEFAULT_RESERVE_FRACTION
        )
        dialect = _dialect_for(provider_settings.provider_id)
        return {key.provider_id: self._pacing.limiter_for(key, limits, dialect)}
