"""Active capability probes: the third assembly layer, paid for in requests."""

from __future__ import annotations

import json

import pytest

import anyinfer as ai
from anyinfer.capabilities.probes import probed_features
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced
from support import make_client

BLUE = json.dumps({"colour": "blue"})

PROBE_SCHEMA_COPY = {
    "type": "object",
    "properties": {"colour": {"type": "string"}},
    "required": ["colour"],
    "additionalProperties": False,
}


# ---- folding results into a feature flag ---------------------------------------------


def test_a_probe_never_erases_the_flags_it_did_not_test() -> None:
    """`features` overlays wholesale, so a bare Feature.TOOLS would wipe the rest."""
    known = Sourced(Feature.STREAMING | Feature.JSON_MODE | Feature.TOOLS, "catalog")
    merged = probed_features(
        known, (ai.FeatureProbe(Feature.JSON_SCHEMA, "supported"),)
    )

    assert merged is not None
    assert merged.provenance == "probed"
    assert Feature.STREAMING in merged.value
    assert Feature.JSON_MODE in merged.value
    assert Feature.JSON_SCHEMA in merged.value


def test_an_unsupported_probe_clears_only_its_own_bit() -> None:
    known = Sourced(Feature.STREAMING | Feature.JSON_SCHEMA, "catalog")
    merged = probed_features(
        known, (ai.FeatureProbe(Feature.JSON_SCHEMA, "unsupported"),)
    )

    assert merged is not None
    assert Feature.JSON_SCHEMA not in merged.value
    assert Feature.STREAMING in merged.value


def test_an_inconclusive_run_records_nothing() -> None:
    known = Sourced(Feature.STREAMING, "catalog")
    assert probed_features(known, (ai.FeatureProbe(Feature.TOOLS, "inconclusive"),)) is None
    assert probed_features(known, ()) is None


# ---- probing end to end --------------------------------------------------------------


async def test_a_conforming_answer_proves_json_schema() -> None:
    server = FakeOpenAIServer(FakeResponse(text=BLUE))
    async with make_client(server) as client:
        report = await client.probe("openai-compat:m", features=[Feature.JSON_SCHEMA])

    assert report.outcome_for(Feature.JSON_SCHEMA) == "supported"
    assert report.requests == 1
    assert report.capabilities is not None
    assert report.capabilities.features.provenance == "probed"


async def test_a_rejection_proves_the_feature_is_unsupported() -> None:
    """The most informative answer: the provider said so itself."""
    server = FakeOpenAIServer(
        FakeResponse(status=400, error_message="response_format is not supported")
    )
    async with make_client(server) as client:
        report = await client.probe("openai-compat:m", features=[Feature.JSON_SCHEMA])

    probe = report.probes[0]
    assert probe.outcome == "unsupported"
    assert "response_format" in probe.detail


async def test_accepted_but_ignored_is_inconclusive_not_a_verdict() -> None:
    """A weak model and an ignored parameter look identical in one reply."""
    server = FakeOpenAIServer(FakeResponse(text="Blue, obviously."))
    async with make_client(server) as client:
        report = await client.probe("openai-compat:m", features=[Feature.JSON_SCHEMA])

    assert report.outcome_for(Feature.JSON_SCHEMA) == "inconclusive"
    assert report.capabilities is None, "nothing settled, so nothing is recorded"


async def test_json_mode_is_judged_on_parseability_not_on_the_schema() -> None:
    """JSON mode promises well-formed JSON and nothing about its shape."""
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"anything": "at all"})))
    async with make_client(server) as client:
        report = await client.probe("openai-compat:m", features=[Feature.JSON_MODE])

    assert report.outcome_for(Feature.JSON_MODE) == "supported"


async def test_a_tool_call_proves_tools() -> None:
    server = FakeOpenAIServer(
        FakeResponse(tool_calls=[{"id": "c1", "name": "record_colour", "arguments": BLUE}])
    )
    async with make_client(server) as client:
        report = await client.probe("openai-compat:m", features=[Feature.TOOLS])

    assert report.outcome_for(Feature.TOOLS) == "supported"
    assert server.requests[0]["tool_choice"] == "required"


async def test_text_instead_of_a_tool_call_is_inconclusive() -> None:
    server = FakeOpenAIServer(FakeResponse(text="The colour is blue."))
    async with make_client(server) as client:
        report = await client.probe("openai-compat:m", features=[Feature.TOOLS])

    assert report.outcome_for(Feature.TOOLS) == "inconclusive"


async def test_multiple_deltas_prove_streaming() -> None:
    server = FakeOpenAIServer(FakeResponse(text="one, two, three, four"), chunk_size=4)
    async with make_client(server) as client:
        report = await client.probe("openai-compat:m", features=[Feature.STREAMING])

    assert report.outcome_for(Feature.STREAMING) == "supported"


async def test_probing_costs_one_request_per_feature() -> None:
    server = FakeOpenAIServer(FakeResponse(text=BLUE))
    async with make_client(server) as client:
        report = await client.probe("openai-compat:m")

    assert report.requests == len(ai.DEFAULT_PROBE_FEATURES)
    assert server.call_count == len(ai.DEFAULT_PROBE_FEATURES)


