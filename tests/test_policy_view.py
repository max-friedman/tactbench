"""Policies are not handed the answer. Round 26.

Review of Round 24 found that the two sides of every pair differ in
``moment.slices`` -- provenance tags like ``near_miss`` and ``time_critical`` used
for stratified reporting -- and that "no ``near_miss`` tag means speak" is right on
100% of dev and held-out. The LLM prompt already withheld them (``render_moment``),
but ``runner.run_policy`` and the ``llm`` command passed the full ``Moment`` to
``Policy.decide``, so any submitted policy could read the label.
"""

from __future__ import annotations

from collections import defaultdict

from tactbench.dataset.loader import load
from tactbench.policies.base import Policy, ask
from tactbench.runner import evaluate, run_policy
from tactbench.schema import Decision, pair_key, policy_view


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
    """Only ``slices`` and ``id`` change -- and ``id`` changes on purpose (R26
    review): it encoded the label as ``-pos-`` / ``-near-``."""
    for item in load("v1", "dev"):
        view = policy_view(item.moment)
        assert view.slices == []
        assert view.id != item.moment.id
        keep = {"slices", "id"}
        assert view.model_dump(exclude=keep) == item.moment.model_dump(exclude=keep)
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


class _IdSnoop(Policy):
    """Reads the label out of the id. Found by the review of R26: ICS 0.0."""

    name = "id-snoop"

    def decide(self, moment):
        return Decision(moment_id=moment.id, surface="-pos-" in moment.id)


def test_an_id_reading_policy_no_longer_solves_the_split():
    for split in ("dev", "test"):
        card = evaluate(_IdSnoop(), load("v1", split))
        assert card.surfaced == 0  # the opaque id never contains "-pos-"


def test_decisions_come_back_under_the_real_id():
    """The policy answers under the opaque id; scoring needs the stored one."""
    items = load("v1", "dev")
    decisions = run_policy(_SlicesSnoop(), items)
    assert [d.moment_id for d in decisions] == [i.moment.id for i in items]


def test_a_pairs_two_views_differ_only_in_the_decider_and_the_opaque_id():
    """Queue item D. The two sides of a pair, as a policy sees them, may differ in
    the decider signal's text and in nothing that carries the label. Written field
    by field over the whole dump, so a field added later is covered too. Before
    R26 this failed twice: on ``slices`` and on ``id``."""

    def flat(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield from flat(v, f"{prefix}.{k}" if prefix else k)
        elif isinstance(obj, list):
            for idx, v in enumerate(obj):
                yield from flat(v, f"{prefix}[{idx}]")
        else:
            yield prefix, obj

    for split in ("dev", "test"):
        pairs = defaultdict(list)
        for item in load("v1", split):
            pairs[pair_key(item.moment.id)].append(item)
        for key, (a, b) in pairs.items():
            va, vb = (dict(flat(policy_view(i.moment).model_dump())) for i in (a, b))
            assert va.keys() == vb.keys(), key
            differ = {f for f in va if va[f] != vb[f]}
            last = len(a.moment.signals) - 1
            assert differ <= {"id", f"signals[{last}].content"}, (key, differ)
            for view in (va, vb):
                assert "pos" not in view["id"] and "near" not in view["id"], view["id"]


def test_policy_run_goes_through_the_view():
    """The third path to ``decide``. Review of R26: it passed raw moments."""
    items = load("v1", "dev")[:5]
    snoop = _SlicesSnoop()
    out = snoop.run([i.moment for i in items])
    assert all(m.slices == [] for m in snoop.seen)
    assert [d.moment_id for d in out] == [i.moment.id for i in items]


def test_ask_is_the_one_path():
    item = load("v1", "dev")[0]
    snoop = _SlicesSnoop()
    d = ask(snoop, item.moment)
    assert d.moment_id == item.moment.id and snoop.seen[0].slices == []


def test_no_code_calls_decide_except_through_ask():
    """Review of R26: "one path" was a claim, not a check -- a mutation handing the
    ``llm`` command a slices-only view with the raw id passed every test. This scans
    ``src/`` and ``experiments/``. The allowed calls either *are* ``ask`` or delegate
    inside a policy, on a moment that is already a view."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    allowed = {
        ("src/tactbench/policies/base.py", "policy.decide(policy_view(moment))"),
        ("src/tactbench/policies/skyline.py", "self._skyline.decide(moment)"),
        ("experiments/implied_comprehension_probe.py", "self._skyline.decide(moment)"),
    }
    found = set()
    for path in [*root.glob("src/**/*.py"), *root.glob("experiments/*.py")]:
        for line in path.read_text().splitlines():
            m = re.search(r"\S*\.decide\(.*\)", line)
            if m and "def decide" not in line:
                found.add((str(path.relative_to(root)), m.group(0)))
    assert found == allowed, f"unexpected direct calls: {sorted(found - allowed)}"


def test_the_llm_command_hands_policies_an_opaque_id(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from tactbench.cli import app
    from tactbench.policies.llm import LLMPolicy

    ids = []

    def spy(self, moment):
        ids.append(moment.id)
        return Decision(moment_id=moment.id, surface=False, rationale="spy")

    monkeypatch.setattr(LLMPolicy, "decide", spy)
    monkeypatch.chdir(tmp_path)
    args = ["llm", "--provider", "local", "--model", "spy", "--limit", "5"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert len(ids) == 5 and all(i.startswith("m-") and "pos" not in i for i in ids)
