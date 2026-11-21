"""Committed LLM results: decisions on disk, re-scored on demand.

A published LLM figure is only checkable if the decisions that produced it are
committed. They live in ``results/<version>-<split>/llm_<variant>_<model>-<split>.jsonl``
(the same file ``tactbench llm`` caches to ``runs/``), with what produced each
model -- weights hash, runtime, decoding settings -- in ``results/MANIFEST.json``.
Nothing here calls a model; scoring a committed file is free and deterministic,
which is what lets the README's LLM table be gated like the built-in one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .dataset.loader import load
from .metrics import Scorecard, score
from .policies.llm import unparsed_rate
from .runner import normalized, silence_ics
from .schema import Decision, Item, pair_key

ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "results"
MANIFEST = RESULTS_DIR / "MANIFEST.json"


def results_dir(version: str = "v1", split: str = "dev") -> Path:
    return RESULTS_DIR / f"{version}-{split}"


def policy_name(path: Path, split: str = "dev") -> str:
    """``llm_rubric_qwen2.5-3b-dev.jsonl`` -> ``llm:rubric:qwen2.5-3b``."""
    stem = path.name.removesuffix(f"-{split}.jsonl")
    _, variant, model = stem.split("_", 2)
    return f"llm:{variant}:{model}"


def load_decisions(path: Path) -> list[Decision]:
    return [
        Decision.model_validate(json.loads(line))
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def load_results(version: str = "v1", split: str = "dev") -> dict[str, list[Decision]]:
    d = results_dir(version, split)
    if not d.exists():
        return {}
    return {policy_name(p, split): load_decisions(p) for p in sorted(d.glob("llm_*.jsonl"))}


def pairs_both_right(items: list[Item], decisions: list[Decision]) -> float:
    """Share of matched pairs answered correctly on **both** sides.

    The two sides of a pair share a body and need opposite answers, so getting
    both right requires reading the one signal that differs. A constant policy --
    always speak, or never -- scores exactly 0.0 however good its ICS looks, and
    a fair coin scores about 0.25. Added in Round 23, when three of the first
    three open-weight models turned out to be constant policies, one of which
    tied silence's ICS by never speaking.
    """
    by_id = {d.moment_id: d.surface for d in decisions}
    pairs: dict[str, list[bool]] = {}
    for item in items:
        right = by_id.get(item.moment.id, False) == item.label.should_surface
        pairs.setdefault(pair_key(item.moment.id), []).append(right)
    whole = [v for v in pairs.values() if len(v) == 2]
    return sum(all(v) for v in whole) / len(whole) if whole else 0.0


def manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def scorecards(version: str = "v1", split: str = "dev") -> list[tuple[Scorecard, float, float]]:
    """(scorecard, unparsed rate, pairs both right) per committed run, best ICS first."""
    items = load(version, split)
    silence = silence_ics(items)
    out = [
        (
            score(items, ds, name, reference_ics=silence),
            unparsed_rate(ds),
            pairs_both_right(items, ds),
        )
        for name, ds in load_results(version, split).items()
    ]
    return sorted(out, key=lambda cu: (cu[0].ics, cu[0].policy))


def _f(x: float | None) -> str:
    return "—" if x is None else f"{x:.3f}"


def _signed(x: float) -> str:
    return f"{x:+.1f}".replace("-", "−")


def markdown_row(card: Scorecard, unparsed: float, pairs: float, bar: float) -> str:
    vs, vb = _signed(card.ics_normalized), _signed(normalized(card.ics, bar))
    return (
        f"| `{card.policy}` | {card.ics:.1f} | {vs} | {vb} | {_f(card.precision_at_interrupt)} "
        f"| {_f(card.recall_high_value)} | {card.ece:.3f} | {card.hard_violations} "
        f"| {card.surfaced}/{card.n} | {pairs:.1%} | {unparsed:.1%} |"
    )


@dataclass(frozen=True)
class Robustness:
    """One model's decisions on a reworded set, compared with the original moments."""

    policy: str
    n: int
    flips: int
    independent: float
    spoke_original: int
    spoke_reworded: int
    ics_original: float
    ics_reworded: float
    pairs_original: float
    pairs_reworded: float
    same_original: int
    same_reworded: int

    @property
    def constant(self) -> bool:
        """Constant on both sets: zero flips is then forced, and says nothing."""
        return {self.spoke_original, self.spoke_reworded} <= {0, self.n}


def same_answer_pairs(decisions: dict[str, Decision]) -> int:
    """Pairs whose two sides got the same speak/stay-quiet decision.

    Both sides share a body and user state and need opposite answers, so a pair
    answered the same on both sides is one where the decider did not move the
    decision. This is what separates "ignores the decider" from "reads it backwards",
    which pairs-both-right alone cannot.
    """
    sides: dict[str, set[bool]] = {}
    for moment_id, d in decisions.items():
        sides.setdefault(pair_key(moment_id), set()).add(d.surface)
    return sum(len(v) == 1 for v in sides.values())


def paraphrase_robustness(reworded: str = "v2para", original: str = "v2") -> list[Robustness]:
    """Compare every committed run on ``reworded`` with the same model on ``original``.

    Moments are matched by id: the reworded set keeps each original id. ``independent``
    is the flips expected if the two decisions were unrelated at the observed speak
    rates, ``n * (p_o (1 - p_p) + p_p (1 - p_o))``. ``same_*`` counts pairs answered
    alike on both sides (``same_answer_pairs``). Round 42.
    """
    para = load(reworded, "dev")
    ids = [i.moment.id for i in para]
    wanted = set(ids)
    orig_items = [i for i in load(original, "dev") if i.moment.id in wanted]
    orig_runs = load_results(original)
    rows = []
    for name, decisions in sorted(load_results(reworded).items()):
        new = {d.moment_id: d for d in decisions}
        old = {d.moment_id: d for d in orig_runs[name] if d.moment_id in new}
        n = len(ids)
        so = sum(old[m].surface for m in ids)
        sp = sum(new[m].surface for m in ids)
        po, pp = so / n, sp / n
        rows.append(
            Robustness(
                policy=name,
                n=n,
                flips=sum(old[m].surface != new[m].surface for m in ids),
                independent=n * (po * (1 - pp) + pp * (1 - po)),
                spoke_original=so,
                spoke_reworded=sp,
                ics_original=score(orig_items, list(old.values()), name).ics,
                ics_reworded=score(para, list(new.values()), name).ics,
                pairs_original=pairs_both_right(orig_items, list(old.values())),
                pairs_reworded=pairs_both_right(para, list(new.values())),
                same_original=same_answer_pairs(old),
                same_reworded=same_answer_pairs(new),
            )
        )
    return rows
