"""A declarative provider for testing an *application's* inference code.

The fakes in `anyinfer.testing.fakes` speak provider dialects, which is what the
conformance suite needs: proof that an adapter handles a real wire shape. An application
testing its own routing, repair, and reduction logic needs something else — a provider
whose behaviour it can *state*, per model, including the failures that are otherwise
unreachable without a real outage.

That is this module. Behaviour lives in a table rather than in branches, so a test reads as
a description of what the provider does:

```python
provider = ScriptedProvider(
    "acme",
    [
        ScriptedModel("fast", text="hi"),
        ScriptedModel("flaky", failures=(ScriptedFailure(status=503, retry_after_s=0.0),)),
    ],
)
```

Requests are served in-process through an ``httpx2`` mock transport — no sockets, no ports,
and identical behaviour on every platform. Rendering is delegated to `FakeOpenAIServer`, so
a scripted provider produces exactly the wire shapes the dialect tests already cover.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx2

from .._client.providers import ProviderSettings
from ..providers.openai_compat import OpenAICompatAdapter
from ..registry import (
    ProviderDescriptor,
    ProviderRegistry,
    ProviderSetupSpec,
    SetupField,
    default_registry,
)
from ..types.capabilities import Feature, ModelCapabilities, Sourced
from .fakes import FakeOpenAIServer, FakeResponse

__all__ = [
    "DEFAULT_SCRIPTED_CAPABILITIES",
    "FailureKind",
    "ScriptedFailure",
    "ScriptedModel",
    "ScriptedProvider",
]

FailureKind = Literal["status", "truncate", "malformed-json", "timeout", "refusal"]
"""How a scripted call fails.

Each kind reaches a different part of the core, and each is otherwise reachable only by
provoking a real provider into misbehaving:

``status``
    An HTTP error, optionally carrying ``Retry-After``. Exercises status classification,
    backoff, and the retry event.
``truncate``
    A stream cut mid-event. Exercises stream teardown and partial-result handling.
``malformed-json``
    A body that will not validate against the requested schema. Exercises validation and
    the bounded repair loop.
``timeout``
    A read timeout, raised rather than slept, so the case is deterministic.
``refusal``
    A completed response reporting ``content_filter``. Exercises the content-policy chain.
"""

DEFAULT_SCRIPTED_CAPABILITIES = ModelCapabilities(
    context_window=Sourced(32_768, "default"),
    features=Sourced(
        Feature.STREAMING | Feature.TOOLS | Feature.SYSTEM_PROMPT | Feature.JSON_MODE,
        "default",
    ),
)
"""Capabilities a scripted model claims when it declares none of its own.

