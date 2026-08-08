"""Supervised ``llama-server`` as a provider.

The adapter composes the local subsystem: resolve the GGUF artifact from the catalog →
ensure it is downloaded and verified → tune a server plan for this machine → supervise the
process → speak the OpenAI-compatible dialect over loopback.

This is why the target ``llama-cpp:qwen2.5-7b-instruct-q4-k-m`` behaves like any hosted
target: everything between "a model name" and "an HTTP endpoint" is handled here, once.

Structured output is genuinely grammar-constrained here — llama.cpp compiles the schema to
GBNF — but the grammar only *constrains* decoding; it does not tell the model what to
produce. The descriptor therefore sets ``grammar_needs_prompt_injection``, and the core also
describes the schema in the prompt.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from ..catalog.model import Catalog
from ..errors import ConfigError, LocalRuntimeError
from ..events.telemetry import DownloadProgress
from ..local.artifacts import GgufArtifact
from ..local.downloads import (
    ProgressCallback,
    artifact_paths,
    download_artifact,
    verify_file,
)
from ..local.hardware import HardwareProfile, detect
from ..local.server import ServerSupervisor
from ..local.store import ModelStore, ResolvedModel
from ..local.tuning import Posture, ServerPlan, TuningInputs, plan_server
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..schema.project import repetition_safe_projection
from ..types.capabilities import (
    DiscoveredModel,
    Feature,
    Health,
    LocalModelInfo,
    ModelCapabilities,
    Sourced,
)
from .base import AdapterEvent, ProviderConfig, WireRequest
from .openai_compat import OpenAICompatAdapter

__all__ = ["LlamaCppAdapter", "LlamaCppOptions", "descriptor"]


@dataclass(frozen=True, slots=True)
class LlamaCppOptions:
    """Adapter configuration, supplied through ``ProviderSettings.options``.

    Attributes:
        catalog: Catalog resolving artifact ids to pinned downloads.
        binary: Path to ``llama-server``.
        model_dir: Where artifacts are stored.
        posture: Tuning posture.
        hardware: Pre-detected hardware, to avoid re-probing.
        idle_ttl_s: Unload a server after this long with no active streams.
        max_resident: How many servers may run at once.
        auto_download: Fetch a missing artifact rather than failing.
        allow_remote_exposure: Bind a non-loopback address; loopback-only by default.
        progress: Download progress callback.
    """

    catalog: Catalog | None = None
    binary: str = "llama-server"
    model_dir: Path | None = None
    posture: Posture = "balanced"
    hardware: HardwareProfile | None = None
    idle_ttl_s: float | None = 900.0
    max_resident: int = 1
    auto_download: bool = True
    allow_remote_exposure: bool = False
    progress: ProgressCallback | None = None

    @classmethod
    def from_mapping(cls, options: Mapping[str, Any]) -> LlamaCppOptions:
        """Build options from a provider settings mapping, ignoring unknown keys."""
        import dataclasses

        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in options.items() if k in known})


class LlamaCppAdapter:
    """Adapter that supervises a local llama-server per model."""

    provider_id: ClassVar[str] = "llama-cpp"

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self._options = LlamaCppOptions.from_mapping(config.options)
        self._hardware = self._options.hardware
        self._supervisor = ServerSupervisor(
            binary=self._options.binary,
            hardware=self._hardware,
            idle_ttl_s=self._options.idle_ttl_s,
            max_resident=self._options.max_resident,
            allow_remote_exposure=self._options.allow_remote_exposure,
            on_lifecycle=config.events,
        )
        self._delegates: dict[str, OpenAICompatAdapter] = {}
        self._model_store: ModelStore | None = None
        self._lock = asyncio.Lock()

    @staticmethod
    def project_schema(schema: Mapping[str, Any]) -> Mapping[str, Any]:
        """Strip constraints that GBNF compilation cannot express efficiently."""
        return repetition_safe_projection(schema)

    # ---- resolution ------------------------------------------------------------------

    def _hardware_profile(self) -> HardwareProfile:
        """Detect hardware once, then reuse it — and share it with the supervisor.

        The supervisor needs the profile for VRAM admission control and backend
        fallback, but detection stays lazy so building a client never probes hardware.
        """
        if self._hardware is None:
            self._hardware = detect()
            self._supervisor.set_hardware(self._hardware)
        return self._hardware

    def _artifact_for(self, model: str) -> GgufArtifact:
        """Resolve a model reference to a pinned catalog artifact."""
        catalog = self._options.catalog
        if catalog is None:
            raise ConfigError(
                "the llama-cpp provider needs a catalog to resolve model artifacts",
                provider=self.provider_id,
                hint=(
                    "pass options={'catalog': my_catalog} in ProviderSettings, or use the "
                    "bundled catalog"
                ),
            )
        return catalog.artifact(model)

    def _store(self) -> ModelStore:
        """The model store this adapter reads from and writes into."""
        if self._model_store is None:
            self._model_store = ModelStore(self._options.model_dir)
        return self._model_store

    async def _ensure_downloaded(self, artifact: GgufArtifact) -> Path:
        """Make sure an artifact is present and verified, downloading if permitted.

        The check is *verification*, not existence. A truncated or corrupted GGUF that an
        older build — or a user — moved into place would otherwise be handed straight to
        llama-server, which fails at load with an error that says nothing about the file.
        Cheap by default: the store compares size and modification time against its index
        and only re-hashes on a mismatch.
        """
        store = self._store()
        located: ResolvedModel | None = await asyncio.to_thread(
            store.locate, artifact.id, engine="llama.cpp"
        )
        if located is not None:
            return located.path

        legacy = await asyncio.to_thread(self._legacy_path, artifact)
        if legacy is not None:
            return legacy

        if not self._options.auto_download:
            raise LocalRuntimeError(
                f"model artifact {artifact.id!r} is not downloaded",
                provider=self.provider_id,
                hint="download it first with client.acquire_model(), or set auto_download=True",
            )
        report = await asyncio.to_thread(
            download_artifact,
            artifact,
            model_dir=self._options.model_dir,
            progress=self._progress_callback(),
        )
        # Register what the compatibility downloader just placed, so the next request
        # answers from the index instead of re-walking the filesystem.
        await asyncio.to_thread(self._store().adopt_legacy_flat, [artifact])
        return report.primary_path

    def _legacy_path(self, artifact: GgufArtifact) -> Path | None:
        """Adopt a verified flat-layout file from a pre-store build, if one is there."""
        paths = artifact_paths(artifact, self._options.model_dir)
        if not all(
            verify_file(path, file.sha256)
            for file, path in zip(artifact.files, paths, strict=True)
        ):
            return None
        self._store().adopt_legacy_flat([artifact])
        return paths[0]

    def _progress_callback(self) -> ProgressCallback | None:
        """Compose the app's progress callback with `DownloadProgress` telemetry."""
        app_progress = self._options.progress
        emit = self._config.events
        if emit is None:
            return app_progress

        def bridge(artifact_id: str, downloaded: int, total: int | None) -> None:
            emit(
                DownloadProgress(
                    artifact_id=artifact_id,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    done=total is not None and downloaded >= total,
                    phase="downloading",
                    session_bytes=downloaded,
                )
            )
            if app_progress is not None:
                app_progress(artifact_id, downloaded, total)

        return bridge

    def _plan_for(self, artifact: GgufArtifact, req: WireRequest) -> ServerPlan:
        """Tune a server plan for this artifact on this machine."""
        return plan_server(
            self._hardware_profile(),
            TuningInputs(
                artifact_size_bytes=artifact.total_size_bytes,
                parameter_size=artifact.parameter_size,
                requested_context=_requested_context(req),
            ),
            posture=self._options.posture,
        )

    async def _delegate_for(self, base_url: str) -> OpenAICompatAdapter:
        """Reuse one HTTP client per supervised server."""
        async with self._lock:
            delegate = self._delegates.get(base_url)
            if delegate is None:
                delegate = OpenAICompatAdapter(
                    ProviderConfig(
                        provider_id=self.provider_id,
                        base_url=base_url,
                        timeout_s=self._config.timeout_s,
                        transport=self._config.transport,
                    )
                )
                self._delegates[base_url] = delegate
            return delegate

    # ---- adapter contract ------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """List the catalog artifacts this provider can serve.

        Discovery here means "what could be run", not "what is loaded": a local provider's
        inventory is the catalog plus what is on disk, and reporting only resident models
        would hide everything the user could choose.
        """
        catalog = self._options.catalog
        if catalog is None:
            return []
        models: list[DiscoveredModel] = []
        for artifact_id in sorted(catalog.artifacts):
            artifact = catalog.artifacts[artifact_id]
            models.append(
                DiscoveredModel(
                    id=artifact_id,
                    capabilities=ModelCapabilities(
                        features=Sourced(_LLAMA_FEATURES, "catalog"),
                        local=LocalModelInfo(
                            artifact_size_bytes=artifact.total_size_bytes,
                            parameter_size=artifact.parameter_size,
                            quantization=artifact.quantization,
                            est_ram_bytes=artifact.est_ram_bytes,
                            est_vram_bytes=artifact.est_vram_bytes,
                        ),
                    ),
                )
            )
        return models

    async def health(self) -> Health:
        """Report supervisor readiness.

        Healthy means "a server could be started", not "one is running": starting on demand
        is the normal path, so requiring a resident server would make every cold client look
        unhealthy and get itself health-gated out of the route.
        """
        try:
            self._supervisor.resolve_binary()
        except LocalRuntimeError as exc:
            return Health(ok=False, detail=exc.detail)
        return Health(ok=True, detail=f"resident: {', '.join(self._supervisor.resident_models)}")

    async def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]:
        """Ensure a server is running for this model, then delegate to the OpenAI dialect."""
        artifact = self._artifact_for(req.model)
        model_path = await self._ensure_downloaded(artifact)
        plan = self._plan_for(artifact, req)

        # Opportunistic TTL sweep: with no background task, each request is the moment
        # servers idle beyond idle_ttl_s get unloaded and their memory returned.
        await self._supervisor.collect_idle()
        managed = await self._supervisor.acquire(req.model, model_path, plan)
        with managed:
            delegate = await self._delegate_for(managed.base_url)
            # The supervised server is a plain OpenAI-compatible endpoint, so the whole
            # generation path is the base adapter's — no duplicated wire logic.
            async for event in delegate.generate(req):
                yield event

    async def aclose(self) -> None:
        """Close delegates and stop every supervised server."""
        for delegate in self._delegates.values():
            await delegate.aclose()
        self._delegates.clear()
        await self._supervisor.aclose()


def _requested_context(req: WireRequest) -> int | None:
    """Honor an explicit context size passed through ``provider_options``."""
    value = req.extra_options.get("context_size")
    return value if isinstance(value, int) and value > 0 else None


_LLAMA_FEATURES = (
    Feature.STREAMING
    | Feature.GRAMMAR
    | Feature.JSON_SCHEMA
    | Feature.TOOLS
    | Feature.SYSTEM_PROMPT
)


descriptor = ProviderDescriptor(
    id="llama-cpp",
    display_name="llama.cpp (supervised llama-server)",
    aliases=("llamacpp", "llama"),
    factory=LlamaCppAdapter,
    locality="local",
    default_base_url=None,
    requires_base_url=False,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="binary",
                label="llama-server path",
                kind="endpoint",
                required=False,
                advanced=True,
                default_value="llama-server",
                help_text="Defaults to 'llama-server' on PATH.",
            ),
            SetupField(
                key="posture",
                label="Resource posture",
                kind="host-profile",
                required=False,
                advanced=True,
                default_value="balanced",
                help_text="conservative, balanced, or aggressive.",
            ),
            SetupField(
                key="model_dir",
                label="Model directory",
                kind="endpoint",
                required=False,
                advanced=True,
                help_text="Where GGUF artifacts are stored.",
            ),
        ),
        model_selection="manual-only",
    ),
    default_capabilities=ModelCapabilities(features=Sourced(_LLAMA_FEATURES, "default")),
    supports_sessions=True,
    grammar_needs_prompt_injection=True,
)
"""Descriptor for the supervised llama.cpp provider."""
