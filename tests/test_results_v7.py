"""The v7 LLM table, gated as v6's is. Round 75.

v7 is v6 plus ``river_swim`` (Round 74). Its thirteen old families are identical to
v6's by id, so each run's v7 cache was seeded from its v6 cache and only the 40 new dev
moments were sent to a model. That reuse is checked here, decision by decision: every
v7 decision on an old-family moment must equal the same run's v6 decision.
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

RUNS = load_results("v7")
MODELS = sorted({name.split(":", 2)[2] for name in RUNS})
NEW = {"river_swim"}
V6 = load_results("v6")


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_v7_run_is_complete(name):
    ids = [d.moment_id for d in RUNS[name]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate decisions"
    assert set(ids) == {i.moment.id for i in load("v7", "dev")}, f"{name}: incomplete run"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_no_v7_run_contains_a_failed_call(name):
    failed = [d.moment_id for d in RUNS[name] if (d.rationale or "").startswith("call failed")]
    assert not failed, f"{name}: {len(failed)} calls failed"


@pytest.mark.parametrize("model", MODELS)
def test_every_v7_model_has_both_variants(model):
    for variant in ("naive", "rubric"):
        assert f"llm:{variant}:{model}" in RUNS, f"{model}: no v7 {variant} run"


def test_every_v6_run_was_repeated_on_v7():
    assert set(RUNS) == set(V6) and len(RUNS) == 28


@pytest.mark.parametrize("name", sorted(RUNS))
def test_old_family_decisions_are_exactly_v6s(name):
    """The seeded cache must not have changed or dropped a single old-family answer."""
    v6 = {d.moment_id: d.model_dump() for d in V6[name]}
    family = {i.moment.id: i.moment.family for i in load("v7", "dev")}
    old = [d for d in RUNS[name] if family[d.moment_id] not in NEW]
    assert len(old) == len(v6)
    assert all(d.model_dump() == v6[d.moment_id] for d in old), name


def test_v7_runs_and_readme_rows_correspond_one_to_one():
    rows = _readme_rows("v7")
    assert set(rows) == set(RUNS)


def test_every_v7_readme_figure_equals_a_fresh_rescore():
    rows = _readme_rows("v7")
    bar = pair_blind_ics(load("v7", "dev"))
    stale = []
    for card, unparsed, pairs in scorecards("v7"):
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
    assert not stale, "README v7 LLM table is stale; run `tactbench results --version v7`"


class TestTheReadmeV7Claims:
    """Every figure in the README's v7 claims block, recomputed."""

    @staticmethod
    def _block() -> str:
        text = (Path(__file__).parent.parent / "README.md").read_text()
        block = text.split("<!-- v7-claims:start -->")[1].split("<!-- v7-claims:end -->")[0]
        return " ".join(block.split())

    @staticmethod
    def _family():
        items = {i.moment.id: i for i in load("v7", "dev") if i.moment.family in NEW}
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

    def test_constant_runs(self):
        items, runs = self._family()
        constant = [ds for ds in runs.values() if len({d.surface for d in ds}) == 1]
        silent = sum(not ds[0].surface for ds in constant)
        assert len(items) == 40 and (len(constant), silent) == (15, 6)
        block = self._block()
        assert "**15** of the 28 runs give every one of its 40 moments the same answer" in block
        assert "(**6** never speak, **9** always do)" in block

    def test_best_pairs(self):
        from math import comb

        split = self._split_pairs()
        best = max(split, key=lambda n: split[n][0])
        assert best == "llm:rubric:granite-3.3-2b" and split[best] == (3, 0, 20)
        assert sum(r == 3 for r, _, _ in split.values()) == 1
        assert sum(comb(3, k) for k in (3,)) / 2**3 == 0.125
        block = self._block()
        assert "**3** of 20 pairs (Granite-3.3-2B with the rubric), below the 5 a coin" in block
        assert "3 right and 0 backwards, p=0.125 at even odds" in block

    def test_split_pairs_across_runs(self):
        split = self._split_pairs()
        right = sum(r for r, _, _ in split.values())
        back = sum(b for _, b, _ in split.values())
        assert (right + back, right, back) == (23, 10, 13)
        block = self._block()
        assert "of the **23** pairs answered differently on their two sides, **10** are" in block
        assert "right and **13** backwards" in block

    def test_the_street_cleaning_comparison(self):
        """The 5 of 20 quoted for street_cleaning is v6's figure, recomputed on v7's runs
        (its decisions are v6's, checked above)."""
        items = {i.moment.id: i for i in load("v7", "dev") if i.moment.family == "street_cleaning"}
        best = 0
        for ds in RUNS.values():
            by_pair: dict = {}
            for d in ds:
                if d.moment_id in items:
                    by_pair.setdefault(pair_key(d.moment_id), {})[
                        items[d.moment_id].label.should_surface
                    ] = d.surface
            best = max(best, sum(p[True] and not p[False] for p in by_pair.values()))
        assert best == 5 and "On `street_cleaning` the best was 5 of 20." in self._block()

    def test_the_two_verdicts_that_move(self):
        c6 = {c.policy: (c, u) for c, u, _ in scorecards("v6")}
        c7 = {c.policy: (c, u) for c, u, _ in scorecards("v7")}
        above6 = {p for p, (c, _) in c6.items() if c.ics_normalized > 0}
        above7 = {p for p, (c, _) in c7.items() if c.ics_normalized > 0}
        assert above7 - above6 == {"llm:naive:qwen2.5-1.5b"} and above6 <= above7
        q, _ = c7["llm:naive:qwen2.5-1.5b"]
        assert c6["llm:naive:qwen2.5-1.5b"][0].surfaced == 0 and q.surfaced == 1
        silence = c7["llm:rubric:qwen2.5-3b"][0]
        assert silence.surfaced == 0 and silence.ics_normalized == 0
        block = self._block()
        assert f"beats silence by **{q.ics_normalized:+.1f}**" in block
        assert f"(ICS {q.ics:.1f} against {silence.ics:.1f}, one catch)" in block
        inc6 = {p for p, (_, u) in c6.items() if u > MAX_UNPARSED}
        inc7 = {p for p, (_, u) in c7.items() if u > MAX_UNPARSED}
        assert inc6 - inc7 == {"llm:naive:qwen2.5-3b"} and inc7 <= inc6
        u6, u7 = c6["llm:naive:qwen2.5-3b"][1], c7["llm:naive:qwen2.5-3b"][1]
        assert round(u6 * 520) == round(u7 * 560) == 28 and u7 == MAX_UNPARSED
        assert "same **28** unreadable answers as on v6, but 28 of 560 is exactly 5.0%" in block

    def test_ordering_against_v6(self):
        c6 = {c.policy: c for c, _, _ in scorecards("v6")}
        c7 = {c.policy: c for c, _, _ in scorecards("v7")}
        rev = tie = 0
        for x, y in combinations(sorted(c7), 2):
            a = (c6[x].ics > c6[y].ics) - (c6[x].ics < c6[y].ics)
            b = (c7[x].ics > c7[y].ics) - (c7[x].ics < c7[y].ics)
            rev += a * b < 0
            tie += a != b and a * b == 0
        assert (rev, tie) == (6, 4)
        block = self._block()
        assert "Of the 378 pairs of runs, **6** are reversed by ICS and **4** change" in block
