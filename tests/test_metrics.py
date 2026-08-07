"""Tests for the scoring rules.

These pin down the properties the benchmark's claims rest on: that cost is
asymmetric, that protected states are treated as violations rather than averaged
away, and that the silence baseline is a meaningful bar.
"""

from __future__ import annotations

import hashlib
from collections import Counter

import pytest

from tactbench.audit import (
    LeakageReport,
    _NaiveBayes,
    item_bigrams,
    item_tokens,
    lexical_leakage,
    ngram_leakage,
    verbatim_overlap,
)
from tactbench.cli import _bucket
from tactbench.dataset.generate import generate
from tactbench.dataset.loader import load
from tactbench.metrics import score, score_item
from tactbench.policies.base import Policy
from tactbench.policies.builtin import AlwaysPolicy, HeuristicPolicy, NeverPolicy
from tactbench.policies.skyline import PartialSkylinePolicy, SkylinePolicy
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
    pair_key,
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
        assert score(items, decisions, "a").ics == score(items, decisions, "a", base_rate=1.0).ics

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
        """Two-sided, deliberately.

        Round 10: this assertion was ``accuracy < 0.70`` — an upper bound only.
        A probe that is reliably *wrong* passes it trivially while being exactly
        as useful to a submitter, who negates it for free. Threshold on distance
        from chance, never on accuracy.
        """
        items = generate(n_pairs_per_scenario=10)
        report = lexical_leakage(items)
        assert report.exploitable_accuracy < 0.70, (
            f"bag-of-words probe reaches {report.accuracy:.1%} without seeing user "
            f"state — worth {report.exploitable_accuracy:.1%} once its polarity is "
            "chosen; the pairing has stopped forcing a judgment"
        )

    def test_the_unigram_probe_is_blind_to_role_permutation(self):
        """Documents *why* the unigram number is 50.0%, so it is not misread again.

        Both sides of a pair carry the same token multiset by construction, so a
        bag-of-words model cannot separate them even in principle. The 50.0% the
        audit reports is the probe's blind spot, not the dataset's resistance --
        an order-aware probe sees the difference immediately.
        """
        items = generate(n_pairs_per_scenario=10)
        by_pair: dict[str, list[Item]] = {}
        for item in items:
            by_pair.setdefault(pair_key(item.moment.id), []).append(item)

        for key, pair in by_pair.items():
            a, b = pair
            assert Counter(item_tokens(a)) == Counter(item_tokens(b)), (
                f"{key}: sides differ in token multiset — not a pure permutation"
            )

        assert lexical_leakage(items).accuracy == pytest.approx(0.5, abs=0.01)
        assert ngram_leakage(items).accuracy > 0.90, (
            "bigrams must separate what unigrams cannot; if this drops, the "
            "dataset changed and the recorded finding needs re-measuring"
        )

    def test_the_probe_still_catches_a_real_tell(self):
        """Guard against the audit going quiet for the wrong reason.

        Every family now probes at exactly 50.0%, which is the design working: a
        bag-of-words model cannot see word order, and a role permutation is only
        a reordering. But "always 50.0%" and "broken and reporting 50.0%" look
        identical from the outside, so pin that a genuine one-sided token still
        registers.
        """
        items = generate(n_pairs_per_scenario=10)
        for item in items:
            tell = "aardvark" if item.label.should_surface else "zeppelin"
            item.moment.signals[0].content += f" {tell}"

        report = lexical_leakage(items)
        assert report.accuracy > 0.70, "a one-sided token must still be detected"
        assert "LEAKING" in report.verdict()

    @pytest.mark.parametrize(
        "accuracy, expect_leaking",
        [
            (0.50, False),
            (0.62, False),  # within the 0.65 verdict threshold, either way
            (0.38, False),
            (0.72, True),  # reliably right
            (0.28, True),  # reliably WRONG -- the case the old audit called clean
        ],
    )
    def test_leakage_is_distance_from_chance_not_accuracy(self, accuracy, expect_leaking):
        """The audit's verdict must be symmetric about chance.

        Round 10: both assertions were upper bounds, so ``meeting_prep`` at 32.8%
        printed as ``at chance``. It was not at chance — it was a 67.2% classifier
        with a minus sign, and negating a classifier is free. A one-sided check
        cannot see an inverted leak, which is the exact kind a broken pair split
        produces.
        """
        report = LeakageReport(accuracy=accuracy, folds=[accuracy], n=100)

        assert report.leakage == pytest.approx(abs(accuracy - 0.5))
        assert report.exploitable_accuracy == pytest.approx(0.5 + abs(accuracy - 0.5))
        assert ("LEAKING" in report.verdict()) is expect_leaking

        mirrored = LeakageReport(accuracy=1 - accuracy, folds=[1 - accuracy], n=100)
        assert mirrored.leakage == pytest.approx(report.leakage), (
            "a probe and its negation leak identically; only the sign differs"
        )
        assert ("LEAKING" in mirrored.verdict()) is expect_leaking

    def test_every_family_sits_at_the_chance_floor(self):
        """**Every** family, with no exceptions.

        Round 1 exempted quiet_hours, reasoning that a medical emergency is not a
        rearrangement of a routine check-in so severity was irreducibly lexical.
        Round 9 measured what that cost: two substrings captured the family, and
        because it carries the highest false-positive cost it drove 82% of the
        headline gap -- so a policy matching those two tokens and coin-flipping
        elsewhere beat silence, while the honest heuristic did not.

        The exemption was wrong, not irreducible. Moving the emergency into the
        shared body and making the decider *who can actually get there* permutes
        cleanly. There is no exempt family now, and adding one requires
        demonstrating that no keyword policy can exploit it -- see
        TestNoKeywordExploit.
        """
        items = generate(n_pairs_per_scenario=10)
        permutable = {i.moment.family for i in items}
        assert len(permutable) >= 9, "new families must be added to the audit"
        for family in sorted(permutable):
            subset = [i for i in items if i.moment.family == family]
            report = lexical_leakage(subset)
            # Two-sided. `meeting_prep` sat at 32.8% under the old one-sided bound
            # and printed as "at chance"; negating that probe scores 67.2%.
            assert report.exploitable_accuracy < 0.60, (
                f"{family} leaks at {report.accuracy:.1%} "
                f"(worth {report.exploitable_accuracy:.1%} after choosing polarity)"
            )

    def test_pairs_share_an_identical_user_state(self):
        """If state differed across a pair it would give the answer away as surely
        as vocabulary did. State determines the *cost* of speaking, not whether."""
        items = generate(n_pairs_per_scenario=5)
        by_pair: dict[str, list] = {}
        for item in items:
            by_pair.setdefault(pair_key(item.moment.id), []).append(item)
        # Every group must actually BE a pair. Guarding the assertion with
        # `if len(pair) == 2` made it vacuous the moment grouping drifted --
        # the same shape of hole this round found in the split itself.
        assert by_pair, "no pairs generated"
        for key, pair in by_pair.items():
            assert len(pair) == 2, f"{key} grouped {len(pair)} items, not 2"
            assert pair[0].moment.user_state == pair[1].moment.user_state, key

    def test_the_two_sides_are_equal_but_not_the_same_objects(self):
        """Byte-identical text, independent objects.

        The shared body must compare equal across a pair. It must not *be* the
        same ``Signal`` instance: that makes the halves silently coupled, so
        editing one item's text edits its partner's. Found in Round 10 by a test
        that appended a per-label tell to every item and produced a dataset where
        both sides carried both tells. Any in-place augmentation or paraphrase
        pass would have hit it the same way.
        """
        items = generate(n_pairs_per_scenario=5)
        by_pair: dict[str, list[Item]] = {}
        for item in items:
            by_pair.setdefault(pair_key(item.moment.id), []).append(item)

        for key, pair in by_pair.items():
            if len(pair) != 2:
                continue
            a, b = pair
            assert len(a.moment.signals) == len(b.moment.signals), f"{key}: length mismatch"
            # The body is every signal but the last; the last one is the decider,
            # which is exactly what differs. `any()` here would pass while a
            # paraphrase pass rewrote all but one body signal -- and paraphrase
            # expansion is a named priority in CLAUDE.md.
            body = list(zip(a.moment.signals[:-1], b.moment.signals[:-1], strict=True))
            assert body, f"{key}: no shared body to compare"
            for x, y in body:
                assert x.content == y.content, f"{key}: body differs -- not a permutation"
                assert x is not y, f"{key}: pair sides share a mutable Signal instance"
            assert a.moment.user_state is not b.moment.user_state, f"{key}: shared UserState"

        # And prove the decoupling behaves: mutating one side leaves the other alone.
        a, b = next(p for p in by_pair.values() if len(p) == 2)
        before = b.moment.signals[0].content
        a.moment.signals[0].content += " sentinel"
        assert b.moment.signals[0].content == before


