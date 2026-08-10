"""Execute the documentation's examples against the fake providers.

Documentation that no longer works is worse than none: it costs a reader their afternoon and
then their trust. Every pattern the docs teach is exercised here, so an example cannot
silently rot (DESIGN.md §25).

These are the *shapes* the docs promise, run end to end.
"""

from __future__ import annotations

import json

import anyinfer as ai
from anyinfer.testing.fakes import FakeOllamaServer, FakeOpenAIServer, FakeResponse
from support import make_client, make_sync_client


def _ollama_client(server: FakeOllamaServer) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "ollama", base_url="http://127.0.0.1:11434",
                transport=server.transport(),
            )
        ]
    )


# ---- quickstart ----------------------------------------------------------------------


def test_quickstart_first_call() -> None:
    """docs/guides/quickstart.md — the three-line sync example."""
    server = FakeOpenAIServer(FakeResponse(text="A one-sentence summary."))
    with make_sync_client(server) as client:
        result = client.generate(
            "Summarize this in one sentence:\nsome text",
            target="openai-compat:fake-model-small",
        )
    assert result.text == "A one-sentence summary."


def test_quickstart_streaming() -> None:
    """docs/guides/quickstart.md and guides/streaming.md — the streaming shape."""
    server = FakeOpenAIServer(FakeResponse(text="Streaming output."))
    with make_sync_client(server) as client, client.stream(
        "hi", target="openai-compat:m"
    ) as stream:
        chunks = [e.text for e in stream if isinstance(e, ai.TextDelta)]
        final = stream.result

    assert "".join(chunks) == "Streaming output."
    assert final.usage.output_tokens is not None
    assert final.timing.total_ms >= 0


async def test_quickstart_structured_output() -> None:
    """docs/guides/quickstart.md — schema with repair."""
    summary_schema = {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "topics": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["headline", "topics"],
    }
    payload = {"headline": "A headline", "topics": ["a", "b"]}
    server = FakeOpenAIServer(FakeResponse(text=json.dumps(payload)))

    async with make_client(server) as client:
        result = await client.generate(
            "article text",
            target="openai-compat:m",
            schema=summary_schema,
            repair=ai.Repair(max_attempts=1),
        )

    assert result.structured == payload
    assert result.structured_mechanism in {"json_schema", "grammar", "json_mode", "prompt"}


async def test_quickstart_fallback_chain() -> None:
    """docs/guides/quickstart.md and guides/fallback.md — the attempt trail."""
    server = FakeOpenAIServer(
        [FakeResponse(status=503), FakeResponse(text="recovered")]
    )
    async with make_client(server) as client:
        result = await client.generate(
            "hi",
            route=ai.Route(
                targets=("openai-compat:m",),
                retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
            ),
        )

    assert result.text == "recovered"
    assert [a.outcome for a in result.attempts] == ["retried", "ok"]
    for attempt in result.attempts:
        assert str(attempt.target)


# ---- concepts ------------------------------------------------------------------------


async def test_targets_resolve_as_documented() -> None:
    """docs/concepts/targets.md — colon splitting and alias order."""
    server = FakeOllamaServer(FakeResponse(text="ok"))
    async with _ollama_client(server) as client:
        resolved = client.resolve("ollama:qwen3:8b")
        assert resolved.provider_id == "ollama"
        assert resolved.model == "qwen3:8b"

        alias = client.resolve("medium")
        assert alias.provider_id == "ollama"
        assert alias.via_alias == "medium"


def test_catalog_overlay_is_documented_correctly() -> None:
    """docs/concepts/targets.md — an app overlay replaces an alias wholesale."""
    from anyinfer.catalog import Catalog

    overlay = Catalog.from_mapping(
        {
            "format_version": 1,
            "aliases": {
                "medium": {
                    "description": "our pinned medium tier",
                    "targets": {"anthropic": {"model": "claude-sonnet-4-5"}},
                }
            },
        }
    )
    merged = ai.load_default_catalog().overlay(overlay)

    assert merged.alias("medium").description == "our pinned medium tier"
    assert set(merged.alias("medium").targets) == {"anthropic"}
    assert merged.alias("small").targets, "other aliases are untouched"


