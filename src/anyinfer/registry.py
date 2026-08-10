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
from .types.capabilities import ModelCapabilities, RateLimitHeaders, TokenCalibration
from .types.requests import CacheMechanism, ReasoningEffort

if TYPE_CHECKING:
    from .providers.base import ProviderAdapter, ProviderConfig

__all__ = [
    "ENTRY_POINT_GROUP",
    "AdapterFactory",
    "HostShorthand",
    "ModelPuller",
    "PluginLoadIssue",
    "PluginLoadReason",
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
    "endpoint",
    "secret",
    "api-version",
    "model-list",
    "reasoning-efforts",
    "host-profile",
    "text",
    "choice",
    "path",
    "directory",
]
"""What a setup field means, so UIs can render it appropriately without provider knowledge.

The kind is what a UI keys its widget *and its empty-editor hint* off, so it has to
distinguish things a single "line of text" would flatten. ``endpoint`` means a URL and a UI
may legitimately hint one; a filesystem path, a bounded enum, and a bare identifier are not
URLs, and rendering them as though they were is how a model directory ends up prompting for
``https://…``. Hence ``path``/``directory`` (offer a file picker), ``choice`` (offer the
declared `SetupField.choices`), and ``text`` (a plain identifier with no shape a UI can
guess).

``host-profile`` predates that split and stays for the credential-chain selectors it was
introduced for — an AWS profile or region names a *provider-side* configuration rather than
a value with a shape.
"""


def normalize_provider_id(value: str) -> str:
    """Normalize a provider id or alias: lowercase, stripped, underscores to hyphens."""
    return value.strip().lower().replace("_", "-")


PluginLoadReason = Literal["import-failed", "not-a-descriptor", "id-taken", "alias-taken"]
"""Why a third-party entry point did not become a usable provider."""


