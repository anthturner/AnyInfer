from __future__ import annotations

from pathlib import Path

import pytest
from anyinfer.types.operations import EmbeddingSpace

from anyinfer_store import EmbeddingSpaceMismatchError, VectorEntry, VectorStore, VectorStoreError


def _space(**overrides: object) -> EmbeddingSpace:
    defaults = {"provider_id": "ollama", "model": "nomic-embed-text", "dimensions": 4}
    return EmbeddingSpace(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_add_and_get_round_trips_the_vector(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    space = _space()
    store.add("a", [1.0, 2.0, 3.0, 4.0], space=space, metadata={"tag": "x"}, text="hello")
    entry = store.get("a")
    assert entry is not None
    assert entry.vector == (1.0, 2.0, 3.0, 4.0)
    assert entry.metadata == {"tag": "x"}
    assert entry.text == "hello"
    store.close()


def test_query_ranks_by_cosine_similarity_descending(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    space = _space()
    store.add("close", [1.0, 0.0, 0.0, 0.0], space=space)
    store.add("far", [0.0, 1.0, 0.0, 0.0], space=space)
    store.add("closest", [1.0, 0.01, 0.0, 0.0], space=space)

    results = store.query([1.0, 0.0, 0.0, 0.0], space=space, top_k=3)
    assert [r.entry.id for r in results] == ["close", "closest", "far"]
    assert results[0].score == pytest.approx(1.0)
    assert results[0].score >= results[1].score >= results[2].score


def test_query_respects_top_k(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    space = _space()
    for i in range(5):
        store.add(f"e{i}", [float(i), 0.0, 0.0, 0.0], space=space)
    assert len(store.query([1.0, 0.0, 0.0, 0.0], space=space, top_k=2)) == 2


def test_query_metadata_filter(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    space = _space()
    store.add("a", [1.0, 0.0, 0.0, 0.0], space=space, metadata={"lang": "en"})
    store.add("b", [1.0, 0.0, 0.0, 0.0], space=space, metadata={"lang": "fr"})
    results = store.query(
        [1.0, 0.0, 0.0, 0.0], space=space, top_k=10, metadata_filter={"lang": "fr"}
    )
    assert [r.entry.id for r in results] == ["b"]


def test_add_with_incompatible_space_is_refused(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    store.add("a", [1.0, 0.0, 0.0, 0.0], space=_space())
    with pytest.raises(EmbeddingSpaceMismatchError):
        store.add("b", [1.0, 0.0, 0.0, 0.0], space=_space(model="different-model"))


def test_query_with_incompatible_space_is_refused(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    store.add("a", [1.0, 0.0, 0.0, 0.0], space=_space())
    with pytest.raises(EmbeddingSpaceMismatchError):
        store.query([1.0, 0.0, 0.0, 0.0], space=_space(provider_id="different-provider"))


def test_query_on_an_empty_store_raises(open_store) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        store = open_store(Path(d) / "s.db")
        with pytest.raises(VectorStoreError):
            store.query([1.0, 0.0, 0.0, 0.0], space=_space())


def test_compatibility_id_permits_a_different_model_string(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    store.add("a", [1.0, 0.0, 0.0, 0.0], space=_space(compatibility_id="my-space-v1"))
    # A different provider/model but the same caller-asserted compatibility id is allowed.
    store.add(
        "b",
        [0.0, 1.0, 0.0, 0.0],
        space=_space(provider_id="other", model="other-model", compatibility_id="my-space-v1"),
    )
    assert store.count() == 2


def test_remove_deletes_an_entry(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    space = _space()
    store.add("a", [1.0, 0.0, 0.0, 0.0], space=space)
    store.remove("a")
    assert store.get("a") is None
    assert store.count() == 0


def test_remove_is_a_no_op_for_a_missing_id(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    store.remove("nonexistent")  # must not raise


def test_add_replaces_an_existing_id(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    space = _space()
    store.add("a", [1.0, 0.0, 0.0, 0.0], space=space, text="v1")
    store.add("a", [0.0, 1.0, 0.0, 0.0], space=space, text="v2")
    assert store.count() == 1
    entry = store.get("a")
    assert entry is not None
    assert entry.text == "v2"


def test_add_many_inserts_a_batch(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    space = _space()
    entries = [VectorEntry(id=f"e{i}", vector=(float(i), 0.0, 0.0, 0.0)) for i in range(10)]
    store.add_many(entries, space=space)
    assert store.count() == 10


def test_persistence_across_process_restarts(tmp_path: Path, open_store) -> None:
    path = tmp_path / "persist.db"
    store = open_store(path)
    space = _space()
    store.add("a", [1.0, 2.0, 3.0, 4.0], space=space, text="hi")
    store.close()

    reopened = open_store(path)
    entry = reopened.get("a")
    assert entry is not None
    assert entry.vector == (1.0, 2.0, 3.0, 4.0)
    assert reopened.space is not None
    assert reopened.space.model == "nomic-embed-text"
    reopened.close()


def test_context_manager_closes_the_connection(tmp_path: Path) -> None:
    with VectorStore.open(tmp_path / "s.db") as store:
        store.add("a", [1.0, 0.0, 0.0, 0.0], space=_space())
    with pytest.raises(Exception):  # noqa: B017 — sqlite3 raises ProgrammingError
        store.count()


def test_compact_does_not_raise(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    store.add("a", [1.0, 0.0, 0.0, 0.0], space=_space())
    store.remove("a")
    store.compact()  # must not raise
    store.close()


def test_export_and_import_round_trip(tmp_path: Path, open_store) -> None:
    space = _space()
    store = open_store(tmp_path / "s.db")
    store.add("a", [1.0, 2.0, 3.0, 4.0], space=space, metadata={"k": "v"}, text="alpha")
    store.add("b", [4.0, 3.0, 2.0, 1.0], space=space, text="beta")
    export_path = tmp_path / "export.jsonl"
    store.export_jsonl(export_path)
    store.close()

    restored = open_store(tmp_path / "restored.db")
    restored.import_jsonl(export_path)
    assert restored.count() == 2
    a = restored.get("a")
    assert a is not None
    assert a.vector == (1.0, 2.0, 3.0, 4.0)
    assert a.metadata == {"k": "v"}
    assert a.text == "alpha"
    restored.close()


def test_rebuild_index_does_not_raise(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    store.rebuild_index()  # must not raise, brute-force backend has nothing to rebuild
    store.close()
