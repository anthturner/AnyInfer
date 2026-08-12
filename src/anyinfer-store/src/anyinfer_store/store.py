"""A single-file, embedded, brute-force vector store.

**The one-sentence boundary this package commits to:** small-scale, single-process,
embedded persistence for personal/prototype-sized corpora — never a clustered, replicated,
or "production vector database" story. Documents numbering in the thousands to low
hundreds of thousands, at typical embedding dimensions (384-3072); one process, one
machine, one writer. When you outgrow this, point a real vector database at
`anyinfer.embed()`/`anyinfer.rerank()` directly — both consume the same public
`EmbeddingResult`/`RerankResult` types this package does, so nothing about your embedding
or reranking calls needs to change when you do.

Similarity search is brute-force cosine similarity, in pure Python, on purpose: at this
package's stated scale ceiling, an approximate index is complexity this package's own
design record (`plans/VECTOR_STORE_ADDON.md` §7) does not commit to paying for without
benchmark evidence it's needed. `SIZE_WARNING_THRESHOLD` is where this module starts
telling you, not guessing silently, that you may be past the point brute force stays fast.
"""

from __future__ import annotations

import array
import json
import math
import sqlite3
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import EmbeddingSpaceMismatchError, VectorStoreError

if TYPE_CHECKING:
    from anyinfer.types.operations import EmbeddingSpace

__all__ = ["SIZE_WARNING_THRESHOLD", "QueryResult", "VectorEntry", "VectorStore"]

SIZE_WARNING_THRESHOLD = 200_000
"""Entry count past which `VectorStore.add`/`add_many` warn that brute-force search may be
noticeably slow — a signal, not a hard limit; nothing stops working at this count."""


@dataclass(frozen=True, slots=True)
class VectorEntry:
    """One stored vector.

    Attributes:
        id: Caller-supplied identifier, unique within one store.
        vector: The embedding vector's components.
        metadata: Small caller-supplied key/value payload, exact-match filterable.
        text: The source text, when the caller chose to keep it — needed for a
            second-stage rerank pass (`anyinfer_store.query_and_rerank`), optional
            otherwise.
    """

    id: str
    vector: tuple[float, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)
    text: str | None = None


@dataclass(frozen=True, slots=True)
class QueryResult:
    """One ranked match from `VectorStore.query`.

    Attributes:
        entry: The matched entry.
        score: Cosine similarity to the query vector, in ``[-1.0, 1.0]``. Meaningful only
            within this store — never compared across stores or embedding spaces.
    """

    entry: VectorEntry
    score: float


