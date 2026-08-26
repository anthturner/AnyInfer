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

import json
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx2

from ..errors import ConfigError, ProviderError, StreamProtocolError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import DiscoveredModel, Health, ModelCapabilities, Sourced
from ..types.events import TextDelta, ToolCallDelta
from ..types.operations import (
    BatchHandle,
    BatchLine,
    BatchReport,
    BatchResult,
    BatchStatus,
    EmbeddingCapabilities,
    EmbeddingInputIntent,
)
from ..types.results import DETAIL_MAX_CHARS, Generation, ResolvedTarget, Timing, ToolCall, Usage
from ._openai_batch import batch_error
from .base import (
    AdapterFinal,
    BatchWireRequest,
    EmbeddingWireRequest,
    EmbeddingWireResult,
    ProviderConfig,
    WireRequest,
)
from .cloud_auth import GoogleTokenSource
from .gemini import _GEMINI_FEATURES, GeminiAdapter, _StreamState, _translate_reasoning
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
        self._options = options
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

    # ---- batches ---------------------------------------------------------------------
    #
    # Vertex's deferred tier is `BatchPredictionJob`, and like Bedrock's it does not carry
    # the job over the wire: input and output are JSONL objects in the *caller's own* GCS
    # bucket, referenced by URI. The bucket is account infrastructure, so it is configured
    # beside `project` and `location` rather than passed on every request. AnyInfer writes
    # the input object, submits the job, and reads the predictions back; it never creates
    # or manages the bucket.
    #
    # The lines are `generateContent` bodies, byte-identical to a live call's — this
    # adapter *is* the Gemini adapter pointed at a Vertex endpoint, so `build_payload`
    # serializes a batched line and a live one the same way.

    async def submit_batch(self, req: BatchWireRequest) -> BatchHandle:
        """Stage the lines in GCS, then create a batch-prediction job over them.

        Raises:
            anyinfer.errors.ConfigError: The batch bucket is not configured.
            anyinfer.errors.ProviderError: The upload or the submission was refused.
        """
        prefix = self._batch_prefix()
        job_name = f"anyinfer-{uuid.uuid4().hex[:24]}"
        input_uri = f"{prefix}/{job_name}/input.jsonl"
        output_prefix = f"{prefix}/{job_name}/out"

        jsonl = "\n".join(
            # `custom_id` is not a Vertex field. It rides in the request body, which the
            # predictions file echoes back verbatim, because that is the only channel the
            # API leaves for correlating an answer with the row that asked for it.
            json.dumps(
                {
                    "request": {
                        **self._batch_body(line),
                        "labels": {_LINE_ID_LABEL: custom_id},
                    }
                }
            )
            for custom_id, line in req.lines
        )
        await self._put_object(input_uri, jsonl.encode("utf-8"))

        payload: dict[str, Any] = {
            "displayName": job_name,
            "model": f"publishers/google/models/{req.model}",
            "inputConfig": {
                "instancesFormat": "jsonl",
                "gcsSource": {"uris": [input_uri]},
            },
            "outputConfig": {
                "predictionsFormat": "jsonl",
                "gcsDestination": {"outputUriPrefix": output_prefix},
            },
        }
        if req.metadata:
            payload["labels"] = dict(req.metadata)
        body = await self._job_call("POST", self._jobs_path(), payload)
        return BatchHandle(
            batch_id=str(body.get("name", "")),
            provider_id=self.provider_id,
            model=req.model,
            line_count=len(req.lines),
            submitted_at=time.time(),
            line_ids=tuple(custom_id for custom_id, _ in req.lines),
            # Vertex writes the predictions under a timestamped directory it names itself,
            # so the exact object is only knowable after the job reports its output info.
            # The prefix is what can be recorded now, and fetch resolves the rest.
            provider_state={"output_prefix": output_prefix},
        )

    def _batch_body(self, line: WireRequest) -> dict[str, Any]:
        """One line's request body: the live `generateContent` shape."""
        return self.build_payload(line)

    def _batch_prefix(self) -> str:
        """Read the caller's batch bucket prefix.

        Raises:
            anyinfer.errors.ConfigError: It is missing or malformed.
        """
        prefix = str(self._options.get("batch_gcs_uri") or "").rstrip("/")
        if not prefix:
            raise ConfigError(
                "vertex batches need a caller-owned GCS prefix",
                provider=self.provider_id,
                hint=(
                    "set options={'batch_gcs_uri': 'gs://my-bucket/anyinfer'} — the "
                    "bucket is yours, and AnyInfer neither creates nor manages it"
                ),
            )
        if not prefix.startswith("gs://"):
            raise ConfigError(
                f"batch_gcs_uri must be a gs:// URI, not {prefix!r}",
                provider=self.provider_id,
            )
        return prefix

    def _jobs_path(self) -> str:
        """The batch-prediction collection for this project and location."""
        return f"/projects/{self._project}/locations/{self._location}/batchPredictionJobs"

    async def batch_status(self, handle: BatchHandle) -> BatchReport:
        """Report state from the job resource."""
        return self._report(handle, await self._job_call("GET", f"/{handle.batch_id}"))

    async def cancel_batch(self, handle: BatchHandle) -> BatchReport:
        """Cancel a job, then report where it landed."""
        await self._job_call("POST", f"/{handle.batch_id}:cancel", {})
        return self._report(handle, await self._job_call("GET", f"/{handle.batch_id}"))

    def _report(self, handle: BatchHandle, body: Mapping[str, Any]) -> BatchReport:
        """Normalize one job resource into a report.

        Vertex reports completion stats only once a job finishes, so counts stay zero
        while it runs rather than being guessed at.
        """
        stats = body.get("completionStats")
        stats = stats if isinstance(stats, Mapping) else {}
        error = body.get("error")
        detail = str(error.get("message", "")) if isinstance(error, Mapping) else ""
        return BatchReport(
            handle=handle,
            status=_VERTEX_BATCH_STATUSES.get(str(body.get("state", "")), "in_progress"),
            completed=int(stats.get("successfulCount", 0) or 0),
            failed=int(stats.get("failedCount", 0) or 0),
            detail=detail[:DETAIL_MAX_CHARS],
        )

    async def fetch_batch(self, handle: BatchHandle) -> BatchResult:
        """Read the predictions back out of GCS and parse them.

        Raises:
            anyinfer.errors.ProviderError: The job has not finished, or the read failed.
        """
        body = await self._job_call("GET", f"/{handle.batch_id}")
        report = self._report(handle, body)
        if not report.finished:
            raise ProviderError(
                f"batch {handle.batch_id} is {report.status}, not finished",
                provider=self.provider_id,
                retryable=True,
                hint="poll batch_status until it reports finished",
            )
        directory = _output_directory(body) or handle.provider_state.get("output_prefix", "")
        if not directory:
            raise ProviderError(
                "the finished job reports no output location",
                provider=self.provider_id,
                hint="fetch a batch with the handle submit_batch returned",
            )
        text = await self._get_object(f"{directory.rstrip('/')}/predictions.jsonl")
        return BatchResult(
            handle=handle, status=report.status, lines=tuple(self._parse_lines(text))
        )

    def _parse_lines(self, jsonl: str) -> Iterable[BatchLine]:
        """Parse the predictions file, one entry per submitted line.

        One file, not two: a rejected line arrives beside an accepted one carrying a
        `status` string where the answer would be.
        """
        for raw in jsonl.splitlines():
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(entry, Mapping):
                continue
            custom_id = _echoed_line_id(entry)
            response = entry.get("response")
            failure = entry.get("status")
            if failure or not isinstance(response, Mapping):
                yield BatchLine(
                    custom_id=custom_id,
                    error=batch_error(
                        self.provider_id,
                        str(failure or "the provider rejected this line without a message"),
                    ),
                )
                continue
            yield BatchLine(custom_id=custom_id, result=self.generation_from_batch_body(response))

    def generation_from_batch_body(self, body: Mapping[str, Any]) -> Generation:
        """Assemble a `Generation` from one answered prediction.

        Read through `_events_from_chunk`, the same reader the live path uses, so a
        batched answer carries the text, tool calls, usage, and finish reason a live one
        would rather than through a second parser that can drift from it.

        Assembled here rather than through the router's attempt buffer: an adapter must not
        import from `anyinfer.routing` — the "adapters never orchestrate" contract enforces
        exactly that — and a prediction has nothing to orchestrate.
        """
        text: list[str] = []
        calls: list[ToolCall] = []
        state = _StreamState()
        final: AdapterFinal | None = None
        for event in self._events_from_chunk(body, state):
            if isinstance(event, TextDelta):
                text.append(event.text)
            elif isinstance(event, ToolCallDelta):
                calls.append(
                    ToolCall(
                        id=event.call_id or "",
                        name=event.name or "",
                        arguments=_vertex_tool_arguments(event.arguments_fragment),
                    )
                )
            elif isinstance(event, AdapterFinal):
                final = event
        final = final or state.finalize()
        usage = final.usage or Usage()
        return Generation(
            text="".join(text),
            structured=None,
            tool_calls=tuple(calls),
            target=ResolvedTarget(provider_id=self.provider_id, model=""),
            finish_reason=final.finish_reason,
            usage=usage.normalized(),
            timing=Timing(started_at=0.0, total_ms=0.0),
        )

    # ---- the two Google surfaces a batch needs beyond generateContent ------------------

    async def _job_call(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        """Issue one batch-prediction request against the aiplatform API.

        Raises:
            anyinfer.errors.ProviderError: The call failed or returned a non-object body.
        """
        try:
            response = await self._client.request(
                method, path, json=payload, headers=self._request_headers()
            )
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="generate") from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=read_error_detail(response.content),
                phase="generate",
            )
        parsed = response.json() if response.content else {}
        if not isinstance(parsed, Mapping):
            raise StreamProtocolError(
                "vertex returned a non-object batch body", provider=self.provider_id
            )
        return parsed

    async def _put_object(self, uri: str, body: bytes) -> None:
        """Write one GCS object with the same OAuth token the API uses.

        Raises:
            anyinfer.errors.ProviderError: The write was refused.
        """
        bucket, key = _split_gs_uri(uri)
        url = (
            f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"
            f"?uploadType=media&name={quote(key, safe='')}"
        )
        headers = {
            "authorization": f"Bearer {self._tokens.token()}",
            "content-type": "application/jsonl",
        }
        try:
            response = await self._client.post(url, content=body, headers=headers)
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="generate") from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=read_error_detail(response.content),
                phase="generate",
            )

    async def _get_object(self, uri: str) -> str:
        """Read one GCS object back.

        Raises:
            anyinfer.errors.ProviderError: The read was refused.
        """
        bucket, key = _split_gs_uri(uri)
        url = (
            f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/"
            f"{quote(key, safe='')}?alt=media"
        )
        headers = {"authorization": f"Bearer {self._tokens.token()}"}
        try:
            response = await self._client.get(url, headers=headers)
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="generate") from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=read_error_detail(response.content),
                phase="generate",
            )
        return response.text

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


