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
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from tactbench.audit import (
    lexical_leakage,
    ngram_leakage,
    null_median,
    null_readings,
    positional_leakage,
)
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


SEEDS = range(SEED, SEED + 20)


def _family_dev(seed: int, family: str) -> list:
    return [
        i
        for i in _split(generate(PAIRS, seed, families=FAMILIES), held=False)
        if i.moment.family == family
    ]


@pytest.mark.parametrize("family", NEW)
def test_the_new_familys_positional_reading_matches_its_null_across_seeds(family):
    """Per-family positional readings at 40 items are noise-dominated (R37: under a
    label-swap null they exceed 60% in about half of family-seed cells), so one seed's
    reading proves nothing either way. Over 20 seeds the observed median must sit
    within 5 points of the null's, and the share of seeds above 60% within 15 points
    -- about 1.5 binomial sd at 20 seeds. Shipped pet_care: 60.0% vs 57.5%, 35% vs 27%.
    """
    obs, null = [], []
    for seed in SEEDS:
        dev = _family_dev(seed, family)
        obs.append(positional_leakage(dev).exploitable_accuracy)
        null += null_readings(dev, positional_leakage, draws=5, seed=seed)
    assert statistics.median(obs) <= statistics.median(null) + 0.05
    above = sum(x > 0.6 for x in obs) / len(obs)
    assert above <= sum(x > 0.6 for x in null) / len(null) + 0.15


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


@pytest.mark.parametrize("family", NEW)
def test_new_families_balance_clause_length(family):
    """Equal token counts are not enough: the privileged clause must not be the longer
    one more often than the shorter, on dev frames and on held-out frames separately.
    Round 45's first pet_care draft leaned 6-0 and a length rule read 90% on dev."""
    sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
    from clause_length_probe import lean

    frames = ALL_FRAMES[family]
    for held in (False, True):
        leans = [lean(a, b) for k, (a, b) in enumerate(frames) if (k in HELD_OUT_FRAMES) == held]
        assert sum(leans) == 0, (family, "held-out" if held else "dev", leans)


def test_the_pet_care_length_exploit_reads_chance_across_seeds():
    """The reviewer's exploit read 90% dev / 83% test on the first draft. On one seed
    it is noisy (the shipped dev reads 30%), so the median over 20 seeds is asserted."""
    sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
    from clause_length_probe import pet_care_exploit

    readings = [pet_care_exploit(generate(PAIRS, seed, families=FAMILIES)) for seed in SEEDS]
    assert 0.45 <= statistics.median(readings) <= 0.55, sorted(readings)


def test_the_body_does_not_always_name_the_skipped_pet_first():
    from tactbench.policies.skyline import _SKIPPED_PET

    first = []
    for i in load("v3", "dev"):
        if i.moment.family == "pet_care":
            body = i.moment.signals[0].content
            skipped = next(g for g in _SKIPPED_PET.search(body).groups() if g)
            names = re.findall(r"\b[A-Z][a-z]+\b", body.split(":", 1)[-1].split("—")[-1])
            first.append(names[0] == skipped)
    assert 0.3 <= sum(first) / len(first) <= 0.7


def test_the_dataset_doc_claims_about_old_families_clause_length():
    """DATASET.md: the dev-majority length rule transfers to held-out frames at or below
    50% in eight of the nine original families; deadline reads 83%."""
    sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
    from clause_length_probe import transfer

    held = {f: transfer(f)[1] for f in FRAMES}
    assert sorted(f for f, x in held.items() if x > 0.5) == ["deadline"]
    assert round(held["deadline"], 2) == 0.83
    doc = " ".join((Path(__file__).parents[1] / "docs" / "DATASET.md").read_text().split())
    assert "at or below 50% there in eight of the nine. `deadline` reads 83%" in doc
