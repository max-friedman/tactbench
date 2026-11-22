"""Letter-count combinations, gated against an exact null. Round 73 (queue item V).

R71's review found a dev-fit weighted bag of letter counts reading held-out
``street_cleaning`` at 24 of 24, and the per-letter gate blind to it. Readings are
fixed by the frames, so a dev->test figure over three test frames is three coin flips.
This gates the steadier figure, leave-one-frame-out over all eight frames, against the
exact null: every one of the 2**8 orientations of which clause in each frame is the
privileged one (``experiments/letter_bag_probe.py``).

Pre-registered before any family was measured against the null: a family fails if
at most 5% of orientations read at least what the shipped one reads (p < 0.05).
At 5% each, 13 families give about 0.65 expected false alarms (14 since v7: about 0.70; 15
since v8: about 0.75; 16 since v9: about 0.80),
so a single failure calls for a look at the frames, not a verdict on its own.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))

import letter_bag_probe as bag  # noqa: E402

ALPHA = 0.05
CASES = [
    (family, f"v{v}")
    for family, (first, _) in bag.FAMILIES.items()
    for v in range(int(first[1:]), bag.LATEST + 1)
]


def test_every_family_is_covered():
    from tactbench.dataset.generate import ALL_SCENARIOS

    assert set(bag.FAMILIES) == {s.family for s in ALL_SCENARIOS} and len(bag.FAMILIES) == 16
    assert bag.LATEST == max(
        int(d.name[1:])
        for d in (Path(__file__).parents[1] / "data").iterdir()
        if d.name[1:].isdigit() and d.name.startswith("v")
    )


@pytest.mark.parametrize(("family", "version"), CASES)
def test_no_letter_bag_beats_its_orientation_null(family, version):
    observed, p = bag.orientation_null(family, version)
    assert p >= ALPHA, f"{family} on {version}: leave-one-frame-out {observed:.1%}, p={p:.3f}"


def test_the_null_would_catch_a_lean(monkeypatch):
    """Add a "z" to every privileged clause of street_cleaning: p must fall under 5%."""
    from tactbench.dataset.generate import ALL_FRAMES, LATER_FRAMES, generate

    family = "street_cleaning"
    padded = [(a.replace(" {who}", "z {who}"), b) for a, b in ALL_FRAMES[family]]
    monkeypatch.setitem(LATER_FRAMES, family, padded)
    monkeypatch.setitem(bag.ALL_FRAMES, family, padded)
    items = generate(32, 20260726, families=13)
    observed, p = bag.null_of_rows(bag.item_rows(items, family))
    assert observed == 1.0 and p < ALPHA


def test_the_figures_stated_in_the_docs():
    doc = " ".join((Path(__file__).parents[1] / "docs" / "DATASET.md").read_text().split())
    readings = {(f, v): bag.orientation_null(f, v) for f, v in CASES}
    low = min(readings, key=lambda k: readings[k][1])
    obs, p = readings[low]
    assert low[0] == "home_security"
    assert f"The lowest is `home_security` at p={p:.3f} ({obs:.1%} leaving one frame out)" in doc
    obs, p = readings[("street_cleaning", "v6")]
    assert f"`street_cleaning`'s {obs:.1%} has p={p:.3f}" in doc
    obs, p = readings[("river_swim", "v7")]
    assert f"`river_swim` (v7) reads {obs:.1%} leaving one frame out, p={p:.3f}" in doc
    obs, p = readings[("photo_backup", "v8")]
    assert f"`photo_backup` (v8) reads {obs:.1%} leaving one frame out, p={p:.3f}" in doc
    obs, p = readings[("dinner_booking", "v9")]
    assert f"`dinner_booking` (v9) reads {obs:.1%} leaving one frame out, p={p:.3f}" in doc
    assert f"{len(readings)} family-version cells" in doc
