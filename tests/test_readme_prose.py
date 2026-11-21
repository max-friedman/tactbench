"""README prose figures outside the gated blocks, pinned. Round 65.

R65 mutated every figure in the README's ungated prose, one at a time, and ran every
test that reads the README. Of 145, **85** could change without any test failing
(75 of 146 after this file; ``experiments/readme_figure_sweep.py``). Most
are history (Rounds 9-13's before/after tables) or definitions (a coin's 25%). This
file pins the ones that state the current data or the current code. The rest are
listed in LOOP_STATE's R65 entry.
"""

from __future__ import annotations

import re
from pathlib import Path

from tactbench.dataset.loader import load
from tactbench.metrics import DND_MULTIPLIER, FALSE_NEGATIVE_COST, FALSE_POSITIVE_COST
from tactbench.policies.builtin import registry
from tactbench.results import scorecards
from tactbench.runner import evaluate, normalized, pair_blind_ics, silence_ics
from tactbench.schema import Activity

ROOT = Path(__file__).resolve().parents[1]
README = " ".join((ROOT / "README.md").read_text().split())


def test_silence_against_the_pair_blind_bar():
    items = load("v1", "dev")
    bar, silence = pair_blind_ics(items), silence_ics(items)
    assert (bar, silence) == (238.0, 336.0)
    quoted = f"at ICS {bar:.0f} against silence's {silence:.0f}, and silence itself scores "
    assert quoted + f"{normalized(silence, bar):.1f}".replace("-", "−") + " against it" in README


def test_the_cost_constants_the_readme_states():
    fp = FALSE_POSITIVE_COST
    assert fp[Activity.IDLE] == fp[Activity.COMMUTING] == 1.0
    assert fp[Activity.SOCIAL] == fp[Activity.EXERCISING] == 2.0
    assert fp[Activity.MEETING] == fp[Activity.FOCUSED_WORK] == 5.0
    assert fp[Activity.SLEEPING] == fp[Activity.DRIVING] == 10.0
    assert set(fp) == set(Activity)
    assert DND_MULTIPLIER == 2.0
    assert FALSE_NEGATIVE_COST == {0: 0.0, 1: 0.5, 2: 2.0, 3: 3.0}
    assert (
        "costs by what the user was doing: 1.0 idle or commuting, 2.0 social or "
        "exercising, 5.0 in a meeting or deep work, 10.0 asleep or driving. Explicit DND "
        "doubles it" in README
    )
    assert (
        "costs by what was missed: 0.5 for a minor cue, 2.0 for a clearly useful one, 3.0 for one "
        "the user is materially worse off without" in README
    )


def test_the_base_rate_table():
    items = load("v1", "dev")
    policies = registry()
    for name in ("skyline", "heuristic", "random@0.5", "always"):
        at1 = evaluate(policies[name], items).precision_at_interrupt
        at100 = evaluate(policies[name], items, base_rate=100).precision_at_interrupt
        bold = "" if name == "skyline" else "**"
        assert f"| `{name}` | {at1:.3f} | {bold}{at100:.3f}{bold} |" in README, name
    always = evaluate(policies["always"], items, base_rate=100).precision_at_interrupt
    assert round(always * 100) == 1 and "roughly **1%**" in README


def test_the_best_v1_run_against_silence():
    cards = {c.policy: c for c, _, _ in scorecards("v1")}
    best = min(cards.values(), key=lambda c: c.ics)
    assert best.policy == "llm:rubric:gemma-3-4b" and best.hard_violations == 0
    assert f"clears silence by +{best.ics_normalized:.1f} with zero hard violations" in README


def test_no_stray_figure_remains_in_the_cost_list():
    block = README.split("**ICS (Interruption Cost Score)**")[1].split("Reported alongside")[0]
    figures = sorted({float(x) for x in re.findall(r"\b\d+\.\d\b", block)})
    assert figures == [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]
