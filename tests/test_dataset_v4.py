"""Dataset v4: v3 plus an eleventh family, ``home_security``. Round 47, queue item 8.

Built the way v3 was (Round 45): the family is appended, so v1-v3 are unchanged and
every moment of v4's first ten families is identical to v3's -- asserted here, since
it is what lets v3's LLM decisions stand for those moments. The new family is held to
every invariant the old ones are, and to the two Round 45 added after pet_care leaked
on clause *character* length: frame lengths balance on dev and held-out frames, and a
length rule reads chance across seeds.
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
    HELD_OUT_FRAMES,
    LATER_FRAMES,
    ZONES,
    generate,
)
from tactbench.dataset.loader import load
from tactbench.metrics import score
from tactbench.policies.builtin import HeuristicPolicy
from tactbench.policies.skyline import _MOTION_ZONE, SkylinePolicy
from tactbench.runner import evaluate, pair_blind_ics
from tactbench.schema import Decision, frame_of, pair_key, policy_view

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
from clause_length_probe import FEATURES, feature_exploit, lean  # noqa: E402

SEED, PAIRS, FAMILIES = 20260726, 32, 11
NEW = ["home_security"]
SEEDS = range(SEED, SEED + 20)


def _split(items, held):
    return [i for i in items if (frame_of(i.moment) in HELD_OUT_FRAMES) == held]


def _family_dev(seed: int, family: str) -> list:
    return [
        i
        for i in _split(generate(PAIRS, seed, families=FAMILIES), held=False)
        if i.moment.family == family
    ]


def test_v4_is_v3_plus_one_appended_family():
    assert len(ALL_SCENARIOS) == FAMILIES
    assert [s.family for s in ALL_SCENARIOS[:FAMILIES]][-1:] == NEW
    assert set(NEW) <= set(LATER_FRAMES)


def test_the_committed_v4_splits_are_reproducible():
    built = generate(PAIRS, SEED, families=FAMILIES)
    for split, held in (("dev", False), ("test", True)):
        assert [i.model_dump() for i in load("v4", split)] == [
            i.model_dump() for i in _split(built, held)
        ]


def test_sizes():
    assert (len(load("v4", "dev")), len(load("v4", "test"))) == (440, 264)


@pytest.mark.parametrize("split", ["dev", "test"])
def test_every_old_family_moment_is_identical_to_v3(split):
    v3 = {i.moment.id: i.model_dump() for i in load("v3", split)}
    old = [i for i in load("v4", split) if i.moment.family not in NEW]
    assert len(old) == len(v3)
    assert all(i.model_dump() == v3[i.moment.id] for i in old)


def test_every_v4_cell_is_order_balanced():
    sys.path.insert(0, str(Path(__file__).parent))
    from test_metrics import TestOrderBalancePrecondition as T

    for split in ("dev", "test"):
        c = Counter(
            (i.moment.family, frame_of(i.moment), T._privileged_first(i))
            for i in load("v4", split)
            if i.label.should_surface
        )
        cells = {(f, fr) for f, fr, _ in c}
        assert len({f for f, _ in cells}) == FAMILIES, split
        assert all(c[(f, fr, True)] == c[(f, fr, False)] for f, fr in cells), split


@pytest.mark.parametrize("family", NEW)
def test_the_new_family_reads_chance_on_every_seed(family):
    for seed in range(SEED, SEED + 10):
        dev = _family_dev(seed, family)
        assert len(dev) == 40
        assert lexical_leakage(dev).exploitable_accuracy == pytest.approx(0.5), seed
        assert ngram_leakage(dev).exploitable_accuracy == pytest.approx(0.5), seed


@pytest.mark.parametrize("family", NEW)
def test_the_new_familys_positional_reading_matches_its_null_across_seeds(family):
    """As for pet_care (test_dataset_v3): one seed's reading is noise at 40 items."""
    obs, null = [], []
    for seed in SEEDS:
        dev = _family_dev(seed, family)
        obs.append(positional_leakage(dev).exploitable_accuracy)
        null += null_readings(dev, positional_leakage, draws=5, seed=seed)
    assert statistics.median(obs) <= statistics.median(null) + 0.05
    above = sum(x > 0.6 for x in obs) / len(obs)
    assert above <= sum(x > 0.6 for x in null) / len(null) + 0.15


def test_v4_overall_positional_is_under_its_null():
    """The shipped dev split reads 52.5% against a null median of 52.4% -- a 0.1-point
    excess on one seed, which is what v3's single-seed version of this check would
    see. One seed is the wrong statistic for a gap that size (R45 learned the same for
    pet_care's positional reading), so the null is compared over 20 seeds, where v4
    reads 51.7% against 53.1% on the first ten. The shipped split must still be under
    60%, and the shipped figure is stated in docs/DATASET.md, not hidden."""
    dev = load("v4", "dev")
    assert positional_leakage(dev).exploitable_accuracy < 0.60
    obs, null = [], []
    for seed in SEEDS:
        split = _split(generate(PAIRS, seed, families=FAMILIES), held=False)
        obs.append(positional_leakage(split).exploitable_accuracy)
        null += null_readings(split, positional_leakage, draws=3, seed=seed)
    assert statistics.median(obs) <= statistics.median(null)


