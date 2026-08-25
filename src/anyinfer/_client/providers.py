"""Provider configuration and lazily-instantiated adapter management.

Adapters are built on first use and cached for the client's lifetime: connection pools and
supervised local servers are expensive to create and must outlive a single request.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

import httpx2

from ..catalog.model import Catalog
from ..credentials import ResolverChain, default_resolver
from ..errors import ConfigError, CredentialError
from ..events.telemetry import TelemetryEvent
from ..local.server import is_loopback
from ..providers.base import (
    EmbedsText,
    GeneratesText,
    ProviderConfig,
    ProviderLifecycle,
    ReranksText,
)
from ..registry import ProviderDescriptor, ProviderRegistry, normalize_provider_id
from ..routing.limits import GoverningTransport, RateLimiter
from ..types.requests import RateLimits

__all__ = ["AdapterPool", "ProviderSettings"]


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    """How one provider instance should be configured on a client.

    A client may hold several instances of the same underlying engine — two Azure
    tenants, a local and a remote Ollama — by giving each one an `alias`. The alias is
    the instance's identity everywhere else: it is what a ``alias:model`` target names,
    what `AdapterPool` keys its adapters by, and what telemetry reports.

    Attributes:
        provider_id: Registered provider id or alias, e.g. ``"openai"`` or ``"claude"``.
            This selects the *engine*, which adapter is built and how it talks.
        alias: Instance id, when this is one of several instances of ``provider_id``.
            Defaults to ``provider_id`` itself, which is the single-instance case.
        base_url: Endpoint override. Optional for providers with a default; required for
            ones that have none (``openai-compat``, ``azure-foundry``).
        api_key: Credential for the provider. Accepts a *reference*
            (``"env://OPENAI_API_KEY"``, ``"credential://system/openai"``) as well as a
            literal; it is resolved once, when the adapter is first built, and registered
            for redaction at that point.
        api_version: Version pin for providers that take one (Azure, Anthropic).
        headers: Extra headers merged into every request.
        options: Provider-specific settings, per the provider's documented
            `ProviderSetupSpec` fields.
        timeout_s: Default per-request timeout for this provider.
        transport: Test seam — an ``httpx2`` transport that intercepts this provider's
            traffic (used by the fake-server and cassette modes).
        limits: Client-side pacing for this instance, or ``None`` for none. Rate limits
            belong to *an account at a provider* rather than to the application, which is
            why they are configured here and not as a client-wide policy.
    """

    provider_id: str
    base_url: str | None = None
    api_key: str | None = None
    api_version: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)
    timeout_s: float = 120.0
    transport: Any | None = None
    proxy: str | None = None
    verify: str | bool | None = None
    client_cert: str | tuple[str, str] | tuple[str, str, str] | None = None
    alias: str | None = None
    limits: RateLimits | None = None

    @property
    def instance_id(self) -> str:
        """This instance's identity: the alias when set, else the provider id."""
        return normalize_provider_id(self.alias or self.provider_id)

    @classmethod
    def of(cls, provider_id: str, **kwargs: Any) -> ProviderSettings:
        """Build settings for a provider id, normalizing the id and any alias."""
        alias = kwargs.pop("alias", None)
        return cls(
            provider_id=normalize_provider_id(provider_id),
            alias=normalize_provider_id(alias) if alias else None,
            **kwargs,
        )


