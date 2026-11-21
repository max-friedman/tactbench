"""The v5 LLM table, gated as v4's is. Round 54.

v5 is v4 plus ``water_notice`` (Round 52). Its eleven old families are byte-identical
to v4's, so each run's v5 cache was seeded from its v4 cache and only the 40 new dev
moments were sent to a model. That reuse is checked here, decision by decision: every
v5 decision on an old-family moment must equal the same run's v4 decision.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import pytest
from test_results import _readme_rows

from tactbench.cli import MAX_UNPARSED
from tactbench.dataset.loader import load
from tactbench.metrics import score
from tactbench.policies.builtin import AlwaysPolicy, NeverPolicy
from tactbench.policies.llm import unparsed_rate
from tactbench.results import load_results, pairs_both_right, scorecards
from tactbench.runner import normalized, pair_blind_ics, run_policy
from tactbench.schema import pair_key

RUNS = load_results("v5")
MODELS = sorted({name.split(":", 2)[2] for name in RUNS})
NEW = {"water_notice"}
V4 = load_results("v4")


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_v5_run_is_complete(name):
    ids = [d.moment_id for d in RUNS[name]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate decisions"
    assert set(ids) == {i.moment.id for i in load("v5", "dev")}, f"{name}: incomplete run"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_no_v5_run_contains_a_failed_call(name):
    failed = [d.moment_id for d in RUNS[name] if (d.rationale or "").startswith("call failed")]
    assert not failed, f"{name}: {len(failed)} calls failed"


@pytest.mark.parametrize("model", MODELS)
def test_every_v5_model_has_both_variants(model):
    for variant in ("naive", "rubric"):
        assert f"llm:{variant}:{model}" in RUNS, f"{model}: no v5 {variant} run"


def test_every_v4_run_was_repeated_on_v5():
    assert set(RUNS) == set(V4) and len(RUNS) == 28


@pytest.mark.parametrize("name", sorted(RUNS))
def test_old_family_decisions_are_exactly_v4s(name):
    """The seeded cache must not have changed or dropped a single old-family answer."""
    v4 = {d.moment_id: d.model_dump() for d in V4[name]}
    family = {i.moment.id: i.moment.family for i in load("v5", "dev")}
    old = [d for d in RUNS[name] if family[d.moment_id] not in NEW]
    assert len(old) == len(v4)
    assert all(d.model_dump() == v4[d.moment_id] for d in old), name


def test_v5_runs_and_readme_rows_correspond_one_to_one():
    rows = _readme_rows("v5")
    assert set(rows) == set(RUNS)


def test_every_v5_readme_figure_equals_a_fresh_rescore():
    rows = _readme_rows("v5")
    bar = pair_blind_ics(load("v5", "dev"))
    stale = []
    for card, unparsed, pairs in scorecards("v5"):
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
    assert not stale, "README v5 LLM table is stale; run `tactbench results --version v5`"


class TestTheReadmeV5Claims:
    """Every figure in the README's v5 claims block, recomputed."""

    @staticmethod
    def _block() -> str:
        text = (Path(__file__).parent.parent / "README.md").read_text()
        block = text.split("<!-- v5-claims:start -->")[1].split("<!-- v5-claims:end -->")[0]
        return " ".join(block.split())

    @staticmethod
    def _new_family():
        items = [i for i in load("v5", "dev") if i.moment.family == "water_notice"]
        ids = {i.moment.id for i in items}
        return items, {n: [d for d in ds if d.moment_id in ids] for n, ds in RUNS.items()}

    @staticmethod
    def _cards(version):
        return {c.policy: (c, u) for c, u, _ in scorecards(version)}

    def test_constant_runs_on_the_new_family(self):
        _, runs = self._new_family()
        constant = [ds for ds in runs.values() if len({d.surface for d in ds}) == 1]
        silent = sum(not ds[0].surface for ds in constant)
        assert len(runs) == 28 and len(constant) == 18 and silent == 10
        block = self._block()
        assert "**18** of the 28 runs" in block
        assert "(**10** never speak, **8** always do)" in block

    def test_best_new_family_pairs_equals_the_coin(self):
        items, runs = self._new_family()
        n_pairs = len(items) // 2
        scores = {n: round(pairs_both_right(items, ds) * n_pairs) for n, ds in runs.items()}
        top = max(scores.values())
        label = {i.moment.id: i.label.should_surface for i in items}
        sides: dict[str, list[str]] = {}
        for i in items:
            sides.setdefault(pair_key(i.moment.id), []).append(i.moment.id)
        # A coin gets a pair right a quarter of the time only if its sides need opposite answers.
        assert all(len(p) == 2 and label[p[0]] != label[p[1]] for p in sides.values())
        assert n_pairs == 20 and top == 5 == round(n_pairs * 0.25)
        assert [n for n, v in scores.items() if v == top] == ["llm:naive:mistral-7b"]
        block = self._block()
        assert "**5** of its 20 pairs" in block and "Mistral-7B, naive" in block

    def test_answers_the_decider_moves_split_evenly(self):
        items, runs = self._new_family()
        label = {i.moment.id: i.label.should_surface for i in items}
        sides: dict[str, list[str]] = {}
        for i in items:
            sides.setdefault(pair_key(i.moment.id), []).append(i.moment.id)
        assert all(len(p) == 2 and label[p[0]] != label[p[1]] for p in sides.values())
        split = wrong = 0
        per_run = {}
        for name, decisions in runs.items():
            ds = {d.moment_id: d for d in decisions}
            moved = [p for p in sides.values() if ds[p[0]].surface != ds[p[1]].surface]
            per_run[name] = len(moved)
            split += len(moved)
            wrong += sum(ds[p[0]].surface != label[p[0]] for p in moved)
        assert (split, wrong, split - wrong) == (27, 13, 14)
        top = sorted(per_run.items(), key=lambda kv: -kv[1])[:2]
        assert top == [("llm:naive:llama-3.1-8b", 8), ("llm:naive:mistral-7b", 7)]
        block = self._block()
        assert "**27** pairs get different answers" in block
        assert "**14** right on both sides and **13** backwards" in block
        assert "Llama-3.1-8B (**8**) and Mistral-7B (**7**)" in block

    def test_home_security_over_the_same_runs(self):
        items = [i for i in load("v5", "dev") if i.moment.family == "home_security"]
        label = {i.moment.id: i.label.should_surface for i in items}
        sides: dict[str, list[str]] = {}
        for i in items:
            sides.setdefault(pair_key(i.moment.id), []).append(i.moment.id)
        split = wrong = 0
        for decisions in RUNS.values():
            ds = {d.moment_id: d for d in decisions}
            moved = [p for p in sides.values() if ds[p[0]].surface != ds[p[1]].surface]
            split += len(moved)
            wrong += sum(ds[p[0]].surface != label[p[0]] for p in moved)
        assert len(RUNS) == 28 and (split, wrong) == (22, 19)
        assert "(**19** of **22**)" in self._block()

    def test_speaking_beats_silence_on_the_new_family(self):
        items, runs = self._new_family()
        never = score(items, run_policy(NeverPolicy(), items), "never").ics
        always = score(items, run_policy(AlwaysPolicy(), items), "always").ics
        assert (always, never) == (40.0, 60.0)
        c4, c5 = self._cards("v4"), self._cards("v5")
        name = "llm:naive:llama-3.2-3b"
        assert sum(d.surface for d in runs[name]) == 35
        moves = {p: c5[p][0].ics_normalized - c4[p][0].ics_normalized for p in c5}
        above = [p for p in c5 if c5[p][0].ics_normalized > 0]
        assert max(above, key=lambda p: moves[p]) == name
        block = self._block()
        assert "(**40** against **60**)" in block and "speaks on **35** of the 40" in block
        assert (
            f"**{c4[name][0].ics_normalized:+.1f}** to **{c5[name][0].ics_normalized:+.1f}**"
            in block
        )

    def test_no_verdict_changes(self):
        c4, c5 = self._cards("v4"), self._cards("v5")
        assert set(c4) == set(c5)
        above4 = {p for p, (c, _) in c4.items() if c.ics_normalized > 0}
        above5 = {p for p, (c, _) in c5.items() if c.ics_normalized > 0}
        inc4 = {p for p, (_, u) in c4.items() if u > MAX_UNPARSED}
        inc5 = {p for p, (_, u) in c5.items() if u > MAX_UNPARSED}
        assert above4 == above5 and len(above5) == 7
        assert inc4 == inc5 == {"llm:naive:qwen2.5-0.5b", "llm:naive:qwen2.5-3b"}
        block = self._block()
        assert "the same **7** runs beat silence" in block
        for policy in sorted(inc5):
            assert f"**{c4[policy][1]:.1%}** to **{c5[policy][1]:.1%}**" in block, policy

    def test_the_unreadable_new_family_answers(self):
        _, runs = self._new_family()
        ds = runs["llm:naive:qwen2.5-0.5b"]
        assert len(ds) == 40 and round(unparsed_rate(ds) * 40) == 7
        silent = [d for d in ds if not d.surface]
        assert len(silent) == 7 and all(unparsed_rate([d]) == 1.0 for d in silent)
        assert "its one split pair there comes from that fallback" in self._block()
        assert "**7** of its 40 `water_notice` answers are unreadable" in self._block()

    def test_ordering_against_v4(self):
        c4, c5 = self._cards("v4"), self._cards("v5")
        changes = []
        for x, y in combinations(sorted(c5), 2):
            s4 = (c4[x][0].ics > c4[y][0].ics) - (c4[x][0].ics < c4[y][0].ics)
            s5 = (c5[x][0].ics > c5[y][0].ics) - (c5[x][0].ics < c5[y][0].ics)
            if s4 != s5:
                changes.append((x, y, s4 * s5 < 0))
        assert len(list(combinations(c5, 2))) == 378
        assert sum(r for *_, r in changes) == 3 and sum(not r for *_, r in changes) == 1
        culprit = "llm:naive:qwen2.5-0.5b"
        assert all(culprit in (x, y) for x, y, _ in changes)
        for version in (c4, c5):
            assert version[culprit][0].ics_normalized < 0 and version[culprit][1] > MAX_UNPARSED
        block = self._block()
        assert "**3** are reversed" in block and "**1** is tied" in block
        assert "Every one involves Qwen2.5-0.5B naive" in block
