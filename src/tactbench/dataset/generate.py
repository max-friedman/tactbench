"""Synthetic moment generation for TactBench.

Design note -- why moments come in pairs, and why that wasn't enough
-------------------------------------------------------------------
A benchmark of "should the assistant speak?" is trivially gameable if the items
that warrant speech look different on the surface from the ones that don't. Any
policy could then match keywords ("delayed", "expires", "overdue") and score well
without having judged anything.

v1 addressed this with matched pairs: every scenario emits a positive and a
near-miss from the same family. **That was not sufficient.** The two sides were
written as different sentences, so a bag-of-words classifier that never saw user
state separated them at 93.5% (see ``tactbench audit``). Tokens like "hallway"
and "inflight" appeared on exactly one side and gave the answer away.

v2 fixes the construction rather than the claim. Two rules:

1. **Pairs share a body.** The context signals are byte-identical across the two
   sides. Only one *decider* signal differs.
2. **The decider is a role permutation wherever the scenario allows it.** Instead
   of rewriting the sentence, the same nouns swap places -- primary/secondary
   on-call, which gate you're standing at, which box is unopened. The two sides
   then carry nearly the same token multiset, so unigram statistics cannot separate
   them and only the structure can.

Where severity is genuinely lexical (a medical emergency is not a permutation of
a routine check-in), permutation is impossible and some residual leakage is
unavoidable. That residue is measured per family by ``tactbench audit`` and
reported honestly rather than claimed away.

Labels remain *by construction*: we know the answer because we built the item
around it. That limitation is documented in docs/DATASET.md.
"""

from __future__ import annotations

import random

from ..schema import Activity, GoldLabel, Item, Moment, Signal, Source, UserState

# --------------------------------------------------------------------------- #
# Entity pools -- Round 12.
#
# Four families baked a single counterpart name into their decider templates
# ("Priya Raman", "Sam", "Dana", "the desk"), so however many pairs the generator
# emitted, the family only ever produced FOUR distinct decider sentences. Round 11
# measured the cost: 91.2% of held-out decider sentences appeared byte-identically
# in the published dev split, and a dict lookup with no model scored +90.9 versus
# silence.
#
# The counterpart is drawn per pair instead. Both sides of a pair still use the
# SAME entity -- the permutation is which role it plays, so varying it cannot
# leak. Pools are deliberately larger than the pair count so repeats are rare.
# --------------------------------------------------------------------------- #

COLLEAGUES = [
    "Priya Raman",
    "Marco Silva",
    "Dana Whitfield",
    "Tom Okafor",
    "Lena Brandt",
    "Sofia Duarte",
    "Aziz Rahman",
    "Grace Lindqvist",
    "Hugo Bellini",
    "Nina Torres",
    "Omar Haddad",
    "Ruth Castellanos",
    "Ivan Petrov",
    "Maya Chandra",
    "Felix Nyondo",
]

HOUSEHOLD = [
    "Dana",
    "Chris",
    "Sam",
    "Alex",
    "Jordan",
    "Robin",
    "Casey",
    "Morgan",
    "Riley",
    "Quinn",
    "Avery",
    "Reese",
    "Devon",
    "Harper",
    "Emerson",
]

PHARMACY_OTHERS = [
    "Sam",
    "Nadia",
    "Theo",
    "Ines",
    "Bruno",
    "Camille",
    "Otto",
    "Priya",
    "Leo",
    "Mira",
    "Yusuf",
    "Elena",
    "Kai",
    "Rosa",
    "Dmitri",
]

# Stand-in nouns for the commerce decider. ONLY the stand-in varies: the returnable
# item stays "the desk", because the body names it and `SkylinePolicy._commerce`
# resolves the relation against that literal. Varying the returnable as well
# requires generalising that handler first -- see the R13 queue item. Kept as a
# flat list rather than tuples of (body form, decider form, stand-in): an earlier
# draft carried those extra columns unused, and a comment describing fields
# nothing reads is how a later contributor wires one in and silently breaks the
# ceiling.
RETURNABLE_STANDINS = [
    "replacement",
    "loaner",
    "spare",
    "substitute",
    "backup",
    "second",
    "alternate",
    "stand-in",
    "rental",
    "floor model",
]

