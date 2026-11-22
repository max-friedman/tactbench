"""The frame search for ``dinner_booking`` (dataset v9). Round 80.

Adapted from ``experiments/frame_search_v8.py`` and committed for the same reason: the
counts DATASET.md quotes must re-run. ``tests/test_dataset_v9.py`` asserts that
:func:`search` still picks the shipped frames and that those counts are the ones
printed here.

Each candidate is ``(privileged, other)``: the privileged clause says the booking at
the restaurant is not confirmed (requested, waitlisted, conditional), the other that a
table is confirmed. Every clause speaks of the booking at that restaurant as a whole
(R76 review), ends ``at``/``from``/``to`` the restaurant, and meets the structural
rules the suite enforces on any frame (``TestProseFrameStructure``): one slot, at the
end, never clause-initial; no clause opens with a stopword; both clauses put the same
token before the slot and have equal skeletons. Candidates use no word of the
family's body templates (``test_the_decider_says_nothing_about_tonight``) and never
*you*, *your* or *home*.

The search is v8's, with negation polarity balanced from the start (the R76 review's
finding, so it is not left for a review to find again):

1. a dev set (frames 0-4) and a held-out set (5-7), lexically disjoint by stem
   (``TestFrameDisjointness``) and, new in v9, by root (:func:`_root`: no two of the
   eight frames share *conditional*, *confirm*, ...), on which each of the eight gated
   clause features -- chars, -er, -s, -ing, -ed, longest word, vowels, consonants -- and
   a generic negation word (``negation_probe.negated``) has the privileged clause win as often as
   it loses, on each split separately;
2. among those, rank by the strongest cheap clause feature (letter counts, letter pairs
   and triples, word prefixes and suffixes of one to three letters, word lengths, word
   count) that reads the same way on both splits, frame by frame (lowest first); then
   by the strongest on dev alone; then by the candidates' order in the list, so the
   result is deterministic.

    uv run python experiments/frame_search_v9.py
"""

from __future__ import annotations

import re
import sys
from itertools import combinations

from negation_probe import negated

from tactbench.dataset.generate import WHO, skeleton

