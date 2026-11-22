"""The v8 LLM table, gated as v7's is. Round 77.

v8 is v7 plus ``photo_backup`` (Round 76). Its fourteen old families are identical to
v7's by id, so each run's v8 cache was seeded from its v7 cache and only the 40 new dev
moments were sent to a model. Every v8 decision on an old-family moment must equal the
same run's v7 decision.
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
from tactbench.schema import pair_key

RUNS = load_results("v8")
MODELS = sorted({name.split(":", 2)[2] for name in RUNS})
NEW = {"photo_backup"}
V7 = load_results("v7")


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_v8_run_is_complete(name):
    ids = [d.moment_id for d in RUNS[name]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate decisions"
    assert set(ids) == {i.moment.id for i in load("v8", "dev")}, f"{name}: incomplete run"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_no_v8_run_contains_a_failed_call(name):
    failed = [d.moment_id for d in RUNS[name] if (d.rationale or "").startswith("call failed")]
    assert not failed, f"{name}: {len(failed)} calls failed"


@pytest.mark.parametrize("model", MODELS)
def test_every_v8_model_has_both_variants(model):
    for variant in ("naive", "rubric"):
        assert f"llm:{variant}:{model}" in RUNS, f"{model}: no v8 {variant} run"


def test_every_v7_run_was_repeated_on_v8():
    assert set(RUNS) == set(V7) and len(RUNS) == 28


@pytest.mark.parametrize("name", sorted(RUNS))
def test_old_family_decisions_are_exactly_v7s(name):
    """The seeded cache must not have changed or dropped a single old-family answer."""
    v7 = {d.moment_id: d.model_dump() for d in V7[name]}
    family = {i.moment.id: i.moment.family for i in load("v8", "dev")}
    old = [d for d in RUNS[name] if family[d.moment_id] not in NEW]
    assert len(old) == len(v7)
    assert all(d.model_dump() == v7[d.moment_id] for d in old), name


def test_v8_runs_and_readme_rows_correspond_one_to_one():
    rows = _readme_rows("v8")
    assert set(rows) == set(RUNS)


def test_every_v8_readme_figure_equals_a_fresh_rescore():
    rows = _readme_rows("v8")
    bar = pair_blind_ics(load("v8", "dev"))
    stale = []
    for card, unparsed, pairs in scorecards("v8"):
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
            if abs(float(quoted) - float(actual)) > tol + 1e-9:  # float edge, e.g. 0.1545
                stale.append(f"{card.policy}.{label}: README {quoted}, actual {actual:.3f}")
    assert not stale, "README v8 LLM table is stale; run `tactbench results --version v8`"


class TestTheReadmeV8Claims:
    """Every figure in the README's v8 claims block, recomputed."""

    @staticmethod
    def _block() -> str:
        text = (Path(__file__).parent.parent / "README.md").read_text()
        block = text.split("<!-- v8-claims:start -->")[1].split("<!-- v8-claims:end -->")[0]
        return " ".join(block.split())

    @staticmethod
    def _split_pairs():
        items = {i.moment.id: i for i in load("v8", "dev") if i.moment.family in NEW}
        out = {}
        for name, ds in RUNS.items():
            by_pair: dict = {}
            for d in ds:
                if d.moment_id in items:
                    by_pair.setdefault(pair_key(d.moment_id), {})[
                        items[d.moment_id].label.should_surface
                    ] = d.surface
            right = sum(p[True] and not p[False] for p in by_pair.values())
            back = sum(p[False] and not p[True] for p in by_pair.values())
            out[name] = (right, back, len(by_pair))
        return items, out

    def test_constant_runs(self):
        items, _ = self._split_pairs()
        runs = {n: [d for d in ds if d.moment_id in items] for n, ds in RUNS.items()}
        constant = [ds for ds in runs.values() if len({d.surface for d in ds}) == 1]
        silent = sum(not ds[0].surface for ds in constant)
        assert len(items) == 40 and (len(constant), silent) == (19, 8)
        block = self._block()
        assert "**19** of the 28 runs give every one of its 40 moments the same answer" in block
        assert "(**8** never speak, **11** always do)" in block

    def test_best_pairs(self):
        from math import comb

        _, split = self._split_pairs()
        top = max(r for r, _, _ in split.values())
        best = [n for n, (r, _, _) in split.items() if r == top]
        assert best == ["llm:rubric:smollm2-1.7b"] and split[best[0]] == (4, 0, 20)
        assert comb(4, 4) / 2**4 == 0.0625
        block = self._block()
        assert "SmolLM2-1.7B with the rubric gets **4** pairs right and **0** backwards" in block
        assert "at even odds that is p=0.0625" in block

    def test_split_pairs_across_runs(self):
        _, split = self._split_pairs()
        right = sum(r for r, _, _ in split.values())
        back = sum(b for _, b, _ in split.values())
        assert (right + back, right, back) == (18, 11, 7)
        block = self._block()
        assert "of the **18** pairs answered differently on their two sides, **11** are" in block
        assert "right and **7** backwards" in block

    def test_nothing_else_moves(self):
        c7 = {c.policy: (c, u) for c, u, _ in scorecards("v7")}
        c8 = {c.policy: (c, u) for c, u, _ in scorecards("v8")}
        above7 = {p for p, (c, _) in c7.items() if c.ics_normalized > 0}
        above8 = {p for p, (c, _) in c8.items() if c.ics_normalized > 0}
        inc7 = {p for p, (_, u) in c7.items() if u > MAX_UNPARSED}
        inc8 = {p for p, (_, u) in c8.items() if u > MAX_UNPARSED}
        assert above7 == above8 and len(above8) == 8
        assert inc7 == inc8 and len(inc8) == 1
        rev = tie = 0
        for x, y in combinations(sorted(c8), 2):
            a = (c7[x][0].ics > c7[y][0].ics) - (c7[x][0].ics < c7[y][0].ics)
            b = (c8[x][0].ics > c8[y][0].ics) - (c8[x][0].ics < c8[y][0].ics)
            rev += a * b < 0
            tie += a != b and a * b == 0
        assert (rev, tie) == (0, 1)
        block = self._block()
        assert "The same **8** runs beat silence as on v7, the same one is" in block
        assert "of the 378 pairs of runs **0** are reversed and **1** changes" in block
