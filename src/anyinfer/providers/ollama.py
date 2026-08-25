"""Ollama's native API (`contracts/ollama.md`).

Deliberately the **native** ``/api/chat`` dialect rather than Ollama's ``/v1``
OpenAI-compatibility layer. The native API is strictly more capable for our purposes: it
carries grammar-enforced structured output via ``format``, per-phase nanosecond timings,
``keep_alive`` session retention, and reasoning via ``think``, and the ``/v1`` layer
*silently discards* parameters it does not implement, which is the failure mode AnyInfer
exists to eliminate.

Framing is NDJSON, not SSE.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from contextlib import aclosing
from typing import Any, ClassVar

import httpx2

from ..errors import ModelNotFoundError, ProviderError, StreamProtocolError
from ..registry import (
    HostShorthand,
    ProviderDescriptor,
    ProviderSetupSpec,
    SetupField,
)
from ..schema.project import repetition_safe_projection
from ..types.capabilities import (
    DiscoveredModel,
    Feature,
    Health,
    LocalModelInfo,
    ModelCapabilities,
    Sourced,
)
from ..types.events import ReasoningDelta, TextDelta, ToolCallDelta
from ..types.messages import (
    AudioPart,
    DocumentPart,
    ImagePart,
    Message,
    Text,
    ToolCall,
    ToolResult,
)
from ..types.requests import ReasoningEffort, Sampling, ToolSpec
from ..types.results import Diagnostic, FinishReason, Usage
from ._multimodal import base64_data, unsupported
from .base import (
    AdapterEvent,
    AdapterFinal,
    EmbeddingWireRequest,
    EmbeddingWireResult,
    ProviderConfig,
    WireRequest,
    _encode_function_tool,
)
from .http import (
    build_client,
    check_response_size,
    classify_status,
    map_transport_error,
    read_error_detail,
)
from .sse import iter_ndjson

__all__ = ["SESSION_KEEP_ALIVE", "OllamaAdapter", "descriptor"]

_DEFAULT_BASE_URL = "http://127.0.0.1:11434"

_DONE_REASONS: Mapping[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "load": "other",
}

_NS_PER_MS = 1_000_000.0

SESSION_KEEP_ALIVE = "10m"
"""How long an open session asks Ollama to keep the model resident.

What a session buys here is residency, not conversation: Ollama holds no chat state, but
it does unload an idle model, and reloading eight gigabytes of weights between two turns of
one conversation is the cost worth removing. Ten minutes is long enough to cover a person
thinking and short enough that an abandoned session releases the memory on its own — which
is also why closing a session sends nothing: the timer is the release mechanism.
"""

_SPILL_THRESHOLD = 0.95
"""VRAM residency below which a loaded model is reported as spilled.

