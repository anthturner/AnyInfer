"""Azure AI Foundry (`contracts/azure-foundry.md`).

An ``openai-compat`` subclass with three Azure-specific differences:

- the output-token parameter is ``max_completion_tokens``, not ``max_tokens``;
- reasoning effort is a flat ``reasoning_effort`` field;
- authentication may be an ``api-key`` header *or* an Entra bearer token obtained through
  ``azure-identity`` (the ``[azure]`` extra).

Everything else — request shaping, SSE parsing, error mapping — is inherited, which is the
point of having a base dialect at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from ..errors import ConfigError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import Feature, ModelCapabilities, Sourced
from ..types.requests import ReasoningEffort
from .base import ProviderConfig
from .openai_compat import OpenAICompatAdapter

__all__ = ["FOUNDRY_SCOPE", "AzureFoundryAdapter", "descriptor"]

FOUNDRY_SCOPE = "https://ai.azure.com/.default"
"""Entra token scope for Foundry, as recorded in the contract snapshot."""


class AzureFoundryAdapter(OpenAICompatAdapter):
    """Adapter for Azure AI Foundry deployments."""

    output_tokens_field: ClassVar[str] = "max_completion_tokens"
    """Azure renamed this parameter; sending ``max_tokens`` is rejected."""

    def __init__(self, config: ProviderConfig) -> None:
        if not config.base_url:
            raise ConfigError(
                "azure-foundry requires the base URL of your Foundry resource",
                provider=config.provider_id,
                hint=(
                    "for example "
                    "https://<resource>.services.ai.azure.com/openai/v1"
                ),
            )
        self._api_version = config.api_version
        super().__init__(config)
        if self._api_version:
            # Older deployments still require the query parameter; newer ``/openai/v1``
            # endpoints ignore it.
            self.chat_path = f"{self.chat_path}?api-version={self._api_version}"
            self.models_path = f"{self.models_path}?api-version={self._api_version}"

    def _build_headers(self, config: ProviderConfig) -> dict[str, str]:
        """Use an ``api-key`` header, or acquire an Entra token when no key is set."""
        headers = {"content-type": "application/json"}

        if config.api_key:
            headers["api-key"] = config.api_key
        else:
            token = self._acquire_entra_token(config)
            if token:
                headers["authorization"] = f"Bearer {token}"

        headers.update({k.lower(): v for k, v in config.headers.items()})
        return headers

    def _acquire_entra_token(self, config: ProviderConfig) -> str | None:
        """Obtain a bearer token through ``azure-identity``.

        Raises:
            ConfigError: If the ``[azure]`` extra is missing, or the credential chain
                cannot produce a token.
        """
        options = config.options
        if not options.get("use_entra", True):
            return None

        try:
            from azure.identity import DefaultAzureCredential
        except ImportError as exc:
            raise ConfigError(
                "azure-foundry needs either an API key or the azure extra for Entra auth",
                provider=self.provider_id,
                hint="pip install 'anyinfer[azure]', or set api_key",
            ) from exc

        scope = str(options.get("scope") or FOUNDRY_SCOPE)
        try:
            credential = DefaultAzureCredential()
            token = credential.get_token(scope)
        except Exception as exc:
            raise ConfigError(
                f"could not acquire an Entra token for {scope}: {exc}",
                provider=self.provider_id,
                hint="run 'az login', or configure a service principal in the environment",
            ) from exc
        return str(token.token)


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
                    "Only needed for deployments that still require it; the v1 surface "
                    "does not."
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
