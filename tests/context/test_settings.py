"""Advanced reduction settings: validation, layering, and the config-file vocabulary."""

from __future__ import annotations

import dataclasses

import pytest

from anyinfer.context import SELECTION_ORDERS, ContextTuning


def test_defaults_are_the_shipped_behaviour():
    tuning = ContextTuning()
    assert tuning.selection_order == "rank"
    assert tuning.diversity == 0.0
    assert not tuning.query_expansion
    assert not tuning.split_identifiers
    assert not tuning.compact_fallback
    assert tuning.salience_weight == 0.0
    assert tuning.near_duplicate_threshold == 0.0
    assert tuning.ranking_is_default


def test_exact_duplicate_collapse_is_the_one_default_that_is_on():
    # Lossless and announced in the envelope, so it does not need opting into.
    assert ContextTuning().collapse_duplicates


def test_recommended_turns_on_the_lossy_settings():
    tuning = ContextTuning.recommended()
    assert tuning.selection_order == "density"
    assert tuning.diversity > 0
    assert tuning.query_expansion
    assert tuning.split_identifiers
    assert tuning.compact_fallback
    assert tuning.near_duplicate_threshold > 0
    assert not tuning.ranking_is_default


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("diversity", 1.5),
        ("diversity", -0.1),
        ("near_duplicate_threshold", 2.0),
        ("rollup_share", 0.0),
        ("rollup_share", 1.0),
        ("shingle_size", 0),
        ("chunk_tokens", 0),
        ("salience_iterations", 0),
        ("expansion_terms", -1),
        ("salience_weight", -1.0),
        ("selection_order", "cheapest"),
        ("expansion_weight", float("nan")),
    ],
)
def test_out_of_range_settings_are_rejected(field, value):
    with pytest.raises(ValueError, match=field.split("_")[0]):
        ContextTuning(**{field: value})


def test_from_mapping_rejects_unknown_names_rather_than_ignoring_them():
    with pytest.raises(ValueError, match="unknown context setting"):
        ContextTuning.from_mapping({"diversty": 0.5})


def test_from_mapping_type_checks_each_field():
    with pytest.raises(ValueError, match="must be true or false"):
        ContextTuning.from_mapping({"query_expansion": "yes"})
    with pytest.raises(ValueError, match="must be an integer"):
        ContextTuning.from_mapping({"expansion_terms": 2.5})
    with pytest.raises(ValueError, match="must be a number"):
        ContextTuning.from_mapping({"diversity": "high"})
    with pytest.raises(ValueError, match="must be one of"):
        ContextTuning.from_mapping({"selection_order": "cheapest"})


def test_from_mapping_rejects_bool_where_a_number_belongs():
    # True == 1 in Python; a config file that says `true` for a count is a mistake.
    with pytest.raises(ValueError, match="must be an integer"):
        ContextTuning.from_mapping({"expansion_terms": True})


def test_merged_ignores_unset_overrides():
    base = ContextTuning(diversity=0.4, query_expansion=True)
    merged = base.merged(diversity=None, compact_fallback=True)
    assert merged.diversity == 0.4
    assert merged.query_expansion
    assert merged.compact_fallback


def test_mapping_round_trips():
    tuning = ContextTuning.recommended()
    assert ContextTuning.from_mapping(tuning.to_mapping()) == tuning


def test_every_field_is_expressible_in_a_config_file():
    # The config block, the CLI flags, and the keyword argument are one vocabulary; a
    # field that cannot round-trip through a mapping would silently break that.
    names = {field.name for field in dataclasses.fields(ContextTuning)}
    assert set(ContextTuning().to_mapping()) == names
    assert set(SELECTION_ORDERS) == {"rank", "density"}
