"""Google Vertex AI (`contracts/vertex.md`).

Vertex serves the same Gemini models as the AI Studio API, over the same
``generateContent`` protocol — the differences are entirely in *addressing* and *auth*:

- **The path carries your project and location**, rather than just a model name.
- **Auth is a Google OAuth access token**, not an API key, so it is acquired and
  refreshed rather than configured once.
- **Discovery is not offered.** Vertex has no "list the models I can call" endpoint
  comparable to the AI Studio one; the model garden is browsed in the console.

Because the wire shape is otherwise identical, this subclasses the Gemini adapter rather
than restating its translation. That is the whole reason the Gemini adapter's endpoint
construction is a separate method.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..errors import ConfigError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import DiscoveredModel, Health, ModelCapabilities, Sourced
from .base import ProviderConfig
from .cloud_auth import GoogleTokenSource
from .gemini import _GEMINI_FEATURES, GeminiAdapter, _translate_reasoning

__all__ = ["VertexAdapter", "descriptor"]

_GLOBAL_LOCATION = "global"
"""Location whose endpoint is unregioned; newer models are only served here."""


class VertexAdapter(GeminiAdapter):
    """Adapter for Gemini models served through Vertex AI."""

    def __init__(self, config: ProviderConfig) -> None:
        options = dict(config.options)
        self._project = str(options.get("project") or "")
        self._location = str(options.get("location") or _GLOBAL_LOCATION)
        if not self._project:
            raise ConfigError(
                "vertex requires the GCP project that owns the endpoint",
                provider=config.provider_id,
                hint="pass options={'project': 'my-project', 'location': 'global'}",
            )

        # An api_key here is a pre-acquired OAuth access token, not a Gemini API key —
        # the two are not interchangeable, and the setup help says so.
        self._tokens = GoogleTokenSource(
            explicit_token=config.api_key,
            options=options,
            transport=config.transport,
        )

        base_url = config.base_url or _default_base_url(self._location)
        super().__init__(
            ProviderConfig(
                provider_id=config.provider_id,
                base_url=base_url,
                api_key=None,  # Vertex authenticates per request, not per client.
                api_version=config.api_version,
                headers=config.headers,
                options=config.options,
                timeout_s=config.timeout_s,
                transport=config.transport,
                events=config.events,
            )
        )

    def _model_path(self, model: str, method: str) -> str:
        """Address a model by project and location, as Vertex requires."""
        return (
            f"/projects/{self._project}/locations/{self._location}"
            f"/publishers/google/models/{model}:{method}"
        )

    def _request_headers(self) -> dict[str, str]:
        """Attach a fresh OAuth bearer token to each request."""
        return {"authorization": f"Bearer {self._tokens.token()}"}

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """Report nothing: Vertex exposes no comparable model-listing endpoint.

        An empty listing is the honest answer. Inventing one from a hardcoded table
        would present a guess as discovery, which is exactly what the provenance rules
        exist to prevent — name the model explicitly in the target instead.
        """
        return []

    async def health(self) -> Health:
        """Report whether a token can be acquired, without spending a generation."""
        try:
            self._tokens.token()
        except Exception as exc:  # noqa: BLE001 — surfaced as unhealthy, not raised
            return Health(ok=False, detail=str(exc)[:200])
        return Health(ok=True, detail=f"{self._project}/{self._location}")


def _default_base_url(location: str) -> str:
    """Build the API root for a location.

    The ``global`` location has an unregioned host; every other location is prefixed.
    """
    if location == _GLOBAL_LOCATION:
        return "https://aiplatform.googleapis.com/v1"
    return f"https://{location}-aiplatform.googleapis.com/v1"


descriptor = ProviderDescriptor(
    id="vertex",
    display_name="Google Vertex AI",
    aliases=("vertex-ai", "google-vertex"),
    factory=VertexAdapter,
    locality="hosted",
    default_base_url=None,
    requires_base_url=False,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="project",
                label="GCP project",
                kind="text",
                required=True,
                help_text="The project that owns the Vertex endpoint.",
                placeholder="my-project-id",
            ),
            SetupField(
                key="location",
                label="Location",
                kind="text",
                required=False,
                default_value=_GLOBAL_LOCATION,
                help_text=(
                    f"Defaults to {_GLOBAL_LOCATION}. Newer models are served only from "
                    "the global endpoint."
                ),
            ),
            SetupField(
                key="api_key",
                label="Access token",
                kind="secret",
                required=False,
                advanced=True,
                help_text=(
                    "A pre-acquired OAuth access token (gcloud auth print-access-token). "
                    "Leave empty to use application default credentials. This is not a "
                    "Gemini API key."
                ),
                placeholder="gcloud auth print-access-token",
            ),
            SetupField(
                key="credentials_file",
                label="Service-account key",
                kind="path",
                required=False,
                advanced=True,
                help_text=(
                    "Path to a service-account JSON key. Defaults to "
                    "GOOGLE_APPLICATION_CREDENTIALS."
                ),
            ),
        ),
        model_selection="manual-only",
    ),
    reasoning_translator=_translate_reasoning,
    default_capabilities=ModelCapabilities(features=Sourced(_GEMINI_FEATURES, "default")),
)
"""Descriptor for the Google Vertex AI provider."""
