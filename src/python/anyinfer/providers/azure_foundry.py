"""Azure AI Foundry (`contracts/azure-foundry.md`).

An ``openai-compat`` subclass with three Azure-specific differences:

- the output-token parameter is ``max_completion_tokens``, not ``max_tokens``;
- reasoning effort is a flat ``reasoning_effort`` field;
- authentication may be an ``api-key`` header *or* an Entra bearer token obtained through
  ``azure-identity`` (the ``[azure]`` extra).

Everything else — request shaping, SSE parsing, error mapping — is inherited, which is the
point of having a base dialect at all.

Embeddings compose `OpenAICompatEmbeddingsMixin` unchanged: the v1 surface
(``{base_url}/openai/v1/embeddings``, model-addressed by deployment name, same as chat)
speaks the identical OpenAI-compatible body verified in ``openai_compat_embeddings.py``.
Verified against learn.microsoft.com/azure/ai-foundry/openai/how-to/embeddings, 2026-08-12:
max 2,048 inputs/request, 8,192 tokens/input, 300,000 tokens aggregate per request — the
same ceilings OpenAI itself documents.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Mapping
from typing import Any, ClassVar

import httpx2

from ..errors import ConfigError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import Feature, ModelCapabilities, Sourced
from ..types.requests import ReasoningEffort
from .base import ProviderConfig
from .openai_compat import OpenAICompatAdapter
from .openai_compat_embeddings import OpenAICompatEmbeddingsMixin

__all__ = ["FOUNDRY_SCOPE", "AzureFoundryAdapter", "descriptor"]

FOUNDRY_SCOPE = "https://ai.azure.com/.default"
"""Entra token scope for Foundry, as recorded in the contract snapshot."""


class AzureFoundryAdapter(OpenAICompatEmbeddingsMixin, OpenAICompatAdapter):
    """Adapter for Azure AI Foundry deployments."""

    output_tokens_field: ClassVar[str] = "max_completion_tokens"
    """Azure renamed this parameter; sending ``max_tokens`` is rejected."""

    def __init__(self, config: ProviderConfig) -> None:
        if not config.base_url:
            raise ConfigError(
                "azure-foundry requires the base URL of your Foundry resource",
                provider=config.provider_id,
                hint=("for example https://<resource>.services.ai.azure.com/openai/v1"),
            )
        self._api_version = config.api_version
        super().__init__(config)
        # Attached rather than baked into the headers, so the first token is fetched when
        # a request needs one and every later request gets a fresh one.
        auth = self._entra_auth(config)
        if auth is not None:
            self._client.auth = auth
        if self._api_version:
            # Older deployments still require the query parameter; newer ``/openai/v1``
            # endpoints ignore it.
            self.chat_path = f"{self.chat_path}?api-version={self._api_version}"
            self.models_path = f"{self.models_path}?api-version={self._api_version}"
            self.embeddings_path = f"{self.embeddings_path}?api-version={self._api_version}"

    def _build_headers(self, config: ProviderConfig) -> dict[str, str]:
        """Use an ``api-key`` header, and leave Entra auth to `_EntraAuth`.

        No token is acquired here. `_build_headers` runs during construction, and
        `DefaultAzureCredential` walks a chain that shells out to `az`, `pwsh`, and `azd`
        and probes the IMDS endpoint over HTTP — so building a client used to spawn
        processes and block on network timeouts before the caller had made a single
        request. It also pinned one token for the process's lifetime, which an Entra token
        outlives by about an hour.
        """
        headers = {"content-type": "application/json"}
        if config.api_key:
            headers["api-key"] = config.api_key
        headers.update({k.lower(): v for k, v in config.headers.items()})
        return headers

    def _entra_auth(self, config: ProviderConfig) -> _EntraAuth | None:
        """The per-request token source, or ``None`` when a key authenticates instead."""
        if config.api_key or not config.options.get("use_entra", True):
            return None
        return _EntraAuth(
            provider_id=self.provider_id,
            scope=str(config.options.get("scope") or FOUNDRY_SCOPE),
        )


class _EntraAuth(httpx2.Auth):
    """Acquires an Entra bearer token on first use and refreshes it before it expires.

    `DefaultAzureCredential` is expensive in a way that matters where it is called from:
    it walks a chain that spawns `az`, `pwsh`, and `azd`, and probes the IMDS endpoint
    over HTTP. Doing that at construction meant every `Client` holding an Azure provider
    paid it at startup, whether or not it ever sent a request — and the spawned probes
    outlived the call often enough to surface as unraisable `ResourceWarning`s in
    unrelated code.

    It is also blocking, so the acquisition runs in a worker thread: the credential chain
    can take seconds, and the event loop is shared with every other in-flight request.

    Attributes:
        _margin_s: How long before expiry a token is replaced. Azure reports absolute
            expiry, and a token that expires mid-flight fails a request that was already
            paid for.
    """

    _margin_s: ClassVar[float] = 300.0

    def __init__(self, *, provider_id: str, scope: str) -> None:
        self._provider_id = provider_id
        self._scope = scope
        self._token: str = ""
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def async_auth_flow(
        self, request: httpx2.Request
    ) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        """Attach a live token to one request."""
        request.headers["authorization"] = f"Bearer {await self._bearer()}"
        yield request

    async def _bearer(self) -> str:
        """The cached token, acquiring or refreshing it when it will not outlast the call.

        Raises:
            anyinfer.errors.ConfigError: The extra is missing, or the chain produced none.
        """
        async with self._lock:
            if self._token and time.time() < self._expires_at - self._margin_s:
                return self._token
            token, expires_at = await asyncio.to_thread(self._acquire)
            self._token, self._expires_at = token, expires_at
            return self._token

    def _acquire(self) -> tuple[str, float]:
        """Walk the credential chain. Blocking, and called only in a worker thread.

        Raises:
            anyinfer.errors.ConfigError: The extra is missing, or the chain produced none.
        """
        try:
            from azure.identity import DefaultAzureCredential
        except ImportError as exc:
            raise ConfigError(
                "azure-foundry needs either an API key or the azure extra for Entra auth",
                provider=self._provider_id,
                hint="pip install 'anyinfer[azure]', or set api_key",
            ) from exc

        try:
            credential = DefaultAzureCredential()
            token = credential.get_token(self._scope)
        except Exception as exc:
            raise ConfigError(
                f"could not acquire an Entra token for {self._scope}: {exc}",
                provider=self._provider_id,
                hint="run 'az login', or configure a service principal in the environment",
            ) from exc
        return str(token.token), float(getattr(token, "expires_on", 0.0) or 0.0)


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Azure exposes effort as a flat field on o-series and gpt-5-family deployments."""
    return {} if effort is None else {"reasoning_effort": effort}


