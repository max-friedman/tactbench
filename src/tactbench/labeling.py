"""Collecting human labels and measuring agreement. Round 31.

Every gold label in ``data/`` is constructed (``raters: 0``). CLAUDE.md's second
priority is measuring how far construction drifts from what people want, which needs
human judgments on a subset and a reported agreement statistic. This module is the
machinery; no human labels have been collected with it yet.

A rater sees exactly what an LLM sees -- :func:`policies.llm.render_moment` of
:func:`schema.policy_view` -- so a human and a model judge the same evidence, and
nothing that encodes the answer (ids, slices, family) is shown -- and answers are
stored under the opaque id, so a rater's own file does not reveal it either. Samples
are whole pairs in a per-rater order, so the two sides are not shown back to back.

**Not directly comparable to the models.** A rater sees both sides of every pair in
one session -- the same text with one role swapped -- and can infer that exactly one
side of each pair is a "speak". A model judges each moment alone. Human
pairs-both-right is therefore an easier task than the LLM column measures; report it
beside that column, not as the same quantity.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .policies.llm import render_moment
from .schema import Item, opaque_id, pair_key, policy_view

LABELS_DIR = Path("labels")
RATER_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
#: Below this many moments answered by every rater, no kappa is reported -- one late
#: rater with two answers once shrank a report to two items and a kappa of -1.0.
MIN_ITEMS = 20


def sample_pairs(items: list[Item], n_pairs: int, salt: str = "labels-v1") -> list[Item]:
    """``n_pairs`` whole pairs, chosen by hashing the pair key -- stable across runs
    and machines (``hashlib``, never ``hash()``; CLAUDE.md rule 6)."""
    by_pair: dict[str, list[Item]] = defaultdict(list)
    for item in items:
        by_pair[pair_key(item.moment.id)].append(item)
    chosen = sorted(by_pair, key=lambda k: hashlib.sha256(f"{salt}:{k}".encode()).hexdigest())
    return [item for key in chosen[:n_pairs] for item in by_pair[key]]


def rater_order(rater: str, items: list[Item]) -> list[Item]:
    """A per-rater shuffle, so the two sides of a pair are not shown back to back."""
    return sorted(items, key=lambda i: hashlib.sha256(f"{rater}:{i.moment.id}".encode()).digest())


def rater_view(item: Item) -> str:
    return render_moment(policy_view(item.moment))


def labels_path(rater: str, version: str = "v1", split: str = "dev") -> Path:
    """Refuses names that are not plain identifiers: ``../x`` once wrote outside the
    labels directory, where ``load_labels`` never looked, so resume lost the answers."""
    if not RATER_NAME.match(rater):
        raise ValueError(f"rater name {rater!r} must match {RATER_NAME.pattern}")
    return LABELS_DIR / f"{version}-{split}" / f"{rater}.jsonl"


def load_labels(version: str = "v1", split: str = "dev") -> dict[str, dict[str, bool]]:
    """``{rater: {opaque item id: surface}}``. A later answer for the same item wins."""
    out: dict[str, dict[str, bool]] = {}
    root = LABELS_DIR / f"{version}-{split}"
    for path in sorted(root.glob("*.jsonl")) if root.exists() else []:
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                out.setdefault(row["rater"], {})[row["item"]] = row["surface"]
    return out


def fleiss_kappa(table: list[list[int]]) -> float | None:
    """Fleiss' kappa for ``table[subject][category]`` counts, equal raters per subject.

    ``None`` when chance agreement is 1 (every rating in one category), where kappa
    is undefined rather than zero.
    """
    n_raters = sum(table[0])
    if n_raters < 2 or any(sum(row) != n_raters for row in table):
        raise ValueError("every subject needs the same number (>= 2) of ratings")
    n = len(table)
    totals = [sum(row[j] for row in table) for j in range(len(table[0]))]
    p_j = [t / (n * n_raters) for t in totals]
    p_e = sum(p * p for p in p_j)
    if p_e == 1.0:
        return None
    p_i = [(sum(c * c for c in row) - n_raters) / (n_raters * (n_raters - 1)) for row in table]
    p_bar = sum(p_i) / n
    return (p_bar - p_e) / (1 - p_e)


@dataclass
class AgreementReport:
    #: Moments every rater answered -- the only ones kappa and the majority use.
    items: int
    #: Whole pairs among those moments.
    pairs: int
    raters: int
    #: In-split answers per rater, so what was dropped is visible.
    answers: dict[str, int]
    #: Moments with an even split; never scored as a match or a miss.
    ties: int
    #: Fewer than ``MIN_ITEMS`` common moments: kappa is withheld.
    too_few: bool
    kappa: float | None
    majority_matches_construction: float | None
    majority_pairs_both_right: float | None
    per_rater: dict[str, float | None] = field(default_factory=dict)


def agreement(items: list[Item], labels: dict[str, dict[str, bool]]) -> AgreementReport:
    """Agreement among raters, and between their majority and the constructed label.

    Labels are keyed by :func:`schema.opaque_id`. Kappa and the majority use only
    moments every rater answered, so the table is rectangular; the report says how
    many that is and how many answers each rater gave. A tie -- every disagreement,
    with two raters -- is counted separately rather than as a miss.
    """
    gold = {opaque_id(i.moment.id): i.label.should_surface for i in items}
    pair_of = {opaque_id(i.moment.id): pair_key(i.moment.id) for i in items}
    raters = sorted(labels)
    answers = {r: sum(m in gold for m in labels[r]) for r in raters}
    common = [m for m in gold if raters and all(m in labels[r] for r in raters)]
    too_few = len(common) < MIN_ITEMS
    table = [
        [sum(not labels[r][m] for r in raters), sum(labels[r][m] for r in raters)] for m in common
    ]
    kappa = fleiss_kappa(table) if len(raters) >= 2 and not too_few else None

    majority: dict[str, bool | None] = {}
    for m in common:
        votes = Counter(labels[r][m] for r in raters)
        majority[m] = None if votes[True] == votes[False] else votes[True] > votes[False]
    untied = [m for m in common if majority[m] is not None]
    matches = sum(majority[m] == gold[m] for m in untied) / len(untied) if untied else None

    by_pair: dict[str, list[str]] = defaultdict(list)
    for m in common:
        by_pair[pair_of[m]].append(m)
    whole = [ms for ms in by_pair.values() if len(ms) == 2]
    scored = [ms for ms in whole if all(majority[m] is not None for m in ms)]
    both = (
        sum(all(majority[m] == gold[m] for m in ms) for ms in scored) / len(scored)
        if scored
        else None
    )

    per_rater = {
        r: (sum(labels[r][m] == gold[m] for m in labels[r] if m in gold) / answers[r])
        if answers[r]
        else None
        for r in raters
    }
    return AgreementReport(
        items=len(common),
        pairs=len(whole),
        raters=len(raters),
        answers=answers,
        ties=len(common) - len(untied),
        too_few=too_few,
        kappa=kappa,
        majority_matches_construction=matches,
        majority_pairs_both_right=both,
        per_rater=per_rater,
    )
