"""Forced-choice C: Round 83's composed question, answered with a letter. Round 84.

Round 83 asked the composed question C ("is the booking for tonight's dinner
unconfirmed or confirmed?") as free text. Six models answered it at 44-57% while
finding the relevant entity (J) and reading the role (R) well. Two confounds stood in
the way of calling that a failure to compose: 19% of mistral's and 15% of granite's C
replies did not parse (most named an entity), and 7 of 48 model-family cells gave one
word at least 90% of the time.

This asks the same C question with lettered options and a one-letter answer, on the
same 640 moments (both sides of every v9 dev pair) and the same six models. Option
order is counterbalanced so that "always A", "always B" and every constant word read
exactly 50% in every family. The pre-registered rules and readings are in
docs/DECIDER_READING.md, "Round 84". Nothing is seeded from Round 83's C answers;
Round 83's R and J answers are used, as recorded, for the chain test.

    uv run python experiments/decider_forced.py --models-dir DIR --server-python PY \\
        [--only NAME ...]          # run (one llama.cpp server per model; resumes)
    uv run python experiments/decider_forced.py --tables   # print the doc/README tables

Every call is appended to ``results/decider-forced/<model>.jsonl`` as it returns.
``tests/test_decider_forced.py`` holds the question set and every figure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist

import decider_chain as ch
import decider_reading as dr

from tactbench.dataset.loader import load
from tactbench.policies.llm import render_moment
from tactbench.schema import frame_of, pair_key

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "decider-forced"
MANIFEST = OUT / "MANIFEST.json"

#: New for Round 84; Round 83's was "2026-11-23.1".
PROMPT_VERSION = "2026-11-23.2"
TEMPERATURE = dr.TEMPERATURE
MAX_TOKENS = dr.MAX_TOKENS

LETTERS = ("A", "B")
#: Replaces Round 83's "Answer with one of the two, exactly as written, and nothing else."
FC_END = "Answer with one letter, A or B, and nothing else."

#: The C question stems, exactly Round 83's, without Round 83's answer instruction.
C_STEMS: dict[str, str] = {f: q.removesuffix(dr._END) for f, q in ch.C_QUESTIONS.items()}
C_WORDS = ch.C_WORDS
TWO_ENTITY = ch.TWO_ENTITY
MODELS = ch.MODELS


def question(family: str, a: str, b: str) -> str:
    """The forced-choice C question: Round 83's stem, the two lettered options, one letter."""
    stem = C_STEMS[family].format(a=a, b=b)
    return f"{stem}\nA) {a}\nB) {b}\n{FC_END}"


@dataclass(frozen=True)
class ForcedItem:
    moment_id: str
    family: str
    frame: int
    decider: str
    speak: bool
    privileged_first: bool  # per pair: Round 82's clause-order stratum
    options: tuple[str, str]  # (word at A, word at B)
    gold_word: str
    prompt: str

    @property
    def gold(self) -> str:
        """The gold letter."""
        return LETTERS[self.options.index(self.gold_word)]

    def word(self, letter: str | None) -> str | None:
        return None if letter is None else self.options[LETTERS.index(letter)]


def _speak_word_at_a(chain: list[ch.ChainItem]) -> dict[str, bool]:
    """Per pair: does the speak-side word sit at A? Exactly half the pairs of each family.

    Pairs are ranked within each family by Round 82's clause-order stratum, then by a
    ``hashlib`` digest, and alternate. Both sides of a pair share the order.
    """
    by_family: dict[str, set[tuple[bool, str]]] = defaultdict(set)
    for c in chain:
        by_family[c.family].add((c.privileged_first, pair_key(c.moment_id)))
    out: dict[str, bool] = {}
    for pairs in by_family.values():
        ranked = sorted(
            pairs,
            key=lambda p: (
                p[0],
                hashlib.sha256(f"decider-forced:order:{p[1]}".encode()).hexdigest(),
            ),
        )
        out |= {key: i % 2 == 0 for i, (_, key) in enumerate(ranked)}
    return out


