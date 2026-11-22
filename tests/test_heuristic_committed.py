"""The heuristic invariant on every committed split. Round 61.

The standing invariant -- "the heuristic stays near chance (0.5 +/- 0.15 precision)
and never solves the set" -- was tested only on a fresh ten-pair build of the nine v1
families (`tests/test_metrics.py`), and each later version added a test for its new
family alone. No committed split was checked whole, and v2 not at all (R58's
coverage map). Here every split on disk is.
"""

from __future__ import annotations

import pytest

from tactbench.dataset.loader import DATA_ROOT, load
from tactbench.policies.builtin import HeuristicPolicy
from tactbench.policies.skyline import SkylinePolicy
from tactbench.runner import evaluate

SPLITS = sorted(
    (d.name, f.stem) for d in DATA_ROOT.iterdir() if d.is_dir() for f in d.glob("*.jsonl")
)


def violations(policy, items) -> list[str]:
    """Why ``policy`` breaks the heuristic invariant on ``items``, if it does."""
    card = evaluate(policy, items)
    out = []
    if card.ics <= 0:
        out.append(f"solves the set (ICS {card.ics})")
    precision = card.precision_at_interrupt
    if precision is None or abs(precision - 0.5) > 0.15:
        out.append(f"precision {precision} outside 0.5 +/- 0.15")
    return out


def test_every_committed_split_is_listed():
    assert len(SPLITS) == 13 and ("v2", "dev") in SPLITS and ("v2para", "dev") in SPLITS


@pytest.mark.parametrize(("version", "split"), SPLITS)
def test_the_heuristic_stays_near_chance_and_does_not_solve(version, split):
    assert violations(HeuristicPolicy(), load(version, split)) == []


@pytest.mark.parametrize(("version", "split"), [("v2", "dev"), ("v5", "test")])
def test_the_check_would_catch_a_policy_that_solves_the_set(version, split):
    """The skyline solves every split, so the same check must reject it."""
    assert violations(SkylinePolicy(), load(version, split))
