"""Is "50.0% everywhere" evidence, or a tautology?

Round 10 left the shortcut audit reporting **exactly 50.0%** for all nine
families. That reads as the strongest possible result. It may instead be the
weakest: the audit's probe is a **bag of words**, which cannot see word order,
and a role permutation is *only* a reordering.

Look at what a pair actually is::

    SPEAK: Nearby: you. 7 hours away, still driving: Mom.
    QUIET: Nearby: Mom. 7 hours away, still driving: you.

Identical token multiset. A unigram model is *structurally incapable* of telling
these apart — it will score 50.0% on a dataset that is perfectly separable, and
report that as safety. Ten rounds of "at chance" may have been measuring the
probe's blind spot rather than the dataset's resistance.

Falsifiable question:

    **Does an order-aware probe separate the pairs the unigram probe cannot —
    and if so, can a policy built on that signal beat silence?**

Separability alone is not a defect. The benchmark's actual claim is that a policy
cannot win by surface pattern matching, and the standard the repo already uses
for that is `TestNoKeywordExploit`: *no shortcut policy may beat silence*. So this
probe answers in two stages.

1. **Separability.** Bigrams and position-tagged unigrams, run through the same
   cross-validated naive Bayes and the same pair-preserving folds as the audit.
   If these clear 60% where unigrams sit at 50%, the audit has a blind spot.

2. **Exploitability — the part that decides whether it matters.** Train the
   order-aware model on the *dev* split, then score it as a real policy on the
   *held-out test* split with ICS, against the silence bar. This is the honest
   test: a submitter fits on published data and is graded on held-out data. If it
   beats silence, the benchmark is solvable by surface statistics and its central
   claim is false in the same way Round 1 found it false.

Run::

    uv run python experiments/order_sensitive_probe.py
"""

from __future__ import annotations

from tactbench.audit import _NaiveBayes, _pair_key, item_tokens, lexical_leakage
from tactbench.dataset.loader import load
from tactbench.metrics import score
from tactbench.runner import silence_ics
from tactbench.schema import Decision, Item

FOLDS = 5


# --------------------------------------------------------------------------- #
# Feature sets
# --------------------------------------------------------------------------- #


def unigrams(item: Item) -> list[str]:
    """What the shipped audit uses."""
    return item_tokens(item)


def bigrams(item: Item) -> list[str]:
    """Adjacent token pairs. The minimum needed to see "A before B"."""
    toks = item_tokens(item)
    return [f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False)]


def positional(item: Item) -> list[str]:
    """Each token tagged with where in the signal it fell, in tenths.

    A different way of seeing order: not which tokens are adjacent, but whereabouts
    each one sits. Agreement between this and bigrams is evidence about the data
    rather than about one feature encoding.
    """
    toks = item_tokens(item)
    n = len(toks) or 1
    return [f"{t}@{(idx * 10) // n}" for idx, t in enumerate(toks)]


def bigrams_plus_unigrams(item: Item) -> list[str]:
    return unigrams(item) + bigrams(item)


# --------------------------------------------------------------------------- #
# 1. separability, on the audit's own folds
# --------------------------------------------------------------------------- #


def cross_validated(items: list[Item], features, folds: int = FOLDS) -> float:
    keys = sorted({_pair_key(i) for i in items})
    fold_of = {k: idx % folds for idx, k in enumerate(keys)}

    scored: list[float] = []
    for f in range(folds):
        train = [i for i in items if fold_of[_pair_key(i)] != f]
        test = [i for i in items if fold_of[_pair_key(i)] == f]
        if not train or not test:
            continue
        model = _NaiveBayes()
        model.fit([(features(i), i.label.should_surface) for i in train])
        hits = sum(1 for i in test if model.predict(features(i)) == i.label.should_surface)
        scored.append(hits / len(test))
    return sum(scored) / len(scored) if scored else 0.5


# --------------------------------------------------------------------------- #
# 2. exploitability -- fit on dev, graded on held-out test, scored with ICS
# --------------------------------------------------------------------------- #


class NgramPolicy:
    """A submitter's shortcut: fit a bag-of-ngrams on the published dev split.

    Sees only signal text -- no user state, no DND, no slices. Exactly the
    information the benchmark says is insufficient.
    """

    def __init__(self, features, train: list[Item]):
        self.features = features
        self.model = _NaiveBayes()
        self.model.fit([(features(i), i.label.should_surface) for i in train])
        self.name = "ngram-exploit"

    def decide(self, moment) -> Decision:
        fake = Item.model_construct(moment=moment, label=None)
        speak = self.model.predict(self.features(fake))
        return Decision(moment_id=moment.id, surface=speak, intent="alert" if speak else None)


def main() -> None:
    dev, test = load("v1", "dev"), load("v1", "test")
    families = sorted({i.moment.family for i in dev})

    feature_sets = [
        ("unigram (shipped audit)", unigrams),
        ("bigram", bigrams),
        ("positional unigram", positional),
        ("unigram + bigram", bigrams_plus_unigrams),
    ]

    print("1. SEPARABILITY -- cross-validated on dev, pairs kept whole\n")
    header = f"{'family':<14} " + " ".join(f"{name.split()[0]:>10}" for name, _ in feature_sets)
    print(header)
    print("-" * len(header))
    for family in families:
        subset = [i for i in dev if i.moment.family == family]
        cells = " ".join(f"{cross_validated(subset, fn):>9.1%} " for _, fn in feature_sets)
        print(f"{family:<14} {cells}")
    print("-" * len(header))
    overall = " ".join(f"{cross_validated(dev, fn):>9.1%} " for _, fn in feature_sets)
    print(f"{'overall':<14} {overall}")

    print(f"\n   (the shipped audit reports {lexical_leakage(dev).accuracy:.1%})")

    print("\n\n2. EXPLOITABILITY -- fit on dev, graded on held-out test, scored by ICS\n")
    reference = silence_ics(test)
    print(f"   silence bar on test: ICS {reference:.1f}\n")
    print(f"{'feature set':<26} {'ICS':>8} {'vs silence':>12} {'prec@int':>10}")
    print("-" * 60)
    for name, fn in feature_sets:
        policy = NgramPolicy(fn, dev)
        decisions = [policy.decide(i.moment) for i in test]
        card = score(test, decisions, name, reference)
        prec = "--" if card.precision_at_interrupt is None else f"{card.precision_at_interrupt:.3f}"
        print(f"{name:<26} {card.ics:>8.1f} {card.ics_normalized:>+11.1f} {prec:>10}")
    print("-" * 60)
    print(
        "\n   'vs silence' above 0 means a text-only surface model, trained on the\n"
        "   published split, is worth shipping over saying nothing. The benchmark's\n"
        "   central claim is that this cannot happen."
    )


if __name__ == "__main__":
    main()
