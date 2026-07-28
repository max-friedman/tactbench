"""Can an ICS score be read back as an implied comprehension fraction?

Round 7 swept a policy that comprehends a random fraction ``p`` of moments and
produced a smooth, monotone ICS curve. That invites an appealing shortcut: score
a real system, look its ICS up on the curve, and report "this model comprehends
about p of these moments."

The curve was built from **uniformly random** errors. A real model does not fail
that way -- it fails *systematically*, and this dataset makes that difference
expensive: a false positive in ``quiet_hours`` costs 10.0 (asleep, DND doubled)
while one in ``commerce`` costs 1.0, and the families carry different cue values.

So the question this probe asks is not "does the mapping exist" but:

    Does implied-p survive structured errors, or does it mis-read exactly the
    systems it would be used on?

``FamilyPartialSkyline`` comprehends whole families and guesses on the rest,
holding the *fraction of moments comprehended* roughly fixed while varying
*which* moments those are. If implied-p is a real quantity, subsets with the same
true fraction should land at similar implied values.

    uv run python experiments/implied_comprehension_probe.py
"""

from __future__ import annotations

import random

from tactbench.dataset.loader import load
from tactbench.policies.base import Policy
from tactbench.policies.skyline import PartialSkylinePolicy, SkylinePolicy
from tactbench.runner import evaluate, silence_ics
from tactbench.schema import Decision, Moment

#: Reference curve resolution. Finer than round 7's sweep so inversion is smooth.
CURVE = [i / 20 for i in range(21)]


class FamilyPartialSkyline(Policy):
    """Comprehends whole families, guesses elsewhere. Structured errors."""

    def __init__(self, families: frozenset[str], seed: int = 0):
        self.families = families
        self.name = "family-partial:" + ",".join(sorted(families))
        self._skyline = SkylinePolicy()
        self._rng = random.Random(seed)

    def decide(self, moment: Moment) -> Decision:
        if moment.family in self.families:
            return self._skyline.decide(moment)
        surface = self._rng.random() < 0.5
        return Decision(
            moment_id=moment.id,
            surface=surface,
            confidence=0.5,
            intent="alert" if surface else None,
        )


def build_curve(items, reference) -> list[tuple[float, float]]:
    return [(p, evaluate(PartialSkylinePolicy(p), items, reference=reference).ics) for p in CURVE]


def implied_p(ics: float, curve: list[tuple[float, float]]) -> float:
    """Invert the reference curve by linear interpolation. Clamps outside it."""
    if ics >= curve[0][1]:
        return 0.0
    if ics <= curve[-1][1]:
        return 1.0
    for (p_a, c_a), (p_b, c_b) in zip(curve, curve[1:], strict=False):
        if c_a >= ics >= c_b:
            span = c_a - c_b
            return p_a + ((c_a - ics) / span if span else 0) * (p_b - p_a)
    return 0.0


def main() -> None:
    items = load("v1", "dev")
    reference = silence_ics(items)
    curve = build_curve(items, reference)
    families = sorted({i.moment.family for i in items})

    # Subsets chosen to hold the moment count roughly level while swapping which
    # families are understood: cheap/low-stakes versus expensive/protected.
    cheap = frozenset({"commerce", "health", "meeting_prep"})
    costly = frozenset({"quiet_hours", "driving", "childcare"})
    mixed = frozenset({"travel", "deadline", "finance"})

    print(f"silence ICS {reference:.1f} · families: {', '.join(families)}\n")
    header = f"{'comprehended families':<34} {'true frac':>10} {'ICS':>8}"
    print(f"{header} {'implied p':>10} {'error':>8}")

    rows = []
    for label, subset in (
        ("cheap (commerce/health/prep)", cheap),
        ("mixed (travel/deadline/finance)", mixed),
        ("costly (quiet/driving/childcare)", costly),
    ):
        policy = FamilyPartialSkyline(subset)
        card = evaluate(policy, items, reference=reference)
        true_frac = sum(1 for i in items if i.moment.family in subset) / len(items)
        est = implied_p(card.ics, curve)
        rows.append((label, true_frac, card.ics, est))
        row = f"{label:<34} {true_frac:>10.3f} {card.ics:>8.1f}"
        print(f"{row} {est:>10.3f} {est - true_frac:>+8.3f}")

    spread = max(r[3] for r in rows) - min(r[3] for r in rows)
    true_spread = max(r[1] for r in rows) - min(r[1] for r in rows)

    print()
    print(f"true fraction varies by {true_spread:.3f}; implied p varies by {spread:.3f}")
    print()
    if spread > 3 * max(true_spread, 0.01):
        print(
            "IMPLIED-p IS NOT A REAL QUANTITY under structured errors.\n"
            "Three systems understanding the same share of moments land at very\n"
            "different implied values, purely from WHICH families they understand.\n"
            "Reporting a bare implied-p for a real model would be misleading."
        )
    else:
        print("Implied-p is stable across structured errors; safe to report.")


if __name__ == "__main__":
    main()