@dataclass(frozen=True, slots=True)
class PluginLoadIssue:
    """An ``anyinfer.providers`` entry point that did not become a usable descriptor.

    A broken third-party package must never take down the registry, so loading failures are
    swallowed. Swallowed silently, though, they produce the worst diagnostic this library
    can offer: the user's provider simply does not exist, and the only symptom is an
    "unknown provider" error listing every provider except theirs. Recording the failure
    here keeps the isolation and removes the silence.

    Attributes:
        entry_point: Name of the entry point that failed.
        reason: What went wrong; see `PluginLoadReason`.
        detail: Bounded, redacted explanation — an import error can name filesystem paths.
    """

    entry_point: str
    reason: PluginLoadReason
    detail: str = ""

    @property
    def summary(self) -> str:
        """One line naming the entry point and what happened to it."""
        text = f"{self.entry_point}: {self.reason}"
        return f"{text} ({self.detail})" if self.detail else text


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

    env_var: str = ""
    """Environment variable this field is conventionally supplied from, if any.

    The machine-readable half of what `placeholder` says in prose. A placeholder reading
    ``"env://ANTHROPIC_API_KEY or a literal key"`` is a UI hint; parsing it back out to
    learn which variable to look for is guessing at free text. Declared here, "is this
    provider already usable on this machine?" becomes a lookup rather than a regex, which
    is what `anyinfer.local.discovery` and a config UI's "we found this in your
    environment" both need.

    The bare variable name, never the ``env://`` reference form — the scheme is the
    credential resolver's spelling, and storing it here would make every consumer strip it.
    Empty when the provider has no convention, which is the case for a generic
    OpenAI-compatible endpoint and for every provider whose credential is not an
    environment variable at all.
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
    trap this exists to avoid, and `ProviderSetupSpec` rejects that combination.
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

    choices: tuple[str, ...] = ()
    """The accepted values, for a ``choice`` field.

    A bounded enum typed into a free-text box is a value that validates at request time
    rather than at configuration time, which turns a typo into a runtime error somewhere
    else entirely. Declaring the set here lets a UI offer it and lets a non-UI caller check
    a stored value without knowing which provider it belongs to.

    Empty for every other kind — a field whose values a provider cannot enumerate has
    nothing to put here, and `SetupField` rejects the two contradictory combinations.
    """

    def __post_init__(self) -> None:
        """Reject a field whose declared choices and kind disagree.

        A ``choice`` with no alternatives renders as an empty dropdown, and choices on a
        free-text field are a constraint no UI will apply. Both are provider-authoring
        errors, caught at import time rather than at the moment someone opens a dialog.
        """
        if self.kind == "choice" and not self.choices:
            raise ConfigError(
                f"setup field {self.key!r} is a choice with no choices",
                hint="declare choices=(…), or use kind='text' for a free-form value",
            )
        if self.kind != "choice" and self.choices:
            raise ConfigError(
                f"setup field {self.key!r} declares choices but its kind is {self.kind!r}",
                hint="only kind='choice' fields are rendered as a fixed set of values",
            )
        if self.env_var and ("://" in self.env_var or self.env_var != self.env_var.strip()):
            raise ConfigError(
                f"setup field {self.key!r} declares env_var {self.env_var!r}, which is not "
                "a bare variable name",
                hint="declare env_var='ANTHROPIC_API_KEY', not the 'env://…' reference form",
            )


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
            group for group in self.any_of if not any(values.get(key, "").strip() for key in group)
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
    identity — the provider counts what it was sent, and only a provider with evidence of
    a systematic gap should declare otherwise.
    """

    rate_limit_headers: RateLimitHeaders = RateLimitHeaders()
    """Which response headers this provider reports its rate-limit state in.

    Empty by default, which means client-side pacing for this provider can only honour the
    bounds its caller configured. Declaring a dialect is what lets pacing anticipate the
    provider's own window instead — and, like every other wire fact here, it belongs in the
    provider's contract snapshot with a verified date.
    """

    governs_own_transport: bool = False
    """Whether this provider builds its own transport rather than taking the core's.

    True for adapters that talk through a vendor SDK or an interactive session instead of
    an ``httpx2`` client the core constructed. The core cannot wrap what it did not build,
    so such a provider gets concurrency pacing only, applied around the call, and reports a
    dropped parameter if the caller asked for header-driven pacing it cannot perform.
    """

    supports_sessions: bool = False
    """Whether the provider can keep state between requests — a session API, or keep-alive
    model residency, rather than treating every request as independent."""

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

    model_inventory: Literal["available", "installed", "served"] = "served"
    """What ``list_models()`` means for model-management UIs.

    ``available`` is a catalog of things that could be run, ``installed`` is a
    provider-owned on-disk store, and ``served`` is the set an already-running engine
    exposes. The distinction prevents an application from presenting every catalog entry
    as though it were already installed.
    """

    uses_catalog: bool = False
    """Whether the core should supply its active catalog to this adapter.

    Declared here so catalog composition is a provider fact, not a provider-id branch in
    client construction. Supervised engines use it to resolve model references while
    ordinary protocol adapters leave it false.
    """

    reports_diagnostics: bool = False
    """Whether this provider's adapter implements
    `SupportsDiagnostics`.

    Declared rather than probed for, so "which providers can tell me about their runtime"
    is answerable from the registry alone. The core only calls ``diagnostics()`` on a
    provider that advertises it here.
    """

    cache_mechanism: CacheMechanism | None = None
    """How this provider's prompt cache is engaged, or ``None`` when it offers nothing.

    ``explicit`` means the wire format accepts per-segment cache marks and the adapter
    knows how to spell one. ``implicit`` means the provider caches stable prefixes by
    itself, so there is nothing to send and the core's whole duty is to leave the prefix
    alone. Declared here rather than inferred, because "does this provider cache" is a
    protocol fact recorded in its contract snapshot, not something to probe for.
    """

    cache_max_marks: int = 0
    """Most explicit cache marks this provider accepts per request; ``0`` when it takes
    none. Exceeding a provider's ceiling is an error on some APIs and silently ignored on
    others, so the core clamps to this and reports the clamp."""

    cache_min_tokens: int = 0
    """Smallest segment this provider will actually cache, in tokens.

    Below its own floor a provider bills a cache *write* and then never serves a read from
    it, so a mark placed there costs money and saves none. ``0`` means the provider states
    no floor.
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
        self._issues: list[PluginLoadIssue] = []

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
            issues = tuple(self._issues)
        if provider_id is None:
            # A provider that failed to load looks identical to one that was never
            # installed. Saying which happened is the difference between a five-minute
            # fix and an abandoned integration.
            blamed = next((i for i in issues if key in i.entry_point or key in i.detail), None)
            if blamed is not None:
                raise ConfigError(
                    f"unknown provider {name!r}",
                    hint=(
                        f"a provider plugin matching it failed to load — {blamed.summary}; "
                        "reinstall or fix that package, then retry"
                    ),
                )
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

    def plugin_issues(self) -> tuple[PluginLoadIssue, ...]:
        """Third-party entry points that did not become usable providers.

        Empty when every installed provider package loaded, which is the ordinary case.
        Populated only once discovery has run, so callers that want a complete answer
        should touch the registry first (any lookup does).
        """
        with self._lock:
            self._ensure_loaded()
            return tuple(self._issues)

    def _load_from_entry_points(self) -> None:
        """Discover third-party providers.

        A provider package that fails to import or yields a bad object must not take down
        every other provider, so broken entries are skipped, but each skip is recorded on
        `plugin_issues`, because a provider that vanishes without explanation is the worst
        failure mode this registry has.
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
                        self._record_issue(
                            point.name,
                            "not-a-descriptor",
                            f"yielded {type(descriptor).__name__}",
                        )
                        continue
                    pid = normalize_provider_id(descriptor.id)
                    if pid in self._descriptors:
                        self._record_issue(point.name, "id-taken", f"provider id {pid!r}")
                        continue
                    taken = [a for a in descriptor.identifiers if a in self._aliases]
                    if taken:
                        self._record_issue(point.name, "alias-taken", f"alias {taken[0]!r}")
                        continue
                    self._register_locked(descriptor)
            except Exception as exc:  # noqa: BLE001 — a broken plugin must not break us
                self._record_issue(point.name, "import-failed", f"{type(exc).__name__}: {exc}")
                continue

    def _record_issue(self, entry_point: str, reason: PluginLoadReason, detail: str) -> None:
        """Note a skipped entry point. Caller must hold the lock."""
        from .redaction import redact
        from .types.results import DETAIL_MAX_CHARS

        bounded = redact(detail)[:DETAIL_MAX_CHARS]
        self._issues.append(
            PluginLoadIssue(entry_point=entry_point, reason=reason, detail=bounded)
        )


default_registry = ProviderRegistry()
"""The process-wide provider registry used when a client is given no other.

Deliberately *not* named ``registry``: a module-level name equal to the module's own name
shadows the module itself on the package, which breaks introspection, documentation
generation, and patching in tests.
"""
