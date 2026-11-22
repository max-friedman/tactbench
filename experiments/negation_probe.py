"""Does the *polarity* of a decider clause give the label away? R76 review.

The R76 review of v8's first `photo_backup` frames found that every privileged clause
carried a negation (*nowhere*, *zero*, *no*, *lacks*, *absent*, *excluded*, ...) and no
other clause did. A policy legal under rule 1 -- a generic lexicon of negation words, a
generic lexicon of deletion words, and no phrase from the generator -- then read the
family 100% on dev and 24 of 24 on held-out test. The family had reduced to polarity, so
the held-out frames tested nothing beyond the dev cue.

Two readings:

* :class:`NegationPolicy`, the reviewer's policy (one family; the heuristic elsewhere).
  For ``photo_backup`` it finds the album named in a body clause with a deletion word;
  for ``dinner_booking`` (v9, R80) the restaurant named in a body clause with a word for
  today. It speaks iff that name's decider clause has a negation word. Everything it
  reads is a generic English lexicon or capitalisation.
* :func:`frame_polarity`, for every family: per frame, whether the clause naming the
  marker is negated and the other is not (the rule is right on that frame), the reverse
  (wrong), or neither (a tie). The marker is located as the other clause probes locate
  it (``letter_bag_probe.clause_rows``), so this bounds what any policy that can find the
  marker's clause gets from polarity alone.

``tests/test_dataset_v8.py`` and ``tests/test_dataset_v9.py`` gate each version's new
family: right and wrong frames are equal on dev and on held-out frames separately, so
the rule reads exactly 50% on both.

    uv run python experiments/negation_probe.py
"""

from __future__ import annotations

import re

from letter_bag_probe import FAMILIES, LATEST

from tactbench.dataset.loader import load
from tactbench.policies.base import Policy, ask
from tactbench.policies.builtin import HeuristicPolicy
from tactbench.schema import Decision, Moment

#: Generic English negation and absence words, written without the generator open.
#: Wider than the reviewer's twelve: the gate should hold against the broader list an
#: adversary would try next.
NEGATION = frozenset(
    "no not never none nothing nowhere nobody neither nor zero without absent missing "
    "lack lacks lacking lacked cannot fail fails failed excluded omitted skipped".split()
)
#: Negating prefixes, on words long enough not to be the bare prefix (until, under are
#: five letters; "unless" counts, which is right).
PREFIXES = ("un", "non", "irr")
#: Generic deletion words, for locating the album the body says is going.
DELETION = frozenset("deleted removed erased deleting lost wiped".split())
#: Generic words for today, for locating the restaurant the body says is tonight's (R80).
TODAY = frozenset("tonight today tonights now".split())
#: The body lexicon that locates each family's marker, for the families the policy reads.
LOCATORS = {"photo_backup": DELETION, "dinner_booking": TODAY}


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+", text)


def negated(clause: str) -> bool:
    return any(
        w.lower() in NEGATION or (len(w) > 5 and w.lower().startswith(PREFIXES))
        for w in _words(clause)
    )


def _names(clause: str) -> set[str]:
    return {w for w in _words(clause)[1:] if w[0].isupper()}


class NegationPolicy(Policy):
    """The reviewer's rule-1-legal policy for one family (``photo_backup`` by default);
    the heuristic elsewhere."""

    name = "negation"

    def __init__(self, family: str = "photo_backup") -> None:
        self._heuristic = HeuristicPolicy()
        self._family = family
        self._locator = LOCATORS[family]

    def decide(self, moment: Moment) -> Decision:
        if moment.family != self._family:
            return ask(self._heuristic, moment)
        doomed: set[str] = set()
        for clause in re.split(r"[.,;:—]", moment.signals[0].content):
            if any(w.lower() in self._locator for w in _words(clause)):
                doomed |= _names(clause)
        flagged: set[str] = set()
        for signal in moment.signals[1:]:
            for clause in signal.content.split("."):
                if negated(clause):
                    flagged |= _names(clause)
        return Decision(moment_id=moment.id, surface=bool(doomed & flagged))


def policy_accuracy(items, family: str = "photo_backup") -> float:
    chosen = [i for i in items if i.moment.family == family]
    policy = NegationPolicy(family)
    return sum(ask(policy, i.moment).surface == i.label.should_surface for i in chosen) / len(
        chosen
    )


def frame_polarity(family: str, version: str) -> dict[str, dict[str, int] | float]:
    """Per split: frames where "speak iff the marker's clause alone is negated" is right,
    wrong, or tied; and its item accuracy (ties a half)."""
    from letter_bag_probe import clause_rows

    out: dict[str, dict[str, int] | float] = {}
    for split in ("dev", "test"):
        rows = clause_rows(load(version, split), family)
        frames: dict[str, int] = {}
        score = 0.0
        for key, mine, other, y in rows:
            lean = negated(mine) - negated(other)
            if y:  # the marker's clause is the privileged one on a positive
                frames[key] = lean
            score += 0.5 if lean == 0 else float((lean > 0) == y)
        out[split] = {
            "right": sum(v > 0 for v in frames.values()),
            "wrong": sum(v < 0 for v in frames.values()),
            "tie": sum(v == 0 for v in frames.values()),
        }
        out[f"{split}_accuracy"] = score / len(rows)
    return out


def main() -> None:
    from tactbench.runner import evaluate

    for family in LOCATORS:
        version = FAMILIES[family][0]
        for split in ("dev", "test"):
            items = load(version, split)
            heuristic = evaluate(HeuristicPolicy(), items).ics
            grafted = evaluate(NegationPolicy(family), items).ics
            print(
                f"{version}/{split}: negation policy on {family} "
                f"{policy_accuracy(items, family):.1%}; ICS heuristic {heuristic:.1f}, "
                f"heuristic + negation {grafted:.1f}"
            )
    print("frame polarity (right/wrong/tie frames; accuracy), every version carrying it:")
    for family, (first, _) in FAMILIES.items():
        cells = []
        for v in range(int(first[1:]), LATEST + 1):
            r = frame_polarity(family, f"v{v}")
            d, t = r["dev"], r["test"]
            assert isinstance(d, dict) and isinstance(t, dict)
            cells.append(
                f"v{v} dev {d['right']}/{d['wrong']}/{d['tie']} {r['dev_accuracy']:.0%}"
                f" test {t['right']}/{t['wrong']}/{t['tie']} {r['test_accuracy']:.0%}"
            )
        print(f"  {family:16} " + " | ".join(cells))


if __name__ == "__main__":
    main()
