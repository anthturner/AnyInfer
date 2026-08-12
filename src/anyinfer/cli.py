"""The ``anyinfer`` command-line interface."""

from __future__ import annotations

import argparse
import copy
import json
import mimetypes
import os
import sys
from collections.abc import Sequence
from dataclasses import fields
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from . import __version__
from .config import AnyInferConfig, load_config
from .errors import AnyInferError, ConfigError

__all__ = ["build_parser", "main"]

_DEFAULT_PORT = 8080
_LOOPBACK = "127.0.0.1"

_TOKEN_ENV = "ANYINFER_SERVE_TOKEN"
"""Bearer token source, so a token never has to appear in a process listing."""

_DEFAULT_CONFIG_NAME = "anyinfer.json"
"""What ``init`` writes, and the file every ``--config`` flag in this CLI expects."""

_DEFAULT_STARTER_NAME = "starter.py"
"""The runnable program ``init`` writes beside the configuration."""


def _add_serve_flags(parser: argparse.ArgumentParser) -> None:
    """Add the flags that describe a sidecar's binding, credentials, and exposure.

    Shared by ``serve`` and ``serve install`` so a generated service definition can only
    ever say what the running command would accept: one declaration, no drift.
    """
    parser.add_argument("--host", default=_LOOPBACK, help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT, help="bind port")
    parser.add_argument(
        "--config", type=Path, help="JSON config file describing providers and routes"
    )
    parser.add_argument(
        "--token",
        default=None,
        help=f"bearer token clients must present (or set {_TOKEN_ENV})",
    )
    parser.add_argument(
        "--allow-remote-exposure",
        action="store_true",
        help="permit binding a non-loopback address; requires a token",
    )
    parser.add_argument(
        "--expose",
        action="append",
        default=[],
        metavar="TARGET",
        help="advertise a concrete provider:model target from /v1/models (repeatable)",
    )


def _copy_parser_actions(
    source: argparse.ArgumentParser,
    destination: argparse.ArgumentParser,
    destinations: set[str],
) -> None:
    """Copy selected argparse actions so two verbs cannot drift in shared flags."""
    for action in source._actions:  # argparse exposes no public action-cloning API
        if action.dest in destinations:
            destination._add_action(copy.copy(action))


