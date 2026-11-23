"""Decider reading: can a model say which entity the decider puts in which role? Round 82.

Every LLM run fails to tell the two sides of a pair apart (best pairs-both-right 14.8%,
a coin ~25%). That has two readings: the model cannot *read* the decider, or it reads
it and does not *use* it. ``experiments/decider_reading.py`` asks each model a direct
two-option factual question about the decider alone, with the moment's full rendered
context and no interruption decision. These tests were written before the probe.

They hold four things: the question set is built from the committed v9 data and is
fair (two options, the swapped pair's two entities, counterbalanced so position and
option order read exactly 50%); the prompt in code is the one documented; the
committed results are complete; and every published figure equals a recomputation.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

import decider_reading as dr  # noqa: E402

from tactbench.dataset.loader import load  # noqa: E402
from tactbench.schema import pair_key  # noqa: E402

DOC = ROOT / "docs" / "DECIDER_READING.md"
README = ROOT / "README.md"


@pytest.fixture(scope="module")
def questions() -> list[dr.Question]:
    return dr.build_questions()


def _block(path: Path, name: str) -> str:
    text = path.read_text()
    return text.split(f"<!-- {name}:start -->\n")[1].split(f"\n<!-- {name}:end -->")[0]


# --------------------------------------------------------------------------- #
# The question set
# --------------------------------------------------------------------------- #


def test_one_question_per_pair_of_committed_v9_dev(questions):
    items = load("v9", "dev")
    by_id = {i.moment.id: i for i in items}
    pairs = {pair_key(i.moment.id) for i in items}
    assert len(questions) == len(pairs) == 320
    assert {pair_key(q.moment_id) for q in questions} == pairs
    for q in questions:
        item = by_id[q.moment_id]  # built from the committed file, not a regeneration
        assert q.family == item.moment.family
        assert q.prompt.startswith(dr.PROMPT_PREAMBLE)
        assert dr.render_moment(item.moment) in q.prompt


def test_sixteen_families_of_twenty(questions):
    counts = Counter(q.family for q in questions)
    assert len(counts) == 16 and set(counts.values()) == {20}
    assert set(dr.QUESTIONS) == set(counts)


def test_sides_are_balanced_by_label_within_each_family(questions):
    items = {i.moment.id: i for i in load("v9", "dev")}
    for fam in dr.QUESTIONS:
        labels = Counter(
            items[q.moment_id].label.should_surface for q in questions if q.family == fam
        )
        assert labels == {True: 10, False: 10}, fam


def test_side_choice_is_deterministic_and_uses_hashlib():
    a = [q.moment_id for q in dr.build_questions()]
    b = [q.moment_id for q in dr.build_questions()]
    assert a == b
    src = (ROOT / "experiments" / "decider_reading.py").read_text()
    assert "hashlib" in src and "hash(" not in src.replace("hashlib", "")


def test_two_options_are_the_two_entities_swapped_in_the_pair(questions):
    items = {i.moment.id: i for i in load("v9", "dev")}
    for q in questions:
        assert len(q.options) == 2 and q.options[0] != q.options[1]
        assert q.gold in q.options
        mine = items[q.moment_id].moment.signals[-1].content
        side, other = ("pos", "near") if "-pos-" in q.moment_id else ("near", "pos")
        partner = items[q.moment_id.replace(f"-{side}-", f"-{other}-")]
        theirs = partner.moment.signals[-1].content
        assert mine != theirs
        # Swap the two options in this side's decider and you get the partner's.
        a, b = q.options
        swapped = mine.replace(a, "\0").replace(b, a).replace("\0", b)
        assert swapped == theirs, q.moment_id
        # Each option names one entity: exactly one of them matches an answer naming it.
        for opt in q.options:
            assert dr.parse_answer(opt, q.options) == opt


def test_the_question_names_both_options_in_its_counterbalanced_order(questions):
    for q in questions:
        a, b = q.options
        tail = q.prompt.split("\n\n")[-1]
        assert tail == dr.QUESTIONS[q.family].format(a=a, b=b)
        assert tail.index(a) < tail.index(b)


def test_always_first_option_reads_exactly_half_in_every_family(questions):
    for fam in dr.QUESTIONS:
        qs = [q for q in questions if q.family == fam]
        assert sum(q.gold == q.options[0] for q in qs) == len(qs) // 2, fam


def test_positional_baseline_reads_exactly_half_in_every_family(questions):
    """The answer is the entity named first in the decider exactly half the time."""
    for fam in dr.QUESTIONS:
        qs = [q for q in questions if q.family == fam]
        assert sum(dr.positional_answer(q) == q.gold for q in qs) == len(qs) // 2, fam


def test_always_the_marker_reads_exactly_half_in_every_family(questions):
    """Gold is the marker (``you``, ``checking``) on half the questions: label-balanced."""
    for fam in dr.QUESTIONS:
        qs = [q for q in questions if q.family == fam]
        assert sum(q.gold == q.marker for q in qs) == len(qs) // 2, fam


def test_baselines_published_are_the_recomputed_ones(questions):
    base = dr.baselines(questions)
    assert base["always first option"] == 0.5
    assert base["first-named in decider"] == 0.5
    assert base["always the marker"] == 0.5
    assert _block(DOC, "decider-reading-baselines") == dr.baselines_table(questions)


def test_the_gold_is_the_entity_the_asked_role_holds(questions):
    for q in questions:
        priv, other = dr.roles(q.decider, q.family, q.frame)
        assert {priv, other} == set(q.options)
        assert q.gold == (priv if dr.ASKED_ROLE[q.family] == "privileged" else other)


def test_parse_answer_counts_neither_and_both_as_unparsed():
    opts = ("you", "Dana")
    assert dr.parse_answer("You", opts) == "you"
    assert dr.parse_answer("Dana.", opts) == "Dana"
    assert dr.parse_answer("Dana or you", opts) is None
    assert dr.parse_answer("The user", opts) is None
    assert dr.parse_answer("Your", opts) is None  # "your" is not "you"
    hopts = ("your prescription", "Sam's prescription")
    assert dr.parse_answer("Sam's prescription", hopts) == "Sam's prescription"
    assert dr.parse_answer("Yours", hopts) == "your prescription"


# --------------------------------------------------------------------------- #
# The prompt is the documented one
# --------------------------------------------------------------------------- #


def test_prompt_preamble_is_documented_verbatim():
    assert _block(DOC, "decider-reading-prompt") == f"```\n{dr.PROMPT_PREAMBLE}\n```"


def test_questions_are_documented_verbatim():
    expected = "\n".join(
        f"| `{fam}` | {dr.ASKED_ROLE[fam]} | {dr.QUESTIONS[fam]} |" for fam in sorted(dr.QUESTIONS)
    )
    header = "| family | role asked | question |\n|---|---|---|\n"
    assert _block(DOC, "decider-reading-questions") == header + expected


def test_decoding_is_greedy_and_short():
    assert dr.TEMPERATURE == 0
    assert dr.MAX_TOKENS <= 16


def test_prediction_is_registered_before_results():
    text = DOC.read_text()
    assert text.index("## Pre-registration") < text.index("## Results")
    for phrase in ("Holm", "one-sided", "exact binomial", "p < 0.05"):
        assert phrase in text


# --------------------------------------------------------------------------- #
# Results: complete, and every figure recomputed
# --------------------------------------------------------------------------- #


def test_every_listed_model_has_complete_results(questions):
    ids = {q.qid for q in questions}
    run = dr.models_run()
    assert run, "no decider-reading results committed"
    for name in run:
        rows = dr.load_rows(name)
        assert {r["qid"] for r in rows} == ids, name
        assert len(rows) == len(ids), name
        for r in rows:
            assert r["prompt_version"] == dr.PROMPT_VERSION


def test_committed_answers_are_reparsed_identically(questions):
    by_qid = {q.qid: q for q in questions}
    for name in dr.models_run():
        for r in dr.load_rows(name):
            q = by_qid[r["qid"]]
            assert r["answer"] == dr.parse_answer(r["response"], q.options)


def test_the_results_table_in_the_docs_is_current(questions):
    assert _block(DOC, "decider-reading-families") == dr.family_table(questions)


def test_the_readme_summary_is_current(questions):
    assert _block(README, "decider-reading") == dr.summary_table(questions)


def test_summary_figures_are_recomputed(questions):
    """Spot-check the table generator against an independent count."""
    by_qid = {q.qid: q for q in questions}
    for name in dr.models_run():
        rows = dr.load_rows(name)
        right = sum(r["answer"] == by_qid[r["qid"]].gold for r in rows)
        s = dr.summarize(name, questions)
        assert s.correct == right and s.n == 320
        assert s.unparsed == sum(r["answer"] is None for r in rows)


def test_binomial_and_holm():
    assert dr.binom_sf(20, 20) == pytest.approx(0.5**20)
    assert dr.binom_sf(0, 20) == 1.0
    assert dr.binom_sf(15, 20) == pytest.approx(0.020694732666015625)
    # Holm with 16 tests: the smallest p must clear 0.05/16 = 0.003125.
    assert dr.holm([0.003, 0.5] + [1.0] * 14) == [True] + [False] * 15
    assert dr.holm([0.004] + [1.0] * 15) == [False] * 16
    assert dr.holm([0.001, 0.003] + [1.0] * 14) == [True, True] + [False] * 14


def test_verdict_rule():
    assert dr.verdict(families_read=12, best_pairs=0.094) == "(b)"
    assert dr.verdict(families_read=2, best_pairs=0.094) == "(a)"
    assert dr.verdict(families_read=6, best_pairs=0.094) == "neither"
    assert dr.verdict(families_read=12, best_pairs=0.40) == "neither"


def test_committed_files_are_json_lines():
    for name in dr.models_run():
        for line in dr.result_path(name).read_text().splitlines():
            json.loads(line)


def test_the_findings_in_readme_and_docs_are_current(questions):
    text = dr.findings(questions)
    assert _block(README, "decider-reading-findings") == text
    assert _block(DOC, "decider-reading-findings") == text
    assert _block(DOC, "decider-reading") == dr.summary_table(questions)


def test_the_readme_section_follows_the_at_a_glance_table():
    text = README.read_text()
    assert text.index("<!-- llm-glance:end -->") < text.index("<!-- decider-reading-findings:start")
    assert text.index("<!-- decider-reading:end -->") < text.index("### How good does a system")


def test_prose_figures_in_the_docs(questions):
    """The hand-written figures under the docs tables, each recomputed."""
    text = " ".join(DOC.read_text().split())
    manifest = json.loads(dr.MANIFEST.read_text())
    total = sum(manifest[m]["call_seconds"] for m in dr.models_run())
    assert set(manifest) == set(dr.models_run())
    assert f"The calls took {round(total):,} seconds in total" in text
    above = [s for s in (dr.summarize(m, questions) for m in dr.models_run()) if s.p < dr.ALPHA]
    lo, hi = (min(s.correct / s.n for s in above), max(s.correct / s.n for s in above))
    assert f"Reading at {round(lo * 100)}-{round(hi * 100)}%" in text
    best = max(s.best_pairs for s in above)
    assert f"the 0-{round(best * 100)}% of pairs" in text
    assert "eleven answer the reading question well above chance" in text and len(above) == 11
    # "roughly two times in three": the median above-chance accuracy is within 60-73%.
    accs = sorted(s.correct / s.n for s in above)
    assert 0.6 <= accs[len(accs) // 2] <= 0.73


def test_preregistration_figures(questions):
    """The thresholds the pre-registration quotes are the binomial's own."""
    text = " ".join(DOC.read_text().split())
    first = min(k for k in range(21) if dr.binom_sf(k, 20) <= dr.ALPHA / 16)
    assert first == 17 and f"which means **{first} of 20** right" in text
    assert f"16 of 20 (p = {dr.binom_sf(16, 20):.4f})" in text
    assert dr.binom_sf(16, 20) <= dr.ALPHA / 8 and dr.binom_sf(16, 20) > dr.ALPHA / 9
    assert f"15 of 20 (p = {dr.binom_sf(15, 20):.3f})" in text
    assert f"(12 of 20, p = {dr.binom_sf(12, 20):.2f})" in text
    assert f"(**{dr.MOST} or more of 16**)" in text and f"(**{dr.FEW} or fewer**)" in text
    readme = " ".join(README.read_text().split())
    assert f"so {len(questions)} two-option questions" in readme
