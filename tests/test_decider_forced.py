"""Forced-choice C: Round 83's composed question, answered with a letter. Round 84.

Round 83 located the chain's break at the composed question C, but its free-text answers
did not always parse and some families drew one word whatever the gold.
``experiments/decider_forced.py`` asks the same question with lettered options. These
tests were written before any Round 84 model call. They hold the question set to the
committed data and its counterbalancing, the parser to its stated strictness, and the
pre-registered rules and power figures to the code. The results tests were strict
``xfail`` until the runs existed (the pre-registration commit, 7c1cefa); they now hold
every published figure to a recomputation.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

import decider_chain as ch  # noqa: E402
import decider_forced as fc  # noqa: E402
import decider_reading as dr  # noqa: E402

from tactbench.dataset.loader import load  # noqa: E402
from tactbench.schema import pair_key  # noqa: E402

DOC = ROOT / "docs" / "DECIDER_READING.md"


def _block(path: Path, name: str) -> str:
    text = path.read_text()
    return text.split(f"<!-- {name}:start -->\n")[1].split(f"\n<!-- {name}:end -->")[0]


def _r84() -> str:
    return " ".join(DOC.read_text().split("## Round 84")[1].split())


@pytest.fixture(scope="module")
def items() -> list[fc.ForcedItem]:
    return fc.build_items()


@pytest.fixture(scope="module")
def chain() -> list[ch.ChainItem]:
    return ch.build_items()


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #


def test_every_moment_of_v9_dev_once(items):
    v9 = load("v9", "dev")
    assert len(items) == len(v9) == 640 == fc.CALLS_PER_MODEL
    assert {f.moment_id for f in items} == {i.moment.id for i in v9}
    assert Counter(f.family for f in items) == {f: 40 for f in dr.QUESTIONS}


def test_gold_follows_the_label(items):
    labels = {i.moment.id: i.label.should_surface for i in load("v9", "dev")}
    for f in items:
        assert f.speak == labels[f.moment_id]
        sw, qw = fc.C_WORDS[f.family]
        assert set(f.options) == {sw, qw}
        assert f.gold_word == (sw if f.speak else qw)
        assert f.options[fc.LETTERS.index(f.gold)] == f.gold_word


def test_the_question_is_round_83s_stem_with_lettered_options(items):
    v9 = {i.moment.id: i.moment for i in load("v9", "dev")}
    for f in items:
        head = f"{dr.PROMPT_PREAMBLE}\n\n{dr.render_moment(v9[f.moment_id])}\n\n"
        a, b = f.options
        stem = ch.C_QUESTIONS[f.family].removesuffix(dr._END).format(a=a, b=b)
        assert f.prompt == f"{head}{stem}\nA) {a}\nB) {b}\n{fc.FC_END}"
    # The stem is Round 83's, only the answer instruction differs.
    for fam, q in ch.C_QUESTIONS.items():
        assert q.endswith(dr._END) and fc.C_STEMS[fam] + dr._END == q
    assert dr._END.strip() not in fc.FC_END


def test_the_documented_prompt_is_the_codes():
    q = fc.question("dinner_booking", "unconfirmed", "confirmed")
    assert _block(DOC, "decider-forced-prompt") == f"```\n{q}\n```"
    assert f"Prompt version `{fc.PROMPT_VERSION}`" in _r84()


def test_new_prompt_version_and_nothing_seeded_from_round_83():
    assert fc.PROMPT_VERSION != ch.PROMPT_VERSION
    assert fc.OUT != ch.OUT
    src = (ROOT / "experiments" / "decider_forced.py").read_text()
    run = src.split("def run_model")[1].split("def main")[0]
    # The runner reads only its own results; Round 83's rows are never consulted.
    assert "ch." not in run and "load_rows(name)" in run


def test_both_sides_of_a_pair_share_the_option_order(items):
    by_pair: dict[str, list[fc.ForcedItem]] = {}
    for f in items:
        by_pair.setdefault(pair_key(f.moment_id), []).append(f)
    assert set(map(len, by_pair.values())) == {2}
    for a, b in by_pair.values():
        assert a.options == b.options
        assert a.speak != b.speak and a.gold != b.gold


def test_a_token_blind_rule_gets_exactly_one_side_of_every_pair(items):
    by_pair: dict[str, list[fc.ForcedItem]] = {}
    for f in items:
        by_pair.setdefault(pair_key(f.moment_id), []).append(f)
    for a, b in by_pair.values():
        assert sorted(a.prompt.split()) == sorted(b.prompt.split())
        assert a.gold != b.gold


def test_gold_letter_is_a_in_exactly_half_of_every_family_side_cell(items):
    for fam in dr.QUESTIONS:
        for side in (True, False):
            cell = [f for f in items if f.family == fam and f.speak == side]
            assert len(cell) == 20
            assert sum(f.gold == "A" for f in cell) == 10, (fam, side)


def test_every_letter_word_pairing_is_gold_exactly_ten_times_per_family(items):
    for fam in dr.QUESTIONS:
        got = Counter((f.gold, f.gold_word) for f in items if f.family == fam)
        sw, qw = fc.C_WORDS[fam]
        assert got == {(x, w): 10 for x in fc.LETTERS for w in (sw, qw)}, fam


def test_constant_letters_and_words_read_exactly_half(items):
    for fam in dr.QUESTIONS:
        fs = [f for f in items if f.family == fam]
        for word in fc.C_WORDS[fam]:
            assert sum(f.gold_word == word for f in fs) == 20
        for side in (True, False):
            cell = [f for f in fs if f.speak == side]
            for letter in fc.LETTERS:
                assert sum(f.gold == letter for f in cell) == 10
            # A constant word cannot be balanced within a side: documented, not hidden.
            assert len({f.gold_word for f in cell}) == 1


def test_baselines_table_is_current(items):
    assert _block(DOC, "decider-forced-baselines") == fc.baselines_table(items)


def test_the_unbalanceable_cell_is_documented():
    text = _r84()
    assert "A constant role word cannot read 50% within a family × side cell" in text


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("reply", "want"),
    [
        ("A", "A"),
        ("B", "B"),
        (" B.", "B"),
        ("\nA\n", "A"),
        ("A) unconfirmed", "A"),
        ("B: confirmed", "B"),
        ("Answer: B", None),
        ("a", None),
        ("b)", None),
        ("**A**", None),
        ("(A)", None),
        ("Absolutely", None),
        ("AB", None),
        ("A1", None),
        ("Both", None),
        ("unconfirmed", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_is_strict_first_letter(reply, want):
    assert fc.parse_letter(reply) == want


def test_every_gold_letter_parses_to_itself(items):
    for f in items:
        assert fc.parse_letter(f.gold) == f.gold
        assert fc.parse_letter(f"{f.gold}) {f.gold_word}") == f.gold


def test_role_words_appear_only_in_the_slot_and_the_options():
    for fam, words in fc.C_WORDS.items():
        stem = fc.C_STEMS[fam].format(a="", b="")
        for w in words:
            assert not ch.key_in(w, stem), (fam, w)
        assert fc.C_STEMS[fam].count("{a}") == 1 and fc.C_STEMS[fam].count("{b}") == 1


# --------------------------------------------------------------------------- #
# Pre-registration
# --------------------------------------------------------------------------- #


def test_preregistration_precedes_results_and_states_the_rules():
    text = DOC.read_text()
    sec = text.split("## Round 84")[1]
    assert sec.index("### Pre-registration (Round 84)") < sec.index("### Results (Round 84)")
    flat = " ".join(sec.split())
    for phrase in (
        f"**at least {fc.HIGH:.0%}** ({fc.high_bar()} of {fc.N_TWO})",
        f"**{fc.low_bar()} of {fc.N_TWO}**",
        "Holm across the six models",
        f"**at least {fc.WORD_PRIOR:.0%} or at most {1 - fc.WORD_PRIOR:.0%}**",
        f"**no more than {fc.MAX_PRIOR_FAMILIES}** of its 8 two-entity families",
        "**Mantel–Haenszel** test stratified by **family × side**",
        "**no continuity correction**",
        "**word prior**",
        f"**{fc.COMPOSES}**",
        f"**{fc.COMPOSITION}**",
        "**unresolved**",
        f"**{fc.CLOSE_AT} or more** of the six models share one reading",
        "closes as **located at C, cause unresolved**",
        "closes it as **composition**",
        "share one reading, AD closes as that reading",
        "*Format* and either prior count toward that unless 4 or more models share them",
        f"**more than {fc.MAX_UNPARSED} of 320** unparsed",
        "**letter prior**",
        "**format**",
        "A *break is composition* reading with a significant chain test is reported as such",
        "the chain-probe line (Rounds 82-84) ends here unless the owner reopens it",
        "Unparsed replies count as wrong",
    ):
        assert phrase in flat, phrase


def test_power_figures_are_the_binomials_own():
    text = _r84()
    k = fc.holm_first_step()
    assert k == 182 and dr.binom_sf(k, 320) <= 0.05 / 6 < dr.binom_sf(k - 1, 320)
    assert f"**{k} of 320** (p = {dr.binom_sf(k, 320):.4f})" in text
    hb, lb = fc.high_bar(), fc.low_bar()
    assert (hb, lb) == (224, 192)
    for p in (0.75, 0.72, 0.70, 0.65):
        assert f"{dr.binom_sf_at(hb, 320, p):.1%}" in text, p
    for p in (0.55, 0.57, 0.60, 0.65):
        assert f"{1 - dr.binom_sf_at(lb, 320, p):.1%}" in text, p
    # The word-prior check: a family of 40 parsed answers.
    flag = min(k for k in range(41) if k / 40 >= fc.WORD_PRIOR)
    assert f"{2 * dr.binom_sf(flag, 40):.1e}" in text
    assert f"{dr.binom_sf_at(flag, 40, 0.90):.1%}" in text
    assert f"{dr.binom_sf_at(flag, 40, 0.75):.1%}" in text
    # Two or more of 8 flagged with no lean (both prior checks).
    p = 2 * dr.binom_sf(flag, 40)
    two = 1 - (1 - p) ** 8 - 8 * p * (1 - p) ** 7
    assert text.count(f"{two:.1e}") == 2 and text.count(f"{p:.1e}") == 2
    # The chain test's approximate power.
    for diff in (0.15, 0.10):
        for alpha in (0.05, 0.05 / 6):
            assert f"{fc.mh_power(220, 100, 0.5, diff, alpha):.1%}" in text, (diff, alpha)


def test_mh_power_is_a_two_proportion_test():
    # No difference: power is the size of the test.
    assert fc.mh_power(220, 100, 0.5, 0.0, 0.05) == pytest.approx(0.05, abs=1e-9)
    assert fc.mh_power(220, 100, 0.5, 0.3, 0.05) > 0.99


def _read(c_high=False, c=0.5, word_ok=True, letter_ok=True, unparsed=0):
    return fc.reading(c_high, c, word_ok, letter_ok, unparsed)


def test_reading_rules():
    assert _read(c_high=True, c=0.80) == fc.COMPOSES
    assert _read(c=0.55) == fc.COMPOSITION
    assert _read(c=0.65) == fc.UNRESOLVED
    # High by share but not above chance after Holm cannot happen at 70% of 320, but the
    # rule still needs both.
    assert _read(c=0.72) == fc.UNRESOLVED
    # The format guard: more than 32 unparsed, whatever C_fc.
    assert _read(c=0.55, unparsed=32) == fc.COMPOSITION
    for c_high, c in ((True, 0.8), (False, 0.5), (False, 0.65)):
        assert _read(c_high=c_high, c=c, unparsed=33) == fc.FORMAT
        # The priors come first, word before letter.
        assert _read(c_high=c_high, c=c, letter_ok=False, unparsed=33) == fc.LETTER
        assert _read(c_high=c_high, c=c, word_ok=False, letter_ok=False, unparsed=33) == fc.PRIOR
    assert fc.READINGS == (
        fc.PRIOR, fc.LETTER, fc.FORMAT, fc.COMPOSES, fc.COMPOSITION, fc.UNRESOLVED
    )  # fmt: skip
    assert fc.MAX_UNPARSED == 32 == round(0.10 * fc.N_TWO)


def test_item_closes():
    rest = [fc.UNRESOLVED, fc.FORMAT]
    assert fc.item_closes([fc.COMPOSITION] * 4 + rest) == "composition"
    assert fc.item_closes([fc.COMPOSES] * 4 + rest) == fc.COMPOSES
    for r in (fc.FORMAT, fc.PRIOR, fc.LETTER):
        assert fc.item_closes([r] * 4 + [fc.COMPOSITION] * 2) == r
    # No reading shared by 4: cause unresolved, however the rest split.
    assert fc.item_closes([fc.COMPOSITION] * 3 + [fc.COMPOSES] * 3) == fc.CAUSE_UNRESOLVED
    assert fc.item_closes([fc.COMPOSITION] * 3 + [fc.FORMAT] * 2 + [fc.PRIOR]) == (
        fc.CAUSE_UNRESOLVED
    )
    assert fc.item_closes([fc.FORMAT] * 3 + [fc.LETTER] * 3) == fc.CAUSE_UNRESOLVED


def _summary(**kw) -> fc.ForcedSummary:
    base = dict(
        model="m",
        right=0,
        unparsed=0,
        parsed_right=0,
        letter_a=0,
        family_share={},
        family_a={},
        family_right={},
        overall=0.0,
        strata=[],
    )
    return fc.ForcedSummary(**(base | kw))


def test_word_prior_counts_families_at_either_extreme():
    s = _summary(family_share={"a": 0.90, "b": 0.10, "c": 0.89, "d": 0.5})
    assert s.word_prior_families == ["a", "b"] and not s.word_ok
    s.family_share["b"] = 0.11
    assert s.word_ok


def test_letter_prior_counts_families_at_either_extreme():
    s = _summary(family_a={"a": 0.90, "b": 0.10, "c": 0.89, "d": 0.5})
    assert s.letter_prior_families == ["a", "b"] and not s.letter_ok
    s.family_a["b"] = 0.11
    assert s.letter_ok


def _reading_of(responses, items, chain):
    s = fc.summarize_responses("llama-3.1-8b", responses, items, chain)
    high = s.pooled >= fc.HIGH and s.p <= 0.05 / 6
    return s, fc.reading(high, s.pooled, s.word_ok, s.letter_ok, s.unparsed)


def test_simulated_replies_get_the_intended_reading(items, chain):
    """The guards do what they are for, on replies built from the real question set."""
    # A constant letter scores exactly 50% and is a letter prior, not composition.
    s, rd = _reading_of({f.moment_id: "A" for f in items}, items, chain)
    assert s.pooled == 0.5 and s.word_ok and rd == fc.LETTER
    # Always the speak word scores exactly 50% and is a word prior.
    speak = {f.moment_id: fc.LETTERS[f.options.index(fc.C_WORDS[f.family][0])] for f in items}
    s, rd = _reading_of(speak, items, chain)
    assert s.pooled == 0.5 and s.letter_ok and rd == fc.PRIOR
    # Answering with the word, not the letter: format, not composition.
    s, rd = _reading_of({f.moment_id: f.gold_word for f in items}, items, chain)
    assert s.unparsed == 320 and rd == fc.FORMAT
    # Every answer right: composes, with no prior of either kind.
    s, rd = _reading_of({f.moment_id: f.gold for f in items}, items, chain)
    assert s.pooled == 1.0 and rd == fc.COMPOSES
    assert set(s.family_a.values()) == {0.5} and set(s.family_share.values()) == {0.5}
    # Right on exactly 55% of each family, no lean: composition.
    replies = {}
    for fam in fc.TWO_ENTITY | set(dr.QUESTIONS):
        fs = sorted((f for f in items if f.family == fam), key=lambda f: f.moment_id)
        for i, f in enumerate(fs):
            wrong = "B" if f.gold == "A" else "A"
            replies[f.moment_id] = f.gold if i % 20 < 11 else wrong
    s, rd = _reading_of(replies, items, chain)
    assert s.pooled == 0.55 and s.word_ok and s.letter_ok and rd == fc.COMPOSITION


def test_mh_one_sided_against_hand_values():
    # One stratum: z = (a - E[a]) / sqrt(V); E = 7.5, V = 15^4 / (30^2 * 29).
    odds, p = fc.mh_one_sided([(10, 5, 5, 10)])
    assert odds == pytest.approx(4.0)
    z = 2.5 / (15**4 / (30 * 30 * 29)) ** 0.5
    from statistics import NormalDist

    assert p == pytest.approx(1 - NormalDist().cdf(z))
    # It halves Round 83's two-sided p when the effect is in the tested direction ...
    assert p == pytest.approx(ch.cmh([(10, 5, 5, 10)])[1] / 2)
    # ... and is the complement when it is not.
    assert fc.mh_one_sided([(5, 10, 10, 5)])[1] == pytest.approx(1 - p)
    # Degenerate strata are skipped; no information at all gives p = 1.
    assert fc.mh_one_sided([(10, 5, 5, 10), (4, 0, 0, 0)]) == pytest.approx((odds, p))
    assert fc.mh_one_sided([(4, 0, 0, 0)])[1] == 1.0


def test_decoding_and_models_match_round_83():
    assert fc.TEMPERATURE == dr.TEMPERATURE == 0 and fc.MAX_TOKENS == dr.MAX_TOKENS
    assert fc.MODELS == ch.MODELS
    assert fc.TWO_ENTITY == ch.TWO_ENTITY and fc.N_TWO == 320


def test_the_chain_test_uses_round_83s_r_and_j(chain):
    """Every two-entity moment has Round 83's R and J answer on record for every model."""
    for m in ch.models_run():
        got = ch.answers(m, chain)
        for c in chain:
            if c.family in fc.TWO_ENTITY:
                assert (c.moment_id, "r") in got and (c.moment_id, "j") in got


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