def _add_arena_flags(parser: argparse.ArgumentParser) -> None:
    """Expose every `ArenaPolicy` field with one generated, parity-checked mapping."""
    from .types.requests import ARENA_MEMO_MODES, ARENA_STRATEGIES, ArenaPolicy

    definitions: dict[str, tuple[str, dict[str, Any]]] = {
        "targets": ("--arena", {"metavar": "A,B,C", "help": "fan out to comma-separated targets"}),
        "strategy": ("--arena-strategy", {"choices": ARENA_STRATEGIES}),
        "judge_target": ("--judge-target", {"metavar": "TARGET"}),
        "instructions": ("--arena-instructions", {"metavar": "TEXT"}),
        "concurrency": ("--arena-concurrency", {"type": int}),
        "min_candidates": ("--arena-min-candidates", {"type": int}),
        "reveal_targets": ("--arena-reveal-targets", {"action": "store_true"}),
        "memoize_tools": ("--memoize-tools", {"choices": ARENA_MEMO_MODES}),
    }
    for item in fields(ArenaPolicy):
        flag, options = definitions[item.name]
        parser.add_argument(flag, dest=f"arena_{item.name}", default=None, **options)
    parser.add_argument("--arena-name", help="named arena from the shared config")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="anyinfer",
        description=(
            "An application-owned hybrid inference runtime for hosted APIs, routing "
            "hubs, existing local services, and supervised llama.cpp."
        ),
    )
    parser.add_argument("--version", action="version", version=f"anyinfer {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    serve = subcommands.add_parser("serve", help="run the OpenAI-compatible HTTP frontend")
    _add_serve_flags(serve)
    # A subparser group that is *not* required, so `anyinfer serve` with no verb keeps
    # running the server, which is the command everything else documents.
    serve_commands = serve.add_subparsers(dest="serve_command", required=False)

    serve_install = serve_commands.add_parser(
        "install",
        help="generate, and optionally register, a service definition for this sidecar",
        description=(
            "Write the systemd unit, launchd agent, or scheduled task that keeps this "
            "sidecar running across logins and reboots. Nothing is registered without "
            "showing the exact file and commands first. User scope by default, which "
            "needs no privileges; --system prints the elevated commands rather than "
            "trying to elevate."
        ),
    )
    _add_serve_flags(serve_install)
    serve_install.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="write the definition to stdout and do nothing else",
    )
    serve_install.add_argument(
        "--system",
        action="store_true",
        help="generate a system-wide service and print the commands to run as root",
    )
    serve_install.add_argument(
        "--force", action="store_true", help="replace an existing definition"
    )
    serve_install.add_argument(
        "-y", "--yes", action="store_true", help="do not ask before writing or registering"
    )
    serve_install.add_argument(
        "--log-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="send output to this file; AnyInfer never rotates it",
    )
    serve_install.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the post-install check that the configured route actually answers",
    )

    serve_uninstall = serve_commands.add_parser(
        "uninstall", help="deregister the service and remove its definition"
    )
    serve_uninstall.add_argument(
        "--system", action="store_true", help="target the system-wide service"
    )
    serve_uninstall.add_argument(
        "-y", "--yes", action="store_true", help="do not ask before removing"
    )

    serve_status = serve_commands.add_parser(
        "status",
        help="report whether the service is installed and what its manager says",
        description=(
            "Read-only. It reports what exists and what the platform's service manager "
            "thinks; it never starts, stops, or restarts anything — that is the "
            "manager's job, not this command's."
        ),
    )
    serve_status.add_argument(
        "--system", action="store_true", help="target the system-wide service"
    )

    run = subcommands.add_parser(
        "run",
        help="run a single prompt and print the result",
        description=(
            "Run one prompt through the same routing, structured-output, and telemetry "
            "path the library uses, then exit. The prompt may be given as an argument, "
            "piped on stdin, or both (stdin is appended, so `cat file | anyinfer run "
            "'Summarize:'` works)."
        ),
    )
    run.add_argument(
        "prompt",
        nargs="?",
        help="the prompt text; omit to read it entirely from stdin",
    )
    run.add_argument(
        "--config", type=Path, help="JSON config file describing providers and routes"
    )
    run.add_argument(
        "--target",
        default=None,
        help="where to send it: an alias ('medium'), or 'provider:model'",
    )
    run.add_argument(
        "--route",
        action="append",
        default=[],
        metavar="TARGET",
        help="ordered fallback target, repeatable; overrides --target",
    )
    _add_arena_flags(run)
    run.add_argument(
        "--context-file",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="caller-approved document to reduce into the request; repeatable",
    )
    run.add_argument(
        "--image",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="attach an image as inline bytes; repeatable",
    )
    run.add_argument(
        "--document",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="attach a document as inline bytes; repeatable",
    )
    run.add_argument(
        "--audio",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="attach audio as inline bytes; repeatable",
    )
    run.add_argument(
        "--context-dir",
        action="append",
        default=[],
        type=Path,
        metavar="DIR",
        help="collect readable source files under a directory; repeatable",
    )
    run.add_argument("--context-query", help="ranking query; defaults to the prompt")
    run.add_argument(
        "--context-strategy",
        choices=("auto", "whole", "ranked", "tiered", "packed"),
        default="auto",
    )
    run.add_argument("--context-max-tokens", type=int, default=None)
    run.add_argument("--context-placement", choices=("system", "prepend_user"), default="system")
    run.add_argument("--system", default=None, help="system prompt")
    run.add_argument(
        "--messages",
        type=Path,
        default=None,
        help=(
            "JSON file holding a multi-turn conversation: a list of "
            "{'role','content'} objects. The prompt and --system are appended to it."
        ),
    )
    run.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="JSON Schema file; the reply is validated against it and printed as JSON",
    )
    run.add_argument(
        "--repair",
        type=int,
        default=None,
        metavar="N",
        help="allow N bounded repair attempts when a schema-checked reply fails to validate",
    )
    run.add_argument(
        "--tool",
        action="append",
        default=[],
        type=Path,
        metavar="FILE",
        help=(
            "JSON file declaring a tool ({'name','description','parameters'}), "
            "repeatable. The CLI never executes tools: requested calls are reported "
            "so a caller can run them."
        ),
    )
    run.add_argument(
        "--tool-choice",
        default="auto",
        choices=["auto", "none", "required"],
        help="how the model may use the declared tools (default: auto)",
    )
    run.add_argument("--temperature", type=float, default=None, help="sampling temperature")
    run.add_argument("--top-p", type=float, default=None, help="nucleus sampling cutoff")
    run.add_argument("--max-tokens", type=int, default=None, help="cap on generated tokens")
    run.add_argument(
        "--stop",
        action="append",
        default=[],
        metavar="TEXT",
        help="stop sequence, repeatable",
    )
    run.add_argument(
        "--reasoning",
        default=None,
        choices=["minimal", "low", "medium", "high"],
        help="reasoning effort, on models that expose it",
    )
    run.add_argument(
        "--timeout", type=float, default=None, metavar="SECONDS", help="per-request timeout"
    )
    run.add_argument(
        "--no-stream",
        action="store_true",
        help="wait for the whole reply instead of streaming it to stdout",
    )
    run.add_argument(
        "--show-reasoning",
        action="store_true",
        help="print reasoning deltas to stderr, on models that emit them",
    )
    run.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object with the text, usage, timing, and tool calls",
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="report what the request would cost and whether it fits, without sending it",
    )
    run.add_argument(
        "--cache",
        choices=("off", "auto", "explicit"),
        help=(
            "engage the target's prompt cache; off unless asked for, because caching "
            "changes what a provider bills"
        ),
    )
    run.add_argument(
        "--stats",
        action="store_true",
        help="print timing, token, and cost figures to stderr when finished",
    )
    run.add_argument(
        "--trace",
        action="store_true",
        help=(
            "print the run manifest to stderr: which target won, which structured-output "
            "mechanism was used, what was dropped or reduced, and on what provenance"
        ),
    )
    run.add_argument(
        "--trace-json",
        nargs="?",
        const="-",
        default=None,
        metavar="PATH",
        help=(
            "write the run manifest as JSON to PATH, or to stdout when given no value. "
            "Content-free: shape, counts, and decisions, never prompt or reply text"
        ),
    )
    embed = subcommands.add_parser(
        "embed",
        help="embed text into vectors",
        description=(
            "Embed one or more texts and print the resulting vectors. Input is a single "
            "positional argument, one text per line from --file/stdin, or one JSON object "
            "per line ({'text': ...}) from --jsonl."
        ),
    )
    embed.add_argument("text", nargs="?", help="a single text to embed")
    embed.add_argument(
        "--config", type=Path, help="JSON config file describing providers and routes"
    )
    embed.add_argument(
        "--target", default=None, help="where to send it: an alias, or 'provider:model'"
    )
    embed.add_argument(
        "--route",
        action="append",
        default=[],
        metavar="TARGET",
        help="ordered fallback target, repeatable; overrides --target",
    )
    embed.add_argument(
        "--file", type=Path, default=None, metavar="PATH", help="newline-delimited texts"
    )
    embed.add_argument(
        "--jsonl",
        type=Path,
        default=None,
        metavar="PATH",
        help="JSON Lines file, one {'text': ...} object per line",
    )
    embed.add_argument(
        "--input-type",
        choices=("query", "document", "classification", "clustering"),
        default=None,
        help="what the embedded text will be used for, on models that distinguish it",
    )
    embed.add_argument("--dimensions", type=int, default=None, help="requested vector length")
    embed.add_argument(
        "--trace",
        action="store_true",
        help="print the run manifest to stderr: route, attempts, usage, and timing",
    )
    embed.add_argument(
        "--trace-json",
        nargs="?",
        const="-",
        default=None,
        metavar="PATH",
        help=(
            "write the run manifest as JSON to PATH, or to stdout when given no value. "
            "Content-free: never input text, document text, or vectors"
        ),
    )
    embed.add_argument(
        "--timeout", type=float, default=None, metavar="SECONDS", help="per-request timeout"
    )
    embed.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object with vectors, space, usage, and timing",
    )
    embed.add_argument(
        "--out", type=Path, default=None, metavar="PATH", help="write JSON output to a file"
    )

    rerank = subcommands.add_parser(
        "rerank",
        help="rank documents by relevance to a query",
        description=(
            "Rank documents against a query and print them best-first. Documents come "
            "from repeated --document flags, one per line from --file, or one JSON "
            "object per line ({'id': ..., 'text': ...}) from --jsonl."
        ),
    )
    rerank.add_argument("query", help="the query every document is scored against")
    rerank.add_argument(
        "--document",
        action="append",
        default=[],
        metavar="TEXT",
        dest="documents",
        help="a document to rank, repeatable; ids are assigned in order",
    )
    rerank.add_argument(
        "--config", type=Path, help="JSON config file describing providers and routes"
    )
    rerank.add_argument(
        "--target", default=None, help="where to send it: an alias, or 'provider:model'"
    )
    rerank.add_argument(
        "--route",
        action="append",
        default=[],
        metavar="TARGET",
        help="ordered fallback target, repeatable; overrides --target",
    )
    rerank.add_argument(
        "--file", type=Path, default=None, metavar="PATH", help="newline-delimited documents"
    )
    rerank.add_argument(
        "--jsonl",
        type=Path,
        default=None,
        metavar="PATH",
        help="JSON Lines file, one {'id': ..., 'text': ...} object per line",
    )
    rerank.add_argument("--top-n", type=int, default=None, metavar="N", help="return only top N")
    rerank.add_argument(
        "--trace",
        action="store_true",
        help="print the run manifest to stderr: route, attempts, usage, and timing",
    )
    rerank.add_argument(
        "--trace-json",
        nargs="?",
        const="-",
        default=None,
        metavar="PATH",
        help=(
            "write the run manifest as JSON to PATH, or to stdout when given no value. "
            "Content-free: never input text, document text, or vectors"
        ),
    )
    rerank.add_argument(
        "--timeout", type=float, default=None, metavar="SECONDS", help="per-request timeout"
    )
    rerank.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object with ranked items, usage, and timing",
    )
    rerank.add_argument(
        "--out", type=Path, default=None, metavar="PATH", help="write JSON output to a file"
    )

    compare = subcommands.add_parser(
        "compare",
        help="compare how one request behaves across targets without sending it",
        description=(
            "Resolve one request against every --target and report fit, degradation, "
            "mechanisms, provenance, and estimated cost. Results stay in caller order; "
            "the command never ranks or chooses a target."
        ),
    )
    _copy_parser_actions(
        run,
        compare,
        {
            "prompt",
            "config",
            "system",
            "messages",
            "schema",
            "repair",
            "tool",
            "tool_choice",
            "temperature",
            "top_p",
            "max_tokens",
            "stop",
            "reasoning",
            "timeout",
            "cache",
            "context_file",
            "context_dir",
            "context_query",
            "context_strategy",
            "context_max_tokens",
            "context_placement",
            "image",
            "document",
            "audio",
        },
    )
    compare.add_argument(
        "--target",
        action="append",
        required=True,
        metavar="TARGET",
        help="target to compare, repeatable; results preserve this order",
    )
    compare.add_argument("--json", action="store_true", help="emit JSON records")
    compare.add_argument(
        "--refresh",
        action="store_true",
        help="refresh provider model listings before comparing (may contact providers)",
    )

    init = subcommands.add_parser(
        "init",
        help="write a working configuration from what this machine can already use",
        description=(
            "Inspect this machine, report what is already usable, and write a valid "
            "configuration file plus a starter program pointed at it. Discovery is "
            "evidence-based: a provider is written only if a loopback endpoint it "
            "declares answered, or a credential variable it names is set. Nothing is "
            "installed, and no credential value is ever written — only 'env://' and "
            "'credential://' references, so the generated file is safe to commit."
        ),
    )
    init.add_argument(
        "--output",
        type=Path,
        default=Path(_DEFAULT_CONFIG_NAME),
        metavar="PATH",
        help=f"where to write the configuration (default: {_DEFAULT_CONFIG_NAME})",
    )
    init.add_argument(
        "--force", action="store_true", help="replace an existing configuration file"
    )
    init.add_argument(
        "--no-probe",
        action="store_true",
        help="do not contact any endpoint; report credential evidence only",
    )
    init.add_argument(
        "--keyring",
        action="store_true",
        help="also look for stored credentials in the OS vault (may prompt to unlock)",
    )
    init.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="write the files without asking, when running on a terminal",
    )
    init.add_argument("--json", action="store_true", help="emit machine-readable output")

    agents_md = subcommands.add_parser(
        "agents-md",
        help="print coding-agent instructions to paste into a consuming repository",
        description=(
            "Print a short instruction fragment describing how AnyInfer is actually "
            "called, for a coding agent working in a repository that uses it. Rendered "
            "from live introspection — the provider counts come from the registry, the "
            "extras from installed metadata, the version from the package, so it cannot "
            "describe an API this release does not have. It writes nothing: redirect it "
            "yourself, e.g. `anyinfer agents-md >> AGENTS.md`."
        ),
    )
    agents_md.add_argument(
        "--format",
        dest="agents_format",
        choices=_agents_md_formats(),
        default="agents",
        help="which consuming file to shape the wrapper for (default: agents)",
    )
    agents_md.add_argument(
        "--config",
        type=Path,
        help="also name this file's configured providers and default route",
    )

    doctor = subcommands.add_parser(
        "doctor", help="report detected hardware and the recommended local tier"
    )
    doctor.add_argument("--json", action="store_true", help="emit machine-readable output")
    doctor.add_argument(
        "--config",
        type=Path,
        help="path to a configuration file; its configured rate limits are reported too",
    )

    verify = subcommands.add_parser(
        "verify", help="prove a target works by sending it one tiny request"
    )
    verify.add_argument(
        "target",
        nargs="?",
        help="a target or alias; defaults to every target in the configured route",
    )
    verify.add_argument("--config", type=Path, help="path to a configuration file")
    verify.add_argument(
        "--timeout", type=float, default=60.0, help="seconds to wait for each answer"
    )
    verify.add_argument("--json", action="store_true", help="emit machine-readable output")

    bench = subcommands.add_parser(
        "benchmark", help="measure a target's prefill and decode throughput"
    )
    bench.add_argument("target", help="a target or alias")
    bench.add_argument("--config", type=Path, help="path to a configuration file")
    bench.add_argument("--prompt-tokens", type=int, default=None, help="approximate prompt size")
    bench.add_argument(
        "--output-tokens", type=int, default=None, help="how many tokens to generate"
    )
    bench.add_argument("--store", type=Path, help="record the measurement in this JSON file")
    bench.add_argument("--json", action="store_true", help="emit machine-readable output")

    context = subcommands.add_parser(
        "context",
        help="reduce a set of files to fit a token budget",
        description=(
            "Collect the given files, reduce them to fit a budget, and print the "
            "envelope. Collection happens here, in the frontend, because deciding what "
            "is safe to send is an application's job — the library only reduces what it "
            "is handed. Use --plan to see what every strategy would produce before "
            "committing to one."
        ),
    )
    context.add_argument("paths", nargs="+", type=Path, help="files or directories to offer")
    context.add_argument(
        "--query", default="", help="what the request is about; drives relevance ranking"
    )
    context.add_argument("--config", type=Path, help="JSON config file (supplies 'context')")
    context.add_argument("--target", help="derive the budget from this target's context window")
    context.add_argument("--max-tokens", type=int, help="token budget; overrides --target")
    context.add_argument(
        "--strategy",
        default="auto",
        choices=_context_strategies(),
        help="reduction strategy (default: auto)",
    )
    context.add_argument("--max-documents", type=int, default=None, help="document ceiling")
    context.add_argument("--max-bytes", type=int, default=None, help="envelope byte ceiling")
    context.add_argument(
        "--pin",
        action="append",
        default=[],
        metavar="PATH",
        help="always include this path, ahead of ranked candidates (repeatable)",
    )
    context.add_argument(
        "--include-generated",
        action="store_true",
        help="offer vendored and generated files, which are skipped by default",
    )
    context.add_argument(
        "--plan",
        action="store_true",
        help="cost every strategy instead of rendering one; spends no inference",
    )
    context.add_argument(
        "--json", action="store_true", dest="as_json", help="print the record as JSON"
    )
    context.add_argument(
        "--preset",
        choices=("default", "recommended"),
        default=None,
        help="start from a named settings preset before applying --context-* flags",
    )
    _add_tuning_flags(context)

    conform = subcommands.add_parser(
        "conform",
        help="run the conformance suite against an adapter and report what it supports",
    )
    conform.add_argument("provider", help="registered provider id of the adapter under test")
    conform.add_argument("--model", help="model id to send during the run")
    conform.add_argument(
        "--scaffold",
        type=Path,
        metavar="DIR",
        help="write a working provider package skeleton into DIR instead of running",
    )
    conform.add_argument(
        "--force", action="store_true", help="overwrite existing files when scaffolding"
    )
    conform.add_argument(
        "--config", type=Path, help="JSON config file describing providers and routes"
    )
    conform.add_argument(
        "--project",
        type=Path,
        help=(
            "directory holding the adapter's pyproject.toml, read for its "
            "[tool.anyinfer.conformance] declarations (default: the current directory)"
        ),
    )
    conform.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="CASE",
        help="restrict the run to one case (repeatable)",
    )
    conform.add_argument("--json", action="store_true", help="emit machine-readable results")
    conform.add_argument(
        "--markdown-row",
        action="store_true",
        help="emit one conformance-matrix row instead of a report",
    )

    mcp = subcommands.add_parser(
        "mcp", help="inspect the Model Context Protocol servers a config file describes"
    )
    mcp_commands = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_list = mcp_commands.add_parser(
        "list", help="connect to each configured server and print the tools it exposes"
    )
    mcp_list.add_argument("--config", type=Path, help="path to a configuration file")
    mcp_list.add_argument("--server", help="only this server, by name")
    mcp_list.add_argument("--json", action="store_true", help="emit machine-readable output")

    providers = subcommands.add_parser("providers", help="list registered providers")
    providers.add_argument("--json", action="store_true", help="emit machine-readable output")

    models = subcommands.add_parser("models", help="browse, download, and locate local models")
    model_commands = models.add_subparsers(dest="models_command", required=True)

    listing = model_commands.add_parser("list", help="browse the catalog with fit annotations")
    listing.add_argument("--best-at", help="filter to one category (coding, reasoning, …)")
    listing.add_argument("--provider", help="filter to models one engine can serve")
    listing.add_argument("--all", action="store_true", help="include models that will not fit")
    listing.add_argument("--json", action="store_true", help="emit machine-readable output")

    add = model_commands.add_parser("add", help="download a catalog model")
    add.add_argument("model", help="a catalog model id")
    add.add_argument("--engine", choices=("llama.cpp", "vllm"), help="which engine to fetch for")
    add.add_argument("--variant", help="acquire this exact variant, skipping selection")
    add.add_argument(
        "--dry-run", action="store_true", help="report the size and choice without downloading"
    )
    add.add_argument(
        "--allow-low-quality",
        action="store_true",
        help="permit quantizations below Q4_K_M when nothing better fits",
    )

    pull = model_commands.add_parser(
        "pull", help="ask an engine that owns its own store to fetch a model"
    )
    pull.add_argument("provider", help="a configured provider, e.g. 'ollama'")
    pull.add_argument("model", help="the model name in that engine's namespace")
    pull.add_argument("--config", type=Path, help="path to a configuration file")

    installed = model_commands.add_parser("installed", help="list downloaded models")
    installed.add_argument("--json", action="store_true", help="emit machine-readable output")

    where = model_commands.add_parser("where", help="print the path of a downloaded model")
    where.add_argument("model", help="a catalog model id")
    where.add_argument("--verify", action="store_true", help="re-hash the files before answering")
    where.add_argument("--json", action="store_true", help="emit machine-readable output")

    remove = model_commands.add_parser("rm", help="delete a downloaded model")
    remove.add_argument("entry", help="a store entry id, as shown by 'models installed'")

    runtime = subcommands.add_parser("runtime", help="manage llama-server runtime variants")
    runtime_commands = runtime.add_subparsers(dest="runtime_command", required=True)

    runtime_commands.add_parser("list", help="show installed and available runtime variants")

    runtime_install = runtime_commands.add_parser("install", help="download a runtime variant")
    runtime_install.add_argument(
        "backend",
        nargs="?",
        choices=("cpu", "vulkan", "metal", "rocm", "cuda"),
        help="which variant; defaults to the small one this machine can use",
    )
    runtime_install.add_argument(
        "--force", action="store_true", help="install even if the hardware checks object"
    )

    runtime_remove = runtime_commands.add_parser("rm", help="delete a runtime variant")
    runtime_remove.add_argument("backend", choices=("cpu", "vulkan", "metal", "rocm", "cuda"))

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Returns:
        A process exit code.
    """
    args = build_parser().parse_args(argv)
    try:
        if args.command == "serve":
            return _serve(args)
        if args.command == "run":
            return _run(args)
        if args.command == "embed":
            return _embed(args)
        if args.command == "rerank":
            return _rerank(args)
        if args.command == "compare":
            return _compare(args)
        if args.command == "init":
            return _init(args)
        if args.command == "agents-md":
            return _agents_md(args)
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "verify":
            return _verify(args)
        if args.command == "benchmark":
            return _benchmark(args)
        if args.command == "context":
            return _context(args)
        if args.command == "providers":
            return _providers(args)
        if args.command == "conform":
            return _conform(args)
        if args.command == "mcp":
            return _mcp(args)
        if args.command == "models":
            return _models(args)
        if args.command == "runtime":
            return _runtime(args)
        return 2
    except AnyInferError as exc:
        return _report_error(exc)


# ---- serve ---------------------------------------------------------------------------


def _serve(args: argparse.Namespace) -> int:
    """Run the frontend, or dispatch one of its service-management verbs."""
    command = getattr(args, "serve_command", None)
    if command == "install":
        return _serve_install(args)
    if command == "uninstall":
        return _serve_uninstall(args)
    if command == "status":
        return _serve_status(args)
    return _serve_run(args)


def _serve_run(args: argparse.Namespace) -> int:
    """Start the HTTP frontend."""
    token = args.token or os.environ.get(_TOKEN_ENV)

    if args.host != _LOOPBACK and not args.allow_remote_exposure:
        print(
            f"refusing to bind {args.host}: pass --allow-remote-exposure to serve beyond "
            "loopback, and understand that this exposes every configured provider",
            file=sys.stderr,
        )
        return 2
    if args.host != _LOOPBACK and not token:
        print(
            f"a non-loopback bind requires a bearer token: pass --token or set {_TOKEN_ENV}",
            file=sys.stderr,
        )
        return 2

    try:
        import uvicorn
    except ImportError:
        print(
            "the serve frontend requires the serve extra: pip install 'anyinfer[serve]'",
            file=sys.stderr,
        )
        return 1

    from . import AsyncClient
    from .serve.app import create_app

    config = _config(args.config)
    settings, route = list(config.providers), config.route
    # The gateway inherits the compaction policy rather than implementing one: it is a
    # codec over a normal client, and that client is where context policy lives.
    client = AsyncClient(
        settings,
        route=route,
        history=config.history,
        cache=config.cache,
        arena=config.arena,
        arenas=config.arenas,
    )
    app = create_app(client, auth_token=token, expose_targets=tuple(args.expose))

    print(f"anyinfer {__version__} serving on http://{args.host}:{args.port}")
    print(f"  authentication: {'bearer token' if token else 'disabled (loopback only)'}")
    print(f"  providers: {', '.join(_describe(s) for s in settings) or '(none configured)'}")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def _describe(settings: Any) -> str:
    """Name one configured instance, showing its engine when the two differ."""
    instance = settings.instance_id
    engine = settings.provider_id
    return instance if instance == engine else f"{instance} ({engine})"


def _config(path: Path | None) -> AnyInferConfig:
    """Load shared configuration, or return an empty configuration."""
    return load_config(path) if path is not None else AnyInferConfig()


# ---- serve install / uninstall / status -------------------------------------------------


def _run_command(command: tuple[str, ...]) -> tuple[int, str]:
    """Run one service-manager command, capturing what it said.

    A module-level seam so the command tests can prove what *would* be run without a
    developer's real systemd, launchd, or Task Scheduler being touched.
    """
    import subprocess

    try:
        finished = subprocess.run(list(command), capture_output=True, text=True, check=False)
    except OSError as exc:
        return 127, f"{command[0]}: {exc}"
    return finished.returncode, (finished.stdout + finished.stderr).strip()


def _service_request(args: argparse.Namespace) -> Any:
    """Build the service request from the flags the user supplied."""
    from .serve.service import ServiceRequest, resolve_executable

    executable, arguments = resolve_executable()
    token = getattr(args, "token", None) or os.environ.get(_TOKEN_ENV)
    config = getattr(args, "config", None)
    return ServiceRequest(
        executable=executable,
        arguments=arguments,
        config=Path(config).resolve() if config is not None else None,
        host=getattr(args, "host", _LOOPBACK),
        port=getattr(args, "port", _DEFAULT_PORT),
        expose=tuple(getattr(args, "expose", ()) or ()),
        allow_remote_exposure=bool(getattr(args, "allow_remote_exposure", False)),
        token=token,
        log_file=getattr(args, "log_file", None),
        scope="system" if getattr(args, "system", False) else "user",
    )


def _print_definition(definition: Any) -> None:
    """Show the exact file and commands, with any secret elided."""
    from .redaction import redact

    print(f"path       {definition.path}")
    if definition.environment_content:
        print(f"env file   {definition.environment_path}   (mode 0600, token only)")
    print(f"scope      {definition.scope}")
    print()
    # Redacted rather than trusted: the token is registered as a secret before this runs,
    # so even an accidental interpolation into the body cannot reach the terminal.
    for line in redact(definition.content).splitlines():
        print(f"  {line}")
    print()
    for label, commands in (
        ("install", definition.install_commands),
        ("uninstall", definition.uninstall_commands),
    ):
        for command in commands:
            print(f"{label:<10} {' '.join(command)}")
    for note in definition.notes:
        print(f"note       {note}")


def _serve_install(args: argparse.Namespace) -> int:
    """Generate a service definition and, once confirmed, register it.

    Returns:
        A process exit code.
    """
    from .redaction import register_secret
    from .serve.service import render_service, write_service

    request = _service_request(args)
    if request.token:
        register_secret(request.token)
    definition = render_service(request)
    _print_definition(definition)

    if args.print_only:
        return 0
    if definition.needs_elevation:
        # Printing rather than elevating. A library CLI that shells into `sudo` is not
        # something to ship, and the operator running these lines is the review step.
        print("\nrun these as root — this command will not elevate for you:")
        print(f"  install -m 644 /dev/stdin {definition.path} <<'UNIT'")
        print("  …the definition above…")
        print("  UNIT")
        for command in definition.install_commands:
            print(f"  {' '.join(command)}")
        return 0
    if not _confirm(f"\nwrite {definition.path} and register the service?", args):
        print("nothing written")
        return 0

    written = write_service(definition, force=args.force)
    for path in written:
        print(f"wrote      {path}")

    for command in definition.install_commands:
        code, output = _run_command(command)
        print(f"ran        {' '.join(command)}" + ("" if code == 0 else f"  (exit {code})"))
        if output:
            for line in output.splitlines():
                print(f"           {line}")
        if code != 0:
            print(
                "the service manager refused the definition; it is written but not registered",
                file=sys.stderr,
            )
            return 1

    if not args.no_verify:
        _verify_after_install(args)
    return 0


def _verify_after_install(args: argparse.Namespace) -> None:
    """Prove the configured route answers, now that the service is running.

    A service that starts and then fails every request at 3am because a credential
    reference is wrong is the failure this catches. It reports; it never uninstalls —
    undoing an operator's install because one target was down would be the wrong call.
    """
    from . import Client

    config = _config(getattr(args, "config", None))
    targets = list(config.route.targets) if config.route else []
    if not config.providers or not targets:
        print("verify     skipped — the configuration names no route to check")
        return

    client = Client(list(config.providers))
    try:
        results = [client.verify(target, timeout_s=30.0) for target in targets]
    except AnyInferError as exc:
        print(f"verify     could not run: {exc.detail}")
        return
    finally:
        client.close()

    for result in results:
        mark = "ok" if result.ok else "FAILED"
        print(f"verify     {mark:<7} {result.target}  {result.detail or ''}".rstrip())
    if not all(result.ok for result in results):
        print(
            "the service is installed and running, but a configured target did not "
            "answer — fix it and the service will pick it up on its next request"
        )


def _serve_uninstall(args: argparse.Namespace) -> int:
    """Deregister the service and remove whatever install wrote.

    Returns:
        A process exit code.
    """
    from .serve.service import render_service

    definition = render_service(_service_request(args))
    paths = [definition.path]
    if definition.environment_path is not None:
        paths.append(definition.environment_path)
    existing = [path for path in paths if Path(path).exists()]

    print(f"path       {definition.path}" + ("" if existing else "   (not present)"))
    for command in definition.uninstall_commands:
        print(f"uninstall  {' '.join(command)}")
    if definition.needs_elevation:
        print("\nrun the commands above as root; this command will not elevate for you")
        return 0
    if not _confirm("\nderegister the service and delete its definition?", args):
        print("nothing removed")
        return 0

    for command in definition.uninstall_commands:
        code, output = _run_command(command)
        print(f"ran        {' '.join(command)}" + ("" if code == 0 else f"  (exit {code})"))
        if output:
            for line in output.splitlines():
                print(f"           {line}")

    for path in paths:
        target = Path(path)
        if target.exists():
            target.unlink()
            print(f"removed    {target}")
    return 0


def _serve_status(args: argparse.Namespace) -> int:
    """Report what exists and what the platform's manager says. Read-only.

    Returns:
        ``0`` when a definition is installed, ``1`` when none is.
    """
    from .serve.service import render_service

    definition = render_service(_service_request(args))
    installed = Path(definition.path).exists()
    print(f"definition {definition.path}")
    print(f"installed  {'yes' if installed else 'no'}")
    if definition.environment_path is not None and Path(definition.environment_path).exists():
        print(f"env file   {definition.environment_path}  (present)")

    for command in definition.status_commands:
        code, output = _run_command(command)
        print(f"manager    {' '.join(command)}  (exit {code})")
        for line in output.splitlines():
            print(f"           {line}")
    return 0 if installed else 1


def _confirm(question: str, args: argparse.Namespace) -> bool:
    """Ask before acting, on a terminal, unless told not to."""
    if getattr(args, "yes", False) or not sys.stdin.isatty():
        return True
    return input(f"{question} [Y/n] ").strip().lower() in ("", "y", "yes")


# ---- run -----------------------------------------------------------------------------


def _compare(args: argparse.Namespace) -> int:
    """Compare a request across targets without dispatching it."""
    from . import Client, Repair, Sampling, SchemaSpec
    from .types.requests import CachePolicy

    messages = _compose_messages(args)
    if not messages:
        print(
            "nothing to compare: give a prompt, pipe one on stdin, or pass --messages",
            file=sys.stderr,
        )
        return 2
    schema = (
        SchemaSpec(_read_json(args.schema, "schema"), name=args.schema.stem)
        if args.schema is not None
        else None
    )
    tools = tuple(_load_tool(path) for path in args.tool)
    if args.tool_choice != "auto" and not tools:
        print("--tool-choice needs at least one --tool", file=sys.stderr)
        return 2
    sampling = None
    if (
        any(value is not None for value in (args.temperature, args.top_p, args.max_tokens))
        or args.stop
    ):
        sampling = Sampling(
            temperature=args.temperature,
            top_p=args.top_p,
            max_output_tokens=args.max_tokens,
            stop=tuple(args.stop),
        )

    config = _config(args.config)
    if not config.providers:
        print("no providers configured: pass --config with a 'providers' list", file=sys.stderr)
        return 2
    context_request = _cli_context_request(args, config)
    if context_request is False:
        return 2
    client = Client(
        list(config.providers),
        route=config.route,
        repair=Repair(max_attempts=args.repair) if args.repair is not None else None,
        history=config.history,
        cache=config.cache,
    )
    try:
        comparisons = client.compare(
            messages,
            targets=tuple(args.target),
            schema=schema,
            tools=tools,
            tool_choice=args.tool_choice,
            sampling=sampling,
            reasoning=args.reasoning,
            timeout_s=args.timeout,
            cache=CachePolicy(mode=args.cache) if args.cache else None,
            context=context_request,
            refresh=args.refresh,
        )
    finally:
        client.close()

    if args.json:
        print(json.dumps([item.to_dict() for item in comparisons], indent=2))
        return 0

    headings = ("target", "resolvable", "fits", "schema", "cache", "cost", "dropped")
    rows: list[tuple[str, ...]] = []
    for item in comparisons:
        cost = (
            f"{item.cost.low}-{item.cost.high} {item.cost.currency}"
            if item.cost is not None
            else "unknown"
        )
        rows.append(
            (
                item.requested,
                "yes" if item.resolvable else "NO",
                "unknown" if item.fits is None else ("yes" if item.fits else "NO"),
                item.structured_mechanism or "none",
                item.cache.mechanism if item.cache and item.cache.mechanism else "none",
                cost,
                ", ".join(drop.parameter for drop in item.dropped) or item.reason or "none",
            )
        )
    widths = [
        max(len(headings[index]), *(len(row[index]) for row in rows))
        for index in range(len(headings))
    ]
    print("  ".join(name.ljust(widths[index]) for index, name in enumerate(headings)))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
    return 0


def _run(args: argparse.Namespace) -> int:
    """Run a single prompt and print the result.

    Returns:
        A process exit code.
    """
    from . import ArenaPolicy, Client, Repair, Route, Sampling, SchemaSpec

    messages = _compose_messages(args)
    if not messages:
        print(
            "nothing to do: give a prompt argument, pipe one on stdin, or pass --messages",
            file=sys.stderr,
        )
        return 2

    schema = None
    if args.schema is not None:
        schema = SchemaSpec(_read_json(args.schema, "schema"), name=args.schema.stem)

    tools = tuple(_load_tool(path) for path in args.tool)
    if args.tool_choice != "auto" and not tools:
        print("--tool-choice needs at least one --tool", file=sys.stderr)
        return 2

    sampling = None
    if (
        any(value is not None for value in (args.temperature, args.top_p, args.max_tokens))
        or args.stop
    ):
        sampling = Sampling(
            temperature=args.temperature,
            top_p=args.top_p,
            max_output_tokens=args.max_tokens,
            stop=tuple(args.stop),
        )

    config = _config(args.config)
    settings, configured_route = list(config.providers), config.route
    route = Route(targets=tuple(args.route)) if args.route else configured_route
    # An explicit --target and a --route are mutually exclusive at the call site; --route
    # wins because naming an ordered fallback list is the more specific instruction.
    target = None if args.route else args.target
    if args.arena_targets and args.arena_name:
        print("--arena and --arena-name are mutually exclusive", file=sys.stderr)
        return 2
    arena_policy = None
    if args.arena_name:
        arena_policy = config.arenas.get(args.arena_name)
        if arena_policy is None:
            print(f"unknown configured arena {args.arena_name!r}", file=sys.stderr)
            return 2
    elif args.arena_targets:
        targets = tuple(item.strip() for item in args.arena_targets.split(",") if item.strip())
        values = {
            "targets": targets,
            "strategy": args.arena_strategy or "first_valid",
            "judge_target": args.arena_judge_target,
            "instructions": args.arena_instructions,
            "concurrency": args.arena_concurrency or 4,
            "min_candidates": args.arena_min_candidates or 1,
            "reveal_targets": bool(args.arena_reveal_targets),
            "memoize_tools": args.arena_memoize_tools or "read_only",
        }
        try:
            arena_policy = ArenaPolicy(**values)
        except ValueError as exc:
            print(f"invalid arena: {exc}", file=sys.stderr)
            return 2

    if not settings:
        print(
            "no providers configured: pass --config pointing at a JSON file with a "
            "'providers' list (see `anyinfer providers` for what each one needs)",
            file=sys.stderr,
        )
        return 2

    effective_arena = arena_policy or (config.arena if target is None and not args.route else None)
    context_request = _cli_context_request(args, config)
    if context_request is False:
        return 2
    client = Client(
        settings,
        route=route,
        repair=Repair(max_attempts=args.repair) if args.repair is not None else None,
        history=config.history,
        cache=config.cache,
        arena=config.arena,
        arenas=config.arenas,
    )
    call: dict[str, Any] = {
        "target": target,
        "route": route if args.route else None,
        "schema": schema,
        "tools": tools,
        "tool_choice": args.tool_choice,
        "sampling": sampling,
        "reasoning": args.reasoning,
        "timeout_s": args.timeout,
        "arena": effective_arena,
        "context": context_request,
    }
    if args.cache:
        # A flag overrides the configured policy for this one invocation; without either,
        # nothing is cached, which is the library's default and the shell's expectation.
        from .types.requests import CachePolicy

        call["cache"] = CachePolicy(mode=args.cache)

    if args.dry_run:
        return _dry_run(client, messages, call, args)

    # Streaming is the default because a one-off run is something a human watches; --json
    # and --schema force the buffered path, since neither can be emitted incrementally.
    streaming = not (args.no_stream or args.json or schema is not None)
    try:
        if streaming:
            generation = _run_streaming(client, messages, call, args)
        else:
            generation = client.generate(messages, **call)
    except AnyInferError as exc:
        return _report_error(exc)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    finally:
        client.close()

    return _emit_result(generation, args, streamed=streaming)


def _embed(args: argparse.Namespace) -> int:
    """Embed one or more texts and print the resulting vectors.

    Collection is the CLI's job — the core receives text, never a path to open. Terminal
    output never dumps raw vector floats unless the caller asked for `--json`, since a
    printed 1536-float vector is not something a human reads.

    Returns:
        A process exit code.
    """
    from . import Client, Route

    inputs = _collect_embed_inputs(args)
    if inputs is None:
        return 2
    if not inputs:
        print(
            "nothing to embed: give a text argument, --file, --jsonl, or pipe on stdin",
            file=sys.stderr,
        )
        return 2

    config = _config(args.config)
    settings, configured_route = list(config.providers), config.route
    route = Route(targets=tuple(args.route)) if args.route else configured_route
    target = None if args.route else args.target
    if not settings:
        print(
            "no providers configured: pass --config pointing at a JSON file with a "
            "'providers' list (see `anyinfer providers` for what each one needs)",
            file=sys.stderr,
        )
        return 2

    client = Client(settings, route=route)
    try:
        result = client.embed(
            inputs,
            target=target,
            route=route if args.route else None,
            input_type=args.input_type,
            dimensions=args.dimensions,
            timeout_s=args.timeout,
            manifest=True if (args.trace or args.trace_json is not None) else None,
        )
    except AnyInferError as exc:
        return _report_error(exc)
    finally:
        client.close()

    _emit_trace(result, args)
    return _emit_embed_result(result, args)


def _collect_embed_inputs(args: argparse.Namespace) -> list[str] | None:
    """Assemble embedding inputs from the positional text, --file, --jsonl, or stdin.

    Returns ``None`` on a usage error (already reported), an empty list when nothing was
    given at all, or the collected texts otherwise.
    """
    sources = [
        value
        for value in (args.text, args.file, args.jsonl)
        if value not in (None, "")
    ]
    if len(sources) > 1:
        print("give at most one of: text argument, --file, --jsonl", file=sys.stderr)
        return None

    if args.text:
        return [args.text]
    if args.file is not None:
        try:
            lines = args.file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            print(f"cannot read {args.file}: {exc}", file=sys.stderr)
            return None
        return [line for line in lines if line.strip()]
    if args.jsonl is not None:
        return _read_jsonl_field(args.jsonl, "text")

    if not sys.stdin.isatty():
        piped = sys.stdin.read()
        return [line for line in piped.splitlines() if line.strip()]
    return []


def _read_jsonl_field(path: Path, field: str) -> list[str] | None:
    """Read one JSON object per line, collecting a required string field from each."""
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        return None
    values: list[str] = []
    for lineno, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError as exc:
            print(f"{path}:{lineno}: invalid JSON: {exc}", file=sys.stderr)
            return None
        if not isinstance(entry, dict) or field not in entry:
            print(f"{path}:{lineno}: missing required field {field!r}", file=sys.stderr)
            return None
        values.append(str(entry[field]))
    return values


def _emit_embed_result(result: Any, args: argparse.Namespace) -> int:
    """Print an `EmbeddingResult`, respecting the `--json`/`--out` output contract."""
    if args.json or args.out is not None:
        payload = {
            "target": str(result.target),
            "space": {
                "provider_id": result.space.provider_id,
                "model": result.space.model,
                "dimensions": result.space.dimensions,
                "normalized": result.space.normalized,
            },
            "vectors": [list(v.values) for v in result.vectors],
            "usage": {
                "input_tokens": result.usage.input_tokens,
                "total_tokens": result.usage.total_tokens,
            },
            "timing_ms": result.timing.total_ms,
            "warnings": list(result.warnings),
        }
        text = json.dumps(payload, indent=2)
        if args.out is not None:
            args.out.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return 0

    print(
        f"{len(result.vectors)} vector(s), {result.space.dimensions} dim, "
        f"target={result.target}",
        file=sys.stderr,
    )
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


def _rerank(args: argparse.Namespace) -> int:
    """Rank documents by relevance to a query and print them best-first.

    Returns:
        A process exit code.
    """
    from . import Client, Route

    documents = _collect_rerank_documents(args)
    if documents is None:
        return 2
    if not documents:
        print(
            "nothing to rank: give --document (repeatable), --file, --jsonl, or pipe on "
            "stdin",
            file=sys.stderr,
        )
        return 2

    config = _config(args.config)
    settings, configured_route = list(config.providers), config.route
    route = Route(targets=tuple(args.route)) if args.route else configured_route
    target = None if args.route else args.target
    if not settings:
        print(
            "no providers configured: pass --config pointing at a JSON file with a "
            "'providers' list (see `anyinfer providers` for what each one needs)",
            file=sys.stderr,
        )
        return 2

    client = Client(settings, route=route)
    try:
        result = client.rerank(
            args.query,
            documents,
            target=target,
            route=route if args.route else None,
            top_n=args.top_n,
            timeout_s=args.timeout,
            manifest=True if (args.trace or args.trace_json is not None) else None,
        )
    except AnyInferError as exc:
        return _report_error(exc)
    finally:
        client.close()

    _emit_trace(result, args)
    return _emit_rerank_result(result, args)


def _collect_rerank_documents(args: argparse.Namespace) -> list[Any] | None:
    """Assemble `RerankDocument`s from --document, --file, --jsonl, or stdin."""
    from . import RerankDocument

    sources = [bool(args.documents), args.file is not None, args.jsonl is not None]
    if sum(sources) > 1:
        print("give at most one of: --document, --file, --jsonl", file=sys.stderr)
        return None

    if args.documents:
        return [RerankDocument(id=str(i), text=t) for i, t in enumerate(args.documents)]
    if args.file is not None:
        try:
            lines = args.file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            print(f"cannot read {args.file}: {exc}", file=sys.stderr)
            return None
        return [
            RerankDocument(id=str(i), text=line)
            for i, line in enumerate(lines)
            if line.strip()
        ]
    if args.jsonl is not None:
        return _read_jsonl_documents(args.jsonl)

    if not sys.stdin.isatty():
        piped = sys.stdin.read()
        lines = [line for line in piped.splitlines() if line.strip()]
        return [RerankDocument(id=str(i), text=line) for i, line in enumerate(lines)]
    return []


def _read_jsonl_documents(path: Path) -> list[Any] | None:
    """Read one {'id', 'text'} object per line into `RerankDocument`s."""
    from . import RerankDocument

    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        return None
    documents: list[Any] = []
    for lineno, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError as exc:
            print(f"{path}:{lineno}: invalid JSON: {exc}", file=sys.stderr)
            return None
        if not isinstance(entry, dict) or "text" not in entry:
            print(f"{path}:{lineno}: missing required field 'text'", file=sys.stderr)
            return None
        doc_id = str(entry.get("id", lineno - 1))
        documents.append(RerankDocument(id=doc_id, text=str(entry["text"])))
    return documents


def _emit_rerank_result(result: Any, args: argparse.Namespace) -> int:
    """Print a `RerankResult`, respecting the `--json`/`--out` output contract."""
    if args.json or args.out is not None:
        payload = {
            "target": str(result.target),
            "items": [
                {"document_id": item.document_id, "score": item.score, "index": item.index}
                for item in result.items
            ],
            "usage": {
                "input_tokens": result.usage.input_tokens,
                "total_tokens": result.usage.total_tokens,
            },
            "timing_ms": result.timing.total_ms,
        }
        text = json.dumps(payload, indent=2)
        if args.out is not None:
            args.out.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return 0

    for rank, item in enumerate(result.items, start=1):
        print(f"{rank}. [{item.document_id}] {item.score:.4f}")
    return 0


def _dry_run(client: Any, messages: Any, call: dict[str, Any], args: argparse.Namespace) -> int:
    """Report the size, fit, and cost of a request without sending it.

    Answers the question a user asks *before* paying for a large prompt, using the same
    budget calculator the client uses at dispatch, so what this prints is what the real
    request would have been held to, not a second estimate of it.
    """
    arena = call.get("arena")
    if arena is not None:
        try:
            rows = client.compare(
                messages,
                targets=arena.targets,
                schema=call["schema"],
                tools=call["tools"],
                sampling=call["sampling"],
            )
        except AnyInferError as exc:
            return _report_error(exc)
        finally:
            client.close()
        costs = [row.cost for row in rows]
        known = all(cost is not None for cost in costs)
        low = sum((cost.low for cost in costs if cost is not None), start=Decimal(0))
        high = sum((cost.high for cost in costs if cost is not None), start=Decimal(0))
        call_ceiling = len(arena.targets) + (1 if arena.strategy in ("judge", "synthesize") else 0)
        arena_payload = {
            "arena_targets": list(arena.targets),
            "strategy": arena.strategy,
            "call_ceiling": call_ceiling,
            "estimated_cost": (
                {"low": str(low), "high": str(high), "currency": "USD"} if known else None
            ),
            "fits": [row.fits for row in rows],
        }
        if args.json:
            print(json.dumps(arena_payload, indent=2))
        else:
            print(f"arena targets      {len(arena.targets)}")
            print(f"call ceiling       {call_ceiling}")
            if known:
                print(f"summed cost        {low}-{high} USD")
            else:
                print("summed cost        unknown — at least one target is unpriced")
        return 0

    target = call["target"] or (call["route"].targets[0] if call["route"] else None)
    if target is None:
        print(
            "--dry-run needs a target: pass --target, or --route, or configure a route",
            file=sys.stderr,
        )
        return 2

    try:
        budget = client.budget(
            messages,
            target=target,
            schema=call["schema"],
            tools=call["tools"],
            sampling=call["sampling"],
        )
        resolved = client.resolve(target)
    except AnyInferError as exc:
        return _report_error(exc)
    finally:
        client.close()

    estimate = budget.estimate
    payload: dict[str, Any] = {
        "target": str(resolved),
        "estimate": {
            "messages": estimate.messages.tokens,
            "tools": estimate.tools.tokens,
            "schema": estimate.schema.tokens,
            "envelope": estimate.envelope.tokens,
            "unpriced_parts": estimate.unpriced_parts,
            "total": estimate.tokens,
            "floor": estimate.floor,
        },
        "context_window": budget.context_window.value if budget.context_window else None,
        "provenance": budget.context_window.provenance if budget.context_window else None,
        "output_reserve_tokens": budget.output_reserve_tokens,
        "input_allowance_tokens": budget.input_allowance_tokens,
        "remaining_tokens": budget.remaining_tokens,
        "fits": budget.fits,
        "estimated_cost": (
            {
                "low": str(budget.estimated_cost.low),
                "high": str(budget.estimated_cost.high),
                "currency": budget.estimated_cost.currency,
            }
            if budget.estimated_cost is not None
            else None
        ),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"target            {resolved}")
    print(f"input estimate    {estimate.tokens} tokens (floor {estimate.floor})")
    if estimate.unpriced_parts:
        print(f"unpriced inputs   {estimate.unpriced_parts} (fit and cost remain unknown)")
    for name, value in (
        ("messages", estimate.messages.tokens),
        ("tools", estimate.tools.tokens),
        ("schema", estimate.schema.tokens),
        ("provider envelope", estimate.envelope.tokens),
    ):
        if value:
            print(f"  {name:<16} {value}")
    if budget.context_window is None:
        # Tri-state, not a guess: an unknown window makes every figure below unknowable.
        print("context window    unknown — no trustworthy figure for this model")
        print("fits              unknown")
        return 0
    print(f"context window    {budget.context_window.value} ({budget.context_window.provenance})")
    print(f"output reserve    {budget.output_reserve_tokens}")
    print(f"input allowance   {budget.input_allowance_tokens}")
    print(f"remaining         {budget.remaining_tokens}")
    print(f"fits              {'yes' if budget.fits else 'NO'}")
    cost = budget.estimated_cost
    if cost is not None:
        print(f"estimated cost    {cost.low}-{cost.high} {cost.currency}")
    else:
        print("estimated cost    unknown — no trustworthy pricing for this model")
    return 0


def _run_streaming(
    client: Any, messages: Any, call: dict[str, Any], args: argparse.Namespace
) -> Any:
    """Stream a reply to stdout as it arrives, returning the final generation."""
    from .types.events import ReasoningDelta, TextDelta

    with client.stream(messages, **call) as stream:
        for event in stream:
            if isinstance(event, TextDelta):
                sys.stdout.write(event.text)
                sys.stdout.flush()
            elif isinstance(event, ReasoningDelta) and args.show_reasoning:
                sys.stderr.write(event.text)
                sys.stderr.flush()
        # A reply that ends without a trailing newline would otherwise run into the shell
        # prompt; a reply that has one should not gain a second.
        if stream.result is not None and not stream.result.text.endswith("\n"):
            sys.stdout.write("\n")
        return stream.result


def _emit_result(generation: Any, args: argparse.Namespace, *, streamed: bool) -> int:
    """Print whatever the chosen output mode calls for.

    Returns:
        A process exit code.
    """
    if generation is None:
        print("the request produced no result", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(_result_payload(generation), indent=2))
    elif generation.structured is not None:
        print(json.dumps(generation.structured, indent=2))
    elif not streamed:
        print(generation.text)

    # Tool calls are the model asking the caller to do something. Reporting them on stderr
    # keeps stdout a clean text (or JSON) channel while still making them impossible to
    # miss; --json puts them in the payload instead.
    if generation.tool_calls and not args.json:
        for call in generation.tool_calls:
            print(
                f"tool call: {call.name}({json.dumps(call.arguments)})",
                file=sys.stderr,
            )

    for warning in generation.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if args.stats and not args.json:
        _print_stats(generation)
    _emit_trace(generation, args)
    return 0


def _emit_trace(generation: Any, args: argparse.Namespace) -> None:
    """Print the run manifest, in whichever spellings were asked for.

    The human tree goes to stderr so it never contaminates the reply on stdout; the JSON
    goes to stdout only when no path was given, which is the one case a caller is clearly
    asking for it as the output.
    """
    from .manifest import render

    manifest = getattr(generation, "manifest", None)
    if manifest is None:
        return
    if getattr(args, "trace", False):
        print(render(manifest), file=sys.stderr)
    destination = getattr(args, "trace_json", None)
    if destination is None:
        return
    payload = manifest.to_json()
    if destination == "-":
        print(payload)
    else:
        Path(destination).write_text(payload + "\n", encoding="utf-8")


def _result_payload(generation: Any) -> dict[str, Any]:
    """Build the ``--json`` object."""
    usage, timing = generation.usage, generation.timing
    payload = {
        "text": generation.text,
        "structured": generation.structured,
        "target": str(generation.target) if generation.target else None,
        "finish_reason": generation.finish_reason,
        "tool_calls": [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in generation.tool_calls
        ],
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "cost_usd": usage.cost_usd,
        },
        "timing": {
            "first_token_ms": timing.first_token_ms,
            "total_ms": timing.total_ms,
            "output_tokens_per_s": timing.output_tokens_per_s,
        },
        "warnings": list(generation.warnings),
    }
    if generation.arena is not None:
        from .arena import arena_to_dict

        payload["arena"] = arena_to_dict(generation.arena)
    return payload


def _print_stats(generation: Any) -> None:
    """Write timing, token, and cost figures to stderr."""
    usage, timing = generation.usage, generation.timing
    print(f"\ntarget            {generation.target or 'unknown'}", file=sys.stderr)
    print(f"finish            {generation.finish_reason}", file=sys.stderr)
    if timing.first_token_ms is not None:
        print(f"first token       {timing.first_token_ms:.0f} ms", file=sys.stderr)
    if timing.total_ms is not None:
        print(f"total            {timing.total_ms:.0f} ms", file=sys.stderr)
    if timing.output_tokens_per_s is not None:
        print(f"throughput        {timing.output_tokens_per_s:.1f} tok/s", file=sys.stderr)
    tokens = f"{usage.input_tokens or '?'} in / {usage.output_tokens or '?'} out"
    if usage.cache_read_tokens:
        tokens = f"{tokens} ({usage.cache_read_tokens} cached)"
    print(f"tokens            {tokens}", file=sys.stderr)
    if usage.cost_usd is not None:
        print(f"cost              ${usage.cost_usd:.6f}", file=sys.stderr)
    else:
        # Never print $0.00 for an unpriced call. A cost that reads as free when it is
        # merely unknown is the accounting mistake this library refuses to make, and the
        # terminal is where a user is most likely to believe it.
        print("cost              unknown (no trusted pricing)", file=sys.stderr)
    if generation.cache_mechanism:
        print(f"cache             {generation.cache_mechanism}", file=sys.stderr)
    if generation.arena is not None:
        print("\narena candidates", file=sys.stderr)
        print("target  cost  first-token  total  rounds  valid", file=sys.stderr)
        for candidate in generation.arena.candidates:
            result = candidate.generation
            cost = (
                f"${result.usage.cost_usd:.6f}"
                if result is not None and result.usage.cost_usd is not None
                else "unknown"
            )
            first = (
                f"{result.timing.first_token_ms:.0f}ms"
                if result is not None and result.timing.first_token_ms is not None
                else "unknown"
            )
            total = f"{candidate.elapsed_ms:.0f}ms"
            print(
                f"{candidate.target}  {cost}  {first}  {total}  "
                f"{candidate.rounds if candidate.rounds is not None else '-'}  "
                f"{candidate.valid if candidate.valid is not None else '-'}",
                file=sys.stderr,
            )


def _report_error(exc: Any) -> int:
    """Print a library error the way a CLI user needs to read it.

    Returns:
        A process exit code.
    """
    print(f"error: {getattr(exc, 'detail', str(exc))}", file=sys.stderr)
    hint = getattr(exc, "hint", None)
    if hint:
        print(f"hint: {hint}", file=sys.stderr)
    return 1


def _compose_messages(args: argparse.Namespace) -> list[Any]:
    """Assemble the conversation from --messages, --system, the argument, and stdin."""
    from . import AudioPart, DocumentPart, ImagePart, Message, Text, system, user

    messages: list[Any] = []
    if args.messages is not None:
        raw = _read_json(args.messages, "messages")
        if not isinstance(raw, list):
            raise SystemExit(f"{args.messages} must contain a JSON list of messages")
        for entry in raw:
            if not isinstance(entry, dict) or "role" not in entry:
                raise SystemExit("each message needs a 'role' and 'content'")
            messages.append(
                Message(
                    role=str(entry["role"]),  # type: ignore[arg-type]
                    content=(Text(str(entry.get("content", ""))),),
                )
            )

    if args.system:
        messages.append(system(args.system))

    # Reading stdin only when it is not a TTY keeps an interactive `anyinfer run "hi"`
    # from hanging on a terminal that will never send EOF.
    piped = ""
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()

    parts = [part for part in (args.prompt, piped) if part]
    if parts:
        messages.append(user("\n\n".join(parts)))
    attachments: list[Any] = []
    for path in args.image:
        attachments.append(
            ImagePart(data=_read_attachment(path), media_type=_media_type(path, "image/png"))
        )
    for path in args.document:
        attachments.append(
            DocumentPart(
                data=_read_attachment(path),
                media_type=_media_type(path, "application/pdf"),
                filename=path.name,
            )
        )
    for path in args.audio:
        attachments.append(
            AudioPart(data=_read_attachment(path), media_type=_media_type(path, "audio/wav"))
        )
    if attachments:
        messages.append(Message(role="user", content=tuple(attachments)))
    return messages


def _read_attachment(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"could not read attachment {path}: {exc}") from exc


def _media_type(path: Path, default: str) -> str:
    return mimetypes.guess_type(path.name)[0] or default


def _cli_context_request(args: argparse.Namespace, config: AnyInferConfig) -> Any | Literal[False]:
    """Build one caller-approved context request identically for run and compare."""
    from . import ContextRequest

    if not args.context_file and not args.context_dir:
        return None
    documents = _collect_documents(
        argparse.Namespace(
            paths=[*args.context_file, *args.context_dir],
            pin=[str(path) for path in args.context_file],
            include_generated=False,
        )
    )
    if not documents:
        print("no readable context documents were found", file=sys.stderr)
        return False
    try:
        return ContextRequest(
            tuple(documents),
            query=args.context_query,
            strategy=args.context_strategy,
            max_tokens=args.context_max_tokens,
            placement=args.context_placement,
            tuning=config.context,
        )
    except ValueError as exc:
        print(f"invalid context request: {exc}", file=sys.stderr)
        return False


def _load_tool(path: Path) -> Any:
    """Read one tool declaration."""
    from . import ToolSpec

    data = _read_json(path, "tool")
    if not isinstance(data, dict) or "name" not in data:
        raise SystemExit(f"tool file {path} needs at least a 'name'")
    return ToolSpec(
        name=str(data["name"]),
        description=str(data.get("description", "")),
        parameters=data.get("parameters") or {"type": "object", "properties": {}},
    )


def _read_json(path: Path, label: str) -> Any:
    """Read a JSON file, failing with a message that names what was being loaded."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"cannot read {label} file {path}: {exc}") from exc
    except ValueError as exc:
        raise SystemExit(f"{label} file {path} is not valid JSON: {exc}") from exc


