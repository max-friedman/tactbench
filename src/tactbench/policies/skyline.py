"""The skyline: what perfect comprehension of these moments would score.

Why this exists
---------------
Once the lexical shortcuts were removed from the dataset, every reference
baseline -- including the hand-written heuristic -- scored *worse than silence*.
That raises a fair objection: maybe the benchmark is degenerate. If no policy can
ever beat saying nothing, then "beat silence" is an impossible bar and the whole
exercise measures nothing.

This policy answers that objection. It reads the same text every other policy
sees, never touches a gold label, and resolves the actual semantic relation each
moment turns on: which gate you are standing at versus which gate boarding moved
to; whether the page names you as primary or as backup; which of two boxes is
still sealed. It scores near-perfectly, which proves the task is solvable and
that the headroom between silence and perfect is real.

What it is NOT
--------------
**This is not a general policy and must never be presented as a baseline.** It is
a template parser tuned to this generator. Point it at moments phrased even
slightly differently and it collapses. Its only job is to mark the ceiling, so
that a system under test can be read as a fraction of achievable performance
rather than against an unknown maximum.

Treat a submitted policy that looks like this one as overfitting, not progress.
"""

from __future__ import annotations

import re

from ..schema import Decision, Moment
from .base import Policy

# "Gate change: B12 to B31" / "moved from B12 to B31" / "gate B12 is now gate B31"
_GATE_CHANGE = re.compile(
    r"(?:gate change:|moved from|gate)\s+([A-Z]\d+)\s+(?:to|is now gate)\s+([A-Z]\d+)",
    re.I,
)
_GATE_LOCATION = re.compile(r"(?:seated|standing) at\s+([A-Z]\d+)", re.I)


class SkylinePolicy(Policy):
    """Resolves each family's deciding relation from the signal text."""

    name = "skyline"

    def decide(self, moment: Moment) -> Decision:
        text = " ".join(s.content for s in moment.signals)
        low = text.lower()
        fn = getattr(self, f"_{moment.family}", None)
        surface = bool(fn(text, low)) if fn else False
        intent_by_family = {
            "travel": "gate_change_alert",
            "deadline": "incident_page",
            "commerce": "return_window_reminder",
            "meeting_prep": "meeting_prep",
            "driving": "reroute_alert",
            "quiet_hours": "family_emergency",
        }
        return Decision(
            moment_id=moment.id,
            surface=surface,
            confidence=0.95 if surface else 0.9,
            intent=intent_by_family.get(moment.family) if surface else None,
            rationale="skyline: resolved the deciding relation directly",
        )

    def _travel(self, text: str, low: str) -> bool:
        """Speak only if the user is standing at the gate boarding moved *away* from."""
        change = _GATE_CHANGE.search(text)
        where = _GATE_LOCATION.search(text)
        if not change or not where:
            return False
        old_gate = change.group(1).upper()
        return where.group(1).upper() == old_gate

    def _deadline(self, text: str, low: str) -> bool:
        """Speak only if the page names the user as primary, not as backup."""
        m = re.search(r"primary[:\s]+\(?([a-z ]+?)[,.)]", low)
        return bool(m and "you" in m.group(1))

    def _commerce(self, text: str, low: str) -> bool:
        """Speak only if the item whose return window is closing is still sealed."""
        if "still boxed:" in low:
            return low.split("still boxed:")[1].split(".")[0].strip().startswith("the desk")
        return bool(re.search(r"the desk is unopened", low))

    def _meeting_prep(self, text: str, low: str) -> bool:
        """Speak only if the meeting the unread document concerns is still ahead."""
        return bool(re.search(r"contract review (?:begins in|starts in)", low))

    def _driving(self, text: str, low: str) -> bool:
        """Speak only if the congestion is on the route the user is actually taking."""
        return bool(
            re.search(r"your route is backed up", low)
            or re.search(r"congestion is on your route", low)
        )

    def _quiet_hours(self, text: str, low: str) -> bool:
        """Speak only if the news is an admission rather than a discharge."""
        return "admitt" in low
