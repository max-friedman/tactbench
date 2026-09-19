"""Should the shortcut probe cross signal boundaries?

``audit.item_tokens`` joins every signal into one string before tokenizing, so
bigrams span the junction between the shared body signal and the discriminating
decider signal. Round 15 found that choice is **load-bearing** and left it
unresolved; this module is the measurement Round 21 used to settle it.

Every **number** quoted below is computed by ``main()``, with one exception, named
here because earlier drafts of this line claimed "nothing here is prose-only" and
were wrong. The exception is the list of six suite tests that fail under the
trailing-signal mutation, and the 70.7% beside it: those come from running the suite
with that mutation applied, not from this module. Reproduce them by appending a
shared ``Signal`` to every item in ``generate`` and running ``uv run pytest -q``.

Why it is not a detail
----------------------
The junction is the only place a discriminating bigram can ride text that is
*shared across all eight frames*. Body text is identical across frames, so a bigram
anchored there **transfers through a held-out frame** -- which is exactly what the
dev/test split exists to prevent. Every other discriminating bigram lives inside a
decider clause and dies with its frame.

The ruling: keep the join
-------------------------
Both readings are defensible. A policy that serializes the moment into one prompt
-- which is what every LLM baseline in ``policies/llm.py`` will do -- genuinely sees
the junction. A policy reading the structured ``Signal`` list never does.

**Keep the join**, because the probe's job is not to model the average reader. A
submitter picks their own representation, so a shortcut reachable under *any*
reasonable serialization is a shortcut in the dataset. Joining is the upper bound
over representations; separating measures one particular reader and would report
"clean" for a leak the LLM baselines could take.

The check, and what it is NOT for
---------------------------------
If the deciders are well-formed the join buys the probe **nothing**, so joined and
separated tokenizations must score the same. ``TestSignalJoinIsFree`` asserts that
with **no tolerance**: **270** family-seed cells (9 families x 30 seeds) at each of
the sizes 16, 20, 24, 30 and 40 -- **1350** in total -- plus a wider **1296**-cell
sweep (8 seeds x 6 sizes x 3 fold counts x 9 families). The gap is identically zero
in every one. Not small -- zero. When the junction carries nothing the two feature
sets differ only by bigrams constant across both classes, and a constant cannot move
a Naive Bayes decision. ``main()`` computes both sweeps.

**Round 21 first justified this check by saying it caught Round 15's clause-initial
defect where the gate did not. That was wrong**, and it is recorded here because the
wrong version nearly shipped. ``TestProseFrameStructure`` already asserts the
clause-initial property directly -- deterministically, every family, no dataset, no
seed (the ``structural`` column below, printed by ``main()``). Against P1 this check
is strictly *weaker*. What lets P1 through is the **60% per-family bound**, not the
gate.

Per-property, across all nine families (table 2 below). The bound is reported twice
because the two disagree, which is a finding in its own right::

    mutation                        gap fires   bound @ship   bound worst/8   structural
    P1 filler clause-initial           7 of 9        2 of 9          5 of 9   9 of 9
    P2 clause opens with a stopword    0 of 9        0 of 9          1 of 9   9 of 9
    P3 differing token before slot     0 of 9        8 of 9          8 of 9   9 of 9

Read honestly, that table says the three structural properties dominate all three
mutations and this check adds nothing against any of them.

It also shows the **60% bound is seed-dependent**: P1 breaches it for 2 families on
``seed=20260726`` and 5 at its worst over eight seeds. The audit samples that seed
exactly once, so every leakage figure this project publishes is a point estimate with
unquantified spread. That is queued, and it is a property of the *bound*, not of the
gate -- the gate catches all three mutations deterministically via
``TestProseFrameStructure``, on every seed, without a dataset.

What the check is actually for
------------------------------
All three properties constrain the decider's **clause openings**, which protects the
junction the *body* sits against. That is sufficient today only because the decider
happens to be the **last** signal.

Append one shared signal after the decider -- leaving ``FRAMES`` untouched, so all
three properties still pass -- and the decider's trailing token is the filler,
abutting text every frame shares (table 3 below)::

    appended trailing signal      gap check fires   60% bound fails
    across nine families                   8 of 9            1 of 9

No frame-shape assertion constrains that junction. This is the check's justification,
and unlike the original one it is exhibited rather than asserted.

Stated precisely, because earlier drafts of this sentence undercounted it.
The suite is **not** blind to that mutation. Appending the signal to every item turns
it red in **six** places::

    per-family 60% bound            quiet_hours at 61.6%
    overall < 70% bound             70.7% at n=10 (size-dependent, marginal)
    split disjointness              \  these THREE fail because the suite
    object identity                  >  hard-codes the decider as the last
    order balance                   /   signal (``signals[-1]``, ``signals[:-1]``)
    dataset reproducibility             fails on ANY generator change, so it
                                        says nothing about signal position

So a family placing a signal after the decider is a loud failure, not a silent one.
What this check adds is **localization and breadth**: it is the only assertion that
names the failure as a *junction leak* rather than as a downstream symptom, and it
fires on 8 of 9 families where the bound fires on 1. No frame-shape property sees it
at all.

A near-miss worth recording
---------------------------
Mutating P2 on ``health`` alone moves nothing -- 0.00% gap, 50.0% exploitable -- and
the obvious conclusion, *the stopword property guards nothing, delete it*, **is
false.** Across all nine families the same violation moves eight of them, by up to
**+16.1%** (``commerce``, 50.0% -> 66.1% at its worst over eight seeds, which is the
one cell where it breaches the bound).

``health`` is the sole exception because its filler pair (``your prescription`` /
``Elena's prescription``) shares a final token, so the internal junction bigram is
identical whichever role each noun plays. That explanation is not inferred from the
nine-row correlation alone: ``health`` is *also* the single family immune to the
trailing-signal leak in table 3, which is an independent test of the same mechanism.

Had this round stopped at the one-family table it would have deleted a live assertion
protecting eight families -- the same shape of error as Round 17 queueing the removal
of a README claim that turned out to be true. **A property measured on one family is
not measured.**

The round then broke that rule repeatedly in its own writeup and in the commits
fixing it, several times *inside the sentence written to fix the previous instance*.
The instances the reviews named are tabulated in ``docs/plans/LOOP_STATE.md`` under
Round 21; no total is claimed there, because earlier drafts of that paragraph each
gave a count and each was wrong.

Tables 2, 3 and 4 exist because of it: every figure quoted above was prose with no
code path until someone checked.

Run::

    uv run python experiments/signal_join_probe.py
"""

