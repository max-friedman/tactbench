"""Core data model for TactBench.

A *moment* is a frozen slice of a user's context. A *policy* looks at a moment and
decides whether to say something. A *gold label* records what a well-calibrated
assistant should have done, and how much it would have been worth.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Source(StrEnum):
    """Where a context signal came from."""

    SCREEN = "screen"
    CALENDAR = "calendar"
    MESSAGE = "message"
    EMAIL = "email"
    LOCATION = "location"
    APP_EVENT = "app_event"
    NOTIFICATION = "notification"
    SENSOR = "sensor"


class Activity(StrEnum):
    """What the user is doing. Drives the cost of interrupting them."""

    FOCUSED_WORK = "focused_work"
    MEETING = "meeting"
    IDLE = "idle"
    COMMUTING = "commuting"
    DRIVING = "driving"
    SLEEPING = "sleeping"
    SOCIAL = "social"
    EXERCISING = "exercising"


#: Activities where an unwanted interruption is not merely annoying but unsafe or
#: trust-destroying. False positives here are counted as hard violations and are
#: reported raw -- never averaged into an aggregate that could hide them.
PROTECTED_ACTIVITIES: frozenset[Activity] = frozenset({Activity.DRIVING, Activity.SLEEPING})


class Signal(BaseModel):
    """One observable piece of context available at the moment."""

    source: Source
    #: Seconds before the moment's timestamp that this signal was observed.
    age_s: int = 0
    content: str
    meta: dict[str, str] = Field(default_factory=dict)


class UserState(BaseModel):
    """The user's disposition at the moment. Not something a policy may ignore."""

    activity: Activity
    #: Do-not-disturb is explicitly on. A stated preference, not an inference.
    dnd: bool = False
    device: str = "phone"
    #: Seconds since the user last touched a device. High values mean the user is
    #: away, so surfacing costs less but also delivers later.
    last_interaction_s: int = 0
    #: Local wall-clock hour, 0-23. Used for quiet-hours reasoning.
    local_hour: int = 12


class Moment(BaseModel):
    """A single benchmark item: everything a policy is allowed to see."""

    id: str
    signals: list[Signal]
    user_state: UserState
    #: Scenario family this moment was drawn from (e.g. "travel", "deadline").
    family: str
    #: Slice tags for stratified reporting, e.g. "near_miss", "quiet_hours".
    slices: list[str] = Field(default_factory=list)


class GoldLabel(BaseModel):
    """Ground truth for a moment."""

    moment_id: str
    should_surface: bool
    #: Value of surfacing, on a 0-3 scale. 0 means actively harmful; 3 means the
    #: user would be materially worse off having missed it. Missing a 3 is scored
    #: far more harshly than missing a 1.
    value: int = Field(ge=0, le=3)
    #: Intents that would be an acceptable thing to say. Empty when
    #: ``should_surface`` is False.
    acceptable_intents: list[str] = Field(default_factory=list)
    #: Seconds within which the cue is still useful. ``None`` means untimed.
    window_s: int | None = None
    rationale: str = ""
    #: How many humans labeled this item. 0 means the label is by construction.
    raters: int = 0
    #: Fraction of raters agreeing with the majority. 1.0 for constructed labels.
    agreement: float = 1.0


class Decision(BaseModel):
    """What a policy returns for a moment."""

    moment_id: str
    surface: bool
    #: The policy's own probability that surfacing is correct. Used for
    #: calibration scoring; policies that don't model it should leave it at 0.5.
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    intent: str | None = None
    cue_text: str | None = None
    latency_ms: float | None = None
    #: Free-form reasoning, kept for the failure viewer. Never scored.
    rationale: str | None = None


class Item(BaseModel):
    """A moment paired with its label, as stored in the dataset files."""

    moment: Moment
    label: GoldLabel