_AZURE_FEATURES = (
    Feature.STREAMING
    | Feature.JSON_SCHEMA
    | Feature.JSON_MODE
    | Feature.TOOLS
    | Feature.REASONING
    | Feature.SYSTEM_PROMPT
)


descriptor = ProviderDescriptor(
    id="azure-foundry",
    display_name="Azure AI Foundry",
    aliases=("azure", "foundry"),
    factory=AzureFoundryAdapter,
    locality="hosted",
    default_base_url=None,
    requires_base_url=True,
    # No static per-model embedding capabilities: the deployment name in `model` is
    # tenant-chosen, not a fixed catalog id, so limits can't be keyed reliably. The
    # 2,048-input / 8,192-token / 300k-aggregate ceilings are documented in the module
    # docstring for callers who need them.
    operations=frozenset({"generation", "embedding"}),
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="base_url",
                label="Resource endpoint",
                kind="endpoint",
                required=True,
                help_text="The OpenAI-compatible root of your Foundry resource.",
                placeholder="https://<resource>.services.ai.azure.com/openai/v1",
            ),
            SetupField(
                key="api_key",
                label="API key",
                kind="secret",
                required=False,
                help_text="Leave empty to authenticate with Entra via azure-identity.",
                placeholder="env://AZURE_OPENAI_API_KEY or a literal key",
                env_var="AZURE_OPENAI_API_KEY",
            ),
            SetupField(
                key="api_version",
                label="API version",
                kind="api-version",
                required=False,
                advanced=True,
                help_text=(
                    "Only needed for deployments that still require it; the v1 surface does not."
                ),
                placeholder="2024-10-21",
            ),
        ),
        model_selection="discover-or-manual",
    ),
    reasoning_translator=_translate_reasoning,
    default_capabilities=ModelCapabilities(features=Sourced(_AZURE_FEATURES, "default")),
)
"""Descriptor for the Azure AI Foundry provider."""
