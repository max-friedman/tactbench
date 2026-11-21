"""A paraphrased slice of dataset v2. Round 42.

CLAUDE.md priority 3, restated in Round 41: paraphrase expansion cannot close a
shortcut while the templates are public, but it can measure something -- whether a
model's decision about a moment survives the same facts in different words.

Each family gets one frame with a new sentence shape. The first template keeps the
family's *privileged* role (the one whose filler decides "speak"), the second its
counterpart, exactly as in ``generate.FRAMES``. :func:`reword` re-renders only the
decider, with the same fillers in the same clause order, so the body, user state,
label and id are unchanged and each reworded moment pairs with its original by id.
"""

from __future__ import annotations

import re

from ..schema import Item, frame_of
from .generate import FRAMES, WHO
from .loader import load

#: (privileged, counterpart) per family, each meaning what frame 0 means.
PARAPHRASE_FRAMES: dict[str, tuple[str, str]] = {
    "childcare": ("Collecting the kids falls to {who}", "Catching the flight falls to {who}"),
    "commerce": ("Unopened in its carton sits {who}", "Assembled in the lounge sits {who}"),
    "deadline": ("First on the pager rotation is {who}", "Second on the pager rotation is {who}"),
    "driving": ("Traffic stands still along {who}", "Traffic moves freely along {who}"),
    "finance": ("Lacking funds for the bill is {who}", "Holding funds for the bill is {who}"),
    "health": ("Ready at the pharmacy is {who}", "Picked up last week is {who}"),
    "meeting_prep": ("Scheduled to start soon is {who}", "Underway for some minutes is {who}"),
    "quiet_hours": ("Close enough to drive is {who}", "Hours of driving away is {who}"),
    "travel": ("Seated in person at {who}", "Boarding on paper at {who}"),
}

#: The frame of v2's dev split that is reworded: every pair in it, 36 pairs.
FRAME = 0


def _filler(clause: str, template: str) -> str | None:
    """The filler in ``template``'s slot, case preserved."""
    pattern = "^" + re.escape(template).replace(re.escape(WHO), "(.+?)") + "$"
    match = re.match(pattern, clause.strip().rstrip("."))
    return match.group(1) if match else None


def reword(item: Item) -> Item:
    """The same moment with its decider in the family's paraphrase frame."""
    family = item.moment.family
    if family not in PARAPHRASE_FRAMES:
        raise ValueError(f"no paraphrase frame for family {family!r} (v2's nine only)")
    privileged, other = FRAMES[family][frame_of(item.moment) % len(FRAMES[family])]
    new_privileged, new_other = PARAPHRASE_FRAMES[family]
    decider = item.moment.signals[-1]
    first, second = decider.content.split(". ", 1)
    clauses = []
    for clause in (first, second):
        if (f := _filler(clause, privileged)) is not None:
            clauses.append(new_privileged.format(who=f) + ".")
        elif (f := _filler(clause, other)) is not None:
            clauses.append(new_other.format(who=f) + ".")
        else:
            raise ValueError(f"{item.moment.id}: cannot parse clause {clause!r}")
    signal = decider.model_copy(update={"content": " ".join(clauses)})
    moment = item.moment.model_copy(
        update={"signals": [*item.moment.signals[:-1], signal]}, deep=True
    )
    return item.model_copy(update={"moment": moment})


def build() -> list[Item]:
    """Every v2 dev pair in :data:`FRAME`, reworded. Deterministic."""
    return [reword(i) for i in load("v2", "dev") if frame_of(i.moment) == FRAME]
