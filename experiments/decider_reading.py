"""Decider reading: can a model say which entity the decider puts in which role? Round 82.

No LLM run on any split tells the two sides of a pair apart (best pairs-both-right
14.8%; a coin gets about 25%). That has two readings, never separated until now:

    (a) the model cannot READ the decider -- it does not know which entity holds
        which role;
    (b) it reads the decider but does not USE it in the decision to interrupt.

This asks each model a direct factual question about the decider alone -- "which
restaurant's booking is confirmed: Marzano or Corvino?" -- after the moment's full
rendered context (the same ``render_moment`` every policy sees), with no interruption
decision involved. One side of each v9 dev pair (320 questions, 16 families x 20),
two options, counterbalanced. Pre-registration and results: docs/DECIDER_READING.md.

    uv run python experiments/decider_reading.py --models-dir DIR --server-python PY \\
        [--only NAME ...]          # run (one llama.cpp server per model; resumes)
    uv run python experiments/decider_reading.py --tables   # print the doc/README tables

Each call is appended to ``results/decider-reading/<model>.jsonl`` as it returns, so a
killed run resumes where it stopped. ``tests/test_decider_reading.py`` holds the
question set, the prompt and every published figure.
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
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from tactbench.dataset.generate import ALL_FRAMES
from tactbench.dataset.loader import load
from tactbench.policies.llm import render_moment
from tactbench.results import scorecards
from tactbench.schema import Item, frame_of, pair_key

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "decider-reading"
MANIFEST = OUT / "MANIFEST.json"
VERSION, SPLIT = "v9", "dev"

#: Prompt changes are result changes.
PROMPT_VERSION = "2026-11-22.1"
TEMPERATURE = 0
MAX_TOKENS = 16
N_CTX = 2048

#: Leads the single user turn; the rendered moment and the question follow, each after
#: a blank line. No system turn, so no chat template can drop the instructions (R50).
PROMPT_PREAMBLE = (
    "Below is a single moment from a user's day: what the user is doing right now, and "
    'some context signals. In the signals, "you" and "your" refer to the user. Read it, '
    "then answer the question after it."
)

_ASK = "According to the last signal, "
_END = " Answer with one of the two, exactly as written, and nothing else."

#: One question per family. ``{a}`` and ``{b}`` are the two options, in the
#: counterbalanced order. Each asks which entity holds one role the decider assigns.
QUESTIONS: dict[str, str] = {
    "childcare": _ASK + "who is responsible for getting the children from school: {a} or {b}?",
    "commerce": _ASK + "which item has never been taken out of its packaging: {a} or {b}?",
    "deadline": _ASK + "who is the main person on call: {a} or {b}?",
    "dinner_booking": _ASK + "which restaurant's booking is confirmed: {a} or {b}?",
    "driving": _ASK + "which road has bad traffic: {a} or {b}?",
    "finance": _ASK + "which account does not have enough money for the payment: {a} or {b}?",
    "health": _ASK + "which prescription has not yet been collected: {a} or {b}?",
    "home_security": _ASK
    + "which part of the home is the worker expected to come into: {a} or {b}?",
    "meeting_prep": _ASK + "which meeting has not started yet: {a} or {b}?",
    "pet_care": _ASK + "which pet has a health problem: {a} or {b}?",
    "photo_backup": _ASK + "which album has a copy saved somewhere besides the cloud: {a} or {b}?",
    "quiet_hours": _ASK + "who can get to the hospital quickly tonight: {a} or {b}?",
    "river_swim": _ASK + "which place is further upstream: {a} or {b}?",
    "street_cleaning": _ASK + "on which street is the car parked at the moment: {a} or {b}?",
    "travel": _ASK + "at which gate is the passenger really present right now: {a} or {b}?",
    "water_notice": _ASK + "in which district does the user live now: {a} or {b}?",
}
QUESTIONS = {fam: q + _END for fam, q in QUESTIONS.items()}

#: Which of the decider's two roles each question asks about. ``privileged`` is the
#: role whose occupant decides the label (``generate.Scenario.frames``); three
#: questions ask the other role, because it is the plainer one to word.
ASKED_ROLE: dict[str, str] = {fam: "privileged" for fam in QUESTIONS} | {
    "dinner_booking": "other",
    "home_security": "other",
    "photo_backup": "other",
}

#: Largest first: the run order, and the order of every table.
ORDER = [
    "llama-3.1-8b",
    "qwen2.5-7b",
    "mistral-7b",
    "gemma-3-4b",
    "phi-3.5-mini",
    "phi-4-mini",
    "qwen2.5-3b",
    "llama-3.2-3b",
    "gemma-2-2b",
    "granite-3.3-2b",
    "smollm2-1.7b",
    "qwen2.5-1.5b",
    "llama-3.2-1b",
    "qwen2.5-0.5b",
]


@dataclass(frozen=True)
class Question:
    qid: str
    moment_id: str
    family: str
    frame: int
    decider: str
    options: tuple[str, str]
    gold: str
    marker: str  # the family's marker filler (``you``, ``checking``) on this side
    privileged_first: bool  # the privileged clause comes first in the decider
    prompt: str


def _digest(tag: str, key: str) -> str:
    return hashlib.sha256(f"decider-reading:{tag}:{key}".encode()).hexdigest()


def roles(decider: str, family: str, frame: int) -> tuple[str, str]:
    """(filler of the privileged clause, filler of the other clause)."""
    return _parse_decider(decider, family, frame)[:2]


def _parse_decider(decider: str, family: str, frame: int) -> tuple[str, str, bool]:
    priv, other = ALL_FRAMES[family][frame]

    def rx(template: str, group: str) -> str:
        head, tail = template.split("{who}")
        return re.escape(head) + f"(?P<{group}>.+?)" + re.escape(tail) + r"\."

    for first in (True, False):
        a, b = (rx(priv, "p"), rx(other, "o")) if first else (rx(other, "o"), rx(priv, "p"))
        m = re.fullmatch(f"{a} {b}", decider)
        if m:
            return m["p"], m["o"], first
    raise ValueError(f"decider does not match {family} frame {frame}: {decider!r}")


def _alternate(keys: list[str], tag: str) -> dict[str, bool]:
    """True for every other key in digest order: an exact half, chosen by hashlib."""
    ranked = sorted(keys, key=lambda k: _digest(tag, k))
    return {k: i % 2 == 0 for i, k in enumerate(ranked)}


def build_questions(items: list[Item] | None = None) -> list[Question]:
    """One question per pair, from the committed v9 dev file.

    Within each family the pairs are stratified by clause order (privileged clause
    first or second); in each stratum, sides alternate positive/near-miss in digest
    order and so does option order, so label, "the first option" and "the entity
    named first" are each the answer to exactly half of a family's questions.
    """
    items = load(VERSION, SPLIT) if items is None else items
    by_pair: dict[str, dict[str, Item]] = defaultdict(dict)
    for it in items:
        side = "pos" if "-pos-" in it.moment.id else "near"
        by_pair[pair_key(it.moment.id)][side] = it

    strata: dict[tuple[str, bool], list[str]] = defaultdict(list)
    for key, sides in by_pair.items():
        m = sides["pos"].moment
        _, _, first = _parse_decider(m.signals[-1].content, m.family, frame_of(m))
        strata[(m.family, first)].append(key)

    out = []
    for (family, _), keys in sorted(strata.items()):
        take_pos = _alternate(keys, "side")
        gold_first = _alternate(keys, "options")
        for key in sorted(keys):
            item = by_pair[key]["pos" if take_pos[key] else "near"]
            m = item.moment
            frame = frame_of(m)
            decider = m.signals[-1].content
            priv, other, first = _parse_decider(decider, family, frame)
            gold = priv if ASKED_ROLE[family] == "privileged" else other
            wrong = other if gold == priv else priv
            options = (gold, wrong) if gold_first[key] else (wrong, gold)
            question = QUESTIONS[family].format(a=options[0], b=options[1])
            out.append(
                Question(
                    qid=key,
                    moment_id=m.id,
                    family=family,
                    frame=frame,
                    decider=decider,
                    options=options,
                    gold=gold,
                    marker=priv if take_pos[key] else other,
                    privileged_first=first,
                    prompt=f"{PROMPT_PREAMBLE}\n\n{render_moment(m)}\n\n{question}",
                )
            )
    return sorted(out, key=lambda q: q.qid)


# --------------------------------------------------------------------------- #
# Parsing and baselines
# --------------------------------------------------------------------------- #


def _key(option: str) -> str:
    """The word that names an option: ``the desk`` -> desk, ``Sam's prescription`` -> Sam."""
    words = option.split()
    if words[0].lower() == "the" and len(words) > 1:
        words = words[1:]
    return words[0].removesuffix("'s")