from __future__ import annotations

from tactbench.audit import _frame_key, _NaiveBayes, tokenize
from tactbench.dataset.generate import FRAMES, WHO, generate, skeleton
from tactbench.schema import Item, Signal, Source

FOLDS = 5
SHIPPED_SEED = 20260726


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


def exploitable(accuracy: float) -> float:
    return 0.5 + abs(accuracy - 0.5)


# -- the three property violations, each generic enough to apply to any family ------


def p1_clause_initial(frame: tuple[str, str]) -> tuple[str, str]:
    """Move the filler to the front. Same tokens, same skeleton length."""
    return tuple(f"{WHO} " + " ".join(skeleton(c)) for c in frame)  # type: ignore[return-value]


def p2_opens_with_stopword(frame: tuple[str, str]) -> tuple[str, str]:
    """Every clause of every frame opens with the same shared token."""
    return tuple("The " + c[0].lower() + c[1:] for c in frame)  # type: ignore[return-value]


def p3_differing_token_before_slot(frame: tuple[str, str]) -> tuple[str, str]:
    """Break the symmetry of the token immediately preceding the slot."""
    a, b = frame
    head, tail = b.split(WHO, 1)
    tokens = head.split()
    if not tokens:
        return frame
    tokens[-1] = "for" if tokens[-1].lower() != "for" else "with"
    return (a, " ".join(tokens) + " " + WHO + tail)


def measure(family: str, seed: int = SHIPPED_SEED, n: int = 30) -> tuple[float, float]:
    """``(gap, exploitable_joined_accuracy)`` for one family."""
    items = [i for i in generate(n_pairs_per_scenario=n, seed=seed) if i.moment.family == family]
    j = frame_folded_accuracy(items, joined_bigrams)
    s = frame_folded_accuracy(items, separated_bigrams)
    return j - s, exploitable(j)


SEEDS = [SHIPPED_SEED + k for k in range(8)]


