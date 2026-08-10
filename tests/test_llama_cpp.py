"""The llama-cpp adapter: catalog resolution, download, tuning, supervision, dialect.

The supervisor is stubbed here so these tests exercise the *adapter's* composition logic
without spawning processes; the supervisor's own behavior is covered in
``test_local_server.py``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.catalog.model import Catalog
from anyinfer.errors import ConfigError, LocalRuntimeError
from anyinfer.local.hardware import Accelerator, HardwareProfile
from anyinfer.local.server import ManagedServer, ServerHandle
from anyinfer.local.tuning import ServerPlan
from anyinfer.providers.llama_cpp import LlamaCppAdapter, LlamaCppOptions
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

GIB = 1024**3
PAYLOAD = b"gguf-bytes"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
PROJECTOR = b"projector-bytes"
PROJECTOR_DIGEST = hashlib.sha256(PROJECTOR).hexdigest()


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog.from_mapping(
        {
            "format_version": 1,
            "aliases": {
                "medium": {"targets": {"llama-cpp": {"gguf": "test-model"}}},
            },
            "gguf_artifacts": {
                "test-model": {
                    "license": "Apache-2.0",
                    "parameter_size": "7B",
                    "quantization": "Q4_K_M",
                    "files": [
                        {
                            "filename": "test-model.gguf",
                            "url": "https://host.invalid/test-model.gguf",
                            "sha256": DIGEST,
                            "size_bytes": len(PAYLOAD),
                        }
                    ],
                }
            },
        }
    )


def _vision_catalog() -> Catalog:
    return Catalog.from_mapping(
        {
            "format_version": 1,
            "gguf_artifacts": {
                "vision-model": {
                    "license": "Apache-2.0",
                    "parameter_size": "7B",
                    "files": [
                        {
                            "filename": "vision-model.gguf",
                            "url": "https://host.invalid/vision-model.gguf",
                            "sha256": DIGEST,
                            "size_bytes": len(PAYLOAD),
                        },
                        {
                            "filename": "mmproj.gguf",
                            "url": "https://host.invalid/mmproj.gguf",
                            "sha256": PROJECTOR_DIGEST,
                            "size_bytes": len(PROJECTOR),
                            "role": "projector",
                        },
                    ],
                }
            },
        }
    )


class _StubSupervisor:
    """Stands in for the real supervisor, recording what the adapter asked for."""

    def __init__(self, host: str = "supervised.invalid", port: int = 8080) -> None:
        self._host = host
        self._port = port
        self.acquisitions: list[tuple[str, Path, ServerPlan]] = []
        self.closed = False
        self.resident_models: tuple[str, ...] = ()
        self.resident_plans: dict[str, ServerPlan] = {}
        self.persisted: list[bool] = []

    async def acquire(
        self, model_key: str, model_path: Path, plan: ServerPlan, *, persist: bool = False
    ) -> ManagedServer:
        self.acquisitions.append((model_key, model_path, plan))
        self.persisted.append(persist)
        handle = ServerHandle(
            model_key=model_key,
            model_path=model_path,
            plan=plan,
            host=self._host,
            port=self._port,
            process=None,  # type: ignore[arg-type]
            started_at=0.0,
        )
        return ManagedServer(handle)

    async def aclose(self) -> None:
        self.closed = True

    async def collect_idle(self) -> int:
        return 0

    def set_hardware(self, hardware: object) -> None:
        self.hardware = hardware

    def resolve_binary(self) -> Path:
        return Path("llama-server")


def _adapter(
    tmp_path: Path,
    fake: FakeOpenAIServer,
    *,
    options: dict[str, Any] | None = None,
) -> tuple[LlamaCppAdapter, _StubSupervisor]:
    from anyinfer.providers.base import ProviderConfig

    settings: dict[str, Any] = {
        "catalog": _catalog(tmp_path),
        "model_dir": tmp_path,
        "hardware": HardwareProfile(
            os_name="linux",
            arch="x86_64",
            total_ram_bytes=32 * GIB,
            physical_cores=8,
            accelerators=(Accelerator(kind="cuda", total_vram_bytes=24 * GIB),),
        ),
    }
    settings.update(options or {})

    adapter = LlamaCppAdapter(
        ProviderConfig(
            provider_id="llama-cpp",
            options=settings,
            transport=fake.transport(),
        )
    )
    supervisor = _StubSupervisor()
    adapter._supervisor = supervisor  # type: ignore[assignment]
    return adapter, supervisor


# ---- options -------------------------------------------------------------------------


def test_options_ignore_unknown_keys() -> None:
    options = LlamaCppOptions.from_mapping({"posture": "aggressive", "not_a_field": 1})
    assert options.posture == "aggressive"


def test_default_options() -> None:
    options = LlamaCppOptions.from_mapping({})
    assert options.binary == "llama-server"
    assert options.auto_download is True
    assert options.allow_remote_exposure is False


# ---- resolution ----------------------------------------------------------------------


async def test_missing_catalog_is_actionable(tmp_path: Path) -> None:
    from anyinfer.providers.base import ProviderConfig, WireRequest

    adapter = LlamaCppAdapter(ProviderConfig(provider_id="llama-cpp"))
    try:
        with pytest.raises(ConfigError) as excinfo:
            async for _ in adapter.generate(WireRequest(model="x", messages=())):
                pass
    finally:
        await adapter.aclose()

    assert excinfo.value.hint is not None
    assert "catalog" in excinfo.value.hint


async def test_unknown_artifact_lists_the_known_ones(tmp_path: Path) -> None:
    from anyinfer.providers.base import WireRequest

    fake = FakeOpenAIServer()
    adapter, _ = _adapter(tmp_path, fake)
    try:
        with pytest.raises(ConfigError) as excinfo:
            async for _ in adapter.generate(WireRequest(model="nope", messages=())):
                pass
    finally:
        await adapter.aclose()

    assert excinfo.value.hint is not None
    assert "test-model" in excinfo.value.hint


async def test_absent_artifact_without_auto_download_is_actionable(tmp_path: Path) -> None:
    from anyinfer.providers.base import WireRequest

    fake = FakeOpenAIServer()
    adapter, _ = _adapter(tmp_path, fake, options={"auto_download": False})
    try:
        with pytest.raises(LocalRuntimeError) as excinfo:
            async for _ in adapter.generate(WireRequest(model="test-model", messages=())):
                pass
    finally:
        await adapter.aclose()

    assert excinfo.value.hint is not None
    assert "auto_download" in excinfo.value.hint


# ---- composition ---------------------------------------------------------------------


async def test_generation_tunes_a_plan_and_delegates_to_the_dialect(tmp_path: Path) -> None:
    """The whole point of the adapter: model name in, supervised OpenAI endpoint out."""
    (tmp_path / "test-model.gguf").write_bytes(PAYLOAD)

    from anyinfer.providers.base import WireRequest

    fake = FakeOpenAIServer(FakeResponse(text="local answer"))
    adapter, supervisor = _adapter(tmp_path, fake)
    try:
        events = [
            e
            async for e in adapter.generate(
                WireRequest(model="test-model", messages=(ai.user("hi"),))
            )
        ]
    finally:
        await adapter.aclose()

    text = "".join(e.text for e in events if isinstance(e, ai.TextDelta))
    assert text == "local answer"

    assert len(supervisor.acquisitions) == 1
    model_key, model_path, plan = supervisor.acquisitions[0]
    assert model_key == "test-model"
    assert model_path.name == "test-model.gguf"
    assert plan.gpu_layers == 999, "the tuner saw the GPU"
    assert plan.context_size > 0


async def test_vision_artifact_supplies_projector_and_capability(tmp_path: Path) -> None:
    (tmp_path / "vision-model.gguf").write_bytes(PAYLOAD)
    (tmp_path / "mmproj.gguf").write_bytes(PROJECTOR)
    fake = FakeOpenAIServer(FakeResponse(text="visible"))
    adapter, supervisor = _adapter(
        tmp_path,
        fake,
        options={"catalog": _vision_catalog()},
    )
    from anyinfer.providers.base import WireRequest

    try:
        events = [
            event
            async for event in adapter.generate(
                WireRequest(
                    model="vision-model",
                    messages=(
                        ai.Message(
                            "user",
                            (ai.Text("inspect"), ai.ImagePart(data=b"image")),
                        ),
                    ),
                )
            )
        ]
        models = await adapter.list_models()
    finally:
        await adapter.aclose()

    assert any(isinstance(event, ai.TextDelta) for event in events)
    plan = supervisor.acquisitions[0][2]
    assert plan.projector_path is not None and plan.projector_path.endswith("mmproj.gguf")
    assert "--mmproj" in plan.server_arguments("model.gguf", host="127.0.0.1", port=1)
    assert models[0].capabilities is not None
    assert models[0].capabilities.features.value & ai.Feature.VISION


async def test_explicit_context_reaches_the_tuner(tmp_path: Path) -> None:
    (tmp_path / "test-model.gguf").write_bytes(PAYLOAD)

    from anyinfer.providers.base import WireRequest

    fake = FakeOpenAIServer(FakeResponse(text="ok"))
    adapter, supervisor = _adapter(tmp_path, fake)
    try:
        async for _ in adapter.generate(
            WireRequest(
                model="test-model",
                messages=(ai.user("hi"),),
                extra_options={"context_size": 4096},
            )
        ):
            pass
    finally:
        await adapter.aclose()

    assert supervisor.acquisitions[0][2].context_size == 4096


async def test_posture_reaches_the_tuner(tmp_path: Path) -> None:
    (tmp_path / "test-model.gguf").write_bytes(PAYLOAD)

    from anyinfer.providers.base import WireRequest

    fake = FakeOpenAIServer(FakeResponse(text="ok"))
    adapter, supervisor = _adapter(tmp_path, fake, options={"posture": "aggressive"})
    try:
        async for _ in adapter.generate(
            WireRequest(model="test-model", messages=(ai.user("hi"),))
        ):
            pass
    finally:
        await adapter.aclose()

    plan = supervisor.acquisitions[0][2]
    assert plan.posture == "aggressive"
    assert plan.parallel == 2


async def test_closing_the_adapter_stops_the_supervisor(tmp_path: Path) -> None:
    fake = FakeOpenAIServer()
    adapter, supervisor = _adapter(tmp_path, fake)
    await adapter.aclose()
    assert supervisor.closed is True


# ---- discovery -----------------------------------------------------------------------


async def test_list_models_reports_catalog_artifacts(tmp_path: Path) -> None:
    """Local discovery means "what could run", not "what is loaded"."""
    fake = FakeOpenAIServer()
    adapter, _ = _adapter(tmp_path, fake)
    try:
        models = await adapter.list_models()
    finally:
        await adapter.aclose()

    assert [m.id for m in models] == ["test-model"]
    caps = models[0].capabilities
    assert caps is not None and caps.local is not None
    assert caps.local.parameter_size == "7B"
    assert caps.local.quantization == "Q4_K_M"


async def test_health_reports_binary_availability(tmp_path: Path) -> None:
    fake = FakeOpenAIServer()
    adapter, _ = _adapter(tmp_path, fake)
    try:
        health = await adapter.health()
    finally:
        await adapter.aclose()

    assert health.ok is True


# ---- runtime diagnostics -------------------------------------------------------------


async def test_diagnostics_report_a_gpu_machine_serving_on_the_cpu(tmp_path: Path) -> None:
    adapter, supervisor = _adapter(tmp_path, FakeOpenAIServer())
    supervisor.resident_plans = {"test-model": ServerPlan(context_size=4096, gpu_layers=0)}
    try:
        reported = tuple(await adapter.diagnostics())
    finally:
        await adapter.aclose()

    assert len(reported) == 1
    assert reported[0].code == "llama-cpp.cpu-only"
    assert reported[0].severity == "warning"
    assert "cuda" in reported[0].message


async def test_diagnostics_stay_quiet_when_layers_are_offloaded(tmp_path: Path) -> None:
    adapter, supervisor = _adapter(tmp_path, FakeOpenAIServer())
    supervisor.resident_plans = {"test-model": ServerPlan(context_size=4096, gpu_layers=999)}
    try:
        assert tuple(await adapter.diagnostics()) == ()
    finally:
        await adapter.aclose()


async def test_diagnostics_stay_quiet_on_a_cpu_only_machine(tmp_path: Path) -> None:
    """Running on the CPU there is the plan working, not the plan degrading."""
    adapter, supervisor = _adapter(
        tmp_path,
        FakeOpenAIServer(),
        options={"hardware": HardwareProfile(os_name="linux", arch="x86_64")},
    )
    supervisor.resident_plans = {"test-model": ServerPlan(context_size=4096, gpu_layers=0)}
    try:
        assert tuple(await adapter.diagnostics()) == ()
    finally:
        await adapter.aclose()


async def test_diagnostics_never_trigger_hardware_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An advisory must not be the thing that probes the machine."""
    import anyinfer.providers.llama_cpp as module

    def explode() -> HardwareProfile:
        raise AssertionError("diagnostics must not detect hardware")

    monkeypatch.setattr(module, "detect", explode)
    adapter, supervisor = _adapter(
        tmp_path, FakeOpenAIServer(), options={"hardware": None}
    )
    supervisor.resident_plans = {"test-model": ServerPlan(context_size=4096, gpu_layers=0)}
    try:
        assert tuple(await adapter.diagnostics()) == ()
    finally:
        await adapter.aclose()


