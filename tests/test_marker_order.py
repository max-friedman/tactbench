"""Where the random marker sits in the decider, for every random-marker family. Round 55.

Three families draw their marker -- the pet that skipped a meal, the zone with motion,
the district under a boil-water notice -- at random from a list, so the
token-positional probe cannot see which clause names it (R52 review). The check that
can: read the marker from the body, as the skyline does, and ask whether the first
decider clause names it. Within each label that must hold exactly half the time, so
"speak iff the marker is named first" reads exactly 50%. R52 gated this for
`water_notice`; here it covers all three, on every version that carries them.
"""

from __future__ import annotations

import pytest

from tactbench.dataset.generate import Scenario, generate
from tactbench.dataset.loader import load
from tactbench.policies.skyline import _BOIL_DISTRICT, _MOTION_ZONE, _SKIPPED_PET

MARKERS = {"pet_care": _SKIPPED_PET, "home_security": _MOTION_ZONE, "water_notice": _BOIL_DISTRICT}
#: First version carrying each family; every later version carries it unchanged.
SINCE = {"pet_care": 3, "home_security": 4, "water_notice": 5}
LATEST = 5
CASES = [
    (f"v{v}", family, split)
    for family, first in SINCE.items()
    for v in range(first, LATEST + 1)
    for split in ("dev", "test")
]


def marker_first(item) -> bool:
    """Is the family's marker, read from the body, named in the decider's first clause?"""
    found = MARKERS[item.moment.family].search(item.moment.signals[0].content)
    marker = next(g for g in found.groups() if g)
    first = item.moment.signals[-1].content.split(". ")[0]
    return first.rstrip(".").split()[-1] == marker


def order_rule(items, family) -> float:
    """ "Speak iff the marker is named in the first decider clause"."""
    chosen = [i for i in items if i.moment.family == family]
    return sum(marker_first(i) == i.label.should_surface for i in chosen) / len(chosen)


@pytest.mark.parametrize(("version", "family", "split"), CASES)
def test_the_marker_is_first_in_half_of_each_label(version, family, split):
    items = [i for i in load(version, split) if i.moment.family == family]
    assert items, (version, family, split)
    for label in (True, False):
        side = [i for i in items if i.label.should_surface == label]
        assert sum(map(marker_first, side)) * 2 == len(side), (version, family, split, label)
    assert order_rule(items, family) == 0.5


def test_every_random_marker_family_is_covered():
    families = {i.moment.family for i in load(f"v{LATEST}", "dev")}
    assert set(MARKERS) <= families
    for family, first in SINCE.items():
        assert any(i.moment.family == family for i in load(f"v{first}", "dev"))
        assert not any(i.moment.family == family for i in load(f"v{first - 1}", "dev"))


@pytest.mark.parametrize("family", sorted(MARKERS))
def test_the_order_check_would_catch_a_fixed_order(family, monkeypatch):
    """Force the privileged clause first for one family and its rule must read 100%."""
    original = Scenario.render_frame

    def privileged_first(self, frame, rng, idx=0):
        if self.family != family:
            return original(self, frame, rng, idx)
        return original(self, frame, rng, idx - idx % (2 * len(self.frames)))

    monkeypatch.setattr(Scenario, "render_frame", privileged_first)
    assert order_rule(generate(32, 20260726, families=12), family) == 1.0
