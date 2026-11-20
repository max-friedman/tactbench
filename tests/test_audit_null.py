"""A chance reference for the positional probe. Round 40, queue item K.

Round 37: at 28-40 items a family, a label-swap null (each pair's labels swapped at
random, so labels carry no information) exceeds 60% on the positional probe in about
half of family-seed cells. The audit printed per-family positional figures with no
such reference, so a high one read as a leak. The audit now prints the null's median
beside each observed figure.
"""

from __future__ import annotations

import random
from collections import defaultdict

from typer.testing import CliRunner

from tactbench.audit import label_swap_null, null_readings, positional_leakage
from tactbench.cli import app
from tactbench.dataset.loader import load
from tactbench.schema import pair_key


def test_the_null_keeps_pairs_whole_and_opposite():
    items = load("v1", "dev")
    null = label_swap_null(items, random.Random(0))
    assert [i.moment.id for i in null] == [i.moment.id for i in items]
    sides = defaultdict(list)
    for i in null:
        sides[pair_key(i.moment.id)].append(i.label.should_surface)
    assert all(sorted(v) == [False, True] for v in sides.values())
    changed = sum(
        a.label.should_surface != b.label.should_surface for a, b in zip(items, null, strict=True)
    )
    assert 0 < changed < len(items)


def test_the_null_does_not_mutate_the_input():
    items = load("v1", "dev")
    before = [i.label.should_surface for i in items]
    label_swap_null(items, random.Random(1))
    assert [i.label.should_surface for i in items] == before


def test_null_readings_are_deterministic():
    sub = [i for i in load("v1", "dev") if i.moment.family == "travel"]
    assert null_readings(sub, positional_leakage, draws=5) == null_readings(
        sub, positional_leakage, draws=5
    )


def test_the_audit_prints_the_null_beside_positional():
    result = CliRunner().invoke(app, ["audit"])
    assert result.exit_code == 0, result.output
    assert "null" in result.output.lower()
