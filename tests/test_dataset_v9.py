"""Dataset v9: v8 plus a sixteenth family, ``dinner_booking``. Queue item 8 (Round 80).

Built the way v3-v8 were: the family is appended, so v1-v8 are unchanged and every
moment of v9's first fifteen families is identical to v8's -- asserted here, since it
is what would let v8's LLM decisions stand for those moments. The new family is held
to every invariant ``photo_backup`` is (tests/test_dataset_v8.py): the clause-feature
checks Rounds 45, 47 and 52 added after leaks on clause length, on -er words and on
vowel counts, the marker-aware order check, the single-letter gate, the character
naive Bayes readings the R74 review added, the committed frame search, and the R76
review's polarity gate, which here is part of the search from the start.

The shared body is the user's calendar: dinner with friends tonight at one restaurant,
and another restaurant on Friday. The decider, a reservations app, says only which of
the two restaurants has confirmed a table and which has not: speak iff tonight's
restaurant has not. The logical form is the same as every family's (R74 review): the
decider labels one entity and, given the body, that label settles it. What the family
adds is a domain (dining out) and a deciding predicate (whether a booking is confirmed
or only requested).
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
    null_readings,
    positional_leakage,
)
from tactbench.dataset.generate import (
    ALL_FRAMES,
    ALL_SCENARIOS,
    HELD_OUT_FRAMES,
    LATER_FRAMES,
    RESTAURANTS,
    generate,
)
from tactbench.dataset.loader import load
from tactbench.metrics import score
from tactbench.policies.builtin import HeuristicPolicy
from tactbench.policies.skyline import _TONIGHT_RESTAURANT, SkylinePolicy
from tactbench.runner import evaluate, pair_blind_ics
from tactbench.schema import Decision, frame_of, pair_key, policy_view

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
from clause_length_probe import FEATURES, feature_exploit, lean  # noqa: E402

SEED, PAIRS, FAMILIES = 20260726, 32, 16
FAMILY = "dinner_booking"
NEW = [FAMILY]
SEEDS = range(SEED, SEED + 20)
#: The family's token-positional comparison runs over 60 seeds, as v5's-v8's do.
#: This probe cannot see clause order for a random marker; order is guarded by
#: ``test_tonights_restaurant_is_first_in_half_of_each_label``.
WIDE_SEEDS = range(SEED, SEED + 60)


def _split(items, held):
    return [i for i in items if (frame_of(i.moment) in HELD_OUT_FRAMES) == held]


def _family_dev(seed: int, family: str) -> list:
    return [
        i
        for i in _split(generate(PAIRS, seed, families=FAMILIES), held=False)
        if i.moment.family == family
    ]


def test_v9_is_v8_plus_one_appended_family():
    assert len(ALL_SCENARIOS) == FAMILIES  # the newest version pins the total
    assert [s.family for s in ALL_SCENARIOS[:FAMILIES]][-1:] == NEW
    assert [s.family for s in ALL_SCENARIOS[: FAMILIES - 1]][-1] == "photo_backup"
    assert set(NEW) <= set(LATER_FRAMES)
    assert set(ALL_FRAMES) == {s.family for s in ALL_SCENARIOS}


def test_the_committed_v9_splits_are_reproducible():
    built = generate(PAIRS, SEED, families=FAMILIES)
    for split, held in (("dev", False), ("test", True)):
        assert [i.model_dump() for i in load("v9", split)] == [
            i.model_dump() for i in _split(built, held)
        ]


def test_sizes():
    assert (len(load("v9", "dev")), len(load("v9", "test"))) == (640, 384)


@pytest.mark.parametrize("split", ["dev", "test"])
def test_every_old_family_moment_is_identical_to_v8(split):
    v8 = {i.moment.id: i.model_dump() for i in load("v8", split)}
    old = [i for i in load("v9", split) if i.moment.family not in NEW]
    assert len(old) == len(v8)
    assert all(i.model_dump() == v8[i.moment.id] for i in old)


def test_every_v9_cell_is_order_balanced():
    sys.path.insert(0, str(Path(__file__).parent))
    from test_metrics import TestOrderBalancePrecondition as T

    for split in ("dev", "test"):
        c = Counter(
            (i.moment.family, frame_of(i.moment), T._privileged_first(i))
            for i in load("v9", split)
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
    """As for water_notice through photo_backup: one seed's reading is noise at 40
    items."""
    obs, null = [], []
    for seed in WIDE_SEEDS:
        dev = _family_dev(seed, family)
        obs.append(positional_leakage(dev).exploitable_accuracy)
        null += null_readings(dev, positional_leakage, draws=5, seed=seed)
    assert statistics.median(obs) <= statistics.median(null) + 0.05
    above = sum(x > 0.6 for x in obs) / len(obs)
    assert above <= sum(x > 0.6 for x in null) / len(null) + 0.15


def _overall_positional(seeds) -> tuple[float, float]:
    """(median observed, median label-swap null) of the overall positional reading."""
    obs, null = [], []
    for seed in seeds:
        split = _split(generate(PAIRS, seed, families=FAMILIES), held=False)
        obs.append(positional_leakage(split).exploitable_accuracy)
        null += null_readings(split, positional_leakage, draws=3, seed=seed)
    return statistics.median(obs), statistics.median(null)


def test_v9_overall_positional_is_under_the_single_seed_bound():
    assert positional_leakage(load("v9", "dev")).exploitable_accuracy < 0.60


def test_v9_overall_positional_20_seed_median_is_under_its_null():
    """v5's form, unchanged. Positional is reported, not gated (Standing invariants)."""
    obs, null = _overall_positional(SEEDS)
    assert obs <= null


