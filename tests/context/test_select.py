"""Selection: strategy dispatch, budget accounting, and honest reporting."""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.context import ContextDocument, normalize_strategy, select
from anyinfer.context.envelope import block_bytes, render_corpus, render_file_block


def _doc(path: str, content: str, **kwargs: object) -> ContextDocument:
    return ContextDocument.of(path, content, **kwargs)  # type: ignore[arg-type]


SMALL = [
    _doc("a.py", "def alpha():\n    return 1\n"),
    _doc("b.py", "def beta():\n    return 2\n"),
]

LARGE = [
    _doc(f"src/mod{i}/file{i}.py", f"def function_{i}():\n    return {i}\n" * 40) for i in range(6)
]


# ---- strategy names ------------------------------------------------------------------


def test_blank_and_none_normalize_to_auto():
    assert normalize_strategy(None) == "auto"
    assert normalize_strategy("  ") == "auto"
    assert normalize_strategy(" WHOLE ") == "whole"


def test_an_unknown_strategy_lists_the_valid_ones():
    with pytest.raises(ValueError) as excinfo:
        normalize_strategy("semantic")
    assert "semantic" in str(excinfo.value)
    assert "tiered" in str(excinfo.value)


def test_non_positive_budgets_are_rejected():
    for kwargs in ({"max_tokens": 0}, {"max_bytes": 0}, {"max_documents": 0}):
        with pytest.raises(ValueError):
            select(SMALL, "q", **{"max_tokens": 100, **kwargs})  # type: ignore[arg-type]


# ---- whole and auto ------------------------------------------------------------------


def test_whole_sends_everything_when_it_fits():
    reduction = select(SMALL, "alpha", max_tokens=100_000)
    assert reduction.representation == "whole"
    assert len(reduction.documents) == 2
    assert reduction.binding_constraints == ()
    assert reduction.complete


def test_auto_is_byte_identical_to_whole_when_the_corpus_fits():
    auto = select(SMALL, "alpha", max_tokens=100_000, strategy="auto")
    whole = select(SMALL, "alpha", max_tokens=100_000, strategy="whole")
    assert auto.text == whole.text
    assert auto.strategy == "auto", "the requested strategy is preserved"
    assert auto.representation == "whole"


def test_auto_escalates_to_tiered_when_the_corpus_does_not_fit():
    reduction = select(LARGE, "function", max_tokens=300, strategy="auto")
    assert reduction.strategy == "auto"
    assert reduction.representation == "tiered"


def test_whole_falls_back_to_ranked_rather_than_tiered():
    """An explicit strategy is a choice; only `auto` escalates across representations."""
    reduction = select(LARGE, "function", max_tokens=300, strategy="whole")
    assert reduction.representation == "ranked"


# ---- greedy selection ----------------------------------------------------------------


def test_the_document_ceiling_reports_and_stops():
    reduction = select(LARGE, "function", max_tokens=100_000, max_documents=2)
    assert len(reduction.documents) == 2
    assert reduction.binding_constraints == ("document count",)
    assert reduction.omitted_count == 4


def test_a_token_overflow_skips_and_continues():
    """A smaller lower-ranked document may still fit after a big one did not."""
    corpus = [
        _doc("huge.py", "x = 1\n" * 2000),
        _doc("tiny.py", "y = 2\n"),
    ]
    reduction = select(corpus, "", max_tokens=200, strategy="ranked")
    assert [d.path for d in reduction.documents] == ["tiny.py"]
    assert "tokens" in reduction.binding_constraints


def test_binding_constraints_use_a_fixed_order():
    reduction = select(LARGE, "function", max_tokens=200, max_documents=1, strategy="ranked")
    assert list(reduction.binding_constraints) == [
        name
        for name in ("document count", "bytes", "tokens")
        if name in reduction.binding_constraints
    ]


def test_byte_accounting_matches_the_rendered_envelope():
    """The number the selector budgets against is the number it actually produces."""
    reduction = select(SMALL, "alpha", max_tokens=100_000)
    assert reduction.total_bytes == len(reduction.text.encode("utf-8"))

    manual = render_corpus(render_file_block(d) for d in reduction.documents)
    assert reduction.text == manual


def test_block_bytes_accounts_for_the_joining_newline():
    block = render_file_block(SMALL[0])
    assert block_bytes(block) == len(block.encode("utf-8")) + 1


# ---- rendering order -----------------------------------------------------------------


def test_path_order_is_the_default_and_is_stable_across_queries():
    """Same selection, different query wording — identical bytes, so caches still hit."""
    one = select(SMALL, "alpha", max_tokens=100_000)
    two = select(SMALL, "beta", max_tokens=100_000)
    assert one.text == two.text


def test_rank_order_renders_strongest_first():
    reduction = select(SMALL, "beta", max_tokens=100_000, render_order="rank")
    assert reduction.documents[0].path == "b.py"


# ---- reporting -----------------------------------------------------------------------


def test_summary_is_content_free():
    reduction = select(LARGE, "function", max_tokens=300, strategy="ranked")
    summary = reduction.summary()
    for document in LARGE:
        assert document.path not in summary
        assert document.content.strip() not in summary
    assert "of 6 document(s)" in summary


def test_metadata_carries_the_full_record():
    reduction = select(LARGE, "function", max_tokens=300, strategy="ranked")
    record = reduction.metadata()
    assert record["candidate_count"] == 6
    assert record["selected_count"] == len(reduction.documents)
    assert record["max_tokens"] == 300
    assert isinstance(record["binding_constraints"], list)


def test_an_observer_receives_a_content_free_event():
    received: list[ai.TelemetryEvent] = []

    class Recorder:
        def on_event(self, event: ai.TelemetryEvent) -> None:
            received.append(event)

    reduction = select(LARGE, "function", max_tokens=300, strategy="ranked", observer=Recorder())

    assert len(received) == 1
    event = received[0]
    assert isinstance(event, ai.ContextReduced)
    assert event.representation == "ranked"
    assert event.candidate_count == 6
    assert event.selected_count == len(reduction.documents)
    assert event.calls == 0
    # Content-free by construction: no field carries a path or document text.
    import dataclasses

    values = [getattr(event, f.name) for f in dataclasses.fields(event)]
    assert not any(isinstance(value, str) and "/" in value for value in values)


def test_an_empty_corpus_reduces_to_an_empty_envelope():
    reduction = select([], "anything", max_tokens=1000)
    assert reduction.documents == ()
    assert reduction.candidate_count == 0
    assert reduction.text