def test_the_shipped_overall_positional_figure_in_the_docs():
    dev = load("v4", "dev")
    assert round(positional_leakage(dev).exploitable_accuracy, 3) == 0.525
    assert round(null_median(dev, positional_leakage), 3) == 0.524
    doc = " ".join((Path(__file__).parents[1] / "docs" / "DATASET.md").read_text().split())
    assert "52.5% against a null median of 52.4%" in doc


def test_pairs_differ_only_in_the_decider_as_a_policy_sees_them():
    for split in ("dev", "test"):
        pairs = defaultdict(list)
        for i in load("v4", split):
            pairs[pair_key(i.moment.id)].append(i)
        for key, (a, b) in pairs.items():
            va = policy_view(a.moment).model_dump(exclude={"id"})
            vb = policy_view(b.moment).model_dump(exclude={"id"})
            assert sorted(va["signals"][-1].pop("content").split()) == sorted(
                vb["signals"][-1].pop("content").split()
            ), key
            assert va == vb, key


def _zones(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", text.lower()) if w in ZONES]


def test_the_zone_pool_is_wide_and_shares_no_word_with_a_frame():
    assert len(ZONES) == len(set(ZONES)) == 40
    frame_words = {w.lower() for a, b in LATER_FRAMES["home_security"] for w in (a + b).split()}
    assert not frame_words & set(ZONES)


@pytest.mark.parametrize("split", ["dev", "test"])
def test_both_zones_appear_on_both_sides(split):
    """The travel lesson (R13): a name only ever in one role is a label."""
    for i in load("v4", split):
        if i.moment.family == "home_security":
            body, decider = i.moment.signals[0].content, i.moment.signals[-1].content
            assert len(set(_zones(decider))) == 2, i.moment.id
            assert set(_zones(decider)) == set(_zones(body)), i.moment.id


@pytest.mark.parametrize("split", ["dev", "test"])
def test_the_body_does_not_always_name_the_motion_zone_first(split):
    first = []
    for i in load("v4", split):
        if i.moment.family == "home_security":
            body = i.moment.signals[0].content
            motion = _MOTION_ZONE.search(body).group(1)
            first.append(_zones(body)[0] == motion)
    assert 0.3 <= sum(first) / len(first) <= 0.7


@pytest.mark.parametrize("family", NEW)
def test_the_new_family_balances_clause_length(family):
    frames = ALL_FRAMES[family]
    for held in (False, True):
        leans = [lean(a, b) for k, (a, b) in enumerate(frames) if (k in HELD_OUT_FRAMES) == held]
        assert sum(leans) == 0, (family, "held-out" if held else "dev", leans)


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_no_clause_feature_reads_the_label(feature):
    """Find the motion zone's clause, compare one feature with the other clause. The
    R47 review's -er rule read 90% dev / 83% test on the first draft; every feature
    must read chance -- median over 20 seeds, and the shipped held-out split."""
    readings = [
        feature_exploit(generate(PAIRS, seed, families=FAMILIES), "home_security", feature)
        for seed in SEEDS
    ]
    assert 0.45 <= statistics.median(readings) <= 0.55, (feature, sorted(readings))
    assert feature_exploit(load("v4", "test"), "home_security", feature) <= 0.6, feature


def test_the_clause_feature_check_would_catch_a_lean(monkeypatch):
    """The R47 review showed the first version of this check could not fail: it took
    the first zone in the body as the marker, and the body order is balanced. Pad every
    privileged clause and the length reading must jump."""
    padded = [(a.replace(" the ", " the whole ", 1), b) for a, b in ALL_FRAMES["home_security"]]
    monkeypatch.setitem(LATER_FRAMES, "home_security", padded)
    items = generate(PAIRS, SEED, families=FAMILIES)
    assert feature_exploit(items, "home_security", "chars") > 0.9


def test_v4_stays_solvable_and_the_skyline_clears_the_bar():
    for split in ("dev", "test"):
        items = load("v4", split)
        card = evaluate(SkylinePolicy(), items)
        assert card.ics == 0.0 and card.hard_violations == 0
        assert card.ics < pair_blind_ics(items)


def test_the_heuristic_does_not_solve_the_new_family():
    for split in ("dev", "test"):
        items = [i for i in load("v4", split) if i.moment.family in NEW]
        assert evaluate(HeuristicPolicy(), items).ics > 0.0, split


def test_no_single_word_policy_reaches_the_pair_blind_bar():
    for split in ("dev", "test"):
        items = load("v4", split)
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