def build_items() -> list[ForcedItem]:
    """Both sides of every v9 dev pair, each with its forced-choice C question.

    The two sides of a pair share one option order, so their prompts carry the same
    tokens and opposite gold letters. Across a family's 20 pairs the speak-side word
    is at A in exactly 10. So in every family x side cell the gold letter is A in
    exactly 10 of 20, and in every family each (letter, word) pairing is gold in
    exactly 10 of 40.
    """
    chain = ch.build_items()
    at_a = _speak_word_at_a(chain)
    moments = {i.moment.id: i.moment for i in load(dr.VERSION, dr.SPLIT)}
    out = []
    for c in chain:
        m = moments[c.moment_id]
        sw, qw = C_WORDS[c.family]
        options = (sw, qw) if at_a[pair_key(c.moment_id)] else (qw, sw)
        head = f"{dr.PROMPT_PREAMBLE}\n\n{render_moment(m)}\n\n"
        out.append(
            ForcedItem(
                moment_id=c.moment_id,
                family=c.family,
                frame=frame_of(m),
                decider=c.decider,
                speak=c.speak,
                privileged_first=c.privileged_first,
                options=options,
                gold_word=sw if c.speak else qw,
                prompt=head + question(c.family, *options),
            )
        )
    return sorted(out, key=lambda f: f.moment_id)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

_LETTER = re.compile(r"\A\s*([AB])(?![A-Za-z0-9])")


def parse_letter(text: str | None) -> str | None:
    """Strict: the reply's first non-space character is a capital A or B, not followed by
    a letter or digit. "B", " A.", "A) unconfirmed" parse; "Answer: B", "a", "**A**",
    "Absolutely" and a role word alone do not."""
    m = _LETTER.match(text or "")
    return m[1] if m else None


# --------------------------------------------------------------------------- #
# Baselines
# --------------------------------------------------------------------------- #


def _first_role_word_in_decider(f: ForcedItem) -> str:
    sw, qw = C_WORDS[f.family]
    return sw if f.privileged_first else qw


BASELINES = {
    "always A": lambda f: f.gold == "A",
    "always B": lambda f: f.gold == "B",
    "always the speak word": lambda f: f.gold_word == C_WORDS[f.family][0],
    "always the silent word": lambda f: f.gold_word == C_WORDS[f.family][1],
    "role word named first in decider": lambda f: f.gold_word == _first_role_word_in_decider(f),
}


