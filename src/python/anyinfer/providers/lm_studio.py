"""LM Studio (`contracts/lm-studio.md`).

LM Studio serves an OpenAI-compatible endpoint, so generation is the shared dialect —
this adapter subclasses it rather than restating chat translation. What it adds is the
part the compatibility layer cannot express: LM Studio's **native model API**, which
reports what is downloaded, what is *loaded*, each model's real context length, and its
quantization.

That distinction matters for a local engine. A hosted provider's model list is a catalog;
a local engine's is inventory, and knowing which models are resident is the difference
between a fast request and a thirty-second load. Discovery therefore reports real
capabilities with ``discovered`` provenance, and `LMStudioAdapter.loaded_models()`
exposes residency the same way the Ollama adapter does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx2

from ..registry import HostShorthand, ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import (
    DiscoveredModel,
    Feature,
    Health,
    LocalModelInfo,
    ModelCapabilities,
    Sourced,
)
from ..types.operations import InferenceOperation
from ..types.requests import ReasoningEffort
from .base import ProviderConfig
from .openai_compat import OpenAICompatAdapter
from .openai_compat_embeddings import OpenAICompatEmbeddingsMixin

__all__ = ["LMStudioAdapter", "descriptor"]

_DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
_DEFAULT_PORT = 1234

_NATIVE_MODELS_PATH = "/api/v1/models"
"""The native listing, relative to the server root rather than the ``/v1`` prefix."""


class LMStudioAdapter(OpenAICompatEmbeddingsMixin, OpenAICompatAdapter):
    """Adapter for LM Studio's local server, with native model discovery."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        # The native API sits beside /v1, not under it, so its root is the base URL with
        # any trailing /v1 removed.
        base = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")
        self._server_root = base[: -len("/v1")] if base.endswith("/v1") else base

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """List models from the native API, falling back to the OpenAI listing.

        The native listing carries context length, quantization, size, and load state;
        the OpenAI one carries ids alone. Older LM Studio builds have no native API, so
        a 404 degrades to the compatible listing rather than failing.
        """
        try:
            response = await self._client.get(f"{self._server_root}{_NATIVE_MODELS_PATH}")
        except httpx2.HTTPError:
            return await super().list_models()
        if response.status_code >= 400:
            return await super().list_models()

        payload = response.json()
        entries = payload.get("models") if isinstance(payload, Mapping) else None
        if not isinstance(entries, list):
            return await super().list_models()

        # Embedding models are listed too, tagged with their operation, rather than
        # filtered out as non-chat — discovery reports what exists, not what one
        # operation can use.
        models = [
            _parse_native_model(entry)
            for entry in entries
            if isinstance(entry, Mapping) and entry.get("type") in (None, "llm", "embedding")
        ]
        return models or await super().list_models()

    async def loaded_models(self) -> Mapping[str, int]:
        """Report which models are resident, and how many instances each has.

        A provider-specific extension beyond the four-method adapter contract, for
        applications that want to prefer an already-loaded model over one that would
        cost a cold load. An unreachable or older server reports nothing rather than
        failing — residency is an optimization, not a correctness input.
        """
        try:
            response = await self._client.get(f"{self._server_root}{_NATIVE_MODELS_PATH}")
        except httpx2.HTTPError:
            return {}
        if response.status_code >= 400:
            return {}

        payload = response.json()
        entries = payload.get("models") if isinstance(payload, Mapping) else None
        if not isinstance(entries, list):
            return {}

        loaded: dict[str, int] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            instances = entry.get("loaded_instances")
            if isinstance(instances, list) and instances:
                loaded[str(entry.get("key", ""))] = len(instances)
        return loaded

    async def health(self) -> Health:
        """Probe readiness, reporting how many models are resident when it succeeds."""
        health = await super().health()
        if not health.ok:
            return health
        resident = await self.loaded_models()
        if not resident:
            return Health(ok=True, detail="no model loaded; the first request will load one")
        return Health(ok=True, detail=f"loaded: {', '.join(sorted(resident))}")