def test_all_six_models_ran():
    assert fc.models_run() == fc.MODELS


def test_results_are_complete_and_reparse(items):
    by_id = {f.moment_id: f for f in items}
    for name in fc.MODELS:
        rows = fc.load_rows(name)
        assert len(rows) == 640 and {r["moment_id"] for r in rows} == set(by_id)
        for r in rows:
            f = by_id[r["moment_id"]]
            assert r["answer"] == fc.parse_letter(r["response"])
            assert r["gold"] == f.gold and r["options"] == list(f.options)
            assert r["prompt_version"] == fc.PROMPT_VERSION


def test_results_tables_are_current(items, chain):
    assert _block(DOC, "decider-forced-summary") == fc.summary_table(items, chain)
    assert _block(DOC, "decider-forced-families") == fc.family_table(items, chain)
    assert _block(DOC, "decider-forced-compare") == fc.compare_table(items, chain)
    assert _block(DOC, "decider-forced-findings") == fc.findings(items, chain)
    readme = ROOT / "README.md"
    assert _block(readme, "decider-forced-summary") == fc.summary_table(items, chain)
    assert _block(readme, "decider-forced-findings") == fc.findings(items, chain)


@pytest.fixture(scope="module")
def ran(items, chain):
    return fc.readings(items, chain)


