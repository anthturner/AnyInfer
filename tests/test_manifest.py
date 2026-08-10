"""Run-manifest assembly, derivation, redaction, and golden files."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from decimal import Decimal
from typing import Any

import jsonschema
import pytest

from anyinfer import (
    AsyncClient,
    Feature,
    ModelCapabilities,
    Pricing,
    Repair,
    Route,
    RunManifest,
    Sourced,
    manifest_json_schema,
)
from anyinfer.events.telemetry import (
    AttemptStarted,
    CachePlanned,
    ContextReduced,
    FallbackTriggered,
    ParameterDropped,
    RepairAttempted,
    RetryScheduled,
)
from anyinfer.manifest import MANIFEST_FORMAT, ManifestBuilder, render, schema_digest
from anyinfer.redaction import register_secret, registry
from anyinfer.testing import (
    ScriptedFailure,
    ScriptedModel,
    ScriptedProvider,
    assert_manifest_matches,
    normalize,
)
from anyinfer.testing.plugin import EventCollector

SHAPE = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


def _provider(registry_: Any, models: list[ScriptedModel], **kwargs: Any) -> ScriptedProvider:
    provider = ScriptedProvider("scripted", models, **kwargs)
    provider.register(registry_)
    return provider


class TestAssembly:
    """RM.2 — the builder folds a run into a record that survives a round trip."""

    @pytest.mark.asyncio
    async def test_records_fallback_degradation_and_repair(
        self, anyinfer_registry: Any, anyinfer_events: EventCollector
    ) -> None:
        first = _provider(
            anyinfer_registry,
            [ScriptedModel("broken", failures=(ScriptedFailure(retry_after_s=0.0),) * 3)],
        )
        second = ScriptedProvider("backup", [ScriptedModel("good", structured={"answer": "yes"})])
        second.register(anyinfer_registry)

        async with AsyncClient(
            [first.settings(), second.settings()],
            registry=anyinfer_registry,
            observers=[anyinfer_events],
            use_default_catalog=False,
        ) as client:
            result = await client.generate(
                "hi",
                route=Route(targets=("scripted:broken", "backup:good")),
                schema=SHAPE,
                repair=Repair(max_attempts=1),
            )

        manifest = result.manifest
        assert manifest is not None
        assert manifest.format == MANIFEST_FORMAT
        assert manifest.complete is True
        assert manifest.route.requested == ("scripted:broken", "backup:good")
        assert manifest.route.resolved == "backup:good"
        assert [step.target for step in manifest.route.considered][-1] == "backup:good"
        assert any(a.target == "scripted:broken" for a in manifest.attempts)
        # The ladder degraded: the scripted provider offers json_mode, not json_schema.
        assert manifest.structured.requested is True
        assert manifest.structured.chosen == "json_mode"
        rejected = {r.mechanism: r.reason for r in manifest.structured.ladder if not r.available}
        assert "json_schema" in rejected
        assert "not known to support" in rejected["json_schema"]

    @pytest.mark.asyncio
    async def test_round_trips_through_dict(self, anyinfer_registry: Any) -> None:
        provider = _provider(anyinfer_registry, [ScriptedModel("m")])
        async with AsyncClient(
            [provider.settings()], registry=anyinfer_registry, use_default_catalog=False
        ) as client:
            result = await client.generate("hi", target="scripted:m")

        assert result.manifest is not None
        data = result.manifest.to_dict()
        assert RunManifest.from_dict(data) == result.manifest
        assert json.loads(result.manifest.to_json()) == data

    def test_unknown_keys_are_ignored_on_load(self) -> None:
        data = RunManifest(request_id="x").to_dict()
        data["a_field_from_the_future"] = 1
        data["route"]["another_one"] = True
        assert RunManifest.from_dict(data).request_id == "x"

    def test_schema_digest_is_key_order_independent(self) -> None:
        assert schema_digest({"a": 1, "b": 2}) == schema_digest({"b": 2, "a": 1})
        assert schema_digest({"a": 1}) != schema_digest({"a": 2})


class TestClientWiring:
    """RM.3 — opt-out, per-request override, and the stream handle."""

    @pytest.mark.asyncio
    async def test_disabled_allocates_no_builder(self, anyinfer_registry: Any) -> None:
        provider = _provider(anyinfer_registry, [ScriptedModel("m")])
        async with AsyncClient(
            [provider.settings()],
            registry=anyinfer_registry,
            use_default_catalog=False,
            manifests=False,
        ) as client:
            result = await client.generate("hi", target="scripted:m")
            assert result.manifest is None
            assert client._builders == {}

    @pytest.mark.asyncio
    async def test_per_request_override(self, anyinfer_registry: Any) -> None:
        provider = _provider(anyinfer_registry, [ScriptedModel("m")])
        async with AsyncClient(
            [provider.settings()],
            registry=anyinfer_registry,
            use_default_catalog=False,
            manifests=False,
        ) as client:
            result = await client.generate("hi", target="scripted:m", manifest=True)
            assert result.manifest is not None
            assert client._builders == {}, "the registry is cleaned up after the run"

    @pytest.mark.asyncio
    async def test_stream_handle_answers_before_and_after_completion(
        self, anyinfer_registry: Any
    ) -> None:
        provider = _provider(anyinfer_registry, [ScriptedModel("m", text="hello")])
        async with AsyncClient(
            [provider.settings()], registry=anyinfer_registry, use_default_catalog=False
        ) as client:
            stream = client.stream("hi", target="scripted:m")
            partial = stream.manifest
            assert partial is not None
            assert partial.complete is False
            result = await stream.collect()
            assert stream.manifest is not None
            assert stream.manifest.complete is True
            assert result.manifest is not None

    @pytest.mark.asyncio
    async def test_abandoned_stream_leaves_no_builder_behind(self, anyinfer_registry: Any) -> None:
        provider = _provider(anyinfer_registry, [ScriptedModel("m", text="hello")])
        async with AsyncClient(
            [provider.settings()], registry=anyinfer_registry, use_default_catalog=False
        ) as client:
            async with client.stream("hi", target="scripted:m") as stream:
                await stream.__anext__()
            assert client._builders == {}
            # The handle still answers, which is the point of a cancelled call's manifest.
            assert stream.manifest is not None
            assert stream.manifest.complete is False


class TestProvenanceFidelity:
    """RM.4 — no field collapses a `Sourced` value into a bare one."""

    @pytest.mark.asyncio
    async def test_probed_and_default_windows_are_distinguishable(
        self, anyinfer_registry: Any
    ) -> None:
        provider = _provider(anyinfer_registry, [ScriptedModel("m")])
        overrides = {
            "scripted:m": ModelCapabilities(
                context_window=Sourced(4096, "override"),
                pricing=Sourced(
                    Pricing(input_per_1m=Decimal("1"), output_per_1m=Decimal("2")),
                    "catalog",
                ),
            )
        }
        async with AsyncClient(
            [provider.settings()],
            registry=anyinfer_registry,
            use_default_catalog=False,
            capability_overrides=overrides,
        ) as client:
            result = await client.generate("hi", target="scripted:m")

        assert result.manifest is not None
        facts = {f.name: f for f in result.manifest.capability.facts}
        assert facts["context_window"].value == 4096
        assert facts["context_window"].provenance == "override"
        assert facts["pricing"].provenance == "override"
        assert facts["features"].provenance == "default"

    def test_every_capability_fact_carries_a_provenance(self) -> None:
        builder = _builder()
        builder.note_capabilities(
            _target(),
            ModelCapabilities(
                context_window=Sourced(1, "probed"),
                max_output_tokens=Sourced(2, "discovered"),
                features=Sourced(Feature.TOOLS, "catalog"),
                default_temperature=Sourced(0.4, "catalog"),
                default_top_p=Sourced(1.0, "catalog"),
            ),
        )
        facts = builder.build().capability.facts
        assert {f.name for f in facts} == {
            "context_window",
            "max_output_tokens",
            "default_temperature",
            "default_top_p",
            "features",
        }
        assert all(f.provenance for f in facts)


class TestPayloadDiscipline:
    """RM.7 — a default manifest is safe to paste into a public issue tracker."""

    @pytest.fixture(autouse=True)
    def _clean_registry(self) -> Any:
        registry.clear()
        yield
        registry.clear()

    @pytest.mark.asyncio
    async def test_default_manifest_carries_no_prompt_schema_or_secret(
        self, anyinfer_registry: Any
    ) -> None:
        secret = "sk-super-secret-value"
        register_secret(secret)
        provider = _provider(
            anyinfer_registry,
            [
                ScriptedModel(
                    "m",
                    structured={"answer": "ok"},
                    failures=(ScriptedFailure(kind="malformed-json"),),
                )
            ],
        )
        async with AsyncClient(
            [provider.settings()], registry=anyinfer_registry, use_default_catalog=False
        ) as client:
            result = await client.generate(
                f"the password is {secret}, please remember it",
                target="scripted:m",
                schema={**SHAPE, "description": secret},
                repair=Repair(max_attempts=1),
            )

        assert result.manifest is not None
        assert result.manifest.payloads is None
        serialized = result.manifest.to_json()
        assert secret not in serialized
        assert "the password is" not in serialized
        assert "not json" not in serialized

    @pytest.mark.asyncio
    async def test_payload_manifest_redacts_every_captured_string(
        self, anyinfer_registry: Any
    ) -> None:
        secret = "sk-super-secret-value"
        register_secret(secret)
        provider = _provider(
            anyinfer_registry,
            [
                ScriptedModel(
                    "m",
                    structured={"answer": "ok"},
                    failures=(ScriptedFailure(kind="malformed-json", message=secret),),
                )
            ],
        )
        async with AsyncClient(
            [provider.settings()],
            registry=anyinfer_registry,
            use_default_catalog=False,
            manifest_payloads=True,
        ) as client:
            result = await client.generate(
                f"the password is {secret}",
                target="scripted:m",
                schema={**SHAPE, "description": secret},
                repair=Repair(max_attempts=1),
            )

        manifest = result.manifest
        assert manifest is not None and manifest.payloads is not None
        assert manifest.payloads.prompt_text is not None
        assert "the password is" in manifest.payloads.prompt_text
        assert manifest.payloads.schema_body is not None
        assert manifest.payloads.repair_texts, "the failed response was captured"
        assert secret not in manifest.to_json()
        assert "[redacted]" in manifest.to_json()


class TestDerivation:
    """RM.8 — the manifest and the event stream may not disagree."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "scenario",
        ["plain", "retry", "fallback", "repair", "dropped", "cache", "compaction"],
    )
    async def test_matches_a_subscribed_observer(
        self, anyinfer_registry: Any, anyinfer_events: EventCollector, scenario: str
    ) -> None:
        result, client = await _run_scenario(scenario, anyinfer_registry, anyinfer_events)
        manifest = result.manifest
        assert manifest is not None

        events = anyinfer_events.events
        # A derivation test where both representations are empty proves nothing, so each
        # scenario asserts it actually reached the machinery it is named for.
        witness = {
            "plain": lambda: len(events) > 3,
            "retry": lambda: any(isinstance(e, RetryScheduled) for e in events),
            "fallback": lambda: any(isinstance(e, FallbackTriggered) for e in events),
            "repair": lambda: any(isinstance(e, RepairAttempted) for e in events),
            "dropped": lambda: any(isinstance(e, ParameterDropped) for e in events),
            "cache": lambda: any(isinstance(e, CachePlanned | ParameterDropped) for e in events),
            "compaction": lambda: any(isinstance(e, ContextReduced) for e in events),
        }[scenario]
        assert witness(), f"the {scenario} scenario never reached its own code path"

        # Every attempt the events describe is in the manifest, and no other.
        started = [e for e in events if isinstance(e, AttemptStarted)]
        assert len(manifest.attempts) == len(started)
        assert [(a.target, a.attempt_number) for a in manifest.attempts] == [
            (str(e.target), e.attempt_number) for e in started
        ]

        # Retries, fallbacks, repairs, drops, reductions, and cache plans all match.
        assert len([a for a in manifest.attempts if a.outcome == "retried"]) == len(
            [e for e in events if isinstance(e, RetryScheduled)]
        )
        assert len([s for s in manifest.route.considered if s.outcome == "abandoned"]) == len(
            [e for e in events if isinstance(e, FallbackTriggered) and e.error is not None]
        )
        assert len(manifest.structured.repairs) == len(
            [e for e in events if isinstance(e, RepairAttempted)]
        )
        assert [(d.parameter, d.reason) for d in manifest.dropped] == [
            (e.parameter, e.reason) for e in events if isinstance(e, ParameterDropped)
        ]
        assert len(manifest.context.reductions) == len(
            [e for e in events if isinstance(e, ContextReduced)]
        )
        planned = [e for e in events if isinstance(e, CachePlanned)]
        if planned:
            assert manifest.cache.mechanism == planned[-1].mechanism
            assert manifest.cache.mark_count == planned[-1].mark_count

        await client.aclose()

    @pytest.mark.asyncio
    async def test_events_for_another_request_are_ignored(self, anyinfer_registry: Any) -> None:
        builder = _builder(request_id="mine")
        builder.observe(AttemptStarted("theirs", _target(), 1))
        assert builder.build().attempts == ()