def parse_answer(text: str, options: tuple[str, str]) -> str | None:
    """The option the answer names, or None when it names neither or both."""
    named = [
        opt
        for opt in options
        if re.search(rf"(?<![\w-]){re.escape(_key(opt))}s?(?![\w-])", text or "", re.IGNORECASE)
    ]
    return named[0] if len(named) == 1 else None


def positional_answer(q: Question) -> str:
    """The entity named first in the decider."""
    priv, other = roles(q.decider, q.family, q.frame)
    return priv if q.privileged_first else other


_STOP = frozenset(
    "the a an of to in on at for is was are and or by with from which who what "
    "according last signal answer one two exactly as written nothing else".split()
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP and len(w) > 2}


def lexical_answer(q: Question) -> str:
    """The entity whose clause shares more words with the question (ties: first option)."""
    asked = _words(QUESTIONS[q.family].format(a="", b=""))
    priv_t, other_t = ALL_FRAMES[q.family][q.frame]
    priv, other = roles(q.decider, q.family, q.frame)
    sp, so = len(asked & _words(priv_t)), len(asked & _words(other_t))
    if sp == so:
        return q.options[0]
    return priv if sp > so else other


BASELINES = {
    "always first option": lambda q: q.options[0],
    "first-named in decider": positional_answer,
    "always the marker": lambda q: q.marker,
    "word overlap with question": lexical_answer,
}


