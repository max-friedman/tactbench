"""How much of the headline comes from one family?

Round 8's per-family breakdown showed enormous spread: ``always`` costs 9.71 per
moment in ``quiet_hours`` and 0.42 in ``commerce``. Round 1's shortcut audit
showed ``quiet_hours`` is the single family that does **not** sit at the chance
floor -- it probes at 100%, because severity is not a token permutation.

Those two facts are uncomfortable together. If the family driving most of the
score is also the family a keyword matcher can solve, then the benchmark's
headline is substantially decided by its least shortcut-resistant component, and
eight of the nine families are along for the ride.

This probe measures it two ways:

1. **Share of total cost** -- what fraction of each policy's ICS comes from each
   family.
2. **Leave-one-family-out** -- drop a family entirely, rescore, and see how far
   the normalized standings move. A family whose removal barely moves anything is
   decorative; one whose removal reorders the board is load-bearing.

    uv run python experiments/family_concentration_probe.py
"""

from __future__ import annotations

from tactbench.dataset.loader import load
from tactbench.metrics import score
from tactbench.policies.builtin import registry
from tactbench.runner import run_policy, silence_ics


def per_family_totals(items, decisions) -> dict[str, float]:
    """Summed (not averaged) cost per family, so shares add to the total."""
    card = score(items, decisions, "probe")
    cost_by_id = {o.moment_id: o.cost for o in card.outcomes}
    totals: dict[str, float] = {}
    for item in items:
        totals[item.moment.family] = (
            totals.get(item.moment.family, 0.0) + cost_by_id[item.moment.id]
        )
    return totals


def main() -> None:
    items = load("v1", "dev")
    families = sorted({i.moment.family for i in items})
    counts = {f: sum(1 for i in items if i.moment.family == f) for f in families}
    policies = registry()

    # 1. Share of each policy's total cost, by family.
    print("Share of each policy's total ICS, by family\n")
    header = f"{'family':<14}{'n':>5}" + "".join(f"{p:>13}" for p in policies)
    print(header)
    totals = {name: per_family_totals(items, run_policy(p, items)) for name, p in policies.items()}
    grand = {name: sum(t.values()) for name, t in totals.items()}

    for fam in families:
        row = f"{fam:<14}{counts[fam]:>5}"
        for name in policies:
            share = totals[name][fam] / grand[name] if grand[name] else 0.0
            row += f"{share:>12.1%}"
        print(row)

    print()
    share_of_moments = {f: counts[f] / len(items) for f in families}
    print(
        f"(each family is {min(share_of_moments.values()):.1%}-"
        f"{max(share_of_moments.values()):.1%} of moments)"
    )

    # 2. Leave-one-family-out: how far do the standings move without it?
    print("\n\nLeave-one-family-out — change in 'vs silence' for each policy\n")
    base_ref = silence_ics(items)
    base = {
        name: 100.0 * (1 - score(items, run_policy(p, items), name).ics / base_ref)
        for name, p in policies.items()
    }

    print(f"{'dropped family':<16}" + "".join(f"{p:>13}" for p in policies))
    swings = {}
    for fam in families:
        kept = [i for i in items if i.moment.family != fam]
        ref = silence_ics(kept)
        row = f"{fam:<16}"
        worst = 0.0
        for name, p in policies.items():
            norm = 100.0 * (1 - score(kept, run_policy(p, kept), name).ics / ref) if ref else 0.0
            delta = norm - base[name]
            worst = max(worst, abs(delta))
            row += f"{delta:>+12.1f}"
        swings[fam] = worst
        print(row)

    print()
    ranked = sorted(swings.items(), key=lambda kv: -kv[1])
    for fam, swing in ranked:
        print(f"  {fam:<14} max swing {swing:>6.1f} points")

    # The swing table above ranks by the LARGEST movement across any policy, which
    # lets random@0.5 dominate -- its per-family costs are noise, so it swings
    # wildly everywhere and tells us nothing about concentration. The headline
    # claim of this benchmark is that `always` loses badly to silence, so measure
    # each family's contribution to exactly that gap.
    print("\n\nContribution to the headline gap (always vs silence)\n")
    always_t = totals["always"]
    never_t = totals["never"]
    gap = grand["always"] - grand["never"]
    contrib = {f: (always_t[f] - never_t[f]) / gap for f in families}
    for fam, share in sorted(contrib.items(), key=lambda kv: -kv[1]):
        print(f"  {fam:<14} {share:>7.1%}   ({share_of_moments[fam]:.1%} of moments)")

    top_fam, top_share = max(contrib.items(), key=lambda kv: kv[1])
    print()
    if top_share > 0.4:
        print(
            f"CONCENTRATED: '{top_fam}' drives {top_share:.0%} of the gap that the\n"
            f"benchmark's headline rests on, from {share_of_moments[top_fam]:.0%} of the moments."
        )
    else:
        print(f"Not concentrated: largest contributor '{top_fam}' at {top_share:.0%}.")


if __name__ == "__main__":
    main()
