"""Types shared across AnyInfer's optional confidentiality packages.

`anyinfer` core never imports this package, and this package never imports
`anyinfer-confidential` — the dependency direction only ever runs the other way, from an
application composing both. It exists solely because a single call can combine
confidentiality facts from two independent places: `anyinfer-confidential` (Tier 1
`SealedTemplate` decryption, Tier 2 `AnyInfer Relay` usage) and `anyinfer` core (Tier 3
attested local execution, Tier 4 model-weight verification, both in
`anyinfer.local.attestation`). Neither package should have to import the other's
internals just to describe "what confidentiality actually happened for this call" — so
the composite lives here, in a package both can depend on.

See DESIGN.md §30 for the tier definitions this type reports against,
and the published Confidentiality Tiers doc for the guarantee each field maps to.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

__all__ = ["ConfidentialityReport"]

if TYPE_CHECKING:

    class _ExecutionStatus(Protocol):
        """The shape `from_status` reads.

        Structural rather than an import: `anyinfer.local.attestation`'s
        `ConfidentialExecutionStatus` satisfies it, and this package still never imports
        `anyinfer`. The dependency direction stays one-way, which is the whole reason
        this package exists.
        """

        @property
        def end_to_end(self) -> bool: ...

        @property
        def cpu_tee(self) -> str | None: ...

        @property
        def model_verified(self) -> bool | None: ...

        @property
        def detail(self) -> str: ...

CpuTeeKind = Literal["sev-snp", "tdx", "nitro", "sgx"]


@dataclass(frozen=True, slots=True)
class ConfidentialityReport:
    """A composite record of every confidentiality guarantee that applied to one call.

    Every field is optional: a caller using only one tier's package leaves the other
    tier's fields `None` rather than fabricating a false negative. `None` always means
    "not evaluated," never "not confidential" — a caller distinguishing "we didn't check"
    from "we checked and it failed" reads the difference directly off which fields are
    populated versus `False`.

    Attributes:
        template_sealed: Tier 1 — the prompt was assembled from a `SealedTemplate` whose
            plaintext was decrypted only immediately before rendering, never persisted.
        relay_used: Tier 2 — request assembly happened inside an `AnyInfer Relay`
            deployment rather than in this process.
        relay_self_hosted: Whether the Relay instance was self-hosted by the caller's own
            organization, when `relay_used` is `True`; `None` when `relay_used` is not
            `True` or the deployment mode was not reported.
        execution_attested: Tier 3 — mirrors
            `anyinfer.local.attestation.ConfidentialExecutionStatus.end_to_end` for the
            local backend that ran this call.
        cpu_tee: The detected CPU TEE family backing `execution_attested`, when known.
        model_verified: Tier 4 — the executing model's weights were checked against a
            vendor-signed manifest inside the same attested boundary `execution_attested`
            reports on.
        notes: Human-readable caveats — e.g. why a field could not be evaluated —
            attributable to a specific tier without inventing new typed fields for every
            possible caveat.
    """

    template_sealed: bool | None = None
    relay_used: bool | None = None
    relay_self_hosted: bool | None = None
    execution_attested: bool | None = None
    cpu_tee: CpuTeeKind | None = None
    model_verified: bool | None = None
    notes: tuple[str, ...] = ()

    @classmethod
    def from_status(
        cls,
        status: _ExecutionStatus,
        *,
        template_sealed: bool | None = None,
        relay_used: bool | None = None,
        relay_self_hosted: bool | None = None,
        include_detail: bool = True,
    ) -> ConfidentialityReport:
        """Compose a report from a core attestation status plus the Tier 1-2 facts.

        The one demonstrated producer of this type. Tier 3 and Tier 4 come off `status`
        — the object `anyinfer.local.attestation.confidential_execution_status()` returns
        — while Tiers 1 and 2 are facts only the calling application knows, because
        whether a prompt came from a sealed template or through a Relay is not something
        the local runtime can observe.

        `status` is taken structurally, so this package still never imports `anyinfer`.

        Args:
            status: A `ConfidentialExecutionStatus` (or anything with the same shape).
            template_sealed: Tier 1 — did this call render from a `SealedTemplate`?
                Leave `None` if Tier 1 was not evaluated; `False` means it was and did
                not apply.
            relay_used: Tier 2 — was assembly done by an `AnyInfer Relay`?
            relay_self_hosted: Whether that Relay was the caller's own deployment.
            include_detail: Carry `status.detail` into `notes`, which is where the
                *reason* a tier did not hold survives — a bare `False` loses it.

        Returns:
            A populated report. Tier 3/4 fields always reflect `status`; Tier 1/2 fields
            reflect exactly what the caller passed, `None` included.
        """
        cpu_tee = status.cpu_tee
        return cls(
            template_sealed=template_sealed,
            relay_used=relay_used,
            relay_self_hosted=relay_self_hosted,
            execution_attested=status.end_to_end,
            # Narrowed only when it is one of the families this type names; an
            # unrecognized value is dropped rather than widening the declared type.
            cpu_tee=cpu_tee if cpu_tee in ("sev-snp", "tdx", "nitro", "sgx") else None,  # type: ignore[arg-type]
            model_verified=status.model_verified,
            notes=(status.detail,) if include_detail and status.detail else (),
        )

    def to_dict(self) -> dict[str, Any]:
        """A plain JSON-safe mapping, for logging or a compliance-mapping artifact."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfidentialityReport:
        """Round-trip counterpart to `to_dict`; unknown keys are ignored (forward-safe)."""
        known = set(cls.__dataclass_fields__)
        filtered = {k: v for k, v in data.items() if k in known}
        if "notes" in filtered:
            filtered["notes"] = tuple(filtered["notes"])
        return cls(**filtered)
