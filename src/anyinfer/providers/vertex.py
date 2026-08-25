"""Google Vertex AI (`contracts/vertex.md`).

Vertex serves the same Gemini models as the AI Studio API, over the same
``generateContent`` protocol — the differences are entirely in *addressing* and *auth*:

- **The path carries your project and location**, rather than just a model name.
- **Auth is a Google OAuth access token**, not an API key, so it is acquired and
  refreshed rather than configured once.
- **Discovery is not offered.** Vertex has no "list the models I can call" endpoint
  comparable to the AI Studio one; the model garden is browsed in the console.

Because the generation wire shape is otherwise identical, this subclasses the Gemini
adapter rather than restating its translation. That is the whole reason the Gemini
adapter's endpoint construction is a separate method.

Embeddings are **not** inherited: Gemini's own API embeds through
``:batchEmbedContents``, but Vertex's text-embeddings how-to (fetched live 2026-08-12,
cloud.google.com/vertex-ai/generative-ai/docs/model-reference/text-embeddings-api)
documents a single ``:predict`` endpoint for every embedding model it lists —
``gemini-embedding-001``, ``text-embedding-005``, ``text-multilingual-embedding-002``,
and the legacy ``textembedding-gecko@001`` — with an ``instances``/``parameters`` body
distinct from ``batchEmbedContents``. (The API reference navigation also lists an
``embedContent`` method under ``publishers.models``, but the how-to guide — the
authoritative source for what's actually documented and supported — describes only
``:predict`` for text embeddings; noted in the contract watchlist rather than assumed.)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx2

from ..errors import ConfigError, ProviderError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import DiscoveredModel, Health, ModelCapabilities, Sourced
from ..types.operations import EmbeddingCapabilities, EmbeddingInputIntent
from ..types.results import Usage
from .base import EmbeddingWireRequest, EmbeddingWireResult, ProviderConfig
from .cloud_auth import GoogleTokenSource
from .gemini import _GEMINI_FEATURES, GeminiAdapter, _translate_reasoning
from .http import check_response_size, classify_status, map_transport_error, read_error_detail

__all__ = ["VertexAdapter", "descriptor"]

_GLOBAL_LOCATION = "global"
"""Location whose endpoint is unregioned; newer models are only served here."""

_TASK_TYPES: Mapping[EmbeddingInputIntent, str] = {
    "query": "RETRIEVAL_QUERY",
    "document": "RETRIEVAL_DOCUMENT",
    "classification": "CLASSIFICATION",
    "clustering": "CLUSTERING",
}
"""Normalized intents mapped to Vertex's ``task_type`` values (verified 2026-08-12).

