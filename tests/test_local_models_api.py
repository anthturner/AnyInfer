"""The client-facing local-model surface: browsing, locality, and acquisition wiring.

Offline throughout. What matters here is the honest-unknown rule — a remote engine gets
``unknown`` fits and a machine-readable cue to ask the user, rather than advice derived
from the wrong computer, and that the locality distinction reaches capability assembly,
where it decides whether "free" is a genuine zero or an unknown.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import anyinfer as ai
from anyinfer._client.models import build_catalog_view, choose_variant, engine_for_provider
from anyinfer._client.providers import AdapterPool, ProviderSettings
from anyinfer.catalog import load_default_catalog
from anyinfer.local.hardware import HardwareProfile
from anyinfer.local.server import is_loopback
from anyinfer.local.store import StoreEntry
from anyinfer.registry import default_registry

GIB = 1024**3


async def test_client_supplies_its_catalog_to_llama_cpp_discovery(tmp_path: Path) -> None:
    """The default demo setup needs no unserializable catalog object in provider options."""
    artifact_id = sorted(load_default_catalog().artifacts)[0]
    client = ai.AsyncClient(
        [ai.ProviderSettings.of("llama-cpp", options={"model_dir": tmp_path})],
        model_dir=tmp_path,
    )
    try:
        client.model_store.register(
            StoreEntry(
                id="installed-for-discovery",
                model_id=artifact_id,
                variant_id=artifact_id,
                engine="llama.cpp",
            )
        )
        models = await client.models("llama-cpp")
        assert [model.id for model in models] == [artifact_id]
    finally:
        await client.aclose()


# ---- loopback detection --------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434",
        "http://127.5.6.7:8080",
        "http://[::1]:11434",
    ],
)
def test_loopback_urls_are_recognized(url: str) -> None:
    assert is_loopback(url)


@pytest.mark.parametrize(
    "url",
    ["http://192.168.1.10:11434", "https://ollama.example.com", "", None, "not a url at all"],
)
def test_anything_else_is_treated_as_somebody_elses_machine(url: str | None) -> None:
    """The safe default: assume remote, because assuming local is the wrong answer."""
    assert not is_loopback(url)


# ---- locality ---------------------------------------------------------------------------


def test_a_loopback_ollama_is_local() -> None:
    pool = AdapterPool(
        [ProviderSettings.of("ollama", base_url="http://127.0.0.1:11434")],
        registry=default_registry,
    )
    assert pool.locality_for("ollama") == "local"


def test_a_remote_ollama_is_not_local() -> None:
    """Otherwise capability assembly stamps a genuine zero on someone else's metered proxy."""
    pool = AdapterPool(
        [ProviderSettings.of("ollama", base_url="http://192.168.1.50:11434")],
        registry=default_registry,
    )
    assert pool.locality_for("ollama") == "remote"


def test_a_supervised_engine_with_no_endpoint_is_local() -> None:
    pool = AdapterPool([ProviderSettings.of("llama-cpp")], registry=default_registry)
    assert pool.locality_for("llama-cpp") == "local"


def test_a_hosted_provider_keeps_its_declared_locality() -> None:
    pool = AdapterPool([ProviderSettings.of("openai", api_key="k")], registry=default_registry)
    assert pool.locality_for("openai") == "hosted"


def test_remote_locality_withholds_the_local_zero_price() -> None:
    from anyinfer.capabilities.assemble import capabilities_for

    descriptor = default_registry.get("ollama")
    local = capabilities_for(descriptor, "qwen3:8b", locality="local")
    remote = capabilities_for(descriptor, "qwen3:8b", locality="remote")

    assert local.pricing is not None
    assert local.pricing.value.input_per_1m == 0
    # Unknown, not zero: we have no idea what somebody else's endpoint charges.
    assert remote.pricing is None


# ---- catalog views -----------------------------------------------------------------------


def _profile(ram: int = 32 * GIB) -> HardwareProfile:
    return HardwareProfile(os_name="linux", arch="x86_64", total_ram_bytes=ram)


def test_a_view_is_annotated_sorted_and_needs_no_network() -> None:
    view = build_catalog_view(load_default_catalog(), hardware=_profile(), detect_backend=False)
    assert len(view) >= 35
    assert view.hardware_source == "provided"
    ranks = [entry.fit.rank for entry in view.entries]
    assert ranks == sorted(ranks, reverse=True)
    assert all(entry.fit.reasons for entry in view.entries)


def test_filtering_by_category_returns_only_that_category() -> None:
    view = build_catalog_view(
        load_default_catalog(),
        hardware=_profile(),
        best_at="coding",
        detect_backend=False,
    )
    assert view.entries
    assert all("coding" in e.model.best_at for e in view.entries)


