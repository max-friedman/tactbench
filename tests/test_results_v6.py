"""The v6 LLM table, gated as v5's is. Round 72.

v6 is v5 plus ``street_cleaning`` (Round 71). Its twelve old families are identical to
v5's by id, so each run's v6 cache was seeded from its v5 cache and only the 40 new dev
moments were sent to a model. That reuse is checked here, decision by decision: every
v6 decision on an old-family moment must equal the same run's v5 decision.
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

RUNS = load_results("v6")
MODELS = sorted({name.split(":", 2)[2] for name in RUNS})
NEW = {"street_cleaning"}
V5 = load_results("v5")


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_v6_run_is_complete(name):
    ids = [d.moment_id for d in RUNS[name]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate decisions"
    assert set(ids) == {i.moment.id for i in load("v6", "dev")}, f"{name}: incomplete run"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_no_v6_run_contains_a_failed_call(name):
    failed = [d.moment_id for d in RUNS[name] if (d.rationale or "").startswith("call failed")]
    assert not failed, f"{name}: {len(failed)} calls failed"


@pytest.mark.parametrize("model", MODELS)
def test_every_v6_model_has_both_variants(model):
    for variant in ("naive", "rubric"):
        assert f"llm:{variant}:{model}" in RUNS, f"{model}: no v6 {variant} run"


def test_every_v5_run_was_repeated_on_v6():
    assert set(RUNS) == set(V5) and len(RUNS) == 28


@pytest.mark.parametrize("name", sorted(RUNS))
def test_old_family_decisions_are_exactly_v5s(name):
    """The seeded cache must not have changed or dropped a single old-family answer."""
    v5 = {d.moment_id: d.model_dump() for d in V5[name]}
    family = {i.moment.id: i.moment.family for i in load("v6", "dev")}
    old = [d for d in RUNS[name] if family[d.moment_id] not in NEW]
    assert len(old) == len(v5)
    assert all(d.model_dump() == v5[d.moment_id] for d in old), name


def test_v6_runs_and_readme_rows_correspond_one_to_one():
    rows = _readme_rows("v6")
    assert set(rows) == set(RUNS)


def test_every_v6_readme_figure_equals_a_fresh_rescore():
    rows = _readme_rows("v6")
    bar = pair_blind_ics(load("v6", "dev"))
    stale = []
    for card, unparsed, pairs in scorecards("v6"):
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
    assert not stale, "README v6 LLM table is stale; run `tactbench results --version v6`"


class TestTheReadmeV6Claims:
    """Every figure in the README's v6 claims block, recomputed."""

    @staticmethod
    def _block() -> str:
        text = (Path(__file__).parent.parent / "README.md").read_text()
        block = text.split("<!-- v6-claims:start -->")[1].split("<!-- v6-claims:end -->")[0]
        return " ".join(block.split())

    @staticmethod
    def _family():
        items = {i.moment.id: i for i in load("v6", "dev") if i.moment.family in NEW}
        return items, {n: [d for d in ds if d.moment_id in items] for n, ds in RUNS.items()}

    @classmethod
    def _split_pairs(cls):
        items, runs = cls._family()
        out = {}
        for name, ds in runs.items():
            by_pair: dict = {}
            for d in ds:
                by_pair.setdefault(pair_key(d.moment_id), {})[
                    items[d.moment_id].label.should_surface
                ] = d.surface
            right = sum(p[True] and not p[False] for p in by_pair.values())
            back = sum(p[False] and not p[True] for p in by_pair.values())
            out[name] = (right, back, len(by_pair))
        return out

    def test_constant_runs_on_the_new_family(self):
        items, runs = self._family()
        assert len(items) == 40
        constant = [ds for ds in runs.values() if len({d.surface for d in ds}) == 1]
        silent = sum(not ds[0].surface for ds in constant)
        assert (len(constant), silent) == (21, 12)
        block = self._block()
        assert "**21** of the 28 runs give every one of its 40 moments the same answer" in block
        assert "(**12** never speak, **9** always do)" in block

    def test_best_pairs_and_its_odds(self):
        from math import comb

        split = self._split_pairs()
        best = max(split, key=lambda n: split[n][0])
        right, back, n = split[best]
        assert best == "llm:rubric:granite-3.3-2b" and (right, back, n) == (5, 1, 20)
        assert max(r for r, _, _ in split.values()) == 5
        assert all(r != 5 for name, (r, _, _) in split.items() if name != best)
        p = sum(comb(6, k) for k in (5, 6)) / 2**6
        assert round(p, 2) == 0.11
        block = self._block()
        assert "**5** of 20 pairs (Granite-3.3-2B with the rubric)" in block
        assert "5 right and 1 backwards; at even odds that is p≈0.11" in block

    def test_split_pairs_across_runs(self):
        split = self._split_pairs()
        right = sum(r for r, _, _ in split.values())
        back = sum(b for _, b, _ in split.values())
        assert (right + back, right, back) == (20, 12, 8)
        assert (
            "of the **20** pairs answered differently on their two sides, "
            "**12** are right and **8** backwards" in self._block()
        )

    def test_nothing_else_moves(self):
        c5 = {c.policy: (c, u) for c, u, _ in scorecards("v5")}
        c6 = {c.policy: (c, u) for c, u, _ in scorecards("v6")}
        assert set(c5) == set(c6)
        above5 = {p for p, (c, _) in c5.items() if c.ics_normalized > 0}
        above6 = {p for p, (c, _) in c6.items() if c.ics_normalized > 0}
        inc5 = {p for p, (_, u) in c5.items() if u > MAX_UNPARSED}
        inc6 = {p for p, (_, u) in c6.items() if u > MAX_UNPARSED}
        assert above5 == above6 and len(above6) == 7
        assert inc5 == inc6 and len(inc6) == 2
        changed = 0
        for x, y in combinations(sorted(c6), 2):
            s5 = (c5[x][0].ics > c5[y][0].ics) - (c5[x][0].ics < c5[y][0].ics)
            s6 = (c6[x][0].ics > c6[y][0].ics) - (c6[x][0].ics < c6[y][0].ics)
            changed += s5 != s6
        assert len(list(combinations(c6, 2))) == 378 and changed == 0
        block = self._block()
        assert "The same **7** runs beat silence as on v5, the same two are inconclusive" in block
        assert "of the 378 pairs of runs **0** change order" in block
