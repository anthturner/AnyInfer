"""Tests for the pack-in demo application.

These run headless (``QT_QPA_PLATFORM=offscreen``) and drive real generations through the
offline fake provider, so the demo is verified end to end without credentials or network.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

import anyinfer as ai

pytest.importorskip("PySide6", reason="the demo app requires the 'demo' extra")

from datetime import UTC

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QDialog

from anyinfer import Retry, Route
from anyinfer.registry import ProviderRegistry
from anyinfer.types.messages import Message, Text, user
from anyinfer.types.requests import Repair, Sampling
from demo_app.config import DemoConfig, ProviderConfig, default_config
from demo_app.engine import Engine, GenerationSpec
from demo_app.fake_provider import DEMO_MODELS, DEMO_PROVIDER_ID, DemoFakeBackend
from demo_app.widgets.schema_panel import EXAMPLE_SCHEMA


def _drain(engine: Engine, timeout_ms: int = 15_000) -> object:
    """Run the Qt event loop until the engine reports a result or a failure."""
    loop = QEventLoop()
    outcome: dict[str, object] = {}

    def on_finished(result: object) -> None:
        outcome["result"] = result
        loop.quit()

    def on_failed(message: str, error: object) -> None:
        outcome["error"] = message
        loop.quit()

    engine.finished.connect(on_finished)
    engine.failed.connect(on_failed)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()

    if "error" in outcome:
        raise AssertionError(f"generation failed: {outcome['error']}")
    if "result" not in outcome:
        raise AssertionError("generation timed out")
    return outcome["result"]


@pytest.fixture
def engine(qapp: object) -> Engine:
    """An engine wired to the offline fake provider."""
    instance = Engine(default_config())
    yield instance
    instance.close()


class TestConfig:
    def test_default_config_enables_only_the_offline_provider(self):
        config = default_config()
        enabled = [p.provider_id for p in config.enabled_providers()]
        assert enabled == [DEMO_PROVIDER_ID]

    def test_round_trips_through_json(self):
        config = default_config().with_provider(
            ProviderConfig("openai", enabled=True, values={"api_key": "env://KEY"})
        )
        restored = DemoConfig.from_json(config.to_json())
        assert restored.for_provider("openai").api_key == "env://KEY"
        assert restored.targets == config.targets

    def test_corrupt_config_falls_back_to_defaults(self, tmp_path):
        path = tmp_path / "demo.json"
        path.write_text("{not json", encoding="utf-8")
        assert DemoConfig.load(path).targets == default_config().targets

    def test_saves_and_loads(self, tmp_path):
        path = tmp_path / "nested" / "demo.json"
        config = default_config().with_targets(["demo-fake:flaky", "demo-fake:reliable"])
        config.save(path)
        assert DemoConfig.load(path).targets == ("demo-fake:flaky", "demo-fake:reliable")

    def test_round_trips_theme_and_context_window(self):
        config = replace(default_config(), theme="dark", context_window_tokens=8192)
        restored = DemoConfig.from_json(config.to_json())
        assert restored.theme == "dark"
        assert restored.context_window_tokens == 8192

    def test_malformed_preferences_fall_back_to_defaults(self):
        restored = DemoConfig.from_json({"theme": "neon", "context_window_tokens": "lots"})
        assert restored.theme == "system"
        assert restored.context_window_tokens is None

    def test_shared_identity_spelling_round_trips_without_redundancy(self):
        config = DemoConfig(
            providers=(
                ProviderConfig("openai", enabled=True),
                ProviderConfig("azure-foundry", alias="work-azure", enabled=True),
            )
        )
        entries = config.to_json()["providers"]
        assert entries[0] == {
            "id": "openai",
            "enabled": True,
            "values": {},
            "options": {},
        }
        assert entries[1]["id"] == "work-azure"
        assert entries[1]["adapter"] == "azure-foundry"
        assert "provider_id" not in entries[1]
        assert "alias" not in entries[1]

        restored = DemoConfig.from_json(config.to_json())
        assert [p.instance_id for p in restored.providers] == ["openai", "work-azure"]
        assert [p.provider_id for p in restored.providers] == ["openai", "azure-foundry"]

    def test_two_instances_of_one_engine_keep_separate_values(self):
        config = DemoConfig(
            providers=(
                ProviderConfig("openai", enabled=True, values={"api_key": "env://FIRST"}),
                ProviderConfig(
                    "openai", alias="openai-2", enabled=True, values={"api_key": "env://SECOND"}
                ),
            )
        )
        restored = DemoConfig.from_json(config.to_json())

        assert restored.for_provider("openai").api_key == "env://FIRST"
        assert restored.for_provider("openai-2").api_key == "env://SECOND"
        assert [p.instance_id for p in restored.instances_of("openai")] == [
            "openai",
            "openai-2",
        ]

    def test_instance_ids_lists_every_configured_instance(self):
        config = DemoConfig(
            providers=(
                ProviderConfig("openai"),
                ProviderConfig("openai", alias="openai-2"),
            )
        )
        assert config.instance_ids() == ("openai", "openai-2")

    def test_with_providers_can_express_a_deletion(self):
        """A merge-only update could never remove an instance the user deleted."""
        config = DemoConfig(providers=(ProviderConfig("openai"), ProviderConfig("ollama")))
        assert config.with_providers([config.providers[0]]).instance_ids() == ("openai",)

    def test_extra_values_carry_fields_provider_settings_has_no_slot_for(self):
        """A provider's non-standard fields must reach the adapter, not be dropped.

        `ProviderSettings` spells three settings at the top level; anything else a
        provider declares — Anthropic's OAuth token here — has to travel in ``options``.
        """
        provider = ProviderConfig(
            "anthropic",
            values={
                "api_key": "sk-ant-key",
                "api_version": "2023-06-01",
                "base_url": "https://api.anthropic.com",
                "oauth_token": "sk-ant-oat01-abc",
            },
        )

        assert provider.extra_values() == {"oauth_token": "sk-ant-oat01-abc"}

    def test_extra_values_omits_blanks(self):
        """An empty editor must not send an empty option that shadows a real credential."""
        provider = ProviderConfig("anthropic", values={"api_key": "k", "oauth_token": ""})
        assert provider.extra_values() == {}

    def test_reads_a_hand_written_serve_config(self):
        """Acceptance: a file written for `anyinfer serve` renders in the demo."""
        restored = DemoConfig.from_json(
            {
                "providers": [
                    {"id": "openai", "api_key": "env://OPENAI_API_KEY"},
                    {
                        "id": "work-azure",
                        "adapter": "azure-foundry",
                        "base_url": "https://wumbo.openai.azure.com",
                    },
                ],
                "default_route": ["openai:gpt-5", "work-azure:gpt-4o"],
            }
        )

        assert restored.instance_ids() == ("openai", "work-azure")
        assert restored.for_provider("work-azure").provider_id == "azure-foundry"
        assert restored.for_provider("work-azure").base_url == "https://wumbo.openai.azure.com"
        assert restored.for_provider("openai").api_key == "env://OPENAI_API_KEY"
        # Listing a provider in a serve file is enabling it.
        assert all(p.enabled for p in restored.providers)
        assert restored.targets == ("openai:gpt-5", "work-azure:gpt-4o")

    def test_a_saved_config_is_readable_by_the_serve_loader(self, tmp_path):
        """Acceptance: the file the demo writes starts `anyinfer serve --config`."""
        path = tmp_path / "demo.json"
        DemoConfig(
            providers=(
                ProviderConfig("openai", enabled=True, values={"api_key": "env://KEY"}),
                ProviderConfig(
                    "azure-foundry",
                    alias="work-azure",
                    enabled=True,
                    values={"base_url": "https://wumbo.openai.azure.com"},
                ),
                ProviderConfig("ollama", enabled=False),
            ),
            targets=("work-azure:gpt-4o",),
        ).save(path)

        parsed = ai.load_config(path)
        settings, route = parsed.providers, parsed.route

        assert [s.instance_id for s in settings] == ["openai", "work-azure"]
        assert [s.provider_id for s in settings] == ["openai", "azure-foundry"]
        assert settings[0].api_key == "env://KEY"
        assert settings[1].base_url == "https://wumbo.openai.azure.com"
        assert route.targets == ("work-azure:gpt-4o",)

    def test_future_shared_config_versions_fall_back_safely(self):
        restored = DemoConfig.from_json({"format_version": 999, "providers": []})

        assert restored == default_config()


class TestFakeProvider:
    def test_registers_and_resolves(self):
        registry = ProviderRegistry()
        from demo_app.fake_provider import register_demo_provider

        register_demo_provider(registry)
        assert registry.resolve_alias("demo") == DEMO_PROVIDER_ID
        assert registry.get(DEMO_PROVIDER_ID).display_name == "Demo (offline fake)"

    def test_serves_every_advertised_model(self):
        backend = DemoFakeBackend()
        transport = backend.transport()
        import httpx2

        for model in DEMO_MODELS:
            request = httpx2.Request(
                "POST",
                "http://demo.invalid/v1/chat/completions",
                json={"model": model, "messages": [{"role": "user", "content": "hi"}]},
            )
            response = transport.handler(request)
            assert response.status_code in (200, 503)


class TestGeneration:
    def test_streams_text_and_reports_timing(self, engine: Engine):
        deltas: list[str] = []
        engine.text_delta.connect(deltas.append)

        engine.generate(
            GenerationSpec(
                messages=(user("Explain AnyInfer."),),
                route=Route.of("demo-fake:reliable"),
                sampling=Sampling(),
            )
        )
        result = _drain(engine)

        assert deltas, "no streamed deltas were emitted"
        # ADR-001 invariant 4: concatenated deltas equal the final text.
        assert "".join(deltas) == result.text
        assert result.finish_reason == "stop"
        assert result.timing.first_token_ms is not None
        assert result.usage.total_tokens is not None

    def test_retries_the_flaky_model_and_still_succeeds(self, engine: Engine):
        failures: list[object] = []
        engine.attempt_failed.connect(failures.append)

        engine.generate(
            GenerationSpec(
                messages=(user("Try the flaky target."),),
                route=Route(
                    targets=("demo-fake:flaky",),
                    retry=Retry(max_attempts=2, backoff_base_s=0.0),
                    health_gate=False,
                ),
                sampling=Sampling(),
            )
        )
        result = _drain(engine)

        assert failures, "the scripted 503 did not surface as a failed attempt"
        assert result.text
        assert any(a.outcome == "ok" for a in result.attempts)

    def test_falls_back_to_the_next_target(self, engine: Engine):
        engine.generate(
            GenerationSpec(
                messages=(user("Exercise the fallback chain."),),
                route=Route(
                    targets=("demo-fake:flaky", "demo-fake:reliable"),
                    retry=Retry(max_attempts=1, backoff_base_s=0.0),
                    health_gate=False,
                ),
                sampling=Sampling(),
            )
        )
        result = _drain(engine)
        assert str(result.target) == "demo-fake:reliable"

    def test_emits_telemetry_events(self, engine: Engine):
        events: list[object] = []
        engine.telemetry.connect(events.append)

        engine.generate(
            GenerationSpec(
                messages=(user("Watch the telemetry."),),
                route=Route.of("demo-fake:reliable"),
                sampling=Sampling(),
            )
        )
        _drain(engine)

        names = {type(e).__name__ for e in events}
        assert {"RequestStarted", "TargetResolved", "RequestCompleted"} <= names

    def test_telemetry_withholds_payloads_by_default(self, engine: Engine):
        events: list[object] = []
        engine.telemetry.connect(events.append)

        engine.generate(
            GenerationSpec(
                messages=(user("Secret prompt text."),),
                route=Route.of("demo-fake:reliable"),
                sampling=Sampling(),
            )
        )
        _drain(engine)

        started = [e for e in events if type(e).__name__ == "RequestStarted"]
        completed = [e for e in events if type(e).__name__ == "RequestCompleted"]
        assert started and started[0].prompt_text is None
        assert completed and completed[0].response_text is None

    def test_structured_output_validates_against_the_schema(self, engine: Engine):
        engine.generate(
            GenerationSpec(
                messages=(user("Analyze this."),),
                route=Route.of("demo-fake:reliable"),
                sampling=Sampling(),
                schema=EXAMPLE_SCHEMA,
                repair=Repair(max_attempts=1),
            )
        )
        result = _drain(engine)

        assert result.structured is not None
        assert result.structured_mechanism is not None
        assert set(EXAMPLE_SCHEMA["required"]) <= set(result.structured)


class TestCancellation:
    def test_cancel_resets_busy_and_allows_a_subsequent_send(self, engine: Engine):
        """A cancelled generation must emit a terminal signal and free the engine."""
        outcomes: list[str] = []
        loop = QEventLoop()
        engine.cancelled.connect(lambda: (outcomes.append("cancelled"), loop.quit()))
        # The worker races the cancel flag; if it wins, `finished` is the terminal
        # signal instead — either way the engine must settle, never wedge.
        engine.finished.connect(lambda _r: (outcomes.append("finished"), loop.quit()))

        engine.generate(
            GenerationSpec(
                messages=(user("Cancel me."),),
                route=Route.of("demo-fake:slow"),
                sampling=Sampling(),
            )
        )
        assert engine.busy
        engine.cancel()
        QTimer.singleShot(15_000, loop.quit)
        loop.exec()

        assert outcomes, "cancel left the engine with no terminal signal at all"
        assert engine.busy is False

        # The engine must accept a new request — a wedged busy flag would ignore it.
        engine.generate(
            GenerationSpec(
                messages=(user("And now answer this."),),
                route=Route.of("demo-fake:reliable"),
                sampling=Sampling(),
            )
        )
        result = _drain(engine)
        assert result.text


class TestDiscoveryFailureIsolation:
    def test_discovery_failure_uses_its_own_signal_path(self, engine: Engine):
        failed: list[str] = []
        discovery: list[str] = []
        loop = QEventLoop()
        engine.failed.connect(lambda m, e: failed.append(m))
        engine.discovery_failed.connect(lambda pid, m, e: (discovery.append(pid), loop.quit()))

        engine.list_models("no-such-provider")
        QTimer.singleShot(15_000, loop.quit)
        loop.exec()

        assert discovery == ["no-such-provider"]
        assert not failed, "a discovery failure leaked into the generation failure path"
        assert engine.busy is False

    def test_discovery_failure_does_not_corrupt_an_in_flight_generation(self, engine: Engine):
        failed: list[str] = []
        discovery: list[str] = []
        engine.failed.connect(lambda m, e: failed.append(m))
        engine.discovery_failed.connect(lambda pid, m, e: discovery.append(pid))

        engine.generate(
            GenerationSpec(
                messages=(user("Keep streaming."),),
                route=Route.of("demo-fake:reliable"),
                sampling=Sampling(),
            )
        )
        engine.check_health("no-such-provider")  # queued behind the generation
        result = _drain(engine)

        assert result.text
        assert not failed, "a discovery failure leaked into the generation failure path"

        if not discovery:  # the probe may still be queued; wait for its own signal
            loop = QEventLoop()
            engine.discovery_failed.connect(lambda *_: loop.quit())
            QTimer.singleShot(15_000, loop.quit)
            loop.exec()
        assert discovery == ["no-such-provider"]


class TestConversation:
    def _result(self) -> object:
        from anyinfer.types.requests import ResolvedTarget
        from anyinfer.types.results import Generation, Timing, Usage

        return Generation(
            text="An answer.",
            structured=None,
            tool_calls=(),
            target=ResolvedTarget("demo-fake", "reliable"),
            finish_reason="stop",
            usage=Usage(input_tokens=5, output_tokens=7, total_tokens=12),
            timing=Timing(started_at=0.0, total_ms=42.0),
        )

    def test_new_conversation_has_no_messages(self):
        from demo_app.conversation import Conversation

        conversation = Conversation.new()
        assert conversation.messages == ()
        assert conversation.title == "New chat"

    def test_title_is_derived_from_the_first_user_message(self):
        from demo_app.conversation import Conversation

        conversation = Conversation.new().with_messages([user("Explain retries in AnyInfer.")])
        assert conversation.title == "Explain retries in AnyInfer."

    def test_long_titles_are_truncated(self):
        from demo_app.conversation import Conversation

        long_text = "x" * 100
        conversation = Conversation.new().with_messages([user(long_text)])
        assert len(conversation.title) == 40
        assert conversation.title.endswith("…")

    def test_round_trips_through_json(self):
        from demo_app.conversation import Conversation

        conversation = Conversation.new().with_messages([user("Hi"), user("Follow-up")])
        conversation = conversation.with_result(self._result())
        restored = Conversation.from_json(conversation.to_json())

        assert restored.id == conversation.id
        assert [m.text for m in restored.messages] == ["Hi", "Follow-up"]
        assert restored.results[0].target == "demo-fake:reliable"
        assert restored.results[0].total_ms == 42.0

    def test_save_and_load_round_trips(self, tmp_path):
        from demo_app.conversation import Conversation

        conversation = Conversation.new().with_messages([user("Persisted.")])
        conversation.save(tmp_path)

        loaded = Conversation.load(tmp_path / f"{conversation.id}.json")
        assert loaded is not None
        assert loaded.messages[0].text == "Persisted."

    def test_load_all_sorts_newest_first_and_skips_corrupt_files(self, tmp_path):
        from datetime import datetime, timedelta

        from demo_app.conversation import Conversation

        base = Conversation.new().with_messages([user("older")])
        older = replace(base, id="older-id", updated_at=datetime.now(UTC))
        newer = replace(
            base,
            id="newer-id",
            updated_at=datetime.now(UTC) + timedelta(seconds=5),
        )
        older.save(tmp_path)
        newer.save(tmp_path)
        (tmp_path / "garbage.json").write_text("{not json", encoding="utf-8")

        loaded = Conversation.load_all(tmp_path)
        assert [c.id for c in loaded] == [newer.id, older.id]

    def test_summary_never_carries_the_raw_generation(self):
        from demo_app.conversation import GenerationSummary

        summary = GenerationSummary.from_result(self._result())
        assert not hasattr(summary, "raw")
        assert not hasattr(summary, "text")

    def test_to_markdown_includes_every_message(self):
        from demo_app.conversation import Conversation

        conversation = Conversation.new().with_messages(
            [user("Question?"), Message(role="assistant", content=(Text("Answer."),))]
        )
        markdown = conversation.to_markdown()
        assert "Question?" in markdown
        assert "Answer." in markdown


class TestSchemaPanel:
    def test_example_schema_is_valid_json_schema(self):
        import jsonschema

        jsonschema.Draft202012Validator.check_schema(EXAMPLE_SCHEMA)

    def test_reports_bad_json(self, qapp: object):
        from demo_app.widgets.schema_panel import SchemaPanel

        panel = SchemaPanel()
        assert panel.schema() is None  # disabled by default

        panel.set_enabled(True)
        panel._editor.setPlainText("{not json")
        with pytest.raises(ValueError, match="not valid JSON"):
            panel.schema()

    def test_returns_parsed_schema_when_enabled(self, qapp: object):
        from demo_app.widgets.schema_panel import SchemaPanel

        panel = SchemaPanel()
        panel.set_enabled(True)
        assert panel.schema() == json.loads(json.dumps(EXAMPLE_SCHEMA))


class TestSettingsDialog:
    def _dialog(self, config=None):
        from demo_app.fake_provider import register_demo_provider
        from demo_app.widgets.settings_dialog import ProviderSettingsDialog

        registry = ProviderRegistry()
        register_demo_provider(registry)
        return ProviderSettingsDialog(registry, config or default_config())

    def test_lists_only_configured_engines_not_every_registered_one(self, qapp: object):
        """The dialog shows what the user configured, not a checklist of everything."""
        dialog = self._dialog()

        assert len(dialog._rows) == len(default_config().providers)
        assert [r.alias() for r in dialog._rows] == [DEMO_PROVIDER_ID]
        # The registry is offered through the dropdown instead.
        assert dialog._engines.count() == len(dialog._registry.known_ids())

    def test_a_fresh_config_shows_an_empty_list(self, qapp: object):
        dialog = self._dialog(DemoConfig())
        assert dialog._rows == []
        assert dialog._empty.isVisible() or not dialog._empty.isHidden()

    def test_adding_an_engine_defaults_its_alias_to_the_provider_id(self, qapp: object):
        dialog = self._dialog(DemoConfig())
        dialog._engines.setCurrentText("Demo (offline fake)")
        dialog._on_add_clicked()

        assert [r.alias() for r in dialog._rows] == [DEMO_PROVIDER_ID]
        assert dialog.result_config().providers[0].alias is None

    def test_adding_the_same_engine_twice_auto_suffixes_the_alias(self, qapp: object):
        dialog = self._dialog(DemoConfig())
        dialog._engines.setCurrentText("Demo (offline fake)")
        dialog._on_add_clicked()
        dialog._on_add_clicked()
        dialog._on_add_clicked()

        assert [r.alias() for r in dialog._rows] == [
            DEMO_PROVIDER_ID,
            f"{DEMO_PROVIDER_ID}-2",
            f"{DEMO_PROVIDER_ID}-3",
        ]

    def test_two_instances_of_one_engine_keep_separate_settings(self, qapp: object):
        """The point of aliases: same engine, different endpoints and credentials."""
        dialog = self._dialog(DemoConfig())
        dialog._engines.setCurrentText("Demo (offline fake)")
        dialog._on_add_clicked()
        dialog._on_add_clicked()
        dialog._rows[1]._alias.setText("second")

        config = dialog.result_config()
        assert [p.instance_id for p in config.providers] == [DEMO_PROVIDER_ID, "second"]
        assert [p.provider_id for p in config.providers] == [DEMO_PROVIDER_ID] * 2
        assert config.instance_ids() == (DEMO_PROVIDER_ID, "second")

    def test_deleting_a_row_removes_it_from_the_result(self, qapp: object):
        dialog = self._dialog()
        assert dialog._rows
        dialog._on_delete_row(dialog._rows[0])

        assert dialog._rows == []
        assert dialog.result_config().providers == ()

    def test_duplicate_aliases_refuse_to_save(self, qapp: object):
        dialog = self._dialog(DemoConfig())
        dialog._engines.setCurrentText("Demo (offline fake)")
        dialog._on_add_clicked()
        dialog._on_add_clicked()
        dialog._rows[1]._alias.setText(DEMO_PROVIDER_ID)

        dialog._on_accept()
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert "unique alias" in dialog._error.text()

    def test_an_empty_alias_refuses_to_save(self, qapp: object):
        dialog = self._dialog()
        dialog._rows[0]._alias.setText("   ")

        dialog._on_accept()
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert "alias is empty" in dialog._error.text()

    def test_a_missing_required_field_refuses_to_save(self, qapp: object):
        from anyinfer.registry import (
            ProviderDescriptor,
            ProviderSetupSpec,
            SetupField,
        )

        dialog = self._dialog(DemoConfig())
        dialog._registry.register(
            ProviderDescriptor(
                id="needs-endpoint",
                display_name="Needs Endpoint",
                factory=lambda config: None,
                setup=ProviderSetupSpec(
                    fields=(SetupField("base_url", "Endpoint", "endpoint", required=True),)
                ),
            )
        )
        dialog._add_row(ProviderConfig("needs-endpoint", enabled=True))

        dialog._on_accept()
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert "Endpoint" in dialog._error.text()

    def test_a_disabled_instance_may_leave_required_fields_empty(self, qapp: object):
        """Validation gates on *enabled* instances, as the old per-panel check did."""
        from anyinfer.registry import (
            ProviderDescriptor,
            ProviderSetupSpec,
            SetupField,
        )

        dialog = self._dialog(DemoConfig())
        dialog._registry.register(
            ProviderDescriptor(
                id="needs-endpoint",
                display_name="Needs Endpoint",
                factory=lambda config: None,
                setup=ProviderSetupSpec(
                    fields=(SetupField("base_url", "Endpoint", "endpoint", required=True),)
                ),
            )
        )
        dialog._add_row(ProviderConfig("needs-endpoint", enabled=False))

        assert dialog._validate() == ""

    def test_is_generic_over_setup_specs(self, qapp: object):
        """The dialog must build editors purely from declared field kinds (ADR-008)."""
        from anyinfer.registry import (
            ProviderDescriptor,
            ProviderSetupSpec,
            SetupField,
        )
        from demo_app.widgets.settings_dialog import _ProviderPanel

        descriptor = ProviderDescriptor(
            id="invented-provider",
            display_name="Invented",
            factory=lambda config: None,  # never instantiated in this test
            setup=ProviderSetupSpec(
                fields=(
                    SetupField("base_url", "Endpoint", "endpoint", required=True),
                    SetupField("api_key", "Key", "secret"),
                    SetupField("api_version", "Version", "api-version"),
                )
            ),
        )
        panel = _ProviderPanel(descriptor, ProviderConfig("invented-provider"))

        assert set(panel.values()) == {"base_url", "api_key", "api_version"}
        assert panel.missing_required() == ["Endpoint"]

    def test_secret_fields_are_masked(self, qapp: object):
        from PySide6.QtWidgets import QLineEdit

        from anyinfer.registry import (
            ProviderDescriptor,
            ProviderSetupSpec,
            SetupField,
        )
        from demo_app.widgets.settings_dialog import _ProviderPanel

        descriptor = ProviderDescriptor(
            id="masked",
            display_name="Masked",
            factory=lambda config: None,
            setup=ProviderSetupSpec(fields=(SetupField("api_key", "Key", "secret"),)),
        )
        panel = _ProviderPanel(descriptor, ProviderConfig("masked"))
        editor = panel._editors["api_key"]
        assert isinstance(editor, QLineEdit)
        assert editor.echoMode() == QLineEdit.EchoMode.Password

    def test_required_fields_are_marked_and_optional_ones_are_not(self, qapp: object):
        """A red asterisk is the only signal that separates mandatory from optional."""
        from PySide6.QtWidgets import QFormLayout

        from anyinfer.registry import ProviderDescriptor, ProviderSetupSpec, SetupField
        from demo_app.widgets.settings_dialog import _ProviderPanel

        descriptor = ProviderDescriptor(
            id="marked",
            display_name="Marked",
            factory=lambda config: None,
            setup=ProviderSetupSpec(
                fields=(
                    SetupField("base_url", "Endpoint", "endpoint", required=True),
                    SetupField("api_version", "Version", "api-version"),
                )
            ),
        )
        panel = _ProviderPanel(descriptor, ProviderConfig("marked"))
        layout = panel._form
        assert isinstance(layout, QFormLayout)
        labels = {
            layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
            .widget()
            .text(): layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
            for row in range(layout.rowCount())
            if layout.itemAt(row, QFormLayout.ItemRole.LabelRole) is not None
        }
        required = next(text for text in labels if text.startswith("Endpoint"))
        optional = next(text for text in labels if text.startswith("Version"))

        assert "color:#d13438" in required and "*" in required
        assert "*" not in optional

    def test_placeholders_come_from_the_field_not_the_dialog(self, qapp: object):
        """A hardcoded example stamps one provider's convention onto every other."""
        from PySide6.QtWidgets import QLineEdit

        from anyinfer.registry import ProviderDescriptor, ProviderSetupSpec, SetupField
        from demo_app.widgets.settings_dialog import _ProviderPanel

        descriptor = ProviderDescriptor(
            id="hinted",
            display_name="Hinted",
            factory=lambda config: None,
            setup=ProviderSetupSpec(
                fields=(
                    SetupField(
                        "api_key",
                        "Key",
                        "secret",
                        placeholder="env://HINTED_API_KEY",
                    ),
                    SetupField("other_key", "Other", "secret"),
                )
            ),
        )
        panel = _ProviderPanel(descriptor, ProviderConfig("hinted"))

        declared = panel._editors["api_key"]
        fallback = panel._editors["other_key"]
        assert isinstance(declared, QLineEdit) and isinstance(fallback, QLineEdit)
        assert declared.placeholderText() == "env://HINTED_API_KEY"
        # The generic fallback must not name any particular provider's variable.
        assert "OPENAI" not in fallback.placeholderText()

    def test_an_any_of_group_is_satisfied_by_either_field(self, qapp: object):
        """Anthropic takes an API key *or* an OAuth token — neither alone is required."""
        from anyinfer.registry import ProviderDescriptor, ProviderSetupSpec, SetupField
        from demo_app.widgets.settings_dialog import _ProviderPanel

        descriptor = ProviderDescriptor(
            id="either-or",
            display_name="Either Or",
            factory=lambda config: None,
            setup=ProviderSetupSpec(
                fields=(
                    SetupField("api_key", "API key", "secret"),
                    SetupField("oauth_token", "OAuth token", "secret"),
                ),
                any_of=(("api_key", "oauth_token"),),
            ),
        )

        empty = _ProviderPanel(descriptor, ProviderConfig("either-or"))
        assert empty.missing_required() == ["API key or OAuth token"]

        keyed = _ProviderPanel(
            descriptor, ProviderConfig("either-or", values={"api_key": "sk-x"})
        )
        assert keyed.missing_required() == []

        oauthed = _ProviderPanel(
            descriptor, ProviderConfig("either-or", values={"oauth_token": "sk-ant-oat01-x"})
        )
        assert oauthed.missing_required() == []

    def test_anthropic_offers_both_credentials_and_an_optional_version(self, qapp: object):
        """The reported UI defects, asserted against the real descriptor."""
        from anyinfer.providers.anthropic import descriptor
        from demo_app.widgets.settings_dialog import _ProviderPanel

        panel = _ProviderPanel(descriptor, ProviderConfig("anthropic"))

        assert set(panel.values()) >= {"api_key", "oauth_token", "api_version"}
        # An API version the user cannot be expected to know must not block a save.
        assert not any(f.required for f in descriptor.setup.fields if f.key == "api_version")
        # Neither credential is individually required; one of the two is.
        assert panel.missing_required() == ["Anthropic API key or claude.ai OAuth token"]

    def test_saving_preserves_a_provider_options_mapping(self, qapp: object):
        """The dialog edits no options, so a save round-trip must not drop them."""
        config = default_config().with_provider(
            ProviderConfig(
                DEMO_PROVIDER_ID, enabled=True, options={"reasoning_effort": "high"}
            )
        )
        dialog = self._dialog(config)

        result = dialog.result_config()
        assert result.for_provider(DEMO_PROVIDER_ID).options == {"reasoning_effort": "high"}

    def test_a_provider_that_is_no_longer_installed_still_renders(self, qapp: object):
        """Its settings must survive a save, not be silently deleted."""
        config = DemoConfig(
            providers=(
                ProviderConfig("gone-away", enabled=True, values={"api_key": "env://K"}),
            )
        )
        dialog = self._dialog(config)

        assert len(dialog._rows) == 1
        assert "not installed" in dialog._rows[0].descriptor.display_name
        assert dialog.result_config().for_provider("gone-away").provider_id == "gone-away"

    def test_standard_value_fields_start_folded_away(self, qapp: object):
        """The prompt is what the provider cannot know; the rest waits behind a chevron."""
        from anyinfer.registry import ProviderDescriptor, ProviderSetupSpec, SetupField
        from demo_app.widgets.settings_dialog import _ProviderPanel

        descriptor = ProviderDescriptor(
            id="folded",
            display_name="Folded",
            factory=lambda config: None,
            setup=ProviderSetupSpec(
                fields=(
                    SetupField("api_key", "Key", "secret", required=True),
                    SetupField(
                        "base_url",
                        "Endpoint",
                        "endpoint",
                        advanced=True,
                        default_value="https://api.folded.example/v1",
                    ),
                )
            ),
        )
        panel = _ProviderPanel(descriptor, ProviderConfig("folded"))
        section = panel.advanced_section
        assert section is not None
        assert not section.expanded
        assert not section._body.isVisibleTo(panel)
        # Folded away, never dropped: a save still round-trips the value.
        assert set(panel.values()) == {"api_key", "base_url"}

    def test_a_folded_field_shows_the_value_it_will_use(self, qapp: object):
        """An empty editor has to read as "uses this", not as "unset"."""
        from PySide6.QtWidgets import QLineEdit

        from anyinfer.registry import ProviderDescriptor, ProviderSetupSpec, SetupField
        from demo_app.widgets.settings_dialog import _ProviderPanel

        descriptor = ProviderDescriptor(
            id="defaulted",
            display_name="Defaulted",
            factory=lambda config: None,
            setup=ProviderSetupSpec(
                fields=(
                    SetupField(
                        "base_url",
                        "Endpoint",
                        "endpoint",
                        advanced=True,
                        default_value="http://127.0.0.1:9999/v1",
                    ),
                )
            ),
        )
        panel = _ProviderPanel(descriptor, ProviderConfig("defaulted"))

        editor = panel._editors["base_url"]
        assert isinstance(editor, QLineEdit)
        assert editor.placeholderText() == "http://127.0.0.1:9999/v1"
        assert "http://127.0.0.1:9999/v1" in editor.toolTip()

    def test_a_stored_override_opens_the_disclosure(self, qapp: object):
        """Hiding a setting that is in force is worse than showing one that is not."""
        from anyinfer.registry import ProviderDescriptor, ProviderSetupSpec, SetupField
        from demo_app.widgets.settings_dialog import _ProviderPanel

        descriptor = ProviderDescriptor(
            id="overridden",
            display_name="Overridden",
            factory=lambda config: None,
            setup=ProviderSetupSpec(
                fields=(
                    SetupField(
                        "base_url",
                        "Endpoint",
                        "endpoint",
                        advanced=True,
                        default_value="https://api.overridden.example/v1",
                    ),
                )
            ),
        )
        panel = _ProviderPanel(
            descriptor,
            ProviderConfig("overridden", values={"base_url": "https://proxy.internal/v1"}),
        )
        section = panel.advanced_section
        assert section is not None and section.expanded

    def test_an_engine_with_only_standard_values_asks_nothing(self, qapp: object):
        """Ollama and every keyless local engine land here — install it and go."""
        from demo_app.widgets.settings_dialog import _ProviderPanel

        descriptor = self._dialog()._registry.get("ollama")
        panel = _ProviderPanel(descriptor, ProviderConfig("ollama"))

        assert descriptor.setup.essential_fields == ()
        assert panel.missing_required() == []
        assert panel.advanced_section is not None
        texts = [
            panel._form.itemAt(row, panel._form.ItemRole.SpanningRole).widget().text()
            for row in range(panel._form.rowCount())
            if panel._form.itemAt(row, panel._form.ItemRole.SpanningRole) is not None
        ]
        assert any("standard settings" in text for text in texts)

    def test_the_dropdown_offers_engines_not_configured_instances(self, qapp: object):
        """A derived instance descriptor must not be offered as a new engine to add."""
        from anyinfer.registry import ProviderDescriptor

        dialog = self._dialog(DemoConfig())
        before = dialog._engines.count()
        dialog._registry.register(
            ProviderDescriptor(
                id="work-instance",
                display_name="Work Instance",
                factory=lambda config: None,
                derived_from=DEMO_PROVIDER_ID,
            )
        )
        rebuilt = self._dialog(DemoConfig())
        # The fresh dialog uses its own registry, so compare shapes rather than counts.
        assert before == rebuilt._engines.count()
        assert "work-instance" not in [
            dialog._engines.itemData(i) for i in range(dialog._engines.count())
        ]


