"""The lexical ranker: scoring, pinning, determinism, and the cache."""

from __future__ import annotations

from collections import Counter

from anyinfer.context import ContextDocument, build_rank_cache, rank, tokenize
from anyinfer.context.rank import ANCHOR_SCORE, score_document


def _doc(path: str, content: str, **kwargs: object) -> ContextDocument:
    return ContextDocument.of(path, content, **kwargs)  # type: ignore[arg-type]


CORPUS = [
    _doc("src/auth/credentials.py", "resolve a credential from the environment\n" * 5),
    _doc("src/util/text.py", "slugify some text for a url\n" * 5),
    _doc("docs/guide.md", "a guide mentioning credential handling once\n"),
    _doc("README.md", "the project readme\n"),
]


# ---- tokenization --------------------------------------------------------------------


def test_tokenize_lowercases_and_drops_stop_words():
    assert tokenize("The Quick Brown Fox") == ["quick", "brown", "fox"]


def test_tokenize_splits_on_non_alphanumerics():
    assert tokenize("resolve_credential(ref)") == ["resolve", "credential", "ref"]


def test_tokenize_ignores_punctuation_only_input():
    assert tokenize("--- ... ///") == []


# ---- scoring -------------------------------------------------------------------------


def test_a_path_match_outranks_a_body_only_match():
    """Someone asking about credentials means the file named for it."""
    ordered = rank(CORPUS, "credential")
    assert ordered[0].path == "src/auth/credentials.py"


def test_anchor_files_get_a_bonus_on_an_empty_query():
    cache = build_rank_cache(CORPUS)
    readme = next(d for d in CORPUS if d.path == "README.md")
    other = next(d for d in CORPUS if d.path == "src/util/text.py")

    assert score_document(readme, Counter(), cache) == ANCHOR_SCORE
    assert score_document(other, Counter(), cache) == 0.0


def test_score_is_zero_when_nothing_matches():
    cache = build_rank_cache(CORPUS)
    document = next(d for d in CORPUS if d.path == "src/util/text.py")
    assert score_document(document, Counter({"kubernetes": 1}), cache) == 0.0


def test_a_rare_term_outweighs_a_common_one():
    """Inverse document frequency: a term in every file discriminates nothing."""
    corpus = [
        _doc("a.txt", "common common common rare\n"),
        _doc("b.txt", "common common common\n"),
        _doc("c.txt", "common common common\n"),
    ]
    cache = build_rank_cache(corpus)
    rare_hit = score_document(corpus[0], Counter({"rare": 1}), cache)
    common_hit = score_document(corpus[0], Counter({"common": 1}), cache)
    assert rare_hit > common_hit


# ---- ordering ------------------------------------------------------------------------


def test_pinned_documents_precede_every_unpinned_one():
    corpus = [
        _doc("src/auth/credentials.py", "credential credential credential\n"),
        _doc("unrelated.py", "nothing to see\n", pinned=True),
    ]
    ordered = rank(corpus, "credential")
    assert ordered[0].path == "unrelated.py", "pinning beats relevance"


def test_ranking_is_deterministic_under_corpus_reversal():
    forward = [d.path for d in rank(CORPUS, "credential")]
    backward = [d.path for d in rank(list(reversed(CORPUS)), "credential")]
    assert forward == backward


def test_ties_break_on_path_depth_then_path():
    corpus = [
        _doc("deep/nested/dir/file.py", "x\n"),
        _doc("shallow.py", "x\n"),
        _doc("also/mid.py", "x\n"),
    ]
    assert [d.path for d in rank(corpus, "")] == [
        "shallow.py",
        "also/mid.py",
        "deep/nested/dir/file.py",
    ]


def test_an_empty_query_still_produces_a_total_order():
    ordered = rank(CORPUS, "")
    assert len(ordered) == len(CORPUS)
    assert len({d.path for d in ordered}) == len(CORPUS)


# ---- the cache -----------------------------------------------------------------------


def test_a_reused_cache_produces_identical_ranking():
    cache = build_rank_cache(CORPUS)
    cold = [d.path for d in rank(CORPUS, "credential")]
    warm = [d.path for d in rank(CORPUS, "credential", rank_cache=cache)]
    assert cold == warm


def test_cache_records_corpus_wide_statistics():
    cache = build_rank_cache(CORPUS)
    assert cache.total_documents == len(CORPUS)
    assert cache.document_frequency["credential"] == 2
    assert cache.document_lengths["README.md"] > 0
