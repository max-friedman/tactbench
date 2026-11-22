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
probability 1/8). Leave-one-frame-out over all eight frames is the steadier figure.

    uv run python experiments/letter_bag_probe.py
"""

from __future__ import annotations

import string

from tactbench.dataset.loader import load
from tactbench.policies.skyline import _BOIL_DISTRICT, _MOTION_ZONE, _SWEPT_STREET
from tactbench.schema import policy_view

#: Families whose marker is read from the body, with the dataset that introduced them.
FAMILIES = {
    "home_security": ("v4", _MOTION_ZONE),
    "water_notice": ("v5", _BOIL_DISTRICT),
    "street_cleaning": ("v6", _SWEPT_STREET),
}
LETTERS = string.ascii_lowercase


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def rows(version: str, family: str, split: str) -> list[tuple[str, list[int], int]]:
    """(frame key, letter-difference signs, label as +1/-1) per moment."""
    marker = FAMILIES[family][1]
    out = []
    for item in load(version, split):
        if item.moment.family != family:
            continue
        view = policy_view(item.moment)
        name = marker.search(view.signals[0].content).group(1)
        clauses = [c.rstrip(".").split() for c in view.signals[-1].content.split(". ")]
        i = next(k for k, words in enumerate(clauses) if words[-1] == name)
        mine, other = " ".join(clauses[i][:-1]).lower(), " ".join(clauses[1 - i][:-1]).lower()
        diff = [_sign(mine.count(ch) - other.count(ch)) for ch in LETTERS]
        out.append(
            (" | ".join(sorted([mine, other])), diff, 1 if item.label.should_surface else -1)
        )
    return out


def _fit(train):
    return [sum(x[j] * y for _, x, y in train) / len(train) for j in range(len(LETTERS))]


def _accuracy(weights, test) -> float:
    score = 0.0
    for _, x, y in test:
        p = _sign(sum(w * v for w, v in zip(weights, x, strict=True)))
        score += 0.5 if p == 0 else float(p == y)
    return score / len(test)


def measure(family: str) -> tuple[float, list[float]]:
    """(dev->test accuracy, leave-one-frame-out accuracy per frame)."""
    version = FAMILIES[family][0]
    dev, test = rows(version, family, "dev"), rows(version, family, "test")
    allr = dev + test
    frames = sorted({k for k, _, _ in allr})
    assert len(frames) == 8, (family, len(frames))
    lofo = []
    for f in frames:
        train = [r for r in allr if r[0] != f]
        held = [r for r in allr if r[0] == f]
        lofo.append(_accuracy(_fit(train), held))
    return _accuracy(_fit(dev), test), lofo


def main() -> None:
    for family in FAMILIES:
        acc, lofo = measure(family)
        hits = sum(a > 0.5 for a in lofo)
        print(
            f"{family:16} {FAMILIES[family][0]}  dev->test {acc:.1%}  "
            f"leave-one-frame-out {sum(lofo) / len(lofo):.1%} ({hits} of 8 frames above half)"
        )


if __name__ == "__main__":
    main()