def test_an_unknown_category_is_an_error_not_an_empty_list() -> None:
    with pytest.raises(ai.ConfigError, match="unknown best_at category"):
        build_catalog_view(
            load_default_catalog(),
            hardware=_profile(),
            best_at="vibes",
            detect_backend=False,
        )


def test_an_8gb_cpu_only_machine_cannot_comfortably_run_a_70b() -> None:
    view = build_catalog_view(
        load_default_catalog(), hardware=_profile(ram=8 * GIB), detect_backend=False
    )
    by_id = {entry.model.id: entry for entry in view.entries}
    assert by_id["deepseek-r1-distill-llama-70b"].fit.level == "no"
    assert by_id["llama-3.2-1b-instruct"].fit.runnable


def test_an_unprobeable_engine_reports_unavailable_and_says_what_to_do() -> None:
    view = build_catalog_view(
        load_default_catalog(), provider_id="ollama", probeable=False, detect_backend=False
    )
    assert view.hardware_source == "unavailable"
    assert view.entries
    assert all(entry.fit.level == "unknown" for entry in view.entries)
    assert any("from_user_input" in note for note in view.notes)


def test_user_supplied_specs_produce_real_fits_and_say_they_were_supplied() -> None:
    supplied = HardwareProfile.from_user_input(ram_gb=64, vram_gb=24, accelerator="cuda")
    view = build_catalog_view(
        load_default_catalog(),
        provider_id="ollama",
        hardware=supplied,
        detect_backend=False,
    )
    assert view.hardware_source == "provided"
    assert any(entry.fit.level != "unknown" for entry in view.entries)
    assert any("specs you provided" in note for note in view.notes)


def test_from_user_input_takes_gigabytes_and_leaves_the_rest_unknown() -> None:
    profile = HardwareProfile.from_user_input(ram_gb=16, vram_gb=8, accelerator="cuda")
    assert profile.total_ram_bytes == 16 * GIB
    assert profile.total_vram_bytes == 8 * GIB
    assert profile.cpu_name is None
    assert profile.user_supplied


def test_from_user_input_treats_an_omitted_value_as_unknown_not_zero() -> None:
    profile = HardwareProfile.from_user_input(ram_gb=16)
    assert profile.total_ram_bytes == 16 * GIB
    assert profile.total_vram_bytes is None
    assert not profile.has_accelerator


def test_no_catalog_yields_an_empty_view_rather_than_an_error() -> None:
    view = build_catalog_view(None)
    assert len(view) == 0
    assert view.hardware_source == "unavailable"


def test_provider_ids_map_to_engines() -> None:
    assert engine_for_provider("llama-cpp") == "llama.cpp"
    assert engine_for_provider("vllm") == "vllm"
    assert engine_for_provider("openai") is None
    assert engine_for_provider(None) is None


def test_an_engine_owned_catalog_channel_points_to_pull_instead_of_contradicting_itself() -> None:
    entry = load_default_catalog().model("qwen3-4b")

    with pytest.raises(ai.ConfigError) as excinfo:
        choose_variant(
            entry,
            engine="ollama",
            hardware=None,
            backend=None,
            prefs=None,
            variant_id=None,
        )

    assert "no downloadable weight variants for ollama" in str(excinfo.value)
    assert excinfo.value.hint is not None
    assert "downloadable variant engines: llama.cpp" in excinfo.value.hint
    assert "pull_model('ollama', 'qwen3:4b')" in excinfo.value.hint
    assert "available on: llama-cpp, ollama" not in str(excinfo.value)


# ---- the client surface --------------------------------------------------------------------


def test_the_sync_client_exposes_a_store_rooted_where_asked(tmp_path: Path) -> None:
    with ai.Client(model_dir=tmp_path) as client:
        assert client.model_store.root == tmp_path
        assert client.installed_models() == []


def test_locate_returns_none_for_a_model_that_was_never_acquired(tmp_path: Path) -> None:
    with ai.Client(model_dir=tmp_path) as client:
        assert client.locate_model("qwen2.5-7b-instruct") is None


def test_removing_an_unknown_entry_reports_that_nothing_happened(tmp_path: Path) -> None:
    with ai.Client(model_dir=tmp_path) as client:
        report = client.remove_model("no-such-entry")
        assert not report.removed
        assert report.freed_bytes == 0


def test_local_catalog_through_the_sync_facade(tmp_path: Path) -> None:
    with ai.Client(model_dir=tmp_path) as client:
        view = client.local_catalog(hardware=_profile())
        assert len(view) >= 35
        assert view.hardware_source == "provided"


def test_acquiring_an_unknown_model_names_the_problem(tmp_path: Path) -> None:
    with (
        ai.Client(model_dir=tmp_path) as client,
        pytest.raises(ai.ConfigError, match="unknown catalog model"),
    ):
        client.acquire_model("no-such-model", variant_id="x")
