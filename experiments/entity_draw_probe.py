"""Does drawing an entity into a seed-invariant decider fix its positional reading?
Round 35, queue item E -- built, measured, rejected.

R25: ``driving``'s deciders contain no seed-drawn entity, so the positional probe
reads a constant 63.3% (above the 60% per-family bound) on every seed; ``finance``
is seed-invariant too (above 60% on 17 of 20). The proposed fix was a ``v2`` dataset
drawing an entity into both families' fillers. This script reproduces it without
changing the shipped generator: it patches the two ``fillers`` methods (the patch
shifts the shared random stream, so only these two families' figures are meaningful
here) and measures 20 seeds.

Result (this script, Round 35): driving stops being constant -- 6 distinct readings,
53.3-76.7% -- but is still above 60% on 9 of 20 seeds, and its worst seed is worse
than the old constant; finance stays above 60% on 19 of 20. A full v2 build with a
private random stream for the draws (not kept) gave the same picture: driving
50.0-81.7%, 10 of 20; finance 19 of 20. The leak is in where the role words sit
within the frames, not in a missing entity.

    uv run python experiments/entity_draw_probe.py
"""

from __future__ import annotations

from unittest import mock

from tactbench.audit import positional_leakage
from tactbench.dataset.generate import (
    HELD_OUT_FRAMES,
    DrivingScenario,
    FinanceScenario,
    generate,
)
from tactbench.schema import frame_of

SEEDS = range(20260726, 20260746)
ROADS = ["Route 9", "the river road", "Elm Street", "the ring road", "Highway 4",
         "the old coast road", "Bridge Street", "the north bypass", "Mill Lane",
         "the county road past the quarry", "Station Avenue", "the frontage road"]  # fmt: skip


def driving(self, rng):
    return "your route", f"the alternate via {rng.choice(ROADS)}"


def finance(self, rng):
    a, b = rng.sample(range(1000, 10000), 2)
    return f"checking ending {a}", f"savings ending {b}"


def spread(family: str) -> list[float]:
    out = []
    for seed in SEEDS:
        items = generate(20, seed)
        dev = [i for i in items if frame_of(i.moment) not in HELD_OUT_FRAMES]
        out.append(
            positional_leakage([i for i in dev if i.moment.family == family]).exploitable_accuracy
        )
    return out


def report(label: str) -> None:
    for family in ("driving", "finance"):
        r = spread(family)
        above = sum(x > 0.6 for x in r)
        distinct = len({round(x, 4) for x in r})
        print(f"{label:<14} {family:<8} {min(r):.1%}-{max(r):.1%}  "
              f"seeds >60%: {above:>2}/20  distinct: {distinct}")  # fmt: skip


def main() -> None:
    report("shipped")
    with (
        mock.patch.object(DrivingScenario, "fillers", driving),
        mock.patch.object(FinanceScenario, "fillers", finance),
    ):
        report("entity drawn")


if __name__ == "__main__":
    main()