#: (privileged: not confirmed, other: confirmed), in authoring order.
CANDIDATES: list[tuple[str, str]] = [
    # Neither clause negated.
    ("Waitlisted for a table at {who}", "Confirmed for a table at {who}"),
    ("Seats pending at {who}", "Seats secured at {who}"),
    ("Reservation status reads tentative at {who}", "Reservation status reads definite at {who}"),
    ("Seating provisional at {who}", "Seating guaranteed at {who}"),
    ("Provisional hold placed at {who}", "Guaranteed hold placed at {who}"),
    ("Booking only requested at {who}", "Booking fully accepted at {who}"),
    ("Hopeful of seating at {who}", "Assured of seating at {who}"),
    ("Acceptance pending from {who}", "Acceptance received from {who}"),
    ("Listed among waitlisted guests at {who}", "Listed among confirmed guests at {who}"),
    ("Queued for a cancellation at {who}", "Booked into a slot at {who}"),
    ("Approval outstanding from {who}", "Approval arrived from {who}"),
    ("Second on the waiting roster at {who}", "Firmly on the dining roster at {who}"),
    ("Tentative slot at {who}", "Settled slot at {who}"),
    ("Possibly a table at {who}", "Certainly a table at {who}"),
    ("Table requested at {who}", "Table reserved at {who}"),
    ("Table sought at {who}", "Table held at {who}"),
    ("Queued for seating at {who}", "Cleared for seating at {who}"),
    ("Spot pending at {who}", "Spot settled at {who}"),
    ("Booking awaits approval at {who}", "Booking has approval at {who}"),
    ("Reservation awaiting approval at {who}", "Reservation holding approval at {who}"),
    ("Standby status at {who}", "Firm status at {who}"),
    ("Diners queued on standby at {who}", "Diners booked in firmly at {who}"),
    ("Waiting list entry stands at {who}", "Firm booking entry stands at {who}"),
    ("Booking request awaits a reply at {who}", "Booking request got a yes at {who}"),
    ("Allocation pending at {who}", "Allocation complete at {who}"),
    ("Waitlisted at {who}", "Confirmed at {who}"),
    ("Seats in doubt at {who}", "Seats in place at {who}"),
    ("Table sought for the party at {who}", "Table waiting for the party at {who}"),
    # Added after the R80 review.
    ("Booking reference pending from {who}", "Booking reference received from {who}"),
    # A negation on the privileged side (the booking is not confirmed).
    ("Lacking a reserved slot at {who}", "Holding a reserved slot at {who}"),
    ("Unconfirmed so far at {who}", "Confirmed so far at {who}"),
    ("Uncertain of a table at {who}", "Certain of a table at {who}"),
    ("Reservation unconfirmed at {who}", "Reservation confirmed at {who}"),
    ("Tables held total zero at {who}", "Tables held total one at {who}"),
    ("Never approved was the request to {who}", "Promptly approved was the request to {who}"),
    ("Without a held table at {who}", "With a held table at {who}"),
    ("Absent from the booked tables at {who}", "Present among the booked tables at {who}"),
    ("Missing a firm booking at {who}", "Holding a firm booking at {who}"),
    ("Seat promised by nobody at {who}", "Seat promised by staff at {who}"),
    ("Uncertainty surrounds the table at {who}", "Certainty surrounds the table at {who}"),
    ("Seat allocation undecided at {who}", "Seat allocation decided at {who}"),
    ("Request unanswered at {who}", "Request honoured at {who}"),
    ("Enquiry unanswered at {who}", "Enquiry accepted at {who}"),
    ("Booking unapproved at {who}", "Booking approved at {who}"),
    ("Seats unassigned at {who}", "Seats assigned at {who}"),
    ("Table unallocated at {who}", "Table allocated at {who}"),
    ("Reservation unaccepted at {who}", "Reservation accepted at {who}"),
    ("Hold unconfirmed by staff at {who}", "Hold confirmed by staff at {who}"),
    ("Acceptance absent from {who}", "Acceptance present from {who}"),
    ("Booking unsettled at {who}", "Booking settled at {who}"),
    ("Booking stands unconfirmed at {who}", "Booking stands firm at {who}"),
    ("Allocation incomplete at {who}", "Allocation complete at {who}"),
    ("Approval lacking at {who}", "Approval given at {who}"),
    ("Seats are not held at {who}", "Seats are now held at {who}"),
    ("Guest list shows none of the party at {who}", "Guest list shows all of the party at {who}"),
    ("Seats held number zero at {who}", "Seats held number four at {who}"),
    ("Seat lacking at {who}", "Seat reserved at {who}"),
    # Added after the R80 review, which replaced two frames.
    ("Holding no table for the party at {who}", "Holding a table for the party at {who}"),
    ("Booked table exists nowhere at {who}", "Booked table exists already at {who}"),
    ("Seat count held is zero at {who}", "Seat count held is four at {who}"),
    ("Places kept for the party number zero at {who}", "Places kept for the party number four at {who}"),
    ("Reference code unissued by {who}", "Reference code issued by {who}"),
    ("Booking reference absent from {who}", "Booking reference arrived from {who}"),
    ("Confirmation code missing from {who}", "Confirmation code received from {who}"),
    ("Name absent from the bookings book at {who}", "Name present in the bookings book at {who}"),
    ("Room for the party unknown at {who}", "Room for the party assured at {who}"),
    # Both clauses negated.
    ("Never secured a table at {who}", "Never lacked a table at {who}"),
    ("Nothing confirmed at {who}", "Everything confirmed at {who}"),
    # A negation on the other side (the booking is confirmed).
    ("Needing a final confirmation at {who}", "Needing no further confirmation at {who}"),
    ("Subject to seat availability at {who}", "Subject to no conditions at {who}"),
    ("Table promised conditionally at {who}", "Table promised unconditionally at {who}"),
    ("Conditional booking at {who}", "Unconditional booking at {who}"),
    ("Seating doubtful at {who}", "Seating undoubted at {who}"),
    ("Chance of losing the table is real at {who}", "Chance of losing the table is zero at {who}"),
    ("Seats might go to others at {who}", "Seats cannot go to others at {who}"),
    ("Table could be given away at {who}", "Table cannot be given away at {who}"),
    # Added after the R80 review.
    ("Party could be turned away at {who}", "Party cannot be turned away at {who}"),
    ("Hostess may turn the party away at {who}", "Hostess cannot turn the party away at {who}"),
    ("Seats might be refused at {who}", "Seats cannot be refused at {who}"),
    (
        "Seated only if someone cancels at {who}",
        "Seated without anybody else cancelling at {who}",
    ),
]

