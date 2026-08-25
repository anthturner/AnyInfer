"""Build provider wire requests from normalized generation requests.

Everything provider-specific that can be decided *before* the adapter runs is decided here:
mechanism selection, schema projection, reasoning-effort translation, prompt injection, and
provider-option narrowing. That keeps adapters focused on protocol translation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..capabilities.pricing import TRUSTED_PROVENANCE
from ..providers.base import WireRequest
from ..registry import ProviderDescriptor
from ..schema.mechanism import choose_mechanism, system_prompt_for
from ..schema.project import identity_projection
from ..types.capabilities import Feature, ModelCapabilities
from ..types.messages import Message, Text, system
from ..types.requests import GenerationRequest, ResolvedTarget
from ..types.results import Mechanism

__all__ = ["build_wire_request", "dropped_parameters"]


def build_wire_request(
    request: GenerationRequest,
    target: ResolvedTarget,
    descriptor: ProviderDescriptor,
    *,
    capabilities: ModelCapabilities | None = None,
    stream: bool = True,
    session_state: Mapping[str, Any] | None = None,
    cache_marks: tuple[int, ...] = (),
) -> WireRequest:
    """Resolve a generation request for one provider.

    Args:
        request: The caller's request.
        target: The resolved provider and model.
        descriptor: The provider's descriptor, supplying translators and projection.
        capabilities: Assembled capabilities, driving mechanism choice.
        stream: Whether to ask the adapter to stream.
        session_state: Continuation data from an open session covering this target, or
            ``None`` when no session applies. An empty mapping is meaningful — it is a
            session's first turn.
        cache_marks: Segment indices the cache planner chose, passed through for the
            adapter to spell. Empty when no cache policy is in force.

    Returns:
        A fully-resolved wire request.
    """
    mechanism: Mechanism | None = None
    wire_schema: Mapping[str, Any] | None = None
    schema_name: str | None = None
    messages = request.messages

    if request.schema is not None:
        mechanism = choose_mechanism(capabilities)
        schema_name = request.schema.name
        projector = _projector_for(descriptor)
        if mechanism in ("json_schema", "grammar"):
            wire_schema = projector(request.schema.json_schema)
        if _needs_prompt_injection(mechanism, descriptor):
            messages = _inject_schema_prompt(messages, request.schema.json_schema)

    # The "*" namespace applies to whichever provider serves the request; a namespace
    # matching the resolved provider wins field-by-field over the wildcard.
    provider_options = {
        **request.provider_options.get("*", {}),
        **request.provider_options.get(target.provider_id, {}),
    }

    return WireRequest(
        model=target.model,
        messages=tuple(messages),
        sampling=request.sampling,
        reasoning_wire=(
            descriptor.reasoning_translator(request.reasoning)
            if _model_takes_reasoning(request, capabilities)
            else {}
        ),
        mechanism=mechanism,
        wire_schema=wire_schema,
        schema_name=schema_name,
        tools=request.tools,
        tool_choice=request.tool_choice,
        cache_marks=cache_marks,
        cite_documents=request.cite_documents and _model_cites(request, capabilities),
        server_tools=request.server_tools,
        logprobs=request.logprobs if _model_reports_logprobs(request, capabilities) else None,
        stream=stream,
        timeout_s=request.effective_timeout_s,
        max_response_bytes=request.max_response_bytes,
        extra_options=dict(provider_options),
        session_state=None if session_state is None else dict(session_state),
    )


def _model_takes_reasoning(
    request: GenerationRequest, capabilities: ModelCapabilities | None
) -> bool:
    """Whether a requested reasoning effort should be sent to this model.

    A provider's descriptor knows how to *spell* reasoning effort; it does not know which
    of that provider's models have one. Sending the field to a model without it is the
    silently-ignored case this library exists to eliminate — the request succeeds, the
    parameter does nothing, and nothing says so.

    Withheld only on a *known* absence, following the same rule as the pre-dispatch gate:
    a ``default``-provenance feature set is a descriptor-level guess, and dropping a
    caller's parameter on a guess would be worse than sending one the model ignores.
    """
    if request.reasoning is None:
        return False
    if capabilities is None or capabilities.features.provenance not in TRUSTED_PROVENANCE:
        return True
    return Feature.REASONING in capabilities.features.value


def _model_reports_logprobs(
    request: GenerationRequest, capabilities: ModelCapabilities | None
) -> bool:
    """Whether a request for log-probabilities should reach this model.

    The same trusted-absence rule `_model_takes_reasoning` applies, for the same reason:
    a ``default``-provenance feature set is a descriptor-level guess, and withholding the
    field on a guess turns a provider that would have answered into one that silently
    could not. The difference from reasoning is what happens on a *known* absence — a
    dropped reasoning effort still produces an answer, while a request whose whole point
    was the probabilities produces a `Generation` with an empty ``logprobs`` a caller
    would otherwise have to notice for themselves. So `dropped_parameters` reports the
    withholding explicitly, and this function only decides what goes on the wire.
    """
    if request.logprobs is None:
        return False
    if capabilities is None or capabilities.features.provenance not in TRUSTED_PROVENANCE:
        return True
    return Feature.LOGPROBS in capabilities.features.value


def _model_cites(request: GenerationRequest, capabilities: ModelCapabilities | None) -> bool:
    """Whether a request for citations should reach this model.

    The same trusted-absence rule the other two capability gates use: a
    ``default``-provenance feature set is a descriptor-level guess, and withholding on a
    guess turns a provider that would have cited into one that silently could not.
    """
    if not request.cite_documents:
        return False
    if capabilities is None or capabilities.features.provenance not in TRUSTED_PROVENANCE:
        return True
    return Feature.CITATIONS in capabilities.features.value


def _projector_for(descriptor: ProviderDescriptor) -> Any:
    """Find a descriptor's schema projector, defaulting to identity."""
    projector = getattr(descriptor.factory, "project_schema", None)
    if callable(projector):
        return projector
    return identity_projection


