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
from .errors import AnyInferError

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
        "--stats",
        action="store_true",
        help="print timing, token, and cost figures to stderr when finished",
    )

    doctor = subcommands.add_parser(
        "doctor", help="report detected hardware and the recommended local tier"
    )
    doctor.add_argument("--json", action="store_true", help="emit machine-readable output")

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
        if args.command == "providers":
            return _providers(args)
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
    client = AsyncClient(settings, route=route)
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
    return 0


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
                            {"key": f.key, "kind": f.kind, "required": f.required}
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
        required = [f.key for f in descriptor.setup.fields if f.required]
        if required:
            print(f"{'':<16} requires: {', '.join(required)}")
    return 0


# ---- models --------------------------------------------------------------------------


def _models(args: argparse.Namespace) -> int:
    """Dispatch the ``models`` subcommands."""
    if args.models_command == "list":
        return _models_list(args)
    if args.models_command == "add":
        return _models_add(args)
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
