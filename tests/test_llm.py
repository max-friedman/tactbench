"""Tests for the LLM policy that need no API key.

The prompt-leak test is the load-bearing one. A moment's ``slices`` field contains
tags like ``near_miss`` and ``already_handled`` -- serializing them into the prompt
would hand the model the answer and produce a meaningless score. That would be very
easy to do by accident and very hard to notice in the results.
"""

from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

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
    #: Round 51: system-turn preflight calls, kept apart so ``seen`` still counts
    #: only the moments a run asked about.
    preflight: list[dict] = []
    #: Simulate a chat template that silently discards the system turn.
    drops_system = False
    #: Round 53: a model that receives the system turn but cannot repeat the word
    #: (Llama-3.2-1B answered "P" and "LED"), and a server that reports no usage.
    weak = False
    reports_usage = True

    def do_POST(self):  # noqa: N802 - stdlib name
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        call = {"path": self.path, "body": body, "auth": self.headers.get("Authorization")}
        messages = body["messages"]
        if not _FakeOpenAI.drops_system:
            visible = messages
        else:
            visible = [m for m in messages if m["role"] != "system"]
        secret = re.search(r"secret word is (\w+)", " ".join(m["content"] for m in visible))
        if any("secret word" in m["content"] for m in messages):
            _FakeOpenAI.preflight.append(call)
            content = secret.group(1) if secret and not _FakeOpenAI.weak else "I don't know."
        else:
            _FakeOpenAI.seen.append(call)
            content = '{"surface": "false", "confidence": 0.8}'
        reply: dict = {"choices": [{"message": {"content": content}}]}
        if _FakeOpenAI.reports_usage:
            # What a template that drops a turn would report: only what it kept.
            tokens = sum(len(m["content"].split()) + 3 for m in visible)
            reply["usage"] = {"prompt_tokens": tokens}
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
    _FakeOpenAI.preflight = []
    _FakeOpenAI.drops_system = False
    _FakeOpenAI.weak = False
    _FakeOpenAI.reports_usage = True
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


