"""The frame search for ``photo_backup`` (dataset v8). Round 76.

Committed so its counts can be re-run: Round 74's review found that v7's search
figures in DATASET.md were the builder's record only, because that script was never
committed. ``tests/test_dataset_v8.py`` asserts that :func:`search` still picks the
shipped frames and that the counts DATASET.md quotes are the ones printed here.

Each candidate is ``(privileged, other)``: the privileged clause says the album has no
copy outside the cloud, the other that it has one. Every candidate meets the
structural rules the suite enforces on any frame (``TestProseFrameStructure``): one
slot, at the end, never clause-initial; no clause opens with a stopword; both clauses
put the same token before the slot and have equal skeletons. Candidates use no word of
the family's body templates (``test_the_decider_says_nothing_about_deletion``).

The search, as for ``water_notice``, ``street_cleaning`` and ``river_swim``:

1. a dev set (frames 0-4) and a held-out set (5-7), lexically disjoint by stem
   (``TestFrameDisjointness``), on which each of the eight gated clause features --
   chars, -er, -s, -ing, -ed, longest word, vowels, consonants -- and, since the R76
   review, a generic negation word (``negation_probe.negated``) has the privileged clause
   win as often as it loses, on each split separately. The review found the first v8
   frames negated in every privileged clause and no other; it also dropped every
   candidate that reports absence at one device rather than for the album as a whole
   (:data:`ONE_PLACE`);
2. among those, rank by the strongest cheap clause feature (letter counts, letter pairs
   and triples, word prefixes and suffixes of one to three letters, word lengths, word
   count) that reads the same way on both splits, frame by frame (lowest first); then
   by the strongest on dev alone; then by the candidates' order in the list, so the
   result is deterministic.

    uv run python experiments/frame_search_v8.py
"""

from __future__ import annotations

import re
import sys
from itertools import combinations

from negation_probe import negated

from tactbench.dataset.generate import WHO, skeleton

#: (privileged: no copy outside the cloud, other: a copy exists), in authoring order.
CANDIDATES: list[tuple[str, str]] = [
    # A negation on the privileged side (the album has no other copy).
    ("Copied nowhere else is {who}", "Copied somewhere else is {who}"),
    ("Offline duplicates number zero for {who}", "Offline duplicates number two for {who}"),
    ("Data rescue would fail for {who}", "Data rescue would succeed for {who}"),
    ("Unmirrored on any disk is {who}", "Mirrored on a disk is {who}"),
    ("Protected by no archive is {who}", "Protected by an archive is {who}"),
    ("Never downloaded was {who}", "Downloaded beforehand was {who}"),
    ("Unsaved anywhere offline is {who}", "Saved somewhere offline is {who}"),
    ("Unrecoverable after loss is {who}", "Recoverable after loss is {who}"),
    ("Untouched by every backup is {who}", "Covered by every backup is {who}"),
    ("Unarchived to date is {who}", "Archived to date is {who}"),
    ("Lacking any duplicate is {who}", "Having a duplicate is {who}"),
    ("Exported nowhere yet was {who}", "Exported elsewhere already was {who}"),
    ("Unduplicated anywhere is {who}", "Duplicated elsewhere is {who}"),
    ("Retrievable by no other means is {who}", "Retrievable by some other means is {who}"),
    ("Second copies exist for none of {who}", "Second copies exist for all of {who}"),
    ("Archived copies number zero for {who}", "Archived copies number three for {who}"),
    ("Irreplaceable from other sources is {who}", "Replaceable from other sources is {who}"),
    ("Elsewhere nothing duplicates {who}", "Elsewhere something duplicates {who}"),
    ("Saved by nothing but the provider is {who}", "Saved by more than the provider is {who}"),
    ("Backed up nowhere is {who}", "Backed up somewhere is {who}"),
    # Neither clause negated (R76 review: polarity must not decide the family).
    ("Lone original survives for {who}", "Spare duplicates survive for {who}"),
    ("Single copy status applies to {who}", "Double copy status applies to {who}"),
    ("Solitary in storage is {who}", "Duplicated in storage is {who}"),
    ("One instance survives of {who}", "Two instances survive of {who}"),
    ("Copies total one for {who}", "Copies total two for {who}"),
    ("Stored in a single place is {who}", "Stored in multiple places too is {who}"),
    ("Residing in one location is {who}", "Residing in two locations is {who}"),
    ("Existing as one copy is {who}", "Existing as two copies is {who}"),
    ("Existing online only is {who}", "Existing offline too is {who}"),
    # Both clauses negated.
    ("Without a duplicate anywhere is {who}", "Never without a duplicate is {who}"),
    ("Missing from every backup is {who}", "Missing from no backup is {who}"),
    ("Absent from all of the backups is {who}", "Absent from none of the backups is {who}"),
    ("Absent from every archive is {who}", "Absent from no archive is {who}"),
    # A negation on the other side (the album has a copy elsewhere).
    (
        "Restoring needs the online original for {who}",
        "Restoring needs no online original for {who}",
    ),
    (
        "Online version is truly the only one for {who}",
        "Online version is not the only one for {who}",
    ),
    ("Dependent on a single instance is {who}", "Dependent on no single instance is {who}"),
    (
        "Losing the hosted pictures loses everything for {who}",
        "Losing the hosted pictures loses nothing for {who}",
    ),
    (
        "Restoration depends on the provider for {who}",
        "Restoration depends on no provider for {who}",
    ),
    ("Closing the account forfeits all of {who}", "Closing the account forfeits none of {who}"),
    ("Always reliant on the provider is {who}", "Never reliant on the provider is {who}"),
    (
        "Server failure would cost every picture of {who}",
        "Server failure would cost no picture of {who}",
    ),
]

