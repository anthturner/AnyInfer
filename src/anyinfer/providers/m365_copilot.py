"""Microsoft 365 Copilot (`contracts/m365-copilot.md`).

The most constrained provider in the set, and honestly so:

- **Interactive authentication only.** There is no client-credential or daemon flow, so
  this provider cannot run headless. It is exempt from live CI conformance, and the
  limitation is surfaced as an actionable error rather than a mysterious 401.
- **No sampling controls and no native structured output.** Schemas are prompt-injected and
  validated client-side; requesting a temperature is a
  `ParameterDropped` event, not a silent no-op.
- **Non-streaming.** The response arrives whole and is emitted as a single delta, which the
  core's event contract already accommodates.

Citations and attributions are retained on ``raw`` rather than normalized: v1 has no typed
model for them, and inventing one now would freeze a shape before it is understood.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, ClassVar

import httpx2

from ..errors import AuthError, ConfigError, StreamProtocolError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import (
    DiscoveredModel,
    Feature,
    Health,
    ModelCapabilities,
    Sourced,
)
from ..types.events import TextDelta
from ..types.messages import Text
from ..types.results import Usage
from ._multimodal import has_multimodal, unsupported
from .base import AdapterEvent, AdapterFinal, ProviderConfig, WireRequest
from .http import build_client, classify_status, map_transport_error, read_error_detail

__all__ = ["M365_COPILOT_SCOPES", "M365CopilotAdapter", "descriptor"]

_DEFAULT_BASE_URL = "https://graph.microsoft.com/v1.0"
_CHAT_PATH = "/copilot/conversations"

M365_COPILOT_SCOPES = ("https://graph.microsoft.com/.default",)
"""Delegated scopes; there is no application-permission equivalent for this API."""

_FIXED_MODEL = "m365-copilot"
"""The service exposes no model selection, so discovery reports this single entry."""


class M365CopilotAdapter:
    """Adapter for Microsoft 365 Copilot's tenant-bound chat API."""

    provider_id: ClassVar[str] = "m365-copilot"

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self._token: str | None = config.api_key
        headers = {"content-type": "application/json"}
        if self._token:
            headers["authorization"] = f"Bearer {self._token}"
        headers.update({k.lower(): v for k, v in config.headers.items()})
        self._client = build_client(
            base_url=(config.base_url or _DEFAULT_BASE_URL).rstrip("/"),
            headers=headers,
            timeout_s=config.timeout_s,
            transport=config.transport,
        )

    # ---- auth ------------------------------------------------------------------------

    def _ensure_token(self) -> str:
        """Return a bearer token, acquiring one interactively if necessary.

        Raises:
            ConfigError: If the ``[azure]`` extra is absent, or no interactive session is
                possible, which is the expected outcome in CI and headless deployments.
        """
        if self._token:
            return self._token

        try:
            from azure.identity import InteractiveBrowserCredential
        except ImportError as exc:
            raise ConfigError(
                "m365-copilot requires the azure extra for its interactive login",
                provider=self.provider_id,
                hint="pip install 'anyinfer[azure]', or supply a token as api_key",
            ) from exc

        options = self._config.options
        scopes = tuple(options.get("scopes") or M365_COPILOT_SCOPES)
        try:
            credential = InteractiveBrowserCredential(
                tenant_id=options.get("tenant_id"),
                client_id=options.get("client_id"),
            )
            token = credential.get_token(*scopes)
        except Exception as exc:
            raise ConfigError(
                f"interactive sign-in for Microsoft 365 Copilot failed: {exc}",
                provider=self.provider_id,
                hint=(
                    "this provider supports interactive authentication only; it cannot "
                    "run headless or in CI. Supply a pre-acquired token as api_key if you "
                    "have one."
                ),
            ) from exc

        self._token = str(token.token)
        self._client.headers["authorization"] = f"Bearer {self._token}"
        return self._token

    # ---- discovery -------------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """Report the single fixed model; the service exposes no model choice."""
        return [
            DiscoveredModel(
                id=_FIXED_MODEL,
                capabilities=ModelCapabilities(features=Sourced(_M365_FEATURES, "catalog")),
            )
        ]

    async def health(self) -> Health:
        """Report whether a token is available without triggering an interactive prompt.

        Deliberately does not sign in: a health probe that opens a browser window would be
        a hostile surprise, and the router calls this speculatively.
        """
        if self._token:
            return Health(ok=True)
        return Health(
            ok=False,
            detail="no Microsoft 365 Copilot token; interactive sign-in is required",
        )

    # ---- generation ------------------------------------------------------------------

    async def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]:
        """Run one non-streaming turn, emitted as a single delta plus a final."""
        self._ensure_token()
        payload = self.build_payload(req)

        try:
            response = await self._client.post(_CHAT_PATH, json=payload, timeout=req.timeout_s)
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id) from exc

        if response.status_code in (401, 403):
            raise AuthError(
                read_error_detail(response.content) or "not authorized for M365 Copilot",
                provider=self.provider_id,
                http_status=response.status_code,
                hint=(
                    "sign in again, and confirm the tenant has a Microsoft 365 Copilot "
                    "license and admin consent for this application"
                ),
            )
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

        body = response.json()
        text = _extract_text(body)
        if text:
            yield TextDelta(text)
        yield AdapterFinal(finish_reason="stop", usage=_parse_usage(body), raw=body)

    def build_payload(self, req: WireRequest) -> dict[str, Any]:
        """Flatten the conversation into the single prompt this API accepts."""
        if has_multimodal(tuple(req.messages)):
            raise unsupported(self.provider_id, "multimodal")
        parts: list[str] = []
        for message in req.messages:
            text = "".join(p.text for p in message.content if isinstance(p, Text))
            if not text:
                continue
            if message.role == "system":
                parts.append(text)
            elif message.role == "assistant":
                parts.append(f"[assistant] {text}")
            else:
                parts.append(text)

        payload: dict[str, Any] = {"message": {"text": "\n\n".join(parts)}}
        payload.update(req.extra_options)
        return payload

    async def aclose(self) -> None:
        """Close the underlying HTTP transport."""
        await self._client.aclose()


