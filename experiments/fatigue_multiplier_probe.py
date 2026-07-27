"""Does modelling fatigue as a cost multiplier change anything?

Round 6 asked whether the queue's top item was worth building. The proposal was:
real interruption cost rises with how recently the user was last interrupted, so
scale false-positive cost by a fatigue level.

This probe answers it **without implementing the feature** — it assigns each
moment a deterministic fatigue level, rescales false-positive cost, and checks
whether the leaderboard ordering moves.

Result: it does not. At k=0 (today), k=0.5, and k=2.0 the ranking is identical.

    k=0.0  skyline < never < heuristic < random@0.5 < always
    k=0.5  skyline < never < heuristic < random@0.5 < always
    k=2.0  skyline < never < heuristic < random@0.5 < always

The reason is structural, not a quirk of these numbers. The multiplier only ever
*increases* false-positive cost, and it is applied identically no matter which
policy produced the false positive. So the whole transform is monotone in "how
many false positives did you make, weighted per-moment" — which is already what
the ordering is determined by. Spreading the scores further apart is not new
information.

**The proposal was rejected on this evidence.** See docs/plans/LOOP_STATE.md for
the re-specified version: fatigue is only interesting when it is *observable
context that changes the correct answer*, and only when it changes it for
low-value cues while leaving high-value ones alone — otherwise a one-line
threshold rule solves it and no judgment is tested.

Kept in the repo rather than deleted so the rejection carries its evidence, and
so a future round proposing the same thing re-runs this instead of re-arguing it:

    uv run python experiments/fatigue_multiplier_probe.py
"""

from __future__ import annotations

import hashlib

from tactbench.dataset.loader import load
from tactbench.metrics import score_item
from tactbench.policies.builtin import registry
from tactbench.runner import run_policy

#: Multipliers to sweep. 0.0 reproduces today's scoring exactly.
K_VALUES = (0.0, 0.5, 2.0)


def fatigue(moment_id: str) -> int:
    """Deterministic 0-5 fatigue level, standing in for 'recent interruptions'."""
    return hashlib.sha256(moment_id.encode()).digest()[1] % 6


def total_cost(items, decisions, k: float) -> float:
    by_id = {d.moment_id: d for d in decisions}
    total = 0.0
    for item in items:
        outcome = score_item(item, by_id[item.moment.id])
        cost = outcome.cost
        if outcome.kind == "fp":
            cost *= 1 + k * fatigue(item.moment.id)
        total += cost
    return total


def main() -> None:
    items = load("v1", "dev")
    rows: dict[str, list[float]] = {}

    header = f"{'policy':<12}" + "".join(f"{f'k={k}':>12}" for k in K_VALUES)
    print(header)
    for name, policy in registry().items():
        decisions = run_policy(policy, items)
        rows[name] = [total_cost(items, decisions, k) for k in K_VALUES]
        print(f"{name:<12}" + "".join(f"{c:>12.1f}" for c in rows[name]))

    print()
    orderings = []
    for i, k in enumerate(K_VALUES):
        order = sorted(rows, key=lambda n: rows[n][i])
        orderings.append(order)
        print(f"k={k:<5} ranking: {' < '.join(order)}")

    unchanged = all(o == orderings[0] for o in orderings)
    print()
    print(
        "REJECTED: ordering is unchanged across every multiplier — a pure rescale."
        if unchanged
        else "Ordering MOVED — the rejection no longer holds; re-open the proposal."
    )


if __name__ == "__main__":
    main()