async def test_event_ordering_as_documented() -> None:
    """docs/concepts/events.md — the four ordering guarantees."""
    server = FakeOpenAIServer(FakeResponse(text="some output"))
    async with make_client(server) as client:
        stream = client.stream("hi", target="openai-compat:m")
        events = [e async for e in stream]

    assert isinstance(events[-1], ai.StreamEnded)
    assert len([e for e in events if isinstance(e, ai.StreamEnded)]) == 1

    marks = [e.name for e in events if isinstance(e, ai.TimingMark)]
    assert marks == ["attempt_start", "first_token"]

    joined = "".join(e.text for e in events if isinstance(e, ai.TextDelta))
    assert joined == events[-1].result.text


def test_cost_is_none_when_unknown() -> None:
    """docs/concepts/capabilities.md — None is not zero."""
    usage = ai.Usage(input_tokens=100, output_tokens=50)
    assert usage.cost_usd is None


async def test_budget_preflight_shape() -> None:
    """docs/concepts/budgeting.md — the calculator, no request issued."""
    from anyinfer.providers.openai_compat import OpenAICompatAdapter
    from anyinfer.registry import ProviderDescriptor, ProviderRegistry

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id="sized",
            display_name="Sized",
            factory=OpenAICompatAdapter,
            requires_base_url=True,
            static_capabilities={
                "m": ai.ModelCapabilities(context_window=ai.Sourced(128_000, "catalog"))
            },
        )
    )
    server = FakeOpenAIServer()
    async with ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "sized", base_url="https://fake.invalid/v1", transport=server.transport()
            )
        ],
        registry=registry,
    ) as client:
        budget = client.budget("plan around me", target="sized:m")

    assert budget.input_allowance_tokens is not None
    assert budget.remaining_tokens is not None and budget.remaining_tokens > 0
    assert budget.fits is True
    assert server.call_count == 0, "budget() must not issue a request"


async def test_budget_unknown_window_is_tri_state() -> None:
    """docs/concepts/budgeting.md — unknown stays unknown."""
    server = FakeOpenAIServer()
    async with make_client(server) as client:
        budget = client.budget("hello", target="openai-compat:m")
    assert budget.fits is None


async def test_estimated_cost_and_override_shape() -> None:
    """docs/concepts/budgeting.md and capabilities.md — cost range and overrides."""
    from decimal import Decimal

    overrides = {
        "openai:gpt-5": ai.ModelCapabilities(
            pricing=ai.Sourced(ai.Pricing(Decimal("1.25"), Decimal("10")))
        )
    }
    async with ai.AsyncClient([], capability_overrides=overrides) as client:
        budget = client.budget("estimate my spend", target="openai:gpt-5")

    cost = budget.estimated_cost
    assert cost is not None and cost.low <= cost.high
    assert budget.pricing is not None and budget.pricing.provenance == "override"


async def test_custom_estimator_plugs_in() -> None:
    """docs/concepts/budgeting.md — the TokenEstimator protocol shape."""

    class Exact:
        def estimate(self, text: str) -> ai.TokenEstimate:
            count = len(text.split())
            return ai.TokenEstimate(count, count)

    server = FakeOpenAIServer(FakeResponse(text="ok"))
    async with make_client(server, estimator=Exact()) as client:
        result = await client.generate("one two three", target="openai-compat:m")
    assert result.text == "ok"


async def test_observers_are_payload_free_by_default() -> None:
    """docs/concepts/telemetry.md — payload privacy."""
    seen: list[ai.TelemetryEvent] = []

    class Recorder:
        def on_event(self, event: ai.TelemetryEvent) -> None:
            seen.append(event)

    server = FakeOpenAIServer(FakeResponse(text="the answer"))
    async with make_client(server, observers=[Recorder()]) as client:
        await client.generate("a private prompt", target="openai-compat:m")

    started = [e for e in seen if isinstance(e, ai.RequestStarted)]
    completed = [e for e in seen if isinstance(e, ai.RequestCompleted)]
    assert started and started[0].prompt_text is None
    assert completed and completed[0].response_text is None


