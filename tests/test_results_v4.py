"""The v4 LLM table, gated as v3's is. Round 48.

v4 is v3 plus ``home_security`` (Round 47). Its ten old families are byte-identical to
v3's, so each run's v4 cache was seeded from its v3 cache and only the 40 new dev
moments were sent to a model. That reuse is checked here, decision by decision: every
v4 decision on an old-family moment must equal the same run's v3 decision.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import pytest
from test_results import _readme_rows

from tactbench.cli import MAX_UNPARSED
from tactbench.dataset.loader import load
from tactbench.policies.llm import unparsed_rate
from tactbench.results import load_results, pairs_both_right, scorecards
from tactbench.runner import normalized, pair_blind_ics

RUNS = load_results("v4")
MODELS = sorted({name.split(":", 2)[2] for name in RUNS})
NEW = {"home_security"}


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_v4_run_is_complete(name):
    ids = [d.moment_id for d in RUNS[name]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate decisions"
    assert set(ids) == {i.moment.id for i in load("v4", "dev")}, f"{name}: incomplete run"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_no_v4_run_contains_a_failed_call(name):
    failed = [d.moment_id for d in RUNS[name] if (d.rationale or "").startswith("call failed")]
    assert not failed, f"{name}: {len(failed)} calls failed"


@pytest.mark.parametrize("model", MODELS)
def test_every_v4_model_has_both_variants(model):
    for variant in ("naive", "rubric"):
        assert f"llm:{variant}:{model}" in RUNS, f"{model}: no v4 {variant} run"


def test_every_v3_run_was_repeated_on_v4():
    assert set(RUNS) == set(load_results("v3"))


@pytest.mark.parametrize("name", sorted(RUNS))
def test_old_family_decisions_are_exactly_v3s(name):
    """The seeded cache must not have changed or dropped a single old-family answer."""
    v3 = {d.moment_id: d.model_dump() for d in load_results("v3")[name]}
    family = {i.moment.id: i.moment.family for i in load("v4", "dev")}
    old = [d for d in RUNS[name] if family[d.moment_id] not in NEW]
    assert len(old) == len(v3)
    assert all(d.model_dump() == v3[d.moment_id] for d in old), name


def test_v4_runs_and_readme_rows_correspond_one_to_one():
    rows = _readme_rows("v4")
    assert set(rows) == set(RUNS)


def test_every_v4_readme_figure_equals_a_fresh_rescore():
    rows = _readme_rows("v4")
    bar = pair_blind_ics(load("v4", "dev"))
    stale = []
    for card, unparsed, pairs in scorecards("v4"):
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
    assert not stale, "README v4 LLM table is stale; run `tactbench results --version v4`"


class TestTheReadmeV4Claims:
    """Every figure in the README's v4 claims block, recomputed."""

    @staticmethod
    def _block() -> str:
        text = (Path(__file__).parent.parent / "README.md").read_text()
        block = text.split("<!-- v4-claims:start -->")[1].split("<!-- v4-claims:end -->")[0]
        return " ".join(block.split())

    @staticmethod
    def _new_family():
        items = [i for i in load("v4", "dev") if i.moment.family == "home_security"]
        ids = {i.moment.id for i in items}
        return items, {n: [d for d in ds if d.moment_id in ids] for n, ds in RUNS.items()}

    @staticmethod
    def _order_changes() -> list[tuple[str, str, bool]]:
        v3 = {c.policy: c.ics for c, _, _ in scorecards("v3")}
        v4 = {c.policy: c.ics for c, _, _ in scorecards("v4")}
        out = []
        for x, y in combinations(sorted(v3), 2):
            s3 = (v3[x] > v3[y]) - (v3[x] < v3[y])
            s4 = (v4[x] > v4[y]) - (v4[x] < v4[y])
            if s3 != s4:
                out.append((x, y, s3 * s4 < 0))
        return out

    def test_constant_runs_on_the_new_family(self):
        _, runs = self._new_family()
        constant = [n for n, ds in runs.items() if len({d.surface for d in ds}) == 1]
        assert len(runs) == 22 and len(constant) == 17
        assert "**17** of the 22 runs" in self._block()

    def test_best_new_family_pairs_and_the_coin(self):
        items, runs = self._new_family()
        n_pairs = len(items) // 2
        scores = {n: round(pairs_both_right(items, ds) * n_pairs) for n, ds in runs.items()}
        top = max(scores.values())
        assert top == 1
        assert sorted(n for n, v in scores.items() if v == top) == [
            "llm:naive:llama-3.1-8b",
            "llm:naive:qwen2.5-0.5b",
        ]
        assert n_pairs == 20 and round(n_pairs * 0.25) == 5
        block = self._block()
        assert "**1** of their 20 pairs" in block
        assert "Llama-3.1-8B and Qwen2.5-0.5B, both naive" in block
        assert "about **5** for a coin" in block

    def test_the_same_runs_are_silenced_as_on_pet_care(self):
        _, runs = self._new_family()
        silenced = {
            n
            for n, ds in RUNS.items()
            if not any(d.surface for d in runs[n])
            and any(d.surface for d in ds if d.moment_id not in {x.moment_id for x in runs[n]})
        }
        v3 = load_results("v3")
        pet = {i.moment.id for i in load("v3", "dev") if i.moment.family == "pet_care"}
        silenced_v3 = {
            n
            for n, ds in v3.items()
            if not any(d.surface for d in ds if d.moment_id in pet)
            and any(d.surface for d in ds if d.moment_id not in pet)
        }
        assert len(silenced) == 6 and silenced == silenced_v3
        assert "same **6** runs that went quiet on `pet_care`" in self._block()

    def test_ordering_against_v3(self):
        changes = self._order_changes()
        assert len(list(combinations(RUNS, 2))) == 231
        assert sum(r for *_, r in changes) == 5
        assert sum(not r for *_, r in changes) == 1
        block = self._block()
        assert "**5** are reversed" in block and "**1** is tied" in block

    def test_every_order_change_is_below_silence_on_both_versions(self):
        n3 = {c.policy: c.ics_normalized for c, _, _ in scorecards("v3")}
        n4 = {c.policy: c.ics_normalized for c, _, _ in scorecards("v4")}
        for x, y, _ in self._order_changes():
            assert n3[x] < 0 and n4[x] < 0 and n3[y] < 0 and n4[y] < 0, (x, y)
        assert "lose to silence on both versions" in self._block()

    def test_the_six_that_beat_silence_keep_their_order(self):
        def ranked(version):
            cards = [c for c, _, _ in scorecards(version) if c.ics_normalized > 0]
            return [c.policy for c in sorted(cards, key=lambda c: c.ics)], cards

        order3, _ = ranked("v3")
        order4, cards4 = ranked("v4")
        assert len(order4) == 6 and order4 == order3
        assert all(c.hard_violations == 0 for c in cards4)
        assert "same **six**, all with zero hard violations" in self._block()

    def test_the_verdicts_that_change(self):
        def rates(version):
            return {c.policy: u for c, u, _ in scorecards(version)}

        u3, u4 = rates("v3"), rates("v4")
        assert {p for p, u in u3.items() if u > MAX_UNPARSED} == {"llm:naive:qwen2.5-3b"}
        assert {p for p, u in u4.items() if u > MAX_UNPARSED} == {
            "llm:naive:qwen2.5-3b",
            "llm:naive:qwen2.5-0.5b",
        }
        block = self._block()
        for policy in ("llm:naive:qwen2.5-0.5b", "llm:naive:qwen2.5-3b"):
            assert f"**{u3[policy]:.1%}** to **{u4[policy]:.1%}**" in block, policy

    def test_the_new_inconclusive_run_is_the_new_familys(self):
        _, runs = self._new_family()
        ds = runs["llm:naive:qwen2.5-0.5b"]
        assert len(ds) == 40 and round(unparsed_rate(ds) * 40) == 14
        assert "**14** of its 40 `home_security` answers" in self._block()
