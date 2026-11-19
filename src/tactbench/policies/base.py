"""Policy interface: the thing being benchmarked."""

from __future__ import annotations

from ..schema import Decision, Moment, policy_view


class Policy:
    """A system under test.

    A policy sees one moment at a time and decides whether to speak. It never
    sees the gold label, and it never sees other moments -- proactive assistance
    is an online decision, so batching would leak information a real system
    would not have.
    """

    name: str = "unnamed"

    def decide(self, moment: Moment) -> Decision:
        raise NotImplementedError

    def run(self, moments: list[Moment]) -> list[Decision]:
        return [ask(self, m) for m in moments]


def ask(policy: Policy, moment: Moment) -> Decision:
    """The one way to put a moment to a policy. Round 26.

    The policy sees :func:`schema.policy_view` -- no ``slices``, an opaque ``id`` --
    and its decision comes back under the stored id, so scoring and caching are
    unchanged. Whatever id the policy wrote, the decision is for the moment that was
    asked about.
    """
    d = policy.decide(policy_view(moment))
    return d.model_copy(update={"moment_id": moment.id})