class TestSplitIntegrity:
    """A pair must never be divided by the dev/test split.

    Round 10. ``cli.build`` bucketed on ``moment.id``, which names an *item*, so
    the two halves of a pair were assigned independently and 72 of 180 pairs
    landed on opposite sides. Because a pair shares a byte-identical body and
    differs only in which noun plays which role, each orphaned test item was a
    near-verbatim copy of a published dev item under the opposite label:

    * 77% of the held-out split had its partner sitting in ``dev.jsonl``
    * negating that partner's label answered **72 of 72** correctly
    * 88.3% of the test split, by table lookup, with no model at all

    The audit had always kept pairs whole across its own folds and said why. The
    artifact it was auditing did not. These tests close that gap at the split,
    where it originates, rather than at any one consumer of it.
    """

    def _splits(self, pairs: int = 20):
        items = generate(n_pairs_per_scenario=pairs, seed=20260726)
        dev = [i for i in items if _bucket(pair_key(i.moment.id)) < 60]
        test = [i for i in items if _bucket(pair_key(i.moment.id)) >= 60]
        return dev, test

    def test_no_pair_spans_the_split(self):
        dev, test = self._splits()
        overlap = {pair_key(i.moment.id) for i in dev} & {pair_key(i.moment.id) for i in test}
        assert not overlap, (
            f"{len(overlap)} pairs are divided across dev and test; each one publishes "
            "a near-verbatim copy of a held-out item under the opposite label"
        )

    def test_every_pair_is_whole_within_its_split(self):
        for name, split in zip(("dev", "test"), self._splits(), strict=True):
            counts = Counter(pair_key(i.moment.id) for i in split)
            orphans = [k for k, n in counts.items() if n != 2]
            assert not orphans, f"{name} holds {len(orphans)} half-pairs, e.g. {orphans[:3]}"

    def test_the_shipped_splits_are_whole(self):
        """Not just the generator — the files actually committed to ``data/``."""
        for name in ("dev", "test"):
            counts = Counter(pair_key(i.moment.id) for i in load("v1", name))
            orphans = [k for k, n in counts.items() if n != 2]
            assert not orphans, f"shipped {name}.jsonl holds {len(orphans)} half-pairs"

        dev_keys = {pair_key(i.moment.id) for i in load("v1", "dev")}
        test_keys = {pair_key(i.moment.id) for i in load("v1", "test")}
        assert not (dev_keys & test_keys)

    def test_the_shipped_files_are_what_the_generator_produces(self):
        """Closes the round's own defect shape, one level up.

        The other tests here check that the *committed* ``data/v1`` is pair-whole.
        Nothing checked that it is still what ``tactbench build`` writes. Change a
        threshold or a scenario's phrasing and forget to rebuild, and the shipped
        files stay pair-whole, every assertion above stays green, and every number
        in the README is computed on a dataset the generator no longer produces --
        "the invariant enforced in the checker and violated in the artifact", again.
        """
        dev, test = self._splits()
        for name, rebuilt in (("dev", dev), ("test", test)):
            shipped = load("v1", name)
            assert [i.model_dump_json() for i in shipped] == [
                i.model_dump_json() for i in rebuilt
            ], f"data/v1/{name}.jsonl is stale -- re-run `uv run tactbench build`"

    def test_partner_lookup_cannot_answer_the_held_out_split(self):
        """The zero-model exploit, as an executable assertion.

        ``moment.id`` is public, so a test item's pair key is public, so its
        partner in the *published* dev split is findable. A pair has one speak
        side and one stay-quiet side, so the partner's label gives the answer by
        negation. This must recover nothing.
        """
        dev, test = load("v1", "dev"), load("v1", "test")
        label_by_pair = {pair_key(i.moment.id): i.label.should_surface for i in dev}

        answerable = [i for i in test if pair_key(i.moment.id) in label_by_pair]
        assert not answerable, (
            f"{len(answerable)}/{len(test)} held-out items ({len(answerable) / len(test):.0%}) "
            "can be answered by negating a label published in dev"
        )


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


