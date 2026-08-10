"""Selection settings: ordering, diversity, incremental reuse, and the plan."""

from __future__ import annotations

import pytest

from anyinfer.context import (
    ENVELOPE_FORMAT,
    ContextDocument,
    ContextTuning,
    Reduction,
    ReductionState,
    plan,
    select,
)

SMALL_RELEVANT = ContextDocument.of("src/auth/token.py", "def token():\n    return 'credential'\n")
BIG_RELEVANT = ContextDocument.of(
    "src/auth/credential_store.py",
    "\n".join(f"# credential note {i}\ndef store_{i}(): return 'credential'" for i in range(80)),
)
FILLER = [
    ContextDocument.of(
        f"src/misc/other_{index}.py",
        "\n".join(f"def unrelated_{index}_{i}(): return {i}" for i in range(20)),
    )
    for index in range(6)
]
CORPUS = [SMALL_RELEVANT, BIG_RELEVANT, *FILLER]


# ---- the envelope declares its version -----------------------------------------------


def test_the_envelope_declares_its_format():
    reduction = select(CORPUS[:2], "credential", max_tokens=100_000)
    assert f'<context format="{ENVELOPE_FORMAT}">' in reduction.text


def test_the_tiers_wrapper_declares_its_format_too():
    reduction = select(CORPUS, "credential", max_tokens=800, strategy="tiered")
    assert f'<context-tiers format="{ENVELOPE_FORMAT}"' in reduction.text


# ---- defaults change nothing ---------------------------------------------------------


@pytest.mark.parametrize("strategy", ["auto", "whole", "ranked", "tiered", "packed"])
def test_default_tuning_renders_exactly_what_no_tuning_does(strategy):
    without = select(CORPUS, "credential", max_tokens=1_500, strategy=strategy)
    with_default = select(
        CORPUS, "credential", max_tokens=1_500, strategy=strategy, tuning=ContextTuning()
    )
    assert without.text == with_default.text


# ---- the budget is never exceeded ----------------------------------------------------


@pytest.mark.parametrize("strategy", ["auto", "whole", "ranked", "tiered", "packed"])
@pytest.mark.parametrize("budget", [200, 700, 1_500, 4_000])
@pytest.mark.parametrize(
    "tuning",
    [ContextTuning(), ContextTuning.recommended()],
    ids=["default", "recommended"],
)
def test_a_reduction_never_overruns_its_budget(strategy, budget, tuning):
    reduction = select(CORPUS, "credential", max_tokens=budget, strategy=strategy, tuning=tuning)
    assert reduction.estimated_tokens <= budget
    assert reduction.total_bytes == len(reduction.text.encode("utf-8"))


# ---- selection order -----------------------------------------------------------------


def test_density_prefers_relevance_per_token():
    budget = 700
    by_rank = select(CORPUS, "credential", max_tokens=budget, strategy="ranked")
    by_density = select(
        CORPUS,
        "credential",
        max_tokens=budget,
        strategy="ranked",
        tuning=ContextTuning(selection_order="density"),
    )
    # The small relevant file costs a fraction of the big one and answers the query too.
    assert SMALL_RELEVANT in by_density.documents
    assert len(by_density.documents) >= len(by_rank.documents)


def test_density_ordering_is_deterministic_under_reversal():
    tuning = ContextTuning(selection_order="density")
    forward = select(CORPUS, "credential", max_tokens=900, tuning=tuning, strategy="ranked")
    backward = select(
        list(reversed(CORPUS)),
        "credential",
        max_tokens=900,
        tuning=tuning,
        strategy="ranked",
    )
    assert forward.text == backward.text


# ---- diversity -----------------------------------------------------------------------


NEAR_TWINS = [
    ContextDocument.of(
        f"src/twin_{index}.py",
        "\n".join(
            f"def handler_{i}(request):\n    return dispatch(request, {i})" for i in range(20)
        )
        + f"\n\ndef only_in_{index}(): pass\n",
    )
    for index in range(5)
] + [
    # Shares the query's vocabulary but almost none of the twins' body, so a
    # relevance-only ranker puts it last and a diversity-aware one does not.
    ContextDocument.of(
        "src/outlier.py",
        "\n".join(f"def compute_{i}(value):\n    return transform(value, {i})" for i in range(18))
        + "\n"
        + "\n".join(f"def handler_{i}(value): pass" for i in range(6)),
    )
]
DIVERSITY_QUERY = "handler dispatch"


def test_relevance_alone_fills_the_budget_with_near_twins():
    plain = select(NEAR_TWINS, DIVERSITY_QUERY, max_tokens=900, strategy="ranked")
    assert [document.path for document in plain.documents] == [
        "src/twin_0.py",
        "src/twin_1.py",
    ]


def test_diversity_makes_room_for_something_different():
    diverse = select(
        NEAR_TWINS,
        DIVERSITY_QUERY,
        max_tokens=900,
        strategy="ranked",
        tuning=ContextTuning(diversity=0.9),
    )
    paths = [document.path for document in diverse.documents]
    assert "src/outlier.py" in paths
    assert "src/twin_1.py" not in paths, "a second near-twin adds little"


def test_diversity_is_deterministic_under_reversal():
    tuning = ContextTuning(diversity=0.9)
    forward = select(NEAR_TWINS, DIVERSITY_QUERY, max_tokens=900, tuning=tuning, strategy="ranked")
    backward = select(
        list(reversed(NEAR_TWINS)),
        DIVERSITY_QUERY,
        max_tokens=900,
        tuning=tuning,
        strategy="ranked",
    )
    assert forward.text == backward.text