def test_v9_overall_positional_60_seed_median_is_under_its_null():
    """v6's gated form, over the same 60 seeds (v7 and v8 pass both)."""
    obs, null = _overall_positional(WIDE_SEEDS)
    assert obs <= null


def test_pairs_differ_only_in_the_decider_as_a_policy_sees_them():
    for split in ("dev", "test"):
        pairs = defaultdict(list)
        for i in load("v9", split):
            pairs[pair_key(i.moment.id)].append(i)
        for key, (a, b) in pairs.items():
            va = policy_view(a.moment).model_dump(exclude={"id"})
            vb = policy_view(b.moment).model_dump(exclude={"id"})
            assert sorted(va["signals"][-1].pop("content").split()) == sorted(
                vb["signals"][-1].pop("content").split()
            ), key
            assert va == vb, key


def _restaurants(text: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z]+", text) if w in RESTAURANTS]


def _tonight(item) -> str:
    return _TONIGHT_RESTAURANT.search(item.moment.signals[0].content).group(1)


def test_the_restaurant_pool_is_wide_and_shares_no_word_with_a_frame_or_pool():
    from tactbench.dataset import generate as g

    assert len(RESTAURANTS) == len(set(RESTAURANTS)) == 40
    assert all(len(s.split()) == 1 and s.isalpha() for s in RESTAURANTS)
    frame_words = {w.lower() for a, b in ALL_FRAMES[FAMILY] for w in (a + b).split()}
    assert not frame_words & {s.lower() for s in RESTAURANTS}
    pools = (
        g.PETS,
        g.ZONES,
        g.DISTRICTS,
        g.STREETS,
        g.REACHES,
        g.ALBUMS,
        g.COLLEAGUES,
        g.HOUSEHOLD,
        g.PHARMACY_OTHERS,
    )
    others = {w.lower() for pool in pools for name in pool for w in name.split()}
    assert not others & {s.lower() for s in RESTAURANTS}


def test_no_restaurant_name_is_a_word_of_the_body_templates():
    """A restaurant that is also a body word would make the body's token multiset
    depend on which restaurant was drawn where."""
    for split in ("dev", "test"):
        for i in load("v9", split):
            if i.moment.family == FAMILY:
                body = i.moment.signals[0].content
                assert len(_restaurants(body)) == 2, i.moment.id


