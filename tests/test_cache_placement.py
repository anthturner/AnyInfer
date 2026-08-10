"""Cache marks reach the wire in the shape Anthropic documents, and only when asked."""

from __future__ import annotations

from typing import Any

import anyinfer as ai
from anyinfer.capabilities.cache import SYSTEM_SEGMENT, TOOLS_SEGMENT
from anyinfer.providers.anthropic import AnthropicAdapter, descriptor
from anyinfer.providers.base import ProviderConfig, WireRequest
from anyinfer.types.messages import assistant, system, user
from anyinfer.types.requests import ToolSpec


def _adapter() -> AnthropicAdapter:
    return AnthropicAdapter(ProviderConfig(provider_id="anthropic", api_key="k"))


def _wire(**overrides: Any) -> WireRequest:
    fields: dict[str, Any] = {
        "model": "claude-sonnet-4-5",
        "messages": (
            system("a long stable preamble"),
            user("first question"),
            assistant("first answer"),
            user("follow-up"),
        ),
    }
    fields.update(overrides)
    return WireRequest(**fields)


def _blocks(payload: dict[str, Any], index: int) -> list[dict[str, Any]]:
    content = payload["messages"][index]["content"]
    assert isinstance(content, list)
    return content


def test_no_marks_leaves_the_payload_exactly_as_before() -> None:
    payload = _adapter().build_payload(_wire())

    assert payload["system"] == "a long stable preamble"
    assert not any(
        "cache_control" in block for message in payload["messages"] for block in message["content"]
    )


def test_a_system_mark_becomes_a_marked_content_block() -> None:
    """`cache_control` cannot attach to a bare string, so the system field changes shape."""
    payload = _adapter().build_payload(_wire(cache_marks=(SYSTEM_SEGMENT,)))

    assert payload["system"] == [
        {
            "type": "text",
            "text": "a long stable preamble",
            "cache_control": {"type": "ephemeral"},
        }
    ]


