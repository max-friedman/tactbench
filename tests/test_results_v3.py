"""The v3 LLM table, gated as v1's and v2's are. Round 46.

v3 is v2 plus ``pet_care`` (Round 45). Its nine old families are byte-identical to
v2's, so each run's v3 cache was seeded from its v2 cache and only the 40 new dev
moments were sent to a model. That reuse is checked here, decision by decision: every
v3 decision on an old-family moment must equal the same run's v2 decision.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import pytest
from test_results import _readme_rows

from tactbench.cli import MAX_UNPARSED
from tactbench.dataset.generate import LATER_FRAMES
from tactbench.dataset.loader import load
from tactbench.results import load_results, pairs_both_right, scorecards
from tactbench.runner import normalized, pair_blind_ics

RUNS = load_results("v3")
MODELS = sorted({name.split(":", 2)[2] for name in RUNS})
NEW = set(LATER_FRAMES)


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_v3_run_is_complete(name):
    ids = [d.moment_id for d in RUNS[name]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate decisions"
    assert set(ids) == {i.moment.id for i in load("v3", "dev")}, f"{name}: incomplete run"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_no_v3_run_contains_a_failed_call(name):
    failed = [d.moment_id for d in RUNS[name] if (d.rationale or "").startswith("call failed")]
    assert not failed, f"{name}: {len(failed)} calls failed"


@pytest.mark.parametrize("model", MODELS)
def test_every_v3_model_has_both_variants(model):
    for variant in ("naive", "rubric"):
        assert f"llm:{variant}:{model}" in RUNS, f"{model}: no v3 {variant} run"


def test_every_v2_run_was_repeated_on_v3():
    assert set(RUNS) == set(load_results("v2"))


@pytest.mark.parametrize("name", sorted(RUNS))
def test_old_family_decisions_are_exactly_v2s(name):
    """The seeded cache must not have changed or dropped a single old-family answer."""
    v2 = {d.moment_id: d.model_dump() for d in load_results("v2")[name]}
    family = {i.moment.id: i.moment.family for i in load("v3", "dev")}
    old = [d for d in RUNS[name] if family[d.moment_id] not in NEW]
    assert len(old) == len(v2)
    assert all(d.model_dump() == v2[d.moment_id] for d in old), name


def test_v3_runs_and_readme_rows_correspond_one_to_one():
    rows = _readme_rows("v3")
    assert set(rows) == set(RUNS)


def test_every_v3_readme_figure_equals_a_fresh_rescore():
    rows = _readme_rows("v3")
    bar = pair_blind_ics(load("v3", "dev"))
    stale = []
    for card, unparsed, pairs in scorecards("v3"):
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
    assert not stale, "README v3 LLM table is stale; run `tactbench results --version v3`"


class TestTheReadmeV3Claims:
    """Every figure in the README's v3 claims block, recomputed."""

    @staticmethod
    def _block() -> str:
        text = (Path(__file__).parent.parent / "README.md").read_text()
        return text.split("<!-- v3-claims:start -->")[1].split("<!-- v3-claims:end -->")[0]

    @staticmethod
    def _pet_care():
        items = [i for i in load("v3", "dev") if i.moment.family == "pet_care"]
        ids = {i.moment.id for i in items}
        return items, {n: [d for d in ds if d.moment_id in ids] for n, ds in RUNS.items()}

    def test_constant_runs_on_the_new_family(self):
        _, runs = self._pet_care()
        constant = [n for n, ds in runs.items() if len({d.surface for d in ds}) == 1]
        assert len(constant) == 18
        assert "**18** of the 22 runs" in self._block()

    def test_best_new_family_pairs_and_the_coin(self):
        items, runs = self._pet_care()
        n_pairs = len(items) // 2
        best = max(runs, key=lambda n: pairs_both_right(items, runs[n]))
        assert best == "llm:naive:llama-3.1-8b"
        assert round(pairs_both_right(items, runs[best]) * n_pairs) == 3
        assert n_pairs == 20 and round(n_pairs * 0.25) == 5
        block = self._block()
        assert "**3** of its 20 pairs" in block and "Llama-3.1-8B, naive" in block
        assert "about **5** for a coin" in block

    def test_ordering_against_v2(self):
        v2 = {c.policy: c.ics for c, _, _ in scorecards("v2")}
        v3 = {c.policy: c.ics for c, _, _ in scorecards("v3")}
        reversed_, retied = 0, 0
        for x, y in combinations(sorted(v2), 2):
            s2 = (v2[x] > v2[y]) - (v2[x] < v2[y])
            s3 = (v3[x] > v3[y]) - (v3[x] < v3[y])
            reversed_ += s2 * s3 < 0
            retied += s2 * s3 >= 0 and s2 != s3
        assert len(list(combinations(v2, 2))) == 231
        assert (reversed_, retied) == (0, 2)
        block = self._block()
        assert "**0** are reversed" in block and "**2** are\ntied" in block

    def test_six_beat_silence_without_hard_violations(self):
        beat = [c for c, _, _ in scorecards("v3") if c.ics_normalized > 0]
        assert len(beat) == 6 and all(c.hard_violations == 0 for c in beat)
        assert "same **six** runs beat silence" in self._block()

    def test_the_one_verdict_that_changes(self):
        def over(version):
            return {c.policy: u for c, u, _ in scorecards(version) if u > MAX_UNPARSED}

        assert over("v2") == {}
        assert set(over("v3")) == {"llm:naive:qwen2.5-3b"}
        u2 = dict((c.policy, u) for c, u, _ in scorecards("v2"))["llm:naive:qwen2.5-3b"]
        block = self._block()
        assert f"**{u2:.1%}**" in block
        assert f"**{over('v3')['llm:naive:qwen2.5-3b']:.1%}**" in block
