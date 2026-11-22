"""Where the random marker sits in the decider, for every random-marker family. Round 55.

Eight families draw their marker at random -- the gate boarding moved away from, the
item whose return window closes, the pet that skipped a meal, the zone with motion, the
district under a boil-water notice, (v6) the street swept tomorrow, (v7) the place
a sewage overflow is discharging into a river, and (v8) the photo album deleted at
midnight -- so the
token-positional probe cannot see which clause names it (R52 review). The check that
can: read the marker from the body, as the skyline does, and ask whether the first
decider clause names it. Within each label that must hold exactly half the time, so
"speak iff the marker is named first" reads exactly 50%. R52 gated this for
`water_notice`; here it covers all of them, on every version that carries them. v1
fails it for `travel` and `commerce`, as it fails cell balance (R36's strict xfail):
20 pairs over 8 frames leave dev 9:5 by order.

This is the privileged-first fraction read through the marker, so it is the same order
property cell balance tests, made exact. It holds on the committed builds (32 pairs
over 8 frames); a build whose pair count is not a multiple of 16 can break it.
"""

from __future__ import annotations

import pytest

from tactbench.dataset.generate import Scenario, generate
from tactbench.dataset.loader import load
from tactbench.policies.skyline import (
    _BOIL_DISTRICT,
    _DELETED_ALBUM,
    _GATE_CHANGE,
    _MARKERS,
    _MOTION_ZONE,
    _OVERFLOW_SITE,
    _RETURN_ITEM,
    _SKIPPED_PET,
    _SWEPT_STREET,
)

#: The body regex the skyline reads each marker with; the first non-empty group.
MARKERS = {
    "travel": _GATE_CHANGE,
    "commerce": _RETURN_ITEM,
    "pet_care": _SKIPPED_PET,
    "home_security": _MOTION_ZONE,
    "water_notice": _BOIL_DISTRICT,
    "street_cleaning": _SWEPT_STREET,
    "river_swim": _OVERFLOW_SITE,
    "photo_backup": _DELETED_ALBUM,
}
#: First version carrying each family; every later version carries it unchanged.
SINCE = {
    "travel": 1,
    "commerce": 1,
    "pet_care": 3,
    "home_security": 4,
    "water_notice": 5,
    "street_cleaning": 6,
    "river_swim": 7,
    "photo_backup": 8,
}
LATEST = 8
V1_IMBALANCE = pytest.mark.xfail(
    strict=True, reason="R36: v1's 20 pairs over 8 frames leave dev 9:5 by clause order"
)
CASES = [
    pytest.param(f"v{v}", family, split, marks=[V1_IMBALANCE] if (v, split) == (1, "dev") else [])
    for family, first in SINCE.items()
    for v in range(first, LATEST + 1)
    for split in ("dev", "test")
]


def marker_first(item) -> bool:
    """Is the family's marker, read from the body, named in the decider's first clause?
    Compared on the last word: every frame ends with its filler, and commerce's filler
    is the item's head noun ("the lens" for "camera lens"), as the skyline reads it."""
    found = MARKERS[item.moment.family].search(item.moment.signals[0].content)
    marker = next(g for g in found.groups() if g).split()[-1].lower()
    first = item.moment.signals[-1].content.split(". ")[0]
    return first.rstrip(".").split()[-1].lower() == marker


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
    """Every family whose skyline marker is read from the body (``None`` in
    ``_MARKERS``) is checked here, so a future one cannot be missed."""
    assert {f for f, m in _MARKERS.items() if m is None} == set(MARKERS) == set(SINCE)
    families = {i.moment.family for i in load(f"v{LATEST}", "dev")}
    assert set(MARKERS) <= families
    for family, first in SINCE.items():
        assert any(i.moment.family == family for i in load(f"v{first}", "dev"))
        if first > 1:
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
    assert order_rule(generate(32, 20260726, families=15), family) == 1.0
