"""The LLM table on held-out `v1/test`, gated as the dev tables are. Round 69.

Until R69 no model had been run on a held-out split (README limitation). These are
the same fourteen models and two prompts as `v4`/`v5` dev, on v1's held-out frames
(5-7): phrasings that occur nowhere in dev.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import pytest
from test_results import _readme_rows

from tactbench.cli import MAX_UNPARSED
from tactbench.dataset.loader import load
from tactbench.results import load_results, scorecards
from tactbench.runner import normalized, pair_blind_ics

VERSION, SPLIT = "v1", "test"
RUNS = load_results(VERSION, SPLIT)
DEV = load_results(VERSION, "dev")
MODELS = sorted({name.split(":", 2)[2] for name in RUNS})


def test_every_model_was_run_on_the_held_out_split():
    v5 = load_results("v5", "dev")
    assert set(RUNS) == set(v5) and len(RUNS) == 28


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_held_out_run_is_complete(name):
    ids = [d.moment_id for d in RUNS[name]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate decisions"
    assert set(ids) == {i.moment.id for i in load(VERSION, SPLIT)}, f"{name}: incomplete"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_no_held_out_run_contains_a_failed_call(name):
    failed = [d.moment_id for d in RUNS[name] if (d.rationale or "").startswith("call failed")]
    assert not failed, f"{name}: {len(failed)} calls failed"


@pytest.mark.parametrize("model", MODELS)
def test_every_model_has_both_variants(model):
    for variant in ("naive", "rubric"):
        assert f"llm:{variant}:{model}" in RUNS, f"{model}: no {variant} run"


def test_held_out_runs_and_readme_rows_correspond_one_to_one():
    assert set(_readme_rows("v1-test")) == set(RUNS)


def test_every_held_out_readme_figure_equals_a_fresh_rescore():
    rows = _readme_rows("v1-test")
    bar = pair_blind_ics(load(VERSION, SPLIT))
    stale = []
    for card, unparsed, pairs in scorecards(VERSION, SPLIT):
        row = rows[card.policy]
        for label, quoted, actual, tol in (
            ("ICS", row["ics"], card.ics, 0.05),
            ("vs silence", row["vs"].replace("−", "-"), card.ics_normalized, 0.05),
            ("vs pair-blind", row["bar"].replace("−", "-"), normalized(card.ics, bar), 0.05),
            ("prec@int", row["prec"], card.precision_at_interrupt, 0.0005),
            ("recall-hv", row["recall"], card.recall_high_value, 0.0005),
            ("ECE", row["ece"], card.ece, 0.0005),
            ("hard viol.", row["hv"], card.hard_violations, 0),
            ("spoke", row["spoke"], card.surfaced, 0),
            ("n", row["n"], card.n, 0),
            ("pairs", row["pairs"], pairs * 100, 0.05),
            ("unparsed", row["unparsed"], unparsed * 100, 0.05),
        ):
            if quoted == "—" or actual is None:
                if (quoted == "—") != (actual is None):
                    stale.append(f"{card.policy}.{label}: README {quoted}, actual {actual}")
                continue
            if abs(float(quoted) - float(actual)) > tol + 1e-9:
                stale.append(f"{card.policy}.{label}: README {quoted}, actual {actual:.3f}")
    assert not stale, "README held-out table is stale; run `tactbench results --split test`"


class TestTheReadmeHeldOutClaims:
    """Every figure in the README's held-out claims block, recomputed."""

    @staticmethod
    def _block() -> str:
        text = (Path(__file__).parent.parent / "README.md").read_text()
        block = text.split("<!-- v1-test-claims:start -->")[1].split("<!-- v1-test-claims:end -->")[
            0
        ]
        return " ".join(block.split())

    @staticmethod
    def _cards(split):
        return {c.policy: (c, u, p) for c, u, p in scorecards(VERSION, split)}

    def test_runs_on_both_splits(self):
        dev, test = self._cards("dev"), self._cards("test")
        both = set(dev) & set(test)
        assert set(dev) <= set(test) and len(both) == 22
        only = {p.split(":", 2)[2] for p in set(test) - both}
        assert only == {"mistral-7b", "phi-4-mini", "granite-3.3-2b"}
        block = self._block()
        assert "22 runs have a row on both v1 splits" in block
        assert (
            "(Mistral-7B, Phi-4-mini and Granite-3.3-2B were added after v1 dev was run)" in block
        )

    def test_verdicts_against_silence(self):
        dev, test = self._cards("dev"), self._cards("test")
        flips = [
            p for p in dev if (dev[p][0].ics_normalized > 0) != (test[p][0].ics_normalized > 0)
        ]
        assert flips == ["llm:naive:gemma-3-4b"]
        block = self._block()
        assert "**21** of the 22 keep their verdict" in block
        c_dev, c_test = dev[flips[0]][0], test[flips[0]][0]
        quoted = (
            f"**{c_dev.ics_normalized:+.1f}** on dev and **{c_test.ics_normalized:+.1f}** on test"
        )
        assert quoted.replace("-", "−") in block
        silence = test["llm:naive:qwen2.5-1.5b"][0]
        assert silence.ics_normalized == 0 and silence.surfaced == 0
        sil = {o.moment_id: o.cost for o in silence.outcomes}
        best_gain = max(sil[o.moment_id] - o.cost for o in c_test.outcomes)
        assert sil and c_test.ics + best_gain == silence.ics == 144.0
        assert (
            f"it scores {c_test.ics:.1f} against silence's {silence.ics:.1f}, and staying "
            f"quiet on any one of its {best_gain:.1f}-point catches would tie it with silence"
        ) in block

    def test_ordering_against_dev(self):
        dev, test = self._cards("dev"), self._cards("test")
        reversed_, tied = [], 0
        for x, y in combinations(sorted(dev), 2):
            a = (dev[x][0].ics > dev[y][0].ics) - (dev[x][0].ics < dev[y][0].ics)
            b = (test[x][0].ics > test[y][0].ics) - (test[x][0].ics < test[y][0].ics)
            if a * b < 0:
                reversed_.append((x, y))
            elif a != b:
                tied += 1
        assert len(list(combinations(dev, 2))) == 231
        assert len(reversed_) == 5 and tied == 8
        culprit = "llm:naive:gemma-3-4b"
        assert all(culprit in pair for pair in reversed_)
        others = {y if x == culprit else x for x, y in reversed_}
        ties = {p for p in others if test[p][0].ics_normalized == 0}
        assert len(ties) == 4 and others - ties == {"llm:naive:qwen2.5-3b"}
        block = self._block()
        assert "Of the 231 pairs of runs, **5** are reversed by ICS." in block
        assert "Every one is Gemma-3-4B naive moving past another run" in block
        assert "four that tie silence, and Qwen2.5-3B naive." in block
        assert "Another **8** are tied on one split and ordered on the other." in block

    def test_the_best_row_is_the_same(self):
        dev, test = self._cards("dev"), self._cards("test")
        best_dev = min(dev, key=lambda p: dev[p][0].ics)
        best_test = min(test, key=lambda p: test[p][0].ics)
        assert best_dev == best_test == "llm:rubric:gemma-3-4b"
        d, t = dev[best_dev][0].ics_normalized, test[best_test][0].ics_normalized
        assert (
            f"The best row is the same on both: Gemma-3-4B with the rubric, "
            f"**{d:+.1f}** on dev and **{t:+.1f}** on test"
        ) in self._block()

    def test_silence_bar_pairs_and_unparsed(self):
        test = self._cards("test")
        bar = pair_blind_ics(load(VERSION, SPLIT))
        above = [p for p in test if test[p][0].ics_normalized > 0]
        best_bar = max(normalized(c.ics, bar) for c, _, _ in test.values())
        best_pairs = max(test, key=lambda p: test[p][2])
        assert best_pairs == "llm:naive:llama-3.1-8b"
        assert test[best_pairs][0].ics_normalized < 0
        worst_unparsed = max(u for _, u, _ in test.values())
        assert worst_unparsed <= MAX_UNPARSED
        block = self._block()
        assert f"**{len(above)}** of the 28 runs beat silence" in block and len(above) == 7
        assert f"**{best_bar:+.1f}** against the".replace("-", "−") in block
        assert (
            f"**{test[best_pairs][2]:.1%}**, from Llama-3.1-8B naive, a run that loses to silence"
            in block
        )
        assert f"highest unparsed rate is **{worst_unparsed:.1%}**" in block

    def test_hard_violations_above_silence(self):
        dev, test = self._cards("dev"), self._cards("test")
        assert all(c.hard_violations == 0 for c, _, _ in dev.values() if c.ics_normalized > 0)
        dirty = {
            p: c.hard_violations
            for p, (c, _, _) in test.items()
            if c.ics_normalized > 0 and c.hard_violations
        }
        assert dirty == {"llm:naive:gemma-3-4b": 4}
        assert (
            "On test Gemma-3-4B naive beats silence with **4**, by the same thin margin."
            in self._block()
        )


def test_the_held_out_frames_are_the_ones_the_readme_names():
    from tactbench.dataset.generate import HELD_OUT_FRAMES

    text = (Path(__file__).parent.parent / "README.md").read_text()
    assert HELD_OUT_FRAMES == frozenset({5, 6, 7})
    assert "deciders use frames 5-7, which appear nowhere in dev" in " ".join(text.split())


def test_the_held_out_section_intro():
    text = " ".join((Path(__file__).parent.parent / "README.md").read_text().split())
    n = len(load(VERSION, SPLIT))
    assert n == 108 and len(RUNS) == 28
    assert f"All {len(RUNS)} runs on v1's held-out split (Round 69): {n} moments" in text