class AdapterPool:
    """Owns adapter instances and their lifecycles for one client.

    Adapters are keyed by **instance id** rather than by engine, so two settings entries
    naming the same ``provider_id`` under different aliases get two independent adapters
    with their own credentials, endpoints, and connection pools.
    """

    def __init__(
        self,
        settings: list[ProviderSettings],
        *,
        registry: ProviderRegistry,
        catalog: Catalog | None = None,
        resolver: ResolverChain | None = None,
        events: Callable[[TelemetryEvent], None] | None = None,
    ) -> None:
        self._registry = registry
        self._catalog = catalog
        self._resolver = resolver or default_resolver()
        self._events = events
        self._settings: dict[str, ProviderSettings] = {}
        self._order: list[str] = []
        for setting in settings:
            instance_id = setting.instance_id
            if instance_id in self._settings:
                raise ConfigError(
                    f"provider instance {instance_id!r} is configured twice",
                    provider=instance_id,
                    hint=(
                        "give each instance a distinct alias, e.g. "
                        "ProviderSettings.of('azure-foundry', alias='work-azure', ...)"
                    ),
                )
            self._settings[instance_id] = setting
            self._order.append(instance_id)
            self._register_alias(setting)
        self._adapters: dict[str, ProviderLifecycle] = {}
        self._limiters: dict[str, RateLimiter] = {}
        self._lock = asyncio.Lock()

    def _register_alias(self, settings: ProviderSettings) -> None:
        """Make ``alias:model`` resolvable by deriving a descriptor for the instance.

        Target resolution runs against the registry, so an aliased instance only becomes
        addressable once the registry knows its id. The derived descriptor is the engine's
        own, re-labelled: same factory, same setup spec, same capabilities — only the
        identity differs, which is exactly what an instance *is*.
        """
        instance_id = settings.instance_id
        engine_id = normalize_provider_id(settings.provider_id)
        if instance_id == engine_id:
            return
        base = self._registry.get(engine_id)
        if self._registry.has(instance_id):
            # Replacing a *previously derived* descriptor is the normal case: an
            # application that rebuilds its client on every settings change re-derives
            # the same instances against a long-lived registry. Taking the name of a
            # real provider is not — that would silently reroute its traffic.
            existing = self._registry.get(instance_id)
            if not getattr(existing, "derived_from", None):
                owner = self._registry.resolve_alias(instance_id)
                raise ConfigError(
                    f"instance alias {instance_id!r} is already registered "
                    f"(it names provider {owner!r})",
                    provider=instance_id,
                    hint="choose an instance alias that is not a provider id or alias",
                )
        derived = replace(
            base, id=instance_id, aliases=(), derived_from=normalize_provider_id(base.id)
        )
        self._registry.register(derived, replace=True)

    @property
    def configured_ids(self) -> tuple[str, ...]:
        """Configured instance ids, in the order the application supplied them.

        This order is what makes catalog-alias resolution deterministic: the first
        configured provider that realizes an alias wins.
        """
        return tuple(self._order)

    def descriptor_for(self, provider_id: str) -> ProviderDescriptor:
        """Look up a provider instance's descriptor."""
        return self._registry.get(provider_id)

    def configuration_reason(self, provider_id: str) -> str | None:
        """Return why an instance cannot be built, without constructing its adapter."""
        key = self._registry.resolve_alias(provider_id)
        descriptor = self._registry.get(key)
        settings = self._settings.get(key)
        if settings is None:
            return f"provider instance {key!r} is not configured"

        values: dict[str, str] = {
            "base_url": settings.base_url or descriptor.default_base_url or "",
            "api_key": settings.api_key or "",
            "api_version": settings.api_version or "",
            **{name: str(value) for name, value in settings.options.items() if value is not None},
        }
        missing = [
            setup_field.key
            for setup_field in descriptor.setup.fields
            if setup_field.required and not values.get(setup_field.key, "").strip()
        ]
        unsatisfied = descriptor.setup.unsatisfied_groups(values)
        if missing:
            return "missing required setting(s): " + ", ".join(missing)
        if unsatisfied:
            return "missing one of required setting group: " + " or ".join(unsatisfied[0])
        if descriptor.requires_base_url and not values["base_url"]:
            return "the provider requires a base URL"

        for setup_field in descriptor.setup.fields:
            if setup_field.kind != "secret":
                continue
            reference = values.get(setup_field.key, "")
            if not reference:
                continue
            try:
                self._resolver.resolve(reference)
            except CredentialError as exc:
                return str(exc)
        return None

    def base_url_for(self, provider_id: str) -> str | None:
        """The endpoint an instance will actually talk to, after defaults and shorthand."""
        try:
            descriptor = self._registry.get(provider_id)
        except ConfigError:
            return None
        settings = self._settings.get(provider_id)
        base_url = (settings.base_url if settings else None) or descriptor.default_base_url
        if descriptor.setup.host_shorthand is not None and base_url:
            base_url = descriptor.setup.host_shorthand.expand(base_url)
        return base_url

    def transport_for(self, provider_id: str) -> Any | None:
        """This instance's transport override, if it was given one.

        Needed by operations that talk to a provider's endpoint without going through its
        adapter — a model pull, for instance, so the fake-server and cassette test modes
        intercept those the same way they intercept generation.
        """
        settings = self._settings.get(self._registry.resolve_alias(provider_id), None)
        return settings.transport if settings is not None else None

    def locality_for(self, provider_id: str) -> Literal["hosted", "local", "remote"]:
        """Where this *instance* runs, which the descriptor alone cannot say.

        A ``local`` engine pointed at a non-loopback address is running on somebody else's
        machine: its per-token cost is not a genuine zero, and this machine's RAM is not
        the RAM that matters. Reporting ``remote`` is what keeps both of those honest.
        """
        try:
            descriptor = self._registry.get(provider_id)
        except ConfigError:
            return "hosted"
        if descriptor.locality != "local":
            return descriptor.locality
        base_url = self.base_url_for(provider_id)
        if base_url is None:
            # No endpoint at all means a supervised in-process engine (llama.cpp), which
            # is as local as it gets.
            return "local"
        return "local" if is_loopback(base_url) else "remote"

    async def get(self, provider_id: str) -> ProviderLifecycle:
        """Return the adapter for a provider instance, building it on first use.

        Raises:
            ConfigError: If the provider is unknown, or its required settings are missing.
        """
        key = self._registry.resolve_alias(provider_id)
        adapter = self._adapters.get(key)
        if adapter is not None:
            return adapter
        async with self._lock:
            adapter = self._adapters.get(key)
            if adapter is not None:
                return adapter
            adapter = self._build(key)
            self._adapters[key] = adapter
            return adapter

    def _build(self, provider_id: str) -> ProviderLifecycle:
        descriptor = self._registry.get(provider_id)
        settings = self._settings.get(provider_id) or ProviderSettings(provider_id=provider_id)

        base_url = settings.base_url or descriptor.default_base_url
        if descriptor.setup.host_shorthand is not None and base_url:
            base_url = descriptor.setup.host_shorthand.expand(base_url)
        if descriptor.requires_base_url and not base_url:
            raise ConfigError(
                f"provider {provider_id!r} requires a base URL",
                provider=provider_id,
                hint=(
                    f"pass ProviderSettings.of({provider_id!r}, base_url=...) when "
                    "constructing the client"
                ),
            )

        api_key = self._resolver.resolve(settings.api_key)
        options = dict(self._resolve_secret_options(descriptor, settings.options))
        if descriptor.uses_catalog and self._catalog is not None:
            options.setdefault("catalog", self._catalog)

        config = ProviderConfig(
            provider_id=provider_id,
            base_url=base_url,
            api_key=api_key,
            api_version=settings.api_version,
            headers=settings.headers,
            options=options,
            timeout_s=settings.timeout_s,
            transport=self._govern(provider_id, descriptor, settings),
            proxy=settings.proxy,
            verify=settings.verify,
            client_cert=settings.client_cert,
            events=self._events,
        )
        adapter = descriptor.factory(config)
        self._validate_operations(provider_id, descriptor, adapter)
        return adapter

    def _validate_operations(
        self, provider_id: str, descriptor: ProviderDescriptor, adapter: ProviderLifecycle
    ) -> None:
        """Fail fast when a descriptor claims an operation its adapter object cannot do.

        A declared-but-unsatisfied operation is a provider-authoring bug, not a runtime
        condition to route around — catching it at first build keeps a broken descriptor
        from surfacing as a confusing `AttributeError` deep inside the router instead.
        """
        checks: dict[str, type] = {
            "generation": GeneratesText,
            "embedding": EmbedsText,
            "rerank": ReranksText,
        }
        for operation in descriptor.operations:
            protocol = checks.get(operation)
            if protocol is not None and not isinstance(adapter, protocol):
                raise ConfigError(
                    f"provider {provider_id!r} declares support for {operation!r} but its "
                    f"adapter does not implement {protocol.__name__}",
                    provider=provider_id,
                    hint="fix the descriptor's operations set or the adapter's factory",
                )

    def _govern(
        self,
        provider_id: str,
        descriptor: ProviderDescriptor,
        settings: ProviderSettings,
    ) -> Any | None:
        """Wrap this instance's transport in its limiter, when it has one.

        Pacing is installed here rather than in the adapter because an adapter translates
        and must not carry policy. Wrapping composes with the test seams: a fake or cassette
        transport ends up *inside* the governor, so pacing can be proven with no network.

        A provider that builds its own transport gets its limiter registered anyway — the
        client applies concurrency around the call, and the limiter is skipped here because
        there is nothing of ours to wrap.
        """
        limits = settings.limits
        if limits is None or not limits.active:
            return settings.transport
        limiter = RateLimiter(
            limits,
            dialect=descriptor.rate_limit_headers,
            provider_id=provider_id,
            events=self._events,
            sees_responses=not descriptor.governs_own_transport,
        )
        self._limiters[provider_id] = limiter
        if descriptor.governs_own_transport:
            return settings.transport
        inner = settings.transport
        if inner is None:
            inner = httpx2.AsyncHTTPTransport()
        return GoverningTransport(inner, limiter)

    def limiter_for(self, provider_id: str) -> RateLimiter | None:
        """This instance's limiter, once its adapter has been built.

        Built lazily with the adapter, so a client that never used a provider never
        allocated its limiter either.
        """
        return self._limiters.get(self._registry.resolve_alias(provider_id))

    def _resolve_secret_options(
        self, descriptor: ProviderDescriptor, options: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Resolve option values the descriptor declares as secrets.

        A provider that takes a second credential (Anthropic's OAuth token beside its API
        key) carries it in ``options``, which is otherwise passed through verbatim. Left
        alone it would never reach the resolver, so ``env://`` would arrive at the
        adapter as the literal string, and a real token would never be registered for
        redaction. Driven off the setup spec's ``secret`` fields, so this stays true for
        any provider, including third-party ones, without naming one.
        """
        secret_keys = {
            f.key
            for f in descriptor.setup.fields
            if f.kind == "secret" and isinstance(options.get(f.key), str)
        }
        if not secret_keys:
            return options
        resolved = dict(options)
        for key in secret_keys:
            resolved[key] = self._resolver.resolve(resolved[key])
        return resolved

    async def aclose(self) -> None:
        """Close every built adapter, gathering failures rather than stopping at the first."""
        adapters = list(self._adapters.values())
        self._adapters.clear()
        results = await asyncio.gather(*(a.aclose() for a in adapters), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, Exception):
                raise result