# ---- local subsystem -----------------------------------------------------------------


def test_hardware_detection_never_raises() -> None:
    """docs/concepts/local.md — detection is advisory and total."""
    from anyinfer import local

    profile = local.detect()
    assert profile.os_name
    assert isinstance(profile.warnings, tuple)


def test_recommendation_explains_itself() -> None:
    """docs/guides/local-inference.md — recommend_alias returns a reason."""
    from anyinfer import local

    profile = local.detect()
    recommendation = local.recommend_alias(profile, ai.load_default_catalog())

    assert recommendation.alias in {"small", "medium", "large", None}
    assert recommendation.reason


def test_tuning_plan_explains_itself() -> None:
    """docs/concepts/local.md — plan.rationale is human-readable."""
    from anyinfer import local

    plan = local.plan_server(
        local.detect(),
        local.TuningInputs(artifact_size_bytes=4_680_000_000, parameter_size="7B"),
        posture="balanced",
    )
    assert plan.context_size > 0
    assert plan.rationale
    assert "--jinja" in plan.server_arguments("/m.gguf", host="127.0.0.1", port=1)


# ---- tools ---------------------------------------------------------------------------


async def test_tool_decorator_shape() -> None:
    """docs/guides/tool-loop.md — the decorator derives a schema from the signature."""

    @ai.tool
    def read_file(path: str) -> str:
        """Read a project file."""
        return f"contents of {path}"

    server = FakeOpenAIServer(
        [
            FakeResponse(
                text="",
                tool_calls=(("c1", "read_file", '{"path": "README.md"}'),),
                finish_reason="tool_calls",
            ),
            FakeResponse(text="The file says hello."),
        ]
    )
    async with make_client(server) as client:
        result = await client.run_tools(
            "What does README.md say?", tools=[read_file], target="openai-compat:m"
        )

    assert result.text == "The file says hello."
    assert read_file.spec.description == "Read a project file."


# ---- examples ------------------------------------------------------------------------


async def test_example_summarizer_shape() -> None:
    """docs/examples/summarize-with-fallback.md — schema + fallback chain together.

    The page's program combines a schema, repair, and a multi-target route; this proves
    the combination, not just each feature alone: a failing first target must still end
    in a validated structured result, with the whole journey on the attempt trail.
    """
    summary_schema = {
        "type": "object",
        "properties": {"headline": {"type": "string"}},
        "required": ["headline"],
    }
    server = FakeOpenAIServer(
        [FakeResponse(status=503), FakeResponse(text=json.dumps({"headline": "h"}))]
    )
    async with make_client(server) as client:
        result = await client.generate(
            "Summarize this text:\nsome text",
            route=ai.Route(
                targets=("openai-compat:primary", "openai-compat:fallback"),
                retry=ai.Retry(max_attempts=1),
            ),
            schema=summary_schema,
            repair=ai.Repair(max_attempts=1),
        )

    assert result.structured == {"headline": "h"}
    assert len(result.attempts) == 2, "the failed target stays on the trail"


def test_example_golden_manifest_shape(
    anyinfer_client, anyinfer_scripted, anyinfer_golden_manifest
) -> None:
    """docs/examples/golden-manifest.md — assert routing behaviour, not prose."""
    from anyinfer.testing import ScriptedFailure, ScriptedModel

    provider = anyinfer_scripted([
        ScriptedModel(
            "primary",
            failures=(ScriptedFailure(status=503, retry_after_s=0.0),),
        ),
        ScriptedModel("fallback", structured={"answer": "stable"}),
    ])
    client = anyinfer_client(provider)
    result = client.generate(
        "answer",
        route=ai.Route(
            targets=(provider.target("primary"), provider.target("fallback")),
            retry=ai.Retry(max_attempts=1, backoff_base_s=0.0),
        ),
        schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
    )

    anyinfer_golden_manifest(result.manifest, "documented_fallback")
    assert result.structured == {"answer": "stable"}