def _parse_native_model(entry: Mapping[str, Any]) -> DiscoveredModel:
    """Read one native listing entry into discovered capabilities.

    The native listing's ``type`` distinguishes ``llm`` from ``embedding`` models, so
    operations arrive with ``discovered`` provenance; generation feature flags are never
    stamped onto an embedding model.
    """
    kind = entry.get("type")
    operations: Sourced[frozenset[InferenceOperation]] | None = None
    if kind == "embedding":
        operations = Sourced(frozenset({"embedding"}), "discovered")
    elif kind == "llm":
        operations = Sourced(frozenset({"generation"}), "discovered")

    features = Feature(0)
    if kind != "embedding":
        features = Feature.STREAMING | Feature.SYSTEM_PROMPT | Feature.JSON_SCHEMA
        capabilities = entry.get("capabilities")
        if isinstance(capabilities, Mapping):
            if capabilities.get("trained_for_tool_use"):
                features |= Feature.TOOLS
            if capabilities.get("reasoning"):
                features |= Feature.REASONING
        else:
            features |= Feature.TOOLS

    window = entry.get("max_context_length")
    context = (
        Sourced(int(window), "discovered")
        if isinstance(window, int) and not isinstance(window, bool) and window > 0
        else None
    )

    quantization = entry.get("quantization")
    quant_name = (
        str(quantization.get("name"))
        if isinstance(quantization, Mapping) and quantization.get("name")
        else (quantization if isinstance(quantization, str) else None)
    )
    size = entry.get("size_bytes")

    return DiscoveredModel(
        id=str(entry.get("key", "")),
        capabilities=ModelCapabilities(
            context_window=context,
            features=Sourced(features, "discovered"),
            operations=operations,
            local=LocalModelInfo(
                artifact_size_bytes=size if isinstance(size, int) else None,
                parameter_size=str(entry["params_string"])
                if isinstance(entry.get("params_string"), str)
                else None,
                quantization=quant_name,
            ),
        ),
    )


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Map normalized effort onto LM Studio's ``reasoning`` field.

    The native API names levels rather than budgeting tokens; ``minimal`` maps to the
    server's ``low``, since ``off`` would disable reasoning outright rather than reduce
    it.
    """
    if effort is None:
        return {}
    if effort == "none":
        return {"reasoning": "off"}
    return {"reasoning": "low" if effort == "minimal" else effort}


_LM_STUDIO_FEATURES = (
    Feature.STREAMING
    | Feature.JSON_SCHEMA
    | Feature.JSON_MODE
    | Feature.TOOLS
    | Feature.SYSTEM_PROMPT
)


descriptor = ProviderDescriptor(
    id="lm-studio",
    display_name="LM Studio",
    aliases=("lmstudio",),
    factory=LMStudioAdapter,
    locality="local",
    default_base_url=_DEFAULT_BASE_URL,
    requires_base_url=False,
    # /v1/embeddings verified against lmstudio.ai/docs/app/api/endpoints/openai on
    # 2026-08-12; per-model limits are whatever the loaded model imposes, so no static
    # embedding capabilities are declared — discovery tags which models embed.
    operations=frozenset({"generation", "embedding"}),
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="base_url",
                label="Server URL",
                kind="endpoint",
                required=False,
                advanced=True,
                default_value=_DEFAULT_BASE_URL,
                help_text=(
                    f"Defaults to {_DEFAULT_BASE_URL}. A bare hostname expands to "
                    f"http://<host>:{_DEFAULT_PORT}."
                ),
            ),
            SetupField(
                key="api_key",
                label="API token",
                kind="secret",
                required=False,
                advanced=True,
                help_text="Only needed when LM Studio's authentication is enabled.",
                placeholder="env://LM_STUDIO_API_KEY or a literal key",
                env_var="LM_STUDIO_API_KEY",
            ),
        ),
        model_selection="discover-or-manual",
        host_shorthand=HostShorthand(scheme="http", default_port=_DEFAULT_PORT),
    ),
    reasoning_translator=_translate_reasoning,
    default_capabilities=ModelCapabilities(features=Sourced(_LM_STUDIO_FEATURES, "default")),
)
"""Descriptor for the LM Studio provider."""
