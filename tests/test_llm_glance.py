"""The README's at-a-glance LLM table equals ``experiments/llm_glance.py``. Round 79."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

import llm_glance  # noqa: E402

from tactbench.results import RESULTS_DIR  # noqa: E402


def _block() -> str:
    text = (ROOT / "README.md").read_text()
    return text.split("<!-- llm-glance:start -->\n")[1].split("\n<!-- llm-glance:end -->")[0]


def test_every_committed_split_is_a_row():
    # Round 82: only split directories (``<version>-<split>``) are LLM runs; a probe's
    # directory such as results/decider-reading/ is not a row.
    on_disk = {
        d.name
        for d in RESULTS_DIR.iterdir()
        if d.is_dir() and re.fullmatch(r"v\d+\w*-(dev|test)", d.name)
    }
    assert {"v1-test", "v2para-dev", "v9-dev"} <= on_disk
    listed = {f"{v}-{s}" for v, s in llm_glance.SPLITS}
    assert listed == on_disk


def test_the_readme_table_is_current():
    assert _block() == llm_glance.table(), "run `uv run python experiments/llm_glance.py`"


def test_no_split_has_a_run_above_the_pair_blind_bar():
    """The sentence under the table: no run on any split clears the pair-blind bar."""
    for line in llm_glance.table().splitlines()[2:]:
        assert line.split(" | ")[6].startswith("−"), line
    text = " ".join((ROOT / "README.md").read_text().split())
    assert "No run on any split clears the pair-blind bar" in text


def test_the_best_pairs_figure_under_the_table():
    best = max(
        float(line.split(" | ")[7].split("%")[0]) for line in llm_glance.table().splitlines()[2:]
    )
    text = " ".join((ROOT / "README.md").read_text().split())
    assert best == 14.8 and f"no run gets more than {best}% of pairs" in text
