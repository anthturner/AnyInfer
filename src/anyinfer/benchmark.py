"""Throughput measurement: what this target actually does on this machine, right now.

Capabilities describe a model. Nothing in them says how *fast* it is here, and for local
inference that is the number that decides everything — the same weights on the same GPU can
differ by an order of magnitude depending on what else is resident, which runtime variant is
installed, and how many layers ended up offloaded. An application choosing a default model,
or explaining a slow session to a user, needs a measurement rather than a table.

Two properties keep this honest.

**Prefill and decode are reported separately, or not at all.** Prefill is compute-bound and
sets time-to-first-token; decode is memory-bandwidth-bound and sets the rest. A machine can
be fast at one and slow at the other, so a single "tokens per second" would hide exactly the
distinction that matters. And prefill throughput is only reported when the provider actually
timed its prefill phase — deriving it from time-to-first-token would silently fold queueing
and network latency into a number labelled *compute*.

**Nothing is written to disk.** A measurement is a value. `MeasurementStore` exists for
applications that want to keep one, and writes only where the caller points it — the
library's own default remains that it persists nothing anywhere.

A measurement is also only meaningful next to the machine and endpoint that produced it, so
every one carries a `MeasurementIdentity`: change the endpoint, the hardware, or the runtime
and you have a different measurement, not a newer one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .types.requests import ResolvedTarget

__all__ = [
    "BENCHMARK_OUTPUT_TOKENS",
    "BENCHMARK_PROMPT_TOKENS",
    "Measurement",
    "MeasurementIdentity",
    "MeasurementStore",
    "benchmark_prompt",
    "identity_for",
    "measurement_from",
    "normalize_endpoint",
]

BENCHMARK_PROMPT_TOKENS = 2_048
"""Default prompt size for a measurement.

