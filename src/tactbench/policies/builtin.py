"""Reference policies.

These exist to establish the floor and the ceiling. The two that matter most are
``never`` -- the silence baseline every real system must beat -- and ``heuristic``,
a deliberately simple rule set. If a large model cannot beat a few dozen lines of
if-statements on interruption cost, that is the headline result, not a bug.

A note on how ``heuristic`` is allowed to work
----------------------------------------------
It would be trivial, and worthless, to write a heuristic that matches phrases
copied out of the dataset generator. Any score it earned would measure nothing
but the fact that one author wrote both files.

So the rules below are restricted to two kinds of input:

* **Structure** -- what the user is doing, whether DND is set, the local hour, how
  long since they touched a device, which sources fired, how stale each signal is,
  and signal metadata such as whether a contact is starred.
* **Generic lexicons** -- ordinary English words for danger and for
  resolution, of the kind you would write before ever seeing this dataset.

No phrase here is lifted from ``dataset/generate.py``. That restriction is the
reason the heuristic's score means something, and it is enforced by a test.
"""

from __future__ import annotations

import random

from ..schema import PROTECTED_ACTIVITIES, Activity, Decision, Moment, Source
from .base import Policy


class AlwaysPolicy(Policy):
    """Speaks at every moment. Upper bound on recall, worst case on cost."""

    name = "always"

    def decide(self, moment: Moment) -> Decision:
        return Decision(
            moment_id=moment.id, surface=True, confidence=1.0, intent="alert"
        )


class NeverPolicy(Policy):
    """Says nothing, ever. The bar. A proactive feature that scores worse than
    this one is a feature that should not ship."""

    name = "never"

    def decide(self, moment: Moment) -> Decision:
        return Decision(moment_id=moment.id, surface=False, confidence=1.0)


class RandomPolicy(Policy):
    """Coin flip at rate ``p``. Deterministic given the seed."""

    name = "random"

    def __init__(self, p: float = 0.5, seed: int = 0):
        self.p = p
        self._rng = random.Random(seed)
        self.name = f"random@{p}"

    def decide(self, moment: Moment) -> Decision:
        surface = self._rng.random() < self.p
        return Decision(
            moment_id=moment.id,
            surface=surface,
            confidence=self.p if surface else 1 - self.p,
            intent="alert" if surface else None,
        )


#: Ordinary English words for "someone could be harmed or a real loss is at
#: stake". Generic vocabulary, not dataset phrasing.
SEVERITY_WORDS = frozenset(
    {
        "emergency",
        "hospital",
        "ambulance",
        "surgery",
        "accident",
        "injured",
        "stable",
        "urgent",
        "incident",
        "outage",
        "failed",
        "failure",
        "breach",
        "evacuate",
    }
)

#: Ordinary English words for "this is finished, or someone else has it".
RESOLUTION_WORDS = frozenset(
    {
        "already",
        "resolved",
        "handled",
        "confirmed",
        "clean",
        "done",
        "fixed",
        "clear",
        "seated",
        "updated",
        "ahead",
    }
)


def _words(moment: Moment) -> set[str]:
    out: set[str] = set()
    for s in moment.signals:
        out.update(w.strip(".,;:'\"!?()") for w in s.content.lower().split())
    return out


def _is_personal(moment: Moment) -> bool:
    """Does any signal come from a person the user has marked as important?"""
    return any(
        s.meta.get("contact") == "family" or s.meta.get("priority") == "starred"
        for s in moment.signals
    )


def _addressed_to_user(moment: Moment) -> bool:
    """Crude second-person check: is the user the subject, or a bystander?

    Real systems resolve this from identity, not grammar. This stands in for that
    capability without reaching for dataset-specific phrasing.
    """
    text = " ".join(s.content.lower() for s in moment.signals)
    return " you " in f" {text} " or text.startswith("you ") or " your " in f" {text} "


class HeuristicPolicy(Policy):
    """Hand-written rules encoding the obvious product instincts.

    Four ideas, in order of how much work they do:

    1. Evidence that the thing is finished, or was never the user's, vetoes
       everything. Speaking after the fact only tells someone they failed.
    2. Protected states and explicit DND raise the bar sharply rather than
       blocking outright -- a family emergency should still get through.
    3. Expensive moments (meeting, deep work) require real severity.
    4. Cheap moments still require that something be at stake, and that the user
       be the one it is at stake for.
    """

    name = "heuristic"

    def decide(self, moment: Moment) -> Decision:
        words = _words(moment)
        state = moment.user_state

        severe = bool(words & SEVERITY_WORDS)
        resolved = bool(words & RESOLUTION_WORDS)
        personal = _is_personal(moment)
        mine = _addressed_to_user(moment)

        # A deadline the user can still act on is the main non-severe reason to
        # speak. Detected structurally: a calendar or location signal fresh
        # enough that the situation has not already moved on.
        actionable_window = any(
            s.source in (Source.CALENDAR, Source.LOCATION, Source.APP_EVENT)
            and s.age_s <= 600
            for s in moment.signals
        )

        if resolved and not severe:
            return Decision(
                moment_id=moment.id,
                surface=False,
                confidence=0.8,
                rationale="signals read as already handled or not the user's to act on",
            )

        if state.activity in PROTECTED_ACTIVITIES or state.dnd:
            surface = severe and (personal or mine)
            return Decision(
                moment_id=moment.id,
                surface=surface,
                confidence=0.75,
                intent="alert" if surface else None,
                rationale="protected state; only severe items concerning the user pass",
            )

        if state.activity in (Activity.MEETING, Activity.FOCUSED_WORK):
            surface = severe and mine
            return Decision(
                moment_id=moment.id,
                surface=surface,
                confidence=0.7,
                intent="alert" if surface else None,
                rationale="expensive moment; requires severity and ownership",
            )

        surface = (severe or actionable_window) and mine
        return Decision(
            moment_id=moment.id,
            surface=surface,
            confidence=0.6,
            intent="alert" if surface else None,
            rationale="cheap moment; speak when something is at stake for this user",
        )


def registry() -> dict[str, Policy]:
    """Name -> policy, for the CLI."""
    return {
        p.name: p
        for p in (
            NeverPolicy(),
            AlwaysPolicy(),
            RandomPolicy(0.5, seed=7),
            HeuristicPolicy(),
        )
    }