# Counterpart meetings for the meeting_prep decider. ONLY the counterpart varies:
# "contract review" is what the body names and `SkylinePolicy._meeting_prep`
# resolves against. Same reasoning as RETURNABLE_STANDINS above.
COUNTERPART_MEETINGS = [
    "budget sync",
    "staffing review",
    "roadmap sync",
    "hiring sync",
    "planning sync",
    "design sync",
    "metrics sync",
    "retro sync",
    "forecast review",
    "onboarding sync",
]


def _mk(
    mid: str,
    family: str,
    signals: list[Signal],
    state: UserState,
    should: bool,
    value: int,
    intents: list[str],
    rationale: str,
    slices: list[str],
    window_s: int | None = None,
) -> Item:
    return Item(
        moment=Moment(id=mid, signals=signals, user_state=state, family=family, slices=slices),
        label=GoldLabel(
            moment_id=mid,
            should_surface=should,
            value=value,
            acceptable_intents=intents if should else [],
            window_s=window_s,
            rationale=rationale,
        ),
    )


class Scenario:
    """One scenario family, emitting a matched pair that shares a body.

    Subclasses build the shared context once and return the two decider variants,
    so the positive and near-miss cannot drift apart lexically by accident.
    """

    family: str = "generic"
    intent: str = "alert"
    positive_value: int = 2
    window_s: int | None = None
    positive_slices: list[str] = []
    near_slices: list[str] = []

    def state(self, rng: random.Random) -> UserState:
        raise NotImplementedError

    def body(self, rng: random.Random) -> list[Signal]:
        """Context signals identical across both sides of the pair."""
        raise NotImplementedError

    def deciders(self, rng: random.Random) -> tuple[Signal, Signal]:
        """(positive_decider, near_miss_decider). Permute roles, don't rewrite."""
        raise NotImplementedError

    def why(self) -> tuple[str, str]:
        raise NotImplementedError

    def pair(self, rng: random.Random, idx: int) -> tuple[Item, Item]:
        # One state *value* shared by both sides: if the user's activity differed
        # between a positive and its near-miss, the *state* would give the answer
        # away just as surely as the vocabulary did.
        state = self.state(rng)
        body = self.body(rng)
        pos_dec, near_dec = self.deciders(rng)
        pos_why, near_why = self.why()

        # Equal, not identical. The shared body must be byte-identical across the
        # pair -- that is the whole construction -- but handing both sides the same
        # mutable `Signal` objects makes the two halves silently coupled: editing
        # one item's text edits its partner's. Round 10 hit this writing a test
        # that appended a per-label tell to each item and got a dataset where both
        # sides carried both tells. Nothing in the shipped code mutates an item,
        # so it had never bitten; it is exactly the kind of latent aliasing that
        # surfaces the first time somebody augments or paraphrases in place.
        def body_for_side() -> list[Signal]:
            return [s.model_copy(deep=True) for s in body]

        positive = _mk(
            f"{self.family}-pos-{idx:04d}",
            self.family,
            [*body_for_side(), pos_dec],
            state,
            should=True,
            value=self.positive_value,
            intents=[self.intent],
            rationale=pos_why,
            slices=list(self.positive_slices),
            window_s=self.window_s,
        )
        near = _mk(
            f"{self.family}-near-{idx:04d}",
            self.family,
            [*body_for_side(), near_dec],
            state.model_copy(deep=True),
            should=False,
            value=0,
            intents=[],
            rationale=near_why,
            slices=["near_miss", *self.near_slices],
        )
        return positive, near


