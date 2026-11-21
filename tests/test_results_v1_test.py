"""The LLM table on held-out `v1/test`, gated as the dev tables are. Round 69.

Until R69 no model had been run on a held-out split (README limitation). These are
the same fourteen models and two prompts as `v4`/`v5` dev, on v1's held-out frames
(5-7): phrasings that occur nowhere in dev.
"""

from __future__ import annotations

import pytest
from test_results import _readme_rows

from tactbench.dataset.loader import load
from tactbench.results import load_results, scorecards
from tactbench.runner import normalized, pair_blind_ics

VERSION, SPLIT = "v1", "test"
RUNS = load_results(VERSION, SPLIT)
DEV = load_results(VERSION, "dev")
MODELS = sorted({name.split(":", 2)[2] for name in RUNS})


def test_every_model_was_run_on_the_held_out_split():
    v5 = load_results("v5", "dev")
    assert set(RUNS) == set(v5) and len(RUNS) == 28


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_held_out_run_is_complete(name):
    ids = [d.moment_id for d in RUNS[name]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate decisions"
    assert set(ids) == {i.moment.id for i in load(VERSION, SPLIT)}, f"{name}: incomplete"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_no_held_out_run_contains_a_failed_call(name):
    failed = [d.moment_id for d in RUNS[name] if (d.rationale or "").startswith("call failed")]
    assert not failed, f"{name}: {len(failed)} calls failed"


@pytest.mark.parametrize("model", MODELS)
def test_every_model_has_both_variants(model):
    for variant in ("naive", "rubric"):
        assert f"llm:{variant}:{model}" in RUNS, f"{model}: no {variant} run"


def test_held_out_runs_and_readme_rows_correspond_one_to_one():
    assert set(_readme_rows("v1-test")) == set(RUNS)


def test_every_held_out_readme_figure_equals_a_fresh_rescore():
    rows = _readme_rows("v1-test")
    bar = pair_blind_ics(load(VERSION, SPLIT))
    stale = []
    for card, unparsed, pairs in scorecards(VERSION, SPLIT):
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
            if abs(float(quoted) - float(actual)) > tol + 1e-9:
                stale.append(f"{card.policy}.{label}: README {quoted}, actual {actual:.3f}")
    assert not stale, "README held-out table is stale; run `tactbench results --split test`"
