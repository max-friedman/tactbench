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

import hashlib
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
# (long form named in the body, short form used in the decider). Round 13: the
# returnable was a constant "the desk", which left the family's marker token fixed
# while the stand-in varied -- the bigram probe read that asymmetry at 2.0 SE from
# chance. Both roles now vary, and `SkylinePolicy` reads the item out of the body
# instead of matching a literal.
RETURNABLES = [
    ("standing desk", "desk"),
    ("espresso machine", "machine"),
    ("road bike", "bike"),
    ("monitor arm", "arm"),
    ("office chair", "chair"),
    ("cast iron pan", "pan"),
    ("wool overcoat", "overcoat"),
    ("electric kettle", "kettle"),
    ("camera lens", "lens"),
    ("folding treadmill", "treadmill"),
]

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


# --------------------------------------------------------------------------- #
# Decider frames -- Round 13.
#
# Every family's decider names two roles and swaps which value occupies which.
# A frame is ``(privileged_label, other_label)``: the privileged role is the one
# whose occupant decides the answer. Rendering puts the family's *marker* value in
# one role and the counterpart in the other, and the pair's two sides swap them --
# so both sides carry an identical token multiset by construction rather than by
# an author remembering to make it so.
#
# **The dev/test split is taken on the frame.** Frames 0-4 are training phrasings;
# 5-7 appear only in the held-out split. Round 12 showed that varying the *entity*
# buys nothing (91.2% -> 29.8% duplication moved the exploit 1.3 points) because
# the frame carries the label. Varying the frame *and holding some out* is the
# lever that was left: a bigram learned on "listed_you" does not fire on a test
# frame that says "At the school gate".
#
# This table is the single definition. `SkylinePolicy` imports it rather than
# keeping its own copy of the phrasings -- two private notions of the same thing
# is how Round 10's split leak survived nine rounds.
# --------------------------------------------------------------------------- #

FRAMES: dict[str, list[tuple[str, str]]] = {
    "childcare": [
        ("Listed for pickup", "Travelling this week"),
        ("On the school run", "Out of town"),
        ("Collecting at half three", "Away on business"),
        ("At the classroom door", "At a conference"),
        ("Doing the afternoon fetch", "On a flight"),
        ("Holding the kids tonight", "Boarding a plane tonight"),
        ("Minding bedtime", "Minding a layover"),
        ("Rostered for the nursery", "Rostered for the depot"),
    ],
    "deadline": [
        ("Primary", "Secondary"),
        ("Paged first", "Alerted second"),
        ("Owns the rota slot", "Escalation target"),
        ("On point", "On standby"),
        ("Carrying the pager", "Carrying the spare"),
        ("Holding the bleeper", "Holding the courtesy copy"),
        ("Accountable tonight", "Unavailable tonight"),
        ("Named lead", "Named deputy"),
    ],
    "health": [
        ("Still at the counter", "Handed over yesterday"),
        ("Waiting for pickup", "Signed for"),
        ("Uncollected", "Claimed"),
        ("On the shelf", "Out the door"),
        ("Awaiting a bag", "Already dispensed"),
        ("Sitting unclaimed", "Taken home"),
        ("Behind the screen", "Through the till"),
        ("In the basket", "Off the premises"),
    ],
    "quiet_hours": [
        ("Nearby", "Hours away"),
        ("Close enough to go", "Too far to go"),
        ("Can be there tonight", "Cannot arrive before morning"),
        ("Nearest to the hospital", "Furthest from the hospital"),
        ("In town", "On the road"),
        ("Twenty minutes from the ward", "A day's drive from the ward"),
        ("Able to walk in", "Unable to walk in"),
        ("Within reach", "Beyond reach"),
    ],
    "finance": [
        ("Short of the payment", "Clears it"),
        ("Below the amount due", "Above the amount due"),
        ("Underfunded", "Flush"),
        ("Cannot carry autopay", "Can carry autopay"),
        ("Insufficient", "Ample"),
        ("Lacking the money", "Holding the money"),
        ("Empty by Friday", "Loaded by Friday"),
        ("Will bounce", "Will settle"),
    ],
    "commerce": [
        ("Still boxed", "Already assembled"),
        ("Unopened", "Set up"),
        ("Sealed", "In use"),
        ("Shrink-wrapped", "Unpacked"),
        ("In its carton", "Out of the carton"),
        ("Factory taped", "Bolted together"),
        ("Never cut open", "Screwed down"),
        ("Awaiting a knife", "Standing on its legs"),
    ],
    "meeting_prep": [
        ("Begins shortly", "Already started"),
        ("Still ahead", "Long since underway"),
        ("Not yet open", "In progress"),
        ("Coming up", "Just passed"),
        ("Due to convene", "Convened without you"),
        ("Doors have not parted", "Doors parted an hour back"),
        ("Queued for later", "Ran earlier"),
        ("Scheduled after this", "Held before this"),
    ],
    "driving": [
        ("Backed up", "Clear"),
        ("Congested", "Flowing"),
        ("Jammed", "Moving"),
        ("Slow", "Open"),
        ("At a standstill", "At speed"),
        ("Crawling", "Running well"),
        ("Gridlocked", "Empty"),
        ("Snarled", "Untroubled"),
    ],
    "travel": [
        ("Standing at", "Ticket lists"),
        ("Physically by", "Printed as"),
        ("Where you wait", "Where the stub points"),
        ("Your actual position", "Your issued gate"),
        ("Boots on the ground at", "Ink says"),
        ("Body is near", "Barcode claims"),
        ("Feet are beside", "Paper insists"),
        ("Currently parked at", "Booked against"),
    ],
}