_LINE_ID_LABEL = "anyinfer_line_id"
"""Where a submitted line's custom id rides.

Vertex has no `custom_id` concept and returns predictions in an order it does not
promise, so the id travels in the request body's own labels — which the predictions file
echoes back verbatim. That echo is the only channel the API leaves for pairing an answer
with the row that asked for it.
"""

_VERTEX_BATCH_STATUSES: Mapping[str, BatchStatus] = {
    "JOB_STATE_QUEUED": "queued",
    "JOB_STATE_PENDING": "queued",
    "JOB_STATE_RUNNING": "in_progress",
    "JOB_STATE_CANCELLING": "in_progress",
    "JOB_STATE_UPDATING": "in_progress",
    "JOB_STATE_SUCCEEDED": "completed",
    "JOB_STATE_PARTIALLY_SUCCEEDED": "completed",
    "JOB_STATE_FAILED": "failed",
    "JOB_STATE_CANCELLED": "cancelled",
    "JOB_STATE_EXPIRED": "expired",
}
"""Vertex's job states, normalized onto the one vocabulary a caller polls.

`PARTIALLY_SUCCEEDED` maps to completed rather than failed for the same reason Bedrock's
does: the job finished, the predictions are readable, and the lines that failed are
reported as failed lines. A whole-batch `failed` would discard the answers that arrived.
"""


