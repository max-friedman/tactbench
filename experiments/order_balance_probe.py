"""Why ``driving`` and ``finance`` exceed the positional bound. Round 36.

Clause order alternates on ``idx // n_frames`` (8 frames), so a (family, frame) cell
is balanced -- as many pairs in each clause order -- only when it holds an even
number of pairs, i.e. when pairs per family is a multiple of 16. The shipped 20
gives cells of 3 pairs (2:1) in frames 0-3: dev is 9:5 by order in every family.
A positional probe learns the majority order. Families whose deciders never vary
(``driving``) show it undiluted -- the fixed 63.3% R25 found.

Two hypotheses this round tested and **rejected** before landing here:

- *missing entities* (R35): drawing entities into the fillers leaves the leak;
- *global imbalance*: offsetting the alternation by frame balances dev 7:7 overall,
  yet driving still reads 63.3% -- the probe's raw accuracy flips to 36.7%, and the
  audit (rightly) counts a negated classifier as exploitable. Cells of 3 pairs stay
  2:1 whatever the rule.

So the fix is the size: at 16 or 32 pairs per family every cell is balanced, and
driving reads exactly 50.0% on every seed. That needs no code change -- a versioned
build at a different ``--pairs`` -- which keeps ``v1`` and its LLM results intact.

    uv run python experiments/order_balance_probe.py
"""

from __future__ import annotations

import statistics

from tactbench.audit import positional_leakage
from tactbench.dataset.generate import FRAMES, HELD_OUT_FRAMES, generate
from tactbench.schema import frame_of

SEEDS = range(20260726, 20260746)


def per_family(n: int) -> dict[str, list[float]]:
    """Positional exploitable accuracy per family over SEEDS, at ``n`` pairs."""
    out: dict[str, list[float]] = {f: [] for f in sorted(FRAMES)}
    for seed in SEEDS:
        dev = [i for i in generate(n, seed) if frame_of(i.moment) not in HELD_OUT_FRAMES]
        for f in out:
            sub = [i for i in dev if i.moment.family == f]
            out[f].append(positional_leakage(sub).exploitable_accuracy)
    return out


def main() -> None:
    print("pairs  family    exploitable range   seeds >60%   raw accuracy range")
    for n in (16, 20, 24, 32):
        for family in ("driving", "finance", None):
            ex, raw = [], []
            for seed in SEEDS:
                dev = [i for i in generate(n, seed) if frame_of(i.moment) not in HELD_OUT_FRAMES]
                sub = dev if family is None else [i for i in dev if i.moment.family == family]
                r = positional_leakage(sub)
                ex.append(r.exploitable_accuracy)
                raw.append(r.accuracy)
            above = sum(x > 0.6 for x in ex)
            print(
                f"{n:>5}  {family or 'overall':<8}  {min(ex):6.1%} - {max(ex):6.1%}"
                f"   {above:>2}/20        {min(raw):6.1%} - {max(raw):6.1%}"
            )

    print("\nevery family, 20 vs 32 pairs (Round 37): median, seeds above 60%")
    a, b = per_family(20), per_family(32)
    for f in a:
        print(
            f"  {f:<13} {statistics.median(a[f]):6.1%} {sum(x > 0.6 for x in a[f]):>3}/20"
            f"   {statistics.median(b[f]):6.1%} {sum(x > 0.6 for x in b[f]):>3}/20"
        )
    cells = [sum(x > 0.6 for f in d for x in d[f]) for d in (a, b)]
    print(f"  cells above 60%: {cells[0]}/180 at 20 pairs, {cells[1]}/180 at 32 pairs")


if __name__ == "__main__":
    main()
