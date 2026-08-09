"""Provider descriptors and the collision-safe registry.

A `ProviderDescriptor` is *declarative data* about a provider: how to build its
adapter, what configuration it needs, how it spells reasoning effort, and what it is known to
support. Consuming applications drive their config UIs from `ProviderSetupSpec`, which
is why no core, config, or UI code ever needs a per-engine ``if/elif`` branch.

Third-party adapters register through the ``anyinfer.providers`` entry-point group, loaded
lazily so import cost stays flat regardless of how many providers are installed.
"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any, Literal

from .errors import ConfigError
from .types.capabilities import ModelCapabilities, TokenCalibration
from .types.requests import ReasoningEffort

if TYPE_CHECKING:
    from .providers.base import ProviderAdapter, ProviderConfig

__all__ = [
    "ENTRY_POINT_GROUP",
    "AdapterFactory",
    "HostShorthand",
    "ModelPuller",
    "ProviderDescriptor",
    "ProviderRegistry",
    "ProviderSetupSpec",
    "ReasoningTranslator",
    "SetupField",
    "SetupFieldKind",
    "default_registry",
    "normalize_provider_id",
]

ENTRY_POINT_GROUP = "anyinfer.providers"
"""Entry-point group third-party adapters advertise themselves under."""

AdapterFactory = Callable[["ProviderConfig"], "ProviderAdapter"]
"""Builds an adapter instance from resolved provider configuration."""

ReasoningTranslator = Callable[[ReasoningEffort | None], Mapping[str, Any]]
"""Translates normalized reasoning effort into provider wire fields."""

ModelPuller = Callable[[Any], Awaitable[Any]]
"""Makes one model available on an engine that owns its own store.

Typed loosely on purpose: the concrete request and report live in ``anyinfer.local``, and
the registry must not import the local subsystem to name them — a descriptor is declarative
data that every adapter imports, and dragging acquisition into that import graph is exactly
what the layering forbids.
"""

SetupFieldKind = Literal[
    "endpoint", "secret", "api-version", "model-list", "reasoning-efforts", "host-profile"
]
"""What a setup field means, so UIs can render it appropriately without provider knowledge."""


def normalize_provider_id(value: str) -> str:
    """Normalize a provider id or alias: lowercase, stripped, underscores to hyphens."""
    return value.strip().lower().replace("_", "-")


@dataclass(frozen=True, slots=True)
class SetupField:
    """One configurable field a provider needs, described declaratively."""

    key: str
    """Machine name the entered value is saved under in provider settings — a well-known
    key such as ``api_key`` or ``api_version``, or a provider-specific ``options`` entry."""

    label: str
    """Human-readable name a UI shows for the field."""

    kind: SetupFieldKind
    """Semantic role of the field, which tells a UI how to render and validate it."""

    required: bool = False
    """Whether saving needs a non-blank value for this field on its own. Either-or
    alternatives between fields are expressed via `ProviderSetupSpec.any_of` instead."""

    help_text: str = ""
    """Explanatory sentence shown alongside the field; empty when the label suffices."""

    placeholder: str = ""
    """Example value a UI shows in the empty editor.

    Declared per field because the right example is provider knowledge: the environment
    variable an Anthropic key conventionally lives in is not the one an OpenAI key does,
    and a UI that guesses picks one provider's convention and is wrong for all the others.
    Empty means the UI falls back to whatever generic hint suits the `kind`.
    """

    advanced: bool = False
    """Whether this field has a standard value that is right for almost every user.

    The split this expresses is *prominence*, not optionality. ``required`` already says
    "saving fails without a value"; plenty of fields are neither required nor worth
    showing — an Ollama base URL, an Anthropic API version, a Bedrock signing profile.
    Presented as equals they read as five questions where there is really one, and every
    consuming application then has to rediscover which is which from prose help text.

    So the provider says it here: ``advanced`` fields are the ones a UI may fold behind a
    disclosure, leaving the fields a user genuinely has to answer in front of them. A
    required field is never advanced — hiding something that blocks saving is exactly the
    trap this exists to avoid — and `ProviderSetupSpec` rejects that combination.
    """

    default_value: str = ""
    """The value the provider falls back to when this field is left blank.

    What a UI shows as "standard: …" beside a hidden field, so folding one away never
    hides *what it will do*. Empty when the field has no default — a credential has none,
    and neither does an endpoint the user must supply.

    A UI should render this rather than pre-filling the editor with it: a saved copy of
    today's default is a value frozen at the moment someone opened a dialog, and it keeps
    overriding the real default long after that default has moved on.
    """


@dataclass(frozen=True, slots=True)
class HostShorthand:
    """Expansion rule for bare hostnames, e.g. ``myserver`` → ``http://myserver:11434``."""

    scheme: str
    """URL scheme prepended when expanding a bare host, e.g. ``http``."""

    default_port: int
    """Port appended when the bare host does not name one."""

    def expand(self, host: str) -> str:
        """Expand a bare host into a full base URL, leaving full URLs untouched."""
        value = host.strip()
        if "://" in value:
            return value
        if ":" in value.split("/", 1)[0]:
            return f"{self.scheme}://{value}"
        return f"{self.scheme}://{value}:{self.default_port}"