def test_pinned_documents_stay_ahead_of_every_ordering():
    pinned = ContextDocument.of("zzz/pinned.py", "def pinned(): pass\n", pinned=True)
    tuning = ContextTuning(selection_order="density", diversity=0.8)
    reduction = select(
        [*NEAR_TWINS, pinned],
        DIVERSITY_QUERY,
        max_tokens=900,
        strategy="ranked",
        tuning=tuning,
    )
    assert pinned in reduction.documents


# ---- incremental reuse ---------------------------------------------------------------


def test_an_unchanged_corpus_reproduces_the_previous_selection():
    tuning = ContextTuning(carry_over_bonus=2.0)
    first = select(CORPUS, "credential", max_tokens=1_200, strategy="ranked", tuning=tuning)
    second = select(
        CORPUS,
        "credential",
        max_tokens=1_200,
        strategy="ranked",
        tuning=tuning,
        previous=first.state(),
    )
    assert second.text == first.text
    assert second.carried_over == len(first.documents)


def test_carry_over_survives_an_unrelated_corpus_change():
    tuning = ContextTuning(carry_over_bonus=5.0)
    first = select(CORPUS, "credential", max_tokens=1_200, strategy="ranked", tuning=tuning)
    grown = [*CORPUS, ContextDocument.of("src/new_credential_helper.py", "credential " * 40)]
    second = select(
        grown,
        "credential",
        max_tokens=1_200,
        strategy="ranked",
        tuning=tuning,
        previous=first.state(),
    )
    kept = {document.path for document in first.documents} & {
        document.path for document in second.documents
    }
    assert kept, "the previous selection should not churn wholesale"
    assert second.carried_over == len(kept)


def test_a_changed_document_is_not_carried_over():
    state = ReductionState(entries=(("src/auth/token.py", "not-the-current-digest"),))
    assert state.unchanged(CORPUS) == frozenset()


def test_state_round_trips_through_a_reduction():
    reduction = select(CORPUS, "credential", max_tokens=1_200, strategy="ranked")
    state = reduction.state()
    assert len(state.entries) == len(reduction.documents)
    assert state.representation == reduction.representation
    assert state.unchanged(CORPUS) == {document.path for document in reduction.documents}


def test_carry_over_does_nothing_without_the_bonus():
    first = select(CORPUS, "credential", max_tokens=1_200, strategy="ranked")
    second = select(
        CORPUS, "credential", max_tokens=1_200, strategy="ranked", previous=first.state()
    )
    assert second.text == first.text  # deterministic anyway
    assert second.carried_over == len(first.documents)


# ---- plan ----------------------------------------------------------------------------


def test_a_plan_costs_every_deterministic_strategy():
    outcome = plan(CORPUS, "credential", max_tokens=1_500)
    assert [option.strategy for option in outcome.options] == [
        "whole",
        "ranked",
        "tiered",
        "packed",
    ]
    assert outcome.candidate_count == len(CORPUS)
    assert outcome.max_tokens == 1_500


def test_plan_figures_match_actually_running_the_strategy():
    outcome = plan(CORPUS, "credential", max_tokens=1_500)
    for option in outcome.options:
        actual = select(CORPUS, "credential", max_tokens=1_500, strategy=option.strategy)
        assert option.estimated_tokens == actual.estimated_tokens
        assert option.selected_count == len(actual.documents)
        assert option.total_bytes == actual.total_bytes
        assert option.binding_constraints == actual.binding_constraints


def test_a_plan_recommends_whole_when_everything_fits():
    outcome = plan(CORPUS, "credential", max_tokens=100_000)
    best = outcome.best()
    assert best is not None
    assert best.strategy == "whole"
    assert best.complete


def test_packed_never_claims_completeness_while_sending_fragments():
    outcome = plan(CORPUS, "credential", max_tokens=1_500)
    packed = outcome.option("packed")
    assert packed is not None
    if packed.partial_count:
        assert not packed.complete


def test_a_plan_projects_the_cost_of_distillation():
    outcome = plan(CORPUS, "credential", max_tokens=1_500)
    assert outcome.distill_chunks > 0
    assert outcome.distill_calls == outcome.distill_chunks + 1
    assert "distill" in outcome.summary()


def test_planning_spends_nothing_and_is_repeatable():
    first = plan(CORPUS, "credential", max_tokens=1_500)
    second = plan(CORPUS, "credential", max_tokens=1_500)
    assert first.metadata() == second.metadata()


def test_an_unknown_strategy_is_not_in_the_plan():
    assert plan(CORPUS, "credential", max_tokens=1_500).option("distill") is None


# ---- reporting -----------------------------------------------------------------------


def test_metadata_is_content_free():
    reduction = select(CORPUS, "credential", max_tokens=900, tuning=ContextTuning.recommended())
    record = reduction.metadata()
    assert "credential note" not in repr(record)
    assert set(record) >= {
        "collapsed_exact",
        "collapsed_near",
        "compacted_count",
        "partial_count",
        "carried_over",
        "complete",
    }


def test_an_empty_corpus_reduces_to_an_empty_envelope():
    reduction = select([], "anything", max_tokens=1_000)
    assert reduction.candidate_count == 0
    assert reduction.documents == ()
    assert isinstance(reduction, Reduction)
    assert reduction.complete
