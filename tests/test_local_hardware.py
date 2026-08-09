"""Hardware detection, tuning, and tier recommendation.

Detection probes are mocked so the suite is deterministic across CI runners; the contract
under test is the *behavior* (never raise, degrade to warnings, invalidate on signature
change), not the specific numbers a given machine reports.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anyinfer.catalog.resolve import load_default_catalog
from anyinfer.local import hardware as hw
from anyinfer.local.hardware import Accelerator, HardwareProfile, detect
from anyinfer.local.recommend import recommend_alias
from anyinfer.local.tuning import (
    CONTEXT_LADDER,
    TuningInputs,
    kv_bytes_per_token,
    plan_server,
)

GIB = 1024**3


def _profile(**overrides: object) -> HardwareProfile:
    base: dict[str, object] = {
        "os_name": "linux",
        "arch": "x86_64",
        "total_ram_bytes": 32 * GIB,
        "physical_cores": 8,
        "logical_cores": 16,
    }
    base.update(overrides)
    return HardwareProfile(**base)  # type: ignore[arg-type]


def _cuda(vram_gib: int) -> tuple[Accelerator, ...]:
    return (Accelerator(kind="cuda", name="Test GPU", total_vram_bytes=vram_gib * GIB),)


# ---- detection -----------------------------------------------------------------------


def test_detection_never_raises_even_when_every_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A detector that can crash the caller is worse than no detector."""
    monkeypatch.setattr(hw, "_run", lambda command: None)
    monkeypatch.setattr(hw, "_detect_ram", lambda: (None, None, "ram probe failed"))
    monkeypatch.setattr(hw, "_detect_cpu", lambda: (None, None, None, "cpu probe failed"))

    profile = detect(use_cache=False)

    assert profile.total_ram_bytes is None
    assert profile.warnings, "failures must surface as warnings"
    assert any("ram probe failed" in w for w in profile.warnings)


def test_no_accelerator_is_a_warning_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stubbing `_run` alone does not describe an accelerator-less machine on every runner:
    # Metal is inferred from the CPU architecture, not from a probe, so an Apple Silicon
    # runner still reports one. Pin the architecture too, so the machine this test claims
    # to be running on is the same one everywhere.
    monkeypatch.setattr(hw, "_run", lambda command: None)
    monkeypatch.setattr(hw.platform, "machine", lambda: "x86_64")
    profile = detect(use_cache=False)

    assert profile.has_accelerator is False
    assert any("no accelerator" in w for w in profile.warnings)


def test_nvidia_output_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str]) -> str | None:
        if command[0] == "nvidia-smi":
            return "NVIDIA GeForce RTX 4090, 24564, 20000\n"
        return None

    monkeypatch.setattr(hw, "_run", fake_run)
    profile = detect(use_cache=False)

    accelerator = profile.primary_accelerator
    assert accelerator is not None
    assert accelerator.kind == "cuda"
    assert accelerator.name == "NVIDIA GeForce RTX 4090"
    assert accelerator.total_vram_bytes == 24564 * 1024 * 1024
    assert profile.has_accelerator is True


def test_multiple_gpus_are_all_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str]) -> str | None:
        if command[0] == "nvidia-smi":
            return "GPU A, 24564, 20000\nGPU B, 24564, 24000\n"
        return None

    monkeypatch.setattr(hw, "_run", fake_run)
    assert len(detect(use_cache=False).accelerators) == 2


def test_profile_survives_a_json_round_trip() -> None:
    profile = _profile(accelerators=_cuda(24), warnings=("something",))
    assert HardwareProfile.from_json(profile.to_json()) == profile


