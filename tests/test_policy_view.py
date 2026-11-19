"""Policies are not handed the answer. Round 26.

Review of Round 24 found that the two sides of every pair differ in
``moment.slices`` -- provenance tags like ``near_miss`` and ``time_critical`` used
for stratified reporting -- and that "no ``near_miss`` tag means speak" is right on
100% of dev and held-out. The LLM prompt already withheld them (``render_moment``),
but ``runner.run_policy`` and the ``llm`` command passed the full ``Moment`` to
``Policy.decide``, so any submitted policy could read the label.
"""

from __future__ import annotations

from tactbench.dataset.loader import load
from tactbench.policies.base import Policy
from tactbench.runner import evaluate, run_policy
from tactbench.schema import Decision, policy_view


class _SlicesSnoop(Policy):
    """Reads the label out of the slice tags. Before R26 this scored perfectly."""

    name = "slices-snoop"

    def __init__(self):
        self.seen = []

    def decide(self, moment):
        self.seen.append(moment)
        return Decision(moment_id=moment.id, surface="near_miss" not in moment.slices)


def test_the_runner_hands_policies_no_slices():
    items = load("v1", "dev")
    snoop = _SlicesSnoop()
    run_policy(snoop, items)
    assert len(snoop.seen) == len(items)
    assert all(m.slices == [] for m in snoop.seen)


def test_a_slices_reading_policy_no_longer_solves_the_split():
    """The before-number: ICS 0.0 (perfect). With no slices it speaks on everything."""
    for split in ("dev", "test"):
        card = evaluate(_SlicesSnoop(), load("v1", split))
        assert card.ics > 0
        assert card.surfaced == card.n


def test_the_view_keeps_everything_a_policy_may_read():
    item = load("v1", "dev")[0]
    view = policy_view(item.moment)
    assert view.slices == []
    assert view.model_dump(exclude={"slices"}) == item.moment.model_dump(exclude={"slices"})
    assert item.moment.slices, "the stored moment itself must be left intact"


def test_reporting_still_slices_on_the_stored_moment():
    """Slice reporting reads the item, not the policy's view, so it keeps working."""
    card = evaluate(_SlicesSnoop(), load("v1", "dev"))
    assert "near_miss" in card.by_slice


def test_the_llm_command_hands_policies_no_slices(tmp_path, monkeypatch):
    """The second path to ``Policy.decide``. Spies on the decision call itself, so
    no server is needed."""
    from typer.testing import CliRunner

    from tactbench.cli import app
    from tactbench.policies.llm import LLMPolicy

    seen = []

    def spy(self, moment):
        seen.append(moment)
        return Decision(moment_id=moment.id, surface=False, rationale="spy")

    monkeypatch.setattr(LLMPolicy, "decide", spy)
    monkeypatch.chdir(tmp_path)
    args = ["llm", "--provider", "local", "--model", "spy", "--limit", "5"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert len(seen) == 5 and all(m.slices == [] for m in seen)
