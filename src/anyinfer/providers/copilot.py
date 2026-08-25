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

from ..errors import AnyInferError, AuthError, ConfigError, ProviderError, RateLimitError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import (
    DiscoveredModel,
    Feature,
    Health,
    ModelCapabilities,
    Sourced,
    TokenCalibration,
)
from ..types.events import TextDelta
from ..types.messages import Text, ToolResult
from ..types.requests import ReasoningEffort
from ..types.results import Usage
from ._multimodal import has_multimodal, unsupported
from .base import AdapterEvent, AdapterFinal, ProviderConfig, WireRequest
from .http import read_int

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
        self._sessions: dict[str, Any] = {}
        """SDK sessions held open for `Session` handles, keyed by the id handed back to
        the core. Holding a transport-level object across requests is the same kind of
        state as holding an HTTP client; no orchestration lives here."""
        self._session_counter = 0

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
        if cli_path:
            # The SDK takes a runtime *connection*, not a flat path: `cli_path=` was an
            # earlier spelling and today's `CopilotClient` is keyword-only with no
            # `**kwargs`, so passing it raises `TypeError` rather than being ignored.
            # `StdioRuntimeConnection` is the variant that spawns the named binary and
            # talks to it over stdin/stdout, which is what pointing at a CLI means.
            options["connection"] = copilot.StdioRuntimeConnection(path=str(cli_path))
        try:
            self._client = copilot.CopilotClient(**options)
        except Exception as exc:
            raise self._map_error(exc) from exc
        return self._client

    def _map_error(self, exc: Exception) -> AnyInferError:
        """Map an SDK or CLI failure to a typed, actionable error.

        Returns `AnyInferError` rather than `ProviderError` because not every failure
        reaching here is the provider's: an options key the installed SDK does not accept
        is a configuration mistake, and `ConfigError` sits on the configure-phase branch
        of the hierarchy rather than under `ProviderError`.
        """
        text = f"{type(exc).__name__}: {exc}"
        lowered = text.lower()

        if isinstance(exc, TypeError) and "keyword argument" in lowered:
            # The whole `options` block is forwarded to a vendor constructor that is
            # keyword-only with no `**kwargs`, so an option this SDK version does not
            # know is a `TypeError` rather than something it ignores. Named explicitly
            # because the generic branch below turns it into a bare repr, which is how
            # a rename in the SDK reads as an unexplained provider failure.
            return ConfigError(
                text,
                provider=self.provider_id,
                hint=(
                    "an 'options' key is not accepted by the installed "
                    "github-copilot-sdk; remove it, or upgrade/downgrade the SDK to a "
                    "version that takes it"
                ),
            )
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
                capabilities=ModelCapabilities(features=Sourced(_COPILOT_FEATURES, "discovered")),
            )
            for model_id in ids
            if model_id
        ]
        if not any(m.id == AUTO_MODEL for m in models):
            models.insert(
                0,
                DiscoveredModel(
                    id=AUTO_MODEL,
                    capabilities=ModelCapabilities(features=Sourced(_COPILOT_FEATURES, "default")),
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
        """Run one turn through a Copilot session, mapping SDK events to ours.

        This is the one provider where a session is the *native* shape: the SDK keeps the
        conversation, so a resumed session does not re-send prior turns at all. Without an
        open session each request still creates and closes its own, which is what makes
        every request independent by default.
        """
        client = await self._ensure_client()

        session_key = _session_key(req)
        held = self._sessions.get(session_key) if session_key else None
        system_prompt, user_prompt = _split_prompt(req, resumed=held is not None)

        session_options: dict[str, Any] = {"model": req.model}
        if system_prompt:
            session_options["system_prompt"] = system_prompt
        session_options.update(req.reasoning_wire)
        session_options.update(req.extra_options)

        usage = Usage()
        emitted_any = False

        session = held
        if session is None:
            try:
                session = await _maybe_await(client.create_session(**session_options))
            except Exception as exc:
                raise self._map_error(exc) from exc
            if req.session_state is not None:
                session_key = session_key or self._next_session_key()
                self._sessions[session_key] = session

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
            if req.session_state is None:
                # No session: this one existed for this request and is closed with it.
                # A held session stays open until the adapter does, since closing it is
                # exactly what the caller asked not to happen.
                close = getattr(session, "close", None) or getattr(session, "aclose", None)
                if close is not None:
                    # Teardown must never mask the failure that brought us here.
                    with contextlib.suppress(Exception):
                        await _maybe_await(close())

        yield AdapterFinal(
            finish_reason="stop" if emitted_any else "other",
            usage=usage.normalized() if _has_counts(usage) else None,
            session_state=(None if session_key is None else {"session_id": session_key}),
        )

    def _next_session_key(self) -> str:
        """Mint a key for a session this adapter is about to hold open."""
        self._session_counter += 1
        return f"copilot-session-{self._session_counter}"

    #: Shutdown method names, most current first. The SDK spells this `stop`; `close` and
    #: `aclose` are kept as fallbacks so an older or newer pin still shuts down rather
    #: than silently doing nothing. Probing for names that do not exist is what let a
    #: rename leak the CLI subprocess on every close, so `_SHUTDOWN_METHODS` is asserted
    #: against the installed SDK in `tests/test_copilot.py` instead of merely hoped for.
    _SHUTDOWN_METHODS = ("stop", "close", "aclose")

    async def aclose(self) -> None:
        """Shut down held sessions, the SDK client, and its CLI runtime.

        The client owns a spawned CLI process, so failing to reach a real shutdown method
        leaks it — silently, because there is nothing to raise. `CopilotClient.stop`
        closes active sessions as part of its own cleanup; sessions are still swept first
        so a session-level failure cannot skip the client shutdown that matters most.
        """
        for session in self._sessions.values():
            await self._shutdown(session)
        self._sessions.clear()
        if self._client is None:
            return
        await self._shutdown(self._client)
        self._client = None

    @staticmethod
    async def _shutdown(target: Any) -> None:
        """Call the first shutdown method `target` actually has, sync or async."""
        for name in CopilotAdapter._SHUTDOWN_METHODS:
            method = getattr(target, name, None)
            if method is None:
                continue
            with contextlib.suppress(Exception):
                await _maybe_await(method())
            return
        # Falling through means every known spelling is gone: the SDK renamed its
        # shutdown API again. Async context-manager exit is the one contract the SDK has
        # kept across those renames, so it is the last resort rather than giving up.
        exit_ = getattr(target, "__aexit__", None)
        if exit_ is not None:
            with contextlib.suppress(Exception):
                await exit_(None, None, None)


# ---- helpers -------------------------------------------------------------------------


def _session_key(req: WireRequest) -> str | None:
    """The held-session key this request continues, if any.

    ``None`` for a request with no session, and for a session's first turn, which has an
    open handle but nothing stored in it yet.
    """
    state = req.session_state
    if not state:
        return None
    key = state.get("session_id")
    return str(key) if key else None


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


def _split_prompt(req: WireRequest, *, resumed: bool = False) -> tuple[str, str]:
    """Flatten the conversation into Copilot's system-plus-turn shape.

    The session API takes a system prompt and one user turn, so prior turns are normally
    folded into the user prompt with role markers rather than being silently dropped.

    A **resumed** session is the exception, and the reason sessions are worth having here:
    the service still holds the conversation, so re-sending it would both pay for those
    tokens again and show the model every earlier turn twice. Only the newest user turn
    goes out.
    """
    if has_multimodal(tuple(req.messages)):
        raise unsupported("copilot", "multimodal")
    system_parts: list[str] = []
    conversation: list[str] = []

    messages = req.messages
    if resumed:
        # Everything before the last user message is already on the service's side.
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].role == "user":
                messages = messages[index:]
                break

    for message in messages:
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
        # Not a plain payload dict (this is an SDK event, read via getattr), so the
        # strict-int/bool-exclusion check is shared by routing the resolved value
        # through the same `read_int` every dict-shaped dialect uses.
        return read_int({name: value}, name)

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

_COPILOT_CALIBRATION = TokenCalibration(multiplier=2.4, overhead_tokens=1_200)
"""The session harness this provider bills for on top of the prompt it is handed.

The CLI runtime builds its own request around the prompt — an agent system preamble, its
built-in tool declarations, workspace framing — none of which appears in the messages this
side serializes. Prompt tokens as Copilot reports them therefore run far above the bytes
sent, and consistently enough to correct for. The figures were arrived at empirically
against this SDK and are the reason budgets here are not quietly optimistic; they are a
calibration, not a measurement, so they move the planning estimate only."""


descriptor = ProviderDescriptor(
    id="copilot",
    display_name="GitHub Copilot",
    aliases=("github-copilot",),
    factory=CopilotAdapter,
    locality="hosted",
    default_base_url=None,
    requires_base_url=False,
    # The SDK owns its own HTTP stack; this adapter never builds an httpx client, so a
    # proxy or CA bundle set here would be accepted and then quietly do nothing.
    honors_connection_settings=False,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="cli_path",
                label="Copilot CLI path",
                kind="path",
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
    token_calibration=_COPILOT_CALIBRATION,
    supports_sessions=True,
    ignored_parameters=("temperature", "top_p", "max_output_tokens", "stop", "tools"),
)
"""Descriptor for the GitHub Copilot provider."""