def dropped_parameters(
    request: GenerationRequest,
    descriptor: ProviderDescriptor,
    capabilities: ModelCapabilities | None = None,
) -> tuple[tuple[str, str], ...]:
    """Find requested parameters this target will not honor.

    Two sources, because a parameter can go unhonored for two different reasons. The
    *provider* may accept and discard it — declared on the descriptor, or this particular
    *model* may not have the feature at all, which only the assembled capabilities know.

    Returns ``(parameter, reason)`` pairs so the caller can emit one
    `ParameterDropped` event per parameter. A parameter
    that is accepted and ignored is the worst failure mode available — it looks exactly
    like success, so it is surfaced rather than tolerated.
    """
    dropped: list[tuple[str, str]] = []
    if request.reasoning is not None and not _model_takes_reasoning(request, capabilities):
        dropped.append(
            (
                "reasoning",
                f"{descriptor.id}'s {'model' if capabilities else 'models'} does not "
                "support reasoning effort, so it was not sent",
            )
        )
    if request.cite_documents and not _model_cites(request, capabilities):
        dropped.append(
            (
                "cite_documents",
                f"{descriptor.id}'s {'model' if capabilities else 'models'} does not "
                "attribute answers to supplied documents, so no citations were requested",
            )
        )
    if request.logprobs is not None and not _model_reports_logprobs(request, capabilities):
        dropped.append(
            (
                "logprobs",
                f"{descriptor.id}'s {'model' if capabilities else 'models'} does not "
                "report token log-probabilities, so none were requested",
            )
        )
    if not descriptor.ignored_parameters:
        return tuple(dropped)

    supplied: dict[str, object] = {
        "temperature": request.sampling.temperature,
        "top_p": request.sampling.top_p,
        "max_output_tokens": request.sampling.max_output_tokens,
        "stop": request.sampling.stop or None,
        "seed": request.sampling.seed,
        "presence_penalty": request.sampling.presence_penalty,
        "frequency_penalty": request.sampling.frequency_penalty,
        "logprobs": request.logprobs,
        "cite_documents": request.cite_documents or None,
        "server_tools.max_uses": next(
            (spec.max_uses for spec in request.server_tools if spec.max_uses is not None), None
        ),
        "reasoning": request.reasoning,
        "tools": request.tools or None,
    }
    already = {name for name, _ in dropped}
    dropped.extend(
        (name, f"{descriptor.id} accepts but ignores {name}")
        for name in descriptor.ignored_parameters
        if supplied.get(name) is not None and name not in already
    )
    return tuple(dropped)


def _needs_prompt_injection(mechanism: Mechanism, descriptor: ProviderDescriptor) -> bool:
    """Whether the schema must also be described in the prompt.

    Always true for ``prompt`` and ``json_mode``, which carry no schema on the wire at all.

    Also true for ``grammar``: a grammar *constrains* decoding but tells the model nothing
    about what it is supposed to produce. A model that has not been shown the schema emits
    syntactically valid JSON with meaningless content — it satisfies the grammar and fails
    the caller. Providers whose json_schema mode already conditions the model (the hosted
    dialects) do not need this, which is why it is a descriptor property rather than a
    blanket rule.
    """
    if mechanism in ("prompt", "json_mode"):
        return True
    if mechanism == "grammar":
        return descriptor.grammar_needs_prompt_injection
    return False


def _inject_schema_prompt(
    messages: tuple[Message, ...],
    json_schema: Mapping[str, Any],
) -> tuple[Message, ...]:
    """Append the schema instruction to the last system message, or prepend a new one.

    Appending to an existing system message keeps instruction precedence intact: providers
    that weight the *first* system message most heavily would otherwise see the schema
    outrank the caller's actual instructions.
    """
    instruction = system_prompt_for(json.dumps(dict(json_schema), indent=2, sort_keys=True))

    last_system = -1
    for index, message in enumerate(messages):
        if message.role == "system":
            last_system = index

    if last_system == -1:
        return (system(instruction), *messages)

    target = messages[last_system]
    merged = Message(
        role="system",
        content=(*target.content, Text("\n\n" + instruction)),
    )
    return (*messages[:last_system], merged, *messages[last_system + 1 :])
