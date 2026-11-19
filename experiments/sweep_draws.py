"""How much does the comprehension sweep depend on which moments it comprehends?

Round 26 changed only the id that ``PartialSkylinePolicy`` hashes and the sweep's
break-even moved 0.29 -> 0.23, ``p = 0.4`` from +10.1 to +38.7, and the smallest step
from 13.4% to 4.8% of the range. So the published sweep is one draw. Round 27 runs
20 draws (``seed`` 0-19; seed 0 is the published one) and reports, per draw:
break-even ``p``, ``vs silence`` at ``p = 0.4``, whether ICS is monotone and anchored,
and the smallest step as a share of the range -- the quantity
``TestMetricDiscrimination`` requires to exceed 2%.

    uv run python experiments/sweep_draws.py
"""

from __future__ import annotations

from tactbench.dataset.loader import load
from tactbench.policies.skyline import PartialSkylinePolicy
from tactbench.runner import evaluate, silence_ics

POINTS = [0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0]
DRAWS = range(20)


def sweep(items, reference, seed):
    cards = {
        p: evaluate(PartialSkylinePolicy(p, seed=seed), items, reference=reference) for p in POINTS
    }
    costs = [cards[p].ics for p in POINTS]
    monotone = all(a >= b for a, b in zip(costs, costs[1:], strict=False))
    anchored = costs[-1] == 0.0 and costs[0] > reference
    span = costs[0] - costs[-1]
    smallest = min(a - b for a, b in zip(costs, costs[1:], strict=False)) / span
    crossover = next(
        (
            pa + (ca - reference) / (ca - cb) * (pb - pa)
            for (pa, ca), (pb, cb) in zip(
                zip(POINTS, costs, strict=True),
                zip(POINTS[1:], costs[1:], strict=True),
                strict=True,
            )
            if ca > reference >= cb
        ),
        None,
    )
    return crossover, cards[0.4].ics_normalized, monotone, anchored, smallest


def main() -> None:
    items = load("v1", "dev")
    reference = silence_ics(items)
    rows = [(s, *sweep(items, reference, s)) for s in DRAWS]
    print(f"{'draw':>4} {'break-even':>11} {'p=0.4':>7} {'mono':>5} {'anch':>5} {'min step':>9}")
    for s, x, v4, mono, anch, step in rows:
        print(f"{s:>4} {x:>11.2f} {v4:>+7.1f} {str(mono):>5} {str(anch):>5} {step:>9.1%}")
    xs = [r[1] for r in rows]
    v4s = [r[2] for r in rows]
    steps = [r[5] for r in rows]
    median = sorted(xs)[len(xs) // 2]
    mono, anch = all(r[3] for r in rows), all(r[4] for r in rows)
    under = sum(s < 0.02 for s in steps)
    print()
    print(f"break-even over {len(rows)} draws: {min(xs):.2f} - {max(xs):.2f} (median {median:.2f})")
    print(f"p=0.4 vs silence: {min(v4s):+.1f} - {max(v4s):+.1f}")
    print(f"monotone on every draw: {mono}; anchored on every draw: {anch}")
    print(f"smallest step: {min(steps):.1%} - {max(steps):.1%}; draws under 2%: {under}")


if __name__ == "__main__":
    main()