# ---- init ----------------------------------------------------------------------------


def _init(args: argparse.Namespace) -> int:
    """Discover what this machine can use, then write a configuration and a starter.

    The first command a new user should run, and the one that decides whether the first
    five minutes end in a working call or in the configuration reference.

    Returns:
        A process exit code.
    """
    import asyncio

    from . import default_registry
    from .config import AnyInferConfig
    from .local import detect, discover, endpoint_candidates

    config_path: Path = args.output
    starter_path = config_path.parent / _DEFAULT_STARTER_NAME
    if config_path.exists() and not args.force:
        # Refused before anything is probed: a command that is going to decline should
        # not spend two dozen connection attempts first.
        print(f"error: {config_path} already exists", file=sys.stderr)
        print(
            "hint: pass --force to replace it, or --output to write somewhere else",
            file=sys.stderr,
        )
        return 1

    profile = detect()
    probed = () if args.no_probe else endpoint_candidates(default_registry)
    found = asyncio.run(discover(default_registry, probe=not args.no_probe, keyring=args.keyring))
    settings, notes = _init_settings(found)
    target, recommendation = _init_target(settings, found, profile)
    route = _init_route(target, found)
    config = AnyInferConfig(providers=tuple(settings), route=route)

    if args.json:
        payload = {
            "hardware": profile.to_json(),
            "probed_endpoints": [group[0] for group in probed],
            "discovered": [
                {
                    "provider_id": entry.provider_id,
                    "evidence": entry.evidence,
                    "base_url": entry.base_url,
                    "detail": entry.detail,
                    "models": list(entry.models),
                    "credential_ref": entry.credential_ref,
                }
                for entry in found
            ],
            "recommendation": {
                "alias": recommendation.alias,
                "reason": recommendation.reason,
                "confident": recommendation.confident,
            },
            "target": target,
            "route": list(route.targets) if route else [],
            "notes": notes,
            "config_path": str(config_path),
            "starter_path": str(starter_path),
        }
        _write_init_files(config, config_path, starter_path, target, force=args.force)
        print(json.dumps(payload, indent=2))
        return 0

    _print_init_findings(profile, probed, found, recommendation, target, notes, args)
    if not _confirm_init(config_path, starter_path, args):
        print("nothing written")
        return 0
    _write_init_files(config, config_path, starter_path, target, force=args.force)

    print(f"\nwrote      {config_path}")
    print(f"wrote      {starter_path}")
    print(f"\nnext       python {starter_path}")
    print(f"           anyinfer verify --config {config_path}")
    # Said once, and nothing is edited: the generated file holds only credential
    # references, so it is safe to commit, and repo hygiene files belong to the user.
    print(
        f"\nnote       {config_path} holds only env:// references, never key material, "
        "so it is safe to commit"
    )
    return 0