class TravelScenario(Scenario):
    """Gate change. The decider is which gate you are standing at -- both gate
    numbers appear on both sides, so the tokens cannot separate them."""

    family = "travel"
    intent = "gate_change_alert"
    positive_value = 3
    window_s = 600
    positive_slices = ["time_critical"]
    near_slices = ["already_handled"]

    def state(self, rng):
        return UserState(
            activity=Activity.COMMUTING,
            device="phone",
            last_interaction_s=rng.randint(30, 300),
            local_hour=rng.randint(7, 20),
        )

    def body(self, rng):
        self._a = rng.choice(["B12", "C4", "A21", "D7"])
        self._b = rng.choice(["B31", "C19", "A2", "D22"])
        mins = rng.choice([25, 30, 35, 40])
        phrasing = rng.choice(
            [
                f"Gate change: {self._a} to {self._b}. Boarding starts in {mins} minutes.",
                f"Your gate moved from {self._a} to {self._b}; boarding in {mins} minutes.",
                f"Departure update — gate {self._a} is now gate {self._b}, "
                f"boarding in {mins} minutes.",
            ]
        )
        return [
            Signal(source=Source.EMAIL, age_s=120, content=phrasing, meta={"sender": "airline"})
        ]

    def deciders(self, rng):
        a, b = self._a, self._b
        variants = [
            (
                f"Boarding pass on screen reads {b}; you are seated at {a}.",
                f"Boarding pass on screen reads {a}; you are seated at {b}.",
            ),
            (
                f"You are standing at {a}. The pass in your wallet still lists {b}.",
                f"You are standing at {b}. The pass in your wallet still lists {a}.",
            ),
        ]
        # Positive: you're at the OLD gate. Near-miss: you're at the NEW gate.
        # Same tokens, swapped positions.
        pos_text, near_text = variants[rng.randrange(len(variants))]
        return (
            Signal(source=Source.LOCATION, age_s=60, content=pos_text),
            Signal(source=Source.LOCATION, age_s=60, content=near_text),
        )

    def why(self):
        return (
            "The user is at the old gate with a stale pass. Missing this costs them the flight.",
            "The user is already at the new gate with the updated pass. Saying "
            "anything is pure noise.",
        )


class DeadlineScenario(Scenario):
    """Production incident. The decider is who holds the page -- primary and
    secondary swap, so both names appear on both sides."""

    family = "deadline"
    intent = "incident_page"
    positive_value = 3
    window_s = 300
    positive_slices = ["time_critical", "breaks_focus"]
    near_slices = ["not_yours", "breaks_focus"]

    def state(self, rng):
        return UserState(
            activity=Activity.FOCUSED_WORK,
            device="laptop",
            last_interaction_s=rng.randint(0, 20),
            local_hour=rng.randint(9, 17),
        )

    def body(self, rng):
        rel = rng.choice(["4.2", "5.0", "3.7", "6.1"])
        phrasing = rng.choice(
            [
                f"Deploy {rel} failed health checks and auto-rolled back.",
                f"Release {rel} rolled back automatically after failing health checks.",
                f"Health checks failed on {rel}; the deploy was rolled back.",
            ]
        )
        return [
            Signal(source=Source.APP_EVENT, age_s=90, content=phrasing),
            Signal(
                source=Source.SCREEN,
                age_s=5,
                content="Writing a design doc in a text editor.",
            ),
        ]

    def deciders(self, rng):
        who = rng.choice(COLLEAGUES)
        variants = [
            (
                f"On-call rotation — primary: you, secondary: {who}.",
                f"On-call rotation — primary: {who}, secondary: you.",
            ),
            (
                f"Paging the primary: you. Backup is {who}.",
                f"Paging the primary: {who}. Backup is you.",
            ),
        ]
        pos_text, near_text = variants[rng.randrange(len(variants))]
        return (
            Signal(source=Source.MESSAGE, age_s=60, content=pos_text),
            Signal(source=Source.MESSAGE, age_s=60, content=near_text),
        )

    def why(self):
        return (
            "The user holds the page for a live production incident and others are "
            "blocked. This clears the bar for breaking focus.",
            "Identical incident, but someone else holds the page. Breaking focus "
            "here is a pure loss.",
        )