def test_example_compare_targets_spends_nothing() -> None:
    """docs/examples/compare-targets.md — two records and zero calls."""
    from anyinfer.testing import ScriptedModel, ScriptedProvider

    provider = ScriptedProvider(
        "offline", [ScriptedModel("small"), ScriptedModel("large")]
    )
    registry = provider.register(
        ai.ProviderRegistry(load_builtins=False, load_entry_points=False)
    )
    with ai.Client(
        [provider.settings()], registry=registry, use_default_catalog=False
    ) as client:
        results = client.compare(
            "Return an object",
            targets=[provider.target("small"), provider.target("large")],
            schema={"type": "object"},
        )

    assert [item.resolvable for item in results] == [True, True]
    assert provider.requests == []


async def test_example_tool_agent_shape() -> None:
    """docs/examples/local-tool-agent.md — a tool with a defaulted parameter."""

    @ai.tool
    def list_files(pattern: str = "*") -> str:
        """List project files matching a glob pattern."""
        return "pyproject.toml"

    server = FakeOpenAIServer(
        [
            FakeResponse(
                text="",
                tool_calls=(("c1", "list_files", "{}"),),
                finish_reason="tool_calls",
            ),
            FakeResponse(text="One file: pyproject.toml."),
        ]
    )
    async with make_client(server) as client:
        result = await client.run_tools(
            "What files are here?", tools=[list_files], target="openai-compat:m"
        )

    assert result.text == "One file: pyproject.toml."
    assert list_files.spec.description == "List project files matching a glob pattern."


# ---- providers -----------------------------------------------------------------------


async def test_ollama_provider_options_pass_through() -> None:
    """docs/providers/ollama.md — the escape hatch."""
    server = FakeOllamaServer(FakeResponse(text="ok"))
    async with _ollama_client(server) as client:
        await client.generate(
            "hi",
            target="ollama:qwen3:8b",
            provider_options={"ollama": {"keep_alive": "10m", "num_ctx": 8192}},
        )

    assert server.requests[0]["keep_alive"] == "10m"
    assert server.requests[0]["num_ctx"] == 8192


def test_provider_listing_matches_the_docs() -> None:
    """docs/providers/README.md — every documented provider is registered."""
    registered = set(ai.default_registry.known_ids())
    documented = {
        "openai", "anthropic", "ollama", "llama-cpp", "openai-compat",
        "openrouter", "azure-foundry", "copilot", "m365-copilot",
    }
    assert documented <= registered


def test_the_complete_provider_index_is_current() -> None:
    """docs/providers/all.md — the generated index still matches the registry.

    The page is checked in rather than built at docs time so the repository and the
    published site agree. That only holds if adding a provider regenerates it, which is
    exactly what this asserts: run `python scripts/generate_provider_index.py`.
    """
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    from generate_provider_index import render  # type: ignore[import-not-found]

    page = repo_root / "docs" / "providers" / "all.md"
    assert page.read_text(encoding="utf-8") == render(), (
        "docs/providers/all.md is stale — "
        "run `python scripts/generate_provider_index.py`"
    )


def test_every_registered_provider_appears_in_the_complete_index() -> None:
    """No provider may ship without being listed somewhere a reader can find it.

    The generator renders from the registry, so this cannot fail while the generator is
    correct — which is the point: it pins the *promise* the page makes (that it is
    complete) rather than the mechanism, and would catch a future generator that
    silently filtered a category out.
    """
    from pathlib import Path

    from anyinfer.registry import ProviderRegistry

    page = (
        Path(__file__).resolve().parent.parent / "docs" / "providers" / "all.md"
    ).read_text(encoding="utf-8")
    # A fresh registry, not the process-wide default: other tests register configured
    # *instances* (a "fake" endpoint derived from openai-compat) into the default one,
    # and those are an application's own naming rather than something to document.
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    for provider_id in registry.known_ids():
        assert f"`{provider_id}:`" in page, f"{provider_id} is missing from all.md"


