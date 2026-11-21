"""Dataset v3: v2 plus a tenth family, ``pet_care``. Round 45, queue item 8.

The new family is appended to the generator's scenario list, never inserted, so
v1 and v2 are byte-identical to what was published and every moment of the first
nine families is identical in v3. That is asserted here, not assumed -- it is what
lets v2's LLM decisions on those moments stand for v3's. The new family is held to
every invariant the old ones are: role-permutation pairs, the gated probes at
chance, the positional probe at or under its label-swap null, order-balanced cells,
the skyline solving it and the heuristic not.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from tactbench.audit import lexical_leakage, ngram_leakage, null_median, positional_leakage
from tactbench.dataset.generate import (
    ALL_FRAMES,
    ALL_SCENARIOS,
    FRAMES,
    HELD_OUT_FRAMES,
    LATER_FRAMES,
    SCENARIOS,
    generate,
)
from tactbench.dataset.loader import load
from tactbench.metrics import score
from tactbench.policies.builtin import HeuristicPolicy
from tactbench.policies.skyline import SkylinePolicy
from tactbench.runner import evaluate, pair_blind_ics
from tactbench.schema import Decision, frame_of, pair_key, policy_view

SEED, PAIRS, FAMILIES = 20260726, 32, 10
NEW = sorted(LATER_FRAMES)


def _split(items, held):
    return [i for i in items if (frame_of(i.moment) in HELD_OUT_FRAMES) == held]


def test_the_family_lists_are_consistent():
    assert len(ALL_SCENARIOS) == FAMILIES and NEW == ["pet_care"]
    assert set(FRAMES) == {s.family for s in SCENARIOS}
    assert set(ALL_FRAMES) == {s.family for s in ALL_SCENARIOS}


def test_the_committed_v3_splits_are_reproducible():
    built = generate(PAIRS, SEED, families=FAMILIES)
    for split, held in (("dev", False), ("test", True)):
        assert [i.model_dump() for i in load("v3", split)] == [
            i.model_dump() for i in _split(built, held)
        ]


def test_sizes():
    assert (len(load("v3", "dev")), len(load("v3", "test"))) == (400, 240)


def test_the_default_still_builds_nine_families():
    assert {i.moment.family for i in generate(PAIRS, SEED)} == set(FRAMES)


@pytest.mark.parametrize("split", ["dev", "test"])
def test_every_old_family_moment_is_identical_to_v2(split):
    v2 = {i.moment.id: i.model_dump() for i in load("v2", split)}
    old = [i for i in load("v3", split) if i.moment.family not in NEW]
    assert len(old) == len(v2)
    assert all(i.model_dump() == v2[i.moment.id] for i in old)


def test_every_v3_cell_is_order_balanced():
    sys.path.insert(0, str(Path(__file__).parent))
    from test_metrics import TestOrderBalancePrecondition as T

    for split in ("dev", "test"):
        c = Counter(
            (i.moment.family, frame_of(i.moment), T._privileged_first(i))
            for i in load("v3", split)
            if i.label.should_surface
        )
        cells = {(f, fr) for f, fr, _ in c}
        assert {f for f, _ in cells} == set(ALL_FRAMES), split
        assert all(c[(f, fr, True)] == c[(f, fr, False)] for f, fr in cells), split


@pytest.mark.parametrize("family", NEW)
def test_the_new_family_reads_chance(family):
    dev = [i for i in load("v3", "dev") if i.moment.family == family]
    assert len(dev) == 40
    assert lexical_leakage(dev).exploitable_accuracy == pytest.approx(0.5)
    assert ngram_leakage(dev).exploitable_accuracy == pytest.approx(0.5)
    pos = positional_leakage(dev).exploitable_accuracy
    assert pos < 0.60 and pos <= null_median(dev, positional_leakage)


@pytest.mark.parametrize("family", NEW)
def test_the_new_family_reads_chance_across_seeds(family):
    """One seed at chance could be luck; the gated probes must hold on every seed."""
    for seed in range(SEED, SEED + 10):
        dev = [
            i
            for i in _split(generate(PAIRS, seed, families=FAMILIES), held=False)
            if i.moment.family == family
        ]
        assert lexical_leakage(dev).exploitable_accuracy == pytest.approx(0.5), seed
        assert ngram_leakage(dev).exploitable_accuracy == pytest.approx(0.5), seed


def test_v3_overall_positional_is_under_its_null():
    dev = load("v3", "dev")
    assert positional_leakage(dev).exploitable_accuracy < 0.60
    assert positional_leakage(dev).exploitable_accuracy <= null_median(dev, positional_leakage)


def test_pairs_differ_only_in_the_decider_as_a_policy_sees_them():
    for split in ("dev", "test"):
        pairs = defaultdict(list)
        for i in load("v3", split):
            pairs[pair_key(i.moment.id)].append(i)
        for key, (a, b) in pairs.items():
            va = policy_view(a.moment).model_dump(exclude={"id"})
            vb = policy_view(b.moment).model_dump(exclude={"id"})
            assert sorted(va["signals"][-1].pop("content").split()) == sorted(
                vb["signals"][-1].pop("content").split()
            ), key
            assert va == vb, key


def test_both_pet_names_appear_on_both_sides():
    """The travel lesson (R13): a name only ever in one role is a label."""
    for i in load("v3", "dev"):
        if i.moment.family == "pet_care":
            body, decider = i.moment.signals[0].content, i.moment.signals[-1].content
            names = set(re.findall(r"\b[A-Z][a-z]+\b", decider)) - {
                w for a, b in LATER_FRAMES["pet_care"] for w in (a + " " + b).split()
            }
            assert len(names) == 2 and all(n in body for n in names), i.moment.id


def test_v3_stays_solvable_and_the_skyline_clears_the_bar():
    for split in ("dev", "test"):
        items = load("v3", split)
        card = evaluate(SkylinePolicy(), items)
        assert card.ics == 0.0 and card.hard_violations == 0
        assert card.ics < pair_blind_ics(items)


def test_the_heuristic_does_not_solve_the_new_family():
    for split in ("dev", "test"):
        items = [i for i in load("v3", split) if i.moment.family in NEW]
        assert evaluate(HeuristicPolicy(), items).ics > 0.0, split


def test_no_single_word_policy_reaches_the_pair_blind_bar():
    for split in ("dev", "test"):
        items = load("v3", split)
        bar = pair_blind_ics(items)
        tokens = [
            set(re.findall(r"[a-z]+", " ".join(s.content for s in i.moment.signals).lower()))
            for i in items
        ]
        for word in sorted(set().union(*tokens)):
            for absent in (False, True):
                ds = [
                    Decision(moment_id=i.moment.id, surface=(word in t) != absent)
                    for i, t in zip(items, tokens, strict=True)
                ]
                assert score(items, ds, word).ics >= bar, (split, word, absent)
