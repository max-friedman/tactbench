"""Can held-out test labels be hidden? Round 33 (CLAUDE.md priority 4).

Priority 4 asked for "held-out test labels hidden behind a submission script so the
leaderboard resists overfitting". Two measurements say hiding the label file cannot
do that while the generator is public:

1. **The file is reproducible.** ``tactbench build`` regenerates ``data/v1/test.jsonl``
   byte-for-byte from public code and seed (CI's "dataset is reproducible" job
   already asserts it), so every hidden label is recoverable.
2. **A secret seed does not help either.** The labels follow from the decider
   *templates*, which are public. ``SkylinePolicy`` -- a parser built only from those
   templates, never shown a label -- scores ICS 0.0 on the held-out frames of splits
   built from seeds it has never seen.

So a held-out set only resists overfitting if its *templates* are private (or its
items are human-written). That is a dataset-authoring decision, not code.

    uv run python experiments/hidden_labels_probe.py
"""

from __future__ import annotations

from tactbench.dataset.generate import HELD_OUT_FRAMES, generate
from tactbench.dataset.loader import load
from tactbench.policies.skyline import SkylinePolicy
from tactbench.runner import evaluate
from tactbench.schema import frame_of

SHIPPED_SEED = 20260726
UNSEEN_SEEDS = (1, 42, 777, 123456, 99999999)


def held_out(seed: int):
    items = generate(n_pairs_per_scenario=20, seed=seed)
    return [i for i in items if frame_of(i.moment) in HELD_OUT_FRAMES]


def main() -> None:
    committed = load("v1", "test")
    rebuilt = held_out(SHIPPED_SEED)
    same = [i.model_dump() for i in committed] == [i.model_dump() for i in rebuilt]
    print(f"test split rebuilt from public code: {len(rebuilt)} items, identical: {same}")
    for seed in UNSEEN_SEEDS:
        card = evaluate(SkylinePolicy(), held_out(seed))
        hv = card.hard_violations
        print(f"unseen seed {seed:>9}: template parser ICS {card.ics:.1f}, hard viol. {hv}")


if __name__ == "__main__":
    main()