def _init_settings(found: Any) -> tuple[list[Any], list[str]]:
    """Turn discovery evidence into provider settings, and note what it could not write.

    A provider whose endpoint is per-account cannot be configured from evidence alone —
    knowing a key exists says nothing about which tenant it belongs to, so it becomes a
    note rather than a half-written entry that fails at the first request.
    """
    from . import ProviderSettings, default_registry

    settings: list[Any] = []
    notes: list[str] = []
    for entry in found:
        descriptor = default_registry.get(entry.provider_id)
        base_url = entry.base_url if entry.evidence == "endpoint" else None
        if descriptor.requires_base_url and not base_url:
            notes.append(
                f"{entry.provider_id}: {entry.detail}, but this provider also needs a "
                f"base URL — add one to {_DEFAULT_CONFIG_NAME} and it becomes usable"
            )
            continue
        fields: dict[str, Any] = {}
        if base_url:
            fields["base_url"] = base_url
        if entry.credential_ref:
            # Well-known settings are their own field; anything else is an options entry,
            # which is exactly the split the configuration format already makes.
            if entry.credential_key in ("api_key", "api_version", "base_url"):
                fields[entry.credential_key] = entry.credential_ref
            else:
                fields["options"] = {entry.credential_key: entry.credential_ref}
        settings.append(ProviderSettings.of(entry.provider_id, **fields))
    return settings, notes


