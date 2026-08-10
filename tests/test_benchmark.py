"""Throughput measurement and the caller-owned measurement store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import anyinfer as ai
from anyinfer.benchmark import (
    Measurement,
    MeasurementIdentity,
    MeasurementStore,
    benchmark_prompt,
    identity_for,
    measurement_from,
    normalize_endpoint,
)
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from support import make_client, make_sync_client

# ---- the prompt ----------------------------------------------------------------------


def test_the_prompt_is_deterministic() -> None:
    """Two runs a week apart must differ because the machine changed, not the prompt."""
    assert benchmark_prompt(512) == benchmark_prompt(512)


def test_the_prompt_scales_with_the_requested_size() -> None:
    small = benchmark_prompt(256)
    large = benchmark_prompt(4096)
    assert len(large) > len(small) * 4
    assert len(small.encode("utf-8")) // 3 >= 200, "roughly the tokens asked for"


# ---- identity ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://API.Example.com/v1/", "https://api.example.com/v1"),
        ("https://api.example.com/v1?api_key=secret", "https://api.example.com/v1"),
        ("https://user:pass@api.example.com/v1", "https://api.example.com/v1"),
        ("https://api.example.com:8443/v1", "https://api.example.com:8443/v1"),
        (None, None),
        ("   ", None),
    ],
)
def test_endpoint_normalization_drops_anything_credential_shaped(
    raw: str | None, expected: str | None
) -> None:
    assert normalize_endpoint(raw) == expected


def test_fingerprints_distinguish_what_the_measurement_is_about() -> None:
    base = MeasurementIdentity("ollama", "qwen3:8b", endpoint="http://127.0.0.1:11434")
    assert (
        base.fingerprint
        == MeasurementIdentity("ollama", "qwen3:8b", endpoint="http://127.0.0.1:11434").fingerprint
    )

    for other in (
        MeasurementIdentity("ollama", "qwen3:4b", endpoint="http://127.0.0.1:11434"),
        MeasurementIdentity("ollama", "qwen3:8b", endpoint="http://10.0.0.5:11434"),
        MeasurementIdentity("ollama", "qwen3:8b", endpoint="http://127.0.0.1:11434", host="x"),
        MeasurementIdentity(
            "ollama", "qwen3:8b", endpoint="http://127.0.0.1:11434", runtime="cuda"
        ),
    ):
        assert other.fingerprint != base.fingerprint


def test_identity_for_normalizes_the_endpoint() -> None:
    identity = identity_for(
        ai.ResolvedTarget("openai", "gpt-5"), endpoint="https://API.Example.com/v1/"
    )
    assert identity.endpoint == "https://api.example.com/v1"


# ---- assembling a measurement --------------------------------------------------------


IDENTITY = MeasurementIdentity("ollama", "qwen3:8b")


def test_prefill_is_computed_only_from_a_reported_prefill_phase() -> None:
    with_phase = measurement_from(
        IDENTITY,
        input_tokens=2000,
        output_tokens=100,
        ttft_ms=500.0,
        total_ms=3000.0,
        decode_tokens_per_s=40.0,
        prefill_ms=1000.0,
    )
    assert with_phase.prefill_tokens_per_s == pytest.approx(2000.0)


def test_prefill_is_none_when_the_provider_did_not_time_it() -> None:
    """TTFT includes queueing and network; calling that compute would be a lie."""
    without = measurement_from(
        IDENTITY,
        input_tokens=2000,
        output_tokens=100,
        ttft_ms=500.0,
        total_ms=3000.0,
        decode_tokens_per_s=40.0,
        prefill_ms=None,
    )
    assert without.prefill_tokens_per_s is None
    assert without.ttft_ms == 500.0, "the raw figure is still reported"


def test_prefill_is_none_without_a_token_count() -> None:
    measurement = measurement_from(
        IDENTITY,
        input_tokens=None,
        output_tokens=100,
        ttft_ms=None,
        total_ms=1.0,
        decode_tokens_per_s=None,
        prefill_ms=800.0,
    )
    assert measurement.prefill_tokens_per_s is None


def test_summary_reports_only_what_was_measured() -> None:
    bare = Measurement(identity=IDENTITY)
    assert "nothing measurable" in bare.summary

    full = Measurement(
        identity=IDENTITY,
        prefill_tokens_per_s=1500.0,
        ttft_ms=300.0,
        decode_tokens_per_s=42.5,
    )
    assert "prefill 1500 tok/s" in full.summary
    assert "decode 42.5 tok/s" in full.summary


# ---- the store -----------------------------------------------------------------------


def test_the_store_round_trips(tmp_path: Path) -> None:
    store = MeasurementStore(tmp_path / "measurements.json")
    measurement = Measurement(identity=IDENTITY, decode_tokens_per_s=40.0, total_ms=1000.0)
    store.record(measurement)

    assert store.get(IDENTITY) == measurement
    assert store.all() == (measurement,)


def test_recording_replaces_the_entry_for_the_same_identity(tmp_path: Path) -> None:
    store = MeasurementStore(tmp_path / "m.json")
    store.record(Measurement(identity=IDENTITY, decode_tokens_per_s=40.0))
    store.record(Measurement(identity=IDENTITY, decode_tokens_per_s=12.0))

    assert len(store.all()) == 1
    stored = store.get(IDENTITY)
    assert stored is not None and stored.decode_tokens_per_s == 12.0


def test_a_different_identity_is_a_different_entry(tmp_path: Path) -> None:
    """A measurement from another machine is not a fresher version of this one."""
    store = MeasurementStore(tmp_path / "m.json")
    elsewhere = MeasurementIdentity("ollama", "qwen3:8b", host="another-machine")
    store.record(Measurement(identity=IDENTITY, decode_tokens_per_s=40.0))
    store.record(Measurement(identity=elsewhere, decode_tokens_per_s=4.0))

    assert len(store.all()) == 2
    here = store.get(IDENTITY)
    assert here is not None and here.decode_tokens_per_s == 40.0


def test_a_missing_store_reads_as_empty(tmp_path: Path) -> None:
    assert MeasurementStore(tmp_path / "nope.json").all() == ()


@pytest.mark.parametrize(
    "contents",
    ["not json at all", "[]", json.dumps({"format_version": 99, "entries": {}})],
    ids=["corrupt", "wrong-shape", "future-version"],
)
def test_an_unreadable_store_reads_as_empty_rather_than_raising(
    tmp_path: Path, contents: str
) -> None:
    """A cache that can break a program is worse than no cache."""
    path = tmp_path / "m.json"
    path.write_text(contents, encoding="utf-8")
    assert MeasurementStore(path).all() == ()


def test_a_tampered_key_is_discarded(tmp_path: Path) -> None:
    """An entry filed under someone else's fingerprint is not this measurement."""
    path = tmp_path / "m.json"
    store = MeasurementStore(path)
    store.record(Measurement(identity=IDENTITY, decode_tokens_per_s=40.0))

    payload = json.loads(path.read_text(encoding="utf-8"))
    entry = next(iter(payload["entries"].values()))
    path.write_text(
        json.dumps({"format_version": 1, "entries": {"deadbeef": entry}}), encoding="utf-8"
    )
    assert MeasurementStore(path).all() == ()


