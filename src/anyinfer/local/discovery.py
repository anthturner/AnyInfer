"""What is already usable on this machine, and the evidence for it.

The question `anyinfer init` has to answer before it can write anything: which providers
would work right now, without installing, downloading, or asking for a credential. Two
sources answer it — an engine already listening on loopback, and an API key already in the
environment — and a third, the OS credential vault, answers it only when asked, because
reading a vault can prompt the user to unlock it.

This lives in the local subsystem because "what is running on this machine" is its subject,
alongside hardware detection and the model store. It is deliberately *descriptor-driven*:
which endpoints to try and which variables to look for are declarative facts on
`anyinfer.registry.ProviderDescriptor`, so adding a provider adds it to discovery with no
code here to change.

Three properties matter more than coverage:

- **Nothing but loopback is contacted.** Only endpoints a descriptor declares as its
  default, and only when they resolve to this machine. Reaching out to a remote host on a
  command whose whole promise is "inspect what you already have" is the kind of surprise
  that gets a tool distrusted.
- **Nothing speculative is reported.** A provider appears here only if it was *observed*:
  the endpoint answered with at least one model, or the variable is present and non-blank.
- **No secret is ever read into a result.** Environment evidence records the variable's
  *name*; vault evidence records the reference. The value stays where it was.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ..errors import AnyInferError
from ..registry import ProviderDescriptor, ProviderRegistry
from .server import is_loopback

__all__ = [
    "KEYRING_IDENTIFIER_SUFFIX",
    "DiscoveredProvider",
    "DiscoveryEvidence",
    "discover",
    "endpoint_candidates",
]

DiscoveryEvidence = Literal["endpoint", "environment", "credential-store"]
"""How a provider was found to be usable.

``endpoint``
    A loopback address the provider declares as its default answered a model listing.
``environment``
    A variable the provider declares as its conventional credential source is set and
    non-blank. Its value was not read.
``credential-store``
    A secret is stored in the OS vault under a conventional identifier. Only ever produced
    when a caller passed ``keyring=True``.
"""

KEYRING_IDENTIFIER_SUFFIX = "-api-key"
"""Suffix of the vault identifier discovery looks under, after the provider id.