class TestMetricDiscrimination:
    """ICS must rank *partial* comprehension, not merely separate none from perfect.

    Six rounds of leaderboards showed every real policy at chance precision and
    the skyline at 1.000, with nothing measured in between. A metric that is flat
    across that range cannot tell a mediocre assistant from a good one -- and the
    middle is where every real system lands, so a flat metric would be broken for
    exactly the systems the benchmark exists to score.

    Full sweep and the reasoning: experiments/discrimination_sweep.py
    """

    SWEEP = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)

    def _ics(self, items, p, reference):
        return evaluate(PartialSkylinePolicy(p), items, reference=reference).ics

    def test_ics_decreases_monotonically_with_comprehension(self):
        items = generate(n_pairs_per_scenario=10)
        reference = silence_ics(items)
        scores = [self._ics(items, p, reference) for p in self.SWEEP]
        for a, b in zip(scores, scores[1:], strict=False):
            assert a >= b, f"ICS rose as comprehension rose: {scores}"

    def test_the_sweep_is_anchored_at_both_ends(self):
        """p=1 must reproduce the skyline exactly; p=0 must lose to silence."""
        items = generate(n_pairs_per_scenario=10)
        reference = silence_ics(items)
        assert self._ics(items, 1.0, reference) == 0.0
        assert self._ics(items, 0.0, reference) > reference

    def test_comprehension_gains_register_across_the_whole_range(self):
        """Not just near the endpoints -- a metric flat through the middle would
        pass the anchoring test above while discriminating nothing."""
        items = generate(n_pairs_per_scenario=10)
        reference = silence_ics(items)
        scores = [self._ics(items, p, reference) for p in self.SWEEP]
        span = scores[0] - scores[-1]
        steps = [a - b for a, b in zip(scores, scores[1:], strict=False)]
        assert min(steps) > 0.02 * span, f"a step barely moved ICS: {steps}"

    def test_comprehension_set_is_nested(self):
        """Raising p only ever ADDS comprehended moments. Without this, a
        non-monotonic sweep could be resampling noise rather than a metric flaw."""
        ids = [i.moment.id for i in generate(n_pairs_per_scenario=5)]
        low, high = PartialSkylinePolicy(0.3), PartialSkylinePolicy(0.7)
        for mid in ids:
            if low.comprehends(mid):
                assert high.comprehends(mid)

    def test_partial_rejects_a_fraction_outside_the_unit_interval(self):
        with pytest.raises(ValueError):
            PartialSkylinePolicy(1.5)