class TestGoldenFiles:
    """RM.9 — a golden manifest is stable across runs, and fails when behaviour moves."""

    def test_normalize_drops_only_volatile_fields(self) -> None:
        manifest = RunManifest(request_id="x", anyinfer_version="9.9.9")
        data = normalize(manifest)
        assert "request_id" not in data
        assert "anyinfer_version" not in data
        assert data["timing"] == {}
        assert "route" in data and "structured" in data

    @pytest.mark.asyncio
    async def test_golden_survives_two_runs_and_catches_a_route_change(
        self, anyinfer_registry: Any, tmp_path: Any
    ) -> None:
        provider = _provider(anyinfer_registry, [ScriptedModel("m"), ScriptedModel("n")])
        golden = tmp_path / "run.json"
        async with AsyncClient(
            [provider.settings()], registry=anyinfer_registry, use_default_catalog=False
        ) as client:
            first = await client.generate("hi", target="scripted:m")
            assert first.manifest is not None
            assert_manifest_matches(first.manifest, golden)

            second = await client.generate("hi", target="scripted:m")
            assert second.manifest is not None
            assert_manifest_matches(second.manifest, golden)

            moved = await client.generate("hi", target="scripted:n")
            assert moved.manifest is not None
            with pytest.raises(AssertionError, match="no longer matches"):
                assert_manifest_matches(moved.manifest, golden)

            assert_manifest_matches(moved.manifest, golden, update=True)
            assert_manifest_matches(moved.manifest, golden)

    @pytest.mark.asyncio
    async def test_plugin_fixture_writes_beside_the_test(
        self, anyinfer_registry: Any, anyinfer_golden_manifest: Any
    ) -> None:
        provider = _provider(anyinfer_registry, [ScriptedModel("m")])
        async with AsyncClient(
            [provider.settings()], registry=anyinfer_registry, use_default_catalog=False
        ) as client:
            result = await client.generate("hi", target="scripted:m")
        anyinfer_golden_manifest(result.manifest, "plugin_fixture")


