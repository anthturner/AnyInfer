"""Duplicate collapse: exact grouping, near grouping, and what it must never touch."""

from __future__ import annotations

from anyinfer.context import ContextDocument, ContextTuning, find_duplicates, select

LICENSE = "\n".join(f"# Copyright line {i} of a long standard header." for i in range(40))


def _vendored(index: int) -> str:
    """A file that differs from its siblings only in one identifier."""
    body = "\n".join(
        f"def helper_{i}(value):\n    return transform(value, {i})" for i in range(40)
    )
    return f"{LICENSE}\n\n{body}\n\ndef unique_{index}():\n    return {index}\n"


def test_byte_identical_documents_collapse():
    documents = [
        ContextDocument.of("a/one.py", "shared content\n"),
        ContextDocument.of("b/two.py", "shared content\n"),
        ContextDocument.of("c/three.py", "different\n"),
    ]
    duplicates = find_duplicates(documents, tuning=ContextTuning())
    assert duplicates.collapsed_count == 1
    assert duplicates.canonical == {"b/two.py": "a/one.py"}
    assert duplicates.is_exact("b/two.py")


def test_the_canonical_is_the_shallowest_path():
    documents = [
        ContextDocument.of("deep/nested/path/file.py", "same\n"),
        ContextDocument.of("top.py", "same\n"),
    ]
    duplicates = find_duplicates(documents, tuning=ContextTuning())
    assert duplicates.canonical == {"deep/nested/path/file.py": "top.py"}


def test_a_pinned_document_becomes_the_canonical():
    documents = [
        ContextDocument.of("a.py", "same\n"),
        ContextDocument.of("z/deeper.py", "same\n", pinned=True),
    ]
    duplicates = find_duplicates(documents, tuning=ContextTuning())
    assert duplicates.canonical == {"a.py": "z/deeper.py"}


def test_collapse_is_off_when_disabled():
    documents = [
        ContextDocument.of("a.py", "same\n"),
        ContextDocument.of("b.py", "same\n"),
    ]
    assert not find_duplicates(documents, tuning=ContextTuning(collapse_duplicates=False))


def test_near_duplicates_need_the_threshold():
    documents = [ContextDocument.of(f"vendor{i}/mod.py", _vendored(i)) for i in range(4)]
    assert not find_duplicates(documents, tuning=ContextTuning())

    tuning = ContextTuning(near_duplicate_threshold=0.9)
    duplicates = find_duplicates(documents, tuning=tuning)
    assert duplicates.collapsed_count == 3
    assert not any(duplicates.is_exact(path) for path in duplicates.canonical)


def test_near_collapse_never_removes_a_pinned_document():
    documents = [ContextDocument.of(f"vendor{i}/mod.py", _vendored(i)) for i in range(4)]
    documents[2] = ContextDocument.of("vendor2/mod.py", _vendored(2), pinned=True)
    duplicates = find_duplicates(documents, tuning=ContextTuning(near_duplicate_threshold=0.9))
    # Pinning means the user chose this file, and its differences are the reason.
    assert "vendor2/mod.py" not in duplicates.canonical


def test_distinct_documents_are_not_near_duplicates():
    documents = [
        ContextDocument.of("a.py", "\n".join(f"def alpha_{i}(): return {i}" for i in range(60))),
        ContextDocument.of("b.py", "\n".join(f"class Beta{i}: pass" for i in range(60))),
    ]
    assert not find_duplicates(documents, tuning=ContextTuning(near_duplicate_threshold=0.8))


def test_grouping_is_deterministic_under_reversal():
    documents = [ContextDocument.of(f"vendor{i}/mod.py", _vendored(i)) for i in range(5)]
    tuning = ContextTuning(near_duplicate_threshold=0.9)
    forward = find_duplicates(documents, tuning=tuning)
    backward = find_duplicates(list(reversed(documents)), tuning=tuning)
    assert dict(forward.canonical) == dict(backward.canonical)


def test_every_duplicate_points_at_a_document_that_is_actually_rendered():
    documents = [
        ContextDocument.of("a.py", _vendored(0)),
        ContextDocument.of("b.py", _vendored(0)),
        ContextDocument.of("c.py", _vendored(1)),
    ]
    tuning = ContextTuning(near_duplicate_threshold=0.9)
    duplicates = find_duplicates(documents, tuning=tuning)
    targets = set(duplicates.canonical.values())
    assert targets.isdisjoint(set(duplicates.canonical)), "no pointer chains"


# ---- how collapse shows up in a reduction --------------------------------------------


def test_the_envelope_points_duplicates_at_their_representative():
    documents = [
        ContextDocument.of("a/one.py", "shared content\n"),
        ContextDocument.of("b/two.py", "shared content\n"),
    ]
    reduction = select(documents, "shared", max_tokens=1_000)
    assert '<duplicate path="b/two.py" of="a/one.py" identical="true"/>' in reduction.text
    assert reduction.text.count("shared content") == 1


def test_exact_collapse_preserves_completeness():
    documents = [
        ContextDocument.of("a.py", "shared\n"),
        ContextDocument.of("b.py", "shared\n"),
    ]
    reduction = select(documents, "shared", max_tokens=1_000)
    assert reduction.collapsed_exact == 1
    assert reduction.omitted_count == 0
    assert reduction.complete, "the same bytes were sent, once; nothing was lost"


def test_near_collapse_forfeits_completeness():
    documents = [ContextDocument.of(f"vendor{i}/mod.py", _vendored(i)) for i in range(3)]
    reduction = select(
        documents,
        "helper",
        max_tokens=100_000,
        tuning=ContextTuning(near_duplicate_threshold=0.9),
    )
    assert reduction.collapsed_near == 2
    assert not reduction.complete, "the near-duplicates' differences were not sent"
    assert 'identical="false"' in reduction.text


def test_collapsed_documents_are_not_counted_as_omitted():
    documents = [ContextDocument.of(f"copy{i}.py", "identical\n") for i in range(5)]
    reduction = select(documents, "identical", max_tokens=1_000)
    assert reduction.candidate_count == 5
    assert reduction.collapsed_exact == 4
    assert reduction.omitted_count == 0
    assert "collapsed" in reduction.summary()


def test_byte_identical_files_stay_lossless_even_when_the_near_pass_groups_them():
    # Losslessness is a property of the bytes, not of which pass did the grouping.
    documents = [
        ContextDocument.of("a.py", _vendored(0)),
        ContextDocument.of("b.py", _vendored(0)),
    ]
    tuning = ContextTuning(collapse_duplicates=False, near_duplicate_threshold=0.9)
    duplicates = find_duplicates(documents, tuning=tuning)
    assert duplicates.collapsed_count == 1
    assert duplicates.is_exact("b.py")

    reduction = select(documents, "helper", max_tokens=100_000, tuning=tuning)
    assert 'identical="true"' in reduction.text
    assert reduction.complete