class CommerceScenario(Scenario):
    """Return window. The decider is which item is still boxed -- the two objects
    swap roles, keeping the token multiset intact."""

    family = "commerce"
    intent = "return_window_reminder"
    positive_value = 2
    window_s = 3600
    positive_slices = ["low_stakes"]
    near_slices = ["already_handled", "low_stakes"]

    def state(self, rng):
        return UserState(
            activity=Activity.IDLE,
            device="phone",
            last_interaction_s=rng.randint(2, 60),
            local_hour=rng.randint(10, 21),
        )

    def body(self, rng):
        hrs = rng.choice([12, 14, 18, 20])
        phrasing = rng.choice(
            [
                f"Return window for the standing desk closes in {hrs} hours.",
                f"You have {hrs} hours left to return the standing desk.",
                f"The standing desk return period ends in {hrs} hours.",
            ]
        )
        return [Signal(source=Source.APP_EVENT, age_s=300, content=phrasing)]

    def deciders(self, rng):
        # The returnable item stays "the desk" -- the body names it, and the
        # relation the skyline resolves is body-item vs still-sealed-item. Only
        # the STAND-IN varies, which keeps the permutation exact (both sides carry
        # the same two nouns) while taking the family from 4 distinct decider
        # sentences to ~20. Round 12.
        alt = rng.choice(RETURNABLE_STANDINS)
        where = rng.choice(["the hallway", "the porch", "the entryway", "the garage"])
        room = rng.choice(["the office", "the study", "the spare room", "the den"])
        variants = [
            (
                f"The desk is unopened in {where}; the {alt} is already set up in {room}.",
                f"The {alt} is unopened in {where}; the desk is already set up in {room}.",
            ),
            (
                f"Still boxed: the desk. Already assembled: the {alt}.",
                f"Still boxed: the {alt}. Already assembled: the desk.",
            ),
        ]
        pos_text, near_text = variants[rng.randrange(len(variants))]
        return (
            Signal(source=Source.SENSOR, age_s=600, content=pos_text),
            Signal(source=Source.SENSOR, age_s=600, content=near_text),
        )

    def why(self):
        return (
            "The desk is still returnable and the user has switched to the "
            "replacement. The deadline is unrecoverable once passed.",
            "The desk is the one they kept and assembled; the return no longer "
            "applies to it. Nothing to act on.",
        )


class MeetingPrepScenario(Scenario):
    """Preparation cue. The decider is whether the meeting is ahead or behind --
    the same minute count appears on both sides."""

    family = "meeting_prep"
    intent = "meeting_prep"
    positive_value = 2
    window_s = 600
    positive_slices = ["lead_time"]
    near_slices = ["too_late", "lead_time"]

    def state(self, rng):
        return UserState(
            activity=Activity.IDLE,
            device="laptop",
            last_interaction_s=rng.randint(5, 90),
            local_hour=rng.randint(9, 16),
        )

    def body(self, rng):
        phrasing = rng.choice(
            [
                "Vendor sent a revised contract 90 minutes ago with changed payment "
                "terms. Unopened.",
                "An unopened revision of the vendor contract arrived 90 minutes ago; "
                "payment terms changed.",
            ]
        )
        return [Signal(source=Source.EMAIL, age_s=5400, content=phrasing)]

    def deciders(self, rng):
        m = rng.choice([6, 8, 9, 10, 11, 12, 14, 15, 17, 18, 20, 22])
        # "contract review" is the subject the body names and the skyline resolves
        # against; only the COUNTERPART meeting varies. Both sides still carry the
        # same two subjects, so the permutation is exact. Round 12.
        other = rng.choice(COUNTERPART_MEETINGS)
        # Two meetings, so "begins in" and "began ago" each appear on both sides and
        # only their subjects swap. Without the second meeting the tense alone gave
        # the answer away and this family probed at 100%.
        variants = [
            (
                f"Contract review begins in {m} minutes; the {other} began {m} minutes ago.",
                f"The {other} begins in {m} minutes; contract review began {m} minutes ago.",
            ),
            (
                f"Calendar: contract review starts in {m} minutes, {other} "
                f"started {m} minutes back.",
                f"Calendar: {other} starts in {m} minutes, contract review "
                f"started {m} minutes back.",
            ),
        ]
        pos_text, near_text = variants[rng.randrange(len(variants))]
        return (
            Signal(source=Source.CALENDAR, age_s=0, content=pos_text),
            Signal(source=Source.CALENDAR, age_s=0, content=near_text),
        )

    def why(self):
        return (
            "There is unread material that changes the meeting and enough time to "
            "read it. Lead time is the whole point.",
            "Same unread document, but the meeting is already underway. A prep cue "
            "after the fact only tells the user they failed.",
        )


