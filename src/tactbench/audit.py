"""Shortcut audits — the benchmark auditing itself.

TactBench's central claim is that its matched-pair design stops a policy from
winning by surface pattern matching. That claim is worth exactly as much as the
evidence for it, so this module tries to break it.

The probe: train a bag-of-words classifier on nothing but the *text of the
signals* -- no user state, no DND flag, no slice tags, none of the structure a
policy is supposed to reason over. If that classifier can separate "speak" from
"stay quiet", then the words alone carry the answer and the pairing has failed.

Chance is 0.5 on a balanced split. A probe scoring near chance means the dataset
forces a judgment. A probe scoring high means it doesn't, and the headline
results are measuring vocabulary rather than tact.

This is a load-bearing test, not a diagnostic: ``test_lexical_leakage_stays_near_chance``
fails the build if the dataset drifts back toward being guessable.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .schema import Item, pair_key

TOKEN_RE = re.compile(r"[a-z0-9']+")


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

    def verdict(self, threshold: float = 0.65) -> str:
        if self.exploitable_accuracy >= threshold:
            direction = (
                ""
                if self.excess_over_chance >= 0
                else " (inverted — the probe is reliably *wrong*, which is exactly "
                "as exploitable as being reliably right)"
            )
            return (
                f"LEAKING — a bag-of-words model reaches {self.accuracy:.1%}, worth "
                f"{self.exploitable_accuracy:.1%} to a learner that picks its polarity"
                f"{direction}. The pairing is not forcing a judgment."
            )
        return (
            f"OK — text-only probe reaches {self.accuracy:.1%}, within "
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


def lexical_leakage(items: list[Item], folds: int = 5) -> LeakageReport:
    """Cross-validated bag-of-words probe over signal text only."""
    docs = [(item_tokens(i), i.label.should_surface) for i in items]
    keys = sorted({_pair_key(i) for i in items})
    fold_of = {k: idx % folds for idx, k in enumerate(keys)}

    accuracies: list[float] = []
    for f in range(folds):
        train = [d for d, i in zip(docs, items, strict=True) if fold_of[_pair_key(i)] != f]
        test = [(d, i) for d, i in zip(docs, items, strict=True) if fold_of[_pair_key(i)] == f]
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