def _init_target(profile_settings: list[Any], found: Any, profile: Any) -> tuple[str, Any]:
    """Choose what the generated route and starter should point at.

    Preference order, and the reason for it: a catalog alias, because it keeps working
    when the machine changes; then a model that was actually *observed* on a running
    engine; then the alias again, unconfirmed, so the starter still has something to say.
    An alias is only kept when it does not contradict what discovery saw — an engine that
    listed four models and none of them is the alias's model would otherwise produce a
    configuration that fails on its first request.
    """
    from . import Client, load_default_catalog
    from .local import recommend_alias

    recommendation = recommend_alias(profile, load_default_catalog())
    observed = {e.provider_id: e.models for e in found if e.evidence == "endpoint"}
    alias = recommendation.alias

    resolved = None
    if alias and profile_settings:
        client = Client(profile_settings)
        try:
            resolved = client.resolve(alias)
        except AnyInferError:
            resolved = None
        finally:
            client.close()

    if resolved is not None:
        serves = observed.get(resolved.provider_id)
        if serves is None or resolved.model in serves:
            return alias or str(resolved), recommendation

    for entry in found:
        if entry.evidence == "endpoint" and entry.models:
            return f"{entry.provider_id}:{entry.models[0]}", recommendation
    return alias or "medium", recommendation