def test_documented_aliases_resolve() -> None:
    """docs/providers/README.md — the alias column is accurate."""
    registry = ai.default_registry
    assert registry.resolve_alias("claude") == "anthropic"
    assert registry.resolve_alias("azure") == "azure-foundry"
    assert registry.resolve_alias("m365") == "m365-copilot"


# ---- context reduction ---------------------------------------------------------------


def test_fitting_context_guide_shape() -> None:
    """docs/guides/fitting-context.md — build documents, budget, reduce, place."""
    from anyinfer import context

    server = FakeOpenAIServer(FakeResponse(text="An answer."))
    documents = [
        context.ContextDocument.of("src/auth/credentials.py", "def resolve(ref):\n    ...\n"),
        context.ContextDocument.of("README.md", "# Project\n", pinned=True),
    ]

    with make_sync_client(server) as client:
        messages = [ai.user("How does credential resolution work?")]
        budget = client.budget(messages, target="openai-compat:fake-model-small")
        max_tokens = budget.remaining_tokens or 8_000

        reduction = context.select(
            documents,
            query="how does credential resolution work?",
            max_tokens=max_tokens,
        )
        messages.insert(0, ai.user(reduction.text))
        result = client.generate(messages, target="openai-compat:fake-model-small")

    assert result.text == "An answer."
    assert reduction.text.startswith("<context format=")
    assert reduction.summary()
    assert isinstance(reduction.metadata(), dict)


def test_context_reduction_concept_page_shapes() -> None:
    """docs/concepts/context-reduction.md — the strategies and their reporting."""
    from anyinfer import context

    documents = [
        context.ContextDocument.of(f"src/mod{i}/file.py", f"def f{i}():\n    return {i}\n" * 30)
        for i in range(5)
    ]

    for strategy in ("whole", "ranked", "tiered", "packed", "auto"):
        reduction = context.select(documents, "f1", max_tokens=400, strategy=strategy)
        assert reduction.text
        assert reduction.strategy == strategy
        assert isinstance(reduction.omitted_count, int)
        assert isinstance(reduction.complete, bool)

    cache = context.build_rank_cache(documents)
    ranked = context.rank(documents, "f1", rank_cache=cache)
    assert len(ranked) == len(documents)


def test_context_reduction_observer_shape() -> None:
    """docs/guides/fitting-context.md — observing a reduction."""
    from anyinfer import context

    seen: list[ai.TelemetryEvent] = []

    class ContextWatcher:
        def on_event(self, event: ai.TelemetryEvent) -> None:
            if isinstance(event, ai.ContextReduced):
                seen.append(event)

    documents = [context.ContextDocument.of("a.py", "x = 1\n" * 500)]
    context.select(documents, "x", max_tokens=50, strategy="ranked",
                   observer=ContextWatcher())

    assert seen and isinstance(seen[0], ai.ContextReduced)


async def test_distill_cookbook_shapes() -> None:
    """docs/examples/distill-a-corpus.md — the basic shape and a deterministic reducer."""
    from anyinfer import context

    server = FakeOpenAIServer(FakeResponse(text="a note"))
    async with make_client(server) as client:
        result = await context.distill(
            "some long material",
            "What changed?",
            client=client,
            target="openai-compat:fake-model-small",
            chunk_tokens=512,
        )
        assert result.text == "a note"
        assert result.calls == 2

        merged = await context.distill(
            "some long material",
            "What changed?",
            client=client,
            target="openai-compat:fake-model-small",
            chunk_tokens=512,
            reducer=lambda notes: " | ".join(notes),
        )
        assert merged.calls == merged.chunk_count, "a reducer spends no reduce call"


def test_module_digest_recipe_shape() -> None:
    """docs/examples/distill-a-corpus.md — module_surfaces feeds tiered digests."""
    from anyinfer import context

    documents = [
        context.ContextDocument.of("src/auth/a.py", "def a():\n    pass\n" * 20),
        context.ContextDocument.of("src/auth/b.py", "def b():\n    pass\n" * 20),
    ]
    surfaces = context.module_surfaces(documents, depth=2)
    assert set(surfaces) == {"src/auth"}

    reduction = context.select(
        documents, "a", max_tokens=4000, strategy="tiered",
        module_digests=dict.fromkeys(surfaces, "Auth helpers."),
    )
    assert "Auth helpers." in reduction.text


