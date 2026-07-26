"""Synthetic moment generation for TactBench v1.

Design note -- why moments come in pairs
----------------------------------------
A benchmark of "should the assistant speak?" is trivially gameable if the items
that warrant speech look different on the surface from the ones that don't. Any
policy could then match keywords ("delayed", "expires", "overdue") and score well
without having judged anything.

So every scenario here emits a **matched pair**: a positive moment and a near-miss
that shares the same signal sources, similar phrasing, and the same scenario
family, differing only in the fact that actually settles it -- the user already
handled it, the information is stale, it concerns someone else, or it arrived at
a moment when acting on it is impossible.

Labels for v1 are *by construction*: we know the answer because we built the item
around it. That is a real limitation, documented in docs/DATASET.md, and the
human-agreement subset exists to measure how far construction drifts from what
people actually want.
"""

from __future__ import annotations

import random

from ..schema import Activity, GoldLabel, Item, Moment, Signal, Source, UserState


class Scenario:
    """One scenario family, able to emit a matched positive/near-miss pair."""

    family: str = "generic"

    def positive(self, rng: random.Random, idx: int) -> Item:
        raise NotImplementedError

    def near_miss(self, rng: random.Random, idx: int) -> Item:
        raise NotImplementedError


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
        moment=Moment(
            id=mid, signals=signals, user_state=state, family=family, slices=slices
        ),
        label=GoldLabel(
            moment_id=mid,
            should_surface=should,
            value=value,
            acceptable_intents=intents if should else [],
            window_s=window_s,
            rationale=rationale,
        ),
    )


class TravelScenario(Scenario):
    """Flight disruptions. The classic proactive-assistant demo, and the classic
    place where assistants over-fire on information the user already has."""

    family = "travel"

    def positive(self, rng: random.Random, idx: int) -> Item:
        gate = rng.choice(["B12", "C4", "A21", "D7"])
        new_gate = rng.choice(["B31", "C19", "A2", "D22"])
        state = UserState(
            activity=Activity.COMMUTING,
            device="phone",
            last_interaction_s=rng.randint(30, 300),
            local_hour=rng.randint(7, 20),
        )
        signals = [
            Signal(
                source=Source.EMAIL,
                age_s=120,
                content=f"Your gate has changed from {gate} to {new_gate}. "
                "Boarding begins in 35 minutes.",
                meta={"sender": "airline"},
            ),
            Signal(
                source=Source.LOCATION,
                age_s=60,
                content="At airport terminal, 8 minute walk from current position "
                f"to gate {new_gate}.",
            ),
            Signal(
                source=Source.SCREEN,
                age_s=45,
                content="Reading a news article, not the airline app.",
            ),
        ]
        return _mk(
            f"travel-pos-{idx:04d}",
            self.family,
            signals,
            state,
            should=True,
            value=3,
            intents=["gate_change_alert"],
            rationale=(
                "Gate moved, the user has not opened the airline app, and there is "
                "a walk involved with a hard deadline. Missing this has a real cost."
            ),
            slices=["time_critical"],
            window_s=600,
        )

    def near_miss(self, rng: random.Random, idx: int) -> Item:
        gate = rng.choice(["B12", "C4", "A21", "D7"])
        new_gate = rng.choice(["B31", "C19", "A2", "D22"])
        state = UserState(
            activity=Activity.COMMUTING,
            device="phone",
            last_interaction_s=rng.randint(5, 40),
            local_hour=rng.randint(7, 20),
        )
        signals = [
            Signal(
                source=Source.EMAIL,
                age_s=120,
                content=f"Your gate has changed from {gate} to {new_gate}. "
                "Boarding begins in 35 minutes.",
                meta={"sender": "airline"},
            ),
            Signal(
                source=Source.LOCATION,
                age_s=60,
                content=f"At airport terminal, already seated at gate {new_gate}.",
            ),
            Signal(
                source=Source.SCREEN,
                age_s=10,
                content="Airline app open, viewing the updated boarding pass.",
            ),
        ]
        return _mk(
            f"travel-near-{idx:04d}",
            self.family,
            signals,
            state,
            should=False,
            value=0,
            intents=[],
            rationale=(
                "Identical disruption, but the user is already at the new gate with "
                "the updated pass on screen. Telling them is pure noise."
            ),
            slices=["near_miss", "already_handled"],
        )