def _split_gs_uri(uri: str) -> tuple[str, str]:
    """Split ``gs://bucket/key`` into its two halves for the JSON API's path shape."""
    bucket, _, key = uri[len("gs://") :].partition("/")
    return bucket, key


def _output_directory(job: Mapping[str, Any]) -> str:
    """Where a finished job actually wrote, which is not the prefix it was given.

    Vertex appends a timestamped directory of its own naming under the requested prefix
    and reports the result in `outputInfo`. Guessing the name would work until it did
    not; the handle's prefix is the fallback for a job that reports nothing.
    """
    info = job.get("outputInfo")
    if isinstance(info, Mapping):
        directory = info.get("gcsOutputDirectory")
        if isinstance(directory, str) and directory:
            return directory
    return ""


def _echoed_line_id(entry: Mapping[str, Any]) -> str:
    """Recover a prediction's submitted id from the request Vertex echoes back."""
    request = entry.get("request")
    labels = request.get("labels") if isinstance(request, Mapping) else None
    if isinstance(labels, Mapping):
        return str(labels.get(_LINE_ID_LABEL, ""))
    return ""


def _vertex_tool_arguments(raw: str) -> Mapping[str, Any]:
    """Parse one batched tool call's arguments, tolerating a provider that sent none."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


descriptor = ProviderDescriptor(
    id="vertex",
    display_name="Google Vertex AI",
    aliases=("vertex-ai", "google-vertex"),
    factory=VertexAdapter,
    locality="hosted",
    default_base_url=None,
    requires_base_url=False,
    operations=frozenset({"generation", "embedding", "batch"}),
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
