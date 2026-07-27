"""Tests for the scoring rules.

These pin down the properties the benchmark's claims rest on: that cost is
asymmetric, that protected states are treated as violations rather than averaged
away, and that the silence baseline is a meaningful bar.
"""

from __future__ import annotations

import pytest

from tactbench.audit import lexical_leakage
from tactbench.dataset.generate import generate
from tactbench.metrics import score, score_item
from tactbench.policies.builtin import AlwaysPolicy, HeuristicPolicy, NeverPolicy
from tactbench.policies.skyline import SkylinePolicy
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

    def test_task_is_solvable(self):
        """The benchmark must not be degenerate.

        Once lexical shortcuts were removed, every reference baseline scored worse
        than silence -- which invites the objection that "beat silence" is an
        impossible bar. The skyline answers it: perfect comprehension of the same
        text, with no access to labels, clears silence by a wide margin. If this
        ever fails, the dataset has become unsolvable rather than merely hard.
        """
        items = generate(n_pairs_per_scenario=5)
        ref = silence_ics(items)
        card = evaluate(SkylinePolicy(), items, reference=ref)
        assert card.ics < ref, "skyline must clear the silence bar"
        assert card.hard_violations == 0

    def test_skyline_labels_are_self_consistent(self):
        """The skyline resolves each family's deciding relation from text alone. If
        it disagrees with a gold label, the dataset contradicts its own stated
        semantics -- which is how an inverted travel pair was caught."""
        items = generate(n_pairs_per_scenario=5)
        card = evaluate(SkylinePolicy(), items)
        assert card.counts["fp"] == 0 and card.counts["fn"] == 0

    def test_lexical_heuristic_is_near_chance(self):
        """A rules baseline with no comprehension should get no traction. Scoring
        well here would mean the shortcuts are back."""
        items = generate(n_pairs_per_scenario=10)
        card = evaluate(HeuristicPolicy(), items)
        assert card.precision_at_interrupt == pytest.approx(0.5, abs=0.15)


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


class TestBaseRate:
    """The split is balanced 50/50 so the near-miss contrast is legible. Production
    is not: a deployed assistant sees vastly more quiet moments than loud ones.
    Importance-weighting the quiet ones is what makes the numbers decision-relevant.
    """

    def test_base_rate_of_one_matches_the_default(self):
        items = generate(n_pairs_per_scenario=5)
        decisions = run_policy(AlwaysPolicy(), items)
        assert score(items, decisions, "a").ics == score(
            items, decisions, "a", base_rate=1.0
        ).ics

    def test_below_one_is_rejected(self):
        items = generate(n_pairs_per_scenario=2)
        with pytest.raises(ValueError):
            score(items, run_policy(AlwaysPolicy(), items), "a", base_rate=0.5)

    def test_a_realistic_prior_punishes_false_positives(self):
        items = generate(n_pairs_per_scenario=5)
        decisions = run_policy(AlwaysPolicy(), items)
        cheap = score(items, decisions, "a", base_rate=1.0).ics
        realistic = score(items, decisions, "a", base_rate=100.0).ics
        assert realistic > 50 * cheap

    def test_silence_is_unaffected_by_the_base_rate(self):
        """Saying nothing produces no false positives, so reweighting the quiet
        moments cannot change its cost. This is why silence gets so much harder to
        beat as the prior gets realistic -- everything else inflates around it."""
        items = generate(n_pairs_per_scenario=5)
        assert silence_ics(items, base_rate=1.0) == silence_ics(items, base_rate=100.0)

    def test_a_perfect_policy_is_also_unaffected(self):
        items = generate(n_pairs_per_scenario=5)
        decisions = run_policy(SkylinePolicy(), items)
        assert score(items, decisions, "s", base_rate=100.0).ics == 0.0

    def test_precision_collapses_at_a_realistic_prior(self):
        """A policy that looks respectable on balanced data can be unshippable in
        production. Half-decent precision at 1:1 becomes roughly 1% at 100:1."""
        items = generate(n_pairs_per_scenario=10)
        decisions = run_policy(HeuristicPolicy(), items)
        balanced = score(items, decisions, "h", base_rate=1.0).precision_at_interrupt
        realistic = score(items, decisions, "h", base_rate=100.0).precision_at_interrupt
        assert balanced > 0.4
        assert realistic < 0.05

    def test_hard_violations_are_counted_not_reweighted(self):
        """Violations are a count of distinct moments in the benchmark, not an
        estimate of production volume. Reweighting them would conflate the two."""
        items = generate(n_pairs_per_scenario=5)
        decisions = run_policy(AlwaysPolicy(), items)
        assert (
            score(items, decisions, "a", base_rate=1.0).hard_violations
            == score(items, decisions, "a", base_rate=100.0).hard_violations
        )


class TestShortcutResistance:
    """The benchmark's central claim is that surface patterns cannot answer it.
    That claim is only worth its evidence, so it is measured, not asserted.

    v1 failed this badly: a bag-of-words probe that never saw user state hit 93.5%,
    because each scenario had one fixed phrasing per side and tokens like "hallway"
    appeared on exactly one of them. The pair construction was rebuilt around role
    permutation, which brought five of six families to the chance floor.
    """

    def test_lexical_leakage_stays_near_chance(self):
        items = generate(n_pairs_per_scenario=10)
        report = lexical_leakage(items)
        assert report.accuracy < 0.70, (
            f"bag-of-words probe reaches {report.accuracy:.1%} without seeing user "
            "state; the pairing has stopped forcing a judgment"
        )

    def test_permutable_families_sit_at_the_chance_floor(self):
        """Five families are built as token permutations and must probe at chance.

        quiet_hours is excluded on purpose: a medical emergency is not a
        rearrangement of a routine check-in, so its residual leakage is
        irreducible and is reported rather than asserted away.
        """
        items = generate(n_pairs_per_scenario=10)
        permutable = {i.moment.family for i in items} - {"quiet_hours"}
        assert len(permutable) >= 8, "new families must be added to the audit"
        for family in sorted(permutable):
            subset = [i for i in items if i.moment.family == family]
            accuracy = lexical_leakage(subset).accuracy
            assert accuracy < 0.60, f"{family} leaks at {accuracy:.1%}"

    def test_pairs_share_an_identical_user_state(self):
        """If state differed across a pair it would give the answer away as surely
        as vocabulary did. State determines the *cost* of speaking, not whether."""
        items = generate(n_pairs_per_scenario=5)
        by_pair: dict[str, list] = {}
        for item in items:
            parts = item.moment.id.split("-")
            by_pair.setdefault(f"{parts[0]}-{parts[-1]}", []).append(item)
        for key, pair in by_pair.items():
            if len(pair) == 2:
                assert pair[0].moment.user_state == pair[1].moment.user_state, key


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
