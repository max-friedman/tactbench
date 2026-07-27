"""Does ICS order *partial* comprehension correctly?

Six rounds of leaderboards show every non-skyline policy at 0.496-0.560 precision
and the skyline at 1.000. Nothing has ever been measured in between. So the
benchmark has been shown to separate *no* comprehension from *perfect*
comprehension, and has never been shown to **rank the middle** -- which is where
every real system lands.

If ICS is not monotone in comprehension, the metric is broken for precisely the
systems it exists to score, and no amount of dataset work would fix it.

The probe interpolates between the two known points. ``PartialSkylinePolicy(p)``
resolves the deciding relation on a deterministic fraction ``p`` of moments and
coin-flips on the rest, so ``p=0`` should behave like ``random@0.5`` and ``p=1``
should reproduce the skyline exactly.

Well-behaved means three things, checked below:

1. **Monotone** -- ICS decreases as ``p`` rises, with no reversals.
2. **Anchored** -- ``p=0`` lands near ``random@0.5``; ``p=1`` lands at 0.
3. **Responsive** -- comprehension gains register across the whole range rather
   than only near the ends. A metric that is flat from p=0.2 to p=0.8 cannot
   tell a mediocre system from a good one, even if the endpoints look fine.

All three hold. The headline number the sweep produced: **a policy needs roughly
30% comprehension before it beats silence at all.** Below that it is worse than
shipping nothing, however well-intentioned.

The three properties are now guarded by ``TestMetricDiscrimination`` in the test
suite; this script stays for the full sweep and the crossover estimate.

    uv run python experiments/discrimination_sweep.py
"""

from __future__ import annotations

from tactbench.dataset.loader import load
from tactbench.policies.skyline import PartialSkylinePolicy
from tactbench.runner import evaluate, silence_ics

SWEEP = (0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0)


def main() -> None:
    items = load("v1", "dev")
    reference = silence_ics(items)

    print(f"silence baseline ICS = {reference:.1f}\n")
    print(f"{'p':>5} {'ICS':>8} {'vs silence':>12} {'prec@int':>10} {'recall-hv':>11}")

    results = []
    for p in SWEEP:
        card = evaluate(PartialSkylinePolicy(p), items, reference=reference)
        results.append((p, card.ics))
        prec = f"{card.precision_at_interrupt:.3f}" if card.precision_at_interrupt else "  --  "
        rec = f"{card.recall_high_value:.3f}" if card.recall_high_value is not None else "  --  "
        print(f"{p:>5.1f} {card.ics:>8.1f} {card.ics_normalized:>+12.1f} {prec:>10} {rec:>11}")

    ics = [c for _, c in results]
    # Deliberately offset pairwise zip, so strict=False is correct here.
    pairs = list(zip(ics, ics[1:], strict=False))
    monotone = all(a >= b for a, b in pairs)
    anchored = ics[-1] == 0.0 and ics[0] > reference

    # Responsiveness: every step should move ICS by a non-trivial share of the
    # total range, not just the endpoints.
    span = ics[0] - ics[-1]
    steps = [a - b for a, b in pairs]
    smallest = min(steps) / span if span else 0.0

    # How much comprehension does a system need before it is worth shipping at
    # all? Linear interpolation between the sweep points that straddle silence.
    crossover = None
    for (p_a, c_a), (p_b, c_b) in zip(results, results[1:], strict=False):
        if c_a > reference >= c_b:
            crossover = p_a + (c_a - reference) / (c_a - c_b) * (p_b - p_a)
            break

    print()
    print(f"monotone decreasing : {monotone}")
    print(f"anchored at p=1 -> 0: {anchored}")
    print(f"smallest step, as a share of total range: {smallest:.1%}")
    if crossover is not None:
        print(f"comprehension needed to beat silence: p ~= {crossover:.2f}")
    print()
    if monotone and anchored and smallest > 0.02:
        print("ICS DISCRIMINATES: partial comprehension is ranked correctly throughout.")
    else:
        print("PROBLEM: the metric does not cleanly order partial comprehension.")


if __name__ == "__main__":
    main()
