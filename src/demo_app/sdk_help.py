"""The demo's "How is this built?" registry: every visible surface, mapped to the SDK.

Each `HelpTopic` ties one thing the user can see or click to the public AnyInfer calls
that implement it, with a minimal snippet showing the same thing done from plain Python.
The widgets never write their own explanation prose — they name a topic key, and the
help dialog renders this registry, so the story the UI tells and the API it points at
cannot drift apart silently. A test resolves every ``api`` entry against the real
package, which turns "the help is stale" from a review comment into a red test.

This module is deliberately import-light: pure data plus a resolver, no Qt. The dialog
that renders topics lives in `demo_app.widgets.sdk_help`.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

__all__ = ["TOPICS", "HelpTopic", "covered_symbols", "resolve_api", "uncovered_symbols"]


@dataclass(frozen=True, slots=True)
class HelpTopic:
    """One mapping from a demo surface to the SDK that implements it.

    Attributes:
        key: Stable identifier widgets use to request this topic.
        title: Heading shown in the help dialog.
        summary: What the surface shows, and which part of the library does the work.
        api: Dotted paths into the ``anyinfer`` package (``"Client.stream"``,
            ``"testing.ScriptedProvider"``). Every entry must resolve — tested.
        snippet: A minimal plain-Python version of the same behaviour.
        demo_source: Repo-relative path to where this demo wires it up.
    """

    key: str
    title: str
    summary: str
    api: tuple[str, ...]
    snippet: str
    demo_source: str


def resolve_api(path: str) -> Any:
    """Resolve one dotted ``api`` entry against the real ``anyinfer`` package.

    Walks attributes from the package root, importing submodules on demand, so
    ``"Client.stream"`` and ``"testing.ScriptedProvider"`` both resolve. While the walk
    is still inside a package, a submodule wins over a same-named attribute —
    ``anyinfer.local`` re-exports a *function* called ``acquire`` that would otherwise
    shadow the ``local.acquire`` module. Raises ``AttributeError`` (or ``ImportError``)
    when the entry has drifted from the API, which is exactly what the help test wants
    to catch.
    """
    import types

    current: Any = importlib.import_module("anyinfer")
    walked = "anyinfer"
    for part in path.split("."):
        if isinstance(current, types.ModuleType):
            try:
                current = importlib.import_module(f"{walked}.{part}")
            except ModuleNotFoundError:
                current = getattr(current, part)
        else:
            current = getattr(current, part)
        walked = f"{walked}.{part}"
    return current


TOPICS: dict[str, HelpTopic] = {
    topic.key: topic
    for topic in (
        HelpTopic(
            key="streaming",
            title="Streaming chat",
            summary=(
                "Every answer in the transcript arrives as a typed event stream — "
                "TextDelta fragments, a first-token timing mark, usage updates, then a "
                "StreamEnded carrying the finished Generation. The demo never parses "
                "provider wire formats: Client.stream() normalizes all of them into the "
                "same events, and the bubbles just append what they are handed."
            ),
            api=(
                "Client.stream",
                "SyncStream",
                "TextDelta",
                "ReasoningDelta",
                "TimingMark",
                "UsageUpdate",
                "AttemptFailed",
                "StreamEnded",
                "Generation",
            ),
            snippet=(
                "import anyinfer as ai\n"
                "\n"
                'client = ai.Client([ai.ProviderSettings.of("ollama")])\n'
                'with client.stream("Tell me a joke.", target="ollama:qwen3:8b") as stream:\n'
                "    for event in stream:\n"
                "        if isinstance(event, ai.TextDelta):\n"
                '            print(event.text, end="", flush=True)\n'
                "        elif isinstance(event, ai.StreamEnded):\n"
                "            result = event.result  # the finished Generation"
            ),
            demo_source="src/demo_app/engine.py",
        ),
        HelpTopic(
            key="routing",
            title="Routing, retries, and fallback",
            summary=(
                "The engine/model picker and the Fallback dropdown build a Route: an "
                "ordered chain of provider:model targets with a per-target retry "
                "budget. Retries, backoff, and the switch to the next target all happen "
                "inside the library — the demo shows the attempt trail it is given and "
                "adds no retry loop of its own. Try the flaky demo model with one "
                "attempt to watch a fallback happen."
            ),
            api=("Route", "Retry", "AttemptRecord", "AllTargetsFailedError"),
            snippet=(
                "import anyinfer as ai\n"
                "\n"
                "route = ai.Route(\n"
                '    targets=("demo-fake:flaky", "demo-fake:reliable"),\n'
                "    retry=ai.Retry(max_attempts=1),\n"
                ")\n"
                'result = client.generate("hello", route=route)\n'
                "for attempt in result.attempts:\n"
                "    print(attempt.target, attempt.outcome)"
            ),
            demo_source="src/demo_app/main_window.py",
        ),
        HelpTopic(
            key="sampling",
            title="Sampling controls",
            summary=(
                "Temperature, top-p, and max tokens map onto one normalized Sampling "
                "value. A control left at 'provider default' is genuinely omitted from "
                "the wire request — AnyInfer never invents a number the user did not "
                "set, so each provider applies its own default."
            ),
            api=("Sampling",),
            snippet=(
                "import anyinfer as ai\n"
                "\n"
                "sampling = ai.Sampling(temperature=0.7, max_output_tokens=256)\n"
                "# top_p stays None -> the field never appears on the wire\n"
                'result = client.generate("hello", target=target, sampling=sampling)'
            ),
            demo_source="src/demo_app/main_window.py",
        ),
        HelpTopic(
            key="reasoning",
            title="Reasoning effort",
            summary=(
                "The Reasoning dropdown sends one of four normalized effort levels. "
                "Each provider's descriptor translates the level into that provider's "
                "own spelling; a provider without the control drops the parameter and "
                "reports a ParameterDropped telemetry event instead of failing. "
                "Reasoning text streams separately from the answer as ReasoningDelta, "
                "which is why the transcript keeps it in a fold."
            ),
            api=("ReasoningEffort", "ReasoningDelta", "ParameterDropped"),
            snippet=(
                "result = client.generate(\n"
                '    "Prove there are infinitely many primes.",\n'
                "    target=target,\n"
                '    reasoning="high",  # a ReasoningEffort: minimal | low | medium | high\n'
                ")\n"
                "# while streaming, thoughts arrive as ReasoningDelta events, apart\n"
                "# from the answer text"
            ),
            demo_source="src/demo_app/main_window.py",
        ),
        HelpTopic(
            key="structured",
            title="Structured output",
            summary=(
                "When the schema panel is enabled, the JSON Schema travels with the "
                "request and the library picks the strongest mechanism the target "
                "supports — grammar, native json_schema, JSON mode, or a prompt "
                "instruction — then validates the answer against the canonical schema "
                "regardless of mechanism. A violation is repaired within the bounded "
                "budget you set, and the result reports which mechanism ran and how "
                "many repairs it took."
            ),
            api=(
                "Generation",
                "Repair",
                "SchemaViolationError",
                "Mechanism",
                "SchemaSpec",
            ),
            snippet=(
                'schema = {"type": "object", "properties": {"sentiment": '
                '{"enum": ["pos", "neg"]}},\n'
                '          "required": ["sentiment"]}\n'
                "result = client.generate(\n"
                '    "Review: great value!", target=target,\n'
                "    schema=schema, repair=ai.Repair(max_attempts=1),\n"
                ")\n"
                "print(result.structured, result.structured_mechanism, result.repair_attempts)"
            ),
            demo_source="src/demo_app/widgets/schema_panel.py",
        ),
        HelpTopic(
            key="telemetry",
            title="Telemetry timeline",
            summary=(
                "Every card in the timeline is a typed in-process event delivered to a "
                "plain observer object — no log parsing, no callbacks into provider "
                "code. The demo registers its observer without payloads, so prompt and "
                "response text arrive as None and the inspector shows them as withheld: "
                "telemetry is payload-free unless a caller opts in."
            ),
            api=(
                "Observer",
                "TelemetryEvent",
                "RequestStarted",
                "TargetResolved",
                "AttemptStarted",
                "AttemptCompleted",
                "RetryScheduled",
                "FallbackTriggered",
                "FirstToken",
                "RepairAttempted",
                "RequestCompleted",
                "RequestFailed",
            ),
            snippet=(
                "class PrintObserver:\n"
                "    def on_event(self, event):\n"
                "        print(type(event).__name__, event.request_id)\n"
                "\n"
                "client = ai.Client(settings, observers=[PrintObserver()])\n"
                "# opt in to text payloads only if you really want them:\n"
                "# client.subscribe(observer, payloads=True)"
            ),
            demo_source="src/demo_app/widgets/telemetry_view.py",
        ),
        HelpTopic(
            key="providers",
            title="Provider discovery and health",
            summary=(
                "The providers table is two adapter-contract calls, the same for every "
                "engine: models() lists what a provider serves and health() probes its "
                "readiness. Provider instances are addressed by alias, so two "
                "configurations of one engine are two distinct rows and two distinct "
                "targets."
            ),
            api=(
                "Client.models",
                "Client.health",
                "DiscoveredModel",
                "Health",
                "ProviderSettings",
                "ModelCapabilities",
                "LocalModelInfo",
                "Feature",
            ),
            snippet=(
                'for model in client.models("ollama"):\n'
                "    print(model.id, model.capabilities)\n"
                'health = client.health("ollama")\n'
                "print(health.ok, health.detail)"
            ),
            demo_source="src/demo_app/main_window.py",
        ),
        HelpTopic(
            key="setup-spec",
            title="Generic provider settings",
            summary=(
                "The settings dialog contains no per-provider code. Every engine "
                "declares its own setup fields — endpoints, keys, project ids — as a "
                "ProviderSetupSpec on its registry descriptor, and the dialog renders "
                "whatever it finds: a new provider (even a third-party one installed "
                "via entry point) gets a working settings page with no demo change. "
                "Credential-shaped values become env:// references, never key material "
                "on disk."
            ),
            api=(
                "ProviderRegistry",
                "ProviderDescriptor",
                "ProviderSetupSpec",
                "SetupField",
                "CredentialResolver",
                "default_resolver",
                "default_registry",
            ),
            snippet=(
                "registry = ai.default_registry  # a ProviderRegistry\n"
                "for descriptor in registry:  # each one a ProviderDescriptor\n"
                "    print(descriptor.id, [f.key for f in descriptor.setup.fields])\n"
                "# the demo renders exactly these SetupField declarations, kind by kind"
            ),
            demo_source="src/demo_app/widgets/settings_dialog.py",
        ),
        HelpTopic(
            key="budget",
            title="Token estimate and cost preflight",
            summary=(
                "The estimate under the composer is Client.budget(): a pure in-process "
                "calculation holding the drafted request against the model's known "
                "context window. The verdict is honestly tri-state — fits, does not "
                "fit, or unknown when no trustworthy window is on file, and the cost "
                "is a range from the pricing table, shown only when pricing actually "
                "exists for the target."
            ),
            api=(
                "Client.budget",
                "ContextBudget",
                "CostEstimate",
                "TokenEstimate",
                "PricingTable",
                "load_default_pricing",
            ),
            snippet=(
                'budget = client.budget(messages, target="openai:gpt-4.1-mini")\n'
                'print(budget.estimate.tokens, "of", budget.context_window)\n'
                'print("fits:", budget.fits)  # True / False / None; never a guess\n'
                'print("cost:", budget.estimated_cost)  # None without pricing on file'
            ),
            demo_source="src/demo_app/widgets/composer.py",
        ),
        HelpTopic(
            key="sessions",
            title="Session reuse",
            summary=(
                "With 'Reuse session' checked, turns thread through one Session handle "
                "per target. A provider that keeps conversations can resume instead of "
                "re-reading the transcript; one that cannot simply gets the messages "
                "again. The handle's reuse property reports what actually happened — "
                "resumed, fresh, or unsupported, and the status line repeats it "
                "verbatim, because the three cost very different amounts."
            ),
            api=("Client.session", "Session", "SessionReuse"),
            snippet=(
                'session = client.session("copilot:gpt-4.1")\n'
                'client.generate("hi", target=session.target, session=session)\n'
                'client.generate("and again", target=session.target, session=session)\n'
                "print(session.reuse)  # 'resumed' | 'fresh' | 'unsupported'"
            ),
            demo_source="src/demo_app/engine.py",
        ),
        HelpTopic(
            key="local-system",
            title="Local system profile and benchmark",
            summary=(
                "The System tab renders the HardwareProfile returned with "
                "Client.local_catalog(), so its CPU, RAM, accelerator, VRAM, runtime, "
                "storage, and model-fit facts stay honest about their source. The separate "
                "Benchmark tab runs Client.benchmark() twice against an installed local "
                "target and consumes BenchmarkSample progress for its live charts. The "
                "second run is warm by construction; its latency and throughput "
                "validate one real model/runtime pairing without pretending to predict "
                "the speed of every model that fits in memory."
            ),
            api=(
                "Client.local_catalog",
                "CatalogView",
                "local.hardware.HardwareProfile",
                "Client.benchmark",
                "BenchmarkSample",
                "Measurement",
            ),
            snippet=(
                'view = client.local_catalog(posture="balanced")\n'
                "print(view.hardware, len(view.runnable))\n"
                'first = client.benchmark("ollama:qwen3:8b")\n'
                'warm = client.benchmark("ollama:qwen3:8b")\n'
                "print(first.ttft_ms, warm.ttft_ms, warm.decode_tokens_per_s)"
            ),
            demo_source="src/demo_app/widgets/models_dialog/benchmark_panel.py",
        ),
        HelpTopic(
            key="catalog",
            title="Local model catalog",
            summary=(
                "The catalog tab is one call: Client.local_catalog() returns the "
                "bundled, pinned catalog annotated with how each entry fits this "
                "machine's detected RAM, VRAM, and accelerators at the posture you "
                "pick. The fit verdict carries the library's own reasons — the numbers "
                "that make 'will not fit' checkable, and the demo only filters rows, "
                "never re-derives a verdict."
            ),
            api=(
                "Client.local_catalog",
                "CatalogView",
                "CatalogEntryFit",
                "ModelEntry",
                "load_default_catalog",
            ),
            snippet=(
                'view = client.local_catalog(posture="balanced")\n'
                "for entry in view.runnable:\n"
                "    print(entry.name, entry.fit.level, entry.fit.reasons)"
            ),
            demo_source="src/demo_app/widgets/models_dialog/catalog_panel.py",
        ),
        HelpTopic(
            key="acquisition",
            title="Model acquisition and the store",
            summary=(
                "Download is one call too: acquire_model() plans, fetches, verifies "
                "hashes, and indexes into AnyInfer's own store, streaming progress "
                "snapshots to the callback you pass. dry_run=True returns the plan — "
                "files, bytes, what is already on disk — without fetching, which is "
                "what the 'What would this download?' button shows. installed_models() "
                "lists the store; remove_model() frees it. Engine-owned stores stay "
                "distinct: pull_model() asks the engine to fetch an exact model id, and "
                "the Catalog table merges its discovered inventory without claiming to "
                "own those files."
            ),
            api=(
                "Client.acquire_model",
                "Client.installed_models",
                "Client.remove_model",
                "Client.pull_model",
                "local.acquire.AcquisitionReport",
                "local.acquire.AcquisitionProgress",
                "local.store.StoreEntry",
            ),
            snippet=(
                'plan = client.acquire_model("qwen3-8b", dry_run=True)\n'
                'print(plan.plan.total_bytes, "bytes to fetch")\n'
                'report = client.acquire_model("qwen3-8b", progress=print)\n'
                'client.pull_model("ollama", "qwen3:8b")\n'
                "for entry in client.installed_models():\n"
                "    print(entry.model_id, entry.directory)"
            ),
            demo_source="src/demo_app/widgets/models_dialog/catalog_panel.py",
        ),
        HelpTopic(
            key="runtimes",
            title="llama.cpp runtimes",
            summary=(
                "Nothing executable is bundled in the wheel. The Runtimes tab lists the "
                "llama.cpp builds already installed and asks the library which "
                "accelerator backends this machine can drive; Install fetches the "
                "pinned build for the chosen backend into the per-user runtime "
                "directory. The supervised llama-server the library runs later uses "
                "the selected backend. The table checkmark shows which installed build "
                "is currently selected."
            ),
            api=(
                "local.runtimes.installed_runtimes",
                "local.runtimes.install_runtime",
                "local.backends.available_backends",
            ),
            snippet=(
                "from anyinfer.local.runtimes import install_runtime, installed_runtimes\n"
                "from anyinfer.local.backends import available_backends\n"
                "\n"
                "print([b.kind for b in available_backends()])\n"
                "report = install_runtime(None)  # None -> best for this machine\n"
                "print(report.backend, report.executable)"
            ),
            demo_source="src/demo_app/widgets/models_dialog/runtime_panel.py",
        ),
        HelpTopic(
            key="target-inspection",
            title="Target inspector",
            summary=(
                "Four separate library calls, with four different price tags, and the "
                "buttons say so. Capabilities is resolve(): a free lookup of what is "
                "already known, every value tagged with its provenance (catalog, "
                "discovered, probed, or default — a measured number and a guess must "
                "never read the same). Verify spends one request to prove the target "
                "answers; Probe spends one per feature to measure what it really "
                "supports; Benchmark times two identical deterministic requests back to "
                "back — the second is warm by construction, so a local engine's "
                "cold-start cost shows up as the gap between them instead of hiding "
                "inside a single number."
            ),
            api=(
                "Client.resolve",
                "Client.verify",
                "Client.probe",
                "Client.benchmark",
                "Client.diagnostics",
                "ResolvedTarget",
                "Verification",
                "ProbeReport",
                "ProbeOutcome",
                "Measurement",
                "Sourced",
                "Provenance",
                "Diagnostic",
                "DiagnosticSeverity",
            ),
            snippet=(
                'resolved = client.resolve("ollama:qwen3:8b")  # no request issued\n'
                'verification = client.verify(resolved.provider_id + ":" + resolved.model)\n'
                "report = client.probe(target)      # one request per probed feature\n"
                "timing = client.benchmark(target)  # one deterministic request, timed\n"
                "print(timing.ttft_ms, timing.decode_tokens_per_s)"
            ),
            demo_source="src/demo_app/widgets/target_inspector.py",
        ),
        HelpTopic(
            key="tools",
            title="Tool loop",
            summary=(
                "The tool loop panel supplies two ordinary Python functions; their JSON "
                "schemas are derived from the signatures by @tool. run_tools() owns the "
                "loop — it issues the request, matches each returned call to a declared "
                "tool, runs it, feeds the result back, and repeats until the model "
                "answers or the round budget is spent. The panel's transcript lists the "
                "functions that actually executed, because a model claiming it called "
                "something is not evidence that it did."
            ),
            api=(
                "tool",
                "Tool",
                "Client.run_tools",
                "ToolCall",
                "ToolResult",
                "ToolLoopError",
                "FinishReason",
            ),
            snippet=(
                "@ai.tool\n"
                "def word_count(text: str) -> int:\n"
                '    """Count the words in a piece of text."""\n'
                "    return len(text.split())\n"
                "\n"
                "result = client.run_tools(\n"
                "    \"How many words is 'the quick brown fox'?\",\n"
                "    tools=[word_count], target=target, max_rounds=4,\n"
                ")"
            ),
            demo_source="src/demo_app/widgets/tools_panel.py",
        ),
        HelpTopic(
            key="embeddings",
            title="Embeddings and rerank",
            summary=(
                "Client.embed() and Client.rerank() are typed, routed operations distinct "
                "from generation — neither is folded into GenerationRequest. Embed turns "
                "text into vectors and returns the EmbeddingSpace that identifies which "
                "model produced them, so a caller can tell whether two results are safely "
                "comparable. Rerank scores a caller-owned document set against a query and "
                "preserves each document's original index and id, so a malformed provider "
                "response can never be silently attributed to the wrong document."
            ),
            api=(
                "Client.embed",
                "Client.rerank",
                "EmbeddingRequest",
                "EmbeddingResult",
                "EmbeddingSpace",
                "EmbeddingVector",
                "RerankRequest",
                "RerankResult",
                "RerankDocument",
                "RankedItem",
            ),
            snippet=(
                "result = client.embed([\"hello\", \"world\"], target=target)\n"
                "print(result.space.dimensions, len(result.vectors))\n"
                "\n"
                "ranked = client.rerank(\n"
                '    "capital of France",\n'
                '    ["Paris is the capital of France.", "Berlin is in Germany."],\n'
                "    target=target,\n"
                ")"
            ),
            demo_source="src/demo_app/widgets/embeddings_panel.py",
        ),
        HelpTopic(
            key="errors",
            title="Errors with hints",
            summary=(
                "Every failure notice in the transcript ends with a hint because every "
                "AnyInfer error carries one: a shallow typed hierarchy with structured "
                "fields — provider, phase, retryable, HTTP status, where detail says "
                "what happened and hint says what to do next. Anything "
                "credential-shaped is registered for redaction before it can appear in "
                "an error, an event, or a log."
            ),
            api=(
                "AnyInferError",
                "AuthError",
                "RateLimitError",
                "ContextLengthError",
                "ProviderUnavailableError",
                "ErrorInfo",
                "register_secret",
                "redact",
            ),
            snippet=(
                "try:\n"
                '    client.generate("hi", target="openai:gpt-4.1-mini")\n'
                "except ai.AnyInferError as error:\n"
                "    print(error.detail)  # bounded, redacted\n"
                "    print(error.hint)    # the actionable next step"
            ),
            demo_source="src/demo_app/main_window.py",
        ),
        HelpTopic(
            key="offline-fake",
            title="The offline demo provider",
            summary=(
                "The demo-fake engine is not a UI mock: it is the library's own "
                "scripted-provider kit registered like any real engine, served through "
                "an in-process transport by the stock OpenAI-compatible adapter. The "
                "router resolves it, telemetry observes it, and the settings dialog "
                "renders it from its setup spec, which is why everything you watch "
                "offline is the real code path, minus the network."
            ),
            api=(
                "testing.ScriptedProvider",
                "testing.ScriptedModel",
                "testing.ScriptedFailure",
                "ProviderRegistry.register",
            ),
            snippet=(
                "from anyinfer.testing import ScriptedModel, ScriptedProvider\n"
                "\n"
                'provider = ScriptedProvider("demo-fake", [\n'
                '    ScriptedModel("reliable"),\n'
                '    ScriptedModel("flaky", failures=(ScriptedFailure(status=503),)),\n'
                "])\n"
                "provider.register(registry)\n"
                "client = ai.Client([provider.settings()], registry=registry)"
            ),
            demo_source="src/demo_app/fake_provider.py",
        ),
        HelpTopic(
            key="history",
            title="History trimming",
            summary=(
                "By default the demo re-sends the whole transcript every turn. The "
                "History dropdown opts into HistoryPolicy — client-side compaction that "
                "keeps the system prompt and the most recent turns, trimming the middle "
                "either only when the request would not fit (last resort) or on every "
                "request (proactive). Trimming is never silent: each reduction emits a "
                "ContextReduced telemetry event saying exactly what was kept, what was "
                "omitted, and the token arithmetic behind it."
            ),
            api=("HistoryPolicy", "ContextReduced"),
            snippet=(
                "result = client.generate(\n"
                "    messages,\n"
                "    target=target,\n"
                '    history=ai.HistoryPolicy(mode="last_resort", keep_recent=6),\n'
                ")\n"
                "# watch for ContextReduced in telemetry — compaction is never silent"
            ),
            demo_source="src/demo_app/main_window.py",
        ),
        HelpTopic(
            key="prompt-cache",
            title="Prompt caching",
            summary=(
                "The Prompt cache dropdown opts into CachePolicy. Caching changes what "
                "a provider bills and how long it retains a copy of the prompt, so no "
                "policy means cached exactly as before: not at all. With one, the "
                "client plans placement — explicit marks where the provider has them, "
                "implicit prefix caching where it does not, and reports the plan as a "
                "CachePlanned telemetry event: mechanism, mark count, and the tokens it "
                "expects to be cacheable. It caches the prefix you send; it never skips "
                "a call or reuses an answer."
            ),
            api=("CachePolicy", "CacheMode", "CacheMechanism", "CachePlanned"),
            snippet=(
                "result = client.generate(\n"
                "    messages,\n"
                "    target=target,\n"
                '    cache=ai.CachePolicy(mode="auto"),  # a CacheMode\n'
                ")\n"
                "# the CachePlanned event reports the mechanism and mark placement"
            ),
            demo_source="src/demo_app/main_window.py",
        ),
        HelpTopic(
            key="messages",
            title="Messages and conversation history",
            summary=(
                "Each transcript turn is a normalized Message — role plus typed content "
                "parts — built with the system()/user()/assistant() helpers and re-sent "
                "as history on the next turn. The saved conversations in the sidebar "
                "are these same values serialized, which is why an exported chat "
                "replays cleanly."
            ),
            api=("Message", "Role", "Text", "ContentPart", "system", "user", "assistant"),
            snippet=(
                "messages = [\n"
                '    ai.system("You are concise."),\n'
                '    ai.user("Why is the sky blue?"),\n'
                "]\n"
                "result = client.generate(messages, target=target)\n"
                "messages.append(ai.assistant(result.text))  # carry history forward"
            ),
            demo_source="src/demo_app/conversation.py",
        ),
        HelpTopic(
            key="metrics",
            title="Timing and usage metrics",
            summary=(
                "The status-bar readout shows only what was measured or reported: TTFT "
                "and total time measured centrally by the core (never by the provider's "
                "own clock), token counts and cost from the provider's usage block. A "
                "number AnyInfer was not given renders as an em dash; never as zero, "
                "and never as an estimate dressed up as a measurement."
            ),
            api=("Timing", "Usage", "Generation", "UsageUpdate", "FirstToken"),
            snippet=(
                'result = client.generate("hello", target=target)\n'
                "print(result.timing.first_token_ms)   # Timing — measured by the core\n"
                "print(result.usage.output_tokens)     # Usage — reported by the provider\n"
                "print(result.usage.cost_usd)          # None without pricing; not 0.0"
            ),
            demo_source="src/demo_app/widgets/metrics.py",
        ),
        HelpTopic(
            key="config",
            title="One shared configuration format",
            summary=(
                "The demo saves its settings in the shared, versioned AnyInfer config "
                "format — the same file the SDK's load_config(), the CLI, and the "
                "sidecar read. A file saved here starts `anyinfer serve --config` on "
                "the same providers and route; credentials are stored as env:// "
                "references, so the file holds no key material."
            ),
            api=("AnyInferConfig", "load_config", "loads_config", "CONFIG_FORMAT_VERSION"),
            snippet=(
                "config = ai.load_config(path)  # the demo's saved file works here\n"
                "print(config.default_route)\n"
                "# anyinfer serve --config <the same file>"
            ),
            demo_source="src/demo_app/config.py",
        ),
    )
}
"""Every help topic, keyed by `HelpTopic.key`. Iteration order is the authoring order."""


def covered_symbols() -> set[str]:
    """Top-level public names the demo's topics reference.

    ``"Client.stream"`` covers ``Client``; ``"local.acquire.AcquisitionReport"`` names a
    submodule surface, which has no top-level entry to cover.
    """
    import anyinfer

    public = set(anyinfer.__all__)
    return {
        entry.split(".", 1)[0]
        for topic in TOPICS.values()
        for entry in topic.api
        if entry.split(".", 1)[0] in public
    }


def uncovered_symbols() -> tuple[str, ...]:
    """Top-level public names no topic references, sorted, dunders excluded."""
    import anyinfer

    covered = covered_symbols()
    return tuple(
        sorted(
            name for name in anyinfer.__all__ if name not in covered and not name.startswith("__")
        )
    )
