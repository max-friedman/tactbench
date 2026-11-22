"""The v9 LLM table, gated as v8's is. Round 81.

v9 is v8 plus ``dinner_booking`` (Round 80). Its fifteen old families are identical to
v8's by id, so each run's v9 cache was seeded from its v8 cache and only the 40 new dev
moments were sent to a model. Every v9 decision on an old-family moment must equal the
same run's v8 decision.
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

RUNS = load_results("v9")
MODELS = sorted({name.split(":", 2)[2] for name in RUNS})
NEW = {"dinner_booking"}
V8 = load_results("v8")


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_v9_run_is_complete(name):
    ids = [d.moment_id for d in RUNS[name]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate decisions"
    assert set(ids) == {i.moment.id for i in load("v9", "dev")}, f"{name}: incomplete run"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_no_v9_run_contains_a_failed_call(name):
    failed = [d.moment_id for d in RUNS[name] if (d.rationale or "").startswith("call failed")]
    assert not failed, f"{name}: {len(failed)} calls failed"


@pytest.mark.parametrize("model", MODELS)
def test_every_v9_model_has_both_variants(model):
    for variant in ("naive", "rubric"):
        assert f"llm:{variant}:{model}" in RUNS, f"{model}: no v9 {variant} run"


def test_every_v8_run_was_repeated_on_v9():
    assert set(RUNS) == set(V8) and len(RUNS) == 28


@pytest.mark.parametrize("name", sorted(RUNS))
def test_old_family_decisions_are_exactly_v8s(name):
    """The seeded cache must not have changed or dropped a single old-family answer."""
    v8 = {d.moment_id: d.model_dump() for d in V8[name]}
    family = {i.moment.id: i.moment.family for i in load("v9", "dev")}
    old = [d for d in RUNS[name] if family[d.moment_id] not in NEW]
    assert len(old) == len(v8)
    assert all(d.model_dump() == v8[d.moment_id] for d in old), name


def test_v9_runs_and_readme_rows_correspond_one_to_one():
    rows = _readme_rows("v9")
    assert set(rows) == set(RUNS)


def test_every_v9_readme_figure_equals_a_fresh_rescore():
    rows = _readme_rows("v9")
    bar = pair_blind_ics(load("v9", "dev"))
    stale = []
    for card, unparsed, pairs in scorecards("v9"):
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
    assert not stale, "README v9 LLM table is stale; run `tactbench results --version v9`"


class TestTheReadmeV9Claims:
    """Every figure in the README's v9 claims block, recomputed."""

    @staticmethod
    def _block() -> str:
        text = (Path(__file__).parent.parent / "README.md").read_text()
        block = text.split("<!-- v9-claims:start -->")[1].split("<!-- v9-claims:end -->")[0]
        return " ".join(block.split())

    @staticmethod
    def _split_pairs():
        items = {i.moment.id: i for i in load("v9", "dev") if i.moment.family in NEW}
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
        assert len(items) == 40 and (len(constant), silent) == (21, 11)
        block = self._block()
        assert "**21** of the 28 runs give every one of its 40 moments the same answer" in block
        assert "(**11** never speak, **10** always do)" in block

    def test_best_pairs(self):
        _, split = self._split_pairs()
        top = max(r for r, _, _ in split.values())
        best = [n for n, (r, _, _) in split.items() if r == top]
        assert best == ["llm:naive:mistral-7b"] and split[best[0]] == (3, 4, 20)
        runner_up = max(r for n, (r, _, _) in split.items() if n not in best)
        assert runner_up == 1
        block = self._block()
        assert "the best is 3 of 20 pairs, with 4 backwards" in block
        assert "Mistral-7B naive gets **3** pairs right and **4** backwards" in block
        assert "no other run gets more than **1** right" in block

    def test_split_pairs_across_runs(self):
        _, split = self._split_pairs()
        right = sum(r for r, _, _ in split.values())
        back = sum(b for _, b, _ in split.values())
        assert (right + back, right, back) == (18, 5, 13)
        block = self._block()
        assert (
            "of the **18** pairs answered differently on their two sides, **5** are right" in block
        )
        assert "and **13** backwards" in block

    def test_nothing_else_moves(self):
        c8 = {c.policy: (c, u) for c, u, _ in scorecards("v8")}
        c9 = {c.policy: (c, u) for c, u, _ in scorecards("v9")}
        above8 = {p for p, (c, _) in c8.items() if c.ics_normalized > 0}
        above9 = {p for p, (c, _) in c9.items() if c.ics_normalized > 0}
        inc8 = {p for p, (_, u) in c8.items() if u > MAX_UNPARSED}
        inc9 = {p for p, (_, u) in c9.items() if u > MAX_UNPARSED}
        assert above8 == above9 and len(above9) == 8
        assert inc8 == inc9 and len(inc9) == 1
        rev = tie = 0
        for x, y in combinations(sorted(c9), 2):
            a = (c8[x][0].ics > c8[y][0].ics) - (c8[x][0].ics < c8[y][0].ics)
            b = (c9[x][0].ics > c9[y][0].ics) - (c9[x][0].ics < c9[y][0].ics)
            rev += a * b < 0
            tie += a != b and a * b == 0
        assert (rev, tie) == (0, 0)
        block = self._block()
        assert "The same **8** runs beat silence as on v8, the same one is" in block
        assert "of the 378 pairs of runs **0** are reversed and **0** change" in block
