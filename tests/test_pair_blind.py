"""The pair-blind bar. Round 24.

Round 23 found that silence is not the comprehension bar. In five families a missed
cue costs more than a false alarm, so a policy that answers both sides of a pair
the same way -- which needs no comprehension, since the sides share a body and a
user state -- beats silence by speaking on both. Five topic words did it: +29.2.

The pair-blind bar is the best cost any such policy can reach: per pair, the cheaper
of "both silent" and "both speak", never choosing a side that would be a hard
violation, because those are never traded. It is the optimum over every policy that
cannot tell a pair's sides apart, so beating it requires reading the decider.
Silence stays the bar for *worth shipping*; this is the bar for *reads the moment*.
"""

from __future__ import annotations

import random
import re
from collections import defaultdict

import pytest
from test_metrics import TestNoKeywordExploit, TestReadmeResultsAreCurrent, _TopicPolicy

from tactbench.dataset.loader import load
from tactbench.metrics import score
from tactbench.policies.builtin import AlwaysPolicy
from tactbench.policies.skyline import SkylinePolicy
from tactbench.runner import evaluate, pair_blind_decisions, pair_blind_ics, silence_ics
from tactbench.schema import Decision, pair_key


@pytest.fixture(scope="module", params=["dev", "test"])
def items(request):
    return load("v1", request.param)


def _pairs(items):
    pairs = defaultdict(list)
    for item in items:
        pairs[pair_key(item.moment.id)].append(item)
    return pairs


def test_the_bar_answers_both_sides_of_every_pair_alike(items):
    by_id = {d.moment_id: d.surface for d in pair_blind_decisions(items)}
    for sides in _pairs(items).values():
        assert len({by_id[i.moment.id] for i in sides}) == 1


def test_the_bar_never_buys_cost_with_a_hard_violation(items):
    card = score(items, pair_blind_decisions(items), "pair-blind")
    assert card.hard_violations == 0
    assert card.ics == pair_blind_ics(items)


@pytest.mark.parametrize("base_rate", [1.0, 10.0, 100.0])
def test_the_bar_is_never_worse_than_silence(items, base_rate):
    assert pair_blind_ics(items, base_rate) <= silence_ics(items, base_rate)


def test_at_a_realistic_prior_the_bar_is_silence(items):
    """At 100 quiet moments per loud one, no false alarm is worth any miss."""
    assert pair_blind_ics(items, 100.0) == silence_ics(items, 100.0)


def test_no_pair_blind_policy_beats_the_bar(items):
    """The bar is an optimum, so this guards the implementation, not the data."""
    bar = pair_blind_ics(items)
    pairs = _pairs(items)
    rng = random.Random(24)
    for _ in range(200):
        speak = {k for k in pairs if rng.random() < 0.5}
        ds = [
            Decision(moment_id=i.moment.id, surface=pair_key(i.moment.id) in speak) for i in items
        ]
        card = score(items, ds, "random-pair-blind")
        if card.hard_violations == 0:
            assert card.ics >= bar


def test_the_round_23_topic_policy_does_not_beat_the_bar(items):
    """The before-number: it beat silence by +29.2. Against the bar it scores 0."""
    card = evaluate(_TopicPolicy(TestReadmeResultsAreCurrent.TOPIC_WORDS), items)
    assert card.ics >= pair_blind_ics(items)


def test_always_does_not_beat_the_bar(items):
    assert evaluate(AlwaysPolicy(), items).ics >= pair_blind_ics(items)


def test_the_bar_is_clearable(items):
    """Skyline reads the decider, so it must clear the bar -- the task stays solvable."""
    card = evaluate(SkylinePolicy(), items)
    assert card.ics < pair_blind_ics(items)
    assert card.hard_violations == 0


def test_a_cheap_hard_violation_is_still_refused():
    """Idle under DND costs 1 x 2 = 2 to interrupt; a value-3 miss costs 3. Speaking
    on both sides is cheaper -- and a hard violation, so the bar must stay silent.
    No shipped pair has this shape, which is why only a constructed one tests it."""
    from tactbench.schema import Activity, GoldLabel, Item, Moment, Signal, Source, UserState

    state = UserState(activity=Activity.IDLE, dnd=True)

    def side(mid: str, surface: bool) -> Item:
        moment = Moment(
            id=mid, signals=[Signal(source=Source.MESSAGE, content="x")], user_state=state,
            family="synthetic",
        )  # fmt: skip
        label = GoldLabel(moment_id=mid, should_surface=surface, value=3 if surface else 0)
        return Item(moment=moment, label=label)

    pair = [side("synthetic-pos-0000", True), side("synthetic-near-0000", False)]
    assert score(pair, [Decision(moment_id=i.moment.id, surface=True) for i in pair], "x").ics < 3
    assert not any(d.surface for d in pair_blind_decisions(pair))


def test_the_readme_quotes_the_bar_it_measures():
    import re
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    found = re.findall(r"sits\s+at ICS (\d+) against silence's (\d+)", readme)
    assert len(found) == 1, "the README sentence quoting the bar was reworded or duplicated"
    dev = load("v1", "dev")
    assert (float(found[0][0]), float(found[0][1])) == (pair_blind_ics(dev), silence_ics(dev))


class TestNoKeywordPolicyBeatsTheBar:
    """The data constraint that replaces "no keyword policy may beat silence". R24.

    ``test_no_pair_blind_policy_beats_the_bar`` checks the optimizer and cannot
    fail on any dataset. This one constrains the *data*: if a generator change lets
    a surface keyword answer the two sides of a pair differently, a single-word
    policy gains on the bar and this fails. Review of R24 found the original
    replacement invariant had no such test.

    Exhaustive over every word in the split, speak-if-present and speak-if-absent.
    """

    @staticmethod
    def _tokens(item):
        return set(re.findall(r"[a-z]+", " ".join(s.content for s in item.moment.signals).lower()))

    def test_no_single_word_policy_reaches_the_bar(self, items):
        bar = pair_blind_ics(items)
        tokens = [self._tokens(i) for i in items]
        beaten = []
        for word in sorted(set().union(*tokens)):
            for absent in (False, True):
                ds = [
                    Decision(moment_id=i.moment.id, surface=(word in t) != absent)
                    for i, t in zip(items, tokens, strict=True)
                ]
                card = score(items, ds, word)
                if card.ics < bar:
                    beaten.append((word, "absent" if absent else "present", card.ics))
        assert not beaten, f"single-word policies beat the pair-blind bar ({bar}): {beaten}"

    @pytest.mark.parametrize(
        "speak_on,quiet_on",
        [({"admitt"}, {"discharg"}), ({"hospital"}, {"home"}), ({"nearby"}, set()),
         ({"emergency", "er"}, {"routine"})],
    )  # fmt: skip
    def test_the_round_9_keyword_sets_do_not_reach_the_bar(self, items, speak_on, quiet_on):
        policy = TestNoKeywordExploit._KeywordPolicy(speak_on, quiet_on)
        assert evaluate(policy, items).ics >= pair_blind_ics(items)
