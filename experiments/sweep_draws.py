"""How much of the comprehension sweep is which moments, and how much is coin flips?

Round 26 changed only the id that ``PartialSkylinePolicy`` hashes and the sweep's
break-even moved 0.29 -> 0.23. Round 27 measures the spread over 20 draws -- and its
review found the first version varied two things at once: *which* moments a given
``p`` comprehends, and the coin flip on every moment it does not. So three
configurations, 20 each:

- ``set``   -- vary ``draw`` (the comprehended set), guesses fixed at ``seed=0``
- ``guess`` -- vary ``seed`` (the coin flips), comprehended set fixed at ``draw=0``
- ``both``  -- vary both together

Break-even is the smallest ``p`` on a 0.01 grid at which ICS beats silence, found by
bisection (ICS is monotone in ``p`` within a draw). Also per draw, on the 7-point
published grid: monotone, anchored, and the smallest step as a share of the range,
which ``TestMetricDiscrimination`` requires to exceed 2%.

    uv run python experiments/sweep_draws.py
"""

from __future__ import annotations

import statistics

from tactbench.dataset.loader import load
from tactbench.policies.skyline import PartialSkylinePolicy
from tactbench.runner import evaluate, silence_ics

GRID = [0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0]
DRAWS = range(20)
CONFIGS = {
    "set": lambda k: {"draw": k, "seed": 0},
    "guess": lambda k: {"draw": 0, "seed": k},
    "both": lambda k: {"draw": k, "seed": k},
}


def break_even(items, reference, **kw) -> float:
    """Smallest p (0.01 grid) whose ICS is below silence."""
    lo, hi = 0, 100  # in hundredths; p=1.0 is the skyline and always beats silence
    while lo < hi:
        mid = (lo + hi) // 2
        if (
            evaluate(PartialSkylinePolicy(mid / 100, **kw), items, reference=reference).ics
            < reference
        ):
            hi = mid
        else:
            lo = mid + 1
    return lo / 100


def grid_props(items, reference, **kw):
    costs = [evaluate(PartialSkylinePolicy(p, **kw), items, reference=reference).ics for p in GRID]
    monotone = all(a >= b for a, b in zip(costs, costs[1:], strict=False))
    anchored = costs[-1] == 0.0 and costs[0] > reference
    span = costs[0] - costs[-1]
    smallest = min(a - b for a, b in zip(costs, costs[1:], strict=False)) / span
    return monotone, anchored, smallest


def main() -> None:
    items = load("v1", "dev")
    reference = silence_ics(items)
    head = f"{'source':<6} {'break-even range':>17} {'median':>7}"
    print(f"{head}   {'mono':>5} {'anch':>5} {'min step':>9}")
    for name, kw in CONFIGS.items():
        xs = [break_even(items, reference, **kw(k)) for k in DRAWS]
        props = [grid_props(items, reference, **kw(k)) for k in DRAWS]
        mono, anch = all(p[0] for p in props), all(p[1] for p in props)
        step = min(p[2] for p in props)
        print(
            f"{name:<6} {min(xs):>8.2f} - {max(xs):.2f} {statistics.median(xs):>7.2f}"
            f"   {str(mono):>5} {str(anch):>5} {step:>9.1%}"
        )
    v4 = [
        evaluate(
            PartialSkylinePolicy(0.4, draw=k, seed=k), items, reference=reference
        ).ics_normalized
        for k in DRAWS
    ]
    print(
        f"\nboth, p=0.4 vs silence: {min(v4):+.1f} - {max(v4):+.1f} (published draw {v4[0]:+.1f})"
    )


if __name__ == "__main__":
    main()