def test_the_decider_says_nothing_about_tonight():
    """The body fixes which restaurant is tonight's and which is Friday's; the decider
    says only which booking is confirmed. So no frame shares a content word with any
    body the family renders (no "dinner", "tonight", "friends", "Friday", "calendar"):
    a frame that did would restate half of the body inside the decider."""
    sys.path.insert(0, str(Path(__file__).parent))
    from test_metrics import TestFrameDisjointness as T

    frame_words = {w for a, b in ALL_FRAMES[FAMILY] for w in T()._content(a) | T()._content(b)}
    body_words: set[str] = set()
    for split in ("dev", "test"):
        for i in load("v9", split):
            if i.moment.family == FAMILY:
                text = i.moment.signals[0].content
                for name in _restaurants(text):
                    text = text.replace(name, " ")
                body_words |= T()._content(text)
    assert frame_words and body_words
    assert not frame_words & body_words, sorted(frame_words & body_words)


def test_no_frame_addresses_the_user():
    """As for river_swim (R74): no frame says *you*, *your* or *home* -- *you* is the
    marker in three other families, and the heuristic reads it."""
    owned = {"you", "your", "yours", "home", "my", "mine", "our"}
    for a, b in ALL_FRAMES[FAMILY]:
        words = {w.lower().strip(".,") for w in (a + " " + b).split()}
        assert not words & owned, (a, b)


@pytest.mark.parametrize("split", ["dev", "test"])
def test_both_restaurants_appear_on_both_sides(split):
    """The travel lesson (R13): a name only ever in one role is a label."""
    for i in load("v9", split):
        if i.moment.family == FAMILY:
            body, decider = i.moment.signals[0].content, i.moment.signals[-1].content
            assert len(set(_restaurants(decider))) == 2, i.moment.id
            assert set(_restaurants(decider)) == set(_restaurants(body)), i.moment.id
            assert _tonight(i) in _restaurants(body), i.moment.id


@pytest.mark.parametrize("split", ["dev", "test"])
def test_the_body_does_not_always_name_tonights_restaurant_first(split):
    first = []
    for i in load("v9", split):
        if i.moment.family == FAMILY:
            first.append(_restaurants(i.moment.signals[0].content)[0] == _tonight(i))
    assert 0.3 <= sum(first) / len(first) <= 0.7


@pytest.mark.parametrize("family", NEW)
def test_the_new_family_balances_clause_length(family):
    frames = ALL_FRAMES[family]
    for held in (False, True):
        leans = [lean(a, b) for k, (a, b) in enumerate(frames) if (k in HELD_OUT_FRAMES) == held]
        assert sum(leans) == 0, (family, "held-out" if held else "dev", leans)


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_no_clause_feature_reads_the_label(feature):
    """Find tonight's restaurant's clause, compare one feature with the other clause;
    every feature must read chance -- median over 20 seeds, and the shipped held-out
    split, two-sided."""
    readings = [
        feature_exploit(generate(PAIRS, seed, families=FAMILIES), FAMILY, feature) for seed in SEEDS
    ]
    assert 0.45 <= statistics.median(readings) <= 0.55, (feature, sorted(readings))
    held = feature_exploit(load("v9", "test"), FAMILY, feature)
    assert abs(held - 0.5) <= 0.1, (feature, held)


def test_the_clause_feature_check_would_catch_a_lean(monkeypatch):
    """Pad every privileged clause and the length reading must jump (R47)."""
    padded = [(a.replace(" {who}", " whole {who}"), b) for a, b in ALL_FRAMES[FAMILY]]
    monkeypatch.setitem(LATER_FRAMES, FAMILY, padded)
    items = generate(PAIRS, SEED, families=FAMILIES)
    assert feature_exploit(items, FAMILY, "chars") > 0.9


