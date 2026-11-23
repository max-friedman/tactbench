"""The decision chain: read the role (R), find the relevant entity (J), compose (C). Round 83.

Round 82 found that models read which entity holds the decider's role at 60-79%,
yet decide no better when they read it right. The decision needs a chain:
R (who holds the role), J (which entity the body makes relevant), and C (the two
composed). ``experiments/decider_chain.py`` asks all three on both sides of every v9
dev pair. These tests were written before the probe existed. They hold the question
set to the committed data and to its counterbalancing, the documented questions and
pre-registration to the code, and the published figures to a recomputation.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

import decider_chain as ch  # noqa: E402
import decider_reading as dr  # noqa: E402

from tactbench.dataset.loader import load  # noqa: E402
from tactbench.schema import pair_key  # noqa: E402

DOC = ROOT / "docs" / "DECIDER_READING.md"


def _block(path: Path, name: str) -> str:
    text = path.read_text()
    return text.split(f"<!-- {name}:start -->\n")[1].split(f"\n<!-- {name}:end -->")[0]


@pytest.fixture(scope="module")
def chain() -> list[ch.ChainItem]:
    return ch.build_items()


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #


def test_every_moment_of_v9_dev_once(chain):
    items = load("v9", "dev")
    assert len(chain) == len(items) == 640
    assert {c.moment_id for c in chain} == {i.moment.id for i in items}
    assert Counter(c.family for c in chain) == {f: 40 for f in dr.QUESTIONS}


def test_both_sides_of_every_pair(chain):
    sides = Counter(pair_key(c.moment_id) for c in chain)
    assert set(sides.values()) == {2}
    labels = {i.moment.id: i.label.should_surface for i in load("v9", "dev")}
    for fam in dr.QUESTIONS:
        assert Counter(labels[c.moment_id] for c in chain if c.family == fam) == {
            True: 20,
            False: 20,
        }


def test_the_r82_side_reuses_r82s_question_exactly(chain):
    r82 = {q.moment_id: q for q in dr.build_questions()}
    asked = [c for c in chain if c.moment_id in r82]
    assert len(asked) == 320
    for c in asked:
        assert c.r.prompt == r82[c.moment_id].prompt
        assert c.r.options == r82[c.moment_id].options
        assert c.r.gold == r82[c.moment_id].gold
        assert c.r_from_r82


def test_the_other_side_gets_r82s_question_with_the_partner_order_flipped(chain):
    r82 = {pair_key(q.moment_id): q for q in dr.build_questions()}
    for c in chain:
        if c.r_from_r82:
            continue
        partner = r82[pair_key(c.moment_id)]
        assert c.r.options == partner.options[::-1]
        priv, other = dr.roles(c.decider, c.family, c.frame)
        assert c.r.gold == (priv if dr.ASKED_ROLE[c.family] == "privileged" else other)
        assert c.r.prompt.endswith(
            dr.QUESTIONS[c.family].format(a=c.r.options[0], b=c.r.options[1])
        )


def test_every_prompt_is_the_documented_preamble_and_the_full_moment(chain):
    items = {i.moment.id: i for i in load("v9", "dev")}
    for c in chain:
        moment = dr.render_moment(items[c.moment_id].moment)
        for q in (c.r, c.j, c.c):
            assert q.prompt.startswith(dr.PROMPT_PREAMBLE + "\n\n" + moment + "\n\n")


def test_j_options_are_the_two_entities_and_gold_is_the_marker(chain):
    for c in chain:
        assert set(c.j.options) == set(c.r.options)
        assert c.j.gold == c.marker
        assert c.j.prompt.endswith(
            ch.J_QUESTIONS[c.family].format(a=c.j.options[0], b=c.j.options[1])
        )


def test_the_marker_is_the_body_entity_on_both_sides(chain):
    """The positive side puts the marker in the privileged role; the near side, the other."""
    for c in chain:
        priv, other = dr.roles(c.decider, c.family, c.frame)
        assert c.marker == (priv if c.speak else other)


def test_c_options_are_the_two_role_words_and_gold_follows_the_label(chain):
    for c in chain:
        priv_word, other_word = ch.C_WORDS[c.family]
        assert set(c.c.options) == {priv_word, other_word}
        assert c.c.gold == (priv_word if c.speak else other_word)
        assert c.c.prompt.endswith(
            ch.C_QUESTIONS[c.family].format(a=c.c.options[0], b=c.c.options[1])
        )


def test_every_option_parses_to_itself(chain):
    for c in chain:
        for q in (c.r, c.j, c.c):
            for opt in q.options:
                assert dr.parse_answer(opt, q.options) == opt


def test_c_role_words_are_in_their_question():
    for fam, (a, b) in ch.C_WORDS.items():
        assert ch.C_QUESTIONS[fam].count("{a}") == 1 and ch.C_QUESTIONS[fam].count("{b}") == 1
        assert a != b


@pytest.mark.parametrize("kind", ["r", "j", "c"])
def test_always_first_option_reads_exactly_half_per_family(chain, kind):
    for fam in dr.QUESTIONS:
        qs = [getattr(c, kind) for c in chain if c.family == fam]
        assert sum(q.gold == q.options[0] for q in qs) == 20, (kind, fam)


@pytest.mark.parametrize("kind", ["r", "j", "c"])
def test_first_named_in_decider_reads_exactly_half_per_family(chain, kind):
    for fam in dr.QUESTIONS:
        cs = [c for c in chain if c.family == fam]
        right = sum(ch.first_named_in_decider(c, kind) == getattr(c, kind).gold for c in cs)
        assert right == 20, (kind, fam)


def test_c_is_blind_to_any_rule_that_reads_only_the_tokens(chain):
    """Both sides of a pair carry the same token multiset and opposite C answers."""
    by_pair: dict[str, list[ch.ChainItem]] = {}
    for c in chain:
        by_pair.setdefault(pair_key(c.moment_id), []).append(c)
    for a, b in by_pair.values():
        assert sorted(a.c.prompt.split()) == sorted(b.c.prompt.split())
        assert a.c.gold != b.c.gold


def test_baselines_table_is_current(chain):
    assert _block(DOC, "decider-chain-baselines") == ch.baselines_table(chain)


def test_two_entity_families_are_those_whose_body_names_both(chain):
    items = {i.moment.id: i for i in load("v9", "dev")}
    for c in chain:
        body = " ".join(s.content for s in items[c.moment_id].moment.signals[:-1])
        named = [o for o in c.j.options if ch.key_in(o, body)]
        assert (len(named) == 2) == (c.family in ch.TWO_ENTITY), (c.family, named)
    assert len(ch.TWO_ENTITY) == 8


# --------------------------------------------------------------------------- #
# Documentation and pre-registration
# --------------------------------------------------------------------------- #


def test_j_and_c_questions_are_documented_verbatim():
    rows = [
        f"| `{f}` | {'two' if f in ch.TWO_ENTITY else 'one or none'} "
        f"| {ch.J_QUESTIONS[f]} | {ch.C_QUESTIONS[f]} "
        f"| {ch.C_WORDS[f][0]} / {ch.C_WORDS[f][1]} |"
        for f in sorted(dr.QUESTIONS)
    ]
    header = (
        "| family | entities the body names | J (body) | C (composed) "
        "| C options: speak / silent |\n|---|---|---|---|---|\n"
    )
    assert _block(DOC, "decider-chain-questions") == header + "\n".join(rows)


def test_power_figures_are_the_binomials_own():
    text = " ".join(DOC.read_text().split())
    k = min(k for k in range(41) if dr.binom_sf(k, 40) <= dr.ALPHA / 16)
    assert k == ch.FIRST_HOLM_STEP == 30
    assert f"**{k} of 40** (p = {dr.binom_sf(k, 40):.4f})" in text
    assert f"{dr.binom_sf_at(k, 40, 0.75):.1%}" in text
    k8 = min(k for k in range(41) if dr.binom_sf(k, 40) <= dr.ALPHA / 8)
    assert f"**{k8} of 40**" in text and f"{dr.binom_sf_at(k8, 40, 0.75):.1%}" in text


def test_preregistration_precedes_results_and_states_the_rules():
    text = DOC.read_text()
    sec = text.split("## Round 83")[1]
    assert sec.index("### Pre-registration (Round 83)") < sec.index("### Results (Round 83)")
    flat = " ".join(sec.split())
    for phrase in (
        "Fisher",
        "P(C right | R right and J right)",
        f"at least {ch.HIGH:.0%}",
        f"below {ch.LOW:.0%}",
        "break in composition",
        "break in finding the relevant entity",
        "break in reading the decider",
    ):
        assert phrase in flat, phrase


def test_reading_rules():
    assert ch.reading(r=0.8, j=0.9, c=0.55) == "composition"
    assert ch.reading(r=0.8, j=0.5, c=0.55) == "finding the relevant entity"
    assert ch.reading(r=0.55, j=0.9, c=0.55) == "reading the decider"
    assert ch.reading(r=0.8, j=0.9, c=0.8) == "no break before the decision"
    assert ch.reading(r=0.65, j=0.9, c=0.55) == "unresolved"


def test_fisher_exact_one_sided():
    # [[a, b], [c, d]]: rows = (R and J right, otherwise), cols = (C right, C wrong).
    assert ch.fisher_greater(5, 0, 0, 5) == pytest.approx(1 / 252)
    assert ch.fisher_greater(0, 5, 5, 0) == pytest.approx(1.0)
    assert ch.fisher_greater(3, 2, 2, 3) == pytest.approx(0.5, abs=0.11)


def test_decoding_matches_r82():
    assert ch.TEMPERATURE == dr.TEMPERATURE == 0 and ch.MAX_TOKENS == dr.MAX_TOKENS


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


def test_results_are_complete_and_reparse(chain):
    run = ch.models_run()
    assert run, "no chain results committed"
    need = {(c.moment_id, k) for c in chain for k in ("j", "c")} | {
        (c.moment_id, "r") for c in chain if not c.r_from_r82
    }
    by_id = {c.moment_id: c for c in chain}
    for name in run:
        rows = ch.load_rows(name)
        assert {(r["moment_id"], r["kind"]) for r in rows} == need, name
        assert len(rows) == len(need)
        for r in rows:
            q = getattr(by_id[r["moment_id"]], r["kind"])
            assert r["answer"] == dr.parse_answer(r["response"], q.options)
            assert r["prompt_version"] == ch.PROMPT_VERSION


def test_results_tables_are_current(chain):
    assert _block(DOC, "decider-chain-summary") == ch.summary_table(chain)
    assert _block(DOC, "decider-chain-families") == ch.family_table(chain)
    assert _block(DOC, "decider-chain-findings") == ch.findings(chain)
    readme = ROOT / "README.md"
    assert _block(readme, "decider-chain-findings") == ch.findings(chain)
    assert _block(readme, "decider-chain-summary") == ch.summary_table(chain)


def test_c_role_words_appear_only_in_the_counterbalanced_slot():
    for fam, words in ch.C_WORDS.items():
        stem = ch.C_QUESTIONS[fam].format(a="", b="")
        for w in words:
            assert not ch.key_in(w, stem), (fam, w)


def test_questions_list_the_options_only_in_the_slot():
    for table in (ch.J_QUESTIONS, ch.C_QUESTIONS, dr.QUESTIONS):
        for q in table.values():
            assert q.count("{a}") == 1 and q.count("{b}") == 1


def test_all_six_models_ran():
    assert ch.models_run() == ch.MODELS


def test_the_findings_wording_holds(chain):
    """The words around the generated figures: "find", "well above chance", "near a coin"."""
    ss = [ch.summarize(m, chain) for m in ch.models_run()]
    assert all(s.pooled["j"] >= ch.HIGH for s in ss)
    assert all(s.p("r") < 0.0001 for s in ss)
    assert all(s.pooled["c"] < ch.LOW for s in ss)
    readme = " ".join((ROOT / "README.md").read_text().split())
    assert "do each step alone and fail at putting them together" in readme


def test_prose_figures_in_the_round_83_docs(chain):
    import json

    text = " ".join(DOC.read_text().split("## Round 83")[1].split())
    manifest = json.loads(ch.MANIFEST.read_text())
    assert set(manifest) == set(ch.models_run())
    total = sum(v["call_seconds"] for v in manifest.values())
    assert f"The calls took {round(total):,} seconds in total" in text
    ss = [ch.summarize(m, chain) for m in ch.models_run()]
    r = sorted(s.pooled["r"] for s in ss)
    assert f"read the role at {round(r[0] * 100)}-{round(r[-1] * 100)}% (R)" in text
    both = sorted(s.chain_table[0] / (s.chain_table[0] + s.chain_table[1]) for s in ss)
    assert f"C is right only {round(both[0] * 100)}-{round(both[-1] * 100)}% of the time" in text
    unresolved = [s for s in ss if s.reading == "unresolved"]
    assert len(unresolved) == 2 and "**Two models are unresolved**" in text
    a, b = unresolved
    assert f"`{a.model}` and `{b.model}` read the role at {a.pooled['r']:.1%} and" in text
    assert f"and {b.pooled['r']:.1%} pooled" in text
    assert all(ch.HIGH > s.pooled["r"] >= ch.LOW for s in unresolved)
    assert sum(s.reading == "composition" for s in ss) == 4
    assert "matches the other four" in text