def test_the_store_creates_its_directory(tmp_path: Path) -> None:
    store = MeasurementStore(tmp_path / "nested" / "deeper" / "m.json")
    store.record(Measurement(identity=IDENTITY))
    assert store.path.exists()


# ---- end to end ----------------------------------------------------------------------


async def test_benchmarking_measures_one_request() -> None:
    server = FakeOpenAIServer(FakeResponse(text="a summary " * 20), chunk_size=8)
    async with make_client(server) as client:
        measurement = await client.benchmark("openai-compat:m", prompt_tokens=256)

    assert server.call_count == 1
    assert measurement.identity.model == "m"
    assert measurement.identity.endpoint == "https://fake.invalid/v1"
    assert measurement.total_ms >= 0.0
    assert measurement.measured_at is not None


async def test_benchmark_progress_exposes_a_terminal_time_series_point() -> None:
    samples: list[ai.BenchmarkSample] = []
    server = FakeOpenAIServer(FakeResponse(text="a summary " * 20), chunk_size=4)
    async with make_client(server) as client:
        measurement = await client.benchmark(
            "openai-compat:m", prompt_tokens=64, progress=samples.append
        )

    assert samples
    assert samples[-1].phase == "complete"
    assert samples[-1].estimated_output_tokens == measurement.output_tokens


async def test_a_hosted_target_records_no_host_signature() -> None:
    """This machine's specs say nothing about a hosted provider's throughput."""
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_client(server) as client:
        measurement = await client.benchmark("openai-compat:m", prompt_tokens=64)

    assert measurement.identity.host is None