# ---- structured output ---------------------------------------------------------------


def test_schema_projection_strips_grammar_hostile_constraints() -> None:
    projected = LlamaCppAdapter.project_schema(
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 80},
                "tags": {"type": "array", "maxItems": 5000},
            },
        }
    )
    assert "minLength" not in projected["properties"]["name"]  # type: ignore[index]
    assert "maxItems" not in projected["properties"]["tags"]  # type: ignore[index]


def test_descriptor_requires_prompt_injection_for_grammar() -> None:
    """A GBNF grammar constrains decoding but never tells the model the shape."""
    from anyinfer.providers.llama_cpp import descriptor

    assert descriptor.grammar_needs_prompt_injection is True
    assert descriptor.locality == "local"
    assert descriptor.supports_sessions is True


async def test_structured_output_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "test-model.gguf").write_bytes(PAYLOAD)
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    fake = FakeOpenAIServer(FakeResponse(text=json.dumps({"answer": "ok"})))

    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "llama-cpp",
                options={
                    "catalog": _catalog(tmp_path),
                    "model_dir": tmp_path,
                    "hardware": HardwareProfile(os_name="linux", arch="x86_64",
                                                total_ram_bytes=32 * GIB),
                },
                transport=fake.transport(),
            )
        ]
    )
    adapter = await client._pool.get("llama-cpp")
    adapter._supervisor = _StubSupervisor()  # type: ignore[attr-defined]

    async with client:
        result = await client.generate("q", target="llama-cpp:test-model", schema=schema)

    assert result.structured == {"answer": "ok"}
    assert result.structured_mechanism == "grammar"

    body = fake.requests[0]
    system_messages = [m for m in body["messages"] if m["role"] == "system"]
    assert system_messages, "grammar mode must still describe the schema in the prompt"


