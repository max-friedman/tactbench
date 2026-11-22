"""Naive Bayes over the decider clauses' characters, against the exact null. Round 74.

The R74 review found that the audit's own naive Bayes, fed the characters of the
clause naming the marker (tagged ``A:``) and of the other clause (``B:``), reads
held-out ``river_swim`` at 24 of 24. It also found that the same learner trained on the
*other* families reads 7 of its 8 frames. This probe measures both readings on every
family, with the exact null of ``letter_bag_probe.orientation_null``: swapping which
clause of a frame is privileged swaps the tags in that frame and leaves the label
alone, so the 2**8 orientations are exhaustive.

Three readings per family and representation (letters, letter pairs):

* dev->test: fit on dev frames, score held-out. Three test frames, so p is at least
  1/8 for a perfect score.
* leave one frame out over all eight.
* transfer: fit on every other family (both splits), score this one's eight frames;
  the null flips only this family's frames.

    uv run python experiments/char_nb_probe.py
"""

from __future__ import annotations

from itertools import product

from letter_bag_probe import FAMILIES, LATEST, clause_rows

from tactbench.audit import _NaiveBayes
from tactbench.dataset.loader import load

REPRESENTATIONS = {
    "letters": lambda c: [ch for ch in c if ch.isalpha()],
    "pairs": lambda c: [c[i : i + 2] for i in range(len(c) - 1) if c[i : i + 2].isalpha()],
}


def _docs(rows, rep, flip=frozenset()):
    f = REPRESENTATIONS[rep]
    out = []
    for key, mine, other, y in rows:
        a, b = (other, mine) if key in flip else (mine, other)
        out.append((key, ["A:" + t for t in f(a)] + ["B:" + t for t in f(b)], y))
    return out


def _score(train, test) -> float:
    nb = _NaiveBayes()
    nb.fit([(t, y) for _, t, y in train])
    return sum(nb.predict(t) == y for _, t, y in test) / len(test)


def _frame_scores(train_of, docs, frames) -> list[float]:
    return [_score(train_of(f), [d for d in docs if d[0] == f]) for f in frames]


def _family_rows(family: str, version: str):
    dev = clause_rows(load(version, "dev"), family)
    test = clause_rows(load(version, "test"), family)
    return dev, test


def readings(family: str, rep: str, version: str = f"v{LATEST}") -> dict[str, tuple[float, float]]:
    """{reading: (observed, exact p)} for one family on one version."""
    dev, test = _family_rows(family, version)
    rows = dev + test
    frames = sorted({r[0] for r in rows})
    dev_frames = {r[0] for r in dev}
    assert len(frames) == 8, (family, len(frames))
    others = (
        [
            r
            for f in FAMILIES
            if f != family
            for r in _family_rows(f, version)[0] + _family_rows(f, version)[1]
        ]
        if _available(version)
        else []
    )

    def dev_test(flip):
        docs = _docs(rows, rep, flip)
        return _score(
            [d for d in docs if d[0] in dev_frames], [d for d in docs if d[0] not in dev_frames]
        )

    def lofo(flip):
        docs = _docs(rows, rep, flip)
        return sum(_frame_scores(lambda f: [d for d in docs if d[0] != f], docs, frames)) / 8

    other_docs = _docs(others, rep)

    def transfer(flip):
        docs = _docs(rows, rep, flip)
        hits = _frame_scores(lambda f: other_docs, docs, frames)
        return sum(h > 0.5 for h in hits) / 8

    out = {}
    for name, fn in (
        ("dev->test", dev_test),
        ("leave-one-frame-out", lofo),
        ("transfer", transfer),
    ):
        observed = fn(frozenset())
        at_least = sum(
            fn(frozenset(f for f, s in zip(frames, signs, strict=True) if s)) >= observed - 1e-12
            for signs in product((0, 1), repeat=8)
        )
        out[name] = (observed, at_least / 2**8)
    return out


def _available(version: str) -> bool:
    return all(int(first[1:]) <= int(version[1:]) for first, _ in FAMILIES.values())


def main() -> None:
    for rep in REPRESENTATIONS:
        print(f"{rep}:")
        for family in FAMILIES:
            r = readings(family, rep)
            print(
                f"  {family:16} " + "  ".join(f"{k} {o:.1%} p={p:.3f}" for k, (o, p) in r.items())
            )


if __name__ == "__main__":
    main()