class DeadlineScenario(Scenario):
    """Work items that block other people. Interrupting focused work is expensive,
    so the bar for speaking is high even when the item is real."""

    family = "deadline"

    def positive(self, rng: random.Random, idx: int) -> Item:
        state = UserState(
            activity=Activity.FOCUSED_WORK,
            device="laptop",
            last_interaction_s=rng.randint(0, 20),
            local_hour=rng.randint(9, 17),
        )
        signals = [
            Signal(
                source=Source.APP_EVENT,
                age_s=90,
                content="Production deploy for release 4.2 failed health checks and "
                "auto-rolled back. You are the listed on-call owner.",
            ),
            Signal(
                source=Source.MESSAGE,
                age_s=60,
                content="#incident: 'anyone seeing the 4.2 rollback? paging on-call'",
            ),
            Signal(
                source=Source.SCREEN,
                age_s=5,
                content="Writing a design doc in a text editor.",
            ),
        ]
        return _mk(
            f"deadline-pos-{idx:04d}",
            self.family,
            signals,
            state,
            should=True,
            value=3,
            intents=["incident_page"],
            rationale=(
                "The user is the named on-call owner of a live production incident "
                "and others are blocked. This clears the bar for breaking focus."
            ),
            slices=["time_critical", "breaks_focus"],
            window_s=300,
        )

    def near_miss(self, rng: random.Random, idx: int) -> Item:
        state = UserState(
            activity=Activity.FOCUSED_WORK,
            device="laptop",
            last_interaction_s=rng.randint(0, 20),
            local_hour=rng.randint(9, 17),
        )
        signals = [
            Signal(
                source=Source.APP_EVENT,
                age_s=90,
                content="Production deploy for release 4.2 failed health checks and "
                "auto-rolled back. On-call owner is Priya Raman.",
            ),
            Signal(
                source=Source.MESSAGE,
                age_s=45,
                content="#incident: 'priya is on it, rollback confirmed clean'",
            ),
            Signal(
                source=Source.SCREEN,
                age_s=5,
                content="Writing a design doc in a text editor.",
            ),
        ]
        return _mk(
            f"deadline-near-{idx:04d}",
            self.family,
            signals,
            state,
            should=False,
            value=0,
            intents=[],
            rationale=(
                "Same incident vocabulary and same urgency cues, but it is someone "
                "else's page and already resolved. Breaking focus here is a pure loss."
            ),
            slices=["near_miss", "not_yours", "breaks_focus"],
        )


class CommerceScenario(Scenario):
    """Price and return-window cues. Low stakes, which is exactly why an assistant
    should not spend an interruption on them during expensive moments."""

    family = "commerce"

    def positive(self, rng: random.Random, idx: int) -> Item:
        state = UserState(
            activity=Activity.IDLE,
            device="phone",
            last_interaction_s=rng.randint(2, 60),
            local_hour=rng.randint(10, 21),
        )
        signals = [
            Signal(
                source=Source.APP_EVENT,
                age_s=300,
                content="Return window for the standing desk you ordered closes "
                "tomorrow. Item is still unopened in the hallway.",
            ),
            Signal(
                source=Source.MESSAGE,
                age_s=86400,
                content="You told a friend: 'honestly might send the desk back'",
            ),
        ]
        return _mk(
            f"commerce-pos-{idx:04d}",
            self.family,
            signals,
            state,
            should=True,
            value=2,
            intents=["return_window_reminder"],
            rationale=(
                "A deadline the user cannot recover from once passed, they signalled "
                "intent to return, and they are idle. Cheap moment, real value."
            ),
            slices=["low_stakes"],
            window_s=3600,
        )

    def near_miss(self, rng: random.Random, idx: int) -> Item:
        state = UserState(
            activity=Activity.MEETING,
            device="laptop",
            last_interaction_s=rng.randint(0, 30),
            local_hour=rng.randint(10, 17),
        )
        signals = [
            Signal(
                source=Source.APP_EVENT,
                age_s=300,
                content="Price dropped 12% on the standing desk you viewed last week.",
            ),
            Signal(
                source=Source.CALENDAR,
                age_s=0,
                content="In progress: 'Quarterly review with leadership' (45 min).",
            ),
        ]
        return _mk(
            f"commerce-near-{idx:04d}",
            self.family,
            signals,
            state,
            should=False,
            value=0,
            intents=[],
            rationale=(
                "A genuine and mildly useful fact, delivered mid-meeting. The value "
                "of a price drop never justifies this interruption cost."
            ),
            slices=["near_miss", "low_stakes", "wrong_moment"],
        )