class TestTelemetryView:
    def test_groups_events_under_their_request(self, qapp: object):
        from anyinfer.events.telemetry import RequestStarted, TargetResolved
        from anyinfer.types.requests import ResolvedTarget
        from demo_app.widgets.telemetry_view import TelemetryView

        view = TelemetryView()
        view.add_event(RequestStarted(request_id="r1", targets=("demo-fake:reliable",)))
        view.add_event(TargetResolved("r1", ResolvedTarget("demo-fake", "reliable")))

        assert len(view._requests) == 1
        assert view.event_count == 2

    def test_marks_withheld_payloads(self, qapp: object):
        from anyinfer.events.telemetry import RequestStarted
        from demo_app.widgets.telemetry_view import _payload_note

        note = _payload_note(RequestStarted(request_id="r", targets=()))
        assert "withheld" in note


class TestChatView:
    def test_turns_do_not_run_together(self, qapp: object):
        from demo_app.widgets.chat_view import MessageList

        view = MessageList()
        view.add_user_message("First question?")
        view.begin_assistant_message("demo-fake:reliable")
        view.append_delta("An answer.")
        view.end_assistant_message()
        view.add_user_message("Second question?")

        lines = view.transcript_text().splitlines()
        assert lines == [
            "You",
            "First question?",
            "Assistant (demo-fake:reliable)",
            "An answer.",
            "You",
            "Second question?",
        ]

    def test_answer_resumes_on_its_own_line_after_a_notice(self, qapp: object):
        """A retry notice mid-turn must not run into the answer text that follows it."""
        from demo_app.widgets.chat_view import MessageList

        view = MessageList()
        view.begin_assistant_message("demo-fake:flaky")
        view.add_notice("[retried] demo-fake:flaky — unavailable", severity="warn")
        view.append_delta("The answer.")

        text = view.transcript_text()
        assert text.endswith("The answer.")
        # The notice reads as happening before the answer, not run into it.
        assert text.index("retried") < text.index("The answer.")

    def test_empty_assistant_turns_are_dropped(self, qapp: object):
        from demo_app.widgets.chat_view import MessageList

        view = MessageList()
        view.begin_assistant_message("demo-fake:reliable")
        view.end_assistant_message()

        assert view.transcript_text() == ""

    def test_markdown_is_rendered_on_turn_completion(self, qapp: object):
        from demo_app.widgets.chat_view import MessageBubble

        bubble = MessageBubble("assistant", "demo-fake:reliable")
        bubble.append_delta("**bold**")
        bubble.render_final()

        assert "bold" in bubble._body.toHtml()
        assert "font-weight" in bubble._body.toHtml() or "<strong>" in bubble._body.toHtml()

    def test_bubbles_grow_to_fit_their_text_instead_of_scrolling(self, qapp: object):
        """A long answer must be readable in full, not boxed behind scrollbars."""
        from demo_app.widgets.chat_view import MessageBubble

        bubble = MessageBubble("assistant", "demo-fake:reliable")
        bubble.set_plain_text("A long answer. " * 60)
        bubble.show()
        qapp.processEvents()  # type: ignore[attr-defined]

        body = bubble._body
        assert body.height() >= body.document().size().height()
        assert not body.verticalScrollBar().isVisible()
        assert not body.horizontalScrollBar().isVisible()

    def test_fenced_code_wraps_inside_the_bubble(self, qapp: object):
        """Qt leaves <pre> unwrapped by default, which pushes code off the bubble's edge."""
        from demo_app.widgets.chat_view import MessageBubble

        bubble = MessageBubble("assistant", "demo-fake:reliable")
        code = " + ".join(f"value_{index}" for index in range(40))
        bubble.append_delta(f"```python\nx = {code}\n```\n")
        bubble.render_final()
        bubble.show()
        qapp.processEvents()  # type: ignore[attr-defined]

        body = bubble._body
        assert body.document().size().width() <= body.viewport().width()

    def test_long_turns_use_the_full_bubble_width_and_short_ones_do_not(self, qapp: object):
        from demo_app.widgets.chat_view import ASSISTANT_BUBBLE_MAX_WIDTH, MessageBubble

        short = MessageBubble("assistant", "demo-fake:reliable")
        short.set_plain_text("Hi.")
        long = MessageBubble("assistant", "demo-fake:reliable")
        long.set_plain_text("A long answer. " * 60)

        assert long._body.sizeHint().width() > short._body.sizeHint().width()
        assert long._body.sizeHint().width() <= ASSISTANT_BUBBLE_MAX_WIDTH

    def test_copy_button_copies_the_message_text(self, qapp: object):
        from PySide6.QtWidgets import QApplication

        from demo_app.widgets.chat_view import MessageBubble

        bubble = MessageBubble("assistant", "demo-fake:reliable")
        bubble.append_delta("Copy me.")
        bubble._copy()

        assert QApplication.clipboard().text() == "Copy me."

    def test_welcome_view_hidden_once_a_message_is_added(self, qapp: object):
        from demo_app.widgets.chat_view import MessageList, WelcomeView

        view = MessageList()
        welcome = WelcomeView()
        view.set_empty_state(welcome)
        assert not welcome.isHidden()

        view.add_user_message("Hi")
        assert welcome.isHidden()

    def test_welcome_view_swaps_the_wordmark_variant_by_theme(self, qapp: object):
        from demo_app import theme
        from demo_app.widgets.chat_view import WelcomeView

        theme.apply_theme(qapp, "light")
        welcome = WelcomeView()
        assert welcome._logo.renderer().isValid()

        theme.apply_theme(qapp, "dark")
        welcome.reapply_theme()
        assert welcome._logo.renderer().isValid()
        assert theme.is_dark_active()

    def test_active_bubble_header_can_be_retitled_to_the_resolved_target(self, qapp: object):
        """After a fallback, the header must name the target that actually answered."""
        from demo_app.widgets.chat_view import MessageList

        view = MessageList()
        view.begin_assistant_message("demo-fake:flaky")
        view.append_delta("Answered by the fallback.")
        view.set_active_target("demo-fake:reliable")
        view.end_assistant_message()

        assert "Assistant (demo-fake:reliable)" in view.transcript_text()
        assert "flaky" not in view.transcript_text()


