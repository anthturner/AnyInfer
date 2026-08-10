"""Ranking settings: identifier splitting, query expansion, and corpus centrality."""

from __future__ import annotations

from anyinfer.context import (
    ContextDocument,
    ContextTuning,
    build_rank_cache,
    expand_query,
    rank,
    salience,
    tokenize,
)

# ---- identifier splitting ------------------------------------------------------------


def test_splitting_keeps_the_compound_and_adds_its_parts():
    assert tokenize("resolveCredentials") == ["resolvecredentials"]
    split = tokenize("resolveCredentials", split_identifiers=True)
    assert split[0] == "resolvecredentials", "an exact match still scores highest"
    assert set(split) >= {"resolve", "credentials"}


def test_snake_case_splits():
    assert set(tokenize("resolve_credentials", split_identifiers=True)) >= {
        "resolve",
        "credentials",
    }


def test_acronyms_split_at_the_right_boundary():
    parts = tokenize("HTTPServerPool", split_identifiers=True)
    assert set(parts) >= {"http", "server", "pool"}
    assert "ttpserverpool" not in parts


def test_a_simple_word_gains_nothing():
    assert tokenize("credentials", split_identifiers=True) == ["credentials"]


def test_splitting_finds_a_document_a_word_query_would_miss():
    documents = [
        ContextDocument.of("a.py", "def resolveCredentials(): pass\n"),
        ContextDocument.of("b.py", "def unrelated(): pass\n" * 20),
    ]
    plain = rank(documents, "resolve credentials")
    split = rank(documents, "resolve credentials", tuning=ContextTuning(split_identifiers=True))
    assert plain[0].path == "a.py" or split[0].path == "a.py"
    assert split[0].path == "a.py"


def test_a_stale_cache_is_rebuilt_rather_than_scored_against():
    documents = [
        ContextDocument.of("a.py", "def resolveCredentials(): pass\n"),
        ContextDocument.of("b.py", "def other(): pass\n"),
    ]
    plain_cache = build_rank_cache(documents)
    tuning = ContextTuning(split_identifiers=True)
    # Passing a cache built the other way must not silently produce wrong ordering.
    assert rank(documents, "credentials", rank_cache=plain_cache, tuning=tuning) == rank(
        documents, "credentials", tuning=tuning
    )


# ---- query expansion -----------------------------------------------------------------


VOCABULARY = [
    ContextDocument.of(
        "docs/auth.md",
        "# Authentication\n\nThe login flow validates a session token before granting access.\n",
    ),
    ContextDocument.of(
        "src/login.py",
        "\n".join(
            f"def login_step_{i}(session, token):\n    return validate(session)" for i in range(20)
        ),
    ),
    ContextDocument.of(
        "src/colors.py",
        "\n".join(f"PALETTE_{i} = ('crimson', 'amber')" for i in range(20)),
    ),
]


def test_expansion_is_a_no_op_unless_enabled():
    cache = build_rank_cache(VOCABULARY)
    base = expand_query("authentication", VOCABULARY, cache=cache)
    assert set(base) == {"authentication"}


def test_expansion_reaches_terms_the_query_never_said():
    cache = build_rank_cache(VOCABULARY)
    tuning = ContextTuning(query_expansion=True)
    expanded = expand_query("authentication", VOCABULARY, cache=cache, tuning=tuning)
    assert "authentication" in expanded
    assert len(expanded) > 1
    assert any(term in expanded for term in ("login", "session", "token"))


def test_expansion_terms_weigh_less_than_the_query():
    cache = build_rank_cache(VOCABULARY)
    tuning = ContextTuning(query_expansion=True, expansion_weight=0.4)
    expanded = expand_query("authentication", VOCABULARY, cache=cache, tuning=tuning)
    for term, weight in expanded.items():
        if term != "authentication":
            assert weight <= 0.4


def test_expansion_finds_a_file_the_plain_query_cannot():
    tuning = ContextTuning(query_expansion=True)
    plain = rank(VOCABULARY, "authentication")
    expanded = rank(VOCABULARY, "authentication", tuning=tuning)
    assert plain.index(VOCABULARY[2]) >= 0
    # login.py never says "authentication"; expansion reaches it through auth.md.
    assert expanded[1].path == "src/login.py"


def test_an_empty_query_expands_to_nothing():
    cache = build_rank_cache(VOCABULARY)
    tuning = ContextTuning(query_expansion=True)
    assert expand_query("", VOCABULARY, cache=cache, tuning=tuning) == {}


def test_expansion_is_deterministic():
    cache = build_rank_cache(VOCABULARY)
    tuning = ContextTuning(query_expansion=True)
    first = expand_query("authentication", VOCABULARY, cache=cache, tuning=tuning)
    second = expand_query("authentication", list(reversed(VOCABULARY)), cache=cache, tuning=tuning)
    assert first == second


# ---- centrality ----------------------------------------------------------------------


GRAPH = [
    ContextDocument.of("app/zcore.py", "SHARED = 1\n"),
    ContextDocument.of("app/one.py", "from app.zcore import SHARED\n"),
    ContextDocument.of("app/two.py", "from app.zcore import SHARED\n"),
    ContextDocument.of("app/three.py", "from app.zcore import SHARED\nfrom app.one import x\n"),
    ContextDocument.of("app/leaf.py", "value = 2\n"),
]


def test_centrality_finds_what_the_corpus_depends_on():
    scores = salience(GRAPH)
    assert scores["app/zcore.py"] == 1.0
    assert scores["app/zcore.py"] > scores["app/leaf.py"]


def test_centrality_is_empty_when_no_edges_resolve():
    isolated = [ContextDocument.of(f"file{i}.txt", "prose\n") for i in range(3)]
    assert salience(isolated) == {}


def test_centrality_orders_a_corpus_with_no_query():
    plain = rank(GRAPH, "")
    central = rank(GRAPH, "", tuning=ContextTuning(salience_weight=1.0))
    assert central[0].path == "app/zcore.py"
    assert plain[0].path != "app/zcore.py", "the plain ranker falls through to the path tie-break"


def test_centrality_is_deterministic_under_reversal():
    tuning = ContextTuning(salience_weight=1.0)
    forward = [document.path for document in rank(GRAPH, "", tuning=tuning)]
    backward = [document.path for document in rank(list(reversed(GRAPH)), "", tuning=tuning)]
    assert forward == backward


def test_a_package_init_is_imported_by_its_directory_name():
    documents = [
        ContextDocument.of("pkg/__init__.py", "VALUE = 1\n"),
        ContextDocument.of("main.py", "import pkg\n"),
        ContextDocument.of("other.py", "x = 1\n"),
    ]
    scores = salience(documents)
    assert scores["pkg/__init__.py"] > scores["other.py"]


# ---- carry-over ----------------------------------------------------------------------


def test_carry_over_lifts_previously_sent_documents():
    documents = [
        ContextDocument.of("a.py", "alpha content\n"),
        ContextDocument.of("b.py", "beta content\n"),
    ]
    tuning = ContextTuning(carry_over_bonus=10.0)
    ordered = rank(documents, "", tuning=tuning, carry_over={"b.py"})
    assert ordered[0].path == "b.py"


def test_carry_over_does_nothing_without_the_bonus():
    documents = [
        ContextDocument.of("a.py", "alpha content\n"),
        ContextDocument.of("b.py", "beta content\n"),
    ]
    ordered = rank(documents, "", carry_over={"b.py"})
    assert ordered[0].path == "a.py"
