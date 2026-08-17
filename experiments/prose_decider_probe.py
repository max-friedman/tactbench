"""Can the deciders be prose again without reopening the surface exploit?

Round 13 bought validity with uniformity. Every decider became two
``Label: value.`` clauses, which makes the permutation hold by construction and
lets frames be held out cleanly -- and reads like a status line rather than
anything a person or an app would send. For a benchmark about *proactive
assistance*, items that do not look like real messages measure something adjacent
to the thing, so "restore prose" went to the top of the queue.

Round 15 built it and **rejected it**. The evidence is here so the next attempt
starts from the rule rather than rediscovering it.

What was built
--------------
A full prose frame table -- nine families x eight frames -- as clause templates
with a ``{who}`` slot and a ``{be}`` copula::

    ("{who} {be} collecting the kids today", "{who} {be} catching the early flight")

    -> "You are collecting the kids today. Dana is catching the early flight."
    -> "Dana is collecting the kids today. You are catching the early flight."

Two properties make that a legal permutation, and both are cheap to get wrong by
hand:

1. **Both clauses take the copula or neither does.** The verb travels with its
   subject, so a pair carries one "are" and one "is" whichever way the roles fall
   and the token multiset survives. A one-sided copula puts "are" on one side and
   "is" on the other and breaks the only invariant the benchmark rests on.
2. **Equal skeleton length** (token count with the filler removed). Unequal
   clauses shift the marker's position with the clause it occupies, which is what
   a position-tagged probe reads -- the lesson Round 13 paid for.

Both held. The table validated clean on copula symmetry, skeleton length, and
pairwise stem-disjointness, the skyline resolved all nine families from the
templates with zero disagreements, and the prose is markedly more natural.

Why it was rejected
-------------------
It regresses the **gated** per-family bigram bound:

    family        unigram   bigram   positional
    health          50.0%    75.0%        52.5%
    deadline        50.0%    60.0%        65.0%
    finance         50.0%    55.0%        55.0%

against a 60% bound that the shipped ``Label: value`` form passes.

The cause is not the wording. Restricting the probe to the decider signal alone
puts health back at exactly 50.0%; the entire 75% comes from **bigrams spanning
the boundary between the body signal and the decider signal**::

    body: "The pharmacy closes in 40 minutes."
    decider: "Your prescription is on the shelf. Otto's prescription is out the door."
                ^-- the token right after the body is the FILLER

``item_tokens`` joins every signal, so the body's last token sits adjacent to the
decider's first token. A prose clause **begins with its subject**, which is the
filler -- so that junction bigram is ``minutes_your`` on one side and
``minutes_otto's`` on the other. The body phrasings are shared across all eight
frames, so unlike every other discriminating bigram this one **transfers straight
through a held-out frame**.

The ``Label: value`` form is immune by accident: its clauses begin with a
frame-specific label, so the junction bigram is identical on both sides.

The rule for the next attempt
-----------------------------
    **The filler must not be clause-initial.**

Prose is fine; prose whose clause starts with the subject is not. Something like
"Today's pickup falls to {who}" keeps the register while putting a frame-specific
token against the body boundary. Note the mirror trap: a clause-*final* filler
puts the filler against the *next* clause's opening instead, so only the first
clause's opening actually matters -- which is the one that touches the body.

Worth checking at the same time: whether ``item_tokens`` should tokenize signals
separately rather than joining them. A cross-signal adjacency is real for a policy
that concatenates and not for one that reads the list, so the probe is currently
making a choice on the reader's behalf without saying so.

Run::

    uv run python experiments/prose_decider_probe.py
"""

from __future__ import annotations

from tactbench.audit import _frame_key, _NaiveBayes, tokenize
from tactbench.dataset.generate import generate
from tactbench.schema import Item

FOLDS = 5


def bigrams(tokens: list[str]) -> list[str]:
    return [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]


def all_signal_bigrams(item: Item) -> list[str]:
    """What the shipped audit sees: every signal joined, then tokenized."""
    return bigrams(tokenize(" ".join(s.content for s in item.moment.signals)))


def decider_only_bigrams(item: Item) -> list[str]:
    """The decider in isolation -- no body/decider junction."""
    return bigrams(tokenize(item.moment.signals[-1].content))


def frame_folded_accuracy(items: list[Item], features, folds: int = FOLDS) -> float:
    keys = sorted({_frame_key(i) for i in items})
    fold_of = {k: n % folds for n, k in enumerate(keys)}
    scored = []
    for f in range(folds):
        train = [i for i in items if fold_of[_frame_key(i)] != f]
        test = [i for i in items if fold_of[_frame_key(i)] == f]
        if not train or not test:
            continue
        model = _NaiveBayes()
        model.fit([(features(i), i.label.should_surface) for i in train])
        scored.append(
            sum(1 for i in test if model.predict(features(i)) == i.label.should_surface) / len(test)
        )
    return sum(scored) / len(scored) if scored else 0.5


def main() -> None:
    items = generate(n_pairs_per_scenario=30)
    families = sorted({i.moment.family for i in items})

    print("Where does a bigram's signal live -- the decider, or the junction?\n")
    print(f"{'family':<14} {'all signals':>13} {'decider only':>14}")
    print("-" * 43)
    for family in families:
        subset = [i for i in items if i.moment.family == family]
        a = frame_folded_accuracy(subset, all_signal_bigrams)
        d = frame_folded_accuracy(subset, decider_only_bigrams)
        print(f"{family:<14} {a:>12.1%} {d:>13.1%}")

    print(
        "\nOn the SHIPPED `Label: value` deciders these two columns agree, because a\n"
        "clause opens with a frame-specific label and the body/decider junction\n"
        "carries nothing. On the prose deciders Round 15 built and rejected, health\n"
        "read 75.0% under 'all signals' and exactly 50.0% under 'decider only' --\n"
        "the whole leak was the junction, because a prose clause opens with its\n"
        "subject, which is the filler.\n\n"
        "Rule for the next attempt: THE FILLER MUST NOT BE CLAUSE-INITIAL.\n"
        "See this module's docstring."
    )


if __name__ == "__main__":
    main()
