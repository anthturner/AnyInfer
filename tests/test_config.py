"""The shared configuration contract used by every integration surface."""

from __future__ import annotations

import json
import ssl
import warnings
from pathlib import Path

import httpx2
import pytest

import anyinfer as ai
from anyinfer.config import build_observers
from support import self_signed_cert


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
                "ignore_runtime_hardware_constraints": True,
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


@pytest.mark.parametrize(
    "server",
    [
        {"name": 7, "command": ["tool-server"]},
        {"name": "tools", "command": ["tool-server"], "env": {"TOKEN": 7}},
        {
            "name": "tools",
            "url": "https://tools.invalid/mcp",
            "headers": {"authorization": ["token"]},
        },
        {"name": "tools", "command": ["tool-server"], "timeout_s": 0},
    ],
)
def test_mcp_config_rejects_values_it_cannot_preserve(server: dict[str, object]) -> None:
    with pytest.raises(ai.ConfigError):
        ai.loads_config(json.dumps({"mcp": [server]}))


def test_a_named_arena_cannot_be_null() -> None:
    with pytest.raises(ai.ConfigError, match=r"arenas\.review must be an object"):
        ai.loads_config(json.dumps({"arenas": {"review": None}}))


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
    {
        "providers": [{"id": "cohere", "api_key": "env://CO_API_KEY"}],
        "default_route": ["cohere:command-a-03-2025"],
        "operation_routes": {
            "embedding": ["cohere:embed-v4.0"],
            "rerank": ["cohere:rerank-v3.5"],
        },
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
    comment = json.loads(text)[COMMENT_KEY]
    assert "review literal credentials" in comment
    assert "safe to commit" not in comment
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


def test_operation_routes_parse_into_routes() -> None:
    config = ai.loads_config(
        json.dumps(
            {
                "providers": [{"id": "cohere", "api_key": "env://CO_API_KEY"}],
                "operation_routes": {"embedding": ["cohere:embed-v4.0"]},
            }
        )
    )
    assert config.operation_routes["embedding"].targets == ("cohere:embed-v4.0",)
    assert "rerank" not in config.operation_routes


def test_operation_routes_reject_generation_key() -> None:
    with pytest.raises(ai.ConfigError, match="unknown operation 'generation'"):
        ai.loads_config(json.dumps({"operation_routes": {"generation": ["openai:gpt-5"]}}))


def test_operation_routes_reject_empty_target_list() -> None:
    with pytest.raises(ai.ConfigError, match="non-empty list"):
        ai.loads_config(json.dumps({"operation_routes": {"embedding": []}}))


def test_repair_block_parses_and_round_trips() -> None:
    """Without this block a sidecar deployment cannot reach the repair loop at all.

    The Python API takes `repair=` per call and the CLI has `run --repair`; `anyinfer
    serve` builds its client from the config file, so structured output through the
    sidecar validated and failed where the Python path would have recovered.
    """
    config = ai.loads_config(
        json.dumps({"format_version": 1, "providers": [], "repair": {"max_attempts": 3}})
    )

    assert config.repair is not None
    assert config.repair.max_attempts == 3
    assert json.loads(ai.dumps_config(config))["repair"] == {"max_attempts": 3}


def test_an_absent_repair_block_means_no_repair() -> None:
    """Repair costs another provider call, so a file that did not ask never spends one."""
    config = ai.loads_config(json.dumps({"format_version": 1, "providers": []}))

    assert config.repair is None
    assert "repair" not in json.loads(ai.dumps_config(config))


def test_a_misspelled_repair_key_fails_loudly() -> None:
    with pytest.raises(ai.ConfigError, match="repair"):
        ai.loads_config(
            json.dumps(
                {"format_version": 1, "providers": [], "repair": {"max_attemps": 3}}
            )
        )


# ---- credential references -----------------------------------------------------------


def test_an_api_key_scheme_nothing_can_resolve_fails_at_load() -> None:
    """Named at the config location, not later as a misleading 401 from the provider."""
    with pytest.raises(ai.ConfigError, match="which no credential resolver handles") as excinfo:
        ai.loads_config(
            json.dumps(
                {
                    "format_version": 1,
                    "providers": [{"id": "openai", "api_key": "vault://prod/openai"}],
                }
            )
        )

    assert excinfo.value.hint is not None
    assert "anyinfer.credential_stores" in excinfo.value.hint


def test_the_builtin_schemes_and_literals_load_without_plugin_discovery() -> None:
    """The common cases must not pay for the extension point by importing third-party code."""
    for reference in ("env://OPENAI_API_KEY", "credential://system/openai", "sk-a-literal"):
        config = ai.loads_config(
            json.dumps(
                {
                    "format_version": 1,
                    "providers": [{"id": "openai", "api_key": reference}],
                }
            )
        )
        assert config.providers[0].api_key == reference


# ---- observers -----------------------------------------------------------------------


def test_observer_block_parses_into_inert_specs(tmp_path: Path) -> None:
    """Reading a config file must not open a log file, the same rule `mcp` follows."""
    target = tmp_path / "telemetry.jsonl"
    config = ai.loads_config(
        json.dumps(
            {
                "format_version": 1,
                "providers": [],
                "observers": ["logging", {"name": "jsonl", "options": {"path": str(target)}}],
            }
        )
    )

    assert [spec.name for spec in config.observers] == ["logging", "jsonl"]
    assert not target.exists(), "parsing must not construct the sink"


def test_build_observers_constructs_them(tmp_path: Path) -> None:
    target = tmp_path / "telemetry.jsonl"
    config = ai.loads_config(
        json.dumps(
            {
                "format_version": 1,
                "providers": [],
                "observers": [{"name": "jsonl", "options": {"path": str(target)}}],
            }
        )
    )

    built = build_observers(config.observers)
    try:
        assert [type(o).__name__ for o in built] == ["JsonlObserver"]
        assert target.exists()
    finally:
        built[0].close()


def test_logging_observer_options_accept_the_string_forms_a_config_file_can_carry() -> None:
    """TOML and JSON carry scalars, so a level and a logger have to be expressible as names."""
    config = ai.loads_config(
        json.dumps(
            {
                "format_version": 1,
                "providers": [],
                "observers": [
                    {
                        "name": "logging",
                        "options": {"level": "WARNING", "logger": "my.app.telemetry"},
                    }
                ],
            }
        )
    )

    built = build_observers(config.observers)
    assert [type(o).__name__ for o in built] == ["LoggingObserver"]


def test_a_bad_logging_level_fails_at_load_not_at_the_first_event() -> None:
    """A bad level must not survive load.

    Otherwise `isEnabledFor` raises per event, the dispatcher suppresses it after one
    warning, and the operator gets a silently empty access log.
    """
    config = ai.loads_config(
        json.dumps(
            {
                "format_version": 1,
                "providers": [],
                "observers": [{"name": "logging", "options": {"level": "LOUD"}}],
            }
        )
    )

    with pytest.raises(ai.ConfigError, match="could not be built"):
        build_observers(config.observers)


def test_observer_block_round_trips(tmp_path: Path) -> None:
    spec = {
        "format_version": 1,
        "providers": [],
        "observers": ["logging", {"name": "jsonl", "options": {"path": str(tmp_path / "t")}}],
    }
    config = ai.loads_config(json.dumps(spec))
    assert json.loads(ai.dumps_config(config))["observers"] == spec["observers"]


def test_an_unknown_observer_name_fails_at_load_not_at_the_first_event() -> None:
    with pytest.raises(ai.ConfigError, match="unknown observer"):
        ai.loads_config(
            json.dumps({"format_version": 1, "providers": [], "observers": ["nope"]})
        )


def test_a_misspelled_observer_key_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(ai.ConfigError, match="observers"):
        ai.loads_config(
            json.dumps(
                {
                    "format_version": 1,
                    "providers": [],
                    "observers": [{"nmae": "logging"}],
                }
            )
        )


def test_build_observers_reports_bad_options_as_config_errors(tmp_path: Path) -> None:
    config = ai.loads_config(
        json.dumps(
            {
                "format_version": 1,
                "providers": [],
                "observers": [{"name": "jsonl", "options": {"not_a_parameter": 1}}],
            }
        )
    )
    with pytest.raises(ai.ConfigError, match="could not be built"):
        build_observers(config.observers)


def test_no_observer_block_means_no_sinks() -> None:
    config = ai.loads_config(json.dumps({"format_version": 1, "providers": []}))
    assert config.observers == ()
    assert build_observers(config.observers) == ()


# ---- proxy, CA bundle, mTLS ----------------------------------------------------------


def test_connection_settings_parse_and_round_trip() -> None:
    """Per-instance, so one provider can trust a corporate CA while another does not."""
    spec = {
        "format_version": 1,
        "providers": [
            {
                "id": "openai",
                "api_key": "env://K",
                "proxy": "http://corp-proxy:3128",
                "verify": "/etc/ssl/corp-ca.pem",
                "client_cert": ["/etc/ssl/client.pem", "/etc/ssl/client.key"],
            }
        ],
    }
    config = ai.loads_config(json.dumps(spec))
    settings = config.providers[0]

    assert settings.proxy == "http://corp-proxy:3128"
    assert settings.verify == "/etc/ssl/corp-ca.pem"
    assert settings.client_cert == ("/etc/ssl/client.pem", "/etc/ssl/client.key")
    assert json.loads(ai.dumps_config(config))["providers"][0] == spec["providers"][0]


def test_verify_false_disables_tls_verification() -> None:
    config = ai.loads_config(
        json.dumps(
            {"format_version": 1, "providers": [{"id": "openai", "verify": False}]}
        )
    )
    assert config.providers[0].verify is False


def test_verify_true_is_the_default_and_is_not_stored() -> None:
    """`true` means "as shipped"; keeping it would only make the file noisier."""
    config = ai.loads_config(
        json.dumps({"format_version": 1, "providers": [{"id": "openai", "verify": True}]})
    )
    assert config.providers[0].verify is None
    assert "verify" not in json.loads(ai.dumps_config(config))["providers"][0]


@pytest.mark.parametrize(
    "bad",
    [
        {"proxy": ""},
        {"verify": 3},
        {"client_cert": ["only-one"]},
        {"client_cert": 7},
    ],
)
def test_malformed_connection_settings_are_refused(bad: dict[str, object]) -> None:
    with pytest.raises(ai.ConfigError):
        ai.loads_config(
            json.dumps({"format_version": 1, "providers": [{"id": "openai", **bad}]})
        )


def test_connection_settings_default_to_unset() -> None:
    """The ordinary case must leave httpx's own environment handling alone."""
    config = ai.loads_config(json.dumps({"format_version": 1, "providers": [{"id": "openai"}]}))
    settings = config.providers[0]
    assert (settings.proxy, settings.verify, settings.client_cert) == (None, None, None)


def test_connection_settings_reach_the_built_http_client() -> None:
    """The one seam a regression slips through: config→settings was pinned, settings→httpx was not.

    Everything above asserts the settings object carries the values. Nothing asserted the
    adapter's client is actually built with them, which is where a silently unused CA
    bundle would live.
    """
    from anyinfer.providers.http import build_client

    # A configured proxy makes httpx route through a mounted proxy transport rather than
    # its default one, so the mount table is the observable proof the value arrived.
    client = build_client(base_url="https://example.invalid", proxy="http://corp-proxy:3128")
    assert client._mounts, "a configured proxy must produce a proxy-mounted transport"

    # `verify=False` reaches the SSL context, which is inspectable without the deprecated
    # string-path form.
    unverified = build_client(base_url="https://example.invalid", verify=False)
    assert unverified._transport._pool._ssl_context.verify_mode == ssl.CERT_NONE

    verified = build_client(base_url="https://example.invalid")
    assert verified._transport._pool._ssl_context.verify_mode == ssl.CERT_REQUIRED


def test_a_supplied_transport_takes_over_from_the_connection_settings() -> None:
    """A supplied transport wins over the connection settings.

    A caller bringing its own transport owns connection handling; this is what the
    offline fake-server and cassette modes rely on.
    """
    from anyinfer.providers.http import build_client

    sentinel = httpx2.AsyncHTTPTransport()
    client = build_client(
        base_url="https://example.invalid",
        transport=sentinel,
        proxy="http://corp-proxy:3128",
        verify=False,
    )

    assert client._transport is sentinel
    assert not client._mounts


def test_a_private_ca_and_mtls_can_be_configured_together(tmp_path: Path) -> None:
    """The exact combination the TLS section documents, which httpx refuses as two fields.

    httpx once took a CA path as `verify=<str>` and a certificate as `cert=...`; both are
    deprecated in favour of one `ssl.SSLContext`, and passing them *together* — the
    corporate-CA-plus-mTLS case — raises `TypeError`. Resolving them into one context is
    what keeps the documented example working.
    """
    from anyinfer.providers.http import build_client

    cert, key, _ = self_signed_cert(tmp_path)
    client = build_client(
        base_url="https://example.invalid",
        proxy="http://corp-proxy:3128",
        verify=str(cert),
        client_cert=(str(cert), str(key)),
    )

    assert client._mounts, "the proxy must still be applied alongside the TLS settings"
    context = next(iter(client._mounts.values()))._pool._ssl_context
    assert context.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize("combined", [False, True])
def test_a_client_certificate_works_with_the_default_trust_store(
    tmp_path: Path, combined: bool
) -> None:
    """MTLS without a private CA must not lose the system trust store."""
    from anyinfer.providers.http import build_client

    cert, key, both = self_signed_cert(tmp_path)
    client_cert: object = str(both) if combined else (str(cert), str(key))
    client = build_client(base_url="https://example.invalid", client_cert=client_cert)  # type: ignore[arg-type]

    assert client._transport._pool._ssl_context.verify_mode == ssl.CERT_REQUIRED


def test_tls_settings_raise_no_deprecation_warning(tmp_path: Path) -> None:
    """Pins the reason this indirection exists, so a revert is caught rather than debated."""
    from anyinfer.providers.http import build_client

    cert, key, _ = self_signed_cert(tmp_path)
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        build_client(
            base_url="https://example.invalid",
            verify=str(cert),
            client_cert=(str(cert), str(key)),
        )


def test_an_unreadable_ca_bundle_names_the_setting() -> None:
    """`ssl` raises a bare FileNotFoundError naming no setting and offering no next step."""
    from anyinfer.providers.http import build_client

    with pytest.raises(ai.ConfigError, match="cannot load the CA bundle") as excinfo:
        build_client(base_url="https://example.invalid", verify="/no/such/ca-bundle.pem")

    assert excinfo.value.hint is not None
    assert "CA bundle" in excinfo.value.hint


def test_an_unreadable_client_certificate_names_the_setting() -> None:
    from anyinfer.providers.http import build_client

    with pytest.raises(ai.ConfigError, match="cannot load the client certificate"):
        build_client(base_url="https://example.invalid", client_cert="/no/such/cert.pem")


def test_settings_an_adapter_cannot_honor_are_refused_at_load() -> None:
    """Copilot delegates transport to its SDK, so these keys would silently do nothing.

    Accepted-and-ignored is the worse failure: the operator believes their corporate CA is
    in effect. This matches the parser's existing rule for a redundant `verify: true`.
    """
    with pytest.raises(ai.ConfigError, match="cannot honor") as excinfo:
        ai.loads_config(
            json.dumps(
                {
                    "format_version": 1,
                    "providers": [{"id": "copilot", "proxy": "http://corp-proxy:3128"}],
                }
            )
        )

    assert excinfo.value.hint is not None
    assert "HTTPS_PROXY" in excinfo.value.hint


def test_an_adapter_that_cannot_honor_them_still_loads_without_them() -> None:
    config = ai.loads_config(
        json.dumps({"format_version": 1, "providers": [{"id": "copilot"}]})
    )
    assert config.providers[0].provider_id == "copilot"
