"""Validate the bundled local-model catalog and runtime table.

Gate for the catalog-refresh workflow and for CI. Both files must parse through the same
code path the library uses, and every entry must satisfy the rules that keep a bad merge
from shipping an unpinned model, an unvetted license, or a fabricated date.

Exit codes: 0 valid, 1 invalid (reasons on stderr).
"""

from __future__ import annotations

import datetime as _dt
import itertools
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = REPO_ROOT / "src" / "anyinfer" / "catalog"
MODELS_PATH = CATALOG_DIR / "models.json"
DEFAULT_PATH = CATALOG_DIR / "default.json"
RUNTIMES_PATH = REPO_ROOT / "src" / "anyinfer" / "local" / "runtimes.json"

sys.path.insert(0, str(REPO_ROOT / "src"))

from anyinfer.catalog.model import BEST_AT, MODEL_KINDS, Catalog  # noqa: E402
from anyinfer.local.downloads import license_allowed  # noqa: E402
from anyinfer.local.runtimes import load_runtime_table  # noqa: E402

_SHA256_LENGTH = 64
_COMMIT_LENGTH = 40


def validate_models(path: Path = MODELS_PATH) -> list[str]:
    """Check every logical model entry. An empty list means the file is valid."""
    problems: list[str] = []
    try:
        catalog = Catalog.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except Exception as error:  # noqa: BLE001 — report, don't crash the validator
        return [f"models.json does not parse: {error}"]

    if not catalog.models:
        return ["models.json defines no models"]

    today = _dt.date.today()
    for model_id, entry in sorted(catalog.models.items()):
        if not license_allowed(entry.license):
            problems.append(
                f"{model_id}: license {entry.license or 'unset'!r} is not in the allowlist"
            )
        for tag in entry.best_at:
            if tag not in BEST_AT:
                problems.append(f"{model_id}: unknown best_at category {tag!r}")
        if not entry.source.startswith("https://"):
            problems.append(f"{model_id}: source must be an https URL")
        try:
            verified = _dt.date.fromisoformat(entry.last_verified)
        except ValueError:
            problems.append(f"{model_id}: last_verified {entry.last_verified!r} is not ISO")
        else:
            if verified > today:
                problems.append(f"{model_id}: last_verified {verified} is in the future")

        if not entry.variants:
            problems.append(f"{model_id}: has no variants")
        if entry.est_ram_bytes and entry.est_file_bytes:
            if entry.est_ram_bytes < entry.est_file_bytes:
                problems.append(
                    f"{model_id}: est_ram_bytes is below est_file_bytes, which cannot be right"
                )
        else:
            problems.append(f"{model_id}: missing est_file_bytes or est_ram_bytes")

        if entry.kind not in MODEL_KINDS:
            problems.append(f"{model_id}: unknown kind {entry.kind!r}")
        problems.extend(_validate_embedding(model_id, entry))

        problems.extend(_validate_variants(model_id, entry))

        if entry.ollama is not None and not entry.ollama.digest:
            problems.append(
                f"{model_id}: Ollama tag {entry.ollama.tag} has no pinned digest, so a moved "
                "tag would be undetectable"
            )

    problems.extend(_validate_alias_targets(catalog))
    return problems


def _validate_embedding(model_id: str, entry: object) -> list[str]:
    """Check that an embedding row says the things an embedding row must say.

    Dimensions are the fact that makes a row useful: it is what the client reports when
    asked what a target produces, and what a caller compares before assuming two indexes
    live in the same space. A row without it is a download link wearing a schema.
    """
    problems: list[str] = []
    embedding = getattr(entry, "embedding", None)
    if getattr(entry, "kind", "generation") != "embedding":
        if embedding is not None:
            problems.append(f"{model_id}: carries embedding facts but is not kind 'embedding'")
        return problems

    if embedding is None:
        problems.append(f"{model_id}: kind is 'embedding' but no embedding facts are recorded")
        return problems
    if not embedding.dimensions:
        problems.append(f"{model_id}: embedding rows must record their vector dimensions")
    if not embedding.max_input_tokens:
        problems.append(f"{model_id}: embedding rows must record max_input_tokens")
    if "embeddings" not in getattr(entry, "best_at", ()):
        problems.append(
            f"{model_id}: an embedding row must carry the 'embeddings' category, or it is "
            "invisible to everyone browsing for one"
        )
    return problems


