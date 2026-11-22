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