class TestMainWindow:
    def test_constructs_and_closes(self, qapp: object):
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            assert window._engine_bar.target() == "demo-fake:reliable"
            assert window._route_targets() == ("demo-fake:reliable",)
        finally:
            window.close()

    def test_temperature_at_minimum_means_unset(self, qapp: object):
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window._temperature.setValue(0.0)
            assert window._build_sampling().temperature is None
            window._temperature.setValue(0.7)
            assert window._build_sampling().temperature == pytest.approx(0.7)
        finally:
            window.close()

    def test_send_streams_an_answer_into_the_transcript(self, qapp: object):
        """The whole path, driven as a user drives it: type, send, watch it stream."""
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window._composer.set_text("What is AnyInfer?")
            window._on_send()
            _drain(window._engine)

            transcript = window._chat.transcript_text()
            assert "What is AnyInfer?" in transcript
            assert "in-process fake provider" in transcript
            assert window._status_metrics._values["target"].text() == "demo-fake:reliable"
            assert window._telemetry.event_count > 0
        finally:
            window.close()

    def test_a_failed_request_does_not_leave_a_dangling_user_turn(self, qapp: object):
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window._engine_bar.set_target("no-such-provider:model")
            window._composer.set_text("This should fail.")
            window._on_send()

            failures: list[str] = []
            loop = QEventLoop()
            window._engine.failed.connect(lambda m, e: (failures.append(m), loop.quit()))
            window._engine.finished.connect(lambda r: loop.quit())
            QTimer.singleShot(15_000, loop.quit)
            loop.exec()

            assert failures, "an unknown provider should fail the request"
            # The user turn that got no answer is dropped, so resending does not double it.
            assert [m.role for m in window._conversation] == ["system"]
            # The library's hint is what makes the failure actionable, so it must be shown.
            assert "known providers" in window._chat.transcript_text()
        finally:
            window.close()

    def test_new_chat_persists_the_previous_conversation_to_disk(self, qapp: object):
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window._composer.set_text("Persist me.")
            window._on_send()
            _drain(window._engine)

            files_before = list(window._conversations_dir.glob("*.json"))
            assert len(files_before) == 1

            window._on_new_chat()
            assert window._chat.transcript_text() == ""
            assert window._conversation == []

            files_after = list(window._conversations_dir.glob("*.json"))
            assert len(files_after) == 1  # the new, empty chat is not saved
            assert window._sidebar._list.count() == 1
        finally:
            window.close()

    def test_selecting_a_conversation_restores_its_transcript(self, qapp: object):
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window._composer.set_text("Remember this.")
            window._on_send()
            _drain(window._engine)
            saved_id = window._current_conversation.id

            window._on_new_chat()
            assert window._chat.transcript_text() == ""

            window._on_conversation_selected(saved_id)
            assert "Remember this." in window._chat.transcript_text()
            assert window._current_conversation.id == saved_id
        finally:
            window.close()

    def test_deleting_a_conversation_removes_its_file(self, qapp: object):
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window._composer.set_text("Delete me.")
            window._on_send()
            _drain(window._engine)
            saved_id = window._current_conversation.id
            path = window._conversations_dir / f"{saved_id}.json"
            assert path.exists()

            window._on_delete_conversation(saved_id)
            assert not path.exists()
        finally:
            window.close()

    def test_hiding_the_left_sidebar_hides_the_conversation_list(self, qapp: object):
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window.show()
            assert window._sidebar.isVisible()
            window._set_left_sidebar_visible(False)
            assert not window._sidebar.isVisible()
            assert not window._left_sidebar_action.isChecked()
            window._set_left_sidebar_visible(True)
            assert window._sidebar.isVisible()
            assert window._left_sidebar_action.isChecked()
        finally:
            window.close()

    def test_hiding_the_right_sidebar_collapses_the_inspector_splitter(self, qapp: object):
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window.show()
            before = window._main_splitter.sizes()
            assert before[1] > 0

            window._set_right_sidebar_visible(False)
            collapsed = window._main_splitter.sizes()
            assert collapsed[1] == 0
            assert not window._right_sidebar_action.isChecked()

            window._set_right_sidebar_visible(True)
            restored = window._main_splitter.sizes()
            assert restored[1] > 0
            assert window._right_sidebar_action.isChecked()
        finally:
            window.close()

    def test_toggle_right_sidebar_flips_visibility(self, qapp: object):
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window.show()
            assert window._main_splitter.sizes()[1] > 0
            window._toggle_right_sidebar()
            assert window._main_splitter.sizes()[1] == 0
            window._toggle_right_sidebar()
            assert window._main_splitter.sizes()[1] > 0
        finally:
            window.close()

    def test_hiding_an_inspector_section_hides_only_that_section(self, qapp: object):
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window.show()
            window._set_inspector_section_visible("telemetry", False)
            assert not window._telemetry_section.isVisible()
            assert window._schema_section.isVisible()
            assert window._providers_section.isVisible()

            window._set_inspector_section_visible("telemetry", True)
            assert window._telemetry_section.isVisible()
        finally:
            window.close()

    def test_conversation_history_checkbox_stays_in_sync_with_left_sidebar_checkbox(
        self, qapp: object
    ):
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window.show()
            window._left_sidebar_action.trigger()
            assert not window._sidebar.isVisible()
        finally:
            window.close()

    def test_saves_to_the_config_path_the_app_was_started_with(self, qapp: object, tmp_path):
        """A session started with `--config PATH` must save back to that path."""
        from demo_app.main_window import MainWindow

        path = tmp_path / "custom" / "session.json"
        window = MainWindow(default_config(), config_path=path)
        try:
            window._set_theme("dark")  # persists preferences
            assert path.exists(), "the save went somewhere other than the session's path"
            assert DemoConfig.load(path).theme == "dark"
        finally:
            window.close()

    def test_custom_theme_can_be_selected_and_restyles_the_window(self, qapp: object):
        from demo_app import theme
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            window._set_theme("ocean")
            assert window._theme == "ocean"
            assert theme.color("bg") == theme.CUSTOM_THEMES["ocean"]["bg"]
        finally:
            window.close()

    def test_theme_menu_stays_in_sync_with_the_active_theme(self, qapp: object):
        """Every theme change, including programmatic ones, checks exactly one action."""
        from demo_app import theme
        from demo_app.main_window import MainWindow

        window = MainWindow(default_config())
        try:
            for key, _label in theme.THEME_CHOICES:
                window._set_theme(key)
                checked = [k for k, a in window._theme_actions.items() if a.isChecked()]
                assert checked == [key]
        finally:
            window.close()


