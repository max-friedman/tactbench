"""Is "below chance" the same as "at chance"?

The shortcut audit is the benchmark's central validity check, and both of its
assertions are **upper bounds**::

    assert report.accuracy < 0.70          # overall
    assert accuracy < 0.60                 # every family

A family probing at 32.8% passes both with room to spare, and ``tactbench audit``
prints ``at chance`` next to it. But a classifier that is wrong 67.2% of the time
is not ignorant -- it is *informative*. Negating its output scores 67.2%, which is
above the very threshold the audit claims to enforce.

So the question this probe answers, falsifiably:

    **Is sub-chance probe accuracy a real, exploitable leak that the one-sided
    audit is blind to -- or is it noise from a small per-family sample?**

Three measurements, in increasing strength of evidence:

1. **Signed leakage.** Report ``|accuracy - 0.5|`` per family, and how many
   standard errors that is from chance. Distance from chance is what leakage
   means; direction is a property of the classifier, not of the dataset.

2. **The honest exploit (nested cross-validation).** A learner is allowed to
   discover the polarity from its *training* data. Inner CV on the outer training
   folds estimates whether the probe generalizes anti-correlated; if so the
   learner flips its own output before scoring the outer test fold. **No test
   label is ever consulted.** If this oriented learner clears 60% on a family, the
   leak is real and a policy author could have found it.

3. **A second, unrelated learner.** Naive Bayes is sensitive to document length,
   so a systematically-wrong NB might be an artifact of the model rather than a
   property of the data. A centroid/cosine probe shares none of that machinery.
   If it *also* separates the family, the signal is in the text.

Run::

    uv run python experiments/signed_leakage_probe.py
"""

from __future__ import annotations

import math

from tactbench.audit import _NaiveBayes, _pair_key, item_tokens, lexical_leakage
from tactbench.dataset.generate import generate
from tactbench.schema import Item

FOLDS = 5


# --------------------------------------------------------------------------- #
# 1. signed leakage
# --------------------------------------------------------------------------- #


def standard_error(n: int) -> float:
    """SE of a proportion at p=0.5. The yardstick for "is this distance real?"."""
    return math.sqrt(0.25 / n) if n else 0.0


# --------------------------------------------------------------------------- #
# 2. the honest exploit -- nested CV picks polarity from training data only
# --------------------------------------------------------------------------- #


def _folds_of(items: list[Item], folds: int) -> dict[str, int]:
    """Pair-preserving fold assignment, identical in spirit to audit.lexical_leakage."""
    keys = sorted({_pair_key(i) for i in items})
    return {k: idx % folds for idx, k in enumerate(keys)}


def _fit_predict(train: list[Item], test: list[Item]) -> list[bool]:
    model = _NaiveBayes()
    model.fit([(item_tokens(i), i.label.should_surface) for i in train])
    return [model.predict(item_tokens(i)) for i in test]


def _accuracy(preds: list[bool], items: list[Item], flip: bool = False) -> float:
    if not items:
        return 0.5
    hits = sum(
        1
        for p, i in zip(preds, items, strict=True)
        if (not p if flip else p) == i.label.should_surface
    )
    return hits / len(items)


def oriented_accuracy(items: list[Item], folds: int = FOLDS) -> float:
    """Out-of-fold accuracy of a learner that also learns its own polarity.

    For each outer fold: run an inner CV *within the training items* to estimate
    the probe's generalization accuracy. If that estimate is below chance, the
    learner negates its predictions on the outer test fold. The outer test labels
    are used only to score -- never to choose the flip.
    """
    fold_of = _folds_of(items, folds)
    scored: list[float] = []

    for f in range(folds):
        train = [i for i in items if fold_of[_pair_key(i)] != f]
        test = [i for i in items if fold_of[_pair_key(i)] == f]
        if not train or not test:
            continue

        # --- inner CV, training items only -> decide polarity ---
        inner_of = _folds_of(train, folds)
        inner_scores: list[float] = []
        for g in range(folds):
            inner_train = [i for i in train if inner_of[_pair_key(i)] != g]
            inner_test = [i for i in train if inner_of[_pair_key(i)] == g]
            if not inner_train or not inner_test:
                continue
            inner_scores.append(_accuracy(_fit_predict(inner_train, inner_test), inner_test))
        flip = bool(inner_scores) and (sum(inner_scores) / len(inner_scores)) < 0.5

        scored.append(_accuracy(_fit_predict(train, test), test, flip=flip))

    return sum(scored) / len(scored) if scored else 0.5