def test_the_pre_registered_outcome(ran):
    """Five word priors, one letter prior, nothing else; AD closes as word prior."""
    got = {m: v[3] for m, v in ran.items()}
    assert got == {
        "llama-3.1-8b": fc.LETTER,
        "qwen2.5-7b": fc.PRIOR,
        "mistral-7b": fc.PRIOR,
        "gemma-3-4b": fc.PRIOR,
        "phi-4-mini": fc.PRIOR,
        "granite-3.3-2b": fc.PRIOR,
    }
    assert fc.item_closes(list(got.values())) == fc.PRIOR
    assert not any(v[1] for v in ran.values())  # no model's C_fc is high
    assert not any(v[2] for v in ran.values())  # the chain test survives for none
    assert all(v[0].unparsed == 0 for v in ran.values())


def test_the_prose_figures(items, chain, ran):
    import json

    text = _r84()
    readme = " ".join((ROOT / "README.md").read_text().split())
    manifest = json.loads(fc.MANIFEST.read_text())
    assert set(manifest) == set(fc.MODELS)
    total = round(sum(v["call_seconds"] for v in manifest.values()))
    assert f"The calls took {total:,} seconds in total" in text
    ss = [v[0] for v in ran.values()]
    pooled = sorted(s.pooled for s in ss)
    assert f"near chance ({pooled[0]:.1%} to {pooled[-1]:.1%})" in text
    words = [m for m, v in ran.items() if v[3] == fc.PRIOR]
    letters = [m for m, v in ran.items() if v[3] == fc.LETTER]
    assert len(words) == 5 and letters == ["llama-3.1-8b"]
    assert "Five of six models fail the word-prior check and `llama-3.1-8b` fails" in text
    assert "Five of six models read *word prior* and one *letter prior*" in readme
    assert "AD closes as **word prior**" in text
    # "No reply failed the strict letter parse"; "Every reply parsed".
    assert sum(s.unparsed for s in ss) == 0 and all(
        len(fc.load_rows(m)) == 640 and all(r["answer"] for r in fc.load_rows(m)) for m in fc.MODELS
    )
    assert "No reply failed the strict letter parse" in text and "Every reply parsed" in readme
    # The two models whose free-text C was below 50% because of parse failures.
    old = {m: ch.summarize(m, chain) for m in fc.MODELS}
    low = sorted(m for m, o in old.items() if o.pooled["c"] < 0.5)
    assert low == ["granite-3.3-2b", "mistral-7b"]
    # "rise to the others' level": each is inside the other four models' C_fc range.
    others = [ran[n][0].pooled for n in fc.MODELS if n not in low]
    assert len(others) == 4
    for m in low:
        assert min(others) <= ran[m][0].pooled <= max(others), m
    # "Over parsed answers their free-text C was already 55.4% and 52.0%".
    assert (
        f"already {old['mistral-7b'].c_on_parsed:.1%} and {old['granite-3.3-2b'].c_on_parsed:.1%}"
        in text
    )
    assert "Parse failure is ruled out as the cause" in text
    assert "break at C was not a parse failure" in text
    assert "break at C was not a parse failure" in readme
    # llama's letter prior: "it says `A` only 12% of the time".
    llama = ran["llama-3.1-8b"][0]
    assert f"it says `A` only {llama.letter_a / llama.parsed:.0%} of the time" in text
    assert llama.letter_prior_families and not llama.word_prior_families
    assert (
        "the pre-registered outcome is *word prior* rather than the *break is composition*"
        in readme
    )
    assert "the prior pre-empts that reading by rule" in readme
    assert "removed after the runs; see Results" in text
    # Families with no prior.
    cs = {m: fc.compare(m, items, chain) for m in fc.MODELS}
    clean = sorted(c["clean_right"] / c["clean_n"] for c in cs.values())
    assert f"C_fc is still only {clean[0]:.1%} to {clean[-1]:.1%}" in text
    top = max(cs, key=lambda m: cs[m]["clean_right"] / cs[m]["clean_n"])
    c = cs[top]
    assert top == "gemma-3-4b"
    assert (
        f"`{top}`'s {c['clean_right']}/{c['clean_n']} "
        f"(p {dr.binom_sf(c['clean_right'], c['clean_n']):.3f}, uncorrected)" in text
    )
    # The conservative flag: a 75% lean is flagged 1.6% of the time, and every model was.
    lean = f"{dr.binom_sf_at(36, 40, 0.75):.1%}"
    assert f"a true 75% lean is flagged only {lean} of the time" in text
    assert f"a true 75% lean is flagged {lean} of the time" in readme
    assert all(s.word_prior_families or s.letter_prior_families for s in ss)
    # The examples of a word prior: `new` for travel, `previous` for street_cleaning.
    assert fc.C_WORDS["travel"][1] == "new" and fc.C_WORDS["street_cleaning"][1] == "previous"
    for fam in ("travel", "street_cleaning"):
        assert sum(fam in s.word_prior_families and s.family_share[fam] <= 0.1 for s in ss) >= 3
    # The chain test's best odds ratio, against Round 83's free-text figure.
    best = max(ss, key=lambda s: s.mh[0])
    assert best.model == "phi-4-mini"
    assert f"`phi-4-mini`'s {best.mh[0]:.2f} (p = {best.mh[1]:.3f})" in text
    assert f"against {old['phi-4-mini'].mh[0]:.2f} on Round 83's" in text
    # Format disagreement.
    diff = sorted(1 - c["same"] / c["both"] for c in cs.values())
    assert f"on {diff[0]:.0%} to {diff[-1]:.0%} of the moments" in text
    # README limitation: every model has at least two flagged families.
    assert all(len(s.word_prior_families) + len(s.letter_prior_families) >= 2 for s in ss)
    assert "one role word or one letter dominates several families" in readme