class VectorStore:
    """A single SQLite file holding one embedding space's worth of vectors.

    Every entry in one store must share a compatible `anyinfer.EmbeddingSpace` — checked
    with `EmbeddingSpace.compatible_with`, the identical rule `anyinfer` core's own routing
    applies for a fallback target — so a query can never silently compare vectors that
    were never comparable to begin with. The space is fixed the first time an entry is
    added and stored permanently in the file; open the same file again later and it's
    already there, no re-declaration needed.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    @classmethod
    def open(cls, path: str | Path) -> VectorStore:
        """Open (creating if needed) a store at `path`."""
        connection = sqlite3.connect(str(path))
        connection.execute(
            "CREATE TABLE IF NOT EXISTS anyinfer_store_space ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), space_json TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS anyinfer_store_entries ("
            "id TEXT PRIMARY KEY, vector BLOB NOT NULL, metadata_json TEXT NOT NULL, "
            "text TEXT)"
        )
        connection.commit()
        return cls(connection)

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __enter__(self) -> VectorStore:
        """Support ``with VectorStore.open(...) as store:``."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the connection on context-manager exit."""
        self.close()

    # ---- space -----------------------------------------------------------------------

    @property
    def space(self) -> EmbeddingSpace | None:
        """The embedding space this store is bound to, or `None` if still empty."""
        row = self._conn.execute(
            "SELECT space_json FROM anyinfer_store_space WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        from anyinfer.types.operations import EmbeddingSpace

        return EmbeddingSpace(**json.loads(row[0]))

    def _bind_space(self, space: EmbeddingSpace) -> None:
        from dataclasses import asdict

        current = self.space
        if current is None:
            self._conn.execute(
                "INSERT INTO anyinfer_store_space (id, space_json) VALUES (1, ?)",
                (json.dumps(asdict(space)),),
            )
            return
        if not current.compatible_with(space):
            raise EmbeddingSpaceMismatchError(
                f"store is bound to {current.provider_id}:{current.model}, "
                f"refusing an incompatible {space.provider_id}:{space.model} vector"
            )

    # ---- writes ------------------------------------------------------------------------

    def add(
        self,
        entry_id: str,
        vector: Sequence[float],
        *,
        space: EmbeddingSpace,
        metadata: Mapping[str, str] | None = None,
        text: str | None = None,
    ) -> None:
        """Insert or replace one vector.

        Raises:
            anyinfer_store.EmbeddingSpaceMismatchError: `space` is not compatible with
                this store's already-bound space (see `EmbeddingSpace.compatible_with`).
        """
        self._bind_space(space)
        self._conn.execute(
            "INSERT OR REPLACE INTO anyinfer_store_entries (id, vector, metadata_json, text) "
            "VALUES (?, ?, ?, ?)",
            (
                entry_id,
                _pack(vector),
                json.dumps(dict(metadata or {})),
                text,
            ),
        )
        self._conn.commit()
        if self.count() == SIZE_WARNING_THRESHOLD:
            warnings.warn(
                f"this store now holds {SIZE_WARNING_THRESHOLD:,} entries — brute-force "
                "cosine search may be noticeably slow past this point; see "
                "anyinfer_store's scale ceiling in its README before growing further",
                stacklevel=2,
            )

    def add_many(self, entries: Sequence[VectorEntry], *, space: EmbeddingSpace) -> None:
        """Insert or replace several vectors in one transaction."""
        self._bind_space(space)
        self._conn.executemany(
            "INSERT OR REPLACE INTO anyinfer_store_entries (id, vector, metadata_json, text) "
            "VALUES (?, ?, ?, ?)",
            [
                (e.id, _pack(e.vector), json.dumps(dict(e.metadata)), e.text)
                for e in entries
            ],
        )
        self._conn.commit()

    def remove(self, entry_id: str) -> None:
        """Delete one entry; a no-op if it does not exist."""
        self._conn.execute("DELETE FROM anyinfer_store_entries WHERE id = ?", (entry_id,))
        self._conn.commit()

    # ---- reads -------------------------------------------------------------------------

    def get(self, entry_id: str) -> VectorEntry | None:
        """Look up one entry by id, or `None`."""
        row = self._conn.execute(
            "SELECT id, vector, metadata_json, text FROM anyinfer_store_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        return _row_to_entry(row) if row is not None else None

    def count(self) -> int:
        """How many entries this store holds."""
        (n,) = self._conn.execute("SELECT COUNT(*) FROM anyinfer_store_entries").fetchone()
        return int(n)

    def query(
        self,
        vector: Sequence[float],
        *,
        space: EmbeddingSpace,
        top_k: int = 10,
        metadata_filter: Mapping[str, str] | None = None,
    ) -> list[QueryResult]:
        """Brute-force top-k cosine similarity search.

        Raises:
            anyinfer_store.EmbeddingSpaceMismatchError: `space` is not compatible with
                this store's bound space.
            anyinfer_store.VectorStoreError: The store is empty (no space bound yet).
        """
        current = self.space
        if current is None:
            raise VectorStoreError("cannot query an empty store — nothing has been added yet")
        if not current.compatible_with(space):
            raise EmbeddingSpaceMismatchError(
                f"store is bound to {current.provider_id}:{current.model}, "
                f"refusing a query in the incompatible {space.provider_id}:{space.model} space"
            )

        query_vec = list(vector)
        query_norm = _norm(query_vec)
        scored: list[tuple[float, VectorEntry]] = []
        for row in self._conn.execute(
            "SELECT id, vector, metadata_json, text FROM anyinfer_store_entries"
        ):
            entry = _row_to_entry(row)
            if metadata_filter and not _matches(entry.metadata, metadata_filter):
                continue
            score = _cosine(query_vec, entry.vector, query_norm)
            scored.append((score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [QueryResult(entry=e, score=s) for s, e in scored[:top_k]]

    # ---- lifecycle -----------------------------------------------------------------

    def rebuild_index(self) -> None:
        """No-op for the brute-force backend; present so a future approximate-index
        backend can share this interface without a caller-visible change.
        """  # noqa: D205

    def compact(self) -> None:
        """Reclaim disk space after deletions (``VACUUM``)."""
        self._conn.execute("VACUUM")

    def export_jsonl(self, path: str | Path) -> None:
        """Write every entry, one JSON object per line, plus a header line with the space."""
        space = self.space
        with Path(path).open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"space": _space_dict(space) if space else None}) + "\n")
            for row in self._conn.execute(
                "SELECT id, vector, metadata_json, text FROM anyinfer_store_entries"
            ):
                entry = _row_to_entry(row)
                handle.write(
                    json.dumps(
                        {
                            "id": entry.id,
                            "vector": list(entry.vector),
                            "metadata": dict(entry.metadata),
                            "text": entry.text,
                        }
                    )
                    + "\n"
                )

    def import_jsonl(self, path: str | Path) -> None:
        """Load entries previously written by `export_jsonl`, into this (possibly
        already-open, possibly empty) store.
        """  # noqa: D205
        from anyinfer.types.operations import EmbeddingSpace

        with Path(path).open(encoding="utf-8") as handle:
            lines = handle.readlines()
        if not lines:
            return
        header = json.loads(lines[0])
        space_dict = header.get("space")
        if space_dict is None:
            return
        space = EmbeddingSpace(**space_dict)
        entries = [
            VectorEntry(
                id=row["id"],
                vector=tuple(row["vector"]),
                metadata=row.get("metadata", {}),
                text=row.get("text"),
            )
            for line in lines[1:]
            for row in [json.loads(line)]
        ]
        if entries:
            self.add_many(entries, space=space)


def _space_dict(space: EmbeddingSpace) -> dict[str, object]:
    from dataclasses import asdict

    return asdict(space)


def _pack(vector: Sequence[float]) -> bytes:
    return array.array("d", vector).tobytes()


def _unpack(blob: bytes) -> tuple[float, ...]:
    values = array.array("d")
    values.frombytes(blob)
    return tuple(values)


def _row_to_entry(row: tuple[str, bytes, str, str | None]) -> VectorEntry:
    entry_id, vector_blob, metadata_json, text = row
    return VectorEntry(
        id=entry_id, vector=_unpack(vector_blob), metadata=json.loads(metadata_json), text=text
    )


def _matches(metadata: Mapping[str, str], filter_: Mapping[str, str]) -> bool:
    return all(metadata.get(key) == value for key, value in filter_.items())


def _norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(v * v for v in vector))


def _cosine(a: Sequence[float], b: Sequence[float], a_norm: float) -> float:
    b_norm = _norm(b)
    if a_norm == 0.0 or b_norm == 0.0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (a_norm * b_norm)