class TestPerFamilyReporting:
    """Where a system fails matters as much as how often.

    Round 8 measured whether an ICS score can be read back as a "comprehension
    fraction" using round 7's curve. It cannot: three policies understanding the
    same share of moments (true fractions within 0.015 of each other) landed at
    implied fractions spanning 0.30, purely from *which* families they understood.

    ICS weights by consequence, which is correct -- a system that handles the
    expensive families really is better. But that makes a single number a
    conflation of how much is understood with which parts, so the per-family
    breakdown is the honest reporting unit.

    See experiments/implied_comprehension_probe.py.
    """

    def test_every_family_is_reported(self):
        items = generate(n_pairs_per_scenario=5)
        card = evaluate(HeuristicPolicy(), items)
        assert set(card.by_family) == {i.moment.family for i in items}

    def test_a_perfect_policy_costs_nothing_in_any_family(self):
        items = generate(n_pairs_per_scenario=5)
        card = evaluate(SkylinePolicy(), items)
        assert all(v == 0.0 for v in card.by_family.values())

    def test_family_costs_reflect_the_asymmetry(self):
        """quiet_hours pairs sleep with DND, so speaking wrongly there costs 10x
        what it costs in a low-stakes family. A policy that always speaks must
        show that, or the breakdown is not carrying consequence."""
        items = generate(n_pairs_per_scenario=5)
        card = evaluate(AlwaysPolicy(), items)
        assert card.by_family["quiet_hours"] > card.by_family["commerce"]

    def test_breakdown_distinguishes_policies_the_headline_ranks_adjacently(self):
        """The point of the breakdown: two policies can sit near each other on ICS
        while failing in completely different places."""
        items = generate(n_pairs_per_scenario=10)
        heuristic = evaluate(HeuristicPolicy(), items).by_family
        always = evaluate(AlwaysPolicy(), items).by_family
        assert any(abs(heuristic[f] - always[f]) > 1.0 for f in heuristic), (
            "per-family costs are indistinguishable between very different policies"
        )


