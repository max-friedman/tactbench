"""The human-labelling tool. Round 31 (CLAUDE.md priority 2).

Constructed labels carry ``raters: 0``; nothing could collect a human label before
this round. These tests pin the statistic against a published worked example, keep
the answer out of what a rater sees, and check the sample is whole pairs.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from tactbench.cli import app
from tactbench.dataset.loader import load
from tactbench.labeling import agreement, fleiss_kappa, rater_order, rater_view, sample_pairs
from tactbench.schema import pair_key


def test_fleiss_kappa_matches_the_published_example():
    """Fleiss (1971) as reproduced on Wikipedia's "Fleiss' kappa" page: 10 subjects,
    5 categories, 14 raters each; kappa = 0.210."""
    table = [
        [0, 0, 0, 0, 14],
        [0, 2, 6, 4, 2],
        [0, 0, 3, 5, 6],
        [0, 3, 9, 2, 0],
        [2, 2, 8, 1, 1],
        [7, 7, 0, 0, 0],
        [3, 2, 6, 3, 0],
        [2, 5, 3, 2, 2],
        [6, 5, 2, 1, 0],
        [0, 2, 2, 3, 7],
    ]
    assert fleiss_kappa(table) == pytest.approx(0.210, abs=0.0005)


def test_fleiss_kappa_edges():
    assert fleiss_kappa([[3, 0], [0, 3], [3, 0]]) == pytest.approx(1.0)
    assert fleiss_kappa([[3, 0], [3, 0]]) is None  # one category used: undefined


def test_the_sample_is_whole_pairs_and_deterministic():
    items = load("v1", "dev")
    a, b = sample_pairs(items, 10), sample_pairs(items, 10)
    assert [i.moment.id for i in a] == [i.moment.id for i in b]
    keys = [pair_key(i.moment.id) for i in a]
    assert len(a) == 20 and all(keys.count(k) == 2 for k in keys)


def test_a_rater_never_sees_the_answer():
    for item in sample_pairs(load("v1", "dev"), 20):
        shown = rater_view(item)
        assert item.moment.id not in shown
        for leak in ("near_miss", "-pos-", "-near-", "time_critical", "frame:"):
            assert leak not in shown, leak


def test_pair_sides_are_not_shown_back_to_back():
    order = rater_order("alice", sample_pairs(load("v1", "dev"), 20))
    adjacent = sum(
        pair_key(a.moment.id) == pair_key(b.moment.id)
        for a, b in zip(order, order[1:], strict=False)
    )
    assert adjacent <= 2  # shuffled per rater, not grouped by pair


def _label(tmp_path, monkeypatch, rater, answers, pairs=2):
    monkeypatch.chdir(tmp_path)
    return CliRunner().invoke(
        app, ["label", "--rater", rater, "--pairs", str(pairs)], input="".join(answers)
    )


def test_label_records_answers_and_resumes(tmp_path, monkeypatch):
    out = _label(tmp_path, monkeypatch, "alice", ["y\n", "n\n", "q\n"])
    assert out.exit_code == 0, out.output
    path = tmp_path / "labels" / "v1-dev" / "alice.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert [r["surface"] for r in rows] == [True, False]
    assert all(r["rater"] == "alice" for r in rows)

    _label(tmp_path, monkeypatch, "alice", ["y\n", "y\n", "q\n"])
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert len(rows) == 4 and len({r["moment_id"] for r in rows}) == 4  # resumed, no repeats


def test_agreement_reports_kappa_and_agreement_with_construction():
    items = sample_pairs(load("v1", "dev"), 5)
    gold = {i.moment.id: i.label.should_surface for i in items}
    labels = {
        "a": dict(gold),
        "b": dict(gold),
        "c": {k: not v for k, v in gold.items()},
    }
    report = agreement(items, labels)
    assert report.items == 10 and report.raters == 3
    assert report.majority_matches_construction == pytest.approx(1.0)
    assert report.per_rater["c"] == pytest.approx(0.0)
    assert report.kappa is not None and report.kappa < 0.5
    assert report.majority_pairs_both_right == pytest.approx(1.0)


def test_agreement_command_runs(tmp_path, monkeypatch):
    _label(tmp_path, monkeypatch, "alice", ["y\n"] * 4)
    _label(tmp_path, monkeypatch, "bob", ["n\n"] * 4)
    out = CliRunner().invoke(app, ["agreement"])
    assert out.exit_code == 0, out.output
    assert "kappa" in out.output.lower() and "alice" in out.output
