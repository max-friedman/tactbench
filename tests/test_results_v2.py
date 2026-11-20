"""The v2 LLM table is gated exactly as v1's is. Round 39.

v2 (Round 37) is the same generator at 32 pairs per family. Its LLM runs live in
``results/v2-dev/`` and its README table between ``llm-results-v2`` markers. Every
v1 gate that is about the runs themselves applies here too: each run complete over
v2/dev, no failed calls, both variants for each model, the table and the runs in one-
to-one correspondence, and every figure equal to a fresh re-score.
"""

from __future__ import annotations

import pytest
from test_results import _readme_rows

from tactbench.dataset.loader import load
from tactbench.results import load_results, manifest, scorecards
from tactbench.runner import normalized, pair_blind_ics

RUNS = load_results("v2")
MODELS = sorted({name.split(":", 2)[2] for name in RUNS})


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_v2_run_is_complete(name):
    ids = [d.moment_id for d in RUNS[name]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate decisions"
    assert set(ids) == {i.moment.id for i in load("v2", "dev")}, f"{name}: incomplete run"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_no_v2_run_contains_a_failed_call(name):
    failed = [d.moment_id for d in RUNS[name] if (d.rationale or "").startswith("call failed")]
    assert not failed, f"{name}: {len(failed)} calls failed"


@pytest.mark.parametrize("model", MODELS)
def test_every_v2_model_has_both_variants_and_a_manifest_entry(model):
    for variant in ("naive", "rubric"):
        assert f"llm:{variant}:{model}" in RUNS, f"{model}: no v2 {variant} run"
    assert model in manifest(), f"{model}: v2 results but no manifest entry"


def test_v2_runs_and_readme_rows_correspond_one_to_one():
    if not RUNS:
        pytest.skip("no v2 runs committed yet")
    rows = _readme_rows("v2")
    assert set(rows) == set(RUNS), (
        f"in README only: {sorted(set(rows) - set(RUNS))}; "
        f"committed but unpublished: {sorted(set(RUNS) - set(rows))}"
    )


def test_every_v2_readme_figure_equals_a_fresh_rescore():
    if not RUNS:
        pytest.skip("no v2 runs committed yet")
    rows = _readme_rows("v2")
    bar = pair_blind_ics(load("v2", "dev"))
    stale = []
    for card, unparsed, pairs in scorecards("v2"):
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
            if abs(float(quoted) - float(actual)) > tol:
                stale.append(f"{card.policy}.{label}: README {quoted}, actual {actual:.3f}")
    assert not stale, "README v2 LLM table is stale; run `tactbench results --version v2`"