def structural_catches(mutate) -> int:
    """How many of the nine families ``TestProseFrameStructure`` rejects outright.

    The point of the comparison: these are deterministic predicates over the frame
    text -- no dataset, no seed, no classifier. Printed rather than asserted in prose
    because the round's first draft quoted this column without producing it.
    """
    original = {k: list(v) for k, v in FRAMES.items()}
    caught = 0
    try:
        for family in sorted(original):
            frames = [mutate(f) for f in original[family]]
            bad = False
            for privileged, other in frames:
                for clause in (privileged, other):
                    head = clause.split(WHO)[0].split()
                    if not head:  # filler is clause-initial
                        bad = True
                    elif skeleton(clause)[0].lower().strip(".,") in _STOP:
                        bad = True
                a_head = privileged.split(WHO)[0].split()
                b_head = other.split(WHO)[0].split()
                if a_head and b_head and a_head[-1].lower() != b_head[-1].lower():
                    bad = True
            caught += bad
    finally:
        for family, frames in original.items():
            FRAMES[family] = frames
    return caught


#: Mirrors ``TestFrameDisjointness.STOP``; duplicated so this module stays runnable
#: on its own rather than importing from the test suite.
_STOP = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "out",
    "that",
    "the",
    "to",
    "was",
    "with",
    "you",
    "your",
    "home",
}


def mutated_table(mutate, heading: str) -> None:
    """Apply `mutate` to every family's frames in turn and report both detectors.

    Reports the bound on the **shipped seed** and as the **max over 8 seeds**, because
    the two disagree and that disagreement is itself a finding: a leak's measured size
    depends on ``seed=20260726``, which the audit samples exactly once.
    """
    original = {k: list(v) for k, v in FRAMES.items()}
    print(heading)
    print(
        f"{'family':<14} {'gap':>9} {'expl@ship':>11} {'expl max/8':>12} "
        f"{'bound@ship':>12} {'bound max':>10} {'gap fires':>11}"
    )
    print("-" * 83)
    fires = at_ship = at_max = 0
    try:
        for family in sorted(original):
            FRAMES[family] = [mutate(f) for f in original[family]]
            gap, ship = measure(family)
            worst = max(measure(family, seed=s)[1] for s in SEEDS)
            FRAMES[family] = original[family]
            fires += abs(gap) > 0
            at_ship += ship > 0.60
            at_max += worst > 0.60
            print(
                f"{family:<14} {gap:>+8.2%} {ship:>10.1%} {worst:>11.1%} "
                f"{('FAIL' if ship > 0.60 else 'pass'):>12} "
                f"{('FAIL' if worst > 0.60 else 'pass'):>10} "
                f"{('yes' if abs(gap) > 0 else 'no'):>11}"
            )
    finally:
        for family, frames in original.items():
            FRAMES[family] = frames
    print(
        f"  -> gap fires in {fires} of 9; the 60% bound fails in {at_ship} of 9 on the "
        f"shipped seed, {at_max} of 9 at its worst over 8;\n"
        f"     TestProseFrameStructure rejects {structural_catches(mutate)} of 9 "
        f"deterministically (no dataset, no seed)\n"
    )


