"""The logical model catalog: schema, fit classification, and variant selection.

Everything here is offline. The bundled catalog is data, hardware profiles are synthetic,
and the point under test is the *judgement*, which rung is chosen, which fit level is
reported, and whether the stated reason actually explains it.
"""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.catalog import BEST_AT, Catalog, load_default_catalog
from anyinfer.local.backends import Backend
from anyinfer.local.fit import classify_fit, memory_budget, sort_by_fit
from anyinfer.local.hardware import Accelerator, HardwareProfile
from anyinfer.local.variants import VariantPrefs, evaluate_variants, select_variant

GIB = 1024**3


def _profile(
    *,
    ram: int | None = 32 * GIB,
    vram: int | None = None,
    kind: str = "cuda",
    capability: str | None = "8.9",
    unified: bool = False,
    count: int = 1,
    name: str = "Test GPU",
) -> HardwareProfile:
    """Build a synthetic profile; ``vram=None`` means CPU-only."""
    accelerators: tuple[Accelerator, ...] = ()
    if vram is not None:
        accelerators = tuple(
            Accelerator(
                kind=kind,  # type: ignore[arg-type]
                name=name,
                total_vram_bytes=None if unified else vram,
                unified_memory=unified,
                compute_capability=capability,
                driver_version="580.00",
            )
            for _ in range(count)
        )
    return HardwareProfile(
        os_name="linux", arch="x86_64", total_ram_bytes=ram, accelerators=accelerators
    )


class _Entry:
    """A minimal catalog-entry stand-in for the fit engine's structural protocol."""

    def __init__(self, entry_id: str, ram: int | None, vram: int | None, params: str = "7B"):
        self.id = entry_id
        self.est_ram_bytes = ram
        self.est_vram_bytes = vram
        self.parameter_size = params


# ---- schema ---------------------------------------------------------------------------


def test_bundled_catalog_ships_a_browsable_model_table() -> None:
    catalog = load_default_catalog()
    assert len(catalog.models) >= 35
    for entry in catalog.models.values():
        assert entry.variants, f"{entry.id} has no variants"
        assert entry.best_at, f"{entry.id} has no categories"
        assert set(entry.best_at) <= BEST_AT
        assert entry.last_verified
        assert entry.source.startswith("https://")


def test_every_gguf_variant_is_pinned_to_a_commit_and_a_hash() -> None:
    for entry in load_default_catalog().models.values():
        for variant in entry.variants:
            assert variant.is_pinned, f"{variant.id} is not fully pinned"
            assert len(variant.source.revision or "") == 40


def test_headline_artifact_matches_the_advertised_quantization() -> None:
    """A user reading a Q4_K_M size must not be handed a Q8_0 download."""
    entry = load_default_catalog().model("qwen2.5-7b-instruct")
    artifact_id = entry.gguf_artifact_id
    assert artifact_id is not None
    assert entry.variant(artifact_id).quantization == entry.quantization


def test_unknown_best_at_category_is_rejected_at_parse_time() -> None:
    with pytest.raises(ai.ConfigError, match="unknown best_at category"):
        Catalog.from_mapping({"format_version": 1, "models": [{"id": "x", "best_at": ["vibes"]}]})


def test_with_alias_target_bridges_a_pick_into_the_tier_ladder() -> None:
    catalog = load_default_catalog()
    merged = catalog.with_alias_target("medium", "llama-cpp", "qwen2.5-14b-instruct")
    target = merged.alias("medium").targets["llama-cpp"]
    assert target.gguf == catalog.model("qwen2.5-14b-instruct").gguf_artifact_id
    assert target.gguf in merged.artifacts
    # The original is untouched: overlays produce new catalogs, they do not mutate.
    assert catalog.alias("medium").targets["llama-cpp"].gguf != target.gguf


def test_with_alias_target_refuses_a_channel_the_model_lacks() -> None:
    """A model published only as a GGUF must not be pointed at from an Ollama target."""
    catalog = load_default_catalog().overlay(
        Catalog.from_mapping(
            {
                "format_version": 1,
                "models": [
                    {
                        "id": "gguf-only",
                        "license": "mit",
                        "best_at": ["general-chat"],
                        "variants": [
                            {
                                "id": "gguf-only-q4",
                                "quantization": "Q4_K_M",
                                "source": {"resolver": "url", "urls": ["https://x/m.gguf"]},
                            }
                        ],
                    }
                ],
            }
        )
    )
    with pytest.raises(ai.ConfigError, match="no Ollama tag"):
        catalog.with_alias_target("medium", "ollama", "gguf-only")


