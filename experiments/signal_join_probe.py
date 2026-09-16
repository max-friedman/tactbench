"""Should the shortcut probe cross signal boundaries?

``audit.item_tokens`` joins every signal into one string before tokenizing, so
bigrams span the junction between the shared body signal and the discriminating
decider signal. Round 15 found that choice is **load-bearing** and left it
unresolved; this module is the measurement Round 21 used to settle it.

Why it is not a detail
----------------------
The junction is the only place a discriminating bigram can ride a *shared* body
phrasing. Body text is identical across all eight frames of a family, so a bigram
anchored there **transfers through a held-out frame** -- which is exactly what the
dev/test split exists to prevent. Every other discriminating bigram lives inside a
decider clause and dies with its frame.

That is why Round 15's prose regressed health to 75.0% under the join and exactly
50.0% without it, and why Round 16's first property (*the filler must not be
clause-initial*) targets the junction specifically.

The ruling: keep the join
-------------------------
Both readings are defensible. A policy that serializes the moment into one prompt
-- which is what every LLM baseline in ``policies/llm.py`` will do -- genuinely sees
the junction. A policy reading the structured ``Signal`` list never does.

**Keep the join**, because the probe's job is not to model the average reader. A
submitter picks their own representation, so a shortcut reachable under *any*
reasonable serialization is a shortcut in the dataset. Joining is the upper bound
over representations; separating measures one particular reader and would report
"clean" for a leak the LLM baselines could take. For an adversarial probe the
conservative choice is the correct one.

What the ruling buys: a check with no tolerance
-----------------------------------------------
If the deciders are well-formed the join buys the probe **nothing** -- the junction
carries no signal, so joined and separated tokenizations must score the *same*. That
equality is measurable and, unlike the structural properties, names no mechanism, so
it holds for a frame shape nobody has designed yet.

It needs no tolerance. Across 270 family-seed cells (9 families x 30 seeds) the gap
is **exactly zero, every time** -- not small, zero -- and that holds at every dataset
size tried. When the junction carries nothing the two feature sets differ only by
bigrams constant across both classes, which cannot move a Naive Bayes decision.

Inverting health's clauses to put the filler clause-initial breaks it in **30 of 30
seeds at 30 pairs per scenario**, the size the test runs. Detection is *not*
monotonic in that size -- 25/30 at 16 pairs, 30/30 at 20, 25/30 at 24, 28/30 at 40 --
because which frames land in which fold shifts with it. So the check is a strong
detector of this defect, not a proof against it. The property that is exact
everywhere is the **zero false-positive rate**, and that is the one the
no-tolerance assertion actually rests on.

``test_join_buys_the_probe_nothing`` asserts it.

Where it beats the existing bound, and where it does not
--------------------------------------------------------
Mutating ``health`` one property at a time, against the shipped seed and the 60%
per-family bigram bound:

    mutation                      ship-seed gap   ship-seed exploitable   bound
    P1 filler clause-initial              3.57%                   53.6%    pass
    P2 clause opens with a stopword       0.00%                   50.0%    pass
    P3 differing token before slot        0.00%                  100.0%    FAIL

**P1 is the case that justifies this round.** On the shipped seed the clause-initial
defect reaches only 53.6% exploitable -- under the 60% bound, so the gate stays green
-- while the gap check catches it outright. The bound does catch P1 on other seeds
(up to 69.3%), which means the existing gate's detection of Round 15's defect was
*seed-dependent*. The gap check is not.

**P3 needs no help**: a differing token before the slot reaches 100% exploitable and
the bound fails instantly. The gap check cannot see it at all, because that is the
*internal* clause-to-clause junction, which both tokenizations cross.

A near-miss worth recording
---------------------------
P2 reads 0.00% / 50.0% above, and the obvious conclusion -- *the stopword property
guards nothing, delete it* -- **is false.** It was an artifact of mutating only
``health``. Applying the strong form of the violation (every clause of every frame
opening with ``the``) across all nine families:

    family        shipped   all-open-'the'      move   breaches 60% bound
    childcare       50.0%           59.1%     +9.1%                   no
    commerce        50.0%           66.1%    +16.1%                  YES
    deadline        50.0%           59.3%     +9.3%                   no
    driving         50.0%           52.9%     +2.9%                   no
    finance         50.0%           52.9%     +2.9%                   no
    health          50.0%           50.0%     +0.0%                   no
    meeting_prep    50.0%           57.7%     +7.7%                   no
    quiet_hours     50.0%           58.0%     +8.0%                   no
    travel          50.0%           54.1%     +4.1%                   no

P2 is load-bearing for **eight of nine families**. ``health`` is the single exception,
and for a reason specific to it: its filler pair is ``your prescription`` /
``Elena's prescription``, which share a final token, so the internal junction bigram
is identical whichever role each noun plays. Families whose fillers are ``you`` and a
colleague's name have no such protection.

Had this round stopped at the one-family table it would have deleted a live assertion
on the strength of the one family where it happens not to bite -- the same shape of
error as Round 17 queueing the removal of a README claim that turned out to be true.
**A property measured on one family is not measured.**

All three properties earn their place. The gap check is **complementary**, not a
replacement: it covers the body junction, which is precisely where the 60% bound is
weakest on the shipped seed.

Run::

    uv run python experiments/signal_join_probe.py
"""