class TestEngineBar:
    def _bar(self, config=None):
        from demo_app.fake_provider import register_demo_provider
        from demo_app.widgets.engine_bar import EngineBar

        registry = ProviderRegistry()
        register_demo_provider(registry)
        return EngineBar(registry, config or default_config())

    def test_builds_the_target_from_the_dropdowns(self, qapp: object):
        bar = self._bar()
        assert bar.provider_id() == DEMO_PROVIDER_ID
        assert bar.target() == "demo-fake:reliable"

    def test_engine_dropdown_shows_display_names(self, qapp: object):
        bar = self._bar()
        assert bar._engine.itemText(0) == "Demo (offline fake)"
        assert bar._engine.itemData(0) == DEMO_PROVIDER_ID

    def test_models_are_listed_with_their_size(self, qapp: object):
        from anyinfer.types.capabilities import (
            DiscoveredModel,
            LocalModelInfo,
            ModelCapabilities,
        )

        bar = self._bar()
        bar.on_models_listed(
            DEMO_PROVIDER_ID,
            [
                DiscoveredModel(
                    "qwen3:8b",
                    ModelCapabilities(
                        local=LocalModelInfo(parameter_size="8.2B", quantization="Q4_K_M")
                    ),
                ),
                DiscoveredModel("plain"),
            ],
        )
        labels = [bar._model.itemText(i) for i in range(bar._model.count())]
        assert "qwen3:8b — 8.2B · Q4_K_M" in labels
        assert "plain" in labels

    def test_a_decorated_model_choice_collapses_to_the_plain_id(self, qapp: object):
        from anyinfer.types.capabilities import (
            DiscoveredModel,
            LocalModelInfo,
            ModelCapabilities,
        )

        bar = self._bar()
        bar.on_models_listed(
            DEMO_PROVIDER_ID,
            [
                DiscoveredModel(
                    "qwen3:8b",
                    ModelCapabilities(local=LocalModelInfo(parameter_size="8.2B")),
                )
            ],
        )
        bar._model.setCurrentText("qwen3:8b — 8.2B")
        assert bar.model() == "qwen3:8b"
        assert bar.target() == "demo-fake:qwen3:8b"

    def test_a_saved_target_for_a_missing_provider_is_kept_verbatim(self, qapp: object):
        bar = self._bar()
        bar.set_target("no-such-provider:model")
        assert bar.target() == "no-such-provider:model"

    def test_auto_detect_shows_the_known_token_count_in_the_disabled_input(self, qapp: object):
        bar = self._bar()
        row = bar._context
        assert row.auto_detect
        assert not row._input.isEnabled()
        # The demo descriptor states a 32,768-token default, so auto-detect shows it.
        assert row._input.placeholderText() == "Auto-detected — 32,768 tokens"
        assert bar.context_window_tokens() is None

    def test_discovery_outranks_the_descriptor_default(self, qapp: object):
        from anyinfer.types.capabilities import (
            DiscoveredModel,
            ModelCapabilities,
            Sourced,
        )

        bar = self._bar()
        bar.on_models_listed(
            DEMO_PROVIDER_ID,
            [
                DiscoveredModel(
                    "reliable",
                    ModelCapabilities(context_window=Sourced(9_000, "discovered")),
                )
            ],
        )
        assert bar._context._input.placeholderText() == "Auto-detected — 9,000 tokens"

    def test_manual_override_round_trips_and_survives_toggling(self, qapp: object):
        bar = self._bar()
        row = bar._context
        row._toggle.click()
        assert not row.auto_detect
        assert row._input.isEnabled()
        row._input.setText("4096")
        assert bar.context_window_tokens() == 4096

        row._toggle.click()  # back to auto: the override is withheld, not forgotten
        assert bar.context_window_tokens() is None
        row._toggle.click()
        assert row._input.text() == "4096"

    def test_a_saved_manual_override_starts_in_manual_mode(self, qapp: object):
        from dataclasses import replace

        bar = self._bar(replace(default_config(), context_window_tokens=8192))
        assert not bar._context.auto_detect
        assert bar.context_window_tokens() == 8192


