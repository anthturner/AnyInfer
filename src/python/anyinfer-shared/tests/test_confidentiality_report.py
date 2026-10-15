from __future__ import annotations

from anyinfer_shared import ConfidentialityReport


def test_defaults_are_all_unevaluated_not_false() -> None:
    report = ConfidentialityReport()
    assert report.template_sealed is None
    assert report.relay_used is None
    assert report.execution_attested is None
    assert report.model_verified is None
    assert report.notes == ()


def test_to_dict_from_dict_round_trip() -> None:
    report = ConfidentialityReport(
        template_sealed=True,
        relay_used=False,
        execution_attested=True,
        cpu_tee="sev-snp",
        model_verified=True,
        notes=("gpu offload not in play",),
    )
    restored = ConfidentialityReport.from_dict(report.to_dict())
    assert restored == report


def test_from_dict_ignores_unknown_keys_forward_safe() -> None:
    restored = ConfidentialityReport.from_dict(
        {"template_sealed": True, "future_field_from_a_later_release": "x"}
    )
    assert restored.template_sealed is True


class _FakeStatus:
    """The structural shape `from_status` reads.

    A stand-in rather than the real `ConfidentialExecutionStatus`, so this package's
    tests keep working without `anyinfer` installed — the same one-way dependency the
    package itself maintains.
    """

    def __init__(
        self,
        *,
        end_to_end: bool,
        cpu_tee: str | None = None,
        model_verified: bool | None = None,
        detail: str = "",
    ) -> None:
        self.end_to_end = end_to_end
        self.cpu_tee = cpu_tee
        self.model_verified = model_verified
        self.detail = detail


def test_from_status_composes_core_tiers_with_caller_supplied_ones() -> None:
    report = ConfidentialityReport.from_status(
        _FakeStatus(
            end_to_end=True,
            cpu_tee="sev-snp",
            model_verified=True,
            detail="CPU-only execution inside an attested SEV-SNP guest",
        ),
        template_sealed=True,
        relay_used=False,
    )

    assert report.execution_attested is True
    assert report.cpu_tee == "sev-snp"
    assert report.model_verified is True
    assert report.template_sealed is True
    assert report.relay_used is False
    assert report.relay_self_hosted is None, "not supplied means not evaluated"
    assert "SEV-SNP" in report.notes[0]


def test_from_status_leaves_unsupplied_tiers_unevaluated() -> None:
    """A caller using only Tier 3 must not fabricate a false negative for Tiers 1-2."""
    report = ConfidentialityReport.from_status(_FakeStatus(end_to_end=False))

    assert report.execution_attested is False
    assert report.template_sealed is None
    assert report.relay_used is None


def test_from_status_carries_the_reason_a_tier_did_not_hold() -> None:
    """A bare False loses the why; notes is where it survives."""
    report = ConfidentialityReport.from_status(
        _FakeStatus(end_to_end=False, detail="no attestable CPU TEE detected")
    )
    assert report.notes == ("no attestable CPU TEE detected",)

    quiet = ConfidentialityReport.from_status(
        _FakeStatus(end_to_end=False, detail="ignored"), include_detail=False
    )
    assert quiet.notes == ()


def test_from_status_drops_an_unrecognized_tee_family() -> None:
    """Rather than widening the declared type with whatever the runtime reported."""
    report = ConfidentialityReport.from_status(
        _FakeStatus(end_to_end=True, cpu_tee="some-future-tee")
    )
    assert report.cpu_tee is None
    assert report.execution_attested is True


def test_from_status_output_round_trips() -> None:
    report = ConfidentialityReport.from_status(
        _FakeStatus(end_to_end=True, cpu_tee="tdx", detail="d"), template_sealed=True
    )
    assert ConfidentialityReport.from_dict(report.to_dict()) == report
