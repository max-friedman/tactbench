"""The decision chain: read the role, find the relevant entity, compose them. Round 83.

Round 82 asked models which entity the decider puts in its role (R) and found 60-79%
right on the good ones, yet their interrupt decisions were no more often right when
the reading was. The decision needs a chain:

    R  READ which entity holds the decider's role ("Marzano's booking is confirmed");
    J  find which entity the BODY makes relevant ("tonight's dinner is at Marzano");
    C  COMPOSE them ("so tonight's booking is confirmed").

This asks all three on both sides of every v9 dev pair (640 moments; R on the side
Round 82 asked is Round 82's own answer) and looks for where the chain breaks.
Questions, power and the pre-registered readings: docs/DECIDER_READING.md, "Round 83".

    uv run python experiments/decider_chain.py --models-dir DIR --server-python PY \\
        [--only NAME ...]          # run (one llama.cpp server per model; resumes)
    uv run python experiments/decider_chain.py --tables   # print the doc/README tables

Every call is appended to ``results/decider-chain/<model>.jsonl`` as it returns. Calls
go moment by moment (R, J, C on one moment in turn), so the server reuses the shared
prompt prefix. ``tests/test_decider_chain.py`` holds the question set and every figure.
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

import decider_reading as dr

from tactbench.dataset.loader import load
from tactbench.policies.llm import render_moment
from tactbench.schema import frame_of, pair_key

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "decider-chain"
MANIFEST = OUT / "MANIFEST.json"

PROMPT_VERSION = "2026-11-23.1"
TEMPERATURE = dr.TEMPERATURE
MAX_TOKENS = dr.MAX_TOKENS

_ASK = "According to the signals, "

#: (J) Which entity does the body make relevant? Answerable from the body (or, where
#: the body names no entity, from who the user is), not from the decider. Gold is the
#: family's marker on both sides of a pair.
J_QUESTIONS: dict[str, str] = {
    "childcare": "which of the two is the user: {a} or {b}?",
    "commerce": "which item's return window is closing: {a} or {b}?",
    "deadline": "which of the two is the user: {a} or {b}?",
    "dinner_booking": "which restaurant is tonight's dinner at: {a} or {b}?",
    "driving": "which road is the user's own: {a} or {b}?",
    "finance": "which account does the card autopay draw from tonight: {a} or {b}?",
    "health": "which prescription is the user's own: {a} or {b}?",
    "home_security": "where has the camera seen motion: {a} or {b}?",
    "meeting_prep": "which meeting is the revised vendor contract for: {a} or {b}?",
    "pet_care": "which pet left its breakfast uneaten: {a} or {b}?",
    "photo_backup": "which album is deleted at midnight: {a} or {b}?",
    "quiet_hours": "which of the two is the user: {a} or {b}?",
    "river_swim": "where is the sewage overflow: {a} or {b}?",
    "street_cleaning": "which street is swept at 7am tomorrow: {a} or {b}?",
    "travel": "which gate did the flight's gate change move away from: {a} or {b}?",
    "water_notice": "which district is under the boil-water notice: {a} or {b}?",
}

#: (C) The decision restated as a fact about the relevant entity, with two role words
#: as options: ``(speak-side word, silent-side word)``. The question names the entity
#: only by what the body says about it, so answering needs J and R together.
C_WORDS: dict[str, tuple[str, str]] = {
    "childcare": ("collecting", "away"),
    "commerce": ("unopened", "used"),
    "deadline": ("main", "backup"),
    "dinner_booking": ("unconfirmed", "confirmed"),
    "driving": ("jammed", "clear"),
    "finance": ("underfunded", "covered"),
    "health": ("uncollected", "collected"),
    "home_security": ("unexpected", "expected"),
    "meeting_prep": ("upcoming", "started"),
    "pet_care": ("fragile", "healthy"),
    "photo_backup": ("lost", "saved"),
    "quiet_hours": ("near", "far"),
    "river_swim": ("upstream", "downstream"),
    "street_cleaning": ("current", "previous"),
    "travel": ("old", "new"),
    "water_notice": ("current", "former"),
}
#: The two role words appear only in the counterbalanced ``{a} or {b}`` slot, so the
#: wording of the question names neither of them first.
C_QUESTIONS: dict[str, str] = {
    "childcare": "for today's school pickup, is the user {a} or {b}?",
    "commerce": "is the item whose return window is closing {a} or {b}?",
    "deadline": "is the user the {a} or the {b} person on call?",
    "dinner_booking": "is the booking for tonight's dinner {a} or {b}?",
    "driving": "is the user's own route {a} or {b}?",
    "finance": "is the account the card autopay draws from tonight {a} or {b}?",
    "health": "is the user's own prescription {a} or {b}?",
    "home_security": "at the place where the camera has seen motion, is a worker {a} or {b}?",
    "meeting_prep": "is the meeting the revised vendor contract is for {a} or {b}?",
    "pet_care": "is the pet that left its breakfast uneaten {a} or {b}?",
    "photo_backup": "when the album deleted at midnight goes, are its photos {a} or {b}?",
    "quiet_hours": "is the user {a} or {b} from the hospital tonight?",
    "river_swim": "is the sewage overflow {a} or {b} of the club's swim?",
    "street_cleaning": "is the street swept at 7am tomorrow the car's {a} or {b} spot?",
    "travel": "is the passenger right now at the {a} or the {b} gate?",
    "water_notice": "is the district under the boil-water notice the user's {a} or {b} home?",
}
J_QUESTIONS = {f: _ASK + q + dr._END for f, q in J_QUESTIONS.items()}
C_QUESTIONS = {f: _ASK + q + dr._END for f, q in C_QUESTIONS.items()}

#: Families whose body names both entities, drawn from one pool per pair. In the other
#: eight the body names one entity or none: the relevant one is the user (``you``,
#: ``your route``) or the one thing the body mentions (``checking``, the item, the
#: contract), the same on every item, so J there can be answered by a constant.
TWO_ENTITY = frozenset(
    {
        "dinner_booking",
        "home_security",
        "pet_care",
        "photo_backup",
        "river_swim",
        "street_cleaning",
        "travel",
        "water_notice",
    }
)

#: Models, largest first (the run order).
MODELS = ["llama-3.1-8b", "qwen2.5-7b", "mistral-7b", "gemma-3-4b", "phi-4-mini", "granite-3.3-2b"]


@dataclass(frozen=True)
class Ask:
    prompt: str
    options: tuple[str, str]
    gold: str


@dataclass(frozen=True)
class ChainItem:
    moment_id: str
    family: str
    frame: int
    decider: str
    speak: bool
    marker: str
    privileged_first: bool
    r: Ask
    j: Ask
    c: Ask
    r_from_r82: bool


def _flags(keys: list[str], tag: str) -> dict[str, bool]:
    ranked = sorted(
        keys, key=lambda k: hashlib.sha256(f"decider-chain:{tag}:{k}".encode()).hexdigest()
    )
    return {k: i % 2 == 0 for i, k in enumerate(ranked)}


def _ordered(gold: str, wrong: str, gold_first: bool) -> tuple[str, str]:
    return (gold, wrong) if gold_first else (wrong, gold)


def build_items() -> list[ChainItem]:
    """Both sides of every v9 dev pair, each with its R, J and C question.

    R on the side Round 82 asked is Round 82's question, unchanged; on the other side
    it is the same question with the partner's option order reversed. J and C option
    orders alternate in digest order within each (family, clause order) stratum, and
    the two sides of a pair take opposite orders. So in every family each of "the first
    option" and "the entity (or role) named first in the decider" is the answer to
    exactly 20 of the 40 questions of each kind.
    """
    r82 = {pair_key(q.moment_id): q for q in dr.build_questions()}
    items = load(dr.VERSION, dr.SPLIT)
    strata: dict[tuple[str, bool], list[str]] = defaultdict(list)
    for key, q in r82.items():
        strata[(q.family, q.privileged_first)].append(key)
    j_first: dict[str, bool] = {}
    c_first: dict[str, bool] = {}
    for keys in strata.values():
        j_first |= _flags(keys, "j")
        c_first |= _flags(keys, "c")

    out = []
    for it in items:
        m = it.moment
        key = pair_key(m.id)
        asked = r82[key]
        speak = it.label.should_surface
        frame = frame_of(m)
        decider = m.signals[-1].content
        priv, other = dr.roles(decider, m.family, frame)
        marker = priv if speak else other
        head = f"{dr.PROMPT_PREAMBLE}\n\n{render_moment(m)}\n\n"
        if asked.moment_id == m.id:
            r = Ask(asked.prompt, asked.options, asked.gold)
        else:
            opts = (asked.options[1], asked.options[0])
            gold = priv if dr.ASKED_ROLE[m.family] == "privileged" else other
            r = Ask(head + dr.QUESTIONS[m.family].format(a=opts[0], b=opts[1]), opts, gold)
        jo = _ordered(marker, other if marker == priv else priv, j_first[key] == speak)
        j = Ask(head + J_QUESTIONS[m.family].format(a=jo[0], b=jo[1]), jo, marker)
        sw, qw = C_WORDS[m.family]
        cg, cw = (sw, qw) if speak else (qw, sw)
        co = _ordered(cg, cw, c_first[key] == speak)
        c = Ask(head + C_QUESTIONS[m.family].format(a=co[0], b=co[1]), co, cg)
        out.append(
            ChainItem(
                moment_id=m.id,
                family=m.family,
                frame=frame,
                decider=decider,
                speak=speak,
                marker=marker,
                privileged_first=asked.privileged_first,
                r=r,
                j=j,
                c=c,
                r_from_r82=asked.moment_id == m.id,
            )
        )
    return sorted(out, key=lambda c: c.moment_id)


# --------------------------------------------------------------------------- #
# Baselines
# --------------------------------------------------------------------------- #


def first_named_in_decider(c: ChainItem, kind: str) -> str:
    """The option the decider names first: an entity for R and J, a role word for C."""
    priv, other = dr.roles(c.decider, c.family, c.frame)
    if kind == "c":
        sw, qw = C_WORDS[c.family]
        return sw if c.privileged_first else qw
    return priv if c.privileged_first else other


def key_in(option: str, text: str) -> bool:
    return dr.parse_answer(text, (option, "\0")) == option


def first_named_in_body(c: ChainItem, body: str) -> str:
    """The option the body names first; the first option when it names neither."""
    pos = []
    for opt in c.j.options:
        m = re.search(rf"(?<![\w-]){re.escape(dr._key(opt))}", body, re.IGNORECASE)
        pos.append(m.start() if m else math.inf)
    return c.j.options[0] if pos[0] <= pos[1] else c.j.options[1]


def _bodies() -> dict[str, str]:
    return {
        i.moment.id: " ".join(s.content for s in i.moment.signals[:-1])
        for i in load(dr.VERSION, dr.SPLIT)
    }


def baselines(chain: list[ChainItem]) -> list[tuple[str, str, dict[str, float]]]:
    bodies = _bodies()
    rules = [
        ("R", "always first option", lambda c: c.r.options[0] == c.r.gold),
        ("R", "first-named in decider", lambda c: first_named_in_decider(c, "r") == c.r.gold),
        ("J", "always first option", lambda c: c.j.options[0] == c.j.gold),
        ("J", "first-named in decider", lambda c: first_named_in_decider(c, "j") == c.j.gold),
        (
            "J",
            "first-named in body",
            lambda c: first_named_in_body(c, bodies[c.moment_id]) == c.j.gold,
        ),
        ("C", "always first option", lambda c: c.c.options[0] == c.c.gold),
        ("C", "first-named in decider", lambda c: first_named_in_decider(c, "c") == c.c.gold),
        ("C", "always the speak word", lambda c: c.c.gold == C_WORDS[c.family][0]),
    ]
    out = []
    for kind, name, f in rules:
        per = {
            fam: sum(f(c) for c in chain if c.family == fam) / sum(c.family == fam for c in chain)
            for fam in sorted(dr.QUESTIONS)
        }
        per["all"] = sum(f(c) for c in chain) / len(chain)
        out.append((kind, name, per))
    return out


def baselines_table(chain: list[ChainItem]) -> str:
    lines = [
        "| question | baseline | overall | lowest family | highest family |",
        "|---|---|---|---|---|",
    ]
    for kind, name, per in baselines(chain):
        fams = [v for k, v in per.items() if k != "all"]
        lines.append(f"| {kind} | {name} | {per['all']:.1%} | {min(fams):.0%} | {max(fams):.0%} |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Statistics and pre-registered readings
# --------------------------------------------------------------------------- #

#: Moments in the eight two-entity families (8 x 40): the pooled n per question.
N_TWO = 320

#: At n = 40 the first Holm step over 16 families needs p <= 0.05/16: 30 of 40.
FIRST_HOLM_STEP = 30
HIGH, LOW = 0.70, 0.60


def reading(r: float, j: float, c: float) -> str:
    """Where the chain breaks, from pooled accuracy on the two-entity families."""
    if j < LOW:
        return "finding the relevant entity"
    if r < LOW:
        return "reading the decider"
    if r >= HIGH and j >= HIGH and c < LOW:
        return "composition"
    if r >= HIGH and j >= HIGH and c >= HIGH:
        return "no break before the decision"
    return "unresolved"


def fisher_greater(a: int, b: int, c: int, d: int) -> float:
    """One-sided Fisher exact p for [[a, b], [c, d]]: P(top-left >= a) under the margins."""
    n, row, col = a + b + c + d, a + b, a + c
    hi = min(row, col)
    terms = (math.comb(row, x) * math.comb(n - row, col - x) for x in range(a, hi + 1))
    return sum(terms) / math.comb(n, col)


def result_path(name: str) -> Path:
    return OUT / f"{name}.jsonl"


def load_rows(name: str) -> list[dict]:
    return [json.loads(line) for line in result_path(name).read_text().splitlines() if line]


#: Calls a complete run makes: J and C on all 640 moments, R on the 320 Round 82 did not ask.
CALLS_PER_MODEL = 1600


def models_run() -> list[str]:
    """Models with a complete run; a run still in progress is not reported."""
    return [
        m
        for m in MODELS
        if result_path(m).exists()
        and len({(r["moment_id"], r["kind"]) for r in load_rows(m)}) == CALLS_PER_MODEL
    ]


def answers(name: str, chain: list[ChainItem]) -> dict[tuple[str, str], bool]:
    """(moment_id, kind) -> right, R on the Round 82 side taken from Round 82's run."""
    by_id = {c.moment_id: c for c in chain}
    out = {}
    for r in dr.load_rows(name):
        out[(r["moment_id"], "r")] = r["answer"] == by_id[r["moment_id"]].r.gold
    for r in load_rows(name):
        q = getattr(by_id[r["moment_id"]], r["kind"])
        out[(r["moment_id"], r["kind"])] = r["answer"] == q.gold
    return out