def test_models_for_filters_by_channel_and_category() -> None:
    catalog = load_default_catalog()
    coding = catalog.models_for("llama-cpp", best_at="coding")
    assert coding
    assert all("coding" in e.best_at for e in coding)
    assert all("llama-cpp" in e.channels for e in coding)


# ---- fit classification ------------------------------------------------------------------


def test_a_model_that_fits_vram_reports_gpu_with_a_reason() -> None:
    fit = classify_fit(_Entry("small", ram=8 * GIB, vram=6 * GIB), _profile(vram=24 * GIB))
    assert fit.level == "gpu"
    assert fit.runnable
    assert any("VRAM" in reason for reason in fit.reasons)


def test_a_model_too_big_for_vram_falls_back_to_the_cpu_path() -> None:
    fit = classify_fit(
        _Entry("mid", ram=12 * GIB, vram=12 * GIB, params="14B"),
        _profile(ram=64 * GIB, vram=8 * GIB),
    )
    assert fit.level == "cpu"
    assert any("slowly" in reason for reason in fit.reasons)


def test_a_70b_model_on_an_8gb_cpu_only_machine_reports_no() -> None:
    fit = classify_fit(
        _Entry("huge", ram=48 * GIB, vram=48 * GIB, params="70B"), _profile(ram=8 * GIB)
    )
    assert fit.level == "no"
    assert not fit.runnable
    assert any("smaller" in reason for reason in fit.reasons)


def test_no_profile_means_unknown_rather_than_a_guess() -> None:
    fit = classify_fit(_Entry("x", ram=4 * GIB, vram=4 * GIB), None)
    assert fit.level == "unknown"
    assert fit.reasons


def test_an_unmeasurable_machine_reports_unknown() -> None:
    blank = HardwareProfile(os_name="linux", arch="x86_64")
    assert classify_fit(_Entry("x", ram=4 * GIB, vram=4 * GIB), blank).level == "unknown"


def test_unified_memory_is_budgeted_once_not_twice() -> None:
    profile = _profile(ram=64 * GIB, vram=0, kind="metal", unified=True, capability=None)
    vram_budget, ram_budget = memory_budget(profile)
    assert vram_budget is None
    assert ram_budget is not None
    fit = classify_fit(_Entry("m", ram=20 * GIB, vram=20 * GIB, params="27B"), profile)
    assert fit.level == "gpu"
    assert any("unified memory" in reason for reason in fit.reasons)


def test_an_nvidia_machine_without_the_cuda_runtime_gets_an_upgrade_hint() -> None:
    from pathlib import Path

    vulkan = Backend(kind="vulkan", binary=Path("llama-server"), rank=20)
    fit = classify_fit(
        _Entry("x", ram=8 * GIB, vram=6 * GIB), _profile(vram=24 * GIB), backend=vulkan
    )
    assert any("CUDA runtime" in reason for reason in fit.reasons)


def test_non_nvidia_hardware_never_gets_the_cuda_hint() -> None:
    from pathlib import Path

    vulkan = Backend(kind="vulkan", binary=Path("llama-server"), rank=20)
    fit = classify_fit(
        _Entry("x", ram=8 * GIB, vram=6 * GIB),
        _profile(vram=24 * GIB, kind="rocm", capability=None),
        backend=vulkan,
    )
    assert not any("CUDA" in reason for reason in fit.reasons)


def test_sorting_puts_the_best_fit_first_and_is_deterministic() -> None:
    profile = _profile(vram=24 * GIB)
    pairs = [
        (entry, classify_fit(entry, profile))
        for entry in (
            _Entry("z-huge", ram=200 * GIB, vram=200 * GIB, params="70B"),
            _Entry("a-small", ram=4 * GIB, vram=3 * GIB, params="3B"),
            _Entry("b-small", ram=4 * GIB, vram=3 * GIB, params="3B"),
        )
    ]
    ordered = sort_by_fit(pairs)
    assert ordered[0][0].id in ("a-small", "b-small")
    assert ordered[-1][0].id == "z-huge"
    assert sort_by_fit(pairs) == ordered


# ---- variant selection --------------------------------------------------------------------


class _Variant:
    """A minimal variant stand-in for the selection protocol."""

    def __init__(
        self,
        variant_id: str,
        quantization: str,
        rank: int,
        size: int,
        *,
        engine: str = "llama.cpp",
        capability: str | None = None,
    ) -> None:
        self.id = variant_id
        self.quantization = quantization
        self.quality_rank = rank
        self.engine = engine
        self.est_file_bytes = size
        self.est_ram_bytes = size + GIB
        self.est_vram_bytes = size + GIB
        self.min_compute_capability = capability


