"""Negation polarity, every family, against its exact null. Round 78 (queue item Z).

R76 found that "speak iff the marker's clause alone carries a negation word" (a generic
lexicon, ``experiments/negation_probe.py``) solved v8's first ``photo_backup`` frames,
and that ``commerce`` and ``finance`` lean three frames to none. A fixed policy reads
each frame right, wrong or tied; swapping which clause of a frame is privileged swaps
right and wrong and leaves a tie alone. So over the 2**8 orientations the count of
right frames among the k untied ones is Binomial(k, 1/2), and p is exact: the share of
orientations at least as far from even as the shipped one, either way (an inverted
lean is as usable as a straight one).

Pre-registered: a family fails if p < 0.05. Three right of three untied gives p=0.25,
so the published leans do not come close, and this records that; it does not ask that
they be regenerated. Eight of eight, as v8's first frames had, gives p=1/128.
"""

from __future__ import annotations

import sys
from math import comb
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))

import letter_bag_probe as bag  # noqa: E402
import negation_probe as neg  # noqa: E402

ALPHA = 0.05
CASES = [
    (family, f"v{v}")
    for family, (first, _) in bag.FAMILIES.items()
    for v in range(int(first[1:]), bag.LATEST + 1)
]


def exact_p(right: int, wrong: int) -> float:
    """Two-sided: P(|R - W| >= observed) for R ~ Binomial(right + wrong, 1/2)."""
    k = right + wrong
    if k == 0:
        return 1.0
    return sum(comb(k, j) for j in range(k + 1) if abs(2 * j - k) >= abs(right - wrong)) / 2**k


def counts(family: str, version: str) -> tuple[int, int]:
    r = neg.frame_polarity(family, version)
    return (
        r["dev"]["right"] + r["test"]["right"],  # type: ignore[index]
        r["dev"]["wrong"] + r["test"]["wrong"],  # type: ignore[index]
    )


def test_the_null_is_exact():
    assert exact_p(3, 0) == 0.25 and exact_p(8, 0) == 1 / 128 and exact_p(4, 4) == 1.0
    assert exact_p(0, 2) == exact_p(2, 0) == 0.5


@pytest.mark.parametrize(("family", "version"), CASES)
def test_polarity_does_not_beat_its_null(family, version):
    right, wrong = counts(family, version)
    assert right + wrong <= 8
    p = exact_p(right, wrong)
    assert p >= ALPHA, f"{family} on {version}: {right} right / {wrong} wrong frames, p={p:.3f}"


def test_the_null_would_catch_v8s_first_frames():
    """The first photo_backup frames carried the negation on every privileged clause."""
    assert exact_p(8, 0) < ALPHA


def test_the_figures_stated_in_the_docs():
    doc = " ".join((Path(__file__).parents[1] / "docs" / "DATASET.md").read_text().split())
    latest = f"v{bag.LATEST}"
    leans = {f: counts(f, latest) for f in bag.FAMILIES}
    straight = sorted(f for f, (r, w) in leans.items() if r - w >= 2)
    inverted = sorted(f for f, (r, w) in leans.items() if w - r >= 2)
    assert straight == ["commerce", "finance", "health"]
    assert inverted == ["deadline", "driving"]
    assert leans["commerce"] == leans["finance"] == (3, 0)
    assert leans["health"] == (2, 0) and leans["deadline"] == leans["driving"] == (0, 2)
    lowest = min(exact_p(*c) for c in leans.values())
    assert lowest == 0.25
    assert "`commerce` and `finance` lean three frames to none (p=0.250 each)" in doc
    assert "`health` two to none and `deadline` and `driving` none to two (p=0.500)" in doc
    assert f"All {len(CASES)} family-version cells pass" in doc