def _init_route(target: str, found: Any) -> Any:
    """The default route to write, or ``None`` when nothing was confirmed.

    A route is a claim that these targets work. With no evidence behind it there is
    nothing to claim, and an empty ``default_route`` is a more honest file than one
    naming a provider that was never found.
    """
    from .routing import Route

    return Route(targets=(target,)) if found else None


def _write_init_files(
    config: Any, config_path: Path, starter_path: Path, target: str, *, force: bool
) -> None:
    """Write the configuration and the starter program.

    Raises:
        ConfigError: If either file exists and ``force`` is false, or cannot be written.
    """
    from ._starter import render_starter
    from .config import dump_config

    dump_config(config, config_path, force=force)
    if starter_path.exists() and not force:
        raise ConfigError(
            f"{starter_path} already exists",
            hint="pass --force to replace it, or --output to write elsewhere",
        )
    source = render_starter(target=target, config_path=config_path.as_posix())
    try:
        starter_path.write_text(source, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            f"cannot write {starter_path}: {exc}",
            hint="check the directory exists and is writable",
        ) from exc


def _print_init_findings(
    profile: Any,
    probed: Any,
    found: Any,
    recommendation: Any,
    target: str,
    notes: list[str],
    args: argparse.Namespace,
) -> None:
    """Print what was detected, contacted, and found, in `_doctor`'s two-column style."""
    import textwrap

    accelerator = ""
    primary = profile.primary_accelerator
    if primary is not None:
        memory = "unified memory" if primary.unified_memory else _gib(primary.total_vram_bytes)
        accelerator = f", {primary.name or primary.kind} ({memory})"
    print(
        f"detected   {profile.os_name} / {profile.arch}, "
        f"{_gib(profile.total_ram_bytes)} RAM{accelerator}"
    )

    # Naming every address contacted is the point: touching loopback ports uninvited can
    # read as scanning, and the answer to that is a summary nobody has to take on trust.
    if args.no_probe:
        print("probed     nothing (--no-probe)")
    elif probed:
        addresses = ", ".join(group[0] for group in probed)
        print(f"probed     {len(probed)} loopback endpoint(s), every one a provider default:")
        for line in textwrap.wrap(addresses, width=88):
            print(f"           {line}")

    if not found:
        print("found      nothing usable yet")
    for entry in found:
        if entry.evidence == "endpoint":
            print(f"found      {entry.provider_id} at {entry.base_url} ({entry.detail})")
        else:
            # The reference rather than the prose, because the reference is literally
            # what lands in the file: what is shown here is what gets written there.
            print(f"found      {entry.provider_id}, credential {entry.credential_ref}")

    alias = recommendation.alias or "none"
    print(f"recommend  {alias}" if target == alias else f"recommend  {alias} -> {target}")
    if not recommendation.confident:
        print("           (low confidence — some hardware could not be detected)")
    for note in notes:
        print(f"note       {note}")
    if not found:
        print(
            "note       nothing to configure yet: start a local engine, set a provider's "
            "API key, or run 'anyinfer models add' to download one"
        )


def _confirm_init(config_path: Path, starter_path: Path, args: argparse.Namespace) -> bool:
    """Ask before writing, on a terminal, unless told not to.

    Two files appear in a directory the user did not name individually. On a terminal
    that is worth one question; in a script it is not, so a non-interactive run proceeds.
    """
    if args.yes or not sys.stdin.isatty():
        return True
    answer = input(f"\nwrite {config_path} and {starter_path}? [Y/n] ").strip().lower()
    return answer in ("", "y", "yes")


# ---- agents-md -------------------------------------------------------------------------


def _agents_md(args: argparse.Namespace) -> int:
    """Print the coding-agent instruction fragment, and write nothing.

    Printing rather than installing is deliberate: the library does not write into
    anybody's ``.claude/``, ``.agents/``, or ``.github/`` directory, and the user's own
    redirect is the confirmation step.

    Returns:
        A process exit code.
    """
    from ._agents_md import render_agents_md

    config = load_config(args.config) if args.config is not None else None
    print(render_agents_md(style=args.agents_format, config=config), end="")
    return 0


# ---- doctor --------------------------------------------------------------------------


def _configured_limits(config_path: Path | None) -> dict[str, str]:
    """Summarize each provider instance's configured pacing, keyed by instance id.

    Empty when no file was given or no instance asked for pacing, which is the ordinary
    case: limits are opt-in, and a report that invented a line for every provider would
    suggest bounds nobody set.
    """
    if config_path is None:
        return {}
    from .config import load_config

    summaries: dict[str, str] = {}
    for settings in load_config(config_path).providers:
        limits = settings.limits
        if limits is None or not limits.active:
            continue
        parts: list[str] = []
        if limits.max_concurrent is not None:
            parts.append(f"{limits.max_concurrent} concurrent")
        if limits.requests_per_minute is not None:
            parts.append(f"{limits.requests_per_minute:g}/min")
        if limits.min_interval_s > 0:
            parts.append(f"{limits.min_interval_s:g}s apart")
        if limits.respect_headers:
            reserve = (
                f", reserving {limits.reserve_fraction:.0%}" if limits.reserve_fraction else ""
            )
            parts.append(f"provider headers{reserve}")
        summaries[settings.instance_id] = ", ".join(parts)
    return summaries


def _doctor(args: argparse.Namespace) -> int:
    """Report detected hardware and the recommended tier."""
    from . import load_default_catalog
    from .local import detect, recommend_alias

    profile = detect()
    recommendation = recommend_alias(profile, load_default_catalog())
    limits = _configured_limits(getattr(args, "config", None))

    if args.json:
        print(
            json.dumps(
                {
                    "hardware": profile.to_json(),
                    "recommendation": {
                        "alias": recommendation.alias,
                        "reason": recommendation.reason,
                        "confident": recommendation.confident,
                    },
                    "rate_limits": limits,
                },
                indent=2,
            )
        )
        return 0

    print(f"platform          {profile.os_name} / {profile.arch}")
    print(f"cpu               {profile.cpu_name or 'unknown'}")
    print(
        f"cores             {profile.physical_cores or '?'} physical, "
        f"{profile.logical_cores or '?'} logical"
    )
    print(f"memory            {_gib(profile.total_ram_bytes)}")

    if profile.accelerators:
        for accelerator in profile.accelerators:
            memory = (
                "unified with system memory"
                if accelerator.unified_memory
                else _gib(accelerator.total_vram_bytes)
            )
            print(
                f"accelerator       {accelerator.kind}: {accelerator.name or 'unnamed'} ({memory})"
            )
    else:
        print("accelerator       none detected")

    print(f"\nrecommended tier  {recommendation.alias or 'none'}")
    print(f"                  {recommendation.reason}")
    if not recommendation.confident:
        print("                  (low confidence — some hardware could not be detected)")

    for warning in profile.warnings:
        print(f"warning           {warning}")

    # Pacing is invisible from the outside — a governed request just looks slow, so an
    # operator asking "why is this slow" should be able to see the bounds in one place.
    for instance_id, summary in limits.items():
        print(f"rate limit        {instance_id}: {summary}")

    # A provider plugin that failed to load is otherwise invisible: the provider simply
    # does not exist, and the only symptom is an "unknown provider" error listing every
    # provider except theirs. No section at all when every plugin loaded.
    from . import default_registry

    for issue in default_registry.plugin_issues():
        print(f"plugin            {issue.summary}")

    # A tier alias is a recommendation, not a configuration. Without this line the next
    # step is the configuration reference, which is the gap `init` exists to close.
    if getattr(args, "config", None) is None and not Path(_DEFAULT_CONFIG_NAME).exists():
        print(f"\nnext              anyinfer init   (writes this as {_DEFAULT_CONFIG_NAME})")
    return 0


# ---- verify --------------------------------------------------------------------------


def _verify(args: argparse.Namespace) -> int:
    """Send one tiny request to each named target and report what happened.

    Exits non-zero when any target failed, so it is usable as a setup gate in a script.
    """
    from . import Client

    config = _config(args.config)
    settings = list(config.providers)
    if not settings:
        print(
            "no providers configured: pass --config pointing at a JSON file with a "
            "'providers' list (see `anyinfer providers` for what each one needs)",
            file=sys.stderr,
        )
        return 2

    targets = [args.target] if args.target else list(config.route.targets if config.route else ())
    if not targets:
        print(
            "nothing to verify: name a target, or configure a route to check every target in it",
            file=sys.stderr,
        )
        return 2

    client = Client(settings)
    try:
        results = [client.verify(target, timeout_s=args.timeout) for target in targets]
    finally:
        client.close()

    if args.json:
        print(json.dumps([_verification_payload(r) for r in results], indent=2))
    else:
        for result in results:
            _print_verification(result)
    return 0 if all(result.ok for result in results) else 1


def _verification_payload(result: Any) -> dict[str, Any]:
    """Shape one verification as JSON."""
    return {
        "target": str(result.target) if result.target is not None else None,
        "ok": result.ok,
        "reached": result.reached,
        "latency_ms": round(result.latency_ms, 1),
        "detail": result.detail,
        "reply": result.reply,
        "mechanism": result.mechanism,
        "usage": {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
        },
        "diagnostics": [
            {"code": d.code, "severity": d.severity, "message": d.message}
            for d in result.diagnostics
        ],
    }


def _print_verification(result: Any) -> None:
    """Print one verification for a human."""
    mark = "ok" if result.ok else ("answered" if result.reached else "FAILED")
    print(f"{mark:<9} {result.target}")
    if result.ok:
        print(f"          {result.latency_ms:.0f} ms", end="")
        if result.mechanism:
            print(f", schema via {result.mechanism}", end="")
        print()
    if result.detail:
        print(f"          {result.detail}")
    for diagnostic in result.diagnostics:
        print(f"          {diagnostic.severity}: {diagnostic.message}")


