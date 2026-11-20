"""Dataset v2: v1's generator at 32 pairs per family. Round 37, queue item E.

Round 36 found the positional leak is the pair count: at 20 pairs per family, frames
holding three pairs are 2:1 by clause order, and a positional probe learns the
majority. At a multiple of 16 every (family, frame) cell is balanced. v2 is the same
generator and seed at 32 pairs -- no code change -- so v1, and the LLM results
measured on it, stay exactly as published. These assert the standing invariants on
v2 that the v1 suite asserts on v1.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

import pytest

from tactbench.audit import lexical_leakage, ngram_leakage, positional_leakage
from tactbench.dataset.generate import FRAMES, HELD_OUT_FRAMES, generate
from tactbench.dataset.loader import load
from tactbench.metrics import score
from tactbench.policies.skyline import SkylinePolicy
from tactbench.runner import evaluate, pair_blind_ics
from tactbench.schema import Decision, frame_of, pair_key, policy_view

SEED, PAIRS = 20260726, 32


def _split(items, held):
    return [i for i in items if (frame_of(i.moment) in HELD_OUT_FRAMES) == held]


def test_the_committed_v2_splits_are_reproducible():
    """CI's reproducibility job rebuilds only v1."""
    for split, held in (("dev", False), ("test", True)):
        assert [i.model_dump() for i in load("v2", split)] == [
            i.model_dump() for i in _split(generate(PAIRS, SEED), held)
        ]


def test_sizes():
    assert (len(load("v2", "dev")), len(load("v2", "test"))) == (360, 216)


def test_every_v2_cell_is_order_balanced():
    """The property v1 lacks (R36's strict xfail)."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from test_metrics import TestOrderBalancePrecondition as T

    for split in ("dev", "test"):
        c = Counter(
            (i.moment.family, frame_of(i.moment), T._privileged_first(i))
            for i in load("v2", split)
            if i.label.should_surface
        )
        cells = {(f, fr) for f, fr, _ in c}
        assert all(c[(f, fr, True)] == c[(f, fr, False)] for f, fr in cells), split


@pytest.mark.parametrize("family", sorted(FRAMES))
def test_gated_probes_at_chance(family):
    dev = [i for i in load("v2", "dev") if i.moment.family == family]
    assert lexical_leakage(dev).exploitable_accuracy == pytest.approx(0.5)
    assert ngram_leakage(dev).exploitable_accuracy == pytest.approx(0.5)


def test_the_structural_positional_leak_is_gone():
    """What v2 fixes, and only that. ``driving`` -- whose deciders hold no drawn
    entity, so the order imbalance showed as a fixed 63.3% -- reads exactly chance
    (on every seed, per the experiment); overall is under the bound. Per-family
    readings for other families are noise-dominated at this size (see the doc gate
    below), so they are not asserted. ``finance`` was in this test until review: it
    reads 50.0% on the shipped seed only, 50.0-70.0% across seeds."""
    dev = load("v2", "dev")
    driving = [i for i in dev if i.moment.family == "driving"]
    assert positional_leakage(driving).exploitable_accuracy == pytest.approx(0.5)
    assert positional_leakage(dev).exploitable_accuracy < 0.60


def test_pairs_differ_only_in_the_decider_as_a_policy_sees_them():
    for split in ("dev", "test"):
        pairs = defaultdict(list)
        for i in load("v2", split):
            pairs[pair_key(i.moment.id)].append(i)
        for key, (a, b) in pairs.items():
            va = policy_view(a.moment).model_dump(exclude={"id"})
            vb = policy_view(b.moment).model_dump(exclude={"id"})
            assert sorted(va["signals"][-1].pop("content").split()) == sorted(
                vb["signals"][-1].pop("content").split()
            ), key
            assert va == vb, key


def test_v2_stays_solvable_and_the_skyline_clears_the_pair_blind_bar():
    for split in ("dev", "test"):
        items = load("v2", split)
        card = evaluate(SkylinePolicy(), items)
        assert card.ics == 0.0 and card.hard_violations == 0
        assert card.ics < pair_blind_ics(items)


def test_no_single_word_policy_reaches_the_pair_blind_bar():
    for split in ("dev", "test"):
        items = load("v2", split)
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


def test_the_dataset_doc_quotes_what_the_experiment_prints():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        [sys.executable, str(root / "experiments" / "order_balance_probe.py")],
        capture_output=True, text=True, check=True, cwd=root,
    ).stdout  # fmt: skip

    def row(n, name):
        m = re.search(
            rf"n={n} {name}\s+observed\s+([\d.]+)%\s+(\d+)/20\s+null\s+([\d.]+)%\s+(\d+)/20", out
        )
        return m.groups()

    def cells(n):
        return re.search(
            rf"n={n} family cells above 60%: observed (\d+)/180, null (\d+)/180", out
        ).groups()

    doc = (root / "docs" / "DATASET.md").read_text()
    o20, o32 = row(20, "overall"), row(32, "overall")
    c32 = row(32, "commerce")
    expect = [
        rf"median is \*\*{o20[0]}%\*\* and it exceeds 60% on \*\*{o20[1]} of 20\*\*",
        rf"against a null of {o20[2]}% and {o20[3]} of 20",
        rf"At 32 pairs it is \*\*{o32[0]}%\*\*, {o32[1]} of 20",
        rf"below the null's {o32[2]}%",
        rf"\*\*{cells(20)[1]} of\s+180\*\* at 20 pairs and \*\*{cells(32)[1]} of 180\*\* at 32; "
        rf"observed is {cells(20)[0]} and {cells(32)[0]}",
        rf"\(11 of 20\), matches its own null \({c32[3]} of 20\)",
    ]
    assert c32[1] == "11"
    for pattern in expect:
        assert len(re.findall(pattern, doc)) == 1, pattern