class TestPublishedSchema:
    """RM.10 — the shipped JSON Schema describes what is actually produced."""

    @pytest.mark.asyncio
    async def test_a_real_manifest_validates(self, anyinfer_registry: Any) -> None:
        provider = _provider(
            anyinfer_registry,
            [
                ScriptedModel(
                    "m",
                    structured={"answer": "ok"},
                    failures=(ScriptedFailure(retry_after_s=0.0),),
                )
            ],
        )
        async with AsyncClient(
            [provider.settings()], registry=anyinfer_registry, use_default_catalog=False
        ) as client:
            result = await client.generate("hi", target="scripted:m", schema=SHAPE)
        assert result.manifest is not None
        jsonschema.validate(result.manifest.to_dict(), manifest_json_schema())

    def test_every_facet_field_is_described(self) -> None:
        schema = manifest_json_schema()
        for f in fields(RunManifest):
            assert f.name in schema["properties"], f"{f.name} is missing from the schema"
            nested = getattr(RunManifest(), f.name)
            described = schema["properties"][f.name]
            if not is_dataclass(nested) or "properties" not in described:
                continue
            for inner in fields(nested):
                assert inner.name in described["properties"], (
                    f"{f.name}.{inner.name} is missing from the schema"
                )


class TestRendering:
    """RM.5 — the human tree is legible, ASCII, and fits its column budget."""

    @pytest.mark.asyncio
    async def test_renders_a_fallback_and_repair_run_in_80_columns(
        self, anyinfer_registry: Any
    ) -> None:
        result, client = await _run_scenario("repair", anyinfer_registry, EventCollector())
        assert result.manifest is not None
        text = render(result.manifest, width=80)
        await client.aclose()

        assert all(len(line) <= 80 for line in text.splitlines())
        assert text.isascii(), "a Windows console cannot encode the rest"
        assert "structured output" in text
        assert "repairs" in text