def _extract_text(body: Any) -> str:
    """Pull assistant text out of the response body's several possible shapes."""
    if not isinstance(body, Mapping):
        return ""
    for key in ("text", "content", "answer"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value

    message = body.get("message")
    if isinstance(message, Mapping):
        for key in ("text", "content"):
            value = message.get(key)
            if isinstance(value, str) and value:
                return value

    messages = body.get("messages")
    if isinstance(messages, list):
        collected = [
            str(entry.get("text", ""))
            for entry in messages
            if isinstance(entry, Mapping) and entry.get("text")
        ]
        return "\n".join(collected)
    return ""


def _parse_usage(body: Any) -> Usage | None:
    """Read usage, which this API generally does not report."""
    if not isinstance(body, Mapping):
        return None
    usage = body.get("usage")
    if not isinstance(usage, Mapping):
        return None

    def field(name: str) -> int | None:
        value = usage.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    parsed = Usage(
        input_tokens=field("promptTokens") or field("prompt_tokens"),
        output_tokens=field("completionTokens") or field("completion_tokens"),
    ).normalized()
    return parsed if parsed != Usage() else None


_M365_FEATURES = Feature.SYSTEM_PROMPT
"""No streaming, no tools, no native structured output, no sampling controls."""


descriptor = ProviderDescriptor(
    id="m365-copilot",
    display_name="Microsoft 365 Copilot",
    aliases=("m365",),
    factory=M365CopilotAdapter,
    locality="hosted",
    default_base_url=_DEFAULT_BASE_URL,
    requires_base_url=False,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="api_key",
                label="Access token",
                kind="secret",
                required=False,
                help_text="A pre-acquired bearer token. Omit to sign in interactively.",
                placeholder="env://M365_COPILOT_TOKEN or a literal token",
                env_var="M365_COPILOT_TOKEN",
            ),
            SetupField(
                key="tenant_id",
                label="Tenant ID",
                kind="text",
                required=False,
                advanced=True,
                # Left blank, the tenant and client below are azure-identity's own
                # defaults rather than values this side chooses, so neither declares a
                # ``default_value`` it would only be guessing at.
                help_text="Entra tenant for the interactive sign-in.",
                placeholder="common",
            ),
            SetupField(
                key="client_id",
                label="Client ID",
                kind="text",
                required=False,
                advanced=True,
                help_text=(
                    "Application (client) ID for the interactive sign-in. Not a secret; "
                    "omit to use the default public client."
                ),
                placeholder="00000000-0000-0000-0000-000000000000",
            ),
        ),
        model_selection="manual-only",
        requirement_note=(
            "Leave the access token empty to sign in interactively — that needs a "
            "browser, so supply a token when running headless or in CI."
        ),
    ),
    default_capabilities=ModelCapabilities(features=Sourced(_M365_FEATURES, "default")),
    # One re-ask, never a loop. Every request here is a Graph round trip against a
    # conversation the service keeps state for, behind an interactively-acquired token —
    # the most expensive request shape in the registry, and the least likely to answer a
    # repeated question differently.
    max_repair_attempts=1,
    ignored_parameters=(
        "temperature",
        "top_p",
        "max_output_tokens",
        "stop",
        "tools",
        "reasoning",
    ),
)
"""Descriptor for the Microsoft 365 Copilot provider."""