# ---- local models --------------------------------------------------------------------


def test_local_models_browse_and_filter(tmp_path) -> None:
    """docs/guides/local-models.md — step 1, browsing with fit annotations."""
    from anyinfer import local

    specs = local.HardwareProfile.from_user_input(ram_gb=64, vram_gb=24, accelerator="cuda")
    with ai.Client(model_dir=tmp_path) as client:
        view = client.local_catalog("llama-cpp", best_at="coding", hardware=specs)

        assert view.runnable
        for entry in view.runnable:
            assert entry.model.est_file_bytes
            assert entry.fit.reasons

        ranks = [entry.fit.rank for entry in view.entries]
        assert ranks == sorted(ranks, reverse=True), "best fit first"


def test_local_models_remote_host_flow(tmp_path) -> None:
    """docs/guides/local-models.md — asking the user for a remote host's specs."""
    from anyinfer import local

    settings = ai.ProviderSettings.of("ollama", base_url="http://192.168.1.50:11434")
    with ai.Client([settings], model_dir=tmp_path) as client:
        blind = client.local_catalog("ollama")
        assert blind.hardware_source == "unavailable"

        specs = local.HardwareProfile.from_user_input(
            ram_gb=64, vram_gb=24, accelerator="cuda"
        )
        informed = client.local_catalog("ollama", hardware=specs)
        assert informed.hardware_source == "provided"
        assert any(entry.fit.level != "unknown" for entry in informed.entries)


def test_local_models_alias_bridge(tmp_path) -> None:
    """docs/guides/local-models.md — using a catalog pick as the medium tier."""
    catalog = ai.load_default_catalog().with_alias_target(
        "medium", "llama-cpp", "qwen2.5-coder-14b-instruct"
    )
    with ai.Client([ai.ProviderSettings.of("llama-cpp")], catalog=catalog,
                    model_dir=tmp_path) as client:
        resolved = client.resolve("medium")
        assert resolved.provider_id == "llama-cpp"
        assert resolved.model in catalog.artifacts


def test_local_models_locate_returns_none_before_acquisition(tmp_path) -> None:
    """docs/concepts/models.md — locate() is a lookup, not a download."""
    with ai.Client(model_dir=tmp_path) as client:
        assert client.locate_model("qwen2.5-7b-instruct") is None


def test_fitting_context_guide_planning_and_tuning() -> None:
    """docs/guides/fitting-context.md — plan, the recommended preset, carry-over."""
    from anyinfer import context

    documents = [
        context.ContextDocument.of(
            f"src/mod{i}/file.py", f"def resolve_{i}(ref):\n    return ref\n" * 20
        )
        for i in range(6)
    ]
    query = "how does credential resolution work?"
    max_tokens = 1_200

    outcome = context.plan(documents, query, max_tokens=max_tokens)
    for option in outcome.options:
        assert isinstance(option.selected_count, int)
        assert isinstance(option.complete, bool)

    best = outcome.best()
    reduction = context.select(
        documents, query, max_tokens=max_tokens, strategy=best.strategy if best else "auto"
    )
    assert reduction.estimated_tokens <= max_tokens

    recommended = context.select(
        documents, query, max_tokens=max_tokens, tuning=context.ContextTuning.recommended()
    )
    assert recommended.estimated_tokens <= max_tokens

    tuning = context.ContextTuning(carry_over_bonus=0.5)
    first = context.select(documents, query, max_tokens=max_tokens, tuning=tuning)
    second = context.select(
        documents, query, max_tokens=max_tokens, tuning=tuning, previous=first.state()
    )
    assert second.carried_over == len(first.documents)