# ---- what recording changes ----------------------------------------------------------


def _claiming_registry(features: Feature) -> ai.ProviderRegistry:
    """An openai-compat registration whose descriptor *claims* a feature set."""
    from anyinfer.providers.openai_compat import OpenAICompatAdapter

    registry = ai.ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(
        ai.ProviderDescriptor(
            id="claims",
            display_name="Fake claims",
            factory=OpenAICompatAdapter,
            requires_base_url=True,
            default_capabilities=ModelCapabilities(features=Sourced(features, "default")),
        )
    )
    return registry


async def test_a_measured_absence_overrides_what_the_descriptor_claimed() -> None:
    """The failure this layer exists for: a server that accepts response_format and lies."""
    from support import make_multi_client

    registry = _claiming_registry(Feature.STREAMING | Feature.JSON_SCHEMA)
    server = FakeOpenAIServer(
        [
            FakeResponse(text=BLUE),  # the believed-claim request
            FakeResponse(status=400, error_message="response_format is not supported"),
            FakeResponse(text=BLUE),  # the request after the measurement
        ]
    )
    async with make_multi_client([("claims", server)], registry=registry) as client:
        before = await client.generate(
            "what colour?", target="claims:m", schema=PROBE_SCHEMA_COPY
        )
        assert before.structured_mechanism == "json_schema", "the claim is believed at first"

        report = await client.probe("claims:m", features=[Feature.JSON_SCHEMA])
        assert report.outcome_for(Feature.JSON_SCHEMA) == "unsupported"

        after = await client.generate(
            "what colour?", target="claims:m", schema=PROBE_SCHEMA_COPY
        )

    assert after.structured_mechanism == "prompt", (
        "a measured absence must outrank the descriptor's assumption"
    )


async def test_a_measured_presence_upgrades_the_mechanism() -> None:
    """The other direction: a compat endpoint that is better than its defaults assume."""
    from support import make_multi_client

    registry = _claiming_registry(Feature.STREAMING)
    server = FakeOpenAIServer(FakeResponse(text=BLUE))
    async with make_multi_client([("claims", server)], registry=registry) as client:
        before = await client.generate(
            "what colour?", target="claims:m", schema=PROBE_SCHEMA_COPY
        )
        assert before.structured_mechanism == "prompt"

        report = await client.probe("claims:m", features=[Feature.JSON_SCHEMA])
        assert report.outcome_for(Feature.JSON_SCHEMA) == "supported"

        after = await client.generate(
            "what colour?", target="claims:m", schema=PROBE_SCHEMA_COPY
        )

    assert after.structured_mechanism == "json_schema"


async def test_record_false_looks_without_committing() -> None:
    server = FakeOpenAIServer(FakeResponse(text=BLUE))
    async with make_client(server) as client:
        before = client.budget("hi", target="openai-compat:m")
        report = await client.probe(
            "openai-compat:m", features=[Feature.JSON_SCHEMA], record=False
        )
        after = client.budget("hi", target="openai-compat:m")

    assert report.capabilities is not None, "it still reports what it found"
    assert before.context_window == after.context_window


async def test_a_feature_no_probe_can_settle_is_refused() -> None:
    server = FakeOpenAIServer()
    async with make_client(server) as client:
        with pytest.raises(ai.ConfigError) as excinfo:
            await client.probe("openai-compat:m", features=[Feature.CACHE_USAGE])

    assert excinfo.value.hint is not None
    assert server.call_count == 0


async def test_probing_is_not_routed() -> None:
    """A probe measures one target; a fallback answering elsewhere would measure that."""
    from support import make_multi_client

    broken = FakeOpenAIServer(FakeResponse(status=500, error_message="down"))
    other = FakeOpenAIServer(FakeResponse(text=BLUE))
    async with make_multi_client(
        [("openai-compat", broken), ("openai", other)],
        route=ai.Route(targets=("openai-compat:m", "openai:gpt-5")),
    ) as client:
        await client.probe("openai-compat:m", features=[Feature.JSON_SCHEMA])

    assert other.call_count == 0
    assert broken.call_count == 1, "one attempt, no retry"


def test_summary_names_what_was_settled() -> None:
    report = ai.ProbeReport(
        target=ai.ResolvedTarget("openai-compat", "m"),
        probes=(
            ai.FeatureProbe(Feature.JSON_SCHEMA, "supported"),
            ai.FeatureProbe(Feature.TOOLS, "unsupported"),
            ai.FeatureProbe(Feature.STREAMING, "inconclusive"),
        ),
    )

    assert "supports JSON_SCHEMA" in report.summary
    assert "does not support TOOLS" in report.summary
    assert "STREAMING" not in report.summary, "an inconclusive probe claims nothing"


def test_sync_client_probe() -> None:
    from support import make_sync_client

    server = FakeOpenAIServer(FakeResponse(text=BLUE))
    client = make_sync_client(server)
    try:
        report = client.probe("openai-compat:m", features=[Feature.JSON_SCHEMA])
    finally:
        client.close()

    assert report.outcome_for(Feature.JSON_SCHEMA) == "supported"