def test_cache_is_keyed_on_the_probe_signature(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Installing a driver changes the signature, which must invalidate the cache."""
    # This test asserts that caching happens, so it must own the bypass switch rather than
    # inherit whatever the surrounding environment set (CI exports it globally).
    monkeypatch.delenv(hw.CACHE_BYPASS_ENV, raising=False)
    cache_file = tmp_path / "hardware.json"
    monkeypatch.setattr(hw, "cache_path", lambda: cache_file)
    monkeypatch.setattr(hw, "probe_signature", lambda: "signature-a")
    monkeypatch.setattr(hw, "_run", lambda command: None)

    first = detect()
    assert cache_file.exists()

    calls: list[int] = []

    def counting_probe() -> HardwareProfile:
        calls.append(1)
        return first

    monkeypatch.setattr(hw, "_probe", counting_probe)

    detect()
    assert not calls, "a matching signature must be served from cache"

    monkeypatch.setattr(hw, "probe_signature", lambda: "signature-b")
    detect()
    assert calls, "a changed signature must force a re-probe"


def test_cache_bypass_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(hw, "cache_path", lambda: tmp_path / "hardware.json")
    monkeypatch.setattr(hw, "_run", lambda command: None)
    monkeypatch.setenv(hw.CACHE_BYPASS_ENV, "1")

    detect()
    assert not (tmp_path / "hardware.json").exists(), "bypass must not write the cache"


def test_corrupt_cache_is_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Asserts the cache is rewritten, so the bypass must be off regardless of the ambient
    # environment.
    monkeypatch.delenv(hw.CACHE_BYPASS_ENV, raising=False)
    cache_file = tmp_path / "hardware.json"
    cache_file.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(hw, "cache_path", lambda: cache_file)
    monkeypatch.setattr(hw, "_run", lambda command: None)

    profile = detect()
    assert profile.os_name, "a corrupt cache must fall back to probing"
    assert json.loads(cache_file.read_text(encoding="utf-8")), "and be rewritten"


def test_unwritable_cache_directory_does_not_break_detection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A read-only or otherwise unwritable cache location degrades to probe-only."""
    # The bypass must be off (CI exports it globally), or the write path is never reached.
    monkeypatch.delenv(hw.CACHE_BYPASS_ENV, raising=False)
    # A file where a directory is needed makes every mkdir under it fail with OSError,
    # which is exactly what a read-only cache root produces.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(hw, "cache_path", lambda: blocker / "sub" / "hardware.json")
    monkeypatch.setattr(hw, "_run", lambda command: None)

    profile = detect()

    assert profile.os_name, "detection must survive an unwritable cache directory"
    assert not (blocker / "sub" / "hardware.json").exists()


# ---- tuning --------------------------------------------------------------------------


def test_gpu_offload_when_an_accelerator_is_present() -> None:
    plan = plan_server(_profile(accelerators=_cuda(24)), TuningInputs(parameter_size="7B"))
    assert plan.gpu_layers == 999
    assert plan.flash_attention is True


def test_cpu_only_plan() -> None:
    plan = plan_server(_profile(), TuningInputs(parameter_size="7B"))
    assert plan.gpu_layers == 0
    assert plan.flash_attention is False
    assert plan.threads == 7, "leave a core for the rest of the system"


def test_larger_vram_earns_a_larger_context() -> None:
    small = plan_server(
        _profile(accelerators=_cuda(8)),
        TuningInputs(artifact_size_bytes=4 * GIB, parameter_size="7B"),
    )
    large = plan_server(
        _profile(accelerators=_cuda(48)),
        TuningInputs(artifact_size_bytes=4 * GIB, parameter_size="7B"),
    )
    assert large.context_size >= small.context_size


def test_context_never_exceeds_the_model_maximum() -> None:
    plan = plan_server(
        _profile(accelerators=_cuda(48)),
        TuningInputs(parameter_size="1.5B", max_context=8192),
    )
    assert plan.context_size <= 8192


def test_explicit_context_request_is_honored() -> None:
    plan = plan_server(
        _profile(accelerators=_cuda(24)),
        TuningInputs(parameter_size="7B", requested_context=4096),
    )
    assert plan.context_size == 4096


def test_aggressive_posture_reserves_for_concurrency() -> None:
    """KV cache scales with slots; budgeting one slot then serving two exhausts VRAM."""
    plan = plan_server(
        _profile(accelerators=_cuda(24)),
        TuningInputs(artifact_size_bytes=4 * GIB, parameter_size="7B"),
        posture="aggressive",
    )
    assert plan.parallel == 2
    assert plan.context_per_slot == plan.context_size // 2
    per_token = kv_bytes_per_token("7B", plan.cache_type_k)
    assert plan.estimated_kv_bytes == plan.context_size * per_token * 2


def test_postures_are_ordered_by_commitment() -> None:
    inputs = TuningInputs(artifact_size_bytes=4 * GIB, parameter_size="7B")
    profile = _profile(accelerators=_cuda(16))
    conservative = plan_server(profile, inputs, posture="conservative")
    balanced = plan_server(profile, inputs, posture="balanced")
    assert balanced.context_size >= conservative.context_size


def test_q8_cache_halves_the_per_token_cost() -> None:
    assert kv_bytes_per_token("7B", "q8_0") == kv_bytes_per_token("7B", "f16") // 2


def test_unknown_memory_falls_back_to_the_smallest_context() -> None:
    profile = HardwareProfile(os_name="linux", arch="x86_64", total_ram_bytes=None)
    plan = plan_server(profile, TuningInputs(parameter_size="7B"))
    assert plan.context_size == CONTEXT_LADDER[0]
    assert any("unknown" in r for r in plan.rationale)


def test_weights_are_subtracted_from_the_budget() -> None:
    """A model must fit alongside its KV cache, not instead of it."""
    profile = _profile(accelerators=_cuda(16))
    light = plan_server(profile, TuningInputs(artifact_size_bytes=1 * GIB,
                                              parameter_size="7B"))
    heavy = plan_server(profile, TuningInputs(artifact_size_bytes=12 * GIB,
                                              parameter_size="7B"))
    assert heavy.context_size <= light.context_size


def test_unified_memory_budgets_against_system_ram() -> None:
    profile = _profile(
        total_ram_bytes=32 * GIB,
        accelerators=(Accelerator(kind="metal", name="M3", unified_memory=True),),
    )
    plan = plan_server(profile, TuningInputs(artifact_size_bytes=4 * GIB,
                                             parameter_size="7B"))
    assert plan.gpu_layers == 999
    assert any("unified memory" in r for r in plan.rationale)


def test_server_arguments_always_enable_jinja() -> None:
    """Without --jinja, llama-server cannot apply chat templates and tools silently fail."""
    plan = plan_server(_profile(accelerators=_cuda(24)), TuningInputs(parameter_size="7B"))
    args = plan.server_arguments("/models/x.gguf", host="127.0.0.1", port=9999)

    assert "--jinja" in args
    assert args[args.index("--model") + 1] == "/models/x.gguf"
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert args[args.index("--port") + 1] == "9999"
    assert args[args.index("--ctx-size") + 1] == str(plan.context_size)


def test_plan_reports_its_memory_estimate() -> None:
    """Admission control depends on this number being present."""
    plan = plan_server(
        _profile(accelerators=_cuda(24)),
        TuningInputs(artifact_size_bytes=4 * GIB, parameter_size="7B"),
    )
    assert plan.estimated_kv_bytes > 0
    assert plan.estimated_total_bytes >= plan.estimated_kv_bytes + 4 * GIB - 1


# ---- recommendation ------------------------------------------------------------------


def test_large_gpu_earns_the_large_tier() -> None:
    result = recommend_alias(_profile(accelerators=_cuda(24)), load_default_catalog())
    assert result.alias == "large"
    assert result.confident is True


def test_modest_machine_gets_a_modest_tier() -> None:
    profile = _profile(total_ram_bytes=6 * GIB, accelerators=())
    result = recommend_alias(profile, load_default_catalog())
    assert result.alias == "small"


def test_unknown_memory_is_not_confident() -> None:
    profile = HardwareProfile(os_name="linux", arch="x86_64", total_ram_bytes=None)
    result = recommend_alias(profile, load_default_catalog())
    assert result.confident is False
    assert result.alias == "small", "unknowns must never inflate the recommendation"


def test_recommendation_explains_itself() -> None:
    result = recommend_alias(_profile(accelerators=_cuda(24)), load_default_catalog())
    assert result.reason
    assert "large" in result.reason
