#!/usr/bin/env python3
"""Pin the downloadable ``llama-server`` runtime variants.

AnyInfer never bundles llama.cpp binaries — they are fetched at runtime — so the set of
fetchable builds is pinned data with the same discipline as the model catalog: a real build
tag, real asset URLs, real sha256 digests, real sizes, and a real ``last_verified`` date,
all read from the upstream GitHub release rather than typed by hand.

Writes ``src/anyinfer/local/runtimes.json``. Run from the repository root::

    python scripts/pin_runtimes.py                 # pin the latest release
    python scripts/pin_runtimes.py --tag b10327    # pin a specific build
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import httpx2

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "anyinfer" / "local" / "runtimes.json"

RELEASES = "https://api.github.com/repos/ggml-org/llama.cpp/releases"

# (platform key, backend) -> asset-name template. ``{tag}`` is the release tag.
ASSETS: Mapping[tuple[str, str], str] = {
    ("win32-amd64", "cpu"): "llama-{tag}-bin-win-cpu-x64.zip",
    ("win32-amd64", "vulkan"): "llama-{tag}-bin-win-vulkan-x64.zip",
    ("win32-amd64", "cuda"): "llama-{tag}-bin-win-cuda-13.3-x64.zip",
    ("win32-amd64", "rocm"): "llama-{tag}-bin-win-hip-radeon-x64.zip",
    ("win32-arm64", "cpu"): "llama-{tag}-bin-win-cpu-arm64.zip",
    ("darwin-arm64", "metal"): "llama-{tag}-bin-macos-arm64.tar.gz",
    ("darwin-amd64", "cpu"): "llama-{tag}-bin-macos-x64.tar.gz",
    ("linux-amd64", "cpu"): "llama-{tag}-bin-ubuntu-x64.tar.gz",
    ("linux-amd64", "vulkan"): "llama-{tag}-bin-ubuntu-vulkan-x64.tar.gz",
    ("linux-amd64", "rocm"): "llama-{tag}-bin-ubuntu-rocm-7.2-x64.tar.gz",
    ("linux-arm64", "cpu"): "llama-{tag}-bin-ubuntu-arm64.tar.gz",
    ("linux-arm64", "vulkan"): "llama-{tag}-bin-ubuntu-vulkan-arm64.tar.gz",
}

# Backends whose payload needs a second archive unpacked alongside it (the CUDA runtime
# libraries ship separately from the llama.cpp build on Windows).
COMPANIONS: Mapping[tuple[str, str], str] = {
    ("win32-amd64", "cuda"): "cudart-llama-bin-win-cuda-13.3-x64.zip",
}

# What the pinned CUDA build demands of the host. Bumping the CUDA version in ASSETS
# without revisiting these strands older GPUs silently, so they live next to each other.
CUDA_REQUIREMENTS = {
    "toolkit": "13.3",
    "min_driver_major": 580,
    "min_compute_capability": "7.5",
    "warn_below_vram_bytes": 6 * 1024**3,
}

_COMMENT = [
    "Pinned llama-server runtime variants, written by scripts/pin_runtimes.py from the",
    "upstream ggml-org/llama.cpp GitHub release. Never hand-edit a digest, size, or date.",
    "AnyInfer does not bundle these binaries (they are hundreds of megabytes for CUDA);",
    "install_runtime() fetches, verifies, and unpacks them into the runtime root.",
]


def fetch_release(client: httpx2.Client, tag: str | None) -> Mapping[str, Any]:
    """Fetch one release payload by tag, or the latest."""
    url = f"{RELEASES}/tags/{tag}" if tag else f"{RELEASES}/latest"
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.get(url, headers=headers)
    response.raise_for_status()
    payload: Mapping[str, Any] = response.json()
    return payload


def asset_index(release: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Index a release's assets by file name."""
    return {str(a["name"]): a for a in release.get("assets", []) if isinstance(a, Mapping)}


def digest_of(asset: Mapping[str, Any]) -> str | None:
    """Extract the sha256 from an asset's ``digest`` field."""
    raw = asset.get("digest")
    if isinstance(raw, str) and raw.startswith("sha256:") and len(raw) == 71:
        return raw.removeprefix("sha256:")
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Refresh the pinned runtime table."""
    parser = argparse.ArgumentParser(description="Pin llama-server runtime artifacts.")
    parser.add_argument("--tag", help="release tag to pin; default is the latest release")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    with httpx2.Client(follow_redirects=True, timeout=httpx2.Timeout(60.0)) as client:
        release = fetch_release(client, args.tag)

    tag = str(release["tag_name"])
    assets = asset_index(release)
    today = date.today().isoformat()

    variants: list[dict[str, Any]] = []
    for (platform_key, backend), template in sorted(ASSETS.items()):
        name = template.format(tag=tag)
        asset = assets.get(name)
        if asset is None:
            print(
                f"  skip  {platform_key}/{backend}: {name} not in release {tag}",
                file=sys.stderr,
            )
            continue
        digest = digest_of(asset)
        if digest is None:
            print(f"  skip  {platform_key}/{backend}: {name} has no sha256", file=sys.stderr)
            continue

        entry: dict[str, Any] = {
            "platform": platform_key,
            "backend": backend,
            "filename": name,
            "url": str(asset["browser_download_url"]),
            "sha256": digest,
            "size_bytes": int(asset["size"]),
        }

        companion_name = COMPANIONS.get((platform_key, backend))
        if companion_name:
            companion = assets.get(companion_name)
            companion_digest = digest_of(companion) if companion else None
            if companion is None or companion_digest is None:
                print(
                    f"  skip  {platform_key}/{backend}: companion {companion_name} unusable",
                    file=sys.stderr,
                )
                continue
            entry["companions"] = [
                {
                    "filename": companion_name,
                    "url": str(companion["browser_download_url"]),
                    "sha256": companion_digest,
                    "size_bytes": int(companion["size"]),
                }
            ]

        variants.append(entry)
        print(f"  pin   {platform_key}/{backend}  ({int(asset['size']) / 1024**2:.0f} MiB)")

    document = {
        "format_version": 1,
        "_comment": _COMMENT,
        "generated": today,
        "build": tag,
        "release_url": str(release["html_url"]),
        "last_verified": today,
        "cuda_requirements": CUDA_REQUIREMENTS,
        "variants": variants,
    }

    if args.dry_run:
        print(f"\ndry run: {len(variants)} variants for build {tag}")
        return 0
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {len(variants)} runtime variants for build {tag} to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
