"""How much do the leakage figures move with the build seed? Rounds 22 and 25.

Reconstructs the committed pipeline (``generate(20, seed)`` then the frame split),
checks the reconstruction equals ``data/v1/dev`` object-for-object at the shipped
seed, and prints -- over 20 seeds -- every probe's overall range and, per family,
the positional range, the number of seeds above the 60% bound, and whether the
family's decider sentences vary with the seed at all.

Round 22 published "6 to 14 seeds out of 20" for the per-family positional count
and had no script producing its 20-seed tables; the review measured 3 to 20. This
script is the before-number for Round 25 and the source for every figure in
``docs/DATASET.md``'s seed section.

    uv run python experiments/seed_spread_probe.py
"""

from __future__ import annotations

from tactbench.audit import lexical_leakage, ngram_leakage, positional_leakage
from tactbench.dataset.generate import FRAMES, HELD_OUT_FRAMES, generate
from tactbench.dataset.loader import load
from tactbench.schema import frame_of

SHIPPED = 20260726
SEEDS = [SHIPPED + k for k in range(20)]
BOUND = 0.60


def dev(seed: int):
    return [
        i
        for i in generate(n_pairs_per_scenario=20, seed=seed)
        if frame_of(i.moment) not in HELD_OUT_FRAMES
    ]


def main() -> None:
    committed = load("v1", "dev")
    assert [i.model_dump() for i in committed] == [i.model_dump() for i in dev(SHIPPED)], (
        "reconstruction differs from data/v1/dev"
    )
    builds = {s: dev(s) for s in SEEDS}

    print(f"{'probe':<11} {'shipped':>8} {'min':>7} {'max':>7}")
    for name, probe in (
        ("unigram", lexical_leakage),
        ("bigram", ngram_leakage),
        ("positional", positional_leakage),
    ):
        r = [probe(builds[s]).exploitable_accuracy for s in SEEDS]
        print(f"{name:<11} {r[0]:>8.1%} {min(r):>7.1%} {max(r):>7.1%}")

    print(f"\n{'family':<13} {'min':>7} {'max':>7} {'>60%':>5} {'decider varies':>15}")
    for fam in sorted(FRAMES):
        r, deciders = [], set()
        for s in SEEDS:
            sub = sorted(
                (i for i in builds[s] if i.moment.family == fam), key=lambda i: i.moment.id
            )
            r.append(positional_leakage(sub).exploitable_accuracy)
            deciders.add(tuple(i.moment.signals[-1].content for i in sub))
        above = sum(x > BOUND for x in r)
        varies = "yes" if len(deciders) > 1 else "no"
        print(f"{fam:<13} {min(r):>7.1%} {max(r):>7.1%} {above:>5} {varies:>15}")


if __name__ == "__main__":
    main()
