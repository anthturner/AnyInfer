"""The ``anyinfer`` command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .config import AnyInferConfig, load_config
from .errors import AnyInferError, ConfigError

__all__ = ["build_parser", "main"]

_DEFAULT_PORT = 8080
_LOOPBACK = "127.0.0.1"

_TOKEN_ENV = "ANYINFER_SERVE_TOKEN"
"""Bearer token source, so a token never has to appear in a process listing."""


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
    serve.add_argument("--host", default=_LOOPBACK, help="bind address (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=_DEFAULT_PORT, help="bind port")
    serve.add_argument(
        "--config", type=Path, help="JSON config file describing providers and routes"
    )
    serve.add_argument(
        "--token",
        default=None,
        help=f"bearer token clients must present (or set {_TOKEN_ENV})",
    )
    serve.add_argument(
        "--allow-remote-exposure",
        action="store_true",
        help="permit binding a non-loopback address; requires a token",
    )
    serve.add_argument(
        "--expose",
        action="append",
        default=[],
        metavar="TARGET",
        help="advertise a concrete provider:model target from /v1/models (repeatable)",
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

    doctor = subcommands.add_parser(
        "doctor", help="report detected hardware and the recommended local tier"
    )
    doctor.add_argument("--json", action="store_true", help="emit machine-readable output")

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
    bench.add_argument(
        "--prompt-tokens", type=int, default=None, help="approximate prompt size"
    )
    bench.add_argument(
        "--output-tokens", type=int, default=None, help="how many tokens to generate"
    )
    bench.add_argument(
        "--store", type=Path, help="record the measurement in this JSON file"
    )
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
    context.add_argument(
        "--target", help="derive the budget from this target's context window"
    )
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
        if args.command == "models":
            return _models(args)
        if args.command == "runtime":
            return _runtime(args)
        return 2
    except AnyInferError as exc:
        return _report_error(exc)


# ---- serve ---------------------------------------------------------------------------


def _serve(args: argparse.Namespace) -> int:
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
    client = AsyncClient(settings, route=route, history=config.history, cache=config.cache)
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


# ---- run -----------------------------------------------------------------------------


def _run(args: argparse.Namespace) -> int:
    """Run a single prompt and print the result.

    Returns:
        A process exit code.
    """
    from . import Client, Repair, Route, Sampling, SchemaSpec

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

    if not settings:
        print(
            "no providers configured: pass --config pointing at a JSON file with a "
            "'providers' list (see `anyinfer providers` for what each one needs)",
            file=sys.stderr,
        )
        return 2

    client = Client(
        settings,
        route=route,
        repair=Repair(max_attempts=args.repair) if args.repair is not None else None,
        history=config.history,
        cache=config.cache,
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


def _dry_run(
    client: Any, messages: Any, call: dict[str, Any], args: argparse.Namespace
) -> int:
    """Report the size, fit, and cost of a request without sending it.

    Answers the question a user asks *before* paying for a large prompt, using the same
    budget calculator the client uses at dispatch — so what this prints is what the real
    request would have been held to, not a second estimate of it.
    """
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
    print(
        f"context window    {budget.context_window.value} "
        f"({budget.context_window.provenance})"
    )
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
    return 0


def _result_payload(generation: Any) -> dict[str, Any]:
    """Build the ``--json`` object."""
    usage, timing = generation.usage, generation.timing
    return {
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
    print(f"tokens            {tokens}", file=sys.stderr)
    if usage.cost_usd is not None:
        print(f"cost              ${usage.cost_usd:.6f}", file=sys.stderr)


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
    from . import Message, Text, system, user

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
    return messages


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


# ---- doctor --------------------------------------------------------------------------


def _doctor(args: argparse.Namespace) -> int:
    """Report detected hardware and the recommended tier."""
    from . import load_default_catalog
    from .local import detect, recommend_alias

    profile = detect()
    recommendation = recommend_alias(profile, load_default_catalog())

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

    # A provider plugin that failed to load is otherwise invisible: the provider simply
    # does not exist, and the only symptom is an "unknown provider" error listing every
    # provider except theirs. No section at all when every plugin loaded.
    from . import default_registry

    for issue in default_registry.plugin_issues():
        print(f"plugin            {issue.summary}")
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
            "nothing to verify: name a target, or configure a route to check every "
            "target in it",
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
    return 0


# ---- context -------------------------------------------------------------------------

_CONTEXT_MAX_FILE_BYTES = 2 * 1024 * 1024
"""Per-file ceiling for CLI collection. A file larger than this is a database, not source."""


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
            seen[relative] = ContextDocument.of(
                relative, text, pinned=relative in pinned
            )

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
            print(
                f"{'':<16} standard: "
                f"{', '.join(f.key for f in setup.advanced_fields)}"
            )

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
            f"installed the {report.backend} runtime (build {report.build}) at "
            f"{report.directory}"
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
