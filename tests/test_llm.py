"""Tests for the LLM policy that need no API key.

The prompt-leak test is the load-bearing one. A moment's ``slices`` field contains
tags like ``near_miss`` and ``already_handled`` -- serializing them into the prompt
would hand the model the answer and produce a meaningless score. That would be very
easy to do by accident and very hard to notice in the results.
"""

from __future__ import annotations

import pytest

from tactbench.dataset.generate import generate
from tactbench.policies.llm import (
    NAIVE_SYSTEM,
    RUBRIC_SYSTEM,
    LLMPolicy,
    MissingCredential,
    parse_response,
    render_moment,
)


class TestPromptDoesNotLeakTheAnswer:
    def test_slices_never_reach_the_prompt(self):
        for item in generate(n_pairs_per_scenario=3):
            rendered = render_moment(item.moment)
            for tag in item.moment.slices:
                assert tag not in rendered, f"slice {tag!r} leaked into the prompt"

    def test_family_is_never_disclosed_as_a_field(self):
        """The family label itself must not be handed over.

        Checked as a labelled field plus the family names that don't collide with
        legitimate content -- 'driving' and 'travel' are excluded because the
        activity value `driving` genuinely belongs in the prompt. A policy has to
        know the user is driving; it must not be told the scenario is *named*
        driving.
        """
        distinctive = {"quiet_hours", "meeting_prep", "deadline", "commerce"}
        for item in generate(n_pairs_per_scenario=3):
            rendered = render_moment(item.moment)
            # As a labelled field. Bare "family" is legitimate content -- it appears
            # as a contact class in signal metadata.
            assert "family:" not in rendered.lower()
            if item.moment.family in distinctive:
                assert item.moment.family not in rendered

    def test_moment_id_never_reaches_the_prompt(self):
        """Ids encode the label outright -- 'travel-pos-0003' versus 'travel-near-0003'."""
        for item in generate(n_pairs_per_scenario=3):
            assert item.moment.id not in render_moment(item.moment)

    def test_a_pair_renders_almost_identically(self):
        """If the two halves of a pair produced very different prompts, the model
        could separate them without judging. Same guarantee the audit checks, at
        the prompt layer."""
        items = {i.moment.id: i for i in generate(n_pairs_per_scenario=3)}
        pos = render_moment(items["travel-pos-0000"].moment)
        near = render_moment(items["travel-near-0000"].moment)
        assert pos != near
        assert len(pos) == pytest.approx(len(near), abs=8)

    def test_rendered_moment_still_carries_what_it_needs(self):
        item = generate(n_pairs_per_scenario=1)[0]
        rendered = render_moment(item.moment)
        assert "USER STATE" in rendered and "SIGNALS" in rendered
        assert item.moment.user_state.activity.value in rendered
        for signal in item.moment.signals:
            assert signal.content in rendered


class TestPrompts:
    def test_naive_variant_withholds_the_cost_structure(self):
        assert "10.0" not in NAIVE_SYSTEM
        assert "hard violation" not in NAIVE_SYSTEM.lower()

    def test_rubric_variant_discloses_it(self):
        assert "10.0" in RUBRIC_SYSTEM
        assert "asleep or driving" in RUBRIC_SYSTEM
        assert "says nothing at all is a strong baseline" in RUBRIC_SYSTEM

    def test_both_demand_strict_json(self):
        for prompt in (NAIVE_SYSTEM, RUBRIC_SYSTEM):
            assert '"surface"' in prompt and '"confidence"' in prompt


class TestResponseParsing:
    def test_parses_clean_json(self):
        d = parse_response('{"surface": true, "confidence": 0.8, "intent": "alert"}', "m1")
        assert (d.surface, d.confidence, d.intent) == (True, 0.8, "alert")

    def test_parses_json_wrapped_in_prose(self):
        d = parse_response('Sure!\n{"surface": false, "confidence": 0.9}\nHope that helps', "m1")
        assert d.surface is False and d.confidence == 0.9

    def test_unparseable_output_is_scored_as_silence(self):
        """A system that cannot produce a decision does not get to surface anything."""
        d = parse_response("I'm not sure I can answer that.", "m1")
        assert d.surface is False

    def test_malformed_json_is_scored_as_silence(self):
        assert parse_response('{"surface": tru', "m1").surface is False

    def test_out_of_range_confidence_is_clamped(self):
        assert parse_response('{"surface": true, "confidence": 7}', "m1").confidence == 1.0
        assert parse_response('{"surface": true, "confidence": -2}', "m1").confidence == 0.0

    def test_non_numeric_confidence_falls_back(self):
        assert parse_response('{"surface": true, "confidence": "high"}', "m1").confidence == 0.5

    @pytest.mark.parametrize("value", ["null", "none", "", "NULL"])
    def test_null_ish_intents_normalize_to_none(self, value):
        d = parse_response(f'{{"surface": true, "intent": "{value}"}}', "m1")
        assert d.intent is None

    def test_moment_id_is_preserved(self):
        assert parse_response('{"surface": true}', "abc-123").moment_id == "abc-123"


class TestCredentials:
    def test_missing_key_raises_an_actionable_error(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        policy = LLMPolicy(provider="anthropic")
        with pytest.raises(MissingCredential) as exc:
            policy.decide(generate(n_pairs_per_scenario=1)[0].moment)
        assert "ANTHROPIC_API_KEY" in str(exc.value)
        assert "export" in str(exc.value)

    def test_unknown_provider_is_rejected_up_front(self):
        with pytest.raises(ValueError):
            LLMPolicy(provider="hotdog")

    def test_unknown_variant_is_rejected_up_front(self):
        with pytest.raises(ValueError):
            LLMPolicy(variant="vibes")

    def test_policy_name_records_variant_and_model(self):
        policy = LLMPolicy(provider="anthropic", model="claude-sonnet-5", variant="naive")
        assert policy.name == "llm:naive:claude-sonnet-5"
