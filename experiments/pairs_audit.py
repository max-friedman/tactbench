"""Audit (Round 28): "a coin gets about 25% of pairs both right; no model beats it."

The README's headline about LLMs rests on two things never measured on this data:
the ~25% coin baseline for pairs-both-right, and ``results.pairs_both_right`` itself,
which was tested only on constant policies and on gold labels. This probe is
independent of that function: it reads the JSONL files directly and pairs moments by
id with its own parsing. It does not import ``tactbench.results``.

Falsified if: a fair coin over 1000 seeds averages outside 20-30%; or the
independent count disagrees with ``tactbench results`` for any committed run; or any
LLM run is within 2 standard deviations of the coin's mean.

    uv run python experiments/pairs_audit.py
"""

from __future__ import annotations

import json
import random
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def gold() -> dict[str, bool]:
    out = {}
    for line in (ROOT / "data" / "v1" / "dev.jsonl").read_text().splitlines():
        row = json.loads(line)
        out[row["moment"]["id"]] = row["label"]["should_surface"]
    return out


def pairs(ids) -> list[tuple[str, str]]:
    groups = defaultdict(list)
    for mid in ids:
        family, side, idx = mid.rsplit("-", 2)
        assert side in ("pos", "near"), mid
        groups[(family, idx)].append(mid)
    assert all(len(v) == 2 for v in groups.values())
    return [tuple(sorted(v)) for v in groups.values()]


def both_right(decide: dict[str, bool], labels: dict[str, bool], ps) -> float:
    return sum(all(decide[m] == labels[m] for m in p) for p in ps) / len(ps)


def main() -> None:
    labels = gold()
    ps = pairs(labels)
    print(f"{len(labels)} dev moments, {len(ps)} pairs")

    coin = []
    for seed in range(1000):
        rng = random.Random(seed)
        coin.append(both_right({m: rng.random() < 0.5 for m in labels}, labels, ps))
    mean, sd = statistics.mean(coin), statistics.pstdev(coin)
    print(
        f"fair coin over 1000 seeds: mean {mean:.1%}, sd {sd:.1%}, "
        f"range {min(coin):.1%}-{max(coin):.1%}"
    )

    table = subprocess.run(
        [sys.executable, "-m", "tactbench.cli", "results"], capture_output=True, text=True,
        check=True, cwd=ROOT,
    ).stdout  # fmt: skip
    quoted = {m.group(1): float(m.group(2)) for m in re.finditer(
        r"^\| `(llm:[^`]+)` \|.*\| ([\d.]+)% \| [\d.]+% \|$", table, re.M)}  # fmt: skip

    # One-sided: the claim is that no run reaches the coin. R28's review found the
    # first version tested |run - coin| < 2 sd, so a run scoring 100% passed it.
    floor = mean - 2 * sd
    mismatches, reaches_coin, mine_by_run = [], [], {}
    for path in sorted((ROOT / "results" / "v1-dev").glob("*.jsonl")):
        variant, model = path.stem.removesuffix("-dev").split("_", 2)[1:]
        name = f"llm:{variant}:{model}"
        decide = {json.loads(x)["moment_id"]: json.loads(x)["surface"]
                  for x in path.read_text().splitlines()}  # fmt: skip
        mine = mine_by_run[name] = both_right(decide, labels, ps)
        if name not in quoted or round(100 * mine, 1) != quoted[name]:
            mismatches.append((name, mine, quoted.get(name)))
        if mine >= floor:
            reaches_coin.append((name, mine))
    unmatched_rows = sorted(set(quoted) - set(mine_by_run))
    print(
        f"independent vs `tactbench results`: {len(mine_by_run)} files compared to "
        f"{len(quoted)} table rows; {len(mismatches)} mismatches {mismatches}; "
        f"rows with no file {unmatched_rows}"
    )
    best = max(mine_by_run.values())
    print(
        f"best run (this probe's count) {best:.1%} = {abs(mean - best) / sd:.1f} sd "
        f"{'below' if best < mean else 'above'} the coin; "
        f"runs at or above coin - 2 sd ({floor:.1%}): {reaches_coin}"
    )
    holds = (
        0.20 <= mean <= 0.30
        and not mismatches
        and not unmatched_rows
        and not reaches_coin
        and len(mine_by_run) == len(quoted) > 0
    )
    print(f"\nverdict: {'holds' if holds else 'fails'}")


if __name__ == "__main__":
    main()
