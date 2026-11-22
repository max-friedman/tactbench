"""Does a bag of letter counts, fit on dev, read a family's held-out test? Round 71.

The per-letter gate in ``tests/test_dataset_v6.py`` tests one letter at a time. A
weighted *combination* of letters can pass it and still read the label: the R71 review
found one at 24 of 24 on held-out ``street_cleaning``. This probe measures that class.

For each moment it compares the two decider clauses with the filler removed: the clause
naming the body's marker (the swept street, the notice district, the motion zone) and
the other one. Each letter a-z contributes the sign of its count difference. Weights
are the per-letter correlation with the label on the training moments; a moment is
predicted by the sign of the weighted sum (0 scores a half).

Two readings, because readings are fixed by the frame: test is only three frames,
so dev->test is three frame-level coin flips (a fixed learner gets 3 of 3 with
probability 1/8). Leave-one-frame-out over all eight frames is the steadier figure,
and R73 judges it against an exact null (:func:`orientation_null`), gated in
``tests/test_letter_bag_null.py``.

    uv run python experiments/letter_bag_probe.py
"""

from __future__ import annotations

import re
import string

from tactbench.dataset.generate import ALL_FRAMES, WHO
from tactbench.dataset.loader import load
from tactbench.policies.skyline import (
    _BOIL_DISTRICT,
    _GATE_CHANGE,
    _MARKERS,
    _MOTION_ZONE,
    _OVERFLOW_SITE,
    _RETURN_ITEM,
    _SKIPPED_PET,
    _SWEPT_STREET,
)
from tactbench.schema import policy_view

#: Families whose marker is read from the body, with the dataset that introduced them
#: and the skyline's regex for the marker (its first non-empty group). R71 measured
#: ``home_security``, ``water_notice`` and ``street_cleaning``; R73 added the rest; R74
#: added ``river_swim``.
FAMILIES: dict[str, tuple[str, re.Pattern[str] | str]] = {
    "travel": ("v1", _GATE_CHANGE),
    "commerce": ("v1", _RETURN_ITEM),
    "pet_care": ("v3", _SKIPPED_PET),
    "home_security": ("v4", _MOTION_ZONE),
    "water_notice": ("v5", _BOIL_DISTRICT),
    "street_cleaning": ("v6", _SWEPT_STREET),
    "river_swim": ("v7", _OVERFLOW_SITE),
}
#: The seven families whose marker is a constant (the skyline's ``_MARKERS``), added in
#: R73 so the null covers every family.
FAMILIES.update({f: ("v1", m) for f, m in _MARKERS.items() if m is not None and f not in FAMILIES})
#: Versions on disk that carry every family above from its first one.
LATEST = 7
LETTERS = string.ascii_lowercase


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def _template(family: str, clause: str) -> str:
    """The frame text of a rendered clause, filler removed. Matched against the
    family's templates rather than by dropping the last word, because a filler can be
    several words (commerce's items)."""
    prefixes = [t.split(WHO)[0] for pair in ALL_FRAMES[family] for t in pair]
    assert all(t.endswith(WHO) for pair in ALL_FRAMES[family] for t in pair), family
    best = max((p for p in prefixes if clause.startswith(p)), key=len)
    return best.strip().lower()


def rows(version: str, family: str, split: str) -> list[tuple[str, list[int], int]]:
    """(frame key, letter-difference signs, label as +1/-1) per moment."""
    return item_rows(load(version, split), family)


def clause_rows(items, family: str) -> list[tuple[str, str, str, bool]]:
    """(frame key, privileged-clause template, other template, label) per moment, the
    privileged clause being the one naming the marker. Shared with
    ``char_nb_probe.py``."""
    marker = FAMILIES[family][1]
    out = []
    for item in items:
        if item.moment.family != family:
            continue
        view = policy_view(item.moment)
        clauses = [c.rstrip(".") for c in view.signals[-1].content.split(". ")]
        if isinstance(marker, str):
            # A constant marker ("you", "your route"): the clause ending in it, which
            # must be exactly one of the two.
            hits = [k for k, c in enumerate(clauses) if c.lower().endswith(" " + marker)]
        else:
            found = marker.search(view.signals[0].content)
            # Compared on the last word, as tests/test_marker_order.py does: commerce's
            # filler is the item's head noun ("the lens" for "camera lens").
            name = next(g for g in found.groups() if g).split()[-1].lower()
            hits = [k for k, c in enumerate(clauses) if c.split()[-1].lower() == name]
        assert len(hits) == 1, (family, view.signals[-1].content)
        i = hits[0]
        mine, other = _template(family, clauses[i]), _template(family, clauses[1 - i])
        out.append((" | ".join(sorted([mine, other])), mine, other, item.label.should_surface))
    return out


