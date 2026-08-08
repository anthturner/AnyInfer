"""GitHub Copilot via the ``github-copilot-sdk`` (`contracts/copilot.md`).

The only adapter that is not raw HTTP: Copilot is reached by driving the Copilot CLI as a
subprocess runtime through its SDK, so there is no wire protocol for us to speak. It is the
one provider SDK allowed in the otherwise HTTP-based adapter layer.

Two things make this provider unusual and shape the code below:

- **No structured-output mode.** The schema is prompt-injected and validated client-side —
  the core's fallback path, which is exactly why that path exists.
- **The ``auto`` sentinel.** Copilot may pick the model at request time, so capabilities for
  ``auto`` are the *conjunction* across every model it might choose.
  Claiming more would be a promise the caller cannot verify until a request fails.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, ClassVar

from ..errors import AuthError, ConfigError, ProviderError, RateLimitError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import (
    DiscoveredModel,
    Feature,
    Health,
    ModelCapabilities,
    Sourced,
)
from ..types.events import TextDelta
from ..types.messages import Text, ToolResult
from ..types.requests import ReasoningEffort
from ..types.results import Usage
from .base import AdapterEvent, AdapterFinal, ProviderConfig, WireRequest

__all__ = ["AUTO_MODEL", "CopilotAdapter", "descriptor"]

AUTO_MODEL = "auto"
"""Sentinel asking Copilot to choose the model for each request."""

_CLI_PATH_ENV = "COPILOT_CLI_PATH"
"""Overrides CLI discovery, matching the SDK's own convention."""

_USAGE_EVENT_TYPE = "assistant.usage"


class CopilotAdapter:
    """Adapter driving the GitHub Copilot CLI through its SDK."""

    provider_id: ClassVar[str] = "copilot"

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self._client: Any = None

    # ---- SDK plumbing ----------------------------------------------------------------

    @staticmethod
    def _import_sdk() -> Any:
        """Import the optional SDK, or explain how to install it.

        A missing extra is a `ConfigError` with an install hint
        rather than an ``ImportError``, so the failure tells the user what to do.
        """
        try:
            import copilot
        except ImportError as exc:
            raise ConfigError(
                "the copilot provider requires the github-copilot-sdk extra",
                provider="copilot",
                hint="pip install 'anyinfer[copilot]', then run 'copilot login'",
            ) from exc
        return copilot

    async def _ensure_client(self) -> Any:
        """Build the SDK client on first use."""
        if self._client is not None:
            return self._client

        copilot = self._import_sdk()
        options: dict[str, Any] = dict(self._config.options)
        cli_path = options.pop("cli_path", None) or os.environ.get(_CLI_PATH_ENV)
        try:
            self._client = copilot.CopilotClient(
                **({"cli_path": cli_path} if cli_path else {}), **options
            )
        except Exception as exc:
            raise self._map_error(exc) from exc
        return self._client

    def _map_error(self, exc: Exception) -> ProviderError:
        """Map an SDK or CLI failure to a typed, actionable error."""
        text = f"{type(exc).__name__}: {exc}"
        lowered = text.lower()

        if "not found" in lowered and ("cli" in lowered or "copilot" in lowered):
            return ProviderError(
                text,
                provider=self.provider_id,
                hint=(
                    "install the Copilot CLI and ensure it is on PATH, or set "
                    f"{_CLI_PATH_ENV} to its location"
                ),
            )
        if any(marker in lowered for marker in ("unauthorized", "auth", "login", "401")):
            return AuthError(
                text,
                provider=self.provider_id,
                hint="run 'copilot login' to authenticate the CLI",
            )
        if any(marker in lowered for marker in ("rate limit", "quota", "429", "too many")):
            return RateLimitError(
                text,
                provider=self.provider_id,
                hint="wait for the quota window to reset, or switch to another provider",
            )
        return ProviderError(text, provider=self.provider_id)

    # ---- discovery -------------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """List the models this Copilot account can use, plus the ``auto`` sentinel."""
        client = await self._ensure_client()
        try:
            listed = await _maybe_await(client.list_models())
        except Exception as exc:
            raise self._map_error(exc) from exc

        ids = [_model_id(entry) for entry in listed or []]
        models = [
            DiscoveredModel(
                id=model_id,
                capabilities=ModelCapabilities(
                    features=Sourced(_COPILOT_FEATURES, "discovered")
                ),
            )
            for model_id in ids
            if model_id
        ]
        if not any(m.id == AUTO_MODEL for m in models):
            models.insert(
                0,
                DiscoveredModel(
                    id=AUTO_MODEL,
                    capabilities=ModelCapabilities(
                        features=Sourced(_COPILOT_FEATURES, "default")
                    ),
                ),
            )
        return models

    async def health(self) -> Health:
        """Probe readiness by listing models, which exercises CLI auth end to end."""
        try:
            await self.list_models()
        except ProviderError as exc:
            return Health(ok=False, detail=exc.detail)
        except ConfigError as exc:
            return Health(ok=False, detail=exc.detail)
        return Health(ok=True)

    # ---- generation ------------------------------------------------------------------

    async def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]:
        """Run one turn through a Copilot session, mapping SDK events to ours."""
        client = await self._ensure_client()
        system_prompt, user_prompt = _split_prompt(req)

        session_options: dict[str, Any] = {"model": req.model}
        if system_prompt:
            session_options["system_prompt"] = system_prompt
        session_options.update(req.reasoning_wire)
        session_options.update(req.extra_options)

        usage = Usage()
        emitted_any = False

        try:
            session = await _maybe_await(client.create_session(**session_options))
        except Exception as exc:
            raise self._map_error(exc) from exc

        try:
            stream = session.send(user_prompt)
            async for event in _aiter(stream):
                text = _event_text(event)
                if text:
                    emitted_any = True
                    yield TextDelta(text)
                reported = _event_usage(event)
                if reported is not None:
                    usage = usage.merge(reported)
        except Exception as exc:
            raise self._map_error(exc) from exc
        finally:
            close = getattr(session, "close", None) or getattr(session, "aclose", None)
            if close is not None:
                # Teardown must never mask the failure that brought us here.
                with contextlib.suppress(Exception):
                    await _maybe_await(close())

        yield AdapterFinal(
            finish_reason="stop" if emitted_any else "other",
            usage=usage.normalized() if _has_counts(usage) else None,
        )

    async def aclose(self) -> None:
        """Shut down the SDK client and its CLI runtime."""
        if self._client is None:
            return
        close = getattr(self._client, "close", None) or getattr(self._client, "aclose", None)
        if close is not None:
            with contextlib.suppress(Exception):
                await _maybe_await(close())
        self._client = None