def test_fitting_context_guide_history_compaction() -> None:
    """docs/guides/fitting-context.md — compact the conversation, then send it."""
    from anyinfer import context

    server = FakeOpenAIServer(FakeResponse(text="An answer."))
    messages = [ai.system("Be brief.")]
    for index in range(10):
        messages.append(ai.user(f"Question {index}. {'x' * 2_000}"))
        messages.append(ai.assistant(f"Answer {index}. {'y' * 2_000}"))
    messages.append(ai.user("And finally?"))

    with make_sync_client(server) as client:
        compaction = context.compact_history(messages, max_tokens=4_000, keep_recent=2)
        assert compaction.fits
        result = client.generate(
            list(compaction.messages), target="openai-compat:fake-model-small"
        )

    assert result.text == "An answer."
    assert compaction.summary()
    assert compaction.messages[0].role == "system"


def test_context_reduction_client_policy_shape() -> None:
    """docs/concepts/context-reduction.md — hand the policy to the client."""
    server = FakeOpenAIServer(FakeResponse(text="An answer."))
    messages = [ai.system("Be brief.")]
    for index in range(5):
        messages.append(ai.user(f"Q{index}. " + "x" * 10_000))
        messages.append(ai.assistant(f"A{index}. " + "y" * 10_000))
    messages.append(ai.user("And finally?"))

    overrides = {
        "openai-compat:fake-model-small": ai.ModelCapabilities(
            context_window=ai.Sourced(8_192, "catalog")
        )
    }
    with make_sync_client(
        server,
        capability_overrides=overrides,
        history=ai.HistoryPolicy(mode="proactive", keep_recent=1),
    ) as client:
        result = client.generate(messages, target="openai-compat:fake-model-small")

    assert result.text == "An answer."


# ---- testing your application --------------------------------------------------------


def test_docs_testing_guide_scripted_provider() -> None:
    """docs/guides/testing-your-app.md — declare a provider, get a real client."""
    from anyinfer.registry import ProviderRegistry
    from anyinfer.testing import ScriptedModel, ScriptedProvider

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    provider = ScriptedProvider("acme", [ScriptedModel("small", text="A one-sentence summary.")])
    provider.register(registry)

    client = ai.Client(
        [provider.settings()], registry=registry, use_default_catalog=False
    )
    with client:
        result = client.generate("Summarize this", target=provider.target("small"))
    assert result.text == "A one-sentence summary."


def test_docs_testing_guide_fallback_and_repair() -> None:
    """docs/guides/testing-your-app.md — scripted failures drive retry and repair."""
    from anyinfer.registry import ProviderRegistry
    from anyinfer.testing import ScriptedFailure, ScriptedModel, ScriptedProvider

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    provider = ScriptedProvider(
        "acme",
        [
            ScriptedModel("flaky", failures=(ScriptedFailure(status=503, retry_after_s=0.0),)),
            ScriptedModel(
                "structured",
                structured={"answer": "valid on the second try"},
                failures=(ScriptedFailure(kind="malformed-json"),),
            ),
        ],
    )
    provider.register(registry)

    client = ai.Client([provider.settings()], registry=registry, use_default_catalog=False)
    with client:
        retried = client.generate("hi", target=provider.target("flaky"))
        repaired = client.generate(
            "extract",
            target=provider.target("structured"),
            schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
            repair=ai.Repair(max_attempts=1),
        )

    assert [attempt.outcome for attempt in retried.attempts] == ["retried", "ok"]
    assert repaired.structured == {"answer": "valid on the second try"}
    assert repaired.repair_attempts == 1


# ---- coding agents -------------------------------------------------------------------
#
# Every "what the API actually is" cell in the fragment `anyinfer agents-md` prints is
# backed by one test here (AL.3). A wrong claim in that fragment is worse than no
# fragment: it is read in somebody else's repository, by an agent with no way to check
# it. So it fails CI instead.


async def test_agents_md_row_targets_are_provider_qualified() -> None:
    """Row: `target=`, not `model=`, and the split is on the first colon only."""
    server = FakeOllamaServer(FakeResponse(text="ok"))
    async with _ollama_client(server) as client:
        resolved = client.resolve("ollama:qwen3:8b")
        alias = client.resolve("medium")

    assert resolved.provider_id == "ollama"
    assert resolved.model == "qwen3:8b", "only the first colon separates provider and model"
    assert alias.via_alias == "medium", "a bare string with no colon is a catalog alias"