Not 1.0: Ollama's own reported sizes wobble by a few megabytes between the weights it
counts and the allocation it makes, and a diagnostic that fires on every healthy load is
one every caller learns to ignore.
"""


class OllamaAdapter:
    """Adapter for a local or proxied Ollama server."""

    provider_id: ClassVar[str] = "ollama"

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        headers: dict[str, str] = {"content-type": "application/json"}
        if config.api_key:
            headers["authorization"] = f"Bearer {config.api_key}"
        headers.update({k.lower(): v for k, v in config.headers.items()})
        self._client = build_client(
            base_url=(config.base_url or _DEFAULT_BASE_URL).rstrip("/"),
            headers=headers,
            timeout_s=config.timeout_s,
            transport=config.transport,
            proxy=config.proxy,
            verify=config.verify,
            client_cert=config.client_cert,
        )

    @staticmethod
    def project_schema(schema: Mapping[str, Any]) -> Mapping[str, Any]:
        """Strip grammar-hostile constraints before sending as ``format``.

        Ollama compiles ``format`` to a decoding grammar, so string-length and huge array
        bounds blow up into unusable repetition rules. The original schema still validates
        the response client-side, so nothing is actually relaxed for the caller.
        """
        return repetition_safe_projection(schema)

    # ---- discovery -------------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """List installed models from ``GET /api/tags``, with their artifact metadata."""
        try:
            response = await self._client.get("/api/tags")
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="discover") from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=read_error_detail(response.content),
                headers=response.headers,
                phase="discover",
            )

        payload = response.json()
        entries = payload.get("models") if isinstance(payload, Mapping) else None
        if not isinstance(entries, list):
            return []

        models: list[DiscoveredModel] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            name = str(entry.get("name") or entry.get("model") or "")
            if not name:
                continue
            models.append(
                DiscoveredModel(id=name, capabilities=self._capabilities_from_tag(entry))
            )
        return models

    def _capabilities_from_tag(self, entry: Mapping[str, Any]) -> ModelCapabilities:
        """Read what ``/api/tags`` actually reports, tagged ``discovered``."""
        details = entry.get("details")
        parameter_size = None
        quantization = None
        if isinstance(details, Mapping):
            raw_params = details.get("parameter_size")
            parameter_size = str(raw_params) if raw_params else None
            raw_quant = details.get("quantization_level")
            quantization = str(raw_quant) if raw_quant else None

        size = entry.get("size")
        return ModelCapabilities(
            features=Sourced(_OLLAMA_FEATURES, "discovered"),
            local=LocalModelInfo(
                artifact_size_bytes=size if isinstance(size, int) else None,
                parameter_size=parameter_size,
                quantization=quantization,
            ),
        )

    async def health(self) -> Health:
        """Probe ``GET /api/tags`` — Ollama answers it even with no models installed."""
        try:
            response = await self._client.get("/api/tags")
        except httpx2.HTTPError as exc:
            return Health(
                ok=False,
                detail=f"cannot reach the Ollama server: {exc}"[:200],
            )
        if response.status_code >= 400:
            return Health(ok=False, detail=f"HTTP {response.status_code}")
        return Health(ok=True)

    async def loaded_models(self) -> Mapping[str, int | None]:
        """Read ``GET /api/ps``: which models are resident, and their VRAM footprint.

        A provider-specific extension beyond the four-method adapter contract, for
        applications that want residency detail. GPU spill is the signal to watch — a
        model loaded with ``size_vram`` well below its total size is running partly on
        the CPU and will be dramatically slower than expected. `diagnostics()` reports
        exactly that condition without the caller having to do the arithmetic.
        """
        return {name: vram for name, (_total, vram) in (await self._residency()).items()}

    async def diagnostics(self) -> Sequence[Diagnostic]:
        """Report resident models that spilled out of VRAM.

        The failure this exists for is not a failure at all from the wire's point of
        view: the request succeeds, the answer is correct, and it took thirty times as
        long as the same model took yesterday because it no longer fits alongside
        whatever else the GPU is holding. Nothing in a `Generation` explains that. This
        does.

        Reads ``/api/ps`` only — the same endpoint `loaded_models()` uses, no generation
        cost, and reports nothing at all when the server is unreachable or too old to
        answer, because an advisory that guesses is worse than one that stays quiet.
        """
        reports: list[Diagnostic] = []
        for name, (total, vram) in sorted((await self._residency()).items()):
            if total is None or vram is None or total <= 0:
                continue
            if vram >= total:
                continue
            resident = vram / total
            if resident >= _SPILL_THRESHOLD:
                continue
            reports.append(
                Diagnostic(
                    code="ollama.gpu-spill",
                    severity="warning",
                    message=(
                        f"{name} is only {resident:.0%} resident in VRAM; the rest runs on "
                        "the CPU, which is far slower. Free GPU memory, or choose a "
                        "smaller model or quantization."
                    ),
                )
            )
        return tuple(reports)

    async def _residency(self) -> Mapping[str, tuple[int | None, int | None]]:
        """Read ``/api/ps`` into ``model -> (total_bytes, vram_bytes)``.

        Every failure resolves to "nothing is known": an unreachable server, an error
        status, or a payload shape this does not recognize all mean the caller learns
        nothing, never that the caller learns something wrong.
        """
        try:
            response = await self._client.get("/api/ps")
        except httpx2.HTTPError:
            return {}
        if response.status_code >= 400:
            return {}
        payload = response.json()
        entries = payload.get("models") if isinstance(payload, Mapping) else None
        if not isinstance(entries, list):
            return {}
        loaded: dict[str, tuple[int | None, int | None]] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            name = str(entry.get("name") or entry.get("model") or "")
            if not name:
                continue
            total = entry.get("size")
            vram = entry.get("size_vram")
            loaded[name] = (
                total if isinstance(total, int) else None,
                vram if isinstance(vram, int) else None,
            )
        return loaded

    # ---- generation ------------------------------------------------------------------

    async def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]:
        """Run one generation against ``POST /api/chat``."""
        payload = self.build_payload(req)
        try:
            async with self._client.stream(
                "POST", "/api/chat", json=payload, timeout=req.timeout_s
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise self._classify(response.status_code, body, response.headers, req)

                state = _StreamState()
                # `aclosing`: an early close of this generator must also close the NDJSON
                # parser's, or it and the open connection are left to finalize during GC
                # instead of closing deterministically.
                async with aclosing(
                    iter_ndjson(
                        response.aiter_bytes(),
                        max_bytes=req.max_response_bytes,
                        provider=self.provider_id,
                    )
                ) as messages:
                    async for message in messages:
                        for event in self._events_from_message(message, state):
                            yield event
                yield state.finalize(session_state=req.session_state)
        except (ProviderError, StreamProtocolError):
            raise
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="stream") from exc

    def _classify(
        self,
        status: int,
        body: bytes,
        headers: Mapping[str, str],
        req: WireRequest | EmbeddingWireRequest,
    ) -> ProviderError:
        """Map an Ollama error, distinguishing "model not pulled" from other 404s.

        Shared between generation and embedding calls — both wire request shapes carry
        ``model``, which is all this needs to build the pull hint.
        """
        detail = read_error_detail(body)
        if status == 404 and "not found" in detail.lower():
            return ModelNotFoundError(
                detail,
                provider=self.provider_id,
                http_status=status,
                hint=f"pull it first: ollama pull {req.model}",
            )
        return classify_status(status, provider=self.provider_id, detail=detail, headers=headers)

    def build_payload(self, req: WireRequest) -> dict[str, Any]:
        """Translate a wire request into an ``/api/chat`` body."""
        payload: dict[str, Any] = {
            "model": req.model,
            "messages": [self._encode_message(m) for m in req.messages],
            "stream": True,
        }

        options = self._encode_options(req.sampling)
        if options:
            payload["options"] = options

        if req.mechanism in ("grammar", "json_schema") and req.wire_schema is not None:
            payload["format"] = dict(req.wire_schema)
        elif req.mechanism == "json_mode":
            payload["format"] = "json"

        if req.tools:
            payload["tools"] = [self._encode_tool(t) for t in req.tools]

        keep_alive = _session_keep_alive(req)
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        payload.update(req.reasoning_wire)
        # The caller's own options win: an explicit keep_alive is a deliberate choice
        # about *their* machine's memory, and a session must not quietly override it.
        payload.update(req.extra_options)
        return payload

    def _encode_options(self, sampling: Sampling) -> dict[str, Any]:
        """Map sampling onto Ollama's ``options`` block, omitting anything unset."""
        options: dict[str, Any] = {}
        if sampling.temperature is not None:
            options["temperature"] = sampling.temperature
        if sampling.top_p is not None:
            options["top_p"] = sampling.top_p
        if sampling.max_output_tokens is not None:
            options["num_predict"] = sampling.max_output_tokens
        if sampling.stop:
            options["stop"] = list(sampling.stop)
        if sampling.seed is not None:
            options["seed"] = sampling.seed
        if sampling.presence_penalty is not None:
            options["presence_penalty"] = sampling.presence_penalty
        if sampling.frequency_penalty is not None:
            options["frequency_penalty"] = sampling.frequency_penalty
        return options

    def _encode_message(self, message: Message) -> dict[str, Any]:
        results = [p for p in message.content if isinstance(p, ToolResult)]
        if results:
            return {"role": "tool", "content": results[0].content}

        encoded: dict[str, Any] = {
            "role": message.role,
            "content": "".join(p.text for p in message.content if isinstance(p, Text)),
        }
        images: list[str] = []
        for part in message.content:
            if isinstance(part, ImagePart):
                if part.data is None:
                    raise unsupported(
                        self.provider_id, "remote image", "inline bytes are required"
                    )
                images.append(base64_data(part.data))
            elif isinstance(part, DocumentPart):
                raise unsupported(self.provider_id, "document")
            elif isinstance(part, AudioPart):
                raise unsupported(self.provider_id, "audio")
        if images:
            encoded["images"] = images
        calls = [p for p in message.content if isinstance(p, ToolCall)]
        if calls:
            encoded["tool_calls"] = [
                {"function": {"name": c.name, "arguments": dict(c.arguments)}} for c in calls
            ]
        return encoded

    def _encode_tool(self, tool: ToolSpec) -> dict[str, Any]:
        return _encode_function_tool(tool)

    def _events_from_message(self, message: Any, state: _StreamState) -> Iterable[AdapterEvent]:
        """Translate one NDJSON object into events."""
        if not isinstance(message, Mapping):
            return

        error = message.get("error")
        if isinstance(error, str) and error:
            raise ProviderError(error, provider=self.provider_id)

        chat = message.get("message")
        if isinstance(chat, Mapping):
            thinking = chat.get("thinking")
            if isinstance(thinking, str) and thinking:
                yield ReasoningDelta(thinking)

            content = chat.get("content")
            if isinstance(content, str) and content:
                yield TextDelta(content)

            calls = chat.get("tool_calls")
            if isinstance(calls, list):
                for call in calls:
                    if not isinstance(call, Mapping):
                        continue
                    function = call.get("function")
                    if not isinstance(function, Mapping):
                        continue
                    arguments = function.get("arguments")
                    fragment = (
                        json.dumps(dict(arguments))
                        if isinstance(arguments, Mapping)
                        else str(arguments or "")
                    )
                    # Ollama emits whole calls rather than fragments, so each one occupies
                    # its own slot in arrival order.
                    index = state.next_tool_index()
                    yield ToolCallDelta(
                        index=index,
                        call_id=f"call_{index}",
                        name=str(function.get("name", "")),
                        arguments_fragment=fragment,
                    )

        if message.get("done") is True:
            state.absorb_final(message)

    # ---- embeddings ------------------------------------------------------------------

    async def embed(self, req: EmbeddingWireRequest) -> EmbeddingWireResult:
        """Run one embedding call against ``POST /api/embed``.

        See ``contracts/ollama.md`` for the verified request/response fields. Batch input
        is native to this endpoint — every text in one request is sent as one array, not
        simulated with repeated calls.
        """
        payload = self._build_embedding_payload(req)
        try:
            response = await self._client.post(
                "/api/embed", json=payload, timeout=req.timeout_s
            )
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="generate") from exc
        if response.status_code >= 400:
            body = response.content
            raise self._classify(response.status_code, body, response.headers, req)
        check_response_size(response.content, req.max_response_bytes, provider=self.provider_id)
        return self._parse_embedding_response(req, response.json())

    def _build_embedding_payload(self, req: EmbeddingWireRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": req.model,
            "input": list(req.inputs) if len(req.inputs) != 1 else req.inputs[0],
        }
        if req.dimensions is not None:
            payload["dimensions"] = req.dimensions
        payload.update(req.extra_options)
        return payload

    def _parse_embedding_response(
        self, req: EmbeddingWireRequest, payload: Any
    ) -> EmbeddingWireResult:
        if not isinstance(payload, Mapping):
            raise ProviderError("embeddings response is not a JSON object", phase="validate")
        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, list):
            raise ProviderError(
                "embeddings response is missing an 'embeddings' array", phase="validate"
            )
        if len(embeddings) != len(req.inputs):
            raise ProviderError(
                f"embeddings response returned {len(embeddings)} vectors for "
                f"{len(req.inputs)} inputs",
                phase="validate",
            )
        vectors: list[tuple[float, ...]] = []
        for entry in embeddings:
            if not isinstance(entry, list):
                raise ProviderError(
                    "embeddings response contains a non-array vector", phase="validate"
                )
            vectors.append(tuple(float(v) for v in entry))

        model = payload.get("model")
        prompt_eval_count = payload.get("prompt_eval_count")
        usage = None
        if isinstance(prompt_eval_count, int):
            usage = Usage(input_tokens=prompt_eval_count)

        # Same phase names generation uses; /api/embed reports no prefill/decode split
        # (contracts/ollama.md), so only these two exist to carry.
        phases: dict[str, float] = {}
        for source_name, phase_name in (
            ("load_duration", "model_load_ms"),
            ("total_duration", "provider_total_ms"),
        ):
            value = payload.get(source_name)
            if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
                phases[phase_name] = float(value) / _NS_PER_MS

        return EmbeddingWireResult(
            vectors=tuple(vectors),
            model=model if isinstance(model, str) else None,
            dimensions=len(vectors[0]) if vectors else None,
            usage=usage,
            phases=phases,
            raw=payload,
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP transport."""
        await self._client.aclose()


class _StreamState:
    """Accumulates the terminal object's counters and phase timings."""

    __slots__ = ("_tool_index", "finish_reason", "phases", "usage")

    def __init__(self) -> None:
        self.finish_reason: FinishReason = "stop"
        self.usage: Usage | None = None
        self.phases: dict[str, float] = {}
        self._tool_index = -1

    def next_tool_index(self) -> int:
        """Allocate the next tool-call slot."""
        self._tool_index += 1
        return self._tool_index

    def absorb_final(self, message: Mapping[str, Any]) -> None:
        """Read the terminal object's ``done_reason``, token counts, and ns durations."""
        reason = message.get("done_reason")
        if isinstance(reason, str):
            self.finish_reason = _DONE_REASONS.get(reason, "other")
        if self._tool_index >= 0:
            self.finish_reason = "tool_calls"

        prompt = message.get("prompt_eval_count")
        output = message.get("eval_count")
        if isinstance(prompt, int) or isinstance(output, int):
            self.usage = Usage(
                input_tokens=prompt if isinstance(prompt, int) else None,
                output_tokens=output if isinstance(output, int) else None,
            ).normalized()

        for wire_name, phase_name in (
            ("load_duration", "model_load_ms"),
            ("prompt_eval_duration", "prefill_ms"),
            ("eval_duration", "decode_ms"),
            ("total_duration", "provider_total_ms"),
        ):
            value = message.get(wire_name)
            if isinstance(value, int | float):
                self.phases[phase_name] = float(value) / _NS_PER_MS

    def finalize(self, *, session_state: Mapping[str, Any] | None = None) -> AdapterFinal:
        """Build the terminal adapter event.

        Ollama keeps no conversation, so an open session's state records only that this
        adapter is holding the model resident — enough for the core to report the session
        as resumed on the turns that follow.
        """
        return AdapterFinal(
            finish_reason=self.finish_reason,
            usage=self.usage,
            phases=dict(self.phases),
            session_state=(None if session_state is None else {"keep_alive": SESSION_KEEP_ALIVE}),
        )


def _session_keep_alive(req: WireRequest) -> str | None:
    """The ``keep_alive`` an open session implies, or ``None`` for an ordinary request.

    ``session_state`` distinguishes the two cases an empty mapping cannot: ``None`` is a
    request with no session, ``{}`` is a session's first turn.
    """
    return SESSION_KEEP_ALIVE if req.session_state is not None else None


async def _pull_model(request: Any) -> Any:
    """Make a model available on this Ollama server.

    Imported inside the call rather than at module scope: the local subsystem is not part
    of an adapter's import surface, and a pull is a rare operation that should not cost
    every client construction the import.
    """
    from ..local.services import pull_ollama_model

    return await pull_ollama_model(request)


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Map normalized effort onto Ollama's ``think`` parameter.

    Ollama accepts a boolean or, on newer builds, an effort level. ``minimal`` maps to
    ``False`` because it means "spend as little as possible", which for a thinking model is
    "do not think".
    """
    if effort is None:
        return {}
    if effort in ("none", "minimal"):
        return {"think": False}
    return {"think": effort}


_OLLAMA_FEATURES = (
    Feature.STREAMING
    | Feature.GRAMMAR
    | Feature.JSON_SCHEMA
    | Feature.JSON_MODE
    | Feature.TOOLS
    | Feature.REASONING
    | Feature.SYSTEM_PROMPT
)


descriptor = ProviderDescriptor(
    id="ollama",
    display_name="Ollama",
    factory=OllamaAdapter,
    locality="local",
    default_base_url=_DEFAULT_BASE_URL,
    requires_base_url=False,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="base_url",
                label="Server address",
                kind="endpoint",
                required=False,
                advanced=True,
                default_value=_DEFAULT_BASE_URL,
                help_text="Defaults to http://127.0.0.1:11434. A bare hostname is expanded.",
            ),
            SetupField(
                key="api_key",
                label="API key",
                kind="secret",
                required=False,
                advanced=True,
                help_text="Only needed for proxied deployments that require auth.",
                placeholder="env://OLLAMA_API_KEY or a literal key",
                env_var="OLLAMA_API_KEY",
            ),
        ),
        model_selection="discover-or-manual",
        host_shorthand=HostShorthand(scheme="http", default_port=11434),
    ),
    reasoning_translator=_translate_reasoning,
    ignored_parameters=("logprobs",),
    default_capabilities=ModelCapabilities(features=Sourced(_OLLAMA_FEATURES, "default")),
    supports_sessions=True,
    # Ollama keeps its own store and downloader, so acquisition here means asking it to
    # pull. The implementation lives in local/, never in this adapter.
    model_puller=_pull_model,
    model_inventory="installed",
    reports_diagnostics=True,
    grammar_needs_prompt_injection=True,
    operations=frozenset({"generation", "embedding"}),
)
"""Descriptor for the Ollama provider."""
