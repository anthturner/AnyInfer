"""Pinned local model artifacts.

These describe *files on disk* — a GGUF and its shards, with the hash and license that make
a download verifiable. They live in the local subsystem rather than the catalog because
they are what the downloader and the llama.cpp adapter operate on; the catalog merely
*references* them by id, keeping alias routing (core policy) separate from artifact
identity (local data).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..types.operations import EmbeddingCapabilities

__all__ = ["GgufArtifact", "GgufFile"]


@dataclass(frozen=True, slots=True)
class GgufFile:
    """One file of a (possibly sharded) GGUF artifact.

    Attributes:
        filename: The name the file is stored under in the model directory.
        url: Pinned download URL.
        sha256: Expected content hash. Empty means the file cannot be verified, and the
            downloader warns instead of checking.
        size_bytes: Expected size, when known; feeds download progress totals.
    """

    filename: str
    url: str
    sha256: str = ""
    size_bytes: int | None = None
    role: Literal["model", "projector"] = "model"


@dataclass(frozen=True, slots=True)
class GgufArtifact:
    """A pinned, verifiable local model artifact.

    Attributes:
        id: Stable artifact id, the handle alias targets and the llama.cpp adapter use.
        files: Every file the artifact comprises — one entry, or several for a sharded
            model.
        license: License id; checked against the download allowlist for
            application-supplied entries.
        description: Free text for display.
        parameter_size: Parameter class (``"7B"``), when known.
        quantization: Quantization of the shipped weights (``"Q4_K_M"``), when known.
        est_ram_bytes: Estimated memory needed on the CPU-only path.
        est_vram_bytes: Estimated memory needed when fully offloaded.
        embedding: Vector facts, when the artifact's weights are an embedding model
            rather than a chat model. Its presence is what marks the artifact as one
            `llama-server` must be started with ``--embeddings`` to serve.
    """

    id: str
    files: tuple[GgufFile, ...]
    license: str = ""
    description: str = ""
    parameter_size: str | None = None
    quantization: str | None = None
    est_ram_bytes: int | None = None
    est_vram_bytes: int | None = None
    embedding: EmbeddingCapabilities | None = None

    def __post_init__(self) -> None:
        """Require model weights first and at most one projector companion."""
        if not self.files or self.files[0].role != "model":
            raise ValueError("a GGUF artifact must begin with a model file")
        if sum(file.role == "projector" for file in self.files) > 1:
            raise ValueError("a GGUF artifact may contain at most one projector")

    @property
    def total_size_bytes(self) -> int | None:
        """Sum of every file's size, or ``None`` when any is unknown."""
        sizes = [f.size_bytes for f in self.files]
        if any(s is None for s in sizes):
            return None
        return sum(s for s in sizes if s is not None)

    @property
    def is_sharded(self) -> bool:
        """Whether this artifact spans multiple files."""
        return sum(file.role == "model" for file in self.files) > 1

    @property
    def projector(self) -> GgufFile | None:
        """Pinned multimodal projector file, when this model has one."""
        return next((file for file in self.files if file.role == "projector"), None)