Deliberately ``default`` provenance: a scripted provider is not a source of truth about
what any real model supports, and a test that needs a *trusted* window should say so by
declaring one.
"""


@dataclass(frozen=True, slots=True)
class ScriptedFailure:
    """One scripted failure, consumed by the next call to its model.

    Attributes:
        kind: Which failure to produce; see `FailureKind`.
        status: HTTP status for ``status`` failures.
        retry_after_s: ``Retry-After`` seconds to advertise, when the failure carries one.
            Use ``0.0`` in tests that assert retry behaviour without waiting for it.
        message: Error text the provider reports. Bounded and inert — it is test data, not
            a template.
    """

    kind: FailureKind = "status"
    status: int = 503
    retry_after_s: float | None = None
    message: str = "scripted failure"


@dataclass(frozen=True, slots=True)
class ScriptedModel:
    """One model a scripted provider serves, and how it behaves.

    Attributes:
        id: Model id, as it appears after the colon in a target.
        text: Assistant text to answer with. Ignored when ``structured`` is set.
        structured: An object to answer with, serialized as JSON. The convenient way to
            script a request that carries a schema.
        tool_calls: Tool calls to emit, as ``(id, name, arguments_json)`` triples.
        finish_reason: Normalized finish reason to report.
        usage: Usage block to report, or ``None`` to report none at all, which is how a
            test reaches the estimated-usage path.
        chunk_size: Characters per streamed delta. Smaller values produce more events.
        answer_after_tools: Text to answer with once the conversation already carries a
            tool result. Without it, a model scripted to call a tool calls it on every
            round and the loop never converges, which is a test that only ever proves the
            round budget works. Set it and the model behaves like a real one: ask, then
            answer.
        failures: Failures consumed in order before any success. A model with two failures
            and a retry budget of one will exhaust the budget; that is the point.
        capabilities: What this model claims to support. Defaults to
            `DEFAULT_SCRIPTED_CAPABILITIES`; declare narrower capabilities to force a
            weaker structured-output mechanism.
    """

    id: str
    text: str = "Scripted answer."
    structured: Mapping[str, Any] | None = None
    tool_calls: tuple[tuple[str, str, str], ...] = ()
    finish_reason: str = "stop"
    usage: Mapping[str, Any] | None = field(
        default_factory=lambda: {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        }
    )
    chunk_size: int = 4
    answer_after_tools: str | None = None
    failures: tuple[ScriptedFailure, ...] = ()
    capabilities: ModelCapabilities = DEFAULT_SCRIPTED_CAPABILITIES

    @property
    def answer_text(self) -> str:
        """The body this model answers with, structured content winning over prose."""
        if self.structured is not None:
            return json.dumps(dict(self.structured))
        return self.text


class ScriptedProvider:
    """A registered provider whose behaviour is declared, not coded.

    Args:
        provider_id: Id to register under, and the left half of every target it serves.
        models: The models this provider serves. At least one is required.
        aliases: Additional names resolving to this provider.
        locality: ``"local"`` (the default) keeps cost at a genuine zero and hardware
            detection honest; pass ``"hosted"`` when a test needs pricing to apply.
        base_url: Endpoint recorded in settings. Never contacted — the transport
            intercepts every request, so it uses an unroutable ``.invalid`` host.
        display_name: Human-readable name for UIs and error messages. Defaults to naming
            the provider as scripted, which is the right answer in a test and the wrong
            one in an application that ships a scripted provider as a visible offline mode.

    Attributes:
        requests: Every request body received, oldest first, across all models.
    """

    def __init__(
        self,
        provider_id: str = "scripted",
        models: Sequence[ScriptedModel] | None = None,
        *,
        aliases: Sequence[str] = (),
        locality: Literal["hosted", "local", "remote"] = "local",
        base_url: str = "http://scripted.invalid/v1",
        display_name: str | None = None,
    ) -> None:
        entries = list(models or [ScriptedModel("default")])
        if not entries:
            raise ValueError("a scripted provider must serve at least one model")
        self.provider_id = provider_id
        self.base_url = base_url
        self.display_name = display_name or f"Scripted ({provider_id})"
        self.requests: list[dict[str, Any]] = []
        self._models = {model.id: model for model in entries}
        self._aliases = tuple(aliases)
        self._locality = locality
        self._consumed: dict[str, int] = dict.fromkeys(self._models, 0)

    # ---- declaration -----------------------------------------------------------------

    @property
    def models(self) -> tuple[ScriptedModel, ...]:
        """The models this provider serves, in declaration order."""
        return tuple(self._models.values())

    def target(self, model_id: str | None = None) -> str:
        """The target string for one of this provider's models.

        Args:
            model_id: Which model; defaults to the first declared.

        Returns:
            A ``provider:model`` target.
        """
        chosen = model_id or next(iter(self._models))
        if chosen not in self._models:
            known = ", ".join(self._models) or "(none)"
            raise KeyError(f"no scripted model {chosen!r}; declared: {known}")
        return f"{self.provider_id}:{chosen}"

    def descriptor(self) -> ProviderDescriptor:
        """The declarative descriptor this provider registers."""
        return ProviderDescriptor(
            id=self.provider_id,
            display_name=self.display_name,
            aliases=self._aliases,
            factory=OpenAICompatAdapter,
            locality=self._locality,
            default_base_url=self.base_url,
            setup=ProviderSetupSpec(
                fields=(
                    SetupField(
                        key="base_url",
                        label="Base URL",
                        kind="endpoint",
                        advanced=True,
                        default_value=self.base_url,
                        help_text=(
                            "Ignored — a scripted provider is served in-process and never "
                            "opens a socket."
                        ),
                    ),
                ),
            ),
            static_capabilities={model.id: model.capabilities for model in self._models.values()},
            default_capabilities=DEFAULT_SCRIPTED_CAPABILITIES,
        )

    def register(self, registry: ProviderRegistry | None = None) -> ProviderRegistry:
        """Register this provider, replacing any earlier registration of the same id.

        Args:
            registry: Where to register. Defaults to the process-wide registry, which is
                convenient in a one-off script and wrong in a test suite — the pytest
                fixtures hand each test its own registry so parallel tests cannot collide.

        Returns:
            The registry that was written to.
        """
        target_registry = registry or default_registry
        target_registry.register(self.descriptor(), replace=True)
        return target_registry

    def settings(self, **overrides: Any) -> ProviderSettings:
        """Provider settings wired to this provider's in-process transport."""
        fields: dict[str, Any] = {
            "base_url": self.base_url,
            "transport": self.transport(),
        }
        fields.update(overrides)
        return ProviderSettings.of(self.provider_id, **fields)

    # ---- behaviour -------------------------------------------------------------------

    def transport(self) -> httpx2.MockTransport:
        """An ``httpx2`` transport serving this provider's scripted behaviour."""
        return httpx2.MockTransport(self._handle)

    def reset(self) -> None:
        """Rewind every model's failure script and forget recorded requests."""
        self._consumed = dict.fromkeys(self._models, 0)
        self.requests.clear()

    def call_count(self, model_id: str | None = None) -> int:
        """How many generation calls were served, in total or for one model."""
        if model_id is None:
            return sum(self._consumed.values())
        return self._consumed.get(model_id, 0)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/models"):
            return self._render(next(iter(self._models.values())), FakeResponse(), request)

        body = self._body(request)
        self.requests.append(body)
        model = self._model_for(body)
        consumed = self._consumed[model.id]
        self._consumed[model.id] = consumed + 1

        if consumed < len(model.failures):
            return self._fail(model, model.failures[consumed], request)
        return self._succeed(model, request, body)

    def _fail(
        self,
        model: ScriptedModel,
        failure: ScriptedFailure,
        request: httpx2.Request,
    ) -> httpx2.Response:
        """Produce one scripted failure."""
        if failure.kind == "timeout":
            # Raised rather than slept: a test that waits for a real timeout is a test that
            # is slow on every run and flaky on a loaded machine.
            raise httpx2.ReadTimeout(failure.message, request=request)

        if failure.kind == "truncate":
            # A stream that stops mid-event: a `data:` line with no terminating blank line
            # and no [DONE], which is what a dropped connection looks like to the parser.
            return httpx2.Response(
                200,
                content=b'data: {"choices":[{"index":0,"delta":{"content":"par',
                headers={"content-type": "text/event-stream"},
                request=request,
            )

        if failure.kind == "malformed-json":
            return self._render(model, FakeResponse(text="definitely not json"), request)

        if failure.kind == "refusal":
            return self._render(
                model,
                FakeResponse(text="", finish_reason="content_filter"),
                request,
            )

        headers = (
            {"retry-after": _format_retry_after(failure.retry_after_s)}
            if failure.retry_after_s is not None
            else {}
        )
        return self._render(
            model,
            FakeResponse(status=failure.status, error_message=failure.message, headers=headers),
            request,
        )

    def _succeed(
        self,
        model: ScriptedModel,
        request: httpx2.Request,
        body: Mapping[str, Any],
    ) -> httpx2.Response:
        """Produce this model's ordinary answer.

        A model with ``answer_after_tools`` set stops calling tools once the
        conversation carries a tool result, which is what a real model does and what
        lets a tool-loop test converge.
        """
        if model.answer_after_tools is not None and _carries_tool_result(body):
            return self._render(
                model,
                FakeResponse(
                    text=model.answer_after_tools,
                    finish_reason="stop",
                    usage=model.usage,
                ),
                request,
            )
        return self._render(
            model,
            FakeResponse(
                text=model.answer_text,
                tool_calls=model.tool_calls,
                finish_reason=model.finish_reason,
                usage=model.usage,
            ),
            request,
        )

    def _render(
        self,
        model: ScriptedModel,
        response: FakeResponse,
        request: httpx2.Request,
    ) -> httpx2.Response:
        """Encode one response through the published fake, so framing stays honest."""
        server = FakeOpenAIServer(
            [response],
            models=list(self._models),
            chunk_size=model.chunk_size,
        )
        # `MockTransport.handler` is typed sync-or-async; the fakes are always sync.
        rendered = server.transport().handler(request)
        if not isinstance(rendered, httpx2.Response):
            raise RuntimeError("the synchronous fake server returned an awaitable response")
        return rendered

    def _model_for(self, body: Mapping[str, Any]) -> ScriptedModel:
        requested = str(body.get("model") or "")
        # A target arrives as `provider:model`, and a model id may itself contain colons,
        # so only a leading provider prefix is stripped.
        if requested.startswith(f"{self.provider_id}:"):
            requested = requested.split(":", 1)[1]
        model = self._models.get(requested)
        if model is not None:
            return model
        return next(iter(self._models.values()))

    @staticmethod
    def _body(request: httpx2.Request) -> dict[str, Any]:
        if not request.content:
            return {}
        try:
            parsed = json.loads(request.content)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def with_model(self, model: ScriptedModel) -> ScriptedProvider:
        """Return this provider with one model's declaration replaced or added.

        Convenience for a test that needs a variant of an otherwise shared provider without
        rebuilding the whole table.
        """
        models = [m if m.id != model.id else model for m in self._models.values()]
        if model.id not in self._models:
            models.append(model)
        return ScriptedProvider(
            self.provider_id,
            models,
            aliases=self._aliases,
            locality=self._locality,
            base_url=self.base_url,
            display_name=self.display_name,
        )


def _carries_tool_result(body: Mapping[str, Any]) -> bool:
    """Whether the request already contains an answered tool call."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return False
    return any(isinstance(message, dict) and message.get("role") == "tool" for message in messages)


def _format_retry_after(seconds: float) -> str:
    """Render ``Retry-After`` the way providers do — whole seconds, never negative."""
    return str(max(0, round(seconds)))
