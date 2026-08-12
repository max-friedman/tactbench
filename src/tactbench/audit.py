"""Shortcut audits — the benchmark auditing itself.

TactBench's central claim is that its matched-pair design stops a policy from
winning by surface pattern matching. That claim is worth exactly as much as the
evidence for it, so this module tries to break it.

The probes: train a classifier on nothing but the *text of the
signals* -- no user state, no DND flag, no slice tags, none of the structure a
policy is supposed to reason over. If that classifier can separate "speak" from
"stay quiet", then the words alone carry the answer and the pairing has failed.

Chance is 0.5 on a balanced split. A probe scoring high means the words carry the
answer and the headline results are measuring vocabulary rather than tact.

**A probe scoring near chance does not mean the dataset forces a judgment.** It
means *that* probe found nothing. Round 11: the bag-of-words probe reported 50.0%
on all nine families for ten rounds, because both sides of a pair carry the same
token multiset by construction and a bag of words cannot see arrangement. The
order-aware probe reached 97.2% on the same data, and a bag-of-bigrams beat silence
on the held-out split until Round 13 held the phrasings out. Read the worst probe,
never the
friendliest, and remember that a clean audit bounds only the shortcuts you
thought to test.

This is a load-bearing test, not a diagnostic: ``test_lexical_leakage_stays_near_chance``
fails the build if the dataset drifts back toward being guessable.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .schema import Item, frame_of, pair_key

TOKEN_RE = re.compile(r"[a-z0-9']+")

#: The bars the audit enforces, as *exploitable* accuracy (see
#: :attr:`LeakageReport.exploitable_accuracy`). Defined once, here, because this
#: round found the same threshold typed out separately in the CLI, in the tests,
#: and in the report's own verdict -- and one of the three was still one-sided
#: after the other two were fixed. A threshold that is a literal at three call
#: sites is three thresholds.
OVERALL_THRESHOLD = 0.70
PER_FAMILY_THRESHOLD = 0.60


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def item_tokens(item: Item) -> list[str]:
    """Only the signal text. Deliberately excludes user_state, slices, and family --
    a policy is *supposed* to need those, so letting the probe see them would
    measure the wrong thing."""
    return tokenize(" ".join(s.content for s in item.moment.signals))


@dataclass
class LeakageReport:
    """Result of the bag-of-words shortcut probe."""

    accuracy: float
    folds: list[float]
    n: int
    #: Tokens most predictive of "speak", worst first, as (token, log-odds).
    top_speak: list[tuple[str, float]] = field(default_factory=list)
    #: Tokens most predictive of "stay quiet".
    top_quiet: list[tuple[str, float]] = field(default_factory=list)

    @property
    def excess_over_chance(self) -> float:
        """Signed distance from coin-flipping. Kept for reporting the *direction*;
        never threshold on it -- use :attr:`leakage`."""
        return self.accuracy - 0.5

    @property
    def leakage(self) -> float:
        """How much the words give away: ``|accuracy - 0.5|``.

        **Distance from chance is what leaks; direction is a property of the
        classifier, not of the dataset.** A probe that is wrong 67% of the time is
        not ignorant — negating it scores 67%, and negating a classifier is free.

        Round 10 found this the expensive way. Both audit assertions were upper
        bounds (``< 0.70`` overall, ``< 0.60`` per family), so a family probing at
        32.8% passed with room to spare and printed as ``at chance``. It was not
        at chance; it was a 67.2% classifier with a minus sign, produced by a
        dev/test split that broke pairs apart. A one-sided check cannot see an
        inverted leak, which is the exact kind the pairing design can produce.
        """
        return abs(self.accuracy - 0.5)

    @property
    def exploitable_accuracy(self) -> float:
        """What a learner gets once it picks the profitable polarity: ``0.5 + leakage``.

        This is the honest headline. A submitter reads their own probe's
        orientation off training data for free, so the benchmark must assume they
        did.
        """
        return 0.5 + self.leakage

    def is_leaking(self, threshold: float = PER_FAMILY_THRESHOLD) -> bool:
        """The single predicate every caller must use.

        Thresholds on :attr:`exploitable_accuracy`, never on raw accuracy, so a
        reliably-wrong probe is judged the same as a reliably-right one.
        """
        return self.exploitable_accuracy >= threshold

    #: What produced this report, for honest phrasing in the verdict.
    probe: str = "bag-of-words"

    def verdict(self, threshold: float = 0.65) -> str:
        if self.is_leaking(threshold):
            direction = (
                ""
                if self.excess_over_chance >= 0
                else " (inverted — the probe is reliably *wrong*, which is exactly "
                "as exploitable as being reliably right)"
            )
            return (
                f"LEAKING — a {self.probe} model reaches {self.accuracy:.1%}, worth "
                f"{self.exploitable_accuracy:.1%} to a learner that picks its polarity"
                f"{direction}. The pairing is not forcing a judgment."
            )
        return (
            f"OK — the {self.probe} probe reaches {self.accuracy:.1%}, within "
            f"{self.leakage:.1%} of the {0.5:.0%} chance floor. Signal text alone "
            "does not carry the answer."
        )


class _NaiveBayes:
    """Multinomial naive Bayes with Laplace smoothing.

    Hand-rolled to keep the audit dependency-free: a benchmark whose own
    validity check needs scikit-learn is a benchmark people will skip running.
    """

    def __init__(self) -> None:
        self.counts: dict[bool, dict[str, int]] = {True: {}, False: {}}
        self.totals: dict[bool, int] = {True: 0, False: 0}
        self.docs: dict[bool, int] = {True: 0, False: 0}
        self.vocab: set[str] = set()

    def fit(self, docs: list[tuple[list[str], bool]]) -> None:
        for tokens, label in docs:
            self.docs[label] += 1
            for t in tokens:
                self.counts[label][t] = self.counts[label].get(t, 0) + 1
                self.totals[label] += 1
                self.vocab.add(t)

    def _log_prob(self, tokens: list[str], label: bool) -> float:
        v = len(self.vocab) or 1
        total_docs = self.docs[True] + self.docs[False]
        prior = math.log((self.docs[label] + 1) / (total_docs + 2))
        lp = prior
        for t in tokens:
            c = self.counts[label].get(t, 0)
            lp += math.log((c + 1) / (self.totals[label] + v))
        return lp

    def predict(self, tokens: list[str]) -> bool:
        return self._log_prob(tokens, True) >= self._log_prob(tokens, False)

    def log_odds(self) -> dict[str, float]:
        """Per-token log P(token|speak) - log P(token|quiet). Large magnitude means
        the token alone tips the answer, which is what we want to eliminate."""
        v = len(self.vocab) or 1
        out: dict[str, float] = {}
        for t in self.vocab:
            a = (self.counts[True].get(t, 0) + 1) / (self.totals[True] + v)
            b = (self.counts[False].get(t, 0) + 1) / (self.totals[False] + v)
            out[t] = math.log(a / b)
        return out


def _pair_key(item: Item) -> str:
    """Group a positive with its near-miss so folds never split a pair.

    Splitting a pair across train and test would let the probe memorize one half
    and trivially answer the other. Delegates to :func:`schema.pair_key` -- the
    single definition -- because this module holding its *own* notion of a pair,
    correct but private, is exactly how the dev/test split came to disagree with
    it for nine rounds without anything going red.
    """
    return pair_key(item.moment.id)


def item_bigrams(item: Item) -> list[str]:
    """Adjacent token pairs -- the minimum needed to see "A before B".

    Round 11: the unigram probe cannot see word order, and a role permutation is
    *only* a reordering::

        SPEAK: Nearby: you. 7 hours away, still driving: Mom.
        QUIET: Nearby: Mom. 7 hours away, still driving: you.

    Identical token multiset. The bag-of-words probe is structurally incapable of
    separating these and reports 50.0% -- which was read as resistance for ten
    rounds, while bigrams separated them at 97.2%. Round 13 split the dev/test
    boundary on the decider frame, so held-out phrasings never appear in training;
    the bigram probe now reads 47.0%.
    """
    toks = item_tokens(item)
    if len(toks) < 2:
        # A one-token signal has no adjacent pair, and an empty feature bag is
        # classified by the class prior alone -- which would print as ~50% and
        # read as "at chance". That is precisely the misreading this probe
        # exists to prevent, so fall back to the unigram rather than go silent.
        return list(toks)
    return [f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False)]


def _frame_key(item: Item) -> str:
    """Group by decider phrasing, so folds hold out a *wording* rather than a pair.

    Round 13. Folding by pair asks "can a model that has seen all five training
    phrasings separate a held-out pair?" -- which for some families is yes, by
    memorising the phrasing. That is not what the benchmark is graded on: a
    submitter fits on `dev` and is scored on `test`, whose wordings are disjoint.
    Folding by frame asks the question that matches the grading.
    """
    return f"{item.moment.family}:{frame_of(item.moment)}"


def item_positional(item: Item) -> list[str]:
    """Each token tagged with where in the signal it fell, in tenths.

    A third axis, added in Round 13 after review. Unigrams cannot see arrangement
    and bigrams see only adjacency; neither notices "the marker sits in the first
    clause". That mattered: the first attempt at balancing clause order used a
    digest of the pair id, which left a third of the (family, frame) cells
    single-order, and a position-tagged probe read five of nine families above the
    per-family bound while every gated check stayed green.

    A probe the gate does not run is a shortcut the gate cannot see.
    """
    toks = item_tokens(item)
    n = len(toks) or 1
    return [f"{t}@{(idx * 10) // n}" for idx, t in enumerate(toks)]


def lexical_leakage(
    items: list[Item], folds: int = 5, features=item_tokens, group=_pair_key
) -> LeakageReport:
    """Cross-validated probe over signal text only.

    ``features`` selects the representation. The default is the historical
    bag-of-words; pass :func:`item_bigrams` for the order-aware probe. Both use
    the same pair-preserving folds, so their numbers are directly comparable --
    and the gap between them is the measure of how much the design relies on the
    probe's blind spot rather than on the pairing.
    """
    docs = [(features(i), i.label.should_surface) for i in items]
    keys = sorted({group(i) for i in items})
    fold_of = {k: idx % folds for idx, k in enumerate(keys)}

    accuracies: list[float] = []
    for f in range(folds):
        train = [d for d, i in zip(docs, items, strict=True) if fold_of[group(i)] != f]
        test = [(d, i) for d, i in zip(docs, items, strict=True) if fold_of[group(i)] == f]
        if not train or not test:
            continue
        model = _NaiveBayes()
        model.fit(train)
        correct = sum(1 for (tokens, label), _ in test if model.predict(tokens) == label)
        accuracies.append(correct / len(test))

    full = _NaiveBayes()
    full.fit(docs)
    odds = sorted(full.log_odds().items(), key=lambda kv: kv[1])

    return LeakageReport(
        accuracy=sum(accuracies) / len(accuracies) if accuracies else 0.5,
        folds=accuracies,
        n=len(items),
        top_speak=[(t, v) for t, v in reversed(odds[-12:])],
        top_quiet=odds[:12],
    )


def positional_leakage(items: list[Item], folds: int = 5) -> LeakageReport:
    """The position-aware probe, folded by frame. See :func:`item_positional`."""
    report = lexical_leakage(items, folds=folds, features=item_positional, group=_frame_key)
    report.probe = "positional"
    return report


def ngram_leakage(items: list[Item], folds: int = 5) -> LeakageReport:
    """The order-aware probe, folded by **frame**.

    See :func:`item_bigrams` for why the probe exists and :func:`_frame_key` for
    why it holds out a wording rather than a pair.
    """
    report = lexical_leakage(items, folds=folds, features=item_bigrams, group=_frame_key)
    report.probe = "bigram"
    return report


def verbatim_overlap(train: list[Item], held_out: list[Item]) -> dict[str, float]:
    """How much of ``held_out`` is text the submitter already has, labelled?

    Round 11 found the bigram probe scoring +99.4 versus silence on the held-out
    split and initially reported it as generalisation. It is mostly not.
    Template diversity is low enough that most held-out **decider sentences appear
    byte-identically in the published split**, so the dominant effect is
    memorisation of repeated strings rather than any model learning a relation.

    This is a near-duplicate leak, and it is a different defect from Round 10's:
    that one split *pairs* across dev and test; this one repeats *text* across
    them. A split can be perfectly pair-whole and still publish its answers.

    Returns fractions of ``held_out``, plus the accuracy of a zero-model lookup.
    """
    by_decider: dict[str, set[bool]] = {}
    for i in train:
        by_decider.setdefault(i.moment.signals[-1].content, set()).add(i.label.should_surface)
    whole_train = {" ".join(s.content for s in i.moment.signals) for i in train}

    n = len(held_out) or 1
    decider_seen = [i for i in held_out if i.moment.signals[-1].content in by_decider]
    unambiguous = [i for i in decider_seen if len(by_decider[i.moment.signals[-1].content]) == 1]
    whole_seen = [
        i for i in held_out if " ".join(s.content for s in i.moment.signals) in whole_train
    ]
    correct = sum(
        1
        for i in unambiguous
        if next(iter(by_decider[i.moment.signals[-1].content])) == i.label.should_surface
    )

    return {
        "decider_published": len(decider_seen) / n,
        "whole_item_published": len(whole_seen) / n,
        "lookup_accuracy": (correct + 0.5 * (len(held_out) - len(unambiguous))) / n,
    }
