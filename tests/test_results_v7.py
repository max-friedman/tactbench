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
V6 = load_results("v7")


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