async def test_agents_md_row_schema_replaces_response_format() -> None:
    """Row: `schema=`, and the reply is validated before the caller sees it."""
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"answer": "yes"})))
    async with make_client(server) as client:
        result = await client.generate("q", target="openai-compat:m", schema=schema)

    assert result.structured == {"answer": "yes"}
    assert result.structured_mechanism in {"json_schema", "grammar", "json_mode", "prompt"}
    assert "response_format" not in server.requests[0] or server.requests[0].get(
        "response_format"
    ), "the mechanism is chosen by the core, never asked for by the caller"


def test_agents_md_row_there_is_no_openai_shaped_namespace() -> None:
    """Row: `client.generate(...)`, not `client.chat.completions.create(...)`."""
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    with make_sync_client(server) as client:
        assert not hasattr(client, "chat")
        assert not hasattr(client, "completions")
        for method in ("generate", "stream", "run_tools", "budget", "verify"):
            assert callable(getattr(client, method))


async def test_agents_md_row_the_router_owns_retry() -> None:
    """Row: `ai.Route` / `ai.Retry`, and every attempt lands on the trail."""
    server = FakeOpenAIServer(
        [FakeResponse(status=503), FakeResponse(text="recovered")]
    )
    async with make_client(server) as client:
        result = await client.generate(
            "hi",
            route=ai.Route(
                targets=("openai-compat:m",),
                retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
            ),
        )
    assert result.text == "recovered"
    assert [a.outcome for a in result.attempts] == ["retried", "ok"]


def test_agents_md_row_cost_is_a_decimal_and_none_is_not_zero() -> None:
    """Row: `Decimal`, and `None` means unknown. Coercing it to 0 is the trap."""
    from decimal import Decimal

    assert ai.Usage(input_tokens=100, output_tokens=50).cost_usd is None
    priced = ai.Usage(input_tokens=1, output_tokens=1, cost_usd=Decimal("0.000125"))
    assert isinstance(priced.cost_usd, Decimal)


async def test_agents_md_row_capabilities_carry_provenance() -> None:
    """Row: a capability is `Sourced[T]`, never a bare number."""
    overrides = {
        "openai-compat:m": ai.ModelCapabilities(
            context_window=ai.Sourced(8_192, "catalog")
        )
    }
    server = FakeOpenAIServer()
    async with make_client(server, capability_overrides=overrides) as client:
        window = client.budget("hi", target="openai-compat:m").context_window

    assert window is not None
    assert window.value == 8_192, "the value is reached through .value, not directly"
    assert window.provenance in {"catalog", "discovered", "probed", "default", "override"}


def test_agents_md_row_there_is_no_per_provider_extra() -> None:
    """Row: `pip install anyinfer[anthropic]` names an extra that has never existed."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    with (root / "pyproject.toml").open("rb") as handle:
        extras = set(tomllib.load(handle)["project"].get("optional-dependencies", {}))

    provider_ids = set(ai.default_registry.known_ids())
    # Two extras share a provider's name, and both are honest: each exists because that
    # adapter needs a real dependency (a vendor SDK, an RSA implementation), not because
    # hosted providers are sold separately. Every other provider works on the core alone.
    assert extras & provider_ids == {"copilot", "vertex"}
    assert "anthropic" not in extras and "openai" not in extras


def test_every_trap_row_has_a_test() -> None:
    """A row added without a test would be an unchecked claim in a stranger's repo."""
    from anyinfer._agents_md import render_agents_md

    fragment = render_agents_md()
    table = fragment.split("### What not to guess", 1)[1].split("###", 1)[0]
    rows = [line for line in table.splitlines() if line.startswith("| `") or
            line.startswith("| a ")]
    covered = [
        name for name in globals() if name.startswith("test_agents_md_row_")
    ]
    assert len(rows) == len(covered), (
        f"{len(rows)} trap rows but {len(covered)} tests — add one beside the others"
    )
