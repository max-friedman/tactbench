"""Run policies against a split and produce scorecards."""

from __future__ import annotations

import time

from .metrics import Scorecard, score
from .policies.base import Policy
from .policies.builtin import NeverPolicy
from .schema import Decision, Item, pair_key


def run_policy(policy: Policy, items: list[Item]) -> list:
    """Run a policy over the moments, timing each decision.

    Policies see moments one at a time and never see labels. Latency is measured
    here rather than trusted from the policy, so a system cannot claim to be
    faster than it is.
    """
    decisions = []
    for item in items:
        started = time.perf_counter()
        d = policy.decide(item.moment)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if d.latency_ms is None:
            d = d.model_copy(update={"latency_ms": elapsed_ms})
        decisions.append(d)
    return decisions


def silence_ics(items: list[Item], base_rate: float = 1.0) -> float:
    """Cost incurred by saying nothing. The reference point for normalization.

    Must be computed at the same ``base_rate`` as the policy it will normalize, or
    the comparison is meaningless.
    """
    never = NeverPolicy()
    return score(items, run_policy(never, items), "never", base_rate=base_rate).ics


def pair_blind_decisions(items: list[Item], base_rate: float = 1.0) -> list[Decision]:
    """The best policy that cannot tell the two sides of a pair apart.

    Both sides share a body and a user state and differ only in the decider, so a
    policy that does not read the decider gives them the same answer. Per pair, this
    takes the cheaper of "both silent" and "both speak" -- never "both speak" where
    either side would be a hard violation, because those are never traded for cost.

    Round 24. Round 23 found this beats silence by +29.2 on ``v1/dev``: in five
    families a miss costs 3 and a false alarm 1, so speaking on both sides nets +2.
    Its ICS is the bar for *reading the moment*; silence stays the bar for *worth
    shipping*. It reads labels, so it is a reference point, not a policy.
    """
    pairs: dict[str, list[Item]] = {}
    for item in items:
        pairs.setdefault(pair_key(item.moment.id), []).append(item)

    speak: set[str] = set()
    for key, sides in pairs.items():
        loud = [Decision(moment_id=i.moment.id, surface=True) for i in sides]
        quiet = [Decision(moment_id=i.moment.id, surface=False) for i in sides]
        loud_card = score(sides, loud, "pair", base_rate=base_rate)
        if loud_card.hard_violations:
            continue
        if loud_card.ics < score(sides, quiet, "pair", base_rate=base_rate).ics:
            speak.add(key)
    return [Decision(moment_id=i.moment.id, surface=pair_key(i.moment.id) in speak) for i in items]


def pair_blind_ics(items: list[Item], base_rate: float = 1.0) -> float:
    """Cost of :func:`pair_blind_decisions`. Beating it requires reading the decider."""
    decisions = pair_blind_decisions(items, base_rate)
    return score(items, decisions, "pair-blind", base_rate=base_rate).ics


def normalized(ics: float, reference: float) -> float:
    """100 at zero cost, 0 at ``reference``, negative when worse than it.

    The same scale as ``Scorecard.ics_normalized``, for a reference other than
    silence -- in practice :func:`pair_blind_ics`.
    """
    return 100.0 * (1.0 - ics / reference) if reference > 0 else 0.0


def evaluate(
    policy: Policy,
    items: list[Item],
    reference: float | None = None,
    base_rate: float = 1.0,
) -> Scorecard:
    if reference is None:
        reference = silence_ics(items, base_rate=base_rate)
    return score(
        items,
        run_policy(policy, items),
        policy.name,
        reference_ics=reference,
        base_rate=base_rate,
    )
