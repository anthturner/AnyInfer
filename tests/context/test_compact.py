"""Compact source: the fidelity between a structural extract and a whole file."""

from __future__ import annotations

import pytest

from anyinfer.context import (
    ContextDocument,
    ContextTuning,
    compact_source,
    select,
    supports_compaction,
)

PYTHON = '''"""Module docstring that costs tokens and says nothing executable."""

# A leading comment.
import os


def resolve(value):
    """Docstring."""
    # An inline explanation.
    return os.path.join(value, "x")


class Thing:
    """Another docstring."""

    attribute = 1
'''

RUST = """// Copyright header line one.
// Copyright header line two.

/* A block comment
   spanning lines. */
use std::fs;

/// Doc comment.
pub fn read(path: &str) -> String {
    fs::read_to_string(path).unwrap()  // trailing comment stays
}
"""


def test_python_loses_comments_docstrings_and_blank_runs():
    result = compact_source(PYTHON, language="python")
    assert "Module docstring" not in result.text
    assert "A leading comment" not in result.text
    assert "An inline explanation" not in result.text
    assert "def resolve(value):" in result.text
    assert "class Thing:" in result.text
    assert "attribute = 1" in result.text
    assert result.is_reduced
    assert result.elided_lines > 0


def test_rust_loses_line_and_block_comments():
    result = compact_source(RUST, language="rust")
    assert "Copyright header" not in result.text
    assert "A block comment" not in result.text
    assert "spanning lines" not in result.text
    assert "Doc comment" not in result.text
    assert "pub fn read" in result.text
    assert "use std::fs;" in result.text


def test_a_trailing_comment_is_left_alone():
    # Removing it would require knowing whether the token sits inside a string literal,
    # and getting that wrong corrupts code rather than shortening it.
    result = compact_source(RUST, language="rust")
    assert "// trailing comment stays" in result.text


def test_a_single_line_docstring_does_not_swallow_the_rest_of_the_file():
    source = 'def f():\n    """One line."""\n    return 1\n\n\ndef g():\n    return 2\n'
    result = compact_source(source, language="python")
    assert "def g():" in result.text
    assert "return 2" in result.text
    assert "One line" not in result.text


def test_an_assignment_of_a_triple_quoted_string_is_not_a_docstring():
    source = 'TEMPLATE = """\nkeep me\n"""\n\ndef f():\n    return TEMPLATE\n'
    result = compact_source(source, language="python")
    assert "keep me" in result.text


def test_an_unknown_language_only_collapses_blank_runs():
    source = "alpha\n\n\n\nbeta\n"
    result = compact_source(source, language=None)
    assert result.text == "alpha\n\nbeta\n"


def test_markdown_keeps_its_content():
    source = "# Title\n\nSome prose.\n\n<!-- a comment -->\n"
    result = compact_source(source, language="markdown")
    assert "# Title" in result.text
    assert "Some prose." in result.text


def test_language_is_inferred_from_the_path():
    result = compact_source(PYTHON, path="src/thing.py")
    assert "Module docstring" not in result.text


def test_empty_content_is_a_no_op():
    result = compact_source("", language="python")
    assert result.text == ""
    assert not result.is_reduced


@pytest.mark.parametrize("language", ["python", "rust", "typescript", "go", "yaml"])
def test_supported_languages_report_themselves(language):
    assert supports_compaction(language)


@pytest.mark.parametrize("language", [None, "markdown", "not-a-language"])
def test_unsupported_languages_report_themselves(language):
    assert not supports_compaction(language)


# ---- how compaction shows up in a reduction ------------------------------------------


def _bulky(index: int) -> ContextDocument:
    body = "\n".join(
        f"# explanation number {i} which exists purely to be removed\n"
        f"def function_{index}_{i}(value):\n"
        f"    return value + {i}\n"
        for i in range(30)
    )
    return ContextDocument.of(f"module_{index}.py", body)


def test_a_file_that_will_not_fit_whole_is_compacted_rather_than_dropped():
    documents = [_bulky(index) for index in range(4)]
    plain = select(documents, "function", max_tokens=900, strategy="ranked")
    compacted = select(
        documents,
        "function",
        max_tokens=900,
        strategy="ranked",
        tuning=ContextTuning(compact_fallback=True),
    )
    assert len(compacted.documents) > len(plain.documents)
    assert compacted.compacted_count > 0
    assert "<file-compact" in compacted.text
    assert "explanation number" not in compacted.text.split("<file-compact")[1]


def test_compaction_reports_what_it_elided():
    documents = [_bulky(index) for index in range(4)]
    reduction = select(
        documents,
        "function",
        max_tokens=900,
        strategy="ranked",
        tuning=ContextTuning(compact_fallback=True),
    )
    assert 'elided_lines="' in reduction.text
    assert not reduction.complete, "a compacted file is not a whole file"
    assert "compacted" in reduction.summary()


def test_compaction_never_pushes_a_reduction_over_budget():
    documents = [_bulky(index) for index in range(6)]
    for budget in (400, 900, 1500, 3000):
        reduction = select(
            documents,
            "function",
            max_tokens=budget,
            strategy="ranked",
            tuning=ContextTuning(compact_fallback=True),
        )
        assert reduction.estimated_tokens <= budget