class QuietHoursScenario(Scenario):
    """The hardest slice: genuinely useful information arriving while the user is
    asleep or driving. Value and timing point in opposite directions."""

    family = "quiet_hours"

    def positive(self, rng: random.Random, idx: int) -> Item:
        state = UserState(
            activity=Activity.SLEEPING,
            dnd=True,
            device="phone",
            last_interaction_s=rng.randint(7200, 20000),
            local_hour=rng.choice([2, 3, 4]),
        )
        signals = [
            Signal(
                source=Source.MESSAGE,
                age_s=60,
                content="Mom: 'Dad's in the ER at Cedars, he's stable but come when "
                "you can.' Third message in 10 minutes.",
                meta={"contact": "family", "priority": "starred"},
            ),
            Signal(source=Source.SENSOR, age_s=30, content="Phone face down, charging."),
        ]
        return _mk(
            f"quiet-pos-{idx:04d}",
            self.family,
            signals,
            state,
            should=True,
            value=3,
            intents=["family_emergency"],
            rationale=(
                "DND exists to be overridden by exactly this. A starred contact, a "
                "medical emergency, and repeat attempts to reach them."
            ),
            slices=["quiet_hours", "dnd_override"],
            window_s=900,
        )

    def near_miss(self, rng: random.Random, idx: int) -> Item:
        state = UserState(
            activity=Activity.SLEEPING,
            dnd=True,
            device="phone",
            last_interaction_s=rng.randint(7200, 20000),
            local_hour=rng.choice([2, 3, 4]),
        )
        signals = [
            Signal(
                source=Source.MESSAGE,
                age_s=60,
                content="Mom: 'Are you awake? Call me when you get a chance.' "
                "Third message in 10 minutes.",
                meta={"contact": "family", "priority": "starred"},
            ),
            Signal(source=Source.SENSOR, age_s=30, content="Phone face down, charging."),
        ]
        return _mk(
            f"quiet-near-{idx:04d}",
            self.family,
            signals,
            state,
            should=False,
            value=0,
            intents=[],
            rationale=(
                "Same contact, same repetition, same hour -- but nothing stated is "
                "urgent. Repetition alone must not be enough to break DND at 3am."
            ),
            slices=["near_miss", "quiet_hours", "dnd_override"],
        )