class TestTheme:
    def test_light_and_dark_render_the_brand_palette(self):
        from demo_app import theme

        light = theme.stylesheet(theme.palette_colors(dark=False))
        dark = theme.stylesheet(theme.palette_colors(dark=True))
        assert "#2C7A6F" in light  # teal reads as the accent on light canvases
        assert "#4FBFA8" in dark  # bright teal takes over on dark canvases
        assert "#E8963C" in light and "#E8963C" in dark  # amber is a brand constant

    def test_an_explicit_preference_overrides_the_system(self, qapp: object):
        from demo_app import theme

        assert theme.resolve_dark(qapp, "dark") is True
        assert theme.resolve_dark(qapp, "light") is False

    def test_custom_themes_have_every_required_token(self):
        from demo_app import theme

        required = set(theme.palette_colors(dark=False))
        for name, tokens in theme.CUSTOM_THEMES.items():
            assert required <= set(tokens), f"{name} is missing tokens: {required - set(tokens)}"

    def test_custom_themes_render_a_valid_stylesheet_and_palette(self):
        from demo_app import theme

        for tokens in theme.CUSTOM_THEMES.values():
            css = theme.stylesheet(tokens)
            assert "$bg" not in css  # every $-token substituted, nothing left dangling
            theme._qt_palette(tokens)  # must not raise

    def test_resolve_theme_returns_the_named_custom_palette(self, qapp: object):
        from demo_app import theme

        resolved = theme.resolve_theme(qapp, "forest")
        assert resolved == theme.CUSTOM_THEMES["forest"]

    def test_resolve_theme_falls_through_to_system_light_dark(self, qapp: object):
        from demo_app import theme

        assert theme.resolve_theme(qapp, "dark") == theme.palette_colors(dark=True)
        assert theme.resolve_theme(qapp, "light") == theme.palette_colors(dark=False)

    def test_apply_theme_tracks_is_dark_active(self, qapp: object):
        from demo_app import theme

        theme.apply_theme(qapp, "dark")
        assert theme.is_dark_active() is True
        theme.apply_theme(qapp, "light")
        assert theme.is_dark_active() is False

    def test_custom_theme_choices_are_distinct_from_defaults(self):
        from demo_app import theme

        default_keys = {key for key, _ in theme.DEFAULT_THEME_CHOICES}
        custom_keys = {key for key, _ in theme.CUSTOM_THEMES_MENU}
        assert default_keys.isdisjoint(custom_keys)
        assert custom_keys == set(theme.CUSTOM_THEMES)


