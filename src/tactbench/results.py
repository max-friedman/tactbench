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
from pathlib import Path

from .dataset.loader import load
from .metrics import Scorecard, score
from .policies.llm import unparsed_rate
from .runner import silence_ics
from .schema import Decision

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


def manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def scorecards(version: str = "v1", split: str = "dev") -> list[tuple[Scorecard, float]]:
    """(scorecard, unparsed rate) per committed run, best ICS first."""
    items = load(version, split)
    silence = silence_ics(items)
    out = [
        (score(items, ds, name, reference_ics=silence), unparsed_rate(ds))
        for name, ds in load_results(version, split).items()
    ]
    return sorted(out, key=lambda cu: (cu[0].ics, cu[0].policy))


def _f(x: float | None) -> str:
    return "—" if x is None else f"{x:.3f}"


def markdown_row(card: Scorecard, unparsed: float) -> str:
    vs = f"{card.ics_normalized:+.1f}".replace("-", "−")
    return (
        f"| `{card.policy}` | {card.ics:.1f} | {vs} | {_f(card.precision_at_interrupt)} "
        f"| {_f(card.recall_high_value)} | {card.ece:.3f} | {card.hard_violations} "
        f"| {card.surfaced}/{card.n} | {unparsed:.1%} |"
    )