class TestCacheDoesNotKeepServerFailures:
    """Review of R23: the cache keyed only on the policy name, so after Gemma 2's
    HTTP 500s a rerun with ``--no-system-role`` would have reused the cached
    failures and scored them as silence again."""

    def _run(self, fake_server, *extra):
        from typer.testing import CliRunner

        from tactbench.cli import app

        args = ["llm", "--provider", "local", "--model", "m", "--base-url", fake_server]
        result = CliRunner().invoke(app, [*args, "--limit", "2", *extra])
        assert result.exit_code == 0, result.output

    def test_a_cached_failed_call_is_asked_again(self, fake_server, tmp_path, monkeypatch):
        from tactbench.dataset.loader import load

        monkeypatch.chdir(tmp_path)
        first = load("v1", "dev")[0].moment.id
        (tmp_path / "runs").mkdir()
        failed = {"moment_id": first, "surface": False, "rationale": "call failed: HTTP 500"}
        (tmp_path / "runs" / "llm_rubric_m-dev.jsonl").write_text(json.dumps(failed) + "\n")

        self._run(fake_server)
        assert len(_FakeOpenAI.seen) == 2  # the failed one, and the one never asked

    def test_without_a_system_role_the_cache_is_separate(self, fake_server, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        self._run(fake_server)
        self._run(fake_server, "--no-system-role")
        assert len(_FakeOpenAI.seen) == 4
        assert (tmp_path / "runs" / "llm_rubric_m-nosys-dev.jsonl").exists()


class TestCacheIsPerDatasetVersion:
    """Round 38. v2 reuses ids like ``travel-pos-0003`` for different text, and the
    cache was keyed on policy and split only -- a v2 run would have scored cached v1
    answers against v2 moments without a word."""

    def _run(self, fake_server, version):
        from typer.testing import CliRunner

        from tactbench.cli import app

        args = ["llm", "--provider", "local", "--model", "m", "--base-url", fake_server]
        result = CliRunner().invoke(app, [*args, "--limit", "2", "--version", version])
        assert result.exit_code == 0, result.output

    def test_a_v2_run_does_not_reuse_v1_answers(self, fake_server, tmp_path, monkeypatch):
        """Seed v1's cache with exactly the ids the v2 run will ask about -- the ids
        exist in both versions -- so a shared cache would answer all of them."""
        from tactbench.dataset.loader import load

        monkeypatch.chdir(tmp_path)
        (tmp_path / "runs").mkdir()
        ids = [i.moment.id for i in load("v2", "dev")[:2]]
        rows = [json.dumps({"moment_id": m, "surface": True, "rationale": "v1"}) for m in ids]
        (tmp_path / "runs" / "llm_rubric_m-dev.jsonl").write_text("\n".join(rows) + "\n")
        self._run(fake_server, "v2")
        assert len(_FakeOpenAI.seen) == 2  # asked, not read from v1's cache

    def test_v1_keeps_its_cache_name(self, fake_server, tmp_path, monkeypatch):
        """So the committed v1 results and anyone's existing v1 cache stay valid."""
        monkeypatch.chdir(tmp_path)
        self._run(fake_server, "v1")
        self._run(fake_server, "v2")
        names = sorted(p.name for p in (tmp_path / "runs").iterdir())
        assert names == ["llm_rubric_m-dev.jsonl", "llm_rubric_m-v2-dev.jsonl"]


class TestSystemTurnPreflight:
    """Round 50 found llama-cpp-python's ``mistral-instruct`` format drops the system
    turn without an error: the model answers, the answers parse, and the run scores
    a prompt the model never saw. Round 51 moves the check into the policy, so
    ``tactbench llm --provider local`` refuses such a server before asking anything.
    """

    def _invoke(self, fake_server, *extra):
        from typer.testing import CliRunner

        from tactbench.cli import app

        args = ["llm", "--provider", "local", "--model", "m", "--base-url", fake_server]
        return CliRunner().invoke(app, [*args, "--limit", "2", *extra])

    def test_the_policy_detects_a_dropped_system_turn(self, fake_server):
        policy = LLMPolicy(provider="local", model="m", base_url=fake_server)
        assert policy.system_turn_reaches_the_model() is True
        _FakeOpenAI.drops_system = True
        assert policy.system_turn_reaches_the_model() is False
        # the secret travels only in the system turn, never in the user turn; the
        # comparison call sends the same user turn alone (R53)
        for call in _FakeOpenAI.preflight:
            *system, user = call["body"]["messages"]
            assert user == {"role": "user", "content": "What is the secret word?"}
            assert all(m["role"] == "system" and "secret word is" in m["content"] for m in system)

    def test_the_cli_refuses_a_server_that_drops_it(self, fake_server, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _FakeOpenAI.drops_system = True
        result = self._invoke(fake_server)
        assert result.exit_code == 1
        assert "--no-system-role" in result.output
        assert _FakeOpenAI.seen == []  # not one moment was asked
        assert not (tmp_path / "runs").exists() or not any((tmp_path / "runs").iterdir())

    def test_the_cli_runs_once_the_check_passes(self, fake_server, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = self._invoke(fake_server)
        assert result.exit_code == 0, result.output
        # two preflight calls (with and without the system turn, R53), one run
        assert len(_FakeOpenAI.preflight) == 2 and len(_FakeOpenAI.seen) == 2

    def test_without_a_system_role_there_is_nothing_to_check(
        self, fake_server, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        _FakeOpenAI.drops_system = True
        result = self._invoke(fake_server, "--no-system-role")
        assert result.exit_code == 0, result.output
        assert _FakeOpenAI.preflight == [] and len(_FakeOpenAI.seen) == 2

    def test_a_fully_cached_run_asks_nothing(self, fake_server, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert self._invoke(fake_server).exit_code == 0
        _FakeOpenAI.preflight, _FakeOpenAI.seen = [], []
        _FakeOpenAI.drops_system = True  # rescoring a cache needs no server at all
        result = self._invoke(fake_server)
        assert result.exit_code == 0, result.output
        assert _FakeOpenAI.preflight == [] and _FakeOpenAI.seen == []

    @pytest.mark.parametrize("failure", ["refused", "http500", "no_choices"])
    def test_a_server_error_names_the_fix(self, failure, tmp_path, monkeypatch):
        """Review of R51: these were uncaught tracebacks. HTTP 500 is how Gemma 2's
        template rejects a system turn, so it must point at --no-system-role."""
        import socket

        from typer.testing import CliRunner

        from tactbench.cli import app

        class Broken(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - stdlib name
                self.rfile.read(int(self.headers["Content-Length"]))
                data = b"{}" if failure == "no_choices" else b"boom"
                self.send_response(200 if failure == "no_choices" else 500)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        monkeypatch.chdir(tmp_path)
        srv = None
        if failure == "refused":
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
        else:
            srv = http.server.HTTPServer(("127.0.0.1", 0), Broken)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            port = srv.server_port
        try:
            args = ["llm", "--provider", "local", "--model", "m", "--limit", "2"]
            url = f"http://127.0.0.1:{port}/v1"
            result = CliRunner().invoke(app, [*args, "--base-url", url])
        finally:
            if srv:
                srv.shutdown()
                srv.server_close()
        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert "--no-system-role" in result.output
        assert not (tmp_path / "runs").exists()

    def test_the_secret_word_is_drawn_per_call(self, fake_server):
        policy = LLMPolicy(provider="local", model="m", base_url=fake_server)
        for _ in range(20):
            assert policy.system_turn_reaches_the_model()
        words = {
            re.search(r"secret word is (\w+)", c["body"]["messages"][0]["content"]).group(1)
            for c in _FakeOpenAI.preflight
            if len(c["body"]["messages"]) == 2
        }
        assert len(words) > 1 and words <= set(LLMPolicy.PREFLIGHT_WORDS)

    def test_a_weak_model_that_receives_the_system_turn_passes(self, fake_server):
        """R53: Llama-3.2-1B received the system turn (59 prompt tokens against 41
        without) but repeated the word in 4 of 7 tries, so the run stopped on a false
        diagnosis. The check is structural now: the system turn must add tokens."""
        _FakeOpenAI.weak = True
        policy = LLMPolicy(provider="local", model="m", base_url=fake_server)
        assert policy.system_turn_reaches_the_model() is True

    def test_a_dropped_system_turn_fails_by_token_count(self, fake_server):
        _FakeOpenAI.drops_system = True
        policy = LLMPolicy(provider="local", model="m", base_url=fake_server)
        assert policy.system_turn_reaches_the_model() is False

    def test_without_usage_it_falls_back_to_the_secret_word(self, fake_server):
        _FakeOpenAI.reports_usage = False
        policy = LLMPolicy(provider="local", model="m", base_url=fake_server)
        assert policy.system_turn_reaches_the_model() is True
        _FakeOpenAI.drops_system = True
        assert policy.system_turn_reaches_the_model() is False
        # the known limit of the fallback: a weak model is refused
        _FakeOpenAI.drops_system, _FakeOpenAI.weak = False, True
        assert policy.system_turn_reaches_the_model() is False

    def test_hosted_providers_are_not_checked(self):
        policy = LLMPolicy(provider="anthropic", model="x")
        with pytest.raises(ValueError):
            policy.system_turn_reaches_the_model()

    def test_the_local_runner_uses_the_policys_check(self):
        """One implementation: the experiment script must not keep its own copy."""
        script = Path(__file__).parent.parent / "experiments" / "run_local_llms.py"
        text = script.read_text()
        assert ".system_turn_reaches_the_model()" in text
        assert "def system_turn_reaches_the_model" not in text
