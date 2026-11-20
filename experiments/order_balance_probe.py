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

import random
import statistics
from collections import defaultdict

from tactbench.audit import positional_leakage
from tactbench.dataset.generate import FRAMES, HELD_OUT_FRAMES, generate
from tactbench.schema import frame_of, pair_key

SEEDS = range(20260726, 20260746)


def label_swap_null(items: list, rng: random.Random) -> list:
    """Each pair's labels swapped with probability 1/2 -- the same moments, with
    labels independent of the text. What the probe reads here is pure noise at this
    sample size. Round 37's review: per-family readings must be read against it."""
    by_pair: dict[str, list] = defaultdict(list)
    for item in items:
        by_pair[pair_key(item.moment.id)].append(item)
    out = []
    for sides in by_pair.values():
        flip = rng.random() < 0.5
        for item in sides:
            surface = item.label.should_surface != flip
            label = item.label.model_copy(update={"should_surface": surface})
            out.append(item.model_copy(update={"label": label}))
    return out


def sweep(n: int) -> dict:
    """Overall and per-family positional readings over SEEDS, observed and null."""
    rng = random.Random(0)
    res = {"overall": ([], []), **{f: ([], []) for f in sorted(FRAMES)}}
    for seed in SEEDS:
        dev = [i for i in generate(n, seed) if frame_of(i.moment) not in HELD_OUT_FRAMES]
        null = label_swap_null(dev, rng)
        res["overall"][0].append(positional_leakage(dev).exploitable_accuracy)
        res["overall"][1].append(positional_leakage(null).exploitable_accuracy)
        for f in FRAMES:
            for k, data in ((0, dev), (1, null)):
                sub = [i for i in data if i.moment.family == f]
                res[f][k].append(positional_leakage(sub).exploitable_accuracy)
    return res


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

    print("\nobserved vs label-swap null (Round 37), median and seeds above 60%:")
    for n in (20, 32):
        res = sweep(n)
        for name, (obs, null) in res.items():
            print(
                f"  n={n} {name:<13} observed {statistics.median(obs):6.1%} "
                f"{sum(x > 0.6 for x in obs):>2}/20   null {statistics.median(null):6.1%} "
                f"{sum(x > 0.6 for x in null):>2}/20"
            )
        cells = [sum(x > 0.6 for f in FRAMES for x in res[f][k]) for k in (0, 1)]
        print(f"  n={n} family cells above 60%: observed {cells[0]}/180, null {cells[1]}/180")


if __name__ == "__main__":
    main()
