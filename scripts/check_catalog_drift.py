"""Deterministic drift check for the bundled model catalog and runtime table.

The cheap, machine-readable half of the weekly catalog refresh. Three things move upstream
without telling us, and each is checked the only way it can be checked cheaply:

- **Pinned GGUF files** — a ``HEAD`` against the pinned revision URL. A 404 means the
  repository was renamed, gated, or force-pushed; a content-length mismatch means the file
  at that path is no longer the file we hashed.
- **Ollama tags** — tags are mutable by design, so the recorded manifest digest is compared
  against the registry's current one. A moved tag is drift, not an error.
- **llama-server runtime artifacts** — the same ``HEAD`` check, because a deleted release
  asset turns "install the runtime" into a dead end.

Stdlib only, so the check runs before any dependency is installed.

Exit codes: 0 no drift, 1 drift detected, 2 check could not run.
Writes ``drift=true|false`` to ``$GITHUB_OUTPUT`` when running in Actions.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_PATH = REPO_ROOT / "src" / "anyinfer" / "catalog" / "models.json"
RUNTIMES_PATH = REPO_ROOT / "src" / "anyinfer" / "local" / "runtimes.json"

HF_RESOLVE = "https://huggingface.co/{repo}/resolve/{revision}/{path}"
OLLAMA_MANIFEST = "https://registry.ollama.ai/v2/library/{name}/manifests/{tag}"

_USER_AGENT = "anyinfer-catalog-drift-check"
_TIMEOUT = 60
_MAX_FILES_PER_VARIANT = 1
"""Check the first shard of each variant.

A shard set is written by one build at one revision, so if the first shard is intact the
rest almost certainly are, and issuing forty requests per model to prove it would make the
weekly job slow enough that someone turns it off.
"""


def _head(url: str) -> tuple[int, int | None]:
    """Return ``(status, content_length)`` for a URL, following redirects."""
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            length = response.headers.get("content-length")
            return response.status, int(length) if length and length.isdigit() else None
    except urllib.error.HTTPError as error:
        return error.code, None


def _get_json(url: str, headers: dict[str, str] | None = None) -> tuple[int, Any, Any]:
    """Return ``(status, payload, headers)`` for a JSON GET."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return response.status, json.load(response), response.headers
    except urllib.error.HTTPError as error:
        return error.code, None, error.headers


def check_models(path: Path = MODELS_PATH) -> list[str]:
    """Compare every pinned model artifact and Ollama tag against upstream."""
    drift: list[str] = []
    document = json.loads(path.read_text(encoding="utf-8"))

    for model in document.get("models", []):
        model_id = model.get("id", "?")
        for variant in model.get("variants", []):
            source = variant.get("source") or {}
            if source.get("resolver") != "huggingface":
                continue
            repo = source.get("repo")
            revision = source.get("revision")
            sizes = source.get("size_bytes") or {}
            for name in list(source.get("files") or [])[:_MAX_FILES_PER_VARIANT]:
                url = HF_RESOLVE.format(repo=repo, revision=revision, path=name)
                status, length = _head(url)
                if status == 404:
                    drift.append(f"{model_id}/{variant.get('id')}: {name} is gone (404) at {url}")
                    continue
                if status in (401, 403):
                    drift.append(
                        f"{model_id}/{variant.get('id')}: {name} now requires authorization "
                        f"(HTTP {status}); the repository may have been gated"
                    )
                    continue
                if status >= 400:
                    drift.append(f"{model_id}/{variant.get('id')}: {name} returned HTTP {status}")
                    continue
                expected = sizes.get(name)
                if expected and length and length != expected:
                    drift.append(
                        f"{model_id}/{variant.get('id')}: {name} is {length} bytes upstream, "
                        f"but {expected} was pinned"
                    )

        ollama = (model.get("sources") or {}).get("ollama")
        if isinstance(ollama, dict) and ollama.get("digest"):
            drift.extend(_check_ollama_tag(model_id, ollama))

    return drift


def _check_ollama_tag(model_id: str, channel: dict[str, Any]) -> list[str]:
    """Compare a recorded Ollama manifest digest against the registry's current one."""
    tag = str(channel.get("tag", ""))
    name, _, version = tag.partition(":")
    url = OLLAMA_MANIFEST.format(name=name, tag=version or "latest")
    status, payload, headers = _get_json(
        url, {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
    )
    if status == 404:
        return [f"{model_id}: Ollama tag {tag} no longer exists"]
    if status >= 400:
        return [f"{model_id}: Ollama tag {tag} returned HTTP {status}"]

    current = headers.get("docker-content-digest") if headers else None
    if not current and isinstance(payload, dict):
        config = payload.get("config")
        if isinstance(config, dict):
            current = config.get("digest")
    if not current:
        return [f"{model_id}: could not read a digest for Ollama tag {tag}"]
    if str(current) != str(channel["digest"]):
        return [
            f"{model_id}: Ollama tag {tag} moved — pinned {channel['digest']}, "
            f"registry now serves {current}"
        ]
    return []


def check_runtimes(path: Path = RUNTIMES_PATH) -> list[str]:
    """Confirm every pinned llama-server artifact is still downloadable."""
    drift: list[str] = []
    document = json.loads(path.read_text(encoding="utf-8"))
    for variant in document.get("variants", []):
        where = f"{variant.get('platform')}/{variant.get('backend')}"
        for artifact in (variant, *variant.get("companions", [])):
            status, length = _head(str(artifact["url"]))
            if status >= 400:
                drift.append(
                    f"runtime {where}: {artifact['filename']} returned HTTP {status}; the "
                    f"pinned build {document.get('build')} may have been deleted"
                )
                continue
            expected = artifact.get("size_bytes")
            if expected and length and length != expected:
                drift.append(
                    f"runtime {where}: {artifact['filename']} is {length} bytes upstream, "
                    f"but {expected} was pinned"
                )
    return drift


def _write_github_output(drifted: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:  # noqa: PTH123
            handle.write(f"drift={'true' if drifted else 'false'}\n")


def main() -> int:
    """CLI entry point."""
    try:
        drift = check_models() + check_runtimes()
    except Exception as error:  # noqa: BLE001 — an unreachable host is a report, not a crash
        print(f"CHECK FAILED: {error}", file=sys.stderr)
        _write_github_output(False)
        return 2
    _write_github_output(bool(drift))
    if drift:
        print("Catalog drift detected:")
        for line in drift:
            print(f"  {line}")
        return 1
    print("No catalog drift: every pinned artifact and Ollama tag still matches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
