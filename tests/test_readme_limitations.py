"""Figures in the README's limitations section, recomputed. Round 64.

CLAUDE.md: the README's credibility rests on its limitations. R64 found three stale:
`quiet_hours` was said to drive "87%" of the always-vs-silence gap (81% on v1, 68% on
v5; unpinned since Round 9), the model count said "three on v4 only" after all
fourteen ran on v5 (R54), and the family list said eleven of twelve.
"""

from __future__ import annotations

from pathlib import Path

from tactbench.dataset.loader import load
from tactbench.metrics import score
from tactbench.policies.builtin import AlwaysPolicy, NeverPolicy
from tactbench.runner import run_policy

ROOT = Path(__file__).resolve().parents[1]


def _limitations() -> str:
    text = (ROOT / "README.md").read_text()
    block = text.split("## Honest limitations")[1].split("## Roadmap")[0]
    return " ".join(block.split())


def quiet_share(version: str, split: str = "dev") -> tuple[float, float]:
    """(share of the always-vs-silence cost gap, share of moments) for quiet_hours."""
    items = load(version, split)
    family = {i.moment.id: i.moment.family for i in items}

    def costs(policy) -> dict[str, float]:
        out: dict[str, float] = {}
        for o in score(items, run_policy(policy, items), policy.name).outcomes:
            out[family[o.moment_id]] = out.get(family[o.moment_id], 0.0) + o.cost
        return out

    always, never = costs(AlwaysPolicy()), costs(NeverPolicy())
    gap = {f: always[f] - never[f] for f in always}
    moments = sum(f == "quiet_hours" for f in family.values()) / len(items)
    return gap["quiet_hours"] / sum(gap.values()), moments


def test_the_quiet_hours_concentration():
    (g1, m1), (g5, m5) = quiet_share("v1"), quiet_share("v5")
    assert [round(x * 100) for x in (g1, m1, g5, m5)] == [81, 11, 68, 8]
    assert (
        "**81%** of the `always`-versus-silence gap from 11% of the moments on `v1`, and "
        "**68%** from 8% on `v5`" in _limitations()
    )


def test_the_model_count():
    runs = [p.stem for p in (ROOT / "results" / "v5-dev").glob("llm_*.jsonl")]
    models = {r.split("_", 2)[2].removesuffix("-dev") for r in runs}
    assert len(models) == 14 and len(runs) == 28, sorted(models)
    block = _limitations()
    assert "Fourteen open-weight models" in block and "three on v4 only" not in block


def test_the_family_count():
    """On the newest dataset on disk, found rather than named (v6 added a family and
    this test had named v5: the hand-listed-cases failure of issue #56)."""
    import re

    from tactbench.dataset.loader import DATA_ROOT

    latest = max(int(d.name[1:]) for d in DATA_ROOT.iterdir() if re.fullmatch(r"v\d+", d.name))
    n = len({i.moment.family for i in load(f"v{latest}", "dev")})
    words = {12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen"}
    assert (latest, n) == (9, 16)  # update with the next version, and the README with it
    assert f"All {words[n]} families" in _limitations()