class TestNoKeywordExploit:
    """No small set of keywords in one family may beat silence.

    Round 9's finding. `quiet_hours` carries the highest false-positive cost in
    the benchmark (asleep, DND-doubled), so it drove **82% of the gap** between
    `always` and silence from 13% of the moments. That concentration is correct --
    waking someone at 3am really is the most expensive error the cost model knows.

    The bug was that the same family was the one exempted from the shortcut audit.
    Concentration plus exploitability meant a policy matching two substrings and
    coin-flipping on the other eight families **beat silence at +28.0**, while the
    hand-written structural heuristic scored -22.9.

    Concentration is fine. Concentration in an exploitable family is not.
    """

    class _KeywordPolicy(Policy):
        """Matches a keyword set; coin-flips elsewhere, deterministically."""

        name = "keyword-exploit"

        def __init__(self, speak_on: set[str], quiet_on: set[str]):
            self.speak_on, self.quiet_on = speak_on, quiet_on

        def decide(self, moment):
            text = " ".join(s.content for s in moment.signals).lower()
            if any(k in text for k in self.speak_on):
                return Decision(moment_id=moment.id, surface=True, intent="alert")
            if any(k in text for k in self.quiet_on):
                return Decision(moment_id=moment.id, surface=False)
            flip = hashlib.sha256(moment.id.encode()).digest()[4] % 2 == 0
            return Decision(moment_id=moment.id, surface=flip, intent="alert" if flip else None)

    @pytest.mark.parametrize(
        "speak_on,quiet_on",
        [
            ({"admitt"}, {"discharg"}),  # the original round 9 exploit
            ({"hospital"}, {"home"}),
            ({"nearby"}, set()),
            ({"emergency", "er"}, {"routine"}),
        ],
    )
    def test_a_keyword_policy_cannot_beat_silence(self, speak_on, quiet_on):
        items = generate(n_pairs_per_scenario=10)
        reference = silence_ics(items)
        card = evaluate(self._KeywordPolicy(speak_on, quiet_on), items, reference=reference)
        assert card.ics > reference, (
            f"keywords {speak_on | quiet_on} beat silence "
            f"({card.ics:.1f} vs {reference:.1f}) — a family is exploitable"
        )