class TestAssets:
    def test_asset_path_resolves_bundled_files(self):
        from demo_app.assets import asset_path

        path = asset_path("anyinfer-icon-512.svg")
        assert path.exists()
        assert path.name == "anyinfer-icon-512.svg"

    def test_read_svg_returns_svg_markup(self):
        from demo_app.assets import read_svg

        svg = read_svg("anyinfer-icon-512.svg")
        assert svg.startswith("<svg")

    def test_both_wordmark_variants_are_bundled(self):
        from demo_app.assets import asset_path

        assert asset_path("anyinfer-horizontal-light.svg").exists()
        assert asset_path("anyinfer-horizontal-dark.svg").exists()


class TestMarkdownRenderer:
    def test_renders_common_constructs(self, qapp: object):
        from demo_app.widgets.markdown_renderer import render_markdown

        html = render_markdown("# Title\n\nSome **bold** and `code`.")
        assert "<h1>Title</h1>" in html
        assert "<strong>bold</strong>" in html
        assert "<code>code</code>" in html

    def test_strips_disallowed_tags_but_keeps_content(self, qapp: object):
        from demo_app.widgets.markdown_renderer import render_markdown

        html = render_markdown("<script>alert(1)</script>Hello")
        assert "<script>" not in html
        assert "alert" in html or "Hello" in html  # falls back to escaped plain text

    def test_only_href_survives_on_links(self, qapp: object):
        from demo_app.widgets.markdown_renderer import render_markdown

        html = render_markdown("[text](https://example.com)")
        assert 'href="https://example.com"' in html
        assert "onclick" not in html