def _benchmark(args: argparse.Namespace) -> int:
    """Measure one target and print what it does."""
    from . import BENCHMARK_OUTPUT_TOKENS, BENCHMARK_PROMPT_TOKENS, Client, MeasurementStore

    config = _config(args.config)
    settings = list(config.providers)
    if not settings:
        print(
            "no providers configured: pass --config pointing at a JSON file with a "
            "'providers' list (see `anyinfer providers` for what each one needs)",
            file=sys.stderr,
        )
        return 2

    client = Client(settings)
    try:
        measurement = client.benchmark(
            args.target,
            prompt_tokens=args.prompt_tokens or BENCHMARK_PROMPT_TOKENS,
            output_tokens=args.output_tokens or BENCHMARK_OUTPUT_TOKENS,
            store=MeasurementStore(args.store) if args.store else None,
        )
    finally:
        client.close()

    if args.json:
        print(json.dumps(measurement.to_json(), indent=2))
        return 0

    print(f"target            {measurement.identity.provider_id}:{measurement.identity.model}")
    print(f"prompt tokens     {measurement.input_tokens if measurement.input_tokens else '?'}")
    print(f"output tokens     {measurement.output_tokens if measurement.output_tokens else '?'}")
    if measurement.ttft_ms is not None:
        print(f"time to first     {measurement.ttft_ms:.0f} ms")
    print(f"total             {measurement.total_ms:.0f} ms")
    if measurement.prefill_tokens_per_s is not None:
        print(f"prefill           {measurement.prefill_tokens_per_s:.0f} tok/s")
    else:
        print("prefill           not reported by this provider")
    if measurement.decode_tokens_per_s is not None:
        print(f"decode            {measurement.decode_tokens_per_s:.1f} tok/s")
    if measurement.model_load_ms is not None:
        # The warmth signal: a figure here means this run paid a cold start, which is the
        # difference between a slow target and a target that was merely asleep.
        state = "cold start" if measurement.model_load_ms > 0 else "already resident"
        print(f"model load        {measurement.model_load_ms:.0f} ms ({state})")
    return 0


# ---- context -------------------------------------------------------------------------

_CONTEXT_MAX_FILE_BYTES = 2 * 1024 * 1024
"""Per-file ceiling for CLI collection. A file larger than this is a database, not source."""


def _agents_md_formats() -> tuple[str, ...]:
    """Instruction-fragment formats, read from the renderer so the two cannot drift."""
    from ._agents_md import AGENTS_MD_FORMATS

    return AGENTS_MD_FORMATS


def _context_strategies() -> tuple[str, ...]:
    """Strategy names, read from the library so the CLI cannot drift from it."""
    from .context import VALID_STRATEGIES

    return VALID_STRATEGIES


def _add_tuning_flags(parser: argparse.ArgumentParser) -> None:
    """Add one ``--context-<setting>`` flag per advanced setting.

    Generated from the dataclass rather than written out, so a setting added to
    `anyinfer.context.ContextTuning` reaches the config file, the CLI, and the Python
    keyword argument as one name with no third place to update.
    """
    import dataclasses

    from .context import ContextTuning

    group = parser.add_argument_group(
        "advanced context settings",
        "Override the 'context' block of the config file. Unset flags leave it alone.",
    )
    for field in dataclasses.fields(ContextTuning):
        flag = f"--context-{field.name.replace('_', '-')}"
        annotation = str(field.type)
        if "bool" in annotation:
            group.add_argument(
                flag,
                dest=f"context_{field.name}",
                action=argparse.BooleanOptionalAction,
                default=None,
            )
        elif "SelectionOrder" in annotation:
            from .context import SELECTION_ORDERS

            group.add_argument(
                flag, dest=f"context_{field.name}", choices=SELECTION_ORDERS, default=None
            )
        elif "int" in annotation:
            group.add_argument(flag, dest=f"context_{field.name}", type=int, default=None)
        else:
            group.add_argument(flag, dest=f"context_{field.name}", type=float, default=None)


def _resolve_tuning(args: argparse.Namespace, config: AnyInferConfig) -> Any:
    """Layer the settings: config file, then preset, then explicit flags."""
    import dataclasses

    from .context import ContextTuning

    tuning = config.context
    if args.preset == "recommended":
        tuning = ContextTuning.recommended()
    elif args.preset == "default":
        tuning = ContextTuning()

    overrides = {
        field.name: getattr(args, f"context_{field.name}", None)
        for field in dataclasses.fields(ContextTuning)
    }
    return tuning.merged(**overrides)


def _context(args: argparse.Namespace) -> int:
    """Reduce a collected corpus and print the envelope, or cost every strategy.

    Returns:
        A process exit code.
    """
    from .context import DEFAULT_MAX_BYTES, DEFAULT_MAX_DOCUMENTS, plan, select

    config = _config(args.config)
    try:
        tuning = _resolve_tuning(args, config)
    except ValueError as exc:
        print(f"invalid context setting: {exc}", file=sys.stderr)
        return 2

    documents = _collect_documents(args)
    if not documents:
        print("no readable text files were found in the given paths", file=sys.stderr)
        return 2

    budget = _context_budget(args, config)
    if budget is None:
        return 2

    common: dict[str, Any] = {
        "max_tokens": budget,
        "max_documents": args.max_documents or DEFAULT_MAX_DOCUMENTS,
        "max_bytes": args.max_bytes or DEFAULT_MAX_BYTES,
        "tuning": tuning,
    }

    if args.plan:
        outcome = plan(documents, args.query, **common)
        if args.as_json:
            print(json.dumps(outcome.metadata(), indent=2))
        else:
            _print_plan(outcome)
        return 0

    reduction = select(documents, args.query, strategy=args.strategy, **common)
    if args.as_json:
        print(json.dumps(reduction.metadata(), indent=2))
    else:
        # The envelope goes to stdout so it can be piped; the account goes to stderr so
        # piping it does not silently discard what was dropped.
        print(reduction.text)
        print(reduction.summary(), file=sys.stderr)
    return 0


def _context_budget(args: argparse.Namespace, config: AnyInferConfig) -> int | None:
    """Resolve the token budget, or explain why it could not be.

    An unknown context window stays unknown: the CLI will not invent one any more than
    the library will.
    """
    if args.max_tokens is not None:
        if args.max_tokens < 1:
            print("--max-tokens must be positive", file=sys.stderr)
            return None
        return int(args.max_tokens)

    if not args.target:
        print(
            "give a budget: pass --max-tokens, or --target to derive it from a model's "
            "context window",
            file=sys.stderr,
        )
        return None

    from . import Client

    with Client(list(config.providers), route=config.route) as client:
        computed = client.budget([], target=args.target)
    remaining = computed.remaining_tokens
    if remaining is None or remaining < 1:
        print(
            f"the context window of {args.target!r} is unknown, so there is no budget to "
            "reduce against; pass --max-tokens to choose one yourself",
            file=sys.stderr,
        )
        return None
    return remaining


def _collect_documents(args: argparse.Namespace) -> list[Any]:
    """Read the given paths into context documents.

    Collection lives here rather than in the library on purpose: walking a filesystem and
    deciding what is safe to send is application policy, and this command is an
    application. Unreadable, oversized, and non-text files are skipped silently, and
    vendored or generated paths are skipped unless asked for.
    """
    from .context import ContextDocument, is_generated_path

    pinned = {_posix(Path(value)) for value in args.pin}
    seen: dict[str, ContextDocument] = {}

    for root in args.paths:
        candidates = sorted(root.rglob("*")) if root.is_dir() else [root]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            relative = _posix(candidate)
            if relative in seen:
                continue
            if not args.include_generated and is_generated_path(relative):
                continue
            try:
                if candidate.stat().st_size > _CONTEXT_MAX_FILE_BYTES:
                    continue
                text = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if "\x00" in text:
                continue
            seen[relative] = ContextDocument.of(relative, text, pinned=relative in pinned)

    return [seen[path] for path in sorted(seen)]


def _posix(path: Path) -> str:
    """A stable POSIX-style path, relative to the working directory when it is below it."""
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _print_plan(outcome: Any) -> None:
    """Print the plan as a table."""
    best = outcome.best()
    print(f"corpus            {outcome.candidate_count} document(s)")
    print(f"budget            {outcome.max_tokens} tokens")
    print()
    print(f"{'strategy':<16}{'kept':>6}{'omitted':>9}{'tokens':>9}{'complete':>10}  limited by")
    for option in outcome.options:
        marker = "*" if best is not None and option.strategy == best.strategy else " "
        limits = ", ".join(option.binding_constraints) or "-"
        # A strategy that could not do what was asked reports what it did instead, the
        # same way `auto` does: `whole` on a corpus that does not fit becomes `ranked`.
        name = (
            option.strategy
            if option.representation == option.strategy
            else f"{option.strategy}>{option.representation}"
        )
        print(
            f"{marker}{name:<15}{option.selected_count:>6}"
            f"{option.omitted_count:>9}{option.estimated_tokens:>9}"
            f"{'yes' if option.complete else 'no':>10}  {limits}"
        )
    print()
    print(
        f"distill           {outcome.distill_chunks} chunk(s), "
        f"{outcome.distill_calls}+ generation call(s); the only strategy that spends money"
    )


def _providers(args: argparse.Namespace) -> int:
    """List every registered provider and what it needs to be configured."""
    from . import default_registry

    descriptors = list(default_registry)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": d.id,
                        "display_name": d.display_name,
                        "aliases": list(d.aliases),
                        "locality": d.locality,
                        "requires_base_url": d.requires_base_url,
                        "fields": [
                            {
                                "key": f.key,
                                "kind": f.kind,
                                "required": f.required,
                                # What a consuming application needs to prompt well: which
                                # fields to ask for, and what the rest already do.
                                "advanced": f.advanced,
                                "default": f.default_value,
                                # The variable this field conventionally comes from, so a
                                # config UI can say "we found this in your environment"
                                # without parsing the placeholder's prose for a name.
                                "env_var": f.env_var,
                            }
                            for f in d.setup.fields
                        ],
                    }
                    for d in descriptors
                ],
                indent=2,
            )
        )
        return 0

    for descriptor in descriptors:
        aliases = f" (aliases: {', '.join(descriptor.aliases)})" if descriptor.aliases else ""
        print(f"{descriptor.id:<16} {descriptor.display_name}{aliases}")
        setup = descriptor.setup
        required = [f.key for f in setup.fields if f.required]
        if required:
            print(f"{'':<16} requires: {', '.join(required)}")
        optional = [f.key for f in setup.essential_fields if not f.required]
        if optional:
            print(f"{'':<16} accepts:  {', '.join(optional)}")
        if setup.advanced_fields:
            print(f"{'':<16} standard: {', '.join(f.key for f in setup.advanced_fields)}")

    issues = default_registry.plugin_issues()
    if issues:
        print("\nprovider plugins that failed to load:")
        for issue in issues:
            print(f"  {issue.summary}")
    return 0


# ---- conform -------------------------------------------------------------------------


def _conform(args: argparse.Namespace) -> int:
    """Run the conformance suite against one adapter and report what it supports."""
    import asyncio

    from . import AsyncClient, default_registry
    from .providers.presets import COMPAT_PRESETS
    from .testing.certify import certify, load_declared_capabilities, render_report
    from .testing.conformance import matrix_row, results_to_json
    from .testing.scaffold import scaffold_provider

    if args.scaffold is not None:
        # Scaffolding names a provider that does not exist yet, so it runs before the
        # registry lookup rather than after it.
        written = scaffold_provider(args.provider, args.scaffold, force=args.force)
        for path in written:
            print(f"wrote  {path}")
        print(
            f"\nnext   pip install -e {args.scaffold}"
            f"\n       implement generate() in the adapter"
            f"\n       anyinfer conform {args.provider} --model <model>"
        )
        return 0

    if not args.model:
        raise ConfigError(
            "--model is required when running the suite",
            hint="name a model this provider serves, e.g. --model gpt-4o-mini",
        )

    provider_id = default_registry.resolve_alias(args.provider)

    # Presets are verified against their own record in contracts/openai-compat-presets.md.
    # Two paths to one answer is how two accounts of "what this preset supports" start
    # disagreeing, so this refuses rather than quietly producing an untracked matrix row.
    if any(provider_id == preset.id for preset in COMPAT_PRESETS):
        raise ConfigError(
            f"{provider_id!r} is an OpenAI-compatible preset, not a dedicated adapter",
            hint=(
                "presets are verified through the preset process recorded in "
                "contracts/openai-compat-presets.md; this command certifies adapters"
            ),
        )

    config = _config(args.config)
    supports = load_declared_capabilities(args.project)

    async def build_client(_scenario: str) -> AsyncClient:
        # A fresh client per case: the runner closes what it is given.
        return AsyncClient(
            list(config.providers),
            route=config.route,
            history=config.history,
            cache=config.cache,
        )

    results = asyncio.run(
        certify(
            provider_id,
            args.model,
            build_client,
            supports=supports,
            only=args.only or None,
        )
    )

    if args.json:
        print(results_to_json(provider_id, results))
    elif args.markdown_row:
        print(matrix_row(provider_id, results))
    else:
        print(render_report(provider_id, results))

    failed = any(not r.passed and not r.skipped for r in results)
    return 1 if failed else 0


