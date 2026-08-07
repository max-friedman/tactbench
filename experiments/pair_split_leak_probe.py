"""The held-out split is not held out.

``audit.lexical_leakage`` is careful to keep a pair whole across its
cross-validation folds, and says why::

    Splitting a pair across train and test would let the probe memorize one half
    and trivially answer the other.

The dataset's own dev/test split does not do this. ``cli.build`` buckets on
``moment.id``::

    dev  = [i for i in items if _bucket(i.moment.id) < 60]
    test = [i for i in items if _bucket(i.moment.id) >= 60]

``moment.id`` is per **item** (``travel-pos-0003`` / ``travel-near-0003``), so the
two sides of a pair get independent buckets and land on opposite sides of the
split roughly 48% of the time. The invariant is enforced in the checker and
violated in the artifact the checker is checking.

That matters here more than it would in an ordinary dataset, because of what a
pair *is* in TactBench: both sides share a **byte-identical body** and an
identical ``UserState``, differing only in which noun plays which role. An
orphaned test item is therefore a near-verbatim copy of a dev item -- carrying
the opposite label.

Falsifiable question:

    **Does the pair-broken split leak dev labels into test -- i.e. does a probe
    fit on dev score materially better on orphaned test items (whose partner it
    trained on) than on whole test pairs (whose partner it never saw)?**

If orphans and non-orphans score the same, the split is merely untidy. If orphans
score higher, the leaderboard's held-out number is partly a memorization score.

Run::

    uv run python experiments/pair_split_leak_probe.py
"""

from __future__ import annotations

from tactbench.audit import _NaiveBayes, _pair_key, item_tokens
from tactbench.dataset.loader import load
from tactbench.schema import Item


def partition(dev: list[Item], test: list[Item]) -> tuple[list[Item], list[Item]]:
    """Split the test items by whether their partner leaked into dev."""
    dev_keys = {_pair_key(i) for i in dev}
    orphaned = [i for i in test if _pair_key(i) in dev_keys]
    intact = [i for i in test if _pair_key(i) not in dev_keys]
    return orphaned, intact


def fit_on(dev: list[Item]) -> _NaiveBayes:
    model = _NaiveBayes()
    model.fit([(item_tokens(i), i.label.should_surface) for i in dev])
    return model


def accuracy(model: _NaiveBayes, items: list[Item]) -> float:
    if not items:
        return float("nan")
    hits = sum(1 for i in items if model.predict(item_tokens(i)) == i.label.should_surface)
    return hits / len(items)


def body_identical(a: Item, b: Item) -> bool:
    """Do the two sides literally share signal text? (Excluding the decider.)"""
    at = {s.content for s in a.moment.signals}
    bt = {s.content for s in b.moment.signals}
    return bool(at & bt)


def main() -> None:
    dev, test = load("v1", "dev"), load("v1", "test")
    orphaned, intact = partition(dev, test)

    print("Pair integrity of the shipped v1 split\n")
    print(f"  dev   {len(dev):>4} items")
    print(f"  test  {len(test):>4} items")
    print(
        f"  test items whose partner is in dev : {len(orphaned):>4}  "
        f"({len(orphaned) / len(test):.0%})"
    )
    print(
        f"  test items with an intact pair     : {len(intact):>4}  ({len(intact) / len(test):.0%})"
    )

    # How much text do a leaked partner and its orphan actually share?
    by_key: dict[str, list[Item]] = {}
    for i in dev + test:
        by_key.setdefault(_pair_key(i), []).append(i)
    shared = sum(
        1
        for i in orphaned
        for partner in by_key[_pair_key(i)]
        if partner is not i and body_identical(i, partner)
    )
    print(f"  orphans sharing signal text with their dev partner: {shared}/{len(orphaned)}")

    model = fit_on(dev)
    a_orphan, a_intact = accuracy(model, orphaned), accuracy(model, intact)

    print("\nBag-of-words probe fit on dev, scored on test\n")
    print(f"{'subset':<34} {'n':>4} {'accuracy':>9}")
    print("-" * 49)
    print(f"{'test items partnered into dev':<34} {len(orphaned):>4} {a_orphan:>8.1%}")
    print(f"{'test items with intact pairs':<34} {len(intact):>4} {a_intact:>8.1%}")
    print(f"{'whole test split':<34} {len(test):>4} {accuracy(model, test):>8.1%}")
    print("-" * 49)
    print(f"{'gap (leak premium)':<34} {'':>4} {a_orphan - a_intact:>+8.1%}")

    print(
        "\nThe gap is large and NEGATIVE, which is the strongest form of the leak.\n"
        "An orphan's dev partner carries near-identical text under the OPPOSITE\n"
        "label, so a probe fit on dev is systematically wrong -- and a systematic\n"
        "wrong answer is a right answer with a minus sign. Inverted: "
        f"{1 - a_orphan:.1%}."
    )

    # ---------------------------------------------------------------- #
    # The exploit needs no statistics at all.
    # ---------------------------------------------------------------- #
    # ``moment.id`` is public, so the pair key of a test item is public, so the
    # partner sitting in the *published dev split* is findable by lookup. A pair
    # has exactly one speak side and one stay-quiet side. Reading the partner's
    # label therefore gives the test label outright -- no model, no training.
    dev_label_by_key: dict[str, bool] = {}
    for i in dev:
        dev_label_by_key.setdefault(_pair_key(i), i.label.should_surface)

    looked_up = [i for i in test if _pair_key(i) in dev_label_by_key]
    exact = sum(
        1 for i in looked_up if (not dev_label_by_key[_pair_key(i)]) == i.label.should_surface
    )

    print("\nThe zero-model exploit: read the partner's label out of dev\n")
    print(f"  test items with a partner published in dev : {len(looked_up)}/{len(test)}")
    print(f"  answered correctly by negating that label  : {exact}/{len(looked_up)}")
    coverage = len(looked_up) / len(test)
    overall = (exact + 0.5 * (len(test) - len(looked_up))) / len(test)
    print(f"  whole-split accuracy (coin-flip elsewhere) : {overall:.1%}")
    print(
        f"\n  {coverage:.0%} of the held-out split is answerable by table lookup\n"
        "  against the published dev file. This requires no learning, no text\n"
        "  analysis, and no access to anything that isn't shipped in the repo."
    )


if __name__ == "__main__":
    main()