There is no protocol here to follow — a vault entry is whatever someone chose to call it —
so discovery looks under two conventional spellings per provider (``openai`` and
``openai-api-key``) and finds nothing otherwise. A caller who named their entry something
else writes the ``credential://`` reference themselves; that is one line of configuration,
and it is better than a command that rummages through a credential store by prefix.
"""

_PROBE_TIMEOUT_S = 1.5
"""Default per-endpoint wall clock. Long enough for a loopback answer, short enough that
two dozen dead ports do not turn a first-run command into a wait."""


@dataclass(frozen=True, slots=True)
class DiscoveredProvider:
    """A provider found usable on this machine, and the evidence for it.

    Attributes:
        provider_id: Registered id of the provider this evidence is for.
        base_url: The endpoint that answered, or the provider's default when the evidence
            is a credential rather than a running service. ``None`` when the provider has
            no default endpoint.
        evidence: What was observed; see `DiscoveryEvidence`.
        detail: One line naming the observation, for display — ``"4 models"``,
            ``"ANTHROPIC_API_KEY set"``. Never contains a credential value.
        models: Model ids the endpoint listed, when it listed any. Empty for credential
            evidence, which says nothing about what a provider serves.
        credential_key: Setup-field key this credential satisfies (``"api_key"``), or
            empty for endpoint evidence.
        credential_ref: The reference a configuration file should carry for that field —
            ``"env://ANTHROPIC_API_KEY"``, ``"credential://system/openai-api-key"``. A
            *reference*, never a value: this is the field a config writer copies, and it is
            built here precisely so no caller is ever tempted to resolve one first.
    """

    provider_id: str
    base_url: str | None
    evidence: DiscoveryEvidence
    detail: str
    models: tuple[str, ...] = ()
    credential_key: str = ""
    credential_ref: str = ""


def endpoint_candidates(registry: ProviderRegistry) -> tuple[tuple[str, ...], ...]:
    """The loopback endpoints `discover` would contact, grouped by shared address.

    Returns:
        One entry per distinct endpoint, as ``(base_url, provider_id, provider_id, …)``
        in registry order. Several engines share a port — ``llamafile``, ``localai``,
        ``ramalama`` and ``llama-swap`` all default to 8080 — so an address that answers
        cannot be attributed to one of them by probing alone, and grouping is how that
        stays visible instead of becoming a coin flip.

    A caller that wants to tell a user exactly what was contacted reads this; the same
    grouping is what keeps `discover` to one request per address.
    """
    grouped: dict[str, list[str]] = {}
    for descriptor in registry:
        url = _probeable_endpoint(descriptor)
        if url is None:
            continue
        grouped.setdefault(url, []).append(descriptor.id)
    return tuple((url, *ids) for url, ids in grouped.items())


async def discover(
    registry: ProviderRegistry,
    *,
    timeout_s: float = _PROBE_TIMEOUT_S,
    probe: bool = True,
    keyring: bool = False,
    environ: Mapping[str, str] | None = None,
    transports: Mapping[str, Any] | None = None,
) -> tuple[DiscoveredProvider, ...]:
    """Report every provider this machine can already use.

    Args:
        registry: Which providers to consider. Endpoints and variables both come from the
            descriptors it holds, so a registry carrying third-party providers discovers
            them on equal terms.
        timeout_s: Wall clock for each endpoint probe. Endpoints are probed concurrently,
            so this bounds the whole endpoint phase rather than summing across it.
        probe: Whether to contact endpoints at all. ``False`` restricts discovery to
            credential evidence, which touches no socket.
        keyring: Whether to consult the OS credential vault. Off by default: an
            environment variable is already in this process, while reading a vault can
            prompt the user to unlock it, so vault evidence is asked for rather than
            collected for free.
        environ: Environment to inspect; defaults to this process's.
        transports: Test seam — ``httpx2`` transports keyed by provider id, used when
            building the probe adapter so a test can prove the probe logic without opening
            a socket.

    Returns:
        The evidence, endpoint findings first and each in registry order. At most one
        entry per provider: an engine that is both running and holds a key in the
        environment is reported as running, since that is the stronger observation.

    Raises:
        anyinfer.errors.ConfigError: If ``keyring=True`` and the ``[keyring]`` extra is
            not installed. Asked for a vault and unable to open one, reporting "nothing
            found" would be a lie by omission.
    """
    found: list[DiscoveredProvider] = []
    if probe:
        found.extend(await _probe_endpoints(registry, timeout_s, transports or {}))

    claimed = {entry.provider_id for entry in found}
    values = os.environ if environ is None else environ
    for descriptor in registry:
        if descriptor.id in claimed:
            continue
        evidence = _environment_evidence(descriptor, values)
        if evidence is not None:
            claimed.add(descriptor.id)
            found.append(evidence)

    if keyring:
        reader = _keyring_reader()
        for descriptor in registry:
            if descriptor.id in claimed:
                continue
            evidence = _vault_evidence(descriptor, reader)
            if evidence is not None:
                claimed.add(descriptor.id)
                found.append(evidence)
    return tuple(found)


# ---- endpoints ---------------------------------------------------------------------


def _probeable_endpoint(descriptor: ProviderDescriptor) -> str | None:
    """The loopback endpoint worth contacting for a descriptor, or ``None``.

    Three conditions, each of which excludes a provider that could otherwise be reported
    without having been observed:

    - it runs on this machine (``locality == "local"``), so contacting it is inspection
      rather than a network call to a third party;
    - it declares a default endpoint that resolves to loopback, so nothing is guessed and
      nothing off-machine is touched;
    - it can enumerate models, so "it answered" is a fact rather than an adapter reporting
      optimistically because it has no cheap probe.
    """
    if descriptor.locality != "local" or descriptor.derived_from is not None:
        return None
    if descriptor.setup.model_selection != "discover-or-manual":
        return None
    url = descriptor.default_base_url
    if not url or not is_loopback(url):
        return None
    return url


async def _probe_endpoints(
    registry: ProviderRegistry,
    timeout_s: float,
    transports: Mapping[str, Any],
) -> list[DiscoveredProvider]:
    """Contact every candidate endpoint once, concurrently, and keep what answered."""
    candidates = endpoint_candidates(registry)
    if not candidates:
        return []
    results = await asyncio.gather(
        *(
            _probe_one(registry, group[0], group[1:], timeout_s, transports)
            for group in candidates
        )
    )
    return [entry for entry in results if entry is not None]


async def _probe_one(
    registry: ProviderRegistry,
    base_url: str,
    provider_ids: tuple[str, ...],
    timeout_s: float,
    transports: Mapping[str, Any],
) -> DiscoveredProvider | None:
    """Ask one endpoint what it serves, reporting nothing if it does not answer.

    Every failure is swallowed: a refused connection, a timeout, a wrong protocol behind
    the port, and a provider whose optional extra is missing all mean the same thing to a
    user — that engine is not available here — and distinguishing them would turn a
    discovery summary into a diagnostics report.
    """
    from ..providers.base import ProviderConfig

    provider_id = provider_ids[0]
    descriptor = registry.get(provider_id)
    config = ProviderConfig(
        provider_id=provider_id,
        base_url=base_url,
        timeout_s=timeout_s,
        transport=transports.get(provider_id),
    )
    try:
        adapter = descriptor.factory(config)
    except (AnyInferError, OSError, ValueError):
        return None
    try:
        async with asyncio.timeout(timeout_s):
            models = await adapter.list_models()
    except (TimeoutError, AnyInferError, OSError, ValueError):
        return None
    finally:
        # `filterwarnings = ["error"]` is in force for this suite, and an unclosed
        # transport surfaces there as an unraisable warning rather than as a test failure
        # anyone can read. Closing in `finally` keeps the probe path clean whether the
        # endpoint answered, refused, or hung.
        with contextlib.suppress(Exception):
            await adapter.aclose()

    ids = tuple(str(getattr(model, "id", model)) for model in models)
    if not ids:
        # An empty listing is a live HTTP server that serves no model, which is not the
        # same as a usable provider — writing it into a configuration would produce a
        # target with nothing behind it.
        return None
    detail = f"{len(ids)} model{'s' if len(ids) != 1 else ''}"
    if len(provider_ids) > 1:
        others = ", ".join(provider_ids[1:])
        detail = f"{detail}; this port is also the default for {others}"
    return DiscoveredProvider(
        provider_id=provider_id,
        base_url=base_url,
        evidence="endpoint",
        detail=detail,
        models=ids,
    )


# ---- credentials -------------------------------------------------------------------


def _environment_evidence(
    descriptor: ProviderDescriptor, environ: Mapping[str, str]
) -> DiscoveredProvider | None:
    """Whether a variable this provider names is set, without reading what it holds."""
    for setup_field in descriptor.setup.fields:
        name = setup_field.env_var
        if not name or not (environ.get(name) or "").strip():
            continue
        return DiscoveredProvider(
            provider_id=descriptor.id,
            base_url=descriptor.default_base_url,
            evidence="environment",
            detail=f"{name} set",
            credential_key=setup_field.key,
            credential_ref=f"env://{name}",
        )
    return None


def _vault_evidence(
    descriptor: ProviderDescriptor, read: Any
) -> DiscoveredProvider | None:
    """Whether the OS vault holds a secret under a conventional identifier."""
    secret_fields = [f for f in descriptor.setup.fields if f.kind == "secret"]
    if not secret_fields:
        return None
    for identifier in (descriptor.id, f"{descriptor.id}{KEYRING_IDENTIFIER_SUFFIX}"):
        if not read(identifier):
            continue
        return DiscoveredProvider(
            provider_id=descriptor.id,
            base_url=descriptor.default_base_url,
            evidence="credential-store",
            detail=f"stored in the OS keyring as {identifier!r}",
            credential_key=secret_fields[0].key,
            credential_ref=f"credential://system/{identifier}",
        )
    return None


def _keyring_reader() -> Any:
    """A ``(identifier) -> bool`` probe over the OS vault.

    Raises:
        anyinfer.errors.ConfigError: If the ``[keyring]`` extra is not installed. A caller
            who asked for the vault and silently got "nothing found" would conclude they
            have no stored credentials, which is a worse answer than the install hint.
    """
    from ..credentials.keyring_store import KEYRING_SERVICE
    from ..errors import ConfigError

    try:
        import keyring
    except ImportError as exc:
        raise ConfigError(
            "discovering stored credentials requires the keyring extra",
            hint="pip install 'anyinfer[keyring]', or drop --keyring",
        ) from exc

    def read(identifier: str) -> bool:
        try:
            return bool(keyring.get_password(KEYRING_SERVICE, identifier))
        except Exception:  # noqa: BLE001 — a locked or absent vault is "nothing found"
            return False

    return read