# ---- downloads -----------------------------------------------------------------------


async def test_missing_artifact_is_downloaded(tmp_path: Path) -> None:
    from anyinfer.providers.base import WireRequest

    def serve(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "host.invalid":
            return httpx2.Response(200, content=PAYLOAD)
        return httpx2.Response(404)

    fake = FakeOpenAIServer(FakeResponse(text="ok"))
    adapter, _ = _adapter(tmp_path, fake)

    import anyinfer.providers.llama_cpp as module

    original = module.download_artifact
    calls: list[str] = []

    def recording(artifact, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(artifact.id)
        return original(artifact, **kwargs, client=httpx2.Client(
            transport=httpx2.MockTransport(serve)
        ))

    module.download_artifact = recording  # type: ignore[assignment]
    try:
        async for _ in adapter.generate(
            WireRequest(model="test-model", messages=(ai.user("hi"),))
        ):
            pass
    finally:
        module.download_artifact = original  # type: ignore[assignment]
        await adapter.aclose()

    assert calls == ["test-model"]
    assert (tmp_path / "test-model.gguf").read_bytes() == PAYLOAD


# ---- lifecycle telemetry bridge ------------------------------------------------------


def test_download_progress_bridges_to_the_events_sink(tmp_path: Path) -> None:
    """ProviderConfig.events receives DownloadProgress alongside the app's own callback."""
    from anyinfer.events.telemetry import DownloadProgress, TelemetryEvent
    from anyinfer.providers.base import ProviderConfig

    emitted: list[TelemetryEvent] = []
    app_calls: list[tuple[str, int, int | None]] = []

    adapter = LlamaCppAdapter(
        ProviderConfig(
            provider_id="llama-cpp",
            options={
                "catalog": _catalog(tmp_path),
                "progress": lambda a, d, t: app_calls.append((a, d, t)),
            },
            events=emitted.append,
        )
    )
    bridge = adapter._progress_callback()
    assert bridge is not None
    bridge("artifact-1", 512, 1024)
    bridge("artifact-1", 1024, 1024)

    assert app_calls == [("artifact-1", 512, 1024), ("artifact-1", 1024, 1024)]
    first, last = emitted
    assert isinstance(first, DownloadProgress) and first.done is False
    assert isinstance(last, DownloadProgress) and last.done is True


def test_supervisor_receives_the_events_sink(tmp_path: Path) -> None:
    """The real supervisor is constructed with on_lifecycle wired to config.events."""
    from anyinfer.providers.base import ProviderConfig

    sink = []
    adapter = LlamaCppAdapter(
        ProviderConfig(
            provider_id="llama-cpp",
            options={"catalog": _catalog(tmp_path)},
            events=sink.append,
        )
    )
    assert adapter._supervisor._on_lifecycle is not None


async def test_a_stored_model_is_served_without_any_network_io(tmp_path: Path) -> None:
    """A verified, registered model must not trigger a download on every request."""
    from anyinfer.local.store import ModelStore
    from anyinfer.providers.base import WireRequest

    (tmp_path / "test-model.gguf").write_bytes(PAYLOAD)
    ModelStore(tmp_path).adopt_legacy_flat([_catalog(tmp_path).artifact("test-model")])

    fake = FakeOpenAIServer(FakeResponse(text="ok"))
    adapter, _ = _adapter(tmp_path, fake)

    import anyinfer.providers.llama_cpp as module

    original = module.download_artifact

    def forbidden(artifact, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("a stored model must not be re-downloaded")

    module.download_artifact = forbidden  # type: ignore[assignment]
    try:
        async for _ in adapter.generate(
            WireRequest(model="test-model", messages=(ai.user("hi"),))
        ):
            pass
    finally:
        module.download_artifact = original  # type: ignore[assignment]
        await adapter.aclose()


async def test_a_corrupted_stored_model_is_re_acquired_not_handed_to_the_server(
    tmp_path: Path,
) -> None:
    """The regression this replaced: the fast path used to check existence, not bytes.

    A truncated GGUF that an older build — or a user — left in place would otherwise be
    passed straight to llama-server, which fails at load with an error that says nothing
    about the file.
    """
    from anyinfer.local.store import ModelStore
    from anyinfer.providers.base import WireRequest

    target = tmp_path / "test-model.gguf"
    target.write_bytes(PAYLOAD)
    store = ModelStore(tmp_path)
    store.adopt_legacy_flat([_catalog(tmp_path).artifact("test-model")])
    assert store.locate("test-model") is not None

    # Corrupt it the way a failed copy or a full disk would.
    target.write_bytes(b"truncated")
    assert store.locate("test-model") is None, "the store must not vouch for these bytes"

    def serve(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=PAYLOAD)

    fake = FakeOpenAIServer(FakeResponse(text="ok"))
    adapter, _ = _adapter(tmp_path, fake)

    import anyinfer.providers.llama_cpp as module

    original = module.download_artifact
    calls: list[str] = []

    def recording(artifact, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(artifact.id)
        return original(artifact, **kwargs, client=httpx2.Client(
            transport=httpx2.MockTransport(serve)
        ))

    module.download_artifact = recording  # type: ignore[assignment]
    try:
        async for _ in adapter.generate(
            WireRequest(model="test-model", messages=(ai.user("hi"),))
        ):
            pass
    finally:
        module.download_artifact = original  # type: ignore[assignment]
        await adapter.aclose()

    assert calls == ["test-model"], "a corrupted file must be re-acquired"
    assert target.read_bytes() == PAYLOAD