async def test_benchmarking_writes_nothing_unless_a_store_is_given(tmp_path: Path) -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_client(server) as client:
        await client.benchmark("openai-compat:m", prompt_tokens=64)
    assert list(tmp_path.iterdir()) == []


async def test_a_store_records_when_passed(tmp_path: Path) -> None:
    store = MeasurementStore(tmp_path / "m.json")
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_client(server) as client:
        measurement = await client.benchmark("openai-compat:m", prompt_tokens=64, store=store)

    assert store.get(measurement.identity) == measurement


async def test_benchmarking_is_not_routed() -> None:
    from support import make_multi_client

    broken = FakeOpenAIServer(FakeResponse(status=500, error_message="down"))
    other = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_multi_client(
        [("openai-compat", broken), ("openai", other)],
        route=ai.Route(targets=("openai-compat:m", "openai:gpt-5")),
    ) as client:
        with pytest.raises(ai.AllTargetsFailedError):
            await client.benchmark("openai-compat:m", prompt_tokens=64)

    assert other.call_count == 0
    assert broken.call_count == 1


def test_sync_client_benchmark() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    client = make_sync_client(server)
    try:
        measurement = client.benchmark("openai-compat:m", prompt_tokens=64)
    finally:
        client.close()

    assert measurement.identity.provider_id == "openai-compat"


async def test_a_provider_that_times_its_prefill_gets_a_prefill_rate() -> None:
    """Ollama reports prompt_eval_duration, so the compute figure is real rather than TTFT."""
    from anyinfer.testing.fakes import FakeOllamaServer

    server = FakeOllamaServer(FakeResponse(text="a summary of the report"))
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "ollama", base_url="http://127.0.0.1:11434", transport=server.transport()
            )
        ]
    )
    async with client:
        measurement = await client.benchmark("ollama:qwen3:8b", prompt_tokens=256)

    assert measurement.prefill_tokens_per_s is not None
    assert measurement.identity.host is not None, "a loopback ollama runs on this machine"


# ---- the warmth signal (CS.1) ------------------------------------------------------------


def test_a_reported_load_duration_reaches_the_measurement() -> None:
    """Ollama reports `load_duration` on every request; the benchmark path now reads it."""
    from anyinfer.benchmark import measurement_from

    measurement = measurement_from(
        IDENTITY,
        input_tokens=10,
        output_tokens=5,
        ttft_ms=12.0,
        total_ms=100.0,
        decode_tokens_per_s=40.0,
        prefill_ms=None,
        model_load_ms=1_840.0,
    )
    assert measurement.model_load_ms == 1_840.0
    assert "loaded in 1840 ms" in measurement.summary


def test_an_unreported_load_is_none_rather_than_zero() -> None:
    """The same tri-state rule as every other rate: unknown is not "instant"."""
    from anyinfer.benchmark import measurement_from

    measurement = measurement_from(
        IDENTITY,
        input_tokens=10,
        output_tokens=5,
        ttft_ms=None,
        total_ms=50.0,
        decode_tokens_per_s=None,
        prefill_ms=None,
    )
    assert measurement.model_load_ms is None
    assert "loaded in" not in measurement.summary


def test_the_load_signal_survives_a_store_round_trip(tmp_path: Path) -> None:
    from anyinfer.benchmark import Measurement, measurement_from

    measurement = measurement_from(
        IDENTITY,
        input_tokens=1,
        output_tokens=1,
        ttft_ms=None,
        total_ms=1.0,
        decode_tokens_per_s=None,
        prefill_ms=None,
        model_load_ms=7.5,
    )
    restored = Measurement.from_json(measurement.to_json())
    assert restored is not None
    assert restored.model_load_ms == 7.5


async def test_a_provider_reported_phase_flows_through_benchmark() -> None:
    """End to end: an adapter phase becomes a field on the measurement."""
    from anyinfer.testing.fakes import FakeOllamaServer

    # The fake reports Ollama's own terminal fields, `load_duration` among them.
    server = FakeOllamaServer(FakeResponse(text="hello"))
    async with ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "ollama", base_url="http://127.0.0.1:11434", transport=server.transport()
            )
        ]
    ) as client:
        measurement = await client.benchmark("ollama:qwen3:8b", output_tokens=4)

    assert measurement.model_load_ms == 300.0