def _validate_variants(model_id: str, entry: object) -> list[str]:
    """Check that every variant is fully pinned and internally consistent."""
    problems: list[str] = []
    variants = getattr(entry, "variants", ())
    for variant in variants:
        where = f"{model_id}/{variant.id}"
        ref = variant.source
        if ref.resolver == "huggingface":
            if not ref.repo:
                problems.append(f"{where}: no repository")
            if not ref.revision or len(ref.revision) != _COMMIT_LENGTH:
                problems.append(
                    f"{where}: revision {ref.revision!r} is not a 40-character commit sha; "
                    "shipped data never pins a branch name"
                )
            if variant.kind == "gguf" and not ref.files:
                problems.append(f"{where}: a GGUF variant must name its shard set")
            for name in ref.files:
                digest = ref.digests.get(name, "")
                if len(digest) != _SHA256_LENGTH:
                    problems.append(f"{where}: {name} has no sha256")
                if not ref.sizes.get(name):
                    problems.append(f"{where}: {name} has no size")
        elif ref.resolver == "url":
            if not ref.urls:
                problems.append(f"{where}: a url variant needs urls")
        else:
            problems.append(f"{where}: unexpected resolver {ref.resolver!r} in shipped data")

        if not variant.est_file_bytes:
            problems.append(f"{where}: missing est_file_bytes")
        if (
            variant.est_ram_bytes
            and variant.est_file_bytes
            and variant.est_ram_bytes < variant.est_file_bytes
        ):
            problems.append(f"{where}: est_ram_bytes is below est_file_bytes")
        if not variant.quantization:
            problems.append(f"{where}: missing quantization")

    # A higher-quality rung cannot be smaller than a lower one. This catches the failure
    # mode where a repository's *auxiliary* GGUF — a vision projector, or a
    # speculative-decoding draft head — is matched as a quantization of the model, which
    # produces an entry claiming a 120B model is 800 MB.
    sized = [v for v in variants if v.kind == "gguf" and v.est_file_bytes]
    ordered = sorted(sized, key=lambda v: v.quality_rank)
    for lower, higher in itertools.pairwise(ordered):
        if (higher.est_file_bytes or 0) < (lower.est_file_bytes or 0):
            problems.append(
                f"{model_id}: {higher.quantization} is smaller than {lower.quantization}; "
                "one of these files is probably not the model"
            )
    return problems


def _validate_alias_targets(models: Catalog) -> list[str]:
    """Check that every bundled alias target still resolves to something that exists."""
    problems: list[str] = []
    try:
        merged = Catalog.from_files(DEFAULT_PATH, MODELS_PATH)
    except Exception as error:  # noqa: BLE001
        return [f"the bundled catalog does not merge: {error}"]

    embedding_artifacts = {
        variant.artifact_id
        for entry in merged.models.values()
        if entry.is_embedding
        for variant in entry.variants
        if variant.artifact_id
    }
    embedding_tags = {
        entry.ollama.tag for entry in merged.models.values() if entry.is_embedding and entry.ollama
    }

    for alias in merged.alias_names():
        for provider_id, target in merged.targets_for_alias(alias).items():
            if target.gguf and target.gguf not in merged.artifacts:
                problems.append(
                    f"alias {alias}/{provider_id} points at unknown artifact {target.gguf!r}"
                )
            # The tier ladder answers "how big a chat model should I run". An embedding
            # model has no answer to that question, so resolving `small` to one would hand
            # a caller who asked for a cheap chat model something that cannot chat at all.
            if target.gguf in embedding_artifacts or target.model in embedding_tags:
                problems.append(
                    f"alias {alias}/{provider_id} points at an embedding model; the "
                    "small/medium/large ladder is a generation-model ladder"
                )
    del models
    return problems


def validate_runtimes(path: Path = RUNTIMES_PATH) -> list[str]:
    """Check the pinned llama-server runtime table."""
    problems: list[str] = []
    try:
        table = load_runtime_table(path)
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001
        return [f"runtimes.json does not parse: {error}"]

    if not table.build:
        problems.append("runtimes.json records no build id")
    if not table.artifacts:
        problems.append("runtimes.json lists no variants")

    today = _dt.date.today()
    try:
        verified = _dt.date.fromisoformat(str(data.get("last_verified", "")))
    except ValueError:
        problems.append(f"runtimes.json last_verified {data.get('last_verified')!r} is not ISO")
    else:
        if verified > today:
            problems.append(f"runtimes.json last_verified {verified} is in the future")

    for artifact in table.artifacts:
        where = f"{artifact.platform}/{artifact.backend}"
        if len(artifact.sha256) != _SHA256_LENGTH:
            problems.append(f"{where}: no sha256")
        if not artifact.size_bytes:
            problems.append(f"{where}: no size")
        if not artifact.url.startswith("https://"):
            problems.append(f"{where}: url must be https")
        for companion in artifact.companions:
            if len(companion.sha256) != _SHA256_LENGTH:
                problems.append(f"{where}: companion {companion.filename} has no sha256")

    if table.min_compute_capability <= 0 or table.min_cuda_driver_major <= 0:
        problems.append(
            "runtimes.json must state the CUDA minimum driver and compute capability; "
            "without them the precondition gate cannot refuse an unsupported GPU"
        )
    return problems


def main() -> int:
    """CLI entry point."""
    problems = validate_models() + validate_runtimes()
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}", file=sys.stderr)
        return 1
    print("models.json, runtimes.json: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
