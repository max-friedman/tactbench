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

import hashlib
import re

from ..dataset.generate import FRAMES, LATER_FRAMES, WHO
from ..dataset.paraphrase import PARAPHRASE_FRAMES
from ..schema import Decision, Moment
from .base import Policy

# "Gate change: B12 to B31" / "moved from B12 to B31" / "gate B12 is now gate B31"
_GATE_CHANGE = re.compile(
    r"(?:gate change:|moved from|gate)\s+([A-Z]\d+)\s+(?:to|is now gate)\s+([A-Z]\d+)",
    re.I,
)
_GATE_LOCATION = re.compile(r"(?:seated|standing) at\s+([A-Z]\d+)", re.I)
# "Return window for the standing desk closes" / "left to return the road bike" /
# "The camera lens return period ends"
_RETURN_ITEM = re.compile(
    r"return window for the ([a-z ]+?) closes"
    r"|left to return the ([a-z ]+?)\."
    r"|the ([a-z ]+?) return period ends",
    re.I,
)

# "feeder: Biscuit left breakfast" / "Biscuit's bowl is still full" / "eaten by Biscuit since"
_SKIPPED_PET = re.compile(
    r"feeder: (\w+) left|(\w+)'s bowl is still full|eaten by (\w+) since", re.I
)

# "motion at the garage" / "movement at the garage"
_MOTION_ZONE = re.compile(r"(?:motion|movement) at the (\w+)", re.I)
_BOIL_DISTRICT = re.compile(r"boil-water notice (?:issued )?(?:for|covers) (\w+)", re.I)
# "street sweeping on Elm" / "sweepers clear Elm" / "crews scheduled for Elm"
_SWEPT_STREET = re.compile(r"(?:street sweeping on|sweepers clear|crews scheduled for) (\w+)", re.I)


#: The value that means *speak* when it occupies a frame's privileged role.
#: ``None`` means the marker is not a constant and must be read from the moment --
#: ``travel`` (the gate boarding moved away from), ``commerce`` (the item whose
#: return window closes) and ``pet_care`` (the pet that skipped its meal).
_MARKERS = {
    "childcare": "you",
    "deadline": "you",
    "quiet_hours": "you",
    "health": "your prescription",
    "finance": "checking",
    "commerce": None,
    "meeting_prep": "contract review",
    "driving": "your route",
    "travel": None,
    "pet_care": None,
    "home_security": None,
    "water_notice": None,
    "street_cleaning": None,
}


class SkylinePolicy(Policy):
    """Resolves each family's deciding relation from the signal text.

    Round 13 replaced nine hand-written string matchers with one resolver over the
    generator's own frame table. That is a deliberate honesty change as much as a
    maintenance one: ``_commerce`` matched the literal ``"the desk"`` and
    ``_meeting_prep`` matched ``"contract review"``, which *resolved nothing* --
    they worked only because those nouns never varied, and would have silently
    mislabelled a whole family the moment they did. A ceiling that is secretly a
    lookup overstates the headroom it is there to measure.

    The resolver reads the decider's two prose clauses, matches one against the
    frame's **privileged** template, and asks whether the family's marker occupies
    that template's filler slot. It imports ``FRAMES`` rather than restating the
    phrasings, because two private notions of the same thing is how Round 10's
    split leak survived nine rounds -- and building the matcher *from* the template
    means a new frame needs no resolver change.
    """

    name = "skyline"

    @staticmethod
    def _clauses(text: str) -> list[str]:
        """Split a decider into its clauses."""
        return [p.strip().rstrip(".").strip() for p in text.split(". ") if p.strip()]

    @staticmethod
    def _filler_in(clause: str, template: str) -> str | None:
        """The filler occupying ``template``'s slot in ``clause``, or None.

        Built from the template rather than hand-written per family, so adding a
        frame cannot leave the ceiling silently resolving nothing.
        """
        pattern = "^" + re.escape(template).replace(re.escape(WHO), "(.+?)") + "$"
        match = re.match(pattern, clause, re.IGNORECASE)
        return match.group(1).strip().lower() if match else None

    def _resolve(self, moment: Moment, text: str, low: str) -> bool:
        frames = list(FRAMES.get(moment.family) or LATER_FRAMES.get(moment.family) or [])
        if not frames:
            return False
        # The reworded slice (`v2para`, R42) states the same relation in one new frame
        # per family; the ceiling must read it too, or the slice is unshown to be
        # solvable. Before R62 the skyline never spoke there (ICS = silence).
        if moment.family in PARAPHRASE_FRAMES:
            frames.append(PARAPHRASE_FRAMES[moment.family])
        marker = _MARKERS.get(moment.family)
        if marker is None:
            # The marker is not a constant -- read it out of the body, which is
            # what "resolving the relation" actually means. travel: the gate
            # boarding moved AWAY from. commerce: the item whose return window is
            # closing. Both were literal string matches until Round 13, which is
            # to say the ceiling was a lookup for those two families.
            if moment.family == "travel":
                change = _GATE_CHANGE.search(text)
                if not change:
                    return False
                marker = change.group(1)
            elif moment.family == "home_security":
                zone = _MOTION_ZONE.search(text)
                if not zone:
                    return False
                marker = zone.group(1)
            elif moment.family == "water_notice":
                district = _BOIL_DISTRICT.search(text)
                if not district:
                    return False
                marker = district.group(1)
            elif moment.family == "street_cleaning":
                street = _SWEPT_STREET.search(text)
                if not street:
                    return False
                marker = street.group(1)
            elif moment.family == "pet_care":
                skipped = _SKIPPED_PET.search(text)
                if not skipped:
                    return False
                marker = next(g for g in skipped.groups() if g)
            else:
                item = _RETURN_ITEM.search(low)
                if not item:
                    return False
                phrase = next(g for g in item.groups() if g)
                marker = "the " + phrase.split()[-1]
        marker = marker.lower()

        for clause in self._clauses(low):
            for privileged_template, _ in frames:
                value = self._filler_in(clause, privileged_template)
                if value is None:
                    continue
                # Exact, or a whole-word prefix. A bare startswith() made
                # "a21".startswith("a2") true, so a travel pair drawing gates A2
                # and A21 had its near-miss resolved as speak -- the ceiling
                # mislabelling a family. It fires on 1.1% of travel pairs and not
                # at all on the shipped seed, which is exactly the kind of defect
                # a fixed-seed self-consistency test at 5 pairs cannot see.
                return value == marker or value.startswith(marker + " ")
        return False

    def decide(self, moment: Moment) -> Decision:
        text = " ".join(s.content for s in moment.signals)
        low = text.lower()
        surface = self._resolve(moment, text, low)
        intent_by_family = {
            "travel": "gate_change_alert",
            "deadline": "incident_page",
            "commerce": "return_window_reminder",
            "meeting_prep": "meeting_prep",
            "driving": "reroute_alert",
            "quiet_hours": "family_emergency",
            "health": "refill_reminder",
            "childcare": "pickup_conflict",
            "finance": "payment_shortfall",
            "home_security": "intrusion_alert",
            "water_notice": "boil_water_alert",
            "street_cleaning": "move_car_alert",
        }
        return Decision(
            moment_id=moment.id,
            surface=surface,
            confidence=0.95 if surface else 0.9,
            intent=intent_by_family.get(moment.family) if surface else None,
            rationale="skyline: resolved the deciding relation directly",
        )