class DrivingScenario(Scenario):
    """Safety-protected state. The decider is which route is congested -- current
    and alternate swap."""

    family = "driving"
    intent = "reroute_alert"
    positive_value = 3
    window_s = 120
    positive_slices = ["protected_state", "time_critical"]
    near_slices = ["protected_state"]

    def state(self, rng):
        return UserState(
            activity=Activity.DRIVING,
            device="phone",
            last_interaction_s=rng.randint(600, 3000),
            local_hour=rng.randint(7, 19),
        )

    def body(self, rng):
        h = rng.choice([2, 3])
        return [
            Signal(
                source=Source.CALENDAR,
                age_s=0,
                content=f"Flight departs in {h} hours.",
            )
        ]

    def deciders(self, rng):
        d = rng.choice([9, 12, 14, 17, 19, 22, 25, 28, 30, 33, 36, 40, 43, 47])
        variants = [
            (
                f"Your route is backed up {d} minutes; the alternate at the next exit is clear.",
                f"The alternate at the next exit is backed up {d} minutes; your route is clear.",
            ),
            (
                f"Congestion is on your route (+{d} min); the next exit avoids it.",
                f"Congestion is on the next exit (+{d} min); your route avoids it.",
            ),
        ]
        pos_text, near_text = variants[rng.randrange(len(variants))]
        return (
            Signal(source=Source.LOCATION, age_s=30, content=pos_text),
            Signal(source=Source.LOCATION, age_s=30, content=near_text),
        )

    def why(self):
        return (
            "Actionable only within a narrow window, and the cost of missing it is "
            "a missed flight.",
            "The user is already on the clear route. Nothing is wrong and nothing "
            "is actionable from the driver's seat.",
        )


