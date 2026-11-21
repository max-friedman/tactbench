"""The v5 LLM table, gated as v4's is. Round 53.

v5 is v4 plus ``water_notice`` (Round 52). Its eleven old families are byte-identical
to v4's, so each run's v5 cache was seeded from its v4 cache and only the 40 new dev
moments were sent to a model. That reuse is checked here, decision by decision: every
v5 decision on an old-family moment must equal the same run's v4 decision.
"""

from __future__ import annotations

import pytest
from test_results import _readme_rows

from tactbench.dataset.loader import load
from tactbench.results import load_results, scorecards
from tactbench.runner import normalized, pair_blind_ics

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
