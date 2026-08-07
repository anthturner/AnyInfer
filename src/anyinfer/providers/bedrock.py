"""AWS Bedrock's Converse API (`contracts/bedrock.md`).

Converse is Bedrock's *unified* interface: one request shape across Claude, Nova, Llama,
Mistral, and DeepSeek, rather than the per-model bodies ``InvokeModel`` demands. That is
exactly the normalization AnyInfer wants, so this adapter speaks Converse and never
InvokeModel.

Four things make this dialect unusual:

- **Streaming is binary.** ``ConverseStream`` answers with AWS's
  ``vnd.amazon.eventstream`` framing and offers no SSE or JSON alternative, so the
  decoder in `anyinfer.providers.eventstream` is not optional.
- **Auth is signed, or a bearer key.** A Bedrock API key is used verbatim when supplied;
  otherwise every request is SigV4-signed from resolved AWS credentials.
- **Content is a list of typed blocks**, and tool results ride on a *user* turn.
- **Usage arrives only in the terminal ``metadata`` event** — a stream closed on
  ``messageStop`` reports no tokens at all.

Model-specific parameters that Converse does not model (Claude's ``top_k`` or extended
thinking, for instance) pass through ``additionalModelRequestFields``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from typing import Any

import httpx2

from ..errors import ConfigError, ProviderError, StreamProtocolError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import DiscoveredModel, Feature, Health, ModelCapabilities, Sourced
from ..types.events import ReasoningDelta, TextDelta, ToolCallDelta, UsageUpdate
from ..types.messages import Message, Text, ToolCall, ToolResult
from ..types.requests import ReasoningEffort, Sampling, ToolSpec
from ..types.results import FinishReason, Usage
from .base import AdapterEvent, AdapterFinal, ProviderConfig, WireRequest
from .cloud_auth import AwsCredentials, resolve_aws_credentials, sigv4_headers
from .eventstream import EventStreamMessage, iter_event_stream
from .http import build_client, classify_status, map_transport_error, read_error_detail

__all__ = ["BedrockAdapter", "descriptor"]

_DEFAULT_REGION = "us-east-1"
_SIGNING_SERVICE = "bedrock"

_STOP_REASONS: Mapping[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "guardrail_intervened": "content_filter",
    "content_filtered": "content_filter",
    "malformed_model_output": "other",
    "malformed_tool_use": "other",
    "model_context_window_exceeded": "length",
}

_RETRYABLE_EXCEPTIONS: Mapping[str, int] = {
    "throttlingException": 429,
    "modelNotReadyException": 429,
    "serviceUnavailableException": 503,
    "internalServerException": 500,
    "modelStreamErrorException": 424,
    "modelTimeoutException": 408,
}
"""In-stream exception frames, mapped to the status the shared classifier expects."""


class BedrockAdapter:
    """Adapter for Amazon Bedrock's Converse API."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self.provider_id = config.provider_id
        options = dict(config.options)

        self._region = str(options.get("region") or _DEFAULT_REGION)
        self._api_key = config.api_key
        self._credentials: AwsCredentials | None = None
        if not self._api_key:
            # Deferred to first use only for the key; credentials are cheap to resolve
            # and failing at construction gives a much clearer error than failing mid-run.
            self._credentials = resolve_aws_credentials(options)
            if self._credentials is None:
                raise ConfigError(
                    "bedrock needs either a Bedrock API key or AWS credentials",
                    provider=self.provider_id,
                    hint=(
                        "set api_key to a Bedrock API key (or env://AWS_BEARER_TOKEN_BEDROCK), "
                        "or configure AWS credentials via the environment, a boto3 profile, "
                        "or options={'aws_access_key_id': ..., 'aws_secret_access_key': ...}"
                    ),
                )

        base_url = config.base_url or f"https://bedrock-runtime.{self._region}.amazonaws.com"
        self._base_url = base_url.rstrip("/")
        self._client = build_client(
            base_url=self._base_url,
            headers={"content-type": "application/json"},
            timeout_s=config.timeout_s,
            transport=config.transport,
        )

    # ---- auth ------------------------------------------------------------------------

    def _auth_headers(self, *, method: str, path: str, body: bytes) -> dict[str, str]:
        """Build the per-request auth headers: a bearer key, or a SigV4 signature."""
        if self._api_key:
            return {"authorization": f"Bearer {self._api_key}"}
        assert self._credentials is not None  # guaranteed by __init__
        return sigv4_headers(
            credentials=self._credentials,
            method=method,
            url=f"{self._base_url}{path}",
            region=self._region,
            service=_SIGNING_SERVICE,
            body=body,
            headers={"content-type": "application/json"},
        )

    # ---- discovery -------------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """List foundation models from the Bedrock control plane.

        The control plane is a *different* host than the runtime, so this signs against
        it separately. Accounts without ``bedrock:ListFoundationModels`` get an empty
        list rather than an error — discovery is a convenience, and a permission gap
        should not make the provider look broken.
        """
        host = f"https://bedrock.{self._region}.amazonaws.com"
        path = "/foundation-models"
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        elif self._credentials is not None:
            headers.update(
                sigv4_headers(
                    credentials=self._credentials,
                    method="GET",
                    url=f"{host}{path}",
                    region=self._region,
                    service=_SIGNING_SERVICE,
                    body=b"",
                    headers=headers,
                )
            )

        try:
            response = await self._client.get(f"{host}{path}", headers=headers)
        except httpx2.HTTPError:
            return []
        if response.status_code >= 400:
            return []

        payload = response.json()
        summaries = payload.get("modelSummaries") if isinstance(payload, Mapping) else None
        if not isinstance(summaries, list):
            return []
        return [
            _parse_model(entry)
            for entry in summaries
            if isinstance(entry, Mapping) and entry.get("modelId")
        ]

    async def health(self) -> Health:
        """Report whether credentials are present.

        Deliberately not a network call: every Bedrock runtime endpoint costs a
        generation, and the control plane may be denied by policy even when inference
        works perfectly.
        """
        if self._api_key or self._credentials is not None:
            return Health(ok=True, detail=f"credentials present for {self._region}")
        return Health(ok=False, detail="no Bedrock API key or AWS credentials")

    # ---- generation ------------------------------------------------------------------

    async def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]:
        """Run one generation through Converse or ConverseStream."""
        payload = self.build_payload(req)
        if req.stream:
            async for event in self._generate_streaming(req, payload):
                yield event
        else:
            async for event in self._generate_buffered(req, payload):
                yield event

    def build_payload(self, req: WireRequest) -> dict[str, Any]:
        """Translate a wire request into a Converse request body."""
        system_blocks, turns = _split_system(req.messages)

        payload: dict[str, Any] = {
            "messages": [self._encode_message(m) for m in turns],
        }
        if system_blocks:
            payload["system"] = system_blocks

        inference = _inference_config(req.sampling)
        if inference:
            payload["inferenceConfig"] = inference

        tools = [self._encode_tool(t) for t in req.tools]
        if req.mechanism in ("json_schema", "grammar") and req.wire_schema is not None:
            # Converse has no response-format field, so a schema becomes a forced tool
            # call — the same emulation the Anthropic adapter uses, and for the same
            # reason: the API genuinely constrains tool input.
            name = req.schema_name or "respond"
            tools.append(
                {
                    "toolSpec": {
                        "name": name,
                        "description": "Return the response in the required structure.",
                        "inputSchema": {"json": dict(req.wire_schema)},
                    }
                }
            )
            payload["toolConfig"] = {
                "tools": tools,
                "toolChoice": {"tool": {"name": name}},
            }
        elif tools:
            payload["toolConfig"] = {
                "tools": tools,
                **_tool_choice(req.tool_choice),
            }

        extra = dict(req.reasoning_wire)
        extra.update(req.extra_options)
        additional = extra.pop("additionalModelRequestFields", None)
        if isinstance(additional, Mapping):
            payload["additionalModelRequestFields"] = dict(additional)
        payload.update(extra)
        return payload

    def _encode_message(self, message: Message) -> dict[str, Any]:
        """Encode one turn into Converse's typed content blocks."""
        blocks: list[dict[str, Any]] = []

        for part in message.content:
            if isinstance(part, Text):
                if part.text:
                    blocks.append({"text": part.text})
            elif isinstance(part, ToolCall):
                blocks.append(
                    {
                        "toolUse": {
                            "toolUseId": part.id,
                            "name": part.name,
                            "input": dict(part.arguments),
                        }
                    }
                )
            elif isinstance(part, ToolResult):
                blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": part.call_id,
                            "content": [{"text": part.content}],
                            **({"status": "error"} if part.is_error else {}),
                        }
                    }
                )

        # Tool results ride on a user turn here, as in the Anthropic dialect.
        role = "user" if message.role in ("user", "tool") else "assistant"
        return {"role": role, "content": blocks or [{"text": ""}]}

    def _encode_tool(self, tool: ToolSpec) -> dict[str, Any]:
        return {
            "toolSpec": {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": {"json": dict(tool.parameters)},
            }
        }

    # ---- buffered path ---------------------------------------------------------------

    async def _generate_buffered(
        self, req: WireRequest, payload: dict[str, Any]
    ) -> AsyncIterator[AdapterEvent]:
        """Issue a unary Converse request and emit it as a one-shot stream."""
        path = f"/model/{_quote_model(req.model)}/converse"
        body = json.dumps(payload).encode("utf-8")

        try:
            response = await self._client.post(
                path,
                content=body,
                headers=self._auth_headers(method="POST", path=path, body=body),
                timeout=req.timeout_s,
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
        if len(response.content) > req.max_response_bytes:
            raise StreamProtocolError(
                f"response exceeded max_response_bytes ({req.max_response_bytes} bytes)",
                provider=self.provider_id,
            )

        try:
            parsed = json.loads(response.content)
        except ValueError as exc:
            raise StreamProtocolError(
                f"bedrock returned a non-JSON body: {exc}", provider=self.provider_id
            ) from exc

        for event in self._events_from_response(parsed):
            yield event

    def _events_from_response(self, payload: Any) -> Iterable[AdapterEvent]:
        """Translate a buffered Converse response into a synthetic event stream."""
        if not isinstance(payload, Mapping):
            raise StreamProtocolError(
                "bedrock returned a non-object response", provider=self.provider_id
            )

        output = payload.get("output")
        message = output.get("message") if isinstance(output, Mapping) else None
        blocks = message.get("content") if isinstance(message, Mapping) else None

        slot = 0
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, Mapping):
                    continue
                text = block.get("text")
                if isinstance(text, str) and text:
                    yield TextDelta(text)
                reasoning = _reasoning_text(block.get("reasoningContent"))
                if reasoning:
                    yield ReasoningDelta(reasoning)
                use = block.get("toolUse")
                if isinstance(use, Mapping):
                    yield ToolCallDelta(
                        index=slot,
                        call_id=str(use.get("toolUseId", "")) or None,
                        name=str(use.get("name", "")) or None,
                        arguments_fragment=json.dumps(dict(use.get("input") or {})),
                    )
                    slot += 1

        usage = _parse_usage(payload.get("usage"))
        if usage is not None:
            yield UsageUpdate(usage)

        raw_reason = payload.get("stopReason")
        finish = _STOP_REASONS.get(raw_reason, "other") if isinstance(raw_reason, str) else "stop"
        yield AdapterFinal(
            finish_reason=finish,
            usage=usage,
            phases=_latency_phases(payload.get("metrics")),
            raw=payload,
        )

    # ---- streaming path --------------------------------------------------------------

    async def _generate_streaming(
        self, req: WireRequest, payload: dict[str, Any]
    ) -> AsyncIterator[AdapterEvent]:
        """Stream ConverseStream, decoding AWS's binary event framing."""
        path = f"/model/{_quote_model(req.model)}/converse-stream"
        body = json.dumps(payload).encode("utf-8")

        try:
            async with self._client.stream(
                "POST",
                path,
                content=body,
                headers=self._auth_headers(method="POST", path=path, body=body),
                timeout=req.timeout_s,
            ) as response:
                if response.status_code >= 400:
                    detail = read_error_detail(await response.aread())
                    raise classify_status(
                        response.status_code,
                        provider=self.provider_id,
                        detail=detail,
                        headers=response.headers,
                    )

                state = _StreamState()
                async for frame in iter_event_stream(
                    response.aiter_bytes(),
                    max_bytes=req.max_response_bytes,
                    provider=self.provider_id,
                ):
                    for event in self._events_from_frame(frame, state):
                        yield event
                yield state.finalize()
        except (ProviderError, StreamProtocolError):
            raise
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="stream") from exc

    def _events_from_frame(
        self, frame: EventStreamMessage, state: _StreamState
    ) -> Iterable[AdapterEvent]:
        """Translate one decoded event-stream frame into adapter events."""
        if frame.is_exception:
            raise self._exception_error(frame)

        payload = frame.json()
        if not isinstance(payload, Mapping):
            return

        kind = frame.event_type
        if kind == "contentBlockStart":
            start = payload.get("start")
            index = payload.get("contentBlockIndex")
            if isinstance(start, Mapping) and isinstance(index, int):
                use = start.get("toolUse")
                if isinstance(use, Mapping):
                    yield ToolCallDelta(
                        index=state.tool_slot(index),
                        call_id=str(use.get("toolUseId", "")) or None,
                        name=str(use.get("name", "")) or None,
                        arguments_fragment="",
                    )
            return

        if kind == "contentBlockDelta":
            delta = payload.get("delta")
            index = payload.get("contentBlockIndex")
            if not isinstance(delta, Mapping):
                return
            text = delta.get("text")
            if isinstance(text, str) and text:
                yield TextDelta(text)
            reasoning = _reasoning_text(delta.get("reasoningContent"))
            if reasoning:
                yield ReasoningDelta(reasoning)
            use = delta.get("toolUse")
            if isinstance(use, Mapping) and isinstance(index, int):
                fragment = use.get("input")
                if isinstance(fragment, str) and fragment:
                    yield ToolCallDelta(
                        index=state.tool_slot(index),
                        call_id=None,
                        name=None,
                        arguments_fragment=fragment,
                    )
            return

        if kind == "messageStop":
            reason = payload.get("stopReason")
            if isinstance(reason, str):
                state.finish_reason = _STOP_REASONS.get(reason, "other")
            return

        if kind == "metadata":
            # Usage lives here and nowhere else: a stream closed on messageStop would
            # report no tokens at all.
            usage = _parse_usage(payload.get("usage"))
            if usage is not None:
                state.usage = state.usage.merge(usage)
                yield UsageUpdate(usage)
            state.phases.update(_latency_phases(payload.get("metrics")))

    def _exception_error(self, frame: EventStreamMessage) -> ProviderError:
        """Map an in-stream exception frame onto the shared status classification."""
        name = str(frame.headers.get(":exception-type") or frame.event_type or "")
        detail = ""
        payload = frame.json()
        if isinstance(payload, Mapping):
            detail = str(payload.get("message") or payload.get("Message") or "")
        status = _RETRYABLE_EXCEPTIONS.get(name, 400)
        return classify_status(
            status,
            provider=self.provider_id,
            detail=detail or f"bedrock stream error: {name or 'unknown'}",
            phase="stream",
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP transport."""
        await self._client.aclose()


class _StreamState:
    """Accumulates cross-frame state so the terminal event is complete."""

    __slots__ = ("finish_reason", "phases", "tool_slots", "usage")

    def __init__(self) -> None:
        self.finish_reason: FinishReason = "stop"
        self.usage = Usage()
        self.tool_slots: dict[int, int] = {}
        self.phases: dict[str, float] = {}

    def tool_slot(self, block_index: int) -> int:
        """Map a content-block index onto a dense tool-call slot.

        Block indices count text blocks too, so a response with prose before a tool call
        would otherwise report a non-zero first tool index.
        """
        slot = self.tool_slots.get(block_index)
        if slot is None:
            slot = len(self.tool_slots)
            self.tool_slots[block_index] = slot
        return slot

    def finalize(self) -> AdapterFinal:
        """Build the terminal adapter event."""
        usage = self.usage.normalized()
        return AdapterFinal(
            finish_reason=self.finish_reason,
            usage=usage if usage != Usage() else None,
            phases=dict(self.phases),
        )


def _split_system(messages: Sequence[Message]) -> tuple[list[dict[str, str]], list[Message]]:
    """Pull system messages into Converse's top-level ``system`` block list."""
    system: list[dict[str, str]] = []
    remaining: list[Message] = []
    for message in messages:
        if message.role == "system":
            if message.text:
                system.append({"text": message.text})
        else:
            remaining.append(message)
    return system, remaining


def _inference_config(sampling: Sampling) -> dict[str, Any]:
    """Build ``inferenceConfig`` from only the fields the caller actually set."""
    config: dict[str, Any] = {}
    if sampling.temperature is not None:
        config["temperature"] = sampling.temperature
    if sampling.top_p is not None:
        config["topP"] = sampling.top_p
    if sampling.max_output_tokens is not None:
        config["maxTokens"] = sampling.max_output_tokens
    if sampling.stop:
        config["stopSequences"] = list(sampling.stop)
    return config


def _tool_choice(choice: str) -> dict[str, Any]:
    """Translate normalized tool choice into Converse's ``toolChoice``.

    ``none`` has no Converse spelling, so it is expressed by omitting tools entirely at
    the call site; here it simply sends no choice.
    """
    if choice == "auto":
        return {"toolChoice": {"auto": {}}}
    if choice == "required":
        return {"toolChoice": {"any": {}}}
    if choice == "none":
        return {}
    return {"toolChoice": {"tool": {"name": choice}}}


def _reasoning_text(block: Any) -> str:
    """Read reasoning text out of a ``reasoningContent`` union, ignoring signatures."""
    if not isinstance(block, Mapping):
        return ""
    text = block.get("text")
    if isinstance(text, str):
        return text
    nested = block.get("reasoningText")
    if isinstance(nested, Mapping):
        inner = nested.get("text")
        if isinstance(inner, str):
            return inner
    return ""


def _parse_usage(payload: Any) -> Usage | None:
    """Read Converse's usage block, including its cache accounting."""
    if not isinstance(payload, Mapping):
        return None

    def field(name: str) -> int | None:
        value = payload.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    usage = Usage(
        input_tokens=field("inputTokens"),
        output_tokens=field("outputTokens"),
        total_tokens=field("totalTokens"),
        cache_read_tokens=field("cacheReadInputTokens"),
        cache_write_tokens=field("cacheWriteInputTokens"),
    )
    return usage if usage != Usage() else None


def _latency_phases(metrics: Any) -> dict[str, float]:
    """Read Bedrock's reported latency into the phase-timing map."""
    if not isinstance(metrics, Mapping):
        return {}
    latency = metrics.get("latencyMs")
    if isinstance(latency, int | float) and not isinstance(latency, bool):
        return {"provider_latency": float(latency)}
    return {}


def _quote_model(model: str) -> str:
    """Percent-encode a model id for the request path.

    Model ids may be inference-profile ids or full ARNs, which contain colons and slashes
    that must survive as path data rather than being read as separators.
    """
    import urllib.parse

    return urllib.parse.quote(model, safe="")


def _parse_model(entry: Mapping[str, Any]) -> DiscoveredModel:
    """Read one foundation-model summary from the control plane."""
    features = Feature.SYSTEM_PROMPT
    streaming = entry.get("responseStreamingSupported")
    if streaming is not False:
        features |= Feature.STREAMING
    if "TEXT" in (entry.get("outputModalities") or []):
        features |= Feature.TOOLS
    return DiscoveredModel(
        id=str(entry["modelId"]),
        capabilities=ModelCapabilities(features=Sourced(features, "discovered")),
    )


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Map normalized effort onto Claude-style extended thinking.

    Converse has no reasoning field of its own; thinking is a model-specific parameter, so
    it travels in ``additionalModelRequestFields``. Bedrock forwards unknown fields to the
    model, which ignores them — so this is harmless on models without thinking, and the
    escape hatch remains available for other spellings.
    """
    if effort is None:
        return {}
    if effort == "minimal":
        return {"additionalModelRequestFields": {"thinking": {"type": "disabled"}}}
    budgets = {"low": 1024, "medium": 4096, "high": 16384}
    return {
        "additionalModelRequestFields": {
            "thinking": {"type": "enabled", "budget_tokens": budgets[effort]}
        }
    }


_BEDROCK_FEATURES = (
    Feature.STREAMING
    | Feature.JSON_SCHEMA
    | Feature.TOOLS
    | Feature.REASONING
    | Feature.SYSTEM_PROMPT
    | Feature.CACHE_USAGE
)


descriptor = ProviderDescriptor(
    id="bedrock",
    display_name="AWS Bedrock",
    aliases=("aws-bedrock", "amazon-bedrock"),
    factory=BedrockAdapter,
    locality="hosted",
    default_base_url=None,
    requires_base_url=False,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="api_key",
                label="Bedrock API key",
                kind="secret",
                required=False,
                help_text=(
                    "A Bedrock API key, sent as a bearer token. Leave empty to sign "
                    "requests with AWS credentials instead."
                ),
                placeholder="env://AWS_BEARER_TOKEN_BEDROCK or a literal key",
            ),
            SetupField(
                key="region",
                label="AWS region",
                kind="host-profile",
                required=False,
                help_text=f"Defaults to {_DEFAULT_REGION}.",
                placeholder=_DEFAULT_REGION,
            ),
            SetupField(
                key="base_url",
                label="Runtime endpoint",
                kind="endpoint",
                required=False,
                help_text="Defaults to the regional Bedrock runtime host.",
                placeholder=f"https://bedrock-runtime.{_DEFAULT_REGION}.amazonaws.com",
            ),
            SetupField(
                key="aws_access_key_id",
                label="AWS access key ID",
                kind="host-profile",
                required=False,
                help_text=(
                    "Sign with an explicit access key instead of the ambient credential "
                    "chain. Requires the secret access key too."
                ),
                placeholder="AKIA…",
            ),
            SetupField(
                key="aws_secret_access_key",
                label="AWS secret access key",
                kind="secret",
                required=False,
                help_text=(
                    "The secret half of the access key above. Accepts env:// and "
                    "credential://."
                ),
                placeholder="env://AWS_SECRET_ACCESS_KEY",
            ),
            SetupField(
                key="aws_session_token",
                label="AWS session token",
                kind="secret",
                required=False,
                help_text="Only for temporary (STS) credentials.",
                placeholder="env://AWS_SESSION_TOKEN",
            ),
            SetupField(
                key="profile",
                label="AWS profile",
                kind="host-profile",
                required=False,
                help_text=(
                    "A named profile to resolve through boto3, when it is installed."
                ),
                placeholder="default",
            ),
        ),
        model_selection="discover-or-manual",
        requirement_note=(
            "Leave every credential field empty to use the ambient AWS chain "
            "(environment, profile, or instance role). Otherwise supply either a Bedrock "
            "API key or an access key ID and secret access key."
        ),
    ),
    reasoning_translator=_translate_reasoning,
    default_capabilities=ModelCapabilities(features=Sourced(_BEDROCK_FEATURES, "default")),
)
"""Descriptor for the AWS Bedrock provider."""
