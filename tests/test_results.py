"""The README's LLM table is gated against committed decisions. Round 23.

Rounds 17-19 found the built-in results gate silently covering less than it
claimed, three times. The LLM table is a new place for the same failure, so every
direction is checked: each committed run is complete, each has a README row, each
README row has a committed run, every figure in a row equals a fresh re-score, and
a row the regex fails to read fails the build instead of being skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tactbench.dataset.loader import load
from tactbench.policies.base import ask
from tactbench.policies.builtin import AlwaysPolicy, NeverPolicy
from tactbench.results import (
    load_results,
    manifest,
    pairs_both_right,
    policy_name,
    results_dir,
    scorecards,
)
from tactbench.runner import normalized, pair_blind_ics

README = Path(__file__).resolve().parents[1] / "README.md"

ROW = re.compile(
    r"^\|\s*`(?P<policy>llm:(?:naive|rubric):[\w.\-]+)`\s*\|\s*(?P<ics>[\d.]+)\s*"
    r"\|\s*(?P<vs>[+−-][\d.]+|0\.0)\s*\|\s*(?P<bar>[+−-][\d.]+|0\.0)\s*\|\s*(?P<prec>[\d.]+|—)\s*\|\s*(?P<recall>[\d.]+|—)\s*"
    r"\|\s*(?P<ece>[\d.]+)\s*\|\s*(?P<hv>\d+)\s*\|\s*(?P<spoke>\d+)/(?P<n>\d+)\s*"
    r"\|\s*(?P<pairs>[\d.]+)%\s*\|\s*(?P<unparsed>[\d.]+)%\s*\|\s*$",
    re.MULTILINE,
)

RUNS = load_results()


MARKERS = {
    "v1": ("<!-- llm-results:start -->", "<!-- llm-results:end -->"),
    "v2": ("<!-- llm-results-v2:start -->", "<!-- llm-results-v2:end -->"),
    "v3": ("<!-- llm-results-v3:start -->", "<!-- llm-results-v3:end -->"),
}


def _readme_table(version: str = "v1") -> str:
    """The README block between a version's markers -- one table per version, so a
    v2 row can never be read as a v1 row or the reverse (Round 39)."""
    start, end = MARKERS[version]
    text = README.read_text()
    assert text.count(start) == 1 and text.count(end) == 1, f"{version} table markers"
    return text.split(start)[1].split(end)[0]


def _readme_rows(version: str = "v1") -> dict[str, re.Match]:
    text = _readme_table(version)
    rows = {m.group("policy"): m for m in ROW.finditer(text)}
    claimed = [ln for ln in text.splitlines() if ln.startswith("| `llm:")]
    assert len(claimed) == len(rows), (
        f"{len(claimed)} README lines look like LLM result rows but {len(rows)} parse. "
        "A row the check cannot read is a row the check does not cover."
    )
    return rows


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_committed_run_is_complete(name):
    """A partial run would be scored as silence on every missing moment."""
    ids = [d.moment_id for d in RUNS[name]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate decisions"
    assert set(ids) == {i.moment.id for i in load("v1", "dev")}, f"{name}: incomplete run"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_no_committed_run_contains_a_failed_call(name):
    """A failed call is the server's answer, not the model's.

    Round 23's first Gemma 2 run returned HTTP 500 on all 504 calls: its chat
    template rejects a system turn. Scored, that is a perfect copy of silence -- ICS
    336, zero hard violations -- attributed to a model that never saw a prompt. An
    unparsed *answer* is the model's failure and is reported; a failed *call* is
    ours, and the run is redone rather than published.
    """
    failed = [d.moment_id for d in RUNS[name] if (d.rationale or "").startswith("call failed")]
    assert not failed, f"{name}: {len(failed)} calls failed, e.g. {failed[0]}"


@pytest.mark.parametrize("name", sorted(RUNS))
def test_every_committed_run_records_what_produced_it(name):
    model = name.split(":", 2)[2]
    entry = manifest().get(model)
    assert entry, f"{model} has results but no MANIFEST.json entry"
    assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
    assert entry["temperature"] == 0


@pytest.mark.parametrize("model", sorted(manifest()))
def test_every_model_in_the_manifest_has_both_variants(model):
    """Round 23 dropped Phi-3.5's naive run while moving files during a resumed
    job; every other check stayed green because each covers only the runs that
    exist. Reporting one variant of a model silently is a selected result."""
    for variant in ("naive", "rubric"):
        assert f"llm:{variant}:{model}" in RUNS, f"{model}: no committed {variant} run"


def test_runs_and_readme_rows_correspond_one_to_one():
    rows = _readme_rows()
    assert set(rows) == set(RUNS), (
        f"in README only: {sorted(set(rows) - set(RUNS))}; "
        f"committed but unpublished: {sorted(set(RUNS) - set(rows))}"
    )


def test_every_readme_figure_equals_a_fresh_rescore():
    rows = _readme_rows()
    bar = pair_blind_ics(load("v1", "dev"))
    stale = []
    for card, unparsed, pairs in scorecards():
        row = rows[card.policy]
        for label, quoted, actual, tol in (
            ("ICS", row["ics"], card.ics, 0.05),
            ("vs silence", row["vs"].replace("−", "-"), card.ics_normalized, 0.05),
            ("vs pair-blind", row["bar"].replace("−", "-"), normalized(card.ics, bar), 0.05),
            ("prec@int", row["prec"], card.precision_at_interrupt, 0.0005),
            ("recall-hv", row["recall"], card.recall_high_value, 0.0005),
            ("ECE", row["ece"], card.ece, 0.0005),
            ("hard viol.", row["hv"], card.hard_violations, 0),
            ("spoke", row["spoke"], card.surfaced, 0),
            ("n", row["n"], card.n, 0),
            ("pairs", row["pairs"], pairs * 100, 0.05),
            ("unparsed", row["unparsed"], unparsed * 100, 0.05),
        ):
            if quoted == "—" or actual is None:
                if (quoted == "—") != (actual is None):
                    stale.append(f"{card.policy}.{label}: README {quoted}, actual {actual}")
                continue
            if abs(float(quoted) - float(actual)) > tol:
                stale.append(f"{card.policy}.{label}: README {quoted}, actual {actual:.3f}")
    assert not stale, "README LLM table is stale; run `tactbench results`:\n  " + "\n  ".join(stale)


def test_file_names_round_trip():
    assert policy_name(results_dir() / "llm_rubric_qwen2.5-0.5b-dev.jsonl") == (
        "llm:rubric:qwen2.5-0.5b"
    )


class TestPairsBothRight:
    """The column exists to expose constant policies, so check that it does."""

    ITEMS = load("v1", "dev")

    def _run(self, policy):
        return [ask(policy, i.moment) for i in self.ITEMS]

    def test_a_constant_policy_scores_zero(self):
        assert pairs_both_right(self.ITEMS, self._run(NeverPolicy())) == 0.0
        assert pairs_both_right(self.ITEMS, self._run(AlwaysPolicy())) == 0.0

    def test_the_gold_labels_score_one(self):
        from tactbench.schema import Decision

        gold = [Decision(moment_id=i.moment.id, surface=i.label.should_surface) for i in self.ITEMS]
        assert pairs_both_right(self.ITEMS, gold) == 1.0


class TestReadmeClaimsAboutTheLLMTable:
    """The README draws three conclusions from the table. If a committed run
    breaks one, the conclusion is stale and the prose must change with it."""

    def test_no_run_reads_the_deciding_signal_better_than_a_coin(self):
        best = max(pairs for _, _, pairs in scorecards())
        assert best < 0.25, f"a run scores {best:.1%} pairs-both-right; update the README"

    def test_no_run_reaches_the_five_word_topic_policy(self):
        from test_metrics import TestReadmeResultsAreCurrent, _TopicPolicy

        from tactbench.runner import evaluate, silence_ics

        items = load("v1", "dev")
        topic = evaluate(
            _TopicPolicy(TestReadmeResultsAreCurrent.TOPIC_WORDS),
            items,
            reference=silence_ics(items),
        ).ics_normalized
        best = max(card.ics_normalized for card, _, _ in scorecards())
        assert best < topic, f"an LLM run ({best:+.1f}) reaches the topic policy ({topic:+.1f})"

    def test_every_run_above_silence_has_zero_hard_violations(self):
        above = [card for card, _, _ in scorecards() if card.ics_normalized > 0]
        assert above
        assert all(card.hard_violations == 0 for card in above), [c.policy for c in above]

    def test_the_hard_violation_split_is_clean(self):
        """README: no run above silence has one; every run below has 11-28."""
        for card, _, _ in scorecards():
            if card.ics_normalized > 0:
                assert card.hard_violations == 0, card.policy
            elif card.ics_normalized < 0:
                assert 11 <= card.hard_violations <= 28, card.policy

    def test_eight_runs_are_constant(self):
        constant = [c.policy for c, _, _ in scorecards() if c.surfaced in (0, c.n)]
        assert len(constant) == 8, constant

    def test_no_run_clears_the_pair_blind_bar(self):
        """README: 'none clears the pair-blind bar'."""
        bar = pair_blind_ics(load("v1", "dev"))
        cleared = [c.policy for c, _, _ in scorecards() if c.ics < bar]
        assert not cleared, f"{cleared} clear the pair-blind bar; update the README"


class TestReadmeLLMProseFigures:
    """Every figure the README's LLM bullets quote, recomputed. Review of R24 found
    six with no test behind them, under a state file claiming each claim was one.
    Each locator must match exactly once, so a reworded sentence fails loudly."""

    @staticmethod
    def _one(pattern: str) -> tuple[str, ...]:
        found = re.findall(pattern, README.read_text())
        assert len(found) == 1, f"locator {pattern!r} matched {len(found)} times"
        return found[0] if isinstance(found[0], tuple) else (found[0],)

    @staticmethod
    def _cards() -> dict:
        return {c.policy: (c, p) for c, _, p in scorecards()}

    def test_best_pairs_figure(self):
        (quoted,) = self._one(r"The best `pairs` score is ([\d.]+)%")
        assert float(quoted) == round(100 * max(p for _, p in self._cards().values()), 1)

    def test_no_run_above_pairs_figure_under_either_prompt(self):
        (quoted,) = self._one(r"no run gets above ([\d.]+)% pairs")
        assert float(quoted) == round(100 * max(p for _, p in self._cards().values()), 1)

    def test_most_moments_spoken_by_a_run_above_silence(self):
        (quoted,) = self._one(r"speaking rarely: (\d+) of 252 moments at most")
        above = [c.surfaced for c, _ in self._cards().values() if c.ics_normalized > 0]
        assert int(quoted) == max(above)

    def test_best_row_against_the_pair_blind_bar(self):
        (quoted,) = self._one(r"and is still\s+−([\d.]+) against what a policy")
        best = min((c for c, _ in self._cards().values()), key=lambda c: c.ics)
        assert -float(quoted) == round(normalized(best.ics, pair_blind_ics(load("v1", "dev"))), 1)

    def test_rubric_deltas(self):
        cards = self._cards()
        for model, label in (("gemma-3-4b", "Gemma-3-4B"), ("qwen2.5-7b", "Qwen2.5-7B")):
            a, b = self._one(rf"{re.escape(label)} from ([−+]\d+\.\d) to\s+([−+]\d+\.\d)")
            naive = cards[f"llm:naive:{model}"][0].ics_normalized
            rubric = cards[f"llm:rubric:{model}"][0].ics_normalized
            assert (float(a.replace("−", "-")), float(b)) == (round(naive, 1), round(rubric, 1))

    def test_phi_decides_identically_under_both_prompts(self):
        self._one(r"Phi-3\.5 makes the same speak-or-stay-quiet decision on all 252 moments")
        naive = {d.moment_id: d.surface for d in RUNS["llm:naive:phi-3.5-mini"]}
        rubric = {d.moment_id: d.surface for d in RUNS["llm:rubric:phi-3.5-mini"]}
        assert naive == rubric

    def test_qwen_echoes_the_template(self):
        self._one(r'`\{"surface": false, "confidence": 0\.0, "intent": null\}`')
        answers = {(d.surface, d.confidence, d.intent) for d in RUNS["llm:naive:qwen2.5-1.5b"]}
        assert answers == {(False, 0.0, None)}


def test_the_pairs_audit_holds():
    """Round 28 §A audit, wired in because it held. ``experiments/pairs_audit.py`` is
    independent of ``results.pairs_both_right``: it reads the JSONL directly. It
    fails if a fair coin's pairs-both-right leaves 20-30%, if its count disagrees
    with ``tactbench results`` on any run, or if any run reaches coin - 2 sd *or
    anything above it* -- which would make the README's "no model beats a coin"
    headline stale. One-sided since review: the first version flagged only runs
    near the coin, and a run scoring 100% passed it."""
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        [sys.executable, str(root / "experiments" / "pairs_audit.py")],
        capture_output=True, text=True, check=True, cwd=root,
    ).stdout  # fmt: skip
    assert out.strip().endswith("verdict: holds"), out
