"""The open-weight LLM results at a glance: one row per committed split. Round 79.

The README carries one full table per dataset (nine of them), and the headline is
spread across 500 lines. This prints the summary the README quotes between its
``llm-glance`` markers; ``tests/test_llm_glance.py`` holds the README to it exactly.

    uv run python experiments/llm_glance.py
"""

from __future__ import annotations

from tactbench.cli import MAX_UNPARSED
from tactbench.dataset.loader import load
from tactbench.results import load_results, scorecards
from tactbench.runner import normalized, pair_blind_ics

#: Every split with committed LLM runs, in the order the README presents them.
SPLITS = [
    ("v1", "dev"),
    ("v1", "test"),
    ("v2", "dev"),
    ("v2para", "dev"),
    ("v3", "dev"),
    ("v4", "dev"),
    ("v5", "dev"),
    ("v6", "dev"),
    ("v7", "dev"),
    ("v8", "dev"),
]


def _name(policy: str) -> str:
    _, variant, model = policy.split(":", 2)
    return f"{model} {variant}"


def _signed(x: float) -> str:
    return f"{x:+.1f}".replace("-", "−")


def row(version: str, split: str) -> str:
    items = load(version, split)
    bar = pair_blind_ics(items)
    cards = scorecards(version, split)
    families = len({i.moment.family for i in items})
    above = [c for c, u, _ in cards if c.ics_normalized > 0 and u <= MAX_UNPARSED]
    best = min(cards, key=lambda t: t[0].ics)[0]
    top_pairs = max(cards, key=lambda t: (t[2], -t[0].ics))
    return (
        f"| `{version}/{split}` | {families} | {len(items)} | {len(cards)} | "
        f"{len(above)} | {_signed(best.ics_normalized)} ({_name(best.policy)}) | "
        f"{_signed(normalized(best.ics, bar))} | "
        f"{top_pairs[2]:.1%} ({_name(top_pairs[0].policy)}) |"
    )


HEADER = (
    "| split | families | moments | runs | beat silence | best vs silence | "
    "best vs pair-blind | best pairs-both-right |\n"
    "|---|---|---|---|---|---|---|---|"
)


def table() -> str:
    assert all(load_results(v, s) for v, s in SPLITS)
    return HEADER + "\n" + "\n".join(row(v, s) for v, s in SPLITS)


if __name__ == "__main__":
    print(table())