def test_a_tools_mark_lands_on_the_last_tool() -> None:
    """A mark covers everything before it, and tools precede messages on this API."""
    tools = (
        ToolSpec(name="search", description="find things", parameters={}),
        ToolSpec(name="fetch", description="get things", parameters={}),
    )

    payload = _adapter().build_payload(_wire(tools=tools, cache_marks=(TOOLS_SEGMENT,)))

    assert "cache_control" not in payload["tools"][0]
    assert payload["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_a_message_mark_lands_on_that_message_after_system_hoisting() -> None:
    """Marks index the request's messages; the system turn is hoisted out of that list."""
    # Request index 2 is the assistant turn; encoded index 1, because the system message
    # became a top-level field.
    payload = _adapter().build_payload(_wire(cache_marks=(2,)))

    assert "cache_control" not in _blocks(payload, 0)[-1]
    assert _blocks(payload, 1)[-1]["cache_control"] == {"type": "ephemeral"}


def test_several_marks_are_all_applied() -> None:
    tools = (ToolSpec(name="search", description="find things", parameters={}),)

    payload = _adapter().build_payload(
        _wire(tools=tools, cache_marks=(TOOLS_SEGMENT, SYSTEM_SEGMENT, 2))
    )

    assert payload["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert isinstance(payload["system"], list)
    assert _blocks(payload, 1)[-1]["cache_control"] == {"type": "ephemeral"}


def test_out_of_range_marks_are_ignored_rather_than_raising() -> None:
    """A plan built against a different message list must never break a request."""
    payload = _adapter().build_payload(_wire(cache_marks=(99,)))

    assert not any(
        "cache_control" in block for message in payload["messages"] for block in message["content"]
    )


def test_the_descriptor_declares_what_the_contract_records() -> None:
    assert descriptor.cache_mechanism == "explicit"
    assert descriptor.cache_max_marks == 4
    assert descriptor.cache_min_tokens == 1024
    assert descriptor.default_capabilities.features.value & ai.Feature.CACHE_PLACEMENT


def test_implicit_providers_declare_no_marks() -> None:
    from anyinfer.providers.deepseek import descriptor as deepseek
    from anyinfer.providers.openai import descriptor as openai

    for implicit in (openai, deepseek):
        assert implicit.cache_mechanism == "implicit"
        assert implicit.cache_max_marks == 0


# ---- end to end through the client ---------------------------------------------------


def _scripted_client(mechanism: str | None, **client_kwargs: Any) -> tuple[Any, Any, list[Any]]:
    """A client over a scripted provider declaring one cache mechanism."""
    from anyinfer.registry import ProviderDescriptor, ProviderRegistry
    from anyinfer.testing import ScriptedModel, ScriptedProvider
    from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced

    provider = ScriptedProvider("acme", [ScriptedModel("m", text="ok")])
    base = provider.descriptor()
    features = Feature.STREAMING | Feature.SYSTEM_PROMPT
    if mechanism == "explicit":
        features |= Feature.CACHE_PLACEMENT
    descriptor_with_cache = ProviderDescriptor(
        id=base.id,
        display_name=base.display_name,
        factory=base.factory,
        default_base_url=base.default_base_url,
        setup=base.setup,
        default_capabilities=ModelCapabilities(features=Sourced(features, "catalog")),
        cache_mechanism=mechanism,  # type: ignore[arg-type]
        cache_max_marks=4 if mechanism == "explicit" else 0,
        cache_min_tokens=0,
    )
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(descriptor_with_cache, replace=True)

    events: list[Any] = []

    class _Observer:
        def on_event(self, event: Any) -> None:
            events.append(event)

    client = ai.Client(
        [provider.settings()],
        registry=registry,
        use_default_catalog=False,
        observers=[_Observer()],
        **client_kwargs,
    )
    return client, provider, events


def test_without_a_policy_nothing_is_planned() -> None:
    client, provider, events = _scripted_client("explicit")
    with client:
        result = client.generate("hi", target=provider.target("m"))

    assert result.cache_mechanism is None
    assert not [e for e in events if isinstance(e, ai.CachePlanned)]


def test_a_policy_reaches_the_result_and_the_event_stream() -> None:
    client, provider, events = _scripted_client("explicit")
    long_system = "stable preamble " * 4000
    with client:
        result = client.generate(
            [ai.system(long_system), ai.user("first"), ai.assistant("answer"), ai.user("next")],
            target=provider.target("m"),
            cache=ai.CachePolicy(min_segment_tokens=0),
        )

    assert result.cache_mechanism == "explicit"
    planned = [e for e in events if isinstance(e, ai.CachePlanned)]
    assert planned and planned[0].mark_count >= 1


def test_a_target_without_caching_reports_a_dropped_parameter() -> None:
    client, provider, events = _scripted_client(None)
    with client:
        result = client.generate("hi", target=provider.target("m"), cache=ai.CachePolicy())

    assert result.cache_mechanism is None
    dropped = [
        e for e in events if isinstance(e, ai.ParameterDropped) and e.parameter == "cache.mode"
    ]
    assert dropped


def test_asking_for_explicit_on_an_implicit_target_is_reported() -> None:
    client, provider, events = _scripted_client("implicit")
    with client:
        result = client.generate(
            [ai.system("preamble " * 2000), ai.user("a"), ai.assistant("b"), ai.user("c")],
            target=provider.target("m"),
            cache=ai.CachePolicy(mode="explicit"),
        )

    assert result.cache_mechanism == "implicit"
    reasons = [
        e.reason
        for e in events
        if isinstance(e, ai.ParameterDropped) and e.parameter == "cache.mode"
    ]
    assert any("implicit" in reason for reason in reasons)


def test_a_client_level_policy_applies_to_every_request() -> None:
    client, provider, _ = _scripted_client("implicit", cache=ai.CachePolicy())
    with client:
        result = client.generate(
            [ai.system("preamble " * 2000), ai.user("a"), ai.assistant("b"), ai.user("c")],
            target=provider.target("m"),
        )

    assert result.cache_mechanism == "implicit"


def test_an_unstable_prefix_is_reported_on_an_implicit_target() -> None:
    """The failure nobody notices: a changing prefix means a hit rate of zero."""
    client, provider, events = _scripted_client("implicit")
    stable_tail = [ai.user("a"), ai.assistant("b"), ai.user("c")]
    with client:
        client.generate(
            [ai.system("preamble " * 2000), *stable_tail],
            target=provider.target("m"),
            cache=ai.CachePolicy(),
        )
        client.generate(
            [ai.system("a DIFFERENT preamble " * 2000), *stable_tail],
            target=provider.target("m"),
            cache=ai.CachePolicy(),
        )

    codes = [e.diagnostic.code for e in events if isinstance(e, ai.ProviderDiagnostic)]
    assert "cache.prefix-unstable" in codes


def test_a_stable_prefix_reports_nothing() -> None:
    client, provider, events = _scripted_client("implicit")
    messages = [ai.system("preamble " * 2000), ai.user("a"), ai.assistant("b"), ai.user("c")]
    with client:
        client.generate(messages, target=provider.target("m"), cache=ai.CachePolicy())
        client.generate(messages, target=provider.target("m"), cache=ai.CachePolicy())

    codes = [e.diagnostic.code for e in events if isinstance(e, ai.ProviderDiagnostic)]
    assert "cache.prefix-unstable" not in codes