class QuietHoursScenario(Scenario):
    """3am, asleep, DND on, a starred contact, and a real emergency.

    Round 1 declared this family irreducibly lexical -- a medical emergency is not
    a rearrangement of a routine check-in -- and exempted it from the per-family
    audit assertion. **That exemption was wrong, and round 9 measured its cost.**

    Because severity decided the label, two substrings (``admitt`` / ``discharg``)
    captured the family. And because it carries the highest false-positive cost in
    the benchmark (sleeping, DND-doubled), it drove **82% of the gap** between
    ``always`` and silence from 13% of the moments. A policy matching those two
    tokens and coin-flipping on the other eight families beat silence at +28.0,
    while the honest structural heuristic scored -22.9.

    The fix was to stop making severity the decider. The emergency now sits in the
    **shared body**, identical on both sides, and the judgment is whether the user
    can actually do anything -- which permutes cleanly:

        positive:  Mom is hours away, the user is the one nearby.
        near-miss: The user is hours away, Mom is the one nearby.

    Same tokens, swapped roles, opposite answers. Waking someone at 3am about a
    crisis they cannot reach for six hours is not help; waking the one person who
    can be there in fifteen minutes is. That is a harder and more honest judgment
    than spotting the word "admitted", and it is not lexical.
    """

    family = "quiet_hours"
    intent = "family_emergency"
    positive_value = 3
    window_s = 900
    positive_slices = ["quiet_hours", "dnd_override"]
    near_slices = ["quiet_hours", "dnd_override", "cannot_act"]

    def state(self, rng):
        return UserState(
            activity=Activity.SLEEPING,
            dnd=True,
            device="phone",
            last_interaction_s=rng.randint(7200, 20000),
            local_hour=rng.choice([2, 3, 4]),
        )

    def body(self, rng):
        n = rng.choice(["Third", "Fourth", "Second"])
        crisis = rng.choice(
            [
                "Mom: 'Dad is at the hospital, they are admitting him tonight.'",
                "Mom: 'They are admitting Dad - he is stable but staying in.'",
                "Mom: 'Dad is being admitted. Nothing is decided until morning.'",
            ]
        )
        return [
            Signal(
                source=Source.MESSAGE,
                age_s=60,
                content=f"{n} message from Mom in ten minutes.",
                meta={"contact": "family", "priority": "starred"},
            ),
            Signal(
                source=Source.MESSAGE,
                age_s=50,
                content=crisis,
                meta={"contact": "family", "priority": "starred"},
            ),
            Signal(source=Source.SENSOR, age_s=30, content="Phone face down, charging."),
        ]

    def deciders(self, rng):
        hrs = rng.choice([3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        variants = [
            (
                f"Mom: 'Right now I am {hrs} hours out; you are the one nearby.'",
                f"Mom: 'Right now you are {hrs} hours out; I am the one nearby.'",
            ),
            (
                f"Nearby: you. {hrs} hours away, still driving: Mom.",
                f"Nearby: Mom. {hrs} hours away, still driving: you.",
            ),
        ]
        pos_text, near_text = variants[rng.randrange(len(variants))]
        return (
            Signal(
                source=Source.MESSAGE,
                age_s=45,
                content=pos_text,
                meta={"contact": "family", "priority": "starred"},
            ),
            Signal(
                source=Source.MESSAGE,
                age_s=45,
                content=near_text,
                meta={"contact": "family", "priority": "starred"},
            ),
        )

    def why(self):
        return (
            "A real admission, and the user is the only person who can be there "
            "tonight. This is what DND exists to be overridden for.",
            "The same admission, but someone closer is already handling it and the "
            "user is hours away. Waking them at 3am buys nothing they can act on "
            "before morning.",
        )


class HealthScenario(Scenario):
    """Prescription pickup. Two people's refills trade which one is outstanding."""

    family = "health"
    intent = "refill_reminder"
    positive_value = 2
    window_s = 2400
    positive_slices = ["low_stakes"]
    near_slices = ["not_yours"]

    def state(self, rng):
        return UserState(
            activity=Activity.IDLE,
            device="phone",
            last_interaction_s=rng.randint(5, 120),
            local_hour=rng.randint(14, 18),
        )

    def body(self, rng):
        mins = rng.choice([35, 40, 50, 55])
        phrasing = rng.choice(
            [
                f"The pharmacy closes in {mins} minutes.",
                f"Pharmacy counter shuts in {mins} minutes.",
                f"{mins} minutes until the pharmacy closes.",
            ]
        )
        return [Signal(source=Source.NOTIFICATION, age_s=180, content=phrasing)]

    def deciders(self, rng):
        who = rng.choice(PHARMACY_OTHERS)
        variants = [
            (
                f"Your refill is waiting for pickup; {who}'s refill was collected yesterday.",
                f"{who}'s refill is waiting for pickup; your refill was collected yesterday.",
            ),
            (
                f"Still at the counter: your prescription. "
                f"Already picked up: {who}'s prescription.",
                f"Still at the counter: {who}'s prescription. "
                f"Already picked up: your prescription.",
            ),
        ]
        pos_text, near_text = variants[rng.randrange(len(variants))]
        return (
            Signal(source=Source.APP_EVENT, age_s=240, content=pos_text),
            Signal(source=Source.APP_EVENT, age_s=240, content=near_text),
        )

    def why(self):
        return (
            "The user's own prescription is still at the counter and the window "
            "closes soon. Acting is cheap and the moment is idle.",
            "The outstanding refill belongs to someone else and the user's was "
            "already collected. Nothing here is theirs to act on.",
        )


class ChildcareScenario(Scenario):
    """School pickup. Which parent is on the list, and which is away, swap."""

    family = "childcare"
    intent = "pickup_conflict"
    positive_value = 3
    window_s = 1800
    positive_slices = ["time_critical", "breaks_focus"]
    near_slices = ["not_yours", "breaks_focus"]

    def state(self, rng):
        return UserState(
            activity=Activity.FOCUSED_WORK,
            device="laptop",
            last_interaction_s=rng.randint(0, 30),
            local_hour=rng.randint(13, 15),
        )

    def body(self, rng):
        t = rng.choice(["3:15", "3:30", "2:45"])
        phrasing = rng.choice(
            [
                f"School pickup is at {t} today.",
                f"Pickup time today is {t}.",
                f"Today's pickup: {t}.",
            ]
        )
        return [Signal(source=Source.CALENDAR, age_s=0, content=phrasing)]

    def deciders(self, rng):
        who = rng.choice(HOUSEHOLD)
        variants = [
            (
                f"You are on the pickup list today; {who} is out of town.",
                f"{who} is on the pickup list today; you are out of town.",
            ),
            (
                f"Listed for pickup: you. Travelling today: {who}.",
                f"Listed for pickup: {who}. Travelling today: you.",
            ),
        ]
        pos_text, near_text = variants[rng.randrange(len(variants))]
        return (
            Signal(source=Source.MESSAGE, age_s=120, content=pos_text),
            Signal(source=Source.MESSAGE, age_s=120, content=near_text),
        )

    def why(self):
        return (
            "The user is the listed parent, the other is away, and a child is "
            "waiting. This clears the bar for breaking focus.",
            "The other parent is listed and present. Same logistics, none of it "
            "the user's to act on.",
        )


class FinanceScenario(Scenario):
    """Autopay shortfall. The two accounts trade which one is short."""

    family = "finance"
    intent = "payment_shortfall"
    positive_value = 3
    window_s = 3600
    positive_slices = ["time_critical"]
    near_slices = ["already_handled"]

    def state(self, rng):
        return UserState(
            activity=Activity.IDLE,
            device="phone",
            last_interaction_s=rng.randint(10, 200),
            local_hour=rng.randint(19, 22),
        )

    def body(self, rng):
        phrasing = rng.choice(
            [
                "Autopay for the credit card draws from checking tonight at 11pm.",
                "Tonight at 11pm, autopay pulls the card balance from checking.",
                "Card autopay hits checking at 11pm tonight.",
            ]
        )
        return [Signal(source=Source.APP_EVENT, age_s=600, content=phrasing)]

    def deciders(self, rng):
        amt = rng.choice([95, 120, 145, 180, 200, 215, 240, 265, 290, 310, 335, 360])
        variants = [
            (
                f"Checking is short ${amt}; savings covers the balance.",
                f"Savings is short ${amt}; checking covers the balance.",
            ),
            (
                f"Below the payment by ${amt}: checking. Above it: savings.",
                f"Below the payment by ${amt}: savings. Above it: checking.",
            ),
        ]
        pos_text, near_text = variants[rng.randrange(len(variants))]
        return (
            Signal(source=Source.APP_EVENT, age_s=300, content=pos_text),
            Signal(source=Source.APP_EVENT, age_s=300, content=near_text),
        )

    def why(self):
        return (
            "Autopay draws from checking and checking is short, so this overdrafts "
            "tonight unless the user moves money. Recoverable only before 11pm.",
            "The shortfall is in an account autopay does not touch; the account it "
            "draws from covers the payment. Nothing will go wrong.",
        )


SCENARIOS: list[Scenario] = [
    TravelScenario(),
    DeadlineScenario(),
    CommerceScenario(),
    QuietHoursScenario(),
    DrivingScenario(),
    MeetingPrepScenario(),
    HealthScenario(),
    ChildcareScenario(),
    FinanceScenario(),
]


def generate(n_pairs_per_scenario: int = 20, seed: int = 20260726) -> list[Item]:
    """Generate a balanced, deterministic set of matched pairs.

    The split is 50/50 surface/stay-quiet by construction. That is deliberate: a
    real deployment sees far more quiet moments than loud ones, but a balanced
    benchmark makes the near-miss contrast legible. docs/DATASET.md explains how
    to reweight to a realistic base rate when that matters.
    """
    rng = random.Random(seed)
    items: list[Item] = []
    for scenario in SCENARIOS:
        for i in range(n_pairs_per_scenario):
            positive, near = scenario.pair(rng, i)
            items.append(positive)
            items.append(near)
    rng.shuffle(items)
    return items