class DrivingScenario(Scenario):
    """Safety-protected state. Even correct cues must be shaped to it, and most
    things that would be fine on a laptop are violations here."""

    family = "driving"

    def positive(self, rng: random.Random, idx: int) -> Item:
        state = UserState(
            activity=Activity.DRIVING,
            device="phone",
            last_interaction_s=rng.randint(600, 3000),
            local_hour=rng.randint(7, 19),
        )
        signals = [
            Signal(
                source=Source.LOCATION,
                age_s=30,
                content="Route to the airport now shows a 40 minute delay; an "
                "alternate route saves 25 minutes if taken at the next exit.",
            ),
            Signal(
                source=Source.CALENDAR,
                age_s=0,
                content="Flight departs in 2 hours 10 minutes.",
            ),
        ]
        return _mk(
            f"driving-pos-{idx:04d}",
            self.family,
            signals,
            state,
            should=True,
            value=3,
            intents=["reroute_alert"],
            rationale=(
                "Actionable only in a narrow window, safety-relevant to deliver as "
                "audio, and the cost of missing it is a missed flight."
            ),
            slices=["protected_state", "time_critical"],
            window_s=120,
        )

    def near_miss(self, rng: random.Random, idx: int) -> Item:
        state = UserState(
            activity=Activity.DRIVING,
            device="phone",
            last_interaction_s=rng.randint(600, 3000),
            local_hour=rng.randint(7, 19),
        )
        signals = [
            Signal(
                source=Source.LOCATION,
                age_s=30,
                content="Route to the airport is clear; you are 25 minutes ahead of "
                "the usual time for this trip.",
            ),
            Signal(
                source=Source.EMAIL,
                age_s=120,
                content="Your flight's inflight menu is now available to pre-order.",
            ),
        ]
        return _mk(
            f"driving-near-{idx:04d}",
            self.family,
            signals,
            state,
            should=False,
            value=0,
            intents=[],
            rationale=(
                "Travel-shaped and flight-related, but nothing is wrong and nothing "
                "is actionable from the driver's seat."
            ),
            slices=["near_miss", "protected_state"],
        )


class MeetingPrepScenario(Scenario):
    """Preparation cues, where the whole judgment is about lead time."""

    family = "meeting_prep"

    def positive(self, rng: random.Random, idx: int) -> Item:
        state = UserState(
            activity=Activity.IDLE,
            device="laptop",
            last_interaction_s=rng.randint(5, 90),
            local_hour=rng.randint(9, 16),
        )
        signals = [
            Signal(
                source=Source.CALENDAR,
                age_s=0,
                content="'Vendor contract review' starts in 12 minutes. You are the "
                "only required attendee besides the vendor.",
            ),
            Signal(
                source=Source.EMAIL,
                age_s=5400,
                content="Vendor sent a revised contract 90 minutes ago with changed "
                "payment terms. Unopened.",
            ),
        ]
        return _mk(
            f"prep-pos-{idx:04d}",
            self.family,
            signals,
            state,
            should=True,
            value=2,
            intents=["meeting_prep"],
            rationale=(
                "There is unread material that changes the meeting, enough time to "
                "read it, and the user is idle. Lead time is the whole point."
            ),
            slices=["lead_time"],
            window_s=600,
        )

    def near_miss(self, rng: random.Random, idx: int) -> Item:
        state = UserState(
            activity=Activity.IDLE,
            device="laptop",
            last_interaction_s=rng.randint(5, 90),
            local_hour=rng.randint(9, 16),
        )
        signals = [
            Signal(
                source=Source.CALENDAR,
                age_s=0,
                content="'Vendor contract review' started 4 minutes ago. You are the "
                "only required attendee besides the vendor.",
            ),
            Signal(
                source=Source.EMAIL,
                age_s=5400,
                content="Vendor sent a revised contract 90 minutes ago with changed "
                "payment terms. Unopened.",
            ),
        ]
        return _mk(
            f"prep-near-{idx:04d}",
            self.family,
            signals,
            state,
            should=False,
            value=0,
            intents=[],
            rationale=(
                "Same unread document, but the meeting is already underway. A prep "
                "cue delivered after the fact only tells the user they failed."
            ),
            slices=["near_miss", "lead_time", "too_late"],
        )


SCENARIOS: list[Scenario] = [
    TravelScenario(),
    DeadlineScenario(),
    CommerceScenario(),
    QuietHoursScenario(),
    DrivingScenario(),
    MeetingPrepScenario(),
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
            items.append(scenario.positive(rng, i))
            items.append(scenario.near_miss(rng, i))
    rng.shuffle(items)
    return items