Large enough that prefill is a real phase rather than rounding error, small enough that the
whole measurement costs a fraction of a cent on a hosted provider.
"""

BENCHMARK_OUTPUT_TOKENS = 128
"""Default output size. Decode throughput needs enough tokens to average over; a handful
would mostly measure the first one."""

_FILLER = (
    "A project status report lists milestones, owners, dates, risks, decisions, "
    "dependencies, budgets, and follow-up actions. "
)
"""Deterministic filler. Ordinary prose, so it tokenizes the way a real prompt does — a
repeated single token would measure a case no real workload produces."""

_MAX_STORE_ENTRIES = 64
_STORE_FORMAT_VERSION = 1


def benchmark_prompt(target_tokens: int = BENCHMARK_PROMPT_TOKENS) -> str:
    """Build a deterministic prompt of roughly ``target_tokens`` tokens.

    Deterministic on purpose: two runs a week apart must differ because the machine
    changed, not because the prompt did.

    Args:
        target_tokens: Approximate size, using the same bytes-per-token heuristic the
            estimator uses.

    Returns:
        The prompt, ending with an instruction that forces a bounded, prose-shaped answer.
    """
    instruction = (
        "\n\nSummarize the report above in exactly one paragraph of plain prose."
    )
    repeats = max(1, (target_tokens * 3) // len(_FILLER.encode("utf-8")))
    return (_FILLER * repeats) + instruction


def normalize_endpoint(endpoint: str | None) -> str | None:
    """Reduce an endpoint to the identity part, dropping anything credential-shaped.

    A measurement's identity must be safe to write to disk and compare across runs, so the
    userinfo, query, and fragment — every place an API key is smuggled into a URL — are
    removed rather than hashed. Host casing and trailing slashes are normalized so two
    spellings of one endpoint compare equal.
    """
    if endpoint is None or not endpoint.strip():
        return None
    parts = urlsplit(endpoint.strip())
    if not parts.scheme or not parts.hostname:
        return endpoint.strip().rstrip("/")
    host = parts.hostname.casefold()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme.casefold(), netloc, parts.path.rstrip("/"), "", ""))


@dataclass(frozen=True, slots=True)
class MeasurementIdentity:
    """What a measurement is a measurement *of*.

    Throughput is not a property of a model; it is a property of a model on an endpoint on
    a machine with a runtime. Change any of those and the old number is not stale, it is
    about something else — which is what `fingerprint` is for.

    Attributes:
        provider_id: The configured provider instance.
        model: The concrete model that served the request.
        endpoint: Normalized base URL, or ``None`` for a supervised in-process engine.
        host: A signature of the machine, for locally-executed targets only. ``None`` for
            hosted providers, where this machine's specs are irrelevant.
        runtime: The local runtime variant in use (``"cuda"``, ``"metal"``, …), when one
            applies.
    """

    provider_id: str
    model: str
    endpoint: str | None = None
    host: str | None = None
    runtime: str | None = None

    @property
    def fingerprint(self) -> str:
        """A stable hash of every field, for use as a store key."""
        canonical = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Measurement:
    """One target's measured throughput.

    Every rate is optional, and ``None`` means *not measured* rather than zero — the same
    tri-state rule cost and context windows follow.

    Attributes:
        identity: What was measured.
        input_tokens: Prompt tokens as the provider counted them.
        output_tokens: Generated tokens as the provider counted them.
        ttft_ms: Time to the first content delta, measured centrally.
        total_ms: Whole-request wall clock.
        prefill_tokens_per_s: Prompt tokens per second, **only** when the provider timed
            its own prefill phase. ``None`` otherwise, because deriving it from
            time-to-first-token would fold queueing and network latency into a figure
            labelled compute.
        decode_tokens_per_s: Generated tokens per second, from first token to completion.
        measured_at: ISO-8601 timestamp the caller stamped, when they stamped one.
    """

    identity: MeasurementIdentity
    input_tokens: int | None = None
    output_tokens: int | None = None
    ttft_ms: float | None = None
    total_ms: float = 0.0
    prefill_tokens_per_s: float | None = None
    decode_tokens_per_s: float | None = None
    measured_at: str | None = None

    @property
    def summary(self) -> str:
        """One line for a status area or a CLI."""
        parts = []
        if self.prefill_tokens_per_s is not None:
            parts.append(f"prefill {self.prefill_tokens_per_s:.0f} tok/s")
        if self.ttft_ms is not None:
            parts.append(f"ttft {self.ttft_ms:.0f} ms")
        if self.decode_tokens_per_s is not None:
            parts.append(f"decode {self.decode_tokens_per_s:.1f} tok/s")
        body = ", ".join(parts) or "nothing measurable"
        return f"{self.identity.provider_id}:{self.identity.model}: {body}"

    def to_json(self) -> dict[str, Any]:
        """A plain-data form suitable for storage or a machine-readable CLI."""
        payload = asdict(self)
        payload["identity"] = asdict(self.identity)
        return payload

    @classmethod
    def from_json(cls, payload: Any) -> Measurement | None:
        """Rebuild a measurement from stored data, or ``None`` if it is unreadable.

        Never raises: a stored measurement is a cache entry, and an unreadable one means
        *measure again*, not *fail*.
        """
        if not isinstance(payload, dict):
            return None
        identity = payload.get("identity")
        if not isinstance(identity, dict):
            return None
        try:
            fields = {k: v for k, v in payload.items() if k != "identity"}
            return cls(identity=MeasurementIdentity(**identity), **fields)
        except (TypeError, ValueError):
            return None


class MeasurementStore:
    """An optional, caller-owned file of past measurements.

    The library persists nothing on its own; an application that wants a "last measured"
    figure across restarts constructs one of these and points it somewhere. Entries are
    keyed by `MeasurementIdentity.fingerprint`, so a
    measurement taken against a different endpoint, machine, or runtime never masquerades
    as a fresher version of this one.

    Reads are total: a missing, truncated, or foreign file yields no entries rather than an
    exception, because a cache that can break a program is worse than no cache.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """Where this store reads and writes."""
        return self._path

    def get(self, identity: MeasurementIdentity) -> Measurement | None:
        """The stored measurement for exactly this identity, if any."""
        return self._load().get(identity.fingerprint)

    def all(self) -> tuple[Measurement, ...]:
        """Every stored measurement, oldest entry first."""
        return tuple(self._load().values())

    def record(self, measurement: Measurement) -> None:
        """Store a measurement, replacing any earlier one for the same identity.

        Writes atomically — a store half-written by an interrupted process would fail every
        subsequent read.
        """
        entries = self._load()
        entries.pop(measurement.identity.fingerprint, None)
        entries[measurement.identity.fingerprint] = measurement
        while len(entries) > _MAX_STORE_ENTRIES:
            entries.pop(next(iter(entries)))

        payload = {
            "format_version": _STORE_FORMAT_VERSION,
            "entries": {key: value.to_json() for key, value in entries.items()},
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self._path)

    def _load(self) -> dict[str, Measurement]:
        """Read the store, treating anything unreadable as empty."""
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if (
            not isinstance(payload, dict)
            or payload.get("format_version") != _STORE_FORMAT_VERSION
            or not isinstance(payload.get("entries"), dict)
        ):
            return {}
        entries: dict[str, Measurement] = {}
        for key, value in payload["entries"].items():
            measurement = Measurement.from_json(value)
            if measurement is not None and measurement.identity.fingerprint == key:
                entries[key] = measurement
        return entries


def measurement_from(
    identity: MeasurementIdentity,
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    ttft_ms: float | None,
    total_ms: float,
    decode_tokens_per_s: float | None,
    prefill_ms: float | None,
    measured_at: str | None = None,
) -> Measurement:
    """Assemble a measurement from one request's usage and timing.

    Prefill throughput is computed here and only here, and only from a provider-reported
    prefill duration — see the module docstring for why time-to-first-token is not an
    acceptable substitute.
    """
    prefill_rate: float | None = None
    if prefill_ms is not None and prefill_ms > 0 and input_tokens:
        prefill_rate = input_tokens / (prefill_ms / 1000.0)
    return Measurement(
        identity=identity,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        ttft_ms=ttft_ms,
        total_ms=total_ms,
        prefill_tokens_per_s=prefill_rate,
        decode_tokens_per_s=decode_tokens_per_s,
        measured_at=measured_at,
    )


def identity_for(
    target: ResolvedTarget,
    *,
    endpoint: str | None,
    host: str | None = None,
    runtime: str | None = None,
) -> MeasurementIdentity:
    """Build an identity for a resolved target, normalizing the endpoint."""
    return MeasurementIdentity(
        provider_id=target.provider_id,
        model=target.model,
        endpoint=normalize_endpoint(endpoint),
        host=host,
        runtime=runtime,
    )