@dataclass(frozen=True, slots=True)
class ProviderSetupSpec:
    """Everything a config UI needs to configure a provider without knowing which it is."""

    fields: tuple[SetupField, ...] = ()
    """The provider's configurable fields, in the order a UI should present them."""

    model_selection: Literal["discover-or-manual", "manual-only"] = "discover-or-manual"
    """Whether a UI may offer models discovered from the endpoint, or must let the user
    type a model id because the provider cannot enumerate what it serves."""

    host_shorthand: HostShorthand | None = None
    """Expansion rule applied when a bare hostname is entered as the base URL, or ``None``
    when only full URLs make sense for this provider."""

    any_of: tuple[tuple[str, ...], ...] = ()
    """Groups of field keys of which at least one must be supplied.

    Some providers accept a choice of credential rather than a fixed one — Anthropic takes
    either an API key or a claude.ai OAuth token. That is a constraint over a *group*, so
    no per-field ``required`` flag can express it: marking both required demands both, and
    marking neither required lets an unconfigured instance save cleanly. Each inner tuple
    names the keys in one such group.
    """

    requirement_note: str = ""
    """One line explaining the spec's requirements, shown beneath the fields.

    Carried here rather than assembled by the UI because only the provider knows *why* its
    ``any_of`` groups exist; a generated sentence would say what is required without ever
    saying what the alternatives mean.
    """

    def __post_init__(self) -> None:
        """Reject a spec that hides a field a user cannot skip.

        Marking a field both mandatory and ``advanced`` asks a UI to do two contradictory
        things, and the resolution it usually picks — honor the disclosure — produces the
        one failure mode worth designing against: a save that refuses, naming a field that
        is not on screen. Caught here, at import time, so it is a provider-authoring error
        rather than a user's dead end.
        """
        blocking = {key for group in self.any_of for key in group}
        for setup_field in self.fields:
            if not setup_field.advanced:
                continue
            if setup_field.required:
                raise ConfigError(
                    f"setup field {setup_field.key!r} is both required and advanced",
                    hint="a field that blocks saving must stay visible; drop advanced=True",
                )
            if setup_field.key in blocking:
                raise ConfigError(
                    f"setup field {setup_field.key!r} is in an any_of group and advanced",
                    hint=(
                        "one of the group has to be filled in, so none of them may be "
                        "hidden behind a disclosure"
                    ),
                )

    @property
    def essential_fields(self) -> tuple[SetupField, ...]:
        """The fields a UI should put in front of the user, in declared order.

        Everything the provider cannot supply a sensible answer for: credentials, and the
        endpoints and identifiers that vary per account. This is the short list an
        application prompts for.
        """
        return tuple(f for f in self.fields if not f.advanced)

    @property
    def advanced_fields(self) -> tuple[SetupField, ...]:
        """The fields that already have a standard value, in declared order.

        Offer them — a base URL override is what makes a proxy or a mirror usable — but
        offer them folded away, since changing one is the rare case rather than the setup
        path.
        """
        return tuple(f for f in self.fields if f.advanced)

    def unsatisfied_groups(self, values: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
        """Return the `any_of` groups no value satisfies.

        Empty when every group has at least one non-blank value, which is the case a UI
        needs to allow a save.
        """
        return tuple(
            group
            for group in self.any_of
            if not any(values.get(key, "").strip() for key in group)
        )

    def label_for(self, key: str) -> str:
        """The declared label for a field key, falling back to the key itself."""
        for setup_field in self.fields:
            if setup_field.key == key:
                return setup_field.label
        return key


def _no_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Default translator: the provider has no reasoning-effort control."""
    return {}


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """Declarative facts about a provider and how to instantiate its adapter."""

    id: str
    """Canonical provider id — the ``provider`` half of a ``provider:model`` target.
    Normalized for lookup: lowercased, stripped, underscores to hyphens."""

    display_name: str
    """Human-readable name for UIs and error messages."""

    factory: AdapterFactory
    """Builds this provider's adapter instance from its resolved configuration."""

    aliases: tuple[str, ...] = ()
    """Alternative names that resolve to this provider; each must be globally unique
    across the registry."""
    locality: Literal["hosted", "local", "remote"] = "hosted"
    """Where inference physically happens.

    ``local`` means "on this machine" and carries two consequences — genuine zero pricing,
    and hardware detection that describes the right computer. ``remote`` is the third case
    a descriptor can never state on its own: an engine that is normally local, reached over
    a network. A client downgrades ``local`` to ``remote`` when the configured base URL is
    not loopback, because stamping zero cost on someone else's metered proxy, or sizing
    models against the wrong machine's RAM, are both silent wrong answers.
    """

    default_base_url: str | None = None
    """Endpoint used when settings supply no base URL; ``None`` when there is no sensible
    default, as with per-tenant or supervised endpoints."""

    requires_base_url: bool = False
    """Whether the adapter cannot be built without a configured base URL."""

    setup: ProviderSetupSpec = ProviderSetupSpec()
    """Declarative description of the configuration this provider needs, which is what a
    config UI renders."""

    reasoning_translator: ReasoningTranslator = _no_reasoning
    """Maps normalized reasoning effort onto this provider's wire fields. The default
    translates every effort to nothing, for providers without a reasoning control."""

    static_capabilities: Mapping[str, ModelCapabilities] = field(default_factory=dict)
    """Per-model capabilities declared ahead of time, keyed by model id; layered over
    `default_capabilities` when capabilities are assembled."""

    default_capabilities: ModelCapabilities = ModelCapabilities()
    """Capabilities assumed for any model without a more specific source."""

    token_calibration: TokenCalibration = TokenCalibration()
    """How much this provider's transport inflates the prompt it is billed for.

    Declared here rather than measured per request because it is a property of the
    provider's envelope, not of any one call: a session API that wraps the caller's
    messages in its own harness charges that harness on every request. The default is the
    identity — the provider counts what it was sent — and only a provider with evidence of
    a systematic gap should declare otherwise.
    """

    supports_sessions: bool = False
    """Whether the provider can keep state between requests — a session API, or keep-alive
    model residency — rather than treating every request as independent."""

    model_puller: ModelPuller | None = None
    """How this provider is told to make a model available, or ``None`` when it cannot be.

    For engines that keep their own model store, registry, and downloader — Ollama — the
    useful operation is not *download these weights* but *make yourself ready*. The
    implementation lives in ``anyinfer.local.services`` and is merely pointed at from here,
    both because acquisition never belongs in an adapter and because a declared hook keeps
    "which providers can do this" answerable from the registry rather than from a chain of
    engine checks in the core.

    Weights fetched this way land in the *engine's* store under the engine's own name.
    Nothing is written to AnyInfer's model store and nothing is indexed there, so
    `locate_model()` will not find them — they are not ours to find.
    """

    reports_diagnostics: bool = False
    """Whether this provider's adapter implements
    `SupportsDiagnostics`.

    Declared rather than probed for, so "which providers can tell me about their runtime"
    is answerable from the registry alone. The core only calls ``diagnostics()`` on a
    provider that advertises it here.
    """

    grammar_needs_prompt_injection: bool = False
    """Whether ``grammar`` mode also requires the schema in the prompt.

    True for engines that compile the schema to a decoding grammar without conditioning
    the model on it (llama.cpp, and Ollama's ``format``): the grammar guarantees
    well-formed JSON but not *meaningful* JSON unless the model was told the shape.
    """

    max_repair_attempts: int | None = None
    """The most schema-repair round trips this provider may be asked for, or ``None`` for
    no provider-imposed ceiling.

    The repair budget is the caller's to set, and for almost every provider it should
    stay that way. A few cannot honor it: a provider whose every request is slow,
    interactively authenticated, or metered per conversation turn makes a second repair
    attempt cost far more than the malformed answer is worth, and one that keeps
    server-side conversation state is unlikely to answer a re-ask differently anyway.

    Such a provider says so here, and the core clamps to it — visibly, as a
    `ParameterDropped` event, since a
    budget quietly reduced from three to one is exactly the kind of degradation this
    library refuses to perform in silence.
    """

    ignored_parameters: tuple[str, ...] = ()
    """Request parameters this provider accepts and silently discards.

    Distinct from "rejects with an error" and from "supported": a silently-ignored
    parameter looks like success while doing nothing, so the core reports it as a
    `ParameterDropped` event instead of letting it pass
    unnoticed.
    """

    derived_from: str | None = None
    """The engine this descriptor is an *instance* of, when it is one.

    An application that configures two Azure tenants or two OpenAI-compatible endpoints
    gives each instance its own id (``work-azure``, ``ollama-local``); each becomes a
    descriptor derived from the underlying engine's, differing only in identity. ``None``
    means this descriptor *is* an engine, which is the ordinary case.
    """

    @property
    def identifiers(self) -> tuple[str, ...]:
        """The id plus every alias, all normalized."""
        return (
            normalize_provider_id(self.id),
            *(normalize_provider_id(a) for a in self.aliases),
        )


class ProviderRegistry:
    """Maps provider ids and aliases to descriptors, rejecting collisions.

    Built-in providers are registered on first use. Entry-point providers are discovered
    lazily on the first lookup that misses, so installing a provider package is enough to
    make it resolvable.
    """

    def __init__(self, *, load_builtins: bool = True, load_entry_points: bool = True) -> None:
        self._descriptors: dict[str, ProviderDescriptor] = {}
        self._aliases: dict[str, str] = {}
        self._lock = threading.RLock()
        self._load_builtins = load_builtins
        self._load_entry_points = load_entry_points
        self._builtins_loaded = False
        self._entry_points_loaded = False

    def register(self, descriptor: ProviderDescriptor, *, replace: bool = False) -> None:
        """Register a descriptor.

        Args:
            descriptor: The provider to register.
            replace: Allow replacing an existing registration of the same id. Aliases are
                still checked against *other* providers.

        Raises:
            ConfigError: On a duplicate id or an alias already claimed by another provider.
        """
        provider_id = normalize_provider_id(descriptor.id)
        with self._lock:
            if not replace and provider_id in self._descriptors:
                raise ConfigError(
                    f"provider id {provider_id!r} is already registered",
                    hint="choose a different id, or pass replace=True to override",
                )
            for alias in descriptor.identifiers:
                owner = self._aliases.get(alias)
                if owner is not None and owner != provider_id:
                    raise ConfigError(
                        f"alias {alias!r} is already claimed by provider {owner!r}",
                        hint="provider aliases must be globally unique",
                    )
            self._descriptors[provider_id] = descriptor
            for alias in descriptor.identifiers:
                self._aliases[alias] = provider_id

    def unregister(self, provider_id: str) -> None:
        """Remove a provider and its aliases. Unknown ids are ignored."""
        pid = normalize_provider_id(provider_id)
        with self._lock:
            self._descriptors.pop(pid, None)
            self._aliases = {a: p for a, p in self._aliases.items() if p != pid}

    def resolve_alias(self, name: str) -> str:
        """Resolve a provider name or alias to a canonical provider id.

        Raises:
            ConfigError: If no provider claims the name.
        """
        key = normalize_provider_id(name)
        with self._lock:
            self._ensure_loaded()
            provider_id = self._aliases.get(key)
        if provider_id is None:
            known = ", ".join(sorted(self.known_ids()))
            raise ConfigError(
                f"unknown provider {name!r}",
                hint=f"known providers: {known}",
            )
        return provider_id

    def get(self, provider_id: str) -> ProviderDescriptor:
        """Look up a descriptor by id or alias.

        Raises:
            ConfigError: If no provider claims the name.
        """
        canonical = self.resolve_alias(provider_id)
        with self._lock:
            return self._descriptors[canonical]

    def has(self, provider_id: str) -> bool:
        """Whether a provider with this id or alias is registered."""
        with self._lock:
            self._ensure_loaded()
            return normalize_provider_id(provider_id) in self._aliases

    def known_ids(self) -> tuple[str, ...]:
        """Every registered canonical provider id, sorted."""
        with self._lock:
            self._ensure_loaded()
            return tuple(sorted(self._descriptors))

    def __iter__(self) -> Iterator[ProviderDescriptor]:
        """Iterate descriptors in canonical-id order."""
        with self._lock:
            self._ensure_loaded()
            return iter([self._descriptors[k] for k in sorted(self._descriptors)])

    def _ensure_loaded(self) -> None:
        """Load built-ins and entry points once. Caller must hold the lock."""
        if self._load_builtins and not self._builtins_loaded:
            self._builtins_loaded = True
            from .providers import builtin_descriptors

            for descriptor in builtin_descriptors():
                if normalize_provider_id(descriptor.id) not in self._descriptors:
                    self._register_locked(descriptor)
        if self._load_entry_points and not self._entry_points_loaded:
            self._entry_points_loaded = True
            self._load_from_entry_points()

    def _register_locked(self, descriptor: ProviderDescriptor) -> None:
        provider_id = normalize_provider_id(descriptor.id)
        self._descriptors[provider_id] = descriptor
        for alias in descriptor.identifiers:
            self._aliases.setdefault(alias, provider_id)

    def _load_from_entry_points(self) -> None:
        """Discover third-party providers.

        A provider package that fails to import or yields a bad object must not take down
        every other provider, so broken entries are skipped; requesting one later fails
        with the ordinary "unknown provider" `ConfigError`.
        """
        try:
            points = entry_points(group=ENTRY_POINT_GROUP)
        except Exception:  # noqa: BLE001 — metadata backends vary across environments
            return
        for point in points:
            try:
                loaded = point.load()
                descriptors = loaded() if callable(loaded) else loaded
                if isinstance(descriptors, ProviderDescriptor):
                    descriptors = [descriptors]
                for descriptor in descriptors:
                    if not isinstance(descriptor, ProviderDescriptor):
                        continue
                    pid = normalize_provider_id(descriptor.id)
                    if pid in self._descriptors:
                        continue
                    if any(a in self._aliases for a in descriptor.identifiers):
                        continue
                    self._register_locked(descriptor)
            except Exception:  # noqa: BLE001 — a broken plugin must not break the registry
                continue


default_registry = ProviderRegistry()
"""The process-wide provider registry used when a client is given no other.

Deliberately *not* named ``registry``: a module-level name equal to the module's own name
shadows the module itself on the package, which breaks introspection, documentation
generation, and patching in tests.
"""