Vertex's vocabulary is larger (also SEMANTIC_SIMILARITY, QUESTION_ANSWERING,
FACT_VERIFICATION, CODE_RETRIEVAL_QUERY) but only these four have a normalized
counterpart; the rest are reachable through ``provider_options`` if a caller needs them.
"""


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
            proxy=config.proxy,
            verify=config.verify,
            client_cert=config.client_cert,
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
                proxy=config.proxy,
                verify=config.verify,
                client_cert=config.client_cert,
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

    async def embed(self, req: EmbeddingWireRequest) -> EmbeddingWireResult:
        """Run one embedding call against ``:predict``.

        Every Vertex embedding model documents this endpoint, not Gemini's
        ``batchEmbedContents`` — see the module docstring. One instance per input; the
        core's batching policy is what keeps a request within a model's real
        ``max_batch_inputs`` (declared per model below).
        """
        instance_extra: dict[str, Any] = {}
        if req.input_type is not None:
            instance_extra["task_type"] = _TASK_TYPES[req.input_type]
        instances = [{"content": text, **instance_extra} for text in req.inputs]

        parameters: dict[str, Any] = {}
        if req.dimensions is not None:
            parameters["outputDimensionality"] = req.dimensions

        payload: dict[str, Any] = {"instances": instances}
        if parameters:
            payload["parameters"] = parameters
        payload.update(req.extra_options)

        path = self._model_path(req.model, "predict")
        try:
            response = await self._client.post(
                path, json=payload, timeout=req.timeout_s, headers=self._request_headers()
            )
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id) from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=read_error_detail(response.content),
                headers=response.headers,
            )
        check_response_size(response.content, req.max_response_bytes, provider=self.provider_id)
        return self._parse_embed_response(req, response.json())

    def _parse_embed_response(
        self, req: EmbeddingWireRequest, payload: Any
    ) -> EmbeddingWireResult:
        if not isinstance(payload, Mapping):
            raise ProviderError("predict response is not a JSON object", phase="validate")
        predictions = payload.get("predictions")
        if not isinstance(predictions, list):
            raise ProviderError(
                "predict response is missing a 'predictions' array", phase="validate"
            )
        if len(predictions) != len(req.inputs):
            raise ProviderError(
                f"predict response returned {len(predictions)} predictions for "
                f"{len(req.inputs)} inputs",
                phase="validate",
            )

        vectors: list[tuple[float, ...]] = []
        total_tokens = 0
        saw_token_count = False
        for entry in predictions:
            embeddings = entry.get("embeddings") if isinstance(entry, Mapping) else None
            values = embeddings.get("values") if isinstance(embeddings, Mapping) else None
            if not isinstance(values, list):
                raise ProviderError(
                    "predict response entry is missing 'embeddings.values'", phase="validate"
                )
            vectors.append(tuple(float(v) for v in values))

            statistics = embeddings.get("statistics") if isinstance(embeddings, Mapping) else None
            token_count = (
                statistics.get("token_count") if isinstance(statistics, Mapping) else None
            )
            if isinstance(token_count, int) and not isinstance(token_count, bool):
                total_tokens += token_count
                saw_token_count = True

        usage = Usage(input_tokens=total_tokens) if saw_token_count else None

        return EmbeddingWireResult(
            vectors=tuple(vectors),
            dimensions=len(vectors[0]) if vectors else None,
            usage=usage,
            raw=payload,
        )


def _default_base_url(location: str) -> str:
    """Build the API root for a location.

    The ``global`` location has an unregioned host; every other location is prefixed.
    """
    if location == _GLOBAL_LOCATION:
        return "https://aiplatform.googleapis.com/v1"
    return f"https://{location}-aiplatform.googleapis.com/v1"


_STATIC_EMBEDDING_CAPABILITIES = {
    # Verified live 2026-08-12 against cloud.google.com/vertex-ai/generative-ai/docs/
    # model-reference/text-embeddings-api: "Limit: five texts of up to 2,048 tokens per
    # text for all models except textembedding-gecko@001 ... For gemini-embedding-001,
    # each request can only include a single input text."
    "gemini-embedding-001": EmbeddingCapabilities(
        dimensions=3_072,
        max_batch_inputs=1,
        max_input_tokens=2_048,
        input_intents=("query", "document", "classification", "clustering"),
    ),
    "text-embedding-005": EmbeddingCapabilities(
        dimensions=768,
        max_batch_inputs=5,
        max_input_tokens=2_048,
        input_intents=("query", "document", "classification", "clustering"),
    ),
    "text-multilingual-embedding-002": EmbeddingCapabilities(
        dimensions=768,
        max_batch_inputs=5,
        max_input_tokens=2_048,
        input_intents=("query", "document", "classification", "clustering"),
    ),
    "textembedding-gecko@001": EmbeddingCapabilities(
        max_batch_inputs=5,
        max_input_tokens=3_072,
        input_intents=("query", "document", "classification", "clustering"),
    ),
}


descriptor = ProviderDescriptor(
    id="vertex",
    display_name="Google Vertex AI",
    aliases=("vertex-ai", "google-vertex"),
    factory=VertexAdapter,
    locality="hosted",
    default_base_url=None,
    requires_base_url=False,
    operations=frozenset({"generation", "embedding"}),
    # Same encoder as Gemini, because this adapter *is* the Gemini adapter pointed at a
    # Vertex endpoint; the tools are Google's, not the API surface's.
    server_tools=frozenset({"web_search", "code_execution"}),
    static_embedding_capabilities=_STATIC_EMBEDDING_CAPABILITIES,
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
