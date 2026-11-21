"""Runs on the reworded set, and the README claims drawn from them. Round 42.

``results/v2para-dev/`` holds each model's decisions on ``data/v2para/dev.jsonl``. The
runs are gated like v1's and v2's -- complete, no failed calls, both variants -- and
every figure in the README's ``paraphrase-claims`` block is recomputed here.
"""

from __future__ import annotations

import re

import pytest

from tactbench.dataset.loader import load
from tactbench.results import ROOT, load_results, paraphrase_robustness

RUNS = load_results("v2para")
MODELS = sorted({name.split(":", 2)[2] for name in RUNS})


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_reworded_run_is_complete(name):
    ids = [d.moment_id for d in RUNS[name]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate decisions"
    assert set(ids) == {i.moment.id for i in load("v2para", "dev")}, f"{name}: incomplete"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_no_reworded_run_contains_a_failed_call(name):
    failed = [d.moment_id for d in RUNS[name] if (d.rationale or "").startswith("call failed")]
    assert not failed, f"{name}: {len(failed)} calls failed"


@pytest.mark.parametrize("model", MODELS)
def test_every_reworded_model_has_both_variants(model):
    for variant in ("naive", "rubric"):
        assert f"llm:{variant}:{model}" in RUNS, f"{model}: no v2para {variant} run"


def test_every_v2_run_was_repeated_on_the_reworded_set():
    assert set(RUNS) == set(load_results("v2")), "the comparison must cover every v2 run"


def _claims() -> str:
    text = (ROOT / "README.md").read_text()
    block = r"<!-- paraphrase-claims:start -->(.*?)<!-- paraphrase-claims:end -->"
    m = re.search(block, text, re.S)
    assert m, "README has no paraphrase-claims block"
    return " ".join(m.group(1).split())


class TestTheReadmeParaphraseClaims:
    ROWS = paraphrase_robustness()
    INFORMATIVE = [r for r in ROWS if not r.constant and r.independent >= 5]

    def test_constant_runs(self):
        constant = sum(r.constant for r in self.ROWS)
        assert f"{constant} of the {len(self.ROWS)} runs are constant on both" in _claims()

    def test_constant_runs_really_cannot_flip(self):
        assert all(r.flips == 0 for r in self.ROWS if r.constant)

    def test_every_informative_run_flips_below_independence(self):
        assert all(r.flips < r.independent for r in self.INFORMATIVE)
        flips = sum(r.flips for r in self.INFORMATIVE)
        expected = round(sum(r.independent for r in self.INFORMATIVE))
        assert f"Of the {len(self.INFORMATIVE)} runs whose independence level" in _claims()
        assert f"{flips} flips against {expected} expected" in _claims()

    def test_the_closest_run(self):
        closest = max(self.INFORMATIVE, key=lambda r: r.flips / r.independent)
        assert closest.policy == "llm:rubric:llama-3.1-8b"
        assert f"at {closest.flips} against {closest.independent:.1f}" in _claims()

    def test_largest_ics_move(self):
        move = max(abs(r.ics_original - r.ics_reworded) for r in self.ROWS)
        assert f"ICS moves by more than {move:g} on the 72" in _claims()

    def test_pairs_ceiling_and_coin(self):
        n_pairs = len(load("v2para", "dev")) // 2
        best = max(max(r.pairs_original, r.pairs_reworded) for r in self.ROWS)
        assert f"more than {round(best * n_pairs)} of the {n_pairs} pairs" in _claims()
        assert f"a coin gets about {round(n_pairs / 4)}" in _claims()