@dataclass
class ChainSummary:
    model: str
    pooled: dict[str, float]  # two-entity families, n = 320 per kind
    overall: dict[str, float]  # all 16 families, n = 640 per kind
    per_family: dict[str, dict[str, int]]  # kind -> family -> right of 40
    read: dict[str, dict[str, bool]]  # kind -> family -> Holm
    chain_table: tuple[int, int, int, int]  # two-entity: [[C ok, C bad] | R&J ok, else]
    unparsed: dict[str, int]
    c_speak_share: float  # two-entity C answers naming the speak-side word

    def right(self, kind: str) -> int:
        return round(self.pooled[kind] * N_TWO)

    def p(self, kind: str) -> float:
        return dr.binom_sf(self.right(kind), N_TWO)

    @property
    def reading(self) -> str:
        return reading(self.pooled["r"], self.pooled["j"], self.pooled["c"])

    @property
    def chain_p(self) -> float:
        return fisher_greater(*self.chain_table)


def summarize(name: str, chain: list[ChainItem]) -> ChainSummary:
    ok = answers(name, chain)
    fams = sorted(dr.QUESTIONS)
    per = {k: {f: 0 for f in fams} for k in "rjc"}
    for c in chain:
        for k in "rjc":
            per[k][c.family] += ok[(c.moment_id, k)]
    read = {
        k: dict(zip(fams, dr.holm([dr.binom_sf(per[k][f], 40) for f in fams]), strict=True))
        for k in "rjc"
    }
    two = [c for c in chain if c.family in TWO_ENTITY]
    pooled = {k: sum(ok[(c.moment_id, k)] for c in two) / len(two) for k in "rjc"}
    overall = {k: sum(ok[(c.moment_id, k)] for c in chain) / len(chain) for k in "rjc"}
    both = [c for c in two if ok[(c.moment_id, "r")] and ok[(c.moment_id, "j")]]
    rest = [c for c in two if not (ok[(c.moment_id, "r")] and ok[(c.moment_id, "j")])]
    a = sum(ok[(c.moment_id, "c")] for c in both)
    cc = sum(ok[(c.moment_id, "c")] for c in rest)
    unparsed = {k: 0 for k in "rjc"}
    for r in load_rows(name):
        unparsed[r["kind"]] += r["answer"] is None
    unparsed["r"] += sum(r["answer"] is None for r in dr.load_rows(name))
    c_rows = [r for r in load_rows(name) if r["kind"] == "c" and r["family"] in TWO_ENTITY]
    speak = sum(r["answer"] == C_WORDS[r["family"]][0] for r in c_rows)
    return ChainSummary(
        model=name,
        pooled=pooled,
        overall=overall,
        per_family=per,
        read=read,
        chain_table=(a, len(both) - a, cc, len(rest) - cc),
        unparsed=unparsed,
        c_speak_share=speak / len(c_rows),
    )