def item_rows(items, family: str) -> list[tuple[str, list[int], int]]:
    """As :func:`rows`, from any items (a mutated build, for a test)."""
    return [
        (key, [_sign(mine.count(ch) - other.count(ch)) for ch in LETTERS], 1 if y else -1)
        for key, mine, other, y in clause_rows(items, family)
    ]


def _fit(train) -> list[int]:
    # Integer weights (the correlation times the training size), so every prediction
    # below is exact. With float weights, sums that are exactly zero came out as tiny
    # positive or negative numbers depending on the Python version's float summation
    # (3.12 changed it), and v4's reading flipped between 83.3% and 100% (R71 CI).
    return [sum(x[j] * y for _, x, y in train) for j in range(len(LETTERS))]


def _accuracy(weights, test) -> float:
    score = 0.0
    for _, x, y in test:
        p = _sign(sum(w * v for w, v in zip(weights, x, strict=True)))
        score += 0.5 if p == 0 else float(p == y)
    return score / len(test)


def _lofo(allr, frames) -> list[float]:
    out = []
    for f in frames:
        train = [r for r in allr if r[0] != f]
        held = [r for r in allr if r[0] == f]
        out.append(_accuracy(_fit(train), held))
    return out


def measure(family: str, version: str | None = None) -> tuple[float, list[float]]:
    """(dev->test accuracy, leave-one-frame-out accuracy per frame)."""
    version = version or FAMILIES[family][0]
    dev, test = rows(version, family, "dev"), rows(version, family, "test")
    allr = dev + test
    frames = sorted({k for k, _, _ in allr})
    assert len(frames) == 8, (family, len(frames))
    return _accuracy(_fit(dev), test), _lofo(allr, frames)


def orientation_null(family: str, version: str | None = None) -> tuple[float, float]:
    """(leave-one-frame-out accuracy, its exact p-value). Round 73.

    Readings are fixed by the frames, so the right null asks what the same learner
    reads when nothing about the letters is tied to the label. Swapping which clause of
    a frame is the privileged one negates every letter difference in that frame and
    leaves the label alone, so the 2**8 orientations of the eight frames are an exact,
    exhaustive null. p is the share of them reading at least the observed accuracy
    (the observed orientation included, so p >= 1/256)."""

    version = version or FAMILIES[family][0]
    return null_of_rows(rows(version, family, "dev") + rows(version, family, "test"))


def null_of_rows(allr) -> tuple[float, float]:
    """:func:`orientation_null` over rows already built."""
    from itertools import product

    frames = sorted({k for k, _, _ in allr})
    assert len(frames) == 8, len(frames)
    observed = sum(_lofo(allr, frames)) / 8
    at_least = 0
    for signs in product((1, -1), repeat=8):
        flip = dict(zip(frames, signs, strict=True))
        flipped = [(k, [flip[k] * v for v in x], y) for k, x, y in allr]
        at_least += sum(_lofo(flipped, frames)) / 8 >= observed - 1e-12
    return observed, at_least / 2**8


def main() -> None:
    for family, (first, _) in FAMILIES.items():
        acc, lofo = measure(family)
        hits = sum(a > 0.5 for a in lofo)
        print(
            f"{family:16} {first}  dev->test {acc:.1%}  "
            f"leave-one-frame-out {sum(lofo) / len(lofo):.1%} ({hits} of 8 frames above half)"
        )
    print("exact orientation null (leave-one-frame-out, p), every version carrying the family:")
    for family, (first, _) in FAMILIES.items():
        cells = []
        for v in range(int(first[1:]), LATEST + 1):
            obs, p = orientation_null(family, f"v{v}")
            cells.append(f"v{v} {obs:.1%} p={p:.3f}")
        print(f"  {family:16} " + "  ".join(cells))


if __name__ == "__main__":
    main()