def baselines_table(items: list[ForcedItem]) -> str:
    fams = sorted(dr.QUESTIONS)
    lines = [
        "| baseline | overall | per family: low / high | per family × side: low / high |",
        "|---|---|---|---|",
    ]
    for name, rule in BASELINES.items():
        fam = [
            sum(rule(f) for f in items if f.family == x) / sum(f.family == x for f in items)
            for x in fams
        ]
        cell = [
            sum(rule(f) for f in items if f.family == x and f.speak == s)
            / sum(f.family == x and f.speak == s for f in items)
            for x in fams
            for s in (True, False)
        ]
        overall = sum(rule(f) for f in items) / len(items)
        lines.append(
            f"| {name} | {overall:.1%} | {min(fam):.0%} / {max(fam):.0%} "
            f"| {min(cell):.0%} / {max(cell):.0%} |"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Statistics and pre-registered readings
# --------------------------------------------------------------------------- #

N_TWO = ch.N_TWO  # 320: 8 two-entity families x 40
HIGH, LOW = 0.70, 0.60
#: A family's parsed answers are a word (or letter) prior when at least this share name
#: one word (or are one letter).
WORD_PRIOR = 0.90
LETTER_PRIOR = 0.90
#: Each prior check passes with at most this many flagged families out of 8.
MAX_PRIOR_FAMILIES = 1
#: The format guard: more than this many unparsed two-entity answers (10% of 320).
MAX_UNPARSED = 32
#: A reading shared by this many models or more closes queue AD as that reading.
CLOSE_AT = 4

PRIOR = "word prior"
LETTER = "letter prior"
FORMAT = "format"
COMPOSES = "composes when the format is fixed"
COMPOSITION = "break is composition"
UNRESOLVED = "unresolved"
#: Every reading, in the order the rules are checked.
READINGS = (PRIOR, LETTER, FORMAT, COMPOSES, COMPOSITION, UNRESOLVED)
CAUSE_UNRESOLVED = "located at C, cause unresolved"


def high_bar() -> int:
    """Right answers (of 320) for "at least 70%"."""
    return math.ceil(HIGH * N_TWO)


def low_bar() -> int:
    """Right answers (of 320) below which C_fc is "below 60%"."""
    return math.ceil(LOW * N_TWO)


def holm_first_step(n_models: int = len(MODELS)) -> int:
    """Fewest right of 320 that clears the first Holm step across the models."""
    return min(k for k in range(N_TWO + 1) if dr.binom_sf(k, N_TWO) <= dr.ALPHA / n_models)


def _flagged(share: float, bar: float) -> bool:
    # Rounded so that a share of exactly 10% (1 - 0.9 is 0.0999... in floating point)
    # counts, as the rule says.
    return round(max(share, 1 - share), 9) >= bar


def reading(c_high: bool, c: float, word_ok: bool, letter_ok: bool, unparsed: int) -> str:
    """The pre-registered per-model reading, rules checked in the order of READINGS."""
    if not word_ok:
        return PRIOR
    if not letter_ok:
        return LETTER
    if unparsed > MAX_UNPARSED:
        return FORMAT
    if c_high:
        return COMPOSES
    if c < LOW:
        return COMPOSITION
    return UNRESOLVED


def item_closes(readings: list[str]) -> str:
    """How queue AD closes: a reading shared by CLOSE_AT or more of the six models, else
    "located at C, cause unresolved". "Break is composition" closes it as composition."""
    for r in READINGS:
        if sum(x == r for x in readings) >= CLOSE_AT:
            return "composition" if r == COMPOSITION else r
    return CAUSE_UNRESOLVED


def mh_one_sided(tables: list[tuple[int, int, int, int]]) -> tuple[float, float]:
    """Mantel-Haenszel common odds ratio and the one-sided CMH p (no continuity correction).

    Each table is [[a, b], [c, d]] = [[C right, C wrong] | R and J right; otherwise].
    The alternative is a > E[a]: C more often right when R and J are both right. Strata
    with a zero margin carry no information and are skipped.
    """
    num = den = s_a = s_e = s_v = 0.0
    for a, b, c, d in tables:
        n = a + b + c + d
        r1, r2, c1, c2 = a + b, c + d, a + c, b + d
        if n < 2 or 0 in (r1, r2, c1, c2):
            continue
        num += a * d / n
        den += b * c / n
        s_a += a
        s_e += r1 * c1 / n
        s_v += r1 * r2 * c1 * c2 / (n * n * (n - 1))
    odds = num / den if den else math.inf
    if not s_v:
        return odds, 1.0
    z = (s_a - s_e) / math.sqrt(s_v)
    return odds, 0.5 * math.erfc(z / math.sqrt(2))


def mh_power(both: int, rest: int, p_rest: float, diff: float, alpha: float) -> float:
    """Approximate power of the one-sided chain test: a two-proportion z test, unstratified.

    C_fc is right at ``p_rest + diff`` on the ``both`` items with R and J right and at
    ``p_rest`` on the ``rest``. Stratifying by family x side can only lose information
    relative to this when the strata share one effect, so treat it as an upper guide.
    """
    p1 = p_rest + diff
    pbar = (both * p1 + rest * p_rest) / (both + rest)
    se0 = math.sqrt(pbar * (1 - pbar) * (1 / both + 1 / rest))
    se1 = math.sqrt(p1 * (1 - p1) / both + p_rest * (1 - p_rest) / rest)
    z = NormalDist().inv_cdf(1 - alpha)
    return 1 - NormalDist().cdf((z * se0 - diff) / se1)


def result_path(name: str) -> Path:
    return OUT / f"{name}.jsonl"


def load_rows(name: str) -> list[dict]:
    return [json.loads(line) for line in result_path(name).read_text().splitlines() if line]


#: One call per moment.
CALLS_PER_MODEL = 640


def models_run() -> list[str]:
    """Models with a complete run; a run still in progress is not reported."""
    return [
        m
        for m in MODELS
        if result_path(m).exists()
        and len({r["moment_id"] for r in load_rows(m)}) == CALLS_PER_MODEL
    ]


@dataclass
class ForcedSummary:
    model: str
    right: int  # two-entity: parsed letter == gold, of N_TWO (unparsed count wrong)
    unparsed: int  # two-entity
    parsed_right: int
    letter_a: int  # parsed two-entity answers that are A
    family_share: dict[str, float]  # two-entity family -> speak-word share of parsed
    family_a: dict[str, float]  # two-entity family -> share of parsed answers that are A
    family_right: dict[str, int]  # every family -> right of 40
    overall: float  # all 16 families, n = 640
    strata: list[tuple[int, int, int, int]]  # family x side, R83's R and J vs C_fc

    @property
    def pooled(self) -> float:
        return self.right / N_TWO

    @property
    def p(self) -> float:
        return dr.binom_sf(self.right, N_TWO)

    @property
    def parsed(self) -> int:
        return N_TWO - self.unparsed

    @property
    def on_parsed(self) -> float:
        return self.parsed_right / self.parsed if self.parsed else 0.0

    @property
    def word_prior_families(self) -> list[str]:
        return sorted(f for f, v in self.family_share.items() if _flagged(v, WORD_PRIOR))

    @property
    def letter_prior_families(self) -> list[str]:
        return sorted(f for f, v in self.family_a.items() if _flagged(v, LETTER_PRIOR))

    @property
    def word_ok(self) -> bool:
        return len(self.word_prior_families) <= MAX_PRIOR_FAMILIES

    @property
    def letter_ok(self) -> bool:
        return len(self.letter_prior_families) <= MAX_PRIOR_FAMILIES

    @property
    def mh(self) -> tuple[float, float]:
        return mh_one_sided(self.strata)


def summarize(name: str, items: list[ForcedItem], chain: list[ch.ChainItem]) -> ForcedSummary:
    responses = {r["moment_id"]: r["response"] for r in load_rows(name)}
    return summarize_responses(name, responses, items, chain)


def summarize_responses(
    name: str, responses: dict[str, str], items: list[ForcedItem], chain: list[ch.ChainItem]
) -> ForcedSummary:
    """The summary of one model's replies (moment id -> reply text); R and J are ``name``'s
    Round 83 answers."""
    answer = {f.moment_id: parse_letter(responses[f.moment_id]) for f in items}
    ok = {f.moment_id: answer[f.moment_id] == f.gold for f in items}
    two = [f for f in items if f.family in TWO_ENTITY]
    parsed = [f for f in two if answer[f.moment_id] is not None]
    share, share_a = {}, {}
    for fam in sorted(TWO_ENTITY):
        fp = [f for f in parsed if f.family == fam]
        speak = sum(f.word(answer[f.moment_id]) == C_WORDS[fam][0] for f in fp)
        share[fam] = speak / len(fp) if fp else 0.5
        share_a[fam] = sum(answer[f.moment_id] == "A" for f in fp) / len(fp) if fp else 0.5
    # Round 83's own R and J answers, as recorded.
    r83 = ch.answers(name, chain)

    def table(fs: list[ForcedItem]) -> tuple[int, int, int, int]:
        both = [f for f in fs if r83[(f.moment_id, "r")] and r83[(f.moment_id, "j")]]
        rest = [f for f in fs if f not in both]
        a = sum(ok[f.moment_id] for f in both)
        c = sum(ok[f.moment_id] for f in rest)
        return a, len(both) - a, c, len(rest) - c

    return ForcedSummary(
        model=name,
        right=sum(ok[f.moment_id] for f in two),
        unparsed=len(two) - len(parsed),
        parsed_right=sum(ok[f.moment_id] for f in parsed),
        letter_a=sum(answer[f.moment_id] == "A" for f in parsed),
        family_share=share,
        family_a=share_a,
        family_right={
            fam: sum(ok[f.moment_id] for f in items if f.family == fam)
            for fam in sorted(dr.QUESTIONS)
        },
        overall=sum(ok.values()) / len(items),
        strata=[
            table([f for f in two if f.family == fam and f.speak == side])
            for fam in sorted(TWO_ENTITY)
            for side in (True, False)
        ],
    )


def readings(items: list[ForcedItem], chain: list[ch.ChainItem]) -> dict[str, tuple]:
    """model -> (summary, C_fc high, MH survives Holm, reading), over the models run."""
    ss = [summarize(m, items, chain) for m in models_run()]
    above = dict(zip([s.model for s in ss], dr.holm([s.p for s in ss]), strict=True))
    mh = dict(zip([s.model for s in ss], dr.holm([s.mh[1] for s in ss]), strict=True))
    out = {}
    for s in ss:
        high = s.pooled >= HIGH and above[s.model]
        rd = reading(high, s.pooled, s.word_ok, s.letter_ok, s.unparsed)
        out[s.model] = (s, high, mh[s.model], rd)
    return out


def summary_table(items: list[ForcedItem], chain: list[ch.ChainItem]) -> str:
    """The pre-registered figures, pooled over the eight two-entity families."""
    lines = [
        "| model | C_fc (unparsed wrong) | unparsed | C_fc on parsed | says A (parsed) "
        "| families ≥ 90% one word | families ≥ 90% one letter | C_fc high "
        "| MH OR (one-sided p) | MH survives Holm "
        "| reading | C_fc, all 16 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, (s, high, mh_ok, rd) in readings(items, chain).items():
        fams = s.word_prior_families
        listed = ", ".join(f"`{f}` {s.family_share[f]:.2f}" for f in fams) if fams else "none"
        lfams = s.letter_prior_families
        lettered = ", ".join(f"`{f}` {s.family_a[f]:.2f}" for f in lfams) if lfams else "none"
        odds, p = s.mh
        say_a = f"{s.letter_a / s.parsed:.0%}" if s.parsed else "—"
        lines.append(
            f"| `{name}` | {s.right}/{N_TWO} ({s.pooled:.1%}, p {dr._p(s.p)}) | {s.unparsed} "
            f"| {s.parsed_right}/{s.parsed} ({s.on_parsed:.1%}) | {say_a} "
            f"| {len(fams)}: {listed} | {len(lfams)}: {lettered} "
            f"| {'yes' if high else 'no'} | {odds:.2f} ({p:.4f}) "
            f"| {'yes' if mh_ok else 'no'} | {rd} | {s.overall:.1%} |"
        )
    return "\n".join(lines)


def family_table(items: list[ForcedItem], chain: list[ch.ChainItem]) -> str:
    fams = sorted(dr.QUESTIONS)
    lines = [
        "| model | " + " | ".join(dr.SHORT[f] for f in fams) + " |",
        "|---|" + "---|" * len(fams),
    ]
    for name in models_run():
        s = summarize(name, items, chain)
        lines.append(f"| `{name}` | " + " | ".join(str(s.family_right[f]) for f in fams) + " |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


def run_model(name: str, path: Path, server_python: str, threads: int) -> float:
    import run_local_llms as rl

    items = build_items()
    done = {r["moment_id"] for r in load_rows(name)} if result_path(name).exists() else set()
    todo = [f for f in items if f.moment_id not in done]
    if not todo:
        return 0.0
    OUT.mkdir(parents=True, exist_ok=True)
    log = open(OUT.parent / f".server-forced-{name}.log", "w")  # noqa: SIM115
    proc = subprocess.Popen(
        [server_python, "-m", "llama_cpp.server", "--model", str(path),
         "--model_alias", name, "--host", "127.0.0.1", "--port", str(rl.PORT),
         "--n_ctx", str(dr.N_CTX), "--n_threads", str(threads), "--seed", "0"],
        stdout=log, stderr=subprocess.STDOUT,
    )  # fmt: skip
    spent = 0.0
    try:
        rl.wait_ready(proc)
        with result_path(name).open("a") as f:
            for i, item in enumerate(todo):
                t0 = time.time()
                text = dr._ask(rl.PORT, name, item.prompt)
                dt = time.time() - t0
                spent += dt
                row = {
                    "moment_id": item.moment_id,
                    "family": item.family,
                    "options": list(item.options),
                    "gold": item.gold,
                    "response": text,
                    "answer": parse_letter(text),
                    "prompt_version": PROMPT_VERSION,
                    "seconds": round(dt, 2),
                }
                f.write(json.dumps(row) + "\n")
                f.flush()
                if i % 30 == 0:
                    print(f"{name}: {len(done) + i + 1}/{len(done) + len(todo)} {dt:.1f}s")
    finally:
        proc.terminate()  # by the PID we started, never by name
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()
    return spent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", type=Path)
    ap.add_argument("--server-python")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--only", action="append")
    ap.add_argument("--tables", action="store_true")
    args = ap.parse_args()
    if args.tables:
        items = build_items()
        print(f"## baselines\n{baselines_table(items)}\n")
        if models_run():
            chain = ch.build_items()
            print(f"## summary\n{summary_table(items, chain)}\n")
            print(f"## families\n{family_table(items, chain)}\n")
        return
    if not (args.models_dir and args.server_python):
        ap.error("--models-dir and --server-python are required to run")
    import run_local_llms as rl

    runtime = subprocess.run(
        [args.server_python, "-c", "import llama_cpp; print(llama_cpp.__version__)"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    for name in MODELS:
        if args.only and name not in args.only:
            continue
        repo, fname = rl.MODELS[name]
        path = args.models_dir / fname
        if not path.exists():
            print(f"skip {name}: {path} not present", file=sys.stderr)
            continue
        spent = run_model(name, path, args.server_python, args.threads)
        manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
        manifest[name] = {
            "hf_repo": repo,
            "file": fname,
            "sha256": rl.sha256(path),
            "runtime": f"llama-cpp-python {runtime}",
            "n_ctx": dr.N_CTX,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "threads": args.threads,
            "prompt_version": PROMPT_VERSION,
            "call_seconds": round(sum(r["seconds"] for r in load_rows(name)), 1),
        }
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"{name}: done, {spent:.0f}s of calls this run", flush=True)


if __name__ == "__main__":
    main()