def _ratio(x: int, n: int) -> str:
    return f"{x}/{n} ({x / n:.0%})" if n else "—"


def _acc(s: ChainSummary, kind: str) -> str:
    p = s.p(kind)
    return f"{s.right(kind)}/{N_TWO} ({s.pooled[kind]:.1%}, p {dr._p(p)})"


def summary_table(chain: list[ChainItem]) -> str:
    lines = [
        "| model | R | J | C | pre-registered reading | C right, R and J right "
        "| C right, otherwise | Fisher p | C says the speak word | R / J / C, all 16 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name in models_run():
        s = summarize(name, chain)
        a, b, c, d = s.chain_table
        lines.append(
            f"| `{name}` | {_acc(s, 'r')} | {_acc(s, 'j')} | {_acc(s, 'c')} "
            f"| {s.reading} | {_ratio(a, a + b)} | {_ratio(c, c + d)} | {s.chain_p:.4f} "
            f"| {s.c_speak_share:.0%} "
            f"| {s.overall['r']:.1%} / {s.overall['j']:.1%} / {s.overall['c']:.1%} |"
        )
    return "\n".join(lines)


def family_table(chain: list[ChainItem]) -> str:
    fams = sorted(dr.QUESTIONS)
    lines = [
        "| model | q | " + " | ".join(dr.SHORT[f] for f in fams) + " | read |",
        "|---|---|" + "---|" * (len(fams) + 1),
    ]
    for name in models_run():
        s = summarize(name, chain)
        for k in "rjc":
            cells = [
                f"**{s.per_family[k][f]}**" if s.read[k][f] else str(s.per_family[k][f])
                for f in fams
            ]
            lines.append(
                f"| `{name}` | {k.upper()} | "
                + " | ".join(cells)
                + f" | {sum(s.read[k].values())} |"
            )
    return "\n".join(lines)


def findings(chain: list[ChainItem]) -> str:
    """The published headline (Round 83); every figure in it is recomputed."""
    ss = [summarize(n, chain) for n in models_run()]

    def span(kind: str) -> str:
        v = sorted(s.pooled[kind] for s in ss)
        return f"{v[0]:.1%} to {v[-1]:.1%}"

    counts: dict[str, int] = defaultdict(int)
    for s in ss:
        counts[s.reading] += 1
    parts = ", ".join(f"**{v}** {k}" for k, v in sorted(counts.items()))
    sig = [s for s in ss if s.chain_p < dr.ALPHA]
    c_above = sum(s.p("c") < dr.ALPHA for s in ss)
    named = ", ".join(f"`{s.model}` (p = {s.chain_p:.3f})" for s in sig) or "none"
    return (
        f"Pooled over the eight two-entity families (n = {N_TWO} per question), all "
        f"{len(ss)} models find the entity the body makes relevant (J **{span('j')}**) and "
        f"read the decider's role well above chance (R **{span('r')}**), but answer the "
        f"composed question near a coin (C **{span('c')}**; {c_above} of {len(ss)} above "
        f"50% at p < 0.05). Pre-registered readings: {parts}. The per-item chain test (C "
        f"more often right when R and J are both right, one-sided Fisher p < 0.05) holds "
        f"for {len(sig)} of {len(ss)}: {named}."
    )


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


def run_model(name: str, path: Path, server_python: str, threads: int) -> float:
    import run_local_llms as rl

    chain = build_items()
    done = (
        {(r["moment_id"], r["kind"]) for r in load_rows(name)}
        if result_path(name).exists()
        else set()
    )
    todo = [
        (c, k)
        for c in chain
        for k in "rjc"
        if (c.moment_id, k) not in done and not (k == "r" and c.r_from_r82)
    ]
    if not todo:
        return 0.0
    OUT.mkdir(parents=True, exist_ok=True)
    log = open(OUT.parent / f".server-chain-{name}.log", "w")  # noqa: SIM115
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
            for i, (c, k) in enumerate(todo):
                q = getattr(c, k)
                t0 = time.time()
                text = dr._ask(rl.PORT, name, q.prompt)
                dt = time.time() - t0
                spent += dt
                row = {
                    "moment_id": c.moment_id,
                    "kind": k,
                    "family": c.family,
                    "options": list(q.options),
                    "gold": q.gold,
                    "response": text,
                    "answer": dr.parse_answer(text, q.options),
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
        chain = build_items()
        print(f"## baselines\n{baselines_table(chain)}\n")
        if models_run():
            print(f"## summary\n{summary_table(chain)}\n\n## families\n{family_table(chain)}\n")
            print(findings(chain))
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
