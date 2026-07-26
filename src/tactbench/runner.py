"""Run policies against a split and produce scorecards."""

from __future__ import annotations

import time

from .metrics import Scorecard, score
from .policies.base import Policy
from .policies.builtin import NeverPolicy
from .schema import Item


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


def silence_ics(items: list[Item]) -> float:
    """Cost incurred by saying nothing. The reference point for normalization."""
    never = NeverPolicy()
    return score(items, run_policy(never, items), "never").ics


def evaluate(policy: Policy, items: list[Item], reference: float | None = None) -> Scorecard:
    if reference is None:
        reference = silence_ics(items)
    return score(items, run_policy(policy, items), policy.name, reference_ics=reference)
