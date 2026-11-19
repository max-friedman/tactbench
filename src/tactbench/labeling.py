"""Collecting human labels and measuring agreement. Round 31.

Every gold label in ``data/`` is constructed (``raters: 0``). CLAUDE.md's second
priority is measuring how far construction drifts from what people want, which needs
human judgments on a subset and a reported agreement statistic. This module is the
machinery; no human labels have been collected with it yet.

A rater sees exactly what an LLM sees -- :func:`policies.llm.render_moment` of
:func:`schema.policy_view` -- so a human and a model judge the same evidence, and
nothing that encodes the answer (ids, slices, family) is shown. Samples are whole
pairs, so a human pairs-both-right figure is comparable to the models', but the two
sides are never shown together: each rater gets their own order.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .policies.llm import render_moment
from .schema import Item, pair_key, policy_view

LABELS_DIR = Path("labels")


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
    return LABELS_DIR / f"{version}-{split}" / f"{rater}.jsonl"


def load_labels(version: str = "v1", split: str = "dev") -> dict[str, dict[str, bool]]:
    """``{rater: {moment_id: surface}}``. A later answer for the same moment wins."""
    out: dict[str, dict[str, bool]] = {}
    root = LABELS_DIR / f"{version}-{split}"
    for path in sorted(root.glob("*.jsonl")) if root.exists() else []:
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                out.setdefault(row["rater"], {})[row["moment_id"]] = row["surface"]
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
    items: int
    raters: int
    kappa: float | None
    majority_matches_construction: float | None
    majority_pairs_both_right: float | None
    per_rater: dict[str, float] = field(default_factory=dict)


def agreement(items: list[Item], labels: dict[str, dict[str, bool]]) -> AgreementReport:
    """Agreement among raters, and between their majority and the constructed label.

    Kappa uses only moments every rater answered, so the table is rectangular. Ties
    in the majority (an even split) count as not matching construction.
    """
    gold = {i.moment.id: i.label.should_surface for i in items}
    raters = sorted(labels)
    common = [m for m in gold if raters and all(m in labels[r] for r in raters)]
    table = [
        [sum(not labels[r][m] for r in raters), sum(labels[r][m] for r in raters)] for m in common
    ]
    kappa = fleiss_kappa(table) if len(raters) >= 2 and common else None

    majority: dict[str, bool | None] = {}
    for m in common:
        votes = Counter(labels[r][m] for r in raters)
        majority[m] = None if votes[True] == votes[False] else votes[True] > votes[False]
    matches = sum(majority[m] == gold[m] for m in common) / len(common) if common else None

    pairs: dict[str, list[str]] = defaultdict(list)
    for m in common:
        pairs[pair_key(m)].append(m)
    whole = [ms for ms in pairs.values() if len(ms) == 2]
    both = (
        sum(all(majority[m] == gold[m] for m in ms) for ms in whole) / len(whole) if whole else None
    )

    per_rater = {
        r: sum(labels[r][m] == gold[m] for m in labels[r] if m in gold)
        / max(1, sum(m in gold for m in labels[r]))
        for r in raters
    }
    return AgreementReport(len(common), len(raters), kappa, matches, both, per_rater)