def _mcp(args: argparse.Namespace) -> int:
    """Dispatch the ``mcp`` subcommands."""
    if args.mcp_command == "list":
        return _mcp_list(args)
    return 2


def _mcp_list(args: argparse.Namespace) -> int:
    """Connect to each configured MCP server and report what it exposes.

    Discovery only. The command-line runner never executes tools — requested calls are
    reported so a caller can run them, and connecting a tool source does not change that.
    What this answers is the question an operator actually has: is my server reachable, and
    what does it claim to offer?
    """
    import asyncio

    from .mcp import MCPToolset

    config = _config(args.config)
    servers = [s for s in config.mcp if not args.server or s.name == args.server]
    if not servers:
        print(
            "no MCP servers configured"
            if not config.mcp
            else f"no configured MCP server named {args.server!r}",
            file=sys.stderr,
        )
        return 1

    async def collect() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for server in servers:
            toolset = await MCPToolset.connect(server)
            try:
                rows.extend(
                    {
                        "server": server.name,
                        "name": tool.spec.name,
                        "description": tool.spec.description,
                        "read_only": tool.spec.annotations.read_only,
                        "destructive": tool.spec.annotations.destructive,
                    }
                    for tool in toolset.tools
                )
            finally:
                await toolset.aclose()
        return rows

    tools = asyncio.run(collect())

    if args.json:
        print(json.dumps(tools, indent=2))
        return 0

    if not tools:
        print("no tools exposed")
        return 0

    width = max(len(row["name"]) for row in tools)
    for row in tools:
        # Annotations are the server's own claims; shown as such, never acted on.
        claims = (("read-only", row["read_only"]), ("destructive", row["destructive"]))
        hints = [label for label, value in claims if value]
        suffix = f"  [{', '.join(hints)} — server's claim]" if hints else ""
        print(f"{row['name'].ljust(width)}  {row['description']}{suffix}")
    return 0


# ---- models --------------------------------------------------------------------------


def _models(args: argparse.Namespace) -> int:
    """Dispatch the ``models`` subcommands."""
    if args.models_command == "list":
        return _models_list(args)
    if args.models_command == "add":
        return _models_add(args)
    if args.models_command == "pull":
        return _models_pull(args)
    if args.models_command == "installed":
        return _models_installed(args)
    if args.models_command == "where":
        return _models_where(args)
    if args.models_command == "rm":
        return _models_remove(args)
    return 2


def _models_list(args: argparse.Namespace) -> int:
    """Browse the bundled catalog, annotated with how each entry fits this machine."""
    from ._client.models import build_catalog_view
    from .catalog import load_default_catalog

    view = build_catalog_view(
        load_default_catalog(), provider_id=args.provider, best_at=args.best_at
    )
    entries = view.entries if args.all else (view.runnable or view.entries)

    if args.json:
        print(
            json.dumps(
                {
                    "hardware_source": view.hardware_source,
                    "notes": list(view.notes),
                    "models": [
                        {
                            "id": e.model.id,
                            "name": e.model.name,
                            "parameter_size": e.model.parameter_size,
                            "quantization": e.model.quantization,
                            "license": e.model.license,
                            "best_at": list(e.model.best_at),
                            "channels": list(e.channels),
                            "download_bytes": e.model.est_file_bytes,
                            "fit": e.fit.level,
                            "reasons": list(e.fit.reasons),
                        }
                        for e in entries
                    ],
                },
                indent=2,
            )
        )
        return 0

    if not entries:
        print("no catalog models matched")
        return 0

    print(f"{'MODEL':<32} {'SIZE':>9}  {'FIT':<8} BEST AT")
    for entry in entries:
        tags = ", ".join(entry.model.best_at)
        print(
            f"{entry.model.id:<32} {_gib(entry.model.est_file_bytes):>9}  "
            f"{entry.fit.level:<8} {tags}"
        )
    for note in view.notes:
        print(f"\nnote  {note}")
    if not args.all and len(view.entries) != len(entries):
        hidden = len(view.entries) - len(entries)
        print(f"\n{hidden} model(s) that will not fit this machine were hidden; pass --all")
    return 0


def _models_add(args: argparse.Namespace) -> int:
    """Download a catalog model, showing aggregate progress."""
    from . import Client
    from .local import VariantPrefs

    prefs = VariantPrefs(allow_low_quality=args.allow_low_quality)
    with Client(use_default_catalog=True) as client:
        reporter = _ProgressPrinter()
        report = client.acquire_model(
            args.model,
            engine=args.engine,
            variant_id=args.variant,
            prefs=prefs,
            dry_run=args.dry_run,
            progress=None if args.dry_run else reporter,
        )
        reporter.finish()

    plan = report.plan
    total = _gib(plan.total_bytes)
    if report.dry_run:
        print(f"would acquire {plan.variant_id} ({plan.quantization}) — {total}")
        already = plan.already_have_bytes
        if already:
            print(f"  {_gib(already)} is already on disk and would not be re-transferred")
        print(f"  destination  {plan.directory}")
    elif report.cancelled:
        print(f"cancelled; {_gib(report.downloaded_bytes)} transferred and kept for resume")
        return 1
    elif report.reused:
        print(f"{plan.variant_id} was already downloaded and verified")
    else:
        print(f"downloaded {plan.variant_id} ({plan.quantization}) — {total}")
    for warning in report.warnings:
        print(f"  note  {warning}")
    return 0


class _ProgressPrinter:
    """Renders aggregate acquisition progress, with a plain fallback off a TTY."""

    def __init__(self) -> None:
        self._tty = sys.stderr.isatty()
        self._wrote = False

    def __call__(self, progress: Any) -> None:
        """Render one progress report."""
        if progress.phase == "done":
            return
        fraction = progress.fraction
        percent = f"{fraction:.0%}" if fraction is not None else "  ?"
        rate = (
            f" {progress.bytes_per_second / 1024**2:.1f} MiB/s"
            if progress.bytes_per_second
            else ""
        )
        eta = f" eta {progress.eta_seconds / 60:.0f}m" if progress.eta_seconds else ""
        line = (
            f"{percent} {_gib(progress.total_downloaded_bytes)} / "
            f"{_gib(progress.total_bytes)}{rate}{eta}"
            f"  [{progress.file_index}/{progress.file_count}] {progress.filename}"
        )
        if self._tty:
            print(f"\r{line:<100}", end="", file=sys.stderr, flush=True)
        elif progress.phase in ("planning", "verifying", "placing"):
            print(line, file=sys.stderr, flush=True)
        self._wrote = True

    def finish(self) -> None:
        """End the progress line, if one was started."""
        if self._wrote and self._tty:
            print(file=sys.stderr)


class _DownloadReporter:
    """Renders `DownloadProgress` telemetry, with a plain fallback off a TTY.

    An observer rather than a callback because a pull's progress arrives as ordinary
    telemetry — the same events any application observer already sees.
    """

    def __init__(self) -> None:
        self._tty = sys.stderr.isatty()
        self._wrote = False

    def on_event(self, event: Any) -> None:
        """Render one progress event, ignoring everything else."""
        if type(event).__name__ != "DownloadProgress" or event.done:
            return
        total = f" / {_gib(event.total_bytes)}" if event.total_bytes else ""
        line = f"{_gib(event.downloaded_bytes)}{total}  {event.phase}"
        if self._tty:
            print("\r" + f"{line:<80}", end="", file=sys.stderr, flush=True)
        else:
            print(line, file=sys.stderr, flush=True)
        self._wrote = True

    def finish(self) -> None:
        """End the progress line, if one was started."""
        if self._wrote and self._tty:
            print(file=sys.stderr)


def _models_pull(args: argparse.Namespace) -> int:
    """Ask an engine that keeps its own store to make a model available."""
    from . import Client

    config = _config(getattr(args, "config", None))
    settings = list(config.providers)
    if not settings:
        print(
            "no providers configured: pass --config pointing at a JSON file with a "
            "'providers' list",
            file=sys.stderr,
        )
        return 2

    reporter = _DownloadReporter()
    client = Client(settings, observers=[reporter])
    try:
        report = client.pull_model(args.provider, args.model)
    finally:
        client.close()
    reporter.finish()

    if report.already_present:
        print(f"{report.model} was already installed on {args.provider}")
    else:
        print(f"pulled {report.model} onto {args.provider} ({_gib(report.bytes_transferred)})")
    return 0


def _models_installed(args: argparse.Namespace) -> int:
    """List what has been downloaded into the model store."""
    from .local import ModelStore

    store = ModelStore()
    entries = store.list_installed()
    if args.json:
        print(json.dumps([e.to_json() for e in entries], indent=2))
        return 0
    if not entries:
        print(f"no models downloaded yet (store: {store.root})")
        return 0
    print(f"{'ENTRY':<44} {'SIZE':>9}  {'QUANT':<8} MODEL")
    for entry in entries:
        print(
            f"{entry.id:<44} {_gib(entry.total_bytes):>9}  "
            f"{entry.quantization or '-':<8} {entry.model_id}"
        )
    print(f"\nstore  {store.root}  ({_gib(store.disk_usage())} total)")
    return 0


def _models_where(args: argparse.Namespace) -> int:
    """Print the path an engine should be launched against."""
    from ._client.models import locate_catalog_model
    from .catalog import load_default_catalog
    from .local import ModelStore

    located = locate_catalog_model(
        load_default_catalog(), ModelStore(), args.model, verify=args.verify
    )
    if located is None:
        print(f"{args.model} is not downloaded", file=sys.stderr)
        return 1
    if args.json:
        print(
            json.dumps(
                {
                    "entry_id": located.entry_id,
                    "path": str(located.path),
                    "kind": located.kind,
                    "engine": located.engine,
                    "quantization": located.quantization,
                    "verified": located.verified,
                    "launch_hints": dict(located.launch_hints),
                    "warnings": list(located.warnings),
                },
                indent=2,
            )
        )
        return 0
    print(located.path)
    if not located.verified:
        print("warning  this model's files were stored without verification", file=sys.stderr)
    return 0


def _models_remove(args: argparse.Namespace) -> int:
    """Delete a downloaded model."""
    from .local import ModelStore

    report = ModelStore().remove(args.entry)
    if not report.removed:
        print(f"no store entry named {args.entry!r}", file=sys.stderr)
        return 1
    if report.external:
        print(f"unregistered {args.entry} (its files belong to another cache and were kept)")
    else:
        print(f"removed {args.entry}, freeing {_gib(report.freed_bytes)}")
    return 0


# ---- runtime -------------------------------------------------------------------------


def _runtime(args: argparse.Namespace) -> int:
    """Dispatch the ``runtime`` subcommands."""
    if args.runtime_command == "list":
        return _runtime_list()
    if args.runtime_command == "install":
        return _runtime_install(args)
    if args.runtime_command == "rm":
        return _runtime_remove(args)
    return 2


def _runtime_list() -> int:
    """Show which llama-server variants are installed and which could be."""
    from .local import detect, installed_runtimes, load_runtime_table, runtime_root
    from .local.runtimes import platform_key

    table = load_runtime_table()
    installed = {m.backend: m for m in installed_runtimes()}
    print(f"pinned build      {table.build}   ({platform_key()})")
    print(f"runtime root      {runtime_root()}\n")
    print(f"{'BACKEND':<10} {'SIZE':>9}  STATUS")
    for artifact in table.for_platform():
        manifest = installed.get(artifact.backend)
        if manifest is None:
            status = "not installed"
        elif manifest.build == table.build:
            status = f"installed at {manifest.directory}"
        else:
            status = f"installed but stale (build {manifest.build}) — reinstall"
        print(f"{artifact.backend:<10} {_gib(artifact.total_bytes):>9}  {status}")

    profile = detect()
    from .local import install_hint

    print(f"\nsuggested         {install_hint(profile, table)}")
    return 0


def _runtime_install(args: argparse.Namespace) -> int:
    """Fetch and unpack a runtime variant."""
    from .local import detect, install_runtime

    profile = detect()
    report = install_runtime(args.backend, hardware=profile, force=args.force)
    if report.reused:
        print(f"the {report.backend} runtime is already installed at {report.directory}")
    else:
        print(
            f"installed the {report.backend} runtime (build {report.build}) at {report.directory}"
        )
    print(f"executable        {report.executable}")
    for warning in report.warnings:
        print(f"warning           {warning}")
    return 0


def _runtime_remove(args: argparse.Namespace) -> int:
    """Delete a runtime variant."""
    from .local import remove_runtime

    if remove_runtime(args.backend):
        print(f"removed the {args.backend} runtime")
        return 0
    print(f"no {args.backend} runtime is installed", file=sys.stderr)
    return 1


def _gib(value: int | None) -> str:
    """Render a byte count in the unit that keeps it readable.

    Runtime archives are tens of megabytes and model weights are tens of gigabytes; a
    fixed unit renders one of them as ``0.0``.
    """
    if not value:
        return "unknown"
    if value < 1024**3:
        return f"{value / 1024**2:.0f} MiB"
    return f"{value / 1024**3:.1f} GiB"


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