def test_v9_stays_solvable_and_the_skyline_clears_the_bar():
    for split in ("dev", "test"):
        items = load("v9", split)
        card = evaluate(SkylinePolicy(), items)
        assert card.ics == 0.0 and card.hard_violations == 0
        assert card.ics < pair_blind_ics(items)


def test_the_heuristic_does_not_solve_the_new_family():
    for split in ("dev", "test"):
        items = [i for i in load("v9", split) if i.moment.family in NEW]
        assert evaluate(HeuristicPolicy(), items).ics > 0.0, split


def test_no_single_word_policy_reaches_the_pair_blind_bar():
    for split in ("dev", "test"):
        items = load("v9", split)
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


def _site_first(item) -> bool:
    """Is tonight's restaurant (read from the body, as the skyline reads it) named in
    the decider's first clause?"""
    first = item.moment.signals[-1].content.split(". ")[0]
    return first.rstrip(".").split()[-1] == _tonight(item)


def _order_rule(items) -> float:
    """ "Speak iff tonight's restaurant is in the first decider clause"."""
    chosen = [i for i in items if i.moment.family == FAMILY]
    return sum(_site_first(i) == i.label.should_surface for i in chosen) / len(chosen)


@pytest.mark.parametrize("split", ["dev", "test"])
def test_tonights_restaurant_is_first_in_half_of_each_label(split):
    """The marker-aware order check (R52 review): within each label, tonight's
    restaurant leads the decider exactly half the time, so the order rule reads exactly
    50%."""
    items = [i for i in load("v9", split) if i.moment.family == FAMILY]
    for label in (True, False):
        side = [i for i in items if i.label.should_surface == label]
        assert sum(map(_site_first, side)) * 2 == len(side), (split, label)
    assert _order_rule(items) == 0.5


def test_the_order_check_would_catch_a_fixed_order(monkeypatch):
    """Force the privileged clause first and the marker-aware rule must read 100%."""
    from tactbench.dataset.generate import Scenario

    original = Scenario.render_frame

    def privileged_first(self, frame, rng, idx=0):
        if self.family != FAMILY:
            return original(self, frame, rng, idx)
        return original(self, frame, rng, idx - idx % (2 * len(self.frames)))

    monkeypatch.setattr(Scenario, "render_frame", privileged_first)
    assert _order_rule(generate(PAIRS, SEED, families=FAMILIES)) == 1.0


_COUNTS = {
    "vowels": lambda c: sum(ch in "aeiou" for ch in c.lower()),
    "consonants": lambda c: sum(ch.isalpha() and ch not in "aeiou" for ch in c.lower()),
}


@pytest.mark.parametrize("feature", ["vowels", "consonants"])
def test_vowel_and_consonant_counts_read_chance(feature, monkeypatch):
    """The R52 leak class. Balanced by frame from the start; gated on the shipped splits."""
    import clause_length_probe as probe

    monkeypatch.setitem(probe.FEATURES, feature, _COUNTS[feature])
    for split in ("dev", "test"):
        assert feature_exploit(load("v9", split), FAMILY, feature) == 0.5, split


def test_the_vowel_gate_would_catch_a_lean(monkeypatch):
    """Lengthen every privileged clause by two vowels and the reading must jump."""
    import clause_length_probe as probe

    padded = [(a.replace(" {who}", "oo {who}"), b) for a, b in ALL_FRAMES[FAMILY]]
    monkeypatch.setitem(LATER_FRAMES, FAMILY, padded)
    monkeypatch.setitem(probe.FEATURES, "vowels", _COUNTS["vowels"])
    items = generate(PAIRS, SEED, families=FAMILIES)
    assert feature_exploit(items, FAMILY, "vowels") > 0.85


def _letters(clause: str) -> Counter:
    return Counter(ch for ch in clause.lower() if ch.isalpha())


