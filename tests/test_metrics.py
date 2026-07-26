"""Tests for the scoring rules.

These pin down the properties the benchmark's claims rest on: that cost is
asymmetric, that protected states are treated as violations rather than averaged
away, and that the silence baseline is a meaningful bar.
"""

from __future__ import annotations

import pytest

from tactbench.dataset.generate import generate
from tactbench.metrics import score, score_item
from tactbench.policies.builtin import AlwaysPolicy, HeuristicPolicy, NeverPolicy
from tactbench.runner import evaluate, run_policy, silence_ics
from tactbench.schema import (
    Activity,
    Decision,
    GoldLabel,
    Item,
    Moment,
    Signal,
    Source,
    UserState,
)


def _item(activity: Activity, should: bool, value: int = 2, dnd: bool = False) -> Item:
    return Item(
        moment=Moment(
            id=f"t-{activity.value}-{should}-{value}-{dnd}",
            signals=[Signal(source=Source.MESSAGE, content="something happened")],
            user_state=UserState(activity=activity, dnd=dnd),
            family="test",
        ),
        label=GoldLabel(
            moment_id=f"t-{activity.value}-{should}-{value}-{dnd}",
            should_surface=should,
            value=value,
            acceptable_intents=["alert"] if should else [],
        ),
    )


def _speak(item: Item, intent: str | None = "alert") -> Decision:
    return Decision(moment_id=item.moment.id, surface=True, intent=intent)


def _quiet(item: Item) -> Decision:
    return Decision(moment_id=item.moment.id, surface=False)


class TestAsymmetry:
    def test_interrupting_a_meeting_costs_more_than_interrupting_idle(self):
        meeting = _item(Activity.MEETING, should=False)
        idle = _item(Activity.IDLE, should=False)
        assert score_item(meeting, _speak(meeting)).cost > score_item(idle, _speak(idle)).cost

    def test_dnd_doubles_the_cost_of_speaking_wrongly(self):
        plain = _item(Activity.IDLE, should=False, dnd=False)
        quiet_hours = _item(Activity.IDLE, should=False, dnd=True)
        assert score_item(quiet_hours, _speak(quiet_hours)).cost == pytest.approx(
            2 * score_item(plain, _speak(plain)).cost
        )

    def test_missing_a_high_value_cue_costs_more_than_missing_a_low_value_one(self):
        high = _item(Activity.IDLE, should=True, value=3)
        low = _item(Activity.IDLE, should=True, value=1)
        assert score_item(high, _quiet(high)).cost > score_item(low, _quiet(low)).cost

    def test_correct_silence_is_free(self):
        item = _item(Activity.FOCUSED_WORK, should=False)
        assert score_item(item, _quiet(item)).cost == 0.0


class TestHardViolations:
    @pytest.mark.parametrize("activity", [Activity.DRIVING, Activity.SLEEPING])
    def test_speaking_wrongly_in_a_protected_state_is_a_violation(self, activity):
        item = _item(activity, should=False)
        assert score_item(item, _speak(item)).hard_violation is True

    def test_correct_speech_in_a_protected_state_is_not_a_violation(self):
        item = _item(Activity.DRIVING, should=True, value=3)
        assert score_item(item, _speak(item)).hard_violation is False

    def test_violations_are_counted_not_averaged(self):
        items = [_item(Activity.DRIVING, should=False)]
        card = score(items, [_speak(items[0])], "test")
        assert card.hard_violations == 1


class TestIntentIsSeparateFromTiming:
    """Whether to speak and what to say are different capabilities. ICS measures
    only the first; naming the wrong intent is recorded but never charged."""

    def test_wrong_intent_is_flagged_but_costs_nothing(self):
        item = _item(Activity.MEETING, should=True, value=2)
        outcome = score_item(item, _speak(item, intent="something_else"))
        assert outcome.wrong_intent is True
        assert outcome.cost == 0.0

    def test_right_moment_right_intent_is_free(self):
        item = _item(Activity.IDLE, should=True)
        assert score_item(item, _speak(item, intent="alert")).cost == 0.0

    def test_a_policy_that_names_no_intent_is_not_penalized(self):
        item = _item(Activity.IDLE, should=True)
        outcome = score_item(item, _speak(item, intent=None))
        assert outcome.wrong_intent is False

    def test_intent_accuracy_is_none_when_no_intents_are_named(self):
        items = [_item(Activity.IDLE, should=True)]
        card = score(items, [_speak(items[0], intent=None)], "no-intent")
        assert card.intent_accuracy is None

    def test_intent_accuracy_scores_only_correctly_timed_cues(self):
        good = _item(Activity.IDLE, should=True, value=2)
        bad = _item(Activity.MEETING, should=True, value=2)
        card = score(
            [good, bad],
            [_speak(good, intent="alert"), _speak(bad, intent="nonsense")],
            "half-right",
        )
        assert card.intent_accuracy == pytest.approx(0.5)