#: Frames reserved for the held-out split. Disjoint from training phrasings by
#: construction, which is what makes `verbatim_overlap` zero rather than merely
#: small.
HELD_OUT_FRAMES = frozenset({5, 6, 7})


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

    #: Structural phrasings of the decider. Round 13.
    #:
    #: Each entry is ``(privileged_label, other_label)``. The decider always names
    #: two roles; the **privileged** one is the role whose occupant decides the
    #: answer (the parent doing pickup, the on-call primary, the account autopay
    #: draws from). Rendering fills one role with ``you`` and the other with an
    #: entity, and the pair's two sides swap which is which -- so both sides carry
    #: an identical token multiset for free, rather than by an author remembering
    #: to make it so.
    #:
    #: Two properties make held-out frames actually hard, and both are load-bearing:
    #:
    #: 1. **The label vocabulary changes per frame.** A bigram learned on dev
    #:    frames ("listed_you") does not fire on a test frame that says "at the
    #:    school gate today". Round 12 established that varying the *entity* buys
    #:    nothing, because the frame carries the label; varying the frame is the
    #:    lever that was left.
    #: 2. **Clause order varies per pair, independently of the frame.** If the
    #:    privileged clause were always first, "you appears early" would answer the
    #:    item regardless of vocabulary and a *positional* probe would sail through
    #:    unseen frames. Tying order to frame parity is not enough either -- the
    #:    dev and test frame sets then carry different order mixes, and a
    #:    positional probe scored 34.7% on held-out frames, which is 65.3% once
    #:    negated. Order is drawn from a stable digest of the pair id, so both
    #:    orders appear within every frame and in both splits.
    @property
    def frames(self) -> list[tuple[str, str]]:
        return FRAMES[self.family]

    def fillers(self, rng: random.Random) -> tuple[str, str]:
        """``(marker, counterpart)``.

        The **marker** is the value that means *speak* when it occupies the
        privileged role -- ``you`` for the person families, ``checking`` for
        finance, the gate boarding moved away from for travel. The counterpart
        fills the other role, and the pair's two sides swap them.
        """
        raise NotImplementedError

    def render_frame(self, frame: int, rng: random.Random, idx: int = 0) -> tuple[str, str]:
        """(positive_text, near_miss_text) for one frame, as an exact permutation."""
        privileged, other = self.frames[frame % len(self.frames)]
        marker, counterpart = self.fillers(rng)
        # Stable per-pair, independent of the frame and of PYTHONHASHSEED.
        first_is_privileged = (
            hashlib.sha256(f"{self.family}-order-{idx}".encode()).digest()[0] % 2 == 0
        )

        def render(in_privileged: str, in_other: str) -> str:
            a = f"{privileged}: {in_privileged}."
            b = f"{other}: {in_other}."
            return f"{a} {b}" if first_is_privileged else f"{b} {a}"

        return render(marker, counterpart), render(counterpart, marker)

    #: Source/age the decider signal is attributed to.
    decider_source: Source = Source.MESSAGE
    decider_age_s: int = 120

    def deciders(self, rng: random.Random, frame: int, idx: int) -> tuple[Signal, Signal]:
        """(positive_decider, near_miss_decider). Permute roles, don't rewrite."""
        pos_text, near_text = self.render_frame(frame, rng, idx)
        return (
            Signal(source=self.decider_source, age_s=self.decider_age_s, content=pos_text),
            Signal(source=self.decider_source, age_s=self.decider_age_s, content=near_text),
        )

    def why(self) -> tuple[str, str]:
        raise NotImplementedError

    def pair(self, rng: random.Random, idx: int) -> tuple[Item, Item]:
        # One state *value* shared by both sides: if the user's activity differed
        # between a positive and its near-miss, the *state* would give the answer
        # away just as surely as the vocabulary did.
        state = self.state(rng)
        body = self.body(rng)
        # Frame is a deterministic function of the pair index, because the dev/test
        # split is taken on the frame: held-out items must use phrasings that never
        # appear in training. See `cli.build` and `schema.frame_of`.
        frame = idx % max(len(self.frames), 1)
        pos_dec, near_dec = self.deciders(rng, frame, idx)
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
            slices=[*self.positive_slices, f"frame:{frame}"],
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
            slices=["near_miss", *self.near_slices, f"frame:{frame}"],
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
        # ONE pool, sampled without replacement. Round 13: these were two disjoint
        # pools -- old gates always from {B12,C4,A21,D7}, new always from
        # {B31,C19,A2,D22} -- so the gate's identity revealed whether it was the
        # old or the new one, and a bigram read `at_b12` -> speak, `at_b31` ->
        # quiet. It survived from Round 1 because both gates appear on both sides
        # of a pair, which is exactly what the unigram probe checks.
        self._a, self._b = rng.sample(
            ["B12", "C4", "A21", "D7", "B31", "C19", "A2", "D22", "E14", "F3"], 2
        )
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

    decider_source = Source.APP_EVENT
    decider_age_s = 60

    def fillers(self, rng):
        return self._a, self._b

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

    decider_source = Source.MESSAGE
    decider_age_s = 120

    def fillers(self, rng):
        return "you", rng.choice(COLLEAGUES)

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
        self._item, self._short = rng.choice(RETURNABLES)
        phrasing = rng.choice(
            [
                f"Return window for the {self._item} closes in {hrs} hours.",
                f"You have {hrs} hours left to return the {self._item}.",
                f"The {self._item} return period ends in {hrs} hours.",
            ]
        )
        return [Signal(source=Source.APP_EVENT, age_s=300, content=phrasing)]

    decider_source = Source.SENSOR
    decider_age_s = 600

    def fillers(self, rng):
        return f"the {self._short}", f"the {rng.choice(RETURNABLE_STANDINS)}"

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

    decider_source = Source.CALENDAR
    decider_age_s = 0

    def fillers(self, rng):
        return "contract review", rng.choice(COUNTERPART_MEETINGS)

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

    decider_source = Source.APP_EVENT
    decider_age_s = 60

    def fillers(self, rng):
        return "your route", "the alternate at the next exit"

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

    decider_source = Source.MESSAGE
    decider_age_s = 120

    def fillers(self, rng):
        return "you", rng.choice(HOUSEHOLD)

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

    decider_source = Source.NOTIFICATION
    decider_age_s = 180

    def fillers(self, rng):
        other = rng.choice(PHARMACY_OTHERS)
        return "your prescription", f"{other}'s prescription"

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

    decider_source = Source.MESSAGE
    decider_age_s = 120

    def fillers(self, rng):
        return "you", rng.choice(HOUSEHOLD)

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

    decider_source = Source.APP_EVENT
    decider_age_s = 300

    def fillers(self, rng):
        return "checking", "savings"

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
