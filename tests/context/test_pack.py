"""The packed strategy: boundary-aware splitting, span tracking, and coalescing."""

from __future__ import annotations

import itertools
import re

from anyinfer.context import ContextDocument, select, split_document
from anyinfer.context.pack import DEFAULT_CHUNK_TOKENS, MIN_CHUNK_TOKENS

PARAGRAPHS = "\n\n".join(f"Paragraph {i} about various matters." for i in range(200))


# ---- splitting -----------------------------------------------------------------------


def test_a_short_document_is_one_chunk():
    document = ContextDocument.of("small.txt", "just a little text\n")
    chunks = split_document(document)
    assert len(chunks) == 1
    assert chunks[0].text == document.content
    assert chunks[0].start_line == 1


def test_splitting_prefers_paragraph_boundaries():
    document = ContextDocument.of("doc.md", PARAGRAPHS)
    chunks = split_document(document, chunk_tokens=64)
    assert len(chunks) > 1
    # Every chunk but the last should end at a paragraph break.
    for chunk in chunks[:-1]:
        assert chunk.text.endswith("\n\n"), "paragraph boundaries are preferred"


def test_splitting_falls_back_to_line_boundaries():
    document = ContextDocument.of("code.py", "".join(f"line_{i} = {i}\n" for i in range(500)))
    chunks = split_document(document, chunk_tokens=64)
    assert len(chunks) > 1
    for chunk in chunks[:-1]:
        assert chunk.text.endswith("\n"), "line boundaries when no paragraph break fits"


def test_a_document_with_no_boundaries_hard_cuts():
    document = ContextDocument.of("blob.txt", "x" * 5000)
    chunks = split_document(document, chunk_tokens=64)
    assert len(chunks) > 1
    assert "".join(chunk.text for chunk in chunks) == document.content


def test_chunks_reassemble_to_the_original_content():
    document = ContextDocument.of("doc.md", PARAGRAPHS)
    chunks = split_document(document, chunk_tokens=64)
    assert "".join(chunk.text for chunk in chunks) == document.content


def test_line_spans_are_contiguous_and_one_based():
    document = ContextDocument.of("code.py", "".join(f"line_{i}\n" for i in range(300)))
    chunks = split_document(document, chunk_tokens=64)
    assert chunks[0].start_line == 1
    for previous, following in itertools.pairwise(chunks):
        assert following.start_line == previous.end_line


def test_a_runt_tail_chunk_merges_backward():
    body = "a" * (DEFAULT_CHUNK_TOKENS * 3) + "\n" + "b" * 10
    document = ContextDocument.of("blob.txt", body)
    chunks = split_document(document, chunk_tokens=DEFAULT_CHUNK_TOKENS)
    assert all(
        len(chunk.text) >= MIN_CHUNK_TOKENS or chunk is chunks[-1] for chunk in chunks
    )
    assert "".join(chunk.text for chunk in chunks) == body


# ---- packing -------------------------------------------------------------------------


CORPUS = [
    ContextDocument.of(
        "src/auth/credentials.py",
        "\n\n".join(
            f"def credential_helper_{i}():\n    return resolve_credential({i})"
            for i in range(60)
        ),
    ),
    ContextDocument.of(
        "src/util/text.py",
        "\n\n".join(f"def slug_{i}(value):\n    return value.lower()" for i in range(60)),
    ),
]


def test_packing_selects_chunks_not_whole_documents():
    reduction = select(CORPUS, "credential", max_tokens=400, strategy="packed")
    assert reduction.representation == "packed"
    assert "<file-chunk" in reduction.text
    assert reduction.tier_metadata is not None
    assert reduction.tier_metadata["chunks_selected"] >= 1
    assert reduction.tier_metadata["chunks_available"] > reduction.tier_metadata[
        "chunks_selected"
    ]


def test_chunk_blocks_carry_line_spans():
    reduction = select(CORPUS, "credential", max_tokens=400, strategy="packed")
    spans = re.findall(r'lines="(\d+)-(\d+)"', reduction.text)
    assert spans
    for start, end in spans:
        assert int(end) >= int(start)


def test_adjacent_chunks_coalesce_into_one_block():
    """A contiguous run reads as one span, not as fragments implying gaps."""
    reduction = select(CORPUS, "credential", max_tokens=100_000, strategy="packed")
    blocks = re.findall(r'<file-chunk path="([^"]+)"', reduction.text)
    # With a huge budget every chunk is selected, so each document collapses to one block.
    assert len(blocks) == len(set(blocks)), "contiguous chunks must merge"


def test_pinned_documents_are_sent_whole_and_first():
    corpus = [
        *CORPUS,
        ContextDocument.of("PINNED.md", "# Pinned\n\nAlways include me.\n", pinned=True),
    ]
    reduction = select(corpus, "credential", max_tokens=100_000, strategy="packed")
    assert '<file path="PINNED.md"' in reduction.text, "pinned documents go in whole"
    assert '<file-chunk path="PINNED.md"' not in reduction.text


def test_relevant_chunks_outrank_irrelevant_ones():
    reduction = select(CORPUS, "credential", max_tokens=300, strategy="packed")
    assert "credential" in reduction.text


def test_packed_output_is_deterministic_under_corpus_reversal():
    forward = select(CORPUS, "credential", max_tokens=500, strategy="packed").text
    backward = select(
        list(reversed(CORPUS)), "credential", max_tokens=500, strategy="packed"
    ).text
    assert forward == backward


def test_the_document_ceiling_counts_documents_not_chunks():
    reduction = select(CORPUS, "credential", max_tokens=100_000, strategy="packed",
                       max_documents=1)
    paths = set(re.findall(r'<file-chunk path="([^"]+)"', reduction.text))
    assert len(paths) == 1
    assert "document count" in reduction.binding_constraints
