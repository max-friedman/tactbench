"""Does clause *character* length give the label away? Round 45 review.

Frames are held to equal token counts (``TestProseFrameStructure``), not equal
character counts. If a family's privileged clause is usually the longer one, a reader
that can locate the marker's clause -- trivial when the marker is ``you``, or the first
name in a body -- answers by comparing lengths.

Two readings:

- **frame lean**: per family, in how many frames the privileged template is longer,
  shorter, or equal (fillers removed). A rule learned on the dev frames (0-4) is then
  applied to the held-out frames (5-7): that is what transfers.
- **exploit** (the R45 reviewer's): find the marker in the body (the pet that
  skipped, the zone with motion), find the decider clause ending in it, speak iff
  that clause is the longer of the two with the fillers removed; ties count one
  half. ``feature_exploit`` does the same for other clause features (R47).

    uv run python experiments/clause_length_probe.py
"""

from __future__ import annotations

from tactbench.dataset.generate import ALL_FRAMES, HELD_OUT_FRAMES, WHO
from tactbench.dataset.loader import load
from tactbench.policies.skyline import _BOIL_DISTRICT, _MOTION_ZONE, _SKIPPED_PET
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


def _marker(item: Item) -> str:
    """The value that means *speak* in the privileged role, read from the body the way
    the skyline reads it. R47 review: taking the first pool name in the body was the
    marker for pet_care's first draft only -- once body order was balanced, that rule
    flips sign at random against the label and reads ~50% whatever the frames do."""
    body = item.moment.signals[0].content
    if item.moment.family == "home_security":
        return _MOTION_ZONE.search(body).group(1)
    if item.moment.family == "water_notice":
        return _BOIL_DISTRICT.search(body).group(1)
    return next(g for g in _SKIPPED_PET.search(body).groups() if g)


#: Clause features a reader could compare once it has found the marker's clause.
#: ``chars`` is the R45 rule; the rest were found by the R47 review (``er`` read
#: 90% dev / 83% test on the first home_security draft).
FEATURES = {
    "chars": lambda c: len(c),
    "er": lambda c: sum(w.lower().rstrip("s").endswith("er") for w in c.split()),
    "s": lambda c: sum(w.endswith("s") for w in c.split()),
    "ing": lambda c: sum(w.endswith("ing") for w in c.split()),
    "ed": lambda c: sum(w.endswith("ed") for w in c.split()),
    "longest": lambda c: max(len(w) for w in c.split()),
}


def feature_exploit(items: list[Item], family: str, feature: str = "chars") -> float:
    """Speak iff the marker's clause has more of ``feature`` (fillers removed); ties 1/2."""
    f = FEATURES[feature]
    score = 0.0
    chosen = [i for i in items if i.moment.family == family]
    for item in chosen:
        marker = _marker(item)
        clauses = [c.rstrip(".").split() for c in item.moment.signals[-1].content.split(". ")]
        mine = next(c for c in clauses if c[-1] == marker)
        other = next(c for c in clauses if c is not mine)
        fm, fo = f(" ".join(mine[:-1])), f(" ".join(other[:-1]))
        score += 0.5 if fm == fo else float((fm > fo) == item.label.should_surface)
    return score / len(chosen)


def length_exploit(items: list[Item], family: str) -> float:
    return feature_exploit(items, family, "chars")


def pet_care_exploit(items: list[Item]) -> float:
    return length_exploit(items, "pet_care")


def main() -> None:
    print(f"{'family':<13} {'longer/shorter/tie':>19} {'dev':>6} {'held-out':>9}")
    for family in sorted(ALL_FRAMES):
        leans = [lean(a, b) for a, b in ALL_FRAMES[family]]
        counts = f"{leans.count(1)}/{leans.count(-1)}/{leans.count(0)}"
        dev, held = transfer(family)
        print(f"{family:<13} {counts:>19} {dev:>6.2f} {held:>9.2f}")
    for split in ("dev", "test"):
        print(f"pet_care exploit on v3/{split}: {pet_care_exploit(load('v3', split)):.1%}")
        hs = length_exploit(load("v4", split), "home_security")
        print(f"home_security exploit on v4/{split}: {hs:.1%}")


if __name__ == "__main__":
    main()
