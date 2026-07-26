"""Scoring for TactBench.

The central claim of this benchmark is that *accuracy is the wrong metric*. The
cost of speaking when you shouldn't have is not symmetric with the cost of staying
quiet when you should have spoken, and neither cost is constant -- both depend on
what the user was doing at the time.

So the headline number is the Interruption Cost Score (ICS): total incurred cost,
normalized against a reference policy. The bar every system must clear is
``never`` -- a policy that says nothing, ever. A proactive assistant that cannot
beat silence is worse than not shipping.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import PROTECTED_ACTIVITIES, Activity, Decision, Item

#: Cost of surfacing when the gold label says not to, by what the user was doing.
#: Interrupting deep work or a meeting is what makes people turn proactive
#: features off; interrupting an idle user is a minor annoyance.
FALSE_POSITIVE_COST: dict[Activity, float] = {
    Activity.SLEEPING: 10.0,
    Activity.DRIVING: 10.0,
    Activity.MEETING: 5.0,
    Activity.FOCUSED_WORK: 5.0,
    Activity.EXERCISING: 2.0,
    Activity.SOCIAL: 2.0,
    Activity.COMMUTING: 1.0,
    Activity.IDLE: 1.0,
}

#: Extra cost when the user has explicitly asked for quiet. Ignoring a stated
#: preference is a different kind of failure from misjudging an inferred state.
DND_MULTIPLIER = 2.0

#: Cost of staying quiet, by how valuable the missed cue would have been.
FALSE_NEGATIVE_COST: dict[int, float] = {0: 0.0, 1: 0.5, 2: 2.0, 3: 3.0}

#: Deciding *whether* to speak and deciding *what* to say are different
#: capabilities, and this benchmark is about the first one. Charging content
#: errors into ICS would let a policy with flawless timing look bad because it
#: emitted a generic intent, which is not the failure mode being studied.
#:
#: So wrong intent is tracked and reported as its own metric -- ``intent_accuracy``
#: -- and never folded into ICS.
WRONG_INTENT_COST = 0.0


@dataclass
class Outcome:
    """Per-item scoring detail, kept so the viewer can show failures."""

    moment_id: str
    kind: str  # "tp" | "fp" | "tn" | "fn"
    cost: float
    hard_violation: bool = False
    wrong_intent: bool = False


@dataclass
class Scorecard:
    """Aggregate results for one policy on one dataset split."""

    policy: str
    n: int
    ics: float
    ics_normalized: float
    precision_at_interrupt: float | None
    recall_high_value: float | None
    timeliness: float | None
    #: Of the correctly-timed cues where the policy named an intent, the fraction
    #: naming an acceptable one. ``None`` when the policy never names intents.
    intent_accuracy: float | None
    ece: float
    hard_violations: int
    surfaced: int
    counts: dict[str, int] = field(default_factory=dict)
    by_slice: dict[str, float] = field(default_factory=dict)
    outcomes: list[Outcome] = field(default_factory=list)

    def beats_silence(self, silence_ics: float) -> bool:
        return self.ics < silence_ics


def _false_positive_cost(item: Item) -> float:
    state = item.moment.user_state
    cost = FALSE_POSITIVE_COST[state.activity]
    if state.dnd:
        cost *= DND_MULTIPLIER
    return cost


def score_item(item: Item, decision: Decision) -> Outcome:
    """Score a single decision against its gold label."""
    label = item.label
    mid = item.moment.id

    if decision.surface and not label.should_surface:
        state = item.moment.user_state
        hard = state.activity in PROTECTED_ACTIVITIES or state.dnd
        return Outcome(mid, "fp", _false_positive_cost(item), hard_violation=hard)

    if not decision.surface and label.should_surface:
        return Outcome(mid, "fn", FALSE_NEGATIVE_COST[label.value])

    if not decision.surface and not label.should_surface:
        return Outcome(mid, "tn", 0.0)

    # Surfaced, and was right to. Note whether the content was also right, but
    # keep that out of the cost -- see WRONG_INTENT_COST.
    wrong = (
        decision.intent is not None
        and bool(label.acceptable_intents)
        and decision.intent not in label.acceptable_intents
    )
    return Outcome(mid, "tp", WRONG_INTENT_COST if wrong else 0.0, wrong_intent=wrong)


def expected_calibration_error(
    decisions: list[Decision], outcomes: list[Outcome], bins: int = 10
) -> float:
    """Standard ECE over the policy's stated confidence that surfacing is correct.

    A decision is "correct" when it matches the gold label, so confidence is
    interpreted as P(my choice is right). Policies that never model confidence sit
    at 0.5 and land in the middle bin, which is the honest place for them to be.
    """
    if not decisions:
        return 0.0

    correct_by_id = {o.moment_id: o.kind in ("tp", "tn") for o in outcomes}
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for d in decisions:
        if d.moment_id not in correct_by_id:
            continue
        idx = min(int(d.confidence * bins), bins - 1)
        buckets[idx].append((d.confidence, correct_by_id[d.moment_id]))

    total = sum(len(b) for b in buckets)
    if total == 0:
        return 0.0

    ece = 0.0
    for b in buckets:
        if not b:
            continue
        avg_conf = sum(c for c, _ in b) / len(b)
        accuracy = sum(1 for _, ok in b if ok) / len(b)
        ece += (len(b) / total) * abs(avg_conf - accuracy)
    return ece


def score(
    items: list[Item],
    decisions: list[Decision],
    policy_name: str,
    reference_ics: float | None = None,
) -> Scorecard:
    """Score a full run.

    ``reference_ics`` is the cost incurred by the ``never`` policy on the same
    split. When provided, ``ics_normalized`` maps 0 cost to 100 and the silence
    baseline to 0 -- so a negative normalized score means the system is actively
    worse than shipping nothing.
    """
    by_id = {d.moment_id: d for d in decisions}
    outcomes: list[Outcome] = []
    used: list[Decision] = []

    for item in items:
        d = by_id.get(item.moment.id)
        if d is None:
            # A policy that declines to answer is treated as staying quiet, which
            # is the safe default rather than a free pass.
            d = Decision(moment_id=item.moment.id, surface=False)
        used.append(d)
        outcomes.append(score_item(item, d))

    counts: dict[str, int] = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for o in outcomes:
        counts[o.kind] += 1

    total_cost = sum(o.cost for o in outcomes)
    hard_violations = sum(1 for o in outcomes if o.hard_violation)
    surfaced = counts["tp"] + counts["fp"]

    precision = counts["tp"] / surfaced if surfaced else None

    high_value = [i for i in items if i.label.should_surface and i.label.value >= 2]
    if high_value:
        hit = sum(1 for i in high_value if by_id.get(i.moment.id, Decision(
            moment_id=i.moment.id, surface=False)).surface)
        recall_hv = hit / len(high_value)
    else:
        recall_hv = None

    timed = [i for i in items if i.label.should_surface and i.label.window_s is not None]
    if timed:
        on_time = 0
        for i in timed:
            d = by_id.get(i.moment.id)
            if d is None or not d.surface:
                continue
            # Latency is optional; a policy that doesn't report it is assumed
            # instantaneous rather than penalized for missing instrumentation.
            if d.latency_ms is None or d.latency_ms / 1000.0 <= (i.label.window_s or 0):
                on_time += 1
        timeliness = on_time / len(timed)
    else:
        timeliness = None

    named = [
        o
        for o in outcomes
        if o.kind == "tp" and by_id.get(o.moment_id) and by_id[o.moment_id].intent is not None
    ]
    intent_accuracy = (
        sum(1 for o in named if not o.wrong_intent) / len(named) if named else None
    )

    ics_norm = 0.0
    if reference_ics is not None and reference_ics > 0:
        ics_norm = 100.0 * (1.0 - total_cost / reference_ics)

    by_slice: dict[str, float] = {}
    cost_by_id = {o.moment_id: o.cost for o in outcomes}
    slice_totals: dict[str, list[float]] = {}
    for item in items:
        for s in item.moment.slices:
            slice_totals.setdefault(s, []).append(cost_by_id[item.moment.id])
    for s, costs in slice_totals.items():
        by_slice[s] = sum(costs) / len(costs)

    return Scorecard(
        policy=policy_name,
        n=len(items),
        ics=total_cost,
        ics_normalized=ics_norm,
        precision_at_interrupt=precision,
        recall_high_value=recall_hv,
        timeliness=timeliness,
        intent_accuracy=intent_accuracy,
        ece=expected_calibration_error(used, outcomes),
        hard_violations=hard_violations,
        surfaced=surfaced,
        counts=counts,
        by_slice=by_slice,
        outcomes=outcomes,
    )
