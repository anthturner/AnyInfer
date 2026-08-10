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


def test_a_provider_without_a_limits_block_is_paced_by_nothing() -> None:
    config = ai.loads_config(json.dumps({"providers": [{"id": "openai"}]}))
    assert config.providers[0].limits is None


def test_the_limits_block_parses_into_rate_limits() -> None:
    config = ai.loads_config(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "openai",
                        "limits": {
                            "max_concurrent": 4,
                            "requests_per_minute": 120,
                            "min_interval_s": 0.25,
                            "reserve_fraction": 0.1,
                            "respect_headers": False,
                        },
                    }
                ]
            }
        )
    )
    limits = config.providers[0].limits
    assert limits == ai.RateLimits(
        max_concurrent=4,
        requests_per_minute=120.0,
        min_interval_s=0.25,
        reserve_fraction=0.1,
        respect_headers=False,
    )


def test_limits_belong_to_the_instance_not_the_engine() -> None:
    """Two instances of one engine on two keys have two independent allowances."""
    config = ai.loads_config(
        json.dumps(
            {
                "providers": [
                    {"id": "fast", "adapter": "openai", "limits": {"max_concurrent": 10}},
                    {"id": "slow", "adapter": "openai", "limits": {"max_concurrent": 1}},
                ]
            }
        )
    )
    assert [p.limits.max_concurrent for p in config.providers] == [10, 1]  # type: ignore[union-attr]


def test_a_misspelled_limit_is_an_error_not_a_silent_no_op() -> None:
    with pytest.raises(ai.ConfigError, match="limits"):
        ai.loads_config(
            json.dumps({"providers": [{"id": "openai", "limits": {"max_concurent": 4}}]})
        )


@pytest.mark.parametrize(
    "limits",
    [
        {"max_concurrent": 0},
        {"max_concurrent": "four"},
        {"requests_per_minute": -1},
        {"reserve_fraction": 1.5},
        {"respect_headers": "yes"},
    ],
)
def test_unenforceable_limits_are_rejected_at_load(limits: dict[str, object]) -> None:
    with pytest.raises(ai.ConfigError):
        ai.loads_config(json.dumps({"providers": [{"id": "openai", "limits": limits}]}))


def test_the_limits_block_must_be_an_object() -> None:
    with pytest.raises(ai.ConfigError, match="limits must be an object"):
        ai.loads_config(json.dumps({"providers": [{"id": "openai", "limits": [4]}]}))


# ---- writing the format ----------------------------------------------------------------


ROUND_TRIP_DOCUMENTS: list[dict[str, object]] = [
    {},
    {"providers": [{"id": "openai", "api_key": "env://OPENAI_API_KEY"}]},
    {
        "providers": [
            {"id": "openai", "api_key": "env://OPENAI_API_KEY"},
            {
                "id": "work-azure",
                "adapter": "azure-foundry",
                "base_url": "https://work.openai.azure.com",
                "api_version": "2024-05-01-preview",
                "headers": {"x-environment": "work"},
                "timeout_s": 30,
                "limits": {"max_concurrent": 4, "respect_headers": False},
            },
        ],
        "default_route": ["openai:gpt-5", "work-azure:gpt-4o"],
    },
    {"providers": [{"id": "ollama", "base_url": "http://127.0.0.1:11434", "limits": {}}]},
    {"history": {}},
    {"history": {"mode": "proactive", "keep_recent": 2, "keep_system": False}},
    {"cache": {"mode": "explicit", "max_marks": 2, "include_tools": False}},
    {"context": {"diversity": 0.25, "selection_order": "density", "query_expansion": True}},
    {
        "mcp": [
            {"name": "fs", "command": ["mcp-server-fs", "."], "cwd": "/srv"},
            {
                "name": "web",
                "url": "https://tools.invalid/mcp",
                "headers": {"authorization": "env://MCP_TOKEN"},
                "timeout_s": 5,
                "allow_tools": ["search"],
                "deny_tools": ["delete"],
            },
        ]
    },
    {"providers": [{"id": "bedrock", "options": {"region": "us-west-2", "profile": "work"}}]},
]
"""Every shape the loader accepts, as the writer has to reproduce it."""


@pytest.mark.parametrize("document", ROUND_TRIP_DOCUMENTS)
def test_writing_and_reading_a_configuration_is_lossless(document: dict[str, object]) -> None:
    """The contract: `loads_config(dumps_config(c)) == c`, for anything the loader takes."""
    original = ai.loads_config(json.dumps(document))
    assert ai.loads_config(ai.dumps_config(original)) == original


@pytest.mark.parametrize("document", ROUND_TRIP_DOCUMENTS)
def test_a_written_configuration_is_stable(document: dict[str, object]) -> None:
    """A second pass changes nothing, so a rewritten file produces no spurious diff."""
    once = ai.dumps_config(ai.loads_config(json.dumps(document)))
    assert ai.dumps_config(ai.loads_config(once)) == once


def test_an_opt_in_policy_left_at_its_defaults_still_writes_its_block() -> None:
    """An absent block and an empty one mean different things; only one is what was asked."""
    written = json.loads(ai.dumps_config(ai.loads_config('{"history": {}}')))
    assert written["history"] == {}


def test_a_comment_is_written_as_json_the_loader_accepts() -> None:
    from anyinfer.config import COMMENT_KEY

    text = ai.dumps_config(ai.AnyInferConfig(), comments=True)
    assert "safe to commit" in json.loads(text)[COMMENT_KEY]
    assert ai.loads_config(text) == ai.AnyInferConfig()


def test_writing_over_an_existing_file_is_refused(tmp_path) -> None:
    destination = tmp_path / "anyinfer.json"
    destination.write_text("keep me", encoding="utf-8")

    with pytest.raises(ai.ConfigError) as caught:
        ai.dump_config(ai.AnyInferConfig(), destination)

    assert "already exists" in caught.value.detail
    assert caught.value.hint and "force" in caught.value.hint
    assert destination.read_text(encoding="utf-8") == "keep me"


def test_force_replaces_an_existing_file(tmp_path) -> None:
    destination = tmp_path / "anyinfer.json"
    destination.write_text("replace me", encoding="utf-8")

    ai.dump_config(ai.AnyInferConfig(), destination, force=True)

    assert ai.load_config(destination) == ai.AnyInferConfig()


def test_a_value_json_cannot_hold_is_refused_rather_than_mangled() -> None:
    settings = ai.ProviderSettings.of("openai", options={"callback": object()})
    with pytest.raises(ai.ConfigError, match="cannot be written as JSON"):
        ai.dumps_config(ai.AnyInferConfig(providers=(settings,)))