from __future__ import annotations

from tactbench.audit import _frame_key, _NaiveBayes, tokenize
from tactbench.dataset.generate import FRAMES, generate
from tactbench.schema import Item

FOLDS = 5


def bigrams(tokens: list[str]) -> list[str]:
    return [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]


def joined_bigrams(item: Item) -> list[str]:
    """What the shipped audit sees: every signal joined, then tokenized."""
    return bigrams(tokenize(" ".join(s.content for s in item.moment.signals)))


def separated_bigrams(item: Item) -> list[str]:
    """Each signal tokenized on its own -- no bigram crosses a signal boundary."""
    out: list[str] = []
    for signal in item.moment.signals:
        out.extend(bigrams(tokenize(signal.content)))
    return out


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


def invert(clause: str) -> str:
    """``"Behind the screen is {who}"`` -> ``"{who} is behind the screen"``.

    Same tokens, same skeleton length, filler moved from clause-final to
    clause-initial -- Round 15's defect and nothing else. Only applies to the
    ``health`` frames, which all end ``" is {who}"``.
    """
    head = clause.removesuffix(" is {who}")
    return "{who} is " + head[0].lower() + head[1:]


def table(items: list[Item], heading: str) -> None:
    print(heading)
    print(f"{'family':<14} {'joined':>9} {'separated':>11} {'gap':>8}")
    print("-" * 45)
    for family in sorted({i.moment.family for i in items}):
        subset = [i for i in items if i.moment.family == family]
        j = frame_folded_accuracy(subset, joined_bigrams)
        s = frame_folded_accuracy(subset, separated_bigrams)
        flag = "  <-- junction carries signal" if abs(j - s) > 1e-9 else ""
        print(f"{family:<14} {j:>8.1%} {s:>10.1%} {j - s:>+8.1%}{flag}")
    print()


def main() -> None:
    table(
        generate(n_pairs_per_scenario=30),
        "Shipped frames -- the two columns must agree exactly, everywhere.\n",
    )

    # Reintroduce Round 15's defect in one family, and *only* that defect. Each
    # shipped `health` clause reads "<skeleton> is {who}"; inverting it moves the
    # filler to clause-initial and changes nothing else. All eight frames stay
    # distinctly worded, the permutation holds, the token multiset is untouched --
    # so the only thing that moves is which token sits against the body boundary.
    #
    # Holding frame variation fixed is what makes this mutation mean anything. An
    # earlier version collapsed all eight frames to a single wording and sent
    # `health` to 82.0% on *both* columns: a real leak, but a frame-variation leak,
    # which this check is not for and does not claim to catch.
    original = FRAMES["health"]
    FRAMES["health"] = [tuple(invert(c) for c in frame) for frame in original]
    try:
        table(
            generate(n_pairs_per_scenario=30),
            "With `health` mutated to a clause-INITIAL filler (Round 15's defect):\n",
        )
    finally:
        FRAMES["health"] = original

    print(
        "The gap is the whole argument. Zero means the join is free: the junction\n"
        "carries nothing, so keeping it costs the audit no honesty and buys coverage\n"
        "of a serializing reader. Nonzero means a bigram is riding the shared body\n"
        "and will transfer through a held-out frame -- the leak the split exists to\n"
        "prevent.\n\n"
        "On the shipped seed that mutation reaches only 53.6% exploitable, under the\n"
        "60% per-family bound, so the gate stays green while this check does not.\n"
        "That is why the check exists. See this module's docstring for the full\n"
        "mutation matrix -- including the one-family reading that would have had this\n"
        "round delete a live assertion."
    )


if __name__ == "__main__":
    main()
