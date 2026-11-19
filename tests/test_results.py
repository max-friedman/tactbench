"""The README's LLM table is gated against committed decisions. Round 23.

Rounds 17-19 found the built-in results gate silently covering less than it
claimed, three times. The LLM table is a new place for the same failure, so every
direction is checked: each committed run is complete, each has a README row, each
README row has a committed run, every figure in a row equals a fresh re-score, and
a row the regex fails to read fails the build instead of being skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tactbench.dataset.loader import load
from tactbench.results import load_results, manifest, policy_name, results_dir, scorecards

README = Path(__file__).resolve().parents[1] / "README.md"

ROW = re.compile(
    r"^\|\s*`(?P<policy>llm:(?:naive|rubric):[\w.\-]+)`\s*\|\s*(?P<ics>[\d.]+)\s*"
    r"\|\s*(?P<vs>[+−-][\d.]+|0\.0)\s*\|\s*(?P<prec>[\d.]+|—)\s*\|\s*(?P<recall>[\d.]+|—)\s*"
    r"\|\s*(?P<ece>[\d.]+)\s*\|\s*(?P<hv>\d+)\s*\|\s*(?P<spoke>\d+)/(?P<n>\d+)\s*"
    r"\|\s*(?P<unparsed>[\d.]+)%\s*\|\s*$",
    re.MULTILINE,
)

RUNS = load_results()


def _readme_rows() -> dict[str, re.Match]:
    text = README.read_text()
    rows = {m.group("policy"): m for m in ROW.finditer(text)}
    claimed = [ln for ln in text.splitlines() if ln.startswith("| `llm:")]
    assert len(claimed) == len(rows), (
        f"{len(claimed)} README lines look like LLM result rows but {len(rows)} parse. "
        "A row the check cannot read is a row the check does not cover."
    )
    return rows


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_committed_run_is_complete(name):
    """A partial run would be scored as silence on every missing moment."""
    ids = [d.moment_id for d in RUNS[name]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate decisions"
    assert set(ids) == {i.moment.id for i in load("v1", "dev")}, f"{name}: incomplete run"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_committed_run_records_what_produced_it(name):
    model = name.split(":", 2)[2]
    entry = manifest().get(model)
    assert entry, f"{model} has results but no MANIFEST.json entry"
    assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
    assert entry["temperature"] == 0


def test_runs_and_readme_rows_correspond_one_to_one():
    rows = _readme_rows()
    assert set(rows) == set(RUNS), (
        f"in README only: {sorted(set(rows) - set(RUNS))}; "
        f"committed but unpublished: {sorted(set(RUNS) - set(rows))}"
    )


def test_every_readme_figure_equals_a_fresh_rescore():
    rows = _readme_rows()
    stale = []
    for card, unparsed in scorecards():
        row = rows[card.policy]
        for label, quoted, actual, tol in (
            ("ICS", row["ics"], card.ics, 0.05),
            ("vs silence", row["vs"].replace("−", "-"), card.ics_normalized, 0.05),
            ("prec@int", row["prec"], card.precision_at_interrupt, 0.0005),
            ("recall-hv", row["recall"], card.recall_high_value, 0.0005),
            ("ECE", row["ece"], card.ece, 0.0005),
            ("hard viol.", row["hv"], card.hard_violations, 0),
            ("spoke", row["spoke"], card.surfaced, 0),
            ("n", row["n"], card.n, 0),
            ("unparsed", row["unparsed"], unparsed * 100, 0.05),
        ):
            if quoted == "—" or actual is None:
                if (quoted == "—") != (actual is None):
                    stale.append(f"{card.policy}.{label}: README {quoted}, actual {actual}")
                continue
            if abs(float(quoted) - float(actual)) > tol:
                stale.append(f"{card.policy}.{label}: README {quoted}, actual {actual:.3f}")
    assert not stale, "README LLM table is stale; run `tactbench results`:\n  " + "\n  ".join(stale)


def test_file_names_round_trip():
    assert policy_name(results_dir() / "llm_rubric_qwen2.5-0.5b-dev.jsonl") == (
        "llm:rubric:qwen2.5-0.5b"
    )
