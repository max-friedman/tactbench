"""Does clause *character* length give the label away? Round 45 review.

Frames are held to equal token counts (``TestProseFrameStructure``), not equal
character counts. If a family's privileged clause is usually the longer one, a reader
that can locate the marker's clause -- trivial when the marker is ``you``, or the first
name in a body -- answers by comparing lengths.

Two readings:

- **frame lean**: per family, in how many frames the privileged template is longer,
  shorter, or equal (fillers removed). A rule learned on the dev frames (0-4) is then
  applied to the held-out frames (5-7): that is what transfers.
- **pet_care exploit** (the reviewer's): take the first pet name in the body as the
  marker, find the decider clause ending in it, speak iff that clause is the longer
  of the two with the names removed; ties count one half.

    uv run python experiments/clause_length_probe.py
"""

from __future__ import annotations

import re

from tactbench.dataset.generate import ALL_FRAMES, HELD_OUT_FRAMES, PETS, WHO
from tactbench.dataset.loader import load
from tactbench.schema import Item


def lean(a: str, b: str) -> int:
    la, lb = len(a.replace(WHO, "")), len(b.replace(WHO, ""))
    return (la > lb) - (la < lb)


def transfer(family: str) -> tuple[float, float]:
    """(dev accuracy, held-out accuracy) of the dev-majority length rule, by frame."""
    leans = [lean(a, b) for a, b in ALL_FRAMES[family]]
    dev = [x for k, x in enumerate(leans) if k not in HELD_OUT_FRAMES]
    held = [x for k, x in enumerate(leans) if k in HELD_OUT_FRAMES]
    sign = (sum(dev) > 0) - (sum(dev) < 0)

    def acc(xs: list[int]) -> float:
        return sum(0.5 if x == 0 or sign == 0 else float(x == sign) for x in xs) / len(xs)

    return acc(dev), acc(held)


def pet_care_exploit(items: list[Item]) -> float:
    names = "|".join(PETS)
    score = 0.0
    pets = [i for i in items if i.moment.family == "pet_care"]
    for item in pets:
        body, decider = item.moment.signals[0].content, item.moment.signals[-1].content
        marker = re.search(rf"\b({names})\b", body).group(1)
        clauses = [c.rstrip(".") for c in decider.split(". ")]
        mine = next(c for c in clauses if c.endswith(marker))
        other = next(c for c in clauses if c is not mine)
        lm = len(mine) - len(marker)
        lo = len(other) - len(other.split()[-1])
        guess = 0.5 if lm == lo else float((lm > lo) == item.label.should_surface)
        score += guess
    return score / len(pets)


def main() -> None:
    print(f"{'family':<13} {'longer/shorter/tie':>19} {'dev':>6} {'held-out':>9}")
    for family in sorted(ALL_FRAMES):
        leans = [lean(a, b) for a, b in ALL_FRAMES[family]]
        counts = f"{leans.count(1)}/{leans.count(-1)}/{leans.count(0)}"
        dev, held = transfer(family)
        print(f"{family:<13} {counts:>19} {dev:>6.2f} {held:>9.2f}")
    for split in ("dev", "test"):
        print(f"pet_care exploit on v3/{split}: {pet_care_exploit(load('v3', split)):.1%}")


if __name__ == "__main__":
    main()
