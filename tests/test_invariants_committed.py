"""The dataset's structural invariants and the skyline's, on every committed split.
Round 62.

`tests/test_metrics.py` asserts these on ``generate(n_pairs_per_scenario=2..10)`` -- a
fresh build of the nine v1 families -- and v2-v5's test files repeat only some of
them. No test read a committed split whole for most of them. Measured in R62 before
this file: every structural property holds on all 11 splits, and the skyline holds on
10. On ``v2para`` it never spoke: 36 missed positives, ICS 96.0 = silence, because it
resolved deciders only from ``generate``'s frames and not the paraphrase frames.
"""

from __future__ import annotations

import pytest

from tactbench.dataset.loader import DATA_ROOT, load
from tactbench.policies.skyline import SkylinePolicy
from tactbench.runner import evaluate, silence_ics
from tactbench.schema import pair_key

SPLITS = sorted(
    (d.name, f.stem) for d in DATA_ROOT.iterdir() if d.is_dir() for f in d.glob("*.jsonl")
)


def _pairs(items):
    pairs: dict[str, list] = {}
    for item in items:
        pairs.setdefault(pair_key(item.moment.id), []).append(item)
    return pairs


def test_every_committed_split_is_listed():
    assert len(SPLITS) == 19 and ("v9", "dev") in SPLITS and ("v9", "test") in SPLITS


@pytest.mark.parametrize(("version", "split"), SPLITS)
def test_every_pair_is_a_role_permutation_of_one_moment(version, split):
    """CLAUDE.md rule 3: two sides, identical UserState, byte-identical body, same
    family, opposite labels -- and deciders that are the same words rearranged, with
    the same source, age and metadata (a permutation, not a rewrite)."""
    pairs = _pairs(load(version, split))
    assert pairs
    for key, pair in pairs.items():
        assert len(pair) == 2, key
        a, b = (p.moment for p in pair)
        assert a.user_state == b.user_state, key
        assert a.signals[:-1] == b.signals[:-1], key
        assert a.family == b.family, key
        assert pair[0].label.should_surface != pair[1].label.should_surface, key
        da, db = a.signals[-1], b.signals[-1]
        assert da.content != db.content, key
        assert sorted(da.content.split()) == sorted(db.content.split()), key
        assert (da.source, da.age_s, da.meta) == (db.source, db.age_s, db.meta), key


@pytest.mark.parametrize(("version", "split"), SPLITS)
def test_labels_are_balanced_tagged_and_carry_intents(version, split):
    items = load(version, split)
    speak = [i for i in items if i.label.should_surface]
    assert len(speak) * 2 == len(items)
    assert all(("near_miss" in i.moment.slices) != i.label.should_surface for i in items)
    assert all(i.label.acceptable_intents for i in speak)


@pytest.mark.parametrize(("version", "split"), SPLITS)
def test_the_skyline_agrees_with_every_label_and_clears_silence(version, split):
    """Labels stay self-consistent, and the task stays solvable (CLAUDE.md rule 2),
    with zero hard violations."""
    items = load(version, split)
    card = evaluate(SkylinePolicy(), items)
    assert (card.counts["fp"], card.counts["fn"], card.hard_violations) == (0, 0, 0)
    assert card.ics < silence_ics(items)
