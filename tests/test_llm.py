"""Tests for the LLM policy that need no API key.

The prompt-leak test is the load-bearing one. A moment's ``slices`` field contains
tags like ``near_miss`` and ``already_handled`` -- serializing them into the prompt
would hand the model the answer and produce a meaningless score. That would be very
easy to do by accident and very hard to notice in the results.
"""

from __future__ import annotations

import http.server
import json
import threading

import pytest

from tactbench.dataset.generate import generate
from tactbench.policies.llm import (
    NAIVE_SYSTEM,
    RUBRIC_SYSTEM,
    LLMPolicy,
    MissingCredential,
    is_unparsed,
    parse_response,
    render_moment,
    unparsed_rate,
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


class TestParsingIsStrictAboutTheDecision:
    """Round 23: the parser decides what a model *said*, so it must not guess.

    ``bool("false")`` is ``True`` in Python. Before R23 a model that quoted its
    boolean -- common in small open-weight models -- was scored as speaking when it
    had answered "stay silent". And because unparseable output is scored as silence,
    which is exactly the bar, a model that never produced valid JSON would tie the
    bar while looking like a real result. Both are checked here.
    """

    @pytest.mark.parametrize("raw", ['"false"', '"False"', '"no"', "0"])
    def test_a_quoted_or_numeric_no_is_silence(self, raw):
        d = parse_response(f'{{"surface": {raw}, "confidence": 0.9}}', "m1")
        assert d.surface is False
        assert not is_unparsed(d)

    @pytest.mark.parametrize("raw", ['"true"', '"True"', '"yes"', "1"])
    def test_a_quoted_or_numeric_yes_is_speech(self, raw):
        d = parse_response(f'{{"surface": {raw}, "confidence": 0.9}}', "m1")
        assert d.surface is True
        assert not is_unparsed(d)

    @pytest.mark.parametrize(
        "text",
        [
            '{"confidence": 0.9}',  # no decision at all
            '{"surface": "maybe", "confidence": 0.9}',
            '{"surface": null}',
            "no json here",
            '{"surface": tru',
        ],
    )
    def test_no_decision_is_silence_and_is_flagged(self, text):
        d = parse_response(text, "m1")
        assert d.surface is False
        assert is_unparsed(d), "a non-answer must be countable, or it reads as the bar"

    def test_a_clean_answer_is_not_flagged(self):
        assert not is_unparsed(parse_response('{"surface": false}', "m1"))

    def test_the_first_object_wins_over_trailing_braces(self):
        d = parse_response('{"surface": true, "confidence": 0.7} (see {notes})', "m1")
        assert d.surface is True and not is_unparsed(d)

    def test_unparsed_rate_counts_only_non_answers(self):
        ds = [
            parse_response('{"surface": true}', "a"),
            parse_response("garbage", "b"),
            parse_response('{"surface": false}', "c"),
            parse_response('{"surface": "perhaps"}', "d"),
        ]
        assert unparsed_rate(ds) == 0.5


class _FakeOpenAI(http.server.BaseHTTPRequestHandler):
    seen: list[dict] = []

    def do_POST(self):  # noqa: N802 - stdlib name
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FakeOpenAI.seen.append(
            {"path": self.path, "body": body, "auth": self.headers.get("Authorization")}
        )
        reply = {"choices": [{"message": {"content": '{"surface": "false", "confidence": 0.8}'}}]}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_server():
    _FakeOpenAI.seen = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()
    srv.server_close()


class TestLocalProvider:
    """An OpenAI-compatible endpoint -- llama.cpp, Ollama, vLLM, LM Studio.

    Lets open-weight models run with no API key and no spend. Tested against a
    stdlib fake, so the wire format is checked without a model.
    """

    def test_needs_no_key_and_sends_the_documented_prompt(self, fake_server, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        policy = LLMPolicy(
            provider="local", model="qwen-test", variant="rubric", base_url=fake_server
        )
        moment = generate(n_pairs_per_scenario=1)[0].moment
        d = policy.decide(moment)

        (call,) = _FakeOpenAI.seen
        assert call["path"] == "/v1/chat/completions"
        body = call["body"]
        assert body["model"] == "qwen-test"
        assert body["temperature"] == 0
        assert body["messages"][0] == {"role": "system", "content": RUBRIC_SYSTEM}
        assert body["messages"][1] == {"role": "user", "content": render_moment(moment)}
        # and the quoted "false" the fake returns is silence, not speech
        assert d.surface is False and not is_unparsed(d)

    def test_name_records_the_model(self, fake_server):
        policy = LLMPolicy(
            provider="local", model="qwen-test", variant="naive", base_url=fake_server
        )
        assert policy.name == "llm:naive:qwen-test"

    def test_local_requires_an_explicit_model(self, fake_server):
        with pytest.raises(ValueError):
            LLMPolicy(provider="local", base_url=fake_server)

    def test_without_a_system_role_the_same_text_leads_the_user_turn(self, fake_server):
        """For chat templates that reject a system turn (Gemma 2). The prompt must
        be the documented one, byte for byte -- only the turn it arrives in moves."""
        policy = LLMPolicy(
            provider="local",
            model="gemma-test",
            variant="naive",
            base_url=fake_server,
            system_role=False,
        )
        moment = generate(n_pairs_per_scenario=1)[0].moment
        policy.decide(moment)
        (call,) = _FakeOpenAI.seen
        assert call["body"]["messages"] == [
            {"role": "user", "content": f"{NAIVE_SYSTEM}\n\n{render_moment(moment)}"}
        ]

    def test_dropping_the_system_role_is_local_only(self):
        with pytest.raises(ValueError):
            LLMPolicy(provider="anthropic", model="x", system_role=False)