def _ladder() -> list[_Variant]:
    return [
        _Variant("m-q8", "Q8_0", 80, 8 * GIB),
        _Variant("m-q6", "Q6_K", 60, 6 * GIB),
        _Variant("m-q5", "Q5_K_M", 50, 5 * GIB),
        _Variant("m-q4", "Q4_K_M", 40, 4 * GIB),
        _Variant("m-iq2", "IQ2_M", 15, 2 * GIB),
    ]


def test_the_highest_rung_that_fits_is_chosen() -> None:
    choice = select_variant(_ladder(), _profile(vram=24 * GIB), parameter_size="7B")
    assert choice is not None
    assert choice.quantization == "Q8_0"
    assert choice.reasons


def test_a_smaller_budget_walks_down_the_ladder_with_reasons() -> None:
    choice = select_variant(_ladder(), _profile(ram=16 * GIB, vram=8 * GIB), parameter_size="7B")
    assert choice is not None
    assert choice.quantization in ("Q4_K_M", "Q5_K_M")
    assert choice.rejected
    assert any("Q8_0" in variant_id or "q8" in variant_id for variant_id, _ in choice.rejected)


def test_nothing_below_q4_is_chosen_without_the_opt_in() -> None:
    """Only IQ2 fits here, and the default ladder would rather admit defeat than ship it."""
    tiny = _profile(ram=6 * GIB, vram=None)
    assert select_variant(_ladder(), tiny, parameter_size="7B") is None

    permitted = select_variant(
        _ladder(), tiny, parameter_size="7B", prefs=VariantPrefs(allow_low_quality=True)
    )
    assert permitted is not None
    assert permitted.quantization == "IQ2_M"


def test_a_refusal_carries_the_reasons_behind_it() -> None:
    """A refusal includes the numbers that explain why nothing fits."""
    choice, rejections = evaluate_variants(
        _ladder(), _profile(ram=6 * GIB, vram=None), parameter_size="7B"
    )
    assert choice is None
    assert rejections
    assert any("quality floor" in reason for _, reason in rejections)
    assert any("budgeted" in reason for _, reason in rejections)


def test_a_gpu_resident_rung_beats_a_better_one_that_would_only_fit_in_ram() -> None:
    """Q4_K_M on the GPU beats Q8_0 paging through the CPU, and says why."""
    choice = select_variant(_ladder(), _profile(ram=64 * GIB, vram=8 * GIB), parameter_size="7B")
    assert choice is not None
    assert choice.quantization == "Q4_K_M"
    assert any("VRAM" in reason for reason in choice.reasons)


def test_with_no_accelerator_the_ram_budget_is_the_only_one() -> None:
    choice = select_variant(_ladder(), _profile(ram=64 * GIB), parameter_size="7B")
    assert choice is not None
    assert choice.quantization == "Q8_0"
    assert any("system RAM" in reason for reason in choice.reasons)


def test_fp8_is_never_chosen_below_compute_capability_8_9() -> None:
    variants = [_Variant("v-fp8", "fp8", 70, 8 * GIB, engine="vllm", capability="8.9")]
    ampere = _profile(vram=24 * GIB, capability="8.6")
    assert select_variant(variants, ampere, engine="vllm", parameter_size="7B") is None

    ada = _profile(vram=24 * GIB, capability="8.9")
    assert select_variant(variants, ada, engine="vllm", parameter_size="7B") is not None


def test_an_unknown_compute_capability_excludes_a_gated_variant() -> None:
    variants = [_Variant("v-awq", "awq", 45, 4 * GIB, engine="vllm")]
    unknown = _profile(vram=24 * GIB, capability=None)
    assert select_variant(variants, unknown, engine="vllm", parameter_size="7B") is None


def test_vllm_is_never_selected_without_an_accelerator() -> None:
    variants = [_Variant("v-bf16", "bf16", 90, 14 * GIB, engine="vllm")]
    choice = select_variant(variants, _profile(ram=64 * GIB), engine="vllm", parameter_size="7B")
    assert choice is None


def test_multi_gpu_summing_is_opt_in_and_only_for_identical_devices() -> None:
    variants = [_Variant("v-bf16", "bf16", 90, 20 * GIB, engine="vllm")]
    pair = _profile(vram=24 * GIB, count=2)

    assert select_variant(variants, pair, engine="vllm", parameter_size="7B") is None

    summed = select_variant(
        variants,
        pair,
        engine="vllm",
        parameter_size="7B",
        prefs=VariantPrefs(allow_multi_gpu=True),
    )
    assert summed is not None
    assert summed.tensor_parallel_size == 2
    assert summed.gpu_memory_utilization == 0.9


def test_an_unknown_machine_yields_no_choice_rather_than_a_guess() -> None:
    assert select_variant(_ladder(), None, parameter_size="7B") is None