# ---- helpers -------------------------------------------------------------------------


async def _maybe_await(value: Any) -> Any:
    """Await a value when the SDK returned a coroutine, else pass it through.

    The SDK mixes sync and async surfaces across versions; this keeps the adapter working
    with both rather than pinning to one shape.
    """
    if hasattr(value, "__await__"):
        return await value
    return value


async def _aiter(stream: Any) -> AsyncIterator[Any]:
    """Iterate a stream that may be async, sync, or a coroutine yielding either."""
    resolved = await _maybe_await(stream)
    if hasattr(resolved, "__aiter__"):
        async for item in resolved:
            yield item
        return
    for item in resolved or ():
        yield item


def _split_prompt(req: WireRequest) -> tuple[str, str]:
    """Flatten the conversation into Copilot's system-plus-turn shape.

    The session API takes a system prompt and one user turn, so prior turns are folded into
    the user prompt with role markers rather than being silently dropped.
    """
    system_parts: list[str] = []
    conversation: list[str] = []

    for message in req.messages:
        text = "".join(p.text for p in message.content if isinstance(p, Text))
        results = [p for p in message.content if isinstance(p, ToolResult)]
        if results:
            conversation.append(f"[tool result] {results[0].content}")
            continue
        if not text:
            continue
        if message.role == "system":
            system_parts.append(text)
        elif message.role == "assistant":
            conversation.append(f"[assistant] {text}")
        else:
            conversation.append(text)

    return "\n\n".join(system_parts), "\n\n".join(conversation)


def _model_id(entry: Any) -> str:
    """Read a model id from whatever shape the SDK returned."""
    if isinstance(entry, str):
        return entry
    for attribute in ("id", "model", "name"):
        value = getattr(entry, attribute, None)
        if isinstance(value, str) and value:
            return value
    if isinstance(entry, Mapping):
        for key in ("id", "model", "name"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _event_text(event: Any) -> str:
    """Extract assistant text from an SDK event, ignoring everything else."""
    for attribute in ("delta", "text", "content"):
        value = getattr(event, attribute, None)
        if isinstance(value, str) and value:
            return value
    if isinstance(event, Mapping):
        for key in ("delta", "text", "content"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _event_usage(event: Any) -> Usage | None:
    """Read an ``assistant.usage`` event, if this is one."""
    event_type = getattr(event, "type", None)
    if isinstance(event, Mapping):
        event_type = event.get("type", event_type)
    if event_type != _USAGE_EVENT_TYPE:
        return None

    def field(name: str) -> int | None:
        value = getattr(event, name, None)
        if value is None and isinstance(event, Mapping):
            value = event.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return Usage(
        input_tokens=field("input_tokens"),
        output_tokens=field("output_tokens"),
        cache_read_tokens=field("cache_read_tokens"),
        cache_write_tokens=field("cache_write_tokens"),
        reasoning_tokens=field("reasoning_tokens"),
    )


def _has_counts(usage: Usage) -> bool:
    """Whether any usage figure was actually reported."""
    return any(
        value is not None
        for value in (
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_tokens,
            usage.cache_write_tokens,
            usage.reasoning_tokens,
        )
    )


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Pass normalized effort through to the SDK's session options."""
    return {} if effort is None else {"reasoning_effort": effort}


_COPILOT_FEATURES = Feature.STREAMING | Feature.SYSTEM_PROMPT | Feature.CACHE_USAGE
"""Excludes JSON_SCHEMA and JSON_MODE (schemas are prompt-injected here) and TOOLS:
the session API takes a prompt and options only, so caller-supplied tool specs have
no wire form and are declared in ``ignored_parameters`` instead of being claimed."""


descriptor = ProviderDescriptor(
    id="copilot",
    display_name="GitHub Copilot",
    aliases=("github-copilot",),
    factory=CopilotAdapter,
    locality="hosted",
    default_base_url=None,
    requires_base_url=False,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="cli_path",
                label="Copilot CLI path",
                kind="endpoint",
                required=False,
                advanced=True,
                # No ``default_value``: the fallback is the SDK's own CLI discovery
                # rather than a fixed path this side could name.
                help_text=f"Defaults to CLI discovery, or the {_CLI_PATH_ENV} environment "
                "variable. Authentication is delegated to 'copilot login'.",
            ),
        ),
        model_selection="discover-or-manual",
    ),
    reasoning_translator=_translate_reasoning,
    default_capabilities=ModelCapabilities(features=Sourced(_COPILOT_FEATURES, "default")),
    supports_sessions=True,
    ignored_parameters=("temperature", "top_p", "max_output_tokens", "stop", "tools"),
)
"""Descriptor for the GitHub Copilot provider."""