class TestOrderSensitiveShortcut:
    """Round 11. The standing rule is that no surface policy may beat silence.

    ``TestNoKeywordExploit`` enforces it for substring matchers. This class
    enforces it for the representation those tests could not express: **word
    order**. Both sides of a pair carry an identical token multiset, so every
    unigram check in this file is structurally blind to the one thing that
    actually differs between them.

    It is currently violated, and the violation is recorded rather than softened.
    Each family has only two structural frames, and the frame carries the label
    (``pickup_you`` -> speak, ``primary_you`` -> speak). R12 varied the entities
    instead, cutting verbatim overlap 91.2% -> 29.8% and moving the exploit 1.3
    points; the bigram still scores 97.5% on held-out items whose phrasing never
    appeared in dev. The fix is more frames, with some held out of dev entirely --
    a dataset rebuild, not an assertion change. See
    ``experiments/order_sensitive_probe.py`` and the queue.
    """

    class _NgramPolicy(Policy):
        """A submitter's shortcut: fit bag-of-bigrams on the published dev split.

        Sees only signal text -- no user state, no DND, no slices. Exactly the
        information the benchmark claims is insufficient.
        """

        name = "ngram-exploit"

        def __init__(self, train: list[Item]):
            self.model = _NaiveBayes()
            self.model.fit([(item_bigrams(i), i.label.should_surface) for i in train])

        def decide(self, moment):
            probe = Item.model_construct(moment=moment, label=None)
            speak = self.model.predict(item_bigrams(probe))
            return Decision(moment_id=moment.id, surface=speak, intent="alert" if speak else None)

    @pytest.mark.xfail(
        strict=True,
        reason="OPEN DEFECT (R11, reduced but not closed by R12). 29.8% of "
        "held-out decider sentences still appear byte-identically in the published "
        "dev split (was 91.2%); a zero-model dict lookup scores 64.9% (was 95.6%). "
        "Holding frames out of dev closes this by construction; strict=True makes "
        "the build fail when it lands.",
    )
    def test_the_held_out_split_is_not_published_verbatim(self):
        """The dominant mechanism, measured separately from the model.

        Round 11 first reported the bigram result as generalisation to unseen
        pairs. Review showed most of it is not: the *pairs* are new, but the
        *sentences* are not. This is a near-duplicate leak and it is a different
        defect from Round 10's pair-key split -- a split can be perfectly
        pair-whole and still publish its own answers.
        """
        overlap = verbatim_overlap(load("v1", "dev"), load("v1", "test"))
        assert overlap["decider_published"] < 0.10, (
            f"{overlap['decider_published']:.1%} of held-out decider sentences are "
            f"published verbatim in dev; a dict lookup scores "
            f"{overlap['lookup_accuracy']:.1%} with no model"
        )

    def test_bigrams_transfer_to_held_out_pairs(self):
        """Pins the measured effect so a dataset change forces a re-measure.

        Note this asserts the DEFECT exists. It is not an xfail because it is a
        characterisation of the current data, not the invariant -- but it will go
        red when paraphrase expansion lands, and that is intended. See the two
        strict xfails in this class for the invariants themselves.
        """
        dev, test = load("v1", "dev"), load("v1", "test")
        assert not ({pair_key(i.moment.id) for i in dev} & {pair_key(i.moment.id) for i in test}), (
            "this measurement is only meaningful against a genuinely held-out split"
        )

        model = _NaiveBayes()
        model.fit([(item_bigrams(i), i.label.should_surface) for i in dev])
        hits = sum(1 for i in test if model.predict(item_bigrams(i)) == i.label.should_surface)
        assert hits / len(test) > 0.90, (
            "a bigram model fit on dev should still transfer to held-out pairs; "
            "if this drops, the templates were varied and the finding needs re-measuring"
        )

    @pytest.mark.xfail(
        strict=True,
        reason="OPEN DEFECT (R11, refined by R12). Each family has only TWO "
        "structural frames, and the frame carries the label, so a bigram model fit "
        "on dev scores +98.1 vs silence on held-out test (ICS 3.0 against a "
        "skyline of 0.0). R12 removed most of the duplicate text R11 blamed and "
        "the exploit moved 1.3 points; the bigram still scores 97.5% on held-out "
        "items whose phrasing never appeared in dev. The fix is more frames with "
        "some held out of dev, not a weaker bound. strict=True so this fails the "
        "build the moment the dataset is repaired, forcing the assertion to be "
        "tightened rather than forgotten.",
    )
    def test_a_surface_ngram_policy_cannot_beat_silence(self):
        dev, test = load("v1", "dev"), load("v1", "test")
        reference = silence_ics(test)
        card = evaluate(self._NgramPolicy(dev), test, reference=reference)
        assert card.ics > reference, (
            f"a bag-of-bigrams fit on dev beats silence on held-out test "
            f"({card.ics:.1f} vs {reference:.1f}, {card.ics_normalized:+.1f}) — "
            "the dataset is solvable by surface pattern matching"
        )