def _letter_leaks(*splits) -> list[tuple[str, list[float]]]:
    """Letters whose "speak iff tonight's restaurant's clause has more of it" reads 70%
    or more (or 30% or less), the same way, on every split given."""
    leaks = []
    for letter in "abcdefghijklmnopqrstuvwxyz":
        readings = []
        for split_items in splits:
            score_, items = 0.0, [i for i in split_items if i.moment.family == FAMILY]
            for item in items:
                site = _tonight(item)
                clauses = [
                    c.rstrip(".").split() for c in item.moment.signals[-1].content.split(". ")
                ]
                mine = next(c for c in clauses if c[-1] == site)
                other = next(c for c in clauses if c is not mine)
                fm = _letters(" ".join(mine[:-1]))[letter]
                fo = _letters(" ".join(other[:-1]))[letter]
                score_ += 0.5 if fm == fo else float((fm > fo) == item.label.should_surface)
            readings.append(score_ / len(items))
        exploit = [0.5 + abs(r - 0.5) for r in readings]
        same_sign = all((r - 0.5) * (readings[0] - 0.5) > 0 for r in readings)
        if same_sign and min(exploit) >= 0.7:
            leaks.append((letter, readings))
    return leaks


def test_no_single_letter_count_reads_the_label_on_both_splits():
    """As on v6-v8: no letter's "speak iff tonight's restaurant's clause has more of it"
    may reach 70% (or fall to 30%) on dev and test both. Combinations are gated against
    an exact null in tests/test_letter_bag_null.py (R73)."""
    assert _letter_leaks(load("v9", "dev"), load("v9", "test")) == []


def test_the_single_letter_gate_would_catch_a_lean(monkeypatch):
    """Add a "z" to every privileged clause and the gate must name that letter."""
    padded = [(a.replace(" {who}", "z {who}"), b) for a, b in ALL_FRAMES[FAMILY]]
    monkeypatch.setitem(LATER_FRAMES, FAMILY, padded)
    items = generate(PAIRS, SEED, families=FAMILIES)
    assert "z" in [letter for letter, _ in _letter_leaks(items, items)]


def _v9_section() -> str:
    doc = (Path(__file__).parents[1] / "docs" / "DATASET.md").read_text()
    return " ".join(doc.split("### Dataset v9")[1].split("\n### ")[0].split())


def test_the_positional_figures_stated_in_the_docs():
    """Pins the shipped-seed, 20-seed and 60-seed overall readings, and the family's
    shipped reading, that DATASET.md's v9 section quotes (read from that section only,
    so a v8 figure cannot satisfy it)."""
    from tactbench.audit import null_median

    dev = load("v9", "dev")
    shipped = positional_leakage(dev).exploitable_accuracy
    family = [i for i in dev if i.moment.family == FAMILY]
    (obs, null), (obs60, null60) = _overall_positional(SEEDS), _overall_positional(WIDE_SEEDS)
    figures = (
        f"{shipped:.1%} against {null_median(dev, positional_leakage):.1%}",
        f"20-seed medians {obs:.1%} against {null:.1%}",
        f"60-seed medians {obs60:.2%} against {null60:.2%}",
        f"{positional_leakage(family).exploitable_accuracy:.1%} positional",
    )
    section = _v9_section()
    for figure in figures:
        assert figure in section, figure


@pytest.mark.parametrize("rep", ["letters", "pairs"])
def test_the_char_nb_readings_are_at_chance_against_the_null(rep):
    """The R74 review's character naive Bayes (letters and letter pairs, tagged by
    clause): dev->test, leave one frame out, and transfer from the other fifteen
    families. Required at p >= 0.05 against the exact orientation null, one-sided as R74
    quotes it and two-sided, as v8's are."""
    sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
    import char_nb_probe as nb

    for two_sided in (False, True):
        for reading, (observed, p) in nb.readings(FAMILY, rep, "v9", two_sided).items():
            assert p >= 0.05, (rep, reading, two_sided, observed, p)