class PartialSkylinePolicy(Policy):
    """A policy with a *dialled* amount of comprehension. Diagnostic, not a baseline.

    Resolves the deciding relation on a deterministic fraction ``p`` of moments
    and coin-flips on the rest, interpolating between ``random@0.5`` (p=0) and
    the skyline (p=1).

    It exists to test the **metric**, not a system. Six rounds of leaderboards
    showed every real policy at chance precision and the skyline at 1.000, with
    nothing in between -- so ICS had been shown to separate no comprehension from
    perfect comprehension, and had never been shown to *rank the middle*, which is
    where every real system lands. A metric that is flat across that range cannot
    tell a mediocre assistant from a good one, however clean its endpoints look.

    Two properties make the sweep interpretable, and **both** are needed:

    1. The comprehending set is chosen by hashing the moment id, so it is
       **nested** -- raising ``p`` only ever adds moments.
    2. The guess for a non-comprehended moment is *also* hashed from the moment
       id, so it is **fixed independently of ``p``**.

    Property 2 was missing in the original implementation, which drew guesses from
    a sequential RNG. That made *which* moments consumed randomness depend on
    ``p``, so raising ``p`` reshuffled every remaining guess rather than only
    converting guesses into correct answers. Monotonicity then held or failed by
    luck: it looked clean on one dataset and reversed on another (round 9 caught
    p=0.4 scoring 112.0 and p=0.6 scoring 120.0).

    With both properties, monotonicity is **structural** rather than statistical:
    raising ``p`` strictly converts coin-flips into correct answers and leaves
    every other decision untouched, so cost can only fall or stay level.
    """

    def __init__(self, p: float, seed: int = 0, draw: int = 0):
        if not 0.0 <= p <= 1.0:
            raise ValueError("p is a comprehension fraction and must be in [0, 1]")
        self.p = p
        #: Selects the coin flips on non-comprehended moments.
        self.seed = seed
        #: Selects *which* moments a given ``p`` comprehends. Separate from ``seed``
        #: since Round 27's review: one knob moving both blamed guess noise on the
        #: comprehended set.
        self.draw = draw
        self.name = f"partial@{p:.1f}"
        self._skyline = SkylinePolicy()

    def comprehends(self, moment_id: str) -> bool:
        # Divided by 256, not 255: at p=1.0 a byte of exactly 255 would give 1.0,
        # which is not < 1.0, so one moment in ~256 would never be comprehended and
        # p=1.0 would not reproduce the skyline. Passes on small samples, fails on
        # large ones.
        #
        # ``draw`` selects which moments a given ``p`` comprehends. Draw 0 hashes the
        # bare id, so the shipped sweep is unchanged; any other draw is a different
        # nested set. Round 26 showed one draw is not a constant: changing the id
        # redrew this set *and* ``_guess``'s coin flips, and break-even moved 0.29 ->
        # 0.23. Round 27 separates the two sources and measures each.
        # Nesting in ``p`` holds within every draw.
        key = moment_id if self.draw == 0 else f"draw{self.draw}:{moment_id}"
        return hashlib.sha256(key.encode()).digest()[2] / 256.0 < self.p

    def _guess(self, moment_id: str) -> bool:
        """Fixed per moment and independent of ``p`` -- see property 2 above."""
        digest = hashlib.sha256(f"{self.seed}:{moment_id}".encode()).digest()
        return digest[3] % 2 == 0

    def decide(self, moment: Moment) -> Decision:
        if self.comprehends(moment.id):
            return self._skyline.decide(moment)
        surface = self._guess(moment.id)
        return Decision(
            moment_id=moment.id,
            surface=surface,
            confidence=0.5,
            intent="alert" if surface else None,
            rationale="guessed",
        )