# ---- helpers -------------------------------------------------------------------------


def _target() -> Any:
    from anyinfer import ResolvedTarget

    return ResolvedTarget("scripted", "m")


def _builder(request_id: str = "rid") -> ManifestBuilder:
    from anyinfer import GenerationRequest, user

    return ManifestBuilder(
        GenerationRequest(messages=(user("hi"),)),
        ["scripted:m"],
        request_id=request_id,
    )


async def _run_scenario(
    scenario: str, registry_: Any, events: EventCollector
) -> tuple[Any, AsyncClient]:
    """Run one scripted scenario, returning its result and the still-open client."""
    from anyinfer import CachePolicy, HistoryPolicy, Sampling, assistant, user

    kwargs: dict[str, Any] = {}
    call: dict[str, Any] = {}
    messages: Any = "hi"

    if scenario == "retry":
        models = [ScriptedModel("m", failures=(ScriptedFailure(),))]
        providers = [_provider(registry_, models)]
        call["target"] = "scripted:m"
    elif scenario == "fallback":
        first = _provider(
            registry_, [ScriptedModel("m", failures=(ScriptedFailure(retry_after_s=0.0),) * 3)]
        )
        second = ScriptedProvider("backup", [ScriptedModel("good")])
        second.register(registry_)
        providers = [first, second]
        call["route"] = Route(targets=("scripted:m", "backup:good"))
    elif scenario == "repair":
        providers = [
            _provider(
                registry_,
                [
                    ScriptedModel(
                        "m",
                        structured={"answer": "ok"},
                        failures=(ScriptedFailure(kind="malformed-json"),),
                    )
                ],
            )
        ]
        call.update(target="scripted:m", schema=SHAPE, repair=Repair(max_attempts=1))
    elif scenario == "dropped":
        providers = [_provider(registry_, [ScriptedModel("m")])]
        call.update(target="scripted:m", reasoning="high")
        # A *trusted* absence is what makes the core withhold the parameter; a default
        # feature set is a guess, and the core sends it rather than dropping on a guess.
        kwargs["capability_overrides"] = {
            "scripted:m": ModelCapabilities(
                features=Sourced(Feature.STREAMING | Feature.TOOLS, "override")
            )
        }
    elif scenario == "cache":
        providers = [_provider(registry_, [ScriptedModel("m")])]
        call.update(target="scripted:m", cache=CachePolicy(mode="auto"))
    elif scenario == "compaction":
        providers = [_provider(registry_, [ScriptedModel("m")])]
        messages = [user("x" * 8000), assistant("y" * 8000), user("hi")]
        call.update(
            target="scripted:m",
            history=HistoryPolicy(mode="proactive", keep_recent=1),
            # Without a cap the derived output reserve claims the whole window, leaving
            # nothing for compaction to compact into.
            sampling=Sampling(max_output_tokens=128),
        )
        kwargs["capability_overrides"] = {
            "scripted:m": ModelCapabilities(context_window=Sourced(2048, "override"))
        }
        kwargs["context_gate"] = False
    else:
        providers = [_provider(registry_, [ScriptedModel("m")])]
        call["target"] = "scripted:m"

    client = AsyncClient(
        [p.settings() for p in providers],
        registry=registry_,
        observers=[events],
        use_default_catalog=False,
        **kwargs,
    )
    return await client.generate(messages, **call), client
