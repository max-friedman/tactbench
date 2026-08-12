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

1b. **How much is duplicate text rather than learning?** Added after review
   pointed out the first draft reported the result as generalisation to unseen
   pairs. The pairs are new; the sentences largely are not. Measure how much
   held-out text is published verbatim in dev, and what a dict lookup alone gets.
   Report the zero-model number *first*, because a finding that a model achieves
   X is worth much less when a lookup table achieves most of X.

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

from tactbench.audit import (
    _NaiveBayes,
    _pair_key,
    item_tokens,
    lexical_leakage,
    verbatim_overlap,
)
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


def _report_exploitability(dev, test, feature_sets) -> None:
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


def main() -> None:
    dev, test = load("v1", "dev"), load("v1", "test")
    families = sorted({i.moment.family for i in dev})

    feature_sets = [
        ("uni(audit)", unigrams),
        ("bigram", bigrams),
        ("positional", positional),
        ("uni+bigram", bigrams_plus_unigrams),
    ]

    print("1. SEPARABILITY -- cross-validated on dev, pairs kept whole\n")
    # Full labels, not name.split()[0] -- that truncated both "unigram (shipped
    # audit)" and "unigram + bigram" to "unigram", printing 50.0% and 97.2% under
    # the same header in the round's own evidence artifact.
    header = f"{'family':<14} " + " ".join(f"{name:>11}" for name, _ in feature_sets)
    print(header)
    print("-" * len(header))
    for family in families:
        subset = [i for i in dev if i.moment.family == family]
        cells = " ".join(f"{cross_validated(subset, fn):>10.1%} " for _, fn in feature_sets)
        print(f"{family:<14} {cells}")
    print("-" * len(header))
    overall = " ".join(f"{cross_validated(dev, fn):>10.1%} " for _, fn in feature_sets)
    print(f"{'overall':<14} {overall}")

    print(f"\n   (the shipped audit reports {lexical_leakage(dev).accuracy:.1%})")

    # ------------------------------------------------------------------ #
    overlap = verbatim_overlap(dev, test)
    print("\n\n1b. HOW MUCH OF THIS IS DUPLICATE TEXT RATHER THAN LEARNING?\n")
    print(f"   held-out deciders published verbatim in dev : {overlap['decider_published']:>6.1%}")
    print(
        f"   held-out items wholly published in dev      : {overlap['whole_item_published']:>6.1%}"
    )
    print(f"   accuracy of a dict lookup, no model at all  : {overlap['lookup_accuracy']:>6.1%}")
    families_by_diversity = sorted(
        (
            (f, len({i.moment.signals[-1].content for i in dev + test if i.moment.family == f}))
            for f in families
        ),
        key=lambda kv: kv[1],
    )
    print("\n   distinct decider sentences per family (40 items each):")
    print("   " + ", ".join(f"{f}={n}" for f, n in families_by_diversity))

    # ------------------------------------------------------------------ #
    # 1c. The decisive control: does the exploit survive when duplication
    # cannot possibly explain it?
    #
    # Round 12 inferred "the frame carries the label" from the exploit barely
    # moving after duplication was cut. That is indirect. This measures it
    # head-on -- score ONLY the held-out items whose decider sentence never
    # appeared in dev. If accuracy holds up there, the residual exploit is not
    # duplication-driven, and no amount of entity variation will touch it.
    published = {i.moment.signals[-1].content for i in dev}
    unseen = [i for i in test if i.moment.signals[-1].content not in published]
    seen = [i for i in test if i.moment.signals[-1].content in published]
    model = _NaiveBayes()
    model.fit([(bigrams(i), i.label.should_surface) for i in dev])

    def acc(subset):
        if not subset:
            return float("nan")
        return sum(1 for i in subset if model.predict(bigrams(i)) == i.label.should_surface) / len(
            subset
        )

    print("\n\n1c. IS THE RESIDUAL EXPLOIT DUPLICATION, OR THE FRAME?\n")
    if not seen:
        print(
            "   No held-out decider appears in dev at all -- the split is taken on\n"
            "   the frame, so this comparison has no 'published' side to make. The\n"
            f"   whole held-out set scores {acc(unseen):.1%}."
        )
        print("\n\n2. EXPLOITABILITY -- fit on dev, graded on held-out test, scored by ICS\n")
        _report_exploitability(dev, test, feature_sets)
        return
    print(
        f"   held-out items whose decider WAS published in dev : {len(seen):>3}  {acc(seen):>6.1%}"
    )
    print(
        f"   held-out items whose decider was NEVER in dev     : "
        f"{len(unseen):>3}  {acc(unseen):>6.1%}"
    )
    print(
        "\n   Comparable accuracy on never-published phrasings means the model is\n"
        "   not recognising strings -- it is reading the frame, which entity\n"
        "   variation leaves untouched."
    )

    print("\n\n2. EXPLOITABILITY -- fit on dev, graded on held-out test, scored by ICS\n")
    _report_exploitability(dev, test, feature_sets)


if __name__ == "__main__":
    main()