# --------------------------------------------------------------------------- #
# 3. an unrelated learner -- centroid cosine, no length sensitivity
# --------------------------------------------------------------------------- #


def _vector(tokens: list[str]) -> dict[str, float]:
    v: dict[str, float] = {}
    for t in tokens:
        v[t] = v.get(t, 0.0) + 1.0
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {k: x / norm for k, x in v.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    small, large = (a, b) if len(a) < len(b) else (b, a)
    return sum(x * large.get(k, 0.0) for k, x in small.items())


def centroid_accuracy(items: list[Item], folds: int = FOLDS) -> float:
    """L2-normalized bag-of-words centroid per class; nearest centroid wins.

    Shares no machinery with naive Bayes -- no priors, no smoothing, no
    length sensitivity. Agreement between the two is evidence about the data.
    """
    fold_of = _folds_of(items, folds)
    scored: list[float] = []

    for f in range(folds):
        train = [i for i in items if fold_of[_pair_key(i)] != f]
        test = [i for i in items if fold_of[_pair_key(i)] == f]
        if not train or not test:
            continue

        centroids: dict[bool, dict[str, float]] = {}
        for label in (True, False):
            side = [_vector(item_tokens(i)) for i in train if i.label.should_surface is label]
            acc: dict[str, float] = {}
            for v in side:
                for k, x in v.items():
                    acc[k] = acc.get(k, 0.0) + x
            norm = math.sqrt(sum(x * x for x in acc.values())) or 1.0
            centroids[label] = {k: x / norm for k, x in acc.items()}

        hits = 0
        for i in test:
            v = _vector(item_tokens(i))
            pred = _cosine(v, centroids[True]) >= _cosine(v, centroids[False])
            hits += pred == i.label.should_surface
        scored.append(hits / len(test))

    return sum(scored) / len(scored) if scored else 0.5


# --------------------------------------------------------------------------- #


def main() -> None:
    items = generate(n_pairs_per_scenario=20)
    families = sorted({i.moment.family for i in items})

    print("Signed leakage -- distance from chance is what leaks, not direction\n")
    header = (
        f"{'family':<14} {'n':>4} {'raw':>7} {'|d-50|':>8} "
        f"{'SEs':>6} {'oriented':>9} {'centroid':>9}"
    )
    print(header)
    print("-" * len(header))

    rows = []
    for family in families:
        subset = [i for i in items if i.moment.family == family]
        raw = lexical_leakage(subset).accuracy
        dist = abs(raw - 0.5)
        se = standard_error(len(subset))
        sigmas = dist / se if se else 0.0
        oriented = oriented_accuracy(subset)
        centroid = centroid_accuracy(subset)
        rows.append((family, raw, dist, sigmas, oriented, centroid))
        print(
            f"{family:<14} {len(subset):>4} {raw:>6.1%} {dist:>8.1%} "
            f"{sigmas:>6.1f} {oriented:>8.1%} {centroid:>8.1%}"
        )

    overall = lexical_leakage(items)
    print("-" * len(header))
    print(
        f"{'overall':<14} {len(items):>4} {overall.accuracy:>6.1%} "
        f"{abs(overall.accuracy - 0.5):>8.1%} "
        f"{abs(overall.accuracy - 0.5) / standard_error(len(items)):>6.1f} "
        f"{oriented_accuracy(items):>8.1%} {centroid_accuracy(items):>8.1%}"
    )

    print("\nWhat the audit would say vs. what is true:\n")
    for family, raw, _dist, _sigmas, oriented, centroid in rows:
        audit_verdict = "at chance" if raw < 0.60 else "LEAKING"
        honest = "LEAKING" if max(oriented, centroid) >= 0.60 else "at chance"
        flag = "  <-- MISSED" if audit_verdict != honest else ""
        print(
            f"  {family:<14} audit says {audit_verdict:<9} | "
            f"oriented {oriented:.1%}, centroid {centroid:.1%} -> {honest}{flag}"
        )


if __name__ == "__main__":
    main()
