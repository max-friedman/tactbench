"""§A audit (Round 49): does a character n-gram model beat chance on held-out frames?

Every surface probe the benchmark gates on reads whole words: unigrams, bigrams,
position-tagged words, a dict lookup, clause features. None sees text below the word,
and Round 47's leak was exactly there -- an *-er* suffix rule read 90% before it was
fixed. This probe is a character n-gram (3-8) averaged perceptron.

**Independent of the code under test.** It imports nothing from ``tactbench``: it reads
the committed JSONL directly and builds features from signal ``content`` strings
only. Ids are used to group pairs and labels to fit and score; neither is a feature.

Fit on ``dev``, scored on ``test``, whose decider frames (5-7) appear nowhere in dev.

    python experiments/char_ngram_audit.py            # v2, v3, v4
    python experiments/char_ngram_audit.py v4 --json  # machine-readable
    python experiments/char_ngram_audit.py v4 --verdict  # what the gate runs
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: Round 49 pre-registration: the claim fails at or above either on held-out test.
MAX_ACCURACY = 0.60
MAX_PAIRS_BOTH_RIGHT = 0.375
#: The probe must stay able to find a leak, or a clean reading is vacuous.
MIN_DEV_FIT = 0.85
MIN_CONTROL_PAIRS = 0.90
#: Added after the R49 review, not pre-registered: the pairwise probe answers the
#: two sides oppositely, so pairs-both-right is ~50% for it at chance and the 37.5%
#: falsifier cannot judge it. Its side-choice accuracy can; chance is 50%.
MAX_PAIR_CHOICE = 0.65
NGRAMS = (3, 4, 5, 6, 7, 8)
EPOCHS = 30


def read(version: str, split: str) -> list[dict]:
    path = ROOT / "data" / version / f"{split}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def pair_of(moment_id: str) -> str:
    """Group the two sides of a pair; never used as a feature."""
    return re.sub(r"-(pos|near)-", "-", moment_id)


def features(row: dict, words: bool = False) -> Counter[str]:
    """Character n-grams of each signal's text, signal index kept, nothing else.

    ``words=True`` gives word unigrams instead -- used only to show the planted
    control is invisible at the word level, so catching it shows sub-word power.
    """
    grams: Counter[str] = Counter()
    for k, signal in enumerate(row["moment"]["signals"]):
        text = " " + signal["content"].lower() + " "
        units = (
            [(1, t) for t in re.findall(r"\w+", text)]
            if words
            else [(n, text[i : i + n]) for n in NGRAMS for i in range(len(text) - n + 1)]
        )
        for n, unit in units:
            grams[f"{n}:{unit}"] += 1
            grams[f"s{k}:{n}:{unit}"] += 1
    return grams


def normalise(grams: Counter[str]) -> dict[str, float]:
    norm = math.sqrt(sum(v * v for v in grams.values())) or 1.0
    return {g: v / norm for g, v in grams.items()}


def perceptron(data: list[tuple[dict[str, float], float]], seed: int) -> dict[str, float]:
    """Averaged perceptron: fits any separable training set, so underfitting cannot
    pass for resistance. Plain SGD logistic regression reached 50-70% on dev here."""
    w: dict[str, float] = defaultdict(float)
    total: dict[str, float] = defaultdict(float)
    stamp: dict[str, int] = defaultdict(int)
    step = 0
    rng = random.Random(seed)
    for _ in range(EPOCHS):
        rng.shuffle(data)
        for x, y in data:
            step += 1
            z = w["__bias__"] + sum(w[g] * v for g, v in x.items())
            if y * z <= 0:
                for g, v in [*x.items(), ("__bias__", 1.0)]:
                    total[g] += (step - stamp[g]) * w[g]
                    stamp[g] = step
                    w[g] += y * v
    for g in w:
        total[g] += (step - stamp[g]) * w[g]
    return {g: total[g] / step for g in w}


def fit(rows: list[dict], seed: int = 0, words: bool = False) -> dict[str, float]:
    label = {True: 1.0, False: -1.0}
    data = [(normalise(features(r, words)), label[r["label"]["should_surface"]]) for r in rows]
    return perceptron(data, seed)


def predict(w: dict[str, float], row: dict, words: bool = False) -> bool:
    x = normalise(features(row, words))
    return w.get("__bias__", 0.0) + sum(w.get(g, 0.0) * v for g, v in x.items()) > 0


def score(rows: list[dict], preds: dict[str, bool]) -> dict:
    right = [preds[r["moment"]["id"]] == r["label"]["should_surface"] for r in rows]
    pairs: dict[str, list[bool]] = defaultdict(list)
    fam: dict[str, list[bool]] = defaultdict(list)
    for r, ok in zip(rows, right, strict=True):
        pairs[pair_of(r["moment"]["id"])].append(ok)
        fam[r["moment"]["family"]].append(ok)
    both = [all(v) for v in pairs.values() if len(v) == 2]
    # Among pairs whose two sides got different answers, the share that picked the
    # right side. Chance is 50% for any probe; pairs-both-right's 25% "coin" holds
    # only for one that ignores pairing (R49 review).
    answers: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        answers[pair_of(r["moment"]["id"])].append(preds[r["moment"]["id"]])
    split = [k for k, v in answers.items() if len(v) == 2 and v[0] != v[1]]
    chose = sum(all(pairs[k]) for k in split)
    return {
        "n": len(rows),
        "accuracy": sum(right) / len(right),
        "pairs": len(both),
        "pairs_both_right": sum(both) / len(both),
        "split_pairs": len(split),
        "pair_choice": chose / len(split) if split else 0.5,
        "spoke": sum(preds.values()),
        "family_accuracy": {f: sum(v) / len(v) for f, v in sorted(fam.items())},
    }


def plant(rows: list[dict]) -> list[dict]:
    """Positive control: a sub-word cue that transfers through held-out frames.

    Every stay-quiet moment's last signal gets ``ish`` glued to its middle word of
    three or more letters. The word changes with the frame and the entity, so a
    word-unigram model reads it at chance (gated); a character model sees ``ish ``
    on every one. The R49 review found the first version (``ish`` on the final word,
    often a recurring entity) was caught by word unigrams too, so it showed nothing
    below the word.
    """
    out = []
    for r in rows:
        r = json.loads(json.dumps(r))
        if not r["label"]["should_surface"]:
            sig = r["moment"]["signals"][-1]
            spots = list(re.finditer(r"\b[A-Za-z]{3,}\b", sig["content"]))
            m = spots[len(spots) // 2]
            sig["content"] = sig["content"][: m.end()] + "ish" + sig["content"][m.end() :]
        out.append(r)
    return out


def audit(version: str, control: bool = False, words: bool = False, seed: int = 0) -> dict:
    dev, test = read(version, "dev"), read(version, "test")
    if control:
        dev, test = plant(dev), plant(test)
    w = fit(dev, seed, words)
    return {
        "version": version + (" +planted" if control else "") + (" words" if words else ""),
        "dev": score(dev, {r["moment"]["id"]: predict(w, r, words) for r in dev}),
        "test": score(test, {r["moment"]["id"]: predict(w, r, words) for r in test}),
    }


def _last_signal_grams(row: dict) -> Counter[str]:
    text = " " + row["moment"]["signals"][-1]["content"].lower() + " "
    return Counter(text[i : i + n] for n in NGRAMS for i in range(len(text) - n + 1))


def _pairs(rows: list[dict]) -> list[tuple[dict, dict]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[pair_of(r["moment"]["id"])].append(r)
    return [(v[0], v[1]) for v in by.values() if len(v) == 2]


def _difference(a: dict, b: dict) -> dict[str, float]:
    x: dict[str, float] = defaultdict(float)
    for g, v in _last_signal_grams(a).items():
        x[g] += v
    for g, v in _last_signal_grams(b).items():
        x[g] -= v
    return {g: v for g, v in x.items() if v}


def audit_pairwise(version: str, seed: int = 0) -> dict:
    """The strongest char probe the R49 review found: pair-aware.

    Trained on within-pair differences of the decider's n-grams, so the shared body
    cancels; it then says which side of a test pair should speak. It answers the
    two sides oppositely, so its pairs-both-right sits near 50% *at chance* --
    judge it by ``pair_choice``. It uses the pairing, which a deployed assistant
    never sees, so it bounds a submitter who exploits the matched design.
    """
    dev, test = read(version, "dev"), read(version, "test")
    label = {True: 1.0, False: -1.0}
    data = [(_difference(a, b), label[a["label"]["should_surface"]]) for a, b in _pairs(dev)]
    w = perceptron(data, seed)
    w.pop("__bias__", None)
    preds = {}
    for a, b in _pairs(test):
        z = sum(w.get(g, 0.0) * v for g, v in _difference(a, b).items())
        preds[a["moment"]["id"]], preds[b["moment"]["id"]] = z > 0, z < 0
    return {"version": version + " pairwise", "test": score(test, preds), "predictions": preds}


def main(argv: list[str]) -> None:
    versions = [a for a in argv if not a.startswith("--")] or ["v2", "v3", "v4", "v5", "v6"]
    results = [audit(v) for v in versions]
    if "--control" in argv:
        results += [audit(v, control=True) for v in versions]
    if "--verdict" in argv:
        for v in versions:
            real, planted = audit(v), audit(v, control=True)
            word_control = audit(v, control=True, words=True)
            pair = audit_pairwise(v)["test"]
            t = real["test"]
            print(
                f"{v}: dev fit {real['dev']['accuracy']:.1%}, test accuracy"
                f" {t['accuracy']:.1%}, pairs-both-right {t['pairs_both_right']:.1%},"
                f" pair choice {t['pair_choice']:.1%} of {t['split_pairs']};"
                f" planted control {planted['test']['pairs_both_right']:.1%},"
                f" word unigrams on it {word_control['test']['accuracy']:.1%};"
                f" pairwise probe pairs-both-right {pair['pairs_both_right']:.1%},"
                f" pair choice {pair['pair_choice']:.1%} of {pair['split_pairs']}"
            )
            if real["dev"]["accuracy"] < MIN_DEV_FIT:
                print("verdict: unmeasurable as stated (probe does not fit dev)")
                return
            if planted["test"]["pairs_both_right"] < MIN_CONTROL_PAIRS:
                print("verdict: unmeasurable as stated (probe misses the planted leak)")
                return
            if word_control["test"]["accuracy"] >= MAX_ACCURACY:
                print("verdict: unmeasurable as stated (control is visible to word unigrams)")
                return
            if t["accuracy"] >= MAX_ACCURACY or t["pairs_both_right"] >= MAX_PAIRS_BOTH_RIGHT:
                print("verdict: fails")
                return
            if pair["pair_choice"] >= MAX_PAIR_CHOICE:
                print("verdict: fails (pairwise probe picks the right side)")
                return
        print("verdict: holds")
        return
    if "--json" in argv:
        print(json.dumps(results))
        return
    for r in results:
        t, d = r["test"], r["dev"]
        print(
            f"{r['version']}: dev acc {d['accuracy']:.1%} | test acc {t['accuracy']:.1%}"
            f"  pairs-both-right {t['pairs_both_right']:.1%} of {t['pairs']}"
            f"  spoke {t['spoke']}/{t['n']}"
        )
        for f, a in t["family_accuracy"].items():
            print(f"    {f:14s} {a:.1%}")


if __name__ == "__main__":
    main(sys.argv[1:])
