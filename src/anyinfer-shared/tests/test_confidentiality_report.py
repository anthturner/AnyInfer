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
