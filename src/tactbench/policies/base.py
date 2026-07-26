"""Policy interface: the thing being benchmarked."""

from __future__ import annotations

from ..schema import Decision, Moment


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
        return [self.decide(m) for m in moments]