class TestComposer:
    def test_ctrl_enter_sends(self, qapp: object):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        from demo_app.widgets.composer import Composer

        composer = Composer()
        sent = []
        composer.send_requested.connect(lambda: sent.append(True))
        composer._text.setPlainText("hello")
        QTest.keyClick(composer._text, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        assert sent

    def test_escape_cancels(self, qapp: object):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        from demo_app.widgets.composer import Composer

        composer = Composer()
        cancelled = []
        composer.cancel_requested.connect(lambda: cancelled.append(True))
        QTest.keyClick(composer._text, Qt.Key.Key_Escape)
        assert cancelled

    def test_quick_action_chosen_carries_the_prompt(self, qapp: object):
        from demo_app.widgets.composer import QUICK_ACTIONS, Composer

        composer = Composer()
        received = []
        composer.quick_action_chosen.connect(received.append)
        composer.quick_action_chosen.emit(QUICK_ACTIONS[0].prompt)
        assert received == [QUICK_ACTIONS[0].prompt]

    def test_set_token_hint_flags_when_it_does_not_fit(self, qapp: object):
        from demo_app.widgets.composer import Composer

        composer = Composer()
        composer.set_token_hint(100, -5, False)
        assert "100" in composer._hint.text()
        assert composer._hint.styleSheet() != ""


class TestConversationSidebar:
    def test_selecting_an_item_emits_its_id(self, qapp: object):
        from demo_app.conversation import Conversation
        from demo_app.widgets.conversation_sidebar import ConversationSidebar

        sidebar = ConversationSidebar()
        conversation = Conversation.new()
        sidebar.set_conversations([conversation])

        selected = []
        sidebar.conversation_selected.connect(selected.append)
        sidebar._list.setCurrentRow(0)
        assert selected == [conversation.id]

    def test_active_conversation_is_preselected(self, qapp: object):
        from demo_app.conversation import Conversation
        from demo_app.widgets.conversation_sidebar import ConversationSidebar

        sidebar = ConversationSidebar()
        a, b = Conversation.new(), Conversation.new()
        sidebar.set_conversations([a, b], active_id=b.id)

        assert sidebar._list.item(1).isSelected()
        assert not sidebar._list.item(0).isSelected()


class TestCollapsibleSection:
    def test_starts_expanded(self, qapp: object):
        from PySide6.QtWidgets import QLabel

        from demo_app.widgets.collapsible_section import CollapsibleSection

        content = QLabel("body")
        section = CollapsibleSection("Telemetry", content)
        assert not section.minimized
        assert content.isVisible() or not content.isHidden()

    def test_minimizing_hides_content_and_pins_header_height(self, qapp: object):
        from PySide6.QtWidgets import QLabel

        from demo_app.widgets.collapsible_section import HEADER_HEIGHT, CollapsibleSection

        content = QLabel("body")
        section = CollapsibleSection("Telemetry", content)
        section.set_minimized(True)

        assert section.minimized
        assert content.isHidden()
        assert section.maximumHeight() == HEADER_HEIGHT

    def test_restoring_unhides_content_and_unbounds_height(self, qapp: object):
        from PySide6.QtWidgets import QLabel

        from demo_app.widgets.collapsible_section import HEADER_HEIGHT, CollapsibleSection

        content = QLabel("body")
        section = CollapsibleSection("Telemetry", content)
        section.set_minimized(True)
        section.set_minimized(False)

        assert not section.minimized
        assert not content.isHidden()
        assert section.maximumHeight() > HEADER_HEIGHT

    def test_toggle_minimized_flips_state(self, qapp: object):
        from PySide6.QtWidgets import QLabel

        from demo_app.widgets.collapsible_section import CollapsibleSection

        section = CollapsibleSection("Telemetry", QLabel("body"))
        section.toggle_minimized()
        assert section.minimized
        section.toggle_minimized()
        assert not section.minimized

    def test_minimized_changed_signal_fires_with_new_state(self, qapp: object):
        from PySide6.QtWidgets import QLabel

        from demo_app.widgets.collapsible_section import CollapsibleSection

        section = CollapsibleSection("Telemetry", QLabel("body"))
        seen = []
        section.minimized_changed.connect(seen.append)
        section.set_minimized(True)
        section.set_minimized(False)
        assert seen == [True, False]

    def test_accordion_gives_freed_space_to_siblings_in_a_splitter(self, qapp: object):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel, QSplitter

        from demo_app.widgets.collapsible_section import HEADER_HEIGHT, CollapsibleSection

        splitter = QSplitter(Qt.Orientation.Vertical)
        sections = [CollapsibleSection(name, QLabel(name)) for name in ("A", "B", "C")]
        for section in sections:
            splitter.addWidget(section)
        splitter.resize(200, 600)
        splitter.show()
        qapp.processEvents()

        before = splitter.sizes()
        sections[0].set_minimized(True)
        qapp.processEvents()
        after = splitter.sizes()

        assert after[0] == HEADER_HEIGHT
        assert after[1] + after[2] > before[1] + before[2]
        splitter.close()


class TestCli:
    def test_help_needs_no_display(self):
        from demo_app.app import build_parser

        parser = build_parser()
        assert parser.prog == "anyinfer-demo"
        args = parser.parse_args(["--reset"])
        assert args.reset is True