def test_the_char_nb_figures_stated_in_the_docs():
    """Both representations' readings, pinned to the v9 section, two-sided p first."""
    sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
    import char_nb_probe as nb

    section = _v9_section()
    labels = {
        "dev->test": "dev→test",
        "leave-one-frame-out": "leaving one frame out",
        "transfer": "trained on the other fifteen families",
    }
    for rep in ("letters", "pairs"):
        one = nb.readings(FAMILY, rep, "v9")
        two = nb.readings(FAMILY, rep, "v9", two_sided=True)
        for reading, label in labels.items():
            observed, p1 = one[reading]
            p2 = two[reading][1]
            figure = (
                f"{rep}, {label}: **{observed:.1%}** (two-sided p={p2:.3f}; one-sided p={p1:.3f})"
            )
            assert figure in section, figure


def test_the_frame_search_is_committed_and_reproduces_the_shipped_frames():
    """As for v8: the search is ``experiments/frame_search_v9.py``; its top-ranked set
    must be the shipped frames, and the counts DATASET.md quotes must be what it prints."""
    sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
    import frame_search_v9 as fs

    result = fs.search()
    assert result["best"] == ALL_FRAMES[FAMILY]
    section = _v9_section()
    assert f"{result['candidates']} candidate frames" in section
    assert f"({result['balanced']:,} such sets)" in section
    assert f"strongest of {result['features']} cheap clause features" in section


def test_polarity_does_not_decide_the_family():
    """The R76 review's gate, applied from the start: on each split separately, the
    frames where "speak iff tonight's restaurant's clause alone is negated" is right
    must equal those where it is wrong (``experiments/negation_probe.py``); so it reads
    exactly half, and the reviewer's policy, pointed at this family, reads half too."""
    sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
    import negation_probe as neg

    r = neg.frame_polarity(FAMILY, "v9")
    for split in ("dev", "test"):
        counts = r[split]
        assert isinstance(counts, dict)
        assert counts["right"] == counts["wrong"], (split, counts)
        assert r[f"{split}_accuracy"] == 0.5, split
        assert neg.policy_accuracy(load("v9", split), FAMILY) == 0.5, split
    assert r["test"]["right"] < 3 and r["test"]["wrong"] < 3  # type: ignore[index]


#: A frame set that fails the polarity gate: eight of the search's candidates that
#: carry the negation on the privileged (unconfirmed) clause only.
ONE_SIDED = [
    ("Lacking a reserved slot at {who}", "Holding a reserved slot at {who}"),
    ("Unconfirmed so far at {who}", "Confirmed so far at {who}"),
    ("Uncertain of a table at {who}", "Certain of a table at {who}"),
    ("Tables held total zero at {who}", "Tables held total one at {who}"),
    ("Without a held table at {who}", "With a held table at {who}"),
    ("Seat promised by nobody at {who}", "Seat promised by staff at {who}"),
    ("Missing a firm booking at {who}", "Holding a firm booking at {who}"),
    ("Never approved was the request to {who}", "Promptly approved was the request to {who}"),
]


def test_the_polarity_gate_would_catch_one_sided_frames(monkeypatch):
    """Ship frames negated on the privileged side only: the polarity rule and the
    reviewer's policy must both read 100% on dev and on held-out test."""
    sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
    import letter_bag_probe as bag
    import negation_probe as neg

    monkeypatch.setitem(LATER_FRAMES, FAMILY, ONE_SIDED)
    monkeypatch.setitem(bag.ALL_FRAMES, FAMILY, ONE_SIDED)
    items = generate(PAIRS, SEED, families=FAMILIES)
    monkeypatch.setattr(neg, "load", lambda v, s: _split(items, held=(s == "test")))
    r = neg.frame_polarity(FAMILY, "v9")
    assert r["dev_accuracy"] == r["test_accuracy"] == 1.0
    assert r["dev"]["right"] == 5 and r["test"]["right"] == 3  # type: ignore[index]
    for held in (False, True):
        assert neg.policy_accuracy(_split(items, held), FAMILY) == 1.0