#: Rejected before the search, with the reason. A careful human could read each one
#: backwards, or it leans on an idiom, or it does not settle whether a table is held.
EXCLUDED: dict[tuple[str, str], str] = {
    ("Seating relies on a callback at {who}", "Seating relies on no callback at {who}"): (
        "the R80 review's objection to 'dependent on no cancellation': relying on no "
        "callback does not say a table is held"
    ),
    ("Revocable hold at {who}", "Irrevocable hold at {who}"): (
        "R80 review: a revocable hold is still a held table, so both sides read as confirmed"
    ),
    ("Dependent on a cancellation at {who}", "Dependent on no cancellation at {who}"): (
        "R80 review: 'dependent on no cancellation' reads as conditional (it holds as long "
        "as nobody cancels) and does not say a table is held"
    ),
    ("Party still unplaced at {who}", "Party already placed at {who}"): (
        "'placed' is unclear: seated, or ranked"
    ),
    ("Covers awaited at {who}", "Covers granted at {who}"): (
        "'covers' is trade jargon for diners; a careful reader may not know it"
    ),
    ("Requests unmet at {who}", "Requests met at {who}"): (
        "the requests could be special requests (a quiet corner, a cake), not the booking"
    ),
    ("Requires a reply from staff at {who}", "Requires nothing further from staff at {who}"): (
        "'requires nothing further from staff' does not say a table is held"
    ),
    ("Waitlist position held at {who}", "Waitlist position unneeded at {who}"): (
        "an unneeded waitlist place implies a table only by inference"
    ),
    ("Seating dependent on demand at {who}", "Seating independent of demand at {who}"): (
        "'independent of demand' does not say a table is held"
    ),
    ("Open questions remain at {who}", "Zero open questions at {who}"): (
        "the questions need not be about the booking"
    ),
    ("Outstanding steps before seating at {who}", "Zero steps before seating at {who}"): (
        "'steps before seating' reads as walking distance"
    ),
    ("Nothing held yet at {who}", "Something held already at {who}"): (
        "'something held' is too vague to mean a table"
    ),
    ("Sitting hoped for at {who}", "Sitting locked in at {who}"): ("'locked in' is an idiom"),
    ("Maybe seated at {who}", "Surely seated at {who}"): (
        "'surely' often signals doubt, so it reads both ways"
    ),
    ("Places applied for at {who}", "Places allotted for at {who}"): (
        "'allotted for at' is not grammatical"
    ),
    ("Booking status open at {who}", "Booking status closed at {who}"): (
        "a closed booking could be a cancelled one: readable backwards"
    ),
    ("Approval withheld so far by {who}", "Approval granted so far by {who}"): (
        "'withheld' can mean refused rather than not yet given"
    ),
    ("Answer pending from {who}", "Answer received from {who}"): (
        "a received answer could be a refusal: does not settle the booking"
    ),
    ("Awaiting a callback from {who}", "Received a confirmation from {who}"): (
        "unequal: 'awaiting a callback' need not concern the booking at all"
    ),
    ("Tentatively pencilled in at {who}", "Firmly booked in at {who}"): (
        "'pencilled in' is an idiom"
    ),
    ("Seating might yet fall through at {who}", "Seating can never fall through at {who}"): (
        "'fall through' is an idiom"
    ),
    ("Without a firm answer is {who}", "With a firm answer is {who}"): (
        "a firm answer could be a firm no; and it makes the restaurant the subject"
    ),
    ("Booking could lapse at {who}", "Booking cannot lapse at {who}"): (
        "a confirmed booking can lapse too, if the party is late: readable both ways"
    ),
    ("Awaiting an answer at {who}", "Awaiting nothing more at {who}"): (
        "'awaiting nothing more' could follow a refusal"
    ),
    ("Final word owed by {who}", "Final word given by {who}"): ("the final word could be no"),
    ("Refusal possible at {who}", "Refusal impossible at {who}"): (
        "'impossible' is a negation the probe's lexicon does not list, so it would hide "
        "polarity from the balance rather than balance it"
    ),
    ("Waitlisted for a table is {who}", "Confirmed for a table is {who}"): (
        "'is {who}' makes the restaurant the one waitlisted; every frame ends 'at' (or "
        "'from', 'to') the restaurant instead"
    ),
    ("Your table is pending at {who}", "Your table is confirmed at {who}"): (
        "'your' is the marker in other families, and the heuristic reads it"
    ),
}

#: The token list the suite treats as stopwords (``TestFrameDisjointness.STOP``),
#: restated here so the script runs without the test package.
STOP = frozenset(
    "the a an of to for on at in is be and not yet it its you your still already up off "
    "out down over under by has have was will this are from due no".split()
)
HELD_OUT = (5, 6, 7)
#: Words no frame may use (R74: no frame says a place is the user's).
ADDRESSED = frozenset({"you", "your", "yours", "home", "my", "mine", "our"})


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "s"):
        if word.endswith(suffix) and len(word) > 4:
            return word[: -len(suffix)]
    return word


