"""An in-process rollup of what a client has spent, and a ceiling it may not cross.

Cost is already tri-state and `Decimal` throughout (`anyinfer.capabilities.pricing`).
Accumulating it correctly is the part that is easy to get wrong: a total that silently omits
the calls it could not price reads as authoritative and is not, and coercing an unknown to
zero is the accounting bug that module exists to prevent. So the arithmetic ships once,
here, rather than in every application that wants a running figure.

**This is not a control plane.** A ledger observes the client it was subscribed to. A policy
is a ceiling the same caller set on the same object, checked before dispatch beside the
context gate. Nothing is shared between processes, nothing is authorized, and no other
consumer of the same API key is visible. Organization-wide quotas remain a deployment's job.

Nothing here writes to disk. An application that wants durability constructs a `SpendStore`
and points it somewhere, the way `anyinfer.benchmark.MeasurementStore` already works.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..events.telemetry import RequestCompleted, RequestFailed, RequestStarted, TelemetryEvent
from ..types.requests import ResolvedTarget
from ..types.results import Usage

__all__ = [
    "STORE_FORMAT_VERSION",
    "SpendLedger",
    "SpendStore",
    "SpendTotals",
]

STORE_FORMAT_VERSION = 1
"""Format version of a persisted spend store."""

_MAX_STORE_ENTRIES = 512
"""Bound on stored buckets, so a long-lived store cannot grow without limit."""


@dataclass(frozen=True, slots=True)
class SpendTotals:
    """What was spent, and what could not be priced.

    ``unknown_requests`` is the honest counterpart to ``cost``. A provider whose pricing is
    absent or untrusted produces no cost at all; never a zero, so a total that reported
    only ``cost`` would quietly understate spend by however many calls it could not price.
    Both numbers travel together for that reason, and every rendering of one should render
    the other.

    Attributes:
        cost: Summed cost of the requests that could be priced.
        currency: Currency the costs are in. A ledger refuses to mix currencies rather than
            converting, because a conversion needs a rate source this library must not have.
        requests: Completed requests observed.
        unknown_requests: Completed requests whose cost could not be known.
        input_tokens: Prompt tokens reported across those requests.
        output_tokens: Generated tokens reported across those requests.
        cache_read_tokens: Prompt tokens the providers reported serving from cache.
    """

    cost: Decimal = Decimal(0)
    currency: str = "USD"
    requests: int = 0
    unknown_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def complete(self) -> bool:
        """Whether every observed request could be priced."""
        return self.unknown_requests == 0

    def plus(self, usage: Usage) -> SpendTotals:
        """Fold one request's usage into these totals."""
        cost = usage.cost_usd
        return SpendTotals(
            cost=self.cost + (cost if cost is not None else Decimal(0)),
            currency=self.currency,
            requests=self.requests + 1,
            unknown_requests=self.unknown_requests + (1 if cost is None else 0),
            input_tokens=self.input_tokens + (usage.input_tokens or 0),
            output_tokens=self.output_tokens + (usage.output_tokens or 0),
            cache_read_tokens=self.cache_read_tokens + (usage.cache_read_tokens or 0),
        )

    def to_json(self) -> dict[str, Any]:
        """Serialize for a `SpendStore`."""
        return {
            "cost": str(self.cost),
            "currency": self.currency,
            "requests": self.requests,
            "unknown_requests": self.unknown_requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SpendTotals | None:
        """Deserialize, returning ``None`` for anything unreadable."""
        try:
            return cls(
                cost=Decimal(str(data["cost"])),
                currency=str(data.get("currency", "USD")),
                requests=int(data.get("requests", 0)),
                unknown_requests=int(data.get("unknown_requests", 0)),
                input_tokens=int(data.get("input_tokens", 0)),
                output_tokens=int(data.get("output_tokens", 0)),
                cache_read_tokens=int(data.get("cache_read_tokens", 0)),
            )
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return None


class SpendLedger:
    """A thread-safe rollup of one client's observed spend.

    Subscribe it like any other observer::

        ledger = SpendLedger()
        client = ai.Client(providers, observers=[ledger])
        ...
        print(ledger.totals().cost)

    Two clients that should share a total are given the *same* ledger. There is deliberately
    no process-wide instance: a global would make a total depend on import order, and would
    silently merge the accounting of two libraries that happen to share a process.

    Only completed requests are counted. A failed attempt that a retry replaced is not
    separately visible in the event stream, so its tokens are not in these totals — the
    figure is "what the successful requests cost", not "everything the provider might
    bill". Where that distinction matters, compare against the provider's own invoice.
    """

    def __init__(self, currency: str = "USD") -> None:
        self._lock = threading.Lock()
        self._currency = currency
        self._overall = SpendTotals(currency=currency)
        self._by_target: dict[str, SpendTotals] = {}
        self._by_label: dict[str, dict[str, SpendTotals]] = {}
        self._metadata: dict[str, Mapping[str, str]] = {}
        self._reservations: dict[str, Decimal] = {}

    # ---- observer ---------------------------------------------------------------------

    def on_event(self, event: TelemetryEvent) -> None:
        """Absorb one telemetry event.

        Fast and non-blocking, as the observer contract requires: this is arithmetic under
        a lock, with no I/O.
        """
        if isinstance(event, RequestStarted):
            if event.metadata:
                with self._lock:
                    self._metadata[event.request_id] = dict(event.metadata)
            return
        if isinstance(event, RequestFailed):
            with self._lock:
                self._metadata.pop(event.request_id, None)
                self._reservations.pop(event.request_id, None)
            return
        if isinstance(event, RequestCompleted):
            self.record(event.target, event.usage, request_id=event.request_id)

    # ---- recording --------------------------------------------------------------------

    def record(
        self,
        target: ResolvedTarget,
        usage: Usage,
        *,
        request_id: str | None = None,
    ) -> None:
        """Fold one completed request into the totals.

        Args:
            target: What served the request.
            usage: Its reported usage, with cost already computed by the core.
            request_id: Correlation id, used to attribute the request to the labels its
                caller supplied.

        Raises:
            ValueError: If the usage carries a cost in a different currency than this
                ledger's. Converting would require a rate source, and a converted figure
                would have no provenance.
        """
        with self._lock:
            metadata = self._metadata.pop(request_id, {}) if request_id else {}
            if request_id:
                self._reservations.pop(request_id, None)
            self._overall = self._overall.plus(usage)

            key = str(target)
            self._by_target[key] = self._by_target.get(
                key, SpendTotals(currency=self._currency)
            ).plus(usage)

            for label, value in metadata.items():
                bucket = self._by_label.setdefault(label, {})
                bucket[value] = bucket.get(value, SpendTotals(currency=self._currency)).plus(usage)

    def reserve(
        self, request_id: str, estimate: Decimal, ceiling: Decimal | None
    ) -> tuple[bool, Decimal, Decimal]:
        """Atomically reserve a preflight estimate against a cumulative ceiling.

        Re-reserving the same request replaces its prior estimate, which lets fallback
        targets update the bound without double-counting one caller request.
        """
        with self._lock:
            previous = self._reservations.get(request_id, Decimal(0))
            reserved = sum(self._reservations.values(), Decimal(0)) - previous
            spent = self._overall.cost
            if ceiling is not None and spent + reserved + estimate > ceiling:
                return False, spent, reserved
            self._reservations[request_id] = estimate
            return True, spent, reserved

    def release(self, request_id: str) -> None:
        """Release a reservation that will not be replaced by a completion event."""
        with self._lock:
            self._reservations.pop(request_id, None)

    def reserved(self) -> Decimal:
        """Total preflight spend currently reserved by in-flight requests."""
        with self._lock:
            return sum(self._reservations.values(), Decimal(0))

    # ---- reading ----------------------------------------------------------------------

    def totals(self) -> SpendTotals:
        """Everything observed so far."""
        with self._lock:
            return self._overall

    def by_target(self) -> Mapping[str, SpendTotals]:
        """Totals per ``provider:model``, in first-seen order."""
        with self._lock:
            return dict(self._by_target)

    def by_label(self, key: str) -> Mapping[str, SpendTotals]:
        """Totals per value of one caller-supplied metadata label.

        The library never interprets these labels — a tenant id, a feature name, a job id
        are all the application's vocabulary, carried through untouched.
        """
        with self._lock:
            return dict(self._by_label.get(key, {}))

    def reset(self) -> None:
        """Forget everything recorded so far."""
        with self._lock:
            self._overall = SpendTotals(currency=self._currency)
            self._by_target.clear()
            self._by_label.clear()
            self._metadata.clear()
            self._reservations.clear()


class SpendStore:
    """An optional, caller-owned file of accumulated spend.

    The library persists nothing on its own. An application that wants a total that
    survives a restart constructs one of these and points it somewhere — the same contract
    `anyinfer.benchmark.MeasurementStore` uses, including its most important property:
    reads are total. A missing, truncated, or foreign file yields nothing rather than
    raising, because a cache that can break a program is worse than no cache.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """Where this store reads and writes."""
        return self._path

    def load(self) -> Mapping[str, SpendTotals]:
        """Every stored bucket, keyed by name. Unreadable content yields nothing."""
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if (
            not isinstance(payload, dict)
            or payload.get("format_version") != STORE_FORMAT_VERSION
            or not isinstance(payload.get("buckets"), dict)
        ):
            return {}
        entries: dict[str, SpendTotals] = {}
        for key, value in payload["buckets"].items():
            if not isinstance(value, dict):
                continue
            totals = SpendTotals.from_json(value)
            if totals is not None:
                entries[str(key)] = totals
        return entries

    def accumulate(self, ledger: SpendLedger, *, bucket: str = "total") -> None:
        """Add a ledger's current totals to the stored bucket, atomically.

        Args:
            ledger: The ledger whose totals to fold in.
            bucket: Which stored bucket to add to — a process name, a job id, or the
                default single bucket.

        Raises:
            ValueError: If the ledger's currency differs from the stored bucket's.
        """
        entries = dict(self.load())
        incoming = ledger.totals()
        existing = entries.get(bucket)
        if existing is not None:
            if existing.currency != incoming.currency:
                raise ValueError(
                    f"stored bucket {bucket!r} is in {existing.currency}, "
                    f"but this ledger is in {incoming.currency}"
                )
            incoming = replace(
                incoming,
                cost=existing.cost + incoming.cost,
                requests=existing.requests + incoming.requests,
                unknown_requests=existing.unknown_requests + incoming.unknown_requests,
                input_tokens=existing.input_tokens + incoming.input_tokens,
                output_tokens=existing.output_tokens + incoming.output_tokens,
                cache_read_tokens=existing.cache_read_tokens + incoming.cache_read_tokens,
            )
        entries[bucket] = incoming

        while len(entries) > _MAX_STORE_ENTRIES:
            entries.pop(next(iter(entries)))

        payload = {
            "format_version": STORE_FORMAT_VERSION,
            "buckets": {key: value.to_json() for key, value in entries.items()},
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic: a store half-written by an interrupted process would fail every read.
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self._path)