class TestMissingDecisions:
    def test_a_policy_that_skips_an_item_is_treated_as_staying_quiet(self):
        items = [_item(Activity.IDLE, should=True, value=3)]
        card = score(items, [], "silent")
        assert card.counts["fn"] == 1
        assert card.ics > 0


class TestBaselines:
    def test_always_speaking_incurs_more_cost_than_silence(self):
        items = generate(n_pairs_per_scenario=3)
        ref = silence_ics(items)
        always = score(items, run_policy(AlwaysPolicy(), items), "always", ref)
        assert always.ics > ref

    def test_silence_normalizes_to_zero(self):
        items = generate(n_pairs_per_scenario=3)
        card = evaluate(NeverPolicy(), items)
        assert card.ics_normalized == pytest.approx(0.0)

    def test_heuristic_beats_silence(self):
        """If the trivial rule set cannot beat saying nothing, the dataset has no
        headroom and the benchmark measures nothing."""
        items = generate(n_pairs_per_scenario=5)
        ref = silence_ics(items)
        card = evaluate(HeuristicPolicy(), items, reference=ref)
        assert card.ics < ref, "heuristic should clear the silence bar"


class TestHeuristicIsHonest:
    """The heuristic's score is only meaningful if it was not written by copying
    the generator. These tests enforce that, because the first draft of this
    benchmark failed it -- the rules matched phrases lifted verbatim from
    ``generate.py`` and scored a perfect 1.000/1.000 that measured nothing."""

    def test_lexicons_are_single_words_not_lifted_phrases(self):
        from tactbench.policies.builtin import RESOLUTION_WORDS, SEVERITY_WORDS

        for term in SEVERITY_WORDS | RESOLUTION_WORDS:
            assert " " not in term, f"{term!r} is a phrase; phrases invite copying"

    def test_lexicons_stay_small(self):
        """An ever-growing word list is phrase-lifting by another name."""
        from tactbench.policies.builtin import RESOLUTION_WORDS, SEVERITY_WORDS

        assert len(SEVERITY_WORDS) <= 20
        assert len(RESOLUTION_WORDS) <= 20

    def test_heuristic_does_not_solve_the_dataset(self):
        """A reference baseline that scores perfectly leaves no headroom, which
        means the benchmark has stopped measuring anything."""
        items = generate(n_pairs_per_scenario=10)
        card = evaluate(HeuristicPolicy(), items)
        assert card.ics > 0, "heuristic scores perfectly; dataset has no headroom"


class TestDataset:
    def test_generation_is_deterministic(self):
        a = generate(n_pairs_per_scenario=4, seed=99)
        b = generate(n_pairs_per_scenario=4, seed=99)
        assert [i.moment.id for i in a] == [i.moment.id for i in b]

    def test_positives_and_near_misses_are_balanced(self):
        items = generate(n_pairs_per_scenario=10)
        speak = sum(1 for i in items if i.label.should_surface)
        assert speak == len(items) - speak

    def test_every_near_miss_is_tagged_for_slicing(self):
        items = generate(n_pairs_per_scenario=2)
        for item in items:
            if not item.label.should_surface:
                assert "near_miss" in item.moment.slices

    def test_every_positive_has_at_least_one_acceptable_intent(self):
        for item in generate(n_pairs_per_scenario=2):
            if item.label.should_surface:
                assert item.label.acceptable_intents

    def test_near_misses_share_a_family_with_their_positive(self):
        """The pairing is the whole defense against keyword matching, so assert
        both halves of every family are present."""
        items = generate(n_pairs_per_scenario=2)
        families = {i.moment.family for i in items}
        for fam in families:
            fam_items = [i for i in items if i.moment.family == fam]
            assert any(i.label.should_surface for i in fam_items)
            assert any(not i.label.should_surface for i in fam_items)