def main() -> None:
    print("TABLE 1 -- shipped frames. The two columns must agree exactly, everywhere.\n")
    print(f"{'family':<14} {'joined':>9} {'separated':>11} {'gap':>8}")
    print("-" * 45)
    for family in sorted(FRAMES):
        gap, _ = measure(family)
        items = [i for i in generate(n_pairs_per_scenario=30) if i.moment.family == family]
        j = frame_folded_accuracy(items, joined_bigrams)
        flag = "  <-- junction carries signal" if abs(gap) > 0 else ""
        print(f"{family:<14} {j:>8.1%} {j - gap:>10.1%} {gap:>+8.1%}{flag}")
    print()

    print("TABLE 2 -- each structural property violated in turn, across all nine")
    print("families. Compare against TestProseFrameStructure, which catches all three")
    print("on 9 of 9 deterministically: this check adds nothing against any of them.\n")
    mutated_table(p1_clause_initial, "P1 -- filler moved to clause-initial:\n")
    mutated_table(p2_opens_with_stopword, "P2 -- every clause opens with 'the':\n")
    mutated_table(p3_differing_token_before_slot, "P3 -- differing token before the slot:\n")

    print("TABLE 3 -- the case that justifies the check. One shared signal appended")
    print("AFTER the decider. FRAMES is untouched, so all three structural properties")
    print("still pass -- yet the decider's trailing filler now abuts shared text.\n")
    print(f"{'family':<14} {'gap':>9} {'exploitable':>13} {'60% bound':>11} {'gap fires':>11}")
    print("-" * 61)
    fires = breaches = 0
    for family in sorted(FRAMES):
        items = [i for i in generate(n_pairs_per_scenario=30) if i.moment.family == family]
        trailed = []
        for item in items:
            copy = item.model_copy(deep=True)
            copy.moment.signals.append(
                Signal(content="Reminder set for later today.", source=Source.MESSAGE, age_s=60)
            )
            trailed.append(copy)
        j = frame_folded_accuracy(trailed, joined_bigrams)
        s = frame_folded_accuracy(trailed, separated_bigrams)
        gap, expl = j - s, exploitable(j)
        fires += abs(gap) > 0
        breaches += expl > 0.60
        print(
            f"{family:<14} {gap:>+8.2%} {expl:>12.1%} "
            f"{('FAIL' if expl > 0.60 else 'pass'):>11} {('yes' if abs(gap) > 0 else 'no'):>11}"
        )
    print(f"  -> gap fires in {fires} of 9; the 60% bound fails in {breaches} of 9\n")

    print("TABLE 4 -- the zero-gap sweep the no-tolerance assertion rests on, and the")
    print("sensitivity ladder. Both were prose-only until a reviewer said so.\n")
    # The ladder sweep: 270 family-seed cells (9 x 30) at each of the five sizes the
    # sensitivity ladder below uses.
    per_size = {}
    for n in (16, 20, 24, 30, 40):
        cells = nonzero = 0
        for k in range(30):
            items = generate(n_pairs_per_scenario=n, seed=SHIPPED_SEED + k)
            for family in sorted(FRAMES):
                sub = [i for i in items if i.moment.family == family]
                j = frame_folded_accuracy(sub, joined_bigrams)
                s = frame_folded_accuracy(sub, separated_bigrams)
                cells += 1
                nonzero += abs(j - s) > 0
        per_size[n] = (cells, nonzero)
    total = sum(c for c, _ in per_size.values())
    bad = sum(z for _, z in per_size.values())
    sizes = ", ".join(f"n={n}: {c} cells / {z} nonzero" for n, (c, z) in per_size.items())
    print(f"  ladder sweep, shipped frames -- {sizes}")
    print(f"  ({total} cells in total, {bad} nonzero)\n")

    # The wider sweep: other seeds, odd sizes, and fold counts other than 5.
    cells = nonzero = 0
    for seed in (1, 7, 42, 999, 123456, SHIPPED_SEED, 88888888, 2**31 - 1):
        for n in (16, 17, 23, 30, 31, 50):
            items = generate(n_pairs_per_scenario=n, seed=seed)
            for folds in (3, 5, 8):
                for family in sorted(FRAMES):
                    sub = [i for i in items if i.moment.family == family]
                    j = frame_folded_accuracy(sub, joined_bigrams, folds)
                    s = frame_folded_accuracy(sub, separated_bigrams, folds)
                    cells += 1
                    nonzero += abs(j - s) > 0
    print(f"  wider sweep: {cells} cells (8 seeds x 6 sizes x 3 fold counts x 9")
    print(f"  families) -- nonzero gaps: {nonzero}\n")

    original = FRAMES["health"]
    FRAMES["health"] = [p1_clause_initial(f) for f in original]
    try:
        ladder = []
        for n in (16, 20, 24, 30, 40):
            hit = 0
            for k in range(30):
                sub = [
                    i
                    for i in generate(n_pairs_per_scenario=n, seed=SHIPPED_SEED + k)
                    if i.moment.family == "health"
                ]
                j = frame_folded_accuracy(sub, joined_bigrams)
                s = frame_folded_accuracy(sub, separated_bigrams)
                hit += abs(j - s) > 0
            ladder.append(f"n={n}: {hit}/30")
    finally:
        FRAMES["health"] = original
    print("  detection of the clause-initial mutation, 30 seeds per size:")
    print(f"    {'   '.join(ladder)}")
    print("  -> not monotonic in size; a strong detector, not a proof. What IS exact")
    print("     at every size is the zero false-positive rate above.\n")

    print(
        "health is the only family immune in TABLE 2's P2 block and the only one\n"
        "immune in TABLE 3 -- two independent confirmations that the mechanism is its\n"
        "fillers sharing a final token.\n\n"
        "The headline: against P1, P2 and P3 the structural properties dominate and\n"
        "this check is redundant. TABLE 3 is the one place it is not -- and even there\n"
        "it is not the only thing that notices; see this module's docstring."
    )


if __name__ == "__main__":
    main()