def _content(clause: str) -> set[str]:
    text = " ".join(skeleton(clause)).lower()
    return {_stem(w) for w in re.findall(r"[a-z]+", text) if w not in STOP}


def _root(word: str) -> str:
    """A content word with a negating prefix and common suffixes removed. Stricter than
    :func:`_stem`, which is the suite's rule: *conditional* and *unconditionally* share a
    root but not a stem, and a dev frame and a held-out frame built on the same root would
    hand a character learner the held-out answer (R80)."""
    for prefix in ("non", "ir", "un", "in"):
        if word.startswith(prefix) and len(word) - len(prefix) >= 5:
            word = word[len(prefix) :]
            break
    for suffix in ("ally", "ly", "ing", "ed", "s", "al"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
    return word


def _roots(clause: str) -> set[str]:
    return {_root(w) for w in _content(clause)}


def _share_a_root(x: set[str], y: set[str]) -> bool:
    """Equal roots, or one root of five letters or more opening the other."""
    return any(
        a == b or (min(len(a), len(b)) >= 5 and (a.startswith(b) or b.startswith(a)))
        for a in x
        for b in y
    )


def _before_slot(clause: str) -> str:
    return clause.split(WHO)[0].split()[-1].lower()


def check_structure(pair: tuple[str, str]) -> None:
    a, b = pair
    for c in pair:
        assert c.count(WHO) == 1 and c.endswith(WHO), c
        assert skeleton(c)[0].lower() not in STOP, c
    assert len(skeleton(a)) == len(skeleton(b)), pair
    assert _before_slot(a) == _before_slot(b), pair


def _text(clause: str) -> str:
    """The clause as feature_exploit sees it: the filler and the space before it gone."""
    return clause.replace(" " + WHO, "")


def _vowels(c: str) -> int:
    return sum(ch in "aeiou" for ch in c.lower())


def _consonants(c: str) -> int:
    return sum(ch.isalpha() and ch not in "aeiou" for ch in c.lower())


#: The eight gated features, as ``clause_length_probe.FEATURES`` and the v8 test define
#: them, and negation (R76).
GATED = {
    "chars": len,
    "er": lambda c: sum(w.lower().rstrip("s").endswith("er") for w in c.split()),
    "s": lambda c: sum(w.endswith("s") for w in c.split()),
    "ing": lambda c: sum(w.endswith("ing") for w in c.split()),
    "ed": lambda c: sum(w.endswith("ed") for w in c.split()),
    "longest": lambda c: max(len(w) for w in c.split()),
    "vowels": _vowels,
    "consonants": _consonants,
    # R76 review: whether the clause carries a generic negation word
    # (``negation_probe.negated``), so polarity balances like every other feature.
    "negation": lambda c: int(negated(c)),
}


def cheap_features(clause: str) -> dict[str, int]:
    """Counts of letters, letter pairs and triples within words, word prefixes and
    suffixes of one to three letters, words of each length, and words."""
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", clause)]
    out: dict[str, int] = {}

    def add(key: str) -> None:
        out[key] = out.get(key, 0) + 1

    for w in words:
        for n in (1, 2, 3):
            for i in range(len(w) - n + 1):
                add(f"gram:{w[i : i + n]}")
            if len(w) >= n:
                add(f"pre:{w[:n]}")
                add(f"suf:{w[-n:]}")
        add(f"len:{len(w)}")
    out["words"] = len(words)
    return out


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def search() -> dict:
    for pair in CANDIDATES:
        check_structure(pair)
    assert not set(CANDIDATES) & set(EXCLUDED)
    assert len(set(CANDIDATES)) == len(CANDIDATES)
    for pair in CANDIDATES:
        words = {w.lower() for c in pair for w in re.findall(r"[A-Za-z]+", c)}
        assert not words & ADDRESSED, pair
    n = len(CANDIDATES)
    texts = [(_text(a), _text(b)) for a, b in CANDIDATES]
    gated = [tuple(_sign(f(a) - f(b)) for f in GATED.values()) for a, b in texts]
    vocab = [_content(a) | _content(b) for a, b in CANDIDATES]
    feats = [(cheap_features(a), cheap_features(b)) for a, b in texts]
    universe = sorted({k for fa, fb in feats for k in (*fa, *fb)})
    cheap = [[_sign(fa.get(k, 0) - fb.get(k, 0)) for k in universe] for fa, fb in feats]

    def disjoint(ids) -> bool:
        return all(not vocab[i] & vocab[j] for i, j in combinations(ids, 2))

    def balanced(ids) -> bool:
        return all(sum(gated[i][k] for i in ids) == 0 for k in range(len(GATED)))

    roots = [_roots(a) | _roots(b) for a, b in CANDIDATES]
    # Lexical disjointness by stem (the suite's rule), and also by root (R80), so that no
    # two chosen frames share a word's root, within a split or across the two.
    clash = [
        {
            j
            for j in range(n)
            if j != i and (vocab[i] & vocab[j] or _share_a_root(roots[i], roots[j]))
        }
        for i in range(n)
    ]

    def disjoint_sets(size: int, start: int = 0, chosen: tuple[int, ...] = ()):
        """Every ``size``-set with no clash, in ``combinations`` order, pruned as it goes so
        the search stays fast with v9's longer candidate list."""
        if len(chosen) == size:
            yield chosen
            return
        for i in range(start, n):
            if not any(i in clash[j] for j in chosen):
                yield from disjoint_sets(size, i + 1, (*chosen, i))

    held_sets = [s for s in disjoint_sets(3) if balanced(s)]
    dev_sets = [s for s in disjoint_sets(5) if balanced(s)]
    assert all(disjoint(s) for s in held_sets + dev_sets)

    def sums(ids):
        return [sum(cheap[i][k] for i in ids) for k in range(len(universe))]

    held_sums = {s: sums(s) for s in held_sets}
    ranked = []
    for d in dev_sets:
        dsum = sums(d)
        dev_alone = max(abs(x) for x in dsum) / 10  # exploit over 0.5 on dev alone
        for h in held_sets:
            if set(d) & set(h) or any(j in clash[i] for i in d for j in h):
                continue
            hsum = held_sums[h]
            both = max(
                (
                    min(abs(x) / 10, abs(y) / 6)
                    for x, y in zip(dsum, hsum, strict=True)
                    if x * y > 0
                ),
                default=0.0,
            )
            ranked.append((both, dev_alone, d, h))
    ranked.sort()
    both, dev_alone, d, h = ranked[0]
    # On the chosen set: the features present in its clauses, and the strongest one
    # reading the same way on both splits and on dev alone, as (name, dev, held-out),
    # each the share of frames on which "speak iff tonight's restaurant's clause has more
    # of it" is right (ties a half), which is its reading on the shipped splits.
    dsum, hsum = sums(d), held_sums[h]
    present = [k for k in range(len(universe)) if any(cheap[i][k] for i in (*d, *h))]

    def reading(k: int) -> tuple[str, float, float]:
        return universe[k], 0.5 + dsum[k] / 10, 0.5 + hsum[k] / 6

    same = [k for k in present if dsum[k] * hsum[k] > 0]
    top_both = max(same, key=lambda k: min(abs(dsum[k]) / 10, abs(hsum[k]) / 6), default=None)
    top_dev = max(present, key=lambda k: abs(dsum[k]))
    return {
        "candidates": n,
        "excluded": len(EXCLUDED),
        "balanced": len(ranked),
        "features": len(universe),
        "best": [CANDIDATES[i] for i in (*d, *h)],
        "best_both": 0.5 + both,
        "best_dev": 0.5 + dev_alone,
        "present": len(present),
        "top_both": None if top_both is None else reading(top_both),
        "top_dev": reading(top_dev),
        "top": [
            ([CANDIDATES[i] for i in (*dd, *hh)], 0.5 + b, 0.5 + da) for b, da, dd, hh in ranked[:6]
        ],
    }


def main(argv: list[str]) -> None:
    r = search()
    print(
        f"{r['candidates']} candidates ({r['excluded']} excluded before the search); "
        f"{r['balanced']:,} balanced dev/held-out sets; {r['features']} cheap features"
    )
    print(f"best: strongest on both splits {r['best_both']:.0%}, on dev alone {r['best_dev']:.0%}")
    print(f"{r['present']} features present; both: {r['top_both']}; dev alone: {r['top_dev']}")
    for k, (a, b) in enumerate(r["best"]):
        print(f"  {k}{'*' if k in HELD_OUT else ' '} {a!r} / {b!r}")
    if "--top" in argv:
        for frames, b, da in r["top"]:
            print(f"{b:.0%} {da:.0%}", [a.split(" {")[0] for a, _ in frames])


if __name__ == "__main__":
    main(sys.argv[1:])
