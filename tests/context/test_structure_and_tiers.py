"""Language detection, structural extraction, and the tiered strategy."""

from __future__ import annotations

from anyinfer.context import (
    ContextDocument,
    detect_language,
    is_generated_path,
    module_surfaces,
    select,
    structural_extract,
)
from anyinfer.context.structure import (
    SMALL_FILE_VERBATIM_BYTES,
    TRUNCATION_MARKER,
)

PYTHON = '''\
"""A module."""

import os
from pathlib import Path


class Resolver:
    """Resolve things."""

    def resolve(self, ref: str) -> str:
        value = os.environ.get(ref)
        if value is None:
            raise KeyError(ref)
        return value


def helper(path):
    return Path(path).read_text()
'''


# ---- language detection --------------------------------------------------------------


def test_known_suffixes_map_to_languages():
    assert detect_language("src/app.py") == "python"
    assert detect_language("src/App.tsx") == "typescript"
    assert detect_language("Main.java") == "java"
    assert detect_language("notes.md") == "markdown"


def test_ambiguous_suffixes_stay_unknown():
    """A .h file may be C or C++; a wrong guess extracts worse than not guessing."""
    assert detect_language("include/api.h") is None
    assert detect_language("notes.txt") is None
    assert detect_language("no-suffix") is None


def test_generated_paths_are_recognized():
    assert is_generated_path("node_modules/left-pad/index.js")
    assert is_generated_path("src/models.g.dart")
    assert is_generated_path("app/bundle.min.js")
    assert is_generated_path("build/output.py")
    assert not is_generated_path("src/app/models.dart")


# ---- extraction ----------------------------------------------------------------------


def test_extraction_keeps_declarations_and_drops_bodies():
    # Padded past the small-file threshold, below which a file is its own extract.
    extract = structural_extract(PYTHON + "\n# filler\n" * 100, language="python")
    assert "import os" in extract
    assert "class Resolver:" in extract
    assert "def resolve(self, ref: str) -> str:" in extract
    assert "raise KeyError(ref)" not in extract, "bodies are dropped"


def test_small_files_are_their_own_extract():
    tiny = "x = 1\n"
    assert len(tiny.encode()) <= SMALL_FILE_VERBATIM_BYTES
    assert structural_extract(tiny, language="python") == tiny


def test_an_unknown_language_yields_no_extract():
    body = "some prose\n" * 100
    assert structural_extract(body, language=None) == ""


def test_an_oversized_extract_is_marked_truncated():
    huge = "".join(f"def function_{i}():\n    pass\n" for i in range(3000))
    extract = structural_extract(huge, language="python")
    assert extract.endswith(TRUNCATION_MARKER), "truncation is never silent"


def test_annotations_are_preserved():
    java = "package app;\n\n@Service\npublic class Thing {\n    void go() {}\n}\n" * 20
    extract = structural_extract(java, language="java")
    assert "@Service" in extract
    assert "public class Thing {" in extract


def test_documents_derive_language_and_extract_by_default():
    document = ContextDocument.of("src/app.py", PYTHON)
    assert document.language == "python"
    assert "class Resolver:" in document.extract
    assert document.sha256


def test_extraction_can_be_opted_out_of():
    document = ContextDocument.of("src/app.py", PYTHON, extract="")
    assert document.extract == ""
    assert document.language == "python", "language detection still runs"


# ---- the tiered strategy -------------------------------------------------------------


CORPUS = [
    ContextDocument.of(f"src/auth/mod{i}.py", PYTHON.replace("Resolver", f"Auth{i}"))
    for i in range(3)
] + [
    ContextDocument.of(f"src/util/util{i}.py", PYTHON.replace("Resolver", f"Util{i}"))
    for i in range(3)
]


def test_every_document_is_covered_by_the_rollup():
    reduction = select(CORPUS, "auth", max_tokens=400, strategy="tiered")
    assert reduction.tier_metadata is not None
    assert reduction.tier_metadata["coverage_fraction"] == 1.0
    assert "<context-tiers" in reduction.text
    assert 'coverage_files="6"' in reduction.text


def test_the_rollup_names_modules_and_their_share():
    reduction = select(CORPUS, "auth", max_tokens=2000, strategy="tiered")
    assert 'path="src/auth"' in reduction.text
    assert 'path="src/util"' in reduction.text
    assert "corpus_share=" in reduction.text


def test_rollup_symbol_lines_carry_clean_identifiers():
    reduction = select(CORPUS, "auth", max_tokens=2000, strategy="tiered")
    symbol_lines = [
        line for line in reduction.text.splitlines() if line.startswith("symbols:")
    ]
    assert symbol_lines
    for line in symbol_lines:
        assert "(" not in line, "a signature must not leak a dangling paren"
        assert ":" not in line.removeprefix("symbols:")


def test_an_empty_label_line_is_omitted_entirely():
    """A bare `dependencies:` costs tokens and conveys nothing."""
    corpus = [ContextDocument.of("notes/a.md", "# Heading\n\ntext\n" * 40)]
    reduction = select(corpus, "heading", max_tokens=2000, strategy="tiered")
    assert "dependencies:" not in reduction.text


def test_digests_are_rendered_only_when_supplied():
    without = select(CORPUS, "auth", max_tokens=4000, strategy="tiered")
    assert "<module-digests>" not in without.text
    assert without.tier_metadata is not None
    assert without.tier_metadata["digests_rendered"] is False

    with_digests = select(
        CORPUS,
        "auth",
        max_tokens=4000,
        strategy="tiered",
        module_digests={"src/auth": "Authentication helpers."},
    )
    assert "<module-digests>" in with_digests.text
    assert "Authentication helpers." in with_digests.text


def test_documents_reports_what_was_rendered_in_detail():
    """Not the ranked prefix — the set that actually appears at detail fidelity."""
    reduction = select(CORPUS, "auth", max_tokens=1200, strategy="tiered")
    for document in reduction.documents:
        assert (
            f'path="{document.path}"' in reduction.text
        ), "every reported document must appear in the envelope"
    assert reduction.tier_metadata is not None
    detail_count = (
        reduction.tier_metadata["extract_count"] + reduction.tier_metadata["verbatim_count"]
    )
    assert detail_count == len(reduction.documents)


def test_binding_constraints_name_the_ceiling_that_actually_bound():
    reduction = select(CORPUS, "auth", max_tokens=300, strategy="tiered")
    assert "tokens" in reduction.binding_constraints
    assert "bytes" not in reduction.binding_constraints


def test_the_rollup_survives_a_budget_too_small_for_anything_else():
    """A corpus map is the one thing this strategy must never drop."""
    reduction = select(CORPUS, "auth", max_tokens=1, strategy="tiered")
    assert "<context-tiers" in reduction.text
    assert reduction.documents == ()


def test_tiered_rendering_is_deterministic_under_corpus_reversal():
    forward = select(CORPUS, "auth", max_tokens=1200, strategy="tiered").text
    backward = select(list(reversed(CORPUS)), "auth", max_tokens=1200, strategy="tiered").text
    assert forward == backward


# ---- module surfaces -----------------------------------------------------------------


def test_module_surfaces_group_deterministically():
    surfaces = module_surfaces(CORPUS, depth=2)
    assert set(surfaces) == {"src/auth", "src/util"}
    assert surfaces == module_surfaces(list(reversed(CORPUS)), depth=2)
    assert "src/auth/mod0.py" in surfaces["src/auth"]