def baselines(questions: list[Question]) -> dict[str, float]:
    return {
        name: sum(f(q) == q.gold for q in questions) / len(questions)
        for name, f in BASELINES.items()
    }


def baselines_table(questions: list[Question]) -> str:
    fams = sorted(QUESTIONS)
    lines = ["| baseline | overall | lowest family | highest family |", "|---|---|---|---|"]
    for name, f in BASELINES.items():
        per = [
            sum(f(q) == q.gold for q in questions if q.family == fam)
            / sum(q.family == fam for q in questions)
            for fam in fams
        ]
        overall = sum(f(q) == q.gold for q in questions) / len(questions)
        lines.append(f"| {name} | {overall:.1%} | {min(per):.0%} | {max(per):.0%} |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Statistics (pre-registered in docs/DECIDER_READING.md)
# --------------------------------------------------------------------------- #

ALPHA = 0.05


def binom_sf(k: int, n: int) -> float:
    """P(X >= k), X ~ Binomial(n, 1/2): the exact one-sided p of k right out of n."""
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2**n


def holm(ps: list[float], alpha: float = ALPHA) -> list[bool]:
    """Holm step-down: which hypotheses are rejected, in the input order."""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    out = [False] * len(ps)
    for rank, i in enumerate(order):
        if ps[i] > alpha / (len(ps) - rank):
            break
        out[i] = True
    return out


#: Pre-registered thresholds. (b) needs most families read (more than half of 16);
#: (a) needs at most a few (three or fewer); a coin's pairs-both-right is about 25%.
MOST, FEW, COIN_PAIRS = 9, 3, 0.25


def verdict(families_read: int, best_pairs: float) -> str:
    if families_read >= MOST and best_pairs <= COIN_PAIRS:
        return "(b)"
    if families_read <= FEW:
        return "(a)"
    return "neither"


def result_path(name: str) -> Path:
    return OUT / f"{name}.jsonl"


def load_rows(name: str) -> list[dict]:
    return [json.loads(line) for line in result_path(name).read_text().splitlines() if line]


def models_run() -> list[str]:
    return [m for m in ORDER if result_path(m).exists()]


@dataclass
class Summary:
    model: str
    n: int
    correct: int
    unparsed: int
    p: float
    per_family: dict[str, int]
    read: dict[str, bool]
    best_pairs: float

    @property
    def families_read(self) -> int:
        return sum(self.read.values())

    @property
    def verdict(self) -> str:
        return verdict(self.families_read, self.best_pairs)


def _best_pairs() -> dict[str, float]:
    best: dict[str, float] = {}
    for card, _, pairs in scorecards(VERSION, SPLIT):
        model = card.policy.split(":", 2)[2]
        best[model] = max(best.get(model, 0.0), pairs)
    return best


_PAIRS_CACHE: dict[str, float] = {}


def summarize(name: str, questions: list[Question]) -> Summary:
    if not _PAIRS_CACHE:
        _PAIRS_CACHE.update(_best_pairs())
    gold = {q.qid: q for q in questions}
    rows = load_rows(name)
    fams = sorted(QUESTIONS)
    per = {fam: 0 for fam in fams}
    size = {fam: sum(q.family == fam for q in questions) for fam in fams}
    for r in rows:
        q = gold[r["qid"]]
        per[q.family] += r["answer"] == q.gold
    read = dict(zip(fams, holm([binom_sf(per[f], size[f]) for f in fams]), strict=True))
    correct = sum(per.values())
    return Summary(
        model=name,
        n=len(rows),
        correct=correct,
        unparsed=sum(r["answer"] is None for r in rows),
        p=binom_sf(correct, len(rows)),
        per_family=per,
        read=read,
        best_pairs=_PAIRS_CACHE[name],
    )


def _p(p: float) -> str:
    return "<0.0001" if p < 1e-4 else f"{p:.4f}"


def summary_table(questions: list[Question]) -> str:
    lines = [
        "| model | right | accuracy | p (one-sided) | unparsed | families read "
        "| best pairs-both-right on v9 | pre-registered verdict (underpowered) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in models_run():
        s = summarize(name, questions)
        lines.append(
            f"| `{name}` | {s.correct}/{s.n} | {s.correct / s.n:.1%} | {_p(s.p)} "
            f"| {s.unparsed} | {s.families_read} of 16 | {s.best_pairs:.1%} | {s.verdict} |"
        )
    return "\n".join(lines)


#: Column heads for the per-family table.
SHORT = {
    "childcare": "child",
    "commerce": "comm",
    "deadline": "dead",
    "dinner_booking": "dine",
    "driving": "drive",
    "finance": "fin",
    "health": "hlth",
    "home_security": "home",
    "meeting_prep": "meet",
    "pet_care": "pet",
    "photo_backup": "photo",
    "quiet_hours": "quiet",
    "river_swim": "river",
    "street_cleaning": "street",
    "travel": "trav",
    "water_notice": "water",
}


def binom_sf_at(k: int, n: int, p: float) -> float:
    """P(X >= k), X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


VARIANTS = ("naive", "rubric")


@dataclass
class Contrast:
    """On the moment a model was asked about: was its interrupt decision right more
    often when its reading was right? One committed v9 run (one prompt variant)."""

    model: str
    variant: str
    spoke: int  # of the 320 asked moments, how many the run spoke on
    read_right: int
    decision_right_when_read_right: int
    read_wrong: int
    decision_right_when_read_wrong: int

    @property
    def when_right(self) -> float:
        return self.decision_right_when_read_right / self.read_right

    @property
    def when_wrong(self) -> float:
        return self.decision_right_when_read_wrong / self.read_wrong


def contrast(name: str, variant: str, questions: list[Question]) -> Contrast:
    by_id = {q.moment_id: q for q in questions}
    labels = {i.moment.id: i.label.should_surface for i in load(VERSION, SPLIT)}
    path = ROOT / "results" / f"{VERSION}-{SPLIT}" / f"llm_{variant}_{name}-{SPLIT}.jsonl"
    surface = {}
    for line in path.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            surface[d["moment_id"]] = bool(d["surface"])
    counts = {True: [0, 0], False: [0, 0]}
    for r in load_rows(name):
        q = by_id[r["moment_id"]]
        ok = r["answer"] == q.gold
        counts[ok][0] += 1
        counts[ok][1] += surface[q.moment_id] == labels[q.moment_id]
    return Contrast(
        model=name,
        variant=variant,
        spoke=sum(surface[q.moment_id] for q in questions),
        read_right=counts[True][0],
        decision_right_when_read_right=counts[True][1],
        read_wrong=counts[False][0],
        decision_right_when_read_wrong=counts[False][1],
    )


def contrasts(questions: list[Question]) -> list[Contrast]:
    return [contrast(m, v, questions) for m in models_run() for v in VARIANTS]


def contrast_table(questions: list[Question]) -> str:
    lines = [
        "| model | prompt | spoke on | reading right: decision right "
        "| reading wrong: decision right |",
        "|---|---|---|---|---|",
    ]
    for c in contrasts(questions):
        lines.append(
            f"| `{c.model}` | {c.variant} | {c.spoke}/320 "
            f"| {c.decision_right_when_read_right}/{c.read_right} ({c.when_right:.0%}) "
            f"| {c.decision_right_when_read_wrong}/{c.read_wrong} ({c.when_wrong:.0%}) |"
        )
    return "\n".join(lines)


def findings(questions: list[Question]) -> str:
    """The published headline, generated so that every figure in it is recomputed."""
    ss = [summarize(name, questions) for name in models_run()]
    above = [s for s in ss if s.p < ALPHA]
    rest = [s for s in ss if s.p >= ALPHA]
    acc = sorted(s.correct / s.n for s in above)
    top = max(ss, key=lambda s: (s.families_read, s.correct))
    votes = {v: sum(s.verdict == v for s in ss) for v in ("(a)", "(b)", "neither")}
    power = binom_sf_at(17, 20, 0.75)
    rest_acc = sorted(s.correct / s.n for s in rest)
    cs = contrasts(questions)
    right = sorted(c.when_right for c in cs)
    wrong = sorted(c.when_wrong for c in cs)
    better = sum(c.when_right > c.when_wrong for c in cs)
    return (
        f"**{len(above)} of {len(ss)}** models answer above chance overall (exact one-sided "
        f"binomial p < 0.05), at **{acc[0]:.1%} to {acc[-1]:.1%}**; the other {len(rest)} "
        f"sit at {rest_acc[0]:.1%} to {rest_acc[-1]:.1%}. No model reads the {MOST} or more "
        f"families (b) needed: the most is **{top.families_read} of 16** (`{top.model}`). "
        f"By the pre-registered rule, **{votes['(a)']}** models support (a), "
        f"**{votes['neither']}** support neither, and **{votes['(b)']}** support (b).\n\n"
        f"That rule is underpowered. At 20 questions per family a true 75% reaches the "
        f"first Holm step (17 of 20) only {power:.1%} of the time, so the (a) labels are not "
        f"evidence that a model cannot read. *Exploratory, not pre-registered:* on the "
        f"moment each model was asked about, its interrupt decision in the committed v9 runs "
        f"(both prompts, {len(cs)} runs) was right {right[0]:.0%} to {right[-1]:.0%} of the "
        f"time when its reading was right and {wrong[0]:.0%} to {wrong[-1]:.0%} when it was "
        f"wrong; it was higher with a right reading in {better} of {len(cs)} runs. Getting "
        f"the role right did not make the decision more often right. Whether a model can "
        f"join the role to the body (which restaurant is tonight's) was not tested, so "
        f'"reads but cannot join" and "reads but ignores" are not separated.'
    )


def family_table(questions: list[Question]) -> str:
    fams = sorted(QUESTIONS)
    lines = [
        "| model | " + " | ".join(SHORT[f] for f in fams) + " | read |",
        "|---|" + "---|" * (len(fams) + 1),
    ]
    for name in models_run():
        s = summarize(name, questions)
        cells = [f"**{s.per_family[f]}**" if s.read[f] else str(s.per_family[f]) for f in fams]
        lines.append(f"| `{name}` | " + " | ".join(cells) + f" | {s.families_read} |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


def _ask(port: int, name: str, prompt: str) -> str:
    body = {
        "model": name,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310
        return json.loads(resp.read())["choices"][0]["message"]["content"] or ""


def run_model(name: str, path: Path, server_python: str, threads: int) -> float:
    """Ask every question not already answered; return the seconds spent on calls."""
    import run_local_llms as rl  # the llama.cpp server conventions, reused

    questions = build_questions()
    done = {r["qid"] for r in load_rows(name)} if result_path(name).exists() else set()
    todo = [q for q in questions if q.qid not in done]
    if not todo:
        return 0.0
    OUT.mkdir(parents=True, exist_ok=True)
    # results/.server-*.log is git-ignored; a log inside OUT would not be.
    log = open(OUT.parent / f".server-{name}.log", "w")  # noqa: SIM115
    proc = subprocess.Popen(
        [server_python, "-m", "llama_cpp.server", "--model", str(path),
         "--model_alias", name, "--host", "127.0.0.1", "--port", str(rl.PORT),
         "--n_ctx", str(N_CTX), "--n_threads", str(threads), "--seed", "0"],
        stdout=log, stderr=subprocess.STDOUT,
    )  # fmt: skip
    spent = 0.0
    try:
        rl.wait_ready(proc)
        with result_path(name).open("a") as f:
            for i, q in enumerate(todo):
                t0 = time.time()
                text = _ask(rl.PORT, name, q.prompt)
                dt = time.time() - t0
                spent += dt
                row = {
                    "qid": q.qid,
                    "moment_id": q.moment_id,
                    "family": q.family,
                    "options": list(q.options),
                    "gold": q.gold,
                    "response": text,
                    "answer": parse_answer(text, q.options),
                    "prompt_version": PROMPT_VERSION,
                    "seconds": round(dt, 2),
                }
                f.write(json.dumps(row) + "\n")
                f.flush()
                if i % 20 == 0:
                    print(f"{name}: {len(done) + i + 1}/{len(questions)} {dt:.1f}s", flush=True)
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
    ap.add_argument("--tables", action="store_true", help="print the published tables")
    args = ap.parse_args()

    if args.tables:
        qs = build_questions()
        for title, table in (
            ("baselines", baselines_table(qs)),
            ("summary (README)", summary_table(qs)),
            ("per family (docs)", family_table(qs)),
        ):
            print(f"## {title}\n{table}\n")
        return
    if not (args.models_dir and args.server_python):
        ap.error("--models-dir and --server-python are required to run")

    sys.path.insert(0, str(ROOT / "experiments"))
    import run_local_llms as rl

    runtime = subprocess.run(
        [args.server_python, "-c", "import llama_cpp; print(llama_cpp.__version__)"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    for name in ORDER:
        if args.only and name not in args.only:
            continue
        repo, fname = rl.MODELS[name]
        path = args.models_dir / fname
        if not path.exists():
            print(f"skip {name}: {path} not present", file=sys.stderr)
            continue
        spent = run_model(name, path, args.server_python, args.threads)
        manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
        entry = manifest.get(name, {})
        entry.update(
            {
                "hf_repo": repo,
                "file": fname,
                "sha256": rl.sha256(path),
                "runtime": f"llama-cpp-python {runtime}",
                "n_ctx": N_CTX,
                "temperature": TEMPERATURE,
                "max_tokens": MAX_TOKENS,
                "threads": args.threads,
                "prompt_version": PROMPT_VERSION,
                "call_seconds": round(
                    sum(r["seconds"] for r in load_rows(name)) if result_path(name).exists() else 0,
                    1,
                ),
            }
        )
        manifest[name] = entry
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"{name}: done, {spent:.0f}s of calls this run", flush=True)


if __name__ == "__main__":
    main()