#: R76 review: these say the album is absent from ONE place, not that no copy exists
#: anywhere else, so the privileged clause does not settle the answer. Dropped from the
#: candidates of the first v8 search.
ONE_PLACE = [
    ("Missing from the backup drive is {who}", "Present on the backup drive is {who}"),
    ("Spare laptop stores nothing from {who}", "Spare laptop stores everything from {who}"),
    ("Excluded from the weekly snapshot is {who}", "Included in the weekly snapshot is {who}"),
    ("Family computer lacks the pictures of {who}", "Family computer holds the pictures of {who}"),
    ("Skipped by the archive job was {who}", "Saved by the archive job was {who}"),
    ("Left out last month was {who}", "Backed up last month was {who}"),
    ("Memory stick contains no images from {who}", "Memory stick contains all images from {who}"),
    (
        "Never received by the home server was {who}",
        "Received safely by the home server was {who}",
    ),
    ("Absent from the old tablet is {who}", "Stored on the old tablet is {who}"),
    ("Backup status reads incomplete for {who}", "Backup status reads complete for {who}"),
    ("Spare phone gallery shows none of {who}", "Spare phone gallery shows all of {who}"),
    ("Omitted from the nightly mirror was {who}", "Written to the nightly mirror was {who}"),
    ("Burned onto no disc was {who}", "Burned onto a disc was {who}"),
    ("Thumb drive copy never made for {who}", "Thumb drive copy already made for {who}"),
    ("Desktop folder holds none of {who}", "Desktop folder holds all of {who}"),
    ("Server replica absent for {who}", "Server replica present for {who}"),
    ("Hard disk carries no trace of {who}", "Hard disk carries every file of {who}"),
    ("Office workstation lacks a copy of {who}", "Office workstation keeps a copy of {who}"),
    ("Offsite vault received nothing from {who}", "Offsite vault received everything from {who}"),
    ("Restore points cover none of {who}", "Restore points cover all of {who}"),
    ("Network share holds no copy of {who}", "Network share holds a copy of {who}"),
]

#: Rejected before the search, with the reason. A careful human could read each one
#: backwards, or it leans on an idiom, or it states the conclusion instead of the fact.
EXCLUDED: dict[tuple[str, str], str] = {
    ("Sync failed overnight for {who}", "Sync finished overnight for {who}"): (
        "a sync could be the phone's sync to the cloud, so a failed one may leave the "
        "photos on the phone: readable backwards"
    ),
    ("Laptop sync never reached {who}", "Laptop sync fully reached {who}"): (
        "a sync again: which way it copies is not stated"
    ),
    ("Spare drive empty of {who}", "Spare drive full of {who}"): (
        "'full of' an album leans on an idiom and reads oddly with a city's name"
    ),
    ("Archived once is {who}", "Archived twice is {who}"): (
        "'archived once' can mean one copy elsewhere, which is the other label"
    ),
    ("Copies held number one for {who}", "Copies held number two for {who}"): (
        "'number one' is an idiom"
    ),
    ("Exposed to permanent loss is {who}", "Shielded from permanent loss is {who}"): (
        "states the conclusion, not whether a copy exists"
    ),
    ("Kept only on the phone is {who}", "Duplicated to the family computer is {who}"): (
        "a copy on the phone is a copy outside the cloud: readable backwards"
    ),
    ("Lone surviving copy belongs to {who}", "Spare duplicate copy belongs to {who}"): (
        "'belongs to' an album is unclear"
    ),
    ("One copy is simply all there is for {who}", "One copy is not all there is for {who}"): (
        "'all there is' leans on an idiom"
    ),
    ("Always short of a duplicate is {who}", "Never short of a duplicate is {who}"): (
        "'short of' leans on an idiom, and 'always short' reads oddly"
    ),
    (
        "Lose the provider and you lose all of {who}",
        "Lose the provider and you lose none of {who}",
    ): ("'you' is the marker in three other families, and the heuristic reads it"),
    ("Status light red beside {who}", "Status light green beside {who}"): (
        "a colour code means whatever the app says it means"
    ),
}

#: The token list the suite treats as stopwords (``TestFrameDisjointness.STOP``),
#: restated here so the script runs without the test package.
STOP = frozenset(
    "the a an of to for on at in is be and not yet it its you your still already up off "
    "out down over under by has have was will this are from due no".split()
)
HELD_OUT = (5, 6, 7)


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "s"):
        if word.endswith(suffix) and len(word) > 4:
            return word[: -len(suffix)]
    return word


def _content(clause: str) -> set[str]:
    text = " ".join(skeleton(clause)).lower()
    return {_stem(w) for w in re.findall(r"[a-z]+", text) if w not in STOP}


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
    assert not set(CANDIDATES) & (set(EXCLUDED) | set(ONE_PLACE))
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

    held_sets = [s for s in combinations(range(n), 3) if balanced(s) and disjoint(s)]
    dev_sets = [s for s in combinations(range(n), 5) if balanced(s) and disjoint(s)]

    def sums(ids):
        return [sum(cheap[i][k] for i in ids) for k in range(len(universe))]

    held_sums = {s: sums(s) for s in held_sets}
    ranked = []
    for d in dev_sets:
        dsum = sums(d)
        dev_alone = max(abs(x) for x in dsum) / 10  # exploit over 0.5 on dev alone
        for h in held_sets:
            if set(d) & set(h) or not disjoint(d + h):
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
    # each the share of frames on which "speak iff the deleted album's clause has more
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
        "one_place": len(ONE_PLACE),
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
