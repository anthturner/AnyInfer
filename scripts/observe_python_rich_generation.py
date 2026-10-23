"""Run the rich-generation corpus through the selected Python checkout.

This executable intentionally begins at the public domain boundary.  It never imports an
installed ``anyinfer``: the selected checkout source is asserted before the public import.
Its construction pass is useful on its own because invalid-media cases fail before a client
or manifest can exist; later execution phases extend this same literal compiler.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "python"
PROFILE = "rich-generation-v1"
FROZEN_CORPUS_SHA256 = "9cff7a50fbfd553ebcfed25186173579fff582796721d0e83cc656e116cc1777"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
from _rich_observation_python import require_python_source  # noqa: E402
from _rich_python_adapters import ScriptLedger  # noqa: E402
from _rich_python_execution import (  # noqa: E402
    _error_projection,
    _http_body,
    _result,
    _wire_request,
    execute_async,
    manifest_projection,
    telemetry_projection,
)

require_python_source(ROOT)
import anyinfer as ai  # noqa: E402

if not Path(ai.__file__ or "").resolve().is_relative_to(SOURCE.resolve()):
    raise RuntimeError(f"anyinfer was not imported from selected source: {ai.__file__}")


def _part(raw: dict[str, Any]) -> Any:
    kind = raw["type"]
    if kind == "text":
        return ai.Text(raw["text"])
    if kind == "tool_call":
        return ai.ToolCall(raw["id"], raw["name"], raw["arguments"])
    if kind == "tool_result":
        return ai.ToolResult(raw["call_id"], raw["content"], raw["is_error"])
    data = raw.get("data")
    if data is not None:
        if data.get("encoding") != "base64" or not isinstance(data.get("value"), str):
            raise ValueError("inline fixture data must be a base64 record")
        decoded = base64.b64decode(data["value"], validate=True)
    else:
        decoded = None
    if kind == "image":
        return ai.ImagePart(
            data=decoded,
            url=raw.get("url"),
            media_type=raw["media_type"],
            detail=raw.get("detail"),
        )
    if kind == "document":
        return ai.DocumentPart(
            data=decoded,
            url=raw.get("url"),
            media_type=raw["media_type"],
            filename=raw.get("filename"),
        )
    if kind == "audio":
        return ai.AudioPart(data=decoded, media_type=raw["media_type"])
    if kind == "video":
        return ai.VideoPart(
            data=decoded,
            url=raw.get("url"),
            media_type=raw["media_type"],
            start_offset_s=raw.get("start_offset_s"),
            end_offset_s=raw.get("end_offset_s"),
            fps=raw.get("fps"),
        )
    raise ValueError(f"unknown fixture part {kind!r}")


def _request(raw: dict[str, Any]) -> ai.GenerationRequest:
    messages = tuple(
        ai.Message(message["role"], tuple(_part(part) for part in message["content"]))
        for message in raw["messages"]
    )
    schema = raw.get("schema")
    if schema is not None:
        schema = ai.SchemaSpec(json_schema=schema["json_schema"], name=schema["name"])
    repair = raw.get("repair")
    if repair is not None:
        repair = ai.Repair(max_attempts=repair["max_attempts"])
    sampling = ai.Sampling(**raw.get("sampling", {}))
    tools = tuple(ai.ToolSpec(**item) for item in raw.get("tools", ()))
    server_tools = tuple(ai.ServerToolSpec(**item) for item in raw.get("server_tools", ()))
    reasoning = raw.get("reasoning")
    if isinstance(reasoning, dict):
        reasoning = ai.ReasoningEffort(**reasoning)
    return ai.GenerationRequest(
        messages=messages,
        schema=schema,
        tools=tools,
        tool_choice=raw.get("tool_choice", "auto"),
        sampling=sampling,
        reasoning=reasoning,
        timeout_s=raw.get("timeout_s"),
        max_response_bytes=raw.get("max_response_bytes", 1048576),
        max_input_part_bytes=raw["max_input_part_bytes"],
        max_input_bytes=raw["max_input_bytes"],
        repair=repair,
        provider_options=raw["provider_options"],
        metadata=raw["metadata"],
        logprobs=raw["logprobs"],
        cite_documents=raw["cite_documents"],
        server_tools=server_tools,
    )


def _error(error: Exception) -> dict[str, Any]:
    return {"type_name": type(error).__name__, "message": str(error)}


def admit_corpus(
    raw: bytes, *, expected_sha256: str = FROZEN_CORPUS_SHA256
) -> tuple[dict[str, Any], str]:
    """Verify frozen bytes before strict UTF-8/JSON decoding and profile admission."""
    corpus_sha256 = hashlib.sha256(raw).hexdigest()
    if corpus_sha256 != expected_sha256:
        raise ValueError("The rich-generation input is not the frozen corpus.")
    corpus = json.loads(raw.decode("utf-8", errors="strict"))
    if not isinstance(corpus, dict) or corpus.get("profile") != PROFILE:
        raise ValueError(f"Unexpected rich-generation profile; expected {PROFILE!r}.")
    return corpus, corpus_sha256


def observe(
    input_path: Path,
    output_path: Path,
    *,
    expected_sha256: str = FROZEN_CORPUS_SHA256,
) -> None:
    """Execute every literal case and write the closed observation document."""
    raw = input_path.read_bytes()
    corpus, corpus_sha256 = admit_corpus(raw, expected_sha256=expected_sha256)
    observations: list[dict[str, Any]] = []
    for case in corpus["cases"]:
        request = case["request"]
        built = None
        try:
            built = _request(request)
        except Exception as error:  # noqa: BLE001 - constructor result is the observation
            public = {
                "entry_point": "construct_request",
                "events": [],
                "result": None,
                "error": _error_projection(error),
            }
            observation = {
                "id": case["id"],
                "kind": case["kind"],
                "public": public,
                "wire": {"calls": []},
                "cleanup": [],
                "telemetry": {"events": [], "manifest": None},
            }
        else:
            if case["kind"] == "generation":
                ledger = ScriptLedger.from_case(case)
                try:
                    events, result, error, cleanup, telemetry = asyncio.run(
                        execute_async(case, built, ledger)
                    )
                    method = {
                        "async_stream": "async_stream",
                        "async_stream_close": "async_stream_close",
                        "async_stream_cancel": "async_stream_cancel",
                        "async_generate": "async_generate",
                        "sync_generate": "sync_generate",
                    }[case["procedure"]["name"]]
                    public = {
                        "entry_point": method,
                        "events": events,
                        "result": None if result is None else _result(result),
                        "error": _error_projection(error),
                    }
                    observation = {
                        "id": case["id"],
                        "kind": case["kind"],
                        "public": public,
                        "wire": {
                            "calls": (
                                [
                                    {
                                        "transport": "adapter",
                                        "provider": provider,
                                        "model": req.model,
                                        "request": _wire_request(req),
                                    }
                                    for provider, req in zip(
                                        ledger.wire_providers, ledger.wire_requests, strict=True
                                    )
                                ]
                                + [
                                    {
                                        "transport": "http",
                                        "provider": provider,
                                        "model": request.get("target", "").split(":", 1)[-1],
                                        "body": _http_body(body),
                                    }
                                    for provider, body in zip(
                                        ledger.http_providers, ledger.http_bodies, strict=True
                                    )
                                ]
                            )
                        },
                        "cleanup": cleanup,
                        "telemetry": {
                            "events": telemetry_projection(telemetry),
                            "manifest": manifest_projection(result) if result else None,
                        },
                    }
                except Exception:
                    # Projection, privacy, and ledger-integrity failures invalidate the
                    # observation. Never turn them into a fabricated empty SDK outcome.
                    raise
            else:
                public = {
                    "entry_point": "construct_request",
                    "events": [],
                    "result": None,
                    "error": None,
                }
                observation = {
                    "id": case["id"],
                    "kind": case["kind"],
                    "public": public,
                    "wire": {"calls": []},
                    "cleanup": [],
                    "telemetry": {"events": [], "manifest": None},
                }
        observations.append(observation)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "profile": corpus["profile"],
                "runtime": "python",
                "source_revision": revision,
                "source_dirty": dirty,
                "corpus_sha256": corpus_sha256,
                "observations": observations,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """Parse the observer command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--observe", nargs=2, metavar=("INPUTS", "OUTPUT"), required=True)
    args = parser.parse_args()
    observe(Path(args.observe[0]), Path(args.observe[1]))


if __name__ == "__main__":
    main()
