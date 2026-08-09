"""The shared configuration contract used by every integration surface."""

from __future__ import annotations

import json

import pytest

import anyinfer as ai


def test_loads_config_builds_provider_instances_and_route() -> None:
    config = ai.loads_config(
        json.dumps(
            {
                "format_version": 1,
                "providers": [
                    {"id": "openai", "api_key": "env://OPENAI_API_KEY"},
                    {
                        "id": "work-azure",
                        "adapter": "azure-foundry",
                        "base_url": "https://work.openai.azure.com",
                        "headers": {"x-environment": "work"},
                        "timeout_s": 30,
                    },
                ],
                "default_route": ["openai:gpt-5", "work-azure:gpt-4o"],
            }
        )
    )

    assert config.format_version == 1
    assert [provider.instance_id for provider in config.providers] == [
        "openai",
        "work-azure",
    ]
    assert config.providers[1].provider_id == "azure-foundry"
    assert config.providers[1].headers == {"x-environment": "work"}
    assert config.providers[1].timeout_s == 30.0
    assert config.route is not None
    assert config.route.targets == ("openai:gpt-5", "work-azure:gpt-4o")


def test_declared_setup_fields_flow_to_provider_options() -> None:
    config = ai.loads_config(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "vertex",
                        "values": {
                            "project": "example-project",
                            "location": "us-central1",
                        },
                    }
                ]
            }
        )
    )

    assert config.providers[0].options["project"] == "example-project"
    assert config.providers[0].options["location"] == "us-central1"


def test_demo_owned_fields_and_disabled_providers_are_compatible() -> None:
    config = ai.loads_config(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "anthropic",
                        "provider_id": "anthropic",
                        "enabled": True,
                        "values": {"api_key": "env://ANTHROPIC_API_KEY"},
                        "options": {},
                    },
                    {"enabled": False, "provider_id": "uninstalled-plugin"},
                ],
                "targets": ["anthropic:m"],
                "default_route": ["anthropic:m"],
                "system_prompt": "demo only",
                "theme": "dark",
                "context_window_tokens": 8192,
            }
        )
    )

    assert [provider.provider_id for provider in config.providers] == ["anthropic"]
    assert config.providers[0].api_key == "env://ANTHROPIC_API_KEY"
    assert config.route is not None and config.route.targets == ("anthropic:m",)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ([], "must be a JSON object"),
        ({"format_version": 2}, "unsupported format_version"),
        ({"format_version": True}, "unsupported format_version"),
        ({"providers": {}}, "'providers' must be a list"),
        ({"providers": [{}]}, ".id must be a non-empty string"),
        ({"providers": [{"id": "not-a-provider"}]}, "unknown provider"),
        ({"providers": [{"id": "openai", "api_key_env": "KEY"}]}, "unknown key"),
        (
            {
                "providers": [
                    {
                        "id": "work",
                        "adapter": "azure-foundry",
                        "provider_id": "openai",
                    }
                ]
            },
            "name different providers",
        ),
        ({"providers": [{"id": "openai", "headers": {"x": 1}}]}, "map strings"),
        ({"default_route": "openai:m"}, "must be a list"),
        ({"unexpected": True}, "top level has unknown key"),
    ],
)
def test_invalid_config_is_rejected(document: object, message: str) -> None:
    with pytest.raises(ai.ConfigError, match=message):
        ai.loads_config(json.dumps(document), source="test.json")


def test_duplicate_instance_ids_are_compared_after_normalization() -> None:
    with pytest.raises(ai.ConfigError, match="configured more than once") as caught:
        ai.loads_config(
            json.dumps(
                {
                    "providers": [
                        {"id": "Work_Azure", "adapter": "azure-foundry"},
                        {"id": "work-azure", "adapter": "azure-foundry"},
                    ]
                }
            )
        )
    assert "unique 'id'" in (caught.value.hint or "")


def test_size_limit_applies_before_json_parsing() -> None:
    oversized = " " * (ai.MAX_CONFIG_BYTES + 1)
    with pytest.raises(ai.ConfigError, match="byte limit"):
        ai.loads_config(oversized)


def test_invalid_utf8_text_is_reported_as_a_config_error() -> None:
    with pytest.raises(ai.ConfigError, match="not valid UTF-8"):
        ai.loads_config('"\ud800"')


def test_load_config_wraps_file_errors(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ai.ConfigError, match="cannot read file") as caught:
        ai.load_config(missing)
    assert caught.value.phase == "configure"


# ---- advanced context-reduction settings ---------------------------------------------


def test_a_file_without_a_context_block_gets_the_shipped_defaults() -> None:
    from anyinfer.context import ContextTuning

    assert ai.loads_config("{}").context == ContextTuning()


def test_the_context_block_parses_into_tuning() -> None:
    config = ai.loads_config(
        json.dumps(
            {
                "context": {
                    "selection_order": "density",
                    "diversity": 0.25,
                    "query_expansion": True,
                    "near_duplicate_threshold": 0.9,
                }
            }
        )
    )
    assert config.context.selection_order == "density"
    assert config.context.diversity == 0.25
    assert config.context.query_expansion
    assert config.context.near_duplicate_threshold == 0.9


def test_a_misspelled_context_setting_is_an_error_not_a_silent_no_op() -> None:
    with pytest.raises(ai.ConfigError, match="unknown context setting"):
        ai.loads_config(json.dumps({"context": {"diversty": 0.5}}))


def test_an_out_of_range_context_setting_is_rejected() -> None:
    with pytest.raises(ai.ConfigError, match="diversity") as caught:
        ai.loads_config(json.dumps({"context": {"diversity": 5}}))
    assert "configuration guide" in (caught.value.hint or "")


def test_the_context_block_must_be_an_object() -> None:
    with pytest.raises(ai.ConfigError, match="'context' must be an object"):
        ai.loads_config(json.dumps({"context": ["density"]}))


def test_context_settings_reach_a_reduction() -> None:
    from anyinfer.context import ContextDocument, select

    config = ai.loads_config(json.dumps({"context": {"collapse_duplicates": False}}))
    documents = [
        ContextDocument.of("a.py", "same\n"),
        ContextDocument.of("b.py", "same\n"),
    ]
    reduction = select(documents, "same", max_tokens=1_000, tuning=config.context)
    assert reduction.collapsed_exact == 0
    assert reduction.text.count("same") == 2
